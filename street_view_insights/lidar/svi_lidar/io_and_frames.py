# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""In-memory .laz streaming, Full-Frame & Pano BigQuery helpers, and ECEF/ENU/Camera frame math."""

from __future__ import annotations

import io
import math
import re
from typing import Any, Mapping, Sequence

import numpy as np

WGS84_A = 6378137.0
WGS84_E2 = 0.00669437999014
# GPS epoch (1980-01-06 00:00:00 UTC) minus Unix epoch (1970-01-01) with 18 leap seconds.
GPS_TO_UNIX_OFFSET_SEC = 315964782

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_\-]+$")
_PANO_OBS_RE = re.compile(r"^o1:(?P<stem>.+)_(?P<k>\d):5001ee$")


def _validate_identifier(value: str, label: str) -> str:
    if not value or value == "YOUR_PROJECT_ID" or not _IDENTIFIER_RE.match(value):
        raise ValueError(
            f"Invalid {label}={value!r}. Set GOOGLE_CLOUD_PROJECT or pass a valid --project ID."
        )
    return value


def parse_pano_observation_id(observation_id: str | None) -> tuple[str | None, int | None]:
    """Parse `('pano_stem', camera_index_k)` from an SV_PANO observation ID `o1:<stem>_<0..6>:5001ee`."""
    if not observation_id:
        return None, None
    m = _PANO_OBS_RE.match(observation_id.strip())
    if not m:
        return None, None
    return m.group("stem"), int(m.group("k"))


def infer_lidar_mode(
    mode: str = "auto",
    observation_id: str | None = None,
    capture_id: str | None = None,
    pano_id: str | None = None,
    asset_id: str | None = None,
) -> str:
    """Resolve `'full_frame'` vs. `'pano'` mode from explicit flag or ID format."""
    norm = (mode or "auto").strip().lower()
    if norm in ("full_frame", "pano"):
        return norm
    if norm != "auto":
        raise ValueError(f"Unsupported mode={mode!r}; expected 'auto', 'full_frame', or 'pano'.")
    if capture_id or pano_id:
        return "pano"
    if asset_id:
        return "full_frame"
    if observation_id and observation_id.strip().endswith(":5001ee"):
        return "pano"
    return "full_frame"


def lla_to_ecef(
    lat_deg: float | np.ndarray,
    lon_deg: float | np.ndarray,
    alt_m: float | np.ndarray,
) -> np.ndarray:
    """Convert WGS84 GPS coordinates (EPSG:4326) to geocentric ECEF meters (EPSG:4978)."""
    lat_r = np.radians(np.asarray(lat_deg, dtype=np.float64))
    lon_r = np.radians(np.asarray(lon_deg, dtype=np.float64))
    alt = np.asarray(alt_m, dtype=np.float64)

    sin_lat = np.sin(lat_r)
    cos_lat = np.cos(lat_r)
    n_val = WGS84_A / np.sqrt(1.0 - WGS84_E2 * (sin_lat * sin_lat))

    x_ecef = (n_val + alt) * cos_lat * np.cos(lon_r)
    y_ecef = (n_val + alt) * cos_lat * np.sin(lon_r)
    z_ecef = (n_val * (1.0 - WGS84_E2) + alt) * sin_lat

    if np.ndim(x_ecef) == 0:
        return np.array([float(x_ecef), float(y_ecef), float(z_ecef)], dtype=np.float64)
    return np.column_stack([x_ecef, y_ecef, z_ecef]).astype(np.float64, copy=False)


def _ecef_to_enu_matrix(origin_lat_deg: float, origin_lon_deg: float) -> np.ndarray:
    lat_r = math.radians(float(origin_lat_deg))
    lon_r = math.radians(float(origin_lon_deg))
    sin_lat, cos_lat = math.sin(lat_r), math.cos(lat_r)
    sin_lon, cos_lon = math.sin(lon_r), math.cos(lon_r)
    return np.array(
        [
            [-sin_lon, cos_lon, 0.0],
            [-sin_lat * cos_lon, -sin_lat * sin_lon, cos_lat],
            [cos_lat * cos_lon, cos_lat * sin_lon, sin_lat],
        ],
        dtype=np.float64,
    )


def ecef_to_enu(
    pts_ecef: np.ndarray,
    origin_lat_deg: float,
    origin_lon_deg: float,
    origin_alt_m: float,
    dtype: np.dtype = np.float32,
) -> np.ndarray:
    """Convert global ECEF meters (EPSG:4978) to local East-North-Up (ENU) meters.

    Subtracts `origin_ecef` in `float64` first so 1 mm LAS precision is preserved
    before casting to `dtype` (`float32` by default).
    """
    pts = np.asarray(pts_ecef, dtype=np.float64)
    if pts.size == 0:
        return np.empty((0, 3), dtype=dtype)
    origin_ecef = lla_to_ecef(origin_lat_deg, origin_lon_deg, origin_alt_m)
    r_enu = _ecef_to_enu_matrix(origin_lat_deg, origin_lon_deg)
    pts_enu = (pts[:, :3] - origin_ecef) @ r_enu.T
    return pts_enu.astype(dtype, copy=False)


def enu_to_ecef(
    pts_enu: np.ndarray,
    origin_lat_deg: float,
    origin_lon_deg: float,
    origin_alt_m: float,
) -> np.ndarray:
    """Convert local tangent ENU meters back to global ECEF meters (EPSG:4978)."""
    pts = np.asarray(pts_enu, dtype=np.float64)
    if pts.size == 0:
        return np.empty((0, 3), dtype=np.float64)
    origin_ecef = lla_to_ecef(origin_lat_deg, origin_lon_deg, origin_alt_m)
    r_enu = _ecef_to_enu_matrix(origin_lat_deg, origin_lon_deg)
    return origin_ecef + (pts[:, :3] @ r_enu)


def enu_to_camera(
    pts_enu: np.ndarray,
    heading_deg: float,
    pitch_deg: float,
    roll_deg: float,
    pitch_offset_deg: float = 0.0,
) -> np.ndarray:
    """Rotate camera-centered ENU meters into the camera frame `[X_right, Y_forward, Z_up]`.

    Sign conventions match `camera_pose` in both `full_frame_observations_latest` and
    `pano_observations_latest`:
      - `heading_deg`: clockwise from North (`0` = North, `90` = East).
      - `pitch_deg`: positive when the camera looks upward above the horizon.
      - `roll_deg`: bank angle around the forward optical axis.
    """
    pts = np.asarray(pts_enu, dtype=np.float64)
    if pts.size == 0:
        return np.empty((0, 3), dtype=np.float64)

    psi = math.radians(float(heading_deg))
    theta = math.radians(float(pitch_deg) + float(pitch_offset_deg))
    phi = math.radians(float(roll_deg))

    ch, sh = math.cos(psi), math.sin(psi)
    rz = np.array([[ch, -sh, 0.0], [sh, ch, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)

    cp, sp = math.cos(-theta), math.sin(-theta)
    rx = np.array([[1.0, 0.0, 0.0], [0.0, cp, -sp], [0.0, sp, cp]], dtype=np.float64)

    cr, sr = math.cos(-phi), math.sin(-phi)
    ry = np.array([[cr, 0.0, sr], [0.0, 1.0, 0.0], [-sr, 0.0, cr]], dtype=np.float64)

    rot = ry @ rx @ rz
    return pts[:, :3] @ rot.T


def deduplicate_enu_voxels(
    pts_enu: np.ndarray,
    intensity: np.ndarray | None = None,
    gps_time: np.ndarray | None = None,
    voxel_size_m: float = 0.02,
) -> dict[str, np.ndarray]:
    """Deduplicate overlapping multi-sensor / multi-stop sweeps on a 3D ENU voxel grid."""
    pts = np.asarray(pts_enu, dtype=np.float32)
    n_pts = len(pts)
    if n_pts == 0 or voxel_size_m <= 0.0:
        out: dict[str, np.ndarray] = {"enu": pts, "keep_indices": np.arange(n_pts, dtype=np.int64)}
        if intensity is not None:
            out["intensity"] = np.asarray(intensity, dtype=np.uint16)
        if gps_time is not None:
            out["gps_time"] = np.asarray(gps_time, dtype=np.float64)
        return out

    if intensity is not None:
        inten = np.asarray(intensity, dtype=np.uint16)
        order = np.argsort(-inten.astype(np.int32), kind="mergesort")
    else:
        inten = None
        order = np.arange(n_pts, dtype=np.int64)

    pts_sorted = pts[order]
    mins = pts_sorted.min(axis=0)
    ijk = np.floor((pts_sorted - mins) / float(voxel_size_m)).astype(np.int64)
    ijk_contig = np.ascontiguousarray(ijk)
    void_view = ijk_contig.view(np.dtype((np.void, ijk_contig.dtype.itemsize * 3))).ravel()
    _, first_pos = np.unique(void_view, return_index=True)
    keep_idx = np.sort(order[first_pos])

    result: dict[str, np.ndarray] = {
        "enu": pts[keep_idx],
        "keep_indices": keep_idx,
    }
    if inten is not None:
        result["intensity"] = inten[keep_idx]
    if gps_time is not None:
        result["gps_time"] = np.asarray(gps_time, dtype=np.float64)[keep_idx]
    return result


def build_observation_lidar_sql(
    project_id: str,
    dataset: str = "imagery_insights_lidar___us",
) -> str:
    """Build parameterized SQL joining Full-Frame observations to deduplicated .laz scans."""
    proj = _validate_identifier(project_id, "project_id")
    dset = _validate_identifier(dataset, "dataset")
    return f"""
WITH dedup_laz AS (
  SELECT
    observation_id,
    device_number,
    uri AS laz_gcs_uri,
    count_points,
    start_time.seconds AS laz_start_gps_sec,
    centroid_lat,
    centroid_lon,
    ROW_NUMBER() OVER (
      PARTITION BY observation_id, device_number
      ORDER BY count_points DESC, uri ASC
    ) AS rn
  FROM `{proj}.{dset}.full_frame_lidar_metadata_latest`
  WHERE observation_id = @observation_id
    AND (centroid_lat IS NULL OR NOT IS_NAN(centroid_lat))
)
SELECT
  o.observation_id,
  o.asset_id,
  o.asset_type,
  o.capture_time,
  UNIX_SECONDS(o.capture_time) - {GPS_TO_UNIX_OFFSET_SEC} AS capture_gps_sec,
  o.gcs_uri AS image_gcs_uri,
  o.camera_pose,
  o.bbox,
  l.device_number,
  l.laz_gcs_uri,
  l.count_points,
  l.laz_start_gps_sec
FROM `{proj}.{dset}.full_frame_observations_latest` AS o
JOIN dedup_laz AS l
  ON o.observation_id = l.observation_id AND l.rn = 1
WHERE o.observation_id = @observation_id
ORDER BY o.asset_id, l.device_number
""".strip()


def build_pano_rosette_lidar_sql(
    project_id: str,
    dataset: str = "imagery_insights_lidar___us",
    lookup_by: str = "observation_id",
) -> str:
    """Build parameterized SQL resolving a 6-lens SV_PANO horizontal rosette + its .laz scans.

    In `pano_lidar_metadata_latest`, each sensor sweep caps at 1,000,000 returns across a 15 s
    window, so rear/side lenses (`_2`, `_3`) often hold the full 0.6–0.9M-point sweep while
    forward lenses receive tiny stub files. Resolving the whole `capture_id` rosette ensures
    rich 360-degree `.laz` coverage and 6-camera True Color RGB draping even when queried by a
    single lens `observation_id`.
    """
    proj = _validate_identifier(project_id, "project_id")
    dset = _validate_identifier(dataset, "dataset")
    if lookup_by == "observation_id":
        target_pred = (
            f"capture_id = (SELECT ANY_VALUE(capture_id) "
            f"FROM `{proj}.{dset}.pano_observations_latest` WHERE observation_id = @target_id)"
        )
    elif lookup_by == "capture_id":
        target_pred = "capture_id = @target_id"
    elif lookup_by == "pano_id":
        target_pred = "pano_id = @target_id"
    else:
        raise ValueError(f"Unsupported lookup_by={lookup_by!r}.")

    return f"""
WITH rosette_obs AS (
  SELECT
    observation_id,
    capture_id,
    pano_id,
    capture_time,
    UNIX_SECONDS(capture_time) - {GPS_TO_UNIX_OFFSET_SEC} AS capture_gps_sec,
    gcs_uri AS image_gcs_uri,
    camera_pose,
    CAST(REGEXP_EXTRACT(observation_id, r'_(\\d)(?::|$)') AS INT64) AS lens_k
  FROM `{proj}.{dset}.pano_observations_latest`
  WHERE {target_pred}
),
dedup_laz AS (
  SELECT
    l.observation_id,
    l.device_number,
    l.uri AS laz_gcs_uri,
    l.count_points,
    l.start_time.seconds AS laz_start_gps_sec,
    ROW_NUMBER() OVER (
      PARTITION BY l.observation_id, l.device_number
      ORDER BY l.count_points DESC, l.uri ASC
    ) AS rn
  FROM `{proj}.{dset}.pano_lidar_metadata_latest` AS l
  JOIN (SELECT DISTINCT observation_id FROM rosette_obs) AS r
    ON l.observation_id = r.observation_id
  WHERE (l.centroid_lat IS NULL OR NOT IS_NAN(l.centroid_lat))
)
SELECT
  r.observation_id,
  r.capture_id,
  r.pano_id,
  r.lens_k,
  r.capture_time,
  r.capture_gps_sec,
  r.image_gcs_uri,
  r.camera_pose,
  l.device_number,
  l.laz_gcs_uri,
  l.count_points,
  l.laz_start_gps_sec
FROM rosette_obs AS r
LEFT JOIN dedup_laz AS l
  ON r.observation_id = l.observation_id AND l.rn = 1
ORDER BY r.lens_k, l.device_number
""".strip()


def select_same_pass_laz_rows(
    direct_rows: Sequence[Mapping[str, Any]],
    neighbor_rows: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Select and deduplicate .laz scans using the 2-sensor vs. 4-sensor rig rule."""
    by_dev: dict[int, Mapping[str, Any]] = {}
    for row in direct_rows:
        if row.get("device_number") is None or not row.get("laz_gcs_uri"):
            continue
        dev = int(row["device_number"])
        prev = by_dev.get(dev)
        if prev is None or int(row.get("count_points") or 0) > int(prev.get("count_points") or 0):
            by_dev[dev] = row

    device_count = len(by_dev)
    rig_type = "4-sensor" if device_count >= 4 else "2-sensor"
    neighbor_window_sec = 2.5 if device_count >= 4 else 6.0

    selected_uris: list[str] = []
    seen_uris: set[str] = set()
    ref_gps_times: list[float] = []

    for dev in sorted(by_dev):
        row = by_dev[dev]
        uri = str(row["laz_gcs_uri"])
        if uri and uri not in seen_uris:
            seen_uris.add(uri)
            selected_uris.append(uri)
        if row.get("laz_start_gps_sec") is not None:
            ref_gps_times.append(float(row["laz_start_gps_sec"]))
        elif row.get("capture_gps_sec") is not None:
            ref_gps_times.append(float(row["capture_gps_sec"]))

    if neighbor_rows and ref_gps_times:
        t_ref = float(np.median(ref_gps_times))
        for nrow in neighbor_rows:
            t_cand = nrow.get("laz_start_gps_sec")
            uri = str(nrow.get("laz_gcs_uri") or "")
            if t_cand is None or not uri or uri in seen_uris:
                continue
            if abs(float(t_cand) - t_ref) <= neighbor_window_sec:
                seen_uris.add(uri)
                selected_uris.append(uri)

    return {
        "rig_type": rig_type,
        "device_count": device_count,
        "recommended_neighbor_window_sec": neighbor_window_sec,
        "laz_uris": selected_uris,
    }


def select_pano_rosette_laz_and_cameras(
    rosette_rows: Sequence[Mapping[str, Any]],
    requested_observation_id: str | None = None,
) -> dict[str, Any]:
    """Filter sky camera `k=6`, deduplicate rich `.laz` sweeps (`>= 500` pts), and order 6 rosette views."""
    cams_by_obs: dict[str, dict[str, Any]] = {}
    rich_uris: list[str] = []
    stub_uris: list[str] = []
    seen_uris: set[str] = set()
    dev_ids: set[int] = set()

    # Order rows so lenses with largest point counts register their `.laz` sweeps first.
    sorted_rows = sorted(
        rosette_rows,
        key=lambda r: (-int(r.get("count_points") or 0), int(r.get("lens_k") if r.get("lens_k") is not None else 0)),
    )
    for row in sorted_rows:
        oid = str(row.get("observation_id") or "")
        if not oid:
            continue
        _, parsed_k = parse_pano_observation_id(oid)
        lens_k = int(row["lens_k"]) if row.get("lens_k") is not None else (parsed_k if parsed_k is not None else 0)
        pose = dict(row.get("camera_pose") or {})
        pitch_deg = float(pose.get("pitch") or pose.get("pitchDeg") or 0.0)

        # Skip sky/zenith camera (`k == 6` or `|pitch| > 45 deg`).
        if lens_k >= 6 or abs(pitch_deg) > 45.0:
            continue

        if oid not in cams_by_obs:
            cams_by_obs[oid] = {
                "lens_k": lens_k,
                "observation_id": oid,
                "capture_id": row.get("capture_id"),
                "pano_id": row.get("pano_id"),
                "capture_time": row.get("capture_time"),
                "image_gcs_uri": row.get("image_gcs_uri"),
                "camera_pose": pose,
            }

        uri = str(row.get("laz_gcs_uri") or "")
        if uri and uri not in seen_uris:
            seen_uris.add(uri)
            if row.get("device_number") is not None:
                dev_ids.add(int(row["device_number"]))
            cnt = int(row.get("count_points") or 0)
            if cnt >= 500:
                rich_uris.append(uri)
            else:
                stub_uris.append(uri)

    rosette_cameras = sorted(cams_by_obs.values(), key=lambda c: (int(c["lens_k"]), str(c["observation_id"])))
    if not rosette_cameras:
        raise LookupError("No horizontal rosette cameras (`k=0..5`) found for pano capture.")

    primary_cam = next(
        (c for c in rosette_cameras if c["observation_id"] == requested_observation_id),
        rosette_cameras[0],
    )
    laz_uris = rich_uris if rich_uris else stub_uris
    device_count = len(dev_ids)
    return {
        "mode": "pano",
        "observation_id": primary_cam["observation_id"],
        "capture_id": primary_cam.get("capture_id"),
        "pano_id": primary_cam.get("pano_id"),
        "capture_time": primary_cam.get("capture_time"),
        "image_gcs_uri": primary_cam.get("image_gcs_uri"),
        "camera_pose": primary_cam["camera_pose"],
        "rosette_cameras": rosette_cameras,
        "catalog_assets": [],
        "rig_type": "4-sensor" if device_count >= 4 else "2-sensor",
        "device_count": device_count,
        "recommended_neighbor_window_sec": 2.5 if device_count >= 4 else 6.0,
        "laz_uris": laz_uris,
    }


def fetch_observation_and_laz_metadata(
    observation_id: str | None = None,
    project_id: str = "YOUR_PROJECT_ID",
    dataset: str = "imagery_insights_lidar___us",
    mode: str = "auto",
    capture_id: str | None = None,
    pano_id: str | None = None,
    max_bytes_billed: int = 10_000_000_000,
    dry_run_first: bool = True,
    bq_client: Any = None,
) -> dict[str, Any]:
    """Query BigQuery for either a Full-Frame observation or a 6-lens Pano rosette + .laz metadata."""
    from google.cloud import bigquery

    resolved_mode = infer_lidar_mode(
        mode=mode,
        observation_id=observation_id,
        capture_id=capture_id,
        pano_id=pano_id,
    )
    client = bq_client or bigquery.Client(project=project_id)

    if resolved_mode == "pano":
        if capture_id:
            lookup_by, target_val = "capture_id", capture_id
        elif pano_id:
            lookup_by, target_val = "pano_id", pano_id
        elif observation_id:
            lookup_by, target_val = "observation_id", observation_id
        else:
            raise ValueError("Pano mode requires --observation-id, --capture-id, or --pano-id.")
        sql = build_pano_rosette_lidar_sql(project_id=project_id, dataset=dataset, lookup_by=lookup_by)
        params = [bigquery.ScalarQueryParameter("target_id", "STRING", target_val)]
    else:
        if not observation_id:
            raise ValueError("Full-Frame mode requires --observation-id.")
        sql = build_observation_lidar_sql(project_id=project_id, dataset=dataset)
        params = [bigquery.ScalarQueryParameter("observation_id", "STRING", observation_id)]

    estimated_bytes = 0
    if dry_run_first:
        dry_cfg = bigquery.QueryJobConfig(query_parameters=params, dry_run=True, use_query_cache=True)
        dry_job = client.query(sql, job_config=dry_cfg)
        estimated_bytes = int(dry_job.total_bytes_processed or 0)
        if estimated_bytes > max_bytes_billed:
            raise RuntimeError(
                f"Dry-run estimated {estimated_bytes:,} bytes, exceeding cap {max_bytes_billed:,}."
            )

    run_cfg = bigquery.QueryJobConfig(
        query_parameters=params,
        maximum_bytes_billed=max_bytes_billed,
        use_query_cache=True,
    )
    rows = [dict(r.items()) for r in client.query(sql, job_config=run_cfg).result()]
    if not rows:
        raise LookupError(f"No LiDAR rows found in mode={resolved_mode!r}.")

    if resolved_mode == "pano":
        parsed = select_pano_rosette_laz_and_cameras(rows, requested_observation_id=observation_id)
        parsed["dry_run_bytes"] = estimated_bytes
        return parsed

    selection = select_same_pass_laz_rows(rows)
    first = rows[0]
    pose_raw = dict(first["camera_pose"])
    bboxes = [
        {"asset_id": r["asset_id"], "asset_type": r["asset_type"], "bbox": dict(r["bbox"])}
        for r in {r["asset_id"]: r for r in rows if r.get("bbox")}.values()
    ]
    return {
        "mode": "full_frame",
        "observation_id": first["observation_id"],
        "capture_time": first["capture_time"],
        "image_gcs_uri": first["image_gcs_uri"],
        "camera_pose": pose_raw,
        "rosette_cameras": [
            {
                "lens_k": 0,
                "observation_id": first["observation_id"],
                "capture_time": first["capture_time"],
                "image_gcs_uri": first["image_gcs_uri"],
                "camera_pose": pose_raw,
            }
        ],
        "catalog_assets": bboxes,
        "dry_run_bytes": estimated_bytes,
        **selection,
    }


def stream_laz_from_gcs(
    laz_gcs_uri: str,
    storage_client: Any = None,
) -> dict[str, np.ndarray]:
    """Stream a LAS 1.4 .laz file in memory from Cloud Storage without local disk writes."""
    if not laz_gcs_uri.startswith("gs://"):
        raise ValueError(f"Expected gs:// URI, got {laz_gcs_uri!r}.")
    import laspy
    from google.cloud import storage

    bucket_name, blob_path = laz_gcs_uri[5:].split("/", 1)
    client = storage_client or storage.Client()
    laz_bytes = client.bucket(bucket_name).blob(blob_path).download_as_bytes()
    las = laspy.read(io.BytesIO(laz_bytes))

    pts_ecef = np.column_stack(
        [
            np.asarray(las.x, dtype=np.float64),
            np.asarray(las.y, dtype=np.float64),
            np.asarray(las.z, dtype=np.float64),
        ]
    )
    intensity = np.asarray(las.intensity, dtype=np.uint16)
    gps_time = (
        np.asarray(las.gps_time, dtype=np.float64)
        if hasattr(las, "gps_time")
        else np.zeros(len(pts_ecef), dtype=np.float64)
    )
    return {
        "ecef": pts_ecef,
        "intensity": intensity,
        "gps_time": gps_time,
    }


def stream_and_merge_laz_enu(
    laz_uris: Sequence[str],
    origin_lat_deg: float,
    origin_lon_deg: float,
    origin_alt_m: float,
    voxel_size_m: float = 0.02,
    storage_client: Any = None,
) -> dict[str, np.ndarray]:
    """Stream multiple .laz files in memory, convert to local ENU, and voxel-deduplicate."""
    enu_parts: list[np.ndarray] = []
    int_parts: list[np.ndarray] = []
    time_parts: list[np.ndarray] = []

    for uri in laz_uris:
        chunk = stream_laz_from_gcs(uri, storage_client=storage_client)
        if len(chunk["ecef"]) == 0:
            continue
        enu_parts.append(
            ecef_to_enu(
                chunk["ecef"],
                origin_lat_deg=origin_lat_deg,
                origin_lon_deg=origin_lon_deg,
                origin_alt_m=origin_alt_m,
                dtype=np.float32,
            )
        )
        int_parts.append(chunk["intensity"])
        time_parts.append(chunk["gps_time"])

    if not enu_parts:
        return {
            "enu": np.empty((0, 3), dtype=np.float32),
            "intensity": np.empty(0, dtype=np.uint16),
            "gps_time": np.empty(0, dtype=np.float64),
            "keep_indices": np.empty(0, dtype=np.int64),
        }

    all_enu = np.vstack(enu_parts)
    all_int = np.concatenate(int_parts)
    all_time = np.concatenate(time_parts)
    return deduplicate_enu_voxels(
        all_enu,
        intensity=all_int,
        gps_time=all_time,
        voxel_size_m=voxel_size_m,
    )
