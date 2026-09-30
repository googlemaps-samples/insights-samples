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
