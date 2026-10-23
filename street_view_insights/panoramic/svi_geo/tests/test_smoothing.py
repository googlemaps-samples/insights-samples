import math

import pytest

from svi_geo import geo, smoothing


def test_majority_filter_removes_single_blip():
    assert smoothing.majority_filter(list("AAGAA")) == list("AAAAA")
    assert smoothing.majority_filter(list("AAGGG")) == list("AAGGG")


def test_viterbi_removes_blip_but_keeps_real_change():
    assert smoothing.viterbi(list("AAAGAAA"), [0.8] * 7, stay_prob=0.9) == list("AAAAAAA")
    obs = list("AAAAAGGGGG")
    assert smoothing.viterbi(obs, [0.8] * 10, stay_prob=0.9) == obs


def _east_track(n=10, spacing=10.0):
    lat, lng = [], []
    for i in range(n):
        la, lo, _ = geo.enu_to_lla(i * spacing, 0.0, 0.0, 48.8, 2.37)
        lat.append(float(la))
        lng.append(float(lo))
    return lat, lng


def test_ten_eastbound_panos_make_one_90m_line():
    lat, lng = _east_track()
    (seg,) = smoothing.segments_from_sequence(lat, lng, ["ASPHALT"] * 10)
    assert seg["length_m"] == pytest.approx(90.0, abs=1.0)
    assert seg["n_panos"] == 10


def test_left_offset_of_eastbound_lands_north():
    lat, lng = _east_track()
    (seg,) = smoothing.segments_from_sequence(lat, lng, ["S"] * 10, offset_m=4.0)
    ys = [c[1] for c in seg["geometry"].coords]
    assert min(ys) > 48.8 + 3.5 / 111_000


def test_breaks_split_and_label_changes_split():
    lat, lng = _east_track()
    brk = [False] * 10
    brk[5] = True
    segs = smoothing.segments_from_sequence(lat, lng, ["A"] * 10, breaks=brk)
    assert len(segs) == 2
    segs = smoothing.segments_from_sequence(lat, lng, list("AAAAAGGGGG"))
    assert [s["label"] for s in segs] == ["A", "G"]
    # consecutive segments meet half-way (total ~= 90 m)
    assert sum(s["length_m"] for s in segs) == pytest.approx(90.0, abs=1.0)
    rows = smoothing.to_wkt_rows(segs, asset="ROAD")
    assert rows[0]["wkt"].startswith("LINESTRING") and rows[0]["asset"] == "ROAD"


def test_flicker_per_km():
    assert smoothing.flicker_per_km(list("AGAG"), 1000.0) == 3
    assert math.isclose(smoothing.flicker_per_km(list("AAAA"), 500.0), 0.0)


def test_low_confidence_observation_is_not_evidence_against_itself():
    # with 3 states, conf 0.2 < 1/3 used to make the observed label LESS likely than others
    assert smoothing.viterbi(["A"], [0.1], states=["B", "C", "A"]) == ["A"]


# ----------------------------------------------------------------------------- Task 9


def test_side_offsets_put_left_north_and_right_south_of_an_eastbound_track():
    assert smoothing.side_offset_m("LEFT", 6.0) == 6.0
    assert smoothing.side_offset_m("RIGHT", 6.0) == -6.0
    assert smoothing.side_offset_m("CENTER", 6.0) == 0.0
    lat, lng = _east_track()
    track_lat = lat[0]
    for side, north in (("LEFT", True), ("RIGHT", False)):
        (seg,) = smoothing.segments_from_sequence(
            lat, lng, ["S"] * 10, offset_m=smoothing.side_offset_m(side, 6.0)
        )
        ys = [c[1] for c in seg["geometry"].coords]
        assert (min(ys) > track_lat) if north else (max(ys) < track_lat), side


A, X = "Concrete", smoothing.ABSENT


def test_absent_run_inside_a_material_run_stays_absent():
    labels = [A] * 3 + [X] * 3 + [A] * 3
    out = smoothing.viterbi(labels, [0.85] * 9, stay_prob=0.9, absent_label=X)
    assert out == labels


def test_single_absent_blip_is_smoothed_but_none_stays_none():
    out = smoothing.viterbi([A, A, X, A, A], [0.85] * 5, stay_prob=0.9, absent_label=X)
    assert out == [A] * 5
    out = smoothing.viterbi([A, A, None, A, A], [0.85, 0.85, 0.0, 0.85, 0.85], absent_label=X)
    assert out == [A, A, None, A, A]  # no answer is not turned into a material


def test_chain_is_decoded_independently_across_breaks():
    labels = [A, A, A, "Gravel"]
    conf = [0.9, 0.9, 0.9, 0.6]
    assert smoothing.viterbi(labels, conf, stay_prob=0.95) == [A] * 4
    brk = [False, False, False, True]
    assert smoothing.viterbi(labels, conf, stay_prob=0.95, breaks=brk) == labels


def test_gap_breaks_and_length_exclude_long_gaps():
    lat, lng = _east_track()  # 10 panos, 10 m apart
    lat2, lng2 = [], []
    for i in range(3):
        la, lo, _ = geo.enu_to_lla(200.0 + 10 * i, 0.0, 0.0, 48.8, 2.37)
        lat2.append(float(la))
        lng2.append(float(lo))
    brk = smoothing.gap_breaks(lat + lat2, lng + lng2, max_gap_m=35.0)
    assert brk == [False] * 10 + [True, False, False]
    total = smoothing.drive_length_m(lat + lat2, lng + lng2, max_gap_m=35.0)
    assert total == pytest.approx(90.0 + 20.0, abs=1.0)


def test_no_segment_is_emitted_for_absent():
    lat, lng = _east_track()
    segs = smoothing.segments_from_sequence(lat, lng, [A] * 4 + [X] * 6)
    assert [s["label"] for s in segs] == [A]


def test_pick_slot_distinguishes_absent_from_no_answer():
    from svi_geo import schemas

    wl = schemas.WindowLabel(
        observations=[
            {"asset": "ROAD", "side": "CENTER", "present": True, "material": "Paved Asphalt",
             "confidence": 0.9},
            {"asset": "SIDEWALK", "side": "LEFT", "present": False, "confidence": 0.7},
            {"asset": "SIDEWALK", "side": "RIGHT", "present": True, "confidence": 0.6},
        ]
    )  # fmt: skip
    assert smoothing.pick_slot(wl, "ROAD", "CENTER") == ("Paved Asphalt", 0.9)
    assert smoothing.pick_slot(wl, "SIDEWALK", "LEFT") == (smoothing.ABSENT, 0.7)
    assert smoothing.pick_slot(wl, "SIDEWALK", "RIGHT") == (None, 0.0)  # present, no material
    assert smoothing.pick_slot(wl, "FENCE", "LEFT") == (None, 0.0)  # not answered
    assert smoothing.pick_slot(None, "ROAD", "CENTER") == (None, 0.0)
