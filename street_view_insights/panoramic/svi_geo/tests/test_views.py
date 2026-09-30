"""UC1 view framing, ranking and house triangulation (pure geometry, zero mocks)."""

import inspect
import math

import numpy as np
import pandas as pd
import pytest

from svi_geo import entities as ent
from svi_geo import geo, rosette, views
from svi_geo import simulate as sim

INTR = rosette.load_intrinsics()


# ----------------------------------------------------------------------------- vertical framing


@pytest.mark.parametrize("d", [8.0, 15.0, 30.0, 45.0])
def test_house_view_pitch_vfov_contains_base_and_top(d):
    pitch, vfov = views.house_view_pitch_vfov(d, cam_h=2.5, house_h=8.0, margin_deg=2.0)
    base = math.degrees(math.atan(-2.5 / d))
    top = math.degrees(math.atan((8.0 - 2.5) / d))
    lo, hi = pitch - vfov / 2, pitch + vfov / 2
    assert lo <= base - 2.0 + 1e-9 and hi >= top + 2.0 - 1e-9
    # and not wastefully tall: the margin is the only slack
    assert (hi - lo) == pytest.approx(top - base + 4.0)


def test_house_view_pitch_vfov_window_matches_a_rendered_view():
    d = 20.0
    pitch, vfov = views.house_view_pitch_vfov(d)
    aspect = 4 / 3
    hfov = views.hfov_for_vfov(vfov, aspect)
    view = rosette.PerspectiveView(0.0, pitch, hfov, 400, 300)
    for el in (math.degrees(math.atan(-2.5 / d)), math.degrees(math.atan(5.5 / d))):
        _, v, ok = view.bearing_to_pixel(0.0, el)
        assert bool(ok) and 0 < float(v) < 299


# ----------------------------------------------------------------------------- ranking


def _cands(rows):
    return pd.DataFrame(rows, columns=["pano_id", "seq_id", "cam_k", "dist_m", "off_axis_deg"])


def test_rank_house_views_orders_by_normalised_distance_plus_off_axis():
    c = _cands(
        [
            ("a", "S0", 1, 10.0, 30.0),  # 10/40 + 30/30 = 1.25
            ("b", "S1", 1, 40.0, 0.0),  # 1.0 + 0 = 1.0
            ("c", "S2", 1, 20.0, 15.0),  # 0.5 + 0.5 = 1.0 -> tie broken by pano id
            ("d", "S3", 1, 12.0, 3.0),  # 0.3 + 0.1 = 0.4
        ]
    )
    out = views.rank_house_views(c, max_per_seq=5)
    assert list(out.pano_id) == ["d", "b", "c", "a"]
    assert out.score.is_monotonic_increasing


def test_rank_house_views_caps_views_per_sequence():
    c = _cands([(f"p{i}", "S0" if i < 4 else "S1", 1, 10.0 + i, 5.0) for i in range(6)])
    out = views.rank_house_views(c, max_per_seq=2)
    assert out.seq_id.value_counts().max() <= 2 and set(out.seq_id) == {"S0", "S1"}


def test_rank_house_views_drops_candidates_without_a_camera():
    c = _cands([("a", "S0", None, 10.0, 5.0), ("b", "S0", 2, 12.0, 5.0)])
    out = views.rank_house_views(c, max_per_seq=5)
    assert list(out.pano_id) == ["b"]


def test_rank_house_views_on_empty_input_keeps_columns():
    out = views.rank_house_views(_cands([]), max_per_seq=2)
    assert out.empty
    for col in ("pano_id", "seq_id", "cam_k", "dist_m", "off_axis_deg", "score"):
        assert col in out.columns


# ----------------------------------------------------------------------------- candidates


def _street(n=12, spacing=8.0):
    fr = sim.synthetic_frames(n, spacing, 48.85, 2.35, travel_deg=0.0)
    fr["gcs_uri"] = "gs://unused/" + fr["observation_id"]
    return fr


def _house_latlng(offset_e=18.0, along_n=45.0):
    lat, lng, _ = geo.enu_to_lla(offset_e, along_n, 0.0, 48.85, 2.35)
    return float(lat), float(lng)


def test_house_view_candidates_frame_the_whole_house_without_black():
    fr = _street()
    lat, lng = _house_latlng()
    cands = views.house_view_candidates(fr, lat, lng, INTR, aspect=4 / 3, max_dist_m=80.0)
    ok = cands[cands.cam_k.notna()]
    assert len(ok) >= 3
    white = np.full((INTR.height, INTR.width, 3), 255, np.uint8)
    for r in ok.to_dict("records"):
        view = views.view_for(r, width=400, height=300)
        out = rosette.render_perspective(white, INTR, r["camera_pose"], view, int(r["cam_k"]))
        assert float(np.mean(out[..., 0] == 0)) < 0.01
        # base and roof line of an 8 m house at the target are both inside the view
        for h in (0.0, 8.0):
            el = math.degrees(math.atan((h - 2.5) / r["dist_m"]))
            _, v, inside = view.bearing_to_pixel(r["bearing"], el)
            assert bool(inside), (r["pano_id"], h)
        # and the house width fits horizontally
        need = 2 * math.degrees(math.atan(14.0 / 2 / r["dist_m"]))
        assert r["hfov"] >= need - 1e-6


def test_house_view_candidates_mark_too_close_panos_as_without_camera():
    fr = _street()
    lat, lng = _house_latlng(offset_e=6.0, along_n=0.0)  # 6 m from the first pano
    cands = views.house_view_candidates(fr, lat, lng, INTR, aspect=4 / 3, max_dist_m=80.0)
    first = cands[cands.pano_id == fr.pano_id.iloc[0]].iloc[0]
    assert pd.isna(first.cam_k)


# ----------------------------------------------------------------------------- triangulation


def _sightings(true_ll, noise_deg, n=3, seed=0):
    """Boxes around the true house point in views rendered from `n` panos 20-30 m away."""
    rng = np.random.default_rng(seed)
    fr = _street(n=12, spacing=8.0)
    out = []
    pano_ids = sorted(fr.pano_id.unique())
    for pid in pano_ids:
        rows = fr[fr.pano_id == pid].to_dict("records")
        pose = rows[0]["camera_pose"]
        d = float(geo.haversine_m(pose["latitude"], pose["longitude"], *true_ll))
        if not 20.0 <= d <= 30.0:
            continue
        az = float(geo.bearing_deg(pose["latitude"], pose["longitude"], *true_ll))
        view = rosette.PerspectiveView(az + rng.uniform(-10, 10), 5.0, 50.0, 1024, 768)
        el = math.degrees(math.atan((4.0 - 2.5) / d))
        u, v, ok = view.bearing_to_pixel(az + rng.uniform(-noise_deg, noise_deg), el)
        assert bool(ok)
        half = 60.0
        box = (float(u) - half, float(v) - 40.0, float(u) + half, float(v) + 40.0)
        out.append(views.HouseSighting(pid, pose, view, box))
        if len(out) == n:
            break
    assert len(out) == n
    return out


def test_triangulate_house_recovers_the_point_and_anchors_the_id_on_it():
    true_ll = _house_latlng(offset_e=18.0, along_n=40.0)
    loc, status = views.triangulate_house(_sightings(true_ll, noise_deg=1.0))
    assert status == "triangulated" and loc is not None
    assert geo.haversine_m(loc.lat, loc.lng, *true_ll) < 1.5
    assert loc.entity_id == ent.entity_id_for("HOUSE", loc.lat, loc.lng)
    assert loc.n_views == 3


def _runs_with_box_noise(n_runs=20, noise_deg=1.0):
    true_ll = _house_latlng(offset_e=18.0, along_n=40.0)
    locs = [
        views.triangulate_house(_sightings(true_ll, noise_deg, seed=s))[0] for s in range(n_runs)
    ]
    assert all(loc is not None for loc in locs)
    return locs


def test_raw_house_id_is_run_local_under_box_noise():
    # 1 deg of box noise moves the point by ~0.5 m, enough to cross a 2 m id cell sometimes:
    # the raw id is not a cross-run key, which is why match_house_ids exists.
    locs = _runs_with_box_noise()
    assert len({loc.entity_id for loc in locs}) > 1


def test_match_house_ids_carries_the_previous_id_under_box_noise():
    locs = _runs_with_box_noise()
    first = locs[0]
    for loc in locs[1:]:
        assert views.match_house_ids([first], [loc], max_m=3.0) == [first.entity_id]


def test_match_house_ids_keeps_new_ids_for_new_or_distant_houses():
    a = views.HouseLocation(28.0, -81.0, "house_a", 2, 0.5)
    near = views.HouseLocation(28.0 + 1.0 / 111_320, -81.0, "house_b", 2, 0.5)  # ~1 m north
    far = views.HouseLocation(28.0 + 10.0 / 111_320, -81.0, "house_c", 2, 0.5)  # ~10 m north
    assert views.match_house_ids([a], [near, far], max_m=3.0) == ["house_a", "house_c"]
    # one previous id is given to at most one new house (the nearest)
    near2 = views.HouseLocation(28.0 + 2.0 / 111_320, -81.0, "house_d", 2, 0.5)
    assert views.match_house_ids([a], [near2, near], max_m=3.0) == ["house_d", "house_a"]
    assert views.match_house_ids([], [near], max_m=3.0) == ["house_b"]


def test_triangulate_house_takes_no_user_coordinate():
    assert "user_latlng" not in inspect.signature(views.triangulate_house).parameters


@pytest.mark.parametrize("n", [0, 1])
def test_triangulate_house_needs_two_views(n):
    true_ll = _house_latlng(offset_e=18.0, along_n=40.0)
    s = _sightings(true_ll, noise_deg=0.0)[:n] if n else []
    assert views.triangulate_house(s) == (None, "unlocated")


# ----------------------------------------------------------------------------- attribute fusion


def test_fuse_attribute_ignores_unknown_when_a_known_value_exists():
    votes = [("UNKNOWN", 0.9), ("UNKNOWN", 0.9), ("BRICK", 0.4)]
    assert ent.fuse_attribute(votes, ignore={"UNKNOWN"})[0] == "BRICK"
    assert ent.fuse_attribute([("UNKNOWN", 0.9)], ignore={"UNKNOWN"}) == (None, 0.0)
    assert ent.fuse_attribute(votes)[0] == "UNKNOWN"  # default behaviour unchanged


# ----------------------------------------------------------------------------- roof views (UC4)


def test_roof_view_pitch_vfov_contains_eave_and_roof_top():
    for d in (12.0, 20.0, 35.0):
        pitch, vfov = views.roof_view_pitch_vfov(d, cam_h=2.5, eave_h=3.0, top_h=10.0)
        lo, hi = pitch - vfov / 2, pitch + vfov / 2
        assert lo < math.degrees(math.atan(0.5 / d)) and hi > math.degrees(math.atan(7.5 / d))


def test_rank_roof_views_covers_the_roof_and_keeps_its_top_in_frame():
    fr = _street(n=14)
    lat, lng = _house_latlng(offset_e=16.0, along_n=55.0)
    out = views.rank_roof_views(fr, lat, lng, INTR, n=6)
    assert 1 <= len(out) <= 6
    assert out.pano_id.is_unique  # at most one view per pano
    white = np.full((INTR.height, INTR.width, 3), 255, np.uint8)
    for r in out.to_dict("records"):
        need = 2 * math.degrees(math.atan(views.ROOF_WIDTH_M / 2 / r["dist_m"]))
        assert r["hfov"] >= need - 1e-6
        view = views.view_for(r, 400, 300)
        top_el = math.degrees(math.atan((views.ROOF_TOP_M - 2.5) / r["dist_m"]))
        _, _, inside = view.bearing_to_pixel(r["bearing"], top_el)
        assert bool(inside)
        rendered = rosette.render_perspective(white, INTR, r["camera_pose"], view, int(r["cam_k"]))
        assert float(np.mean(rendered[..., 0] == 0)) < 0.01


def test_rank_roof_views_prefers_the_12_to_35_m_band():
    fr = _street(n=14)
    lat, lng = _house_latlng(offset_e=16.0, along_n=55.0)
    out = views.rank_roof_views(fr, lat, lng, INTR, n=3)
    assert all(12.0 <= d <= 35.0 for d in out.dist_m)


def test_rank_roof_views_diversifies_across_sequences():
    a = _street(n=14)
    b = sim.synthetic_frames(14, 8.0, 48.85, 2.35 + 0.00001, travel_deg=0.0, seq_id="S1")
    b["gcs_uri"] = "gs://unused/" + b["observation_id"]
    fr = pd.concat([a, b], ignore_index=True)
    lat, lng = _house_latlng(offset_e=16.0, along_n=55.0)
    out = views.rank_roof_views(fr, lat, lng, INTR, n=2)
    assert set(out.seq_id) == {"S0", "S1"}


def test_rank_roof_views_empty_when_nothing_qualifies():
    fr = _street(n=3)
    lat, lng = _house_latlng(offset_e=300.0, along_n=0.0)  # far away
    out = views.rank_roof_views(fr, lat, lng, INTR, n=4)
    assert out.empty and "score" in out.columns and "cam_k" in out.columns


def _texture(shape, seed, scale=0.35, blur=5):
    """Multiplicative luminance texture (leaves and siding vary mostly in brightness)."""
    import cv2

    n = np.random.default_rng(seed).normal(0, 1, shape[:2]).astype(np.float32)
    n = cv2.GaussianBlur(n, (0, 0), blur)
    return 1.0 + scale * n / (n.std() + 1e-9)


def _roof_scene(canopy_cover: float, canopy_bgr=(92, 108, 100), seed=0):
    """Sky above a grey metal roof (rows 150-450 of the box), with a canopy of the given
    colour covering `canopy_cover` of the box from one side. The default canopy is the dull
    grey-green of the live Florida views (RGB ~100/108/92): saturation ~38/255, below the old
    HSV screen's 40, so the old screen scored such canopy as not foliage."""
    h, w = 600, 800
    img = np.empty((h, w, 3), np.float32)
    img[:300] = (230, 210, 200)  # overcast sky (BGR)
    img[300:] = (150, 150, 150)  # grey metal roof
    img *= _texture((h, w), seed, 0.12)[..., None]
    box = (200, 150, 600, 450)
    x0, y0, x1, y1 = box
    if canopy_cover:
        cut = int(x0 + (x1 - x0) * canopy_cover)
        leaves = np.array(canopy_bgr, np.float32) * _texture((h, w), seed + 1, 0.45, 2)[..., None]
        img[y0:y1, x0:cut] = leaves[y0:y1, x0:cut]
    return np.clip(img, 0, 255).astype(np.uint8), box


@pytest.mark.parametrize("bgr", [(92, 108, 100), (40, 140, 50), (55, 80, 60)],
                         ids=["dull_grey_green", "bright_green", "dark_green"])  # fmt: skip
def test_occlusion_screen_rejects_a_roof_hidden_by_realistic_canopy(bgr):
    img, box = _roof_scene(0.7, bgr)
    s = views.occlusion_screen(img, box)
    assert s["foliage_frac"] >= 0.6 and s["rejected"]


def test_occlusion_screen_keeps_a_clear_roof_under_grey_sky():
    img, box = _roof_scene(0.0)
    s = views.occlusion_screen(img, box)
    assert s["foliage_frac"] < 0.05 and not s["rejected"]


def test_occlusion_screen_keeps_a_roof_with_a_small_tree():
    img, box = _roof_scene(0.25)
    s = views.occlusion_screen(img, box)
    assert 0.15 < s["foliage_frac"] < 0.35 and not s["rejected"]


def test_roof_box_spans_the_roof_width_and_eave_to_ridge():
    view = rosette.PerspectiveView(90.0, 14.0, 60.0, 1200, 900)
    row = {"bearing": 90.0, "dist_m": 30.0}
    x0, y0, x1, y1 = views.roof_box(row, view)
    assert (x0 + x1) / 2 == pytest.approx(view.cx, abs=1)
    level = rosette.PerspectiveView(90.0, 0.0, 60.0, 1200, 900)  # width checked on the horizon
    lx0, _, lx1, _ = views.roof_box(row, level)
    az0, _ = level.pixel_to_bearing(lx0, level.cy)
    az1, _ = level.pixel_to_bearing(lx1, level.cy)
    width_m = 2 * 30.0 * np.tan(np.radians((float(az1) - float(az0)) / 2))
    assert width_m == pytest.approx(views.ROOF_WIDTH_M, rel=0.02)
    _, el_top = view.pixel_to_bearing(view.cx, y0)
    _, el_eave = view.pixel_to_bearing(view.cx, y1)
    rise = views.ROOF_TOP_M - views.CAM_HEIGHT_M
    assert float(el_top) == pytest.approx(np.degrees(np.arctan(rise / 30.0)), abs=0.1)
    drop = views.ROOF_EAVE_M - views.CAM_HEIGHT_M
    assert float(el_eave) == pytest.approx(np.degrees(np.arctan(drop / 30.0)), abs=0.1)


def test_roof_decoys_are_non_roof_rows_across_the_roof_width():
    view = rosette.PerspectiveView(90.0, 14.0, 60.0, 1200, 900)
    row = {"bearing": 90.0, "dist_m": 25.0}
    x0, _, x1, y_eave = views.roof_box(row, view)
    decoys = views.roof_decoys(row, view)
    assert set(decoys) == {"horizon", "wall_base", "siding"}
    heights = {
        "horizon": [views.CAM_HEIGHT_M],
        "wall_base": [0.0],
        "siding": views.SIDING_HEIGHTS_M,
    }
    for name, segs in decoys.items():
        assert len(segs) == len(heights[name])
        for ((ax, ay), (bx, by)), h in zip(segs, heights[name], strict=True):
            assert ay == pytest.approx(by) and ay > y_eave  # level, below the eave
            assert ax == pytest.approx(max(x0, 0.0)) and bx == pytest.approx(min(x1, 1199.0))
            _, el = view.pixel_to_bearing(view.cx, ay)
            expect = np.degrees(np.arctan((h - views.CAM_HEIGHT_M) / 25.0))
            assert float(el) == pytest.approx(expect, abs=0.1)


def test_wall_box_spans_eave_to_wall_base_under_the_roof_box():
    view = rosette.PerspectiveView(90.0, 14.0, 60.0, 1200, 900)
    row = {"bearing": 90.0, "dist_m": 25.0}
    rx0, _, rx1, y_eave = views.roof_box(row, view)
    x0, y0, x1, y1 = views.wall_box(row, view)
    assert (x0, x1, y0) == pytest.approx((rx0, rx1, y_eave))
    assert y1 == pytest.approx(views.roof_decoys(row, view)["wall_base"][0][0][1])


def test_occlusion_screen_rejects_low_sky_contact_when_min_sky_contact_set():
    img, box = _roof_scene(0.0)
    # Clear sky above box -> sky_contact >= 0.30 -> not rejected
    s_clear = views.occlusion_screen(img, box, min_sky_contact=0.25)
    assert s_clear["sky_contact"] >= 0.30 and not s_clear["rejected"]

    # Overhanging palm/wall blocking sky above box (rows 0..150 inside x0..x1)
    img_blocked = img.copy()
    x0, y0, x1, _ = box
    leaves = np.array((55, 80, 60), np.float32) * _texture(img.shape[:2], 99, 0.45, 2)[..., None]
    img_blocked[:y0, x0:x1] = np.clip(leaves[:y0, x0:x1], 0, 255).astype(np.uint8)
    s_blocked = views.occlusion_screen(img_blocked, box, min_sky_contact=0.25)
    assert s_blocked["sky_contact"] < 0.25 and s_blocked["rejected"]
