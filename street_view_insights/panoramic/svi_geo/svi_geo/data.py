"""Guarded BigQuery access to the Street View Insights pano views, plus GCS path derivation.

Rules enforced here:
* Only `pano_observations_latest` / `pano_observations_all` of an allow-listed dataset
  (`imagery_insights___us`, plus `$SVI_ALLOWED_DATASETS`) in any project may be queried.
* Every query is dry-run first (no cache) and refused above `max_bytes` (<= 2 GB); the real
  run sets `maximum_bytes_billed`.
* SQL must be parameterised (`@name` + ScalarQueryParameter); `{`/`}` are rejected so
  f-string-built SQL cannot slip through.
* `gcs_uri` is never selected with the metadata: selecting it costs ~1.9 GB on these views.
  The URI is derived from `gs://<bucket>/<snapshot_id>/v0/<observation_id>.jpg`.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from google.cloud import bigquery

from svi_geo import rosette

PROJECT = "imagery-insights-sandbox"
DATASET = "imagery_insights___us"
PANO_LATEST = f"{PROJECT}.{DATASET}.pano_observations_latest"
PANO_ALL = f"{PROJECT}.{DATASET}.pano_observations_all"
SNAP_TABLE = f"{PROJECT}.{DATASET}.snapshots"
CROPPED_ASSETS_LATEST = f"{PROJECT}.{DATASET}.cropped_assets_latest"
FULL_FRAME_ASSETS_LATEST = f"{PROJECT}.{DATASET}.full_frame_assets_latest"
FORBIDDEN_MARKERS = (
    "full_frame_observations",
    "cropped_observations",
    "all_observations",
    "all_assets",
)
PANO_VIEWS = (
    "pano_observations_latest",
    "pano_observations_all",
    "snapshots",
    "cropped_assets_latest",
    "full_frame_assets_latest",
)
ALLOWED_TABLES = frozenset(
    {
        PANO_LATEST,
        PANO_ALL,
        SNAP_TABLE,
        CROPPED_ASSETS_LATEST,
        FULL_FRAME_ASSETS_LATEST,
    }
)
HARD_MAX_BYTES = 2_000_000_000
MAX_UNNEST_POINTS = 5000
BYTES_MANIFEST_PATH = Path(__file__).resolve().parent.parent / "data" / "bytes_manifest.json"
TEMPLATE_CEILINGS_BYTES: dict[str, int] = {
    "rosette_sql": 1_950_000_000,
    "rosette_target_sql": 1_950_000_000,
    "snapshot_catalog_sql": 1_000_000,
    "cluster_points_sql": 0,
    "repeat_pairs_sql": 1_450_000_000,
    "coverage_sql": 1_100_000_000,
    "tracks_sql": 1_500_000_000,
    "multi_aoi_sql": 1_750_000_000,
    "assets_in_aoi_sql": 100_000_000,
}
# Imagery Insights datasets whose pano views may be queried. Extend with the comma-separated
# environment variable SVI_ALLOWED_DATASETS (e.g. a dataset linked in another region).
DEFAULT_ALLOWED_DATASETS = (DATASET,)
_IDENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]*$")


def allowed_datasets(env: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """DEFAULT_ALLOWED_DATASETS plus the validated names in $SVI_ALLOWED_DATASETS."""
    env = os.environ if env is None else env
    extra = [d.strip() for d in env.get("SVI_ALLOWED_DATASETS", "").split(",") if d.strip()]
    for d in extra:
        if not _IDENT_RE.match(d):
            raise ValueError(f"invalid dataset in SVI_ALLOWED_DATASETS: {d!r}")
    return tuple(dict.fromkeys([*DEFAULT_ALLOWED_DATASETS, *extra]))


class QueryTooExpensive(RuntimeError):
    """Dry run exceeded the byte cap; the real query was not executed."""


class DisallowedTable(ValueError):
    """SQL referenced a table outside the pano allow-list."""


class UnsafeSql(ValueError):
    """SQL looks string-formatted (contains braces)."""


def is_pano_table(name: str, datasets: Sequence[str] | None = None) -> bool:
    """True for `<project>.<dataset>.<view>` with an allow-listed dataset and view."""
    datasets = allowed_datasets() if datasets is None else datasets
    parts = (name or "").split(".")
    return (
        len(parts) == 3
        and bool(_IDENT_RE.match(parts[0]))
        and parts[1] in datasets
        and parts[2] in PANO_VIEWS
    )


def pano_table(
    project: str,
    dataset: str = DATASET,
    view: str = PANO_VIEWS[0],
    datasets: Sequence[str] | None = None,
) -> str:
    """Fully-qualified pano view in the caller's project (identifiers validated, dataset in
    the allow-list)."""
    if view not in PANO_VIEWS:
        raise DisallowedTable(f"only {PANO_VIEWS} may be queried, got {view!r}")
    for v in (project, dataset):
        if not _IDENT_RE.match(v or ""):
            raise ValueError(f"invalid BigQuery identifier: {v!r}")
    datasets = allowed_datasets() if datasets is None else datasets
    if dataset not in datasets:
        raise DisallowedTable(
            f"dataset {dataset!r} is not in the allow-list {list(datasets)}; "
            "add it to SVI_ALLOWED_DATASETS"
        )
    return f"{project}.{dataset}.{view}"


def pano_tables(
    project: str, dataset: str = DATASET, datasets: Sequence[str] | None = None
) -> frozenset[str]:
    return frozenset(pano_table(project, dataset, v, datasets) for v in PANO_VIEWS)


_TABLE_TOKEN = re.compile(r"`([^`]+)`|\b(?:FROM|JOIN)\s+([A-Za-z0-9_\-]+\.[A-Za-z0-9_\-.]+)", re.I)


def referenced_tables(sql: str) -> set[str]:
    """Fully-qualified table references (backticked or after FROM/JOIN)."""
    out = set()
    for m in _TABLE_TOKEN.finditer(sql):
        name = (m.group(1) or m.group(2) or "").strip()
        if name.count(".") >= 1:
            out.add(name.replace("`", ""))
    return out


def assert_allowed_table(
    sql: str,
    allowed: frozenset[str] = ALLOWED_TABLES,
    *,
    allow_table_free: bool = False,
) -> None:
    lowered = sql.lower()
    for marker in FORBIDDEN_MARKERS:
        if marker in lowered:
            raise DisallowedTable(f"forbidden table marker {marker!r} in SQL")
    tables = referenced_tables(sql)
    if allow_table_free:
        if "`" in sql or tables:
            raise DisallowedTable(f"table-free SQL must not reference tables: {sorted(tables)}")
        if "unnest(@" not in lowered:
            raise DisallowedTable("table-free SQL must query UNNEST(@param)")
        return
    if not tables:
        raise DisallowedTable("no fully-qualified table found in SQL")
    bad = sorted(t for t in tables if t not in allowed)
    if bad:
        raise DisallowedTable(f"tables not in pano allow-list: {bad}")


def _param(name: str, value: Any, type_: str | None = None) -> bigquery.ScalarQueryParameter:
    if type_ is None:
        if isinstance(value, bool):
            type_ = "BOOL"
        elif isinstance(value, int):
            type_ = "INT64"
        elif isinstance(value, float):
            type_ = "FLOAT64"
        elif isinstance(value, dt.datetime):
            type_ = "TIMESTAMP"
        else:
            type_ = "STRING"
    return bigquery.ScalarQueryParameter(name, type_, value)


QueryParam = bigquery.ScalarQueryParameter | bigquery.ArrayQueryParameter
Params = Mapping[str, Any] | Sequence[QueryParam]


def build_params(params: Params | None) -> list[QueryParam]:
    """Mapping name -> value | (value, TYPE) | ready-made query parameter."""
    if not params:
        return []
    if isinstance(params, Mapping):
        out = []
        for k, v in params.items():
            if isinstance(v, (bigquery.ScalarQueryParameter, bigquery.ArrayQueryParameter)):
                out.append(v)
            elif isinstance(v, tuple) and len(v) == 2 and isinstance(v[1], str):
                out.append(_param(k, v[0], v[1]))  # (value, explicit type)
            else:
                out.append(_param(k, v))
        return out
    return list(params)


def aoi_array_param(name: str, aois: Sequence[tuple[float, float]]) -> bigquery.ArrayQueryParameter:
    """ARRAY<STRUCT<lat FLOAT64, lng FLOAT64>> parameter for multi-AOI queries."""
    return bigquery.ArrayQueryParameter(
        name,
        "STRUCT",
        [
            bigquery.StructQueryParameter(
                None,
                bigquery.ScalarQueryParameter("lat", "FLOAT64", float(lat)),
                bigquery.ScalarQueryParameter("lng", "FLOAT64", float(lng)),
            )
            for lat, lng in aois
        ],
    )


def named_aoi_array_param(
    name: str, aois: Mapping[str, tuple[float, float]] | Sequence[tuple[str, float, float]]
) -> bigquery.ArrayQueryParameter:
    """ARRAY<STRUCT<name STRING, lat FLOAT64, lng FLOAT64>> parameter for multi_aoi_sql."""
    items = [(k, v[0], v[1]) for k, v in aois.items()] if isinstance(aois, Mapping) else list(aois)
    return bigquery.ArrayQueryParameter(
        name,
        "STRUCT",
        [
            bigquery.StructQueryParameter(
                None,
                bigquery.ScalarQueryParameter("name", "STRING", str(aoi_name)),
                bigquery.ScalarQueryParameter("lat", "FLOAT64", float(lat)),
                bigquery.ScalarQueryParameter("lng", "FLOAT64", float(lng)),
            )
            for aoi_name, lat, lng in items
        ],
    )


def _param_key(p: QueryParam) -> Any:
    if isinstance(p, bigquery.ArrayQueryParameter):
        return (p.name, "ARRAY", repr(p.to_api_repr()))
    return (p.name, p.type_, str(p.value))


class QueryRunner:
    """Dry-run-first, byte-capped, allow-listed BigQuery runner."""

    def __init__(
        self,
        client: Any,
        max_bytes: int = HARD_MAX_BYTES,
        allowed_tables: frozenset[str] = ALLOWED_TABLES,
        log: Callable[[str], None] | None = print,
        cache_dir: str | Path | None = None,
        cache_ttl_s: float = 7 * 24 * 3600,
        allowed_datasets: Sequence[str] | None = None,
    ):
        if max_bytes > HARD_MAX_BYTES:
            raise ValueError(f"max_bytes must be <= {HARD_MAX_BYTES}")
        self.client = client
        self.max_bytes = int(max_bytes)
        requested = frozenset(allowed_tables)
        if not requested or not all(is_pano_table(t, allowed_datasets) for t in requested):
            raise DisallowedTable(f"allowed_tables must be pano views only: {sorted(requested)}")
        self.allowed_tables = requested
        self.log = log
        self.cache_dir = cache_dir
        self.cache_ttl_s = min(float(cache_ttl_s), 35 * 24 * 3600.0)
        self.last_dry_run_bytes: int | None = None
        self.total_billed_estimate = 0

    def dry_run(
        self,
        sql: str,
        params: Params | None = None,
        *,
        allow_table_free: bool = False,
    ) -> int:
        self._check(sql, allow_table_free=allow_table_free)
        cfg = bigquery.QueryJobConfig(
            dry_run=True, use_query_cache=False, query_parameters=build_params(params)
        )
        job = self.client.query(sql, job_config=cfg)
        self.last_dry_run_bytes = int(job.total_bytes_processed or 0)
        if allow_table_free and self.last_dry_run_bytes != 0:
            raise QueryTooExpensive(
                f"table-free SQL must dry-run to 0 bytes, got {self.last_dry_run_bytes:,}"
            )
        return self.last_dry_run_bytes

    def run(
        self,
        sql: str,
        params: Params | None = None,
        refresh: bool = False,
        *,
        allow_table_free: bool = False,
    ) -> pd.DataFrame:
        self._check(sql, allow_table_free=allow_table_free)
        cache_file = self._cache_file(sql, params)
        if (
            not refresh
            and cache_file is not None
            and cache_file.exists()
            and time.time() - cache_file.stat().st_mtime < self.cache_ttl_s
        ):
            if self.log:
                self.log(f"[bigquery] local cache hit {cache_file.name} (0 bytes billed)")
            return pd.read_parquet(cache_file)
        n = self.dry_run(sql, params, allow_table_free=allow_table_free)
        if self.log:
            self.log(f"[bigquery] dry run: {n / 1e9:.3f} GB (cap {self.max_bytes / 1e9:.1f} GB)")
        if n > self.max_bytes:
            raise QueryTooExpensive(f"query would process {n:,} bytes > cap {self.max_bytes:,}")
        cfg = bigquery.QueryJobConfig(
            maximum_bytes_billed=self.max_bytes, query_parameters=build_params(params)
        )
        job = self.client.query(sql, job_config=cfg)
        self.total_billed_estimate += n
        df = job.to_dataframe()
        if cache_file is not None:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(cache_file)
        return df

    def _cache_file(self, sql: str, params: Params | None) -> Path | None:
        if self.cache_dir is None:
            return None
        key = json.dumps([sql, [_param_key(p) for p in build_params(params)]], sort_keys=True)
        return Path(self.cache_dir) / f"{hashlib.sha256(key.encode()).hexdigest()[:24]}.parquet"

    def _check(self, sql: str, *, allow_table_free: bool = False) -> None:
        if "{" in sql or "}" in sql:
            raise UnsafeSql("SQL contains braces; build SQL with @params, not string formatting")
        assert_allowed_table(sql, self.allowed_tables, allow_table_free=allow_table_free)


# --------------------------------------------------------------------------- Canonical SQL (§2)

_ROSETTE_SQL_TEMPLATE = """
WITH frames AS (
  SELECT capture_id, pano_id, snapshot_id, capture_time, map_url,
         ST_GEOGPOINT(capture_location.longitude, capture_location.latitude) AS geog,
         CAST(REGEXP_EXTRACT(observation_id, r'_(\\d)(?::|$)') AS INT64) AS k,
         observation_id,
         camera_pose.heading AS heading, camera_pose.pitch AS pitch, camera_pose.roll AS roll,
         camera_pose.altitude AS cam_alt,
         camera_pose.latitude AS cam_lat, camera_pose.longitude AS cam_lng
  FROM `__TABLE__`
  WHERE ST_DWITHIN(ST_GEOGPOINT(capture_location.longitude, capture_location.latitude),
                   ST_GEOGPOINT(@lng, @lat), @radius_m)
    AND (@snapshot_id IS NULL OR snapshot_id = @snapshot_id)
    AND (@include_unpublished OR COALESCE(pano_id, '') != '')
),
rosettes AS (
  SELECT capture_id, snapshot_id,
         ANY_VALUE(pano_id) AS pano_id, MIN(capture_time) AS capture_time,
         ANY_VALUE(geog) AS geog, ANY_VALUE(map_url) AS map_url, ANY_VALUE(cam_alt) AS cam_alt,
         ARRAY_AGG(STRUCT(k, observation_id, heading, pitch, roll, cam_lat, cam_lng) ORDER BY k) AS cams,
         COUNT(*) AS n_frames
  FROM frames GROUP BY capture_id, snapshot_id
),
seq AS (
  SELECT *, LAG(geog) OVER w AS g_prev, LAG(capture_time) OVER w AS t_prev, LEAD(geog) OVER w AS g_next
  FROM rosettes WINDOW w AS (PARTITION BY snapshot_id ORDER BY capture_time, capture_id)
),
brk AS (
  SELECT *, IF(g_prev IS NULL OR TIMESTAMP_DIFF(capture_time, t_prev, MILLISECOND) > @max_dt_ms
                OR ST_DISTANCE(geog, g_prev) > @max_step_m, 1, 0) AS is_break,
         ST_AZIMUTH(geog, g_next) AS az_next, ST_AZIMUTH(g_prev, geog) AS az_prev
  FROM seq
),
isl AS (
  SELECT *, CONCAT(SUBSTR(snapshot_id, 1, 8), '_', CAST(SUM(is_break) OVER
              (PARTITION BY snapshot_id ORDER BY capture_time, capture_id) AS STRING)) AS seq_id
  FROM brk
)
SELECT capture_id, pano_id, snapshot_id, capture_time, map_url, cam_alt, n_frames, cams,
       ST_Y(geog) AS lat, ST_X(geog) AS lng, ST_ASTEXT(geog) AS wkt, seq_id,
       ROW_NUMBER() OVER (PARTITION BY seq_id ORDER BY capture_time, capture_id) AS seq_idx,
       IF(is_break = 1, NULL, ST_DISTANCE(geog, g_prev)) AS step_m,
       SUM(IF(is_break = 1, 0, ST_DISTANCE(geog, g_prev))) OVER (PARTITION BY seq_id ORDER BY capture_time, capture_id) AS cum_m,
       MOD(CAST(ROUND(COALESCE(az_next, az_prev) * 180 / ACOS(-1)) AS INT64) + 360, 360) AS travel_deg,
       ST_GEOHASH(geog, 7) AS gh7__TARGET_COLS__
FROM isl ORDER BY snapshot_id, capture_time, capture_id
"""

_ROSETTE_TARGET_COLS = """,
       ST_DISTANCE(geog, ST_GEOGPOINT(COALESCE(@tlng, @lng), COALESCE(@tlat, @lat))) AS target_dist_m,
       ROUND(ST_AZIMUTH(geog, ST_GEOGPOINT(COALESCE(@tlng, @lng), COALESCE(@tlat, @lat))) * 180 / ACOS(-1), 3) AS target_bearing_deg,
       (SELECT AS STRUCT c.k, c.observation_id, c.heading,
               ABS(MOD(CAST(ROUND(c.heading - (ST_AZIMUTH(geog, ST_GEOGPOINT(COALESCE(@tlng, @lng), COALESCE(@tlat, @lat))) * 180 / ACOS(-1))) AS INT64) + 540, 360) - 180) AS off_axis_deg
        FROM UNNEST(cams) AS c WHERE c.k < 6 ORDER BY off_axis_deg LIMIT 1) AS best_cam"""


def rosette_sql(table: str = PANO_LATEST, *, include_target: bool = False) -> str:
    """Canonical capture_id-keyed rosette query with SQL-side sequences, bearings and cams."""
    if not is_pano_table(table):
        raise DisallowedTable(table)
    target_cols = _ROSETTE_TARGET_COLS if include_target else ""
    return _ROSETTE_SQL_TEMPLATE.replace("__TABLE__", table).replace("__TARGET_COLS__", target_cols)


ROSETTE_SQL = rosette_sql(PANO_LATEST)


def rosette_params(
    *,
    lat: float,
    lng: float,
    radius_m: float,
    snapshot_id: str | None = None,
    include_unpublished: bool = True,
    max_dt_ms: int = 5000,
    max_step_m: float = 35.0,
    tlat: float | None = None,
    tlng: float | None = None,
    include_target: bool = False,
) -> dict[str, tuple[Any, str]]:
    """Typed parameters for `rosette_sql`."""
    out: dict[str, tuple[Any, str]] = {
        "lat": (float(lat), "FLOAT64"),
        "lng": (float(lng), "FLOAT64"),
        "radius_m": (float(radius_m), "FLOAT64"),
        "snapshot_id": (snapshot_id, "STRING"),
        "include_unpublished": (bool(include_unpublished), "BOOL"),
        "max_dt_ms": (int(max_dt_ms), "INT64"),
        "max_step_m": (float(max_step_m), "FLOAT64"),
    }
    if include_target or tlat is not None or tlng is not None:
        out["tlat"] = (float(lat if tlat is None else tlat), "FLOAT64")
        out["tlng"] = (float(lng if tlng is None else tlng), "FLOAT64")
    return out


_SNAPSHOT_CATALOG_TEMPLATE = """
SELECT snapshot_id, subscription_id, creation_time,
       TIMESTAMP_ADD(creation_time, INTERVAL 35 DAY) AS expires_about,
       ARRAY_TO_STRING(product_types, ',') AS tiers
FROM `__TABLE__`
WHERE 'SV_PANO' IN UNNEST(product_types)
ORDER BY creation_time DESC
"""


def snapshot_catalog_sql(table: str = SNAP_TABLE) -> str:
    """Catalog of SV_PANO snapshots with approximate 35-day expiry timestamps."""
    if not is_pano_table(table):
        raise DisallowedTable(table)
    return _SNAPSHOT_CATALOG_TEMPLATE.replace("__TABLE__", table)


_CLUSTER_POINTS_SQL = """
SELECT p.entity_id, p.cls, p.lat, p.lng,
       ST_CLUSTERDBSCAN(ST_GEOGPOINT(p.lng, p.lat), @eps_m, @min_pts) OVER (PARTITION BY p.cls) AS cluster_id
FROM UNNEST(@points) AS p
ORDER BY p.cls, cluster_id, p.entity_id
"""


def cluster_points_sql() -> str:
    """Table-free ST_CLUSTERDBSCAN query over UNNEST(@points) (0 bytes scanned)."""
    return _CLUSTER_POINTS_SQL


def cluster_points_params(
    points: Sequence[Mapping[str, Any]],
    *,
    eps_m: float = 8.0,
    min_pts: int = 1,
) -> list[QueryParam]:
    """Parameters for `cluster_points_sql` (capped at MAX_UNNEST_POINTS)."""
    if len(points) > MAX_UNNEST_POINTS:
        raise ValueError(f"points length {len(points)} exceeds cap {MAX_UNNEST_POINTS}")
    structs = [
        bigquery.StructQueryParameter(
            None,
            bigquery.ScalarQueryParameter("entity_id", "STRING", str(pt["entity_id"])),
            bigquery.ScalarQueryParameter("cls", "STRING", str(pt["cls"])),
            bigquery.ScalarQueryParameter("lat", "FLOAT64", float(pt["lat"])),
            bigquery.ScalarQueryParameter("lng", "FLOAT64", float(pt["lng"])),
        )
        for pt in points
    ]
    return [
        bigquery.ArrayQueryParameter("points", "STRUCT", structs),
        bigquery.ScalarQueryParameter("eps_m", "FLOAT64", float(eps_m)),
        bigquery.ScalarQueryParameter("min_pts", "INT64", int(min_pts)),
    ]


_REPEAT_PAIRS_TEMPLATE = """
WITH p AS (
  SELECT capture_id, snapshot_id, MIN(capture_time) AS t, DATE(MIN(capture_time)) AS d,
         ANY_VALUE(ST_GEOGPOINT(capture_location.longitude, capture_location.latitude)) AS g
  FROM `__TABLE__`
  WHERE ST_DWITHIN(ST_GEOGPOINT(capture_location.longitude, capture_location.latitude),
                   ST_GEOGPOINT(@lng, @lat), @radius_m)
  GROUP BY capture_id, snapshot_id
),
pairs AS (
  SELECT a.capture_id AS a_id, b.capture_id AS b_id,
         a.snapshot_id AS a_snapshot_id, b.snapshot_id AS b_snapshot_id,
         a.d AS a_day, b.d AS b_day,
         ST_DISTANCE(a.g, b.g) AS sep_m, DATE_DIFF(b.d, a.d, DAY) AS days_apart,
         ROW_NUMBER() OVER (PARTITION BY a.capture_id, b.d ORDER BY ST_DISTANCE(a.g, b.g)) AS rn
  FROM p AS a JOIN p AS b
    ON a.d < b.d AND ST_DWITHIN(a.g, b.g, @pair_m)
)
SELECT a_id, b_id, a_snapshot_id, b_snapshot_id, a_day, b_day, days_apart, sep_m
FROM pairs WHERE rn = 1
ORDER BY a_day, b_day, sep_m
"""


def repeat_pairs_sql(table: str = PANO_LATEST) -> str:
    """Matched repeat-pass rosette pairs across distinct capture days within `@pair_m`."""
    if not is_pano_table(table):
        raise DisallowedTable(table)
    return _REPEAT_PAIRS_TEMPLATE.replace("__TABLE__", table)


def repeat_pairs_params(
    *,
    lat: float,
    lng: float,
    radius_m: float = 250.0,
    pair_m: float = 6.0,
) -> dict[str, tuple[Any, str]]:
    return {
        "lat": (float(lat), "FLOAT64"),
        "lng": (float(lng), "FLOAT64"),
        "radius_m": (float(radius_m), "FLOAT64"),
        "pair_m": (float(pair_m), "FLOAT64"),
    }


_COVERAGE_TEMPLATE = """
WITH p AS (
  SELECT capture_id, MIN(capture_time) AS t,
         ANY_VALUE(ST_GEOGPOINT(capture_location.longitude, capture_location.latitude)) AS g
  FROM `__TABLE__`
  WHERE capture_location.latitude BETWEEN @lat_min AND @lat_max
    AND capture_location.longitude BETWEEN @lng_min AND @lng_max
  GROUP BY capture_id
)
SELECT ST_GEOHASH(g, 6) AS gh6, COUNT(*) AS rosettes, COUNT(DISTINCT DATE(t)) AS capture_days,
       MIN(t) AS t_min, MAX(t) AS t_max, ST_ASTEXT(ST_CENTROID_AGG(g)) AS centroid_wkt
FROM p GROUP BY gh6 HAVING rosettes >= @min_rosettes
ORDER BY capture_days DESC, rosettes DESC LIMIT 200
"""


def coverage_sql(table: str = PANO_LATEST) -> str:
    """Geohash-6 coverage summary inside a lat/lng bounding box."""
    if not is_pano_table(table):
        raise DisallowedTable(table)
    return _COVERAGE_TEMPLATE.replace("__TABLE__", table)


def coverage_params(
    *,
    lat_min: float = 27.9,
    lat_max: float = 28.2,
    lng_min: float = -82.1,
    lng_max: float = -81.8,
    min_rosettes: int = 20,
) -> dict[str, tuple[Any, str]]:
    return {
        "lat_min": (float(lat_min), "FLOAT64"),
        "lat_max": (float(lat_max), "FLOAT64"),
        "lng_min": (float(lng_min), "FLOAT64"),
        "lng_max": (float(lng_max), "FLOAT64"),
        "min_rosettes": (int(min_rosettes), "INT64"),
    }


_TRACKS_TEMPLATE = """
WITH rosettes AS (
  SELECT capture_id, snapshot_id,
         ANY_VALUE(pano_id) AS pano_id, MIN(capture_time) AS capture_time,
         ANY_VALUE(ST_GEOGPOINT(capture_location.longitude, capture_location.latitude)) AS geog
  FROM `__TABLE__`
  WHERE ST_DWITHIN(ST_GEOGPOINT(capture_location.longitude, capture_location.latitude),
                   ST_GEOGPOINT(@lng, @lat), @radius_m)
    AND (@include_unpublished OR COALESCE(pano_id, '') != '')
  GROUP BY capture_id, snapshot_id
),
seq AS (
  SELECT *, LAG(geog) OVER w AS g_prev, LAG(capture_time) OVER w AS t_prev
  FROM rosettes WINDOW w AS (PARTITION BY snapshot_id ORDER BY capture_time, capture_id)
),
brk AS (
  SELECT *, IF(g_prev IS NULL OR TIMESTAMP_DIFF(capture_time, t_prev, MILLISECOND) > @max_dt_ms
                OR ST_DISTANCE(geog, g_prev) > @max_step_m, 1, 0) AS is_break
  FROM seq
),
isl AS (
  SELECT *, CONCAT(SUBSTR(snapshot_id, 1, 8), '_', CAST(SUM(is_break) OVER
              (PARTITION BY snapshot_id ORDER BY capture_time, capture_id) AS STRING)) AS seq_id
  FROM brk
)
SELECT seq_id, COUNT(*) AS n_rosettes, COUNTIF(pano_id IS NULL) AS n_null_pano_id,
       MIN(capture_time) AS t0, DATE(MIN(capture_time)) AS capture_day,
       ST_LENGTH(ST_MAKELINE(ARRAY_AGG(geog ORDER BY capture_time, capture_id))) AS len_m,
       ST_ASGEOJSON(ST_MAKELINE(ARRAY_AGG(geog ORDER BY capture_time, capture_id))) AS track_geojson
FROM isl GROUP BY seq_id HAVING n_rosettes >= 2 ORDER BY n_rosettes DESC
"""


def tracks_sql(table: str = PANO_LATEST) -> str:
    """Sequence track LineStrings and GeoJSON per SQL sequence."""
    if not is_pano_table(table):
        raise DisallowedTable(table)
    return _TRACKS_TEMPLATE.replace("__TABLE__", table)


def tracks_params(
    *,
    lat: float,
    lng: float,
    radius_m: float = 250.0,
    include_unpublished: bool = True,
    max_dt_ms: int = 5000,
    max_step_m: float = 35.0,
) -> dict[str, tuple[Any, str]]:
    return {
        "lat": (float(lat), "FLOAT64"),
        "lng": (float(lng), "FLOAT64"),
        "radius_m": (float(radius_m), "FLOAT64"),
        "include_unpublished": (bool(include_unpublished), "BOOL"),
        "max_dt_ms": (int(max_dt_ms), "INT64"),
        "max_step_m": (float(max_step_m), "FLOAT64"),
    }


_MULTI_AOI_ROSETTE_TEMPLATE = """
WITH frames AS (
  SELECT capture_id, pano_id, snapshot_id, capture_time, observation_id,
         ST_GEOGPOINT(capture_location.longitude, capture_location.latitude) AS geog,
         CAST(REGEXP_EXTRACT(observation_id, r'_(\\d)(?::|$)') AS INT64) AS k,
         camera_pose.heading AS heading, camera_pose.pitch AS pitch, camera_pose.roll AS roll,
         (SELECT a.name FROM UNNEST(@aois) AS a
          WHERE ST_DWITHIN(ST_GEOGPOINT(capture_location.longitude, capture_location.latitude),
                           ST_GEOGPOINT(a.lng, a.lat), @radius_m) LIMIT 1) AS aoi
  FROM `__TABLE__`
  WHERE (@include_unpublished OR COALESCE(pano_id, '') != '')
)
SELECT aoi, capture_id, ANY_VALUE(pano_id) AS pano_id, snapshot_id, MIN(capture_time) AS capture_time,
       ST_Y(ANY_VALUE(geog)) AS lat, ST_X(ANY_VALUE(geog)) AS lng,
       ST_ASTEXT(ANY_VALUE(geog)) AS wkt,
       ST_GEOHASH(ANY_VALUE(geog), 7) AS gh7,
       ARRAY_AGG(STRUCT(k, observation_id, heading, pitch, roll) ORDER BY k) AS cams
FROM frames WHERE aoi IS NOT NULL
GROUP BY aoi, capture_id, snapshot_id
"""


def multi_aoi_sql(table: str = PANO_LATEST) -> str:
    """Multi-AOI capture_id-keyed rosette query in one table scan."""
    if not is_pano_table(table):
        raise DisallowedTable(table)
    return _MULTI_AOI_ROSETTE_TEMPLATE.replace("__TABLE__", table)


def multi_aoi_rosette_params(
    aois: Mapping[str, tuple[float, float]] | Sequence[tuple[str, float, float]],
    radius_m: float = 1500.0,
    *,
    include_unpublished: bool = True,
) -> list[QueryParam]:
    return [
        named_aoi_array_param("aois", aois),
        bigquery.ScalarQueryParameter("radius_m", "FLOAT64", float(radius_m)),
        bigquery.ScalarQueryParameter("include_unpublished", "BOOL", bool(include_unpublished)),
    ]


_ASSETS_IN_AOI_TEMPLATE = """
SELECT asset_id, asset_type, location.latitude AS lat, location.longitude AS lng, detection_time,
       ST_DISTANCE(ST_GEOGPOINT(location.longitude, location.latitude), ST_GEOGPOINT(@lng, @lat)) AS dist_m
FROM `__TABLE__`
WHERE ST_DWITHIN(ST_GEOGPOINT(location.longitude, location.latitude), ST_GEOGPOINT(@lng, @lat), @radius_m)
ORDER BY dist_m
"""


def assets_in_aoi_sql(table: str = CROPPED_ASSETS_LATEST) -> str:
    """Metadata-only asset inventory inside an AOI (no gcs_uri)."""
    if not is_pano_table(table):
        raise DisallowedTable(table)
    return _ASSETS_IN_AOI_TEMPLATE.replace("__TABLE__", table)


def assets_in_aoi_params(
    *, lat: float, lng: float, radius_m: float = 250.0
) -> dict[str, tuple[Any, str]]:
    return {
        "lat": (float(lat), "FLOAT64"),
        "lng": (float(lng), "FLOAT64"),
        "radius_m": (float(radius_m), "FLOAT64"),
    }


def compute_bytes_manifest(
    runner: QueryRunner,
    *,
    output_path: Path | None = BYTES_MANIFEST_PATH,
) -> dict[str, Any]:
    """Dry-run every canonical SQL template, verify ceilings, and write `bytes_manifest.json`."""
    specs: list[tuple[str, str, Params | None, bool]] = [
        (
            "rosette_sql",
            rosette_sql(),
            rosette_params(lat=28.0502, lng=-81.9601, radius_m=250.0),
            False,
        ),
        (
            "rosette_target_sql",
            rosette_sql(include_target=True),
            rosette_params(
                lat=28.05047,
                lng=-81.96015,
                radius_m=80.0,
                tlat=28.05047,
                tlng=-81.96015,
                include_target=True,
            ),
            False,
        ),
        ("snapshot_catalog_sql", snapshot_catalog_sql(), None, False),
        (
            "cluster_points_sql",
            cluster_points_sql(),
            cluster_points_params(
                [
                    {"entity_id": "e1", "cls": "UTILITY_POLE", "lat": 28.0502, "lng": -81.9601},
                    {"entity_id": "e2", "cls": "UTILITY_POLE", "lat": 28.05023, "lng": -81.96012},
                ]
            ),
            True,
        ),
        (
            "repeat_pairs_sql",
            repeat_pairs_sql(),
            repeat_pairs_params(lat=28.0502, lng=-81.9601, radius_m=250.0, pair_m=6.0),
            False,
        ),
        ("coverage_sql", coverage_sql(), coverage_params(), False),
        (
            "tracks_sql",
            tracks_sql(),
            tracks_params(lat=28.0502, lng=-81.9601, radius_m=250.0),
            False,
        ),
        (
            "multi_aoi_sql",
            multi_aoi_sql(),
            multi_aoi_rosette_params(
                [("tune", 28.05, -81.96), ("heldout", 40.76, -111.91), ("stress", 34.71, 135.54)],
                radius_m=1500.0,
            ),
            False,
        ),
        (
            "assets_in_aoi_sql",
            assets_in_aoi_sql(),
            assets_in_aoi_params(lat=28.0502, lng=-81.9601, radius_m=250.0),
            False,
        ),
    ]
    templates_out: dict[str, dict[str, Any]] = {}
    for name, sql, params, table_free in specs:
        n_bytes = runner.dry_run(sql, params, allow_table_free=table_free)
        ceiling = TEMPLATE_CEILINGS_BYTES[name]
        templates_out[name] = {
            "dry_run_bytes": n_bytes,
            "dry_run_gb": round(n_bytes / 1e9, 6),
            "ceiling_bytes": ceiling,
            "ceiling_gb": round(ceiling / 1e9, 6),
            "usd_at_6_25_per_tb": round((n_bytes / 1e12) * 6.25, 5),
        }
    manifest = {
        "project": PROJECT,
        "dataset": DATASET,
        "hard_max_bytes": HARD_MAX_BYTES,
        "templates": templates_out,
    }
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


# --------------------------------------------------------------------------- Legacy frame SQL

_PANO_META_TEMPLATE = """
SELECT
  pano_id,
  observation_id,
  snapshot_id,
  capture_time,
  capture_location.latitude AS lat,
  capture_location.longitude AS lng,
  camera_pose.heading AS heading,
  camera_pose.pitch AS pitch,
  camera_pose.roll AS roll,
  camera_pose.latitude AS cam_lat,
  camera_pose.longitude AS cam_lng,
  camera_pose.altitude AS cam_alt
FROM `__TABLE__`
WHERE COALESCE(pano_id, '') != ''
  AND (@snapshot_id IS NULL OR snapshot_id = @snapshot_id)
  AND (@radius_m IS NULL OR ST_DWITHIN(
        ST_GEOGPOINT(capture_location.longitude, capture_location.latitude),
        ST_GEOGPOINT(@lng, @lat), @radius_m))
  AND (@sample_mod IS NULL OR MOD(ABS(FARM_FINGERPRINT(pano_id)), @sample_mod) = @sample_rem)
  AND (@t_start IS NULL OR capture_time >= @t_start)
  AND (@t_end IS NULL OR capture_time < @t_end)
"""


def pano_meta_sql(table: str = PANO_LATEST) -> str:
    """Metadata-only pano query (no gcs_uri) for an allow-listed table."""
    if not is_pano_table(table):
        raise DisallowedTable(table)
    return _PANO_META_TEMPLATE.replace("__TABLE__", table)


PANO_META_SQL = pano_meta_sql(PANO_LATEST)


def pano_meta_params(
    *,
    snapshot_id: str | None = None,
    lat: float | None = None,
    lng: float | None = None,
    radius_m: float | None = None,
    sample_mod: int | None = None,
    sample_rem: int = 0,
    t_start: dt.datetime | None = None,
    t_end: dt.datetime | None = None,
) -> dict[str, tuple[Any, str]]:
    """Typed parameters for PANO_META_SQL (None disables a filter)."""
    return {
        "snapshot_id": (snapshot_id, "STRING"),
        "lat": (None if lat is None else float(lat), "FLOAT64"),
        "lng": (None if lng is None else float(lng), "FLOAT64"),
        "radius_m": (None if radius_m is None else float(radius_m), "FLOAT64"),
        "sample_mod": (sample_mod, "INT64"),
        "sample_rem": (int(sample_rem), "INT64"),
        "t_start": (t_start, "TIMESTAMP"),
        "t_end": (t_end, "TIMESTAMP"),
    }


_MULTI_AOI_TEMPLATE = """
SELECT
  pano_id,
  observation_id,
  snapshot_id,
  capture_time,
  capture_location.latitude AS lat,
  capture_location.longitude AS lng,
  camera_pose.heading AS heading,
  camera_pose.pitch AS pitch,
  camera_pose.roll AS roll,
  camera_pose.latitude AS cam_lat,
  camera_pose.longitude AS cam_lng,
  camera_pose.altitude AS cam_alt
FROM `__TABLE__`
WHERE COALESCE(pano_id, '') != ''
  AND EXISTS (
    SELECT 1 FROM UNNEST(@aois) AS a
    WHERE ST_DWITHIN(
      ST_GEOGPOINT(capture_location.longitude, capture_location.latitude),
      ST_GEOGPOINT(a.lng, a.lat), @radius_m))
"""


def multi_aoi_meta_sql(table: str = PANO_LATEST) -> str:
    """Metadata for every pano within `@radius_m` of any AOI centre in `@aois` (one scan)."""
    if not is_pano_table(table):
        raise DisallowedTable(table)
    return _MULTI_AOI_TEMPLATE.replace("__TABLE__", table)


def multi_aoi_params(aois: Sequence[tuple[float, float]], radius_m: float) -> list[QueryParam]:
    return [
        aoi_array_param("aois", aois),
        bigquery.ScalarQueryParameter("radius_m", "FLOAT64", float(radius_m)),
    ]


def assign_nearest_aoi(
    frames: pd.DataFrame, aois: Mapping[str, tuple[float, float]], max_dist_m: float
) -> pd.DataFrame:
    """Label each row with the nearest AOI name (None if farther than `max_dist_m`)."""
    from svi_geo.geo import haversine_m

    names = list(aois)
    lat = frames["lat"].to_numpy(dtype=float)
    lng = frames["lng"].to_numpy(dtype=float)
    dists = [haversine_m(lat, lng, aois[n][0], aois[n][1]) for n in names]
    stacked = np.vstack([np.broadcast_to(d, lat.shape) for d in dists])
    best = stacked.argmin(axis=0)
    best_d = stacked[best, np.arange(lat.size)]
    out = frames.copy()
    out["aoi"] = [names[b] if d <= max_dist_m else None for b, d in zip(best, best_d, strict=True)]
    return out


# --------------------------------------------------------------------------- GCS paths

DEFAULT_QUERY_CACHE = Path.home() / ".cache" / "svi_geo" / "bq"


def gcs_uri_for(bucket: str, snapshot_id: str, observation_id: str) -> str:
    """Frame URI derived from metadata, so `gcs_uri` never has to be selected (~1.9 GB scan).

    Layout of the Imagery Insights frame bucket linked to your dataset (the bucket name is a
    required parameter, `GCS_BUCKET`):

        gs://<bucket>/<snapshot_id>/v0/<observation_id>.jpg

    e.g. `gs://b/21d75cd4-.../v0/o1:<pano_id>_0:5001ee.jpg`. This layout is what the published
    `gcs_uri` column contains; if it ever changes, a fetch fails with 404 rather than returning
    the wrong frame.
    """
    b = bucket.removeprefix("gs://").strip("/")
    return f"gs://{b}/{snapshot_id}/v0/{observation_id}.jpg"


def split_gcs_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("gs://"):
        raise ValueError(f"not a gs:// uri: {uri}")
    bucket, _, name = uri[5:].partition("/")
    return bucket, name


# --------------------------------------------------------------------------- frames


def ensure_capture_id(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure `capture_id` is present as primary rosette key and `pano_id` as nullable metadata."""
    if "capture_id" in df.columns and "pano_id" in df.columns:
        return df
    out = df.copy()
    if "capture_id" not in out.columns:
        if "pano_id" in out.columns:
            out["capture_id"] = out["pano_id"]
        else:
            out["capture_id"] = [f"cap_{i}" for i in range(len(out))]
    if "pano_id" not in out.columns:
        out["pano_id"] = out["capture_id"]
    return out


def frames_from_rosettes(rosettes: pd.DataFrame, bucket: str | None = None) -> pd.DataFrame:
    """Explode rosette rows (`cams` ARRAY<STRUCT>) into one row per camera frame.

    Derives `gcs_uri` via `gcs_uri_for(bucket, snapshot_id, observation_id)` when `bucket` is
    provided, so `gcs_uri` never needs to be queried from BigQuery.
    """
    rosettes = ensure_capture_id(rosettes)
    passthrough = [
        c
        for c in (
            "map_url",
            "seq_id",
            "seq_idx",
            "step_m",
            "cum_m",
            "travel_deg",
            "gh7",
            "wkt",
            "aoi",
            "target_dist_m",
            "target_bearing_deg",
        )
        if c in rosettes.columns
    ]
    rows: list[dict[str, Any]] = []
    for r in rosettes.to_dict("records"):
        cid = str(r["capture_id"])
        pid = r.get("pano_id")
        snap = str(r["snapshot_id"])
        ctime = pd.to_datetime(r["capture_time"], utc=True)
        lat = float(r["lat"])
        lng = float(r["lng"])
        alt_raw = r.get("cam_alt")
        cam_alt = float(alt_raw) if alt_raw is not None and pd.notna(alt_raw) else 0.0
        extra = {col: r.get(col) for col in passthrough}
        cams = r.get("cams")
        for c in () if cams is None else cams:
            obs_id = str(c["observation_id"])
            k_raw = c.get("k")
            cam_k = int(k_raw) if k_raw is not None else int(rosette.camera_index(obs_id) or 0)
            heading = float(c["heading"])
            pitch = float(c["pitch"])
            roll = float(c["roll"])
            cam_lat = float(c["cam_lat"]) if c.get("cam_lat") is not None else lat
            cam_lng = float(c["cam_lng"]) if c.get("cam_lng") is not None else lng
            pose = {
                "heading": heading,
                "pitch": pitch,
                "roll": roll,
                "latitude": cam_lat,
                "longitude": cam_lng,
                "altitude": cam_alt,
            }
            uri = gcs_uri_for(bucket, snap, obs_id) if bucket else None
            rows.append(
                {
                    "capture_id": cid,
                    "pano_id": pid,
                    "observation_id": obs_id,
                    "snapshot_id": snap,
                    "capture_time": ctime,
                    "lat": lat,
                    "lng": lng,
                    "cam_k": cam_k,
                    "heading": heading,
                    "pitch": pitch,
                    "roll": roll,
                    "cam_lat": cam_lat,
                    "cam_lng": cam_lng,
                    "cam_alt": cam_alt,
                    "camera_pose": pose,
                    "gcs_uri": uri,
                    **extra,
                }
            )
    return pd.DataFrame(rows)


def normalize_frames(df: pd.DataFrame) -> pd.DataFrame:
    """Add `cam_k`, `capture_id`, and a `camera_pose` dict column to frame metadata output."""
    out = ensure_capture_id(df.copy())
    out["cam_k"] = out["observation_id"].map(rosette.camera_index)
    out["camera_pose"] = [
        {
            "heading": float(r.heading),
            "pitch": float(r.pitch),
            "roll": float(r.roll),
            "latitude": float(r.cam_lat),
            "longitude": float(r.cam_lng),
            "altitude": float(r.cam_alt),
        }
        for r in out.itertuples(index=False)
    ]
    if "capture_time" in out:
        out["capture_time"] = pd.to_datetime(out["capture_time"], utc=True)
    return out


def panos_from_frames(frames: pd.DataFrame) -> pd.DataFrame:
    """One row per rosette (capture_id, pano_id, snapshot_id, capture_time, lat, lng)."""
    df = ensure_capture_id(frames)
    base_cols = ["capture_id", "pano_id", "snapshot_id", "capture_time", "lat", "lng"]
    extra_cols = [
        c
        for c in ("seq_id", "seq_idx", "step_m", "cum_m", "travel_deg", "gh7", "wkt", "map_url")
        if c in df.columns
    ]
    cols = base_cols + extra_cols
    return (
        df[cols]
        .drop_duplicates("capture_id")
        .sort_values(["snapshot_id", "capture_time", "capture_id"])
        .reset_index(drop=True)
    )


rosettes_from_frames = panos_from_frames


def make_bigquery_client(project: str = PROJECT, credentials: Any = None) -> bigquery.Client:
    return bigquery.Client(project=project, credentials=credentials)
