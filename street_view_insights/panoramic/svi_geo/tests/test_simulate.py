"""Zero-mock tests for the synthetic scene / observation simulator (T9a)."""

import dataclasses
import math

import numpy as np

from svi_geo import entities as ent
from svi_geo import geo, rosette
from svi_geo import simulate as sim

INTR = rosette.DEFAULT_INTRINSICS
REF = (48.85, 2.35)


def _frames(n=12, spacing=10.0, travel=30.0):
    return sim.synthetic_frames(n, spacing, REF[0], REF[1], travel_deg=travel)


def test_synthetic_frames_have_rosette_layout():
    fr = _frames(3)
    assert set(fr["cam_k"]) == set(range(7))
    assert fr["pano_id"].nunique() == 3
    p0 = fr[fr["pano_id"] == fr["pano_id"].iloc[0]]
    heads = sorted(float(p["heading"]) for p in p0[p0["cam_k"] < 6]["camera_pose"])
    np.testing.assert_allclose(np.diff(heads), 60.0, atol=1e-9)
    assert all(rosette.camera_index(o) is not None for o in fr["observation_id"])


def test_simulation_is_deterministic_under_seed():
    fr = _frames()
    a = sim.make_scene(fr, n_poles=6, n_signs=3, n_houses=3, seed=4)
    b = sim.make_scene(fr, n_poles=6, n_signs=3, n_houses=3, seed=4)
    assert [o.obj_id for o in a.objects] == [o.obj_id for o in b.objects]
    for x, y in zip(a.objects, b.objects, strict=True):
        np.testing.assert_array_equal(x.point_enu, y.point_enu)
    ra = sim.simulate_observations(a, fr, INTR, sim.NoiseModel(), seed=1)
    rb = sim.simulate_observations(b, fr, INTR, sim.NoiseModel(), seed=1)
    assert ra.detections == rb.detections
    c = sim.make_scene(fr, n_poles=6, n_signs=3, n_houses=3, seed=5)
    assert any(
        not np.allclose(x.point_enu, y.point_enu) for x, y in zip(a.objects, c.objects, strict=True)
    )


def test_object_behind_the_camera_is_never_observed():
    fr = _frames(1, travel=0.0)
    front = fr[fr["cam_k"] == 0]  # cam 0 faces the travel direction (north)
    ref = sim.scene_ref(front)
    behind = sim.SceneObject("pole_0", "UTILITY_POLE", np.array([1.0, -10.0, 0.0]))
    ahead = sim.SceneObject("pole_1", "UTILITY_POLE", np.array([1.0, 10.0, 0.0]))
    scene = sim.Scene([behind, ahead], ref)
    res = sim.simulate_observations(scene, front, INTR, sim.NOISE_FREE)
    assert [d.obj_id for d in res.detections] == ["pole_1"]


def test_ranges_are_limited_to_3_40_m():
    fr = _frames(1, travel=0.0)
    ref = sim.scene_ref(fr)
    objs = [
        sim.SceneObject(f"pole_{i}", "UTILITY_POLE", np.array([2.0, y, 0.0]))
        for i, y in enumerate([2.0, 10.0, 39.0, 45.0])
    ]
    res = sim.simulate_observations(sim.Scene(objs, ref), fr, INTR, sim.NOISE_FREE)
    assert sorted(d.obj_id for d in res.detections) == ["pole_1", "pole_2"]


def test_noise_free_observations_recover_exact_bearings():
    fr = _frames(4)
    scene = sim.make_scene(fr, n_poles=5, n_signs=0, n_houses=0, seed=2)
    res = sim.simulate_observations(scene, fr, INTR, sim.NOISE_FREE)
    obs = sim.to_observations(res.detections, fr, INTR, scene.ref_lla)
    truth = {o.obj_id: o.point_enu for o in scene.objects}
    assert obs
    for o, d in zip(obs, res.detections, strict=True):
        p = truth[d.obj_id]
        az = geo.enu_bearing_deg(p[0] - o.ray.origin[0], p[1] - o.ray.origin[1])
        assert abs(float(geo.angdiff(o.ray.az_deg, az))) < 1e-4
        el = math.degrees(
            math.atan2(p[2] - o.ray.origin[2], math.hypot(*(p[:2] - o.ray.origin[:2])))
        )
        assert abs(o.el_bottom_deg - el) < 1e-4


def test_intrinsics_mismatch_biases_bearings():
    fr = _frames(4)
    true = dataclasses.replace(INTR, fx=1750.0, fy=1750.0)
    scene = sim.make_scene(fr, n_poles=5, n_signs=0, n_houses=0, seed=2)
    res = sim.simulate_observations(scene, fr, true, sim.NOISE_FREE)
    good = sim.to_observations(res.detections, fr, true, scene.ref_lla)
    bad = sim.to_observations(res.detections, fr, INTR, scene.ref_lla)
    err = [
        abs(float(geo.angdiff(a.ray.az_deg, b.ray.az_deg))) for a, b in zip(good, bad, strict=True)
    ]
    assert max(err) > 1.0


def test_noise_model_rates():
    fr = _frames(30, spacing=8.0)
    scene = sim.make_scene(fr, n_poles=40, n_signs=0, n_houses=0, seed=0)
    clean = sim.simulate_observations(scene, fr, INTR, sim.NOISE_FREE, seed=3)
    noise = sim.NoiseModel(bearing_sigma_deg=0.0, pos_sigma_m=0.0, yaw_sigma_deg=0.0)
    noisy = sim.simulate_observations(scene, fr, INTR, noise, seed=3)
    n_true = sum(d.obj_id is not None for d in noisy.detections)
    n_fp = sum(d.obj_id is None for d in noisy.detections)
    assert 0.7 < n_true / len(clean.detections) < 0.9  # 20% dropout
    assert 0.05 < n_fp / n_true < 0.15  # 10% false positives


def test_pipeline_on_clean_simulation_is_pure():
    fr = _frames(12)
    scene = sim.make_scene(fr, n_poles=6, n_signs=3, n_houses=3, seed=7)
    res = sim.simulate_observations(scene, fr, INTR, sim.NoiseModel(0.5, 0.5, 0, 0, 0, 0, 0))
    obs = sim.to_observations(res.detections, fr, INTR, scene.ref_lla)
    out = ent.cluster(obs, scene.ref_lla, cam_height_m=sim.CAM_HEIGHT_M)
    truth = sim.truth_labels(res.detections)
    tot = good = 0
    for e in out:
        labels = [truth[o] for o in e.obs_ids]
        tot += len(labels)
        good += max(labels.count(v) for v in set(labels))
    assert good / tot >= 0.95


def test_full_noise_simulation_keeps_one_entity_per_observation():
    """QA F7 invariant on the noisy simulator (dropout, false positives, class confusion)."""
    fr = _frames(16)
    scene = sim.make_scene(fr, n_poles=8, n_signs=4, n_houses=4, seed=3)
    res = sim.simulate_observations(scene, fr, INTR, sim.NoiseModel(), seed=3)
    obs = sim.to_observations(res.detections, fr, INTR, scene.ref_lla)
    out = ent.cluster(obs, scene.ref_lla, cam_height_m=sim.CAM_HEIGHT_M)
    ids = [o for e in out for o in e.obs_ids]
    assert len(ids) == len(set(ids))
    assert set(ids) <= {o.obs_id for o in obs}
    assert any(t is None for t in sim.truth_labels(res.detections).values())  # FPs present
