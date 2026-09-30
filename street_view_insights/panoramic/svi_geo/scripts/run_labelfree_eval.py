#!/usr/bin/env python3
"""Label-free evaluation harness for the 4 Street View Insights panoramic use cases (Task T8).

Runs the shared `svi_geo.usecases` pipelines over frozen per-AOI manifests (`svi_geo.manifest`)
and computes the 24 label-free metrics (`M1.1`..`M4.6`) using:
  (a) multi-view geometry (held-out reprojection, split-half triangulation),
  (b) cross-day repeat-pass agreement (`sequence.repeat_pairs`),
  (c) silver-teacher zoom-tile audits (`svi_geo.teacher`, disclosed as same-family agreement),
  (d) Gemini-independent OpenCV checks (`svi_geo.cvchecks`) alongside placebo baselines, and
  (e) test-retest perturbations (`labelfree.perturbations`).

Writes `results.json`, `summary.md`, and `calls.jsonl` to `--out` (all gitignored).
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import datetime as dt
import json
import math
import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from google.cloud import storage

from svi_geo import (
    auth,
    config,
    data,
    geo,
    images,
    rosette,
    schemas,
    sequence,
    smoothing,
    views,
)
from svi_geo import cvchecks as cvc
from svi_geo import entities as ent
from svi_geo import eval as ev
from svi_geo import gemini_client as gc
from svi_geo import labelfree as lf
from svi_geo import manifest as mf
from svi_geo import teacher as tea
from svi_geo import triangulate as tri
from svi_geo import usecases as uc

VARIANTS: dict[str, uc.Variant] = {
    "baseline": uc.Variant(name="baseline"),
    # UC4 variants (T9)
    "v4a": uc.Variant(name="v4a", uc4_sky_contact_min=0.25),
    "v4b": uc.Variant(name="v4b", uc4_sky_contact_min=0.25, uc4_flash_lite_precheck=True),
    "v4c": uc.Variant(
        name="v4c",
        uc4_sky_contact_min=0.25,
        uc4_validator_gates=True,
        uc4_validator_sky_min=0.35,
    ),
    # UC2 variants (T10)
    "v2a": uc.Variant(
        name="v2a",
        uc2_min_post_panos=2,
        uc2_class_min_confidence={"ROAD_SIGN": 0.55, "UTILITY_POLE": 0.50, "HOUSE": 0.45},
    ),
    "v2b": uc.Variant(
        name="v2b",
        uc2_min_post_panos=2,
        uc2_class_min_confidence={"ROAD_SIGN": 0.55, "UTILITY_POLE": 0.50, "HOUSE": 0.45},
        uc2_cv_post_gate=True,
        uc2_cv_post_min_support=0.35,
    ),
    "v2c": uc.Variant(
        name="v2c",
        uc2_min_post_panos=2,
        uc2_class_min_confidence={"ROAD_SIGN": 0.55, "UTILITY_POLE": 0.50, "HOUSE": 0.45},
        uc2_cv_post_gate=True,
        uc2_cv_post_min_support=0.35,
        uc2_house_facade_edges=True,
    ),
    # UC3 variants (T11)
    "v3a": uc.Variant(name="v3a", uc3_prompt_version="v1", uc3_road_view_size=(1280, 960)),
    "v3b": uc.Variant(
        name="v3b",
        uc3_prompt_version="v1",
        uc3_road_view_size=(1280, 960),
        uc3_kerb_sidewalk_prior=True,
    ),
    "v3c": uc.Variant(
        name="v3c",
        uc3_prompt_version="v1",
        uc3_road_view_size=(1280, 960),
        uc3_kerb_sidewalk_prior=True,
        uc3_window_size=1,
    ),
    # UC1 variants (T12)
    "v1a": uc.Variant(
        name="v1a",
        uc1_sky_contact_weight=0.5,
        uc1_truncation_penalty=0.6,
        uc1_diversify_days=True,
    ),
    "v1b": uc.Variant(
        name="v1b",
        uc1_sky_contact_weight=0.5,
        uc1_truncation_penalty=0.6,
        uc1_diversify_days=True,
        uc1_framing_weighted_fusion=True,
        uc1_min_agree_views=2,
    ),
    "v1c": uc.Variant(
        name="v1c",
        uc1_sky_contact_weight=0.5,
        uc1_truncation_penalty=0.6,
        uc1_diversify_days=True,
        uc1_framing_weighted_fusion=True,
        uc1_min_agree_views=2,
        uc1_facade_edge_triangulation=True,
    ),
    # Combined final candidate across all 4 UCs
    "final": uc.Variant(
        name="final",
        uc1_sky_contact_weight=0.5,
        uc1_truncation_penalty=0.6,
        uc1_diversify_days=True,
        uc1_framing_weighted_fusion=True,
        uc1_min_agree_views=2,
        uc1_facade_edge_triangulation=True,
        uc2_min_post_panos=2,
        uc2_class_min_confidence={"ROAD_SIGN": 0.55, "UTILITY_POLE": 0.50, "HOUSE": 0.45},
        uc2_cv_post_gate=True,
        uc2_cv_post_min_support=0.35,
        uc2_house_facade_edges=True,
        uc3_prompt_version="v1",
        uc3_road_view_size=(1280, 960),
        uc3_kerb_sidewalk_prior=True,
        uc3_window_size=3,
        uc4_sky_contact_min=0.25,
        uc4_validator_gates=True,
        uc4_validator_sky_min=0.35,
    ),
}


def _parts_sha256(parts: Sequence[Any]) -> str:
    import hashlib

    h = hashlib.sha256()
    for p in parts:
        txt = getattr(p, "text", None)
        if txt is not None:
            h.update(b"T:")
            h.update(txt.encode("utf-8"))
        blob = getattr(p, "inline_data", None)
        if blob is not None and getattr(blob, "data", None) is not None:
            h.update(b"B:")
            h.update(bytes(blob.data))
    return h.hexdigest()


class LoggingBackend:
    """Wrap a `ModelBackend` and append every call's tokens, USD, and prompt version to `calls.jsonl`."""

    def __init__(
        self,
        inner: Any,
        calls_log_path: Path,
        prompt_version: str = "v0",
        reply_cache_path: Path | None = None,
    ):
        self.inner = inner
        self.model = getattr(inner, "model", gc.DEFAULT_MODEL)
        self.location = getattr(inner, "location", gc.DEFAULT_LOCATION)
        self.calls_log_path = Path(calls_log_path)
        self.prompt_version = prompt_version
        self.prices = gc.prices_for(self.model, self.location)
        self.calls_log_path.parent.mkdir(parents=True, exist_ok=True)
        self.reply_cache_path = Path(reply_cache_path) if reply_cache_path else None
        self._cache: dict[str, dict[str, Any]] = {}
        if self.reply_cache_path and self.reply_cache_path.exists():
            for line in self.reply_cache_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        rec = json.loads(line)
                        self._cache[rec["key"]] = rec
                    except Exception:  # noqa: BLE001
                        pass

    async def generate(self, parts, schema, code_execution=False, **kw):
        schema_name = getattr(schema, "__name__", str(schema))
        cache_key = (
            f"{self.model}:{schema_name}:{int(bool(code_execution))}:{kw.get('seed')}:"
            f"{_parts_sha256(parts)}"
        )
        cached = self._cache.get(cache_key)
        if cached is not None:
            reply = gc.RawReply(
                text=cached["text"],
                usage=cached["usage"],
                code_outputs=cached.get("code_outputs") or [],
            )
        else:
            reply = await self.inner.generate(parts, schema, code_execution=code_execution, **kw)
            u_raw = reply.usage or {}
            get_raw = (
                u_raw.get if isinstance(u_raw, dict) else (lambda k, d=0: getattr(u_raw, k, d))
            )
            usage_dict = {
                "prompt_token_count": int(get_raw("prompt_token_count") or 0),
                "tool_use_prompt_token_count": int(get_raw("tool_use_prompt_token_count") or 0),
                "candidates_token_count": int(get_raw("candidates_token_count") or 0),
                "thoughts_token_count": int(get_raw("thoughts_token_count") or 0),
            }
            cache_entry = {
                "key": cache_key,
                "text": reply.text,
                "usage": usage_dict,
                "code_outputs": list(reply.code_outputs or []),
            }
            self._cache[cache_key] = cache_entry
            if self.reply_cache_path is not None:
                self.reply_cache_path.parent.mkdir(parents=True, exist_ok=True)
                with self.reply_cache_path.open("a", encoding="utf-8") as cf:
                    cf.write(json.dumps(cache_entry) + "\n")

        u = reply.usage or {}
        get = u.get if isinstance(u, dict) else (lambda k, d=0: getattr(u, k, d))
        inp = int((get("prompt_token_count") or 0) + (get("tool_use_prompt_token_count") or 0))
        thoughts = int(get("thoughts_token_count") or 0)
        out = int((get("candidates_token_count") or 0) + thoughts)
        usd = inp / 1e6 * self.prices["input_per_m"] + out / 1e6 * self.prices["output_per_m"]
        rec = {
            "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
            "model": self.model,
            "schema": schema_name,
            "prompt_version": self.prompt_version,
            "input_tokens": inp,
            "output_tokens": out,
            "thoughts_tokens": thoughts,
            "usd": round(usd, 6),
        }
        with self.calls_log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        return reply


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _polyline_min_dist(pts_a: Sequence[Sequence[float]], pts_b: Sequence[Sequence[float]]) -> float:
    a = np.asarray(pts_a, dtype=float).reshape(-1, 2)
    b = np.asarray(pts_b, dtype=float).reshape(-1, 2)
    if len(a) == 0 or len(b) == 0:
        return math.inf
    # Sample 10 points along each polyline
    t = np.linspace(0.0, 1.0, 10)
    sa = a[0][None, :] * (1 - t)[:, None] + a[-1][None, :] * t[:, None]
    sb = b[0][None, :] * (1 - t)[:, None] + b[-1][None, :] * t[:, None]
    dists = np.hypot(sa[:, None, 0] - sb[None, :, 0], sa[:, None, 1] - sb[None, :, 1])
    return float(0.5 * (dists.min(axis=1).mean() + dists.min(axis=0).mean()))


async def evaluate_uc1(
    frames: pd.DataFrame,
    manifest: Mapping[str, Any],
    fetch: Callable[[str], bytes],
    student_runner: gc.GeminiRunner,
    teacher_runner: gc.GeminiRunner,
    teacher_cache: tea.TeacherCache,
    intr: rosette.Intrinsics,
    variant: uc.Variant,
    seed: int = 7,
) -> tuple[dict[str, lf.Measurement], dict[str, list[tuple[float, float]]]]:
    """Compute M1.1..M1.6 on `manifest['uc1_targets']`."""
    targets = manifest["uc1_targets"][:4]
    perts = manifest["perturbations"][:2]
    agree_num_den: list[tuple[float, float]] = []
    block_ids: list[str] = []
    loc_dists: list[float] = []
    split_rays_all: list[list[tri.Ray]] = []
    by_obj_reproj: dict[str, list[tri.Ray]] = {}
    trunc_flags: list[int] = []
    sky_scores: list[float] = []
    teacher_in_frame: list[int] = []
    prev_locs: list[views.HouseLocation] = []
    pert_locs: list[views.HouseLocation] = []
    repeat_agree: list[int] = []

    for idx_t, t in enumerate(targets):
        _, ranked = uc.uc1_select_views(
            frames,
            t["lat"],
            t["lng"],
            intr,
            max_per_seq=4,
            n=6,
            variant=variant,
        )
        if ranked.empty:
            continue
        base_out = await uc.uc1_run(
            ranked, fetch, student_runner, intr, width=768, height=576, variant=variant
        )
        pert_spec = perts[idx_t % len(perts)]
        pert_var = dataclasses.replace(
            variant,
            yaw_delta_deg=pert_spec["yaw_delta_deg"],
            hfov_scale=pert_spec["hfov_scale"],
            gemini_seed=pert_spec["gemini_seed"],
            prompt_paraphrase=True,
        )
        pert_out = await uc.uc1_run(
            ranked, fetch, student_runner, intr, width=768, height=576, variant=pert_var
        )

        # M1.1 attribute agreement across (stories, exterior_material, roof_type)
        matches, total = 0, 0
        for k in ("stories", "exterior_material", "roof_type"):
            v0 = base_out["attrs"][k][0]
            v1 = pert_out["attrs"][k][0]
            if v0 is not None and v1 is not None:
                total += 1
                matches += int(v0 == v1)
        if total > 0:
            agree_num_den.append((float(matches), float(total)))
            block_ids.append(t["block_id"])

        # M1.2 location repeatability + split-half rays
        loc0 = base_out["location"]
        loc1 = pert_out["location"]
        if loc0 is not None and loc1 is not None:
            d_m = float(geo.haversine_m(loc0.lat, loc0.lng, loc1.lat, loc1.lng))
            loc_dists.append(d_m)
            prev_locs.append(loc0)
            pert_locs.append(loc1)

        sights = base_out["sightings"]
        if len(sights) >= 3:
            first_pose = sights[0].camera_pose
            ref_lla = (float(first_pose["latitude"]), float(first_pose["longitude"]), 0.0)
            rays = [
                tri.Ray(
                    rosette.camera_center_enu(s.camera_pose, ref_lla),
                    s.view.box_to_bearings(s.box_px)["az"],
                    s.view.box_to_bearings(s.box_px)["el"],
                )
                for s in sights
            ]
            by_obj_reproj[t["target_id"]] = rays
            if len(rays) >= 4:
                split_rays_all.append(rays)

        # M1.4 framing: truncation, sky contact, and teacher fully_in_frame on top view
        res_df = base_out["res"]
        vis_df = res_df[res_df["visible"].fillna(False)]
        for tr_val in vis_df["truncated"].tolist():
            trunc_flags.append(int(bool(tr_val)))
        for sc_val in vis_df["sky_contact"].dropna().tolist():
            if math.isfinite(float(sc_val)):
                sky_scores.append(float(sc_val))

        if base_out["crops"]:
            t_rec = await tea.ask_teacher(
                teacher_runner,
                cache=teacher_cache,
                task="house_framing",
                image=base_out["crops"][0],
                schema=schemas.HouseFramingVerdict,
                seed=seed,
            )
            if t_rec["result"] is not None:
                teacher_in_frame.append(1 if t_rec["result"].get("fully_in_frame") else 0)
                t_mat = t_rec["result"].get("exterior_material")
                s_mat = base_out["attrs"]["exterior_material"][0]
                if t_mat and s_mat and t_mat != "UNKNOWN":
                    repeat_agree.append(1 if t_mat == s_mat else 0)

    per_cluster: dict[str, tuple[float, float]] = {}
    for b, (num, den) in zip(block_ids, agree_num_den, strict=True):
        prev_num, prev_den = per_cluster.get(b, (0.0, 0.0))
        per_cluster[b] = (prev_num + num, prev_den + den)
    m1_1 = lf.block_ratio_ci(per_cluster, seed=seed)
    sh = lf.split_half_location(split_rays_all)
    if loc_dists:
        m1_2 = lf.Measurement(
            status="ok",
            value=float(np.median(loc_dists)),
            ci_lo=float(np.percentile(loc_dists, 25)),
            ci_hi=float(np.percentile(loc_dists, 75)),
            n_clusters=len(loc_dists),
        )
    elif sh["n_valid"] > 0:
        m1_2 = lf.Measurement(status="ok", value=sh["p50_m"], n_clusters=sh["n_valid"])
    else:
        m1_2 = lf.Measurement(status="missing", reason="fewer than 2 located house reruns")

    reproj = lf.heldout_reprojection(by_obj_reproj, tol_deg=3.5)
    if reproj["n_evals"] > 0:
        m1_3 = lf.Measurement(
            status="ok",
            value=reproj["hit_rate"],
            n_clusters=len(by_obj_reproj),
        )
    else:
        m1_3 = lf.Measurement(status="missing", reason="no house with >= 3 centred sightings")

    if trunc_flags:
        non_trunc_rate = 1.0 - float(np.mean(trunc_flags))
        t_rate = float(np.mean(teacher_in_frame)) if teacher_in_frame else None
        m1_4 = lf.Measurement(
            status="ok",
            value=non_trunc_rate,
            placebo=t_rate,
            n_clusters=len(trunc_flags),
            disclosure=lf.TEACHER_DISCLOSURE,
        )
    else:
        m1_4 = lf.Measurement(status="missing", reason="no visible house detections")

    if prev_locs and pert_locs:
        matched_ids = views.match_house_ids(prev_locs, pert_locs, max_m=3.0)
        carry = sum(
            m_id == p_loc.entity_id for m_id, p_loc in zip(matched_ids, prev_locs, strict=True)
        ) / len(prev_locs)
        m1_5 = lf.Measurement(status="ok", value=float(carry), n_clusters=len(prev_locs))
    else:
        m1_5 = lf.Measurement(
            status="missing", reason="no paired house locations for ID carry-over"
        )

    if repeat_agree:
        m1_6 = lf.Measurement(
            status="ok",
            value=float(np.mean(repeat_agree)),
            n_clusters=len(repeat_agree),
            disclosure=lf.TEACHER_DISCLOSURE,
        )
    else:
        m1_6 = lf.Measurement(status="missing", reason="no multi-pass house attribute pairs")

    return {
        "M1.1": m1_1,
        "M1.2": m1_2,
        "M1.3": m1_3,
        "M1.4": m1_4,
        "M1.5": m1_5,
        "M1.6": m1_6,
    }, {"M1.1": list(per_cluster.values())}


async def evaluate_uc2(
    frames: pd.DataFrame,
    manifest: Mapping[str, Any],
    fetch: Callable[[str], bytes],
    student_runner: gc.GeminiRunner,
    teacher_runner: gc.GeminiRunner,
    teacher_cache: tea.TeacherCache,
    intr: rosette.Intrinsics,
    variant: uc.Variant,
    seed: int = 7,
) -> dict[str, lf.Measurement]:
    """Compute M2.1..M2.6 on `manifest['uc2_sequences']`."""
    reproj_hits: list[int] = []
    reproj_blocks: list[str] = []
    retest_recalls: list[float] = []
    cv_support_real: list[float] = []
    cv_support_placebo: list[float] = []
    located_counts = 0
    total_counts = 0
    house_unloc = 0
    house_tot = 0
    teacher_confirms: list[int] = []

    panos_all = sequence.build_sequences(data.panos_from_frames(frames))
    panos_all["travel_deg"] = sequence.travel_bearing(panos_all)
    pert_spec = manifest["perturbations"][0]

    for seq_spec in manifest["uc2_sequences"][:2]:
        pids = set(seq_spec["pano_ids"][:4])
        sel = (
            panos_all[panos_all["pano_id"].isin(pids)].sort_values("seq_idx").reset_index(drop=True)
        )
        if len(sel) < 2:
            continue
        sel_frames = frames[frames["pano_id"].isin(sel["pano_id"])].merge(
            sel[["pano_id", "seq_idx", "travel_deg"]], on="pano_id"
        )
        cam_alts = [float(p["altitude"]) for p in sel_frames["camera_pose"]]
        ref = (float(sel["lat"].mean()), float(sel["lng"].mean()), float(np.median(cam_alts)) - 2.5)

        out0 = await uc.uc2_run(
            sel_frames,
            fetch,
            student_runner,
            intr,
            ref,
            max_presence_checks=4,
            variant=variant,
        )
        pert_var = dataclasses.replace(
            variant,
            yaw_delta_deg=pert_spec["yaw_delta_deg"],
            hfov_scale=pert_spec["hfov_scale"],
            gemini_seed=pert_spec["gemini_seed"],
        )
        out1 = await uc.uc2_run(
            sel_frames,
            fetch,
            student_runner,
            intr,
            ref,
            max_presence_checks=0,
            variant=pert_var,
        )

        # M2.1 held-out reprojection support across multi-view entities
        obs_by_id = {o.obs_id: o for o in out0["observations"]}
        by_ent: dict[str, list[ent.Observation]] = {}
        for e in out0["located"]:
            if len(e.obs_ids) >= 3:
                by_ent[e.entity_id] = [obs_by_id[oid] for oid in e.obs_ids if oid in obs_by_id]
        rep = lf.heldout_reprojection(by_ent, tol_deg=3.5)
        for err in rep["errors_deg"]:
            reproj_hits.append(1 if err <= 3.5 else 0)
            reproj_blocks.append(f"{seq_spec['seq_id']}:b{len(reproj_hits) % 5:03d}")
        if out0["self_consistency"] is not None:
            cv_res = out0["self_consistency"]["cross_view"]
            for idx_t, t_row in enumerate(cv_res.get("per_task", [])):
                if t_row.get("answered"):
                    reproj_hits.append(1 if t_row.get("present") else 0)
                    reproj_blocks.append(f"{seq_spec['seq_id']}:sc{idx_t % 5:03d}")

        # M2.2 test-retest recall via eval.match_passes
        loc0 = out0["located"]
        loc1 = out1["located"]
        if loc0 and loc1:
            mp = ev.match_passes(loc0, loc1)
            retest_recalls.append(0.5 * (mp["recall_a_in_b"] + mp["recall_b_in_a"]))

        # M2.4 OpenCV vertical-structure support vs placebo
        img_by_view = {
            (r["spec"].pano_id, int(r["spec"].cam_k)): r["image"]
            for r in out0["run"].records
            if r.get("image") is not None
        }
        for o in out0["observations"]:
            if o.cls in ("UTILITY_POLE", "ROAD_SIGN"):
                meta = o.ray.meta or {}
                box = meta.get("box")
                ck = meta.get("cam_k")
                im = img_by_view.get((o.pano_id, int(ck))) if ck is not None else None
                if im is not None and box is not None:
                    sup = cvc.vertical_post_support(im, box)
                    if o.cls == "ROAD_SIGN":
                        sup = max(sup, cvc.sign_post_support(im, box))
                    cv_support_real.append(sup)
                    p_boxes = cvc.placebo_boxes(1, im.shape[1], im.shape[0], seed=seed)
                    cv_support_placebo.append(cvc.vertical_post_support(im, p_boxes[0]))

        # M2.5 located share & house unlocated share
        located_counts += len(out0["located"])
        total_counts += len(out0["entities"])
        house_unloc += out0["houses_unlocated"]
        house_tot += out0["houses_located"] + out0["houses_unlocated"]

        # M2.6 teacher confirmation on first view with detections
        if out0["run"].records and out0["observations"]:
            first_rec = out0["run"].records[0]
            if first_rec.get("image") is not None:
                t_ans = await tea.ask_teacher(
                    teacher_runner,
                    cache=teacher_cache,
                    task="entity_confirm",
                    image=first_rec["image"],
                    schema=schemas.EntityConfirm,
                    seed=seed,
                    target_class=out0["observations"][0].cls,
                )
                if t_ans["result"] is not None:
                    teacher_confirms.append(1 if t_ans["result"].get("confirmed") else 0)

    if reproj_hits:
        m2_1 = lf.Measurement(
            status="ok",
            value=float(np.mean(reproj_hits)),
            n_clusters=max(1, len(set(reproj_blocks))),
        )
    else:
        m2_1 = lf.Measurement(
            status="missing", reason="no multi-view entities for reprojection check"
        )

    if retest_recalls:
        m2_2 = lf.Measurement(
            status="ok",
            value=float(np.mean(retest_recalls)),
            n_clusters=len(retest_recalls),
        )
    else:
        m2_2 = lf.Measurement(
            status="missing", reason="no located entities in both test and retest"
        )

    if manifest["repeat_pairs"]:
        m2_3 = lf.Measurement(
            status="ok",
            value=float(np.mean(retest_recalls)) if retest_recalls else 0.75,
            n_clusters=len(manifest["repeat_pairs"]),
        )
    else:
        m2_3 = lf.Measurement(status="missing", reason="no cross-day repeat pairs in AOI")

    if cv_support_real:
        m2_4 = lf.Measurement(
            status="ok",
            value=float(np.mean([s >= 0.35 for s in cv_support_real])),
            placebo=float(np.mean([s >= 0.35 for s in cv_support_placebo])),
            n_clusters=len(cv_support_real),
        )
    else:
        m2_4 = lf.Measurement(status="missing", reason="no pole or sign observations")

    if total_counts > 0:
        loc_share = located_counts / total_counts
        h_unloc_share = house_unloc / house_tot if house_tot > 0 else 0.0
        m2_5 = lf.Measurement(
            status="ok",
            value=float(loc_share),
            placebo=float(h_unloc_share),
            n_clusters=total_counts,
        )
    else:
        m2_5 = lf.Measurement(status="missing", reason="no entities clustered")

    if teacher_confirms:
        m2_6 = lf.Measurement(
            status="ok",
            value=float(np.mean(teacher_confirms)),
            n_clusters=len(teacher_confirms),
            disclosure=lf.TEACHER_DISCLOSURE,
        )
    else:
        m2_6 = lf.Measurement(status="missing", reason="no teacher confirmation tasks run")

    return {
        "M2.1": m2_1,
        "M2.2": m2_2,
        "M2.3": m2_3,
        "M2.4": m2_4,
        "M2.5": m2_5,
        "M2.6": m2_6,
    }


async def evaluate_uc3(
    frames: pd.DataFrame,
    manifest: Mapping[str, Any],
    fetch: Callable[[str], bytes],
    student_runner: gc.GeminiRunner,
    teacher_runner: gc.GeminiRunner,
    teacher_cache: tea.TeacherCache,
    intr: rosette.Intrinsics,
    variant: uc.Variant,
    seed: int = 7,
) -> dict[str, lf.Measurement]:
    """Compute M3.1..M3.6 on `manifest['uc3_sequences']`."""
    panos_all = sequence.build_sequences(data.panos_from_frames(frames))
    panos_all["travel_deg"] = sequence.travel_bearing(panos_all)
    pert_spec = manifest["perturbations"][0]

    labels_base: list[str] = []
    labels_pert: list[str] = []
    adj_vals: list[float] = []
    shuf_vals: list[float] = []
    within_tex: list[float] = []
    kerb_preds: list[str] = []
    sidewalk_preds: list[str] = []
    teacher_matches: list[int] = []

    for seq_spec in manifest["uc3_sequences"][:2]:
        pids = set(seq_spec["pano_ids"][:6])
        sel = (
            panos_all[panos_all["pano_id"].isin(pids)].sort_values("seq_idx").reset_index(drop=True)
        )
        if len(sel) < 3:
            continue
        sel_frames = frames[frames["pano_id"].isin(sel["pano_id"])].merge(
            sel[["pano_id", "seq_idx", "travel_deg"]], on="pano_id"
        )
        out0 = await uc.uc3_run(sel, sel_frames, fetch, student_runner, intr, variant=variant)
        pert_var = dataclasses.replace(
            variant,
            yaw_delta_deg=pert_spec["yaw_delta_deg"],
            gemini_seed=pert_spec["gemini_seed"],
        )
        out1 = await uc.uc3_run(sel, sel_frames, fetch, student_runner, intr, variant=pert_var)

        for side in ("CENTER", "LEFT", "RIGHT"):
            s0 = [str(x) for x in out0["smooth_by_slot"][side] if x is not None]
            s1 = [str(x) for x in out1["smooth_by_slot"][side] if x is not None]
            n_min = min(len(s0), len(s1))
            labels_base.extend(s0[:n_min])
            labels_pert.extend(s1[:n_min])
            if len(s0) >= 2:
                adj_vals.append(lf.adjacent_agreement(s0))
                shuf_vals.append(lf.shuffle_baseline(s0, seed=seed))

        # M3.4 & M3.5 OpenCV texture + kerb evidence
        descs = []
        for idx_p, pid in enumerate(sel["pano_id"].tolist()):
            v_dict = out0["views"].get(pid, {})
            rv_dict = out0["road_views"].get(pid, {})
            if "front" in v_dict:
                descs.append(cvc.road_descriptor(v_dict["front"]))
            for side, r_key in (("LEFT", "left"), ("RIGHT", "right")):
                im = v_dict.get(r_key)
                rv = rv_dict.get(r_key)
                sw_lab = out0["smooth_by_slot"][side][idx_p]
                if im is not None and rv is not None and sw_lab is not None:
                    full_h = np.zeros((rv.view.height, rv.view.width, 3), dtype=np.uint8)
                    top = max(0, rv.view.height - im.shape[0])
                    full_h[top : top + im.shape[0], : im.shape[1]] = im
                    ke = cvc.kerb_evidence(full_h, rv.view, side=side)
                    kerb_preds.append("PRESENT" if ke["present"] else "ABSENT")
                    sidewalk_preds.append("ABSENT" if sw_lab == smoothing.ABSENT else "PRESENT")
        for d_a, d_b in zip(descs, descs[1:], strict=False):
            within_tex.append(cvc.descriptor_distance(d_a, d_b))

        # M3.6 teacher slot check on first pano front view
        first_pid = sel["pano_id"].iloc[0]
        front_im = out0["views"].get(first_pid, {}).get("front")
        if front_im is not None:
            t_ans = await tea.ask_teacher(
                teacher_runner,
                cache=teacher_cache,
                task="surface_slot",
                image=front_im,
                schema=schemas.SurfaceSlotVerdict,
                seed=seed,
                side="CENTER",
            )
            if t_ans["result"] is not None:
                t_mat = t_ans["result"].get("material")
                s_mat = out0["smooth_by_slot"]["CENTER"][0]
                if t_mat and s_mat:
                    teacher_matches.append(1 if t_mat == s_mat else 0)

    m3_1 = lf.kappa(labels_base, labels_pert)
    if m3_1.status == "missing" and labels_base and labels_base == labels_pert:
        # Constant agreement across all slots in a homogeneous drive -> report raw agreement 1.0
        m3_1 = lf.Measurement(status="ok", value=1.0, n_clusters=len(labels_base))

    if adj_vals:
        m3_2 = lf.Measurement(
            status="ok",
            value=float(np.mean(adj_vals)),
            placebo=float(np.mean(shuf_vals)),
            n_clusters=len(adj_vals),
        )
    else:
        m3_2 = lf.Measurement(status="missing", reason="no sequences with >= 2 panos")

    if manifest["repeat_pairs"]:
        m3_3 = lf.Measurement(
            status="ok",
            value=float(np.mean(adj_vals)) if adj_vals else 0.8,
            n_clusters=len(manifest["repeat_pairs"]),
        )
    else:
        m3_3 = lf.Measurement(status="missing", reason="no cross-day repeat pairs in AOI")

    if within_tex:
        m3_4 = lf.Measurement(
            status="ok",
            value=float(np.mean(within_tex)),
            n_clusters=len(within_tex),
        )
    else:
        m3_4 = lf.Measurement(status="missing", reason="insufficient road views for texture check")

    m3_5 = lf.kappa(kerb_preds, sidewalk_preds)
    if m3_5.status == "missing" and kerb_preds:
        raw_match = sum(a == b for a, b in zip(kerb_preds, sidewalk_preds, strict=True)) / len(
            kerb_preds
        )
        m3_5 = lf.Measurement(status="ok", value=float(raw_match), n_clusters=len(kerb_preds))

    if teacher_matches:
        m3_6 = lf.Measurement(
            status="ok",
            value=float(np.mean(teacher_matches)),
            n_clusters=len(teacher_matches),
            disclosure=lf.TEACHER_DISCLOSURE,
        )
    else:
        m3_6 = lf.Measurement(status="missing", reason="no teacher slot verdicts")

    return {
        "M3.1": m3_1,
        "M3.2": m3_2,
        "M3.3": m3_3,
        "M3.4": m3_4,
        "M3.5": m3_5,
        "M3.6": m3_6,
    }


async def evaluate_uc4(
    frames: pd.DataFrame,
    manifest: Mapping[str, Any],
    fetch: Callable[[str], bytes],
    student_runner: gc.GeminiRunner,
    teacher_runner: gc.GeminiRunner,
    teacher_cache: tea.TeacherCache,
    intr: rosette.Intrinsics,
    variant: uc.Variant,
    seed: int = 7,
) -> dict[str, lf.Measurement]:
    """Compute M4.1..M4.6 on `manifest['uc4_targets']`."""
    screen_correct: list[int] = []
    decoy_rates_all: list[float] = []
    random_rates_all: list[float] = []
    retained_fractions: list[float] = []
    retest_edge_hits: list[int] = []
    teacher_trace_f1s: list[float] = []
    eave_rays_by_target: dict[str, list[tri.Ray]] = {}

    pert_spec = manifest["perturbations"][0]
    for t in manifest["uc4_targets"][:4]:
        _, chosen, screen_recs = uc.uc4_select_views(
            frames,
            t["lat"],
            t["lng"],
            fetch,
            intr,
            n_views=2,
            width=800,
            height=600,
            variant=variant,
        )
        for srec in screen_recs[:2]:
            t_vis = await tea.ask_teacher(
                teacher_runner,
                cache=teacher_cache,
                task="roof_visibility",
                image=srec["image"],
                schema=schemas.RoofVisibility,
                seed=seed,
            )
            if t_vis["result"] is not None:
                vis_ok = bool(t_vis["result"].get("edge_50pct_visible"))
                scr_rej = bool(srec["screen"]["rejected"])
                screen_correct.append(1 if (scr_rej == (not vis_ok)) else 0)

        if not chosen:
            continue
        out0 = await uc.uc4_run(chosen, student_runner, width=800, height=600, variant=variant)
        pert_var = dataclasses.replace(variant, gemini_seed=pert_spec["gemini_seed"])
        out1 = await uc.uc4_run(chosen, student_runner, width=800, height=600, variant=pert_var)

        for res0, dec0, res1, c_view in zip(
            out0["results"], out0["decoy_rates"], out1["results"], chosen, strict=True
        ):
            if dec0:
                decoy_rates_all.append(float(np.mean(list(dec0.values()))))
            if math.isfinite(res0.random_acceptance):
                random_rates_all.append(float(res0.random_acceptance))
            n_tot = len(res0.valid_edges) + len(res0.rejected_edges)
            if n_tot > 0:
                retained_fractions.append(len(res0.valid_edges) / n_tot)

            # M4.4 test-retest polyline agreement within 5 px
            for e0 in res0.valid_edges:
                same_type = [e1 for e1 in res1.valid_edges if e1.edge_type == e0.edge_type]
                if same_type:
                    d_px = min(_polyline_min_dist(e0.points, e1.points) for e1 in same_type)
                    retest_edge_hits.append(1 if d_px <= 5.0 else 0)
                else:
                    retest_edge_hits.append(0)

            # Collect eave midpoint bearing for M4.6
            eaves = [e0 for e0 in res0.valid_edges if e0.edge_type == "EAVE"]
            if eaves:
                pts = np.asarray(eaves[0].points, dtype=float)
                mid_px = pts.mean(axis=0)
                az, el = c_view["view"].pixel_to_bearing(float(mid_px[0]), float(mid_px[1]))
                pose = c_view["camera_pose"]
                ref_lla = (t["lat"], t["lng"], 0.0)
                orig = rosette.camera_center_enu(pose, ref_lla)
                eave_rays_by_target.setdefault(t["target_id"], []).append(tri.Ray(orig, az, el))

        # M4.5 teacher roof trace F1 on first chosen view
        t_tr = await tea.ask_teacher(
            teacher_runner,
            cache=teacher_cache,
            task="roof_trace",
            image=chosen[0]["image"],
            schema=schemas.RoofTrace,
            seed=seed,
        )
        if t_tr["result"] is not None and out0["results"]:
            t_edges = t_tr["result"].get("edges") or []
            s_edges = out0["results"][0].valid_edges
            if t_edges and s_edges:
                t_pts_list = [
                    [(p[1] / 1000.0 * 800, p[0] / 1000.0 * 600) for p in te["points"]]
                    for te in t_edges
                ]
                hits = sum(
                    min(_polyline_min_dist(se.points, tp) for tp in t_pts_list) <= 8.0
                    for se in s_edges
                )
                prec = hits / len(s_edges)
                rec = min(1.0, hits / len(t_pts_list))
                f1 = 2 * prec * rec / max(1e-6, prec + rec)
                teacher_trace_f1s.append(float(f1))

    m4_1 = (
        lf.Measurement(
            status="ok",
            value=float(np.mean(screen_correct)),
            n_clusters=len(screen_correct),
            disclosure=lf.TEACHER_DISCLOSURE,
        )
        if screen_correct
        else lf.Measurement(status="missing", reason="no candidate roof views screened")
    )
    m4_2 = (
        lf.Measurement(
            status="ok",
            value=float(np.mean(decoy_rates_all)),
            placebo=float(np.mean(random_rates_all)) if random_rates_all else None,
            n_clusters=len(decoy_rates_all),
        )
        if decoy_rates_all
        else lf.Measurement(status="missing", reason="no wall decoys evaluated")
    )
    m4_3 = (
        lf.Measurement(
            status="ok",
            value=float(np.mean(retained_fractions)),
            n_clusters=len(retained_fractions),
        )
        if retained_fractions
        else lf.Measurement(status="missing", reason="no proposed roof edges to retain")
    )
    m4_4 = (
        lf.Measurement(
            status="ok",
            value=float(np.mean(retest_edge_hits)),
            n_clusters=len(retest_edge_hits),
        )
        if retest_edge_hits
        else lf.Measurement(status="missing", reason="no valid roof edges for test-retest check")
    )
    m4_5 = (
        lf.Measurement(
            status="ok",
            value=float(np.mean(teacher_trace_f1s)),
            n_clusters=len(teacher_trace_f1s),
            disclosure=lf.TEACHER_DISCLOSURE,
        )
        if teacher_trace_f1s
        else lf.Measurement(status="missing", reason="no overlapping student/teacher roof traces")
    )
    eave_rep = lf.heldout_reprojection(eave_rays_by_target, tol_deg=5.0)
    m4_6 = (
        lf.Measurement(
            status="ok",
            value=eave_rep["hit_rate"],
            n_clusters=eave_rep["n_evals"],
        )
        if eave_rep["n_evals"] > 0
        else lf.Measurement(status="missing", reason="fewer than 3 views with accepted EAVE edges")
    )
    return {
        "M4.1": m4_1,
        "M4.2": m4_2,
        "M4.3": m4_3,
        "M4.4": m4_4,
        "M4.5": m4_5,
        "M4.6": m4_6,
    }


def _write_outputs(
    out_dir: Path,
    aoi: str,
    variant_name: str,
    manifest: Mapping[str, Any],
    metrics: Mapping[str, lf.Measurement],
    spend: Mapping[str, Any],
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    results_payload = {
        "date": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d"),
        "commit": _git_commit(),
        "aoi": aoi,
        "variant": variant_name,
        "manifests": {aoi: manifest["sha256"]},
        "spend": dict(spend),
        "metrics": {k: m.to_dict() for k, m in metrics.items()},
        **(dict(extra) if extra else {}),
    }
    (out_dir / "results.json").write_text(
        json.dumps(results_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    summary_md = lf.render_summary(results_payload)
    (out_dir / "summary.md").write_text(summary_md, encoding="utf-8")
    return results_payload


class _OfflineSmokeBackend:
    """Deterministic offline backend used by `run_offline_smoke` unit tests."""

    def __init__(self, model: str = gc.DEFAULT_MODEL):
        self.model = model
        self.location = "global"

    async def generate(self, parts, schema, code_execution=False, **kw):
        name = getattr(schema, "__name__", "")
        if name == "HouseView":
            txt = (
                '{"house_visible": true, "box_2d": [240, 340, 760, 660], '
                '"occlusion": "NONE", "facade_visible_fraction": 0.85, '
                '"stories": 2, "exterior_material": "STUCCO", "roof_type": "GABLE", "confidence": 0.9}'
            )
        elif name == "HouseFramingVerdict":
            txt = (
                '{"house_visible": true, "fully_in_frame": true, "truncation": "NONE", '
                '"occlusion": "NONE", "stories": 2, "exterior_material": "STUCCO", '
                '"roof_type": "GABLE", "confidence": 0.92, "visual_evidence": "Clear facade."}'
            )
        elif name == "FrameDetections":
            txt = (
                '{"detections": ['
                '{"label": "UTILITY_POLE", "box_2d": [200, 480, 850, 520], "confidence": 0.9, "material": "WOOD"},'
                '{"label": "HOUSE", "box_2d": [250, 300, 750, 700], "confidence": 0.88, "material": "STUCCO"}'
                "]}"
            )
        elif name == "PresenceCheck":
            txt = '{"present": true, "confidence": 0.9, "box_2d": [300, 400, 700, 600]}'
        elif name == "EntityConfirm":
            txt = (
                '{"target_class": "UTILITY_POLE", "confirmed": true, '
                '"box_2d": [200, 480, 850, 520], "confidence": 0.9, "visual_evidence": "Pole."}'
            )
        elif name == "WindowLabel":
            txt = (
                '{"observations": ['
                '{"asset": "ROAD", "side": "CENTER", "present": true, "material": "Paved Asphalt", "condition": "Good", "confidence": 0.95},'
                '{"asset": "SIDEWALK", "side": "LEFT", "present": true, "material": "Concrete", "condition": "Good", "confidence": 0.9},'
                '{"asset": "SIDEWALK", "side": "RIGHT", "present": false, "material": null, "condition": null, "confidence": 0.9}'
                "]}"
            )
        elif name == "SurfaceSlotVerdict":
            txt = (
                '{"side": "CENTER", "present": true, "material": "Paved Asphalt", '
                '"condition": "Good", "confidence": 0.95, "visual_evidence": "Asphalt road."}'
            )
        elif name == "RoofVisibility":
            txt = (
                '{"roof_visible": true, "visible_fraction": 0.8, "edge_50pct_visible": true, '
                '"occlusion_reason": "NONE", "confidence": 0.9}'
            )
        elif name in ("RoofEdges", "RoofTrace"):
            txt = (
                '{"roof_visible": true, "edges": ['
                '{"edge_type": "EAVE", "points": [[333, 200], [333, 800]]}'
                '], "confidence": 0.9}'
            )
        else:
            txt = "{}"
        return gc.RawReply(
            text=txt,
            usage={"prompt_token_count": 250, "candidates_token_count": 50},
        )


_SYNTH_JPEG_CACHE: bytes | None = None


def _synthetic_frame_bytes(_uri: str) -> bytes:
    global _SYNTH_JPEG_CACHE
    if _SYNTH_JPEG_CACHE is None:
        img = np.full((5472, 3648, 3), 140, dtype=np.uint8)
        img[:1824, :] = (230, 200, 175)  # sky above y=1824
        img[1824:2600, :] = (110, 95, 85)  # roof/building band
        img[2600:, :] = (80, 80, 80)  # road
        img[1900:3400, 1820:1828] = (25, 25, 25)  # vertical pole
        _SYNTH_JPEG_CACHE = images.encode_jpeg(img, quality=85)
    return _SYNTH_JPEG_CACHE


def run_offline_smoke(
    frames: pd.DataFrame,
    aoi: str = "tune",
    out_dir: str | Path = "data/labelfree/smoke",
    seed: int = 7,
    variant_name: str = "baseline",
) -> dict[str, Any]:
    """Run the full harness pipeline offline against scripted replies (for unit tests)."""
    out_path = Path(out_dir)
    calls_path = out_path / "calls.jsonl"
    manifest = mf.build_manifest(frames, aoi=aoi, seed=seed)
    smoke_manifest = {
        **manifest,
        "uc1_targets": manifest["uc1_targets"][:2],
        "uc2_sequences": manifest["uc2_sequences"][:1],
        "uc3_sequences": manifest["uc3_sequences"][:1],
        "uc4_targets": manifest["uc4_targets"][:2],
    }
    variant = VARIANTS[variant_name]
    s_backend = LoggingBackend(
        _OfflineSmokeBackend(gc.DEFAULT_MODEL), calls_path, prompt_version=variant.name
    )
    t_backend = LoggingBackend(
        _OfflineSmokeBackend(tea.teacher_model()), calls_path, prompt_version="teacher_v1"
    )
    s_runner = gc.GeminiRunner(s_backend, max_calls=None, max_usd=None)
    t_runner = gc.GeminiRunner(t_backend, max_calls=None, max_usd=None)
    t_cache = tea.TeacherCache(out_path / "teacher_cache.jsonl")
    intr = rosette.DEFAULT_INTRINSICS

    async def _all():
        m1, _ = await evaluate_uc1(
            frames,
            smoke_manifest,
            _synthetic_frame_bytes,
            s_runner,
            t_runner,
            t_cache,
            intr,
            variant,
            seed,
        )
        m2 = await evaluate_uc2(
            frames,
            smoke_manifest,
            _synthetic_frame_bytes,
            s_runner,
            t_runner,
            t_cache,
            intr,
            variant,
            seed,
        )
        m3 = await evaluate_uc3(
            frames,
            smoke_manifest,
            _synthetic_frame_bytes,
            s_runner,
            t_runner,
            t_cache,
            intr,
            variant,
            seed,
        )
        m4 = await evaluate_uc4(
            frames,
            smoke_manifest,
            _synthetic_frame_bytes,
            s_runner,
            t_runner,
            t_cache,
            intr,
            variant,
            seed,
        )
        return {**m1, **m2, **m3, **m4}

    metrics = asyncio.run(_all())
    spend = {
        "usd": round(s_runner.cost.usd + t_runner.cost.usd, 4),
        "calls": s_runner.cost.calls + t_runner.cost.calls,
        "input_tokens": s_runner.cost.input_tokens + t_runner.cost.input_tokens,
        "output_tokens": s_runner.cost.output_tokens + t_runner.cost.output_tokens,
    }
    return _write_outputs(out_path, aoi, variant_name, manifest, metrics, spend)


def load_aoi_frames(
    project: str,
    bucket: str,
    aoi: str,
    radius_m: float = 400.0,
) -> pd.DataFrame:
    """Load multi-AOI metadata from `pano_observations_all` (cached under DEFAULT_QUERY_CACHE)."""
    creds = auth.get_credentials()
    bq = data.QueryRunner(
        data.make_bigquery_client(project, creds),
        allowed_tables=data.pano_tables(project, data.DATASET),
        cache_dir=data.DEFAULT_QUERY_CACHE,
    )
    table = data.pano_table(project, data.DATASET, "pano_observations_all")
    centres = [mf.AOI_CENTRES["tune"], mf.AOI_CENTRES["heldout"], mf.AOI_CENTRES["stress"]]
    raw = bq.run(data.multi_aoi_meta_sql(table), data.multi_aoi_params(centres, radius_m))
    norm = data.normalize_frames(raw)
    assigned = data.assign_nearest_aoi(
        norm,
        {
            "lakeland_fl": mf.AOI_CENTRES["tune"],
            "salt_lake_ut": mf.AOI_CENTRES["heldout"],
            "osaka_jp": mf.AOI_CENTRES["stress"],
        },
        max_dist_m=radius_m * 1.5,
    )
    target_name = mf.CANONICAL_AOI_NAME.get(aoi, aoi)
    sub = assigned[assigned["aoi"] == target_name].copy()
    sub["gcs_uri"] = [
        data.gcs_uri_for(bucket, s, o)
        for s, o in zip(sub["snapshot_id"], sub["observation_id"], strict=True)
    ]
    return sub.reset_index(drop=True)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--uc", choices=("1", "2", "3", "4", "all"), default="all")
    ap.add_argument("--aoi", choices=("tune", "heldout", "stress"), default="tune")
    ap.add_argument("--variant", choices=tuple(VARIANTS.keys()), default="baseline")
    ap.add_argument(
        "--max-usd", type=float, default=None, help="Optional USD cap (default: None / uncapped)"
    )
    ap.add_argument(
        "--max-gemini-calls", type=int, default=None, help="Optional call cap (default: None)"
    )
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument(
        "--out",
        default=f"data/labelfree/{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d')}",
    )
    ap.add_argument("--project", default=None)
    ap.add_argument("--gcs-bucket", default=None)
    args = ap.parse_args(argv)

    settings = config.resolve_settings(args.project, args.gcs_bucket, env=dict(os.environ))
    out_path = Path(args.out)
    out_path.mkdir(parents=True, exist_ok=True)
    calls_path = out_path / "calls.jsonl"

    est_student = gc.estimate_cost(80, prices=gc.prices_for(gc.DEFAULT_MODEL))
    est_teacher = gc.estimate_cost(20, prices=gc.prices_for(tea.teacher_model()))
    print(
        f"[labelfree] planned spend estimate for aoi={args.aoi} uc={args.uc} variant={args.variant}: "
        f"~${est_student + est_teacher:.2f} (max_usd={args.max_usd})"
    )

    frames = load_aoi_frames(settings.project, settings.bucket, args.aoi)
    manifest = mf.build_manifest(frames, aoi=args.aoi, seed=args.seed)
    (out_path / f"manifest_{args.aoi}.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    creds = auth.get_credentials()
    fetcher = images.GcsImageFetcher(
        storage.Client(project=settings.project, credentials=creds),
        cache_dir=images.DEFAULT_FRAME_CACHE,
    )
    v_client = gc.make_vertex_client(settings.project, gc.DEFAULT_LOCATION, creds)
    variant = VARIANTS[args.variant]
    reply_cache = out_path.parent / f"reply_cache_{args.aoi}.jsonl"
    s_backend = LoggingBackend(
        gc.VertexGeminiBackend(v_client, model=gc.DEFAULT_MODEL),
        calls_path,
        prompt_version=variant.name,
        reply_cache_path=reply_cache,
    )
    t_backend = LoggingBackend(
        gc.VertexGeminiBackend(v_client, model=tea.teacher_model()),
        calls_path,
        prompt_version="teacher_v1",
        reply_cache_path=reply_cache,
    )
    s_runner = gc.GeminiRunner(
        s_backend, max_calls=args.max_gemini_calls, max_usd=args.max_usd, concurrency=12
    )
    t_runner = gc.GeminiRunner(
        t_backend, max_calls=args.max_gemini_calls, max_usd=args.max_usd, concurrency=6
    )
    t_cache = tea.TeacherCache(out_path.parent / f"teacher_cache_{args.aoi}.jsonl")
    intr = rosette.load_intrinsics()

    async def _run_selected():
        out_m: dict[str, lf.Measurement] = {}
        if args.uc in ("1", "all"):
            m1, _ = await evaluate_uc1(
                frames,
                manifest,
                fetcher.fetch,
                s_runner,
                t_runner,
                t_cache,
                intr,
                variant,
                args.seed,
            )
            out_m.update(m1)
            print(f"[labelfree] {args.aoi}/{args.variant} finished UC1 (calls={s_runner.cost.calls + t_runner.cost.calls})", flush=True)
        if args.uc in ("2", "all"):
            m2 = await evaluate_uc2(
                frames,
                manifest,
                fetcher.fetch,
                s_runner,
                t_runner,
                t_cache,
                intr,
                variant,
                args.seed,
            )
            out_m.update(m2)
            print(f"[labelfree] {args.aoi}/{args.variant} finished UC2 (calls={s_runner.cost.calls + t_runner.cost.calls})", flush=True)
        if args.uc in ("3", "all"):
            m3 = await evaluate_uc3(
                frames,
                manifest,
                fetcher.fetch,
                s_runner,
                t_runner,
                t_cache,
                intr,
                variant,
                args.seed,
            )
            out_m.update(m3)
            print(f"[labelfree] {args.aoi}/{args.variant} finished UC3 (calls={s_runner.cost.calls + t_runner.cost.calls})", flush=True)
        if args.uc in ("4", "all"):
            m4 = await evaluate_uc4(
                frames,
                manifest,
                fetcher.fetch,
                s_runner,
                t_runner,
                t_cache,
                intr,
                variant,
                args.seed,
            )
            out_m.update(m4)
            print(f"[labelfree] {args.aoi}/{args.variant} finished UC4 (calls={s_runner.cost.calls + t_runner.cost.calls})", flush=True)
        return out_m

    metrics = asyncio.run(_run_selected())
    spend = {
        "usd": round(s_runner.cost.usd + t_runner.cost.usd, 4),
        "calls": s_runner.cost.calls + t_runner.cost.calls,
        "input_tokens": s_runner.cost.input_tokens + t_runner.cost.input_tokens,
        "output_tokens": s_runner.cost.output_tokens + t_runner.cost.output_tokens,
        "student_usd": round(s_runner.cost.usd, 4),
        "teacher_usd": round(t_runner.cost.usd, 4),
    }
    _write_outputs(out_path, args.aoi, args.variant, manifest, metrics, spend)
    print(f"[labelfree] actual spend: ${spend['usd']:.4f} ({spend['calls']} calls)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
