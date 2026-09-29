"""Discrete-asset detection pipeline: code renders the views, Gemini only draws boxes (T12).

Per pano and ground camera, code renders a world-oriented, level (pitch 0) pinhole view from
the calibrated fisheye frame. Gemini returns `FrameDetections` boxes on that view; code turns
each box into a world bearing with the view's exact geometry (`PerspectiveView.box_to_bearings`)
and the camera centre from `camera_pose` (`rosette.camera_center_enu`), then `entities.cluster`
triangulates and deduplicates. No geometry is asked of the model.
"""

from __future__ import annotations

import dataclasses
import math
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

from svi_geo import entities as ent
from svi_geo import geo, images, rosette, schemas
from svi_geo import triangulate as tri

DETECT_CLASSES = ("HOUSE", "UTILITY_POLE", "ROAD_SIGN")
VIEW_HFOV_DEG = 70.0  # 60 deg camera spacing + 10 deg overlap between neighbouring views
VIEW_SIZE = (1024, 1280)  # width, height -> vfov ~82 deg (pole bases down to ~-41 deg)
INTRA_PANO_AZ_TOL_DEG = {"HOUSE": 8.0}
DEFAULT_AZ_TOL_DEG = 2.0


@dataclasses.dataclass(frozen=True)
class ViewSpec:
    pano_id: str
    cam_k: int
    observation_id: str
    gcs_uri: str
    pose: Mapping[str, Any]
    view: rosette.PerspectiveView


def views_for_pano(
    rows: Sequence[Mapping[str, Any]],
    intr: rosette.Intrinsics,
    hfov_deg: float = VIEW_HFOV_DEG,
    size: tuple[int, int] = VIEW_SIZE,
) -> list[ViewSpec]:
    """One level view per ground camera, centred on the camera's (calibrated) heading."""
    out = []
    for r in sorted(rows, key=lambda r: int(r["cam_k"])):
        k = int(r["cam_k"])
        if not rosette.is_ground_camera(k):
            continue
        yaw = float(r["camera_pose"]["heading"]) + intr.cam_rot_delta_deg.get(k, (0.0,))[0]
        view = rosette.PerspectiveView(yaw % 360.0, 0.0, hfov_deg, size[0], size[1])
        out.append(
            ViewSpec(
                r["pano_id"], k, r["observation_id"], r.get("gcs_uri", ""), r["camera_pose"], view
            )
        )
    return out


def render_view(image: np.ndarray, intr: rosette.Intrinsics, spec: ViewSpec) -> np.ndarray:
    return rosette.render_perspective(image, intr, spec.pose, spec.view, spec.cam_k)


def detection_prompt(classes: Sequence[str] = DETECT_CLASSES) -> str:
    names = ", ".join(classes)
    return (
        "This is a rectified, level street-level photo (no lens distortion). Detect every "
        f"instance of these classes: {names}. For each, return label, a tight box_2d "
        "[ymin, xmin, ymax, xmax] on a 0-1000 scale covering the WHOLE visible object (for "
        "poles and sign posts the box bottom must be where the post meets the ground), your "
        "confidence (0-1) and the material if clearly visible, else UNKNOWN. Skip objects that "
        "are mostly hidden or cut off by the image border. Return an empty list if none."
    )


def detections_to_observations(
    fd: schemas.FrameDetections,
    spec: ViewSpec,
    ref_lla: Sequence[float],
    min_confidence: float = 0.3,
    classes: Sequence[str] = DETECT_CLASSES,
) -> list[ent.Observation]:
    """Boxes on a rendered view -> world-bearing observations (pure geometry)."""
    w, h = spec.view.width, spec.view.height
    origin = rosette.camera_center_enu(spec.pose, ref_lla)
    out = []
    for i, d in enumerate(fd.detections):
        cls = d.label.value
        if cls not in classes or d.confidence < min_confidence:
            continue
        box = schemas.box_2d_to_pixels(d.box_2d, w, h)
        b = spec.view.box_to_bearings(box)
        truncated = box[3] >= h - 2  # bottom cut by the view border: no ground contact
        el_bottom = None if truncated else b["el_bottom"]
        el = el_bottom if (cls in ent.GROUND_CONTACT and el_bottom is not None) else b["el"]
        out.append(
            ent.Observation(
                obs_id=f"{spec.observation_id}#{i}",
                pano_id=spec.pano_id,
                cls=cls,
                ray=tri.Ray(origin, b["az"], el, meta={"cam_k": spec.cam_k, "box": box}),
                confidence=float(d.confidence),
                el_bottom_deg=el_bottom,
                el_top_deg=b["el_top"],
                attrs={"material": d.material.value if d.material else None},
            )
        )
    return out


def merge_intra_pano(
    observations: Sequence[ent.Observation],
    az_tol_deg: Mapping[str, float] | None = None,
) -> list[ent.Observation]:
    """Neighbouring views overlap by ~10 deg, so one object can be boxed twice in a pano.
    Keep the most confident box per (pano, class) within an azimuth tolerance."""
    tol = {**INTRA_PANO_AZ_TOL_DEG, **(az_tol_deg or {})}
    groups: dict[tuple[str, str], list[ent.Observation]] = defaultdict(list)
    for o in observations:
        groups[(o.pano_id, o.cls)].append(o)
    out = []
    for key in sorted(groups):
        kept: list[ent.Observation] = []
        for o in sorted(groups[key], key=lambda o: (-o.confidence, o.obs_id)):
            t = tol.get(o.cls, DEFAULT_AZ_TOL_DEG)
            if all(abs(float(geo.angdiff(o.ray.az_deg, k.ray.az_deg))) > t for k in kept):
                kept.append(o)
        out.extend(kept)
    return out


@dataclasses.dataclass
class DetectionRun:
    observations: list[ent.Observation]
    records: list[dict]  # per view: spec, detections (and the rendered image if kept)


async def detect_panos(
    frames: pd.DataFrame,
    fetch: Callable[[str], bytes],
    runner: Any,
    intr: rosette.Intrinsics,
    ref_lla: Sequence[float],
    classes: Sequence[str] = DETECT_CLASSES,
    keep_images: bool = False,
    min_confidence: float = 0.3,
) -> DetectionRun:
    """Render every ground view of every pano in code, ask Gemini for boxes, convert to rays.

    `frames` rows need pano_id, cam_k, observation_id, camera_pose and gcs_uri.
    """
    specs = [
        s
        for _, g in frames.groupby("pano_id", sort=True)
        for s in views_for_pano(g.to_dict("records"), intr)
    ]
    prompt = detection_prompt(classes)
    rendered = []
    for s in specs:
        img = images.decode(fetch(s.gcs_uri))
        rendered.append(render_view(img, intr, s))
    replies = await runner.ask_many([([prompt, im], schemas.FrameDetections) for im in rendered])
    obs, records = [], []
    for s, im, fd in zip(specs, rendered, replies, strict=True):
        rec = {"spec": s, "detections": fd}
        if keep_images:
            rec["image"] = im
        records.append(rec)
        if fd is not None:
            obs.extend(detections_to_observations(fd, s, ref_lla, min_confidence, classes))
    return DetectionRun(merge_intra_pano(obs), records)


def task_renderer(
    frames: pd.DataFrame,
    fetch: Callable[[str], bytes],
    intr: rosette.Intrinsics,
    hfov_deg: float = 40.0,
    size: int = 768,
    lift_m: float = 2.0,
) -> Callable[[Any], tuple[np.ndarray, rosette.PerspectiveView]]:
    """Renderer for self-consistency `ViewTask`s: a small world-oriented view centred on the
    predicted bearing (poles/signs: `lift_m` above the ground point), rendered in code from the
    task's own frame. `frames` rows need pano_id, cam_k, camera_pose and gcs_uri."""
    rows = {(r["pano_id"], int(r["cam_k"])): r for r in frames.to_dict("records")}

    def render(task) -> tuple[np.ndarray, rosette.PerspectiveView]:
        row = rows[(task.pano_id, int(task.cam_k))]
        img = images.decode(fetch(row["gcs_uri"]))
        lift = lift_m if task.cls in ent.GROUND_CONTACT else 0.0
        el = math.degrees(math.atan(math.tan(math.radians(task.el_deg)) + lift / task.range_m))
        view = rosette.PerspectiveView(
            float(task.az_deg), float(np.clip(el, -30.0, 30.0)), hfov_deg, size, size
        )
        return rosette.render_perspective(img, intr, row["camera_pose"], view, task.cam_k), view

    return render
