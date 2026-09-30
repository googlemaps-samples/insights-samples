#!/usr/bin/env python3
"""Score pipeline output against a human-filled label kit (see EVALUATION.md).

    ../../../.venv/bin/python scripts/score_labels.py \
        --labels ~/svi_label_kit/2026-01-01/labels.csv --pipeline-output run.json \
        [--roof-output roof.json] [--second-labels labels_b.csv]

`--pipeline-output`: JSON list of detection rows {pano_id, view_yaw_deg, cls, box, entity_id}
and segment rows {pano_id, cls, side, material | present=false}. `--roof-output`: JSON list of
{pano_id, view_yaw_deg, edge_type, points, accepted}. `--second-labels`: the second labeller's
sheet for the repeated panos, scored against the first as inter-annotator agreement.
Every rate is printed with a 95% bootstrap CI over panos. Nothing is printed for metrics
without labels: this script never substitutes defaults for missing data.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from svi_geo import eval as ev


def _read_csv(path: str) -> list[dict]:
    with Path(path).open(newline="") as f:
        return list(csv.DictReader(f))


def _labels_as_predictions(rows: list[dict]) -> list[dict]:
    """Segment label rows in the prediction format (for inter-annotator agreement)."""
    return [
        {"pano_id": r["pano_id"], "cls": r["class"], "side": r.get("side"),
         "material": r.get("material"), "present": r.get("present") or True}
        for r in rows
        if r.get("class") in ev.SEGMENTS
    ]  # fmt: skip


def _fmt_ci(name: str, ci: tuple[float, float, float]) -> str:
    point, lo, hi = ci
    if point != point:
        return f"{name}: no labelled data"
    return f"{name}: {point:.3f} (95% CI {lo:.3f}-{hi:.3f})"


def report(labels_path, preds, roof_preds=None, second=None) -> dict:
    labels = _read_csv(labels_path)
    out = {"hand_labels": ev.score_hand_labels(labels_path, preds)}
    seg_labels = [r for r in labels if r.get("class") in ev.SEGMENTS]
    out["material_accuracy_ci"] = ev.bootstrap_ci(ev.per_pano_counts(
        seg_labels, preds, ev.score_segment_labels, "material_accuracy", "n_material"))  # fmt: skip
    if roof_preds is not None:
        roof_labels = [r for r in labels if r.get("class") == "ROOF_EDGE"]
        out["roof"] = ev.score_roof_labels(roof_labels, roof_preds)
        out["edge_recall_ci"] = ev.bootstrap_ci(ev.per_pano_counts(
            roof_labels, roof_preds, ev.score_roof_labels, "edge_recall", "n_label_edges"))  # fmt: skip
    if second is not None:
        repeated = {r["pano_id"] for r in second}
        first = [r for r in seg_labels if r["pano_id"] in repeated]
        out["inter_annotator_segments"] = ev.score_segment_labels(
            first, _labels_as_predictions(second)
        )
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--labels", required=True)
    ap.add_argument("--pipeline-output", required=True)
    ap.add_argument("--roof-output")
    ap.add_argument("--second-labels")
    args = ap.parse_args()
    preds = json.loads(Path(args.pipeline_output).read_text())
    roof_preds = json.loads(Path(args.roof_output).read_text()) if args.roof_output else None
    second = _read_csv(args.second_labels) if args.second_labels else None
    res = report(args.labels, preds, roof_preds, second)
    print(json.dumps(res, indent=1, default=str))
    print(_fmt_ci("UC3 material accuracy", res["material_accuracy_ci"]))
    if "edge_recall_ci" in res:
        print(_fmt_ci("UC4 edge recall", res["edge_recall_ci"]))


if __name__ == "__main__":
    sys.exit(main())
