"""Install svi_geo into Colab-equivalent virtualenvs and run the offline test suite in each.

Rows (see constraints/ for the provenance of each freeze):

* py312-colab-2026.07: Python 3.12 + Colab runtime 2026.07 (numpy 2.0.2, pandas 2.2.2, ...)
* py313-colab-current: Python 3.13 + the current Colab runtime (numpy 2.1.3, pandas 2.2.3, ...)
* py313-opencv-4.14:   the current runtime with opencv-python-headless 4.14 instead of 5.0

For each row:

1. `uv venv --seed --python X` (the venv's own pip is used, so pip.conf indexes apply);
2. install svi_geo's direct dependencies at Colab's versions (the "preinstalled" state);
3. `pip install --dry-run --report` svi_geo[notebooks] WITHOUT constraints and fail if pip
   would replace any preinstalled package (the "no upgrades on Colab" check);
4. `pip install -e .[notebooks,dev] -c <constraints>`;
5. `pytest -m "not live and not slow"` (the static notebook tests are part of that run).

Usage: check_colab_compat.py --workdir DIR [--rows all|NAME[,NAME]]
Prints `ROW <name>: PASS|FAIL <reason>` per row; exit code 1 if any row fails.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import tomllib

PKG = Path(__file__).resolve().parents[1]
CONSTRAINTS = PKG / "constraints"
PIN = re.compile(r"^([A-Za-z0-9_.\-]+)==(\S+)$")


@dataclasses.dataclass(frozen=True)
class Row:
    name: str
    python: str
    constraints: str
    overrides: tuple[tuple[str, str], ...] = ()


ROWS = (
    Row("py312-colab-2026.07", "3.12", "colab-2026.07.txt"),
    Row("py313-colab-current", "3.13", "colab-current.txt"),
    Row(
        "py313-opencv-4.14",
        "3.13",
        "colab-current.txt",
        (("opencv-python-headless", "4.14.0.94"),),
    ),
)


def canon(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def read_pins(path: Path) -> dict[str, str]:
    out = {}
    for line in path.read_text().splitlines():
        m = PIN.match(line.strip())
        if m:
            out[canon(m.group(1))] = m.group(2)
    return out


def direct_deps(extras: tuple[str, ...] = ("notebooks",)) -> list[str]:
    proj = tomllib.loads((PKG / "pyproject.toml").read_text())["project"]
    specs = list(proj["dependencies"])
    for e in extras:
        specs += proj["optional-dependencies"][e]
    return [canon(re.split(r"[<>=~!\[ ;]", s, maxsplit=1)[0]) for s in specs]


def write_constraints(row: Row, workdir: Path) -> Path:
    pins = read_pins(CONSTRAINTS / row.constraints)
    for name, ver in row.overrides:
        pins[canon(name)] = ver
    path = workdir / f"{row.name}-constraints.txt"
    path.write_text("".join(f"{n}=={v}\n" for n, v in sorted(pins.items())))
    return path


def run(cmd: list[str], cwd: Path | None = None, log=None) -> subprocess.CompletedProcess:
    res = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, check=False, env=os.environ.copy()
    )
    if log is not None:
        log.write(f"$ {' '.join(cmd)}\n{res.stdout}\n{res.stderr}\n")
    return res


def find_uv() -> str | None:
    uv = shutil.which("uv") or str(Path(sys.executable).with_name("uv"))
    return uv if Path(uv).exists() else None


def make_venv(row: Row, venv: Path, log) -> str | None:
    uv = find_uv()
    if uv:
        res = run([uv, "venv", "--clear", "--seed", "--python", row.python, str(venv)], log=log)
    else:
        exe = shutil.which(f"python{row.python}")
        if exe is None:
            return f"no uv and no python{row.python}"
        res = run([exe, "-m", "venv", "--clear", str(venv)], log=log)
    return None if res.returncode == 0 else f"venv creation failed: {res.stderr[-400:]}"


def check_row(row: Row, workdir: Path) -> tuple[bool, str]:
    venv = workdir / row.name
    cons = write_constraints(row, workdir)
    with (workdir / f"{row.name}.log").open("w") as log:
        err = make_venv(row, venv, log)
        if err:
            return False, err
        py = str(venv / "bin" / "python")
        pip = [py, "-m", "pip", "--disable-pip-version-check"]
        pins = read_pins(cons)
        pre = [f"{n}=={pins[n]}" for n in direct_deps() if n in pins]
        res = run(pip + ["install", "-q", *pre], log=log)
        if res.returncode:
            return False, f"installing Colab's preinstalled versions failed: {res.stderr[-600:]}"
        report = workdir / f"{row.name}-dryrun.json"
        res = run(
            pip + ["install", "--dry-run", "-q", "--report", str(report), f"{PKG}[notebooks]"],
            log=log,
        )
        if res.returncode:
            return False, f"dry-run install failed: {res.stderr[-600:]}"
        installed = {
            canon(d["name"])
            for d in json.loads(run(pip + ["list", "--format", "json"]).stdout or "[]")
        }
        items = json.loads(report.read_text())["install"]
        would = {canon(i["metadata"]["name"]): i["metadata"]["version"] for i in items}
        upgrades = {n: v for n, v in would.items() if n in installed}
        if upgrades:
            return False, f"pip would replace preinstalled packages: {upgrades}"
        res = run(pip + ["install", "-q", "-e", f"{PKG}[notebooks,dev]", "-c", str(cons)], log=log)
        if res.returncode:
            return False, f"install with constraints failed: {res.stderr[-600:]}"
        res = run([py, str(Path(__file__).with_name("print_versions.py"))], log=log)
        versions = res.stdout.strip()
        if res.returncode:
            return False, f"API check failed: {versions} {res.stderr[-400:]}"
        res = run(
            [py, "-m", "pytest", "-m", "not live and not slow", "-q", "-p", "no:cacheprovider"],
            cwd=PKG,
            log=log,
        )
        tail = res.stdout.strip().splitlines()[-1:] or [res.stderr[-300:]]
        if res.returncode:
            return False, f"pytest failed: {tail[0]} ({versions}); see {log.name}"
        return True, f"{tail[0]} | new installs {sorted(would)} | {versions}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--workdir", required=True, type=Path)
    ap.add_argument("--rows", default="all")
    args = ap.parse_args(argv)
    args.workdir.mkdir(parents=True, exist_ok=True)
    wanted = {r.name for r in ROWS} if args.rows == "all" else set(args.rows.split(","))
    ok_all = True
    for row in ROWS:
        if row.name not in wanted:
            continue
        ok, msg = check_row(row, args.workdir)
        ok_all &= ok
        print(f"ROW {row.name}: {'PASS' if ok else 'FAIL'} {msg}", flush=True)
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
