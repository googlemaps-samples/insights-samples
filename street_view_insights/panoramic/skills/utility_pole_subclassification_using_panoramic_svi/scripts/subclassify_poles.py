#!/usr/bin/env python3
"""Multi-view utility pole sub-classification, 2D ENU triangulation, and equipment audit from `SV_PANO`.

Supports four execution modes (`--mode=audit|fetch_sv|triangulate|render_candidates`, default `audit`):
  - `audit`: End-to-end corridor discovery, 2D horizontal ENU multi-view triangulation, single-view
    40-deg zoom infill (`Trigger A`), >50m same-side span-continuity audit (`Trigger B`), closed-loop
    3D-to-2D magenta base reprojection, 3-panel distance-adaptive inspection composites
    (`[1: Full Vertical Shaft | 2: Crown & Cross-Arm Zoom (2x) | 3: Base & Ground Zoom (2x)]`), and
    Gemini structured `PoleSubClassification` fused with OpenCV LSD verticality and lean gates.
  - `fetch_sv`: Query `pano_observations_latest`, spatially deduplicate overlapping multi-year passes
    (~8m spacing, sorted geographically North-to-South, West-to-East), and render calibrated `(u, v)` +
    top-edge cyan world compass azimuth (`{az:03.0f}deg`) camera frames, 3-column contact sheets, and
    `sv_index.json`.
  - `triangulate`: Intersect pixel observations (`P01=cap:cam:u:v,...;P02=...`) across >=2 captures
    using height-invariant 2D horizontal ENU least-squares bearing triangulation, enforcing the `> 10 deg`
    Parallax Rule (GDOP), `<= 1.5 m` residual gate, `behind_camera` check, and `> 50 m` span-gap check.
  - `render_candidates`: Reproject 3D pole candidates `(lat, lng)` back onto calibrated Street View
    camera frames as magenta circles (`P{id}:{label}`) + vertical azimuth plumb lines and render
    3-panel inspection composites for closed-loop 3D-to-2D visual verification.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import cv2
import pandas as pd

try:
    from svi_geo import auth as _svi_auth
    from svi_geo import data as _svi_data
    from svi_geo import gemini_client as _svi_gc
    from svi_geo import geo as _svi_geo
    from svi_geo import images as _svi_images
    from svi_geo import rosette as _svi_rosette
    from svi_geo import schemas as _svi_schemas
    from svi_geo import sequence as _svi_sequence
    from svi_geo import usecases as _svi_uc
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "ERROR: svi_geo package is required. Install with `pip install -e street_view_insights/panoramic/svi_geo`."
    ) from exc


DEFAULT_DATASET = "imagery_insights___us"
DEFAULT_LOCATION = "global"
DEFAULT_MODEL = _svi_gc.DEFAULT_MODEL
MAX_BYTES_BILLED = getattr(_svi_data, "DEFAULT_BYTES_CAP", 2_000_000_000)
VALID_MODES = ("audit", "fetch_sv", "triangulate", "render_candidates")

# Re-export shared enums & schema so standalone skill imports and svi_geo.schemas stay identical
AssetMaterial = _svi_schemas.AssetMaterial
AssetCondition = _svi_schemas.AssetCondition
PoleSubType = _svi_schemas.PoleSubType
CrossArmConfig = _svi_schemas.CrossArmConfig
PoleEquipment = _svi_schemas.PoleEquipment
TRUE_UTILITY_POLE_SUBTYPES = _svi_schemas.TRUE_UTILITY_POLE_SUBTYPES
PoleSubClassification = _svi_schemas.PoleSubClassification


_FIELDS = """
  capture_id, pano_id, observation_id, snapshot_id, capture_time,
  capture_location.latitude AS lat, capture_location.longitude AS lng,
  camera_pose.heading AS heading, camera_pose.pitch AS pitch, camera_pose.roll AS roll"""

# Parameterised SQL against the allow-listed pano_observations_latest view (never selects gcs_uri)
COORDS_SQL = (
    "SELECT"
    + _FIELDS
    + """
FROM `__PROJECT__.__DATASET__.pano_observations_latest`
WHERE ST_DWITHIN(ST_GEOGPOINT(capture_location.longitude, capture_location.latitude),
                 ST_GEOGPOINT(@lng, @lat), @radius_m)
"""
)

ID_SQL = (
    """WITH hit AS (
  SELECT capture_location.latitude AS lat, capture_location.longitude AS lng
  FROM `__PROJECT__.__DATASET__.pano_observations_latest`
  WHERE observation_id = @id OR capture_id = @id OR pano_id = @id
  LIMIT 1
)
SELECT hit.lat AS hit_lat, hit.lng AS hit_lng,"""
    + _FIELDS
    + """
FROM `__PROJECT__.__DATASET__.pano_observations_latest`, hit
WHERE ST_DWITHIN(ST_GEOGPOINT(capture_location.longitude, capture_location.latitude),
                 ST_GEOGPOINT(hit.lng, hit.lat), @radius_m)
"""
)

_IDENT = re.compile(r"^[A-Za-z0-9_\-.]+$")


def render_sql(template: str, project: str, dataset: str) -> str:
    """Substitute and validate `<project>.<dataset>` against the svi_geo allow-list."""
    for v in (project, dataset):
        if not _IDENT.match(v or ""):
            raise ValueError(f"invalid BigQuery identifier: {v!r}")
    allowed = set(_svi_data.allowed_datasets())
    if dataset not in allowed:
        raise ValueError(f"dataset {dataset!r} is not in allowed_datasets {sorted(allowed)}")
    table = _svi_data.pano_table(project, dataset, "pano_observations_latest").strip("`")
    return template.replace("__PROJECT__.__DATASET__.pano_observations_latest", table)


def gcs_uri_for(bucket: str, snapshot_id: str, observation_id: str) -> str:
    """Derive `gs://<bucket>/<snapshot_id>/v0/<observation_id>.jpg` without selecting gcs_uri."""
    return _svi_data.gcs_uri_for(bucket, snapshot_id, observation_id)


def deduplicate_rosettes_spatially(
    panos: pd.DataFrame,
    min_spacing_m: float = 8.0,
) -> pd.DataFrame:
    """Deduplicate overlapping multi-year Street View passes at `min_spacing_m` (~8m) and sort
    geographically North-to-South, West-to-East (`(-round(lat, 5), round(lng, 5))`).
    """
    if panos.empty:
        return panos.copy()
    work = panos.copy()
    if "capture_time" in work.columns:
        work = work.sort_values("capture_time", ascending=False)
    if min_spacing_m > 0.0:
        kept_rows: list[pd.Series] = []
        kept_coords: list[tuple[float, float]] = []
        for _, row in work.iterrows():
            rlat, rlng = float(row["lat"]), float(row["lng"])
            if any(
                float(_svi_geo.haversine_m(rlat, rlng, klat, klng)) < min_spacing_m
                for klat, klng in kept_coords
            ):
                continue
            kept_rows.append(row)
            kept_coords.append((rlat, rlng))
        work = pd.DataFrame(kept_rows)
    work["_lat_sort"] = -work["lat"].round(5)
    work["_lng_sort"] = work["lng"].round(5)
    work = (
        work.sort_values(["_lat_sort", "_lng_sort", "capture_id"])
        .drop(columns=["_lat_sort", "_lng_sort"])
        .reset_index(drop=True)
    )
    work["cap_idx"] = list(range(len(work)))
    return work


def parse_observation_spec(spec: str) -> dict[str, list[dict[str, Any]]]:
    """Parse `--observations` string formatted as `P01=cap:cam:u:v,cap:cam:u:v;P02=...`."""
    out: dict[str, list[dict[str, Any]]] = {}
    for entry in (spec or "").split(";"):
        entry = entry.strip()
        if not entry or "=" not in entry:
            continue
        pole_id, obs_str = entry.split("=", 1)
        pole_id = pole_id.strip()
        obs_list: list[dict[str, Any]] = []
        for item in obs_str.split(","):
            parts = [p.strip() for p in item.strip().split(":")]
            if len(parts) != 4:
                raise ValueError(
                    f"Invalid observation {item!r} for {pole_id!r}; expected 'cap_idx:cam_k:u:v'."
                )
            cap_tok, cam_tok, u_tok, v_tok = parts
            ob: dict[str, Any] = {
                "cam_k": int(cam_tok),
                "u": float(u_tok),
                "v": float(v_tok),
            }
            if cap_tok.isdigit():
                ob["cap_idx"] = int(cap_tok)
            else:
                ob["capture_id"] = cap_tok
            obs_list.append(ob)
        if obs_list:
            out[pole_id] = obs_list
    return out


def load_candidates_input(
    candidates_json: str | None = None,
    candidates_csv: str | None = None,
) -> list[dict[str, Any]]:
    """Load 3D pole candidates `(pole_id, lat, lng, label)` from JSON or CSV for `--mode=render_candidates`."""
    if candidates_json:
        raw = json.loads(Path(candidates_json).read_text())
        items = raw.get("poles") or raw.get("candidates") or raw if isinstance(raw, Mapping) else raw
        out: list[dict[str, Any]] = []
        for idx, r in enumerate(items, start=1):
            out.append(
                {
                    "pole_id": str(r.get("pole_id") or r.get("entity_id") or f"P{idx:02d}"),
                    "lat": float(r["lat"]),
                    "lng": float(r["lng"]),
                    "pole_subtype": str(
                        r.get("pole_subtype") or r.get("label") or r.get("initial_cls") or "UTILITY_POLE"
                    ),
                }
            )
        return out
    if candidates_csv:
        out_csv: list[dict[str, Any]] = []
        with Path(candidates_csv).open(newline="") as f:
            reader = csv.DictReader(row for row in f if not row.lstrip().startswith("#"))
            for idx, r in enumerate(reader, start=1):
                out_csv.append(
                    {
                        "pole_id": str(
                            r.get("pole_id") or r.get("id") or r.get("entity_id") or f"P{idx:02d}"
                        ),
                        "lat": float(r["lat"]),
                        "lng": float(r["lng"]),
                        "pole_subtype": str(
                            r.get("pole_subtype") or r.get("label") or r.get("sub_class") or "UTILITY_POLE"
                        ),
                    }
                )
        return out_csv
    raise ValueError("Provide --candidates-json or --candidates-csv for --mode=render_candidates.")


def query_corridor_frames(
    project: str,
    dataset: str,
    bucket: str,
    *,
    lat: float | None = None,
    lng: float | None = None,
    lookup_id: str | None = None,
    radius_m: float = 80.0,
    max_rosettes: int = 6,
    min_spacing_m: float = 0.0,
) -> tuple[pd.DataFrame, float]:
    """Dry-run and execute the corridor rosette query under the 2 GB safety cap."""
    from google.cloud import bigquery

    creds = _svi_auth.get_credentials()
    client = bigquery.Client(project=project, credentials=creds)
    if lookup_id:
        sql = render_sql(ID_SQL, project, dataset)
        params = [
            bigquery.ScalarQueryParameter("id", "STRING", str(lookup_id)),
            bigquery.ScalarQueryParameter("radius_m", "FLOAT64", float(radius_m)),
        ]
    else:
        if lat is None or lng is None:
            raise ValueError("Provide either (lat, lng) or lookup_id.")
        sql = render_sql(COORDS_SQL, project, dataset)
        params = [
            bigquery.ScalarQueryParameter("lat", "FLOAT64", float(lat)),
            bigquery.ScalarQueryParameter("lng", "FLOAT64", float(lng)),
            bigquery.ScalarQueryParameter("radius_m", "FLOAT64", float(radius_m)),
        ]

    dry_cfg = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False, query_parameters=params)
    dry_job = client.query(sql, job_config=dry_cfg)
    bytes_est = int(dry_job.total_bytes_processed or 0)
    if bytes_est > MAX_BYTES_BILLED:
        raise RuntimeError(
            f"BigQuery dry-run estimated {bytes_est / 1e9:.2f} GB, exceeding {MAX_BYTES_BILLED / 1e9:.2f} GB cap."
        )

    run_cfg = bigquery.QueryJobConfig(
        query_parameters=params,
        maximum_bytes_billed=MAX_BYTES_BILLED,
    )
    rows = [dict(r.items()) for r in client.query(sql, job_config=run_cfg).result()]
    if not rows:
        return pd.DataFrame(), bytes_est / 1e9

    df = pd.DataFrame(rows)
    if (lat is None or lng is None) and "hit_lat" in df.columns and "hit_lng" in df.columns:
        lat = float(df["hit_lat"].iloc[0])
        lng = float(df["hit_lng"].iloc[0])
    elif lat is None or lng is None:
        lat = float(df["lat"].iloc[0])
        lng = float(df["lng"].iloc[0])

    df["cam_k"] = [
        _svi_rosette.camera_index(str(oid)) for oid in df["observation_id"]
    ]
    df = df[df["cam_k"].notna()].copy()
    df["cam_k"] = df["cam_k"].astype(int)

    # Keep complete 7-camera rosettes (or >= 6 ground cameras)
    counts = df.groupby("capture_id")["cam_k"].nunique()
    valid_caps = set(counts[counts >= 6].index)
    df = df[df["capture_id"].isin(valid_caps)].copy()
    if df.empty:
        return pd.DataFrame(), bytes_est / 1e9

    # Ensure pano_id is populated for sequence/triangulation helpers
    df["pano_id"] = df["capture_id"].astype(str)
    df["camera_pose"] = [
        {
            "heading": float(r["heading"] or 0.0),
            "pitch": float(r["pitch"] or 0.0) if pd.notna(r["pitch"]) else 0.0,
            "roll": float(r["roll"] or 0.0) if pd.notna(r["roll"]) else 0.0,
            "latitude": float(r["lat"]),
            "longitude": float(r["lng"]),
        }
        for _, r in df.iterrows()
    ]
    df["gcs_uri"] = [
        gcs_uri_for(bucket, str(s), str(o))
        for s, o in zip(df["snapshot_id"], df["observation_id"], strict=True)
    ]

    panos = df.drop_duplicates("pano_id").copy()
    if min_spacing_m > 0.0:
        panos = deduplicate_rosettes_spatially(panos, min_spacing_m=min_spacing_m)
    panos["dist_center_m"] = _svi_geo.haversine_m(
        panos["lat"].to_numpy(), panos["lng"].to_numpy(), float(lat), float(lng)
    )
    panos = panos.sort_values("dist_center_m").head(max(1, int(max_rosettes)))
    panos_geo = deduplicate_rosettes_spatially(panos, min_spacing_m=0.0)
    cap_idx_map = {str(r["pano_id"]): int(r["cap_idx"]) for _, r in panos_geo.iterrows()}
    seq_panos = _svi_sequence.build_sequences(panos)

    df = df.merge(
        seq_panos[["pano_id", "seq_id", "seq_idx"]],
        on="pano_id",
        how="inner",
    )
    df["cap_idx"] = [cap_idx_map.get(str(pid), 0) for pid in df["pano_id"]]
    df = df.sort_values(["seq_id", "seq_idx", "cam_k"]).reset_index(drop=True)
    return df, bytes_est / 1e9


def _select_pole_candidates(
    uc2_out: Mapping[str, Any],
    max_poles: int,
) -> list[Any]:
    """Select located pole/light candidates (preferring multi-pano triangulated entities)."""
    entities = list(uc2_out.get("entities") or [])
    located = [
        e
        for e in entities
        if getattr(e, "located", False)
        and getattr(e, "cls", "") in {"UTILITY_POLE", "STREET_LIGHT"}
    ]
    located.sort(
        key=lambda e: (
            0 if getattr(e, "method", "") == "triangulated" else 1,
            -int(getattr(e, "n_panos", 1)),
            -float(getattr(e, "confidence", 0.0)),
        )
    )
    return located[: max(1, int(max_poles))]


def _parse_int_list(val: str | None, default: Sequence[int]) -> list[int]:
    if not val:
        return list(default)
    return [int(x.strip()) for x in val.split(",") if x.strip()]


def _run_fetch_sv_mode(
    args: argparse.Namespace,
    frames: pd.DataFrame,
    fetch: Any,
    intr: _svi_rosette.Intrinsics,
    dry_run_gb: float,
) -> dict[str, Any]:
    """Render calibrated `(u,v)` + compass-azimuth camera frames, contact sheets, and `sv_index.json`."""
    out_dir = Path(args.output_dir or "./sv_inspection")
    sv_dir = out_dir / "sv_images"
    sv_dir.mkdir(parents=True, exist_ok=True)

    cam_indices = _parse_int_list(getattr(args, "camera_indices", None), (0, 1, 2, 3, 4, 5))
    cap_filter = (
        set(_parse_int_list(getattr(args, "capture_indices", None), ()))
        if getattr(args, "capture_indices", None)
        else None
    )

    captures_out: list[dict[str, Any]] = []
    saved_sheets: list[str] = []
    saved_frames: list[str] = []

    for cap_idx, grp in frames.groupby("cap_idx", sort=True):
        c_idx = int(cap_idx)
        if cap_filter is not None and c_idx not in cap_filter:
            continue
        rendered = _svi_uc.render_capture_contact_sheet(
            grp,
            fetch,
            intr,
            cap_idx=c_idx,
            camera_indices=cam_indices,
        )
        if rendered is None:
            continue
        sheet_path = sv_dir / f"cap_{c_idx:03d}_sheet.jpg"
        cv2.imwrite(str(sheet_path), rendered["contact_sheet"])
        saved_sheets.append(str(sheet_path))

        cam_files: dict[str, str] = {}
        for k, im in rendered["camera_frames"].items():
            cam_path = sv_dir / f"cap_{c_idx:03d}_cam_{int(k)}.jpg"
            cv2.imwrite(str(cam_path), im)
            cam_files[str(k)] = str(cam_path)
            saved_frames.append(str(cam_path))
            if str(k) in rendered["cameras"]:
                rendered["cameras"][str(k)]["image_file"] = str(cam_path)

        captures_out.append(
            {
                "cap_idx": c_idx,
                "capture_id": rendered["capture_id"],
                "capture_date": rendered["capture_date"],
                "lat": rendered["lat"],
                "lng": rendered["lng"],
                "heading": rendered["heading"],
                "contact_sheet_file": str(sheet_path),
                "cameras": rendered["cameras"],
            }
        )

    sv_index = {
        "mode": "fetch_sv",
        "corridor": {
            "center_lat": float(args.lat) if args.lat is not None else float(frames["lat"].iloc[0]),
            "center_lng": float(args.lng) if args.lng is not None else float(frames["lng"].iloc[0]),
            "radius_m": args.radius_m,
            "rosettes_inspected": len(captures_out),
            "bq_dry_run_gb": round(dry_run_gb, 4),
        },
        "captures": captures_out,
        "saved_contact_sheets": saved_sheets,
        "saved_camera_frames": saved_frames,
    }
    sv_index_path = out_dir / "sv_index.json"
    sv_index_path.write_text(json.dumps(sv_index, indent=2) + "\n")
    sv_index["sv_index_file"] = str(sv_index_path)
    return sv_index


async def run_pipeline(args: argparse.Namespace) -> dict[str, Any]:
    """Execute the requested `--mode` (`audit`, `fetch_sv`, `triangulate`, or `render_candidates`)."""
    mode = getattr(args, "mode", "audit") or "audit"
    intr = _svi_rosette.load_intrinsics()

    # Mode: triangulate can operate completely offline if sv_index.json exists in --output-dir
    if mode == "triangulate":
        obs_by_pole: dict[str, list[dict[str, Any]]] = {}
        if getattr(args, "observations_json", None):
            obs_by_pole = json.loads(Path(args.observations_json).read_text())
        elif getattr(args, "observations", None):
            obs_by_pole = parse_observation_spec(args.observations)
        else:
            raise ValueError("Provide --observations or --observations-json for --mode=triangulate.")

        sv_index_file = (
            Path(args.output_dir) / "sv_index.json"
            if getattr(args, "output_dir", None)
            else None
        )
        if sv_index_file is not None and sv_index_file.exists():
            sv_idx = json.loads(sv_index_file.read_text())
            tri_poles = _svi_uc.triangulate_observations_2d_enu(obs_by_pole, sv_idx, intr)
            cap_rows = [
                {
                    "capture_id": c["capture_id"],
                    "pano_id": c["capture_id"],
                    "lat": c["lat"],
                    "lng": c["lng"],
                    "seq_idx": i,
                }
                for i, c in enumerate(sv_idx.get("captures", []))
            ]
            span_audit = _svi_uc.audit_corridor_span_gaps(tri_poles, cap_rows)
        else:
            frames, _ = query_corridor_frames(
                args.project,
                args.dataset,
                args.gcs_bucket,
                lat=args.lat,
                lng=args.lng,
                lookup_id=getattr(args, "lookup_id", None),
                radius_m=args.radius_m,
                max_rosettes=args.max_rosettes,
                min_spacing_m=getattr(args, "min_spacing_m", 8.0),
            )
            tri_poles = _svi_uc.triangulate_observations_2d_enu(obs_by_pole, frames, intr)
            span_audit = _svi_uc.audit_corridor_span_gaps(tri_poles, frames)

        payload = {
            "mode": "triangulate",
            "triangulated_poles": tri_poles,
            "corridor_span_audit": span_audit,
        }
        if args.output_json:
            out_json_path = Path(args.output_json)
            out_json_path.parent.mkdir(parents=True, exist_ok=True)
            out_json_path.write_text(json.dumps(payload, indent=2) + "\n")
        return payload

    frames, dry_run_gb = query_corridor_frames(
        args.project,
        args.dataset,
        args.gcs_bucket,
        lat=args.lat,
        lng=args.lng,
        lookup_id=getattr(args, "lookup_id", None),
        radius_m=args.radius_m,
        max_rosettes=args.max_rosettes,
        min_spacing_m=getattr(args, "min_spacing_m", 0.0 if mode == "audit" else 8.0),
    )
    if frames.empty:
        raise RuntimeError(
            f"No complete 7-camera rosettes found within {args.radius_m}m of target."
        )
    center_lat = float(args.lat) if args.lat is not None else float(frames["lat"].iloc[0])
    center_lng = float(args.lng) if args.lng is not None else float(frames["lng"].iloc[0])

    from google.cloud import storage

    creds = _svi_auth.get_credentials()
    ref = (float(frames["lat"].iloc[0]), float(frames["lng"].iloc[0]), 0.0)
    cache_dir = (
        Path(args.output_dir) / ".tile_cache"
        if args.output_dir
        else _svi_images.DEFAULT_FRAME_CACHE
    )
    storage_client = storage.Client(project=args.project, credentials=creds)
    fetcher = _svi_images.GcsImageFetcher(storage_client, cache_dir=cache_dir)
    fetch = fetcher.fetch

    if mode == "fetch_sv":
        payload = _run_fetch_sv_mode(args, frames, fetch, intr, dry_run_gb)
        if args.output_json:
            out_json_path = Path(args.output_json)
            out_json_path.parent.mkdir(parents=True, exist_ok=True)
            out_json_path.write_text(json.dumps(payload, indent=2) + "\n")
        return payload

    if mode == "render_candidates":
        cands = load_candidates_input(
            candidates_json=getattr(args, "candidates_json", None),
            candidates_csv=getattr(args, "candidates_csv", None),
        )
        out_dir = Path(args.output_dir or "./sv_reprojection")
        sv_dir = out_dir / "sv_images"
        sv_dir.mkdir(parents=True, exist_ok=True)
        cam_indices = _parse_int_list(getattr(args, "camera_indices", None), (0, 1, 2, 3, 4, 5))
        cap_filter = (
            set(_parse_int_list(getattr(args, "capture_indices", None), ()))
            if getattr(args, "capture_indices", None)
            else None
        )

        reproj_sheets: list[str] = []
        for cap_idx, grp in frames.groupby("cap_idx", sort=True):
            c_idx = int(cap_idx)
            if cap_filter is not None and c_idx not in cap_filter:
                continue
            rendered = _svi_uc.render_capture_contact_sheet(
                grp,
                fetch,
                intr,
                cap_idx=c_idx,
                camera_indices=cam_indices,
                candidates=cands,
            )
            if rendered is None:
                continue
            sheet_path = sv_dir / f"reproj_cap_{c_idx:03d}_sheet.jpg"
            cv2.imwrite(str(sheet_path), rendered["contact_sheet"])
            reproj_sheets.append(str(sheet_path))

        rows_by_pano = {
            str(pid): grp.to_dict("records") for pid, grp in frames.groupby("pano_id", sort=False)
        }
        composite_files: list[str] = []
        for cand in cands:
            sel_panos, _ = _svi_uc._select_parallax_panos_for_pole(
                cand["lat"], cand["lng"], frames, set(), max_views=2
            )
            for v_idx, pid in enumerate(sel_panos, start=1):
                comp = _svi_uc.render_pole_inspection_composite(
                    rows_by_pano.get(pid, []),
                    cand["lat"],
                    cand["lng"],
                    fetch,
                    intr,
                )
                if comp is not None:
                    cpath = out_dir / f"{cand['pole_id']}_view{v_idx}_{pid[:12]}.png"
                    cv2.imwrite(str(cpath), comp["composite_img"])
                    composite_files.append(str(cpath))

        payload = {
            "mode": "render_candidates",
            "candidates_reprojected": len(cands),
            "reprojected_contact_sheets": reproj_sheets,
            "saved_composite_images": composite_files,
        }
        if args.output_json:
            out_json_path = Path(args.output_json)
            out_json_path.parent.mkdir(parents=True, exist_ok=True)
            out_json_path.write_text(json.dumps(payload, indent=2) + "\n")
        return payload

    v_client = _svi_gc.make_vertex_client(
        args.project,
        location=args.location,
        credentials=creds,
    )
    backend = _svi_gc.VertexGeminiBackend(
        v_client,
        model=args.model,
        location=args.location,
        log=lambda m: print(m, file=sys.stderr),
    )
    runner = _svi_gc.GeminiRunner(
        backend,
        max_calls=120,
        concurrency=6,
        log=lambda m: print(m, file=sys.stderr),
    )

    # Stage 1: Multi-rosette right-of-way detection + 3D ENU triangulation + single-view zoom infill
    uc2_out = await _svi_uc.uc2_run(
        frames,
        fetch,
        runner,
        intr,
        ref,
        max_presence_checks=4,
        variant=_svi_uc.DEFAULT_VARIANT,
    )
    candidates = _select_pole_candidates(uc2_out, max_poles=args.max_poles)

    # Stage 2: Multi-view 3-panel composite inspection + Gemini PoleSubClassification + LSD gates
    sub_out = await _svi_uc.subclassify_poles(
        candidates,
        frames,
        fetch,
        runner,
        intr,
        max_poles=args.max_poles,
        max_views_per_pole=2,
    )

    saved_images: list[str] = []
    out_dir = Path(args.output_dir) if args.output_dir else None
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)

    clean_records: list[dict[str, Any]] = []
    for rec in sub_out["records"]:
        rec_copy = {k: v for k, v in rec.items() if k != "composites"}
        comp_files: list[str] = []
        if out_dir is not None:
            for v_idx, comp in enumerate(rec.get("composites", []), start=1):
                fname = f"{rec['entity_id']}_view{v_idx}_{comp['pano_id'][:12]}.png"
                fpath = out_dir / fname
                cv2.imwrite(str(fpath), comp["composite_img"])
                comp_files.append(str(fpath))
                saved_images.append(str(fpath))
        rec_copy["inspection_composite_files"] = comp_files
        clean_records.append(rec_copy)

    infill_recovered = int(
        uc2_out.get("infill_recovered", uc2_out.get("infill_recovered_poles", 0))
    )
    span_audit = sub_out.get("corridor_span_audit") or _svi_uc.audit_corridor_span_gaps(
        clean_records, frames
    )
    payload = {
        "corridor": {
            "center_lat": center_lat,
            "center_lng": center_lng,
            "radius_m": args.radius_m,
            "rosettes_inspected": int(frames["pano_id"].nunique()),
            "frames_inspected": int(len(frames)),
            "bq_dry_run_gb": round(dry_run_gb, 4),
        },
        "summary": {
            "candidates_evaluated": len(clean_records),
            "true_utility_pole_count": sub_out["true_utility_pole_count"],
            "non_utility_vertical_count": sub_out["non_utility_vertical_count"],
            "false_detection_count": int(sub_out.get("false_detection_count", 0)),
            "infill_recovered_poles": infill_recovered,
            "corridor_span_gaps_over_50m": len(span_audit.get("span_gaps", [])),
        },
        "corridor_span_audit": span_audit,
        "poles": clean_records,
        "saved_composite_images": saved_images,
        "cost": {
            "model": args.model,
            "calls": runner.cost.calls,
            "input_tokens": runner.cost.input_tokens,
            "output_tokens": runner.cost.output_tokens,
            "usd": round(runner.cost.usd, 5),
        },
    }

    if args.output_json:
        out_json_path = Path(args.output_json)
        out_json_path.parent.mkdir(parents=True, exist_ok=True)
        out_json_path.write_text(json.dumps(payload, indent=2) + "\n")

    print(runner.cost.summary(), file=sys.stderr)
    return payload


def parse_args(
    argv: Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
) -> argparse.Namespace:
    """Parse CLI arguments with environment variable defaults (`PROJECT_ID`, `GCS_BUCKET`)."""
    env = os.environ if env is None else env
    p = argparse.ArgumentParser(
        description="Sub-classify roadside utility poles vs. lookalikes from Street View Insights (SV_PANO) rosettes."
    )
    p.add_argument(
        "--mode",
        choices=VALID_MODES,
        default="audit",
        help="Execution mode: audit (default), fetch_sv, triangulate, or render_candidates.",
    )
    p.add_argument(
        "--project",
        "--project_id",
        "--project-id",
        dest="project",
        default=env.get("PROJECT_ID") or env.get("GOOGLE_CLOUD_PROJECT"),
        help="Google Cloud project ID (defaults to $PROJECT_ID or $GOOGLE_CLOUD_PROJECT).",
    )
    p.add_argument(
        "--gcs-bucket",
        "--gcs_bucket",
        dest="gcs_bucket",
        default=env.get("GCS_BUCKET"),
        help="Street View Insights Cloud Storage bucket name (defaults to $GCS_BUCKET).",
    )
    p.add_argument(
        "--dataset",
        default=env.get("BQ_DATASET", DEFAULT_DATASET),
        help=f"BigQuery dataset name (default: {DEFAULT_DATASET}).",
    )
    p.add_argument(
        "--location",
        default=env.get("VERTEX_LOCATION", DEFAULT_LOCATION),
        help=f"Vertex AI location (default: {DEFAULT_LOCATION}).",
    )
    p.add_argument(
        "--model",
        default=env.get("GEMINI_MODEL", DEFAULT_MODEL),
        help=f"Gemini model name (default: {DEFAULT_MODEL}).",
    )
    p.add_argument("--lat", type=float, default=None, help="Corridor center latitude (WGS84).")
    p.add_argument("--lng", type=float, default=None, help="Corridor center longitude (WGS84).")
    p.add_argument(
        "--coordinates",
        default=None,
        help="Optional 'lat,lng' string (alternative to --lat and --lng).",
    )
    id_group = p.add_mutually_exclusive_group()
    id_group.add_argument(
        "--capture-id",
        "--capture_id",
        dest="capture_id",
        default=None,
        help="Look up corridor center from a specific capture_id.",
    )
    id_group.add_argument(
        "--pano-id",
        "--pano_id",
        dest="pano_id",
        default=None,
        help="Look up corridor center from a specific pano_id.",
    )
    id_group.add_argument(
        "--observation-id",
        "--observation_id",
        dest="observation_id",
        default=None,
        help="Look up corridor center from a specific observation_id.",
    )
    p.add_argument(
        "--radius-m",
        "--radius_m",
        dest="radius_m",
        type=float,
        default=80.0,
        help="Search radius in metres around (lat, lng) or ID lookup (default: 80).",
    )
    p.add_argument(
        "--max-rosettes",
        "--max_rosettes",
        dest="max_rosettes",
        type=int,
        default=6,
        help="Maximum 7-camera rosettes to inspect along the corridor (default: 6).",
    )
    p.add_argument(
        "--min-spacing-m",
        "--min_spacing_m",
        dest="min_spacing_m",
        type=float,
        default=0.0,
        help="Minimum spatial spacing in metres when deduplicating multi-year passes (default: 0 for audit, 8.0 for fetch_sv).",
    )
    p.add_argument(
        "--max-poles",
        "--max_poles",
        dest="max_poles",
        type=int,
        default=5,
        help="Maximum candidate vertical structures to sub-classify (default: 5).",
    )
    p.add_argument(
        "--capture-indices",
        "--capture_indices",
        dest="capture_indices",
        default=None,
        help="Optional comma-separated capture indices (e.g. '0,2,4') for --mode=fetch_sv or --mode=render_candidates.",
    )
    p.add_argument(
        "--camera-indices",
        "--camera_indices",
        dest="camera_indices",
        default="0,1,2,3,4,5",
        help="Comma-separated horizontal camera indices to render (default: '0,1,2,3,4,5').",
    )
    p.add_argument(
        "--observations",
        default=None,
        help="Pixel observation spec for --mode=triangulate ('P01=cap:cam:u:v,cap:cam:u:v;P02=...').",
    )
    p.add_argument(
        "--observations-json",
        "--observations_json",
        dest="observations_json",
        default=None,
        help="Path to JSON file mapping pole_id to [{'cap_idx': 0, 'cam_k': 4, 'u': 2240, 'v': 3120}, ...] for --mode=triangulate.",
    )
    p.add_argument(
        "--candidates-json",
        "--candidates_json",
        dest="candidates_json",
        default=None,
        help="Path to JSON file of triangulated pole candidates for --mode=render_candidates.",
    )
    p.add_argument(
        "--candidates-csv",
        "--candidates_csv",
        dest="candidates_csv",
        default=None,
        help="Path to CSV file ('pole_id,lat,lng,pole_subtype') for --mode=render_candidates.",
    )
    p.add_argument(
        "--output-json",
        "--output_json",
        "--output",
        dest="output_json",
        default=None,
        help="Optional path to write the structured JSON audit output.",
    )
    p.add_argument(
        "--output-dir",
        "--output_dir",
        dest="output_dir",
        default=None,
        help="Optional directory to save 3-panel inspection composites, calibrated SV contact sheets, and sv_index.json.",
    )

    args = p.parse_args(argv)
    if args.coordinates:
        try:
            lat_s, lng_s = [x.strip() for x in args.coordinates.split(",", 1)]
            args.lat = float(lat_s)
            args.lng = float(lng_s)
        except Exception:
            p.error(f"Invalid --coordinates {args.coordinates!r}; expected 'lat,lng'.")
    args.lookup_id = args.capture_id or args.pano_id or args.observation_id

    # Offline triangulation from an existing sv_index.json in --output-dir does not require coordinates/BQ
    has_local_sv_index = bool(
        args.mode == "triangulate"
        and args.output_dir
        and (Path(args.output_dir) / "sv_index.json").exists()
    )
    if not has_local_sv_index:
        if args.lookup_id is None and (args.lat is None or args.lng is None):
            p.error(
                "Provide --lat and --lng (or --coordinates 'lat,lng'), or one of --capture-id / --pano-id / --observation-id."
            )
        if not args.project:
            p.error("Provide --project / --project_id or set $PROJECT_ID.")
        if not args.gcs_bucket:
            p.error("Provide --gcs-bucket / --gcs_bucket or set $GCS_BUCKET.")
        args.gcs_bucket = str(args.gcs_bucket).removeprefix("gs://").strip("/")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    payload = asyncio.run(run_pipeline(args))
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
