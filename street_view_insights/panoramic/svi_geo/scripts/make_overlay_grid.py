#!/usr/bin/env python3
"""Render a visual QA overlay grid for an SVI panoramic notebook (U12 / §4.4).

Accepted boxes/edges are drawn in green (`#2ea043`); rejected boxes/edges are drawn in red
(`#d93025`) with their rejection reason label (`low_post_support`, `wall_decoy`, etc.).
Every saved grid includes the mandatory Google attribution footer (`attribution.save_figure`).
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import cv2
import matplotlib.pyplot as plt
import numpy as np

from svi_geo import attribution


def _draw_panel(panel: Mapping[str, Any]) -> tuple[np.ndarray, int, int, list[str]]:
    img = np.asarray(panel["image"], dtype=np.uint8)
    canvas = img.copy() if img.ndim == 3 else cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    n_acc = 0
    n_rej = 0
    reasons: list[str] = []

    for box in panel.get("accepted_boxes") or ():
        x0, y0, x1, y1 = (int(round(float(v))) for v in box[:4])
        label = str(box[4]) if len(box) > 4 else "OK"
        cv2.rectangle(canvas, (x0, y0), (x1, y1), (67, 160, 46), 2)
        cv2.putText(
            canvas,
            f"OK:{label}",
            (max(2, x0), max(16, y0 - 4)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (67, 160, 46),
            1,
            cv2.LINE_AA,
        )
        n_acc += 1

    for box in panel.get("rejected_boxes") or ():
        x0, y0, x1, y1 = (int(round(float(v))) for v in box[:4])
        reason = str(box[4]) if len(box) > 4 else "rejected"
        cv2.rectangle(canvas, (x0, y0), (x1, y1), (37, 48, 217), 2)
        cv2.putText(
            canvas,
            f"REJ:{reason}",
            (max(2, x0), max(16, y0 - 4)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (37, 48, 217),
            1,
            cv2.LINE_AA,
        )
        n_rej += 1
        reasons.append(reason)

    for edge in panel.get("accepted_edges") or ():
        pts = np.asarray(edge, dtype=np.int32).reshape(-1, 1, 2)
        if len(pts) >= 2:
            cv2.polylines(canvas, [pts], isClosed=False, color=(67, 160, 46), thickness=2)
            n_acc += 1

    for item in panel.get("rejected_edges") or ():
        if isinstance(item, tuple | list) and len(item) == 2 and isinstance(item[1], str):
            pts_raw, reason = item[0], str(item[1])
        else:
            pts_raw, reason = item, "rejected_edge"
        pts = np.asarray(pts_raw, dtype=np.int32).reshape(-1, 1, 2)
        if len(pts) >= 2:
            cv2.polylines(canvas, [pts], isClosed=False, color=(37, 48, 217), thickness=2)
            p0 = pts[0, 0]
            cv2.putText(
                canvas,
                f"REJ:{reason}",
                (max(2, int(p0[0])), max(16, int(p0[1]) - 4)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.42,
                (37, 48, 217),
                1,
                cv2.LINE_AA,
            )
            n_rej += 1
            reasons.append(reason)

    return canvas, n_acc, n_rej, reasons


def render_overlay_grid(
    panels: Sequence[Mapping[str, Any]],
    out_path: str | Path,
    *,
    notebook_name: str = "svi_notebook",
    cols: int = 3,
    qa_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Render `panels` into an attribution-stamped PNG grid at `out_path` (and optional `qa_dir`)."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    n = max(1, len(panels))
    ncols = min(max(1, int(cols)), n)
    nrows = int(math.ceil(n / ncols))

    fig, axes = plt.subplots(nrows, ncols, figsize=(4.5 * ncols, 3.6 * nrows), squeeze=False)
    total_acc = 0
    total_rej = 0
    all_reasons: list[str] = []

    for idx in range(nrows * ncols):
        ax = axes[idx // ncols][idx % ncols]
        ax.axis("off")
        if idx >= len(panels):
            continue
        p = panels[idx]
        bgr, n_acc, n_rej, reasons = _draw_panel(p)
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        ax.imshow(rgb)
        title = str(p.get("title") or f"panel_{idx}")
        ax.set_title(f"{title} (ok={n_acc}, rej={n_rej})", fontsize=9)
        total_acc += n_acc
        total_rej += n_rej
        all_reasons.extend(reasons)

    fig.suptitle(
        f"{notebook_name}: accepted={total_acc} (green) | rejected={total_rej} (red)",
        fontsize=11,
    )
    fig.tight_layout(rect=(0, 0.04, 1, 0.95))
    attribution.save_figure(fig, out)
    plt.close(fig)

    if qa_dir is not None:
        qdir = Path(qa_dir)
        qdir.mkdir(parents=True, exist_ok=True)
        qcopy = qdir / f"{notebook_name}_overlay_grid.png"
        qcopy.write_bytes(out.read_bytes())

    meta = {
        "notebook": notebook_name,
        "out_path": str(out),
        "n_panels": len(panels),
        "n_accepted": total_acc,
        "n_rejected": total_rej,
        "rejection_reasons": sorted(set(all_reasons)),
    }
    meta_path = out.with_suffix(".json")
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta
