#!/usr/bin/env python3
"""Surface material detection on one panoramic Street View frame (pano views only).

Pipeline (all deterministic code except the single Gemini perception call):
1. Metadata lookup in `pano_observations_latest` with parameterised SQL (no `gcs_uri` column:
   selecting it scans ~1.9 GB, so the frame path is derived from the published pattern
   gs://<bucket>/<snapshot_id>/v0/<observation_id>.jpg).
2. Travel direction from the neighbouring panos of the same drive (or `--travel-deg`); the
   script stops if neither is available rather than guessing a camera.
3. Download the frame(s) with the caller's credentials and render a road view in code: with
   svi_geo installed, a view centred on the travel direction and pitched down in world
   coordinates (`sequence.road_view`: the covering camera, or the two cameras flanking the
   seam composited), with the vehicle hood cropped and less than 1 % outside the sensor
   (checked); otherwise a fixed lower-frame crop of the camera nearest the travel direction.
4. Send the view INLINE as bytes to Gemini with a pydantic `response_schema`; the reply is
   validated in code (numeric confidence, shared material taxonomy incl. Turf). The token
   usage and estimated cost are printed.
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
  camera_pose.heading AS heading, camera_pose.pitch AS pitch, camera_pose.roll AS roll"""

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

# Frames of the pano identified by @id (observation, pano or capture id) plus its neighbours:
# the id is looked up once (LIMIT 1) and the frames are filtered by distance to that location.
# The table is not clustered, so BigQuery bills the referenced columns in full; the dry run
# measured 1.63 GB (COORDS_SQL: 1.40 GB), both under the 2 GB cap.
ID_SQL = (
    """WITH hit AS (
  SELECT capture_location.latitude AS lat, capture_location.longitude AS lng
  FROM `__PROJECT__.__DATASET__.pano_observations_latest`
  WHERE pano_id IS NOT NULL AND (observation_id = @id OR pano_id = @id OR capture_id = @id)
  LIMIT 1
)
SELECT hit.lat AS hit_lat, hit.lng AS hit_lng,"""
    + _FIELDS
    + """
FROM `__PROJECT__.__DATASET__.pano_observations_latest`, hit
WHERE pano_id IS NOT NULL
  AND ST_DWITHIN(ST_GEOGPOINT(capture_location.longitude, capture_location.latitude),
                 ST_GEOGPOINT(hit.lng, hit.lat), @radius_m)
"""
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
    cfg = bigquery.QueryJobConfig(maximum_bytes_billed=MAX_BYTES_BILLED, query_parameters=params)
    return [dict(r) for r in client.query(sql, job_config=cfg).result()]


def gcs_uri_for(bucket: str, snapshot_id: str, observation_id: str) -> str:
    """gs://<bucket>/<snapshot_id>/v0/<observation_id>.jpg (the published frame layout)."""
    return f"gs://{bucket}/{snapshot_id}/v0/{observation_id}.jpg"


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
    return math.hypot((lat2 - lat1) * k, (lng2 - lng1) * k * math.cos(math.radians(lat1)))


def travel_direction(rows: list[dict], pano_id: str, max_dt_s: float = 5.0) -> float | None:
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


def resolve_travel(measured: float | None, override: float | None) -> float:
    """`--travel-deg` if given, else the measured travel direction; never a guess."""
    if override is not None:
        return float(override) % 360.0
    if measured is None:
        raise ValueError(
            "cannot determine the travel direction (no neighbouring pano of the same drive "
            "within 5 s); pass --travel-deg"
        )
    return float(measured)


def pick_front_camera(frames: list[dict], travel_deg: float | None) -> dict:
    """Ground camera (0-5) whose heading is closest to the travel direction (fallback view
    when svi_geo is not installed)."""
    ground = [f for f in frames if 0 <= int(f["cam_k"]) <= 5]
    if travel_deg is None:
        raise ValueError("the travel direction is required to pick the front camera")

    def diff(f):
        return abs(((float(f["heading"]) - travel_deg + 180.0) % 360.0) - 180.0)

    return min(ground, key=lambda f: (diff(f), int(f["cam_k"])))


def _fit_within(img: np.ndarray, max_side: int = MAX_IMAGE_SIDE) -> np.ndarray:
    h, w = img.shape[:2]
    s = max_side / max(h, w)
    return cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA) if s < 1 else img


ROAD_PITCH_DEG = -22.0  # world pitch of the road view (PerspectiveView angles are world)
ROAD_HFOV_DEG = 60.0
ROAD_VIEW_SIZE = (1024, 768)


MAX_BLACK = 0.01  # share of the sent view allowed outside the sensor


def plan_road_view(frames: list[dict], travel_deg: float):
    """svi_geo `RoadView` centred on `travel_deg`: the ground camera that covers it, or the
    cameras flanking the seam composited. Raises ValueError if no view can be rendered."""
    from svi_geo import rosette, sequence

    rv = sequence.road_view(
        frames, rosette.load_intrinsics(), travel_deg, "front",
        pitch_deg=ROAD_PITCH_DEG, hfov_deg=ROAD_HFOV_DEG, size=ROAD_VIEW_SIZE,
    )  # fmt: skip
    if rv is None:
        raise ValueError(f"no camera of this pano covers a road view at {travel_deg:.1f} deg")
    return rv


def check_black(rv, max_black: float = MAX_BLACK) -> None:
    """Raise if more than `max_black` of the hood-cropped view is outside the sensor."""
    if not rv.black_sent < max_black:
        raise ValueError(
            f"road view black fraction {rv.black_sent:.4f} >= {max_black} (outside the sensor)"
        )


def cost_line(usage, model: str) -> str:
    """Token usage and estimated cost of the Gemini call (svi_geo price table)."""
    from svi_geo import gemini_client

    tracker = gemini_client.CostTracker(prices=gemini_client.prices_for(model))
    tracker.add(usage)
    return (
        f"[gemini] calls={tracker.calls} input_tokens={tracker.input_tokens:,} "
        f"output_tokens={tracker.output_tokens:,} est. ${tracker.usd:.4f}"
    )


def road_view_spec(pose: dict, cam_k: int | None, intr):
    """World-oriented road view along the camera's calibrated heading (pose heading + the
    fitted per-camera yaw delta), pitched `ROAD_PITCH_DEG` below the horizon."""
    from svi_geo import rosette

    delta = intr.cam_rot_delta_deg.get(int(cam_k), (0.0,))[0] if cam_k is not None else 0.0
    yaw = (float(pose["heading"]) + delta) % 360.0
    return rosette.PerspectiveView(yaw, ROAD_PITCH_DEG, ROAD_HFOV_DEG, *ROAD_VIEW_SIZE)


def road_view(image: np.ndarray, pose: dict | None = None, cam_k: int | None = None) -> np.ndarray:
    """Deterministic road-facing view.

    With svi_geo installed and the frame's `camera_pose`: a 60 deg wide view rectified with the
    fitted fisheye model along the camera's calibrated heading, pitched 22 deg below the
    horizon in world coordinates (the pose's pitch and roll are applied), with the rows that
    show the vehicle hood cropped. Without a pose (`--image`), the image is treated as a level
    camera looking along its optical axis. Without svi_geo, a fixed crop of the lower frame."""
    try:
        from svi_geo import rosette
    except ImportError:
        h, w = image.shape[:2]
        return _fit_within(image[int(0.55 * h) : int(0.82 * h), int(0.1 * w) : int(0.9 * w)])
    intr = rosette.load_intrinsics()
    if pose is None:
        pose, cam_k = {"heading": 0.0, "pitch": 0.0, "roll": 0.0}, None
        intr = dataclasses.replace(intr, pose_convention=(1, 1), cam_rot_delta_deg={})
    view = road_view_spec(pose, cam_k, intr)
    out = rosette.render_perspective(image, intr, pose, view, cam_k)
    keep = rosette.hood_row(view, pose, intr, rosette.HOOD_ELEV_DEG, cam_k)
    return _fit_within(out[:keep])


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


def parse_args(argv=None, env=None):
    """CLI arguments. `env` (default: the process environment) supplies PROJECT_ID /
    GOOGLE_CLOUD_PROJECT / GCS_BUCKET / BIGQUERY_DATASET defaults; nothing else is guessed."""
    env = dict(os.environ) if env is None else env
    p = argparse.ArgumentParser(description="Surface material detection (panoramic SVI).")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--image", help="Path to a local image file (already downloaded).")
    g.add_argument("--observation-id", "--pano-id", dest="observation_id")
    g.add_argument("--coordinates", help="'lat,lng' - nearest pano within --radius-m")
    p.add_argument("--radius-m", type=float, default=30.0)
    p.add_argument(
        "--travel-deg",
        type=float,
        help="Travel direction (deg from north) if it cannot be measured from neighbouring panos.",
    )
    p.add_argument("--output", help="Optional path to save the JSON result.")
    p.add_argument(
        "--project",
        default=env.get("PROJECT_ID") or env.get("GOOGLE_CLOUD_PROJECT"),
        help="Billing project (default: $PROJECT_ID, then $GOOGLE_CLOUD_PROJECT).",
    )
    p.add_argument("--dataset", default=env.get("BIGQUERY_DATASET", DEFAULT_DATASET))
    p.add_argument(
        "--gcs-bucket",
        default=env.get("GCS_BUCKET"),
        help="Frame bucket linked to your dataset (default: $GCS_BUCKET). Required unless --image.",
    )
    p.add_argument("--location", default="global")
    p.add_argument("--model", default="gemini-3.5-flash")
    args = p.parse_args(argv)
    if not args.project:
        p.error("set --project or the PROJECT_ID environment variable")
    args.gcs_bucket = (args.gcs_bucket or "").removeprefix("gs://").strip("/") or None
    if not args.image and not args.gcs_bucket:
        p.error("set --gcs-bucket or the GCS_BUCKET environment variable")
    return args


def frame_rows(rows: list[dict], pano_id: str) -> list[dict]:
    """The frames of `pano_id` with their camera index and full `camera_pose` (missing pitch or
    roll are treated as level)."""
    out = []
    for r in rows:
        k = _camera_index(r["observation_id"])
        if r["pano_id"] != pano_id or k is None:
            continue
        pose = {
            "heading": float(r["heading"]),
            "pitch": float(r["pitch"] or 0.0),
            "roll": float(r["roll"] or 0.0),
            "latitude": float(r["lat"]),
            "longitude": float(r["lng"]),
        }
        out.append({**r, "cam_k": k, "camera_pose": pose})
    return sorted(out, key=lambda f: f["cam_k"])


def _download(gcs, bucket: str, frame: dict) -> np.ndarray:
    uri = gcs_uri_for(bucket, frame["snapshot_id"], frame["observation_id"])
    data = gcs.bucket(bucket).blob(uri.removeprefix("gs://").split("/", 1)[1]).download_as_bytes()
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"cannot decode {uri}")
    return img


def fetch_view(args) -> tuple[np.ndarray, dict]:
    """Look up the pano, download the frame(s) with the caller's credentials and return the
    road view to send plus its metadata."""
    from google.cloud import bigquery, storage

    creds, _ = _optional_svi_geo_auth()
    project = args.project
    bq = bigquery.Client(project=project, credentials=creds)
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
        if not rows:
            raise ValueError(f"no pano observation found for {args.observation_id}")
        # An observation or pano id names its row; a capture id is resolved by the location
        # of the matched row (hit_lat/hit_lng), i.e. the pano at distance 0.
        near = min(
            rows,
            key=lambda r: (
                args.observation_id not in (r["observation_id"], r["pano_id"]),
                _dist_m(r["hit_lat"], r["hit_lng"], r["lat"], r["lng"]),
            ),
        )
    pano = near["pano_id"]
    frames = frame_rows(rows, pano)
    travel = resolve_travel(travel_direction(rows, pano), args.travel_deg)
    gcs = storage.Client(project=project, credentials=creds)
    meta = {
        "pano_id": pano,
        "travel_deg": round(travel, 1),
        "capture_time": str(near["capture_time"]),
        "project": project,
    }
    try:
        from svi_geo import images, rosette, sequence
    except ImportError:
        cam = pick_front_camera(frames, travel)
        img = _download(gcs, args.gcs_bucket, cam)
        meta.update(observation_id=cam["observation_id"], cam_k=cam["cam_k"])
        return road_view(img), meta
    rv = plan_road_view(frames, travel)
    check_black(rv)
    imgs = {int(r["cam_k"]): _download(gcs, args.gcs_bucket, r) for r in rv.rows}
    view = sequence.render_road_view(imgs, rosette.load_intrinsics(), rv)
    print(
        f"[view] yaw={rv.view.yaw_deg:.1f} hfov={rv.view.hfov_deg:.1f} cameras="
        f"{sorted(imgs)} black_fraction_sent={rv.black_sent:.4f} "
        f"dark_pixel_fraction={images.dark_pixel_fraction(view):.4f}",
        file=sys.stderr,
    )
    meta.update(
        observation_ids=[r["observation_id"] for r in rv.rows],
        cam_k=sorted(imgs),
        black_fraction_sent=round(float(rv.black_sent), 4),
    )
    return _fit_within(view), meta


def main():
    args = parse_args()
    try:
        if args.image:
            img = cv2.imread(args.image, cv2.IMREAD_COLOR)
            if img is None:
                raise ValueError(f"cannot read {args.image}")
            meta = {"image": args.image, "project": args.project}
            view = road_view(img)
        else:
            view, meta = fetch_view(args)
    except Exception as e:  # noqa: BLE001 - CLI boundary
        print(f"Error loading image: {e}", file=sys.stderr)
        sys.exit(1)

    from google import genai
    from google.genai import types

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
    try:
        print(cost_line(resp.usage_metadata, args.model), file=sys.stderr)
    except ImportError:  # no svi_geo price table: report the raw token counts only
        print(f"[gemini] calls=1 usage={resp.usage_metadata}", file=sys.stderr)
    out = {
        **result.model_dump(mode="json"),
        "source": {k: v for k, v in meta.items() if k not in ("project", "camera_pose")},
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
