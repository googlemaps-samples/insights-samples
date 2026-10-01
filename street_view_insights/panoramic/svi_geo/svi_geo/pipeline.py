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

from svi_geo import data, geo, images, rosette, schemas
from svi_geo import entities as ent
from svi_geo import triangulate as tri

PUBLIC_ROW_CLASSES = (
    "UTILITY_POLE",
    "ROAD_SIGN",
    "STREET_LIGHT",
    "FIRE_HYDRANT",
    "STREET_TREE",
)
DETECT_CLASSES = PUBLIC_ROW_CLASSES
VIEW_HFOV_DEG = 70.0  # 60 deg camera spacing + 10 deg overlap between neighbouring views
VIEW_SIZE = (1024, 1280)  # width, height -> vfov ~82 deg (pole bases down to ~-41 deg)
INTRA_PANO_AZ_TOL_DEG = {"HOUSE": 8.0, "STREET_TREE": 4.0}
DEFAULT_AZ_TOL_DEG = 2.0


@dataclasses.dataclass(frozen=True)
class ViewSpec:
    pano_id: str
    cam_k: int
    observation_id: str
    gcs_uri: str
    pose: Mapping[str, Any]
    view: rosette.PerspectiveView

    @property
    def capture_id(self) -> str:
        return self.pano_id


def views_for_pano(
    rows: Sequence[Mapping[str, Any]],
    intr: rosette.Intrinsics,
    hfov_deg: float = VIEW_HFOV_DEG,
    size: tuple[int, int] = VIEW_SIZE,
    *,
    yaw_delta_deg: float = 0.0,
    hfov_scale: float = 1.0,
) -> list[ViewSpec]:
    """One level view per ground camera, centred on the camera's (calibrated) heading."""
    out = []
    eff_hfov = float(np.clip(hfov_deg * hfov_scale, 20.0, 110.0))
    for r in sorted(rows, key=lambda r: int(r["cam_k"])):
        k = int(r["cam_k"])
        if not rosette.is_ground_camera(k):
            continue
        yaw = (
            float(r["camera_pose"]["heading"])
            + intr.cam_rot_delta_deg.get(k, (0.0,))[0]
            + yaw_delta_deg
        )
        view = rosette.PerspectiveView(yaw % 360.0, 0.0, eff_hfov, size[0], size[1])
        cid = str(r.get("capture_id") or r.get("pano_id") or "")
        out.append(
            ViewSpec(cid, k, r["observation_id"], r.get("gcs_uri", ""), r["camera_pose"], view)
        )
    return out


def render_view(
    image: np.ndarray,
    intr: rosette.Intrinsics,
    spec: ViewSpec,
    *,
    antialias: bool = True,
    mask_hood: bool = False,
) -> np.ndarray:
    return rosette.render_perspective(
        image, intr, spec.pose, spec.view, spec.cam_k, antialias=antialias, mask_hood=mask_hood
    )


def detection_prompt(classes: Sequence[str] = DETECT_CLASSES) -> str:
    names = ", ".join(classes)
    return (
        "This is a rectified, level street-level photo (no lens distortion). Detect every "
        f"public right-of-way asset of these classes: {names}. For each asset, return label, a "
        "tight box_2d [ymin, xmin, ymax, xmax] on a 0-1000 scale covering the WHOLE visible "
        "vertical extent down to ground contact:\n"
        "- For UTILITY_POLE, ROAD_SIGN, STREET_LIGHT, and FIRE_HYDRANT, the box bottom (ymax) "
        "MUST be where the post or base meets the ground/sidewalk.\n"
        "- For STREET_TREE, box the roadside/curb-strip tree from its canopy top down to where "
        "the trunk base meets the ground or planting strip (ymax at trunk base); distinguish "
        "living trees with foliage/bark from utility poles.\n"
        "- Do NOT box residential houses, private buildings, or distant background forest canopies.\n"
        "Also return confidence (0-1), material if clearly visible (WOOD, METAL, CONCRETE, "
        "OTHER, or UNKNOWN), and condition (GOOD, FAIR, POOR, or UNKNOWN). Skip objects that "
        "are mostly hidden or cut off by the image border. Return an empty list if none."
    )


def build_fewshot_prompt_parts(
    examples: Sequence[tuple[np.ndarray, schemas.FrameDetections, str]],
    query_image: np.ndarray,
    classes: Sequence[str] = DETECT_CLASSES,
) -> list[Any]:
    """Build a multimodal visual few-shot prompt list `[prompt, ex_text, ex_img, ex_json, ..., query_img]`."""
    parts: list[Any] = [detection_prompt(classes)]
    for idx, (ex_img, ex_fd, note) in enumerate(examples, start=1):
        parts.append(
            f"\n--- Few-Shot Example {idx} ({note}) ---\nReference rectified perspective crop:"
        )
        parts.append(ex_img)
        parts.append(
            f"Expected `FrameDetections` JSON for Example {idx} (note how `ymax` reaches the exact "
            f"ground-contact point of the post or tree trunk):\n{ex_fd.model_dump_json()}"
        )
    parts.append(
        "\n--- Target Perspective View ---\n"
        "Now detect all visible public right-of-way assets in this target image and return JSON "
        "matching `FrameDetections`:"
    )
    parts.append(query_image)
    return parts


def detections_to_observations(
    fd: schemas.FrameDetections,
    spec: ViewSpec,
    ref_lla: Sequence[float],
    min_confidence: float = 0.3,
    classes: Sequence[str] = DETECT_CLASSES,
    *,
    image: np.ndarray | None = None,
) -> list[ent.Observation]:
    """Boxes on a rendered view -> world-bearing observations (pure geometry)."""
    from svi_geo import views

    w, h = spec.view.width, spec.view.height
    origin = rosette.camera_center_enu(spec.pose, ref_lla)
    out = []
    for i, d in enumerate(fd.detections):
        cls = d.label.value
        if cls not in classes or d.confidence < min_confidence:
            continue
        box = schemas.box_2d_to_pixels(d.box_2d, w, h)
        ro = views.redaction_overlap(image, box) if image is not None else 0.0
        conf = float(d.confidence) * (0.5 if ro > 0.30 else 1.0)
        if conf < min_confidence:
            continue
        b = spec.view.box_to_bearings(box)
        ymid = 0.5 * (box[1] + box[3])
        az_l, _ = spec.view.pixel_to_bearing(box[0], ymid)
        az_r, _ = spec.view.pixel_to_bearing(box[2], ymid)
        truncated = box[3] >= h - 2  # bottom cut by the view border: no ground contact
        el_bottom = None if truncated else b["el_bottom"]
        el = el_bottom if (cls in ent.GROUND_CONTACT and el_bottom is not None) else b["el"]
        out.append(
            ent.Observation(
                obs_id=f"{spec.observation_id}#{i}",
                pano_id=spec.pano_id,
                cls=cls,
                ray=tri.Ray(
                    origin,
                    b["az"],
                    el,
                    meta={
                        "cam_k": spec.cam_k,
                        "box": box,
                        "az_left": float(az_l),
                        "az_right": float(az_r),
                        "redaction_overlap": ro,
                    },
                ),
                confidence=conf,
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
    raise_if_all_failed: bool = True,
    *,
    yaw_delta_deg: float = 0.0,
    hfov_scale: float = 1.0,
    seed: int | None = None,
    decode_scale: float | None = None,
    antialias: bool = True,
    thinking_level: str | None = None,
    media_resolution: str | None = None,
) -> DetectionRun:
    """Render every ground view of every rosette in code, ask Gemini for boxes, convert to rays.

    `frames` rows need capture_id (or pano_id), cam_k, observation_id, camera_pose and gcs_uri.
    """
    from svi_geo import views

    frames = data.ensure_capture_id(frames)
    specs = [
        s
        for _, g in frames.groupby("capture_id", sort=True)
        for s in views_for_pano(
            g.to_dict("records"),
            intr,
            yaw_delta_deg=yaw_delta_deg,
            hfov_scale=hfov_scale,
        )
    ]
    prompt = detection_prompt(classes)
    rendered = []
    for s in specs:
        scale = (
            float(decode_scale)
            if decode_scale is not None
            else images.decode_scale_for_view(s.view.width, s.view.hfov_deg)
        )
        img = images.decode(fetch(s.gcs_uri), scale=scale)
        rendered.append(render_view(img, intr, s, antialias=antialias))
        del img
    ask_kw: dict[str, Any] = {"raise_if_all_failed": raise_if_all_failed}
    if seed is not None:
        ask_kw["seed"] = seed
    if thinking_level is not None:
        ask_kw["thinking_level"] = thinking_level
    if media_resolution is not None:
        ask_kw["media_resolution"] = media_resolution
    replies = await runner.ask_many(
        [([prompt, im], schemas.FrameDetections) for im in rendered],
        **ask_kw,
    )
    obs, records = [], []
    for s, im, fd in zip(specs, rendered, replies, strict=True):
        black = rosette.view_black_fraction(intr, s.pose, s.view, s.cam_k)
        ro_max = 0.0
        if fd is not None and fd.detections:
            ro_max = max(
                views.redaction_overlap(
                    im, schemas.box_2d_to_pixels(d.box_2d, s.view.width, s.view.height)
                )
                for d in fd.detections
            )
        rec = {
            "spec": s,
            "detections": fd,
            "black_fraction": black,
            "redaction_overlap_max": ro_max,
        }
        if keep_images:
            rec["image"] = im
        records.append(rec)
        if fd is not None:
            obs.extend(
                detections_to_observations(fd, s, ref_lla, min_confidence, classes, image=im)
            )
    return DetectionRun(merge_intra_pano(obs), records)


def task_renderer(
    frames: pd.DataFrame,
    fetch: Callable[[str], bytes],
    intr: rosette.Intrinsics,
    hfov_deg: float = 40.0,
    size: int = 768,
    lift_m: float = 2.0,
    min_hfov_deg: float = 20.0,
    max_black: float = 0.01,
) -> Callable[[Any], tuple[np.ndarray, rosette.PerspectiveView, float] | None]:
    """Renderer for self-consistency `ViewTask`s: a small world-oriented square view centred on
    the predicted bearing (poles/signs: `lift_m` above the ground point), rendered in code.

    The view is rendered from whichever ground camera of the task's rosette covers it
    (`rosette.best_camera_for_view`), narrowed from `hfov_deg` if needed so that less than
    `max_black` of it falls outside the sensor. Returns (image, view, black_fraction), or None
    when no camera covers even `min_hfov_deg` (the task cannot be checked).
    `frames` rows need capture_id (or pano_id), cam_k, observation_id, camera_pose and gcs_uri."""
    frames = data.ensure_capture_id(frames)
    by_pano: dict[str, list[dict]] = defaultdict(list)
    for r in frames.to_dict("records"):
        cid = str(r.get("capture_id") or r.get("pano_id") or "")
        by_pano[cid].append(r)
        if r.get("pano_id") and str(r["pano_id"]) != cid:
            by_pano[str(r["pano_id"])].append(r)

    def render(task) -> tuple[np.ndarray, rosette.PerspectiveView, float] | None:
        lift = lift_m if task.cls in ent.GROUND_CONTACT else 0.0
        el = math.degrees(math.atan(math.tan(math.radians(task.el_deg)) + lift / task.range_m))
        pitch = float(np.clip(el, -30.0, 30.0))
        choice = rosette.best_camera_for_view(
            by_pano[task.pano_id], intr, float(task.az_deg), pitch, 1.0,
            min_hfov=min_hfov_deg, max_black=max_black, hfov_cap=hfov_deg,
        )  # fmt: skip
        if choice is None:
            return None
        row = choice.row
        view = rosette.PerspectiveView(float(task.az_deg), pitch, choice.hfov_deg, size, size)
        scale = images.decode_scale_for_view(size, choice.hfov_deg)
        img = images.decode(fetch(row["gcs_uri"]), scale=scale)
        pose = row["camera_pose"]
        black = rosette.view_black_fraction(intr, pose, view, choice.cam_k)
        return rosette.render_perspective(img, intr, pose, view, choice.cam_k), view, black

    return render
