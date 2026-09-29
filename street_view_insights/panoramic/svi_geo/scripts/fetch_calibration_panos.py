#!/usr/bin/env python3
"""Sample calibration panos (pano views only) and download cameras 0-5.

Outputs (gitignored):
  data/calib_panos.parquet  one row per frame (metadata only) with split = train|pair|heldout
Frames are cached full-resolution under ~/.cache/svi_geo/frames (outside the repo).

Split: whole drive sequences are assigned to held-out by a stable hash of the sequence id,
so held-out panos never share a drive with training panos.
"""

from __future__ import annotations

import argparse
import hashlib
import time
from pathlib import Path

import numpy as np
import pandas as pd
from google.cloud import storage

from svi_geo import auth, data, images, sequence

# Dense AOIs found with one aggregate query over pano_observations_latest (0.01 deg cells).
AOIS = {
    "paris_south": (48.81, 2.45),
    "lakeland_fl": (28.05, -81.96),
    "salt_lake_ut": (40.76, -111.91),
    "osaka_jp": (34.71, 135.54),
    "mountain_view_ca": (37.41, -122.02),
}


def _stable_frac(s: str) -> float:
    return int(hashlib.sha1(s.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def _daytime(panos: pd.DataFrame) -> pd.Series:
    local_hour = (
        panos["capture_time"].dt.hour + panos["capture_time"].dt.minute / 60 + panos["lng"] / 15.0
    ) % 24
    return (local_hour >= 9) & (local_hour <= 17)


def select(
    frames: pd.DataFrame, n_train: int, n_pairs: int, n_held: int, seed: int
) -> pd.DataFrame:
    panos = data.panos_from_frames(frames)
    panos = panos[_daytime(panos)]
    seqs = sequence.build_sequences(panos)
    seqs["held"] = seqs["seq_id"].map(lambda s: _stable_frac(s) < 0.25)
    rng = np.random.default_rng(seed)
    chosen = {}
    held = seqs[seqs["held"]]
    if len(held):
        # at most one pano per held-out sequence first, then fill
        firsts = held.groupby("seq_id").sample(1, random_state=seed)
        pick = firsts.sample(min(n_held, len(firsts)), random_state=seed)
        for p in pick["pano_id"]:
            chosen[p] = "heldout"
    train = seqs[~seqs["held"]]
    # consecutive pairs (i, i+1) from training sequences, far apart from each other
    long_seqs = train.groupby("seq_id").filter(lambda g: len(g) >= 4)
    pair_seq_ids = list(long_seqs["seq_id"].unique())
    rng.shuffle(pair_seq_ids)
    for sid in pair_seq_ids[:n_pairs]:
        g = long_seqs[long_seqs["seq_id"] == sid].sort_values("seq_idx")
        i = int(rng.integers(0, len(g) - 1))
        chosen[g.iloc[i]["pano_id"]] = "pair"
        chosen[g.iloc[i + 1]["pano_id"]] = "pair"
    rest = train[~train["pano_id"].isin(chosen)]
    per_seq = rest.groupby("seq_id").sample(1, random_state=seed)
    pick = per_seq.sample(min(n_train, len(per_seq)), random_state=seed)
    for p in pick["pano_id"]:
        chosen[p] = "train"
    out = frames[frames["pano_id"].isin(chosen) & frames["cam_k"].between(0, 5)].copy()
    out["split"] = out["pano_id"].map(chosen)
    out = out.merge(seqs[["pano_id", "seq_id", "seq_idx"]], on="pano_id", how="left")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/calib_panos.parquet")
    ap.add_argument("--radius-m", type=float, default=250.0)
    ap.add_argument("--train-per-aoi", type=int, default=12)
    ap.add_argument("--pairs-per-aoi", type=int, default=4)
    ap.add_argument("--heldout-per-aoi", type=int, default=4)
    ap.add_argument("--project", default=data.PROJECT)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--no-download", action="store_true")
    args = ap.parse_args()

    creds = auth.get_credentials()
    runner = data.QueryRunner(
        data.make_bigquery_client(args.project, creds), cache_dir=data.DEFAULT_QUERY_CACHE
    )
    raw = runner.run(
        data.multi_aoi_meta_sql(), data.multi_aoi_params(list(AOIS.values()), args.radius_m)
    )
    all_frames = data.assign_nearest_aoi(data.normalize_frames(raw), AOIS, args.radius_m * 1.5)
    parts = []
    for name, frames in all_frames.groupby("aoi"):
        sel = select(
            frames, args.train_per_aoi, args.pairs_per_aoi, args.heldout_per_aoi, args.seed
        )
        sel["aoi"] = name
        print(
            f"{name}: {frames['pano_id'].nunique()} panos in AOI -> "
            f"{sel.groupby('split')['pano_id'].nunique().to_dict()}"
        )
        parts.append(sel)
    calib = pd.concat(parts, ignore_index=True)
    bucket = data.discover_bucket(runner)
    print(f"[bigquery] total billed estimate this run: {runner.total_billed_estimate / 1e9:.2f} GB")
    calib["gcs_uri"] = [
        data.gcs_uri_for(bucket, s, o)
        for s, o in zip(calib["snapshot_id"], calib["observation_id"], strict=True)
    ]
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    calib.to_parquet(args.out)
    print(f"wrote {args.out}: {calib['pano_id'].nunique()} panos, {len(calib)} frames")
    print(calib.groupby("split")["pano_id"].nunique())
    if args.no_download:
        return
    fetcher = images.GcsImageFetcher(storage.Client(project=args.project, credentials=creds))
    t = time.time()
    res = fetcher.fetch_many(list(calib["gcs_uri"]), max_workers=4)
    errs = {u: e for u, e in res.items() if isinstance(e, Exception)}
    print(
        f"downloaded {fetcher.n_downloads} new frames ({fetcher.bytes_downloaded / 1e9:.2f} GB) in "
        f"{time.time() - t:.0f}s; errors: {len(errs)}"
    )
    for u, e in list(errs.items())[:5]:
        print("  ", u, repr(e)[:200])


if __name__ == "__main__":
    main()
