"""Shared use-case execution pipelines for notebooks and the label-free evaluation harness (T7).

The notebooks and `scripts/run_labelfree_eval.py` both call these functions so the evaluation
harness tests the exact code path shipped in the notebooks. All experimental improvements live
on `Variant` with defaults that preserve baseline behaviour until promoted by `labelfree.decide_keep`.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

from svi_geo import cvchecks as cvc
from svi_geo import entities as ent
from svi_geo import eval as ev
from svi_geo import gemini_client as gc
from svi_geo import geo, images, pipeline, roof, rosette, schemas, sequence, smoothing, views

UC1_PROMPT_V0 = (
    "The image is centred on the bearing of a target house. Is a house visible at the CENTRE? "
    "If yes, box it ([ymin, xmin, ymax, xmax], 0-1000), and report occlusion, the visible "
    "fraction of its facade, stories, exterior material and roof type, with your confidence."
)
UC1_PROMPT_PARAPHRASE = (
    "This rectified street-level view looks directly toward a residential building near the "
    "horizontal centre. Determine whether a house is visible at the centre; if so, return its "
    "tight bounding box [ymin, xmin, ymax, xmax] in 0..1000, occlusion level, visible facade "
    "fraction, number of stories, primary exterior cladding material, and roof geometry."
)

UC3_PROMPT_V0 = (
    "You see street-level views from up to three consecutive panoramas of one drive: the "
    "PREVIOUS pano (front view, if any), the CENTRE pano (front, left and right views) and the "
    "NEXT pano (front view, if any). Report, for the CENTRE pano only, the ROAD (side CENTER) "
    "and the SIDEWALK on the LEFT and on the RIGHT: present, surface material, condition and "
    "your confidence (0-1). If there is no sidewalk on a side, report it with present=false. "
    "Use the neighbouring panos only as context for surfaces hidden in the centre views."
)
UC3_PROMPT_V1 = (
    "You are auditing road and pedestrian sidewalk surfaces for the CENTRE panorama using "
    "rectified street-level views (prompt_version=uc3_v1). Examine the CENTRE front view for "
    "ROAD (side CENTER), the CENTRE left view for SIDEWALK LEFT, and the CENTRE right view for "
    "SIDEWALK RIGHT (using PREVIOUS/NEXT front views only when a parked vehicle or shadow hides "
    "the centre surface). Definition of SIDEWALK: a constructed, paved or graded pedestrian "
    "walkway separated from the roadway by a kerb, verge, or drainage line. Do NOT classify "
    "grass lawns, unpaved road shoulders, gravel verges, or private residential driveways as "
    "SIDEWALK; when no continuous pedestrian walkway exists on a side, you MUST set "
    "present=false and material=null."
)

UC4_PROMPT_V0 = (
    "This is a lens-corrected street-level photo. Trace the visible roof edges of the main "
    "building (ridge, eaves, hips, valleys, rakes) as polylines of [y, x] points on a 0-1000 "
    "grid. Only include edges you can see; set roof_visible=false if no roof is visible."
)


@dataclasses.dataclass(frozen=True)
class Variant:
    """Configuration flags for UC1..UC4 pipelines (defaults reproduce the baseline notebooks)."""

    name: str = "baseline"
    # Perturbation controls (signal e)
    yaw_delta_deg: float = 0.0
    hfov_scale: float = 1.0
    gemini_seed: int | None = None
    prompt_paraphrase: bool = False

    # Global rendering & Gemini dials
    antialias: bool = True
    thinking_level: str | None = None
    media_resolution: str | None = None

    # UC1 parameters
    uc1_view_size: tuple[int, int] = (1024, 768)
    uc1_sky_contact_weight: float = 0.0
    uc1_truncation_penalty: float = 0.0
    uc1_diversify_days: bool = False
    uc1_framing_weighted_fusion: bool = False
    uc1_min_agree_views: int = 1
    uc1_facade_edge_triangulation: bool = False
    uc1_clahe: bool = False

    # UC2 parameters
    uc2_min_confidence: float = 0.40
    uc2_class_min_confidence: Mapping[str, float] = dataclasses.field(default_factory=dict)
    uc2_min_post_panos: int = 1
    uc2_cv_post_gate: bool = False
    uc2_cv_post_min_support: float = 0.35
    uc2_cv_tree_min_support: float = 0.25
    uc2_house_facade_edges: bool = False

    # UC3 parameters
    uc3_prompt_version: str = "v0"
    uc3_road_view_size: tuple[int, int] = (1024, 768)
    uc3_kerb_sidewalk_prior: bool = False
    uc3_window_size: int = 3
    uc3_stay_prob: float = 0.88

    # UC4 parameters
    uc4_view_size: tuple[int, int] = (1200, 900)
    uc4_sky_contact_min: float = 0.0
    uc4_flash_lite_precheck: bool = False
    uc4_validator_gates: bool = False
    uc4_validator_sky_min: float = 0.35
    uc4_clahe: bool = False

    def describe(self) -> str:
        """Human-readable summary starting with `variant=<name>` followed by all tuned fields."""
        fields = [
            f"{f.name}={getattr(self, f.name)!r}"
            for f in dataclasses.fields(self)
            if f.name != "name"
        ]
        return f"variant={self.name}\n  " + ", ".join(fields)


BASELINE_VARIANT = Variant(name="baseline")

DEFAULT_VARIANT = Variant(
    name="final",
    uc1_sky_contact_weight=0.5,
    uc1_truncation_penalty=0.6,
    uc1_diversify_days=False,
    uc1_framing_weighted_fusion=True,
    uc1_min_agree_views=1,
    uc1_facade_edge_triangulation=True,
    uc2_min_post_panos=2,
    uc2_class_min_confidence={
        "ROAD_SIGN": 0.55,
        "UTILITY_POLE": 0.50,
        "STREET_LIGHT": 0.50,
        "FIRE_HYDRANT": 0.50,
        "STREET_TREE": 0.48,
    },
    uc2_cv_post_gate=True,
    uc2_cv_post_min_support=0.35,
    uc2_cv_tree_min_support=0.25,
    uc2_house_facade_edges=False,
    uc3_prompt_version="v1",
    uc3_road_view_size=(1280, 960),
    uc3_kerb_sidewalk_prior=True,
    uc3_window_size=3,
    uc4_sky_contact_min=0.25,
    uc4_validator_gates=True,
    uc4_validator_sky_min=0.20,
)


# --------------------------------------------------------------------------- UC1


def uc1_select_views(
    frames: pd.DataFrame,
    lat: float,
    lng: float,
    intr: rosette.Intrinsics,
    *,
    aspect: float = 4 / 3,
    house_width_m: float = views.HOUSE_WIDTH_M,
    house_height_m: float = views.HOUSE_HEIGHT_M,
    max_dist_m: float = 80.0,
    max_per_seq: int = 4,
    n: int = 12,
    variant: Variant = DEFAULT_VARIANT,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Select and rank candidate views for UC1 (`house_image_discovery_with_cost`)."""
    cands = views.house_view_candidates(
        frames,
        lat,
        lng,
        intr,
        aspect=aspect,
        house_width_m=house_width_m,
        house_height_m=house_height_m,
        max_dist_m=max_dist_m,
    )
    rank_kw: dict[str, Any] = {"max_per_seq": max_per_seq, "n": n}
    if variant.uc1_diversify_days:
        rank_kw["diversify_days"] = True
        rank_kw["frames"] = frames
    ranked = views.rank_house_views(cands, **rank_kw)
    return cands, ranked


def _box_truncated(box_2d: Sequence[int] | None, margin: int = 15) -> bool:
    if not box_2d or len(box_2d) != 4:
        return True
    y0, x0, y1, x1 = box_2d
    return bool(x0 <= margin or y0 <= margin or x1 >= 1000 - margin or y1 >= 1000 - margin)


def _framing_weight(
    v: schemas.HouseView,
    crop: np.ndarray,
    width: int,
    height: int,
    variant: Variant,
) -> float:
    w = float(v.confidence)
    if not variant.uc1_framing_weighted_fusion:
        return w
    w *= max(0.2, float(v.facade_visible_fraction))
    if v.occlusion == schemas.Occlusion.HEAVY:
        w *= 0.25
    elif v.occlusion == schemas.Occlusion.PARTIAL:
        w *= 0.65
    if _box_truncated(v.box_2d):
        w *= max(0.1, 1.0 - float(variant.uc1_truncation_penalty or 0.6))
    if v.box_2d:
        box_px = schemas.box_2d_to_pixels(v.box_2d, width, height)
        if views.redaction_overlap(crop, box_px) > 0.30:
            w *= 0.5
        if variant.uc1_sky_contact_weight > 0.0:
            x0, y0, x1, _ = box_px
            sc = cvc.sky_contact(crop, [(x0, y0), (x1, y0)])
            w *= 1.0 + float(variant.uc1_sky_contact_weight) * sc
    return w


async def uc1_run(
    ranked: pd.DataFrame,
    fetch: Callable[[str], bytes],
    runner: gc.GeminiRunner,
    intr: rosette.Intrinsics,
    *,
    width: int | None = None,
    height: int | None = None,
    variant: Variant = DEFAULT_VARIANT,
) -> dict[str, Any]:
    """Render ranked house views, query Gemini (`HouseView`), triangulate location, and fuse attributes."""
    w = int(width) if width is not None else int(variant.uc1_view_size[0])
    h = int(height) if height is not None else int(variant.uc1_view_size[1])
    raw_rows = ranked.to_dict("records")
    cand_rows: list[dict[str, Any]] = []
    valid_indices: list[int] = []
    crops: list[np.ndarray] = []
    black: list[float] = []
    view_objs: list[rosette.PerspectiveView] = []
    for idx_r, r in enumerate(raw_rows):
        base_view = views.view_for(r, w, h)
        if variant.yaw_delta_deg != 0.0 or variant.hfov_scale != 1.0:
            yaw = (base_view.yaw_deg + variant.yaw_delta_deg) % 360.0
            hfov = min(
                float(r.get("max_hfov", base_view.hfov_deg)),
                base_view.hfov_deg * variant.hfov_scale,
            )
            v_obj = rosette.PerspectiveView(yaw, base_view.pitch_deg, hfov, w, h)
        else:
            v_obj = base_view
        scale = images.decode_scale_for_view(w, v_obj.hfov_deg)
        try:
            img = images.decode(fetch(r["gcs_uri"]), scale=scale)
        except Exception:
            continue
        cand_rows.append(r)
        valid_indices.append(idx_r)
        view_objs.append(v_obj)
        crop = rosette.render_perspective(
            img,
            intr,
            r["camera_pose"],
            v_obj,
            int(r["cam_k"]),
            antialias=variant.antialias,
            mask_hood=True,
        )
        if variant.uc1_clahe:
            crop = images.clahe_lab(crop)
        crops.append(crop)
        black.append(rosette.view_black_fraction(intr, r["camera_pose"], v_obj, int(r["cam_k"])))

    prompt = UC1_PROMPT_PARAPHRASE if variant.prompt_paraphrase else UC1_PROMPT_V0
    ask_kw: dict[str, Any] = {
        "validator": lambda v: v.validate_in_image(w, h),
    }
    if variant.gemini_seed is not None:
        ask_kw["seed"] = variant.gemini_seed
    if variant.thinking_level is not None:
        ask_kw["thinking_level"] = variant.thinking_level
    if variant.media_resolution is not None:
        ask_kw["media_resolution"] = variant.media_resolution
    views_out = await runner.ask_many(
        [([prompt, c], schemas.HouseView) for c in crops],
        **ask_kw,
    )

    centred = [
        bool(
            v and v.house_visible and v.box_2d and abs((v.box_2d[1] + v.box_2d[3]) / 2 - 500) < 250
        )
        for v in views_out
    ]
    truncated = [bool(v and v.house_visible and _box_truncated(v.box_2d)) for v in views_out]
    sky_contacts = []
    redaction_overlaps = []
    for c, v in zip(crops, views_out, strict=True):
        if v and v.house_visible and v.box_2d:
            box_px = schemas.box_2d_to_pixels(v.box_2d, w, h)
            x0, y0, x1, _ = box_px
            sky_contacts.append(cvc.sky_contact(c, [(x0, y0), (x1, y0)]))
            redaction_overlaps.append(views.redaction_overlap(c, box_px))
        else:
            sky_contacts.append(float("nan"))
            redaction_overlaps.append(0.0)

    res = ranked.iloc[valid_indices].assign(
        visible=[v.house_visible if v else None for v in views_out],
        occlusion=[v.occlusion.value if v else None for v in views_out],
        facade_fraction=[v.facade_visible_fraction if v else None for v in views_out],
        confidence=[v.confidence if v else None for v in views_out],
        centred=centred,
        truncated=truncated,
        sky_contact=sky_contacts,
        redaction_overlap=redaction_overlaps,
    )
    sightings = [
        views.HouseSighting(
            str(r.get("capture_id") or r.get("pano_id") or ""),
            r["camera_pose"],
            v_obj,
            schemas.box_2d_to_pixels(v.box_2d, w, h),
        )
        for r, v_obj, v, c in zip(cand_rows, view_objs, views_out, centred, strict=True)
        if c
    ]
    tri_kw: dict[str, Any] = {}
    if variant.uc1_facade_edge_triangulation:
        tri_kw["use_facade_edges"] = True
    location, status = views.triangulate_house(sightings, **tri_kw)

    def _val(x: Any) -> Any:
        return getattr(x, "value", x)

    ok_pairs = [
        (v, c_img)
        for v, c_img, is_c in zip(views_out, crops, centred, strict=True)
        if is_c and v is not None
    ]
    attrs: dict[str, tuple[Any, float]] = {}
    for k in ("stories", "exterior_material", "roof_type"):
        votes = [
            (_val(getattr(v, k)), _framing_weight(v, c_img, w, h, variant)) for v, c_img in ok_pairs
        ]
        fuse_kw: dict[str, Any] = {"ignore": {"UNKNOWN"}}
        if variant.uc1_min_agree_views > 1:
            fuse_kw["min_agree_views"] = variant.uc1_min_agree_views
        attrs[k] = ent.fuse_attribute(votes, **fuse_kw)

    return {
        "crops": crops,
        "views_out": views_out,
        "res": res,
        "sightings": sightings,
        "location": location,
        "status": status,
        "attrs": attrs,
        "black": black,
        "black_fraction_max": max(black) if black else float("nan"),
        "dark_pixel_max": max((images.dark_pixel_fraction(c) for c in crops), default=float("nan")),
        "redaction_overlap_max": max(redaction_overlaps, default=0.0),
    }


# --------------------------------------------------------------------------- UC2


def _filter_observations_uc2(
    run: pipeline.DetectionRun,
    variant: Variant,
) -> list[ent.Observation]:
    """Apply public-ROW class filter, per-class confidence thresholds, and OpenCV post/tree gates."""
    obs = [o for o in run.observations if o.cls in pipeline.PUBLIC_ROW_CLASSES]
    if variant.uc2_class_min_confidence:
        obs = [
            o
            for o in obs
            if o.confidence
            >= float(variant.uc2_class_min_confidence.get(o.cls, variant.uc2_min_confidence))
        ]
    if not variant.uc2_cv_post_gate:
        return obs
    img_by_view: dict[tuple[str, int], np.ndarray] = {}
    for rec in run.records:
        im = rec.get("image")
        spec = rec.get("spec")
        if im is not None and spec is not None:
            img_by_view[(spec.pano_id, int(spec.cam_k))] = im
    kept: list[ent.Observation] = []
    for o in obs:
        meta = o.ray.meta or {}
        box = meta.get("box")
        cam_k = meta.get("cam_k")
        im = img_by_view.get((o.pano_id, int(cam_k))) if cam_k is not None else None
        if im is None or box is None:
            kept.append(o)
            continue
        if o.cls in ("UTILITY_POLE", "STREET_LIGHT", "FIRE_HYDRANT"):
            sup = cvc.vertical_post_support(im, box)
            if sup < variant.uc2_cv_post_min_support:
                continue
        elif o.cls == "ROAD_SIGN":
            sup = max(cvc.vertical_post_support(im, box), cvc.sign_post_support(im, box))
            if sup < variant.uc2_cv_post_min_support:
                continue
        elif o.cls == "STREET_TREE":
            sup = cvc.street_tree_support(im, box)
            if sup < variant.uc2_cv_tree_min_support:
                continue
        kept.append(o)
    return kept


def _record_detections(rec: Mapping[str, Any]) -> list[schemas.Detection]:
    raw = rec.get("detections")
    if raw is None:
        return []
    if hasattr(raw, "detections"):
        return list(raw.detections or [])
    return list(raw)


def build_uc2_fewshot_parts(
    records: Sequence[Mapping[str, Any]],
    *,
    classes: Sequence[str] = pipeline.DETECT_CLASSES,
    thumb_size: tuple[int, int] = (512, 640),
) -> tuple[list[Any], dict[str, Any]]:
    """Construct a live multimodal visual few-shot prompt from OpenCV-verified reference crops.

    Selects:
    - Example 1: the view with the highest OpenCV `vertical_post_support` utility pole or road sign.
    - Example 2: a distinct view with the highest OpenCV `street_tree_support` roadside tree
      (disambiguating `STREET_TREE` with trunk-base ground contact from `UTILITY_POLE`).
    - Target query view: a third distinct view (or the next view with detections).
    """
    import cv2

    tw, th = int(thumb_size[0]), int(thumb_size[1])

    def _thumb(im: np.ndarray) -> np.ndarray:
        if im.shape[1] == tw and im.shape[0] == th:
            return im
        return cv2.resize(im, (tw, th), interpolation=cv2.INTER_AREA)

    best_pole_idx = 0
    best_pole_sup = -1.0
    best_tree_idx = -1
    best_tree_sup = -1.0

    for idx, rec in enumerate(records):
        im = rec.get("image")
        if im is None:
            continue
        h, w = im.shape[:2]
        for d in _record_detections(rec):
            box_px = schemas.box_2d_to_pixels(d.box_2d, w, h)
            lbl = d.label.value
            if lbl in ("UTILITY_POLE", "ROAD_SIGN", "STREET_LIGHT"):
                sup = cvc.vertical_post_support(im, box_px)
                if lbl == "ROAD_SIGN":
                    sup = max(sup, cvc.sign_post_support(im, box_px))
                if sup > best_pole_sup:
                    best_pole_sup = sup
                    best_pole_idx = idx
            elif lbl == "STREET_TREE":
                sup = cvc.street_tree_support(im, box_px)
                if sup > best_tree_sup and idx != best_pole_idx:
                    best_tree_sup = sup
                    best_tree_idx = idx

    if best_tree_idx < 0:
        for idx, rec in enumerate(records):
            if idx == best_pole_idx or rec.get("image") is None:
                continue
            if any(d.label.value == "STREET_TREE" for d in _record_detections(rec)):
                best_tree_idx = idx
                break
    if best_tree_idx < 0:
        best_tree_idx = 1 if len(records) > 1 and best_pole_idx == 0 else 0

    ex1_rec = records[best_pole_idx]
    ex1_dets = [
        d
        for d in _record_detections(ex1_rec)
        if d.label.value in ("UTILITY_POLE", "ROAD_SIGN", "STREET_LIGHT", "FIRE_HYDRANT")
    ]
    if not ex1_dets:
        ex1_dets = [
            schemas.Detection(
                label="UTILITY_POLE",
                box_2d=[140, 470, 860, 525],
                confidence=0.92,
                material="WOOD",
                condition="GOOD",
            )
        ]
    ex1_fd = schemas.FrameDetections(detections=ex1_dets[:3])

    ex2_rec = records[best_tree_idx]
    ex2_dets = [
        d for d in _record_detections(ex2_rec) if d.label.value in ("STREET_TREE", "UTILITY_POLE")
    ]
    if not any(d.label.value == "STREET_TREE" for d in ex2_dets):
        ex2_dets = [
            schemas.Detection(
                label="STREET_TREE",
                box_2d=[120, 320, 860, 620],
                confidence=0.90,
                material="WOOD",
                condition="GOOD",
            ),
            *ex2_dets[:1],
        ]
    ex2_fd = schemas.FrameDetections(detections=ex2_dets[:3])

    query_idx = next(
        (
            i
            for i, r in enumerate(records)
            if i not in (best_pole_idx, best_tree_idx)
            and r.get("image") is not None
            and _record_detections(r)
        ),
        next(
            (i for i in range(len(records)) if i not in (best_pole_idx, best_tree_idx)),
            best_pole_idx,
        ),
    )
    query_rec = records[query_idx]

    examples = [
        (
            _thumb(ex1_rec["image"]),
            ex1_fd,
            f"LSD-verified utility pole / road sign (vertical_post_support={max(0.0, best_pole_sup):.2f})",
        ),
        (
            _thumb(ex2_rec["image"]),
            ex2_fd,
            f"OpenCV-verified street tree with trunk-base ground contact (street_tree_support={max(0.0, best_tree_sup):.2f})",
        ),
    ]
    parts = pipeline.build_fewshot_prompt_parts(
        examples, _thumb(query_rec["image"]), classes=classes
    )
    meta = {
        "n_examples": len(examples),
        "pole_example_idx": best_pole_idx,
        "pole_support": float(max(0.0, best_pole_sup)),
        "tree_example_idx": best_tree_idx,
        "tree_support": float(max(0.0, best_tree_sup)),
        "query_idx": query_idx,
        "query_record": query_rec,
    }
    return parts, meta


def select_best_post_for_lean(
    records: Sequence[Mapping[str, Any]],
) -> tuple[np.ndarray, tuple[float, float, float, float], str, float]:
    """Select the clearest vertical pole/sign crop from `records` for `uc2_measure_post_lean`."""
    best_im: np.ndarray | None = None
    best_box: tuple[float, float, float, float] | None = None
    best_label = "UTILITY_POLE"
    best_score = -1.0
    best_sup = 0.0

    for rec in records:
        im = rec.get("image")
        if im is None:
            continue
        h, w = im.shape[:2]
        for d in _record_detections(rec):
            lbl = d.label.value
            if lbl not in ("UTILITY_POLE", "ROAD_SIGN", "STREET_LIGHT"):
                continue
            bx = schemas.box_2d_to_pixels(d.box_2d, w, h)
            bw = float(bx[2] - bx[0])
            bh = float(bx[3] - bx[1])
            if bh < 32.0 or bw < 4.0:
                continue
            sup = cvc.vertical_post_support(im, bx, max_tilt_deg=12.0)
            slender_bonus = 0.25 if bw <= 0.45 * bh else 0.0
            pole_bonus = 0.15 if lbl == "UTILITY_POLE" else 0.0
            score = sup + slender_bonus + pole_bonus + 0.05 * min(1.0, bh / 240.0)
            if score > best_score:
                best_score = score
                best_sup = float(sup)
                best_im = im
                best_box = (float(bx[0]), float(bx[1]), float(bx[2]), float(bx[3]))
                best_label = lbl

    if best_im is None or best_box is None:
        fallback_rec = next((r for r in records if r.get("image") is not None), records[0])
        best_im = fallback_rec["image"]
        h, w = best_im.shape[:2]
        best_box = (0.42 * w, 0.18 * h, 0.58 * w, 0.85 * h)
        best_sup = float(cvc.vertical_post_support(best_im, best_box, max_tilt_deg=12.0))
    return best_im, best_box, best_label, best_sup


async def uc2_run(
    sel_frames: pd.DataFrame,
    fetch: Callable[[str], bytes],
    runner: gc.GeminiRunner,
    intr: rosette.Intrinsics,
    ref: Sequence[float],
    *,
    classes: Sequence[str] = pipeline.DETECT_CLASSES,
    min_confidence: float | None = None,
    max_presence_checks: int = 10,
    variant: Variant = DEFAULT_VARIANT,
) -> dict[str, Any]:
    """Run UC2 detection, multi-view deduplication, and self-consistency check."""
    conf_floor = min_confidence if min_confidence is not None else variant.uc2_min_confidence
    det_kw: dict[str, Any] = {
        "classes": classes,
        "keep_images": True,
        "min_confidence": conf_floor,
        "antialias": variant.antialias,
    }
    if variant.yaw_delta_deg != 0.0:
        det_kw["yaw_delta_deg"] = variant.yaw_delta_deg
    if variant.hfov_scale != 1.0:
        det_kw["hfov_scale"] = variant.hfov_scale
    if variant.gemini_seed is not None:
        det_kw["seed"] = variant.gemini_seed
    if variant.thinking_level is not None:
        det_kw["thinking_level"] = variant.thinking_level
    if variant.media_resolution is not None:
        det_kw["media_resolution"] = variant.media_resolution
    run = await pipeline.detect_panos(sel_frames, fetch, runner, intr, ref, **det_kw)
    filtered_obs = _filter_observations_uc2(run, variant)
    cluster_kw: dict[str, Any] = {"merge_single_view": True}
    if variant.uc2_min_post_panos > 1:
        cluster_kw["min_post_panos"] = variant.uc2_min_post_panos
    if variant.uc2_house_facade_edges:
        cluster_kw["use_house_facade_edges"] = True
    from svi_geo import data, geo

    entities = ent.cluster(filtered_obs, ref, **cluster_kw)
    infill_recovered = 0
    if max_presence_checks > 0:
        entities, filtered_obs, infill_recovered = await infill_unlocated_poles(
            entities,
            filtered_obs,
            sel_frames,
            intr,
            fetch,
            runner,
            ref,
            min_post_panos=variant.uc2_min_post_panos,
            max_infill_calls=min(4, max_presence_checks),
            variant=variant,
        )
    located = ent.located_entities(entities)
    unlocated = [e for e in entities if e.method == "unlocated"]
    ent_df = ent.entities_to_dataframe(entities)
    sv_rows: list[dict[str, Any]] = []
    for o in filtered_obs:
        p_sv = ent._single_view_point(o, 2.5)
        if p_sv is not None:
            olat, olng, _ = geo.enu_to_lla(float(p_sv[0]), float(p_sv[1]), float(p_sv[2]), *ref)
            sv_rows.append(
                {
                    "obs_id": o.obs_id,
                    "pano_id": o.pano_id,
                    "class": o.cls,
                    "lat": float(olat),
                    "lng": float(olng),
                    "confidence": float(o.confidence),
                }
            )
    single_view_df = pd.DataFrame(
        sv_rows, columns=["obs_id", "pano_id", "class", "lat", "lng", "confidence"]
    )
    corridor_spans = sequence.audit_corridor_spans(data.panos_from_frames(sel_frames), located)
    trees = ent_df[ent_df["class"] == "STREET_TREE"]
    trees_located = int((trees.method != "unlocated").sum())
    trees_unlocated = int((trees.method == "unlocated").sum())
    posts = ent_df[ent_df["class"].isin(list(ent.POST_GROUP))]
    posts_located = int((posts.method != "unlocated").sum())
    posts_unlocated = int((posts.method == "unlocated").sum())
    houses = ent_df[ent_df["class"] == "HOUSE"]
    houses_located = int((houses.method != "unlocated").sum())
    houses_unlocated = int((houses.method == "unlocated").sum())

    sc = None
    if max_presence_checks > 0 and located:
        render = pipeline.task_renderer(sel_frames, fetch, intr)
        sc = await ev.self_consistency(
            located, sel_frames, intr, ref, render, runner, max_tasks=max_presence_checks
        )

    det_black = max((r["black_fraction"] for r in run.records), default=float("nan"))
    det_dark = max(
        (images.dark_pixel_fraction(r["image"]) for r in run.records if r.get("image") is not None),
        default=float("nan"),
    )
    det_redaction = max(
        (float(r.get("redaction_overlap_max", 0.0)) for r in run.records),
        default=0.0,
    )
    return {
        "run": run,
        "observations": filtered_obs,
        "entities": entities,
        "located": located,
        "unlocated": unlocated,
        "ent_df": ent_df,
        "single_view_df": single_view_df,
        "corridor_spans": corridor_spans,
        "infill_recovered": infill_recovered,
        "trees_located": trees_located,
        "trees_unlocated": trees_unlocated,
        "posts_located": posts_located,
        "posts_unlocated": posts_unlocated,
        "houses_located": houses_located,
        "houses_unlocated": houses_unlocated,
        "self_consistency": sc,
        "det_black": det_black,
        "det_dark": det_dark,
        "black_fraction_max": det_black,
        "dark_pixel_max": det_dark,
        "redaction_overlap_max": det_redaction,
    }


async def infill_unlocated_poles(
    entities: Sequence[ent.Entity],
    observations: Sequence[ent.Observation],
    frames: pd.DataFrame,
    intr: rosette.Intrinsics,
    fetch: Callable[[str], bytes],
    runner: gc.GeminiRunner,
    ref_lla: tuple[float, float, float],
    *,
    min_post_panos: int = 2,
    max_infill_calls: int = 4,
    cam_height_m: float = 2.5,
    seed: int = 0,
    variant: Variant = BASELINE_VARIANT,
) -> tuple[list[ent.Entity], list[ent.Observation], int]:
    """Targeted 40-deg zoom infill (`PresenceCheck`) from adjacent rosettes (`K-1` / `K+1`)
    for single-view `UTILITY_POLE` candidates held in `unlocated` due to `min_post_panos >= 2`."""
    import math

    from svi_geo import data
    from svi_geo import triangulate as tri

    if max_infill_calls <= 0:
        return list(entities), list(observations), 0

    frames_norm = data.ensure_capture_id(frames)
    obs_by_id = {o.obs_id: o for o in observations}
    unloc_poles = [
        e for e in entities if e.method == "unlocated" and e.cls == "UTILITY_POLE" and e.obs_ids
    ]
    if not unloc_poles:
        return list(entities), list(observations), 0

    # Order rosettes along sequence
    pano_order = (
        frames_norm[["capture_id", "seq_idx"]]
        .drop_duplicates("capture_id")
        .sort_values("seq_idx")
        .reset_index(drop=True)
        if "seq_idx" in frames_norm.columns
        else frames_norm[["capture_id"]].drop_duplicates("capture_id").reset_index(drop=True)
    )
    cid_list = [str(c) for c in pano_order["capture_id"].tolist()]
    cid_to_pos = {cid: idx for idx, cid in enumerate(cid_list)}

    new_obs: list[ent.Observation] = []
    calls_made = 0
    for e in unloc_poles:
        if calls_made >= max_infill_calls:
            break
        o0 = obs_by_id.get(e.obs_ids[0])
        if o0 is None:
            continue
        r_sv = ent._single_view_range(o0, cam_height_m)
        if r_sv is None:
            continue
        p_sv = tri.point_from_range(o0.ray, min(float(r_sv), 28.0))
        pos = cid_to_pos.get(str(o0.pano_id))
        if pos is None:
            continue
        adj_cids = [cid_list[p] for p in (pos - 1, pos + 1) if 0 <= p < len(cid_list)]
        if not adj_cids:
            continue

        # Rank candidate adjacent rosettes by predicted parallax angle to o0 (require >= 6 deg and range <= 50 m)
        candidates: list[tuple[float, str, Any, np.ndarray, float]] = []
        for acid in adj_cids:
            sub = frames_norm[frames_norm["capture_id"].astype(str) == acid]
            ground_rows = [
                r for r in sub.to_dict("records") if rosette.is_ground_camera(int(r["cam_k"]))
            ]
            if not ground_rows:
                continue
            origin_adj = rosette.camera_center_enu(ground_rows[0]["camera_pose"], ref_lla)
            v = p_sv - origin_adj
            horiz_d = float(math.hypot(v[0], v[1]))
            if horiz_d < 2.0 or horiz_d > 50.0:
                continue
            az_pred = float(math.degrees(math.atan2(v[0], v[1])) % 360.0)
            dir_adj = np.array([math.sin(math.radians(az_pred)), math.cos(math.radians(az_pred))])
            dot_par = float(np.clip(np.dot(o0.ray.dir2d, dir_adj), -1.0, 1.0))
            pred_parallax_deg = float(math.degrees(math.acos(dot_par)))
            if pred_parallax_deg < 6.0:
                continue
            choice = rosette.best_camera_for_view(
                ground_rows, intr, az_pred, 0.0, 1.0, min_hfov=25.0, max_black=0.05, hfov_cap=40.0
            )
            if choice is not None:
                candidates.append((pred_parallax_deg, acid, choice, origin_adj, az_pred))

        candidates.sort(key=lambda item: -item[0])
        if not candidates:
            continue

        w, h = 512, 512
        scale = images.decode_scale_for_view(w, 40.0)
        for _pred_par, acid, choice, origin_adj, az_pred in candidates:
            if calls_made >= max_infill_calls:
                break
            view = rosette.PerspectiveView(az_pred, 0.0, 40.0, w, h)
            try:
                raw_im = images.decode(fetch(choice.row["gcs_uri"]), scale=scale)
                crop = rosette.render_perspective(
                    raw_im,
                    intr,
                    choice.row["camera_pose"],
                    view,
                    int(choice.cam_k),
                    antialias=True,
                    mask_hood=True,
                )
            except Exception:
                continue

            calls_made += 1
            chk = await runner.ask(
                [
                    "Is a vertical utility pole (wooden timber pole, or concrete/metal pole "
                    "supporting overhead wires, crossarms, insulators, transformers, risers, or "
                    "street-light mast arm) visible near the horizontal centre of this targeted "
                    "40-deg zoom view? If present, return present=true and box_2d tightly around "
                    "the vertical pole shaft down to ground contact.",
                    crop,
                ],
                schemas.PresenceCheck,
                seed=seed,
            )
            if (
                chk is None
                or not chk.present
                or float(chk.confidence) < 0.55
                or chk.box_2d is None
                or len(chk.box_2d) != 4
            ):
                continue

            x0, y0, x1, y1 = schemas.box_2d_to_pixels(chk.box_2d, w, h)
            box_px = (float(x0), float(y0), float(x1), float(y1))
            if (
                variant.uc2_cv_post_gate
                and cvc.vertical_post_support(crop, box_px) < variant.uc2_cv_post_min_support
            ):
                continue

            u_c = 0.5 * (x0 + x1)
            az_obs, el_center = view.pixel_to_bearing(u_c, 0.5 * (y0 + y1))
            _, el_bot = view.pixel_to_bearing(u_c, min(float(h - 1), float(y1)))

            new_obs.append(
                ent.Observation(
                    obs_id=f"infill_{acid}_{len(new_obs)}",
                    pano_id=str(acid),
                    cls="UTILITY_POLE",
                    ray=tri.Ray(
                        origin_adj,
                        float(az_obs),
                        float(el_center),
                        meta={"cam_k": int(choice.cam_k), "box": box_px, "infill": True},
                    ),
                    confidence=float(chk.confidence),
                    el_bottom_deg=float(el_bot),
                    attrs=dict(o0.attrs),
                )
            )
            break

    if not new_obs:
        return list(entities), list(observations), 0

    all_obs = [*observations, *new_obs]
    reclustered = ent.cluster(
        all_obs,
        ref_lla,
        merge_single_view=True,
        min_post_panos=min_post_panos,
        use_house_facade_edges=variant.uc2_house_facade_edges,
    )
    return reclustered, all_obs, len(new_obs)



# --------------------------------------------------------------------------- UC3


async def uc3_run(
    sel: pd.DataFrame,
    sel_frames: pd.DataFrame,
    fetch: Callable[[str], bytes],
    runner: gc.GeminiRunner,
    intr: rosette.Intrinsics,
    *,
    road_view_pitch: float = -22.0,
    max_gap_m: float = 35.0,
    sidewalk_offset_m: float = 6.0,
    variant: Variant = DEFAULT_VARIANT,
) -> dict[str, Any]:
    """Render front/left/right road views, query `WindowLabel`, smooth with Viterbi, and emit segments."""
    from svi_geo import data

    sel = data.ensure_capture_id(sel).reset_index(drop=True)
    sel_frames = data.ensure_capture_id(sel_frames)
    views_by_pano: dict[str, dict[str, np.ndarray]] = {}
    rv_by_pano: dict[str, dict[str, sequence.RoadView]] = {}
    black: list[float] = []
    zero: list[float] = []
    redactions: list[float] = []
    for p in sel.itertuples():
        cid = str(getattr(p, "capture_id", None) or getattr(p, "pano_id", ""))
        rows = sel_frames[sel_frames.capture_id == cid].to_dict("records")
        out_v: dict[str, np.ndarray] = {}
        out_rv: dict[str, sequence.RoadView] = {}
        travel = (float(p.travel_deg) + variant.yaw_delta_deg) % 360.0
        for role in ("front", "left", "right"):
            rv = sequence.road_view(
                rows,
                intr,
                travel,
                role,
                pitch_deg=road_view_pitch,
                size=variant.uc3_road_view_size,
            )
            if rv is None:
                continue
            scale = images.decode_scale_for_view(rv.view.width, rv.view.hfov_deg)
            try:
                imgs = {
                    int(r["cam_k"]): images.decode(fetch(r["gcs_uri"]), scale=scale)
                    for r in rv.rows
                }
            except Exception:
                continue
            black.append(rv.black_sent)
            rendered = sequence.render_road_view(imgs, intr, rv)
            out_v[role] = rendered
            out_rv[role] = rv
            zero.append(images.dark_pixel_fraction(rendered))
            redactions.append(
                views.redaction_overlap(rendered, (0, 0, rendered.shape[1], rendered.shape[0]))
            )
        views_by_pano[cid] = out_v
        rv_by_pano[cid] = out_rv
        if getattr(p, "pano_id", None) and str(p.pano_id) != cid:
            views_by_pano[str(p.pano_id)] = out_v
            rv_by_pano[str(p.pano_id)] = out_rv

    prompt = UC3_PROMPT_V1 if variant.uc3_prompt_version == "v1" else UC3_PROMPT_V0
    breaks = smoothing.gap_breaks(sel.lat, sel.lng, max_gap_m)
    cids = [str(c) for c in sel["capture_id"].tolist()]

    def window_request(i: int):
        c = views_by_pano[cids[i]]
        items: list[Any] = [prompt]
        use_neighbours = variant.uc3_window_size >= 3
        if use_neighbours and i > 0 and not breaks[i] and "front" in views_by_pano[cids[i - 1]]:
            items += ["PREVIOUS front:", views_by_pano[cids[i - 1]]["front"]]
        for role in ("front", "left", "right"):
            if role in c:
                items += [f"CENTRE {role}:", c[role]]
        if (
            use_neighbours
            and i + 1 < len(sel)
            and not breaks[i + 1]
            and "front" in views_by_pano[cids[i + 1]]
        ):
            items += ["NEXT front:", views_by_pano[cids[i + 1]]["front"]]
        return items, schemas.WindowLabel

    ask_kw: dict[str, Any] = {}
    if variant.gemini_seed is not None:
        ask_kw["seed"] = variant.gemini_seed
    if variant.thinking_level is not None:
        ask_kw["thinking_level"] = variant.thinking_level
    if variant.media_resolution is not None:
        ask_kw["media_resolution"] = variant.media_resolution
    labels = await runner.ask_many([window_request(i) for i in range(len(sel))], **ask_kw)

    length_m = smoothing.drive_length_m(sel.lat, sel.lng, max_gap_m)
    slot_rows = []
    raw_by_slot: dict[str, list[Any]] = {}
    smooth_by_slot: dict[str, list[Any]] = {}
    for asset, side in (("ROAD", "CENTER"), ("SIDEWALK", "LEFT"), ("SIDEWALK", "RIGHT")):
        raw, conf = zip(*(smoothing.pick_slot(wl, asset, side) for wl in labels), strict=True)
        raw, conf = list(raw), list(conf)
        if variant.uc3_kerb_sidewalk_prior and asset == "SIDEWALK":
            for idx_p, cid in enumerate(cids):
                role_key = "left" if side == "LEFT" else "right"
                im = views_by_pano.get(cid, {}).get(role_key)
                rv = rv_by_pano.get(cid, {}).get(role_key)
                if im is not None and rv is not None and raw[idx_p] is not None:
                    full_h = np.zeros((rv.view.height, rv.view.width, 3), dtype=np.uint8)
                    top = max(0, rv.view.height - im.shape[0])
                    full_h[top : top + im.shape[0], : im.shape[1]] = im
                    ke = cvc.kerb_evidence(full_h, rv.view, side=side)
                    if not ke["present"] and raw[idx_p] != smoothing.ABSENT and conf[idx_p] < 0.85:
                        conf[idx_p] = max(0.35, conf[idx_p] * 0.65)
        smooth = smoothing.viterbi(
            raw,
            conf,
            stay_prob=variant.uc3_stay_prob,
            absent_label=smoothing.ABSENT,
            breaks=breaks,
        )
        raw_by_slot[side] = raw
        smooth_by_slot[side] = smooth
        segs = smoothing.segments_from_sequence(
            sel.lat,
            sel.lng,
            smooth,
            offset_m=smoothing.side_offset_m(side, sidewalk_offset_m),
            breaks=breaks,
        )
        answered = [i for i, x in enumerate(raw) if x is not None]
        changed = sum(raw[i] != smooth[i] for i in answered)
        slot_rows.append(
            {
                "asset": asset,
                "side": side,
                "n_answered": len(answered),
                "changed_by_smoothing": changed,
                "raw_smoothed_agreement": 1 - changed / len(answered) if answered else float("nan"),
                "absent_share": (
                    sum(smooth[i] == smoothing.ABSENT for i in answered) / len(answered)
                    if answered
                    else float("nan")
                ),
                "n_segments": len(segs),
                "segment_m": sum(s_["length_m"] for s_ in segs),
                "segments": segs,
            }
        )
    summary = pd.DataFrame([{k: v for k, v in r.items() if k != "segments"} for r in slot_rows])
    return {
        "views": views_by_pano,
        "road_views": rv_by_pano,
        "labels": labels,
        "breaks": breaks,
        "length_m": length_m,
        "rows": slot_rows,
        "raw_by_slot": raw_by_slot,
        "smooth_by_slot": smooth_by_slot,
        "summary": summary,
        "n_segments": int(summary.n_segments.sum()),
        "black": black,
        "zero": zero,
        "black_fraction_max": max(black) if black else float("nan"),
        "dark_pixel_max": max(zero) if zero else float("nan"),
        "redaction_overlap_max": max(redactions, default=0.0),
        "prompt_version": f"uc3_{variant.uc3_prompt_version}",
    }


# --------------------------------------------------------------------------- UC4


def uc4_select_views(
    frames: pd.DataFrame,
    lat: float,
    lng: float,
    fetch: Callable[[str], bytes],
    intr: rosette.Intrinsics,
    *,
    n_views: int = 3,
    n_candidates: int | None = None,
    width: int | None = None,
    height: int | None = None,
    max_dist_m: float = 60.0,
    variant: Variant = DEFAULT_VARIANT,
) -> tuple[pd.DataFrame, list[dict[str, Any]], list[dict[str, Any]]]:
    """Rank candidate roof views, render each, and apply the occlusion screen."""
    w = int(width) if width is not None else int(variant.uc4_view_size[0])
    h = int(height) if height is not None else int(variant.uc4_view_size[1])
    cand_cap = n_candidates if n_candidates is not None else 2 * n_views
    roof_views = views.rank_roof_views(
        frames, lat, lng, intr, n=cand_cap, aspect=w / h, max_dist_m=max_dist_m
    )
    chosen: list[dict[str, Any]] = []
    screen_records: list[dict[str, Any]] = []
    for row in roof_views.to_dict("records"):
        bearing = (float(row["bearing"]) + variant.yaw_delta_deg) % 360.0
        hfov = float(row["hfov"]) * variant.hfov_scale
        scale = images.decode_scale_for_view(w, hfov)
        try:
            img_raw = images.decode(fetch(row["gcs_uri"]), scale=scale)
        except Exception:
            continue
        img, view, black = roof.render_roof_view(
            img_raw,
            intr,
            row["camera_pose"],
            bearing,
            int(row["cam_k"]),
            pitch_deg=float(row["pitch"]),
            hfov_deg=hfov,
            width=w,
            height=h,
        )
        if variant.uc4_clahe:
            img = images.clahe_lab(img)
        rbox = views.roof_box(row, view)
        scr_kw: dict[str, Any] = {}
        if variant.uc4_sky_contact_min > 0.0:
            scr_kw["min_sky_contact"] = variant.uc4_sky_contact_min
        screen = views.occlusion_screen(img, rbox, **scr_kw)
        rec = {**row, "image": img, "view": view, "black": black, "screen": screen}
        screen_records.append(rec)
        if not screen["rejected"] and len(chosen) < n_views:
            chosen.append(rec)
    return roof_views, chosen, screen_records


async def uc4_run(
    chosen: Sequence[Mapping[str, Any]],
    runner: gc.GeminiRunner,
    *,
    width: int | None = None,
    height: int | None = None,
    variant: Variant = DEFAULT_VARIANT,
) -> dict[str, Any]:
    """Query Gemini for `RoofEdges` on `chosen` views and validate/snap against image evidence."""
    w = (
        int(width)
        if width is not None
        else (int(chosen[0]["image"].shape[1]) if chosen else int(variant.uc4_view_size[0]))
    )
    h = (
        int(height)
        if height is not None
        else (int(chosen[0]["image"].shape[0]) if chosen else int(variant.uc4_view_size[1]))
    )
    ask_kw: dict[str, Any] = {
        "validator": lambda r: r.validate_in_image(w, h),
    }
    if variant.gemini_seed is not None:
        ask_kw["seed"] = variant.gemini_seed
    if variant.thinking_level is not None:
        ask_kw["thinking_level"] = variant.thinking_level
    if variant.media_resolution is not None:
        ask_kw["media_resolution"] = variant.media_resolution
    roofs = await runner.ask_many(
        [([UC4_PROMPT_V0, c["image"]], schemas.RoofEdges) for c in chosen],
        **ask_kw,
    )

    def to_pixels(edge):
        return edge.edge_type.value, [(x / 1000 * w, y / 1000 * h) for y, x in edge.points]

    results = []
    decoy_rates = []
    redactions = []
    for c, rf in zip(chosen, roofs, strict=True):
        proposed = [to_pixels(e) for e in (rf.edges if rf else [])]
        valid_mask = c["image"].max(axis=2) > 0
        horizon = roof.horizon_row_for(c["view"])
        rbox = views.roof_box(c, c["view"])
        wbox = views.wall_box(c, c["view"])
        redactions.append(views.redaction_overlap(c["image"], rbox))
        val_kw: dict[str, Any] = {}
        if variant.uc4_validator_gates:
            val_kw["roof_box"] = rbox
            val_kw["wall_box"] = wbox
            val_kw["min_sky_contact"] = variant.uc4_validator_sky_min
        res = roof.validate_roof_edges(
            c["image"],
            proposed,
            valid_mask=valid_mask,
            horizon_row=horizon,
            baseline_region=rbox,
            **val_kw,
        )
        named = views.roof_decoys(c, c["view"])
        named["wall_lines"] = roof.straight_lines_in(c["image"], wbox)
        decoys = roof.decoy_acceptance(
            c["image"],
            named,
            valid_mask,
            horizon_row=horizon,
            **val_kw,
        )
        results.append(res)
        decoy_rates.append(decoys)

    return {
        "roofs": roofs,
        "results": results,
        "decoy_rates": decoy_rates,
        "accepted_edges": sum(len(r.valid_edges) for r in results),
        "black_fraction_max": max((float(c["black"]) for c in chosen), default=float("nan")),
        "dark_pixel_max": max(
            (images.dark_pixel_fraction(c["image"]) for c in chosen), default=float("nan")
        ),
        "redaction_overlap_max": max(redactions, default=0.0),
    }


# --------------------------------------------------- Agentic-vision cells (U11)

MEASURE_STDOUT_PATTERN = r"MEASURE:\s*\{"

UC4_AGENTIC_PROMPT = (
    "You MUST use Python code execution with OpenCV/NumPy in a single concise script on the input "
    "roof image to detect straight line segments in the upper roof region (rows 0.15*H..0.60*H, "
    "length >= 20 px), compute the dominant near-horizontal eave angle in degrees in [-45, 45] "
    "(0 = horizontal), optional rake angle in degrees, LSD overlap fraction in [0, 1], and segment "
    "count. Do NOT call plt.show(), plt.savefig(), or save/display any images in code execution. "
    "You MUST print a line starting with `MEASURE: {...}` containing JSON with keys "
    "`eave_angle_deg` and `lsd_overlap_fraction`, then return the final JSON matching the schema."
)

UC1_AGENTIC_PROMPT = (
    "You MUST use Python code execution with OpenCV/NumPy in a single concise script on the house "
    "facade image to compute the horizontal Sobel-y gradient row profile, count prominent "
    "window/storey bands, and estimate the number of building stories (1..4). Do NOT call "
    "plt.show(), plt.savefig(), or save/display any images in code execution. You MUST print a "
    "line starting with `MEASURE: {...}` containing JSON with keys `window_rows` and "
    "`estimated_stories`, then return the final JSON matching the schema."
)

UC2_AGENTIC_PROMPT = (
    "You MUST use Python code execution with OpenCV/NumPy in a single concise script on the "
    "utility-pole / sign-post crop to detect near-vertical line segments and measure the dominant "
    "pole lean angle in degrees from vertical in [-45, 45] (0 = perfectly vertical) and vertical "
    "support fraction in [0, 1]. Specifically, convert the image to grayscale, run "
    "`raw = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD).detect(gray)[0]`, and for each "
    "segment `(ax, ay, bx, by)` compute `dx = bx - ax; dy = by - ay` (flipping `dx, dy = -dx, -dy` "
    "if `dy < 0`). Keep segments with `dy >= 6.0` and `abs(math.degrees(math.atan2(dx, dy))) <= 15.0`, "
    "compute `lean_angle_deg` as the length-weighted median of `math.degrees(math.atan2(dx, dy))` "
    "(or `0.0` if none), and `vertical_support` as the fraction of image height covered by those "
    "vertical segments in [0, 1]. Do NOT call plt.show(), plt.savefig(), or save/display any images "
    "in code execution. You MUST print a line starting with `MEASURE: {...}` containing JSON with "
    "keys `lean_angle_deg` and `vertical_support`, then return the final JSON matching the schema."
)

UC3_AGENTIC_PROMPT = (
    "You MUST use Python code execution with OpenCV/NumPy in a single concise script on the road "
    "surface crop to compute the mean grayscale luminance (`mean_luma = float(np.mean(gray))` in "
    "0..255), mean Sobel gradient magnitude (`grad_mean = float(np.mean(np.hypot("
    "cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3))))`), "
    "and row index (`change_row_norm` in 0..1000 or null) of the strongest vertical texture change. "
    "Do NOT call plt.show(), plt.savefig(), or save/display any images in code execution. "
    "You MUST print a line starting with `MEASURE: {...}` containing JSON with keys "
    "`mean_luma` and `grad_mean`, then return the final JSON matching the schema."
)


def _local_eave_angle_and_overlay(
    image: np.ndarray, roof_box: Sequence[float] | None = None
) -> tuple[float, np.ndarray]:
    import math

    import cv2

    h, w = image.shape[:2]
    if roof_box is not None and len(roof_box) == 4:
        x0, y0, x1, y1 = (float(v) for v in roof_box)
    else:
        x0, y0, x1, y1 = 0.05 * w, 0.12 * h, 0.95 * w, 0.60 * h
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    det = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD)
    raw = det.detect(gray)[0]
    segs = np.zeros((0, 4), dtype=float) if raw is None else raw.reshape(-1, 4).astype(float)

    overlay = image.copy() if image.ndim == 3 else cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    pts_for_fit: list[tuple[float, float]] = []
    angles: list[float] = []
    weights: list[float] = []
    for ax, ay, bx, by in segs:
        mx, my = 0.5 * (ax + bx), 0.5 * (ay + by)
        if not (x0 <= mx <= x1 and y0 <= my <= y1):
            continue
        length = math.hypot(bx - ax, by - ay)
        if length < 20.0:
            continue
        dx, dy = (bx - ax, by - ay) if bx >= ax else (ax - bx, ay - by)
        ang = math.degrees(math.atan2(dy, max(1e-6, dx)))
        if abs(ang) <= 35.0:
            angles.append(ang)
            weights.append(length)
            pts_for_fit.extend([(ax, ay), (bx, by)])
            cv2.line(
                overlay,
                (int(round(ax)), int(round(ay))),
                (int(round(bx)), int(round(by))),
                (46, 160, 67),
                2,
            )

    if len(pts_for_fit) >= 4:
        arr = np.asarray(pts_for_fit, dtype=np.float32)
        vx, vy, cx, cy = cv2.fitLine(arr, cv2.DIST_HUBER, 0, 0.01, 0.01)
        vx_f, vy_f = float(vx[0]), float(vy[0])
        if vx_f < 0:
            vx_f, vy_f = -vx_f, -vy_f
        local_deg = float(math.degrees(math.atan2(vy_f, max(1e-6, vx_f))))
        if angles:
            # Anchor to length-weighted median angle when multiple heights shift a single line fit
            order = np.argsort(angles)
            cum = np.cumsum(np.asarray(weights)[order])
            med_deg = float(np.asarray(angles)[order][np.searchsorted(cum, 0.5 * cum[-1])])
            if abs(local_deg - med_deg) > 2.0:
                local_deg = med_deg
        c_x, c_y = float(cx[0]), float(cy[0])
        rad = math.radians(local_deg)
        p1 = (int(round(c_x - 120 * math.cos(rad))), int(round(c_y - 120 * math.sin(rad))))
        p2 = (int(round(c_x + 120 * math.cos(rad))), int(round(c_y + 120 * math.sin(rad))))
        cv2.line(overlay, p1, p2, (11, 87, 208), 2)
    else:
        local_deg = 0.0
    return local_deg, overlay


async def uc4_measure_roof_angles(
    image: np.ndarray,
    runner: gc.GeminiRunner,
    *,
    roof_box: Sequence[float] | None = None,
    tol_deg: float = 4.0,
    seed: int | None = 0,
    code_execution: bool = True,
    thinking_level: str = "MEDIUM",
    media_resolution: str = "HIGH",
    validator: Any = None,
    expect_stdout: str = MEASURE_STDOUT_PATTERN,
) -> dict[str, Any]:
    """Run one validated code-execution call on a roof crop and cross-check eave angle locally."""
    h, w = image.shape[:2]
    val_fn = validator if validator is not None else (lambda r: None)
    reply, trace = await runner.ask(
        [UC4_AGENTIC_PROMPT, image],
        schemas.RoofAngleMeasurement,
        code_execution=code_execution,
        thinking_level=thinking_level,
        media_resolution=media_resolution,
        expect_stdout=expect_stdout,
        validator=val_fn,
        seed=seed,
        return_trace=True,
    )
    gc.check_code_exec_trace(trace, expect_stdout=expect_stdout, sent_image_shape=(h, w))
    local_deg, overlay = _local_eave_angle_and_overlay(image, roof_box=roof_box)
    delta = (
        abs(float(reply.eave_angle_deg) - float(local_deg)) if reply is not None else float("inf")
    )
    agree = bool(delta <= float(tol_deg))
    status = "agree" if agree else "disagree"
    return {
        "measurement": reply,
        "trace": trace,
        "local_eave_angle_deg": local_deg,
        "delta_deg": delta,
        "agree": agree,
        "agreement_line": f"code_exec_agreement={status}(eave_delta_deg={delta:.2f},tol={tol_deg:.1f})",
        "overlay": overlay,
    }


async def uc1_count_storeys(
    image: np.ndarray,
    runner: gc.GeminiRunner,
    *,
    box_2d: Sequence[int] | None = None,
    fused_stories: int | None = None,
    tol_rows: int = 1,
    seed: int | None = 0,
    code_execution: bool = True,
    thinking_level: str = "MEDIUM",
    media_resolution: str = "HIGH",
    validator: Any = None,
    expect_stdout: str = MEASURE_STDOUT_PATTERN,
) -> dict[str, Any]:
    """Run one validated code-execution call on the best house crop and cross-check storey count."""
    import cv2

    h, w = image.shape[:2]
    crop = image
    if box_2d is not None and len(box_2d) == 4:
        x0, y0, x1, y1 = (int(round(v)) for v in schemas.box_2d_to_pixels(box_2d, w, h))
        x0, x1 = max(0, min(x0, w - 1)), max(1, min(x1, w))
        y0, y1 = max(0, min(y0, h - 1)), max(1, min(y1, h))
        if x1 - x0 >= 16 and y1 - y0 >= 16:
            crop = image[y0:y1, x0:x1]
    ch, cw = crop.shape[:2]
    val_fn = validator if validator is not None else (lambda r: None)
    reply, trace = await runner.ask(
        [UC1_AGENTIC_PROMPT, crop],
        schemas.StoreyRowMeasurement,
        code_execution=code_execution,
        thinking_level=thinking_level,
        media_resolution=media_resolution,
        expect_stdout=expect_stdout,
        validator=val_fn,
        seed=seed,
        return_trace=True,
    )
    gc.check_code_exec_trace(trace, expect_stdout=expect_stdout, sent_image_shape=(ch, cw))

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    gy = np.abs(cv2.Sobel(gray.astype(np.float32), cv2.CV_32F, 0, 1, ksize=3))
    prof = gy.mean(axis=1)
    k = max(3, ch // 15)
    smooth = np.convolve(prof, np.ones(k) / k, mode="same")
    thresh = float(np.percentile(smooth, 65.0))
    min_sep = max(4, int(0.18 * ch))
    peaks: list[int] = []
    for r_idx in range(min_sep // 2, ch - min_sep // 2):
        if smooth[r_idx] >= thresh and smooth[r_idx] == np.max(
            smooth[max(0, r_idx - min_sep // 2) : min(ch, r_idx + min_sep // 2 + 1)]
        ):
            if not peaks or r_idx - peaks[-1] >= min_sep:
                peaks.append(r_idx)
    sobel_stories = int(np.clip(len(peaks), 1, 4))
    ref_stories = int(fused_stories) if fused_stories is not None else sobel_stories
    est = int(reply.estimated_stories) if reply is not None else 0
    delta = abs(est - sobel_stories)
    fused_delta = abs(est - ref_stories)
    agree = bool(delta <= int(tol_rows))
    status = "agree" if agree else "disagree"

    overlay = crop.copy() if crop.ndim == 3 else cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR)
    for yn in reply.row_y_centres_norm if reply else []:
        ry = int(round(yn / 1000.0 * ch))
        cv2.line(overlay, (0, ry), (cw - 1, ry), (11, 87, 208), 2)
    return {
        "measurement": reply,
        "trace": trace,
        "local_stories": sobel_stories,
        "sobel_peaks": sobel_stories,
        "fused_stories": ref_stories,
        "fused_stories_delta": fused_delta,
        "delta_rows": delta,
        "agree": agree,
        "agreement_line": f"code_exec_agreement={status}(stories_delta={delta},tol={tol_rows})",
        "overlay": overlay,
    }


async def uc2_measure_post_lean(
    image: np.ndarray,
    runner: gc.GeminiRunner,
    *,
    box_px: Sequence[float] | None = None,
    tol_deg: float = 3.0,
    seed: int | None = 0,
    code_execution: bool = True,
    thinking_level: str = "MEDIUM",
    media_resolution: str = "HIGH",
    validator: Any = None,
    expect_stdout: str = MEASURE_STDOUT_PATTERN,
) -> dict[str, Any]:
    """Run one validated code-execution call on a located pole/sign crop and cross-check lean angle."""
    import math

    import cv2

    h, w = image.shape[:2]
    if box_px is None or len(box_px) != 4:
        box_px = (0.35 * w, 0.15 * h, 0.65 * w, 0.85 * h)
    x0, y0, x1, y1 = (float(v) for v in box_px)
    ix0 = max(0, int(round(min(x0, x1))) - 12)
    ix1 = min(w, int(round(max(x0, x1))) + 12)
    iy0 = max(0, int(round(min(y0, y1))) - 8)
    iy1 = min(h, int(round(max(y0, y1))) + 8)
    crop = image[iy0:iy1, ix0:ix1] if (ix1 - ix0 >= 8 and iy1 - iy0 >= 8) else image
    ch, cw = crop.shape[:2]
    val_fn = validator if validator is not None else (lambda r: None)

    reply, trace = await runner.ask(
        [UC2_AGENTIC_PROMPT, crop],
        schemas.PostLeanMeasurement,
        code_execution=code_execution,
        thinking_level=thinking_level,
        media_resolution=media_resolution,
        expect_stdout=expect_stdout,
        validator=val_fn,
        seed=seed,
        return_trace=True,
    )
    gc.check_code_exec_trace(trace, expect_stdout=expect_stdout, sent_image_shape=(ch, cw))

    local_sup = cvc.vertical_post_support(image, box_px, max_tilt_deg=12.0)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    raw = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD).detect(gray)[0]
    segs = np.zeros((0, 4), dtype=float) if raw is None else raw.reshape(-1, 4).astype(float)
    leans: list[float] = []
    weights: list[float] = []
    overlay = crop.copy() if crop.ndim == 3 else cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR)
    for ax, ay, bx, by in segs:
        dx = bx - ax
        dy = by - ay
        if dy < 0:
            dx, dy = -dx, -dy
        if dy < 6.0:
            continue
        lean = math.degrees(math.atan2(dx, dy))
        if abs(lean) <= 15.0:
            leans.append(lean)
            weights.append(math.hypot(dx, dy))
            cv2.line(
                overlay,
                (int(round(ax)), int(round(ay))),
                (int(round(bx)), int(round(by))),
                (46, 160, 67),
                2,
            )
    if leans:
        order = np.argsort(leans)
        cum = np.cumsum(np.asarray(weights)[order])
        local_lean = float(np.asarray(leans)[order][np.searchsorted(cum, 0.5 * cum[-1])])
    else:
        local_lean = 0.0
    delta = abs(float(reply.lean_angle_deg) - local_lean) if reply is not None else float("inf")
    agree = bool(delta <= float(tol_deg))
    status = "agree" if agree else "disagree"
    return {
        "measurement": reply,
        "trace": trace,
        "local_lean_angle_deg": local_lean,
        "local_vertical_support": local_sup,
        "delta_deg": delta,
        "agree": agree,
        "agreement_line": f"code_exec_agreement={status}(lean_delta_deg={delta:.2f},tol={tol_deg:.1f})",
        "overlay": overlay,
    }


async def uc3_locate_material_boundary(
    image: np.ndarray,
    runner: gc.GeminiRunner,
    *,
    view: rosette.PerspectiveView | None = None,
    viterbi_boundary_m: float | None = None,
    forward_range_m: tuple[float, float] = (3.0, 18.0),
    tol_rel: float = 0.10,
    tol_m: float = 1.0,
    seed: int | None = 0,
    code_execution: bool = True,
    thinking_level: str = "MEDIUM",
    media_resolution: str = "HIGH",
    validator: Any = None,
    expect_stdout: str = MEASURE_STDOUT_PATTERN,
) -> dict[str, Any]:
    """Run one validated code-execution call on a road/IPM patch and cross-check texture stats & boundary."""
    import cv2

    work_img = image
    if view is not None:
        try:
            ipm_crop, _ipm_valid = cvc.ground_ipm(image, view, forward_m=forward_range_m)
            if ipm_crop.size > 0 and np.any(ipm_crop > 0):
                work_img = ipm_crop
        except Exception:
            work_img = image

    h, w = work_img.shape[:2]
    val_fn = validator if validator is not None else (lambda r: None)
    reply, trace = await runner.ask(
        [UC3_AGENTIC_PROMPT, work_img],
        schemas.MaterialBoundaryMeasurement,
        code_execution=code_execution,
        thinking_level=thinking_level,
        media_resolution=media_resolution,
        expect_stdout=expect_stdout,
        validator=val_fn,
        seed=seed,
        return_trace=True,
    )
    gc.check_code_exec_trace(trace, expect_stdout=expect_stdout, sent_image_shape=(h, w))

    desc = cvc.road_descriptor(work_img)
    lab_luma = float(desc[0] * 255.0)
    gray = cv2.cvtColor(work_img, cv2.COLOR_BGR2GRAY) if work_img.ndim == 3 else work_img
    gray_luma = float(gray[gray > 0].mean()) if np.any(gray > 0) else float(gray.mean())
    rep_luma = float(reply.mean_luma) if reply is not None else -1e9
    denom = max(1.0, lab_luma, gray_luma)
    rel_err = min(abs(rep_luma - lab_luma), abs(rep_luma - gray_luma)) / denom

    gx = cv2.Sobel(gray.astype(np.float32), cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray.astype(np.float32), cv2.CV_32F, 0, 1, ksize=3)
    g_mag = np.hypot(gx, gy)
    g_l1 = np.abs(gx) + np.abs(gy)
    local_grad_l2 = float(g_mag.mean())
    local_grad_l1 = float((0.5 * g_l1).mean())
    local_grad_sum = float(g_l1.mean())
    rep_grad = float(reply.grad_mean) if reply is not None else -1e9
    grad_denom = max(1.0, local_grad_l2, abs(rep_grad))
    grad_rel_err = (
        min(
            abs(rep_grad - local_grad_l2),
            abs(rep_grad - local_grad_l1),
            abs(rep_grad - local_grad_sum),
        )
        / grad_denom
    )

    f_min, f_max = float(forward_range_m[0]), float(forward_range_m[1])
    if reply is not None and reply.change_row_norm is not None:
        # Row 0 is far (f_max), row 1000 is near (f_min)
        est_boundary_m = f_max - (float(reply.change_row_norm) / 1000.0) * (f_max - f_min)
    else:
        est_boundary_m = None

    if viterbi_boundary_m is not None and est_boundary_m is not None:
        boundary_delta_m = abs(float(est_boundary_m) - float(viterbi_boundary_m))
        boundary_ok = boundary_delta_m <= float(tol_m)
    else:
        boundary_delta_m = 0.0
        boundary_ok = True

    agree = bool(
        rel_err <= float(tol_rel) and grad_rel_err <= max(float(tol_rel), 0.25) and boundary_ok
    )
    status = "agree" if agree else "disagree"

    overlay = work_img.copy() if work_img.ndim == 3 else cv2.cvtColor(work_img, cv2.COLOR_GRAY2BGR)
    if reply is not None and reply.change_row_norm is not None:
        ry = int(round(reply.change_row_norm / 1000.0 * h))
        cv2.line(overlay, (0, ry), (w - 1, ry), (11, 87, 208), 2)
    return {
        "measurement": reply,
        "trace": trace,
        "local_lab_luma": lab_luma,
        "local_gray_luma": gray_luma,
        "local_grad_mean": local_grad_l2,
        "rel_error": rel_err,
        "grad_rel_error": grad_rel_err,
        "est_boundary_m": est_boundary_m,
        "boundary_delta_m": boundary_delta_m,
        "agree": agree,
        "agreement_line": (
            f"code_exec_agreement={status}(luma_rel_err={rel_err:.3f},"
            f"grad_rel_err={grad_rel_err:.3f},tol={tol_rel:.2f})"
        ),
        "overlay": overlay,
    }


# ------------------------------------------- Optional extensions O1 & O2 (UC2)

REPEAT_PASS_DIFF_PROMPT = (
    "Compare these two perspective street-view images captured on different dates at the "
    "same location and bearing. Determine whether there is a genuine physical change to street "
    "furniture, poles, signs, or building facades (`change_detected=true`) or only lighting, "
    "shadow, foliage, or parked-vehicle differences (`change_detected=false`)."
)


def _compute_ssim_and_heatmap(img_a: np.ndarray, img_b: np.ndarray) -> tuple[float, np.ndarray]:
    import cv2

    g1 = cv2.cvtColor(img_a, cv2.COLOR_BGR2GRAY).astype(np.float32)
    g2 = cv2.cvtColor(img_b, cv2.COLOR_BGR2GRAY).astype(np.float32)
    if g1.shape != g2.shape:
        g2 = cv2.resize(g2, (g1.shape[1], g1.shape[0]))
    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2
    mu1 = cv2.GaussianBlur(g1, (11, 11), 1.5)
    mu2 = cv2.GaussianBlur(g2, (11, 11), 1.5)
    mu1_sq = mu1 * mu1
    mu2_sq = mu2 * mu2
    mu1_mu2 = mu1 * mu2
    sigma1_sq = cv2.GaussianBlur(g1 * g1, (11, 11), 1.5) - mu1_sq
    sigma2_sq = cv2.GaussianBlur(g2 * g2, (11, 11), 1.5) - mu2_sq
    sigma12 = cv2.GaussianBlur(g1 * g2, (11, 11), 1.5) - mu1_mu2
    ssim_map = ((2 * mu1_mu2 + c1) * (2 * sigma12 + c2)) / (
        (mu1_sq + mu2_sq + c1) * (sigma1_sq + sigma2_sq + c2)
    )
    ssim_val = float(np.clip(np.mean(ssim_map), -1.0, 1.0))
    abs_diff = np.abs(g1 - g2).astype(np.uint8)
    heatmap = cv2.applyColorMap(abs_diff, cv2.COLORMAP_INFERNO)
    return ssim_val, heatmap


async def uc2_repeat_pass_diff(
    repeat_pairs_df: pd.DataFrame,
    frames: pd.DataFrame,
    intr: rosette.Intrinsics,
    fetch: Callable[[str], bytes],
    runner: gc.GeminiRunner,
    *,
    width: int = 768,
    height: int = 576,
    seed: int = 0,
) -> dict[str, Any]:
    """Render aligned cross-day views for a repeat-pass pair, compute SSIM/absdiff, and query RepeatPassDiff (O1)."""
    from svi_geo import data

    frames_norm = data.ensure_capture_id(frames)
    pair_row: dict[str, Any] | None = None
    sub_a = pd.DataFrame()
    sub_b = pd.DataFrame()

    if repeat_pairs_df is not None and not repeat_pairs_df.empty:
        for r in repeat_pairs_df.to_dict("records"):
            aid = str(r.get("a_id") or "")
            bid = str(r.get("b_id") or "")
            sa = frames_norm[frames_norm["capture_id"].astype(str) == aid]
            sb = frames_norm[frames_norm["capture_id"].astype(str) == bid]
            if not sa.empty and not sb.empty:
                pair_row = r
                sub_a, sub_b = sa, sb
                break

    if sub_a.empty or sub_b.empty:
        cids = frames_norm["capture_id"].dropna().unique().tolist()
        if len(cids) >= 2:
            sub_a = frames_norm[frames_norm["capture_id"] == cids[0]]
            sub_b = frames_norm[frames_norm["capture_id"] == cids[1]]
            pair_row = {"a_id": str(cids[0]), "b_id": str(cids[1]), "sep_m": 0.0, "days_apart": 1}
        elif len(cids) == 1:
            sub_a = frames_norm[frames_norm["capture_id"] == cids[0]]
            sub_b = sub_a
            pair_row = {"a_id": str(cids[0]), "b_id": str(cids[0]), "sep_m": 0.0, "days_apart": 0}
        else:
            raise ValueError("no frames available for uc2_repeat_pass_diff")

    rec_a = [r for r in sub_a.to_dict("records") if rosette.is_ground_camera(int(r["cam_k"]))]
    rec_b = [r for r in sub_b.to_dict("records") if rosette.is_ground_camera(int(r["cam_k"]))]
    r0_a = rec_a[0] if rec_a else sub_a.to_dict("records")[0]
    bearing = float(r0_a["camera_pose"]["heading"])
    choice_b = rosette.best_camera_for_view(
        rec_b or sub_b.to_dict("records"), intr, bearing, 0.0, width / height, min_hfov=60.0
    )
    r0_b = (
        choice_b.row
        if choice_b is not None
        else (rec_b[0] if rec_b else sub_b.to_dict("records")[0])
    )

    v_obj = rosette.PerspectiveView(bearing, 0.0, 70.0, width, height)
    scale = images.decode_scale_for_view(width, 70.0)
    raw_a = images.decode(fetch(r0_a["gcs_uri"]), scale=scale)
    raw_b = images.decode(fetch(r0_b["gcs_uri"]), scale=scale)
    img_a = rosette.render_perspective(
        raw_a, intr, r0_a["camera_pose"], v_obj, int(r0_a["cam_k"]), antialias=True, mask_hood=True
    )
    img_b = rosette.render_perspective(
        raw_b, intr, r0_b["camera_pose"], v_obj, int(r0_b["cam_k"]), antialias=True, mask_hood=True
    )
    ssim_val, heatmap = _compute_ssim_and_heatmap(img_a, img_b)
    verdict = await runner.ask(
        [REPEAT_PASS_DIFF_PROMPT, img_a, img_b],
        schemas.RepeatPassDiff,
        seed=seed,
    )
    return {
        "pair": pair_row,
        "img_a": img_a,
        "img_b": img_b,
        "diff_heatmap": heatmap,
        "ssim": ssim_val,
        "verdict": verdict,
    }


async def uc2_asset_audit(
    assets_df: pd.DataFrame,
    located_entities: Sequence[Any],
    frames: pd.DataFrame,
    intr: rosette.Intrinsics,
    fetch: Callable[[str], bytes],
    runner: gc.GeminiRunner,
    *,
    max_assets: int = 3,
    match_radius_m: float = 15.0,
    seed: int = 0,
) -> dict[str, Any]:
    """Project `cropped_assets_latest` inventory into rosette views, match against located entities,
    and confirm the closest asset with Gemini `PresenceCheck` (O2)."""
    import math

    from svi_geo import data, geo, maps

    if assets_df is None or assets_df.empty:
        return {
            "audit_df": pd.DataFrame(
                columns=[
                    "asset_id",
                    "asset_type",
                    "lat",
                    "lng",
                    "nearest_entity_m",
                    "nearest_entity_id",
                    "nearest_entity_cls",
                    "matched",
                    "matched_6m",
                    "exact_class_match",
                    "post_group_match",
                    "exact_class_match_6m",
                    "post_group_match_6m",
                    "proj_u",
                    "proj_v",
                ]
            ),
            "matched_count": 0,
            "matched_6m_count": 0,
            "exact_class_matched_count": 0,
            "post_group_matched_count": 0,
            "exact_class_matched_6m_count": 0,
            "post_group_matched_6m_count": 0,
            "gemini_confirmed": False,
        }

    frames_norm = data.ensure_capture_id(frames)
    ground_rows = [
        r for r in frames_norm.to_dict("records") if rosette.is_ground_camera(int(r["cam_k"]))
    ]
    rosette_coords = [
        (float(r["camera_pose"]["latitude"]), float(r["camera_pose"]["longitude"]))
        for r in ground_rows
        if r.get("camera_pose")
    ]
    records_out: list[dict[str, Any]] = []

    for row in assets_df.to_dict("records"):
        wkt = row.get("wkt")
        if wkt:
            try:
                alat, alng = maps.parse_wkt_point(str(wkt))
            except ValueError:
                alat, alng = float(row["lat"]), float(row["lng"])
        else:
            alat, alng = float(row["lat"]), float(row["lng"])

        if rosette_coords:
            min_ros_m = min(
                float(geo.haversine_m(alat, alng, rlat, rlng)) for rlat, rlng in rosette_coords
            )
            if min_ros_m > 50.0:
                continue

        best_ent_m = float("inf")
        best_ent_id: str | None = None
        best_ent_cls: str | None = None
        for e in located_entities or ():
            elat = getattr(e, "lat", None) if not isinstance(e, Mapping) else e.get("lat")
            elng = getattr(e, "lng", None) if not isinstance(e, Mapping) else e.get("lng")
            if elat is not None and elng is not None:
                d_e = float(geo.haversine_m(alat, alng, float(elat), float(elng)))
                if d_e < best_ent_m:
                    best_ent_m = d_e
                    best_ent_id = str(
                        getattr(e, "entity_id", "")
                        if not isinstance(e, Mapping)
                        else (e.get("entity_id") or "")
                    )
                    best_ent_cls = str(
                        getattr(e, "cls", "")
                        if not isinstance(e, Mapping)
                        else (e.get("cls") or e.get("class") or "")
                    )
        matched = bool(best_ent_m <= float(match_radius_m))
        matched_6m = bool(best_ent_m <= 6.0)
        raw_atype = str(row.get("asset_type") or "")
        expected_cls = raw_atype.removeprefix("ASSET_CLASS_")
        exact_class_match = bool(
            matched and best_ent_cls and expected_cls and best_ent_cls == expected_cls
        )
        post_group_match = bool(
            matched and (not best_ent_cls or best_ent_cls in ent.POST_GROUP)
        )
        exact_class_match_6m = bool(
            matched_6m and best_ent_cls and expected_cls and best_ent_cls == expected_cls
        )
        post_group_match_6m = bool(
            matched_6m and (not best_ent_cls or best_ent_cls in ent.POST_GROUP)
        )

        proj_u, proj_v = float("nan"), float("nan")
        r_near = None
        v_obj = None
        if ground_rows:
            dists = [
                float(
                    geo.haversine_m(
                        r["camera_pose"]["latitude"], r["camera_pose"]["longitude"], alat, alng
                    )
                )
                for r in ground_rows
            ]
            best_idx = int(np.argmin(dists))
            r_near = ground_rows[best_idx]
            pose = r_near["camera_pose"]
            brg = float(geo.bearing_deg(pose["latitude"], pose["longitude"], alat, alng))
            v_obj = rosette.PerspectiveView(brg, 0.0, 60.0, 640, 480)
            u_px, v_px, ok_px = v_obj.bearing_to_pixel(brg, 0.0)
            if bool(ok_px):
                proj_u, proj_v = float(u_px), float(v_px)

        records_out.append(
            {
                "asset_id": str(row.get("asset_id") or ""),
                "asset_type": raw_atype,
                "lat": alat,
                "lng": alng,
                "nearest_entity_m": best_ent_m if math.isfinite(best_ent_m) else None,
                "nearest_entity_id": best_ent_id if matched else None,
                "nearest_entity_cls": best_ent_cls if matched else None,
                "matched": matched,
                "matched_6m": matched_6m,
                "exact_class_match": exact_class_match,
                "post_group_match": post_group_match,
                "exact_class_match_6m": exact_class_match_6m,
                "post_group_match_6m": post_group_match_6m,
                "proj_u": proj_u,
                "proj_v": proj_v,
                "_r_near": r_near,
                "_v_obj": v_obj,
            }
        )

    records_out.sort(
        key=lambda r: (
            0 if r["matched"] else 1,
            float(r["nearest_entity_m"]) if r["nearest_entity_m"] is not None else float("inf"),
        )
    )

    first_crop: np.ndarray | None = None
    first_type: str = "ROAD_SIGN"
    for r in records_out[: max(1, int(max_assets))]:
        r_near = r.get("_r_near")
        v_obj = r.get("_v_obj")
        if r_near is not None and v_obj is not None:
            try:
                scale = images.decode_scale_for_view(640, 60.0)
                raw_im = images.decode(fetch(r_near["gcs_uri"]), scale=scale)
                first_crop = rosette.render_perspective(
                    raw_im,
                    intr,
                    r_near["camera_pose"],
                    v_obj,
                    int(r_near["cam_k"]),
                    antialias=True,
                    mask_hood=True,
                )
                first_type = str(r.get("asset_type") or "ASSET")
                break
            except Exception:
                first_crop = None

    for r in records_out:
        r.pop("_r_near", None)
        r.pop("_v_obj", None)

    audit_df = pd.DataFrame(records_out)
    gemini_confirmed = False
    if first_crop is not None:
        chk = await runner.ask(
            [
                f"Is a street asset matching `{first_type}` visible near the centre of this view?",
                first_crop,
            ],
            schemas.PresenceCheck,
            seed=seed,
        )
        gemini_confirmed = bool(chk and chk.present)

    return {
        "audit_df": audit_df,
        "matched_count": int(audit_df["matched"].sum()) if not audit_df.empty else 0,
        "matched_6m_count": int(audit_df["matched_6m"].sum()) if not audit_df.empty else 0,
        "exact_class_matched_count": (
            int(audit_df["exact_class_match"].sum()) if not audit_df.empty else 0
        ),
        "post_group_matched_count": (
            int(audit_df["post_group_match"].sum()) if not audit_df.empty else 0
        ),
        "exact_class_matched_6m_count": (
            int(audit_df["exact_class_match_6m"].sum()) if not audit_df.empty else 0
        ),
        "post_group_matched_6m_count": (
            int(audit_df["post_group_match_6m"].sum()) if not audit_df.empty else 0
        ),
        "gemini_confirmed": gemini_confirmed,
    }


POLE_SUBCLASSIFICATION_PROMPT = """You are a senior electric and telecom utility GIS asset auditor inspecting calibrated Street View Insights (`SV_PANO`) 3-panel perspective composites of a triangulated roadside vertical structure.

Each composite image contains 3 side-by-side panels rendered from the KB4 fisheye rosette:
- Panel 1 (Left): Full Vertical Shaft View (`pitch=+5 deg`, `vfov=85 deg`) from ground line to crown.
- Panel 2 (Center): High-Resolution Crown & Cross-Arm Zoom (top 45% of the vertical shaft).
- Panel 3 (Right): High-Resolution Base & Ground-Contact Zoom (bottom 45% of the vertical shaft).

Apply these strict sub-classification rules:
1. TRUE UTILITY POLES (`is_true_utility_pole = true`):
   - `DISTRIBUTION_UTILITY_POLE`: Carries overhead primary/secondary electric distribution conductors, insulators, pole-mount transformers, or fused cutouts, without a separate lower communications strand.
   - `JOINT_USE_UTILITY_POLE`: Carries electric distribution at the upper crown AND lower-tier telecom/fiber cables, splice cases, or street-light luminaires attached to the same utility shaft.
   - `TRANSMISSION_POLE`: Tall sub-transmission or transmission structure with multi-circuit cross-arms, large suspension/post insulators, and high-voltage conductors.
   - `DOUBLE_POLE_TRANSFER_PAIR`: Two adjacent utility poles standing side-by-side (typically an aging or topped pole strapped or mid-transfer to a replacement pole). Set `is_double_pole = true`.
2. NON-UTILITY LOOKALIKES (`is_true_utility_pole = false`):
   - `STANDALONE_STREET_LIGHT`: Dedicated roadway/pedestrian lighting standard (metal, concrete, or fiberglass shaft with mast arm + luminaire, fed underground with NO overhead distribution conductors or cross-arms).
   - `TRAFFIC_SIGNAL_MAST_ARM`: Heavy structural pole supporting traffic signal heads, pedestrian push-buttons, or intersection mast arms without overhead power distribution lines.
   - `GUY_STUB_OR_PUSH_BRACE`: Unwired stub pole or angled push-brace pole used purely for mechanical guying/bracing.
   - `TELECOM_OR_CELL_MONOPOLE`: Dedicated small-cell/5G antenna monopole or standalone communications drop pole with no electric distribution lines.
   - `SIGN_POST_OR_OTHER`: Thin sign post, bollard, flagpole, or tree trunk mistaken for a pole.

Return a JSON object matching `PoleSubClassification`."""


def _iter_rows(rows: Any) -> list[Mapping[str, Any]]:
    """Convert a DataFrame or sequence of mapping rows into a list of dicts."""
    if isinstance(rows, pd.DataFrame):
        return rows.to_dict("records")
    return list(rows or [])


def render_pole_inspection_composite(
    pano_rows: Any,
    pole_lat: float,
    pole_lng: float,
    fetch: Callable[[str], bytes],
    intr: rosette.Intrinsics = rosette.DEFAULT_INTRINSICS,
    *,
    panel_width: int = 360,
    panel_height: int = 480,
    pitch_deg: float | None = None,
    vfov_deg: float | None = None,
) -> dict[str, Any] | None:
    """Render a 3-panel calibrated inspection composite for a candidate pole from one rosette.

    Panels:
      1. Full Vertical Shaft View (distance-adaptive pitch & vfov, cropped above vehicle hood)
      2. Crown & Cross-Arm Zoom (projected upper-crown elevation window at 2x optical resolution)
      3. Base & Trunk Ground-Contact Zoom (projected ground-collar window at 2x optical resolution)
    """
    import cv2

    ground_rows = [
        r for r in _iter_rows(pano_rows) if rosette.is_ground_camera(int(r.get("cam_k", -1)))
    ]
    if not ground_rows:
        return None

    r0 = ground_rows[0]
    clat = float(r0.get("lat") or r0.get("camera_pose", {}).get("latitude", 0.0))
    clng = float(r0.get("lng") or r0.get("camera_pose", {}).get("longitude", 0.0))
    pano_id = str(r0.get("capture_id") or r0.get("pano_id") or "")
    dist_m = float(geo.haversine_m(clat, clng, float(pole_lat), float(pole_lng)))
    bearing = float(geo.bearing_deg(clat, clng, float(pole_lat), float(pole_lng)))

    # Distance-adaptive vertical framing (camera height ~2.5m, pole crown up to ~11.0m above ground)
    eff_dist = max(dist_m, 4.0)
    el_base = max(-38.0, math.degrees(math.atan2(-2.5, eff_dist)) - 4.0)
    el_top = min(58.0, math.degrees(math.atan2(8.5, eff_dist)) + 4.0)
    if pitch_deg is None:
        pitch_val = float(np.clip(0.5 * (el_top + el_base), 2.0, 26.0))
    else:
        pitch_val = float(pitch_deg)
    if vfov_deg is None:
        half_span = max(abs(el_top - pitch_val), abs(pitch_val - el_base))
        vfov_val = float(np.clip(2.0 * half_span * 1.08, 48.0, 86.0))
    else:
        vfov_val = float(vfov_deg)

    pw, ph = int(panel_width), int(panel_height)
    aspect = pw / float(ph)
    hfov_deg = float(views.hfov_for_vfov(vfov_val, aspect))

    # Ensure the multi-camera composite has <0.1% black border even at the top crown crop
    max_hfov_m, max_vfov_m = 0.0, 0.0
    for p_try in (pitch_val, max(2.0, pitch_val - 4.0), max(2.0, pitch_val - 8.0), 8.0, 4.0):
        mh, mv = rosette.max_view_fov_multi(
            intr,
            ground_rows,
            bearing,
            float(p_try),
            aspect,
            max_black=0.001,
            hfov_cap=max(hfov_deg, 75.0),
        )
        if mh >= 32.0:
            pitch_val = float(p_try)
            max_hfov_m, max_vfov_m = float(mh), float(mv)
            break
    if max_hfov_m >= 25.0 and hfov_deg > max_hfov_m:
        hfov_deg = float(max_hfov_m)
        vfov_val = float(max_vfov_m)

    # Prefer a single camera if it can cover >=46 deg HFOV (or the requested hfov_deg) with <0.2% black border,
    # avoiding any multi-camera seam step across the pole shaft; otherwise composite adjacent ground cameras.
    single_min_hfov = min(hfov_deg, 46.0)
    choice = rosette.best_camera_for_view(
        ground_rows,
        intr,
        bearing,
        pitch_deg=pitch_val,
        aspect=aspect,
        min_hfov=single_min_hfov,
        max_black=0.002,
        hfov_cap=max(hfov_deg, 75.0),
    )
    if choice is not None and choice.hfov_deg < hfov_deg:
        hfov_deg = float(choice.hfov_deg)
        vfov_val = float(choice.vfov_deg)

    best_row = choice.row if choice is not None else None
    if best_row is None:
        best_row = min(
            ground_rows,
            key=lambda r: abs(
                float(
                    geo.angdiff(
                        float(r.get("heading") or r.get("camera_pose", {}).get("heading", 0.0)),
                        bearing,
                    )
                )
            ),
        )

    cam_k = int(best_row["cam_k"])
    pose = best_row["camera_pose"]
    # Render at 2x resolution so the Crown and Base panels preserve native optical detail
    hi_w, hi_h = pw * 2, ph * 2
    hi_view = rosette.PerspectiveView(
        yaw_deg=bearing,
        pitch_deg=pitch_val,
        hfov_deg=hfov_deg,
        width=hi_w,
        height=hi_h,
    )
    scale = images.decode_scale_for_view(hi_h, hfov_deg)
    single_keep = rosette.hood_row(hi_view, pose, intr, rosette.HOOD_ELEV_DEG, cam_k)
    single_black = rosette.view_black_fraction(intr, pose, hi_view, cam_k, max_row=single_keep)

    if choice is not None and single_black < 0.005:
        used_rows = (best_row,)
        raw_im = images.decode(fetch(best_row["gcs_uri"]), scale=scale)
        hi_img = rosette.render_perspective(
            raw_im,
            intr,
            pose,
            hi_view,
            cam_k,
            antialias=True,
            mask_hood=False,
        )
    else:
        used_rows = rosette.composite_rows(intr, ground_rows, hi_view)
        if not used_rows:
            used_rows = (best_row,)
        imgs_by_k = {
            int(r["cam_k"]): images.decode(fetch(r["gcs_uri"]), scale=scale)
            for r in used_rows
        }
        hi_img = rosette.render_perspective_multi(
            imgs_by_k,
            intr,
            used_rows,
            hi_view,
            antialias=True,
        )

    # Crop above the capture-vehicle hood (both camera-frame and world-frame rays < HOOD_ELEV_DEG)
    vs = np.arange(hi_h, dtype=np.float64)
    us_probe = np.array([0.0, hi_view.cx, float(hi_w - 1)], dtype=np.float64)
    _, el_probe = hi_view.pixel_to_bearing(us_probe[:, None], vs[None, :])
    below_world = np.nonzero(el_probe.min(axis=0) < (rosette.HOOD_ELEV_DEG + 1.0))[0]
    world_keep = int(below_world[0]) if below_world.size else hi_h
    cam_keep = min(
        rosette.hood_row(
            hi_view, r["camera_pose"], intr, rosette.HOOD_ELEV_DEG + 1.0, int(r["cam_k"])
        )
        for r in used_rows
    )
    # Also trim any top rows where uncovered sensor border appears in the middle 60% crown width
    x_lo = int(round(0.20 * hi_w))
    x_hi = int(round(0.80 * hi_w))
    row_black_frac = (hi_img[: min(world_keep, int(cam_keep)), x_lo:x_hi].max(axis=2) == 0).mean(
        axis=1
    )
    bad_top = np.nonzero(row_black_frac > 0.005)[0]
    top_trim = int(bad_top[-1] + 1) if (bad_top.size and bad_top[0] == 0 and bad_top[-1] < 0.25 * hi_h) else 0

    keep = max(int(round(0.50 * hi_h)), min(world_keep, int(cam_keep), hi_h))
    hi_valid = hi_img[top_trim:keep]
    valid_h = hi_valid.shape[0]

    full_clean = cv2.resize(hi_valid, (pw, ph), interpolation=cv2.INTER_AREA)

    # Measure deterministic OpenCV LSD verticality support & lean angle on the clean full-shaft view
    center_box = (0.28 * pw, 0.08 * ph, 0.72 * pw, 0.92 * ph)
    vert_sup = float(cvc.vertical_post_support(full_clean, center_box, max_tilt_deg=12.0))
    lsd_lean = float(cvc.estimate_post_lean_deg(full_clean, center_box, max_tilt_deg=15.0))

    # Project 3D elevation windows for the pole's upper crown (+3.5m..+9.0m) and ground collar (-2.6m..+2.2m)
    crown_el_lo = math.degrees(math.atan2(3.5, eff_dist))
    crown_el_hi = min(65.0, math.degrees(math.atan2(9.0, eff_dist)) + 2.0)
    base_el_lo = max(rosette.HOOD_ELEV_DEG + 1.5, math.degrees(math.atan2(-2.6, eff_dist)) - 2.0)
    base_el_hi = math.degrees(math.atan2(2.2, eff_dist))

    _, v_crown_top, _ = hi_view.bearing_to_pixel(bearing, crown_el_hi)
    _, v_crown_bot, _ = hi_view.bearing_to_pixel(bearing, crown_el_lo)
    _, v_base_top, _ = hi_view.bearing_to_pixel(bearing, base_el_hi)
    _, v_base_bot, _ = hi_view.bearing_to_pixel(bearing, base_el_lo)

    win_h = max(64, int(round(0.45 * valid_h)))

    crown_center = 0.5 * (float(v_crown_top) + float(v_crown_bot)) - top_trim
    y_crown_lo = int(np.clip(round(crown_center - 0.5 * win_h), 0, max(0, valid_h - win_h)))
    y_crown_hi = min(valid_h, y_crown_lo + win_h)

    base_center = 0.5 * (float(v_base_top) + float(v_base_bot)) - top_trim
    y_base_lo = int(np.clip(round(base_center - 0.5 * win_h), 0, max(0, valid_h - win_h)))
    y_base_hi = min(valid_h, y_base_lo + win_h)
    if y_base_lo <= y_crown_lo:
        y_base_lo = max(0, valid_h - win_h)
        y_base_hi = valid_h

    crown_crop = hi_valid[y_crown_lo:y_crown_hi, x_lo:x_hi]
    base_crop = hi_valid[y_base_lo:y_base_hi, x_lo:x_hi]
    crown_clean = cv2.resize(crown_crop, (pw, ph), interpolation=cv2.INTER_CUBIC)
    base_clean = cv2.resize(base_crop, (pw, ph), interpolation=cv2.INTER_CUBIC)
    blk = max(
        float((p.max(axis=2) == 0).mean()) for p in (full_clean, crown_clean, base_clean)
    )

    def _annotate_panel(panel: np.ndarray, title: str, draw_guide: bool = False) -> np.ndarray:
        out = panel.copy()
        if draw_guide:
            cx = pw // 2
            cv2.line(out, (cx, 28), (cx, ph - 8), (60, 210, 90), 1, cv2.LINE_AA)
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

    p1 = _annotate_panel(full_clean, f"1: FULL SHAFT ({dist_m:.1f}m)", draw_guide=True)
    p2 = _annotate_panel(crown_clean, "2: CROWN & CROSS-ARM (2X)")
    p3 = _annotate_panel(base_clean, "3: BASE & GROUND (2X)")
    # Add thin vertical dividers between panels and mandatory Google imagery credit
    composite = np.hstack([p1, p2, p3])
    cv2.line(composite, (pw, 0), (pw, ph), (220, 225, 230), 2)
    cv2.line(composite, (2 * pw, 0), (2 * pw, ph), (220, 225, 230), 2)
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
        "pano_id": pano_id,
        "observation_id": str(best_row.get("observation_id") or ""),
        "cam_k": cam_k,
        "used_cam_ks": [int(r["cam_k"]) for r in used_rows],
        "bearing_deg": bearing,
        "dist_m": dist_m,
        "pitch_deg": round(pitch_val, 2),
        "vfov_deg": round(vfov_val, 2),
        "crown_el_range_deg": (round(crown_el_lo, 2), round(crown_el_hi, 2)),
        "base_el_range_deg": (round(base_el_lo, 2), round(base_el_hi, 2)),
        "black_fraction": blk,
        "vertical_support": vert_sup,
        "lsd_lean_deg": lsd_lean,
    }


def _select_parallax_panos_for_pole(
    pole_lat: float,
    pole_lng: float,
    frames: Any,
    observed_pano_ids: set[str],
    max_views: int = 2,
) -> tuple[list[str], float]:
    """Select up to `max_views` rosettes with maximum azimuth parallax around `(pole_lat, pole_lng)`."""
    pano_meta: list[dict[str, Any]] = []
    seen: set[str] = set()
    for r in _iter_rows(frames):
        pid = str(r.get("capture_id") or r.get("pano_id") or "")
        if not pid or pid in seen:
            continue
        seen.add(pid)
        rlat = float(r.get("lat") or r.get("camera_pose", {}).get("latitude", 0.0))
        rlng = float(r.get("lng") or r.get("camera_pose", {}).get("longitude", 0.0))
        dist = float(geo.haversine_m(rlat, rlng, pole_lat, pole_lng))
        if dist < 2.5 or dist > 45.0:
            continue
        az = float(geo.bearing_deg(rlat, rlng, pole_lat, pole_lng))
        pano_meta.append(
            {
                "pano_id": pid,
                "dist_m": dist,
                "bearing_deg": az,
                "observed": pid in observed_pano_ids,
            }
        )

    if not pano_meta:
        return [], 0.0

    # Primary view: prefer observed rosettes at >=5.5m (closest to optimal 14m inspection distance)
    pano_meta.sort(
        key=lambda m: (
            0 if m["observed"] else 1,
            0 if m["dist_m"] >= 5.5 else 1,
            abs(m["dist_m"] - 14.0),
        )
    )
    primary = pano_meta[0]
    selected_meta = [primary]

    if max_views >= 2 and len(pano_meta) >= 2:
        obs_good = [
            m for m in pano_meta[1:] if m["observed"] and 5.5 <= m["dist_m"] <= 38.0
        ]
        obs_any = [m for m in pano_meta[1:] if m["observed"] and m["dist_m"] <= 38.0]
        near_good = [m for m in pano_meta[1:] if 5.5 <= m["dist_m"] <= 28.0]
        pool = (
            obs_good
            or obs_any
            or near_good
            or [m for m in pano_meta[1:] if m["dist_m"] <= 28.0]
        )
        if pool:
            best_sec = max(
                pool,
                key=lambda m: (
                    abs(float(geo.angdiff(primary["bearing_deg"], m["bearing_deg"])))
                    - 0.4 * max(0.0, m["dist_m"] - 20.0)
                ),
            )
            selected_meta.append(best_sec)

    # Compute maximum azimuth parallax strictly across the selected/observed views for this pole
    support_bearings = [
        m["bearing_deg"] for m in pano_meta if m["observed"] or m in selected_meta
    ]
    max_parallax = 0.0
    for i in range(len(support_bearings)):
        for j in range(i + 1, len(support_bearings)):
            par = abs(float(geo.angdiff(support_bearings[i], support_bearings[j])))
            if par > max_parallax:
                max_parallax = par

    selected = [m["pano_id"] for m in selected_meta[:max_views]]
    return selected, float(max_parallax)


async def subclassify_poles(
    entities: Sequence[Any],
    frames: Any,
    fetch: Callable[[str], bytes],
    runner: gc.GeminiRunner,
    intr: rosette.Intrinsics = rosette.DEFAULT_INTRINSICS,
    *,
    max_poles: int = 5,
    max_views_per_pole: int = 2,
    panel_width: int = 360,
    panel_height: int = 480,
    seed: int | None = 0,
) -> dict[str, Any]:
    """Sub-classify triangulated vertical pole candidates using 3-panel multi-view composites and LSD gates."""
    pole_candidates: list[dict[str, Any]] = []
    for e in entities:
        if isinstance(e, Mapping):
            cls_name = str(e.get("cls") or "UTILITY_POLE")
            located = bool(e.get("located", True))
            lat = e.get("lat")
            lng = e.get("lng")
            eid = str(e.get("entity_id") or "pole")
            conf = float(e.get("confidence", 0.8))
            n_panos = int(e.get("n_panos", 1))
            pano_ids = list(e.get("pano_ids") or [])
            obs_list = list(e.get("observations") or [])
            ent_par = float(e.get("max_parallax_deg", 0.0) or 0.0)
        else:
            cls_name = str(getattr(e, "cls", "UTILITY_POLE"))
            located = bool(getattr(e, "located", True))
            lat = getattr(e, "lat", None)
            lng = getattr(e, "lng", None)
            eid = str(getattr(e, "entity_id", "pole"))
            conf = float(getattr(e, "confidence", 0.8))
            n_panos = int(getattr(e, "n_panos", 1))
            pano_ids = list(getattr(e, "pano_ids", []) or [])
            obs_list = list(getattr(e, "observations", []) or [])
            ent_par = float(getattr(e, "max_parallax_deg", 0.0) or 0.0)

        if not located or lat is None or lng is None or not math.isfinite(float(lat)):
            continue
        if cls_name not in {"UTILITY_POLE", "STREET_LIGHT"}:
            continue

        obs_panos: set[str] = {str(p) for p in pano_ids if p}
        obs_bearings: list[float] = []
        for o in obs_list:
            opid = str(o.get("pano_id") if isinstance(o, Mapping) else getattr(o, "pano_id", ""))
            if opid:
                obs_panos.add(opid)
            ray = o.get("ray") if isinstance(o, Mapping) else getattr(o, "ray", None)
            if ray is not None and hasattr(ray, "azimuth_deg"):
                obs_bearings.append(float(ray.azimuth_deg))

        pole_candidates.append(
            {
                "entity_id": eid,
                "initial_cls": cls_name,
                "lat": float(lat),
                "lng": float(lng),
                "initial_confidence": conf,
                "n_panos": n_panos,
                "obs_panos": obs_panos,
                "obs_bearings": obs_bearings,
                "entity_max_parallax_deg": ent_par,
            }
        )

    pole_candidates.sort(key=lambda c: (-c["n_panos"], -c["initial_confidence"], c["entity_id"]))
    pole_candidates = pole_candidates[: max(1, int(max_poles))]

    all_rows = _iter_rows(frames)
    rows_by_pano: dict[str, list[Mapping[str, Any]]] = {}
    for r in all_rows:
        pid = str(r.get("capture_id") or r.get("pano_id") or "")
        if pid:
            rows_by_pano.setdefault(pid, []).append(r)

    records: list[dict[str, Any]] = []
    for cand in pole_candidates:
        sel_panos, max_par = _select_parallax_panos_for_pole(
            cand["lat"],
            cand["lng"],
            all_rows,
            cand["obs_panos"],
            max_views=max_views_per_pole,
        )
        max_par = max(max_par, cand["entity_max_parallax_deg"])
        # Also include parallax from original observations if larger
        ob = cand["obs_bearings"]
        for i in range(len(ob)):
            for j in range(i + 1, len(ob)):
                max_par = max(max_par, abs(float(geo.angdiff(ob[i], ob[j]))))

        composites: list[dict[str, Any]] = []
        for pid in sel_panos:
            p_rows = rows_by_pano.get(pid, [])
            if not p_rows:
                continue
            comp = render_pole_inspection_composite(
                p_rows,
                cand["lat"],
                cand["lng"],
                fetch,
                intr,
                panel_width=panel_width,
                panel_height=panel_height,
            )
            if comp is not None:
                composites.append(comp)

        if not composites:
            continue

        best_vert_sup = max(c["vertical_support"] for c in composites)
        lsd_leans = [c["lsd_lean_deg"] for c in composites]
        lsd_lean_med = float(np.median(lsd_leans)) if lsd_leans else 0.0

        prompt_parts: list[Any] = [
            POLE_SUBCLASSIFICATION_PROMPT
            + f"\n\nCandidate metadata: entity_id={cand['entity_id']}, initial_detector_class={cand['initial_cls']}, "
            f"triangulated_panos={cand['n_panos']}, max_azimuth_parallax_deg={max_par:.1f}, "
            f"opencv_lsd_vertical_support={best_vert_sup:.2f}, opencv_lsd_lean_deg={lsd_lean_med:.2f}."
        ]
        for idx, c in enumerate(composites):
            prompt_parts.append(
                f"View {idx + 1} (rosette={c['pano_id']}, cam={c['cam_k']}, "
                f"distance={c['dist_m']:.1f}m, bearing={c['bearing_deg']:.1f} deg):"
            )
            prompt_parts.append(c["composite_img"])

        verdict = await runner.ask(
            prompt_parts,
            schemas.PoleSubClassification,
            seed=seed,
        )
        if verdict is None:
            continue

        # Deterministic taxonomy & geometry fusion gates:
        is_true_utility = verdict.pole_subtype in schemas.TRUE_UTILITY_POLE_SUBTYPES
        is_double = bool(
            verdict.is_double_pole
            or verdict.pole_subtype == schemas.PoleSubType.DOUBLE_POLE_TRANSFER_PAIR
        )
        is_false_det = bool(
            not is_true_utility
            and verdict.pole_subtype == schemas.PoleSubType.SIGN_POST_OR_OTHER
            and float(verdict.confidence) < 0.35
            and best_vert_sup < 0.25
        )
        llm_lean = float(np.clip(verdict.lean_deg, -45.0, 45.0))
        if best_vert_sup >= 0.35 and abs(llm_lean - lsd_lean_med) <= 5.0:
            fused_lean = round(0.5 * (llm_lean + lsd_lean_med), 2)
        elif best_vert_sup >= 0.50 and abs(llm_lean - lsd_lean_med) > 10.0:
            fused_lean = round(lsd_lean_med, 2)
        else:
            fused_lean = round(llm_lean, 2)

        records.append(
            {
                "entity_id": cand["entity_id"],
                "initial_cls": cand["initial_cls"],
                "lat": round(cand["lat"], 7),
                "lng": round(cand["lng"], 7),
                "n_panos": cand["n_panos"],
                "supporting_rosettes": [c["pano_id"] for c in composites],
                "supporting_observations": [c["observation_id"] for c in composites],
                "max_parallax_deg": round(max_par, 2),
                "opencv_vertical_support": round(best_vert_sup, 3),
                "opencv_lsd_lean_deg": round(lsd_lean_med, 2),
                "pole_subtype": verdict.pole_subtype.value,
                "is_true_utility_pole": bool(is_true_utility),
                "is_false_detection": is_false_det,
                "material": verdict.material.value,
                "condition": verdict.condition.value,
                "crossarm_config": verdict.crossarm_config.value,
                "attached_equipment": [eq.value for eq in verdict.attached_equipment],
                "is_double_pole": is_double,
                "lean_deg": fused_lean,
                "confidence": round(float(verdict.confidence), 3),
                "evidence_summary": verdict.evidence_summary,
                "composites": composites,
            }
        )

    true_count = sum(1 for r in records if r["is_true_utility_pole"])
    false_count = sum(1 for r in records if r["is_false_detection"])
    non_util_count = sum(
        1 for r in records if not r["is_true_utility_pole"] and not r["is_false_detection"]
    )
    return {
        "records": records,
        "true_utility_pole_count": true_count,
        "non_utility_vertical_count": non_util_count,
        "false_detection_count": false_count,
    }


