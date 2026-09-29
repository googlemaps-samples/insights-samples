"""Drive-sequence reconstruction for pano captures.

`capture_id` holds exactly one pano, so drives are rebuilt from `snapshot_id` +
`capture_time` + distance. Nothing here assumes a particular pano spacing: the gap threshold
defaults to a multiple of the spacing *measured* on the same data (`spacing_stats`).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from svi_geo import geo, rosette

_REQUIRED = ("pano_id", "snapshot_id", "capture_time", "lat", "lng")


def _prep(panos: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in _REQUIRED if c not in panos.columns]
    if missing:
        raise ValueError(f"panos frame missing columns {missing}")
    df = panos.drop_duplicates("pano_id").copy()
    df["capture_time"] = pd.to_datetime(df["capture_time"], utc=True)
    df["_t"] = (df["capture_time"] - pd.Timestamp("1970-01-01", tz="UTC")).dt.total_seconds()
    lat0, lng0 = float(df["lat"].mean()), float(df["lng"].mean())
    e, n, _ = geo.lla_to_enu(df["lat"].to_numpy(), df["lng"].to_numpy(), 0.0, lat0, lng0, 0.0)
    df["_e"], df["_n"] = e, n
    return df.sort_values(["snapshot_id", "_t", "pano_id"]).reset_index(drop=True)


def spacing_stats(panos: pd.DataFrame, max_dt_s: float = 5.0, max_d_m: float = 50.0) -> dict:
    """Distance between time-consecutive panos of a snapshot (0 < dt <= max_dt, d < max_d)."""
    df = _prep(panos)
    ds = []
    for _, g in df.groupby("snapshot_id", sort=False):
        dt = np.diff(g["_t"].to_numpy())
        d = np.hypot(np.diff(g["_e"].to_numpy()), np.diff(g["_n"].to_numpy()))
        keep = (dt > 0) & (dt <= max_dt_s) & (d < max_d_m)
        ds.append(d[keep])
    d = np.concatenate(ds) if ds else np.array([])
    if d.size == 0:
        return {"n": 0, "median_m": float("nan"), "p10_m": float("nan"), "p90_m": float("nan")}
    return {
        "n": int(d.size),
        "median_m": float(np.median(d)),
        "p10_m": float(np.percentile(d, 10)),
        "p90_m": float(np.percentile(d, 90)),
    }


def build_sequences(
    panos: pd.DataFrame,
    max_dt_s: float = 5.0,
    max_gap_m: float | None = None,
    gap_factor: float = 3.0,
) -> pd.DataFrame:
    """Chain panos into drive sequences.

    Per snapshot, in time order, each pano's predecessor is the spatially nearest earlier pano
    within `max_dt_s` and `max_gap_m` that has no successor yet. `max_gap_m` defaults to
    `gap_factor` x the measured median spacing. Returns the panos with `seq_id`, `seq_idx`.
    """
    df = _prep(panos)
    if max_gap_m is None:
        med = spacing_stats(panos, max_dt_s=max_dt_s)["median_m"]
        max_gap_m = gap_factor * (med if np.isfinite(med) else 10.0)
    t = df["_t"].to_numpy()
    e = df["_e"].to_numpy()
    n = df["_n"].to_numpy()
    snap = df["snapshot_id"].to_numpy()
    pred = np.full(len(df), -1)
    has_succ = np.zeros(len(df), bool)
    lo = 0
    for i in range(len(df)):
        while lo < i and (snap[lo] != snap[i] or t[i] - t[lo] > max_dt_s):
            lo += 1
        best, best_d = -1, np.inf
        for j in range(lo, i):
            if has_succ[j] or t[j] >= t[i] or snap[j] != snap[i]:
                continue
            d = np.hypot(e[i] - e[j], n[i] - n[j])
            if d <= max_gap_m and d < best_d:
                best, best_d = j, d
        if best >= 0:
            pred[i] = best
            has_succ[best] = True
    seq_id = np.empty(len(df), dtype=object)
    seq_idx = np.zeros(len(df), int)
    pano = df["pano_id"].to_numpy()
    for i in range(len(df)):
        if pred[i] < 0:
            seq_id[i] = f"{str(snap[i])[:8]}_{pano[i]}"
            seq_idx[i] = 0
        else:
            seq_id[i] = seq_id[pred[i]]
            seq_idx[i] = seq_idx[pred[i]] + 1
    df["seq_id"] = seq_id
    df["seq_idx"] = seq_idx
    df.attrs["max_gap_m"] = float(max_gap_m)
    return (
        df.drop(columns=["_t", "_e", "_n"])
        .sort_values(["seq_id", "seq_idx"])
        .reset_index(drop=True)
    )


def travel_bearing(seqs: pd.DataFrame) -> np.ndarray:
    """Travel direction (deg) per row: central difference inside a sequence, one-sided at ends."""
    out = np.full(len(seqs), np.nan)
    order = seqs.sort_values(["seq_id", "seq_idx"])
    for _, g in order.groupby("seq_id", sort=False):
        idx = g.index.to_numpy()
        lat, lng = g["lat"].to_numpy(), g["lng"].to_numpy()
        m = len(g)
        if m < 2:
            continue
        for a in range(m):
            p, q = max(a - 1, 0), min(a + 1, m - 1)
            out[idx[a]] = geo.bearing_deg(lat[p], lng[p], lat[q], lng[q])
    return out


def neighbours(seqs: pd.DataFrame, pano_id: str, k: int = 2) -> pd.DataFrame:
    """Panos within k steps of `pano_id` in its sequence (excluding itself), in order."""
    row = seqs.loc[seqs["pano_id"] == pano_id]
    if row.empty:
        return seqs.iloc[0:0]
    sid, i = row.iloc[0]["seq_id"], int(row.iloc[0]["seq_idx"])
    g = seqs[(seqs["seq_id"] == sid) & (seqs["seq_idx"] != i) & ((seqs["seq_idx"] - i).abs() <= k)]
    return g.sort_values("seq_idx")


ROLE_OFFSETS = {"front": 0.0, "right": 90.0, "back": 180.0, "left": -90.0}


def _pose(row: Any) -> Mapping[str, Any]:
    return row["camera_pose"] if isinstance(row, Mapping) else row.camera_pose


def camera_roles(frames: pd.DataFrame | list, travel_deg: float, include_sky: bool = False) -> dict:
    """Map front/right/back/left (and optionally sky) to the frame rows of one pano."""
    rows = frames.to_dict("records") if isinstance(frames, pd.DataFrame) else list(frames)
    ground, sky = [], None
    for r in rows:
        k = rosette.camera_index(r["observation_id"])
        if k is None:
            continue
        if rosette.is_ground_camera(k) and abs(float(_pose(r).get("pitch", 0.0))) <= 45.0:
            ground.append(r)
        elif k == rosette.SKY_CAMERA:
            sky = r
    roles = {}
    if ground and np.isfinite(travel_deg):
        for role, off in ROLE_OFFSETS.items():
            target = travel_deg + off
            roles[role] = min(
                ground, key=lambda r: abs(float(geo.angdiff(float(_pose(r)["heading"]), target)))
            )
    if include_sky and sky is not None:
        roles["sky"] = sky
    return roles
