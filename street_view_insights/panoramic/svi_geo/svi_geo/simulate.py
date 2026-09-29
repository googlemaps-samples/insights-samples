"""Synthetic scenes and detections on real pano geometry, for dedup evaluation (T9a).

Objects (poles, signs, houses) are placed along a drive path and "observed" by every camera
of every pano through a camera model: world bearing -> native fisheye pixel with the TRUE
intrinsics and the TRUE (noise-perturbed) pose. The pipeline then turns the pixel back into
a bearing with ITS intrinsics and the REPORTED pose (`to_observations`), exactly like a real
detection. Using different intrinsics for truth and pipeline reproduces model mismatch.

Camera centres come from `rosette.camera_center_enu(pose)` directly: `camera_pose` positions
are already per camera, so the rosette radius is never added again (QA S13).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

from svi_geo import entities as ent
from svi_geo import geo, rosette, sequence
from svi_geo import triangulate as tri

CAM_HEIGHT_M = 2.5
ROSETTE_OFFSET_M = 0.083  # measured median camera_pose offset from the pano centre
HOUSE_HEIGHT_M = 6.0
MIN_SEP_M = {"UTILITY_POLE": 3.0, "ROAD_SIGN": 3.0, "HOUSE": 14.0}
CLASSES = ("UTILITY_POLE", "ROAD_SIGN", "HOUSE")


@dataclasses.dataclass(frozen=True)
class NoiseModel:
    bearing_sigma_deg: float = 1.0
    elev_sigma_deg: float = 1.0
    pos_sigma_m: float = 0.5
    yaw_sigma_deg: float = 0.3
    dropout: float = 0.2
    fp_rate: float = 0.1
    class_confusion: float = 0.05


NOISE_FREE = NoiseModel(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)


@dataclasses.dataclass(frozen=True)
class SceneObject:
    obj_id: str
    cls: str
    point_enu: np.ndarray  # ground-contact point (poles/signs) or footprint centre (houses)


@dataclasses.dataclass
class Scene:
    objects: list[SceneObject]
    ref_lla: tuple[float, float, float]


@dataclasses.dataclass(frozen=True)
class SimDetection:
    obs_id: str
    pano_id: str
    cam_k: int
    cls: str
    u: float  # native fisheye pixel of the reference point (box bottom-centre / centre)
    v: float
    confidence: float
    obj_id: str | None  # None = false positive


@dataclasses.dataclass
class SimResult:
    detections: list[SimDetection]
    visible: dict[str, int]  # obj_id -> number of panos that see it (before dropout)


# --------------------------------------------------------------------------- frames


def synthetic_frames(
    n_panos: int,
    spacing_m: float,
    lat0: float,
    lng0: float,
    travel_deg: float = 0.0,
    cam_alt_m: float = 35.0 + CAM_HEIGHT_M,
    seq_id: str = "S0",
    t0: dt.datetime | None = None,
) -> pd.DataFrame:
    """Straight-drive frames in the PANO_META_SQL + normalize_frames layout (7 cams/pano)."""
    t0 = t0 or dt.datetime(2024, 5, 1, 12, tzinfo=dt.timezone.utc)
    rows = []
    for i in range(n_panos):
        e = i * spacing_m * math.sin(math.radians(travel_deg))
        n = i * spacing_m * math.cos(math.radians(travel_deg))
        lat, lng, _ = geo.enu_to_lla(e, n, 0.0, lat0, lng0)
        pid = f"{seq_id}p{i:04d}"
        for k in range(7):
            h = (travel_deg + 60.0 * k) % 360.0 if k < 6 else travel_deg
            pitch = (9.0 if k % 2 == 0 else -9.0) if k < 6 else 90.0
            off = ROSETTE_OFFSET_M if k < 6 else 0.0
            ce, cn = e + off * math.sin(math.radians(h)), n + off * math.cos(math.radians(h))
            clat, clng, _ = geo.enu_to_lla(ce, cn, 0.0, lat0, lng0)
            rows.append(
                {
                    "pano_id": pid,
                    "observation_id": f"o1:{pid}_{k}:5001ee",
                    "snapshot_id": "sim",
                    "capture_time": t0 + dt.timedelta(seconds=2 * i),
                    "lat": float(lat),
                    "lng": float(lng),
                    "cam_k": k,
                    "seq_id": seq_id,
                    "seq_idx": i,
                    "camera_pose": {
                        "heading": h,
                        "pitch": pitch,
                        "roll": 0.0,
                        "latitude": float(clat),
                        "longitude": float(clng),
                        "altitude": cam_alt_m,
                    },
                }
            )
    return pd.DataFrame(rows)


def scene_ref(frames: pd.DataFrame, cam_height_m: float = CAM_HEIGHT_M):
    """ENU reference: mean camera position, altitude = median camera altitude - cam height."""
    poses = list(frames["camera_pose"])
    lat = float(np.mean([p["latitude"] for p in poses]))
    lng = float(np.mean([p["longitude"] for p in poses]))
    alt = float(np.median([p["altitude"] for p in poses])) - cam_height_m
    return (lat, lng, alt)


def _ground_frames(frames: pd.DataFrame) -> pd.DataFrame:
    return frames[frames["cam_k"].between(0, 5)]


def _pano_centres(frames: pd.DataFrame, ref) -> dict[str, np.ndarray]:
    out = {}
    for pid, g in _ground_frames(frames).groupby("pano_id", sort=True):
        out[pid] = np.mean([rosette.camera_center_enu(p, ref) for p in g["camera_pose"]], axis=0)
    return out


# --------------------------------------------------------------------------- scene


def make_scene(
    frames: pd.DataFrame,
    n_poles: int,
    n_signs: int,
    n_houses: int,
    street_offset_m: tuple[float, float] = (3.0, 12.0),
    seed: int = 0,
    cam_height_m: float = CAM_HEIGHT_M,
) -> Scene:
    """Place objects beside the real drive path (frames need seq_id/seq_idx, as from
    `sequence.build_sequences` merged onto frames, or `synthetic_frames`)."""
    rng = np.random.default_rng(seed)
    ref = scene_ref(frames, cam_height_m)
    panos = frames.drop_duplicates("pano_id").sort_values(["seq_id", "seq_idx"])
    panos = panos.reset_index(drop=True)
    travel = sequence.travel_bearing(panos)
    centres = _pano_centres(frames, ref)
    pids = list(panos["pano_id"])
    objs: list[SceneObject] = []
    lo, hi = street_offset_m
    for cls, n in (("UTILITY_POLE", n_poles), ("ROAD_SIGN", n_signs), ("HOUSE", n_houses)):
        placed = 0
        for _ in range(n * 50):
            if placed == n:
                break
            i = int(rng.integers(len(pids)))
            c = centres[pids[i]]
            t = math.radians(travel[i] if np.isfinite(travel[i]) else 0.0)
            fwd = np.array([math.sin(t), math.cos(t)])
            left = np.array([-fwd[1], fwd[0]])
            side = 1.0 if rng.random() < 0.5 else -1.0
            if cls == "HOUSE":
                off = rng.uniform(hi + 2.0, hi + 12.0)
            else:
                off = rng.uniform(lo, min(hi, 8.0) if cls == "ROAD_SIGN" else hi)
            xy = c[:2] + fwd * rng.uniform(-5.0, 5.0) + left * side * off
            if any(
                o.cls == cls and np.linalg.norm(o.point_enu[:2] - xy) < MIN_SEP_M[cls] for o in objs
            ):
                continue
            z = c[2] - cam_height_m
            objs.append(SceneObject(f"{cls.lower()}_{placed}", cls, np.array([*xy, z])))
            placed += 1
    return Scene(objs, ref)


def truth_points(scene: Scene) -> dict[str, tuple[float, float]]:
    return {o.obj_id: (float(o.point_enu[0]), float(o.point_enu[1])) for o in scene.objects}


def truth_labels(dets: Sequence[SimDetection]) -> dict[str, str | None]:
    return {d.obs_id: d.obj_id for d in dets}


# --------------------------------------------------------------------------- observation


def _ref_point(o: SceneObject) -> np.ndarray:
    """Bearing reference: box bottom (ground contact) or the facade centre for houses."""
    if o.cls == "HOUSE":
        return o.point_enu + np.array([0.0, 0.0, HOUSE_HEIGHT_M / 2.0])
    return o.point_enu


def _perturbed_pose(pose: Mapping[str, Any], dyaw: float) -> dict:
    p = dict(pose)
    p["heading"] = (float(p["heading"]) + dyaw) % 360.0
    return p


def simulate_observations(
    scene: Scene,
    frames: pd.DataFrame,
    intr: rosette.Intrinsics,
    noise: NoiseModel,
    seed: int = 0,
    min_range_m: float = 3.0,
    max_range_m: float = 40.0,
    hood_elev_deg: float = -40.0,
) -> SimResult:
    """One detection per (pano, object) seen by a ground camera (the most on-axis one)."""
    rng = np.random.default_rng(seed)
    ref = scene.ref_lla
    dets: list[SimDetection] = []
    visible: dict[str, int] = {}
    classes = sorted({o.cls for o in scene.objects}) or list(CLASSES)
    gf = _ground_frames(frames)
    for pid, g in gf.groupby("pano_id", sort=True):
        rows = sorted(g.to_dict("records"), key=lambda r: r["cam_k"])
        d_pos = np.r_[rng.normal(0.0, noise.pos_sigma_m, 2), 0.0] if noise.pos_sigma_m else 0.0
        dyaw = float(rng.normal(0.0, noise.yaw_sigma_deg)) if noise.yaw_sigma_deg else 0.0
        true_c = {
            r["cam_k"]: rosette.camera_center_enu(r["camera_pose"], ref) + d_pos for r in rows
        }
        true_pose = {r["cam_k"]: _perturbed_pose(r["camera_pose"], dyaw) for r in rows}
        n_true = 0
        for o in scene.objects:
            p = _ref_point(o)
            best = None
            for r in rows:
                k = r["cam_k"]
                d = p - true_c[k]
                rh = math.hypot(d[0], d[1])
                if not (min_range_m <= rh <= max_range_m):
                    continue
                az = float(geo.enu_bearing_deg(d[0], d[1]))
                el = math.degrees(math.atan2(d[2], rh))
                u, v, ok = rosette.bearing_to_pixel(
                    intr, true_pose[k], az, el, k, hood_elev_deg=hood_elev_deg
                )
                if not bool(ok):
                    continue
                off_axis = abs(float(geo.angdiff(az, true_pose[k]["heading"])))
                if best is None or off_axis < best[0]:
                    best = (off_axis, k, az, el, rh)
            if best is None:
                continue
            visible[o.obj_id] = visible.get(o.obj_id, 0) + 1
            if noise.dropout and rng.random() < noise.dropout:
                continue
            _, k, az, el, rh = best
            sig = noise.bearing_sigma_deg
            if o.cls == "HOUSE":  # box centre wanders over the facade between views
                sig = math.hypot(sig, math.degrees(math.atan2(1.5, rh)))
            az_n = az + (rng.normal(0.0, sig) if sig else 0.0)
            el_n = el + (rng.normal(0.0, noise.elev_sigma_deg) if noise.elev_sigma_deg else 0.0)
            u, v, ok = rosette.bearing_to_pixel(intr, true_pose[k], az_n, el_n, k)
            if not bool(ok):
                continue
            cls = o.cls
            if noise.class_confusion and rng.random() < noise.class_confusion:
                others = [c for c in classes if c != o.cls]
                if others:
                    cls = others[int(rng.integers(len(others)))]
            conf = float(rng.uniform(0.5, 0.99)) if noise != NOISE_FREE else 0.9
            dets.append(
                SimDetection(f"{pid}_{o.obj_id}", pid, k, cls, float(u), float(v), conf, o.obj_id)
            )
            n_true += 1
        n_fp = int(rng.binomial(n_true, noise.fp_rate)) if noise.fp_rate else 0
        for j in range(n_fp):
            k = int(rng.integers(6))
            if k not in true_pose:
                continue
            u = float(rng.uniform(0.25, 0.75) * intr.width)
            v = float(rng.uniform(0.45, 0.75) * intr.height)
            cls = classes[int(rng.integers(len(classes)))]
            conf = float(rng.uniform(0.3, 0.8))
            dets.append(SimDetection(f"{pid}_fp{j}", pid, k, cls, u, v, conf, None))
    return SimResult(dets, visible)


def to_observations(
    dets: Sequence[SimDetection],
    frames: pd.DataFrame,
    intr: rosette.Intrinsics,
    ref_lla: Sequence[float],
) -> list[ent.Observation]:
    """Detections -> world rays with the PIPELINE intrinsics and the REPORTED camera poses."""
    pose_of = {
        (r["pano_id"], int(r["cam_k"])): r["camera_pose"]
        for r in _ground_frames(frames).to_dict("records")
    }
    out = []
    for d in dets:
        pose = pose_of[(d.pano_id, d.cam_k)]
        az, el = rosette.pixel_to_bearing(intr, pose, d.u, d.v, d.cam_k)
        origin = rosette.camera_center_enu(pose, ref_lla)
        out.append(
            ent.Observation(
                obs_id=d.obs_id,
                pano_id=d.pano_id,
                cls=d.cls,
                ray=tri.Ray(origin, float(az), float(el)),
                confidence=d.confidence,
                el_bottom_deg=float(el),
            )
        )
    return out
