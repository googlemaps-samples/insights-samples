import dataclasses
import math

import cv2
import numpy as np
import pytest

from svi_geo import geo, rosette
from svi_geo.rosette import Intrinsics, PerspectiveView

# ---------------------------------------------------------------- 2a: IDs and intrinsics


def test_camera_index_parses_observation_id():
    assert rosette.camera_index("o1:pH6Vw35Syoz67z7D4AyaXg_3:5001ee") == 3
    assert rosette.camera_index("o1:---zLYmNYEHVW4MKF1YhYA_0:5001ee") == 0
    assert rosette.pano_id_from_observation("o1:pH6Vw35Syoz67z7D4AyaXg_3:5001ee") == (
        "pH6Vw35Syoz67z7D4AyaXg"
    )


@pytest.mark.parametrize("bad", ["", "o1:abc:5001ee", "o1:abc_12:5001ee", "x1:abc_3:5001ee", None])
def test_camera_index_malformed_is_none(bad):
    assert rosette.camera_index(bad) is None


def test_is_ground_camera():
    assert all(rosette.is_ground_camera(k) for k in range(6))
    assert rosette.is_ground_camera(6) is False


def test_intrinsics_json_round_trip(tmp_path):
    intr = dataclasses.replace(
        rosette.DEFAULT_INTRINSICS,
        k1=0.01,
        cam_rot_delta_deg={0: [0.1, -0.2, 0.0], 3: [0.0, 0.05, 0.3]},
        source_snapshots=["a", "b"],
    )
    p = tmp_path / "i.json"
    intr.save(p)
    back = Intrinsics.load(p)
    assert back == intr
    assert back.cam_rot_delta_deg[3] == [0.0, 0.05, 0.3]
    assert rosette.DEFAULT_INTRINSICS.fitted is False


def test_intrinsics_scaled():
    s = rosette.DEFAULT_INTRINSICS.scaled(0.5)
    assert s.width == 1824 and s.height == 2736
    assert s.fx == pytest.approx(rosette.DEFAULT_INTRINSICS.fx / 2)
    assert s.cx == pytest.approx((rosette.DEFAULT_INTRINSICS.cx + 0.5) / 2 - 0.5)


# ---------------------------------------------------------------- 2b: projection math

INTR_K = Intrinsics(
    width=3648,
    height=5472,
    fx=1800.0,
    fy=1800.0,
    cx=1824.0,
    cy=2900.0,
    k1=0.02,
    k2=-0.01,
    k3=0.0,
    k4=0.0,
    max_theta_deg=100.0,
)


def _pose(heading=0.0, pitch=0.0, roll=0.0, lat=48.8, lng=2.37):
    return {
        "heading": heading,
        "pitch": pitch,
        "roll": roll,
        "latitude": lat,
        "longitude": lng,
        "altitude": 50.0,
    }


def test_principal_point_maps_to_camera_heading_and_pitch():
    for intr in (rosette.DEFAULT_INTRINSICS, INTR_K):
        az, el = rosette.pixel_to_bearing(intr, _pose(123.0, 7.0, 1.5), intr.cx, intr.cy)
        assert float(az) == pytest.approx(123.0, abs=1e-9)
        assert float(el) == pytest.approx(7.0, abs=1e-9)


@pytest.mark.parametrize("intr", [rosette.DEFAULT_INTRINSICS, INTR_K])
def test_unproject_project_round_trip(intr):
    rng = np.random.default_rng(1)
    theta = rng.uniform(0, math.radians(95), 500)
    phi = rng.uniform(-math.pi, math.pi, 500)
    d = np.stack([np.sin(theta) * np.cos(phi), np.sin(theta) * np.sin(phi), np.cos(theta)], 1)
    uv = rosette.project(intr, d)
    d2 = rosette.unproject(intr, uv)
    np.testing.assert_allclose(d2, d, atol=1e-9)


def test_image_axis_orientation():
    pose = _pose(90.0, 0.0, 0.0)
    intr = INTR_K
    az_r, _ = rosette.pixel_to_bearing(intr, pose, intr.cx + 300, intr.cy)
    az_l, _ = rosette.pixel_to_bearing(intr, pose, intr.cx - 300, intr.cy)
    _, el_d = rosette.pixel_to_bearing(intr, pose, intr.cx, intr.cy + 300)
    assert geo.angdiff(90.0, az_r) > 0  # right of centre = clockwise
    assert geo.angdiff(90.0, az_l) < 0
    assert el_d < 0  # v grows downward


def test_bearing_pixel_round_trip_grid():
    pose = _pose(-64.9, -9.5, 1.2)
    intr = INTR_K
    u, v = np.meshgrid(np.linspace(400, 3200, 9), np.linspace(600, 5000, 9))
    az, el = rosette.pixel_to_bearing(intr, pose, u, v)
    u2, v2, ok = rosette.bearing_to_pixel(intr, pose, az, el)
    assert ok.all()
    np.testing.assert_allclose(u2, u, atol=1e-6)
    np.testing.assert_allclose(v2, v, atol=1e-6)


def test_wrap_350_plus_20():
    pose = _pose(350.0, 0.0, 0.0)
    intr = rosette.DEFAULT_INTRINSICS
    u, v, ok = rosette.bearing_to_pixel(intr, pose, 10.0, 0.0)
    assert ok
    assert u == pytest.approx(intr.cx + intr.fx * math.radians(20.0), abs=1e-6)
    az, _ = rosette.pixel_to_bearing(intr, pose, u, v)
    assert float(az) == pytest.approx(10.0, abs=1e-9)


def test_agrees_with_cv2_fisheye():
    intr = INTR_K
    rng = np.random.default_rng(2)
    pts = rng.uniform([-5, -5, 1], [5, 5, 10], size=(200, 3))
    K = np.array([[intr.fx, 0, intr.cx], [0, intr.fy, intr.cy], [0, 0, 1]])
    D = np.array([intr.k1, intr.k2, intr.k3, intr.k4])
    cv_uv, _ = cv2.fisheye.projectPoints(pts.reshape(-1, 1, 3), np.zeros(3), np.zeros(3), K, D)
    ours = rosette.project(intr, pts)
    np.testing.assert_allclose(ours, cv_uv.reshape(-1, 2), atol=1e-6)


def test_camera_center_is_the_pose_position():
    """camera_pose lat/lng/alt are already per-camera (measured ~0.08 m from the pano centre
    along each camera's heading), so no rosette offset is added by default."""
    pose = _pose(90.0, 0.0, 0.0)
    c = rosette.camera_center_enu(pose, ref=(48.8, 2.37, 50.0))
    np.testing.assert_allclose(c, [0.0, 0.0, 0.0], atol=1e-6)
    c = rosette.camera_center_enu(pose, ref=(48.8, 2.37, 50.0), extra_offset_m=0.12)
    np.testing.assert_allclose(c, [0.12, 0.0, 0.0], atol=1e-6)


# ---------------------------------------------------------------- 2c: render_perspective / undistort


def _small_intr():
    return INTR_K.scaled(0.25)


def _render_world_checkerboard(intr, pose, square_m=0.5, dist_m=4.0, n_squares=8):
    """Fisheye image of a finite vertical checkerboard (white margin) in front of the camera.

    3x3 supersampled so edges are anti-aliased.
    """
    h, w = intr.height, intr.width
    R = rosette.cam_rotation(pose["heading"], pose["pitch"], pose["roll"])
    fwd, right, down = R[:, 2], R[:, 0], R[:, 1]
    acc = np.zeros(h * w)
    offs = (-1 / 3, 0.0, 1 / 3)
    for dy in offs:
        for dx in offs:
            u, v = np.meshgrid(np.arange(w) + dx, np.arange(h) + dy)
            d = rosette.unproject(intr, np.stack([u.ravel(), v.ravel()], 1))
            dw = d @ R.T
            t = dist_m / np.clip(dw @ fwd, 1e-9, None)
            p = dw * t[:, None]
            a = np.floor(p @ right / square_m).astype(int)
            b = np.floor(p @ down / square_m).astype(int)
            half = n_squares // 2
            on_board = (a >= -half) & (a < half) & (b >= -half) & (b < half) & (dw @ fwd > 0.2)
            black = on_board & ((a + b) % 2 == 0)
            acc += np.where(black, 0.0, 255.0)
    return (acc / 9.0).round().astype(np.uint8).reshape(h, w)


def test_undistort_makes_lines_straight():
    intr = _small_intr()
    pose = _pose(0.0, 0.0, 0.0)
    img = _render_world_checkerboard(intr, pose)
    und, view = rosette.undistort(img, intr, hfov_deg=70.0, out_size=(900, 900))
    assert isinstance(view, PerspectiveView)
    found, corners = cv2.findChessboardCornersSB(und, (7, 7))
    assert found
    grid = corners.reshape(7, 7, 2)
    worst = 0.0
    for line in list(grid) + list(grid.transpose(1, 0, 2)):
        x, y = line[:, 0], line[:, 1]
        A = np.stack([x, y, np.ones_like(x)], 1)
        _, _, vt = np.linalg.svd(A - A.mean(0) * [1, 1, 0])
        n = vt[-1, :2] / np.linalg.norm(vt[-1, :2])
        resid = (np.stack([x, y], 1) - [x.mean(), y.mean()]) @ n
        worst = max(worst, float(np.abs(resid).max()))
    assert worst < 1.0


def test_render_perspective_point_lands_at_predicted_pixel():
    intr = _small_intr()
    pose = _pose(0.0, 5.0, 1.0)
    img = np.zeros((intr.height, intr.width), np.uint8)
    u, v, ok = rosette.bearing_to_pixel(intr, pose, 30.0, 0.0)
    assert ok
    cv2.circle(img, (int(round(float(u))), int(round(float(v)))), 3, 255, -1)
    # sub-pixel target: re-derive the bearing of the painted centre
    az, el = rosette.pixel_to_bearing(intr, pose, round(float(u)), round(float(v)))
    view = PerspectiveView(yaw_deg=20.0, pitch_deg=0.0, hfov_deg=60.0, width=800, height=600)
    out = rosette.render_perspective(img, intr, pose, view)
    ys, xs = np.nonzero(out > 64)
    w = out[ys, xs].astype(float)
    cx, cy = (xs * w).sum() / w.sum(), (ys * w).sum() / w.sum()
    pu, pv, pok = view.bearing_to_pixel(az, el)
    assert pok
    assert abs(cx - pu) < 1.0 and abs(cy - pv) < 1.0
    # and back
    baz, bel = view.pixel_to_bearing(pu, pv)
    assert float(geo.angdiff(az, baz)) == pytest.approx(0.0, abs=1e-9)
    assert float(bel) == pytest.approx(float(el), abs=1e-9)


# ---------------------------------------------------------------- 2d: masks + camera selection


def test_valid_mask_corners_false_centre_true():
    intr = _small_intr()
    m = rosette.valid_mask(intr)
    assert m.shape == (intr.height, intr.width)
    assert not m[0, 0] and not m[0, -1] and not m[-1, 0] and not m[-1, -1]
    assert m[intr.height // 2, intr.width // 2]


def test_valid_mask_with_pose_excludes_hood():
    intr = _small_intr()
    m = rosette.valid_mask(intr, _pose(0.0, 0.0, 0.0), hood_elev_deg=-35.0)
    assert not m[-2, intr.width // 2]
    assert m[intr.height // 2, intr.width // 2]


def _dense_valid_mask(intr, pose, hood):
    u, v = np.meshgrid(np.arange(intr.width, dtype=float), np.arange(intr.height, dtype=float))
    d = rosette.unproject(intr, np.stack([u, v], -1))
    theta = np.degrees(np.arccos(np.clip(d[..., 2], -1, 1)))
    _, el = rosette.dir_to_bearing(d @ rosette.pose_rotation(intr, pose).T)
    return (theta <= intr.max_theta_deg) & (el > hood)


def test_fast_valid_mask_matches_dense():
    intr = _small_intr()
    pose = _pose(0.0, 8.0, 1.0)
    fast = rosette.valid_mask(intr, pose, hood_elev_deg=-35.0, step=4)
    dense = _dense_valid_mask(intr, pose, -35.0)
    assert (fast == dense).mean() > 0.995


def test_valid_mask_full_resolution_is_cheap():
    import time

    t = time.perf_counter()
    m = rosette.valid_mask(rosette.DEFAULT_INTRINSICS, _pose(0.0, 8.0, 0.0))
    assert m.shape == (5472, 3648)
    assert time.perf_counter() - t < 3.0


def test_privacy_blob_and_texture_masks():
    rng = np.random.default_rng(0)
    img = rng.integers(40, 220, size=(200, 300), dtype=np.uint8)
    img[50:90, 100:160] = 0  # privacy blob
    img[:30, :] = 180  # flat "sky"
    pm = rosette.privacy_blob_mask(img)
    assert not pm[70, 130] and pm[150, 50]
    tm = rosette.textured_mask(img, ksize=9)
    assert not tm[5, 150] and tm[150, 150]


def test_bearing_to_pixel_hood_cut():
    intr = INTR_K
    pose = _pose(0.0, 0.0, 0.0)
    _, _, ok = rosette.bearing_to_pixel(intr, pose, 0.0, -50.0)
    assert ok
    _, _, ok = rosette.bearing_to_pixel(intr, pose, 0.0, -50.0, hood_elev_deg=-35.0)
    assert not ok


def test_select_camera_uses_fitted_yaw_delta():
    rows = _pano_rows([60, 120, 180, -120, -60, 0])
    lat, lng, _ = geo.enu_to_lla(
        30 * math.sin(math.radians(95)), 30 * math.cos(math.radians(95)), 0, 48.8, 2.37
    )
    assert rows.index(rosette.select_camera_for_target(rows, lat, lng)) == 1
    intr = dataclasses.replace(INTR_K, cam_rot_delta_deg={1: [20.0, 0, 0]})
    assert rows.index(rosette.select_camera_for_target(rows, lat, lng, intr=intr)) == 0


def _pano_rows(headings, pitches=None, lat=48.8, lng=2.37):
    pitches = pitches or [9, -9, 9, -9, 9, -9]
    rows = [
        {
            "observation_id": f"o1:PANO_{k}:5001ee",
            "camera_pose": _pose(h, p, 0.0, lat, lng),
        }
        for k, (h, p) in enumerate(zip(headings, pitches, strict=True))
    ]
    rows.append(
        {"observation_id": "o1:PANO_6:5001ee", "camera_pose": _pose(90.0, 87.0, 0.0, lat, lng)}
    )
    return rows


HEADINGS = [55, 115, 175, -125, -65, -5]


def test_select_camera_for_target_east_and_west():
    rows = _pano_rows(HEADINGS)
    lat_e, lng_e, _ = geo.enu_to_lla(30.0, 0.0, 0.0, 48.8, 2.37)
    lat_w, lng_w, _ = geo.enu_to_lla(-30.0, 0.0, 0.0, 48.8, 2.37)
    assert rows.index(rosette.select_camera_for_target(rows, lat_e, lng_e)) == 1
    assert rows.index(rosette.select_camera_for_target(rows, lat_w, lng_w)) == 4


def test_select_camera_never_picks_sky_camera():
    rows = _pano_rows(HEADINGS)
    for bearing in range(0, 360, 15):
        lat, lng, _ = geo.enu_to_lla(
            30 * math.sin(math.radians(bearing)),
            30 * math.cos(math.radians(bearing)),
            0,
            48.8,
            2.37,
        )
        chosen = rosette.select_camera_for_target(rows, lat, lng)
        assert rosette.camera_index(chosen["observation_id"]) != 6


def test_select_camera_tie_breaks_on_pitch():
    rows = _pano_rows([90, 90, 175, -125, -65, -5], pitches=[9, -2, 9, -9, 9, -9])
    lat, lng, _ = geo.enu_to_lla(30.0, 0.0, 0.0, 48.8, 2.37)
    assert rows.index(rosette.select_camera_for_target(rows, lat, lng)) == 1


def test_shipped_intrinsics_cover_the_frame():
    """Regression: max_theta_deg must be in degrees (a radians value masked every pixel)."""
    intr = rosette.load_intrinsics()
    corners = np.array([[0.0, 0.0], [intr.width - 1.0, 0.0], [0.0, intr.height - 1.0]])
    edge_mid = np.array([[0.0, intr.height / 2.0], [intr.width - 1.0, intr.height / 2.0]])
    assert intr.max_theta_deg > 45.0
    theta_edges = np.degrees(rosette.theta_of_pixel(intr, edge_mid))
    assert np.all(theta_edges < intr.max_theta_deg)  # left/right frame edges are usable
    assert np.degrees(rosette.theta_of_pixel(intr, corners)).max() > 30.0
    assert rosette.lens_mask(intr).mean() > 0.9


def test_frame_edge_theta_is_a_plausible_half_fov():
    intr = rosette.load_intrinsics()  # fitted model shipped with the package
    th = rosette.frame_edge_theta_deg(intr)
    assert 40.0 < th < 90.0
    top = np.array([[intr.cx, 0.0]])  # the portrait frame's farthest edge midpoint
    assert abs(np.degrees(rosette.theta_of_pixel(intr, top))[0] - th) < 3.0
    assert intr.max_theta_deg >= th


# ---------------------------------------------------------------- U6: scaled bearing, antialias, equirect strip


def test_scaled_intrinsics_preserve_pixel_to_bearing():
    intr_full = rosette.load_intrinsics()
    intr_half = intr_full.scaled(0.5)
    pose = _pose(115.0, -4.0, 0.8)
    # Compare bearings across a grid of normalized coordinates
    for fx in (0.2, 0.35, 0.5, 0.65, 0.8):
        for fy in (0.2, 0.35, 0.5, 0.65, 0.8):
            u_full = fx * intr_full.width - 0.5
            v_full = fy * intr_full.height - 0.5
            u_half = fx * intr_half.width - 0.5
            v_half = fy * intr_half.height - 0.5
            az1, el1 = rosette.pixel_to_bearing(intr_full, pose, u_full, v_full, cam_k=1)
            az2, el2 = rosette.pixel_to_bearing(intr_half, pose, u_half, v_half, cam_k=1)
            assert abs(float(geo.angdiff(az1, az2))) <= 0.01
            assert abs(float(el1) - float(el2)) <= 0.01


def test_render_has_less_aliasing_energy():
    intr = INTR_K.scaled(0.5)  # 1824 x 2736, fx=900
    pose = _pose(0.0, 0.0, 0.0)
    # Synthetic zone plate / fine radial sinusoid in camera frame with period ~3 source pixels
    u, v = np.meshgrid(
        np.arange(intr.width, dtype=np.float64), np.arange(intr.height, dtype=np.float64)
    )
    r = np.hypot(u - intr.cx, v - intr.cy)
    zone = (127.5 + 127.5 * np.cos(2 * math.pi * r / 3.2)).clip(0, 255).astype(np.uint8)
    zone_bgr = np.stack([zone, zone, zone], axis=-1)

    # Render into a strongly minified 256x192 view (f ~ 183 px -> minification f_src / f_view ~ 4.9)
    view = PerspectiveView(yaw_deg=0.0, pitch_deg=0.0, hfov_deg=70.0, width=256, height=192)
    f_min = rosette.minification_factor(intr, view)
    assert f_min > 2.5

    aliased = rosette.render_perspective(zone_bgr, intr, pose, view, antialias=False)
    antialiased = rosette.render_perspective(zone_bgr, intr, pose, view, antialias=True)

    # Measure high-frequency Laplacian energy (aliased Moiré produces strong high-frequency energy)
    lap_raw = float(np.mean(cv2.Laplacian(aliased[..., 0].astype(np.float32), cv2.CV_32F) ** 2))
    lap_aa = float(np.mean(cv2.Laplacian(antialiased[..., 0].astype(np.float32), cv2.CV_32F) ** 2))
    assert lap_aa <= 0.6 * lap_raw


def test_equirect_strip_yaw_markers_within_half_degree():
    intr = _small_intr()
    headings = [0.0, 60.0, 120.0, 180.0, 240.0, 300.0]
    rows = _pano_rows(headings, pitches=[0.0] * 6)[:6]
    frames6 = {}
    marker_yaws = [30.0, 150.0, 275.0]
    for k, r in enumerate(rows):
        im = np.full((intr.height, intr.width, 3), 30, dtype=np.uint8)
        for myaw in marker_yaws:
            u, v, ok = rosette.bearing_to_pixel(intr, r["camera_pose"], myaw, 0.0, cam_k=k)
            if bool(ok):
                cv2.circle(im, (int(round(float(u))), int(round(float(v)))), 6, (0, 255, 0), -1)
        frames6[k] = im

    strip = rosette.render_equirect_strip(
        frames6, intr, rows, width=1440, pitch_range=(-30.0, 45.0)
    )
    assert strip.shape[1] == 1440 and strip.shape[2] == 3
    # Check each marker yaw lands at column round(myaw / 360 * width) within 0.5 deg (2 px at 1440w)
    green = strip[..., 1].max(axis=0)
    for myaw in marker_yaws:
        expected_col = (myaw / 360.0) * 1440.0
        window = np.arange(1440)
        near = np.abs(((window - expected_col + 720) % 1440) - 720) <= 10
        cols = np.nonzero(near & (green > 180))[0]
        assert cols.size > 0
        peak_col = float(np.mean(cols))
        peak_yaw = (peak_col + 0.5) / 1440.0 * 360.0
        assert abs(float(geo.angdiff(peak_yaw, myaw))) <= 0.5
