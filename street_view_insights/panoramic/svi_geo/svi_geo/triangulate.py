"""Multi-view bearing triangulation in a local ENU frame (pure numpy, no LLM).

A detection in a pano becomes a `Ray`: camera centre (ENU, metres) + world azimuth/elevation
of the object's reference point (e.g. the bottom-centre of its box). Rays from several panos
are intersected in the horizontal plane by linear least squares; the height comes from the
elevations. Degenerate geometry is rejected with an explicit reason instead of returning a
wild point.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Sequence
from typing import Any

import numpy as np


@dataclasses.dataclass(frozen=True)
class Ray:
    origin: np.ndarray  # (3,) ENU metres (camera optical centre)
    az_deg: float  # clockwise from north
    el_deg: float  # up positive
    weight: float = 1.0
    meta: Any = None

    @property
    def dir2d(self) -> np.ndarray:
        a = math.radians(self.az_deg)
        return np.array([math.sin(a), math.cos(a)])


@dataclasses.dataclass(frozen=True)
class Intersection:
    ok: bool
    point: np.ndarray | None  # (3,) ENU
    rms_m: float
    ranges_m: np.ndarray | None
    reason: str = ""


def _max_pairwise_angle_deg(rays: Sequence[Ray]) -> float:
    best = 0.0
    for i in range(len(rays)):
        for j in range(i + 1, len(rays)):
            d = abs(((rays[i].az_deg - rays[j].az_deg + 180.0) % 360.0) - 180.0)
            best = max(best, min(d, 180.0 - d))  # lines, not half-lines
    return best


def intersect_rays(
    rays: Sequence[Ray],
    min_angle_deg: float = 5.0,
    max_range_m: float = 60.0,
    max_rms_m: float = 1.5,
    min_range_m: float = 0.5,
) -> Intersection:
    """Weighted 2D least-squares intersection of >= 2 bearing rays.

    Rejections (ok=False, point=None): `too_few`, `ill_conditioned` (max pairwise ray angle
    below `min_angle_deg`), `behind` (any ray would have to look backwards), `out_of_range`
    (a range > `max_range_m`), `high_rms` (perpendicular misfit rms > `max_rms_m`).
    """
    if len(rays) < 2:
        return Intersection(False, None, math.inf, None, "too_few")
    if _max_pairwise_angle_deg(rays) < min_angle_deg:
        return Intersection(False, None, math.inf, None, "ill_conditioned")
    d = np.array([r.dir2d for r in rays])
    n = np.stack([d[:, 1], -d[:, 0]], -1)  # unit normals to each ray line
    o = np.array([r.origin[:2] for r in rays], float)
    w = np.sqrt(np.array([r.weight for r in rays], float))
    A = n * w[:, None]
    b = np.sum(n * o, -1) * w
    p, *_ = np.linalg.lstsq(A, b, rcond=None)
    ranges = np.sum((p - o) * d, -1)
    if np.any(ranges < min_range_m):
        return Intersection(False, None, math.inf, ranges, "behind")
    if np.any(ranges > max_range_m):
        return Intersection(False, None, math.inf, ranges, "out_of_range")
    perp = np.sum((p - o) * n, -1)
    rms = float(np.sqrt(np.mean(perp**2)))
    if rms > max_rms_m:
        return Intersection(False, None, rms, ranges, "high_rms")
    z = np.array(
        [
            r.origin[2] + t * math.tan(math.radians(r.el_deg))
            for r, t in zip(rays, ranges, strict=True)
        ]
    )
    point = np.array([p[0], p[1], float(np.average(z, weights=w**2))])
    return Intersection(True, point, rms, ranges, "")


def single_view_range(el_bottom_deg: float, cam_height_m: float) -> float | None:
    """Horizontal range to a ground-contact point seen at elevation `el_bottom_deg` (< 0)."""
    if el_bottom_deg >= -0.5:
        return None
    return cam_height_m / math.tan(math.radians(-el_bottom_deg))


def plate_range(el_top_deg: float, el_bottom_deg: float, plate_height_m: float) -> float | None:
    """Horizontal range to a vertical plate of known height from its top/bottom elevations."""
    dt = math.tan(math.radians(el_top_deg)) - math.tan(math.radians(el_bottom_deg))
    if dt <= 1e-6:
        return None
    return plate_height_m / dt


def point_from_range(ray: Ray, range_m: float) -> np.ndarray:
    """ENU point at horizontal distance `range_m` along `ray`."""
    d = ray.dir2d
    z = ray.origin[2] + range_m * math.tan(math.radians(ray.el_deg))
    return np.array([ray.origin[0] + range_m * d[0], ray.origin[1] + range_m * d[1], z])


def ray_point_distance_m(ray: Ray, point: np.ndarray) -> float:
    """Perpendicular horizontal distance of `point` from the ray line (inf if behind)."""
    v = np.asarray(point[:2], float) - ray.origin[:2]
    d = ray.dir2d
    t = float(v @ d)
    if t < 0:
        return math.inf
    return float(abs(v[0] * d[1] - v[1] * d[0]))
