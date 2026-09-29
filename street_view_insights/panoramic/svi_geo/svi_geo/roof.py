import dataclasses
import math
from collections.abc import Mapping, Sequence

import cv2
import numpy as np

from svi_geo import geo, rosette


@dataclasses.dataclass
class RoofValidationResult:
    valid_edges: list[list[tuple[float, float]]]
    rejected_edges: list[list[tuple[float, float]]]
    mean_gradient_support: float
    raw_mean_gradient_support: float
    median_angle_residual_deg: float
    floating_sky_edges_count: int
    corner_foldover_rate: float


def render_roof_view(
    image: np.ndarray,
    intr: rosette.Intrinsics,
    camera_pose: Mapping[str, float],
    target_bearing_deg: float,
    cam_k: int,
    pitch_deg: float = 14.0,
    hfov_deg: float = 65.0,
    width: int = 1200,
    height: int = 900,
) -> tuple[np.ndarray, rosette.PerspectiveView]:
    heading = rosette._pose_get(camera_pose, "heading")
    if (
        intr is not None
        and getattr(intr, "cam_rot_delta_deg", None)
        and cam_k in intr.cam_rot_delta_deg
    ):
        heading += intr.cam_rot_delta_deg[cam_k][0]

    off_axis = abs(float(geo.angdiff(heading, target_bearing_deg)))

    max_hfov = 2.0 * (48.9 - off_axis)
    clamped_hfov = max(min(hfov_deg, max_hfov), 10.0)

    view = rosette.PerspectiveView(
        width=width,
        height=height,
        hfov_deg=clamped_hfov,
        yaw_deg=target_bearing_deg,
        pitch_deg=pitch_deg,
        roll_deg=0.0,
    )
    rendered = rosette.render_perspective(image, intr, camera_pose, view, cam_k=cam_k)
    return rendered, view


def point_line_dist(pt, p1, p2):
    n = np.linalg.norm(p2 - p1)
    if n < 1e-6:
        return np.linalg.norm(pt - p1)
    return np.abs((p2[0] - p1[0]) * (p1[1] - pt[1]) - (p2[1] - p1[1]) * (p1[0] - pt[0])) / n


def validate_and_snap_roof_edges(
    image_bgr: np.ndarray,
    roof_edges: Sequence[Sequence[Sequence[float]]],
    snap_tol_px: float = 15.0,
    min_gradient_support: float = 0.75,
    mask_foliage: bool = True,
) -> RoofValidationResult:
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)

    # Foliage (greens)
    lower_green = np.array([35, 40, 40])
    upper_green = np.array([85, 255, 255])
    foliage_mask = cv2.inRange(hsv, lower_green, upper_green)

    # Sky (blue/gray in upper 1/3)
    h_top = image_bgr.shape[0] // 3
    sky_mask = np.zeros(image_bgr.shape[:2], dtype=np.uint8)
    lower_sky = np.array([90, 0, 100])
    upper_sky = np.array([130, 80, 255])
    sky_mask[:h_top, :] = cv2.inRange(hsv[:h_top, :], lower_sky, upper_sky)

    combined_mask = (
        cv2.bitwise_or(foliage_mask, sky_mask) if mask_foliage else np.zeros_like(foliage_mask)
    )

    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    canny = cv2.Canny(gray, 50, 150)

    # Gradient support mask - dilated canny
    element = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (int(snap_tol_px * 2 + 1), int(snap_tol_px * 2 + 1))
    )
    grad_mask = cv2.dilate(canny, element)

    lsd = cv2.createLineSegmentDetector(refine=cv2.LSD_REFINE_STD)
    lines, _, _, _ = lsd.detect(gray)
    cv_segments = []
    if lines is not None:
        for line in lines:
            x1, y1, x2, y2 = line.flatten()[:4]
            cv_segments.append((np.array([x1, y1]), np.array([x2, y2])))

    valid_edges = []
    rejected_edges = []
    grad_supports = []
    raw_grad_supports = []
    floating_count = 0
    ang_residuals = []
    corner_count = 0
    foldover_count = 0

    for poly in roof_edges:
        if len(poly) < 2:
            continue

        poly_valid = True
        poly_snap = []

        for i in range(len(poly) - 1):
            p1 = np.array(poly[i][:2])
            p2 = np.array(poly[i + 1][:2])
            length = max(int(np.linalg.norm(p2 - p1)), 1)
            t = np.linspace(0, 1, length)
            pts = (p1[None, :] * (1 - t)[:, None] + p2[None, :] * t[:, None]).astype(int)
            pts = np.clip(pts, [0, 0], [image_bgr.shape[1] - 1, image_bgr.shape[0] - 1])

            # evaluate support and foliage
            support_pixels = grad_mask[pts[:, 1], pts[:, 0]] > 0
            foliage_pixels = combined_mask[pts[:, 1], pts[:, 0]] > 0

            support_frac = np.mean(support_pixels)
            foliage_frac = np.mean(foliage_pixels)
            raw_grad_supports.append(support_frac)

            if support_frac < min_gradient_support or foliage_frac > 0.55:
                poly_valid = False

            if foliage_frac > 0.55 and np.mean(sky_mask[pts[:, 1], pts[:, 0]]) > 0.2:
                floating_count += 1

            # Snap to nearest collinear LSD segment

            pt_dir = p2 - p1
            pt_dir_norm = np.linalg.norm(pt_dir)
            if pt_dir_norm > 1e-6:
                pt_dir = pt_dir / pt_dir_norm

            for cv_p1, cv_p2 in cv_segments:
                cv_dir = cv_p2 - cv_p1
                cv_dir_norm = np.linalg.norm(cv_dir)
                if cv_dir_norm < 1e-6:
                    continue
                cv_dir = cv_dir / cv_dir_norm

                # Check collinearity
                cos_angle = abs(np.dot(pt_dir, cv_dir))
                if cos_angle > 0.95:  # roughly 18 degrees collinear
                    d1 = point_line_dist(cv_p1, p1, p2)
                    d2 = point_line_dist(cv_p2, p1, p2)
                    if d1 < snap_tol_px and d2 < snap_tol_px:
                        # Angle residual
                        diff_deg = math.degrees(math.acos(min(cos_angle, 1.0)))
                        ang_residuals.append(diff_deg)
                        p1 = cv_p1 + np.dot(p1 - cv_p1, cv_dir) * cv_dir
                        p2 = cv_p1 + np.dot(p2 - cv_p1, cv_dir) * cv_dir
                        break

            poly_snap.append((p1, p2))

            length_snap = max(int(np.linalg.norm(p2 - p1)), 1)
            t_s = np.linspace(0, 1, length_snap)
            pts_s = (p1[None, :] * (1 - t_s)[:, None] + p2[None, :] * t_s[:, None]).astype(int)
            pts_s = np.clip(pts_s, [0, 0], [image_bgr.shape[1] - 1, image_bgr.shape[0] - 1])
            support_pixels_s = grad_mask[pts_s[:, 1], pts_s[:, 0]] > 0
            grad_supports.append(np.mean(support_pixels_s))

            if i > 0:
                corner_count += 1
                # Check for foldover (angle > 170 deg turning back)
                prev_p1 = np.array(poly[i - 1][:2])
                v1 = prev_p1 - p1
                v2 = p2 - p1
                n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
                if n1 > 1e-6 and n2 > 1e-6:
                    dot = np.dot(v1, v2) / (n1 * n2)
                    if dot > 0.9:  # U-turn foldover
                        foldover_count += 1

        if poly_valid:
            # Reconstruct polyline from snapped segments for output
            recon = [poly_snap[0][0].tolist(), poly_snap[0][1].tolist()]
            for j in range(1, len(poly_snap)):
                recon.append(poly_snap[j][1].tolist())
            valid_edges.append(recon)
        else:
            rejected_edges.append(poly)

    mean_sup = float(np.mean(grad_supports)) if grad_supports else 0.0
    raw_mean_sup = float(np.mean(raw_grad_supports)) if raw_grad_supports else 0.0
    med_ang = float(np.median(ang_residuals)) if ang_residuals else 0.0
    fold_rate = foldover_count / max(corner_count, 1)

    return RoofValidationResult(
        valid_edges=valid_edges,
        rejected_edges=rejected_edges,
        mean_gradient_support=mean_sup,
        raw_mean_gradient_support=raw_mean_sup,
        median_angle_residual_deg=med_ang,
        floating_sky_edges_count=floating_count,
        corner_foldover_rate=fold_rate,
    )
