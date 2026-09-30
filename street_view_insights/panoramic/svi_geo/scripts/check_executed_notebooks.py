#!/usr/bin/env python3
"""Acceptance checks on notebooks executed with nbconvert.

    jupyter nbconvert --to notebook --execute --ExecutePreprocessor.timeout=1800 \
        --output-dir ~/tmp/nbfix ../notebooks/<nb>.ipynb
    ../../../.venv/bin/python scripts/check_executed_notebooks.py ~/tmp/nbfix/*.ipynb

For every notebook it requires:

- no error outputs;
- at least one `Gemini calls=` summary line, and `failures=0` on every one;
- at least one measured `black_fraction_max=` value, and every value < 0.01 (`nan`, printed
  when a step had nothing to render, is not a measurement);
- a non-empty result: `centred_views=` (UC1), `located_entities=` (UC2), `segments=` (UC3)
  or `accepted_edges=` (UC4) >= 1.

Prints a per-notebook stats line (Gemini calls, failures and cost from the last summary line,
the result count and the max black fraction) and exits 1 if any check fails.
"""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path
from typing import Any

MAX_BLACK = 0.01
RESULT_KEYS = {
    "house_image_discovery_with_cost": "centred_views",
    "analyze_sequential_images": "located_entities",
    "surface_material_detection": "segments",
    "roof_edge_tracing": "accepted_edges",
}
_GEMINI = re.compile(r"Gemini calls=(\d+) .*?failures=(\d+).*?est_cost=\$([0-9.]+)")
_BLACK = re.compile(r"black_fraction_max=([0-9.]+|nan)")


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
    """(problems, stats) for one executed notebook; `name` selects the result key."""
    if name not in RESULT_KEYS:
        raise ValueError(f"unknown notebook {name!r}; expected one of {sorted(RESULT_KEYS)}")
    text, errors = _stdout(nb)
    problems = [f"error output: {e}" for e in errors]
    stats: dict[str, Any] = {}

    gem = _GEMINI.findall(text)
    if not gem:
        problems.append("no 'Gemini calls=' line")
    for calls, failures, _ in gem:
        if int(failures):
            problems.append(f"Gemini summary with failures={failures} (calls={calls})")
    if gem:
        calls, failures, cost = gem[-1]
        stats.update(gemini_calls=int(calls), gemini_failures=int(failures),
                     est_cost_usd=float(cost))  # fmt: skip

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
