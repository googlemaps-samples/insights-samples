"""Field-of-view limits of the fitted rosette model (Task 4).

Zero mocks, no imagery: every test uses the tracked `load_intrinsics()` JSON and a synthetic
all-white full-resolution frame, and "measured" black fractions come from the real
`render_perspective` path.
"""

import functools
import time

import numpy as np
import pytest

from svi_geo import rosette

INTR = rosette.load_intrinsics()
CAM_K = 0
POSE = {"heading": 0.0, "pitch": 0.0, "roll": 0.0}
# optical-axis heading of camera CAM_K in the world (pose heading + fitted yaw delta)
AXIS = POSE["heading"] + INTR.cam_rot_delta_deg[CAM_K][0]
ASPECT = 4 / 3
RENDER_W, RENDER_H = 400, 300


@functools.lru_cache(maxsize=1)
def _white():
    return np.full((INTR.height, INTR.width, 3), 255, np.uint8)


def measured_black(view, pose=POSE, cam_k=CAM_K):
    out = rosette.render_perspective(_white(), INTR, pose, view, cam_k)
    return float(np.mean(out[..., 0] == 0))


def _view(off, pitch, hfov, w=RENDER_W, h=RENDER_H):
    return rosette.PerspectiveView(AXIS + off, pitch, hfov, w, h)


# ----------------------------------------------------------------------------- sensor edges


def test_sensor_edge_theta_matches_unproject_at_edge_midpoints():
    e = rosette.sensor_edge_theta_deg(INTR)
    assert set(e) == {"left", "right", "top", "bottom"}

    def theta_at(u, v):
        return float(np.degrees(rosette.theta_of_pixel(INTR, np.array([[u, v]])))[0])

    cap = INTR.max_theta_deg
    assert e["left"] == pytest.approx(min(cap, theta_at(0, INTR.cy)), abs=0.05)
    assert e["right"] == pytest.approx(min(cap, theta_at(INTR.width - 1, INTR.cy)), abs=0.05)
    assert e["top"] == pytest.approx(min(cap, theta_at(INTR.cx, 0)), abs=0.05)
    assert e["bottom"] == pytest.approx(min(cap, theta_at(INTR.cx, INTR.height - 1)), abs=0.05)
    assert all(v <= cap for v in e.values())
    # the principal point is off-centre, so the horizontal edges differ
    assert abs(e["left"] - e["right"]) > 1.0
    assert max(e["left"], e["right"]) < min(e["top"], e["bottom"])  # portrait sensor


# ----------------------------------------------------------------------------- analytic black


@pytest.mark.parametrize("off", [0, 10, 20, 30])
def test_view_black_fraction_agrees_with_rendered_white_frame(off):
    view = _view(off, 0.0, 70.0)
    analytic = rosette.view_black_fraction(INTR, POSE, view, CAM_K, step=4)
    measured = measured_black(view)
    assert analytic == pytest.approx(measured, abs=0.005)
    if off == 30:
        assert measured > 0.05  # the check is not vacuous


# ----------------------------------------------------------------------------- max_view_fov


GRID = [(off, pitch) for off in (-30, -20, -10, 0, 10, 20, 30) for pitch in (-12, 0, 8, 14)]


@pytest.mark.parametrize("off, pitch", GRID)
def test_max_view_fov_is_valid_and_tight(off, pitch):
    hfov, vfov = rosette.max_view_fov(INTR, POSE, CAM_K, AXIS + off, pitch, ASPECT)
    assert hfov > 0 and vfov > 0
    assert measured_black(_view(off, pitch, hfov)) < 0.01
    if hfov < 90.0 - 1e-6:  # cap not hit: 10% wider must show >= 1% black
        assert measured_black(_view(off, pitch, min(1.1 * hfov, 179.0))) >= 0.01


def test_max_view_fov_is_asymmetric_left_right():
    left, _ = rosette.max_view_fov(INTR, POSE, CAM_K, AXIS - 20, 0.0, ASPECT)
    right, _ = rosette.max_view_fov(INTR, POSE, CAM_K, AXIS + 20, 0.0, ASPECT)
    assert abs(left - right) > 1.0


def test_max_view_fov_vfov_follows_aspect():
    hfov, vfov = rosette.max_view_fov(INTR, POSE, CAM_K, AXIS, 0.0, ASPECT)
    assert np.tan(np.radians(vfov) / 2) == pytest.approx(np.tan(np.radians(hfov) / 2) / ASPECT)


def test_max_view_fov_is_fast():
    rosette.max_view_fov(INTR, POSE, CAM_K, AXIS + 10, 8.0, ASPECT)  # warm caches
    t0 = time.perf_counter()
    for off in (-25, 0, 25):
        rosette.max_view_fov(INTR, POSE, CAM_K, AXIS + off, 8.0, ASPECT)
    assert (time.perf_counter() - t0) / 3 < 0.05


# ----------------------------------------------------------------------------- camera choice


def _pano_rows(heading0=0.0):
    """Six ground cameras 60 deg apart plus the sky camera, like a real rosette."""
    rows = []
    for k in range(7):
        pitch = 90.0 if k == rosette.SKY_CAMERA else 0.0
        pose = {"heading": (heading0 + 60.0 * k) % 360, "pitch": pitch, "roll": 0.0,
                "latitude": 48.85, "longitude": 2.35, "altitude": 35.0}  # fmt: skip
        rows.append({"observation_id": f"o1:PANO_{k}:5001ee", "cam_k": k, "camera_pose": pose})
    return rows


def _axis(k, heading0=0.0):
    return heading0 + 60.0 * k + INTR.cam_rot_delta_deg[k][0]


def test_best_camera_is_the_facing_camera_when_on_axis():
    choice = rosette.best_camera_for_view(_pano_rows(), INTR, _axis(1), 0.0, ASPECT, 20.0)
    assert choice is not None and choice.cam_k == 1


def test_best_camera_switches_to_the_adjacent_camera_when_it_is_better():
    rows = _pano_rows()
    # 35 deg right of camera 1 is 25 deg left of camera 2
    yaw = _axis(1) + 35.0
    choice = rosette.best_camera_for_view(rows, INTR, yaw, 0.0, ASPECT, 20.0)
    assert choice is not None and choice.cam_k == 2
    own, _ = rosette.max_view_fov(INTR, rows[1]["camera_pose"], 1, yaw, 0.0, ASPECT)
    assert choice.hfov_deg > own
    assert (
        measured_black(
            rosette.PerspectiveView(yaw, 0.0, choice.hfov_deg, RENDER_W, RENDER_H),
            rows[2]["camera_pose"],
            2,
        )
        < 0.01
    )


def test_best_camera_ignores_the_sky_camera():
    choice = rosette.best_camera_for_view(_pano_rows(), INTR, 0.0, 60.0, ASPECT, 1.0)
    assert choice is None or choice.cam_k != rosette.SKY_CAMERA


def test_best_camera_returns_none_when_no_camera_reaches_min_hfov():
    assert rosette.best_camera_for_view(_pano_rows(), INTR, _axis(1), 0.0, ASPECT, 89.0) is None


# ----------------------------------------------------------------------------- F6 seam parallax
def _explicit_seam_step_px(view, el_deg, depth_m, cam_h=2.5, radius=0.084, half_angle=30.0):
    """Two camera centres on the rosette circle at +-half_angle from the seam direction (+y);
    a point on the seam ray at `depth_m` slant range (or on the ground) projected into the
    view from both centres: the pixel distance is the step at the seam."""
    a = np.radians(half_angle)
    c1, c2 = (
        np.array([radius * np.sin(a), radius * np.cos(a), 0.0]),
        np.array([-radius * np.sin(a), radius * np.cos(a), 0.0]),
    )
    mid = (c1 + c2) / 2
    e = np.radians(el_deg)
    d = np.array([0.0, np.cos(e), np.sin(e)])
    s = depth_m if depth_m is not None else cam_h / -np.sin(e)
    p = mid + s * d
    px = []
    for c in (c1, c2):
        r = p - c
        az = np.degrees(np.arctan2(r[0], r[1]))
        el = np.degrees(np.arctan2(r[2], np.hypot(r[0], r[1])))
        u, v, ok = view.bearing_to_pixel(az, el)
        assert bool(ok)
        px.append((float(u), float(v)))
    return float(np.hypot(px[0][0] - px[1][0], px[0][1] - px[1][1]))


def test_seam_parallax_matches_explicit_reprojection_and_the_documented_range():
    view = rosette.PerspectiveView(0.0, -22.0, 70.0, 1024, 768)  # f ~ 731 px
    near = rosette.seam_parallax_px(view, rosette.HOOD_ELEV_DEG)  # ground at the hood crop
    assert near == pytest.approx(_explicit_seam_step_px(view, -40.0, None), rel=0.05)
    assert 14.0 <= near <= 18.0  # ~16 px, as documented
    for depth in (20.0, 50.0):  # objects near the horizon
        far = rosette.seam_parallax_px(view, 0.0, depth_m=depth)
        assert far == pytest.approx(_explicit_seam_step_px(view, 0.0, depth), rel=0.05)
        assert 1.0 <= far <= 3.5
