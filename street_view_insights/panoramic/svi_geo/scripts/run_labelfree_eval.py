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
    # Combined final candidate across all 4 UCs (selected on tune=lakeland_fl)
    "final": uc.Variant(
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
        t_lvl = kw.get("thinking_level", getattr(self.inner, "thinking_level", None))
        m_res = kw.get("media_resolution", getattr(self.inner, "media_resolution", None))
        cache_key = (
            f"{self.model}:{schema_name}:{int(bool(code_execution))}:{kw.get('seed')}:"
            f"{t_lvl}:{m_res}:{_parts_sha256(parts)}"
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
                "cached_content_token_count": int(get_raw("cached_content_token_count") or 0),
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
            "thinking_level": str(t_lvl),
            "media_resolution": str(m_res),
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


def _add_cluster(
    clusters: dict[str, tuple[float, float]], key: str, num: float, den: float = 1.0
) -> None:
    prev_num, prev_den = clusters.get(key, (0.0, 0.0))
    clusters[key] = (prev_num + float(num), prev_den + float(den))


def _ratio_measurement(
    per_cluster: Mapping[str, tuple[float, float]],
    *,
    seed: int = 7,
    placebo: float | None = None,
    disclosure: str = "",
    missing_reason: str = "no observations",
) -> lf.Measurement:
    """Compute block-bootstrap CI via `lf.block_ratio_ci` when >= 5 clusters exist,
    or exact ratio `Measurement.ok` when 1..4 clusters exist, or `Measurement.missing` when empty."""
    valid = {k: (float(v[0]), float(v[1])) for k, v in per_cluster.items() if float(v[1]) > 0}
    if not valid:
        return lf.Measurement.missing(missing_reason, disclosure=disclosure)
    if len(valid) >= 5:
        return lf.block_ratio_ci(
            valid,
            seed=seed,
            min_clusters=5,
            placebo=placebo,
            disclosure=disclosure,
        )
    tot_num = sum(v[0] for v in valid.values())
    tot_den = sum(v[1] for v in valid.values())
    if tot_den <= 0:
        return lf.Measurement.missing(missing_reason, disclosure=disclosure)
    return lf.Measurement.ok(
        float(tot_num / tot_den),
        n_clusters=len(valid),
        placebo=placebo,
        disclosure=disclosure,
    )


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
    """Compute M1.1..M1.7 on `manifest['uc1_targets']` and `manifest['repeat_pairs']`."""
    targets = manifest["uc1_targets"][:4]
    perts = manifest["perturbations"][:2]
    blocks_map = manifest.get("blocks", {})
    agree_num_den: list[tuple[float, float]] = []
    block_ids: list[str] = []
    loc_dists: list[float] = []
    split_rays_all: list[list[tri.Ray]] = []
    by_obj_reproj: dict[str, list[tri.Ray]] = {}
    reproj_by_block: dict[str, tuple[float, float]] = {}
    non_trunc_by_block: dict[str, tuple[float, float]] = {}
    sky_scores: list[float] = []
    teacher_in_frame: list[int] = []
    prev_locs: list[views.HouseLocation] = []
    pert_locs: list[views.HouseLocation] = []
    loc_blocks: list[str] = []
    repeat_by_block: dict[str, tuple[float, float]] = {}
    rep_pairs_a: list[str] = []
    rep_pairs_b: list[str] = []
    rep_pair_blocks: list[str] = []

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
        w1, h1 = variant.uc1_view_size
        base_out = await uc.uc1_run(
            ranked, fetch, student_runner, intr, width=w1, height=h1, variant=variant
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
            ranked, fetch, student_runner, intr, width=w1, height=h1, variant=pert_var
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

        # M1.6 & M1.7: Cross-day repeat-pass attribute agreement on disjoint capture dates
        ranked_dates = ranked.copy()
        if "capture_time" not in ranked_dates.columns and "capture_time" in frames.columns:
            ct_map = frames.drop_duplicates("capture_id").set_index("capture_id")["capture_time"]
            ranked_dates["capture_time"] = ranked_dates["capture_id"].map(ct_map)
        if "capture_time" in ranked_dates.columns:
            ranked_dates["_day"] = pd.to_datetime(
                ranked_dates["capture_time"], utc=True
            ).dt.strftime("%Y-%m-%d")
        else:
            ranked_dates["_day"] = None
        uniq_days = sorted(ranked_dates["_day"].dropna().unique().tolist())
        if len(uniq_days) < 2 and "capture_time" in frames.columns:
            # Expand search radius slightly to find cross-day repeat-pass views of the same target
            _, ranked_wide = uc.uc1_select_views(
                frames,
                t["lat"],
                t["lng"],
                intr,
                max_dist_m=60.0,
                max_per_seq=6,
                n=10,
                variant=variant,
            )
            if not ranked_wide.empty and "capture_time" in ranked_wide.columns:
                ranked_dates = ranked_wide.copy()
                ranked_dates["_day"] = pd.to_datetime(
                    ranked_dates["capture_time"], utc=True
                ).dt.strftime("%Y-%m-%d")
                uniq_days = sorted(ranked_dates["_day"].dropna().unique().tolist())
        if len(uniq_days) >= 2:
            day_a_df = ranked_dates[ranked_dates["_day"] == uniq_days[0]].drop(columns=["_day"])
            day_b_df = ranked_dates[ranked_dates["_day"] != uniq_days[0]].drop(columns=["_day"])
            if not day_a_df.empty and not day_b_df.empty:
                out_day_a = await uc.uc1_run(
                    day_a_df, fetch, student_runner, intr, width=w1, height=h1, variant=variant
                )
                out_day_b = await uc.uc1_run(
                    day_b_df, fetch, student_runner, intr, width=w1, height=h1, variant=variant
                )
                for k in ("stories", "exterior_material", "roof_type"):
                    va = out_day_a["attrs"][k][0]
                    vb = out_day_b["attrs"][k][0]
                    if va is not None and vb is not None:
                        _add_cluster(
                            repeat_by_block, str(t["block_id"]), 1.0 if va == vb else 0.0, 1.0
                        )
                        rep_pairs_a.append(f"{k}:{va}")
                        rep_pairs_b.append(f"{k}:{vb}")
                        rep_pair_blocks.append(str(t["block_id"]))

        # M1.2 location repeatability + split-half rays
        loc0 = base_out["location"]
        loc1 = pert_out["location"]
        if loc0 is not None and loc1 is not None:
            d_m = float(geo.haversine_m(loc0.lat, loc0.lng, loc1.lat, loc1.lng))
            loc_dists.append(d_m)
            prev_locs.append(loc0)
            pert_locs.append(loc1)
            loc_blocks.append(t["block_id"])

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
            rep_t = lf.heldout_reprojection({t["target_id"]: rays}, tol_deg=3.5)
            anchor_id = str(t.get("anchor_capture_id") or t.get("anchor_pano_id") or "")
            for s_obj, err_deg in zip(sights, rep_t["errors_deg"], strict=False):
                s_pid = str(
                    getattr(s_obj, "capture_id", "") or getattr(s_obj, "pano_id", "") or anchor_id
                )
                s_blk = blocks_map.get(s_pid, f"{t['block_id']}:{s_pid}")
                _add_cluster(reproj_by_block, s_blk, 1.0 if err_deg <= 3.5 else 0.0, 1.0)
            if len(rays) >= 4:
                split_rays_all.append(rays)

        # M1.4 framing: truncation, sky contact, and teacher fully_in_frame on top view
        res_df = base_out["res"]
        vis_df = res_df[res_df["visible"].fillna(False)]
        for row_idx, r_row in vis_df.iterrows():
            r_pid = str(r_row.get("capture_id") or r_row.get("pano_id") or f"r_{row_idx}")
            r_blk = blocks_map.get(r_pid, f"{t['block_id']}:{r_pid}")
            _add_cluster(non_trunc_by_block, r_blk, 0.0 if bool(r_row["truncated"]) else 1.0, 1.0)
        for sc_val in vis_df["sky_contact"].dropna().tolist():
            if math.isfinite(float(sc_val)):
                sky_scores.append(float(sc_val))

        if base_out["crops"]:
            top_crop = base_out["crops"][0]
            t_rec = await tea.ask_teacher(
                teacher_runner,
                cache=teacher_cache,
                task="house_framing",
                image=top_crop,
                extra_images=[zt["image"] for zt in tea.tiles(top_crop)],
                schema=schemas.HouseFramingVerdict,
                seed=seed,
            )
            if t_rec["result"] is not None:
                teacher_in_frame.append(1 if t_rec["result"].get("fully_in_frame") else 0)

    # Also evaluate explicit repeat_pairs from manifest if fewer than 2 targets had multi-day views
    if len(rep_pairs_a) < 6 and manifest.get("repeat_pairs"):
        key_col = "capture_id" if "capture_id" in frames.columns else "pano_id"
        w1, h1 = variant.uc1_view_size
        for rp_idx, rp in enumerate(manifest["repeat_pairs"][:2]):
            c_pairs = rp.get("capture_pairs") or rp.get("pano_pairs") or []
            if not c_pairs:
                continue
            ids_a = {str(pair[0]) for pair in c_pairs}
            ids_b = {str(pair[1]) for pair in c_pairs}
            sub_a = frames[frames[key_col].astype(str).isin(ids_a)]
            sub_b = frames[frames[key_col].astype(str).isin(ids_b)]
            if sub_a.empty or sub_b.empty:
                continue
            step = max(1, len(c_pairs) // 4)
            for p_idx in range(0, len(c_pairs), step):
                if len(rep_pairs_a) >= 9:
                    break
                cid_a = str(c_pairs[p_idx][0])
                anc_rows = sub_a[sub_a[key_col].astype(str) == cid_a]
                anchor_row = anc_rows.iloc[0] if not anc_rows.empty else sub_a.iloc[0]
                for de_m, dn_m in ((16.0, 0.0), (-16.0, 0.0), (0.0, 16.0), (0.0, -16.0)):
                    tlat_arr, tlng_arr, _ = geo.enu_to_lla(
                        de_m,
                        dn_m,
                        0.0,
                        float(anchor_row["lat"]),
                        float(anchor_row["lng"]),
                        0.0,
                    )
                    tlat, tlng = float(tlat_arr), float(tlng_arr)
                    _, rk_a = uc.uc1_select_views(
                        sub_a, tlat, tlng, intr, max_per_seq=4, n=3, variant=variant
                    )
                    _, rk_b = uc.uc1_select_views(
                        sub_b, tlat, tlng, intr, max_per_seq=4, n=3, variant=variant
                    )
                    if rk_a.empty or rk_b.empty:
                        continue
                    out_a = await uc.uc1_run(
                        rk_a, fetch, student_runner, intr, width=w1, height=h1, variant=variant
                    )
                    out_b = await uc.uc1_run(
                        rk_b, fetch, student_runner, intr, width=w1, height=h1, variant=variant
                    )
                    blk = f"{blocks_map.get(cid_a, f'rp_{rp_idx}')}:p{p_idx}"
                    added = 0
                    for k in ("stories", "exterior_material", "roof_type"):
                        va = out_a["attrs"][k][0]
                        vb = out_b["attrs"][k][0]
                        if va is not None and vb is not None:
                            _add_cluster(repeat_by_block, blk, 1.0 if va == vb else 0.0, 1.0)
                            rep_pairs_a.append(f"{k}:{va}")
                            rep_pairs_b.append(f"{k}:{vb}")
                            rep_pair_blocks.append(blk)
                            added += 1
                    if added > 0:
                        break

    per_cluster: dict[str, tuple[float, float]] = {}
    for b, (num, den) in zip(block_ids, agree_num_den, strict=True):
        _add_cluster(per_cluster, b, num, den)
    m1_1 = lf.block_ratio_ci(per_cluster, seed=seed, min_clusters=max(2, min(5, len(per_cluster))))
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

    m1_3 = _ratio_measurement(
        reproj_by_block,
        seed=seed,
        missing_reason="no house with >= 3 centred sightings",
    )

    t_rate = float(np.mean(teacher_in_frame)) if teacher_in_frame else None
    m1_4 = _ratio_measurement(
        non_trunc_by_block,
        seed=seed,
        placebo=t_rate,
        disclosure=lf.TEACHER_DISCLOSURE,
        missing_reason="no visible house detections",
    )

    if prev_locs and pert_locs:
        matched_ids = views.match_house_ids(prev_locs, pert_locs, max_m=3.0)
        carry_by_block: dict[str, tuple[float, float]] = {}
        for m_id, p_loc, b_id in zip(matched_ids, prev_locs, loc_blocks, strict=True):
            _add_cluster(carry_by_block, b_id, 1.0 if m_id == p_loc.entity_id else 0.0, 1.0)
        m1_5 = _ratio_measurement(
            carry_by_block,
            seed=seed,
            missing_reason="no paired house locations for ID carry-over",
        )
    else:
        m1_5 = lf.Measurement(
            status="missing", reason="no paired house locations for ID carry-over"
        )

    m1_6 = _ratio_measurement(
        repeat_by_block,
        seed=seed,
        disclosure="cross-day repeat-pass consistency != accuracy",
        missing_reason="no multi-pass house attribute pairs",
    )

    m1_7 = lf.repeat_pass_agreement_vs_placebo(rep_pairs_a, rep_pairs_b, rep_pair_blocks, seed=seed)

    return {
        "M1.1": m1_1,
        "M1.2": m1_2,
        "M1.3": m1_3,
        "M1.4": m1_4,
        "M1.5": m1_5,
        "M1.6": m1_6,
        "M1.7": m1_7,
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
    """Compute M2.1..M2.6 on `manifest['uc2_sequences']` and `manifest['repeat_pairs']`."""
    blocks_map = manifest.get("blocks", {})
    reproj_by_block: dict[str, tuple[float, float]] = {}
    retest_by_block: dict[str, tuple[float, float]] = {}
    repeat_by_block: dict[str, tuple[float, float]] = {}
    cv_support_by_block: dict[str, tuple[float, float]] = {}
    cv_support_placebo: list[float] = []
    loc_share_by_block: dict[str, tuple[float, float]] = {}
    house_unloc = 0
    house_tot = 0
    teacher_by_block: dict[str, tuple[float, float]] = {}

    panos_all = sequence.build_sequences(data.panos_from_frames(frames))
    panos_all["travel_deg"] = sequence.travel_bearing(panos_all)
    id_col = "capture_id" if "capture_id" in panos_all.columns else "pano_id"
    pert_spec = manifest["perturbations"][0]

    for seq_spec in manifest["uc2_sequences"][:2]:
        seq_ids_list = seq_spec.get("capture_ids") or seq_spec.get("pano_ids") or []
        pids = set(seq_ids_list[:4])
        sel = panos_all[panos_all[id_col].isin(pids)].sort_values("seq_idx").reset_index(drop=True)
        if len(sel) < 2:
            continue
        sel_frames = frames[frames[id_col].isin(sel[id_col])].merge(
            sel[[id_col, "seq_idx", "travel_deg"]], on=id_col
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
        for idx_err, err in enumerate(rep["errors_deg"]):
            _add_cluster(
                reproj_by_block,
                f"{seq_spec['seq_id']}:b{idx_err % 5:03d}",
                1.0 if err <= 3.5 else 0.0,
                1.0,
            )
        if out0["self_consistency"] is not None:
            cv_res = out0["self_consistency"]["cross_view"]
            for idx_t, t_row in enumerate(cv_res.get("per_task", [])):
                if t_row.get("answered"):
                    t_pid = str(t_row.get("capture_id") or t_row.get("pano_id") or "")
                    t_blk = blocks_map.get(t_pid, f"{seq_spec['seq_id']}:sc{idx_t % 5:03d}")
                    _add_cluster(reproj_by_block, t_blk, 1.0 if t_row.get("present") else 0.0, 1.0)

        # M2.2 test-retest recall via eval.match_passes
        loc0 = out0["located"]
        loc1 = out1["located"]
        if loc0 and loc1:
            mp = ev.match_passes(loc0, loc1)
            rec_val = 0.5 * (mp["recall_a_in_b"] + mp["recall_b_in_a"])
            _add_cluster(retest_by_block, str(seq_spec["seq_id"]), rec_val, 1.0)

        # M2.4 OpenCV vertical-structure support vs placebo
        img_by_view = {
            (str(r["spec"].capture_id or r["spec"].pano_id), int(r["spec"].cam_k)): r["image"]
            for r in out0["run"].records
            if r.get("image") is not None
        }
        for o in out0["observations"]:
            if o.cls in ("UTILITY_POLE", "ROAD_SIGN"):
                meta = o.ray.meta or {}
                box = meta.get("box")
                ck = meta.get("cam_k")
                o_key = str(getattr(o, "capture_id", "") or o.pano_id)
                im = img_by_view.get((o_key, int(ck))) if ck is not None else None
                if im is not None and box is not None:
                    sup = cvc.vertical_post_support(im, box)
                    if o.cls == "ROAD_SIGN":
                        sup = max(sup, cvc.sign_post_support(im, box))
                    o_blk = blocks_map.get(o_key, f"{seq_spec['seq_id']}:{o_key}")
                    _add_cluster(cv_support_by_block, o_blk, 1.0 if sup >= 0.35 else 0.0, 1.0)
                    p_boxes = cvc.placebo_boxes(1, im.shape[1], im.shape[0], seed=seed)
                    cv_support_placebo.append(cvc.vertical_post_support(im, p_boxes[0]))

        # M2.5 located share & house unlocated share
        loc_ids = {e.entity_id for e in out0["located"]}
        for e in out0["entities"]:
            e_ids = getattr(e, "capture_ids", None) or e.pano_ids
            e_pid = str(e_ids[0]) if e_ids else str(seq_spec["seq_id"])
            e_blk = blocks_map.get(e_pid, f"{seq_spec['seq_id']}:{e_pid}")
            _add_cluster(loc_share_by_block, e_blk, 1.0 if e.entity_id in loc_ids else 0.0, 1.0)
        house_unloc += out0["houses_unlocated"]
        house_tot += out0["houses_located"] + out0["houses_unlocated"]

        # M2.6 teacher confirmation on first view with detections
        if out0["run"].records and out0["observations"]:
            first_rec = out0["run"].records[0]
            if first_rec.get("image") is not None:
                first_im = first_rec["image"]
                t_ans = await tea.ask_teacher(
                    teacher_runner,
                    cache=teacher_cache,
                    task="entity_confirm",
                    image=first_im,
                    extra_images=[zt["image"] for zt in tea.tiles(first_im)],
                    schema=schemas.EntityConfirm,
                    seed=seed,
                    target_class=out0["observations"][0].cls,
                )
                if t_ans["result"] is not None:
                    _add_cluster(
                        teacher_by_block,
                        str(seq_spec["seq_id"]),
                        1.0 if t_ans["result"].get("confirmed") else 0.0,
                        1.0,
                    )

    # M2.3 true cross-day repeat-pass entity recall across manifest['repeat_pairs']
    for rp_idx, rp in enumerate(manifest.get("repeat_pairs", [])[:2]):
        pairs_ab = rp.get("capture_pairs") or rp.get("pano_pairs") or []
        pids_a: list[str] = []
        pids_b: list[str] = []
        for pa, pb in pairs_ab:
            if pa not in pids_a and len(pids_a) < 4:
                pids_a.append(str(pa))
            if pb not in pids_b and len(pids_b) < 4:
                pids_b.append(str(pb))
        sel_a = (
            panos_all[panos_all[id_col].isin(pids_a)].sort_values("seq_idx").reset_index(drop=True)
        )
        sel_b = (
            panos_all[panos_all[id_col].isin(pids_b)].sort_values("seq_idx").reset_index(drop=True)
        )
        if len(sel_a) < 2 or len(sel_b) < 2:
            continue
        frames_a = frames[frames[id_col].isin(sel_a[id_col])].merge(
            sel_a[[id_col, "seq_idx", "travel_deg"]], on=id_col
        )
        frames_b = frames[frames[id_col].isin(sel_b[id_col])].merge(
            sel_b[[id_col, "seq_idx", "travel_deg"]], on=id_col
        )
        both_panos = pd.concat([sel_a, sel_b], ignore_index=True)
        cam_alts_ab = [
            float(p["altitude"])
            for p in pd.concat(
                [frames_a["camera_pose"], frames_b["camera_pose"]], ignore_index=True
            )
        ]
        ref_ab = (
            float(both_panos["lat"].mean()),
            float(both_panos["lng"].mean()),
            float(np.median(cam_alts_ab)) - 2.5,
        )
        out_a = await uc.uc2_run(
            frames_a,
            fetch,
            student_runner,
            intr,
            ref_ab,
            max_presence_checks=0,
            variant=variant,
        )
        out_b = await uc.uc2_run(
            frames_b,
            fetch,
            student_runner,
            intr,
            ref_ab,
            max_presence_checks=0,
            variant=variant,
        )
        loc_a = out_a["located"]
        loc_b = out_b["located"]
        if loc_a and loc_b:
            mp_rep = ev.match_passes(
                loc_a,
                loc_b,
                eps_by_class={"UTILITY_POLE": 4.0, "ROAD_SIGN": 4.0, "HOUSE": 8.0},
            )
            rep_recall = 0.5 * (mp_rep["recall_a_in_b"] + mp_rep["recall_b_in_a"])
            _add_cluster(
                repeat_by_block,
                f"{rp.get('seq_a', 'a')}:{rp.get('seq_b', 'b')}:{rp_idx}",
                rep_recall,
                1.0,
            )

    m2_1 = _ratio_measurement(
        reproj_by_block,
        seed=seed,
        missing_reason="no multi-view entities for reprojection check",
    )
    m2_2 = _ratio_measurement(
        retest_by_block,
        seed=seed,
        missing_reason="no located entities in both test and retest",
    )
    m2_3 = _ratio_measurement(
        repeat_by_block,
        seed=seed,
        missing_reason=(
            "no located entities in cross-day repeat passes"
            if manifest.get("repeat_pairs")
            else "no cross-day repeat pairs in AOI"
        ),
    )
    placebo_2_4 = (
        float(np.mean([s >= 0.35 for s in cv_support_placebo])) if cv_support_placebo else None
    )
    m2_4 = _ratio_measurement(
        cv_support_by_block,
        seed=seed,
        placebo=placebo_2_4,
        missing_reason="no pole or sign observations",
    )
    h_unloc_share = float(house_unloc / house_tot) if house_tot > 0 else None
    m2_5 = _ratio_measurement(
        loc_share_by_block,
        seed=seed,
        placebo=h_unloc_share,
        missing_reason="no entities clustered",
    )
    m2_6 = _ratio_measurement(
        teacher_by_block,
        seed=seed,
        disclosure=lf.TEACHER_DISCLOSURE,
        missing_reason="no teacher confirmation tasks run",
    )

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
    """Compute M3.1..M3.7 on `manifest['uc3_sequences']` and `manifest['repeat_pairs']`."""
    blocks_map = manifest.get("blocks", {})
    panos_all = sequence.build_sequences(data.panos_from_frames(frames))
    panos_all["travel_deg"] = sequence.travel_bearing(panos_all)
    id_col = "capture_id" if "capture_id" in panos_all.columns else "pano_id"
    pert_spec = manifest["perturbations"][0]

    labels_base: list[str] = []
    labels_pert: list[str] = []
    adj_by_block: dict[str, tuple[float, float]] = {}
    shuf_vals: list[float] = []
    repeat_bin_by_block: dict[str, tuple[float, float]] = {}
    rep_slot_a: list[str] = []
    rep_slot_b: list[str] = []
    rep_slot_blks: list[str] = []
    within_tex: list[float] = []
    kerb_preds: list[str] = []
    sidewalk_preds: list[str] = []
    teacher_by_block: dict[str, tuple[float, float]] = {}
    cached_uc3_runs: dict[tuple[str, ...], dict[str, Any]] = {}

    for seq_spec in manifest["uc3_sequences"][:2]:
        seq_ids_list = seq_spec.get("capture_ids") or seq_spec.get("pano_ids") or []
        pids = set(seq_ids_list[:6])
        sel = panos_all[panos_all[id_col].isin(pids)].sort_values("seq_idx").reset_index(drop=True)
        if len(sel) < 3:
            continue
        sel_frames = frames[frames[id_col].isin(sel[id_col])].merge(
            sel[[id_col, "seq_idx", "travel_deg"]], on=id_col
        )
        out0 = await uc.uc3_run(sel, sel_frames, fetch, student_runner, intr, variant=variant)
        cached_uc3_runs[tuple(sel[id_col].astype(str).tolist())] = out0
        pert_var = dataclasses.replace(
            variant,
            yaw_delta_deg=pert_spec["yaw_delta_deg"],
            gemini_seed=pert_spec["gemini_seed"],
        )
        out1 = await uc.uc3_run(sel, sel_frames, fetch, student_runner, intr, variant=pert_var)

        sel_pids = sel[id_col].astype(str).tolist()
        for side in ("CENTER", "LEFT", "RIGHT"):
            raw0 = out0["smooth_by_slot"][side]
            raw1 = out1["smooth_by_slot"][side]
            s0 = [str(x) for x in raw0 if x is not None]
            s1 = [str(x) for x in raw1 if x is not None]
            n_min = min(len(s0), len(s1))
            labels_base.extend(s0[:n_min])
            labels_pert.extend(s1[:n_min])
            if len(s0) >= 2:
                shuf_vals.append(lf.shuffle_baseline(s0, seed=seed))
                for idx_pair in range(len(raw0) - 1):
                    if raw0[idx_pair] is not None and raw0[idx_pair + 1] is not None:
                        p_curr = str(sel_pids[min(idx_pair + 1, len(sel_pids) - 1)])
                        p_blk = blocks_map.get(p_curr, f"{seq_spec['seq_id']}:{p_curr}")
                        _add_cluster(
                            adj_by_block,
                            p_blk,
                            1.0 if str(raw0[idx_pair]) == str(raw0[idx_pair + 1]) else 0.0,
                            1.0,
                        )

        # M3.4 & M3.5 OpenCV texture + kerb evidence
        descs = []
        for idx_p, pid in enumerate(sel_pids):
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
        first_pid = sel_pids[0]
        front_im = out0["views"].get(first_pid, {}).get("front")
        if front_im is not None:
            t_ans = await tea.ask_teacher(
                teacher_runner,
                cache=teacher_cache,
                task="surface_slot",
                image=front_im,
                extra_images=[zt["image"] for zt in tea.tiles(front_im)],
                schema=schemas.SurfaceSlotVerdict,
                seed=seed,
                side="CENTER",
            )
            if t_ans["result"] is not None:
                t_mat = t_ans["result"].get("material")
                s_mat = out0["smooth_by_slot"]["CENTER"][0]
                if t_mat and s_mat:
                    _add_cluster(
                        teacher_by_block,
                        str(seq_spec["seq_id"]),
                        1.0 if t_mat == s_mat else 0.0,
                        1.0,
                    )

    # M3.3 & M3.7 true cross-day 20 m bin agreement across manifest['repeat_pairs']
    for rp_idx, rp in enumerate(manifest.get("repeat_pairs", [])[:2]):
        pairs_ab = rp.get("capture_pairs") or rp.get("pano_pairs") or []
        pids_a: list[str] = []
        pids_b: list[str] = []
        for pa, pb in pairs_ab:
            if pa not in pids_a and len(pids_a) < 6:
                pids_a.append(str(pa))
            if pb not in pids_b and len(pids_b) < 6:
                pids_b.append(str(pb))
        sel_a = (
            panos_all[panos_all[id_col].isin(pids_a)].sort_values("seq_idx").reset_index(drop=True)
        )
        sel_b = (
            panos_all[panos_all[id_col].isin(pids_b)].sort_values("seq_idx").reset_index(drop=True)
        )
        if len(sel_a) < 2 or len(sel_b) < 2:
            continue

        key_a = tuple(sel_a[id_col].astype(str).tolist())
        if key_a in cached_uc3_runs:
            out_a = cached_uc3_runs[key_a]
        else:
            frames_a = frames[frames[id_col].isin(sel_a[id_col])].merge(
                sel_a[[id_col, "seq_idx", "travel_deg"]], on=id_col
            )
            out_a = await uc.uc3_run(sel_a, frames_a, fetch, student_runner, intr, variant=variant)
            cached_uc3_runs[key_a] = out_a

        key_b = tuple(sel_b[id_col].astype(str).tolist())
        if key_b in cached_uc3_runs:
            out_b = cached_uc3_runs[key_b]
        else:
            frames_b = frames[frames[id_col].isin(sel_b[id_col])].merge(
                sel_b[[id_col, "seq_idx", "travel_deg"]], on=id_col
            )
            out_b = await uc.uc3_run(sel_b, frames_b, fetch, student_runner, intr, variant=variant)
            cached_uc3_runs[key_b] = out_b

        # Project sel_a and sel_b onto the along-road axis of sel_a in 20 m bins
        lat0, lng0 = float(sel_a["lat"].iloc[0]), float(sel_a["lng"].iloc[0])
        ea, na, _ = geo.lla_to_enu(
            sel_a["lat"].to_numpy(), sel_a["lng"].to_numpy(), 0.0, lat0, lng0, 0.0
        )
        eb, nb, _ = geo.lla_to_enu(
            sel_b["lat"].to_numpy(), sel_b["lng"].to_numpy(), 0.0, lat0, lng0, 0.0
        )
        axis = np.array([ea[-1] - ea[0], na[-1] - na[0]], dtype=float)
        norm_axis = float(np.hypot(axis[0], axis[1]))
        if norm_axis > 1e-3:
            axis /= norm_axis
        else:
            axis = np.array([0.0, 1.0], dtype=float)
        s_a = ea * axis[0] + na * axis[1]
        s_b = eb * axis[0] + nb * axis[1]
        s_min = float(min(np.min(s_a), np.min(s_b)))
        bins_a = [int(math.floor((float(x) - s_min) / 20.0)) for x in s_a]
        bins_b = [int(math.floor((float(x) - s_min) / 20.0)) for x in s_b]

        t_deg_a = (
            float(sel_a["travel_deg"].iloc[0]) if np.isfinite(sel_a["travel_deg"].iloc[0]) else 0.0
        )
        t_deg_b = (
            float(sel_b["travel_deg"].iloc[0]) if np.isfinite(sel_b["travel_deg"].iloc[0]) else 0.0
        )
        opp_dir = abs(float(geo.angdiff(t_deg_a, t_deg_b))) > 90.0
        side_map_b = {
            "CENTER": "CENTER",
            "LEFT": "RIGHT" if opp_dir else "LEFT",
            "RIGHT": "LEFT" if opp_dir else "RIGHT",
        }

        shared_bins = sorted(set(bins_a) & set(bins_b))
        for b_idx in shared_bins:
            idx_in_a = [i for i, b_val in enumerate(bins_a) if b_val == b_idx]
            idx_in_b = [i for i, b_val in enumerate(bins_b) if b_val == b_idx]
            for side in ("CENTER", "LEFT", "RIGHT"):
                side_b = side_map_b[side]
                labs_a = [
                    str(out_a["smooth_by_slot"][side][i])
                    for i in idx_in_a
                    if out_a["smooth_by_slot"][side][i] is not None
                ]
                labs_b = [
                    str(out_b["smooth_by_slot"][side_b][i])
                    for i in idx_in_b
                    if out_b["smooth_by_slot"][side_b][i] is not None
                ]
                if labs_a and labs_b:
                    mode_a = max(set(labs_a), key=labs_a.count)
                    mode_b = max(set(labs_b), key=labs_b.count)
                    blk_key = f"{rp.get('seq_a', 'a')}:{rp_idx}:bin{b_idx:03d}"
                    _add_cluster(
                        repeat_bin_by_block,
                        blk_key,
                        1.0 if mode_a == mode_b else 0.0,
                        1.0,
                    )
                    rep_slot_a.append(f"{side}:{mode_a}")
                    rep_slot_b.append(f"{side}:{mode_b}")
                    rep_slot_blks.append(blk_key)

    m3_1 = lf.kappa(labels_base, labels_pert)
    if m3_1.status == "missing" and labels_base:
        raw_agree = sum(a == b for a, b in zip(labels_base, labels_pert, strict=True)) / len(
            labels_base
        )
        m3_1 = lf.Measurement.missing(
            f"{m3_1.reason} (raw_agreement={raw_agree:.3f})",
            n_clusters=len(labels_base),
        )

    m3_2 = _ratio_measurement(
        adj_by_block,
        seed=seed,
        placebo=float(np.mean(shuf_vals)) if shuf_vals else None,
        missing_reason="no sequences with >= 2 panos",
    )

    m3_3 = _ratio_measurement(
        repeat_bin_by_block,
        seed=seed,
        missing_reason=(
            "no overlapping 20 m bins in cross-day repeat pairs"
            if manifest.get("repeat_pairs")
            else "no cross-day repeat pairs in AOI"
        ),
    )

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
        m3_5 = lf.Measurement.missing(
            f"{m3_5.reason} (raw_agreement={raw_match:.3f})",
            n_clusters=len(kerb_preds),
        )

    m3_6 = _ratio_measurement(
        teacher_by_block,
        seed=seed,
        disclosure=lf.TEACHER_DISCLOSURE,
        missing_reason="no teacher slot verdicts",
    )

    m3_7 = lf.repeat_pass_agreement_vs_placebo(rep_slot_a, rep_slot_b, rep_slot_blks, seed=seed)

    return {
        "M3.1": m3_1,
        "M3.2": m3_2,
        "M3.3": m3_3,
        "M3.4": m3_4,
        "M3.5": m3_5,
        "M3.6": m3_6,
        "M3.7": m3_7,
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
    screen_by_block: dict[str, tuple[float, float]] = {}
    decoy_by_block: dict[str, tuple[float, float]] = {}
    random_rates_all: list[float] = []
    retained_by_block: dict[str, tuple[float, float]] = {}
    retest_by_block: dict[str, tuple[float, float]] = {}
    teacher_trace_by_block: dict[str, tuple[float, float]] = {}
    eave_rays_by_target: dict[str, list[tri.Ray]] = {}

    w4, h4 = variant.uc4_view_size
    pert_spec = manifest["perturbations"][0]
    for t in manifest["uc4_targets"][:4]:
        _, chosen, screen_recs = uc.uc4_select_views(
            frames,
            t["lat"],
            t["lng"],
            fetch,
            intr,
            n_views=2,
            width=w4,
            height=h4,
            variant=variant,
        )
        for s_idx, srec in enumerate(screen_recs[:2]):
            s_im = srec["image"]
            t_vis = await tea.ask_teacher(
                teacher_runner,
                cache=teacher_cache,
                task="roof_visibility",
                image=s_im,
                extra_images=[zt["image"] for zt in tea.tiles(s_im)],
                schema=schemas.RoofVisibility,
                seed=seed,
            )
            if t_vis["result"] is not None:
                vis_ok = bool(t_vis["result"].get("edge_50pct_visible"))
                scr_rej = bool(srec["screen"]["rejected"])
                _add_cluster(
                    screen_by_block,
                    f"{t['block_id']}:s{s_idx}",
                    1.0 if (scr_rej == (not vis_ok)) else 0.0,
                    1.0,
                )

        if not chosen:
            continue
        out0 = await uc.uc4_run(chosen, student_runner, width=w4, height=h4, variant=variant)
        pert_var = dataclasses.replace(variant, gemini_seed=pert_spec["gemini_seed"])
        out1 = await uc.uc4_run(chosen, student_runner, width=w4, height=h4, variant=pert_var)

        for v_idx, (res0, dec0, res1, c_view) in enumerate(
            zip(out0["results"], out0["decoy_rates"], out1["results"], chosen, strict=True)
        ):
            v_blk = f"{t['block_id']}:v{v_idx}"
            if dec0:
                _add_cluster(decoy_by_block, v_blk, float(np.mean(list(dec0.values()))), 1.0)
            if math.isfinite(res0.random_acceptance):
                random_rates_all.append(float(res0.random_acceptance))
            n_tot = len(res0.valid_edges) + len(res0.rejected_edges)
            if n_tot > 0:
                _add_cluster(retained_by_block, v_blk, float(len(res0.valid_edges)), float(n_tot))

            # M4.4 test-retest polyline agreement within 5 px
            for e_idx, e0 in enumerate(res0.valid_edges):
                same_type = [e1 for e1 in res1.valid_edges if e1.edge_type == e0.edge_type]
                if same_type:
                    d_px = min(_polyline_min_dist(e0.points, e1.points) for e1 in same_type)
                    hit_val = 1.0 if d_px <= 5.0 else 0.0
                else:
                    hit_val = 0.0
                _add_cluster(retest_by_block, f"{v_blk}:e{e_idx}", hit_val, 1.0)

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
        c0_im = chosen[0]["image"]
        t_tr = await tea.ask_teacher(
            teacher_runner,
            cache=teacher_cache,
            task="roof_trace",
            image=c0_im,
            extra_images=[zt["image"] for zt in tea.tiles(c0_im)],
            schema=schemas.RoofTrace,
            seed=seed,
        )
        if t_tr["result"] is not None and out0["results"]:
            t_edges = t_tr["result"].get("edges") or []
            s_edges = out0["results"][0].valid_edges
            if t_edges and s_edges:
                t_pts_list = [
                    [(p[1] / 1000.0 * w4, p[0] / 1000.0 * h4) for p in te["points"]]
                    for te in t_edges
                ]
                hits = sum(
                    min(_polyline_min_dist(se.points, tp) for tp in t_pts_list) <= 8.0
                    for se in s_edges
                )
                prec = hits / len(s_edges)
                rec = min(1.0, hits / len(t_pts_list))
                f1 = 2 * prec * rec / max(1e-6, prec + rec)
                _add_cluster(teacher_trace_by_block, t["block_id"], float(f1), 1.0)

    m4_1 = _ratio_measurement(
        screen_by_block,
        seed=seed,
        disclosure=lf.TEACHER_DISCLOSURE,
        missing_reason="no candidate roof views screened",
    )
    m4_2 = _ratio_measurement(
        decoy_by_block,
        seed=seed,
        placebo=float(np.mean(random_rates_all)) if random_rates_all else None,
        missing_reason="no wall decoys evaluated",
    )
    m4_3 = _ratio_measurement(
        retained_by_block,
        seed=seed,
        missing_reason="no proposed roof edges to retain",
    )
    m4_4 = _ratio_measurement(
        retest_by_block,
        seed=seed,
        missing_reason="no valid roof edges for test-retest check",
    )
    m4_5 = _ratio_measurement(
        teacher_trace_by_block,
        seed=seed,
        disclosure=lf.TEACHER_DISCLOSURE,
        missing_reason="no overlapping student/teacher roof traces",
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
    thinking_level: str | None = None,
    media_resolution: str | None = None,
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
    if thinking_level is not None:
        variant = dataclasses.replace(variant, thinking_level=thinking_level)
    if media_resolution is not None:
        variant = dataclasses.replace(variant, media_resolution=media_resolution)
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
    return _write_outputs(
        out_path,
        aoi,
        variant_name,
        manifest,
        metrics,
        spend,
        extra={
            "thinking_level": variant.thinking_level,
            "media_resolution": variant.media_resolution,
        },
    )


def load_aoi_frames(
    project: str,
    bucket: str,
    aoi: str,
    radius_m: float = 400.0,
    *,
    include_unpublished: bool = True,
) -> pd.DataFrame:
    """Load multi-AOI rosettes from `pano_observations_all` (cached under DEFAULT_QUERY_CACHE)
    and expand to frames via `data.frames_from_rosettes` (preserving `pano_id IS NULL` rows)."""
    creds = auth.get_credentials()
    bq = data.QueryRunner(
        data.make_bigquery_client(project, creds),
        allowed_tables=data.pano_tables(project, data.DATASET),
        cache_dir=data.DEFAULT_QUERY_CACHE,
    )
    table = data.pano_table(project, data.DATASET, "pano_observations_all")
    aois_named = {
        "lakeland_fl": mf.AOI_CENTRES["tune"],
        "salt_lake_ut": mf.AOI_CENTRES["heldout"],
        "osaka_jp": mf.AOI_CENTRES["stress"],
    }
    rosettes = bq.run(
        data.multi_aoi_sql(table),
        data.multi_aoi_rosette_params(
            aois_named, radius_m=radius_m, include_unpublished=include_unpublished
        ),
        template_name="multi_aoi_sql",
    )
    target_name = mf.CANONICAL_AOI_NAME.get(aoi, aoi)
    sub_rosettes = rosettes[rosettes["aoi"] == target_name].copy()
    return data.frames_from_rosettes(sub_rosettes, bucket=bucket).reset_index(drop=True)


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--uc", choices=("1", "2", "3", "4", "all"), default="all")
    ap.add_argument("--aoi", choices=("tune", "heldout", "stress"), default="tune")
    ap.add_argument("--variant", choices=tuple(VARIANTS.keys()), default="baseline")
    ap.add_argument(
        "--thinking-level",
        choices=("MINIMAL", "LOW", "MEDIUM", "HIGH"),
        default=None,
        help="Override Variant.thinking_level (e.g., MINIMAL, LOW, MEDIUM, HIGH)",
    )
    ap.add_argument(
        "--media-resolution",
        choices=("LOW", "MEDIUM", "HIGH"),
        default=None,
        help="Override Variant.media_resolution (e.g., LOW, MEDIUM, HIGH)",
    )
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
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    ap = build_arg_parser()
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
    if args.thinking_level is not None:
        variant = dataclasses.replace(variant, thinking_level=args.thinking_level)
    if args.media_resolution is not None:
        variant = dataclasses.replace(variant, media_resolution=args.media_resolution)
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
            print(
                f"[labelfree] {args.aoi}/{args.variant} finished UC1 (calls={s_runner.cost.calls + t_runner.cost.calls})",
                flush=True,
            )
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
            print(
                f"[labelfree] {args.aoi}/{args.variant} finished UC2 (calls={s_runner.cost.calls + t_runner.cost.calls})",
                flush=True,
            )
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
            print(
                f"[labelfree] {args.aoi}/{args.variant} finished UC3 (calls={s_runner.cost.calls + t_runner.cost.calls})",
                flush=True,
            )
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
            print(
                f"[labelfree] {args.aoi}/{args.variant} finished UC4 (calls={s_runner.cost.calls + t_runner.cost.calls})",
                flush=True,
            )
        return out_m

    metrics = asyncio.run(_run_selected())
    spend = {
        "usd": round(s_runner.cost.usd + t_runner.cost.usd, 4),
        "calls": s_runner.cost.calls + t_runner.cost.calls,
        "input_tokens": s_runner.cost.input_tokens + t_runner.cost.input_tokens,
        "output_tokens": s_runner.cost.output_tokens + t_runner.cost.output_tokens,
        "thoughts_tokens": s_runner.cost.thoughts_tokens + t_runner.cost.thoughts_tokens,
        "student_usd": round(s_runner.cost.usd, 4),
        "teacher_usd": round(t_runner.cost.usd, 4),
    }
    _write_outputs(
        out_path,
        args.aoi,
        args.variant,
        manifest,
        metrics,
        spend,
        extra={
            "thinking_level": variant.thinking_level,
            "media_resolution": variant.media_resolution,
        },
    )
    print(f"[labelfree] actual spend: ${spend['usd']:.4f} ({spend['calls']} calls)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
