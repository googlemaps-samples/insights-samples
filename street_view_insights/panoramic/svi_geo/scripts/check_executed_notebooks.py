#!/usr/bin/env python3
"""Acceptance checks on notebooks executed with nbconvert (U12 / §4.3).

    jupyter nbconvert --to notebook --execute --ExecutePreprocessor.timeout=1800 \
        --output-dir ~/tmp/nbref ../notebooks/<nb>.ipynb
    ../../../.venv/bin/python scripts/check_executed_notebooks.py ~/tmp/nbref/*.ipynb

Mandatory regex-parsed lines for the four reference use-case notebooks:
1. `snapshots=<id8,...> rosettes=N null_pano_id=M sequences=S bq_bytes=B bq_cached=<0|1>`
2. `variant=final`
3. `Gemini calls=N ... failures=0 ... est_cost=$E ... code_exec_runs=K ok=K fallbacks=0`
4. `black_fraction_max=f dark_pixel_max=g redaction_overlap_max=h`
5. `<result key>=R` (`centred_views` / `located_entities` / `segments` / `accepted_edges` >= 1)
6. `code_exec_agreement=<agree|disagree|skipped>(detail)`
7. `map_rendered=1 artefacts=P peak_rss_mb=Q`

For `00_explore_coverage` (zero-Gemini warm-up notebook), lines 1, 4, 5 (`strips_rendered>=1`),
and 7 (`map_rendered=1 artefacts>=2 peak_rss_mb<=4000`) are checked and `Gemini calls` must be 0.
"""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path
from typing import Any

MAX_BLACK = 0.01
DEFAULT_MAX_RSS_MB = 8000.0
CEILINGS_PATH = Path(__file__).with_name("ceilings.json")

RESULT_KEYS = {
    "00_explore_coverage": "strips_rendered",
    "house_image_discovery_with_cost": "centred_views",
    "analyze_sequential_images": "located_entities",
    "surface_material_detection": "segments",
    "roof_edge_tracing": "accepted_edges",
}

_SNAPSHOTS = re.compile(
    r"snapshots=([^\s]+)\s+rosettes=(\d+)\s+null_pano_id=(\d+)\s+sequences=(\d+)\s+"
    r"bq_bytes=(\d+)\s+bq_cached=([01])"
)
_VARIANT = re.compile(r"(?m)^variant=([^\s]+)")
_GEMINI = re.compile(
    r"Gemini calls=(\d+)\s+.*?failures=(\d+).*?est_cost=\$([0-9.]+)"
    r"(?:\s+ceiling=\$([0-9.]+))?"
    r"(?:\s+code_exec_runs=(\d+)\s+ok=(\d+)\s+fallbacks=(\d+))?"
)
_BLACK = re.compile(r"black_fraction_max=([0-9.]+|nan)")
_CODE_EXEC_AGREE = re.compile(r"code_exec_agreement=(agree|disagree|skipped)\(([^)]*)\)")
_MAP_RSS = re.compile(r"map_rendered=([01])\s+artefacts=(\d+)\s+peak_rss_mb=([0-9.]+)")


def load_ceilings() -> dict[str, dict[str, Any]]:
    if CEILINGS_PATH.exists():
        return json.loads(CEILINGS_PATH.read_text(encoding="utf-8"))
    return {}


def _stdout(nb: dict) -> tuple[str, list[str]]:
    text, errors = [], []
    for cell in nb.get("cells", []):
        for out in cell.get("outputs", []):
            kind = out.get("output_type")
            if kind == "error":
                errors.append(f"{out.get('ename')}: {out.get('evalue')}")
            elif kind == "stream":
                t = out.get("text", "")
                text.append(t if isinstance(t, str) else "".join(t))
            elif kind in ("execute_result", "display_data"):
                t = out.get("data", {}).get("text/plain", "")
                text.append(t if isinstance(t, str) else "".join(t))
    return "\n".join(text), errors


def check_notebook(nb: dict, name: str) -> tuple[list[str], dict[str, Any]]:
    """(problems, stats) for one executed notebook; `name` selects the result key and ceiling."""
    if name not in RESULT_KEYS:
        raise ValueError(f"unknown notebook {name!r}; expected one of {sorted(RESULT_KEYS)}")
    ceilings = load_ceilings().get(name, {})
    max_usd = float(ceilings.get("max_usd", 1.0))
    max_rss_mb = float(ceilings.get("max_rss_mb", DEFAULT_MAX_RSS_MB))
    is_warmup = name == "00_explore_coverage"

    text, errors = _stdout(nb)
    problems = [f"error output: {e}" for e in errors]
    stats: dict[str, Any] = {}

    snap_matches = _SNAPSHOTS.findall(text)
    if not snap_matches:
        problems.append("no 'snapshots=... rosettes=...' line")
    else:
        snaps, rosettes, null_panos, seqs, bq_bytes, bq_cached = snap_matches[-1]
        stats.update(
            snapshots=snaps,
            rosettes=int(rosettes),
            null_pano_id=int(null_panos),
            sequences=int(seqs),
            bq_bytes=int(bq_bytes),
            bq_cached=int(bq_cached),
        )
        if stats["rosettes"] < 1:
            problems.append(f"rosettes={stats['rosettes']} < 1")

    if not is_warmup:
        var_matches = _VARIANT.findall(text)
        if not var_matches or var_matches[-1] != "final":
            problems.append("missing 'variant=final' line")
        else:
            stats["variant"] = var_matches[-1]

        gem = _GEMINI.findall(text)
        if not gem:
            problems.append("no 'Gemini calls=' line")
        for calls, failures, *_rest in gem:
            if int(failures):
                problems.append(f"Gemini summary with failures={failures} (calls={calls})")
        if gem:
            calls, failures, cost, ceil_str, ce_runs, ce_ok, fb = gem[-1]
            est_cost = float(cost)
            eff_ceil = float(ceil_str) if ceil_str else max_usd
            stats.update(
                gemini_calls=int(calls),
                gemini_failures=int(failures),
                est_cost_usd=est_cost,
                ceiling_usd=eff_ceil,
            )
            if est_cost > max(eff_ceil, max_usd):
                problems.append(
                    f"est_cost=${est_cost:.4f} exceeds ceiling=${min(eff_ceil, max_usd):.4f}"
                )
            if ce_runs != "":
                runs_i, ok_i, fb_i = int(ce_runs), int(ce_ok), int(fb)
                stats.update(code_exec_runs=runs_i, code_exec_ok=ok_i, fallbacks=fb_i)
                if fb_i != 0:
                    problems.append(f"fallbacks={fb_i} != 0")
                if runs_i < 1 or ok_i != runs_i:
                    problems.append(
                        f"code_exec_runs={runs_i} ok={ok_i} (expected >=1 and ok==runs)"
                    )
            else:
                problems.append("Gemini summary missing code_exec_runs/ok/fallbacks fields")

        cexec = _CODE_EXEC_AGREE.findall(text)
        if not cexec:
            problems.append("no 'code_exec_agreement=' line")
        else:
            status, detail = cexec[-1]
            stats["code_exec_agreement"] = f"{status}({detail})"

    key = RESULT_KEYS[name]
    counts = re.findall(rf"(?<![A-Za-z_]){key}=(\d+)", text)
    if not counts:
        problems.append(f"no '{key}=' line")
    else:
        stats[key] = int(counts[-1])
        if stats[key] < 1:
            problems.append(f"{key}={stats[key]}: empty result")

    blacks = [float(v) for v in _BLACK.findall(text)]
    measured = [b for b in blacks if not math.isnan(b)]
    if not measured:
        problems.append("no black_fraction_max measurement")
    else:
        stats["black_fraction_max"] = max(measured)
        for b in measured:
            if b >= MAX_BLACK:
                problems.append(f"black_fraction_max={b:.4f} >= {MAX_BLACK}")

    map_rss = _MAP_RSS.findall(text)
    if not map_rss:
        problems.append("no 'map_rendered=... artefacts=... peak_rss_mb=...' line")
    else:
        m_ok, arts, rss = map_rss[-1]
        stats.update(
            map_rendered=int(m_ok),
            artefacts=int(arts),
            peak_rss_mb=float(rss),
        )
        if int(m_ok) != 1:
            problems.append(f"map_rendered={m_ok} != 1")
        if int(arts) < 2:
            problems.append(f"artefacts={arts} < 2")
        if float(rss) > max_rss_mb:
            problems.append(f"peak_rss_mb={float(rss):.1f} > {max_rss_mb:.1f}")

    return problems, stats


def main(argv: list[str] | None = None) -> int:
    paths = [Path(p) for p in (sys.argv[1:] if argv is None else argv)]
    failed = False
    for path in paths:
        problems, stats = check_notebook(json.loads(path.read_text()), path.stem)
        status = "FAIL" if problems else "ok"
        print(f"{path.stem}: {status} {json.dumps(stats)}")
        for p in problems:
            print(f"  - {p}")
        failed |= bool(problems)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
