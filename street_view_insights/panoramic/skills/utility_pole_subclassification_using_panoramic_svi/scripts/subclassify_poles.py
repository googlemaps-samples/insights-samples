#!/usr/bin/env python3
"""Multi-view utility pole sub-classification and equipment audit from Street View Insights (`SV_PANO`).

Discovers roadside vertical structures across a sequence of 7-camera `SV_PANO` rosettes,
triangulates their 3D positions in a local East-North-Up (ENU) frame, renders calibrated
3-panel inspection composites (Full Vertical Shaft + Crown/Cross-Arm Zoom + Base/Ground Zoom)
from approach and recede viewpoints, and fuses Gemini structured sub-classification with
deterministic OpenCV Line Segment Detector (LSD) verticality and lean-angle gates.
"""

from __future__ import annotations

import argparse
import asyncio
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
    table = _svi_data.pano_table(project, dataset, "pano_observations_latest")
    return template.replace("__PROJECT__.__DATASET__.pano_observations_latest", table)


def gcs_uri_for(bucket: str, snapshot_id: str, observation_id: str) -> str:
    """Derive `gs://<bucket>/<snapshot_id>/v0/<observation_id>.jpg` without selecting gcs_uri."""
    return _svi_data.gcs_uri_for(bucket, snapshot_id, observation_id)


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
    panos["dist_center_m"] = _svi_geo.haversine_m(
        panos["lat"].to_numpy(), panos["lng"].to_numpy(), float(lat), float(lng)
    )
    panos = panos.sort_values("dist_center_m").head(max(1, int(max_rosettes)))
    seq_panos = _svi_sequence.build_sequences(panos)

    df = df.merge(
        seq_panos[["pano_id", "seq_id", "seq_idx"]],
        on="pano_id",
        how="inner",
    )
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


async def run_pipeline(args: argparse.Namespace) -> dict[str, Any]:
    """Execute corridor discovery, 3D pole triangulation, 3-panel composite rendering, and sub-classification."""
    frames, dry_run_gb = query_corridor_frames(
        args.project,
        args.dataset,
        args.gcs_bucket,
        lat=args.lat,
        lng=args.lng,
        lookup_id=getattr(args, "lookup_id", None),
        radius_m=args.radius_m,
        max_rosettes=args.max_rosettes,
    )
    if frames.empty:
        raise RuntimeError(
            f"No complete 7-camera rosettes found within {args.radius_m}m of target."
        )
    center_lat = float(args.lat) if args.lat is not None else float(frames["lat"].iloc[0])
    center_lng = float(args.lng) if args.lng is not None else float(frames["lng"].iloc[0])

    from google.cloud import storage

    creds = _svi_auth.get_credentials()
    intr = _svi_rosette.load_intrinsics()
    ref = (float(frames["lat"].iloc[0]), float(frames["lng"].iloc[0]), 0.0)
    cache_dir = (
        Path(args.output_dir) / ".tile_cache"
        if args.output_dir
        else _svi_images.DEFAULT_FRAME_CACHE
    )
    storage_client = storage.Client(project=args.project, credentials=creds)
    fetcher = _svi_images.GcsImageFetcher(storage_client, cache_dir=cache_dir)
    fetch = fetcher.fetch

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
        },
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
        "--max-poles",
        "--max_poles",
        dest="max_poles",
        type=int,
        default=5,
        help="Maximum candidate vertical structures to sub-classify (default: 5).",
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
        help="Optional directory to save the 3-panel calibrated inspection composite PNGs.",
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
