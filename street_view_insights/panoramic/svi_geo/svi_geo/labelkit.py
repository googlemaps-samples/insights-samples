"""Hand-label kit for evaluating the notebooks on real imagery (no labels are generated here).

The kit renders the views a human labeller needs and writes a pre-filled CSV label sheet; the
human enters boxes, object keys, surface materials/sides/presence and roof polylines. Labels
and images stay local; only aggregate metrics (with bootstrap CIs over panos) are published.
See `EVALUATION.md` for the protocol and `scripts/make_label_kit.py` / `score_labels.py`.
"""

from __future__ import annotations

import csv
import html
import random
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from svi_geo import geo

# Existing label format (tests/fixtures/labels_small.csv) ...
BASE_COLUMNS = (
    "label_id", "pano_id", "observation_id", "view_yaw_deg", "class", "x0", "y0", "x1", "y1",
    "object_key", "material", "condition", "notes",
)  # fmt: skip
# ... plus the optional columns for surfaces (side, present) and roofs (edge_type, points_json).
OPTIONAL_COLUMNS = ("side", "present", "edge_type", "points_json", "labeller")
HEADER = BASE_COLUMNS + OPTIONAL_COLUMNS

SURFACE_SLOTS = (("ROAD_SEGMENT", "CENTER"), ("SIDEWALK_SEGMENT", "LEFT"),
                 ("SIDEWALK_SEGMENT", "RIGHT"))  # fmt: skip


def surface_slots(pano_ids: Iterable[str]) -> list[dict[str, str]]:
    """One empty UC3 row per (pano, asset, side); the labeller fills material and present."""
    return [
        {"label_id": f"S_{pid}_{side}", "pano_id": pid, "class": cls, "side": side}
        for pid in pano_ids
        for cls, side in SURFACE_SLOTS
    ]


def view_rows(views: Iterable[Mapping[str, Any]], cls: str = "") -> list[dict[str, str]]:
    """One empty row per rendered view (pano_id, observation_id, view_yaw_deg); the labeller
    duplicates the row for every object boxed in that view."""
    return [
        {
            "label_id": f"V_{v['pano_id']}_{round(float(v['view_yaw_deg']))}",
            "pano_id": v["pano_id"],
            "observation_id": v.get("observation_id", ""),
            "view_yaw_deg": f"{float(v['view_yaw_deg']):.1f}",
            "class": cls,
        }
        for v in views
    ]


def write_label_sheet(path: str | Path, rows: Sequence[Mapping[str, Any]]) -> Path:
    """Write the label CSV with the exact `HEADER`; missing cells are left empty."""
    path = Path(path)
    for r in rows:
        extra = set(r) - set(HEADER)
        if extra:
            raise ValueError(f"unknown label columns {sorted(extra)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(HEADER))
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in HEADER})
    return path


def second_labeller_panos(pano_ids: Sequence[str], fraction: float = 0.2, seed: int = 0):
    """Deterministic sample of panos that a second labeller repeats (inter-annotator check)."""
    ids = sorted(set(pano_ids))
    k = max(1, round(fraction * len(ids))) if ids else 0
    return sorted(random.Random(seed).sample(ids, k))


def html_page(title: str, items: Sequence[Mapping[str, str]]) -> str:
    """Static HTML page showing each rendered view (relative image path) with its ids."""
    cards = "\n".join(
        f"<figure><img src='{html.escape(it['image'])}' width='640'>"
        f"<figcaption>{html.escape(it['caption'])}</figcaption></figure>"
        for it in items
    )
    return (
        f"<!doctype html><meta charset='utf-8'><title>{html.escape(title)}</title>"
        f"<h1>{html.escape(title)}</h1><p>Imagery © Google. Local labelling only; do not "
        f"redistribute.</p>\n{cards}\n"
    )


def consecutive_window(seqs: pd.DataFrame, lat: float, lng: float, n: int) -> list[str]:
    """`n` consecutive pano ids of the longest drive sequence (`sequence.build_sequences`
    output), centred on the pano nearest (lat, lng) and clamped to the sequence ends."""
    lens = seqs.groupby("seq_id").size()
    seq = seqs[seqs["seq_id"] == lens.idxmax()].sort_values("seq_idx")
    if len(seq) < n:
        raise ValueError(f"longest sequence has {len(seq)} panos; need {n} consecutive panos")
    d = geo.haversine_m(seq["lat"].to_numpy(), seq["lng"].to_numpy(), lat, lng)
    mid = int(np.argmin(d))
    lo = max(0, min(mid - n // 2, len(seq) - n))
    return [str(p) for p in seq["pano_id"].to_numpy()[lo : lo + n]]
