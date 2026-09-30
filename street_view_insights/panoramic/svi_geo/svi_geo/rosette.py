"""7-camera rosette model for Street View Insights panoramic (`SV_PANO`) imagery.

A "pano" in `pano_observations_*` is 7 unstitched frames (observation id
`o1:<pano_id>_<k>:5001ee`, k = 0..6). Cameras 0-5 look roughly horizontally ~60 deg apart,
camera 6 points at the sky. Each frame has its own `camera_pose` (heading, pitch, roll), but
no intrinsics are published, so we model every horizontal camera with one shared
Kannala-Brandt (KB4 / OpenCV fisheye) model, fitted by `svi_geo.calibrate`.

Conventions
-----------
* Camera frame: OpenCV (x right, y down, z forward).
* World frame: local ENU (east, north, up).
* `cam_rotation(...)` returns R (3x3) whose columns are the camera right/down/forward axes
  in ENU, i.e. `d_world = R @ d_cam`.
* Bearings: azimuth in degrees clockwise from north in [0, 360), elevation in degrees.
"""

from __future__ import annotations

import dataclasses
import functools
import json
import math
import re
from collections.abc import Mapping, Sequence
from importlib import resources
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from svi_geo import geo

_OBS_RE = re.compile(r"^o1:(?P<pano>.+)_(?P<k>\d):5001ee$")
SKY_CAMERA = 6
N_GROUND_CAMERAS = 6


# --------------------------------------------------------------------------- ids


def camera_index(observation_id: str | None) -> int | None:
    """Camera index k from `o1:<pano>_<k>:5001ee`, or None if malformed."""
    if not isinstance(observation_id, str):
        return None
    m = _OBS_RE.match(observation_id)
    return int(m.group("k")) if m else None


def pano_id_from_observation(observation_id: str) -> str | None:
    m = _OBS_RE.match(observation_id or "")
    return m.group("pano") if m else None


def is_ground_camera(k: int) -> bool:
    """True for the 6 roughly-horizontal cameras, False for the sky camera (6)."""
    return 0 <= int(k) < N_GROUND_CAMERAS


# --------------------------------------------------------------------------- intrinsics


@dataclasses.dataclass(frozen=True)
class Intrinsics:
    """Shared KB4 fisheye model for the horizontal rosette cameras (full-resolution pixels)."""

    width: int
    height: int
    fx: float
    fy: float
    cx: float
    cy: float
    k1: float = 0.0
    k2: float = 0.0
    k3: float = 0.0
    k4: float = 0.0
    max_theta_deg: float = 100.0
    fitted: bool = False
    source_snapshots: list[str] = dataclasses.field(default_factory=list)
    rosette_radius_m: float = 0.10
    # Per camera index k: small [dyaw, dpitch, droll] corrections (deg) added to camera_pose.
    cam_rot_delta_deg: dict[int, list[float]] = dataclasses.field(default_factory=dict)
    # Sign applied to (pitch, roll) from camera_pose, chosen from data during calibration.
    pose_convention: tuple[int, int] = (1, 1)
    metrics: dict[str, Any] = dataclasses.field(default_factory=dict)
    notes: str = ""

    @property
    def dist(self) -> np.ndarray:
        return np.array([self.k1, self.k2, self.k3, self.k4], dtype=np.float64)

    @property
    def K(self) -> np.ndarray:
        return np.array([[self.fx, 0, self.cx], [0, self.fy, self.cy], [0, 0, 1.0]])

    def scaled(self, s: float) -> Intrinsics:
        """Intrinsics for an image resized by factor `s` (pixel-centre convention)."""
        return dataclasses.replace(
            self,
            width=int(round(self.width * s)),
            height=int(round(self.height * s)),
            fx=self.fx * s,
            fy=self.fy * s,
            cx=(self.cx + 0.5) * s - 0.5,
            cy=(self.cy + 0.5) * s - 0.5,
        )

    def for_image(self, image: np.ndarray) -> Intrinsics:
        """Rescale to match `image` (e.g. a half-resolution copy)."""
        h, w = image.shape[:2]
        if (w, h) == (self.width, self.height):
            return self
        return self.scaled(w / self.width)

    def to_dict(self) -> dict[str, Any]:
        d = dataclasses.asdict(self)
        d["cam_rot_delta_deg"] = {str(k): list(v) for k, v in self.cam_rot_delta_deg.items()}
        d["pose_convention"] = list(self.pose_convention)
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Intrinsics:
        d = dict(d)
        d["cam_rot_delta_deg"] = {
            int(k): [float(x) for x in v] for k, v in d.get("cam_rot_delta_deg", {}).items()
        }
        d["pose_convention"] = tuple(int(x) for x in d.get("pose_convention", (1, 1)))
        d["source_snapshots"] = list(d.get("source_snapshots", []))
        fields = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in fields})

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n")

    @classmethod
    def load(cls, path: str | Path) -> Intrinsics:
        return cls.from_dict(json.loads(Path(path).read_text()))


# Placeholder equidistant guess used until calibration (and as the "uncalibrated" baseline).
DEFAULT_INTRINSICS = Intrinsics(
    width=3648,
    height=5472,
    fx=1400.0,
    fy=1400.0,
    cx=1823.5,
    cy=2735.5,
    max_theta_deg=100.0,
    fitted=False,
    notes="Placeholder equidistant guess (f=1400 px); not fitted.",
)

FITTED_INTRINSICS_FILE = "rosette_kb4_v1.json"


def load_intrinsics(path: str | Path | None = None) -> Intrinsics:
    """Load fitted intrinsics (packaged JSON by default), falling back to the placeholder."""
    if path is not None:
        return Intrinsics.load(path)
    try:
        ref = resources.files("svi_geo").joinpath("intrinsics", FITTED_INTRINSICS_FILE)
        if ref.is_file():
            return Intrinsics.from_dict(json.loads(ref.read_text()))
    except (FileNotFoundError, ModuleNotFoundError):
        pass
    return DEFAULT_INTRINSICS


# --------------------------------------------------------------------------- rotations


def _pose_get(pose: Mapping[str, Any], key: str) -> float:
    v = pose.get(key) if isinstance(pose, Mapping) else getattr(pose, key)
    return 0.0 if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)


def cam_rotation(
    heading_deg: float,
    pitch_deg: float,
    roll_deg: float,
    convention: Sequence[int] = (1, 1),
    delta: Sequence[float] | None = None,
) -> np.ndarray:
    """Camera->ENU rotation. Columns = camera right, down, forward in ENU.

    `convention` = (pitch_sign, roll_sign) applied to the pose angles; `delta` =
    [dyaw, dpitch, droll] degrees added after the sign convention.
    """
    h = float(heading_deg)
    p = convention[0] * float(pitch_deg)
    r = convention[1] * float(roll_deg)
    if delta is not None:
        h, p, r = h + delta[0], p + delta[1], r + delta[2]
    h, p, r = math.radians(h), math.radians(p), math.radians(r)
    fwd = np.array([math.sin(h) * math.cos(p), math.cos(h) * math.cos(p), math.sin(p)])
    right0 = np.array([math.cos(h), -math.sin(h), 0.0])
    down0 = np.cross(fwd, right0)
    right = math.cos(r) * right0 + math.sin(r) * down0
    down = -math.sin(r) * right0 + math.cos(r) * down0
    return np.stack([right, down, fwd], axis=1)


def pose_rotation(
    intr: Intrinsics, pose: Mapping[str, Any], cam_k: int | None = None
) -> np.ndarray:
    """Rotation for a camera pose, applying the fitted convention and per-camera delta."""
    delta = intr.cam_rot_delta_deg.get(int(cam_k)) if cam_k is not None else None
    return cam_rotation(
        _pose_get(pose, "heading"),
        _pose_get(pose, "pitch"),
        _pose_get(pose, "roll"),
        intr.pose_convention,
        delta,
    )


# --------------------------------------------------------------------------- KB4 projection


def project(intr: Intrinsics, d_cam: np.ndarray) -> np.ndarray:
    """Camera-frame directions/points (..., 3) -> pixels (..., 2) with the KB4 model."""
    d = np.asarray(d_cam, dtype=np.float64)
    x, y, z = d[..., 0], d[..., 1], d[..., 2]
    r = np.hypot(x, y)
    theta = np.arctan2(r, z)
    t2 = theta * theta
    theta_d = theta * (1 + t2 * (intr.k1 + t2 * (intr.k2 + t2 * (intr.k3 + t2 * intr.k4))))
    safe_r = np.where(r > 1e-15, r, 1.0)
    scale = np.where(r > 1e-15, theta_d / safe_r, 1.0 / np.where(z != 0, z, 1.0))
    u = intr.fx * x * scale + intr.cx
    v = intr.fy * y * scale + intr.cy
    return np.stack([u, v], axis=-1)


def _theta_from_theta_d(intr: Intrinsics, theta_d: np.ndarray, iters: int = 30) -> np.ndarray:
    k1, k2, k3, k4 = intr.k1, intr.k2, intr.k3, intr.k4
    theta = theta_d.copy()
    for _ in range(iters):
        t2 = theta * theta
        f = theta * (1 + t2 * (k1 + t2 * (k2 + t2 * (k3 + t2 * k4)))) - theta_d
        fp = 1 + t2 * (3 * k1 + t2 * (5 * k2 + t2 * (7 * k3 + t2 * 9 * k4)))
        step = f / np.where(np.abs(fp) > 1e-12, fp, 1e-12)
        theta = np.clip(theta - step, 0.0, math.pi)
        if np.all(np.abs(step) < 1e-15):
            break
    return theta


def unproject(intr: Intrinsics, uv: np.ndarray) -> np.ndarray:
    """Pixels (..., 2) -> unit camera-frame directions (..., 3)."""
    uv = np.asarray(uv, dtype=np.float64)
    mx = (uv[..., 0] - intr.cx) / intr.fx
    my = (uv[..., 1] - intr.cy) / intr.fy
    theta_d = np.hypot(mx, my)
    theta = _theta_from_theta_d(intr, theta_d)
    s = np.where(theta_d > 1e-15, np.sin(theta) / np.where(theta_d > 1e-15, theta_d, 1.0), 1.0)
    return np.stack([mx * s, my * s, np.cos(theta)], axis=-1)


def theta_of_pixel(intr: Intrinsics, uv: np.ndarray) -> np.ndarray:
    """Off-axis angle (rad) of pixels."""
    d = unproject(intr, uv)
    return np.arccos(np.clip(d[..., 2], -1.0, 1.0))


# --------------------------------------------------------------------------- bearings


def dir_to_bearing(d_world: np.ndarray):
    d = np.asarray(d_world, dtype=np.float64)
    az = np.mod(np.degrees(np.arctan2(d[..., 0], d[..., 1])), 360.0)
    el = np.degrees(np.arcsin(np.clip(d[..., 2] / np.linalg.norm(d, axis=-1), -1.0, 1.0)))
    return az, el


def bearing_to_dir(az_deg, el_deg) -> np.ndarray:
    az = np.radians(np.asarray(az_deg, dtype=np.float64))
    el = np.radians(np.asarray(el_deg, dtype=np.float64))
    return np.stack(
        np.broadcast_arrays(np.sin(az) * np.cos(el), np.cos(az) * np.cos(el), np.sin(el)), -1
    )


def world_rays(intr: Intrinsics, pose: Mapping[str, Any], u, v, cam_k: int | None = None):
    """Unit ENU ray directions for pixels (u, v)."""
    uv = np.stack(np.broadcast_arrays(np.asarray(u, float), np.asarray(v, float)), -1)
    return unproject(intr, uv) @ pose_rotation(intr, pose, cam_k).T


def pixel_to_bearing(intr: Intrinsics, pose: Mapping[str, Any], u, v, cam_k: int | None = None):
    """Pixel(s) -> (azimuth deg [0,360), elevation deg) in the world."""
    return dir_to_bearing(world_rays(intr, pose, u, v, cam_k))


def bearing_to_pixel(
    intr: Intrinsics,
    pose: Mapping[str, Any],
    az_deg,
    el_deg,
    cam_k: int | None = None,
    hood_elev_deg: float | None = None,
):
    """World bearing(s) -> (u, v, ok).

    ok = inside the fitted FOV and the image bounds (and above `hood_elev_deg`, if given).
    """
    d_cam = bearing_to_dir(az_deg, el_deg) @ pose_rotation(intr, pose, cam_k)
    uv = project(intr, d_cam)
    theta = np.degrees(np.arccos(np.clip(d_cam[..., 2], -1.0, 1.0)))
    u, v = uv[..., 0], uv[..., 1]
    ok = (
        (theta <= intr.max_theta_deg)
        & (u >= 0)
        & (u <= intr.width - 1)
        & (v >= 0)
        & (v <= intr.height - 1)
    )
    if hood_elev_deg is not None:
        ok &= np.asarray(el_deg, dtype=np.float64) > hood_elev_deg
    return u, v, ok


def camera_center_enu(
    pose: Mapping[str, Any], ref: Sequence[float], extra_offset_m: float = 0.0
) -> np.ndarray:
    """Camera optical centre in ENU(ref).

    `camera_pose` latitude/longitude/altitude are already per camera (they sit ~0.08 m from the
    pano centre along each camera's heading), so the pose position is returned as is.
    `extra_offset_m` adds a horizontal offset along the heading (synthetic scenes only).
    """
    e, n, u = geo.lla_to_enu(
        _pose_get(pose, "latitude"),
        _pose_get(pose, "longitude"),
        _pose_get(pose, "altitude"),
        ref[0],
        ref[1],
        ref[2] if len(ref) > 2 else 0.0,
    )
    h = math.radians(_pose_get(pose, "heading"))
    return np.array(
        [
            float(e) + extra_offset_m * math.sin(h),
            float(n) + extra_offset_m * math.cos(h),
            float(u),
        ]
    )


# --------------------------------------------------------------------------- perspective views


@dataclasses.dataclass(frozen=True)
class PerspectiveView:
    """A virtual, world-oriented pinhole camera (zero roll unless `roll_deg` is set)."""

    yaw_deg: float
    pitch_deg: float
    hfov_deg: float
    width: int
    height: int
    roll_deg: float = 0.0

    @property
    def f(self) -> float:
        return (self.width / 2.0) / math.tan(math.radians(self.hfov_deg) / 2.0)

    @property
    def cx(self) -> float:
        return (self.width - 1) / 2.0

    @property
    def cy(self) -> float:
        return (self.height - 1) / 2.0

    @property
    def R(self) -> np.ndarray:
        return cam_rotation(self.yaw_deg, self.pitch_deg, self.roll_deg)

    def pixel_dirs(self, u, v) -> np.ndarray:
        u = np.asarray(u, dtype=np.float64)
        v = np.asarray(v, dtype=np.float64)
        d = np.stack(np.broadcast_arrays((u - self.cx) / self.f, (v - self.cy) / self.f, 1.0), -1)
        d = d / np.linalg.norm(d, axis=-1, keepdims=True)
        return d @ self.R.T

    def pixel_to_bearing(self, u, v):
        return dir_to_bearing(self.pixel_dirs(u, v))

    def bearing_to_pixel(self, az_deg, el_deg):
        d = bearing_to_dir(az_deg, el_deg) @ self.R
        z = d[..., 2]
        zs = np.where(z > 1e-9, z, 1e-9)
        u = self.f * d[..., 0] / zs + self.cx
        v = self.f * d[..., 1] / zs + self.cy
        ok = (z > 1e-9) & (u >= 0) & (u <= self.width - 1) & (v >= 0) & (v <= self.height - 1)
        return u, v, ok

    def box_to_bearings(self, box_px: Sequence[float]):
        """(x0, y0, x1, y1) view pixels -> dict of centre/bottom/top bearings."""
        x0, y0, x1, y1 = box_px
        xc = (x0 + x1) / 2
        az_c, el_c = self.pixel_to_bearing(xc, (y0 + y1) / 2)
        _, el_b = self.pixel_to_bearing(xc, y1)
        _, el_t = self.pixel_to_bearing(xc, y0)
        az_l, _ = self.pixel_to_bearing(x0, (y0 + y1) / 2)
        az_r, _ = self.pixel_to_bearing(x1, (y0 + y1) / 2)
        return {
            "az": float(az_c),
            "el": float(el_c),
            "el_bottom": float(el_b),
            "el_top": float(el_t),
            "az_width": float(abs(geo.angdiff(az_l, az_r))),
        }


def perspective_maps(
    intr: Intrinsics, pose: Mapping[str, Any], view: PerspectiveView, cam_k: int | None = None
):
    """cv2.remap maps (map_x, map_y float32) from a fisheye frame into `view`."""
    u, v = np.meshgrid(
        np.arange(view.width, dtype=np.float64), np.arange(view.height, dtype=np.float64)
    )
    d_world = view.pixel_dirs(u, v)
    d_cam = d_world @ pose_rotation(intr, pose, cam_k)
    uv = project(intr, d_cam)
    theta = np.degrees(np.arccos(np.clip(d_cam[..., 2], -1.0, 1.0)))
    bad = theta > intr.max_theta_deg
    map_x = np.where(bad, -1.0, uv[..., 0]).astype(np.float32)
    map_y = np.where(bad, -1.0, uv[..., 1]).astype(np.float32)
    return map_x, map_y


def render_perspective(
    image: np.ndarray,
    intr: Intrinsics,
    pose: Mapping[str, Any],
    view: PerspectiveView,
    cam_k: int | None = None,
    interpolation: int = cv2.INTER_LINEAR,
) -> np.ndarray:
    """Resample a fisheye frame into a world-oriented pinhole `view`."""
    intr_img = intr.for_image(image)
    map_x, map_y = perspective_maps(intr_img, pose, view, cam_k)
    return cv2.remap(image, map_x, map_y, interpolation, borderMode=cv2.BORDER_CONSTANT)


_IDENTITY_POSE = {"heading": 0.0, "pitch": 0.0, "roll": 0.0}


def undistort(
    image: np.ndarray,
    intr: Intrinsics,
    hfov_deg: float = 90.0,
    out_size: tuple[int, int] = (1200, 1600),
) -> tuple[np.ndarray, PerspectiveView]:
    """Deterministic rectification: a pinhole view sharing the camera's own orientation.

    Returns (image, view). `view` bearings are relative to the camera (yaw 0 = optical axis).
    """
    w, h = out_size
    view = PerspectiveView(yaw_deg=0.0, pitch_deg=0.0, hfov_deg=hfov_deg, width=w, height=h)
    intr0 = dataclasses.replace(intr, pose_convention=(1, 1), cam_rot_delta_deg={})
    return render_perspective(image, intr0, _IDENTITY_POSE, view), view


# --------------------------------------------------------------------------- masks + selection


@functools.lru_cache(maxsize=64)
def _theta_d_limit(k1: float, k2: float, k3: float, k4: float, max_theta_deg: float) -> float:
    """Largest normalised radius theta_d that is inside max_theta and where KB4 is invertible."""
    theta = np.linspace(0.0, math.radians(max_theta_deg), 20001)
    t2 = theta * theta
    theta_d = theta * (1 + t2 * (k1 + t2 * (k2 + t2 * (k3 + t2 * k4))))
    dtd = 1 + t2 * (3 * k1 + t2 * (5 * k2 + t2 * (7 * k3 + t2 * 9 * k4)))
    bad = np.nonzero(dtd <= 0)[0]
    last = bad[0] - 1 if bad.size else len(theta) - 1
    return float(theta_d[max(last, 0)])


def lens_mask(intr: Intrinsics) -> np.ndarray:
    """Pixels inside the fitted lens circle (theta <= max_theta and KB4 invertible)."""
    lim = _theta_d_limit(intr.k1, intr.k2, intr.k3, intr.k4, intr.max_theta_deg)
    mx = ((np.arange(intr.width, dtype=np.float32) - intr.cx) / intr.fx) ** 2
    my = ((np.arange(intr.height, dtype=np.float32) - intr.cy) / intr.fy) ** 2
    return (my[:, None] + mx[None, :]) <= np.float32(lim * lim)


def valid_mask(
    intr: Intrinsics,
    pose: Mapping[str, Any] | None = None,
    hood_elev_deg: float = -35.0,
    cam_k: int | None = None,
    step: int = 8,
) -> np.ndarray:
    """Boolean mask of usable pixels: inside the lens circle and (if pose) above the hood.

    The lens term is an exact radius test; the pose-dependent hood term is evaluated on a
    `step`-pixel grid and upsampled (nearest), so a full 3648x5472 mask stays cheap.
    """
    ok = lens_mask(intr)
    if pose is not None:
        us = np.arange(0, intr.width, step, dtype=np.float64) + (step - 1) / 2.0
        vs = np.arange(0, intr.height, step, dtype=np.float64) + (step - 1) / 2.0
        u, v = np.meshgrid(np.minimum(us, intr.width - 1), np.minimum(vs, intr.height - 1))
        _, el = pixel_to_bearing(intr, pose, u, v, cam_k)
        coarse = (el > hood_elev_deg).astype(np.uint8)
        full = cv2.resize(coarse, (len(us) * step, len(vs) * step), interpolation=cv2.INTER_NEAREST)
        ok &= full[: intr.height, : intr.width].astype(bool)
    return ok


def privacy_blob_mask(
    image: np.ndarray, thresh: int = 8, min_area_frac: float = 2e-5
) -> np.ndarray:
    """True where the pixel is NOT inside a solid-black privacy blob (value < thresh)."""
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    dark = (gray < thresh).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(dark, connectivity=8)
    min_area = max(16, int(min_area_frac * gray.size))
    blob = np.zeros(gray.shape, bool)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= min_area:
            blob |= labels == i
    if blob.any():
        blob = cv2.dilate(blob.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    return ~blob


def textured_mask(image: np.ndarray, ksize: int = 31, min_std: float = 4.0) -> np.ndarray:
    """True where local intensity std-dev >= min_std (drops flat sky / blown-out regions)."""
    gray = (image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)).astype(
        np.float32
    )
    mean = cv2.blur(gray, (ksize, ksize))
    sq = cv2.blur(gray * gray, (ksize, ksize))
    return np.sqrt(np.maximum(sq - mean * mean, 0.0)) >= min_std


def _row_get(row: Any, key: str):
    return row.get(key) if isinstance(row, Mapping) else getattr(row, key)


def rank_cameras_for_target(
    pano_rows: Sequence[Any],
    lat: float,
    lng: float,
    max_abs_pitch: float = 45.0,
    intr: Intrinsics | None = None,
) -> list[Any]:
    """Return horizontal cameras of one pano ranked by heading facing (lat, lng)."""
    candidates = []
    for row in pano_rows:
        k = camera_index(_row_get(row, "observation_id"))
        pose = _row_get(row, "camera_pose")
        if k is None or not is_ground_camera(k) or abs(_pose_get(pose, "pitch")) > max_abs_pitch:
            continue
        heading = _pose_get(pose, "heading")
        if intr is not None and k in intr.cam_rot_delta_deg:
            heading += intr.cam_rot_delta_deg[k][0]
        b = geo.bearing_deg(_pose_get(pose, "latitude"), _pose_get(pose, "longitude"), lat, lng)
        key = (round(abs(float(geo.angdiff(heading, b))), 6), abs(_pose_get(pose, "pitch")))
        candidates.append((key, row))
    candidates.sort(key=lambda x: x[0])
    return [c[1] for c in candidates]


def select_camera_for_target(
    pano_rows: Sequence[Any],
    lat: float,
    lng: float,
    max_abs_pitch: float = 45.0,
    intr: Intrinsics | None = None,
):
    ranked = rank_cameras_for_target(pano_rows, lat, lng, max_abs_pitch, intr)
    return ranked[0] if ranked else None


def frame_edge_theta_deg(intr: Intrinsics) -> float:
    """Off-axis angle (deg) of the farthest frame-edge midpoint (left/right/top/bottom).

    The lens images the whole sensor, so a fitted `max_theta_deg` should reach at least the
    edge midpoints; limited to where the KB4 model is invertible."""
    r_d = max(
        max(intr.cx, intr.width - 1 - intr.cx) / intr.fx,
        max(intr.cy, intr.height - 1 - intr.cy) / intr.fy,
    )
    lim = _theta_d_limit(intr.k1, intr.k2, intr.k3, intr.k4, 110.0)
    theta = _theta_from_theta_d(intr, np.array([min(r_d, lim)]))
    return float(np.degrees(theta[0]))


# --------------------------------------------------------------------------- field of view


def _invertible_theta_deg(intr: Intrinsics, search_deg: float = 110.0) -> float:
    """Largest incidence angle (deg) up to which the KB4 polynomial is monotonic."""
    lim = _theta_d_limit(intr.k1, intr.k2, intr.k3, intr.k4, search_deg)
    return float(np.degrees(_theta_from_theta_d(intr, np.array([lim]))[0]))


def sensor_edge_theta_deg(intr: Intrinsics) -> dict[str, float]:
    """Incidence angle (deg) at the midpoint of each sensor edge, capped by `max_theta_deg`
    and by the KB4 invertibility limit.

    The principal point is not centred, so the left and right limits differ: a view turned
    towards the nearer edge runs out of sensor sooner. Use these (or `max_view_fov`) instead
    of a single symmetric half-FOV."""
    cap = min(intr.max_theta_deg, _invertible_theta_deg(intr))
    lim = _theta_d_limit(intr.k1, intr.k2, intr.k3, intr.k4, 110.0)
    mids = {
        "left": (0.0, intr.cy),
        "right": (intr.width - 1.0, intr.cy),
        "top": (intr.cx, 0.0),
        "bottom": (intr.cx, intr.height - 1.0),
    }
    out = {}
    for side, (u, v) in mids.items():
        r_d = math.hypot((u - intr.cx) / intr.fx, (v - intr.cy) / intr.fy)
        theta = _theta_from_theta_d(intr, np.array([min(r_d, lim)]))[0]
        out[side] = float(min(cap, math.degrees(theta)))
    return out


def _view_grid(view: PerspectiveView, step: int, max_row: int | None = None):
    h = view.height if max_row is None else max(1, min(int(max_row), view.height))
    us = np.minimum(np.arange(0, view.width, step, dtype=np.float64) + (step - 1) / 2.0,
                    view.width - 1)  # fmt: skip
    vs = np.minimum(np.arange(0, h, step, dtype=np.float64) + (step - 1) / 2.0,
                    h - 1)  # fmt: skip
    return np.meshgrid(us, vs)


def view_black_fraction(
    intr: Intrinsics,
    pose: Mapping[str, Any],
    view: PerspectiveView,
    cam_k: int | None = None,
    step: int = 4,
    max_row: int | None = None,
) -> float:
    """Analytic share of `view` pixels that `render_perspective` leaves black: rays beyond
    `max_theta_deg` (or the KB4 invertibility limit) or that land outside the sensor.
    Evaluated on a `step`-pixel grid of the view (rows above `max_row` only, i.e. the image
    that remains after cropping to `[:max_row]`); no image needed.

    This is sensor coverage only: it does not count pixels the dataset itself redacted
    (black privacy blobs inside the frame), which are image content."""
    u, v = _view_grid(view, max(1, int(step)), max_row)
    theta, ok = _coverage(intr, pose, view, cam_k, u, v)
    return float(np.mean(~ok))


def _coverage(intr, pose, view, cam_k, u, v):
    """(incidence angle deg, covered) of view pixels (u, v) in one camera: covered rays are
    within `max_theta_deg` and the KB4 invertibility limit and land on the sensor."""
    d_cam = view.pixel_dirs(u, v) @ pose_rotation(intr, pose, cam_k)
    theta = np.degrees(np.arccos(np.clip(d_cam[..., 2], -1.0, 1.0)))
    uv = project(intr, d_cam)
    cap = min(intr.max_theta_deg, _invertible_theta_deg(intr))
    ok = (
        (theta <= cap)
        & (uv[..., 0] >= 0)
        & (uv[..., 0] <= intr.width - 1)
        & (uv[..., 1] >= 0)
        & (uv[..., 1] <= intr.height - 1)
    )
    return theta, ok


def vfov_for(hfov_deg: float, aspect: float) -> float:
    """Vertical FOV (deg) of a pinhole view with horizontal FOV `hfov_deg`, aspect = w / h."""
    return float(np.degrees(2 * math.atan(math.tan(math.radians(hfov_deg) / 2) / aspect)))


FOV_EVAL_WIDTH = 96  # grid used by max_view_fov (the black fraction is resolution-independent)
FOV_SAFETY = 0.8  # aim below max_black so a full-resolution render stays under it


def max_view_fov(
    intr: Intrinsics,
    pose: Mapping[str, Any],
    cam_k: int | None,
    yaw_deg: float,
    pitch_deg: float,
    aspect: float,
    max_black: float = 0.01,
    hfov_cap: float = 90.0,
    min_hfov: float = 1.0,
    iters: int = 12,
) -> tuple[float, float]:
    """Widest (hfov, vfov) of a view centred at (yaw, pitch) whose black share is below
    `max_black`, found by bisection on the analytic `view_black_fraction`.

    Returns (0.0, 0.0) if even `min_hfov` is not valid (the target is outside this camera)."""

    def black(view: PerspectiveView) -> float:
        return view_black_fraction(intr, pose, view, cam_k, step=1)

    return _widest_view(black, yaw_deg, pitch_deg, aspect, max_black, hfov_cap, min_hfov, iters)


def _widest_view(black_of, yaw_deg, pitch_deg, aspect, max_black, hfov_cap, min_hfov, iters):
    """Bisection on hfov for the widest view whose `black_of(view)` is below the target."""
    w = FOV_EVAL_WIDTH
    h = max(8, int(round(w / aspect)))
    target = max_black * FOV_SAFETY

    def black(hfov: float) -> float:
        return black_of(PerspectiveView(float(yaw_deg), float(pitch_deg), float(hfov), w, h))

    if black(hfov_cap) <= target:
        return float(hfov_cap), vfov_for(hfov_cap, aspect)
    if black(min_hfov) > target:
        return 0.0, 0.0
    lo, hi = float(min_hfov), float(hfov_cap)
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        if black(mid) <= target:
            lo = mid
        else:
            hi = mid
    return lo, vfov_for(lo, aspect)


@dataclasses.dataclass(frozen=True)
class CameraChoice:
    row: Any
    cam_k: int
    hfov_deg: float
    vfov_deg: float


def best_camera_for_view(
    pano_rows: Sequence[Any],
    intr: Intrinsics,
    yaw_deg: float,
    pitch_deg: float,
    aspect: float,
    min_hfov: float,
    max_black: float = 0.01,
    hfov_cap: float = 90.0,
) -> CameraChoice | None:
    """The ground camera of one pano that can render the widest valid view at (yaw, pitch).

    Every ground camera is checked with `max_view_fov`, so a target near the seam between two
    cameras is rendered from whichever camera actually covers it. None if no camera reaches
    `min_hfov`."""
    best: CameraChoice | None = None
    for row in pano_rows:
        k = camera_index(_row_get(row, "observation_id"))
        if k is None or not is_ground_camera(k):
            continue
        hfov, vfov = max_view_fov(
            intr, _row_get(row, "camera_pose"), k, yaw_deg, pitch_deg, aspect,
            max_black=max_black, hfov_cap=hfov_cap,
        )  # fmt: skip
        if hfov >= min_hfov and (best is None or hfov > best.hfov_deg):
            best = CameraChoice(row, k, hfov, vfov)
    return best


# Elevation (deg, camera frame) below which the capture vehicle's body fills the ground views.
HOOD_ELEV_DEG = -40.0


def hood_row(
    view: PerspectiveView,
    pose: Mapping[str, Any],
    intr: Intrinsics,
    hood_elev_deg: float = HOOD_ELEV_DEG,
    cam_k: int | None = None,
) -> int:
    """First row of `view` (centre column) whose ray points below `hood_elev_deg` in the
    camera frame of (`pose`, `cam_k`), i.e. onto the vehicle; `view.height` if none does.
    Rows from here down show the vehicle, not the road, and should be cropped away."""
    vs = np.arange(view.height, dtype=np.float64)
    d_cam = view.pixel_dirs(np.full_like(vs, view.cx), vs) @ pose_rotation(intr, pose, cam_k)
    el = np.degrees(np.arcsin(np.clip(-d_cam[..., 1], -1.0, 1.0)))
    below = np.nonzero(el < hood_elev_deg)[0]
    return int(below[0]) if below.size else int(view.height)


# --------------------------------------------------------------------------- multi-camera views
# A view centred on the seam between two cameras (on the real rosette the travel direction is
# such a seam) is composited: every view pixel is taken from the covering camera whose optical
# axis is nearest to it. The seam is hard (no blending). The two cameras flanking the travel
# direction sit on the rosette circle (radius 0.084 m) at +-30 deg, 0.084 m apart across the
# seam, so a point is seen from slightly different directions: `seam_parallax_px`. In a 70 deg
# 1024 px road view pitched -22 deg (f = 731 px) the step is 16.6 px for the ground at the
# hood-crop row (-40 deg, 3.9 m slant range), 8.4 px for the ground at -20 deg, and 3.3 / 1.3 px
# for objects 20 / 50 m away near the horizon (tests/test_rosette_fov.py).
ROSETTE_RADIUS_M = 0.084


def seam_parallax_px(
    view: PerspectiveView,
    el_deg: float,
    depth_m: float | None = None,
    cam_height_m: float = 2.5,
    radius_m: float = ROSETTE_RADIUS_M,
    half_angle_deg: float = 30.0,
) -> float:
    """Step (view pixels) at a composite seam along `view.yaw_deg` for a point on the seam
    ray at elevation `el_deg`: the point is projected into `view` from the two camera centres
    on the rosette circle at +-`half_angle_deg` from the seam, and the pixel distance returned.
    The point lies at slant range `depth_m`, or on the ground under the ray (camera
    `cam_height_m` up) when `depth_m` is None and the ray points down."""
    e = math.radians(el_deg)
    if depth_m is None:
        if el_deg >= 0:
            raise ValueError("a ray at or above the horizon has no ground point; pass depth_m")
        depth_m = cam_height_m / math.sin(-e)
    yaw = math.radians(view.yaw_deg)
    fwd = np.array([math.sin(yaw), math.cos(yaw)])
    side = np.array([math.cos(yaw), -math.sin(yaw)])
    a = math.radians(half_angle_deg)
    centres = [radius_m * (math.cos(a) * fwd + sgn * math.sin(a) * side) for sgn in (1, -1)]
    mid = (centres[0] + centres[1]) / 2
    p_h = mid + depth_m * math.cos(e) * fwd
    p_z = depth_m * math.sin(e)
    px = []
    for c in centres:
        r = p_h - c
        az = math.degrees(math.atan2(r[0], r[1]))
        el = math.degrees(math.atan2(p_z, math.hypot(r[0], r[1])))
        u, v, _ = view.bearing_to_pixel(az, el)
        px.append((float(u), float(v)))
    return float(math.hypot(px[0][0] - px[1][0], px[0][1] - px[1][1]))


def _ground_rows(rows: Sequence[Any]) -> list[tuple[Any, int]]:
    out = []
    for row in rows:
        k = camera_index(_row_get(row, "observation_id"))
        if k is not None and is_ground_camera(k):
            out.append((row, k))
    return out


def _owners(intr: Intrinsics, rows: Sequence[Any], view: PerspectiveView, u, v):
    """(ground rows, index of the owning camera per pixel or -1 where no camera covers it)."""
    ground = _ground_rows(rows)
    best = np.full(np.shape(u), np.inf)
    owner = np.full(np.shape(u), -1, dtype=np.int64)
    for i, (row, k) in enumerate(ground):
        theta, ok = _coverage(intr, _row_get(row, "camera_pose"), view, k, u, v)
        better = ok & (theta < best)
        best = np.where(better, theta, best)
        owner = np.where(better, i, owner)
    return ground, owner


def view_black_fraction_multi(
    intr: Intrinsics,
    rows: Sequence[Any],
    view: PerspectiveView,
    step: int = 4,
    max_row: int | None = None,
) -> float:
    """Share of `view` pixels (rows above `max_row` when given) that no ground camera in
    `rows` covers (black when composited). Sensor coverage only, like `view_black_fraction`."""
    u, v = _view_grid(view, max(1, int(step)), max_row)
    _, owner = _owners(intr, rows, view, u, v)
    return float(np.mean(owner < 0))


def max_view_fov_multi(
    intr: Intrinsics,
    rows: Sequence[Any],
    yaw_deg: float,
    pitch_deg: float,
    aspect: float,
    max_black: float = 0.01,
    hfov_cap: float = 90.0,
    min_hfov: float = 1.0,
    iters: int = 12,
) -> tuple[float, float]:
    """`max_view_fov` for a view composited from all ground cameras in `rows`."""

    def black(view: PerspectiveView) -> float:
        return view_black_fraction_multi(intr, rows, view, step=1)

    return _widest_view(black, yaw_deg, pitch_deg, aspect, max_black, hfov_cap, min_hfov, iters)


def composite_rows(intr: Intrinsics, rows: Sequence[Any], view: PerspectiveView, step: int = 4):
    """The ground-camera rows that own at least one pixel of the composited `view`."""
    u, v = _view_grid(view, max(1, int(step)))
    ground, owner = _owners(intr, rows, view, u, v)
    used = set(np.unique(owner[owner >= 0]).tolist())
    return tuple(row for i, (row, _) in enumerate(ground) if i in used)


def render_perspective_multi(
    images: Mapping[int, np.ndarray],
    intr: Intrinsics,
    rows: Sequence[Any],
    view: PerspectiveView,
    interpolation: int = cv2.INTER_LINEAR,
) -> np.ndarray:
    """Composite `view` from several frames of one pano; `images` maps cam_k -> frame. Each
    pixel comes from the covering camera nearest its optical axis; uncovered pixels are 0."""
    u, v = np.meshgrid(np.arange(view.width, dtype=np.float64),
                       np.arange(view.height, dtype=np.float64))  # fmt: skip
    ground, owner = _owners(intr, rows, view, u, v)
    out = None
    for i, (row, k) in enumerate(ground):
        mask = owner == i
        if not mask.any():
            continue
        img = images[k]
        part = render_perspective(img, intr, _row_get(row, "camera_pose"), view, k, interpolation)
        if out is None:
            out = np.zeros_like(part)
        out[mask] = part[mask]
    if out is None:
        raise ValueError("no camera in rows covers the view")
    return out
