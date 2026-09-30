#!/usr/bin/env python3
"""T3d: fit the shared rosette intrinsics on real pano frames and evaluate on held-out panos.

    ../../../.venv/bin/python scripts/fit_intrinsics.py --use-sequence \
        --out svi_geo/intrinsics/rosette_kb4_v1.json --report data/calib_report.md

Everything is deterministic numpy/OpenCV/scipy; no LLM is involved. Held-out panos (whole
drive sequences, chosen by a stable hash of the sequence id) are never used in the fit.
Outputs under data/ are gitignored; only the intrinsics JSON is meant to be committed.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
from google.cloud import storage

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_calibration_panos import AOIS  # noqa: E402

from svi_geo import (  # noqa: E402
    auth,
    calib_real,
    calibrate,
    config,
    data,
    images,
    rosette,
    sequence,
)
from svi_geo import calib_features as cf  # noqa: E402

W, H = 3648, 5472
ALL_CONV = [(1, 1), (-1, 1), (1, -1), (-1, -1)]


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def heldout_neighbours(runner, calib: pd.DataFrame, bucket: str, radius_m: float) -> pd.DataFrame:
    """Frames of the next (or previous) pano in the drive of each held-out pano (cache hit)."""
    raw = runner.run(
        data.multi_aoi_meta_sql(), data.multi_aoi_params(list(AOIS.values()), radius_m)
    )
    frames = data.assign_nearest_aoi(data.normalize_frames(raw), AOIS, radius_m * 1.5)
    panos = data.panos_from_frames(frames)
    seqs = sequence.build_sequences(panos)
    held = calib[calib["split"] == "heldout"]["pano_id"].unique()
    pick = {}
    by_seq = {sid: g.sort_values("seq_idx") for sid, g in seqs.groupby("seq_id")}
    s_of = seqs.set_index("pano_id")
    for pid in held:
        if pid not in s_of.index:
            continue
        g = by_seq[s_of.loc[pid, "seq_id"]]
        i = int(s_of.loc[pid, "seq_idx"])
        nxt = g[g["seq_idx"] == i + 1]
        prv = g[g["seq_idx"] == i - 1]
        nb = nxt if len(nxt) else prv
        if len(nb):
            pick[nb["pano_id"].iloc[0]] = pid
    nb = frames[frames["pano_id"].isin(pick) & frames["cam_k"].between(0, 5)].copy()
    nb["split"] = "heldout_nb"
    nb["pair_of"] = nb["pano_id"].map(pick)
    nb["gcs_uri"] = [
        data.gcs_uri_for(bucket, s, o)
        for s, o in zip(nb["snapshot_id"], nb["observation_id"], strict=True)
    ]
    return nb


def consecutive_pairs(df: pd.DataFrame) -> list[tuple[str, str]]:
    pairs = []
    for _, g in df.drop_duplicates("pano_id").groupby("seq_id"):
        g = g.sort_values("seq_idx")
        ids, idx = list(g["pano_id"]), list(g["seq_idx"])
        for i in range(len(ids) - 1):
            if idx[i + 1] - idx[i] == 1:
                pairs.append((ids[i], ids[i + 1]))
    return pairs


def with_radius(intr: rosette.Intrinsics, r: float) -> rosette.Intrinsics:
    return dataclasses.replace(intr, rosette_radius_m=float(r))


def build_problem(inst, feats, pano_ids, pairs, intr, intra_thr, seq_thr, chains_raw):
    ms = calib_real.intra_matches(inst, feats, pano_ids, W, intr=intr, thr_deg=intra_thr)
    if pairs:
        seq_intr = intr or rosette.DEFAULT_INTRINSICS
        calib_real.sequence_matches(inst, feats, pairs, seq_intr, thr_deg=seq_thr, out=ms)
    chains = calib_real.select_chains(inst, intr, chains_raw) if (intr and chains_raw) else []
    return ms.problem(inst, W, H, len(pairs), chains)


def stats(x: np.ndarray) -> dict:
    x = np.asarray(x, float)
    if not len(x):
        return {"n": 0}
    return {
        "n": int(len(x)),
        "median": float(np.median(x)),
        "p90": float(np.percentile(x, 90)),
        "mean": float(np.mean(x)),
    }


def seam_check(frames_by_key, fetcher, intr, pano_ids, out_dir: Path | None, tag: str):
    """Render adjacent cameras at their bisector heading (hfov 30, 1000 px) and measure the
    SIFT displacement between the two renders. The rosette baseline (~0.08-0.16 m) causes a
    horizontal parallax, so the gated metric is the vertical displacement component (QA F5);
    total displacement is reported too."""
    view_kw = {"pitch_deg": 0.0, "hfov_deg": 30.0, "width": 1000, "height": 1000}
    deg_per_px = 30.0 / 1000
    sift = cv2.SIFT_create(nfeatures=3000)
    dy_all, d_all, n_pairs = [], [], 0
    for pid in pano_ids:
        for k in range(6):
            k2 = (k + 1) % 6
            if (pid, k) not in frames_by_key or (pid, k2) not in frames_by_key:
                continue
            ra, rb = frames_by_key[(pid, k)], frames_by_key[(pid, k2)]
            ha, hb = ra["camera_pose"]["heading"], rb["camera_pose"]["heading"]
            yaw = ha + (((hb - ha + 180.0) % 360.0) - 180.0) / 2.0
            view = rosette.PerspectiveView(yaw_deg=float(yaw), **view_kw)
            ims = []
            for r in (ra, rb):
                img = images.decode(fetcher.fetch(r["gcs_uri"]), gray=True)
                ims.append(
                    rosette.render_perspective(img, intr, r["camera_pose"], view, r["cam_k"])
                )
            valid = (ims[0] > 0) & (ims[1] > 0)
            m = (valid * 255).astype(np.uint8)
            k1, d1 = sift.detectAndCompute(ims[0], m)
            k2_, d2 = sift.detectAndCompute(ims[1], m)
            if d1 is None or d2 is None:
                continue
            i1, i2 = cf.ratio_match(d1, d2, 0.75)
            if len(i1) < 8:
                continue
            p1 = np.float64([k1[i].pt for i in i1])
            p2 = np.float64([k2_[i].pt for i in i2])
            disp = p2 - p1
            ok = np.linalg.norm(disp, axis=1) < 60
            if ok.sum() < 8:
                continue
            n_pairs += 1
            dy_all.append(np.abs(disp[ok, 1]))
            d_all.append(np.linalg.norm(disp[ok], axis=1))
            if out_dir is not None and n_pairs <= 12:
                out_dir.mkdir(parents=True, exist_ok=True)
                blend = cv2.merge([ims[0], ims[1], ims[0]])  # magenta/green anaglyph
                cv2.imwrite(str(out_dir / f"{tag}_{pid[:8]}_{k}{k2}.jpg"), blend)
    dy = np.concatenate(dy_all) if dy_all else np.array([])
    d = np.concatenate(d_all) if d_all else np.array([])
    return {
        "n_pairs": n_pairs,
        "n_matches": int(len(dy)),
        "vertical_px": stats(dy),
        "total_px": stats(d),
        "vertical_deg_median": float(np.median(dy) * deg_per_px) if len(dy) else None,
        "deg_per_px": deg_per_px,
    }


def evaluate(tag, intr, prob_h, prob_hs, chains_h, frames_by_key, fetcher, held_ids, seam_dir):
    comp = calibrate.heldout_match_error_components(prob_h, intr)
    tot = np.concatenate([comp["total_a"], comp["total_b"]]) if comp else np.array([])
    across = np.concatenate([comp["across_a"], comp["across_b"]]) if comp else np.array([])
    along = np.concatenate([comp["along_a"], comp["along_b"]]) if comp else np.array([])
    seq = calibrate.heldout_match_errors(prob_hs, intr, kind=1) if prob_hs.n_seq else np.array([])
    vert = calibrate.verticality_residuals(dataclasses.replace(prob_h, chains=chains_h), intr)
    out = {
        "intra_total_deg": stats(tot),
        "intra_across_epipolar_deg": stats(across),
        "intra_along_epipolar_deg": stats(along),
        "consecutive_pano_deg": stats(seq),
        "verticality_deg": stats(vert),
        "seam": seam_check(frames_by_key, fetcher, intr, held_ids, seam_dir, tag),
    }
    log(f"eval {tag}: {json.dumps(out)}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gcs-bucket", default=None, help="frame bucket (default: $GCS_BUCKET)")
    ap.add_argument("--panos", default="data/calib_panos.parquet")
    ap.add_argument("--out", default="svi_geo/intrinsics/rosette_kb4_v1.json")
    ap.add_argument("--report", default="data/calib_report.md")
    ap.add_argument("--metrics-json", default="data/calib_metrics.json")
    ap.add_argument("--seam-dir", default="data/seams")
    ap.add_argument("--radius-m", type=float, default=250.0, help="AOI radius used by the fetch")
    ap.add_argument("--use-sequence", action="store_true")
    ap.add_argument("--iterations", type=int, default=2)
    args = ap.parse_args()

    creds = auth.get_credentials()
    runner = data.QueryRunner(
        data.make_bigquery_client(data.PROJECT, creds), cache_dir=data.DEFAULT_QUERY_CACHE
    )
    fetcher = images.GcsImageFetcher(
        storage.Client(project=data.PROJECT, credentials=creds),
        cache_dir=images.DEFAULT_FRAME_CACHE,
    )
    calib = pd.read_parquet(args.panos)
    bucket = config.require_bucket(args.gcs_bucket, env=dict(os.environ))
    nb = heldout_neighbours(runner, calib, bucket, args.radius_m)
    log(f"held-out neighbours: {nb['pano_id'].nunique()} panos; downloading missing frames")
    res = fetcher.fetch_many(list(nb["gcs_uri"]), max_workers=4)
    bad = [u for u, v in res.items() if isinstance(v, Exception)]
    nb = nb[~nb["gcs_uri"].isin(bad)]
    frames = pd.concat([calib, nb], ignore_index=True)
    frames = frames[frames["cam_k"].between(0, 5)]
    inst = calib_real.instances_from_frames(frames)
    log(
        f"instances={len(inst.instances)} measured rosette radius={inst.radius_m:.4f} m "
        f"(p10-p90 {inst.radius_p10_p90[0]:.4f}-{inst.radius_p10_p90[1]:.4f})"
    )
    uri_of = {(r.pano_id, int(r.cam_k)): r.gcs_uri for r in frames.itertuples(index=False)}
    frames_by_key = {(r["pano_id"], int(r["cam_k"])): r for r in frames.to_dict("records")}
    store = calib_real.FeatureStore(fetcher)
    feats = lambda pid, k: store.get(uri_of[(pid, k)])  # noqa: E731

    train_ids = list(calib[calib["split"].isin(["train", "pair"])]["pano_id"].unique())
    held_ids = list(calib[calib["split"] == "heldout"]["pano_id"].unique())
    pairs = consecutive_pairs(calib[calib["split"] == "pair"]) if args.use_sequence else []
    log(f"train panos={len(train_ids)} consecutive pairs={len(pairs)} held-out={len(held_ids)}")
    t = time.time()
    for pid in train_ids + held_ids:
        for k in range(6):
            if (pid, k) in uri_of:
                feats(pid, k)
    log(f"features ready in {time.time() - t:.0f}s")
    chains_raw = [
        (inst.index[(pid, k)], c)
        for pid in train_ids
        for k in range(6)
        if (pid, k) in uri_of
        for c in feats(pid, k).chains
    ]

    base = with_radius(rosette.DEFAULT_INTRINSICS, inst.radius_m)
    history = []
    # stage 0: model-free matches, all pose conventions, no lines
    prob = build_problem(inst, feats, train_ids, pairs, None, None, 1.5, None)
    log(f"stage0 problem: intra={prob.n_intra} seq={prob.n_seq}")
    res = calibrate.fit(
        prob, base, conventions=ALL_CONV, use_lines=False, radius_m=inst.radius_m, log=log
    )
    cur = res.intrinsics
    history.append({"stage": 0, **res.report, "fx": cur.fx, "conv": cur.pose_convention})
    log(
        f"stage0: f={cur.fx:.1f} cx={cur.cx:.1f} cy={cur.cy:.1f} k={cur.k1:.4f},{cur.k2:.4f},"
        f"{cur.k3:.4f} conv={cur.pose_convention} report={res.report}"
    )
    for it in range(1, args.iterations + 1):
        intra_thr, seq_thr = (2.5, 0.5) if it == 1 else (1.5, 0.3)
        prob = build_problem(inst, feats, train_ids, pairs, cur, intra_thr, seq_thr, chains_raw)
        n_vert = sum(c.vertical for c in prob.chains)
        log(
            f"stage{it} problem: intra={prob.n_intra} seq={prob.n_seq} chains={len(prob.chains)} "
            f"vertical={n_vert}"
        )
        res = calibrate.fit(
            prob,
            cur,
            conventions=[tuple(cur.pose_convention)],
            f_grid=[cur.fx],
            radius_m=inst.radius_m,
            log=log,
        )
        cur = res.intrinsics
        history.append({"stage": it, **res.report, "fx": cur.fx, "n_vertical": n_vert})
        log(
            f"stage{it}: f={cur.fx:.1f} cx={cur.cx:.1f} cy={cur.cy:.1f} "
            f"k={cur.k1:.4f},{cur.k2:.4f},{cur.k3:.4f} deltas={cur.cam_rot_delta_deg}"
        )
    final_prob = prob
    diag = calibrate.fit(
        final_prob,
        cur,
        conventions=[tuple(cur.pose_convention)],
        f_grid=[cur.fx],
        radius_m=inst.radius_m,
        fit_radius=True,
        outlier_rounds=0,
    )
    log(f"diagnostic free-radius fit: r={diag.intrinsics.rosette_radius_m:.4f} m")

    # max_theta from the observed feature distribution (99.5th pct of used pixels)
    theta = np.degrees(  # theta_of_pixel returns radians
        rosette.theta_of_pixel(cur, np.concatenate([final_prob.uv_a, final_prob.uv_b]))
    )
    # ... but at least the frame-edge midpoints: the lens images the whole sensor, and
    # features are sparse near the hood/sky, so the percentile alone clips usable pixels
    max_theta = float(
        min(110.0, max(np.percentile(theta, 99.5) + 2.0, rosette.frame_edge_theta_deg(cur) + 1.0))
    )
    cur = dataclasses.replace(cur, max_theta_deg=max_theta)

    # ------------------------------------------------------------------ held-out evaluation
    ms_h = calib_real.intra_matches(inst, feats, held_ids, W, intr=None)  # model-free set
    prob_h = ms_h.problem(inst, W, H, 0, [])
    nb_pairs = [
        (r.pair_of, r.pano_id) for r in nb.drop_duplicates("pano_id").itertuples(index=False)
    ]
    for pid in {p for pr in nb_pairs for p in pr}:
        for k in range(6):
            if (pid, k) in uri_of:
                feats(pid, k)
    ms_hs = calib_real.sequence_matches(inst, feats, nb_pairs, cur, thr_deg=1.0)
    prob_hs = ms_hs.problem(inst, W, H, len(nb_pairs), [])
    raw_h = [
        (inst.index[(pid, k)], c)
        for pid in held_ids
        for k in range(6)
        if (pid, k) in uri_of
        for c in feats(pid, k).chains
    ]
    chains_h = [c for c in calib_real.select_chains(inst, cur, raw_h) if c.vertical]
    log(
        f"held-out: intra matches={prob_h.n_intra} consecutive matches={prob_hs.n_seq} "
        f"vertical chains={len(chains_h)}"
    )
    seam_dir = Path(args.seam_dir)
    ev_fit = evaluate(
        "fitted", cur, prob_h, prob_hs, chains_h, frames_by_key, fetcher, held_ids, seam_dir
    )
    ev_def = evaluate(
        "default", base, prob_h, prob_hs, chains_h, frames_by_key, fetcher, held_ids, seam_dir
    )
    base_conv = dataclasses.replace(base, pose_convention=cur.pose_convention)
    ev_defc = evaluate(
        "default_conv", base_conv, prob_h, prob_hs, chains_h, frames_by_key, fetcher, held_ids, None
    )

    m1_fit = ev_fit["intra_total_deg"].get("median", np.nan)
    m1_def = ev_def["intra_total_deg"].get("median", np.nan)
    seam_fit = ev_fit["seam"]["vertical_px"].get("median", np.nan)
    seam_def = ev_def["seam"]["vertical_px"].get("median", np.nan)
    gates = {
        "1_intra_median_lt_1deg": bool(m1_fit < 1.0),
        "1_intra_median_lt_0.5deg_stretch": bool(m1_fit < 0.5),
        "1_intra_p90_lt_2deg": bool(ev_fit["intra_total_deg"].get("p90", np.nan) < 2.0),
        # QA S12: the 3 px (0.09 deg at 0.03 deg/px) gate is THE acceptance gate; the plan's
        # 0.27 deg figure is looser and reported as secondary only.
        "2_seam_vertical_lt_3px": bool(seam_fit < 3.0),
        "2b_secondary_seam_vertical_lt_0.27deg": bool(
            seam_fit * ev_fit["seam"]["deg_per_px"] < 0.27
        ),
        "3_verticality_median_lt_0.5deg": bool(
            ev_fit["verticality_deg"].get("median", np.nan) < 0.5
        ),
        "4_3x_better_than_default_metric1": bool(m1_def >= 3 * m1_fit),
        "4_3x_better_than_default_metric2": bool(seam_def >= 3 * seam_fit),
    }
    snapshots = sorted(calib["snapshot_id"].unique())
    metrics = {
        "created": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "n_train_panos": len(train_ids),
        "n_consecutive_pairs": len(pairs),
        "n_heldout_panos": len(held_ids),
        "heldout_split": "sha1(seq_id) < 0.25 (whole drive sequences), not FARM_FINGERPRINT(pano_id)",
        "aois": {k: list(v) for k, v in AOIS.items()},
        "measured_radius_m": inst.radius_m,
        "measured_radius_p10_p90": inst.radius_p10_p90,
        "free_radius_diagnostic_m": diag.intrinsics.rosette_radius_m,
        "fit_history": history,
        "fitted": ev_fit,
        "default": ev_def,
        "default_with_fitted_convention": ev_defc,
        "gates": gates,
    }
    final = dataclasses.replace(
        cur,
        rosette_radius_m=inst.radius_m,
        fitted=True,
        source_snapshots=snapshots,
        metrics={
            "heldout_intra_median_deg": m1_fit,
            "heldout_intra_p90_deg": ev_fit["intra_total_deg"].get("p90"),
            "heldout_seam_vertical_px_median": seam_fit,
            "heldout_verticality_median_deg": ev_fit["verticality_deg"].get("median"),
            "heldout_consecutive_median_deg": ev_fit["consecutive_pano_deg"].get("median"),
            "n_train_panos": len(train_ids),
            "n_heldout_panos": len(held_ids),
            "gates": gates,
        },
        notes=(
            "KB4 fisheye shared by cameras 0-5, fitted by scripts/fit_intrinsics.py on "
            f"{len(train_ids)} pano_observations_latest panos ({len(pairs)} consecutive pairs) "
            "from 5 AOIs; per-camera rotation deltas; rosette radius measured from camera_pose "
            "positions (not fitted)."
        ),
    )
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    final.save(args.out)
    Path(args.metrics_json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.metrics_json).write_text(json.dumps(metrics, indent=2, default=float))
    write_report(args.report, final, metrics)
    log(f"wrote {args.out}, {args.metrics_json}, {args.report}")
    log(f"gates: {json.dumps(gates)}")


def _row(name, fit, default, key):
    f, d = fit[key], default[key]
    fm = f.get("median")
    dm = d.get("median")
    return (
        f"| {name} | {fm:.3f} / {f.get('p90', float('nan')):.3f} | "
        f"{dm:.3f} / {d.get('p90', float('nan')):.3f} | {f.get('n', 0)} |"
        if fm is not None and dm is not None
        else f"| {name} | n/a | n/a | 0 |"
    )


def write_report(path, intr, m):
    fit, dflt = m["fitted"], m["default"]
    lines = [
        "# Rosette calibration report (T3d)",
        "",
        f"Created {m['created']}. Train panos: {m['n_train_panos']}, consecutive pairs: "
        f"{m['n_consecutive_pairs']}, held-out panos: {m['n_heldout_panos']}.",
        "",
        f"Held-out split: {m['heldout_split']} (deviation from the plan's FARM_FINGERPRINT; "
        "keeps whole drives out of training).",
        "",
        f"Fitted: f={intr.fx:.1f}px cx={intr.cx:.1f} cy={intr.cy:.1f} k1..k4="
        f"{intr.k1:.5f},{intr.k2:.5f},{intr.k3:.5f},{intr.k4:.5f} max_theta={intr.max_theta_deg:.1f} "
        f"pose_convention={intr.pose_convention}",
        "",
        f"Rosette radius: measured from camera_pose positions {m['measured_radius_m']:.4f} m "
        f"(p10-p90 {m['measured_radius_p10_p90'][0]:.4f}-{m['measured_radius_p10_p90'][1]:.4f}); "
        f"free-radius diagnostic fit {m['free_radius_diagnostic_m']:.4f} m (r is a gauge of the "
        "intra-pano term, so the measured value is used).",
        "",
        "## Held-out metrics (median / p90)",
        "",
        "| metric | fitted | DEFAULT placeholder | n |",
        "|---|---|---|---|",
        _row("intra-pano angular error, deg (min depth 3 m)", fit, dflt, "intra_total_deg"),
        _row("  across-epipolar component, deg", fit, dflt, "intra_across_epipolar_deg"),
        _row("  along-epipolar component, deg", fit, dflt, "intra_along_epipolar_deg"),
        _row("consecutive-pano error, deg (no gate)", fit, dflt, "consecutive_pano_deg"),
        _row("verticality, deg", fit, dflt, "verticality_deg"),
        f"| seam vertical displacement, px (0.03 deg/px) | "
        f"{fit['seam']['vertical_px'].get('median', float('nan')):.2f} / "
        f"{fit['seam']['vertical_px'].get('p90', float('nan')):.2f} | "
        f"{dflt['seam']['vertical_px'].get('median', float('nan')):.2f} / "
        f"{dflt['seam']['vertical_px'].get('p90', float('nan')):.2f} | "
        f"{fit['seam']['n_matches']} |",
        f"| seam total displacement, px (includes baseline parallax) | "
        f"{fit['seam']['total_px'].get('median', float('nan')):.2f} | "
        f"{dflt['seam']['total_px'].get('median', float('nan')):.2f} | |",
        "",
        "Seam rule: vertical component only (rosette baseline is horizontal, so parallax is "
        "horizontal; QA F5). Render: hfov 30 deg, 1000 px (0.03 deg/px; the plan's 0.09 deg/px "
        "figure was arithmetically wrong). The 3 px vertical gate is the primary acceptance "
        "gate; 0.27 deg is reported as a secondary, looser figure.",
        "",
        "Selection bias (QA S11): held-out intra-pano matches are selected model-free (pixel "
        "RANSAC), so metric 1 is unbiased. Held-out consecutive-pano matches and vertical chains "
        "are selected with the FITTED model and then reused for every column, which biases those "
        "two rows in favour of the fitted model; treat them as consistency checks, not as a fair "
        "comparison. The seam metric uses model-free SIFT on the renders.",
        "",
        "## Acceptance gates",
        "",
    ]
    lines += [f"- {k}: {'PASS' if v else 'FAIL'}" for k, v in m["gates"].items()]
    lines += [
        "",
        "## Fit history",
        "",
        "```",
        json.dumps(m["fit_history"], indent=1, default=str),
        "```",
    ]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
