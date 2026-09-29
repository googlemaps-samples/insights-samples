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
