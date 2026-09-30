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


GOOD = "Gemini calls=12 requests=12 failures=0 skipped_budget=0 est_cost=$0.0412\n"


def test_a_clean_run_passes_and_reports_stats(chk):
    nb = _nb("black_fraction_max=0.0031\n", GOOD, "accepted_edges=7\n")
    problems, stats = chk.check_notebook(nb, "roof_edge_tracing")
    assert problems == []
    assert stats == {"gemini_calls": 12, "gemini_failures": 0, "est_cost_usd": 0.0412,
                     "accepted_edges": 7, "black_fraction_max": 0.0031}  # fmt: skip


def test_error_outputs_failures_black_and_empty_results_are_reported(chk):
    bad = GOOD.replace("failures=0", "failures=2")
    nb = _nb("detection views: black_fraction_max=0.0200\n", bad, "located_entities=0\n",
             error=True)  # fmt: skip
    problems, _ = chk.check_notebook(nb, "analyze_sequential_images")
    text = " | ".join(problems)
    assert "error output" in text and "RuntimeError" in text
    assert "failures=2" in text
    assert "black_fraction_max=0.0200" in text
    assert "located_entities=0" in text


def test_missing_lines_are_problems_not_passes(chk):
    problems, _ = chk.check_notebook(_nb("nothing here\n"), "surface_material_detection")
    text = " | ".join(problems)
    assert "no 'Gemini calls=' line" in text
    assert "no black_fraction_max" in text
    assert "no 'segments=' line" in text


def test_nan_black_fraction_needs_another_measured_value(chk):
    nb = _nb("presence views: black_fraction_max=nan\n", GOOD, "centred_views=3\n")
    problems, _ = chk.check_notebook(nb, "house_image_discovery_with_cost")
    assert any("no black_fraction_max" in p for p in problems)
    nb = _nb("detection views: black_fraction_max=0.0\npresence views: black_fraction_max=nan\n",
             GOOD, "located_entities=4\n")  # fmt: skip
    problems, stats = chk.check_notebook(nb, "analyze_sequential_images")
    assert problems == [] and stats["black_fraction_max"] == 0.0


def test_cost_and_calls_come_from_the_last_summary_line(chk):
    first = GOOD
    last = GOOD.replace("calls=12", "calls=20").replace("0.0412", "0.0700")
    nb = _nb("black_fraction_max=0.001\n", first, last, "segments=5\n")
    _, stats = chk.check_notebook(nb, "surface_material_detection")
    assert stats["gemini_calls"] == 20 and stats["est_cost_usd"] == pytest.approx(0.07)


def test_main_exits_nonzero_on_problems(chk, tmp_path, capsys):
    good = tmp_path / "roof_edge_tracing.ipynb"
    good.write_text(json.dumps(_nb("black_fraction_max=0.0\n", GOOD, "accepted_edges=1\n")))
    assert chk.main([str(good)]) == 0
    bad = tmp_path / "surface_material_detection.ipynb"
    bad.write_text(json.dumps(_nb(GOOD)))
    assert chk.main([str(good), str(bad)]) == 1
    assert "surface_material_detection" in capsys.readouterr().out
    with pytest.raises(ValueError, match="unknown notebook"):
        chk.check_notebook(_nb(GOOD), "something_else")
