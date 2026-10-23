"""Frozen per-AOI manifests for label-free evaluation (Task T8).

AOI mapping (from `fetch_calibration_panos.AOIS`):
* `tune` -> `lakeland_fl` `(28.05, -81.96)`
* `heldout` -> `salt_lake_ut` `(40.76, -111.91)`
* `stress` -> `osaka_jp` `(34.71, 135.54)`

A manifest deterministically selects:
* UC1: 8 house target coordinates (offset ~18 m laterally from distinct drive sequences) and up to 8 views each.
* UC2: up to 4 sequences of up to 10 consecutive panos each.
* UC3: up to 4 sequences of up to 15 consecutive panos each (prioritising sequences that belong to a cross-day repeat pair).
* UC4: 10 building target coordinates and up to 6 candidate views each.
* Repeat-pass pairs (`sequence.repeat_pairs`), spatial blocks (`sequence.blocks`), and perturbation specs (`labelfree.perturbations`).

Every manifest carries a `sha256` digest of its canonical JSON payload; `assert_same_manifest`
refuses paired before/after comparisons when the two manifests differ.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from svi_geo import data, geo, sequence
from svi_geo import labelfree as lf

AOI_CENTRES: dict[str, tuple[float, float]] = {
    "tune": (28.05, -81.96),  # lakeland_fl
    "heldout": (40.76, -111.91),  # salt_lake_ut
    "stress": (34.71, 135.54),  # osaka_jp
    "lakeland_fl": (28.05, -81.96),
    "salt_lake_ut": (40.76, -111.91),
    "osaka_jp": (34.71, 135.54),
}

CANONICAL_AOI_NAME: dict[str, str] = {
    "tune": "lakeland_fl",
    "heldout": "salt_lake_ut",
    "stress": "osaka_jp",
    "lakeland_fl": "lakeland_fl",
    "salt_lake_ut": "salt_lake_ut",
    "osaka_jp": "osaka_jp",
}


def _select_targets_along_sequences(
    panos: pd.DataFrame,
    n_targets: int,
    lateral_offset_m: float,
    seed: int,
) -> list[dict[str, Any]]:
    """Deterministically place `n_targets` building/house coordinates beside drive sequences."""
    rng = np.random.default_rng(seed)
    df = data.ensure_capture_id(panos).sort_values(["seq_id", "seq_idx"]).reset_index(drop=True)
    df["travel_deg"] = sequence.travel_bearing(df)
    # Prefer sequences with at least 4 panos so multi-view triangulation has coverage
    seq_counts = df.groupby("seq_id").size()
    good_sids = sorted(seq_counts[seq_counts >= 4].index.tolist())
    if not good_sids:
        good_sids = sorted(df["seq_id"].unique().tolist())

    targets: list[dict[str, Any]] = []
    for idx in range(n_targets):
        sid = good_sids[idx % len(good_sids)]
        g = df[df["seq_id"] == sid].reset_index(drop=True)
        # Pick an interior pano of the sequence
        pos = int((idx // max(1, len(good_sids)) * 3 + len(g) // 2) % len(g))
        row = g.iloc[pos]
        t_deg = float(row["travel_deg"]) if np.isfinite(row["travel_deg"]) else 0.0
        side = 1.0 if (idx % 2 == 0) else -1.0
        perp_rad = math.radians((t_deg + side * 90.0) % 360.0)
        de = lateral_offset_m * math.sin(perp_rad) + float(rng.uniform(-1.5, 1.5))
        dn = lateral_offset_m * math.cos(perp_rad) + float(rng.uniform(-1.5, 1.5))
        t_lat, t_lng, _ = geo.enu_to_lla(de, dn, 0.0, float(row["lat"]), float(row["lng"]), 0.0)
        cid = str(row["capture_id"])
        targets.append(
            {
                "target_id": f"target_{idx:02d}",
                "seq_id": str(sid),
                "anchor_capture_id": cid,
                "anchor_pano_id": cid,
                "lat": round(float(t_lat), 7),
                "lng": round(float(t_lng), 7),
                "block_id": f"{sid}:b{pos // 5:03d}",
            }
        )
    return targets


def _select_sequence_windows(
    panos: pd.DataFrame,
    n_seqs: int,
    window_panos: int,
    repeat_sids: set[str],
) -> list[dict[str, Any]]:
    """Select up to `n_seqs` sequences of up to `window_panos` consecutive rosettes each."""
    df = data.ensure_capture_id(panos).sort_values(["seq_id", "seq_idx"]).reset_index(drop=True)
    grouped = []
    for sid, g in df.groupby("seq_id", sort=True):
        is_rep = 1 if str(sid) in repeat_sids else 0
        grouped.append((is_rep, len(g), str(sid), g.reset_index(drop=True)))
    # Sort: repeat-pair sequences first, then longest sequences, then seq_id
    grouped.sort(key=lambda x: (-x[0], -x[1], x[2]))
    out: list[dict[str, Any]] = []
    for _, _, sid, g in grouped[:n_seqs]:
        mid = len(g) // 2
        lo = max(0, min(mid - window_panos // 2, len(g) - window_panos))
        sub = g.iloc[lo : lo + window_panos]
        cids = [str(p) for p in sub["capture_id"].tolist()]
        out.append(
            {
                "seq_id": sid,
                "capture_ids": cids,
                "pano_ids": cids,
                "n_panos": int(len(sub)),
            }
        )
    return out


def build_manifest(
    frames: pd.DataFrame,
    aoi: str = "tune",
    seed: int = 7,
) -> dict[str, Any]:
    """Build a deterministic, hash-locked evaluation manifest from `frames` for `aoi`."""
    aoi_name = CANONICAL_AOI_NAME.get(aoi, aoi)
    panos = sequence.build_sequences(data.panos_from_frames(frames))
    rep_pairs = sequence.repeat_pairs(panos)
    rep_sids: set[str] = set()
    for rp in rep_pairs[:2]:
        rep_sids.add(rp["seq_a"])
        rep_sids.add(rp["seq_b"])

    blk_map = sequence.blocks(panos, block_size=5)
    uc1_targets = _select_targets_along_sequences(
        panos, n_targets=8, lateral_offset_m=18.0, seed=seed
    )
    uc4_targets = _select_targets_along_sequences(
        panos, n_targets=10, lateral_offset_m=20.0, seed=seed + 100
    )
    uc2_seqs = _select_sequence_windows(panos, n_seqs=4, window_panos=10, repeat_sids=rep_sids)
    uc3_seqs = _select_sequence_windows(panos, n_seqs=4, window_panos=15, repeat_sids=rep_sids)
    perts = lf.perturbations(seed=seed, n=3)

    payload = {
        "aoi": aoi,
        "aoi_name": aoi_name,
        "key_column": "capture_id",
        "seed": int(seed),
        "n_panos_total": int(len(panos)),
        "n_sequences_total": int(panos["seq_id"].nunique()),
        "uc1_targets": uc1_targets,
        "uc2_sequences": uc2_seqs,
        "uc3_sequences": uc3_seqs,
        "uc4_targets": uc4_targets,
        "repeat_pairs": rep_pairs[:4],
        "blocks": blk_map,
        "perturbations": perts,
    }
    canon = json.dumps(payload, sort_keys=True)
    digest = hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]
    return {**payload, "sha256": digest}


def assert_same_manifest(m_before: Mapping[str, Any], m_after: Mapping[str, Any]) -> None:
    """Refuse before/after comparison if the two manifests do not have the exact same sha256 or capture_id key."""
    if m_before.get("key_column") != "capture_id" or m_after.get("key_column") != "capture_id":
        raise ValueError("manifest must be keyed on 'capture_id' (rejecting old pano_id manifest)")
    h1 = m_before.get("sha256")
    h2 = m_after.get("sha256")
    if not h1 or not h2 or h1 != h2:
        raise ValueError(f"manifest sha256 mismatch: before={h1!r} vs after={h2!r}")
