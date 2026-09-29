"""Build real-data calibration problems from downloaded pano frames (deterministic OpenCV).

Pipeline (all code, no LLM):
1. `instances_from_frames`: one `CamInstance` per frame. Camera positions come straight from
   `camera_pose` (already per camera); the pano centre is their mean and the rosette radius
   is the measured median offset.
2. `FeatureStore`: SIFT keypoints + edge chains per frame at half resolution, cached on disk.
3. `intra_matches` / `sequence_matches`: ratio-test matches between adjacent cameras of one
   pano, and between same-index cameras of consecutive panos, filtered geometrically
   (model-free pixel RANSAC first, then angular/essential consistency under the current fit).
4. `select_chains`: keep chains that are straight under the current fit; tag verticals.
"""

from __future__ import annotations

import dataclasses
import hashlib
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

from svi_geo import calib_features as cf
from svi_geo import calibrate, geo, images, rosette
from svi_geo.calibrate import CalibProblem, CamInstance, Chain
from svi_geo.rosette import Intrinsics

HALF = 0.5
DEFAULT_FEATURE_CACHE = Path.home() / ".cache" / "svi_geo" / "features"


# --------------------------------------------------------------------------- instances


@dataclasses.dataclass
class InstanceSet:
    instances: list[CamInstance]
    index: dict[tuple[str, int], int]  # (pano_id, cam_k) -> instance index
    radius_m: float
    radius_p10_p90: tuple[float, float]


def instances_from_frames(frames: pd.DataFrame) -> InstanceSet:
    """`frames` needs pano_id, cam_k, heading, pitch, roll, cam_lat, cam_lng, cam_alt, aoi."""
    frames = frames[frames["cam_k"].between(0, 5)]
    refs = {}
    for aoi, g in frames.groupby("aoi"):
        r0 = g.sort_values(["pano_id", "cam_k"]).iloc[0]
        refs[aoi] = (float(r0["cam_lat"]), float(r0["cam_lng"]), float(r0["cam_alt"]))
    instances, index, offsets = [], {}, []
    for pid, g in frames.sort_values(["pano_id", "cam_k"]).groupby("pano_id", sort=False):
        ref = refs[g["aoi"].iloc[0]]
        enu = np.stack(
            geo.lla_to_enu(
                g["cam_lat"].to_numpy(float),
                g["cam_lng"].to_numpy(float),
                g["cam_alt"].to_numpy(float),
                *ref,
            ),
            -1,
        )
        centre = enu.mean(0)
        offsets.extend(np.linalg.norm((enu - centre)[:, :2], axis=1).tolist())
        for row in g.itertuples(index=False):
            index[(pid, int(row.cam_k))] = len(instances)
            instances.append(
                CamInstance(
                    pid,
                    int(row.cam_k),
                    centre,
                    float(row.heading),
                    float(row.pitch),
                    float(row.roll),
                )
            )
    off = np.array(offsets)
    return InstanceSet(
        instances,
        index,
        float(np.median(off)),
        (float(np.percentile(off, 10)), float(np.percentile(off, 90))),
    )


# --------------------------------------------------------------------------- features


@dataclasses.dataclass
class FrameFeatures:
    uv: np.ndarray
    desc: np.ndarray
    chains: list[np.ndarray]


class FeatureStore:
    """Half-resolution SIFT + edge chains per frame URI, cached as .npz."""

    def __init__(
        self,
        fetcher: images.ImageFetcher,
        cache_dir: str | Path | None = DEFAULT_FEATURE_CACHE,
        n_features: int = 6000,
    ):
        self.fetcher = fetcher
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.n_features = n_features
        self._mem: dict[str, FrameFeatures] = {}

    def _path(self, uri: str) -> Path | None:
        if self.cache_dir is None:
            return None
        h = hashlib.sha1(f"{uri}|{self.n_features}|v1".encode()).hexdigest()[:20]
        return self.cache_dir / f"{h}.npz"

    def get(self, uri: str) -> FrameFeatures:
        if uri in self._mem:
            return self._mem[uri]
        path = self._path(uri)
        if path is not None and path.exists():
            z = np.load(path, allow_pickle=False)
            n_ch = int(z["n_chains"])
            ff = FrameFeatures(z["uv"], z["desc"], [z[f"ch{i}"] for i in range(n_ch)])
        else:
            gray = images.decode(self.fetcher.fetch(uri), scale=HALF, gray=True)
            mask = cf.frame_mask(gray)
            feats = cf.detect(gray, HALF, mask, n=self.n_features)
            chains = cf.edge_chains(gray, HALF, mask)
            ff = FrameFeatures(feats.uv, feats.desc, chains)
            if path is not None:
                path.parent.mkdir(parents=True, exist_ok=True)
                arrays = {f"ch{i}": c for i, c in enumerate(chains)}
                np.savez_compressed(
                    path, uv=ff.uv, desc=ff.desc, n_chains=np.array(len(chains)), **arrays
                )
        self._mem[uri] = ff
        return ff


# --------------------------------------------------------------------------- matching


@dataclasses.dataclass
class MatchSet:
    a: list[int] = dataclasses.field(default_factory=list)
    b: list[int] = dataclasses.field(default_factory=list)
    uva: list[np.ndarray] = dataclasses.field(default_factory=list)
    uvb: list[np.ndarray] = dataclasses.field(default_factory=list)
    kind: list[int] = dataclasses.field(default_factory=list)
    pair: list[int] = dataclasses.field(default_factory=list)

    def add(self, ia: int, ib: int, ua: np.ndarray, ub: np.ndarray, kind: int, pair: int) -> None:
        n = len(ua)
        self.a.extend([ia] * n)
        self.b.extend([ib] * n)
        self.uva.append(ua)
        self.uvb.append(ub)
        self.kind.extend([kind] * n)
        self.pair.extend([pair] * n)

    def problem(
        self, inst: InstanceSet, width: int, height: int, n_pairs: int, chains: list[Chain]
    ) -> CalibProblem:
        cat = lambda xs: np.concatenate(xs) if xs else np.zeros((0, 2))  # noqa: E731
        return CalibProblem(
            width=width,
            height=height,
            instances=inst.instances,
            m_a=np.array(self.a, int),
            m_b=np.array(self.b, int),
            uv_a=cat(self.uva),
            uv_b=cat(self.uvb),
            m_kind=np.array(self.kind, int),
            m_pair=np.array(self.pair, int),
            n_pairs=n_pairs,
            chains=chains,
        )


def pixel_ransac_inliers(ua: np.ndarray, ub: np.ndarray, thr_px: float = 6.0) -> np.ndarray:
    """Model-free fundamental-matrix RANSAC in full-res pixels (local overlap regions only)."""
    out = np.zeros(len(ua), bool)
    if len(ua) < 12:
        return out
    _, inl = cv2.findFundamentalMat(ua, ub, cv2.FM_RANSAC, thr_px, 0.999)
    if inl is not None:
        out = inl.ravel().astype(bool)
    return out


def _world_rays(inst: InstanceSet, intr: Intrinsics, idx: int, uv: np.ndarray) -> np.ndarray:
    ci = inst.instances[idx]
    R = rosette.cam_rotation(
        ci.heading,
        ci.pitch,
        ci.roll,
        intr.pose_convention,
        intr.cam_rot_delta_deg.get(ci.cam_k),
    )
    return rosette.unproject(intr, uv) @ R.T


def intra_matches(
    inst: InstanceSet,
    feats: Callable[[str, int], FrameFeatures],
    pano_ids: Iterable[str],
    width: int,
    intr: Intrinsics | None = None,
    thr_deg: float = 2.5,
    ratio: float = 0.8,
    out: MatchSet | None = None,
) -> MatchSet:
    """Adjacent-camera matches (k, k+1 mod 6) restricted to the facing halves of the frames.

    Without `intr` the filter is model-free pixel RANSAC; with `intr` it is angular consistency
    of the world rays (intra-pano baseline ~0.08-0.16 m -> parallax < ~2 deg beyond 3 m).
    """
    out = out or MatchSet()
    for pid in pano_ids:
        for k in range(6):
            k2 = (k + 1) % 6
            if (pid, k) not in inst.index or (pid, k2) not in inst.index:
                continue
            fa, fb = feats(pid, k), feats(pid, k2)
            sa = fa.uv[:, 0] > 0.5 * width
            sb = fb.uv[:, 0] < 0.5 * width
            ia_, ib_ = cf.ratio_match(fa.desc[sa], fb.desc[sb], ratio)
            if len(ia_) < 12:
                continue
            ua = fa.uv[sa][ia_]
            ub = fb.uv[sb][ib_]
            ia, ib = inst.index[(pid, k)], inst.index[(pid, k2)]
            if intr is None:
                ok = pixel_ransac_inliers(ua, ub)
            else:
                ok = cf.angular_inliers(
                    _world_rays(inst, intr, ia, ua), _world_rays(inst, intr, ib, ub), thr_deg
                )
            if ok.sum() >= 8:
                out.add(ia, ib, ua[ok], ub[ok], 0, -1)
    return out


def sequence_matches(
    inst: InstanceSet,
    feats: Callable[[str, int], FrameFeatures],
    pairs: Sequence[tuple[str, str]],
    intr: Intrinsics,
    thr_deg: float = 0.5,
    ratio: float = 0.8,
    min_inliers: int = 20,
    cams: Sequence[int] = range(6),
    out: MatchSet | None = None,
    pair_offset: int = 0,
) -> MatchSet:
    """Same-index camera matches between consecutive panos (essential RANSAC on rays)."""
    out = out or MatchSet()
    for q, (p1, p2) in enumerate(pairs):
        for k in cams:
            if (p1, k) not in inst.index or (p2, k) not in inst.index:
                continue
            fa, fb = feats(p1, k), feats(p2, k)
            ia_, ib_ = cf.ratio_match(fa.desc, fb.desc, ratio)
            if len(ia_) < min_inliers:
                continue
            ua, ub = fa.uv[ia_], fb.uv[ib_]
            ok = cf.essential_inliers(
                rosette.unproject(intr, ua), rosette.unproject(intr, ub), thr_deg
            )
            if ok.sum() >= min_inliers:
                out.add(
                    inst.index[(p1, k)], inst.index[(p2, k)], ua[ok], ub[ok], 1, pair_offset + q
                )
    return out


# --------------------------------------------------------------------------- line chains


def chain_geometry(
    inst: InstanceSet, intr: Intrinsics, idx: int, uv: np.ndarray
) -> tuple[float, float, np.ndarray, float, float]:
    """(rms great-circle residual deg, angular extent deg, world normal, az span, el span)."""
    rays_cam = rosette.unproject(intr, uv)
    res, _ = calibrate.great_circle_residuals(rays_cam)
    ext = float(cf.angle_between_deg(rays_cam[0], rays_cam[-1]))
    rays_w = _world_rays(inst, intr, idx, uv)
    _, n_w = calibrate.great_circle_residuals(rays_w)
    az, el = rosette.dir_to_bearing(rays_w)
    az_span = float(np.ptp(np.unwrap(np.radians(az))) * 180 / np.pi)
    el_span = float(np.ptp(el))
    return float(np.sqrt(np.mean(res**2))), ext, n_w, az_span, el_span


def select_chains(
    inst: InstanceSet,
    intr: Intrinsics,
    raw: Iterable[tuple[int, np.ndarray]],
    max_rms_deg: float = 0.15,
    min_extent_deg: float = 5.0,
    vertical_tol_deg: float = 15.0,
    per_instance: int = 8,
) -> list[Chain]:
    """Straight chains under `intr`; vertical = world plane normal within tol of horizontal."""
    by_inst: dict[int, list[tuple[float, Chain]]] = {}
    sin_tol = np.sin(np.radians(vertical_tol_deg))
    for idx, uv in raw:
        if len(uv) < 20:
            continue
        rms, ext, n_w, az_span, el_span = chain_geometry(inst, intr, idx, uv)
        if rms > max_rms_deg or ext < min_extent_deg:
            continue
        vertical = abs(n_w[2]) < sin_tol and el_span > az_span
        by_inst.setdefault(idx, []).append((ext, Chain(idx, uv, bool(vertical))))
    out = []
    for lst in by_inst.values():
        lst.sort(key=lambda t: -t[0])
        out.extend(c for _, c in lst[:per_instance])
    return out
