"""Drive-sequence reconstruction for pano captures.

`capture_id` holds exactly one pano, so drives are rebuilt from `snapshot_id` +
`capture_time` + distance. Nothing here assumes a particular pano spacing: the gap threshold
defaults to a multiple of the spacing *measured* on the same data (`spacing_stats`).
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Mapping, Sequence
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


ROAD_VIEW_ROLES = {"front": 0.0, "left": -90.0, "right": 90.0}


def road_view_yaw(travel_deg: float, role: str) -> float:
    """World yaw of a road view: travel direction + 0 (front), -90 (left) or +90 (right)."""
    return float((travel_deg + ROAD_VIEW_ROLES[role]) % 360.0)


@dataclasses.dataclass(frozen=True)
class RoadView:
    choice: rosette.CameraChoice
    view: rosette.PerspectiveView
    keep_rows: int  # rows above the vehicle hood; the rest is cropped after rendering
    rows: tuple = ()  # the frames the view is rendered from (2 when composited on a seam)
    black: float = math.nan  # analytic share of view pixels without image data
    black_sent: float = math.nan  # the same share in the hood-cropped image sent to Gemini


def road_view(
    pano_rows: Sequence[Any],
    intr: rosette.Intrinsics,
    travel_deg: float,
    role: str,
    pitch_deg: float = -22.0,
    hfov_deg: float = 70.0,
    size: tuple[int, int] = (1024, 768),
    hood_elev_deg: float = rosette.HOOD_ELEV_DEG,
    min_hfov_deg: float = 40.0,
    max_black: float = 0.01,
) -> RoadView | None:
    """A world-oriented road view centred on travel + role offset (not on a camera heading).

    The camera is whichever ground camera of the pano covers the view best
    (`rosette.best_camera_for_view`); the FOV is narrowed from `hfov_deg` if needed so that
    less than `max_black` of the view falls outside the sensor. Rows below the vehicle hood
    are reported in `keep_rows` so `render_road_view` crops them. None if no camera reaches
    `min_hfov_deg`.

    If no single camera reaches `min_hfov_deg` (the view is centred on the seam between two
    cameras, as the travel direction is on the real rosette), the view is composited from the
    ground cameras that cover it (`rosette.render_perspective_multi`); `rows` then lists them
    and `choice` is the one whose axis is nearest the view centre."""
    w, h = size
    yaw = road_view_yaw(travel_deg, role)
    choice = rosette.best_camera_for_view(
        pano_rows, intr, yaw, pitch_deg, w / h,
        min_hfov=min_hfov_deg, max_black=max_black, hfov_cap=hfov_deg,
    )  # fmt: skip
    if choice is not None:
        view = rosette.PerspectiveView(yaw, float(pitch_deg), choice.hfov_deg, w, h)
        keep = rosette.hood_row(view, _pose(choice.row), intr, hood_elev_deg, choice.cam_k)
        pose = _pose(choice.row)
        black = rosette.view_black_fraction(intr, pose, view, choice.cam_k)
        sent = rosette.view_black_fraction(intr, pose, view, choice.cam_k, max_row=keep)
        return RoadView(choice, view, keep, (choice.row,), black, sent)
    hfov, vfov = rosette.max_view_fov_multi(
        intr, pano_rows, yaw, pitch_deg, w / h, max_black=max_black, hfov_cap=hfov_deg,
        min_hfov=min_hfov_deg,
    )  # fmt: skip
    if hfov < min_hfov_deg:
        return None
    view = rosette.PerspectiveView(yaw, float(pitch_deg), hfov, w, h)
    used = rosette.composite_rows(intr, pano_rows, view)
    ks = [rosette.camera_index(r["observation_id"]) for r in used]
    centre = [
        abs(geo.angdiff(_axis_heading(intr, r, k), yaw)) for r, k in zip(used, ks, strict=True)
    ]
    i = int(np.argmin(centre))
    choice = rosette.CameraChoice(used[i], ks[i], hfov, vfov)
    keep = min(rosette.hood_row(view, _pose(r), intr, hood_elev_deg, k)
               for r, k in zip(used, ks, strict=True))  # fmt: skip
    black = rosette.view_black_fraction_multi(intr, used, view)
    sent = rosette.view_black_fraction_multi(intr, used, view, max_row=keep)
    return RoadView(choice, view, keep, used, black, sent)


def _axis_heading(intr: rosette.Intrinsics, row: Any, k: int) -> float:
    return float(_pose(row)["heading"]) + intr.cam_rot_delta_deg.get(k, (0.0,))[0]


def render_road_view(
    image: np.ndarray | Mapping[int, np.ndarray], intr: rosette.Intrinsics, rv: RoadView
) -> np.ndarray:
    """Render `rv` and crop the rows below the vehicle hood. `image` is the frame of
    `rv.choice`, or a {cam_k: frame} mapping covering every row in `rv.rows` (required when
    the view is composited from two cameras)."""
    if len(rv.rows) > 1:
        if not isinstance(image, Mapping):
            raise TypeError("a composited road view needs {cam_k: frame} for all of rv.rows")
        out = rosette.render_perspective_multi(image, intr, rv.rows, rv.view)
    else:
        img = image[rv.choice.cam_k] if isinstance(image, Mapping) else image
        out = rosette.render_perspective(img, intr, _pose(rv.choice.row), rv.view, rv.choice.cam_k)
    return out[: rv.keep_rows]
