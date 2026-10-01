"""Shared attribution-stamped Folium map helpers for Street View Insights notebooks (Task U10).

Consumes BigQuery `ST_ASTEXT(geog) AS wkt` (`POINT(lng lat)`) or `(lat, lng)` columns and
stamps mandatory `Imagery © Google` attribution (`attribution.FOLIUM_ATTR` + HTML badge).
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import folium
import pandas as pd

from svi_geo import attribution, geo

_WKT_POINT_RE = re.compile(
    r"POINT\s*\(\s*([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s+([-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*\)",
    re.I,
)

CLASS_COLORS = {
    "HOUSE": "#0B57D0",
    "UTILITY_POLE": "#E37400",
    "ROAD_SIGN": "#C5221F",
}

MATERIAL_COLORS = {
    "Paved Asphalt": "#1F1F1F",
    "Concrete": "#0B57D0",
    "Brick or Cobblestone": "#B06000",
    "Gravel": "#8D6E63",
    "Unpaved Dirt": "#6D4C41",
    "ABSENT": "#BDC1C6",
}


def parse_wkt_point(wkt: str) -> tuple[float, float]:
    """Parse BigQuery `ST_ASTEXT(geog)` (`POINT(lng lat)`) into `(lat, lng)`."""
    m = _WKT_POINT_RE.search(str(wkt or ""))
    if not m:
        raise ValueError(f"could not parse WKT POINT from {wkt!r}")
    lng = float(m.group(1))
    lat = float(m.group(2))
    return lat, lng


def _row_lat_lng(row: Any) -> tuple[float, float]:
    get = row.get if isinstance(row, Mapping) else (lambda k, d=None: getattr(row, k, d))
    wkt = get("wkt")
    if wkt:
        try:
            return parse_wkt_point(str(wkt))
        except ValueError:
            pass
    return float(get("lat")), float(get("lng"))


def add_attribution_badge(m: folium.Map, text: str = attribution.IMAGERY_CREDIT) -> folium.Map:
    """Inject a persistent bottom-left attribution badge into a Folium map."""
    badge_html = (
        '<div style="position: fixed; bottom: 8px; left: 8px; z-index: 9999; '
        "background: rgba(255,255,255,0.92); color: #1F1F1F; padding: 3px 8px; "
        'border-radius: 4px; font-family: sans-serif; font-size: 11px; border: 1px solid #DADCE0;">'
        f"Street View Insights | <b>{text}</b></div>"
    )
    m.get_root().html.add_child(folium.Element(badge_html))
    return m


def _base_map(
    center_lat: float,
    center_lng: float,
    zoom_start: int = 18,
) -> folium.Map:
    m = folium.Map(
        location=[float(center_lat), float(center_lng)],
        zoom_start=zoom_start,
        tiles="OpenStreetMap",
        attr=attribution.FOLIUM_ATTR,
        control_scale=True,
    )
    return add_attribution_badge(m)


def _finalize_map(m: folium.Map, out_path: str | Path | None) -> folium.Map:
    if out_path is not None:
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        m.save(str(p))
    return m


def rosette_tracks_map(
    rosettes: pd.DataFrame,
    *,
    out_path: str | Path | None = None,
    zoom_start: int = 17,
) -> folium.Map:
    """Plot drive sequence tracks (`LineString` per `seq_id`) and rosette capture points from WKT."""
    if rosettes.empty:
        m = _base_map(28.0502, -81.9601, zoom_start=zoom_start)
        return _finalize_map(m, out_path)
    coords = [_row_lat_lng(r) for r in rosettes.to_dict("records")]
    clat = sum(c[0] for c in coords) / len(coords)
    clng = sum(c[1] for c in coords) / len(coords)
    m = _base_map(clat, clng, zoom_start=zoom_start)

    df = rosettes.copy()
    if "seq_id" in df.columns:
        sort_cols = [c for c in ("seq_id", "seq_idx", "capture_time") if c in df.columns]
        for seq_id, grp in df.sort_values(sort_cols).groupby("seq_id", sort=False):
            pts = [_row_lat_lng(r) for r in grp.to_dict("records")]
            if len(pts) >= 2:
                folium.PolyLine(
                    pts,
                    color="#0B57D0",
                    weight=3,
                    opacity=0.75,
                    tooltip=f"seq_id={seq_id} ({len(pts)} rosettes)",
                ).add_to(m)

    for r in df.to_dict("records"):
        lat, lng = _row_lat_lng(r)
        cid = str(r.get("capture_id") or r.get("pano_id") or "")
        pid = r.get("pano_id")
        murl = r.get("map_url") or ""
        link = f'<br><a href="{murl}" target="_blank">Open in Google Maps</a>' if murl else ""
        popup = (
            f"<b>capture_id</b>: {cid[:16]}<br><b>pano_id</b>: {pid or 'NULL (unpublished)'}{link}"
        )
        folium.CircleMarker(
            location=[lat, lng],
            radius=4,
            color="#0B57D0" if pid else "#E37400",
            fill=True,
            fill_opacity=0.85,
            popup=folium.Popup(popup, max_width=280),
        ).add_to(m)

    return _finalize_map(m, out_path)


def uc1_house_map(
    rosettes: pd.DataFrame,
    *,
    target_lat: float,
    target_lng: float,
    sightings: Sequence[Any] = (),
    location: Any = None,
    out_path: str | Path | None = None,
    zoom_start: int = 19,
) -> folium.Map:
    """Plot target house, candidate rosettes (from WKT), sighting rays, and triangulated location."""
    m = _base_map(target_lat, target_lng, zoom_start=zoom_start)

    folium.Marker(
        location=[float(target_lat), float(target_lng)],
        tooltip="Target house query point",
        icon=folium.Icon(color="blue", icon="home"),
    ).add_to(m)

    if not rosettes.empty:
        for r in rosettes.to_dict("records"):
            lat, lng = _row_lat_lng(r)
            cid = str(r.get("capture_id") or r.get("pano_id") or "")
            folium.CircleMarker(
                location=[lat, lng],
                radius=4,
                color="#5F6368",
                fill=True,
                fill_opacity=0.7,
                tooltip=f"rosette {cid[:12]}",
            ).add_to(m)

    for s in sightings:
        pose = getattr(s, "camera_pose", None) or {}
        clat = float(pose.get("latitude", target_lat))
        clng = float(pose.get("longitude", target_lng))
        view = getattr(s, "view", None)
        box_px = getattr(s, "box_px", None)
        if view is not None and box_px is not None:
            az = float(view.box_to_bearings(box_px)["az"])
        else:
            az = float(geo.bearing_deg(clat, clng, target_lat, target_lng))
        ray_len_m = 45.0
        de = ray_len_m * math.sin(math.radians(az))
        dn = ray_len_m * math.cos(math.radians(az))
        end_lat, end_lng, _ = geo.enu_to_lla(de, dn, 0.0, clat, clng, 0.0)
        folium.PolyLine(
            [(clat, clng), (float(end_lat), float(end_lng))],
            color="#E37400",
            weight=2,
            opacity=0.8,
            dash_array="5, 5",
            tooltip=f"sighting ray az={az:.1f} deg",
        ).add_to(m)

    if location is not None and getattr(location, "lat", None) is not None:
        folium.CircleMarker(
            location=[float(location.lat), float(location.lng)],
            radius=7,
            color="#137333",
            fill=True,
            fill_color="#137333",
            fill_opacity=0.95,
            tooltip=(
                f"Triangulated house ({getattr(location, 'method', 'triangulated')}, "
                f"rms={getattr(location, 'rms_m', 0.0):.2f} m)"
            ),
        ).add_to(m)

    return _finalize_map(m, out_path)


def uc2_entities_map(
    rosettes: pd.DataFrame,
    entities_df: pd.DataFrame,
    *,
    out_path: str | Path | None = None,
    zoom_start: int = 18,
) -> folium.Map:
    """Plot drive track from `rosettes` WKT and located discrete assets (`entities_df`)."""
    m = rosette_tracks_map(rosettes, out_path=None, zoom_start=zoom_start)
    if entities_df is not None and not entities_df.empty:
        for r in entities_df.to_dict("records"):
            lat = r.get("lat")
            lng = r.get("lng")
            if lat is None or lng is None or pd.isna(lat) or pd.isna(lng):
                continue
            cls = str(r.get("class", "ENTITY"))
            color = CLASS_COLORS.get(cls, "#137333")
            eid = str(r.get("entity_id", ""))
            method = str(r.get("method", ""))
            n_panos = r.get("n_panos", 1)
            folium.CircleMarker(
                location=[float(lat), float(lng)],
                radius=6,
                color=color,
                fill=True,
                fill_color=color,
                fill_opacity=0.9,
                tooltip=f"{eid} ({cls}, {method}, n_panos={n_panos})",
            ).add_to(m)
    return _finalize_map(m, out_path)


def uc3_segments_map(
    rosettes: pd.DataFrame,
    slot_rows: Sequence[Mapping[str, Any]],
    *,
    out_path: str | Path | None = None,
    zoom_start: int = 18,
) -> folium.Map:
    """Plot smoothed road and left/right sidewalk surface segments along the rosette sequence."""
    if not rosettes.empty:
        coords = [_row_lat_lng(r) for r in rosettes.to_dict("records")]
        clat = sum(c[0] for c in coords) / len(coords)
        clng = sum(c[1] for c in coords) / len(coords)
    else:
        clat, clng = 28.0502, -81.9601
    m = _base_map(clat, clng, zoom_start=zoom_start)

    for slot in slot_rows:
        asset = str(slot.get("asset", "SURFACE"))
        side = str(slot.get("side", "CENTER"))
        for seg in slot.get("segments", ()):
            label = str(seg.get("label", "UNKNOWN"))
            pts = seg.get("points") or []
            if len(pts) < 2:
                continue
            color = MATERIAL_COLORS.get(label, "#0B57D0")
            weight = 6 if side == "CENTER" else 4
            folium.PolyLine(
                [(float(p[0]), float(p[1])) for p in pts],
                color=color,
                weight=weight,
                opacity=0.88,
                tooltip=f"{asset} ({side}): {label} ({seg.get('length_m', 0.0):.1f} m)",
            ).add_to(m)

    if not rosettes.empty:
        for r in rosettes.to_dict("records"):
            lat, lng = _row_lat_lng(r)
            folium.CircleMarker(
                location=[lat, lng],
                radius=3,
                color="#5F6368",
                fill=True,
                fill_opacity=0.7,
            ).add_to(m)

    return _finalize_map(m, out_path)


def uc4_roof_map(
    rosettes_or_chosen: Sequence[Mapping[str, Any]] | pd.DataFrame,
    *,
    target_lat: float,
    target_lng: float,
    results: Sequence[Any] = (),
    out_path: str | Path | None = None,
    zoom_start: int = 19,
) -> folium.Map:
    """Plot target building and selected roof-inspection camera viewpoints + rays."""
    m = _base_map(target_lat, target_lng, zoom_start=zoom_start)
    folium.Marker(
        location=[float(target_lat), float(target_lng)],
        tooltip="Target building roof",
        icon=folium.Icon(color="red", icon="home"),
    ).add_to(m)

    records = (
        rosettes_or_chosen.to_dict("records")
        if isinstance(rosettes_or_chosen, pd.DataFrame)
        else [dict(r) for r in rosettes_or_chosen]
    )
    for idx, r in enumerate(records):
        pose = r.get("camera_pose")
        if isinstance(pose, Mapping):
            lat = float(pose.get("latitude", r.get("lat", target_lat)))
            lng = float(pose.get("longitude", r.get("lng", target_lng)))
        else:
            lat, lng = _row_lat_lng(r)
        n_acc = len(results[idx].valid_edges) if idx < len(results) else 0
        folium.CircleMarker(
            location=[lat, lng],
            radius=5,
            color="#137333" if n_acc > 0 else "#0B57D0",
            fill=True,
            fill_opacity=0.85,
            tooltip=f"view #{idx} (accepted_edges={n_acc})",
        ).add_to(m)
        folium.PolyLine(
            [(lat, lng), (float(target_lat), float(target_lng))],
            color="#0B57D0",
            weight=2,
            opacity=0.7,
            dash_array="4, 4",
        ).add_to(m)

    return _finalize_map(m, out_path)


def _draw_overlay_panel(panel: Mapping[str, Any]) -> tuple[Any, int, int, list[str]]:
    import cv2
    import numpy as np

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
    """Render `panels` into an attribution-stamped PNG grid at `out_path` (and optional `qa_dir`).

    Accepted boxes/edges are drawn in green (`#2ea043`); rejected boxes/edges are drawn in red
    (`#d93025`) with their rejection reason label (`low_post_support`, `wall_decoy`, etc.).
    """
    import json

    import cv2
    import matplotlib.pyplot as plt

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
        bgr, n_acc, n_rej, reasons = _draw_overlay_panel(p)
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
