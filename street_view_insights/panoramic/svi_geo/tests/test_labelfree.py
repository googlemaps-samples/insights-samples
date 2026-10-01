"""Unit tests for svi_geo.labelfree statistical core (pure, no network)."""

from __future__ import annotations

import math

import pytest

from svi_geo import eval as ev
from svi_geo import labelfree as lf

EXPECTED_METRIC_IDS = {
    "M1.1",
    "M1.2",
    "M1.3",
    "M1.4",
    "M1.5",
    "M1.6",
    "M1.7",
    "M2.1",
    "M2.2",
    "M2.3",
    "M2.4",
    "M2.5",
    "M2.6",
    "M3.1",
    "M3.2",
    "M3.3",
    "M3.4",
    "M3.5",
    "M3.6",
    "M3.7",
    "M4.1",
    "M4.2",
    "M4.3",
    "M4.4",
    "M4.5",
    "M4.6",
}


def test_measurement_invariants_and_formatting():
    m_ok = lf.Measurement.ok(0.75, 0.60, 0.85, n_clusters=8, placebo=0.12)
    assert m_ok.status == "ok"
    assert m_ok.value == pytest.approx(0.75)
    assert "0.750" in str(m_ok)

    m_miss = lf.Measurement.missing("no repeat pass in AOI")
    assert m_miss.status == "missing"
    assert m_miss.value is None
    assert str(m_miss) == "missing: no repeat pass in AOI"

    # value is None iff status is missing; NaN is never allowed as an ok value
    with pytest.raises(ValueError, match="missing"):
        lf.Measurement(status="ok", value=None)
    with pytest.raises(ValueError, match="missing"):
        lf.Measurement(status="missing", value=0.5, reason="bad")
    with pytest.raises(ValueError, match="reason"):
        lf.Measurement(status="missing", value=None, reason="")
    with pytest.raises(ValueError, match="finite"):
        lf.Measurement(status="ok", value=math.nan)


def test_block_ratio_ci_all_ones_and_two_cluster_point_estimate():
    ones = {f"b{i}": (4.0, 4.0) for i in range(6)}
    m = lf.block_ratio_ci(ones, seed=42)
    assert m.status == "ok"
    assert (m.value, m.ci_lo, m.ci_hi) == pytest.approx((1.0, 1.0, 1.0))

    # Exact two-cluster point estimate when min_clusters=2: (1 + 3) / (2 + 6) = 4 / 8 = 0.5
    two = {"b0": (1.0, 2.0), "b1": (3.0, 6.0)}
    m2 = lf.block_ratio_ci(two, min_clusters=2, seed=42)
    assert m2.status == "ok"
    assert m2.value == pytest.approx(0.5)

    # Fewer than 5 clusters with default min_clusters=5 gives missing
    m_small = lf.block_ratio_ci(
        {"b0": (1.0, 2.0), "b1": (2.0, 3.0), "b2": (1.0, 1.0), "b3": (0.0, 1.0)}
    )
    assert m_small.status == "missing"
    assert "5" in m_small.reason

    # Fixed seed is reproducible
    mixed = {f"b{i}": (float(i % 3), 3.0) for i in range(8)}
    a = lf.block_ratio_ci(mixed, seed=123)
    b = lf.block_ratio_ci(mixed, seed=123)
    assert (a.value, a.ci_lo, a.ci_hi) == (b.value, b.ci_lo, b.ci_hi)
    assert a.ci_lo < a.value < a.ci_hi


def test_eval_bootstrap_ci_supports_clusters_kwarg():
    per_pano = {
        "p0": (1.0, 1.0),
        "p1": (1.0, 1.0),
        "p2": (0.0, 1.0),
        "p3": (0.0, 1.0),
    }
    clusters = {"p0": "c0", "p1": "c0", "p2": "c1", "p3": "c1"}
    pt, lo, hi = ev.bootstrap_ci(per_pano, n_boot=200, seed=0, clusters=clusters)
    assert pt == pytest.approx(0.5)
    assert lo == pytest.approx(0.0) and hi == pytest.approx(1.0)


def test_paired_diff_ci_identical_constant_shift_and_mismatched_keys():
    before = {f"b{i}": 0.1 * i for i in range(6)}
    m_same = lf.paired_diff_ci(before, dict(before), seed=0)
    assert m_same.status == "ok"
    assert (m_same.value, m_same.ci_lo, m_same.ci_hi) == pytest.approx((0.0, 0.0, 0.0))

    after = {k: v + 0.2 for k, v in before.items()}
    m_shift = lf.paired_diff_ci(before, after, seed=0)
    assert m_shift.status == "ok"
    assert (m_shift.value, m_shift.ci_lo, m_shift.ci_hi) == pytest.approx((0.2, 0.2, 0.2))

    with pytest.raises(ValueError, match="mismatch"):
        lf.paired_diff_ci(before, {"b0": 0.1})


def test_kappa_perfect_chance_and_constant_missing():
    y = ["A", "B", "A", "B", "A", "B", "A", "B"]
    m_perf = lf.kappa(y, list(y))
    assert m_perf.status == "ok" and m_perf.value == pytest.approx(1.0)

    # Orthogonal balanced sequences -> chance agreement == 0.5, kappa == 0.0
    y1 = ["A", "A", "B", "B"] * 5
    y2 = ["A", "B", "A", "B"] * 5
    m_chance = lf.kappa(y1, y2)
    assert m_chance.status == "ok" and m_chance.value == pytest.approx(0.0, abs=1e-9)

    # Constant labels on both sides give missing, not 1
    m_const = lf.kappa(["A"] * 10, ["A"] * 10)
    assert m_const.status == "missing"
    assert m_const.value is None


def test_mcnemar_exact():
    m = lf.mcnemar_exact(0, 6)
    assert m.status == "ok"
    assert m.value == pytest.approx(0.03125)

    m_zero = lf.mcnemar_exact(0, 0)
    assert m_zero.status == "missing"


def test_adjacent_agreement_and_shuffle_baseline():
    # Two long runs of A then B: adjacent agreement is high (18/19), shuffle baseline is ~0.47
    seq = ["A"] * 10 + ["B"] * 10
    adj = lf.adjacent_agreement(seq)
    shuf = lf.shuffle_baseline(seq, n_shuffles=500, seed=0)
    assert adj == pytest.approx(18 / 19)
    assert 0.40 < shuf < 0.55
    assert adj > shuf


def test_decide_keep_table():
    # 1. Clear primary win, guard within delta -> keep
    res_keep = lf.decide_keep(
        primaries=[("M2.1", lf.Measurement.ok(0.18, 0.05, 0.30, n_clusters=8), "higher")],
        guards=[("M2.2", lf.Measurement.ok(-0.01, -0.03, 0.02, n_clusters=8), 0.05, "higher")],
    )
    assert res_keep["keep"] is True

    # 2. Primarywin but guard CI lies entirely beyond delta (-0.05) -> reject
    res_guard_fail = lf.decide_keep(
        primaries=[("M2.1", lf.Measurement.ok(0.18, 0.05, 0.30, n_clusters=8), "higher")],
        guards=[("M2.2", lf.Measurement.ok(-0.09, -0.14, -0.06, n_clusters=8), 0.05, "higher")],
    )
    assert res_guard_fail["keep"] is False
    assert "guard" in res_guard_fail["reason"].lower()

    # 3. Holm correction across 2 primaries: marginal primary (CI [0.005, 0.20], p ~ 0.04)
    # passes single test (p < 0.05) but fails Holm alpha/2 = 0.025 when paired with a null second primary
    res_holm_fail = lf.decide_keep(
        primaries=[
            ("M4.1", lf.Measurement.ok(0.1025, 0.005, 0.20, n_clusters=8), "higher"),
            ("M4.2", lf.Measurement.ok(-0.02, -0.15, 0.11, n_clusters=8), "lower"),
        ],
        guards=[],
    )
    assert res_holm_fail["keep"] is False
    assert "holm" in res_holm_fail["reason"].lower()

    # 4. Both primaries strongly significant -> passes Holm
    res_holm_pass = lf.decide_keep(
        primaries=[
            ("M4.1", lf.Measurement.ok(0.20, 0.08, 0.32, n_clusters=8), "higher"),
            ("M4.2", lf.Measurement.ok(-0.35, -0.50, -0.20, n_clusters=8), "lower"),
        ],
        guards=[("M4.3", lf.Measurement.ok(-0.02, -0.06, 0.02, n_clusters=8), 0.10, "higher")],
    )
    assert res_holm_pass["keep"] is True


def test_decide_keep_includes_cost_guard():
    prim = [("M2.1", lf.Measurement.ok(0.18, 0.05, 0.30, n_clusters=8), "higher")]
    res_ok = lf.decide_keep(primaries=prim, cost_diff_usd=-0.02, max_cost_delta_usd=0.0)
    assert res_ok["keep"] is True
    res_cost_fail = lf.decide_keep(primaries=prim, cost_diff_usd=0.03, max_cost_delta_usd=0.0)
    assert res_cost_fail["keep"] is False
    assert "cost guard" in res_cost_fail["reason"].lower()
    m_cost = lf.Measurement.ok(0.04, 0.01, 0.07, n_clusters=6)
    res_m_fail = lf.decide_keep(primaries=prim, cost_diff_usd=m_cost, max_cost_delta_usd=0.0)
    assert res_m_fail["keep"] is False
    assert "cost guard" in res_m_fail["reason"].lower()


def test_change_detection_signal_vs_shuffle_placebo():
    pairs_a = ["ASPHALT"] * 6 + ["CONCRETE"] * 6 + ["GRAVEL"] * 6
    pairs_b = ["ASPHALT"] * 6 + ["CONCRETE"] * 5 + ["ASPHALT"] + ["GRAVEL"] * 6
    blocks = [f"b{i // 3}" for i in range(len(pairs_a))]
    m = lf.repeat_pass_agreement_vs_placebo(pairs_a, pairs_b, blocks, seed=7)
    assert m.status == "ok"
    assert m.value is not None and m.placebo is not None
    assert m.value > 0.90
    assert m.placebo < 0.45
    assert m.value - m.placebo >= 0.45
    assert "consistency != accuracy" in m.disclosure


def test_metric_docs_cover_every_metric_and_render_summary():
    assert set(lf.METRIC_DOCS.keys()) == EXPECTED_METRIC_IDS
    for mid, doc in lf.METRIC_DOCS.items():
        assert doc.get("measures"), f"{mid} missing 'measures'"
        assert doc.get("does_not_measure"), f"{mid} missing 'does_not_measure'"

    summary = lf.render_summary(
        {
            "date": "2026-09-30",
            "commit": "15a622d",
            "manifests": {"tune": "sha256:aaa", "heldout": "sha256:bbb"},
            "spend": {"usd": 1.23, "calls": 120, "input_tokens": 180000, "output_tokens": 90000},
            "metrics": {
                "M1.1": lf.Measurement.ok(0.78, 0.65, 0.88, n_clusters=8),
                "M1.6": lf.Measurement.missing("no repeat pass in AOI"),
                "M2.6": lf.Measurement.ok(
                    0.82, 0.70, 0.91, n_clusters=8, placebo=0.08, disclosure=lf.TEACHER_DISCLOSURE
                ),
            },
        }
    )
    assert "same model family; not accuracy" in summary
    assert "sha256:aaa" in summary and "sha256:bbb" in summary
    assert "$1.23" in summary
    assert "missing: no repeat pass in AOI" in summary
    assert lf.METRIC_DOCS["M1.1"]["does_not_measure"] in summary


def test_run_labelfree_eval_repeat_pairs_constant_kappa_and_teacher_tiles(tmp_path, monkeypatch):
    """Regression test for F1, F2, F3:
    - M2.3 and M3.3 are computed from cross-day repeat_pairs (no 0.75/0.8 fallback or M2.2/M3.2 copy).
    - Constant-label M3.1 and M3.5 preserve status='missing' (never overwritten with 1.0 or 0.0).
    - ask_teacher receives 4 zoom tiles via extra_images from tea.tiles().
    """
    import asyncio
    import datetime as dt
    import sys
    from pathlib import Path

    import pandas as pd

    from svi_geo import data, rosette
    from svi_geo import gemini_client as gc
    from svi_geo import manifest as mf
    from svi_geo import simulate as sim
    from svi_geo import teacher as tea
    from svi_geo import usecases as uc

    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import run_labelfree_eval as rle

    t1 = dt.datetime(2024, 5, 1, 12, 0, tzinfo=dt.timezone.utc)
    t2 = dt.datetime(2024, 6, 15, 14, 0, tzinfo=dt.timezone.utc)
    fr1 = sim.synthetic_frames(12, 10.0, 28.0500, -81.9600, travel_deg=0.0, seq_id="S1", t0=t1)
    fr2 = sim.synthetic_frames(12, 10.0, 28.0500, -81.95998, travel_deg=0.0, seq_id="S2", t0=t2)
    fr = pd.concat([fr1, fr2], ignore_index=True)
    fr["gcs_uri"] = [
        data.gcs_uri_for("test-bucket", s, o)
        for s, o in zip(fr["snapshot_id"], fr["observation_id"], strict=True)
    ]
    manifest = mf.build_manifest(fr, aoi="tune", seed=7)
    assert len(manifest["repeat_pairs"]) >= 1

    # Spy on tea.ask_teacher to verify extra_images contains 4 zoom tiles from tea.tiles()
    seen_extra_counts: list[int] = []
    orig_ask_teacher = tea.ask_teacher

    async def _spy_ask_teacher(*args, **kwargs):
        extra = kwargs.get("extra_images")
        seen_extra_counts.append(len(extra) if extra is not None else 0)
        return await orig_ask_teacher(*args, **kwargs)

    monkeypatch.setattr(tea, "ask_teacher", _spy_ask_teacher)

    class _ConstantSurfaceBackend(rle._OfflineSmokeBackend):
        async def generate(self, parts, schema, code_execution=False, **kw):
            if getattr(schema, "__name__", "") == "WindowLabel":
                txt = (
                    '{"observations": ['
                    '{"asset": "ROAD", "side": "CENTER", "present": false, "material": null, "condition": null, "confidence": 0.95},'
                    '{"asset": "SIDEWALK", "side": "LEFT", "present": false, "material": null, "condition": null, "confidence": 0.9},'
                    '{"asset": "SIDEWALK", "side": "RIGHT", "present": false, "material": null, "condition": null, "confidence": 0.9}'
                    "]}"
                )
                return gc.RawReply(
                    text=txt,
                    usage={"prompt_token_count": 50, "candidates_token_count": 20},
                )
            return await super().generate(parts, schema, code_execution=code_execution, **kw)

    s_runner = gc.GeminiRunner(_ConstantSurfaceBackend(gc.DEFAULT_MODEL))
    t_runner = gc.GeminiRunner(rle._OfflineSmokeBackend(tea.teacher_model()))
    t_cache = tea.TeacherCache(tmp_path / "teacher_cache.jsonl")
    intr = rosette.DEFAULT_INTRINSICS

    # 1. With constant ABSENT labels on both sides, Cohen's kappa is undefined and MUST remain 'missing'.
    m3 = asyncio.run(
        rle.evaluate_uc3(
            fr,
            manifest,
            rle._synthetic_frame_bytes,
            s_runner,
            t_runner,
            t_cache,
            intr,
            uc.Variant(name="baseline"),
            seed=7,
        )
    )
    assert m3["M3.1"].status == "missing"
    assert m3["M3.1"].value is None
    assert m3["M3.5"].status == "missing"
    assert m3["M3.5"].value is None
    assert m3["M3.3"].status == "ok"
    assert seen_extra_counts and all(c == 4 for c in seen_extra_counts)

    # 2. When uc2_sequences is empty (so retest_recalls is empty) and repeat_pairs has panos with
    # no detections, M2.3 MUST be 'missing' (never fallback literal 0.75).
    class _EmptyDetBackend(rle._OfflineSmokeBackend):
        async def generate(self, parts, schema, code_execution=False, **kw):
            if getattr(schema, "__name__", "") == "FrameDetections":
                return gc.RawReply(
                    text='{"detections": []}',
                    usage={"prompt_token_count": 10, "candidates_token_count": 5},
                )
            return await super().generate(parts, schema, code_execution=code_execution, **kw)

    empty_runner = gc.GeminiRunner(_EmptyDetBackend(gc.DEFAULT_MODEL))
    m2_empty = asyncio.run(
        rle.evaluate_uc2(
            fr,
            manifest,
            rle._synthetic_frame_bytes,
            empty_runner,
            t_runner,
            t_cache,
            intr,
            uc.Variant(name="baseline"),
            seed=7,
        )
    )
    assert m2_empty["M2.2"].status == "missing"
    assert m2_empty["M2.3"].status == "missing"
    assert m2_empty["M2.3"].value is None
