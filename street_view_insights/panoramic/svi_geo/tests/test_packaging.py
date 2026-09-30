import svi_geo


def test_import_and_version():
    assert isinstance(svi_geo.__version__, str)
    assert svi_geo.__version__.count(".") == 2


def test_ruff_is_clean_from_the_repository_root():
    """`ruff check street_view_insights/panoramic` from the repo root must pass (notebooks
    included), not only from inside svi_geo/."""
    import shutil
    import subprocess
    import sys
    from pathlib import Path

    import pytest

    ruff = shutil.which("ruff") or str(Path(sys.executable).with_name("ruff"))
    if not Path(ruff).exists():
        pytest.skip("ruff not installed")
    root = Path(__file__).resolve().parents[4]
    res = subprocess.run(
        [ruff, "check", "--no-cache", "street_view_insights/panoramic"],
        cwd=root, capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert res.returncode == 0, res.stdout[-3000:]


def test_readme_evaluation_section_has_no_stale_pass_gates():
    """Retracted / self-consistency numbers must not be framed as passing quality gates."""
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "README.md").read_text()
    evaluation = text.split("## Evaluation", 1)[1]
    assert "PASS" not in evaluation and "FAIL" not in evaluation
    assert "was not written" not in evaluation  # scripts/make_label_kit.py exists
    assert (Path(__file__).resolve().parents[1] / "scripts" / "make_label_kit.py").exists()
