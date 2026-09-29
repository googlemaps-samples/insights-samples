"""Zero-mock synthetic tests for multi-view entity deduplication."""

import math

import numpy as np

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
    assert e.method == "single_view"
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
