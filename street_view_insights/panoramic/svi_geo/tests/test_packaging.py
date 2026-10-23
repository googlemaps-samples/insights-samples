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


def test_dependencies_are_pinned_and_the_lock_file_has_hashes():
    import re
    from pathlib import Path

    import tomllib

    pkg = Path(__file__).resolve().parents[1]
    proj = tomllib.loads((pkg / "pyproject.toml").read_text())["project"]
    specs = list(proj["dependencies"])
    for extra in proj["optional-dependencies"].values():
        specs += extra
    for spec in specs:
        # an exact pin, or a lower bound together with an upper bound
        assert "==" in spec or (">=" in spec and "<" in spec.replace("<=", "")), spec
    lock_checks = [
        ("requirements.lock", proj["dependencies"]),
        (
            "requirements-notebooks.lock",
            proj["dependencies"] + proj["optional-dependencies"]["notebooks"],
        ),
        ("requirements-dev.lock", proj["dependencies"] + proj["optional-dependencies"]["dev"]),
    ]
    for lock_filename, expected_specs in lock_checks:
        lock = (pkg / lock_filename).read_text()
        pinned = re.findall(r"^([A-Za-z0-9_.\-]+)==[^\s]+ \\$", lock, re.M)
        assert pinned, f"{lock_filename} has no == pins"
        for block in re.split(r"\n(?=[A-Za-z0-9_.\-]+==)", lock.split("\n", 1)[1]):
            if "==" in block.split("\n", 1)[0]:
                assert "--hash=sha256:" in block, f"{lock_filename}: {block.split(chr(10), 1)[0]}"
        names = {n.lower().replace("_", "-") for n in pinned}
        for spec in expected_specs:
            name = re.split(r"[<>=~!\[ ]", spec, maxsplit=1)[0].lower()
            assert name in names, f"{name} missing from {lock_filename}"
