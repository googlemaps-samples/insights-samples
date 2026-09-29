#!/usr/bin/env python3
"""Surface material detection on one panoramic Street View frame (pano views only).

Pipeline (all deterministic code except the single Gemini perception call):
1. Metadata lookup in `pano_observations_latest` with parameterised SQL (no `gcs_uri` column:
   selecting it scans ~1.9 GB, so the frame path is derived from the published pattern
   gs://<bucket>/<snapshot_id>/v0/<observation_id>.jpg).
2. Pick the forward-facing camera of the pano from the travel direction (neighbouring panos
   of the same drive), falling back to camera 0.
3. Download the frame with the caller's credentials and render a road-facing view in code
   (rectified with svi_geo when installed, otherwise a fixed lower-frame crop).
4. Send the view INLINE as bytes to Gemini with a pydantic `response_schema`; the reply is
   validated in code (numeric confidence, shared material taxonomy incl. Turf).
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import math
import os
import re
import sys
from enum import Enum
from pathlib import Path

import cv2
import numpy as np
from pydantic import BaseModel, Field

DEFAULT_DATASET = "imagery_insights___us"
MAX_BYTES_BILLED = 2_000_000_000
MAX_IMAGE_SIDE = 1536
BUCKET_CACHE = Path.home() / ".cache" / "svi_geo" / "bucket.json"

# ----------------------------------------------------------------------------- schema
# Copied from svi_geo.schemas so the skill runs stand-alone; a test keeps them identical.


class SurfaceMaterial(str, Enum):
    PAVED_ASPHALT = "Paved Asphalt"
    CONCRETE = "Concrete"
    BRICK_PAVERS = "Brick/Pavers"
    COBBLESTONE = "Cobblestone"
    GRAVEL = "Gravel"
    DIRT = "Dirt"
    MUD = "Mud"
    TURF = "Turf"
    UNPAVED = "Unpaved"
    OTHER = "Other"


class SurfaceCondition(str, Enum):
    GOOD = "Good"
    FAIR = "Fair"
    DAMAGED = "Damaged/Potholes"
    SEVERELY_DEGRADED = "Severely Degraded"


class SurfaceMaterialResult(BaseModel):
    """Single-image surface material answer (the skill's output)."""

    primary_material: SurfaceMaterial
    secondary_materials: list[SurfaceMaterial] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    surface_condition: SurfaceCondition
    visual_reasoning: str


SURFACE_MATERIAL_PROMPT = (
    "Act as a civil engineering material analyst. The image is a rectified, downward-looking "
    "street-level view of the ground in front of the capture vehicle. Identify the dominant "
    "material of the main traveled surface, any secondary surface materials, and the surface "
    "condition. Base the answer only on visible texture, aggregate, joints, colour and wear. "
    "confidence is your probability (0-1) that primary_material is correct."
)

# ----------------------------------------------------------------------------- SQL

_FIELDS = """
  pano_id, observation_id, snapshot_id, capture_time,
  capture_location.latitude AS lat, capture_location.longitude AS lng,
  camera_pose.heading AS heading"""

# Frames of every pano within @radius_m of the point (the nearest pano plus its neighbours,
# which give the travel direction). Filtered with ST_DWITHIN, never a full-table ORDER BY.
COORDS_SQL = (
    "SELECT"
    + _FIELDS
    + """
FROM `__PROJECT__.__DATASET__.pano_observations_latest`
WHERE pano_id IS NOT NULL
  AND ST_DWITHIN(ST_GEOGPOINT(capture_location.longitude, capture_location.latitude),
                 ST_GEOGPOINT(@lng, @lat), @radius_m)
"""
)

# Frames of the pano identified by @id (observation, pano or capture id) plus its neighbours.
ID_SQL = (
    "SELECT"
    + _FIELDS
    + """
FROM `__PROJECT__.__DATASET__.pano_observations_latest`
WHERE pano_id IS NOT NULL
  AND ST_DWITHIN(ST_GEOGPOINT(capture_location.longitude, capture_location.latitude),
    (SELECT ANY_VALUE(capture_location) FROM `__PROJECT__.__DATASET__.pano_observations_latest`
     WHERE pano_id IS NOT NULL AND (observation_id = @id OR pano_id = @id OR capture_id = @id)),
    @radius_m)
"""
)

BUCKET_SQL = (
    "SELECT gcs_uri FROM `__PROJECT__.__DATASET__.pano_observations_latest` "
    "WHERE pano_id IS NOT NULL LIMIT 1"
)

_IDENT = re.compile(r"^[A-Za-z0-9_\-.]+$")


def render_sql(template: str, project: str, dataset: str) -> str:
    """Substitute validated identifiers (values always go through query parameters)."""
    for v in (project, dataset):
        if not _IDENT.match(v or ""):
            raise ValueError(f"invalid BigQuery identifier: {v!r}")
    return template.replace("__PROJECT__", project).replace("__DATASET__", dataset)


def run_query(client, sql: str, params: list) -> list:
    from google.cloud import bigquery

    dry = client.query(
        sql,
        job_config=bigquery.QueryJobConfig(
            dry_run=True, use_query_cache=False, query_parameters=params
        ),
    )
    gb = (dry.total_bytes_processed or 0) / 1e9
    print(
        f"[bigquery] dry run: {gb:.3f} GB (cap {MAX_BYTES_BILLED / 1e9:.1f} GB)",
        file=sys.stderr,
    )
    if (dry.total_bytes_processed or 0) > MAX_BYTES_BILLED:
        raise RuntimeError(f"query would scan {gb:.2f} GB > cap")
    cfg = bigquery.QueryJobConfig(
        maximum_bytes_billed=MAX_BYTES_BILLED, query_parameters=params
    )
    return [dict(r) for r in client.query(sql, job_config=cfg).result()]


def gcs_uri_for(bucket: str, snapshot_id: str, observation_id: str) -> str:
    return f"gs://{bucket}/{snapshot_id}/v0/{observation_id}.jpg"


def discover_bucket(client, project: str, dataset: str, override: str | None) -> str:
    if override:
        return override.removeprefix("gs://").strip("/")
    if os.environ.get("GCS_BUCKET"):
        return os.environ["GCS_BUCKET"].removeprefix("gs://").strip("/")
    table = f"{project}.{dataset}.pano_observations_latest"
    cache = json.loads(BUCKET_CACHE.read_text()) if BUCKET_CACHE.exists() else {}
    if table in cache:
        return cache[table]
    rows = run_query(client, render_sql(BUCKET_SQL, project, dataset), [])
    bucket = rows[0]["gcs_uri"].removeprefix("gs://").split("/", 1)[0]
    cache[table] = bucket
    BUCKET_CACHE.parent.mkdir(parents=True, exist_ok=True)
    BUCKET_CACHE.write_text(json.dumps(cache, indent=2))
    return bucket


# ----------------------------------------------------------------------------- geometry


def _camera_index(observation_id: str) -> int | None:
    m = re.match(r"^o1:.+_(\d):5001ee$", observation_id or "")
    return int(m.group(1)) if m else None


def _bearing(lat1, lng1, lat2, lng2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lng2 - lng1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.atan2(x, y)) % 360.0


def _dist_m(lat1, lng1, lat2, lng2) -> float:
    k = 111_320.0
    return math.hypot(
        (lat2 - lat1) * k, (lng2 - lng1) * k * math.cos(math.radians(lat1))
    )


def travel_direction(
    rows: list[dict], pano_id: str, max_dt_s: float = 5.0
) -> float | None:
    """Bearing from the previous to the next pano of the same drive (same snapshot, <= 5 s)."""
    panos = {}
    for r in rows:
        panos.setdefault(r["pano_id"], r)
    me = panos[pano_id]
    t0 = me["capture_time"]
    same = [
        p
        for p in panos.values()
        if p["snapshot_id"] == me["snapshot_id"]
        and abs((p["capture_time"] - t0).total_seconds()) <= max_dt_s
    ]
    same.sort(key=lambda p: p["capture_time"])
    if len(same) < 2:
        return None
    first, last = same[0], same[-1]
    if _dist_m(first["lat"], first["lng"], last["lat"], last["lng"]) < 1.0:
        return None
    return _bearing(first["lat"], first["lng"], last["lat"], last["lng"])


def pick_front_camera(frames: list[dict], travel_deg: float | None) -> dict:
    """Ground camera (0-5) whose heading is closest to the travel direction (else camera 0)."""
    ground = [f for f in frames if 0 <= int(f["cam_k"]) <= 5]
    if travel_deg is None:
        return min(ground, key=lambda f: int(f["cam_k"]))

    def diff(f):
        return abs(((float(f["heading"]) - travel_deg + 180.0) % 360.0) - 180.0)

    return min(ground, key=lambda f: (diff(f), int(f["cam_k"])))


def _fit_within(img: np.ndarray, max_side: int = MAX_IMAGE_SIDE) -> np.ndarray:
    h, w = img.shape[:2]
    s = max_side / max(h, w)
    return (
        cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
        if s < 1
        else img
    )


def road_view(image: np.ndarray) -> np.ndarray:
    """Deterministic road-facing view: rectified 25 deg below the optical axis with svi_geo's
    fitted fisheye model when installed, else a fixed crop of the lower frame."""
    try:
        from svi_geo import rosette

        # 60 deg wide, 25 deg down: stays inside the lens field of view
        view = rosette.PerspectiveView(0.0, -12.0, 60.0, 1024, 1024)
        intr = rosette.load_intrinsics()
        ident = {"heading": 0.0, "pitch": 0.0, "roll": 0.0}
        intr0 = dataclasses.replace(intr, pose_convention=(1, 1), cam_rot_delta_deg={})
        out = rosette.render_perspective(image, intr0, ident, view)
    except ImportError:
        h, w = image.shape[:2]
        out = image[int(0.55 * h) : int(0.82 * h), int(0.1 * w) : int(0.9 * w)]
    return _fit_within(out)


# ----------------------------------------------------------------------------- auth


def _optional_svi_geo_auth():
    """(credentials, extra genai HttpOptions kwargs) from svi_geo if installed, else defaults.

    svi_geo honours SVI_USE_GCLOUD_TOKEN / SVI_ECP_PROXY_URL (optional workstation helpers);
    without it every client uses Application Default Credentials and the public endpoint."""
    try:
        from svi_geo import auth
    except ImportError:
        return None, {}
    return auth.get_credentials(), auth.genai_http_options_kwargs()


# ----------------------------------------------------------------------------- main


def parse_args():
    p = argparse.ArgumentParser(
        description="Surface material detection (panoramic SVI)."
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--image", help="Path to a local image file (already downloaded).")
    g.add_argument("--observation-id", "--pano-id", dest="observation_id")
    g.add_argument("--coordinates", help="'lat,lng' - nearest pano within --radius-m")
    p.add_argument("--radius-m", type=float, default=30.0)
    p.add_argument("--output", help="Optional path to save the JSON result.")
    p.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT"))
    p.add_argument("--dataset", default=os.getenv("BIGQUERY_DATASET", DEFAULT_DATASET))
    p.add_argument(
        "--gcs-bucket", default=None, help="Frame bucket (skips a ~1.9 GB lookup)."
    )
    p.add_argument("--location", default="global")
    p.add_argument("--model", default="gemini-3.5-flash")
    return p.parse_args()


def fetch_frame(args) -> tuple[np.ndarray, dict]:
    from google.cloud import bigquery, storage

    creds, _ = _optional_svi_geo_auth()
    bq = bigquery.Client(project=args.project, credentials=creds)
    project = args.project or bq.project
    if args.coordinates:
        lat, lng = (float(x) for x in args.coordinates.split(","))
        params = [
            bigquery.ScalarQueryParameter("lat", "FLOAT64", lat),
            bigquery.ScalarQueryParameter("lng", "FLOAT64", lng),
            bigquery.ScalarQueryParameter("radius_m", "FLOAT64", args.radius_m),
        ]
        rows = run_query(bq, render_sql(COORDS_SQL, project, args.dataset), params)
        if not rows:
            raise ValueError(f"no pano within {args.radius_m} m of {lat},{lng}")
        near = min(rows, key=lambda r: _dist_m(lat, lng, r["lat"], r["lng"]))
    else:
        params = [
            bigquery.ScalarQueryParameter("id", "STRING", args.observation_id),
            bigquery.ScalarQueryParameter("radius_m", "FLOAT64", args.radius_m),
        ]
        rows = run_query(bq, render_sql(ID_SQL, project, args.dataset), params)
        hit = [
            r
            for r in rows
            if args.observation_id in (r["observation_id"], r["pano_id"])
        ]
        if not hit:
            raise ValueError(f"no pano observation found for {args.observation_id}")
        near = hit[0]
    pano = near["pano_id"]
    frames = [
        {**r, "cam_k": _camera_index(r["observation_id"])}
        for r in rows
        if r["pano_id"] == pano
    ]
    frames = [f for f in frames if f["cam_k"] is not None]
    travel = travel_direction(rows, pano)
    cam = pick_front_camera(frames, travel)
    bucket = discover_bucket(bq, project, args.dataset, args.gcs_bucket)
    uri = gcs_uri_for(bucket, cam["snapshot_id"], cam["observation_id"])
    name = uri.removeprefix("gs://").split("/", 1)[1]
    gcs = storage.Client(project=project, credentials=creds)
    data = gcs.bucket(bucket).blob(name).download_as_bytes()
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    meta = {
        "pano_id": pano,
        "observation_id": cam["observation_id"],
        "cam_k": cam["cam_k"],
        "travel_deg": travel,
        "capture_time": str(cam["capture_time"]),
        "project": project,
    }
    return img, meta


def main():
    args = parse_args()
    try:
        if args.image:
            img = cv2.imread(args.image, cv2.IMREAD_COLOR)
            if img is None:
                raise ValueError(f"cannot read {args.image}")
            meta = {"image": args.image, "project": args.project}
        else:
            img, meta = fetch_frame(args)
    except Exception as e:  # noqa: BLE001 - CLI boundary
        print(f"Error loading image: {e}", file=sys.stderr)
        sys.exit(1)

    from google import genai
    from google.genai import types

    view = road_view(img)
    ok, jpg = cv2.imencode(".jpg", view, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        print("Error: could not encode the road view", file=sys.stderr)
        sys.exit(1)
    creds, http_kw = _optional_svi_geo_auth()
    client = genai.Client(
        vertexai=True,
        project=meta["project"],
        location=args.location,
        credentials=creds,
        http_options=types.HttpOptions(**http_kw) if http_kw else None,
    )
    try:
        resp = client.models.generate_content(
            model=args.model,
            contents=[
                types.Part.from_bytes(data=jpg.tobytes(), mime_type="image/jpeg"),
                SURFACE_MATERIAL_PROMPT,
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=SurfaceMaterialResult,
            ),
        )
        result = SurfaceMaterialResult.model_validate_json(resp.text)
    except Exception as e:  # noqa: BLE001 - CLI boundary
        print(f"Material detection failed: {e}", file=sys.stderr)
        sys.exit(1)
    out = {
        **result.model_dump(mode="json"),
        "source": {k: v for k, v in meta.items() if k != "project"},
        "created": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }
    text = json.dumps(out, indent=2)
    print(text)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text)
        print(f"Saved surface material analysis to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
