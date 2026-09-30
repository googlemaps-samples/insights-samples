"""Zero-mock synthetic tests for multi-view entity deduplication."""

import math

import numpy as np
import pytest

from svi_geo import entities as ent
from svi_geo import triangulate as tri

REF = (48.8, 2.37, 0.0)
CAM_H = 2.5


def _panos(n=8, spacing=10.0):
    return [(f"P{i}", np.array([0.0, i * spacing, CAM_H])) for i in range(n)]


OBJECTS = [
    ("UTILITY_POLE", np.array([4.0, 12.0, 0.0])),
    ("UTILITY_POLE", np.array([4.0, 14.0, 0.0])),  # 2 m from the previous pole
    ("UTILITY_POLE", np.array([-5.0, 45.0, 0.0])),
    ("ROAD_SIGN", np.array([3.5, 30.0, 0.0])),
    ("ROAD_SIGN", np.array([-4.0, 62.0, 0.0])),
    ("HOUSE", np.array([14.0, 20.0, 0.0])),
    ("HOUSE", np.array([-15.0, 40.0, 0.0])),
    ("HOUSE", np.array([15.0, 55.0, 0.0])),
]


def _observe(objects, panos, sigma_deg=0.5, seed=0, max_range=40.0):
    rng = np.random.default_rng(seed)
    obs, truth = [], {}
    for pid, c in panos:
        for oi, (cls, x) in enumerate(objects):
            d = x - c
            rng_h = math.hypot(d[0], d[1])
            if rng_h < 3 or rng_h > max_range:
                continue
            az = math.degrees(math.atan2(d[0], d[1])) + rng.normal(0, sigma_deg)
            el_b = math.degrees(math.atan2(d[2], rng_h)) + rng.normal(0, sigma_deg)
            oid = f"{pid}_{oi}"
            obs.append(
                ent.Observation(
                    obs_id=oid,
                    pano_id=pid,
                    cls=cls,
                    ray=tri.Ray(c, az, el_b),
                    confidence=0.9,
                    el_bottom_deg=el_b,
                    attrs={"material": "WOOD" if oi % 2 == 0 else "METAL"},
                )
            )
            truth[oid] = oi
    return obs, truth


def _purity(entities, truth):
    tot, good = 0, 0
    for e in entities:
        labels = [truth[o] for o in e.obs_ids if o in truth]
        if not labels:
            continue
        tot += len(labels)
        good += max(labels.count(v) for v in set(labels))
    return good / tot


def _assert_one_entity_per_obs(entities):
    ids = [o for e in entities for o in e.obs_ids]
    assert len(ids) == len(set(ids))


def test_eight_objects_become_eight_entities():
    obs, truth = _observe(OBJECTS, _panos())
    out = ent.cluster(obs, REF, cam_height_m=CAM_H)
    multi = [e for e in out if e.n_panos >= 2]
    assert len(multi) == 8
    assert len(out) == 8  # no extra single-view duplicates
    _assert_one_entity_per_obs(out)
    assert _purity(out, truth) >= 0.95
    for e in multi:
        oi = max(set(truth[o] for o in e.obs_ids), key=[truth[o] for o in e.obs_ids].count)
        err = np.linalg.norm(e.point_enu[:2] - OBJECTS[oi][1][:2])
        assert err < 1.0, (e.cls, err)
        assert e.cls == OBJECTS[oi][0]


def test_close_poles_are_not_merged():
    obs, truth = _observe(OBJECTS[:2], _panos())
    out = ent.cluster(obs, REF, cam_height_m=CAM_H)
    poles = [e for e in out if e.n_panos >= 2]
    assert len(poles) == 2
    assert len({e.entity_id for e in out}) == len(out)  # ids unique even 2 m apart
    _assert_one_entity_per_obs(out)
    for e, (_, x) in zip(sorted(poles, key=lambda e: e.point_enu[1]), OBJECTS[:2], strict=True):
        assert np.linalg.norm(e.point_enu[:2] - x[:2]) < 0.5
    # Beyond ~25 m the two poles are < 1 sigma apart in azimuth and elevation, so far views can
    # be swapped (physically ambiguous at 0.5 deg); near views must be assigned correctly.
    pano_y = {pid: c[1] for pid, c in _panos()}
    near = {o: v for o, v in truth.items() if pano_y[o.split("_")[0]] <= 20}
    assert _purity(out, near) >= 0.95
    assert _purity(out, truth) >= 0.8


def test_entity_ids_are_deterministic_and_order_independent():
    obs, _ = _observe(OBJECTS, _panos())
    a = ent.cluster(obs, REF, cam_height_m=CAM_H)
    b = ent.cluster(list(reversed(obs)), REF, cam_height_m=CAM_H)
    assert sorted(e.entity_id for e in a) == sorted(e.entity_id for e in b)


def test_single_view_leftover_uses_ground_contact_range():
    c = np.array([0.0, 0.0, CAM_H])
    el_b = -math.degrees(math.atan2(CAM_H, 10.0))
    o = ent.Observation("x", "P0", "UTILITY_POLE", tri.Ray(c, 90.0, el_b), 0.8, el_bottom_deg=el_b)
    (e,) = ent.cluster([o], REF, cam_height_m=CAM_H)
    assert e.method == "single_view_ground_contact"
    np.testing.assert_allclose(e.point_enu[:2], [10.0, 0.0], atol=0.05)


def test_attributes_are_confidence_weighted():
    votes = [("WOOD", 0.9), ("METAL", 0.4), ("METAL", 0.4)]
    assert ent.fuse_attribute(votes) == ("WOOD", 0.9 / 1.7)


def test_long_street_with_one_degree_noise_has_no_split_entities():
    """Many collinear panos + 1 deg noise scatter pair votes along the viewing direction; a
    pole must still end up as one entity (split centres from disjoint panos are merged)."""
    panos = _panos(n=24, spacing=5.0)
    poles = [("UTILITY_POLE", np.array([4.5 * (-1) ** i, 8.0 + 11.0 * i, 0.0])) for i in range(10)]
    for seed in range(4):
        obs, truth = _observe(poles, panos, sigma_deg=1.0, seed=seed)
        entities = ent.cluster(obs, REF)
        _assert_one_entity_per_obs(entities)
        majority = [max(set(lab := [truth[o] for o in e.obs_ids]), key=lab.count) for e in entities]
        assert len(majority) - len(set(majority)) <= 1, (seed, len(entities))
        assert _purity(entities, truth) >= 0.95


def test_ground_height_comes_from_rays_on_a_slope():
    """Street climbing 15%: a pole's base height must be measured by the rays, not taken as
    'camera height below the observers' (which is metres off for far, higher observers)."""
    panos = [(f"S{i}", np.array([0.0, 5.0 * i, CAM_H + 0.75 * i])) for i in range(12)]
    pole = [("UTILITY_POLE", np.array([4.0, 6.0, 0.9]))]
    obs, _truth = _observe(pole, panos, sigma_deg=0.3, seed=1)
    entities = ent.cluster(obs, REF)
    assert len(entities) == 1
    assert entities[0].method == "triangulated"
    assert abs(entities[0].point_enu[2] - 0.9) < 0.5
    assert entities[0].n_panos == len({o.pano_id for o in obs})


# ----------------------------------------------------------------------------- Task 8


def test_eps_override_must_use_cluster_keys():
    obs, _ = _observe(OBJECTS[:2], _panos())
    with pytest.raises(ValueError, match="POST_GROUP"):
        ent.cluster(obs, REF, eps_by_class={"UTILITY_POLE": 3.5})
    with pytest.raises(ValueError, match="unknown"):
        ent.cluster(obs, REF, eps_by_class={"SPACESHIP": 3.5})
    # valid cluster keys are accepted
    ent.cluster(obs, REF, eps_by_class={"POST_GROUP": 3.0, "HOUSE": 8.0})


def test_two_houses_twenty_metres_apart_are_two_triangulated_entities():
    houses = [("HOUSE", np.array([14.0, 10.0, 0.0])), ("HOUSE", np.array([14.0, 30.0, 0.0]))]
    for seed in range(20):
        panos = [(f"P{i}", np.array([0.0, 8.0 * i, CAM_H])) for i in range(6)]
        obs, truth = _observe(houses, panos, sigma_deg=1.0, seed=seed)
        # every house is seen from at least 4 panos
        assert all(list(truth.values()).count(k) >= 4 for k in (0, 1))
        out = ent.cluster(obs, REF, cam_height_m=CAM_H)
        assert len(out) == 2, (seed, [(e.method, e.n_panos) for e in out])
        assert all(e.method == "triangulated" for e in out)
        assert _purity(out, truth) == 1.0


def _single_house(el_bottom):
    c = np.array([0.0, 0.0, CAM_H])
    el = el_bottom if el_bottom is not None else -5.0
    return ent.Observation("h1", "P0", "HOUSE", tri.Ray(c, 90.0, el), 0.9, el_bottom_deg=el_bottom)


def test_single_view_house_without_ground_contact_is_unlocated():
    (e,) = ent.cluster([_single_house(None)], REF, cam_height_m=CAM_H)
    assert e.method == "unlocated"
    assert math.isnan(e.lat) and math.isnan(e.lng)
    assert np.all(np.isnan(e.point_enu))
    assert "unlocated" in e.entity_id
    assert ent.located_entities([e]) == []


def test_single_view_house_with_ground_contact_uses_single_view_range():
    el_b = -math.degrees(math.atan2(CAM_H, 18.0))
    (e,) = ent.cluster([_single_house(el_b)], REF, cam_height_m=CAM_H)
    assert e.method == "single_view_ground_contact"
    expected = tri.single_view_range(el_b, CAM_H)
    assert e.range_m == pytest.approx(expected)
    np.testing.assert_allclose(e.point_enu[:2], [expected, 0.0], atol=1e-6)
    assert ent.located_entities([e]) == [e]


def test_no_fixed_default_range_for_placement():
    assert not hasattr(ent, "DEFAULT_RANGE_M")


def test_ghost_suppression_only_compares_same_cluster_key():
    houses = [("HOUSE", np.array([14.0, 20.0, 0.0]))]
    obs, _ = _observe(houses, _panos(5), sigma_deg=0.3, seed=2)
    pole_xy = np.array([14.0, 18.0])  # 2 m from the house centre
    c = np.array([0.0, 0.0, CAM_H])
    rng_h = float(np.hypot(*pole_xy))
    az = math.degrees(math.atan2(pole_xy[0], pole_xy[1]))
    el_b = -math.degrees(math.atan2(CAM_H, rng_h))
    pole = ent.Observation("pole", "P0", "UTILITY_POLE", tri.Ray(c, az, el_b), 0.5, el_b)
    out = ent.cluster([*obs, pole], REF, cam_height_m=CAM_H)
    poles = [e for e in out if e.cls == "UTILITY_POLE"]
    assert len(poles) == 1 and poles[0].method == "single_view_ground_contact"
    assert [e.method for e in out if e.cls == "HOUSE"] == ["triangulated"]


def test_ghost_conf_is_a_parameter_for_same_key_ghosts():
    # a triangulated pole plus a weak second ray from a pano that already supports it
    obs, _ = _observe([("UTILITY_POLE", np.array([4.0, 20.0, 0.0]))], _panos(5), seed=3)
    c = np.array([0.0, 0.0, CAM_H])
    # its ground point is 2 m from the pole but its azimuth is ~5 sigma off, so it is not
    # attached to the pole and stays a single view
    target = np.array([6.0, 19.5])
    el_b = -math.degrees(math.atan2(CAM_H, float(np.hypot(*target))))
    az = math.degrees(math.atan2(target[0], target[1]))
    weak = ent.Observation("weak", "P0", "UTILITY_POLE", tri.Ray(c, az, el_b), 0.4, el_b)
    default = ent.cluster([*obs, weak], REF, cam_height_m=CAM_H)
    kept = ent.cluster([*obs, weak], REF, cam_height_m=CAM_H, ghost_conf=0.0)
    assert len(kept) == len(default) + 1
    assert any("weak" in e.obs_ids and e.method != "triangulated" for e in kept)


# ----------------------------------------------------------------------------- round 2 (F2)


def _observe_extended(facades, panos, sigma_deg=1.0, seed=0, max_range=40.0, min_visible=1.0):
    """Houses as facades parallel to the street (x = const, y0..y1), not points. A detector's
    box spans the visible part of the facade, so each ray points at the angular midpoint of
    that part and the box bottom at the ground under that direction. With `min_visible` < 1
    each view sees a random sub-interval (trees, parked vehicles, the image border) of at
    least that share of the facade, so the rays of one house do not meet in one point."""
    rng = np.random.default_rng(seed)
    obs, truth = [], {}
    for pid, c in panos:
        for oi, (x, fy0, fy1) in enumerate(facades):
            vis = rng.uniform(min_visible, 1.0) * (fy1 - fy0)
            y0 = fy0 + rng.uniform(0.0, (fy1 - fy0) - vis)
            y1 = y0 + vis
            az0 = math.degrees(math.atan2(x - c[0], y0 - c[1]))
            az1 = math.degrees(math.atan2(x - c[0], y1 - c[1]))
            az = (az0 + az1) / 2
            # facade point in that direction (x fixed), and its ground range
            t = (x - c[0]) / math.sin(math.radians(az))
            if t < 3 or t > max_range:
                continue
            el_b = -math.degrees(math.atan2(c[2], t))
            az += rng.normal(0, sigma_deg)
            el_b += rng.normal(0, sigma_deg)
            oid = f"{pid}_{oi}"
            obs.append(ent.Observation(oid, pid, "HOUSE", tri.Ray(c, az, el_b), 0.9,
                                       el_bottom_deg=el_b))  # fmt: skip
            truth[oid] = oi
    return obs, truth


def test_extended_houses_are_triangulated_despite_facade_misfit():
    """Two 10 m facades 10 m apart, each view seeing a random 40-100 % of each facade.

    Measured: 19 of 20 seeds give exactly two pure triangulated houses. In the other seed
    (seed 2) three rays of each house cross in the front yard (rms 1.7 m) and form one
    mixed triangulation; the angles alone cannot reject it, whatever the RMS limit (probed
    with 3, 5, 6 and 7 m). The test pins that rate instead of hiding the failure."""
    facades = [(14.0, 5.0, 15.0), (14.0, 25.0, 35.0)]
    exact, failures = 0, []
    for seed in range(20):
        panos = [(f"P{i}", np.array([0.0, 8.0 * i, CAM_H])) for i in range(6)]
        obs, truth = _observe_extended(facades, panos, seed=seed, min_visible=0.4)
        out = ent.cluster(obs, REF, cam_height_m=CAM_H)
        tri_h = [e for e in out if e.method == "triangulated"]
        ok = len(tri_h) == 2 and len(out) == 2 and _purity(out, truth) == 1.0
        for e in tri_h if ok else []:
            x, y0, y1 = facades[truth[e.obs_ids[0]]]
            ok = ok and abs(e.point_enu[1] - (y0 + y1) / 2) < 5.0  # within the facade
        exact += ok
        if not ok:
            failures.append((seed, [(e.method, e.n_panos, round(e.rms_m, 1)) for e in out]))
    assert exact >= 19, failures


def test_max_triangulation_rms_is_separate_from_eps():
    assert ent.MAX_TRIANGULATION_RMS_M["HOUSE"] > ent.CLUSTER_EPS["HOUSE"]
    assert ent.MAX_TRIANGULATION_RMS_M["POST_GROUP"] == ent.CLUSTER_EPS["POST_GROUP"]


@pytest.mark.parametrize(("range_m", "located"), [(20.0, True), (29.0, True), (45.0, False)])
def test_single_view_house_is_only_placed_within_the_house_range_cap(range_m, located):
    el_b = -math.degrees(math.atan2(CAM_H, range_m))
    (e,) = ent.cluster([_single_house(el_b)], REF, cam_height_m=CAM_H)
    assert e.located is located
    assert e.method == ("single_view_ground_contact" if located else "unlocated")


def test_single_view_pole_keeps_the_longer_range_cap():
    c = np.array([0.0, 0.0, CAM_H])
    el_b = -math.degrees(math.atan2(CAM_H, 45.0))
    o = ent.Observation("p", "P0", "UTILITY_POLE", tri.Ray(c, 90.0, el_b), 0.8, el_bottom_deg=el_b)
    (e,) = ent.cluster([o], REF, cam_height_m=CAM_H)
    assert e.method == "single_view_ground_contact"


def test_min_post_panos_excludes_single_view_signs_from_located_entities():
    c = np.array([0.0, 0.0, CAM_H])
    el_b = -math.degrees(math.atan2(CAM_H, 12.0))
    sign_single = ent.Observation(
        "s1", "P0", "ROAD_SIGN", tri.Ray(c, 80.0, el_b), 0.85, el_bottom_deg=el_b
    )
    pole_obs, _ = _observe([("UTILITY_POLE", np.array([4.0, 20.0, 0.0]))], _panos(4), seed=0)
    entities = ent.cluster([*pole_obs, sign_single], REF, cam_height_m=CAM_H, min_post_panos=2)
    located = ent.located_entities(entities)
    assert [e.cls for e in located] == ["UTILITY_POLE"]
    candidates = [e for e in entities if not e.located]
    assert len(candidates) == 1 and candidates[0].cls == "ROAD_SIGN"


def test_three_14m_houses_seen_from_six_panos_located_via_facade_edges():
    facades = [(16.0, 4.0, 18.0), (16.0, 28.0, 42.0), (16.0, 52.0, 66.0)]
    panos = [(f"P{i}", np.array([0.0, 12.0 * i, CAM_H])) for i in range(6)]
    obs = []
    for pid, c in panos:
        for oi, (x, fy0, fy1) in enumerate(facades):
            if abs(c[1] - 0.5 * (fy0 + fy1)) > 26.0:
                continue
            az_left = math.degrees(math.atan2(x - c[0], fy1 - c[1]))
            az_right = math.degrees(math.atan2(x - c[0], fy0 - c[1]))
            # Partial occlusion shifts the apparent box centre while true edges remain recoverable
            az_mid = 0.5 * (az_left + az_right) + (1.5 if c[1] < 0.5 * (fy0 + fy1) else -1.5)
            obs.append(
                ent.Observation(
                    obs_id=f"{pid}_{oi}",
                    pano_id=pid,
                    cls="HOUSE",
                    ray=tri.Ray(
                        c,
                        az_mid,
                        0.0,
                        meta={"az_left": az_left, "az_right": az_right},
                    ),
                    confidence=0.9,
                    el_bottom_deg=None,
                )
            )
    out_edge = ent.cluster(obs, REF, cam_height_m=CAM_H, use_house_facade_edges=True)
    loc_edge = [e for e in out_edge if e.located and e.cls == "HOUSE"]
    assert len(loc_edge) == 3
    for e in loc_edge:
        dists = [
            float(np.hypot(e.point_enu[0] - x, e.point_enu[1] - 0.5 * (fy0 + fy1)))
            for x, fy0, fy1 in facades
        ]
        assert min(dists) <= 2.0, dists


def test_fuse_attribute_returns_unknown_when_fewer_than_min_agree_views():
    # Two disagreeing views -> returns ("UNKNOWN", 0.0) when min_agree_views=2
    assert ent.fuse_attribute(
        [("BRICK", 0.9), ("STUCCO", 0.85)], ignore={"UNKNOWN"}, min_agree_views=2
    ) == ("UNKNOWN", 0.0)
    # Two agreeing views -> returns the agreed value
    val, share = ent.fuse_attribute(
        [("BRICK", 0.9), ("BRICK", 0.8), ("STUCCO", 0.7)],
        ignore={"UNKNOWN"},
        min_agree_views=2,
    )
    assert val == "BRICK" and share > 0.6
