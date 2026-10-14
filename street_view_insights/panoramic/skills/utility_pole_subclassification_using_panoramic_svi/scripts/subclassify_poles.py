#!/usr/bin/env python3
"""Multi-view utility pole sub-classification and equipment audit on panoramic Street View Insights (`SV_PANO`).

Pipeline (100% in-memory image processing — never writes Street View or composite images to disk):
1. Metadata lookup in `pano_observations_latest` with parameterised SQL under a 2 GB dry-run cap
   (deriving `gs://<bucket>/<snapshot_id>/v0/<observation_id>.jpg` without selecting `gcs_uri`).
2. Spatial deduplication (~8 m spacing) and multi-rosette right-of-way detection + height-invariant
   2D horizontal `(East, North)` ENU triangulation (`> 10 deg` parallax rule; single-view `40 deg`
   adjacent-capture zoom infill).
3. In-memory 3-panel multi-zone crop generation (`[1: Full Vertical Shaft | 2: Crown & Cross-Arm Zoom (2x)
   | 3: Base & Ground Collar Zoom (2x)]`) cropped above the capture-vehicle hood (`< 1%` black border).
4. Inline perception (`PoleSubClassification`) fused with deterministic OpenCV LSD verticality and
   lean-angle gates (`estimate_post_lean_deg`).
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
DEFAULT_RADIUS_M = 60.0
MAX_ROSETTES = 6
MAX_POLES = 5
MIN_SPACING_M = 8.0
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
    table = _svi_data.pano_table(project, dataset, "pano_observations_latest").strip("`")
    return template.replace("__PROJECT__.__DATASET__.pano_observations_latest", table)


def gcs_uri_for(bucket: str, snapshot_id: str, observation_id: str) -> str:
    """Derive `gs://<bucket>/<snapshot_id>/v0/<observation_id>.jpg` without selecting gcs_uri."""
    return _svi_data.gcs_uri_for(bucket, snapshot_id, observation_id)


def deduplicate_rosettes_spatially(
    panos: pd.DataFrame,
    min_spacing_m: float = MIN_SPACING_M,
) -> pd.DataFrame:
    """Deduplicate overlapping multi-year Street View passes at `min_spacing_m` (~8 m)."""
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
    return work.reset_index(drop=True)


def query_corridor_frames(
    project: str,
    dataset: str,
    bucket: str,
    *,
    lat: float | None = None,
    lng: float | None = None,
    lookup_id: str | None = None,
    radius_m: float = DEFAULT_RADIUS_M,
    max_rosettes: int = MAX_ROSETTES,
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
    panos_dedup = deduplicate_rosettes_spatially(panos, min_spacing_m=MIN_SPACING_M)
    if len(panos_dedup) >= 2:
        panos = panos_dedup
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
    max_poles: int = MAX_POLES,
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
    """Run in-memory corridor discovery, 2D ENU triangulation, and 3-panel pole sub-classification."""
    frames, _ = query_corridor_frames(
        args.project,
        args.dataset,
        args.gcs_bucket,
        lat=args.lat,
        lng=args.lng,
        lookup_id=args.lookup_id,
        radius_m=args.radius_m,
    )
    if frames.empty:
        raise RuntimeError(
            f"No complete 7-camera rosettes found within {args.radius_m}m of target."
        )

    from google.cloud import storage

    creds = _svi_auth.get_credentials()
    intr = _svi_rosette.load_intrinsics()
    ref = (float(frames["lat"].iloc[0]), float(frames["lng"].iloc[0]), 0.0)

    # Purely in-memory GCS image fetcher (cache_dir=None) with per-run dict memoization
    storage_client = storage.Client(project=args.project, credentials=creds)
    raw_fetcher = _svi_images.GcsImageFetcher(storage_client, cache_dir=None)
    mem_cache: dict[str, bytes] = {}

    def fetch(uri: str) -> bytes:
        if uri not in mem_cache:
            mem_cache[uri] = raw_fetcher.fetch(uri)
        return mem_cache[uri]

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

    # Stage 1: Multi-rosette right-of-way detection + 2D horizontal ENU triangulation + single-view zoom infill
    uc2_out = await _svi_uc.uc2_run(
        frames,
        fetch,
        runner,
        intr,
        ref,
        max_presence_checks=4,
        variant=_svi_uc.DEFAULT_VARIANT,
    )
    candidates = _select_pole_candidates(uc2_out, max_poles=MAX_POLES)

    # Stage 2: In-memory 3-panel composite inspection + Gemini PoleSubClassification + LSD gates
    sub_out = await _svi_uc.subclassify_poles(
        candidates,
        frames,
        fetch,
        runner,
        intr,
        max_poles=MAX_POLES,
        max_views_per_pole=2,
    )

    poles = list(sub_out.get("poles") or [])
    payload = {
        "pole_count": len(poles),
        "poles": poles,
    }

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2) + "\n")

    print(runner.cost.summary(), file=sys.stderr)
    return payload


def _parse_coordinates(raw: Sequence[str] | str) -> tuple[float, float]:
    tokens = [raw] if isinstance(raw, str) else list(raw)
    joined = ",".join(t.strip() for t in tokens if t.strip())
    parts = [p.strip() for p in joined.split(",") if p.strip()]
    if len(parts) != 2:
        raise ValueError(f"Expected 'lat,lng' or 'LAT LNG', got {raw!r}")
    return float(parts[0]), float(parts[1])


def parse_args(
    argv: Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
) -> argparse.Namespace:
    """Parse CLI arguments with environment variable defaults (`PROJECT_ID`, `GCS_BUCKET`)."""
    env = os.environ if env is None else env
    p = argparse.ArgumentParser(
        description="Sub-classify roadside utility poles vs. lookalikes from panoramic Street View Insights (SV_PANO).",
        allow_abbrev=False,
    )
    target = p.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--coordinates",
        nargs="+",
        metavar="LAT,LNG",
        help="Target GPS coordinates ('lat,lng' or 'LAT LNG').",
    )
    target.add_argument(
        "--capture-id",
        dest="capture_id",
        help="Panoramic capture_id (rosette key).",
    )
    target.add_argument(
        "--observation-id",
        dest="observation_id",
        help="Panoramic observation_id.",
    )
    p.add_argument(
        "--project",
        default=env.get("PROJECT_ID") or env.get("GOOGLE_CLOUD_PROJECT"),
        help="Google Cloud project ID for BigQuery and Vertex AI (default: $PROJECT_ID or $GOOGLE_CLOUD_PROJECT).",
    )
    p.add_argument(
        "--gcs-bucket",
        dest="gcs_bucket",
        default=env.get("GCS_BUCKET"),
        help="Cloud Storage bucket name for Street View Insights imagery (default: $GCS_BUCKET).",
    )
    p.add_argument(
        "--radius-m",
        dest="radius_m",
        type=float,
        default=DEFAULT_RADIUS_M,
        help=f"Search radius in meters around --coordinates (default: {DEFAULT_RADIUS_M}).",
    )
    p.add_argument(
        "--dataset",
        default=env.get("BIGQUERY_DATASET") or env.get("BQ_DATASET") or DEFAULT_DATASET,
        help=f"BigQuery dataset name (default: {DEFAULT_DATASET}).",
    )
    p.add_argument(
        "--model",
        default=env.get("GEMINI_MODEL", DEFAULT_MODEL),
        help=f"Gemini model name (default: {DEFAULT_MODEL}).",
    )
    p.add_argument(
        "--location",
        default=env.get("VERTEX_LOCATION", DEFAULT_LOCATION),
        help=f"Vertex AI region (default: {DEFAULT_LOCATION}).",
    )
    p.add_argument(
        "--output",
        default=None,
        help="Output JSON file path (prints to stdout if omitted).",
    )

    args = p.parse_args(argv)
    args.lat = None
    args.lng = None
    if args.coordinates:
        try:
            args.lat, args.lng = _parse_coordinates(args.coordinates)
        except Exception:
            p.error(f"Invalid --coordinates {args.coordinates!r}; expected 'lat,lng' or 'LAT LNG'.")
    args.lookup_id = args.capture_id or args.observation_id
    if not args.project:
        p.error("Provide --project or set the PROJECT_ID environment variable.")
    if not args.gcs_bucket:
        p.error("Provide --gcs-bucket or set the GCS_BUCKET environment variable.")
    args.gcs_bucket = str(args.gcs_bucket).removeprefix("gs://").strip("/")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    payload = asyncio.run(run_pipeline(args))
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
