"""check_executed_notebooks.py: acceptance checks on nbconvert-executed notebooks (Task 12)."""

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "check_executed_notebooks.py"


@pytest.fixture(scope="module")
def chk():
    spec = importlib.util.spec_from_file_location("check_executed_notebooks", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _nb(*texts, error=False):
    cells = [
        {"cell_type": "code", "source": "", "metadata": {}, "execution_count": i,
         "outputs": [{"output_type": "stream", "name": "stdout", "text": t}]}
        for i, t in enumerate(texts)
    ]  # fmt: skip
    if error:
        cells[-1]["outputs"].append(
            {"output_type": "error", "ename": "RuntimeError", "evalue": "boom", "traceback": []}
        )
    return {"cells": cells, "metadata": {}, "nbformat": 4, "nbformat_minor": 5}


OLD_GOOD = "Gemini calls=12 requests=12 failures=0 skipped_budget=0 est_cost=$0.0412\n"

REF_SNAP = "snapshots=21d75cd4,58e1384f rosettes=42 null_pano_id=28 sequences=5 bq_bytes=1831000000 bq_cached=1\n"
REF_VAR = "variant=final\n"
REF_GEM = (
    "Gemini calls=12 requests=12 failures=0 skipped_budget=0 "
    "input=14200 (cached 0) output=1850 (thinking 1200) tool_intermediate=320 "
    "est_cost=$0.0412 ceiling=$0.1000 code_exec_runs=1 ok=1 fallbacks=0\n"
)
REF_IMG = "black_fraction_max=0.0031 dark_pixel_max=0.0120 redaction_overlap_max=0.0000\n"
REF_CEXEC = "code_exec_agreement=agree(eave_delta_deg=0.85,tol=4.0)\n"
REF_MAP = "map_rendered=1 artefacts=3 peak_rss_mb=640.5\n"


def _full_lines(
    result_line: str = "accepted_edges=7\n", gem_line: str = REF_GEM
) -> tuple[str, ...]:
    return (REF_SNAP, REF_VAR, REF_IMG, gem_line, result_line, REF_CEXEC, REF_MAP)


def test_checker_requires_rosette_variant_codeexec_cost_rss_lines(chk):
    # Old fixture text without snapshots/rosettes, variant=final, code_exec, map/rss MUST fail
    old_nb = _nb("black_fraction_max=0.0031\n", OLD_GOOD, "accepted_edges=7\n")
    problems, _ = chk.check_notebook(old_nb, "roof_edge_tracing")
    joined = " | ".join(problems)
    assert "rosettes=" in joined or "snapshots=" in joined
    assert "variant=final" in joined
    assert "code_exec_agreement=" in joined
    assert "peak_rss_mb=" in joined


def test_a_clean_run_passes_and_reports_stats(chk):
    nb = _nb(*_full_lines("accepted_edges=7\n"))
    problems, stats = chk.check_notebook(nb, "roof_edge_tracing")
    assert problems == [], f"Unexpected problems: {problems}"
    assert stats["gemini_calls"] == 12
    assert stats["gemini_failures"] == 0
    assert stats["est_cost_usd"] == pytest.approx(0.0412)
    assert stats["accepted_edges"] == 7
    assert stats["black_fraction_max"] == pytest.approx(0.0031)
    assert stats["rosettes"] == 42
    assert stats["null_pano_id"] == 28
    assert stats["code_exec_runs"] == 1
    assert stats["code_exec_ok"] == 1
    assert stats["peak_rss_mb"] == pytest.approx(640.5)


def test_error_outputs_failures_black_and_empty_results_are_reported(chk):
    bad = REF_GEM.replace("failures=0", "failures=2").replace(
        "est_cost=$0.0412", "est_cost=$0.9500"
    )
    nb = _nb(
        REF_SNAP,
        REF_VAR,
        "detection views: black_fraction_max=0.0200 dark_pixel_max=0.01 redaction_overlap_max=0.0\n",
        bad,
        "located_entities=0\n",
        REF_CEXEC,
        REF_MAP,
        error=True,
    )
    problems, _ = chk.check_notebook(nb, "analyze_sequential_images")
    text = " | ".join(problems)
    assert "error output" in text and "RuntimeError" in text
    assert "failures=2" in text
    assert "black_fraction_max=0.0200" in text
    assert "located_entities=0" in text
    assert "ceiling" in text


def test_missing_lines_are_problems_not_passes(chk):
    problems, _ = chk.check_notebook(_nb("nothing here\n"), "surface_material_detection")
    text = " | ".join(problems)
    assert "no 'Gemini calls=' line" in text
    assert "no black_fraction_max" in text
    assert "no 'segments=' line" in text


def test_nan_black_fraction_needs_another_measured_value(chk):
    nb = _nb(
        REF_SNAP,
        REF_VAR,
        "presence views: black_fraction_max=nan dark_pixel_max=0.0 redaction_overlap_max=0.0\n",
        REF_GEM,
        "centred_views=3\n",
        REF_CEXEC,
        REF_MAP,
    )
    problems, _ = chk.check_notebook(nb, "house_image_discovery_with_cost")
    assert any("no black_fraction_max" in p for p in problems)
    nb = _nb(
        REF_SNAP,
        REF_VAR,
        "detection views: black_fraction_max=0.0 dark_pixel_max=0.0 redaction_overlap_max=0.0\npresence views: black_fraction_max=nan\n",
        REF_GEM,
        "located_entities=4\n",
        REF_CEXEC,
        REF_MAP,
    )
    problems, stats = chk.check_notebook(nb, "analyze_sequential_images")
    assert problems == [] and stats["black_fraction_max"] == 0.0


def test_cost_and_calls_come_from_the_last_summary_line(chk):
    first = REF_GEM
    last = REF_GEM.replace("calls=12", "calls=20").replace("0.0412", "0.0700")
    nb = _nb(
        REF_SNAP,
        REF_VAR,
        REF_IMG,
        first,
        last,
        "segments=5\n",
        REF_CEXEC,
        REF_MAP,
    )
    problems, stats = chk.check_notebook(nb, "surface_material_detection")
    assert problems == []
    assert stats["gemini_calls"] == 20 and stats["est_cost_usd"] == pytest.approx(0.07)


def test_main_exits_nonzero_on_problems(chk, tmp_path, capsys):
    good = tmp_path / "roof_edge_tracing.ipynb"
    good.write_text(json.dumps(_nb(*_full_lines("accepted_edges=1\n"))))
    assert chk.main([str(good)]) == 0
    bad = tmp_path / "surface_material_detection.ipynb"
    bad.write_text(json.dumps(_nb(OLD_GOOD)))
    assert chk.main([str(good), str(bad)]) == 1
    assert "surface_material_detection" in capsys.readouterr().out
    with pytest.raises(ValueError, match="unknown notebook"):
        chk.check_notebook(_nb(REF_GEM), "something_else")


def test_overlay_grid_marks_rejections(tmp_path):
    import numpy as np

    grid_script = Path(__file__).parents[1] / "scripts" / "make_overlay_grid.py"
    spec = importlib.util.spec_from_file_location("make_overlay_grid", grid_script)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    img = np.full((240, 320, 3), 200, dtype=np.uint8)
    out_png = tmp_path / "qa_grid.png"
    meta = mod.render_overlay_grid(
        panels=[
            {
                "image": img,
                "title": "capture_001",
                "accepted_boxes": [(40, 40, 140, 140, "HOUSE")],
                "rejected_boxes": [(160, 50, 280, 180, "low_post_support")],
                "accepted_edges": [[(20.0, 60.0), (200.0, 60.0)]],
                "rejected_edges": [([(20.0, 190.0), (220.0, 190.0)], "wall_decoy")],
            }
        ],
        out_path=out_png,
        notebook_name="roof_edge_tracing",
    )
    assert out_png.exists() and out_png.stat().st_size > 1000
    assert meta["n_accepted"] == 2
    assert meta["n_rejected"] == 2
    assert "wall_decoy" in meta["rejection_reasons"]
    assert "low_post_support" in meta["rejection_reasons"]
