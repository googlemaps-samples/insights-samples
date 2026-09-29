import os

from svi_geo import notebook_eval


def test_eval_writes_files(tmp_path):
    os.chdir(tmp_path)
    notebook_eval.evaluate_notebook_v2(None)
    assert os.path.exists("svi_geo/data/notebook_eval_v2_report.json")
    assert os.path.exists("svi_geo/data/notebook_eval_v2_report.md")
