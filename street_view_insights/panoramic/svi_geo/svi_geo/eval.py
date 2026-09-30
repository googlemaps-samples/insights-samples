"""Evaluation without ground truth (T9): clustering metrics, baselines, self-consistency on real
panos, and optional hand-label scoring. All metric code is deterministic; Gemini is only used,
through a `GeminiRunner`, to answer a yes/no presence question on code-rendered crops.
"""

from __future__ import annotations

import csv
import dataclasses
import json
import math
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from sklearn.cluster import DBSCAN
from sklearn.metrics import adjusted_rand_score, v_measure_score

from svi_geo import entities as ent
from svi_geo import geo, rosette, schemas
from svi_geo import triangulate as tri

# ----------------------------------------------------------------------------- clustering metrics


def _pct(x: Sequence[float], q: float) -> float:
    return float(np.percentile(x, q)) if len(x) else math.nan


def clustering_metrics(
    pred: Mapping[str, str],
    truth: Mapping[str, str | None],
    pred_points: Mapping[str, Sequence[float]] | None = None,
    truth_points: Mapping[str, Sequence[float]] | None = None,
    visible_objects: Iterable[str] | None = None,
) -> dict[str, float]:
    """Observation-weighted dedup metrics.

    `pred`: obs_id -> entity label; `truth`: obs_id -> object id (None = false positive).
    Only true observations count for purity/completeness/V/ARI. An entity "claims" its majority
    object; entities whose majority object is already claimed by a bigger entity are
    duplicates. Location error is measured between each object and its claiming entity.
    """
    ids = sorted(o for o in pred if truth.get(o) is not None)
    members: dict[str, list[str]] = defaultdict(list)
    for o in ids:
        members[pred[o]].append(truth[o])
    obj_counts = Counter(truth[o] for o in ids)
    n = len(ids)
    fp_entities = {pred[o] for o in pred if truth.get(o) is None} - set(members)
    out: dict[str, float] = {
        "n_obs": float(n),
        "n_objects": float(len(obj_counts)),
        "n_entities": float(len(members)),
        "n_fp_entities": float(len(fp_entities)),
    }
    if not n:
        return out
    purity = sum(max(Counter(v).values()) for v in members.values()) / n
    best_in_one: dict[str, int] = defaultdict(int)
    for v in members.values():
        for obj, c in Counter(v).items():
            best_in_one[obj] = max(best_in_one[obj], c)
    completeness = sum(best_in_one.values()) / n
    # claims: biggest majority first, deterministic tie-break on label
    ranked = []
    for lab, v in members.items():
        c = Counter(v)
        top = max(sorted(c), key=lambda k: c[k])
        ranked.append((-c[top], lab, top))
    claim: dict[str, str] = {}
    n_dup = 0
    for _, lab, top in sorted(ranked):
        if top in claim:
            n_dup += 1
        else:
            claim[top] = lab
    labels_true = [truth[o] for o in ids]
    labels_pred = [pred[o] for o in ids]
    out.update(
        purity=purity,
        completeness=completeness,
        duplicate_rate=n_dup / len(obj_counts),
        entities_per_object=len(members) / len(obj_counts),
        v_measure=float(v_measure_score(labels_true, labels_pred)),
        ari=float(adjusted_rand_score(labels_true, labels_pred)),
    )
    if pred_points is not None and truth_points is not None:
        err = [
            float(np.hypot(*(np.asarray(pred_points[lab][:2]) - np.asarray(truth_points[obj][:2]))))
            for obj, lab in sorted(claim.items())
            if lab in pred_points and obj in truth_points
        ]
        out["loc_err_median_m"] = _pct(err, 50)
        out["loc_err_p90_m"] = _pct(err, 90)
    vis = set(visible_objects) if visible_objects is not None else None
    if vis:
        out["missed_rate"] = len(vis - set(claim)) / len(vis)
    return out


# ----------------------------------------------------------------------------- baselines


def entity_labels(
    entities: Sequence[ent.Entity], observations: Sequence[ent.Observation] | None = None
):
    """Labels + centres. Observations the pipeline dropped (suppressed ghosts) count as their
    own singleton entity so they are not silently excluded from the clustering metrics.
    Only located entities get a centre: unlocated and dropped ones have no position, so
    they are left out of the location error instead of being given an invented range."""
    labels = ent.labels_by_observation(entities)
    centres = {e.entity_id: tuple(e.point_enu[:2]) for e in ent.located_entities(entities)}
    for o in observations or []:
        if o.obs_id not in labels:
            labels[o.obs_id] = f"dropped_{o.obs_id}"
    return labels, centres


def b0_labels(observations: Sequence[ent.Observation]):
    """B0: no dedup, every observation is its own entity (placed at 12 m for location)."""
    labels = {o.obs_id: o.obs_id for o in observations}
    centres = {o.obs_id: tuple(tri.point_from_range(o.ray, 12.0)[:2]) for o in observations}
    return labels, centres


def _dbscan_points(observations, points, eps_by_class: Mapping[str, float] | float, prefix: str):
    labels, centres = {}, {}
    by_cls: dict[str, list[int]] = defaultdict(list)
    for i, o in enumerate(observations):
        by_cls[o.cls].append(i)
    for cls in sorted(by_cls):
        idx = by_cls[cls]
        eps = eps_by_class if isinstance(eps_by_class, float | int) else eps_by_class.get(cls, 4.0)
        xy = np.array([points[i][:2] for i in idx])
        lab = DBSCAN(eps=float(eps), min_samples=1).fit_predict(xy)
        for j, i in enumerate(idx):
            labels[observations[i].obs_id] = f"{prefix}{cls}_{lab[j]}"
        for c in set(lab):
            centres[f"{prefix}{cls}_{c}"] = tuple(xy[lab == c].mean(axis=0))
    return labels, centres


def fixed_range_labels(
    observations: Sequence[ent.Observation], range_m: float = 12.0, eps_m: float = 3.0
):
    """B1: every detection placed `range_m` along its bearing, then DBSCAN(eps_m) per class."""
    pts = [tri.point_from_range(o.ray, range_m) for o in observations]
    return _dbscan_points(observations, pts, float(eps_m), "b1_")


def single_view_labels(
    observations: Sequence[ent.Observation],
    cam_height_m: float = 2.5,
    eps_by_class: Mapping[str, float] | None = None,
):
    """Ablation: calibrated bearings, but single-view ranging only (no triangulation)."""
    eps = {**ent.EPS_BY_CLASS, **(eps_by_class or {})}
    pts = []
    for o in observations:
        p = ent._single_view_point(o, cam_height_m)  # noqa: SLF001 - same ranging as cluster()
        pts.append(p if p is not None else tri.point_from_range(o.ray, 12.0))
    return _dbscan_points(observations, pts, eps, "sv_")


# ----------------------------------------------------------------------------- self-consistency


@dataclasses.dataclass(frozen=True)
class ViewTask:
    entity_id: str
    cls: str
    pano_id: str
    cam_k: int
    az_deg: float
    el_deg: float
    range_m: float
    observation_id: str


def _visible_views(
    point: np.ndarray,
    frames: pd.DataFrame,
    intr: rosette.Intrinsics,
    ref_lla: Sequence[float],
    min_range_m: float,
    max_range_m: float,
    hood_elev_deg: float = -40.0,
):
    """(pano_id, row, az, el, range) per pano whose best-facing ground camera sees `point`."""
    out = []
    gf = frames[frames["cam_k"].between(0, 5)]
    for pid, g in gf.groupby("pano_id", sort=True):
        rows = g.to_dict("records")
        c = np.mean([rosette.camera_center_enu(r["camera_pose"], ref_lla) for r in rows], axis=0)
        d = point - c
        rh = math.hypot(d[0], d[1])
        if not (min_range_m <= rh <= max_range_m):
            continue
        lat, lng, _ = geo.enu_to_lla(point[0], point[1], point[2], *ref_lla)
        row = rosette.select_camera_for_target(rows, float(lat), float(lng), intr=intr)
        if row is None:
            continue
        cc = rosette.camera_center_enu(row["camera_pose"], ref_lla)
        dd = point - cc
        az = float(geo.enu_bearing_deg(dd[0], dd[1]))
        el = math.degrees(math.atan2(dd[2], math.hypot(dd[0], dd[1])))
        *_, ok = rosette.bearing_to_pixel(
            intr, row["camera_pose"], az, el, int(row["cam_k"]), hood_elev_deg=hood_elev_deg
        )
        if bool(ok):
            out.append((pid, row, az, el, rh))
    return out


def predict_withheld_views(
    entities: Sequence[ent.Entity],
    frames: pd.DataFrame,
    intr: rosette.Intrinsics,
    ref_lla: Sequence[float],
    min_range_m: float = 3.0,
    max_range_m: float = 30.0,
    max_tasks: int | None = None,
    stratify: bool = True,
) -> list[ViewTask]:
    """For each triangulated entity, the panos (not among its supporting panos) where the
    geometry predicts it is visible, with the camera and bearing to render.

    With `stratify` (default) the list is ordered round-robin across classes, and within a
    class round-robin across entities, so truncating to `max_tasks` samples every class and
    many entities instead of the first entities by id."""
    tasks = []
    for e in sorted(entities, key=lambda e: e.entity_id):
        if e.method != "triangulated" or e.n_panos < 2:
            continue
        for pid, row, az, el, rh in _visible_views(
            e.point_enu, frames, intr, ref_lla, min_range_m, max_range_m
        ):
            if pid in set(e.pano_ids):
                continue
            tasks.append(
                ViewTask(
                    e.entity_id, e.cls, pid, int(row["cam_k"]), az, el, rh, row["observation_id"]
                )
            )
    if stratify:
        tasks = _round_robin_by_class(tasks)
    return tasks[:max_tasks] if max_tasks is not None else tasks


def _interleave(queues: Sequence[Sequence[Any]]) -> list[Any]:
    out: list[Any] = []
    for k in range(max((len(q) for q in queues), default=0)):
        out.extend(q[k] for q in queues if k < len(q))
    return out


def _round_robin_by_class(tasks: Sequence[ViewTask]) -> list[ViewTask]:
    by_cls: dict[str, dict[str, list[ViewTask]]] = defaultdict(lambda: defaultdict(list))
    for t in tasks:
        by_cls[t.cls][t.entity_id].append(t)
    per_cls = [
        _interleave([by_ent[e] for e in sorted(by_ent)]) for _, by_ent in sorted(by_cls.items())
    ]
    return _interleave(per_cls)


# The presence prompt accepts an object only inside the central third of the crop, so a
# confirmed offset can never exceed this fraction of the horizontal FOV.
SELECTION_BOUND_FRACTION = 1.0 / 6.0


def presence_prompt(cls: str) -> str:
    name = cls.replace("_", " ").lower()
    return (
        f"This is a rectified street-level photo crop. Is a {name} visible at or very near the "
        f"CENTRE of the image? Answer present=true only if a {name} is within the central third "
        "of the image. If present, give box_2d [ymin, xmin, ymax, xmax] on a 0-1000 scale for "
        "the one nearest the centre. Confidence is your probability (0-1)."
    )


async def cross_view_agreement(
    tasks: Sequence[ViewTask],
    render: Callable[[ViewTask], tuple | None],
    runner: Any,
    raise_if_all_failed: bool = True,
) -> dict[str, Any]:
    """Ask `PresenceCheck` on a code-rendered crop centred at each predicted bearing.

    `render(task)` returns (image, view) or (image, view, black_fraction), or None when the
    task cannot be rendered (it is then reported as not rendered and never sent)."""
    reqs, views, blacks, rendered = [], [], [], []
    for t in tasks:
        out = render(t)
        rendered.append(out is not None)
        if out is None:
            continue
        img, view = out[0], out[1]
        if len(out) > 2:
            blacks.append(float(out[2]))
        reqs.append(([presence_prompt(t.cls), img], schemas.PresenceCheck))
        views.append(view)
    answers = iter(await runner.ask_many(reqs, raise_if_all_failed=raise_if_all_failed))
    view_iter = iter(views)
    present, offsets, signed, per_task = [], [], [], []
    by_cls: dict[str, list[float]] = {}
    for t, ok in zip(tasks, rendered, strict=True):
        view, r = (next(view_iter), next(answers)) if ok else (None, None)
        rec = {
            "entity_id": t.entity_id,
            "pano_id": t.pano_id,
            "cls": t.cls,
            "rendered": ok,
            "answered": r is not None,
        }
        if r is not None:
            present.append(bool(r.present))
            rec["present"] = bool(r.present)

            if r.present and r.box_2d:
                x0, y0, x1, y1 = schemas.box_2d_to_pixels(r.box_2d, view.width, view.height)
                if t.cls in ent.GROUND_CONTACT:
                    cx, cy = (x0 + x1) / 2, y1
                else:
                    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                az, _ = view.pixel_to_bearing(cx, cy)
                s_off = float(geo.angdiff(float(az), t.az_deg))
                offset_m = float(t.range_m * math.tan(math.radians(abs(s_off))))

                # Check metrics gating
                offsets.append(abs(s_off))
                signed.append(s_off)
                by_cls.setdefault(t.cls, []).append(abs(s_off))
                rec["offset_deg"] = abs(s_off)
                rec["offset_m"] = offset_m
                rec["signed_offset_deg"] = s_off
        per_task.append(rec)
    return {
        "n_tasks": len(tasks),
        "n_unrenderable": rendered.count(False),
        "black_fraction_max": max(blacks) if blacks else math.nan,
        # offsets are bounded by the prompt's selection window, not a measured accuracy
        "selection_bound_deg": (
            max(v.hfov_deg for v in views) * SELECTION_BOUND_FRACTION if views else math.nan
        ),
        "n_asked": len(present),
        "confirmation_rate": float(np.mean(present)) if present else math.nan,
        "median_offset_deg": _pct(offsets, 50),
        # a systematic sign would point at a camera-model/heading bias, not detection noise
        "median_signed_offset_deg": _pct(signed, 50),
        "median_offset_deg_by_class": {c: _pct(v, 50) for c, v in sorted(by_cls.items())},
        "median_offset_m": _pct([r["offset_m"] for r in per_task if "offset_m" in r], 50),
        "per_task": per_task,
    }


def detection_stability(
    entities: Sequence[ent.Entity],
    frames: pd.DataFrame,
    intr: rosette.Intrinsics,
    ref_lla: Sequence[float],
    min_range_m: float = 3.0,
    max_range_m: float = 30.0,
) -> dict[str, float]:
    """Per class: mean over entities of |panos predicted visible AND assigned| / |predicted|."""
    per_cls: dict[str, list[float]] = defaultdict(list)
    for e in entities:
        vis = {
            v[0]
            for v in _visible_views(e.point_enu, frames, intr, ref_lla, min_range_m, max_range_m)
        }
        if vis:
            per_cls[e.cls].append(len(vis & set(e.pano_ids)) / len(vis))
    return {c: float(np.mean(v)) for c, v in sorted(per_cls.items())}


def match_passes(
    a: Sequence[ent.Entity],
    b: Sequence[ent.Entity],
    eps_by_class: Mapping[str, float] | None = None,
    multi_view_only: bool = False,
) -> dict[str, float]:
    """Hungarian matching of entities from two independent passes, per class, within eps.

    Unlocated entities have no position and are ignored. `multi_view_only` keeps entities
    seen from >= 2 panos (a single-view range from one box bottom is much noisier than a
    triangulation, so those are not expected to line up between passes)."""
    eps_map = {**ent.EPS_BY_CLASS, **(eps_by_class or {})}
    a, b = ent.located_entities(a), ent.located_entities(b)
    if multi_view_only:
        a = [e for e in a if e.n_panos >= 2]
        b = [e for e in b if e.n_panos >= 2]
    matched = 0
    for cls in sorted({e.cls for e in a} | {e.cls for e in b}):
        ea = [e for e in a if e.cls == cls]
        eb = [e for e in b if e.cls == cls]
        if not ea or not eb:
            continue
        pa = np.array([e.point_enu[:2] for e in ea])
        pb = np.array([e.point_enu[:2] for e in eb])
        d = np.linalg.norm(pa[:, None] - pb[None], axis=-1)
        r, c = linear_sum_assignment(d)
        matched += int(np.sum(d[r, c] <= eps_map.get(cls, ent.DEFAULT_EPS)))
    return {
        "n_a": float(len(a)),
        "n_b": float(len(b)),
        "matched": float(matched),
        "recall_a_in_b": matched / len(a) if a else math.nan,
        "recall_b_in_a": matched / len(b) if b else math.nan,
        "count_ratio": len(b) / len(a) if a else math.nan,
    }


async def self_consistency(
    entities: Sequence[ent.Entity],
    frames: pd.DataFrame,
    intr: rosette.Intrinsics,
    ref_lla: Sequence[float],
    render: Callable[[ViewTask], tuple[np.ndarray, rosette.PerspectiveView]],
    runner: Any,
    max_tasks: int | None = None,
    passes: tuple[Sequence[ent.Entity], Sequence[ent.Entity]] | None = None,
) -> dict[str, Any]:
    """9b bundle: cross-view agreement (Gemini), detection stability and repeat-pass matching."""
    tasks = predict_withheld_views(entities, frames, intr, ref_lla, max_tasks=max_tasks)
    out: dict[str, Any] = {"cross_view": await cross_view_agreement(tasks, render, runner)}
    out["stability"] = detection_stability(entities, frames, intr, ref_lla)
    if passes is not None:
        out["repeat_pass"] = match_passes(*passes)
        out["repeat_pass_multi_view"] = match_passes(*passes, multi_view_only=True)
    return out


# ----------------------------------------------------------------------------- hand labels

DISCRETE = {"HOUSE", "UTILITY_POLE", "ROAD_SIGN"}
SEGMENTS = {"ROAD_SEGMENT", "SIDEWALK_SEGMENT"}


def _iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def score_hand_labels(labels_csv: str | Path, pipeline_output: Sequence[Mapping[str, Any]]):
    """Score pipeline output against the optional hand-label kit; None if the file is absent.

    pipeline rows: {pano_id, view_yaw_deg, cls, box=(x0,y0,x1,y1), entity_id} for discrete
    detections, {pano_id, cls, material} for segments.
    """
    path = Path(labels_csv)
    if not path.is_file():
        return None
    with path.open(newline="") as f:
        labels = list(csv.DictReader(f))
    disc = [r for r in labels if r["class"] in DISCRETE and r["x0"]]
    preds = [p for p in pipeline_output if p.get("cls") in DISCRETE and p.get("box")]

    def key(pano, yaw, cls):
        return (str(pano), round(float(yaw)), cls)

    used, pairs = set(), []
    for lab in disc:
        box = tuple(float(lab[c]) for c in ("x0", "y0", "x1", "y1"))
        k = key(lab["pano_id"], lab["view_yaw_deg"], lab["class"])
        best, best_iou = None, 0.3
        for j, p in enumerate(preds):
            if j in used or key(p["pano_id"], p.get("view_yaw_deg", 0), p["cls"]) != k:
                continue
            iou = _iou(box, p["box"])
            if iou >= best_iou:
                best, best_iou = j, iou
        if best is not None:
            used.add(best)
            pairs.append((lab, preds[best]))
    out: dict[str, Any] = {
        "n_labels": len(disc),
        "detection_recall": len(pairs) / len(disc) if disc else math.nan,
        "detection_precision": len(pairs) / len(preds) if preds else math.nan,
    }
    keyed = [(lab, p) for lab, p in pairs if lab.get("object_key") and p.get("entity_id")]
    if keyed:
        pred = {f"m{i}": p["entity_id"] for i, (_, p) in enumerate(keyed)}
        truth = {f"m{i}": lab["object_key"] for i, (lab, _) in enumerate(keyed)}
        m = clustering_metrics(pred, truth)
        out["dedup_purity"], out["dedup_completeness"] = m["purity"], m["completeness"]
    # segments: keyed by (pano, class, side), present=false scored as ABSENT
    out.update(score_segment_labels(labels, pipeline_output))
    return out


# ----------------------------------------------------------------------------- label-kit scoring

SIDEWALK = "SIDEWALK_SEGMENT"
_ABSENT = "ABSENT"


def _truthy(v: Any) -> bool | None:
    s = str(v).strip().lower() if v is not None else ""
    if s in ("true", "1", "yes", "y"):
        return True
    if s in ("false", "0", "no", "n"):
        return False
    return None


def _slot_value(material: Any, present: Any) -> str | None:
    """Material (lower case), ABSENT, or None when the slot carries no usable value."""
    p = present if isinstance(present, bool) else _truthy(present)
    if p is False:
        return _ABSENT
    m = str(material).strip().lower() if material not in (None, "") else ""
    return m or None


def score_segment_labels(
    labels: Sequence[Mapping[str, Any]], predictions: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """UC3 metrics from label-kit rows keyed by (pano_id, class, side).

    Label rows: class ROAD_SEGMENT/SIDEWALK_SEGMENT, side, present, material. Prediction rows:
    pano_id, cls, side, and material or present=False. Returns material accuracy (slots
    present in both), sidewalk presence F1 and the side-swap rate (panos whose two sidewalk
    sides differ in the labels and whose predictions are exactly mirrored)."""

    def key(r, cls_key):
        return (str(r["pano_id"]), r[cls_key], str(r.get("side") or "CENTER"))

    lab = {
        key(r, "class"): _slot_value(r.get("material"), r.get("present"))
        for r in labels
        if r.get("class") in SEGMENTS
    }
    pred = {
        key(p, "cls"): _slot_value(p.get("material"), p.get("present", True))
        for p in predictions
        if p.get("cls") in SEGMENTS
    }
    lab = {k: v for k, v in lab.items() if v is not None}
    pred = {k: v for k, v in pred.items() if v is not None}
    both = sorted(set(lab) & set(pred))
    mat = [lab[k] == pred[k] for k in both if _ABSENT not in (lab[k], pred[k])]
    side = [k for k in both if k[1] == SIDEWALK]
    tp = sum(lab[k] != _ABSENT and pred[k] != _ABSENT for k in side)
    fp = sum(lab[k] == _ABSENT and pred[k] != _ABSENT for k in side)
    fn = sum(lab[k] != _ABSENT and pred[k] == _ABSENT for k in side)
    swaps, n_pairs = 0, 0
    for pano in sorted({k[0] for k in side}):
        kl, kr = (pano, SIDEWALK, "LEFT"), (pano, SIDEWALK, "RIGHT")
        if all(k in lab and k in pred for k in (kl, kr)) and lab[kl] != lab[kr]:
            n_pairs += 1
            swaps += pred[kl] == lab[kr] and pred[kr] == lab[kl]
    return {
        "n_slots": len(both),
        "n_material": len(mat),
        "material_accuracy": float(np.mean(mat)) if mat else math.nan,
        "sidewalk_presence_f1": 2 * tp / (2 * tp + fp + fn) if (tp + fp + fn) else math.nan,
        "side_swap_rate": swaps / n_pairs if n_pairs else math.nan,
    }


def _polyline_points(pts: Sequence[Sequence[float]], step: float = 1.0) -> np.ndarray:
    p = np.asarray(pts, float)
    out = [p[:1]]
    for a, b in zip(p[:-1], p[1:], strict=True):
        n = max(1, int(np.ceil(np.linalg.norm(b - a) / step)))
        out.append(a + (b - a) * (np.arange(1, n + 1)[:, None] / n))
    return np.concatenate(out)


def _point_to_polyline(q: np.ndarray, pts: Sequence[Sequence[float]]) -> np.ndarray:
    p = np.asarray(pts, float)
    best = np.full(len(q), np.inf)
    for a, b in zip(p[:-1], p[1:], strict=True):
        ab = b - a
        t = np.clip(((q - a) @ ab) / max(float(ab @ ab), 1e-12), 0.0, 1.0)
        best = np.minimum(best, np.linalg.norm(q - (a + t[:, None] * ab), axis=1))
    return best


def polyline_distance(a: Sequence[Sequence[float]], b: Sequence[Sequence[float]]) -> float:
    """Symmetric mean distance (px) between two polylines, sampled every pixel."""
    da = _point_to_polyline(_polyline_points(a), b).mean()
    db = _point_to_polyline(_polyline_points(b), a).mean()
    return float((da + db) / 2)


def score_roof_labels(
    labels: Sequence[Mapping[str, Any]],
    predictions: Sequence[Mapping[str, Any]],
    max_mean_dist_px: float = 5.0,
) -> dict[str, Any]:
    """UC4 metrics: edge precision/recall (same view and edge type, mean distance within
    `max_mean_dist_px`, one-to-one greedy by distance) and the validator's accept/reject
    confusion against those matches (a matched prediction is a true edge)."""
    labs = [
        (str(r["pano_id"]), round(float(r["view_yaw_deg"])), r["edge_type"],
         json.loads(r["points_json"]))
        for r in labels
        if r.get("class") == "ROOF_EDGE" and r.get("points_json")
    ]  # fmt: skip
    cands = []
    for i, (pid, yaw, et, pts) in enumerate(labs):
        for j, p in enumerate(predictions):
            same = (str(p["pano_id"]), round(float(p["view_yaw_deg"])), p["edge_type"])
            if same == (pid, yaw, et) and len(p["points"]) >= 2:
                d = polyline_distance(pts, p["points"])
                if d <= max_mean_dist_px:
                    cands.append((d, i, j))
    used_l, used_p = set(), set()
    for _, i, j in sorted(cands):
        if i not in used_l and j not in used_p:
            used_l.add(i)
            used_p.add(j)
    conf = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    for j, p in enumerate(predictions):
        true_edge, acc = j in used_p, bool(p.get("accepted"))
        conf[("tp" if true_edge else "fp") if acc else ("fn" if true_edge else "tn")] += 1
    return {
        "n_label_edges": len(labs),
        "n_pred_edges": len(predictions),
        "edge_recall": len(used_l) / len(labs) if labs else math.nan,
        "edge_precision": len(used_p) / len(predictions) if predictions else math.nan,
        "validator_confusion": conf,
    }


def bootstrap_ci(
    per_pano: Mapping[str, tuple[float, float]],
    n_boot: int = 1000,
    seed: int = 0,
    alpha: float = 0.05,
) -> tuple[float, float, float]:
    """(point, lo, hi) of the ratio sum(num) / sum(den) with a percentile bootstrap that
    resamples panos (views of one pano are correlated). NaNs when there is no data."""
    keys = sorted(per_pano)
    if not keys:
        return math.nan, math.nan, math.nan
    num = np.array([per_pano[k][0] for k in keys], float)
    den = np.array([per_pano[k][1] for k in keys], float)
    point = float(num.sum() / den.sum()) if den.sum() else math.nan
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(keys), (int(n_boot), len(keys)))
    d = den[idx].sum(1)
    stats = np.where(d > 0, num[idx].sum(1) / np.where(d > 0, d, 1.0), np.nan)
    lo, hi = np.nanpercentile(stats, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return point, float(min(lo, point)), float(max(hi, point))


def per_pano_counts(
    labels: Sequence[Mapping[str, Any]],
    predictions: Sequence[Mapping[str, Any]],
    scorer: Callable[..., Mapping[str, Any]],
    rate_key: str,
    n_key: str,
) -> dict[str, tuple[float, int]]:
    """{pano_id: (successes, trials)} for `bootstrap_ci`: `scorer` is run on each pano's
    labels and predictions alone, and successes = rate * trials (0 when there are no trials)."""
    out = {}
    for pano in sorted({str(r["pano_id"]) for r in labels}):
        lab = [r for r in labels if str(r["pano_id"]) == pano]
        pred = [p for p in predictions if str(p["pano_id"]) == pano]
        s = scorer(lab, pred)
        n = int(s[n_key])
        out[pano] = (float(s[rate_key]) * n if n else 0.0, n)
    return out
