"""Pydantic response schemas shared by the notebooks, the skill and the eval (Gemini-facing).

Every Gemini call in this package asks for one of these models via `response_schema`, so the
reply is parsed and validated in code. Geometry (boxes -> pixels -> bearings) is handled by
`box_2d_to_pixels` + `rosette`/`PerspectiveView`, never by the model.

Box convention (Gemini native): `box_2d = [ymin, xmin, ymax, xmax]`, integers in 0..1000,
normalised to the image that was sent.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from pydantic.json_schema import SkipJsonSchema


class AssetClass(str, Enum):
    HOUSE = "HOUSE"
    UTILITY_POLE = "UTILITY_POLE"
    ROAD_SIGN = "ROAD_SIGN"
    STREET_LIGHT = "STREET_LIGHT"
    FIRE_HYDRANT = "FIRE_HYDRANT"
    STREET_TREE = "STREET_TREE"
    GATE = "GATE"


class AssetMaterial(str, Enum):
    """Vote-able material of a discrete asset (constrained decoding, no free text; QA F10)."""

    WOOD = "WOOD"
    CONCRETE = "CONCRETE"
    METAL = "METAL"
    COMPOSITE = "COMPOSITE"
    BRICK = "BRICK"
    STONE = "STONE"
    PLASTIC = "PLASTIC"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class ExteriorMaterial(str, Enum):
    BRICK = "BRICK"
    STONE = "STONE"
    WOOD = "WOOD"
    VINYL = "VINYL"
    STUCCO = "STUCCO"
    CONCRETE = "CONCRETE"
    FIBER_CEMENT = "FIBER_CEMENT"
    METAL = "METAL"
    GLASS = "GLASS"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class RoofType(str, Enum):
    GABLE = "GABLE"
    HIP = "HIP"
    FLAT = "FLAT"
    MANSARD = "MANSARD"
    SHED = "SHED"
    GAMBREL = "GAMBREL"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


MIN_BOX_PX = 2.0


def _check_in_range(coords: list[int] | list[float], what: str) -> None:
    if any(c < 0 or c > 1000 for c in coords):
        raise ValueError(f"{what} values must be in 0..1000, got {list(coords)}")


def _check_box_in_image(box: list[int] | None, width: int, height: int) -> None:
    """Range-check a 0..1000 box and reject boxes under MIN_BOX_PX in either pixel dimension."""
    if box is None:
        return
    if len(box) != 4:
        raise ValueError("box_2d must have 4 values [ymin, xmin, ymax, xmax]")
    _check_in_range(box, "box_2d")
    x0, y0, x1, y1 = box_2d_to_pixels(box, width, height)
    if x1 - x0 < MIN_BOX_PX or y1 - y0 < MIN_BOX_PX:
        raise ValueError(f"degenerate box_2d {list(box)} in a {width}x{height} image")


def _check_box(v: list[int] | None) -> list[int] | None:
    if v is None:
        return v
    if len(v) != 4:
        raise ValueError("box_2d must have 4 values [ymin, xmin, ymax, xmax]")
    if any(c < 0 or c > 1000 for c in v):
        raise ValueError("box_2d values must be in 0..1000")
    if v[0] >= v[2] or v[1] >= v[3]:
        raise ValueError("box_2d must satisfy ymin < ymax and xmin < xmax")
    return [int(c) for c in v]


class Detection(BaseModel):
    label: AssetClass
    box_2d: list[int] = Field(description="[ymin, xmin, ymax, xmax] in 0..1000")
    confidence: float = Field(ge=0.0, le=1.0)
    material: AssetMaterial | None = None
    notes: str | None = None

    @field_validator("box_2d")
    @classmethod
    def _valid_box(cls, v):
        return _check_box(v)


def _repair_box(v: Any) -> Any:
    """Clip to 0..1000 and order each axis; leaves anything unrepairable for validation."""
    if not isinstance(v, list | tuple) or len(v) != 4:
        return v
    try:
        y0, x0, y1, x1 = (min(1000, max(0, int(round(float(c))))) for c in v)
    except (TypeError, ValueError):
        return v
    return [min(y0, y1), min(x0, x1), max(y0, y1), max(x0, x1)]


class FrameDetections(BaseModel):
    """Detections in one image. Individual malformed boxes are repaired (swapped corners,
    slight overflow) or dropped and counted in `n_dropped`, so one bad box does not force a
    paid re-ask of the whole reply (QA S14)."""

    detections: list[Detection]
    n_dropped: SkipJsonSchema[int] = 0

    @model_validator(mode="before")
    @classmethod
    def _drop_bad(cls, data: Any) -> Any:
        if not isinstance(data, dict) or not isinstance(data.get("detections"), list):
            return data
        good, dropped = [], 0
        for d in data["detections"]:
            if isinstance(d, dict) and "box_2d" in d:
                d = {**d, "box_2d": _repair_box(d["box_2d"])}
            try:
                good.append(Detection.model_validate(d))
            except ValidationError:
                dropped += 1
        return {**data, "detections": good, "n_dropped": int(data.get("n_dropped", 0)) + dropped}


class SameObjectVerdict(BaseModel):
    same_object: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


class SurfaceMaterial(str, Enum):
    PAVED_ASPHALT = "Paved Asphalt"
    CONCRETE = "Concrete"
    BRICK_PAVERS = "Brick/Pavers"
    COBBLESTONE = "Cobblestone"
    GRAVEL = "Gravel"
    DIRT = "Dirt"
    MUD = "Mud"
    TURF = "Turf"
    UNPAVED = "Unpaved"
    OTHER = "Other"


class SurfaceCondition(str, Enum):
    GOOD = "Good"
    FAIR = "Fair"
    DAMAGED = "Damaged/Potholes"
    SEVERELY_DEGRADED = "Severely Degraded"


class ContinuousAsset(str, Enum):
    ROAD = "ROAD"
    SIDEWALK = "SIDEWALK"
    FENCE = "FENCE"
    POWER_LINE = "POWER_LINE"


class Side(str, Enum):
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    CENTER = "CENTER"


class ContinuousAssetObservation(BaseModel):
    asset: ContinuousAsset
    side: Side
    present: bool
    material: SurfaceMaterial | None = None
    condition: SurfaceCondition | None = None
    confidence: float = Field(ge=0.0, le=1.0)


class WindowLabel(BaseModel):
    """Labels for the centre pano of a 3-pano window (views rendered in code)."""

    observations: list[ContinuousAssetObservation]


class SurfaceMaterialResult(BaseModel):
    """Single-image surface material answer (the skill's output)."""

    primary_material: SurfaceMaterial
    secondary_materials: list[SurfaceMaterial] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    surface_condition: SurfaceCondition
    visual_reasoning: str


class Occlusion(str, Enum):
    NONE = "NONE"
    PARTIAL = "PARTIAL"
    HEAVY = "HEAVY"


class HouseView(BaseModel):
    house_visible: bool
    box_2d: list[int] | None = None
    occlusion: Occlusion
    facade_visible_fraction: float = Field(ge=0.0, le=1.0)
    stories: int | None = Field(default=None, ge=1, le=10)
    exterior_material: ExteriorMaterial | None = None
    roof_type: RoofType | None = None
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("box_2d")
    @classmethod
    def _valid_box(cls, v):
        return _check_box(v)

    def validate_in_image(self, width: int, height: int) -> None:
        """Raise ValueError if the box is out of range or degenerate in a width x height image."""
        _check_box_in_image(self.box_2d, width, height)


class EdgeType(str, Enum):
    RIDGE = "RIDGE"
    EAVE = "EAVE"
    HIP = "HIP"
    VALLEY = "VALLEY"
    RAKE = "RAKE"


class RoofEdge(BaseModel):
    edge_type: EdgeType
    points: list[list[int]] = Field(description="polyline of [y, x] points in 0..1000")

    @field_validator("edge_type", mode="before")
    @classmethod
    def _coerce_edge(cls, v):
        return str(v).upper() if v else v

    @field_validator("points", mode="before")
    @classmethod
    def _pts(cls, v):
        if not v:
            return []
        v = [[int(round(float(c))) for c in p] for p in v]
        if len(v) < 2:
            raise ValueError("an edge needs >= 2 points")
        for p in v:
            if len(p) != 2 or any(c < 0 or c > 1000 for c in p):
                raise ValueError("points must be [y, x] in 0..1000")
        return v


class RoofEdges(BaseModel):
    roof_visible: bool
    edges: list[RoofEdge] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)

    def validate_in_image(self, width: int, height: int) -> None:
        """Raise ValueError for a polyline with < 2 points, points outside 0..1000, or points
        that repeat once mapped to whole pixels of a width x height image."""
        for i, e in enumerate(self.edges):
            pts = list(e.points or [])
            if len(pts) < 2:
                raise ValueError(f"edge {i} needs >= 2 points, got {len(pts)}")
            pixels = []
            for p in pts:
                if len(p) != 2:
                    raise ValueError(f"edge {i}: points must be [y, x] pairs")
                _check_in_range(p, f"edge {i} point")
                pixels.append((round(p[1] / 1000 * width), round(p[0] / 1000 * height)))
            if len(set(pixels)) != len(pixels):
                raise ValueError(f"edge {i} has repeated points {pts} in a {width}x{height} image")


class PresenceCheck(BaseModel):
    present: bool
    confidence: float = Field(ge=0.0, le=1.0)
    box_2d: list[int] | None = None

    @field_validator("box_2d")
    @classmethod
    def _valid_box(cls, v):
        return _check_box(v)


def box_2d_to_pixels(box_2d, width: int, height: int) -> tuple[float, float, float, float]:
    """[ymin, xmin, ymax, xmax] (0..1000) -> (x0, y0, x1, y1) pixels in a width x height image."""
    ymin, xmin, ymax, xmax = (float(c) for c in box_2d)
    return (xmin / 1000 * width, ymin / 1000 * height, xmax / 1000 * width, ymax / 1000 * height)


class HouseFramingVerdict(BaseModel):
    """Silver-teacher verdict on house framing and attributes (UC1)."""

    house_visible: bool
    fully_in_frame: bool
    truncation: str = Field(description="NONE, LEFT, RIGHT, TOP, BOTTOM, or MULTIPLE")
    occlusion: Occlusion
    stories: int | None = Field(default=None, ge=1, le=10)
    exterior_material: ExteriorMaterial | None = None
    roof_type: RoofType | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    visual_evidence: str


class EntityConfirm(BaseModel):
    """Silver-teacher confirmation of a discrete roadside asset at a projected zoom tile (UC2)."""

    target_class: AssetClass
    confirmed: bool
    box_2d: list[int] | None = Field(
        default=None, description="[ymin, xmin, ymax, xmax] in 0..1000 if confirmed"
    )
    confidence: float = Field(ge=0.0, le=1.0)
    visual_evidence: str

    @field_validator("box_2d")
    @classmethod
    def _valid_box(cls, v):
        return _check_box(v)


class SurfaceSlotVerdict(BaseModel):
    """Silver-teacher verdict on one road/sidewalk slot in a high-res crop (UC3)."""

    side: Side
    present: bool
    material: SurfaceMaterial | None = None
    condition: SurfaceCondition | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    visual_evidence: str


class RoofVisibility(BaseModel):
    """Silver-teacher verdict on whether roof edges are visible or occluded (UC4 M4.1)."""

    roof_visible: bool
    visible_fraction: float = Field(ge=0.0, le=1.0)
    edge_50pct_visible: bool = Field(
        description="True if at least 50% of the primary eave or ridge boundary is unobstructed"
    )
    occlusion_reason: str = Field(description="NONE, FOLIAGE, POLE, NEIGHBOR, OUT_OF_FRAME, OTHER")
    confidence: float = Field(ge=0.0, le=1.0)


class RoofTrace(BaseModel):
    """Silver-teacher roof polyline trace on high-resolution zoom view (UC4 M4.5)."""

    roof_visible: bool
    edges: list[RoofEdge] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class RoofAngleMeasurement(BaseModel):
    """Agentic-vision (code execution) LSD eave/rake angle measurement on a roof view (UC4)."""

    eave_angle_deg: float = Field(ge=-89.0, le=89.0)
    rake_angle_deg: float | None = Field(default=None, ge=-89.0, le=89.0)
    lsd_overlap_fraction: float = Field(ge=0.0, le=1.0)
    n_segments: int = Field(ge=0)
    confidence: float = Field(ge=0.0, le=1.0)


class StoreyRowMeasurement(BaseModel):
    """Agentic-vision (code execution) horizontal window-row / storey count on a house crop (UC1)."""

    window_rows: int = Field(ge=0, le=10)
    estimated_stories: int = Field(ge=1, le=10)
    row_y_centres_norm: list[int] = Field(
        default_factory=list, description="normalised y row centres in 0..1000"
    )
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("row_y_centres_norm")
    @classmethod
    def _valid_centres(cls, v: list[int]) -> list[int]:
        _check_in_range(v, "row_y_centres_norm")
        return [int(c) for c in v]


class PostLeanMeasurement(BaseModel):
    """Agentic-vision (code execution) vertical lean-angle measurement on a pole/sign crop (UC2)."""

    lean_angle_deg: float = Field(
        ge=-45.0, le=45.0, description="lean angle in degrees from vertical"
    )
    vertical_support: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)


class MaterialBoundaryMeasurement(BaseModel):
    """Agentic-vision (code execution) road texture & transition measurement on an IPM/road crop (UC3)."""

    change_row_norm: int | None = Field(
        default=None, ge=0, le=1000, description="normalised row 0..1000 of material transition"
    )
    mean_luma: float = Field(ge=0.0, le=255.0)
    grad_mean: float = Field(ge=0.0)
    confidence: float = Field(ge=0.0, le=1.0)


class RepeatPassDiff(BaseModel):
    """Pairwise repeat-pass change detection verdict across two capture dates (O1)."""

    change_detected: bool
    change_summary: str
    changed_box_2d: list[int] | None = None
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("changed_box_2d")
    @classmethod
    def _valid_box(cls, v):
        return _check_box(v)
