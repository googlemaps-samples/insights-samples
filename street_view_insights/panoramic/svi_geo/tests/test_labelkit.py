"""Hand-label kit: sheet format, slots and roof scoring (synthetic fixtures only)."""

import csv
import json
from pathlib import Path

import pytest

from svi_geo import eval as ev
from svi_geo import labelkit

FIXTURES = Path(__file__).parent / "fixtures"

BASE = (
    "label_id,pano_id,observation_id,view_yaw_deg,class,x0,y0,x1,y1,object_key,material,"
    "condition,notes"
)


def test_label_sheet_header_is_exact():
    assert ",".join(labelkit.BASE_COLUMNS) == BASE
    assert labelkit.OPTIONAL_COLUMNS == ("side", "present", "edge_type", "points_json", "labeller")
    assert labelkit.HEADER == labelkit.BASE_COLUMNS + labelkit.OPTIONAL_COLUMNS


def test_write_label_sheet_prefills_rows_with_the_header(tmp_path):
    rows = labelkit.surface_slots(["P1", "P2"])
    path = labelkit.write_label_sheet(tmp_path / "labels.csv", rows)
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        assert tuple(reader.fieldnames) == labelkit.HEADER
        got = list(reader)
    assert len(got) == 6  # 2 panos x ROAD/CENTER, SIDEWALK/LEFT, SIDEWALK/RIGHT
    assert {(r["class"], r["side"]) for r in got} == {
        ("ROAD_SEGMENT", "CENTER"), ("SIDEWALK_SEGMENT", "LEFT"), ("SIDEWALK_SEGMENT", "RIGHT"),
    }  # fmt: skip
    assert all(r["material"] == "" and r["present"] == "" for r in got)  # human fills these


def test_write_label_sheet_rejects_unknown_columns(tmp_path):
    with pytest.raises(ValueError, match="unknown"):
        labelkit.write_label_sheet(tmp_path / "x.csv", [{"label_id": "a", "colour": "red"}])


def test_second_labeller_sample_is_deterministic_and_about_20_percent():
    panos = [f"P{i:02d}" for i in range(40)]
    a = labelkit.second_labeller_panos(panos, fraction=0.2, seed=7)
    assert a == labelkit.second_labeller_panos(panos, fraction=0.2, seed=7)
    assert len(a) == 8 and set(a) <= set(panos)


def test_fixtures_are_marked_synthetic():
    for name in ("labels_small.csv", "labels_segments_roof.csv"):
        with (FIXTURES / name).open(newline="") as f:
            rows = list(csv.DictReader(f))
        assert rows and all(r["notes"] == "synthetic fixture" for r in rows), name


def _seg_labels():
    with (FIXTURES / "labels_segments_roof.csv").open(newline="") as f:
        return [r for r in csv.DictReader(f) if r["class"].endswith("_SEGMENT")]


def test_segments_are_keyed_by_pano_class_and_side_and_absent_is_scored():
    preds = [
        {"pano_id": "P1", "cls": "ROAD_SEGMENT", "side": "CENTER", "material": "Paved Asphalt"},
        {"pano_id": "P1", "cls": "SIDEWALK_SEGMENT", "side": "LEFT", "material": "Concrete"},
        {"pano_id": "P1", "cls": "SIDEWALK_SEGMENT", "side": "RIGHT", "present": False},
        {"pano_id": "P2", "cls": "SIDEWALK_SEGMENT", "side": "LEFT", "present": False},
        {"pano_id": "P2", "cls": "SIDEWALK_SEGMENT", "side": "RIGHT", "material": "Concrete"},
    ]
    s = ev.score_segment_labels(_seg_labels(), preds)
    # labels: P1 L=Concrete, R=absent; P2 L=Concrete, R=absent (see fixture)
    assert s["material_accuracy"] == pytest.approx(1.0)  # road P1 + sidewalk P1-L
    assert s["sidewalk_presence_f1"] == pytest.approx(2 * 1 / (2 * 1 + 1 + 1))
    assert s["side_swap_rate"] == pytest.approx(1 / 2)  # P2 is mirrored
    assert s["n_slots"] == 5


def test_roof_edges_are_matched_within_5px_mean_distance():
    with (FIXTURES / "labels_segments_roof.csv").open(newline="") as f:
        roof = [r for r in csv.DictReader(f) if r["class"] == "ROOF_EDGE"]
    preds = [
        # 2 px below the labelled ridge -> match
        {"pano_id": "P1", "view_yaw_deg": 90, "edge_type": "RIDGE",
         "points": [[100, 102], [300, 102]], "accepted": True},
        # far from any label -> false positive, rejected by the validator
        {"pano_id": "P1", "view_yaw_deg": 90, "edge_type": "EAVE",
         "points": [[100, 400], [300, 400]], "accepted": False},
        # right place but wrong type -> not a match
        {"pano_id": "P1", "view_yaw_deg": 90, "edge_type": "HIP",
         "points": [[100, 250], [300, 250]], "accepted": True},
    ]  # fmt: skip
    s = ev.score_roof_labels(roof, preds)
    assert s["edge_recall"] == pytest.approx(1 / 2)
    assert s["edge_precision"] == pytest.approx(1 / 3)
    assert s["validator_confusion"] == {"tp": 1, "fp": 1, "fn": 0, "tn": 1}
    json.dumps(s)


def test_bootstrap_ci_resamples_panos():
    same = {f"P{i}": (3, 4) for i in range(10)}
    point, lo, hi = ev.bootstrap_ci(same, n_boot=200, seed=0)
    assert point == lo == hi == pytest.approx(0.75)
    mixed = {f"P{i}": ((1, 1) if i % 2 else (0, 1)) for i in range(20)}
    point, lo, hi = ev.bootstrap_ci(mixed, n_boot=500, seed=1)
    assert point == pytest.approx(0.5) and lo < 0.5 < hi and 0.2 < lo and hi < 0.8
    assert ev.bootstrap_ci(mixed, n_boot=500, seed=1) == (point, lo, hi)
    assert all(v != v for v in ev.bootstrap_ci({}, n_boot=10))  # NaN when empty


def test_score_hand_labels_uses_side_keyed_segments(tmp_path):
    rows = [dict(r, notes="synthetic fixture") for r in _seg_labels()]
    path = labelkit.write_label_sheet(tmp_path / "l.csv", rows)
    preds = [
        {"pano_id": "P1", "cls": "SIDEWALK_SEGMENT", "side": "RIGHT", "present": False},
        {"pano_id": "P1", "cls": "SIDEWALK_SEGMENT", "side": "LEFT", "material": "Brick/Pavers"},
    ]
    s = ev.score_hand_labels(path, preds)
    assert s["n_slots"] == 2 and s["material_accuracy"] == 0.0
    assert s["sidewalk_presence_f1"] == pytest.approx(1.0)


def test_per_pano_counts_feed_the_bootstrap():
    preds = [
        {"pano_id": "P1", "cls": "ROAD_SEGMENT", "side": "CENTER", "material": "Paved Asphalt"},
        {"pano_id": "P1", "cls": "SIDEWALK_SEGMENT", "side": "LEFT", "material": "Brick/Pavers"},
        {"pano_id": "P2", "cls": "SIDEWALK_SEGMENT", "side": "LEFT", "material": "Concrete"},
    ]
    counts = ev.per_pano_counts(
        _seg_labels(), preds, ev.score_segment_labels, "material_accuracy", "n_material"
    )
    # P1: road right, sidewalk-L wrong; P2: sidewalk-L right
    assert counts == {"P1": (1.0, 2), "P2": (1.0, 1)}
    point, lo, hi = ev.bootstrap_ci(counts, n_boot=100, seed=0)
    assert point == pytest.approx(2 / 3) and lo <= point <= hi


def test_consecutive_window_takes_n_panos_of_the_longest_sequence_near_the_point():
    import pandas as pd

    rows = [
        {"pano_id": f"A{i}", "seq_id": 0, "seq_idx": i, "lat": 40.0, "lng": -105.0 + i * 1e-4}
        for i in range(30)
    ] + [
        {"pano_id": f"B{i}", "seq_id": 1, "seq_idx": i, "lat": 40.001, "lng": -105.0 + i * 1e-4}
        for i in range(5)
    ]
    seqs = pd.DataFrame(rows).sample(frac=1.0, random_state=0)
    ids = labelkit.consecutive_window(seqs, 40.0, -105.0 + 25e-4, n=10)
    assert ids == [f"A{i}" for i in range(20, 30)]  # clamped to the end of the sequence
    ids = labelkit.consecutive_window(seqs, 40.0, -105.0 + 10e-4, n=4)
    assert ids == [f"A{i}" for i in range(8, 12)]
    with pytest.raises(ValueError, match="consecutive"):
        labelkit.consecutive_window(seqs, 40.0, -105.0, n=31)


def _load_script(name):
    import importlib.util

    path = Path(__file__).parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_score_labels_script_reports_cis_and_inter_annotator_agreement():
    sl = _load_script("score_labels")
    path = FIXTURES / "labels_segments_roof.csv"
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    preds = [
        {"pano_id": "P1", "cls": "ROAD_SEGMENT", "side": "CENTER", "material": "Paved Asphalt"},
        {"pano_id": "P1", "cls": "SIDEWALK_SEGMENT", "side": "LEFT", "material": "Concrete"},
    ]
    roof_preds = [{"pano_id": "P1", "view_yaw_deg": 90, "edge_type": "RIDGE",
                   "points": [[100, 102], [300, 102]], "accepted": True}]  # fmt: skip
    res = sl.report(path, preds, roof_preds, second=[r for r in rows if r["pano_id"] == "P1"])
    assert res["hand_labels"]["material_accuracy"] == pytest.approx(1.0)
    assert res["material_accuracy_ci"] == pytest.approx((1.0, 1.0, 1.0))
    assert res["roof"]["edge_recall"] == pytest.approx(1 / 2)
    assert res["edge_recall_ci"][0] == pytest.approx(1 / 2)
    agree = res["inter_annotator_segments"]
    assert agree["material_accuracy"] == pytest.approx(1.0) and agree["n_slots"] >= 2
    json.dumps(res, default=str)


def test_make_label_kit_script_imports_and_parses_aoi():
    mk = _load_script("make_label_kit")
    assert mk.parse_latlng("40.1,-105.2") == (40.1, -105.2)
    assert mk.ROAD_VIEW_PITCH == -22.0 and mk.MAX_BLACK == 0.01
