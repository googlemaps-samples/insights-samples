#!/usr/bin/env python3
"""T9 evaluation driver.

    ../../../.venv/bin/python scripts/run_eval.py --synthetic
    ../../../.venv/bin/python scripts/run_eval.py --self-consistency --max-gemini-calls 400
    ../../../.venv/bin/python scripts/run_eval.py --labels data/label_kit/labels.csv \
        --pipeline-output data/label_kit/pipeline_output.json

--synthetic: objects placed along REAL drive paths (the cached multi-AOI pano metadata query,
0 extra bytes if cached), detections simulated through the fitted camera model, full dedup
pipeline vs baselines B0/B1 (0 Gemini calls).
--self-consistency: real panos, Gemini boxes on code-rendered views, cross-view presence
checks, detection stability and repeat-pass entity matching (Gemini calls bounded by
--max-gemini-calls; counts and estimated cost are printed before and after).
Every mode writes data/eval_<date>_<mode>.md and .json (gitignored).
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_calibration_panos import AOIS  # noqa: E402

from svi_geo import auth, data, geo, images, pipeline, rosette, sequence  # noqa: E402
from svi_geo import entities as ent  # noqa: E402
from svi_geo import eval as ev  # noqa: E402
from svi_geo import gemini_client as gc  # noqa: E402
from svi_geo import simulate as sim  # noqa: E402

SIGMAS = (0.5, 1.0, 2.0)
TARGETS = {  # sigma = 1 deg, calibrated pipeline
    "purity": (">=", 0.90),
    "completeness": (">=", 0.80),
    "duplicate_rate": ("<=", 0.15),
    "loc_err_median_m": ("<=", 1.5),
    "loc_err_p90_m": ("<=", 4.0),
}
M_PIPE = "pipeline (calibrated)"
M_PIPE_DEF = "pipeline (placeholder intrinsics)"
M_SV = "single-view only (calibrated)"
M_B1 = "B1: 12 m + DBSCAN 3 m (placeholder intrinsics)"
M_B1C = "B1 with calibrated intrinsics"
M_B0 = "B0: no dedup"
METHODS = (M_PIPE, M_PIPE_DEF, M_SV, M_B1, M_B1C, M_B0)
COLS = (
    "purity",
    "completeness",
    "duplicate_rate",
    "entities_per_object",
    "v_measure",
    "ari",
    "loc_err_median_m",
    "loc_err_p90_m",
    "missed_rate",
)


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_aoi_frames(runner, radius_m: float) -> pd.DataFrame:
    raw = runner.run(
        data.multi_aoi_meta_sql(), data.multi_aoi_params(list(AOIS.values()), radius_m)
    )
    return data.assign_nearest_aoi(data.normalize_frames(raw), AOIS, radius_m * 1.5)


def with_sequences(frames: pd.DataFrame) -> pd.DataFrame:
    seqs = sequence.build_sequences(data.panos_from_frames(frames))
    return frames.merge(seqs[["pano_id", "seq_id", "seq_idx"]], on="pano_id")


def nearest_panos(frames: pd.DataFrame, centre, n: int) -> pd.DataFrame:
    p = frames.drop_duplicates("pano_id")
    d = geo.haversine_m(p["lat"].to_numpy(), p["lng"].to_numpy(), centre[0], centre[1])
    keep = set(p["pano_id"].to_numpy()[np.argsort(d)[:n]])
    return frames[frames["pano_id"].isin(keep)]


def _fmt(v) -> str:
    return "n/a" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:.3f}"


# ----------------------------------------------------------------------------- synthetic


def run_synthetic(args) -> dict:
    creds = auth.get_credentials()
    runner = data.QueryRunner(
        data.make_bigquery_client(data.PROJECT, creds), cache_dir=data.DEFAULT_QUERY_CACHE
    )
    frames_all = load_aoi_frames(runner, args.radius_m)
    intr_true = rosette.load_intrinsics()
    if not intr_true.fitted:
        log("WARNING: no fitted intrinsics found; truth and pipeline both use the placeholder")
    intr_def = rosette.DEFAULT_INTRINSICS
    log(
        f"truth intrinsics: fitted={intr_true.fitted} f={intr_true.fx:.1f}; placeholder f={intr_def.fx}"
    )
    rows = []
    for aoi in args.aois:
        fa = frames_all[frames_all["aoi"] == aoi]
        fa = with_sequences(nearest_panos(fa, AOIS[aoi], args.n_panos))
        n_p = fa["pano_id"].nunique()
        n_seq = fa["seq_id"].nunique()
        for seed in range(args.seeds):
            scene = sim.make_scene(
                fa, n_poles=n_p // 4, n_signs=n_p // 8, n_houses=n_p // 6, seed=seed
            )
            tp = sim.truth_points(scene)
            for sigma in SIGMAS:
                noise = sim.NoiseModel(bearing_sigma_deg=sigma, elev_sigma_deg=sigma)
                res = sim.simulate_observations(scene, fa, intr_true, noise, seed=seed)
                truth = sim.truth_labels(res.detections)
                vis = {o for o, n in res.visible.items() if n >= 2}
                obs_c = sim.to_observations(res.detections, fa, intr_true, scene.ref_lla)
                obs_d = sim.to_observations(res.detections, fa, intr_def, scene.ref_lla)
                t0 = time.time()
                preds = {
                    M_PIPE: ev.entity_labels(ent.cluster(obs_c, scene.ref_lla), obs_c),
                    M_PIPE_DEF: ev.entity_labels(ent.cluster(obs_d, scene.ref_lla), obs_d),
                    M_SV: ev.single_view_labels(obs_c),
                    M_B1: ev.fixed_range_labels(obs_d),
                    M_B1C: ev.fixed_range_labels(obs_c),
                    M_B0: ev.b0_labels(obs_c),
                }
                for m, (lab, cen) in preds.items():
                    met = ev.clustering_metrics(lab, truth, cen, tp, visible_objects=vis)
                    rows.append({"aoi": aoi, "seed": seed, "sigma": sigma, "method": m, **met})
                log(
                    f"{aoi} seed={seed} sigma={sigma}: panos={n_p} seqs={n_seq} objects="
                    f"{len(scene.objects)} dets={len(res.detections)} ({time.time() - t0:.1f}s)"
                )
    df = pd.DataFrame(rows)
    agg = df.groupby(["sigma", "method"])[list(COLS)].mean().reset_index()
    at1 = agg[agg["sigma"] == 1.0].set_index("method")
    checks = {}
    for k, (op, thr) in TARGETS.items():
        v = float(at1.loc[M_PIPE, k])
        checks[f"{k} {op} {thr}"] = bool(v >= thr if op == ">=" else v <= thr)
    vm_p, vm_b = float(at1.loc[M_PIPE, "v_measure"]), float(at1.loc[M_B1, "v_measure"])
    dr_p, dr_b = float(at1.loc[M_PIPE, "duplicate_rate"]), float(at1.loc[M_B1, "duplicate_rate"])
    checks["V-measure >= 1.25 x B1"] = bool(vm_p >= 1.25 * vm_b)
    checks["duplicate_rate <= B1 / 2"] = bool(dr_p <= dr_b / 2)
    return {"rows": rows, "agg": agg.to_dict("records"), "checks": checks, "args": vars(args)}


def synthetic_report(res: dict) -> str:
    agg = pd.DataFrame(res["agg"])
    a = res["args"]
    lines = [
        "# Synthetic dedup evaluation (T9a)",
        "",
        f"AOIs: {', '.join(a['aois'])}; up to {a['n_panos']} real panos per AOI (real drive "
        f"paths and per-camera poses from pano_observations_latest); {a['seeds']} scene seeds; "
        "noise: bearing/elevation sigma as listed, pose 0.5 m / 0.3 deg, 20% dropout, 10% "
        "false positives, 5% class confusion. Truth uses the fitted intrinsics; the pipeline's "
        "bearing_sigma_deg is fixed at its default (1.0) for every sigma. Means over AOIs x seeds.",
        "",
    ]
    for sigma in SIGMAS:
        lines += [f"## sigma = {sigma} deg", "", "| method | " + " | ".join(COLS) + " |"]
        lines.append("|---" * (len(COLS) + 1) + "|")
        sub = agg[agg["sigma"] == sigma].set_index("method")
        for m in METHODS:
            if m in sub.index:
                lines.append(f"| {m} | " + " | ".join(_fmt(sub.loc[m, c]) for c in COLS) + " |")
        lines.append("")
    lines += ["## Acceptance (sigma = 1 deg, calibrated pipeline)", ""]
    lines += [f"- {k}: {'PASS' if v else 'FAIL'}" for k, v in res["checks"].items()]
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------------- self-consistency


def find_repeat_passes(frames: pd.DataFrame, n: int, max_d_m: float = 8.0):
    """(aoi, panos of pass A, panos of pass B): two sequences that drive the same road."""
    for aoi in sorted(frames["aoi"].dropna().unique()):
        fa = with_sequences(frames[frames["aoi"] == aoi])
        p = fa.drop_duplicates("pano_id").sort_values(["seq_id", "seq_idx"])
        lens = p.groupby("seq_id").size().sort_values(ascending=False)
        seqs = list(lens[lens >= n].index)  # pass A needs n consecutive panos
        others = list(lens[lens >= 2].index)  # pass B: any other drive over that road
        for sa in seqs:
            a = p[p["seq_id"] == sa]
            for sb in others:
                if sb == sa:
                    continue
                b = p[p["seq_id"] == sb]
                d = geo.haversine_m(
                    a["lat"].to_numpy()[:, None],
                    a["lng"].to_numpy()[:, None],
                    b["lat"].to_numpy()[None],
                    b["lng"].to_numpy()[None],
                )
                close = d.min(1) <= max_d_m
                if close.sum() < n:
                    continue
                # n consecutive A panos on the shared road, and the B panos next to them
                idx = np.flatnonzero(close)
                for s in range(len(idx) - n + 1):
                    run = idx[s : s + n]
                    if run[-1] - run[0] == n - 1:
                        pa = list(a["pano_id"].to_numpy()[run])
                        pb = sorted(set(b["pano_id"].to_numpy()[d[run].argmin(1)]))
                        return aoi, fa, pa, pb
    return None


async def run_self_consistency_async(args) -> dict:
    creds = auth.get_credentials()
    from google.cloud import storage

    runner_bq = data.QueryRunner(
        data.make_bigquery_client(data.PROJECT, creds), cache_dir=data.DEFAULT_QUERY_CACHE
    )
    frames_all = load_aoi_frames(runner_bq, args.radius_m)
    bucket = data.discover_bucket(runner_bq)
    found = find_repeat_passes(frames_all, args.sc_panos)
    if found is None:
        raise SystemExit("no repeat pass with enough panos found in the AOIs")
    aoi, fa, pa, pb = found
    log(f"AOI {aoi}: pass A {len(pa)} panos, pass B {len(pb)} panos")
    fa = fa.copy()
    fa["gcs_uri"] = [
        data.gcs_uri_for(bucket, s, o)
        for s, o in zip(fa["snapshot_id"], fa["observation_id"], strict=True)
    ]
    fr_a = fa[fa["pano_id"].isin(pa) & fa["cam_k"].between(0, 5)]
    fr_b = fa[fa["pano_id"].isin(pb) & fa["cam_k"].between(0, 5)]
    fetcher = images.GcsImageFetcher(storage.Client(project=data.PROJECT, credentials=creds))
    uris = sorted(set(fr_a["gcs_uri"]) | set(fr_b["gcs_uri"]))
    res = fetcher.fetch_many(uris, max_workers=4)
    bad = [u for u, v in res.items() if isinstance(v, Exception)]
    if bad:
        log(f"{len(bad)} frames failed to download; dropping them")
        fr_a, fr_b = fr_a[~fr_a["gcs_uri"].isin(bad)], fr_b[~fr_b["gcs_uri"].isin(bad)]
    intr = rosette.load_intrinsics()
    ref = sim.scene_ref(pd.concat([fr_a, fr_b]))
    n_det = len(fr_a) + len(fr_b)
    n_est = n_det + args.max_presence
    log(
        f"planned Gemini calls: {n_det} detection views + <= {args.max_presence} presence checks; "
        f"estimated cost ${gc.estimate_cost(n_est):.2f} (budget MAX_GEMINI_CALLS="
        f"{args.max_gemini_calls})"
    )
    client = gc.make_vertex_client(data.PROJECT, gc.DEFAULT_LOCATION, creds)
    runner = gc.GeminiRunner(
        gc.VertexGeminiBackend(client, model=args.model),
        max_calls=args.max_gemini_calls,
        concurrency=args.concurrency,
        log=log,
    )
    run_a = await pipeline.detect_panos(fr_a, fetcher.fetch, runner, intr, ref)
    log(f"pass A: {len(run_a.observations)} observations; {runner.cost.summary()}")
    run_b = await pipeline.detect_panos(fr_b, fetcher.fetch, runner, intr, ref)
    log(f"pass B: {len(run_b.observations)} observations; {runner.cost.summary()}")
    ent_a = ent.cluster(run_a.observations, ref)
    ent_b = ent.cluster(run_b.observations, ref)

    render = pipeline.task_renderer(fr_a, fetcher.fetch, intr)
    sc = await ev.self_consistency(
        ent_a,
        fr_a,
        intr,
        ref,
        render,
        runner,
        max_tasks=args.max_presence,
        passes=(ent_a, ent_b),
    )
    per_cls_b = defaultdict(int)
    for e in ent_b:
        per_cls_b[e.cls] += 1
    per_cls_a = defaultdict(int)
    for e in ent_a:
        per_cls_a[e.cls] += 1
    out = {
        "aoi": aoi,
        "n_panos_a": len(pa),
        "n_panos_b": len(pb),
        "entities_a": dict(per_cls_a),
        "entities_b": dict(per_cls_b),
        "entities_a_multi_view": sum(e.n_panos >= 2 for e in ent_a),
        "observations_a": len(run_a.observations),
        "observations_b": len(run_b.observations),
        "cross_view": {k: v for k, v in sc["cross_view"].items() if k != "per_task"},
        "per_task": sc["cross_view"]["per_task"],
        "stability": sc["stability"],
        "repeat_pass": sc["repeat_pass"],
        "repeat_pass_multi_view": sc["repeat_pass_multi_view"],
        "gemini": {
            "calls": runner.cost.calls,
            "failures": runner.cost.failures,
            "input_tokens": runner.cost.input_tokens,
            "output_tokens": runner.cost.output_tokens,
            "thinking_tokens": runner.cost.thoughts_tokens,
            "est_cost_usd": runner.cost.usd,
        },
        "args": vars(args),
    }
    log(runner.cost.summary())
    return out


def sc_report(r: dict) -> str:
    cv, rp, g = r["cross_view"], r["repeat_pass"], r["gemini"]
    rpm = r["repeat_pass_multi_view"]
    lines = [
        "# Self-consistency on real panos (T9b)",
        "",
        f"AOI {r['aoi']}: pass A {r['n_panos_a']} consecutive panos, pass B {r['n_panos_b']} "
        "panos of an independent drive over the same road.",
        f"Observations A/B: {r['observations_a']}/{r['observations_b']}; entities A: "
        f"{r['entities_a']} ({r['entities_a_multi_view']} multi-view); entities B: "
        f"{r['entities_b']}.",
        "",
        "| metric | value | target |",
        "|---|---|---|",
        f"| cross-view confirmation rate ({cv['n_asked']} presence checks) | "
        f"{_fmt(cv['confirmation_rate'])} | >= 0.75 |",
        f"| median azimuth offset, deg | {_fmt(cv['median_offset_deg'])} | < 2 |",
        f"| median signed azimuth offset, deg | {_fmt(cv['median_signed_offset_deg'])} | ~0 |",
        *(
            f"| median azimuth offset {c}, deg | {_fmt(v)} | |"
            for c, v in cv["median_offset_deg_by_class"].items()
        ),
        f"| repeat-pass entity recall A in B | {_fmt(rp['recall_a_in_b'])} | >= 0.7 |",
        f"| repeat-pass entity recall B in A | {_fmt(rp['recall_b_in_a'])} | |",
        f"| entity count ratio B/A | {_fmt(rp['count_ratio'])} | |",
        f"| repeat-pass recall A in B, multi-view entities only ({int(rpm['n_a'])} vs "
        f"{int(rpm['n_b'])}) | {_fmt(rpm['recall_a_in_b'])} | |",
    ]
    for c, v in r["stability"].items():
        lines.append(f"| detection stability {c} | {_fmt(v)} | |")
    lines += [
        "",
        f"Gemini: {g['calls']} calls ({g['failures']} failures), {g['input_tokens']:,} input / "
        f"{g['output_tokens']:,} output tokens ({g['thinking_tokens']:,} thinking), estimated "
        f"${g['est_cost_usd']:.3f} at list-price estimates.",
        "",
        "Caveat: presence checks are answered by the same model family that produced the "
        "detections, so agreement is correlated with its own errors; hand labels (9c) are the "
        "only independent check.",
    ]
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------------- main


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--self-consistency", action="store_true")
    ap.add_argument("--labels")
    ap.add_argument("--pipeline-output")
    ap.add_argument("--aois", nargs="+", default=["paris_south", "salt_lake_ut", "osaka_jp"])
    ap.add_argument("--n-panos", type=int, default=150)
    ap.add_argument("--seeds", type=int, default=2)
    ap.add_argument("--sc-panos", type=int, default=10, help="panos per pass (self-consistency)")
    ap.add_argument("--radius-m", type=float, default=250.0)
    ap.add_argument("--max-gemini-calls", type=int, default=gc.DEFAULT_MAX_CALLS)
    ap.add_argument("--max-presence", type=int, default=80)
    ap.add_argument("--concurrency", type=int, default=gc.DEFAULT_CONCURRENCY)
    ap.add_argument("--model", default=gc.DEFAULT_MODEL)
    ap.add_argument("--out-dir", default="data")
    args = ap.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d")
    if args.synthetic:
        res = run_synthetic(args)
        (out / f"eval_{stamp}_synthetic.json").write_text(json.dumps(res, indent=1, default=str))
        md = synthetic_report(res)
        (out / f"eval_{stamp}_synthetic.md").write_text(md)
        print(md)
    if args.self_consistency:
        res = asyncio.run(run_self_consistency_async(args))
        (out / f"eval_{stamp}_self_consistency.json").write_text(
            json.dumps(res, indent=1, default=str)
        )
        md = sc_report(res)
        (out / f"eval_{stamp}_self_consistency.md").write_text(md)
        print(md)
    if args.labels:
        preds = json.loads(Path(args.pipeline_output).read_text()) if args.pipeline_output else []
        s = ev.score_hand_labels(args.labels, preds)
        if s is None:
            print(f"{args.labels} not found; skipping hand-label scoring")
        else:
            (out / f"eval_{stamp}_labels.json").write_text(json.dumps(s, indent=1))
            print(json.dumps(s, indent=1))


if __name__ == "__main__":
    main()
