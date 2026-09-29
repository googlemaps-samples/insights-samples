"""Deterministic image features for rosette calibration (OpenCV only, no LLM).

* `frame_mask`: where features may be detected (privacy blur, low texture and hood excluded).
* `detect`: SIFT on a reduced-resolution gray frame, keypoints returned in full-res pixels.
* `ratio_match`: Lowe ratio test (+ optional mutual check).
* `angular_inliers`: keep matches whose world rays agree within a threshold (intra-pano
  baseline is ~0.16 m, so parallax is small beyond a few metres).
* `essential_inliers`: RANSAC essential matrix on unit rays for consecutive panos.
* `edge_chains`: long, junction-free Canny chains as candidate straight lines.
"""

from __future__ import annotations

import dataclasses

import cv2
import numpy as np

from svi_geo import rosette


@dataclasses.dataclass
class Features:
    uv: np.ndarray  # (N, 2) full-resolution pixel coordinates
    desc: np.ndarray  # (N, 128) float32


def frame_mask(gray: np.ndarray, hood_frac: float = 0.20) -> np.ndarray:
    """uint8 mask (255 = usable) at the gray image's resolution."""
    m = rosette.privacy_blob_mask(gray) & rosette.textured_mask(gray)
    h = gray.shape[0]
    if hood_frac > 0:
        m[int((1.0 - hood_frac) * h) :, :] = False
    return m.astype(np.uint8) * 255


def detect(
    gray: np.ndarray, scale: float, mask: np.ndarray | None = None, n: int = 6000
) -> Features:
    """SIFT on `gray` (already reduced by `scale`); coordinates mapped to full resolution."""
    sift = cv2.SIFT_create(nfeatures=n)
    kps, desc = sift.detectAndCompute(gray, mask)
    if desc is None or not kps:
        return Features(np.zeros((0, 2)), np.zeros((0, 128), np.float32))
    pts = np.float64([k.pt for k in kps])
    # pixel-centre convention: full = (reduced + 0.5) / scale - 0.5
    return Features((pts + 0.5) / scale - 0.5, desc.astype(np.float32))


def ratio_match(d1: np.ndarray, d2: np.ndarray, ratio: float = 0.75, mutual: bool = True):
    """Index pairs (i1, i2) passing Lowe's ratio test (and mutual nearest neighbour)."""
    if len(d1) < 2 or len(d2) < 2:
        return np.zeros(0, int), np.zeros(0, int)
    bf = cv2.BFMatcher(cv2.NORM_L2)
    fwd = bf.knnMatch(d1, d2, k=2)
    i1, i2 = [], []
    for pair in fwd:
        if len(pair) == 2 and pair[0].distance < ratio * pair[1].distance:
            i1.append(pair[0].queryIdx)
            i2.append(pair[0].trainIdx)
    i1, i2 = np.array(i1, int), np.array(i2, int)
    if mutual and len(i1):
        back = {m.queryIdx: m.trainIdx for m in bf.match(d2, d1)}
        ok = np.array([back.get(b) == a for a, b in zip(i1, i2, strict=True)])
        i1, i2 = i1[ok], i2[ok]
    return i1, i2


def angle_between_deg(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a = a / np.linalg.norm(a, axis=-1, keepdims=True)
    b = b / np.linalg.norm(b, axis=-1, keepdims=True)
    return np.degrees(np.arctan2(np.linalg.norm(np.cross(a, b), axis=-1), np.sum(a * b, -1)))


def angular_inliers(rays_a: np.ndarray, rays_b: np.ndarray, thr_deg: float) -> np.ndarray:
    """Matches whose world rays point the same way (rotation-only consistency)."""
    return angle_between_deg(rays_a, rays_b) < thr_deg


def essential_inliers(
    rays_a: np.ndarray, rays_b: np.ndarray, thr_deg: float = 0.3, min_z: float = 0.2
) -> np.ndarray:
    """RANSAC essential matrix on camera-frame unit rays (both views must face forward)."""
    ok = (rays_a[:, 2] > min_z) & (rays_b[:, 2] > min_z)
    out = np.zeros(len(rays_a), bool)
    if ok.sum() < 8:
        return out
    pa = rays_a[ok, :2] / rays_a[ok, 2:3]
    pb = rays_b[ok, :2] / rays_b[ok, 2:3]
    _, inl = cv2.findEssentialMat(
        pa, pb, np.eye(3), method=cv2.RANSAC, prob=0.999, threshold=np.radians(thr_deg)
    )
    if inl is None:
        return out
    out[np.nonzero(ok)[0]] = inl.ravel().astype(bool)
    return out


def edge_chains(
    gray: np.ndarray,
    scale: float,
    mask: np.ndarray | None = None,
    min_len_px: int = 250,
    max_points: int = 80,
    canny: tuple[int, int] = (60, 160),
) -> list[np.ndarray]:
    """Junction-free Canny chains with >= `min_len_px` pixels (at the reduced scale).

    Returns full-resolution (M, 2) pixel arrays, subsampled to <= `max_points` points. Whether a
    chain is actually straight is decided later from its rays (it depends on the intrinsics).
    """
    edges = cv2.Canny(gray, *canny)
    if mask is not None:
        edges[mask == 0] = 0
    e = (edges > 0).astype(np.uint8)
    nb = cv2.filter2D(e, -1, np.ones((3, 3), np.float32), borderType=cv2.BORDER_CONSTANT)
    e[(nb - e) >= 3] = 0  # drop junction pixels (>= 3 neighbours) so chains stay simple
    n, labels, stats, _ = cv2.connectedComponentsWithStats(e, connectivity=8)
    out = []
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] < min_len_px:
            continue
        ys, xs = np.nonzero(labels == i)
        order = np.argsort(xs + ys * 1e-6) if np.ptp(xs) >= np.ptp(ys) else np.argsort(ys)
        pts = np.stack([xs[order], ys[order]], -1).astype(np.float64)
        if len(pts) > max_points:
            pts = pts[np.linspace(0, len(pts) - 1, max_points).astype(int)]
        out.append((pts + 0.5) / scale - 0.5)
    return out
