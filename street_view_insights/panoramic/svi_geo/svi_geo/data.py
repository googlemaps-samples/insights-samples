"""Guarded BigQuery access to the Street View Insights pano views, plus GCS path derivation.

Rules enforced here:
* Only `pano_observations_latest` / `pano_observations_all` (in any project) may be queried.
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
ALLOWED_TABLES = frozenset({PANO_LATEST, PANO_ALL})
HARD_MAX_BYTES = 2_000_000_000
FORBIDDEN_MARKERS = ("full_frame_", "cropped_", "all_observations", "all_assets")
PANO_VIEWS = ("pano_observations_latest", "pano_observations_all")
_PANO_TABLE_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_\-]*\.imagery_insights___us\.pano_observations_(latest|all)$"
)
_IDENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]*$")


class QueryTooExpensive(RuntimeError):
    """Dry run exceeded the byte cap; the real query was not executed."""


class DisallowedTable(ValueError):
    """SQL referenced a table outside the pano allow-list."""


class UnsafeSql(ValueError):
    """SQL looks string-formatted (contains braces)."""


def is_pano_table(name: str) -> bool:
    """True for `<project>.<dataset>.pano_observations_latest|all` (any project/dataset)."""
    return bool(_PANO_TABLE_RE.match(name or ""))


def pano_table(project: str, dataset: str = DATASET, view: str = PANO_VIEWS[0]) -> str:
    """Fully-qualified pano view in the caller's project (identifiers validated)."""
    if view not in PANO_VIEWS:
        raise DisallowedTable(f"only {PANO_VIEWS} may be queried, got {view!r}")
    for v in (project, dataset):
        if not _IDENT_RE.match(v or ""):
            raise ValueError(f"invalid BigQuery identifier: {v!r}")
    return f"{project}.{dataset}.{view}"


def pano_tables(project: str, dataset: str = DATASET) -> frozenset[str]:
    return frozenset(pano_table(project, dataset, v) for v in PANO_VIEWS)


_TABLE_TOKEN = re.compile(r"`([^`]+)`|\b(?:FROM|JOIN)\s+([A-Za-z0-9_\-]+\.[A-Za-z0-9_\-.]+)", re.I)


def referenced_tables(sql: str) -> set[str]:
    """Fully-qualified table references (backticked or after FROM/JOIN)."""
    out = set()
    for m in _TABLE_TOKEN.finditer(sql):
        name = (m.group(1) or m.group(2) or "").strip()
        if name.count(".") >= 1:
            out.add(name.replace("`", ""))
    return out


def assert_allowed_table(sql: str, allowed: frozenset[str] = ALLOWED_TABLES) -> None:
    lowered = sql.lower()
    for marker in FORBIDDEN_MARKERS:
        if marker in lowered:
            raise DisallowedTable(f"forbidden table marker {marker!r} in SQL")
    tables = referenced_tables(sql)
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
    ):
        if max_bytes > HARD_MAX_BYTES:
            raise ValueError(f"max_bytes must be <= {HARD_MAX_BYTES}")
        self.client = client
        self.max_bytes = int(max_bytes)
        requested = frozenset(allowed_tables)
        if not requested or not all(is_pano_table(t) for t in requested):
            raise DisallowedTable(f"allowed_tables must be pano views only: {sorted(requested)}")
        self.allowed_tables = requested
        self.log = log
        self.cache_dir = cache_dir
        self.cache_ttl_s = cache_ttl_s
        self.last_dry_run_bytes: int | None = None
        self.total_billed_estimate = 0

    def dry_run(self, sql: str, params: Params | None = None) -> int:
        self._check(sql)
        cfg = bigquery.QueryJobConfig(
            dry_run=True, use_query_cache=False, query_parameters=build_params(params)
        )
        job = self.client.query(sql, job_config=cfg)
        self.last_dry_run_bytes = int(job.total_bytes_processed or 0)
        return self.last_dry_run_bytes

    def run(self, sql: str, params: Params | None = None, refresh: bool = False) -> pd.DataFrame:
        self._check(sql)
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
        n = self.dry_run(sql, params)
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

    def _check(self, sql: str) -> None:
        if "{" in sql or "}" in sql:
            raise UnsafeSql("SQL contains braces; build SQL with @params, not string formatting")
        assert_allowed_table(sql, self.allowed_tables)


# --------------------------------------------------------------------------- SQL

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
WHERE pano_id IS NOT NULL
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
WHERE pano_id IS NOT NULL
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

DEFAULT_BUCKET_CACHE = Path.home() / ".cache" / "svi_geo" / "bucket.json"
DEFAULT_QUERY_CACHE = Path.home() / ".cache" / "svi_geo" / "bq"


def gcs_uri_for(bucket: str, snapshot_id: str, observation_id: str) -> str:
    b = bucket.removeprefix("gs://").strip("/")
    return f"gs://{b}/{snapshot_id}/v0/{observation_id}.jpg"


def split_gcs_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("gs://"):
        raise ValueError(f"not a gs:// uri: {uri}")
    bucket, _, name = uri[5:].partition("/")
    return bucket, name


_BUCKET_SQL_TEMPLATE = "SELECT gcs_uri FROM `__TABLE__` WHERE pano_id IS NOT NULL LIMIT 1"


def discover_bucket(
    runner: QueryRunner,
    table: str = PANO_LATEST,
    cache_path: str | Path = DEFAULT_BUCKET_CACHE,
    override: str | None = None,
) -> str:
    """Bucket holding the pano frames: override > $GCS_BUCKET > cache > one guarded query (~1.9 GB)."""
    if override:
        return override.removeprefix("gs://").strip("/")
    env = os.environ.get("GCS_BUCKET")
    if env:
        return env.removeprefix("gs://").strip("/")
    cache_path = Path(cache_path)
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    if table in cache:
        return cache[table]
    if not is_pano_table(table):
        raise DisallowedTable(table)
    df = runner.run(_BUCKET_SQL_TEMPLATE.replace("__TABLE__", table))
    bucket, _ = split_gcs_uri(str(df["gcs_uri"].iloc[0]))
    cache[table] = bucket
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cache, indent=2))
    return bucket


# --------------------------------------------------------------------------- frames


def normalize_frames(df: pd.DataFrame) -> pd.DataFrame:
    """Add `cam_k` and a `camera_pose` dict column to PANO_META_SQL output."""
    out = df.copy()
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
    """One row per pano (pano_id, snapshot_id, capture_time, lat, lng)."""
    cols = ["pano_id", "snapshot_id", "capture_time", "lat", "lng"]
    return (
        frames[cols]
        .drop_duplicates("pano_id")
        .sort_values(["snapshot_id", "capture_time"])
        .reset_index(drop=True)
    )


def make_bigquery_client(project: str = PROJECT, credentials: Any = None) -> bigquery.Client:
    return bigquery.Client(project=project, credentials=credentials)
