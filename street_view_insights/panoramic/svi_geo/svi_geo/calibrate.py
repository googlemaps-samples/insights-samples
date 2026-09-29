"""Pano-only self-calibration of the shared rosette intrinsics.

No intrinsics are published for `SV_PANO` frames, so we fit one KB4 fisheye model shared by
cameras 0-5, plus small per-camera-index rotation corrections, the rosette radius and the
sign convention of `camera_pose` pitch/roll. Constraints (all residuals are angular, deg):

[a] intra-pano overlap: feature matches between adjacent cameras (k, k+1) of one pano.
[b] consecutive panos: matches between same-direction cameras of panos ~10 m apart
    (per-pair GNSS/yaw nuisance with priors).
[c] line priors: long edge chains must map to great circles (straightness), and chains
    classified as vertical must lie in a vertical plane (verticality).

Per-match depths are eliminated in closed form (variable projection): for the current global
parameters each match is midpoint-triangulated (depth floored at 1 / RHO_MAX) and the residual is
the angular error in both views. Only ~30-80 global parameters remain, so a dense exact
trust-region solve is fast. Everything is numpy/scipy; nothing here uses an LLM.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Iterable, Sequence
from typing import Any

import numpy as np
from scipy.optimize import least_squares

from svi_geo import rosette
from svi_geo.rosette import Intrinsics

F_SCALE_DEG = 0.5
DELTA_SIGMA_DEG = 0.5
NUIS_SIGMA_DEG = 0.3
NUIS_SIGMA_M = 0.3
GAUGE_WEIGHT = 100.0
RHO_MAX = 0.5

# --------------------------------------------------------------------------- data model


@dataclasses.dataclass
class CamInstance:
    """One physical frame: pano position + reported pose angles + camera index."""

    pano_id: str
    cam_k: int
    center_enu: np.ndarray  # pano (rosette) centre in a local ENU frame, metres
    heading: float
    pitch: float
    roll: float


@dataclasses.dataclass
class Chain:
    inst: int
    uv: np.ndarray  # (M, 2) full-resolution pixels
    vertical: bool = False


@dataclasses.dataclass
class CalibProblem:
    width: int
    height: int
    instances: list[CamInstance]
    # matches: parallel arrays
    m_a: np.ndarray  # instance index of view 1
    m_b: np.ndarray  # instance index of view 2
    uv_a: np.ndarray  # (N, 2)
    uv_b: np.ndarray  # (N, 2)
    m_kind: np.ndarray  # 0 = intra-pano overlap, 1 = consecutive-pano
    m_pair: np.ndarray  # consecutive-pano pair id (index into nuisance), -1 for intra
    n_pairs: int
    chains: list[Chain] = dataclasses.field(default_factory=list)

    @property
    def n_intra(self) -> int:
        return int((self.m_kind == 0).sum())

    @property
    def n_seq(self) -> int:
        return int((self.m_kind == 1).sum())

    def subset(self, keep: np.ndarray) -> CalibProblem:
        return dataclasses.replace(
            self,
            m_a=self.m_a[keep],
            m_b=self.m_b[keep],
            uv_a=self.uv_a[keep],
            uv_b=self.uv_b[keep],
            m_kind=self.m_kind[keep],
            m_pair=self.m_pair[keep],
        )


# --------------------------------------------------------------------------- geometry helpers


def rot_batch(h_deg, p_deg, r_deg) -> np.ndarray:
    """Vectorised `rosette.cam_rotation` (convention/delta already applied): (n, 3, 3)."""
    h, p, r = (np.radians(np.asarray(x, dtype=np.float64)) for x in (h_deg, p_deg, r_deg))
    sh, ch, sp, cp, sr, cr = np.sin(h), np.cos(h), np.sin(p), np.cos(p), np.sin(r), np.cos(r)
    fwd = np.stack([sh * cp, ch * cp, sp], -1)
    right0 = np.stack([ch, -sh, np.zeros_like(h)], -1)
    down0 = np.cross(fwd, right0)
    right = cr[..., None] * right0 + sr[..., None] * down0
    down = -sr[..., None] * right0 + cr[..., None] * down0
    return np.stack([right, down, fwd], -1)


def great_circle_residuals(rays: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Signed angular distance (deg) of unit rays from their best-fit great circle, and its normal."""
    rays = np.asarray(rays, dtype=np.float64)
    _, _, vt = np.linalg.svd(rays, full_matrices=False)
    n = vt[-1]
    return np.degrees(np.arcsin(np.clip(rays @ n, -1.0, 1.0))), n


def batched_great_circles(rays: np.ndarray, offsets: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """`great_circle_residuals` for many chains at once.

    `rays` (N, 3) are the concatenated unit rays; chain i is rays[offsets[i]:offsets[i+1]].
    Normals are oriented along cross(first ray, last ray) so residual signs are stable across
    solver iterations (finite-difference Jacobians break if a normal flips).
    """
    outer = rays[:, :, None] * rays[:, None, :]
    scatter = np.add.reduceat(outer, offsets[:-1], axis=0)
    _, vecs = np.linalg.eigh(scatter)
    normals = vecs[:, :, 0]
    ref = np.cross(rays[offsets[:-1]], rays[offsets[1:] - 1])
    normals *= np.where(np.sum(normals * ref, -1) < 0, -1.0, 1.0)[:, None]
    chain_of = np.repeat(np.arange(len(offsets) - 1), np.diff(offsets))
    res = np.degrees(np.arcsin(np.clip(np.sum(rays * normals[chain_of], -1), -1.0, 1.0)))
    return res, normals


def _angle_deg(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a = a / np.linalg.norm(a, axis=-1, keepdims=True)
    b = b / np.linalg.norm(b, axis=-1, keepdims=True)
    return np.degrees(np.arctan2(np.linalg.norm(np.cross(a, b), axis=-1), np.sum(a * b, -1)))


MIN_DEPTH_M = 3.0


def _midpoint(c1, r1, c2, r2, min_depth_m: float, far_m: float):
    c1 = np.broadcast_to(np.asarray(c1, float), np.shape(r1))
    c2 = np.broadcast_to(np.asarray(c2, float), np.shape(r2))
    w0 = c1 - c2
    a = np.sum(r1 * r1, -1)
    b = np.sum(r1 * r2, -1)
    c = np.sum(r2 * r2, -1)
    d = np.sum(r1 * w0, -1)
    e = np.sum(r2 * w0, -1)
    den = a * c - b * b
    ok = den > 1e-12
    s = np.where(ok, (b * e - c * d) / np.where(ok, den, 1.0), far_m)
    t = np.where(ok, (a * e - b * d) / np.where(ok, den, 1.0), far_m)
    # rays that diverge (negative depth) are treated as points at infinity
    s = np.where(s < 0, far_m, s)
    t = np.where(t < 0, far_m, t)
    s = np.clip(s, min_depth_m, far_m)
    t = np.clip(t, min_depth_m, far_m)
    x = 0.5 * ((c1 + s[..., None] * r1) + (c2 + t[..., None] * r2))
    return c1, c2, x


def two_view_error_components(
    c1, r1, c2, r2, min_depth_m: float = MIN_DEPTH_M, far_m: float = 1e4
) -> dict[str, np.ndarray]:
    """Midpoint triangulation errors split into along- and across-epipolar components (deg).

    `across` is the out-of-epipolar-plane angle (cannot be absorbed by depth); `along` is the
    in-plane remainder (partly absorbable by depth; bounded by the `min_depth_m` floor).
    """
    c1, c2, x = _midpoint(c1, r1, c2, r2, min_depth_m, far_m)
    out = {}
    for name, c, r, other in (("a", c1, r1, c2), ("b", c2, r2, c1)):
        pred = x - c
        tot = _angle_deg(pred, r)
        base = other - c
        n = np.cross(base, r)
        nn = np.linalg.norm(n, axis=-1, keepdims=True)
        n = np.where(nn > 1e-12, n / np.where(nn > 1e-12, nn, 1.0), 0.0)
        pu = pred / np.linalg.norm(pred, axis=-1, keepdims=True)
        across = np.degrees(np.arcsin(np.clip(np.abs(np.sum(pu * n, -1)), 0.0, 1.0)))
        out[f"total_{name}"] = tot
        out[f"across_{name}"] = across
        out[f"along_{name}"] = np.sqrt(np.maximum(tot**2 - across**2, 0.0))
    return out


def two_view_errors_deg(c1, r1, c2, r2, far_m: float = 1e4, min_depth_m: float = MIN_DEPTH_M):
    """Midpoint-triangulate each ray pair; angular error (deg) of the point in each view.

    Depths are floored at `min_depth_m` (default 3 m): with a ~0.1 m rosette baseline a lower
    floor would let a small depth absorb several degrees of along-epipolar (bearing) error.
    """
    c1, c2, x = _midpoint(c1, r1, c2, r2, min_depth_m, far_m)
    return _angle_deg(x - c1, r1), _angle_deg(x - c2, r2)


# --------------------------------------------------------------------------- parameter packing


@dataclasses.dataclass
class _Layout:
    fit_k: tuple[int, ...]
    n_inst: int
    n_pairs: int
    n_match: int

    @property
    def n_intr(self) -> int:
        return 3 + len(self.fit_k)  # f, cx, cy, k...

    @property
    def i_delta(self) -> int:
        return self.n_intr

    @property
    def i_r(self) -> int:
        return self.i_delta + 18

    @property
    def i_nuis(self) -> int:
        return self.i_r + 1

    @property
    def i_rho(self) -> int:
        return self.i_nuis + 3 * self.n_pairs

    @property
    def size(self) -> int:
        return self.i_rho + self.n_match


def _unpack(
    x: np.ndarray, lay: _Layout, base: Intrinsics
) -> tuple[Intrinsics, np.ndarray, float, np.ndarray, np.ndarray]:
    ks = [base.k1, base.k2, base.k3, base.k4]
    for j, k in enumerate(lay.fit_k):
        ks[k - 1] = x[3 + j]
    intr = dataclasses.replace(
        base, fx=x[0], fy=x[0], cx=x[1], cy=x[2], k1=ks[0], k2=ks[1], k3=ks[2], k4=ks[3]
    )
    deltas = x[lay.i_delta : lay.i_delta + 18].reshape(6, 3)
    r = float(x[lay.i_r])
    nuis = x[lay.i_nuis : lay.i_rho].reshape(lay.n_pairs, 3)
    rho = x[lay.i_rho :]
    return intr, deltas, r, nuis, rho


class _Model:
    """Residual evaluation for one CalibProblem under a pose convention."""

    def __init__(
        self,
        prob: CalibProblem,
        base: Intrinsics,
        convention: Sequence[int],
        fit_k: tuple[int, ...],
        use_overlap: bool,
        use_sequence: bool,
        use_lines: bool,
        line_weight: float,
        radius_prior: tuple[float, float] = (0.10, 1e-3),
    ):
        self.prob = prob
        self.radius_prior = radius_prior
        self.base = base
        self.conv = tuple(convention)
        keep = np.zeros(len(prob.m_kind), bool)
        if use_overlap:
            keep |= prob.m_kind == 0
        if use_sequence:
            keep |= prob.m_kind == 1
        self.keep = keep
        self.use_lines = use_lines and len(prob.chains) > 0
        self.line_w = math.sqrt(line_weight)
        inst = prob.instances
        self.k = np.array([i.cam_k for i in inst])
        self.h = np.array([i.heading for i in inst])
        self.p = np.array([i.pitch for i in inst]) * self.conv[0]
        self.r = np.array([i.roll for i in inst]) * self.conv[1]
        self.c = np.array([i.center_enu for i in inst], dtype=np.float64)
        sel = np.nonzero(keep)[0]
        self.sel = sel
        self.a, self.b = prob.m_a[sel], prob.m_b[sel]
        self.uva, self.uvb = prob.uv_a[sel], prob.uv_b[sel]
        self.pair = prob.m_pair[sel]
        self.lay = _Layout(fit_k, len(inst), prob.n_pairs, 0)  # depths: closed form
        if self.use_lines:
            self.ch_inst = np.array([c.inst for c in prob.chains])
            self.ch_vert = np.array([c.vertical for c in prob.chains])
            self.ch_len = np.array([len(c.uv) for c in prob.chains])
            self.ch_uv = np.concatenate([c.uv for c in prob.chains])
            self.ch_off = np.concatenate([[0], np.cumsum(self.ch_len)])
        self.n_res = self._count()
        self._unproj_cache: dict[str, tuple[tuple[float, ...], np.ndarray]] = {}

    def _unproj(self, intr: Intrinsics, key: str, uv: np.ndarray) -> np.ndarray:
        """unproject() memoised on the intrinsics: most finite-difference column groups only
        perturb rotations / depths, so the (iterative) KB4 inversion can be reused."""
        ik = (intr.fx, intr.fy, intr.cx, intr.cy, intr.k1, intr.k2, intr.k3, intr.k4)
        hit = self._unproj_cache.get(key)
        if hit is not None and hit[0] == ik:
            return hit[1]
        d = rosette.unproject(intr, uv)
        self._unproj_cache[key] = (ik, d)
        return d

    def _count(self) -> int:
        n = 6 * len(self.sel) + 18 + 3 + 3 * self.lay.n_pairs + 1
        if self.use_lines:
            n += int(self.ch_len.sum()) + int(self.ch_vert.sum())
        return n

    # ---------------------------------------------------------------- poses
    def poses(
        self,
        deltas: np.ndarray,
        r: float,
        nuis: np.ndarray,
        extra_yaw=None,
        extra_e=None,
        extra_n=None,
    ):
        h = self.h + deltas[self.k, 0]
        p = self.p + deltas[self.k, 1]
        rr = self.r + deltas[self.k, 2]
        R = rot_batch(h, p, rr)
        hh = np.radians(self.h)
        C = self.c + r * np.stack([np.sin(hh), np.cos(hh), np.zeros_like(hh)], -1)
        return R, C

    def _match_rot_centres(self, deltas, r, nuis):
        R, C = self.poses(deltas, r, nuis)
        Ra, Ca = R[self.a], C[self.a]
        Rb, Cb = R[self.b].copy(), C[self.b].copy()
        m = self.pair >= 0
        if m.any():
            nz = nuis[self.pair[m]]
            h = self.h[self.b[m]] + deltas[self.k[self.b[m]], 0] + nz[:, 0]
            p = self.p[self.b[m]] + deltas[self.k[self.b[m]], 1]
            rr = self.r[self.b[m]] + deltas[self.k[self.b[m]], 2]
            Rb[m] = rot_batch(h, p, rr)
            Cb[m] = Cb[m] + np.stack([nz[:, 1], nz[:, 2], np.zeros(m.sum())], -1)
        return Ra, Ca, Rb, Cb

    def match_residual_vectors(self, x):
        """(N, 6) chord residuals (deg) in views a and b after midpoint triangulation."""
        intr, deltas, r, nuis, _ = _unpack(x, self.lay, self.base)
        Ra, Ca, Rb, Cb = self._match_rot_centres(deltas, r, nuis)
        da, db = self._unproj(intr, "a", self.uva), self._unproj(intr, "b", self.uvb)
        ra = np.einsum("nij,nj->ni", Ra, da)
        rb = np.einsum("nij,nj->ni", Rb, db)
        _, _, X = _midpoint(Ca, ra, Cb, rb, 1.0 / RHO_MAX, 1e4)
        pa = np.einsum("nji,nj->ni", Ra, X - Ca)
        pb = np.einsum("nji,nj->ni", Rb, X - Cb)
        pa /= np.linalg.norm(pa, axis=-1, keepdims=True)
        pb /= np.linalg.norm(pb, axis=-1, keepdims=True)
        return np.degrees(np.concatenate([pa - da, pb - db], -1))

    def residuals(self, x):
        intr, deltas, r, nuis, _ = _unpack(x, self.lay, self.base)
        # Angular residuals shrink as f grows (zooming in), which makes f run away when the
        # wide-angle overlap term is absent; weighting by f / f_ref gives pixel-equivalent
        # residuals (reprojection error) that carry no such bias.
        px = intr.fx / self.base.fx
        parts = [self.match_residual_vectors(x).ravel() * px]
        s = F_SCALE_DEG
        parts.append((deltas / DELTA_SIGMA_DEG * s).ravel())
        parts.append(deltas.mean(0) * GAUGE_WEIGHT)
        nsig = np.array([NUIS_SIGMA_DEG, NUIS_SIGMA_M, NUIS_SIGMA_M])
        parts.append((nuis / nsig * s).ravel())
        r0, r_sigma = self.radius_prior
        parts.append(np.array([(r - r0) / r_sigma * s]))
        if self.use_lines:
            parts.extend(p * px for p in self._line_residuals(intr, deltas, r, nuis))
        return np.concatenate(parts)

    def _line_residuals(self, intr, deltas, r, nuis):
        rays = self._unproj(intr, "ch", self.ch_uv)
        straight, normals = batched_great_circles(rays, self.ch_off)
        out = [straight * self.line_w]
        if self.ch_vert.any():
            R, _ = self.poses(deltas, r, nuis)
            nw = np.einsum("nij,nj->ni", R[self.ch_inst[self.ch_vert]], normals[self.ch_vert])
            out.append(np.degrees(np.arcsin(np.clip(nw[:, 2], -1, 1))) * self.line_w)
        return out


# --------------------------------------------------------------------------- fitting


@dataclasses.dataclass
class FitResult:
    intrinsics: Intrinsics
    cost: float
    convention_costs: dict[tuple[int, int], float]
    inliers: np.ndarray  # mask over prob matches (True = used in final fit)
    report: dict[str, Any]


def _x0(model: _Model, init: Intrinsics, f0: float, r0: float) -> np.ndarray:
    lay = model.lay
    x = np.zeros(lay.size)
    x[0], x[1], x[2] = f0, init.cx, init.cy
    ks = [init.k1, init.k2, init.k3, init.k4]
    for j, k in enumerate(lay.fit_k):
        x[3 + j] = ks[k - 1]
    x[lay.i_r] = r0
    return x


def _bounds(model: _Model, init: Intrinsics, f0: float) -> tuple[np.ndarray, np.ndarray]:
    lay = model.lay
    lo = np.full(lay.size, -np.inf)
    hi = np.full(lay.size, np.inf)
    lo[0], hi[0] = 0.5 * f0, 2.0 * f0
    lo[1], hi[1] = init.cx - 400, init.cx + 400
    lo[2], hi[2] = init.cy - 600, init.cy + 600
    lo[3 : lay.n_intr], hi[3 : lay.n_intr] = -0.5, 0.5
    lo[lay.i_delta : lay.i_r], hi[lay.i_delta : lay.i_r] = -5.0, 5.0
    lo[lay.i_r], hi[lay.i_r] = 0.0, 0.3
    nz = np.tile([3.0, 3.0, 3.0], lay.n_pairs)
    lo[lay.i_nuis : lay.i_rho], hi[lay.i_nuis : lay.i_rho] = -nz, nz
    return lo, hi


def _grid_f(model: _Model, init: Intrinsics, grid: Iterable[float], r0: float) -> float:
    """Pick an initial focal length by the median residual over a coarse grid."""
    best_f, best = None, np.inf
    for f in grid:
        x = _x0(model, dataclasses.replace(init, k1=0, k2=0, k3=0, k4=0), f, r0)
        res = model.residuals(x)
        nm = 6 * len(model.sel)
        if nm:
            score = float(np.median(np.abs(res[:nm])))
        else:
            score = float(np.median(np.abs(res[nm + 22 + 3 * model.lay.n_pairs :])))
        if score < best:
            best, best_f = score, f
    return float(best_f)


def _solve(model: _Model, x0, lo, hi, max_nfev):
    x0 = np.clip(x0, lo + 1e-12, hi - 1e-12)
    return least_squares(
        model.residuals,
        x0,
        bounds=(lo, hi),
        loss="soft_l1",
        f_scale=F_SCALE_DEG,
        x_scale="jac",
        method="trf",
        tr_solver="exact",
        max_nfev=max_nfev,
        xtol=1e-10,
        ftol=1e-10,
        gtol=1e-10,
    )


def _match_norms(model: _Model, x) -> np.ndarray:
    return np.linalg.norm(model.match_residual_vectors(x), axis=-1)


def fit(
    prob: CalibProblem,
    init: Intrinsics,
    use_overlap: bool = True,
    use_sequence: bool = True,
    use_lines: bool = True,
    conventions: Sequence[tuple[int, int]] = ((1, 1),),
    fit_k: tuple[int, ...] = (1, 2, 3),
    line_weight: float = 0.2,
    f_grid: Iterable[float] | None = None,
    outlier_rounds: int = 2,
    max_nfev: int = 200,
    radius_m: float = 0.10,
    fit_radius: bool = False,
    log=None,
) -> FitResult:
    """Fit shared KB4 intrinsics + per-camera deltas (+ pose convention).

    The rosette radius is held at `radius_m` by default: with a free inverse depth per match,
    intra-pano residuals depend only on rho * r (an exact gauge, see
    `test_radius_is_a_gauge_of_intra_pano_matches`), and the ~10 m consecutive-pano baseline
    makes the remaining sensitivity negligible next to GNSS noise. `fit_radius=True` frees it
    with a weak 5 cm prior (diagnostic only).
    """
    radius_prior = (radius_m, 0.05 if fit_radius else 1e-4)
    f_grid = list(f_grid) if f_grid is not None else list(np.linspace(0.6, 1.6, 21) * init.fx)
    conv_costs: dict[tuple[int, int], float] = {}
    best = None
    for conv in conventions:
        model = _Model(
            prob, init, conv, fit_k, use_overlap, use_sequence, use_lines, line_weight, radius_prior
        )
        f0 = _grid_f(model, init, f_grid, radius_m)
        lo, hi = _bounds(model, init, f0)
        x = _x0(model, init, f0, radius_m)
        sol = _solve(model, x, lo, hi, max_nfev=max_nfev if len(conventions) == 1 else 60)
        conv_costs[tuple(conv)] = float(sol.cost)
        if log:
            log(f"convention {conv}: f0={f0:.0f} cost={sol.cost:.1f}")
        if best is None or sol.cost < best[0]:
            best = (sol.cost, conv, model, sol, lo, hi)
    _, conv, model, sol, lo, hi = best
    keep_all = model.keep.copy()
    # outlier rejection + refit on the chosen convention
    x = sol.x
    final_lay = model.lay
    inl = np.ones(len(model.sel), bool)
    rounds: list[dict[str, float]] = []
    for _ in range(outlier_rounds):
        norms = _match_norms(model, x)
        thr = max(1.0, 4.0 * float(np.median(norms[inl]))) if inl.any() else 1.0
        inl = norms < thr
        keep = np.zeros(len(prob.m_kind), bool)
        keep[model.sel[inl]] = True
        sub = prob.subset(keep)
        model2 = _Model(
            sub, init, conv, fit_k, use_overlap, use_sequence, use_lines, line_weight, radius_prior
        )
        final_lay = model2.lay
        lo2, hi2 = _bounds(model2, init, float(x[0]))
        lo2[0], hi2[0] = lo[0], hi[0]
        sol = _solve(model2, x, lo2, hi2, max_nfev=max_nfev)
        x = sol.x
        rounds.append({"threshold_deg": thr, "inlier_frac": float(inl.mean())})
    intr, deltas, r, nuis, _ = _unpack(sol.x, final_lay, init)
    inliers = np.zeros(len(prob.m_kind), bool)
    inliers[model.sel[inl]] = True
    final = dataclasses.replace(
        intr,
        fitted=True,
        rosette_radius_m=float(r),
        cam_rot_delta_deg={k: [float(v) for v in deltas[k]] for k in range(6)},
        pose_convention=tuple(int(c) for c in conv),
    )
    report = {
        "convention_costs": {str(k): v for k, v in conv_costs.items()},
        "n_matches_used": int(inliers.sum()),
        "n_matches_total": int(keep_all.sum()),
        "n_chains": len(prob.chains),
        "cost": float(sol.cost),
        "nfev": int(sol.nfev),
        "status": int(sol.status),
        "outlier_rounds": rounds,
    }
    return FitResult(final, float(sol.cost), conv_costs, inliers, report)


# --------------------------------------------------------------------------- evaluation


def world_rays_and_centres(prob: CalibProblem, intr: Intrinsics, idx: np.ndarray, uv: np.ndarray):
    """World rays + camera centres for instance indices `idx` observing pixels `uv`."""
    inst = [prob.instances[i] for i in idx]
    conv = intr.pose_convention
    h = np.array([i.heading for i in inst], dtype=np.float64)
    p = np.array([i.pitch for i in inst]) * conv[0]
    r = np.array([i.roll for i in inst]) * conv[1]
    k = np.array([i.cam_k for i in inst])
    dl = np.array([intr.cam_rot_delta_deg.get(int(kk), [0.0, 0.0, 0.0]) for kk in k]).reshape(-1, 3)
    R = rot_batch(h + dl[:, 0], p + dl[:, 1], r + dl[:, 2])
    hh = np.radians(h)
    C = np.array([i.center_enu for i in inst]) + intr.rosette_radius_m * np.stack(
        [np.sin(hh), np.cos(hh), np.zeros_like(hh)], -1
    )
    rays = np.einsum("nij,nj->ni", R, rosette.unproject(intr, uv))
    return rays, C


def heldout_match_errors(
    prob: CalibProblem, intr: Intrinsics, kind: int = 0, min_depth_m: float = MIN_DEPTH_M
) -> np.ndarray:
    """Angular error (deg) in both views after midpoint triangulation, for matches of `kind`."""
    comp = heldout_match_error_components(prob, intr, kind, min_depth_m)
    if not comp:
        return np.array([])
    return np.concatenate([comp["total_a"], comp["total_b"]])


def heldout_match_error_components(
    prob: CalibProblem, intr: Intrinsics, kind: int = 0, min_depth_m: float = MIN_DEPTH_M
) -> dict[str, np.ndarray]:
    sel = prob.m_kind == kind
    if not sel.any():
        return {}
    ra, ca = world_rays_and_centres(prob, intr, prob.m_a[sel], prob.uv_a[sel])
    rb, cb = world_rays_and_centres(prob, intr, prob.m_b[sel], prob.uv_b[sel])
    return two_view_error_components(ca, ra, cb, rb, min_depth_m=min_depth_m)


def verticality_residuals(prob: CalibProblem, intr: Intrinsics) -> np.ndarray:
    """|angle| (deg) between world up and the great-circle plane of each vertical chain."""
    out = []
    for c in prob.chains:
        if not c.vertical:
            continue
        rays, _ = world_rays_and_centres(prob, intr, np.full(len(c.uv), c.inst), c.uv)
        _, n = great_circle_residuals(rays)
        out.append(abs(math.degrees(math.asin(np.clip(n[2], -1, 1)))))
    return np.array(out)


def straightness_residuals(prob: CalibProblem, intr: Intrinsics) -> np.ndarray:
    """RMS great-circle residual (deg) per chain."""
    out = []
    for c in prob.chains:
        res, _ = great_circle_residuals(rosette.unproject(intr, c.uv))
        out.append(float(np.sqrt(np.mean(res**2))))
    return np.array(out)


# --------------------------------------------------------------------------- synthetic problems


def synthetic_rosette_problem(
    true: Intrinsics,
    n_panos: int = 10,
    n_points_per_pair: int = 50,
    n_seq_pairs: int = 6,
    n_lines_per_cam: int = 2,
    pixel_noise: float = 0.5,
    outlier_frac: float = 0.1,
    delta_sigma_deg: float = 0.3,
    seed: int = 0,
    reported_convention: tuple[int, int] = (1, 1),
    deltas: dict[int, Sequence[float]] | None = None,
) -> tuple[CalibProblem, dict]:
    """Synthetic rosette scenes with known intrinsics/deltas/radius (zero mocks)."""
    rng = np.random.default_rng(seed)
    if deltas is None:
        d = rng.normal(0, delta_sigma_deg, size=(6, 3))
        d -= d.mean(0)
    else:
        d = np.array([deltas[k] for k in range(6)], dtype=np.float64)
    r0 = true.rosette_radius_m
    instances: list[CamInstance] = []
    true_R: list[np.ndarray] = []
    true_C: list[np.ndarray] = []

    def add_pano(pid: str, centre: np.ndarray, base_heading: float) -> list[int]:
        idx = []
        for k in range(6):
            h = base_heading + 60.0 * k + rng.normal(0, 0.5)
            p_true = (9.0 if k % 2 == 0 else -9.0) + rng.normal(0, 0.5)
            r_true = rng.normal(0, 1.0)
            R = rosette.cam_rotation(h, p_true, r_true, (1, 1), d[k])
            hh = math.radians(h)
            C = centre + r0 * np.array([math.sin(hh), math.cos(hh), 0.0])
            instances.append(
                CamInstance(
                    pid,
                    k,
                    centre.copy(),
                    h,
                    p_true * reported_convention[0],
                    r_true * reported_convention[1],
                )
            )
            true_R.append(R)
            true_C.append(C)
            idx.append(len(instances) - 1)
        return idx

    def visible(i: int, X: np.ndarray):
        dc = (X - true_C[i]) @ true_R[i]
        uv = rosette.project(true, dc)
        th = np.degrees(np.arccos(np.clip(dc[:, 2] / np.linalg.norm(dc, axis=1), -1, 1)))
        ok = (th < true.max_theta_deg - 3) & (uv[:, 0] > 5) & (uv[:, 0] < true.width - 5)
        ok &= (uv[:, 1] > 5) & (uv[:, 1] < true.height - 5)
        return uv, ok

    m_a, m_b, uva, uvb, kind, pair = [], [], [], [], [], []

    def add_matches(ia, ib, X, knd, pid):
        ua, oka = visible(ia, X)
        ub, okb = visible(ib, X)
        ok = oka & okb
        ua, ub = ua[ok], ub[ok]
        ua = ua + rng.normal(0, pixel_noise, ua.shape)
        ub = ub + rng.normal(0, pixel_noise, ub.shape)
        n_out = int(round(outlier_frac * len(ub)))
        if n_out:
            j = rng.choice(len(ub), n_out, replace=False)
            ub[j] = rng.uniform([0, 0], [true.width, true.height], size=(n_out, 2))
        for q in range(len(ua)):
            m_a.append(ia)
            m_b.append(ib)
            uva.append(ua[q])
            uvb.append(ub[q])
            kind.append(knd)
            pair.append(pid)

    chains: list[Chain] = []
    pano_idx = []
    for i in range(n_panos):
        centre = np.array([i * 80.0, rng.normal(0, 5), 0.0])
        idx = add_pano(f"P{i}", centre, rng.uniform(0, 360))
        pano_idx.append(idx)
        for k in range(6):
            ia, ib = idx[k], idx[(k + 1) % 6]
            h = instances[ia].heading + 30.0
            az = np.radians(h + rng.uniform(-22, 22, n_points_per_pair * 3))
            el = np.radians(rng.uniform(-35, 45, n_points_per_pair * 3))
            dist = rng.uniform(5, 60, n_points_per_pair * 3)
            X = centre + dist[:, None] * np.stack(
                [np.sin(az) * np.cos(el), np.cos(az) * np.cos(el), np.sin(el)], -1
            )
            X[:, 2] = np.maximum(X[:, 2], -2.4)
            add_matches(ia, ib, X[: n_points_per_pair * 2], 0, -1)
        # line chains
        for k in range(6):
            ia = idx[k]
            for li in range(n_lines_per_cam):
                vertical = li % 2 == 0
                hdg = math.radians(instances[ia].heading + rng.uniform(-45, 45))
                dist = rng.uniform(6, 25)
                base = centre + dist * np.array([math.sin(hdg), math.cos(hdg), 0.0])
                if vertical:
                    pts = base + np.linspace(-2.3, 6.0, 80)[:, None] * np.array([0, 0, 1.0])
                else:
                    ang = rng.uniform(0, math.pi)
                    dirv = np.array([math.cos(ang), math.sin(ang), 0.0])
                    pts = (
                        base
                        + np.array([0, 0, rng.uniform(-2, 4)])
                        + np.linspace(-6, 6, 80)[:, None] * dirv
                    )
                uv, ok = visible(ia, pts)
                if ok.sum() >= 20:
                    chains.append(
                        Chain(ia, uv[ok] + rng.normal(0, pixel_noise, (ok.sum(), 2)), vertical)
                    )
    # consecutive-pano pairs: displaced copies 10 m ahead along camera 0
    for q in range(n_seq_pairs):
        src = pano_idx[q % len(pano_idx)]
        base_h = instances[src[0]].heading
        centre = instances[src[0]].center_enu + 10.0 * np.array(
            [math.sin(math.radians(base_h)), math.cos(math.radians(base_h)), 0.0]
        )
        idx_b = add_pano(
            f"S{q}", centre + rng.normal(0, 0.1, 3) * [1, 1, 0], base_h + rng.normal(0, 1.0)
        )
        for k in (0, 3):
            ia, ib = src[k], idx_b[k]
            h = instances[ia].heading
            az = np.radians(h + rng.uniform(-40, 40, n_points_per_pair * 3))
            el = np.radians(rng.uniform(-25, 35, n_points_per_pair * 3))
            dist = rng.uniform(15, 60, n_points_per_pair * 3)
            X = instances[ia].center_enu + dist[:, None] * np.stack(
                [np.sin(az) * np.cos(el), np.cos(az) * np.cos(el), np.sin(el)], -1
            )
            X[:, 2] = np.maximum(X[:, 2], -2.4)
            add_matches(ia, ib, X[: n_points_per_pair * 2], 1, q)
    prob = CalibProblem(
        width=true.width,
        height=true.height,
        instances=instances,
        m_a=np.array(m_a, int),
        m_b=np.array(m_b, int),
        uv_a=np.array(uva, float).reshape(-1, 2),
        uv_b=np.array(uvb, float).reshape(-1, 2),
        m_kind=np.array(kind, int),
        m_pair=np.array(pair, int),
        n_pairs=n_seq_pairs,
        chains=chains,
    )
    truth = {"deltas": {k: d[k].tolist() for k in range(6)}, "radius": r0}
    return prob, truth
