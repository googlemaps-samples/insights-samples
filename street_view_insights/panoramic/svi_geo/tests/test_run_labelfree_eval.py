"""Offline unit tests for svi_geo/manifest.py and scripts/run_labelfree_eval.py (Task T8 RED)."""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

from svi_geo import data
from svi_geo import labelfree as lf
from svi_geo import manifest as mf
from svi_geo import simulate as sim

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _make_synthetic_aoi_frames() -> pd.DataFrame:
    t1 = dt.datetime(2024, 5, 1, 12, 0, tzinfo=dt.timezone.utc)
    t2 = dt.datetime(2024, 6, 15, 14, 0, tzinfo=dt.timezone.utc)
    # Two parallel 12-pano sequences on different dates + two more sequences
    fr1 = sim.synthetic_frames(15, 10.0, 28.0500, -81.9600, travel_deg=0.0, seq_id="S1", t0=t1)
    fr2 = sim.synthetic_frames(15, 10.0, 28.0500, -81.95998, travel_deg=0.0, seq_id="S2", t0=t2)
    fr3 = sim.synthetic_frames(15, 10.0, 28.0510, -81.9610, travel_deg=90.0, seq_id="S3", t0=t1)
    fr4 = sim.synthetic_frames(15, 10.0, 28.0490, -81.9590, travel_deg=180.0, seq_id="S4", t0=t2)
    all_fr = pd.concat([fr1, fr2, fr3, fr4], ignore_index=True)
    all_fr["gcs_uri"] = [
        data.gcs_uri_for("test-bucket", s, o)
        for s, o in zip(all_fr["snapshot_id"], all_fr["observation_id"], strict=True)
    ]
    return all_fr


def test_build_manifest_is_deterministic_and_verifies_hash():
    fr = _make_synthetic_aoi_frames()
    m1 = mf.build_manifest(fr, aoi="tune", seed=7)
    m2 = mf.build_manifest(fr, aoi="tune", seed=7)
    assert m1["sha256"] == m2["sha256"]
    assert len(m1["uc1_targets"]) == 8
    assert len(m1["uc4_targets"]) == 10
    assert len(m1["uc2_sequences"]) >= 1
    assert len(m1["uc3_sequences"]) >= 1
    assert len(m1["repeat_pairs"]) >= 1
    assert len(m1["blocks"]) >= 5

    # Hash check passes on identical manifest, raises on mismatch
    mf.assert_same_manifest(m1, m2)
    m_diff = dict(m2, sha256="0" * 64)
    with pytest.raises(ValueError, match="manifest sha256 mismatch"):
        mf.assert_same_manifest(m1, m_diff)


def test_run_labelfree_eval_offline_writes_results_summary_and_calls(tmp_path):
    import run_labelfree_eval as rle

    fr = _make_synthetic_aoi_frames()
    out_dir = tmp_path / "eval_out"
    res = rle.run_offline_smoke(frames=fr, aoi="tune", out_dir=out_dir, seed=7)
    assert res["aoi"] == "tune"
    assert (out_dir / "results.json").is_file()
    assert (out_dir / "summary.md").is_file()
    assert (out_dir / "calls.jsonl").is_file()

    loaded = json.loads((out_dir / "results.json").read_text(encoding="utf-8"))
    assert "manifests" in loaded and "tune" in loaded["manifests"]
    assert "metrics" in loaded
    for mid in lf.METRIC_DOCS:
        assert mid in loaded["metrics"], f"missing metric {mid}"
        m = loaded["metrics"][mid]
        assert m["status"] in ("ok", "missing")
        if m["status"] == "missing":
            assert m["value"] is None and m["reason"]
        else:
            assert m["value"] is not None

    summary_md = (out_dir / "summary.md").read_text(encoding="utf-8")
    assert lf.TEACHER_DISCLOSURE in summary_md
    assert loaded["manifests"]["tune"] in summary_md

    calls_lines = (out_dir / "calls.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(calls_lines) >= 1
    first_call = json.loads(calls_lines[0])
    for req_key in ("model", "input_tokens", "output_tokens", "usd", "prompt_version"):
        assert req_key in first_call
