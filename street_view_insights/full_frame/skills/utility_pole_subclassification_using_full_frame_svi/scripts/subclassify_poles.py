#!/usr/bin/env python3
"""Multi-view utility pole sub-classification and equipment audit on Full-Frame Street View Insights (`SV_FULL_FRAME_ASSETS`).

Pipeline (100% in-memory image processing — never writes Street View or composite images to disk):
1. Catalog discovery in `full_frame_observations_latest` with parameterised SQL under a 2 GB dry-run
   safety cap (reconstructing `gs://<bucket>/<snapshot_id>/v0/<observation_id>.jpg` without selecting
   `gcs_uri`) and same-exposure bounding-box deduplication.
2. Multi-view distance/size hygiene (`4.5 m <= distance_m <= 40.0 m`, `bbox` height `>= 300 px`),
   `>= 10 deg` azimuth parallax view selection, and `< 3.5 m` pairwise buddy-pole proximity check.
3. In-memory 3-panel multi-zone crop slicing (`[1: Full Shaft | 2: Crown & Cross-Arm Zoom (2x)
   | 3: Base & Ground Collar Zoom (2x)]`) anchored to the cataloged pixel `bbox` with cyan corner ticks.
4. Inline Gemini structured perception (`PoleSubClassification`) fused with deterministic OpenCV LSD
   verticality/lean gates and voltage-tier consistency rules.
"""

from __future__ import annotations

import argparse
import asyncio
import enum
import math
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

try:
    from svi_geo import auth as _svi_auth
    from svi_geo import cvchecks as _svi_cvc
    from svi_geo import gemini_client as _svi_gc
    from svi_geo import geo as _svi_geo
except ImportError:  # pragma: no cover
    _svi_auth = None
    _svi_cvc = None
    _svi_gc = None
    _svi_geo = None


DEFAULT_DATASET = "imagery_insights___us"
ALLOWED_DATASETS = frozenset({"imagery_insights___us", "imagery_insights___eu"})
DEFAULT_LOCATION = "global"
DEFAULT_MODEL = getattr(_svi_gc, "DEFAULT_MODEL", "gemini-3-flash-preview")
DEFAULT_RADIUS_M = 60.0
MAX_POLES = 10
MAX_VIEWS_PER_POLE = 2
MIN_DIST_M = 4.5
MAX_DIST_M = 40.0
MIN_BBOX_HEIGHT_PX = 300
MIN_PARALLAX_DEG = 10.0
BUDDY_POLE_DIST_M = 3.5
FRAME_WIDTH_PX = 3648
FRAME_HEIGHT_PX = 5472
MAX_BYTES_BILLED = 2_000_000_000


class PoleSubType(str, enum.Enum):
    TRANSMISSION = "TRANSMISSION"
    DISTRIBUTION_PRIMARY = "DISTRIBUTION_PRIMARY"
    DISTRIBUTION_SECONDARY = "DISTRIBUTION_SECONDARY"
    TELECOM_ONLY = "TELECOM_ONLY"
    JOINT_USE_LIGHT = "JOINT_USE_LIGHT"
    SERVICE_RISER_POLE = "SERVICE_RISER_POLE"
    GUY_STUB_POLE = "GUY_STUB_POLE"
    STREET_LIGHT_ONLY = "STREET_LIGHT_ONLY"
    OTHER_NON_UTILITY = "OTHER_NON_UTILITY"


TRUE_UTILITY_POLE_SUBTYPES: frozenset[PoleSubType] = frozenset(
    {
        PoleSubType.TRANSMISSION,
        PoleSubType.DISTRIBUTION_PRIMARY,
        PoleSubType.DISTRIBUTION_SECONDARY,
        PoleSubType.TELECOM_ONLY,
        PoleSubType.JOINT_USE_LIGHT,
        PoleSubType.SERVICE_RISER_POLE,
    }
)


class PoleMaterial(str, enum.Enum):
    WOOD = "WOOD"
    METAL = "METAL"
    CONCRETE = "CONCRETE"
    FIBERGLASS = "FIBERGLASS"
    UNKNOWN = "UNKNOWN"


class PoleCondition(str, enum.Enum):
    GOOD = "GOOD"
    FAIR = "FAIR"
    DAMAGED = "DAMAGED"
    UNKNOWN = "UNKNOWN"


class CrossArmConfig(str, enum.Enum):
    NONE = "NONE"
    SINGLE_WOOD = "SINGLE_WOOD"
    DOUBLE_WOOD = "DOUBLE_WOOD"
    STEEL_DAVIT = "STEEL_DAVIT"
    FIBERGLASS_BRACKET = "FIBERGLASS_BRACKET"
    H_FRAME = "H_FRAME"


class PoleEquipment(str, enum.Enum):
    TRANSFORMER_CAN = "TRANSFORMER_CAN"
    RISER_CONDUIT = "RISER_CONDUIT"
    CAPACITOR_BANK = "CAPACITOR_BANK"
    RECLOSER_SWITCH = "RECLOSER_SWITCH"
    FUSE_CUTOUT = "FUSE_CUTOUT"
    GUY_WIRE = "GUY_WIRE"
    STREET_LIGHT_LUMINARY = "STREET_LIGHT_LUMINARY"
    SPLICE_CLOSURE = "SPLICE_CLOSURE"


class PoleSubClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sub_type: PoleSubType
    is_true_utility_pole: bool
    material: PoleMaterial
    condition: PoleCondition
    cross_arm: CrossArmConfig
    equipment: list[PoleEquipment] = Field(default_factory=list, max_length=8)
    has_primary_conductors: bool = False
    has_secondary_conductors: bool = False
    has_telecom_attach: bool = False
    is_double_pole: bool = False
    lean_angle_deg: float = Field(ge=-45.0, le=45.0)
    structural_anomaly: bool = False
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str = Field(min_length=1, max_length=320)


POLE_SUBCLASSIFICATION_PROMPT = """You are a senior electric and telecom utility GIS asset auditor inspecting calibrated Street View Insights (`SV_FULL_FRAME_ASSETS`) 3-panel multi-zone crops of a cataloged `ASSET_CLASS_UTILITY_POLE` candidate.

Each composite image contains 3 side-by-side panels sliced in-memory around the cataloged pixel bounding box (`bbox`):
- Panel 1 (Left, `1: FULL SHAFT`): Full vertical shaft plus context, with cyan corner ticks marking the exact target `bbox` (`asset_id`) to audit.
- Panel 2 (Center, `2: CROWN & CROSS-ARM (2X)`): 2x zoom of the upper crown (`ymin - 0.18*h_box` to `ymin + 0.45*h_box` with wide `+/-1.8*w_box` horizontal context) showing cross-arms, insulators, primary/secondary conductors, and luminaire arms.
- Panel 3 (Right, `3: BASE & GROUND (2X)`): 2x zoom of the lower shaft and ground collar (`ymax - 0.40*h_box` to `ymax + 0.15*h_box` with `+/-1.8*w_box` horizontal context) showing shaft material, riser conduits, down-guy anchors, and adjacent buddy poles.

Apply these strict 4-Gate sub-classification rules:
1. GATE 1 — TRUE UTILITY POLE (`is_true_utility_pole = true`) vs. LOOKALIKE EXCLUSION (`is_true_utility_pole = false`):
   - `TRANSMISSION` (`true`): Tall lattice/tubular steel, concrete, or H-frame structure carrying high-voltage lines on long suspension/post insulator strings.
   - `DISTRIBUTION_PRIMARY` (`true`): Carries 1-3+ high-voltage primary phase conductors on pin/post insulators or cross-arms at the pole top (without a street-light luminary arm).
   - `DISTRIBUTION_SECONDARY` (`true`): Carries low-voltage open-wire or multiplexed triplex secondary distribution and residential service drops below primary height (bare crown, no high-voltage top insulators).
   - `TELECOM_ONLY` (`true`): Supports communication/fiber-optic bundles (thick black insulated cables with splice closures at mid-span) with a bare crown and no electric power conductors.
   - `JOINT_USE_LIGHT` (`true`): Carries overhead electric/telecom utility conductors PLUS a cobra-head or decorative street-light luminary arm (`STREET_LIGHT_LUMINARY`).
   - `SERVICE_RISER_POLE` (`true`): Utility pole whose primary role is transitioning overhead conductors underground via a prominent vertical riser conduit (`RISER_CONDUIT` U-guard/PVC pipe) strapped to the shaft.
   - `GUY_STUB_POLE` (`false`): Short, unenergized wood stub/brace pole supporting ONLY overhead guy strands and a diagonal down-guy anchor wire (`GUY_WIRE`) into the ground, with ZERO energized primary/secondary power or telecom drops.
   - `STREET_LIGHT_ONLY` (`false`): Standalone roadway/pedestrian lighting pole (metal, concrete, or fiberglass shaft with mast arm + luminaire) fed underground with ZERO overhead utility wires.
   - `OTHER_NON_UTILITY` (`false`): Traffic signal mast arm, standalone sign post, camera pole, flagpole, bollard, or tree trunk.
2. GATE 2 & GATE 3 — CROWN & MID-SHAFT HARDWARE AUDIT:
   - Classify `cross_arm` (`NONE`, `SINGLE_WOOD`, `DOUBLE_WOOD`, `STEEL_DAVIT`, `FIBERGLASS_BRACKET`, `H_FRAME`).
   - List all visible `equipment` (`TRANSFORMER_CAN`, `RISER_CONDUIT`, `CAPACITOR_BANK`, `RECLOSER_SWITCH`, `FUSE_CUTOUT`, `GUY_WIRE`, `STREET_LIGHT_LUMINARY`, `SPLICE_CLOSURE`).
   - Set `has_primary_conductors`, `has_secondary_conductors`, and `has_telecom_attach`.
3. GATE 4 — BASE MATERIAL, BUDDY-POLE & STRUCTURAL LEAN AUDIT:
   - Classify `material` (`WOOD`, `METAL`, `CONCRETE`, `FIBERGLASS`, `UNKNOWN`) and `condition` (`GOOD`, `FAIR`, `DAMAGED`, `UNKNOWN`).
   - Set `is_double_pole = true` ONLY when two utility poles stand side-by-side (`0.5 m - 1.2 m` spacing or an old topped pole strapped/lashed to a replacement pole mid-transfer).
   - Estimate `lean_angle_deg` from vertical (`[-45, 45]`) and set `structural_anomaly = true` if `abs(lean_angle_deg) > 8.0`, `condition == "DAMAGED"`, or `is_double_pole == true`.

Return a JSON object matching `PoleSubClassification`."""


_FIELDS = """
  asset_id, observation_id, snapshot_id, asset_type, capture_time, pano_id,
  location.latitude AS lat, location.longitude AS lng,
  camera_pose.latitude AS cam_lat, camera_pose.longitude AS cam_lng,
  camera_pose.heading AS heading, camera_pose.pitch AS pitch, camera_pose.roll AS roll,
  bbox.lo.x AS xmin, bbox.lo.y AS ymin, bbox.hi.x AS xmax, bbox.hi.y AS ymax"""

# Parameterised SQL against full_frame_observations_latest (never selects gcs_uri or latest_observations)
COORDS_SQL = (
    "SELECT"
    + _FIELDS
    + """
FROM `__PROJECT__.__DATASET__.full_frame_observations_latest`
WHERE asset_type = 'ASSET_CLASS_UTILITY_POLE'
  AND ST_DWITHIN(ST_GEOGPOINT(location.longitude, location.latitude),
                 ST_GEOGPOINT(@lng, @lat), @radius_m)
"""
)

ASSET_SQL = (
    "SELECT"
    + _FIELDS
    + """
FROM `__PROJECT__.__DATASET__.full_frame_observations_latest`
WHERE asset_id = @id
"""
)

OBS_SQL = (
    """WITH target AS (
  SELECT asset_id
  FROM `__PROJECT__.__DATASET__.full_frame_observations_latest`
  WHERE observation_id = @id
  LIMIT 1
)
SELECT"""
    + _FIELDS
    + """
FROM `__PROJECT__.__DATASET__.full_frame_observations_latest`
WHERE asset_id IN (SELECT asset_id FROM target)
"""
)

_IDENT = re.compile(r"^[A-Za-z0-9_\-.]+$")


def render_sql(template: str, project: str, dataset: str) -> str:
    """Substitute and validate `<project>.<dataset>` against the dataset allow-list."""
    for v in (project, dataset):
        if not _IDENT.match(v or ""):
            raise ValueError(f"invalid BigQuery identifier: {v!r}")
    if dataset not in ALLOWED_DATASETS:
        raise ValueError(
            f"dataset {dataset!r} is not in ALLOWED_DATASETS {sorted(ALLOWED_DATASETS)}"
        )
    table = f"{project}.{dataset}.full_frame_observations_latest"
    return template.replace("__PROJECT__.__DATASET__.full_frame_observations_latest", table)


def gcs_uri_for(bucket: str, snapshot_id: str, observation_id: str) -> str:
    """Derive `gs://<bucket>/<snapshot_id>/v0/<observation_id>.jpg` without selecting gcs_uri."""
    clean_bucket = str(bucket).removeprefix("gs://").strip("/")
    return f"gs://{clean_bucket}/{snapshot_id}/v0/{observation_id}.jpg"


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in meters between two WGS84 `(lat, lng)` coordinates."""
    if _svi_geo is not None:
        return float(_svi_geo.haversine_m(lat1, lng1, lat2, lng2))
    r_earth = 6_371_008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(0.5 * dp) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(0.5 * dl) ** 2
    return float(2.0 * r_earth * math.asin(min(1.0, math.sqrt(a))))


def bearing_deg(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Initial compass bearing in degrees `[0, 360)` from `(lat1, lng1)` to `(lat2, lng2)`."""
    if _svi_geo is not None:
        return float(_svi_geo.bearing_deg(lat1, lng1, lat2, lng2))
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lng2 - lng1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return float(math.degrees(math.atan2(y, x)) % 360.0)


def angdiff_deg(a: float, b: float) -> float:
    """Signed shortest angular difference `(a - b)` in degrees `[-180, 180)`."""
    return float((a - b + 180.0) % 360.0 - 180.0)


def get_credentials():
    """Resolve Google Cloud credentials (supporting `SVI_USE_GCLOUD_TOKEN=1` and ADC)."""
    if _svi_auth is not None:
        return _svi_auth.get_credentials()
    if os.environ.get("SVI_USE_GCLOUD_TOKEN") == "1":
        from google.oauth2 import credentials as oauth2_credentials

        tok = subprocess.check_output(["gcloud", "auth", "print-access-token"], text=True).strip()
        return oauth2_credentials.Credentials(token=tok)
    import google.auth

    creds, _ = google.auth.default()
    return creds


def deduplicate_same_exposure_observations(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse jittered duplicate `bbox` rows from the exact same camera exposure.

    Groups by `(asset_id, str(capture_time), round(cam_lat, 5), round(cam_lng, 5))` and keeps the
    best-centered bounding box (closest to horizontal center `x = 1824` with largest box height).
    """
    if df.empty:
        return df.copy()
    work = df.copy()
    work["xmin"] = work["xmin"].astype(float)
    work["ymin"] = work["ymin"].astype(float)
    work["xmax"] = work["xmax"].astype(float)
    work["ymax"] = work["ymax"].astype(float)
    work["bbox_w"] = (work["xmax"] - work["xmin"]).clip(lower=1.0)
    work["bbox_h"] = (work["ymax"] - work["ymin"]).clip(lower=1.0)
    work["bbox_cx"] = 0.5 * (work["xmin"] + work["xmax"])
    work["center_offset_px"] = (work["bbox_cx"] - 0.5 * FRAME_WIDTH_PX).abs()
    work["distance_m"] = [
        haversine_m(float(clat), float(clng), float(alat), float(alng))
        for clat, clng, alat, alng in zip(
            work["cam_lat"], work["cam_lng"], work["lat"], work["lng"], strict=True
        )
    ]
    work["bearing_deg"] = [
        bearing_deg(float(clat), float(clng), float(alat), float(alng))
        for clat, clng, alat, alng in zip(
            work["cam_lat"], work["cam_lng"], work["lat"], work["lng"], strict=True
        )
    ]
    work["_exp_time"] = work["capture_time"].astype(str)
    work["_exp_lat"] = work["cam_lat"].astype(float).round(5)
    work["_exp_lng"] = work["cam_lng"].astype(float).round(5)

    # Sort so the best-centered, tallest box per exposure comes first
    work = work.sort_values(
        ["asset_id", "_exp_time", "_exp_lat", "_exp_lng", "center_offset_px", "bbox_h"],
        ascending=[True, True, True, True, True, False],
    )
    dedup = work.drop_duplicates(
        subset=["asset_id", "_exp_time", "_exp_lat", "_exp_lng"], keep="first"
    ).copy()
    return dedup.drop(columns=["_exp_time", "_exp_lat", "_exp_lng"]).reset_index(drop=True)


def select_parallax_views_for_asset(
    asset_rows: pd.DataFrame,
    *,
    max_views: int = MAX_VIEWS_PER_POLE,
    min_dist_m: float = MIN_DIST_M,
    max_dist_m: float = MAX_DIST_M,
    min_bbox_h: float = MIN_BBOX_HEIGHT_PX,
    allow_fallback: bool = False,
) -> tuple[list[dict[str, Any]], float]:
    """Filter deduplicated exposures to `4.5m..40m` and `bbox_h >= 300px`, then select up to
    `max_views` views maximizing sharpness and `>= 10 deg` azimuth parallax.
    """
    if asset_rows.empty:
        return [], 0.0

    valid = asset_rows[
        (asset_rows["distance_m"] >= float(min_dist_m))
        & (asset_rows["distance_m"] <= float(max_dist_m))
        & (asset_rows["bbox_h"] >= float(min_bbox_h))
    ].copy()
    if valid.empty:
        if not allow_fallback:
            return [], 0.0
        valid = asset_rows.copy()

    # Score primary view: prefer well-centered (`|bbox_cx - 1824| < 1200`), optimal distance (~14m), tall bbox
    valid["_well_centered"] = (valid["center_offset_px"] < 1200.0).astype(int)
    valid["_dist_pen"] = (valid["distance_m"] - 14.0).abs()
    valid = valid.sort_values(
        ["_well_centered", "_dist_pen", "bbox_h"],
        ascending=[False, True, False],
    )
    records = valid.drop(columns=["_well_centered", "_dist_pen"]).to_dict("records")
    primary = records[0]
    selected = [primary]

    if max_views >= 2 and len(records) >= 2:
        # Prefer secondary views with >= 10 deg azimuth parallax relative to primary
        high_par = [
            r
            for r in records[1:]
            if abs(angdiff_deg(float(r["bearing_deg"]), float(primary["bearing_deg"])))
            >= MIN_PARALLAX_DEG
        ]
        pool = high_par or records[1:]
        best_sec = max(
            pool,
            key=lambda r: (
                abs(angdiff_deg(float(r["bearing_deg"]), float(primary["bearing_deg"])))
                - 0.4 * max(0.0, float(r["distance_m"]) - 22.0)
                - (8.0 if float(r["center_offset_px"]) >= 1450.0 else 0.0)
            ),
        )
        selected.append(best_sec)

    # Compute max azimuth parallax across all valid exposures for this asset
    bearings = [float(r["bearing_deg"]) for r in records]
    max_par = 0.0
    for i in range(len(bearings)):
        for j in range(i + 1, len(bearings)):
            par = abs(angdiff_deg(bearings[i], bearings[j]))
            max_par = max(max_par, par)

    return selected[:max_views], float(max_par)


def build_full_frame_3panel_crop(
    raw_img: np.ndarray,
    bbox: tuple[float, float, float, float],
    *,
    dist_m: float = 14.0,
    panel_width: int = 360,
    panel_height: int = 480,
) -> dict[str, Any]:
    """Slice an in-memory 3-panel inspection composite around a Full-Frame pixel `bbox`.

    Panels:
      1. `1: FULL SHAFT`: Full pole height (`ymin - 0.15*h_box` to `ymax + 0.15*h_box`) with
         contextual width and subtle cyan corner ticks marking the exact target `bbox`.
      2. `2: CROWN & CROSS-ARM (2X)`: Upper crown (`ymin - 0.18*h_box` to `ymin + 0.45*h_box`)
         with wide `+/-1.8*w_box` horizontal context.
      3. `3: BASE & GROUND (2X)`: Lower shaft and ground collar (`ymax - 0.40*h_box` to
         `ymax + 0.15*h_box`) with `+/-1.8*w_box` horizontal context.
    """
    h_img, w_img = raw_img.shape[:2]
    pw, ph = int(panel_width), int(panel_height)

    xmin, ymin, xmax, ymax = [float(v) for v in bbox]
    xmin = float(np.clip(xmin, 0.0, max(1.0, w_img - 2.0)))
    xmax = float(np.clip(xmax, xmin + 4.0, float(w_img)))
    ymin = float(np.clip(ymin, 0.0, max(1.0, h_img - 2.0)))
    ymax = float(np.clip(ymax, ymin + 16.0, float(h_img)))

    w_box = xmax - xmin
    h_box = ymax - ymin
    cx_box = 0.5 * (xmin + xmax)

    def _safe_crop(x0: float, y0: float, x1: float, y1: float) -> tuple[np.ndarray, tuple[int, int, int, int]]:
        ix0 = int(np.clip(round(x0), 0, w_img - 2))
        iy0 = int(np.clip(round(y0), 0, h_img - 2))
        ix1 = int(np.clip(round(x1), ix0 + 2, w_img))
        iy1 = int(np.clip(round(y1), iy0 + 2, h_img))
        return raw_img[iy0:iy1, ix0:ix1], (ix0, iy0, ix1, iy1)

    # Panel 1: Full Shaft + contextual margins
    full_half_w = max(1.75 * w_box, 0.28 * h_box, 180.0)
    full_crop, (fx0, fy0, fx1, fy1) = _safe_crop(
        cx_box - full_half_w,
        ymin - 0.15 * h_box,
        cx_box + full_half_w,
        ymax + 0.15 * h_box,
    )
    full_clean = cv2.resize(full_crop, (pw, ph), interpolation=cv2.INTER_AREA)

    # Map original bbox into full_clean coordinates for LSD measurement & cyan corner ticks
    fw = max(1.0, float(fx1 - fx0))
    fh = max(1.0, float(fy1 - fy0))
    bx0 = float(np.clip((xmin - fx0) / fw * pw, 0.0, pw - 1.0))
    by0 = float(np.clip((ymin - fy0) / fh * ph, 0.0, ph - 1.0))
    bx1 = float(np.clip((xmax - fx0) / fw * pw, bx0 + 2.0, float(pw)))
    by1 = float(np.clip((ymax - fy0) / fh * ph, by0 + 8.0, float(ph)))

    # Measure OpenCV LSD vertical support & lean on the clean full-shaft crop prior to drawing ticks
    lsd_box = (max(0.0, bx0 - 16.0), by0, min(float(pw), bx1 + 16.0), by1)
    if _svi_cvc is not None:
        vert_sup = float(_svi_cvc.vertical_post_support(full_clean, lsd_box, max_tilt_deg=12.0))
        lsd_lean = float(_svi_cvc.estimate_post_lean_deg(full_clean, lsd_box, max_tilt_deg=15.0))
    else:  # pragma: no cover
        vert_sup, lsd_lean = 0.5, 0.0

    # Panel 2: Crown & Cross-Arm Zoom (2x)
    zoom_half_w = max(1.8 * w_box, 0.22 * h_box, 260.0)
    crown_crop, _ = _safe_crop(
        cx_box - zoom_half_w,
        ymin - 0.18 * h_box,
        cx_box + zoom_half_w,
        ymin + 0.45 * h_box,
    )
    crown_clean = cv2.resize(crown_crop, (pw, ph), interpolation=cv2.INTER_CUBIC)

    # Panel 3: Base & Ground Collar Zoom (2x)
    base_crop, _ = _safe_crop(
        cx_box - zoom_half_w,
        ymax - 0.40 * h_box,
        cx_box + zoom_half_w,
        ymax + 0.15 * h_box,
    )
    base_clean = cv2.resize(base_crop, (pw, ph), interpolation=cv2.INTER_CUBIC)

    def _draw_corner_ticks(img: np.ndarray, box: tuple[float, float, float, float]) -> None:
        x0, y0, x1, y1 = [round(v) for v in box]
        y0 = max(28, y0)
        tick = max(10, min(22, round(0.22 * min(max(12, x1 - x0), max(24, y1 - y0)))))
        color = (255, 230, 0)  # High-visibility cyan/gold in RGB/BGR
        for cx, cy, dx, dy in (
            (x0, y0, 1, 1),
            (x1, y0, -1, 1),
            (x0, y1, 1, -1),
            (x1, y1, -1, -1),
        ):
            cv2.line(img, (cx, cy), (cx + dx * tick, cy), color, 2, cv2.LINE_AA)
            cv2.line(img, (cx, cy), (cx, cy + dy * tick), color, 2, cv2.LINE_AA)

    def _annotate_panel(
        panel: np.ndarray,
        title: str,
        *,
        corner_box: tuple[float, float, float, float] | None = None,
    ) -> np.ndarray:
        out = panel.copy()
        if corner_box is not None:
            _draw_corner_ticks(out, corner_box)
        cv2.rectangle(out, (0, 0), (pw, 24), (24, 28, 36), -1)
        cv2.putText(
            out,
            title,
            (8, 16),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.42,
            (240, 244, 248),
            1,
            cv2.LINE_AA,
        )
        return out

    p1 = _annotate_panel(
        full_clean,
        f"1: FULL SHAFT ({dist_m:.1f}m)",
        corner_box=(bx0, by0, bx1, by1),
    )
    p2 = _annotate_panel(crown_clean, "2: CROWN & CROSS-ARM (2X)")
    p3 = _annotate_panel(base_clean, "3: BASE & GROUND (2X)")

    composite = np.hstack([p1, p2, p3])
    cv2.line(composite, (pw, 0), (pw, ph), (220, 225, 230), 2)
    cv2.line(composite, (2 * pw, 0), (2 * pw, ph), (220, 225, 230), 2)

    # Mandatory Google Street View imagery attribution badge
    credit_w, credit_h = 148, 20
    cx0, cy0 = composite.shape[1] - credit_w - 6, composite.shape[0] - credit_h - 6
    cv2.rectangle(
        composite,
        (cx0, cy0),
        (composite.shape[1] - 6, composite.shape[0] - 6),
        (24, 28, 36),
        -1,
    )
    cv2.putText(
        composite,
        "Imagery (c) Google",
        (cx0 + 6, cy0 + 14),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.38,
        (235, 240, 245),
        1,
        cv2.LINE_AA,
    )

    return {
        "composite_img": composite,
        "panels": (full_clean, crown_clean, base_clean),
        "bbox_in_panel1": (bx0, by0, bx1, by1),
        "vertical_support": vert_sup,
        "lsd_lean_deg": lsd_lean,
    }


def apply_consistency_gates(
    verdict: PoleSubClassification,
    *,
    best_vert_sup: float,
    lsd_lean_med: float,
) -> dict[str, Any]:
    """Enforce deterministic taxonomy, voltage-tier, and OpenCV LSD lean fusion rules."""
    sub_type = verdict.sub_type
    is_true_utility = sub_type in TRUE_UTILITY_POLE_SUBTYPES

    eq_set = {eq.value for eq in verdict.equipment}
    # Promote DISTRIBUTION_PRIMARY with STREET_LIGHT_LUMINARY to JOINT_USE_LIGHT if appropriate
    if (
        sub_type == PoleSubType.DISTRIBUTION_PRIMARY
        and PoleEquipment.STREET_LIGHT_LUMINARY.value in eq_set
    ):
        sub_type = PoleSubType.JOINT_USE_LIGHT
        is_true_utility = True

    if not is_true_utility:
        has_primary = False
        has_secondary = False
        has_telecom = False
        cross_arm = CrossArmConfig.NONE.value
        is_double = False
    else:
        cross_arm = verdict.cross_arm.value
        has_primary = bool(
            verdict.has_primary_conductors
            or sub_type in {PoleSubType.TRANSMISSION, PoleSubType.DISTRIBUTION_PRIMARY}
            or cross_arm != CrossArmConfig.NONE.value
            or PoleEquipment.TRANSFORMER_CAN.value in eq_set
            or PoleEquipment.FUSE_CUTOUT.value in eq_set
            or PoleEquipment.RECLOSER_SWITCH.value in eq_set
            or PoleEquipment.CAPACITOR_BANK.value in eq_set
        )
        has_secondary = bool(
            verdict.has_secondary_conductors
            or sub_type in {PoleSubType.DISTRIBUTION_SECONDARY, PoleSubType.JOINT_USE_LIGHT}
            or PoleEquipment.TRANSFORMER_CAN.value in eq_set
            or PoleEquipment.STREET_LIGHT_LUMINARY.value in eq_set
        )
        has_telecom = bool(
            verdict.has_telecom_attach
            or sub_type == PoleSubType.TELECOM_ONLY
            or PoleEquipment.SPLICE_CLOSURE.value in eq_set
        )
        is_double = bool(verdict.is_double_pole)

    llm_lean = float(np.clip(verdict.lean_angle_deg, -45.0, 45.0))
    if best_vert_sup >= 0.35 and abs(llm_lean - lsd_lean_med) <= 5.0:
        fused_lean = round(0.5 * (llm_lean + lsd_lean_med), 2)
    elif best_vert_sup >= 0.50 and abs(llm_lean - lsd_lean_med) > 10.0:
        fused_lean = round(lsd_lean_med, 2)
    else:
        fused_lean = round(llm_lean, 2)

    condition_val = verdict.condition.value
    has_anomaly = bool(
        verdict.structural_anomaly
        or abs(fused_lean) > 8.0
        or condition_val == PoleCondition.DAMAGED.value
        or is_double
    )

    return {
        "is_true_utility_pole": bool(is_true_utility),
        "sub_type": sub_type.value,
        "material": verdict.material.value,
        "condition": condition_val,
        "cross_arm": cross_arm,
        "equipment": [eq.value for eq in verdict.equipment],
        "has_primary_conductors": has_primary,
        "has_secondary_conductors": has_secondary,
        "has_telecom_attach": has_telecom,
        "is_double_pole": is_double,
        "lean_angle_deg": fused_lean,
        "structural_anomaly": has_anomaly,
        "confidence": round(float(verdict.confidence), 3),
        "evidence": verdict.evidence,
    }


def query_catalog_observations(
    project: str,
    dataset: str,
    bucket: str,
    *,
    lat: float | None = None,
    lng: float | None = None,
    asset_id: str | None = None,
    observation_id: str | None = None,
    radius_m: float = DEFAULT_RADIUS_M,
) -> tuple[pd.DataFrame, float]:
    """Dry-run and execute the `full_frame_observations_latest` query under the 2 GB safety cap."""
    from google.cloud import bigquery

    creds = get_credentials()
    client = bigquery.Client(project=project, credentials=creds)
    if asset_id:
        sql = render_sql(ASSET_SQL, project, dataset)
        params = [bigquery.ScalarQueryParameter("id", "STRING", str(asset_id))]
    elif observation_id:
        sql = render_sql(OBS_SQL, project, dataset)
        params = [bigquery.ScalarQueryParameter("id", "STRING", str(observation_id))]
    else:
        if lat is None or lng is None:
            raise ValueError("Provide --coordinates, --asset-id, or --observation-id.")
        sql = render_sql(COORDS_SQL, project, dataset)
        params = [
            bigquery.ScalarQueryParameter("lat", "FLOAT64", float(lat)),
            bigquery.ScalarQueryParameter("lng", "FLOAT64", float(lng)),
            bigquery.ScalarQueryParameter("radius_m", "FLOAT64", float(radius_m)),
        ]

    dry_cfg = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False, query_parameters=params)
    dry_job = client.query(sql, job_config=dry_cfg)
    bytes_est = int(dry_job.total_bytes_processed or 0)
    if bytes_est > MAX_BYTES_BILLED:
        raise RuntimeError(
            f"BigQuery dry-run estimated {bytes_est / 1e9:.2f} GB, exceeding {MAX_BYTES_BILLED / 1e9:.2f} GB cap."
        )

    run_cfg = bigquery.QueryJobConfig(
        query_parameters=params,
        maximum_bytes_billed=MAX_BYTES_BILLED,
    )
    rows = [dict(r.items()) for r in client.query(sql, job_config=run_cfg).result()]
    if not rows:
        return pd.DataFrame(), bytes_est / 1e9

    df = pd.DataFrame(rows)
    df["gcs_uri"] = [
        gcs_uri_for(bucket, str(s), str(o))
        for s, o in zip(df["snapshot_id"], df["observation_id"], strict=True)
    ]
    return df, bytes_est / 1e9


def _decode_rgb_in_memory(raw_bytes: bytes) -> np.ndarray:
    """Decode JPEG bytes into an RGB numpy array in memory."""
    arr = np.frombuffer(raw_bytes, dtype=np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError("Failed to decode JPEG bytes in memory.")
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def _compute_nearest_asset_distances(asset_meta: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Compute `< 3.5 m` pairwise proximity across cataloged assets in the corridor."""
    out: dict[str, dict[str, Any]] = {}
    for i, a in enumerate(asset_meta):
        aid = str(a["asset_id"])
        best_d = float("inf")
        best_id: str | None = None
        for j, b in enumerate(asset_meta):
            if i == j:
                continue
            d = haversine_m(float(a["lat"]), float(a["lng"]), float(b["lat"]), float(b["lng"]))
            if d < best_d:
                best_d = d
                best_id = str(b["asset_id"])
        out[aid] = {
            "nearest_dist_m": best_d if math.isfinite(best_d) else None,
            "nearest_asset_id": best_id if best_d <= BUDDY_POLE_DIST_M else None,
        }
    return out


async def subclassify_full_frame_poles(
    raw_df: pd.DataFrame,
    fetch: Callable[[str], bytes],
    ask_fn: Callable[[list[Any]], Any],
    *,
    max_poles: int = MAX_POLES,
    max_views_per_pole: int = MAX_VIEWS_PER_POLE,
    allow_single_fallback: bool = False,
) -> dict[str, Any]:
    """Run deduplication, multi-view parallax selection, in-memory 3-panel slicing, and Gemini + LSD audit."""
    dedup = deduplicate_same_exposure_observations(raw_df)
    if dedup.empty:
        return {"pole_count": 0, "poles": []}

    candidate_assets: list[dict[str, Any]] = []
    for aid, grp in dedup.groupby("asset_id", sort=False):
        sel_views, max_par = select_parallax_views_for_asset(
            grp,
            max_views=max_views_per_pole,
            allow_fallback=allow_single_fallback,
        )
        if not sel_views:
            continue
        candidate_assets.append(
            {
                "asset_id": str(aid),
                "lat": float(grp["lat"].iloc[0]),
                "lng": float(grp["lng"].iloc[0]),
                "selected_views": sel_views,
                "parallax_deg": float(max_par),
                "n_valid_exposures": len(grp),
            }
        )

    candidate_assets.sort(
        key=lambda c: (
            0 if len(c["selected_views"]) >= 2 and c["parallax_deg"] >= MIN_PARALLAX_DEG else 1,
            -len(c["selected_views"]),
            -c["parallax_deg"],
            c["asset_id"],
        )
    )
    candidate_assets = candidate_assets[: max(1, int(max_poles))]
    proximity = _compute_nearest_asset_distances(candidate_assets)

    poles: list[dict[str, Any]] = []
    for cand in candidate_assets:
        aid = cand["asset_id"]
        prox = proximity.get(aid, {})
        near_id = prox.get("nearest_asset_id")
        near_d = prox.get("nearest_dist_m")

        composites: list[dict[str, Any]] = []
        for v in cand["selected_views"]:
            try:
                raw_im = _decode_rgb_in_memory(fetch(str(v["gcs_uri"])))
                comp = build_full_frame_3panel_crop(
                    raw_im,
                    (float(v["xmin"]), float(v["ymin"]), float(v["xmax"]), float(v["ymax"])),
                    dist_m=float(v["distance_m"]),
                )
                comp["observation_id"] = str(v["observation_id"])
                comp["distance_m"] = float(v["distance_m"])
                comp["bearing_deg"] = float(v["bearing_deg"])
                composites.append(comp)
            except (ValueError, RuntimeError, OSError, KeyError) as exc:
                print(f"Skipping unreadable view for {aid}: {exc}", file=sys.stderr)
                continue

        if not composites:
            continue

        best_vert_sup = max(float(c["vertical_support"]) for c in composites)
        lsd_leans = [float(c["lsd_lean_deg"]) for c in composites]
        lsd_lean_med = float(np.median(lsd_leans)) if lsd_leans else 0.0

        prox_note = (
            f"nearby_catalog_asset={near_id} at {near_d:.2f}m (<3.5m buddy-pole check required)"
            if near_id and near_d is not None
            else "no_other_catalog_asset_within_3.5m"
        )
        prompt_parts: list[Any] = [
            POLE_SUBCLASSIFICATION_PROMPT
            + f"\n\nCandidate metadata: asset_id={aid}, lat={cand['lat']:.6f}, lng={cand['lng']:.6f}, "
            f"views_used={len(composites)}, azimuth_parallax_deg={cand['parallax_deg']:.1f}, "
            f"opencv_lsd_vertical_support={best_vert_sup:.2f}, opencv_lsd_lean_deg={lsd_lean_med:.2f}, "
            f"{prox_note}."
        ]
        for idx, c in enumerate(composites):
            prompt_parts.append(
                f"View {idx + 1} (observation_id={c['observation_id']}, "
                f"distance={c['distance_m']:.1f}m, bearing={c['bearing_deg']:.1f} deg):"
            )
            prompt_parts.append(c["composite_img"])

        verdict = await ask_fn(prompt_parts)
        if verdict is None:
            continue

        gated = apply_consistency_gates(
            verdict,
            best_vert_sup=best_vert_sup,
            lsd_lean_med=lsd_lean_med,
        )
        poles.append(
            {
                "pole_id": aid,
                "lat": round(cand["lat"], 6),
                "lng": round(cand["lng"], 6),
                "is_true_utility_pole": gated["is_true_utility_pole"],
                "sub_type": gated["sub_type"],
                "material": gated["material"],
                "condition": gated["condition"],
                "cross_arm": gated["cross_arm"],
                "equipment": gated["equipment"],
                "has_primary_conductors": gated["has_primary_conductors"],
                "has_secondary_conductors": gated["has_secondary_conductors"],
                "has_telecom_attach": gated["has_telecom_attach"],
                "is_double_pole": gated["is_double_pole"],
                "lean_angle_deg": gated["lean_angle_deg"],
                "structural_anomaly": gated["structural_anomaly"],
                "confidence": gated["confidence"],
                "views_used": len(composites),
                "parallax_deg": round(cand["parallax_deg"], 1),
                "evidence": gated["evidence"],
            }
        )

    return {
        "pole_count": len(poles),
        "poles": poles,
    }


async def run_pipeline(args: argparse.Namespace) -> dict[str, Any]:
    """Run Full-Frame catalog discovery, exposure deduplication, and in-memory 3-panel sub-classification."""
    raw_df, _ = query_catalog_observations(
        args.project,
        args.dataset,
        args.gcs_bucket,
        lat=args.lat,
        lng=args.lng,
        asset_id=args.asset_id,
        observation_id=args.observation_id,
        radius_m=args.radius_m,
    )
    if raw_df.empty:
        return {"pole_count": 0, "poles": []}

    from google.cloud import storage

    creds = get_credentials()
    storage_client = storage.Client(project=args.project, credentials=creds)
    mem_cache: dict[str, bytes] = {}

    def fetch(uri: str) -> bytes:
        if uri not in mem_cache:
            clean = uri.removeprefix("gs://")
            bkt_name, blob_path = clean.split("/", 1)
            mem_cache[uri] = storage_client.bucket(bkt_name).blob(blob_path).download_as_bytes()
        return mem_cache[uri]

    if _svi_gc is not None:
        v_client = _svi_gc.make_vertex_client(
            args.project,
            location=args.location,
            credentials=creds,
        )
        backend = _svi_gc.VertexGeminiBackend(
            v_client,
            model=args.model,
            location=args.location,
            log=lambda m: print(m, file=sys.stderr),
        )
        runner = _svi_gc.GeminiRunner(
            backend,
            max_calls=40,
            concurrency=4,
            log=lambda m: print(m, file=sys.stderr),
        )

        async def ask_fn(parts: list[Any]) -> PoleSubClassification | None:
            return await runner.ask(parts, PoleSubClassification, seed=0)

        payload = await subclassify_full_frame_poles(
            raw_df,
            fetch,
            ask_fn,
            max_poles=MAX_POLES,
            max_views_per_pole=MAX_VIEWS_PER_POLE,
            allow_single_fallback=bool(args.asset_id or args.observation_id),
        )
        print(runner.cost.summary(), file=sys.stderr)
    else:  # pragma: no cover
        from google import genai
        from google.genai import types

        client = genai.Client(
            vertexai=True,
            project=args.project,
            location=args.location,
            credentials=creds,
        )

        async def ask_fn(parts: list[Any]) -> PoleSubClassification | None:
            genai_parts: list[Any] = []
            for p in parts:
                if isinstance(p, np.ndarray):
                    bgr = cv2.cvtColor(p, cv2.COLOR_RGB2BGR)
                    ok, buf = cv2.imencode(".jpg", bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
                    if not ok:
                        raise RuntimeError("Failed to encode composite crop in memory.")
                    genai_parts.append(
                        types.Part.from_bytes(data=buf.tobytes(), mime_type="image/jpeg")
                    )
                else:
                    genai_parts.append(str(p))
            resp = await asyncio.to_thread(
                client.models.generate_content,
                model=args.model,
                contents=genai_parts,
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    response_mime_type="application/json",
                    response_schema=PoleSubClassification,
                ),
            )
            return PoleSubClassification.model_validate_json(resp.text)

        payload = await subclassify_full_frame_poles(
            raw_df,
            fetch,
            ask_fn,
            max_poles=MAX_POLES,
            max_views_per_pole=MAX_VIEWS_PER_POLE,
            allow_single_fallback=bool(args.asset_id or args.observation_id),
        )

    if args.output:
        import json

        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2) + "\n")

    return payload


def _parse_coordinates(raw: Sequence[str] | str) -> tuple[float, float]:
    tokens = [raw] if isinstance(raw, str) else list(raw)
    joined = ",".join(t.strip() for t in tokens if t.strip())
    parts = [p.strip() for p in joined.split(",") if p.strip()]
    if len(parts) != 2:
        raise ValueError(f"Expected 'lat,lng' or 'LAT LNG', got {raw!r}")
    return float(parts[0]), float(parts[1])


def parse_args(
    argv: Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
) -> argparse.Namespace:
    """Parse CLI arguments with environment variable defaults (`PROJECT_ID`, `GCS_BUCKET`)."""
    env = os.environ if env is None else env
    p = argparse.ArgumentParser(
        description=(
            "Sub-classify cataloged ASSET_CLASS_UTILITY_POLE entities from Street View Insights "
            "Full-Frame views (full_frame_observations_latest)."
        ),
        allow_abbrev=False,
    )
    target = p.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--coordinates",
        nargs="+",
        metavar="LAT,LNG",
        help="Target GPS coordinates ('lat,lng' or 'LAT LNG').",
    )
    target.add_argument(
        "--asset-id",
        dest="asset_id",
        help="Cataloged Street View Insights asset_id.",
    )
    target.add_argument(
        "--observation-id",
        dest="observation_id",
        help="Full-frame observation_id.",
    )
    p.add_argument(
        "--project",
        default=env.get("PROJECT_ID") or env.get("GOOGLE_CLOUD_PROJECT"),
        help="Google Cloud project ID for BigQuery and Vertex AI (default: $PROJECT_ID or $GOOGLE_CLOUD_PROJECT).",
    )
    p.add_argument(
        "--gcs-bucket",
        dest="gcs_bucket",
        default=env.get("GCS_BUCKET"),
        help="Cloud Storage bucket name for Street View Insights imagery (default: $GCS_BUCKET).",
    )
    p.add_argument(
        "--radius-m",
        dest="radius_m",
        type=float,
        default=DEFAULT_RADIUS_M,
        help=f"Search radius in meters around --coordinates (default: {DEFAULT_RADIUS_M}).",
    )
    p.add_argument(
        "--dataset",
        default=env.get("BIGQUERY_DATASET") or env.get("BQ_DATASET") or DEFAULT_DATASET,
        help=f"BigQuery dataset name (default: {DEFAULT_DATASET}).",
    )
    p.add_argument(
        "--model",
        default=env.get("GEMINI_MODEL", DEFAULT_MODEL),
        help=f"Gemini model name (default: {DEFAULT_MODEL}).",
    )
    p.add_argument(
        "--location",
        default=env.get("VERTEX_LOCATION", DEFAULT_LOCATION),
        help=f"Vertex AI region (default: {DEFAULT_LOCATION}).",
    )
    p.add_argument(
        "--output",
        default=None,
        help="Output JSON file path (prints to stdout if omitted).",
    )

    args = p.parse_args(argv)
    args.lat = None
    args.lng = None
    if args.coordinates:
        try:
            args.lat, args.lng = _parse_coordinates(args.coordinates)
        except (ValueError, TypeError):
            p.error(f"Invalid --coordinates {args.coordinates!r}; expected 'lat,lng' or 'LAT LNG'.")
    if not args.project:
        p.error("Provide --project or set the PROJECT_ID environment variable.")
    if not args.gcs_bucket:
        p.error("Provide --gcs-bucket or set the GCS_BUCKET environment variable.")
    args.gcs_bucket = str(args.gcs_bucket).removeprefix("gs://").strip("/")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    import json

    args = parse_args(argv)
    payload = asyncio.run(run_pipeline(args))
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
