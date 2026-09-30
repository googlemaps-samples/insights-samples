"""UC1 view framing, ranking and house triangulation (pure geometry, zero mocks)."""

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


def test_triangulated_id_does_not_depend_on_the_user_coordinate():
    true_ll = _house_latlng(offset_e=18.0, along_n=40.0)
    s = _sightings(true_ll, noise_deg=1.0)
    a, _ = views.triangulate_house(s)
    # the user's coordinate is only used to pick views; a 2 m shift changes nothing
    b, _ = views.triangulate_house(s, user_latlng=_house_latlng(offset_e=20.0, along_n=40.0))
    assert a.entity_id == b.entity_id
    assert ent.entity_id_for("HOUSE", *true_ll) != ent.entity_id_for(
        "HOUSE", *_house_latlng(offset_e=20.0, along_n=41.0)
    )  # the old user-anchored id would have changed


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
