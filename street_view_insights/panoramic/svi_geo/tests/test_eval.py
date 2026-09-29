"""Zero-mock tests for evaluation metrics, baselines, self-consistency and hand-label scoring."""

import asyncio
import math
from pathlib import Path

import numpy as np
import pytest

from svi_geo import entities as ent
from svi_geo import eval as ev
from svi_geo import gemini_client as gc
from svi_geo import rosette
from svi_geo import simulate as sim
from svi_geo import triangulate as tri

FIXTURES = Path(__file__).parent / "fixtures"


# ----------------------------------------------------------------------------- metrics


def test_perfect_clustering_scores_one():
    truth = {"a1": "A", "a2": "A", "b1": "B", "b2": "B", "b3": "B"}
    pred = {"a1": "x", "a2": "x", "b1": "y", "b2": "y", "b3": "y"}
    m = ev.clustering_metrics(pred, truth)
    assert m["purity"] == 1.0 and m["completeness"] == 1.0
    assert m["v_measure"] == pytest.approx(1.0) and m["ari"] == pytest.approx(1.0)
    assert m["duplicate_rate"] == 0.0 and m["entities_per_object"] == 1.0


def test_all_singletons_completeness_is_one_over_n():
    n = 4
    truth = {f"{o}{i}": o for o in "ABC" for i in range(n)}
    pred = {k: k for k in truth}  # B0: every observation is its own entity
    m = ev.clustering_metrics(pred, truth)
    assert m["purity"] == 1.0
    assert m["completeness"] == pytest.approx(1 / n)
    assert m["entities_per_object"] == pytest.approx(n)
    assert m["duplicate_rate"] == pytest.approx(n - 1)


def test_split_object_counts_one_duplicate_and_false_positives_are_excluded():
    truth = {"a1": "A", "a2": "A", "a3": "A", "b1": "B", "fp": None}
    pred = {"a1": "x", "a2": "x", "a3": "z", "b1": "y", "fp": "w"}
    m = ev.clustering_metrics(pred, truth)
    assert m["duplicate_rate"] == pytest.approx(0.5)  # 1 duplicate / 2 objects
    assert m["n_fp_entities"] == 1
    assert m["purity"] == 1.0
    assert m["completeness"] == pytest.approx(3 / 4)


def test_location_error_and_missed_rate():
    truth = {"a1": "A", "a2": "A", "b1": "B"}
    pred = {"a1": "x", "a2": "x", "b1": "y"}
    pts = {"A": (0.0, 0.0), "B": (10.0, 0.0), "C": (20.0, 0.0)}
    centres = {"x": (3.0, 4.0), "y": (10.0, 1.0)}
    m = ev.clustering_metrics(pred, truth, centres, pts, visible_objects={"A", "B", "C"})
    assert m["loc_err_median_m"] == pytest.approx(3.0)
    assert m["loc_err_p90_m"] == pytest.approx(1.0 + 0.9 * 4.0)
    assert m["missed_rate"] == pytest.approx(1 / 3)


# ----------------------------------------------------------------------------- baselines


def _obs(oid, pid, origin, az, el=-10.0, cls="UTILITY_POLE"):
    return ent.Observation(oid, pid, cls, tri.Ray(np.asarray(origin, float), az, el), 0.9, el)


def test_b0_entities_per_object_is_mean_observations_per_object():
    fr = sim.synthetic_frames(10, 10.0, 48.85, 2.35)
    scene = sim.make_scene(fr, n_poles=8, n_signs=0, n_houses=0, seed=1)
    res = sim.simulate_observations(scene, fr, rosette.DEFAULT_INTRINSICS, sim.NOISE_FREE)
    obs = sim.to_observations(res.detections, fr, rosette.DEFAULT_INTRINSICS, scene.ref_lla)
    truth = sim.truth_labels(res.detections)
    labels, _ = ev.b0_labels(obs)
    m = ev.clustering_metrics(labels, truth)
    per_obj = np.bincount(np.unique(list(truth.values()), return_inverse=True)[1])
    assert m["entities_per_object"] == pytest.approx(per_obj.mean())


def test_fixed_range_baseline_places_points_at_12m_and_merges_within_eps():
    o1 = _obs("o1", "P0", [0, 0, 2.5], 90.0)
    o2 = _obs("o2", "P1", [0, 1, 2.5], 90.0)  # 1 m apart -> merged at eps 3
    o3 = _obs("o3", "P2", [0, 30, 2.5], 90.0)
    labels, centres = ev.fixed_range_labels([o1, o2, o3], range_m=12.0, eps_m=3.0)
    assert labels["o1"] == labels["o2"] != labels["o3"]
    np.testing.assert_allclose(centres[labels["o3"]], [12.0, 30.0], atol=1e-9)


def test_single_view_ablation_uses_ground_contact_range():
    el = -math.degrees(math.atan2(2.5, 10.0))
    o1 = _obs("o1", "P0", [0, 0, 2.5], 90.0, el)
    labels, centres = ev.single_view_labels([o1], cam_height_m=2.5)
    np.testing.assert_allclose(centres[labels["o1"]], [10.0, 0.0], atol=1e-6)


# ----------------------------------------------------------------------------- self-consistency


class ScriptedBackend:
    def __init__(self, present):
        self.present = list(present)
        self.calls = 0

    async def generate(self, parts, schema, code_execution=False):
        p = self.present[self.calls % len(self.present)]
        self.calls += 1
        box = "[450, 450, 550, 550]" if p else "null"
        text = f'{{"present": {str(p).lower()}, "confidence": 0.8, "box_2d": {box}}}'
        return gc.RawReply(text, {"prompt_token_count": 500, "candidates_token_count": 20})


def test_cross_view_agreement_rate_with_fake_backend():
    tasks = [
        ev.ViewTask(f"e{i}", "UTILITY_POLE", f"P{i}", 0, 10.0 * i, -5.0, 12.0, f"o{i}")
        for i in range(4)
    ]

    def render(task):
        view = rosette.PerspectiveView(task.az_deg, task.el_deg, 40.0, 256, 256)
        return np.zeros((256, 256, 3), np.uint8), view

    backend = ScriptedBackend([True, True, False, True])
    runner = gc.GeminiRunner(backend, max_calls=10, log=lambda *_: None)
    out = asyncio.run(ev.cross_view_agreement(tasks, render, runner))
    assert out["n_asked"] == 4 and backend.calls == 4
    assert out["confirmation_rate"] == pytest.approx(0.75)
    assert out["median_offset_deg"] < 0.2  # box centred on the prediction


def test_predict_withheld_views_targets_panos_not_in_the_entity():
    fr = sim.synthetic_frames(6, 10.0, 48.85, 2.35, travel_deg=0.0)
    ref = sim.scene_ref(fr)
    e = ent.Entity(
        "pole_x", "UTILITY_POLE", np.array([4.0, 25.0, 0.0]), 0, 0, ["a", "b"],
        [fr["pano_id"].unique()[1], fr["pano_id"].unique()[2]], "triangulated", 0.1, 0.9, {},
    )  # fmt: skip
    tasks = ev.predict_withheld_views([e], fr, rosette.DEFAULT_INTRINSICS, ref, max_range_m=30.0)
    pids = {t.pano_id for t in tasks}
    assert pids and not pids & set(e.pano_ids)
    for t in tasks:
        assert 0 <= t.cam_k < 6 and 3.0 <= t.range_m <= 30.0


def test_two_pass_matching():
    def mk(pts, tag):
        return [
            ent.Entity(f"{tag}{i}", "UTILITY_POLE", np.array([x, y, 0.0]), 0, 0, [], [],
                       "triangulated", 0.1, 0.9, {})
            for i, (x, y) in enumerate(pts)
        ]  # fmt: skip

    a = mk([(0, 0), (0, 20), (5, 40), (8, 60)], "a")
    b = mk([(0.5, 0.3), (0.2, 21.0), (5, 47), (30, 30), (8.4, 59.0)], "b")
    m = ev.match_passes(a, b)
    assert m["matched"] == 3
    assert m["recall_a_in_b"] == pytest.approx(0.75)
    assert m["count_ratio"] == pytest.approx(5 / 4)


def test_detection_stability():
    fr = sim.synthetic_frames(5, 10.0, 48.85, 2.35, travel_deg=0.0)
    ref = sim.scene_ref(fr)
    pids = list(fr["pano_id"].unique())
    e = ent.Entity(
        "p", "UTILITY_POLE", np.array([4.0, 0.0, 0.0]), 0, 0, ["a", "b"], pids[:2],
        "triangulated", 0.1, 0.9, {},
    )  # fmt: skip
    out = ev.detection_stability([e], fr, rosette.DEFAULT_INTRINSICS, ref, max_range_m=40.0)
    # scene ENU is centred on the drive: all 5 panos are 4-21 m away and see it -> 2 / 5
    assert out["UTILITY_POLE"] == pytest.approx(2 / 5)


# ----------------------------------------------------------------------------- hand labels


def test_score_hand_labels_fixture():
    pipeline = [
        {"pano_id": "P1", "view_yaw_deg": 0, "cls": "UTILITY_POLE", "box": (102, 98, 121, 405),
         "entity_id": "E1"},
        {"pano_id": "P2", "view_yaw_deg": 0, "cls": "UTILITY_POLE", "box": (200, 100, 220, 400),
         "entity_id": "E1"},
        {"pano_id": "P1", "view_yaw_deg": 0, "cls": "ROAD_SIGN", "box": (300, 200, 340, 240),
         "entity_id": "E2"},
        {"pano_id": "P2", "view_yaw_deg": 0, "cls": "UTILITY_POLE", "box": (600, 100, 620, 400),
         "entity_id": "E3"},
        {"pano_id": "P1", "cls": "ROAD_SEGMENT", "material": "Paved Asphalt"},
        {"pano_id": "P2", "cls": "ROAD_SEGMENT", "material": "paved asphalt"},
    ]  # fmt: skip
    s = ev.score_hand_labels(FIXTURES / "labels_small.csv", pipeline)
    assert s["detection_recall"] == pytest.approx(0.75)
    assert s["detection_precision"] == pytest.approx(0.75)
    assert s["dedup_purity"] == 1.0 and s["dedup_completeness"] == 1.0
    assert s["material_accuracy"] == pytest.approx(0.5)


def test_score_hand_labels_missing_file_returns_none(tmp_path):
    assert ev.score_hand_labels(tmp_path / "nope.csv", []) is None


def test_cross_view_reports_signed_and_per_class_offsets():
    tasks = [
        ev.ViewTask("e0", "UTILITY_POLE", "P0", 0, 10.0, -5.0, 12.0, "o0"),
        ev.ViewTask("e1", "HOUSE", "P1", 0, 50.0, 0.0, 15.0, "o1"),
    ]

    def render(task):
        view = rosette.PerspectiveView(task.az_deg, task.el_deg, 40.0, 256, 256)
        return np.zeros((256, 256, 3), np.uint8), view

    runner = gc.GeminiRunner(ScriptedBackend([True]), max_calls=10, log=lambda *_: None)
    out = asyncio.run(ev.cross_view_agreement(tasks, render, runner))
    assert set(out["median_offset_deg_by_class"]) == {"UTILITY_POLE", "HOUSE"}
    assert abs(out["median_signed_offset_deg"]) < 0.2
    assert all("signed_offset_deg" in t for t in out["per_task"])


def test_two_pass_matching_multiview_only():
    def mk(pts, tag, n_panos):
        return [
            ent.Entity(f"{tag}{i}", "UTILITY_POLE", np.array([x, y, 0.0]), 0, 0, [],
                       [f"p{k}" for k in range(n)], "triangulated" if n > 1 else "single_view",
                       0.1, 0.9, {})
            for i, ((x, y), n) in enumerate(zip(pts, n_panos, strict=True))
        ]  # fmt: skip

    a = mk([(0, 0), (0, 20), (9, 40)], "a", [3, 2, 1])
    b = mk([(0.5, 0.3), (0.2, 21.0), (30, 30)], "b", [2, 2, 1])
    m = ev.match_passes(a, b, multi_view_only=True)
    assert m["n_a"] == 2 and m["n_b"] == 2 and m["matched"] == 2
    assert m["recall_a_in_b"] == pytest.approx(1.0)
