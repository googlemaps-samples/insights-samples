"""Shared use-case execution pipelines for notebooks and the label-free evaluation harness (T7).

The notebooks and `scripts/run_labelfree_eval.py` both call these functions so the evaluation
harness tests the exact code path shipped in the notebooks. All experimental improvements live
on `Variant` with defaults that preserve baseline behaviour until promoted by `labelfree.decide_keep`.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

from svi_geo import cvchecks as cvc
from svi_geo import entities as ent
from svi_geo import eval as ev
from svi_geo import gemini_client as gc
from svi_geo import images, pipeline, roof, rosette, schemas, sequence, smoothing, views

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
    uc2_class_min_confidence={"ROAD_SIGN": 0.55, "UTILITY_POLE": 0.50, "HOUSE": 0.45},
    uc2_cv_post_gate=True,
    uc2_cv_post_min_support=0.35,
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
    """Apply per-class confidence thresholds and optional OpenCV vertical-post gates."""
    obs = list(run.observations)
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
        if o.cls == "UTILITY_POLE":
            sup = cvc.vertical_post_support(im, box)
            if sup < variant.uc2_cv_post_min_support:
                continue
        elif o.cls == "ROAD_SIGN":
            sup = max(cvc.vertical_post_support(im, box), cvc.sign_post_support(im, box))
            if sup < variant.uc2_cv_post_min_support:
                continue
        kept.append(o)
    return kept


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
    run = await pipeline.detect_panos(sel_frames, fetch, runner, intr, ref, **det_kw)
    filtered_obs = _filter_observations_uc2(run, variant)
    cluster_kw: dict[str, Any] = {"merge_single_view": True}
    if variant.uc2_min_post_panos > 1:
        cluster_kw["min_post_panos"] = variant.uc2_min_post_panos
    if variant.uc2_house_facade_edges:
        cluster_kw["use_house_facade_edges"] = True
    entities = ent.cluster(filtered_obs, ref, **cluster_kw)
    located = ent.located_entities(entities)
    unlocated = [e for e in entities if e.method == "unlocated"]
    ent_df = pd.DataFrame(
        [
            {
                "entity_id": e.entity_id,
                "class": e.cls,
                "lat": e.lat,
                "lng": e.lng,
                "method": e.method,
                "range_m": e.range_m,
                "n_panos": e.n_panos,
                "n_obs": len(e.obs_ids),
                "rms_m": e.rms_m,
                "confidence": e.confidence,
                **{k: v[0] for k, v in e.attrs.items()},
            }
            for e in entities
        ],
        columns=[
            "entity_id",
            "class",
            "lat",
            "lng",
            "method",
            "range_m",
            "n_panos",
            "n_obs",
            "rms_m",
            "confidence",
        ],
    )
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
        "houses_located": houses_located,
        "houses_unlocated": houses_unlocated,
        "self_consistency": sc,
        "det_black": det_black,
        "det_dark": det_dark,
        "black_fraction_max": det_black,
        "dark_pixel_max": det_dark,
        "redaction_overlap_max": det_redaction,
    }


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
