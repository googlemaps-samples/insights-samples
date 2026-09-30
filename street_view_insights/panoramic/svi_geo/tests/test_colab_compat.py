"""Colab compatibility: svi_geo must install on Colab without upgrading preinstalled packages.

`constraints/colab-*.txt` are Colab's own pip-freeze files (googlecolab/backend-info, commit
and date in each header). The fast tests check svi_geo's version specifiers against them;
the slow test builds Colab-equivalent virtualenvs (Python 3.12 + runtime 2026.07, Python 3.13
+ the current runtime, and an opencv 4.14 row) and runs the offline suite inside each one.
"""

from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import tomllib
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

PKG = Path(__file__).resolve().parents[1]
CONSTRAINTS = PKG / "constraints"
COLAB_FILES = ("colab-2026.07.txt", "colab-current.txt")
PIN = re.compile(r"^([A-Za-z0-9_.\-]+)==(\S+)$")


def _pins(path: Path) -> dict[str, Version]:
    out = {}
    for line in path.read_text().splitlines():
        m = PIN.match(line.strip())
        if m:
            out[canonicalize_name(m.group(1))] = Version(m.group(2))
    return out


def _requirements() -> list[Requirement]:
    proj = tomllib.loads((PKG / "pyproject.toml").read_text())["project"]
    specs = list(proj["dependencies"])
    for extra in ("notebooks", "dev"):
        specs += proj["optional-dependencies"][extra]
    return [Requirement(s) for s in specs]


@pytest.mark.parametrize("fname", COLAB_FILES)
def test_lower_bounds_admit_colab_versions(fname):
    """Every direct dependency that Colab preinstalls must accept Colab's version as is."""
    pins = _pins(CONSTRAINTS / fname)
    checked, rejected = [], []
    for req in _requirements():
        v = pins.get(canonicalize_name(req.name))
        if v is None:
            continue  # not preinstalled on Colab: pip installs it, nothing is upgraded
        checked.append(req.name)
        if not req.specifier.contains(v, prereleases=True):
            rejected.append(f"{req} rejects Colab's {req.name}=={v}")
    assert not rejected, "\n".join(rejected)
    # the core numeric stack must actually be covered by the check
    for name in ("numpy", "pandas", "scipy", "scikit-learn", "pyarrow", "google-genai"):
        assert name in checked, f"{name} not found in {fname}"


@pytest.mark.parametrize("fname", COLAB_FILES)
def test_constraint_files_have_provenance(fname):
    head = "\n".join((CONSTRAINTS / fname).read_text().splitlines()[:8])
    assert re.search(
        r"https://github\.com/googlecolab/backend-info/blob/[0-9a-f]{40}/pip-freeze\.txt", head
    ), "source URL with the backend-info commit SHA"
    assert re.search(r"committed \d{4}-\d{2}-\d{2}", head), "source commit date"
    assert re.search(r"fetched \d{4}-\d{2}-\d{2}", head), "fetch date"
    assert len(_pins(CONSTRAINTS / fname)) > 100, "a full freeze, not a hand-picked subset"


# APIs added after numpy 2.0 / pandas 2.2 (Colab 2026.07 ships numpy 2.0.2, pandas 2.2.2).
NEW_NUMPY = {"unstack", "cumulative_sum", "cumulative_prod", "matvec", "vecmat"}
NEW_PANDAS = {"col"}
SOURCE_DIRS = [PKG / "svi_geo", PKG / "scripts", PKG / "tests"]


def test_no_new_numpy_pandas_only_apis():
    hits = []
    for d in SOURCE_DIRS:
        for f in sorted(d.rglob("*.py")):
            if f.name == Path(__file__).name:
                continue
            for node in ast.walk(ast.parse(f.read_text())):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                    mod, attr = node.value.id, node.attr
                    if (mod in ("np", "numpy") and attr in NEW_NUMPY) or (
                        mod in ("pd", "pandas") and attr in NEW_PANDAS
                    ):
                        hits.append(f"{f.relative_to(PKG)}:{node.lineno} {mod}.{attr}")
    assert not hits, hits


def test_notebook_install_cell_mentions_colab_preinstalled_versions():
    import nbformat

    for nb_path in sorted((PKG.parent / "notebooks").glob("*.ipynb")):
        nb = nbformat.read(nb_path, as_version=4)
        install = next(c.source for c in nb.cells if 'pip", "install"' in c.source)
        assert "Colab" in install and "preinstalled" in install, nb_path.name


# --------------------------------------------------------------------------- slow venv matrix


@pytest.mark.slow
def test_colab_venv_runs_offline_suite(tmp_path):
    """Build the Colab-equivalent venvs and run `pytest -m "not live and not slow"` in each."""
    uv = shutil.which("uv") or str(Path(sys.executable).with_name("uv"))
    if not Path(uv).exists() and shutil.which("python3.12") is None:
        pytest.skip("neither uv nor python3.12 is available to build a Python 3.12 venv")
    script = PKG / "scripts" / "check_colab_compat.py"
    res = subprocess.run(
        [sys.executable, str(script), "--workdir", str(tmp_path), "--rows", "all"],
        capture_output=True,
        text=True,
        check=False,
        env=os.environ.copy(),
    )
    print(res.stdout[-6000:])
    assert res.returncode == 0, res.stdout[-4000:] + res.stderr[-2000:]
    for row in ("py312-colab-2026.07", "py313-colab-current", "py313-opencv-4.14"):
        assert f"ROW {row}: PASS" in res.stdout, row
