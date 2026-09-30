"""Explicit run settings for the notebooks, scripts and skills.

The billing project and the frame bucket must be given explicitly: as a notebook parameter or
through the `PROJECT_ID` / `GCS_BUCKET` entries of the `env` mapping passed in by the caller.
There are no silent fallbacks: `GOOGLE_CLOUD_PROJECT` and the ADC project are ignored (they
picked the wrong billing project on managed workstations), and the bucket is never discovered
by selecting `gcs_uri` (a ~1.9 GB scan). `resolve_settings` never reads `os.environ` itself;
callers pass `dict(os.environ)` so the source of every value is visible.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Mapping

PROJECT_PLACEHOLDER = "YOUR_PROJECT_ID"
DEFAULT_DATASET = "imagery_insights___us"
_PROJECT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-.:]*$")
_BUCKET_RE = re.compile(r"^[a-z0-9]([a-z0-9_\-.]*[a-z0-9])?$")


class ConfigError(ValueError):
    """A required setting is missing, still a placeholder, or malformed."""


@dataclasses.dataclass(frozen=True)
class Settings:
    project: str
    bucket: str
    dataset: str = DEFAULT_DATASET


def normalize_bucket(value: str) -> str:
    """`gs://b/` -> `b`."""
    return (value or "").strip().removeprefix("gs://").strip("/")


def _pick(explicit: str | None, env: Mapping[str, str], key: str, placeholders: set[str]) -> str:
    v = (explicit or "").strip()
    if v and v not in placeholders:
        return v
    return (env.get(key) or "").strip()


def require_bucket(value: str | None, env: Mapping[str, str] | None = None) -> str:
    """Frame bucket from an explicit value, else `env["GCS_BUCKET"]`; raises if neither."""
    b = normalize_bucket(_pick(value, env or {}, "GCS_BUCKET", {""}))
    if not b:
        raise ConfigError(
            "GCS_BUCKET is required: the Imagery Insights frame bucket linked to your project "
            "(gs://<bucket>/<snapshot_id>/v0/<observation_id>.jpg)."
        )
    if not _BUCKET_RE.match(b):
        raise ConfigError(f"GCS_BUCKET is not a valid bucket name: {b!r}")
    return b


def resolve_settings(
    project: str | None = PROJECT_PLACEHOLDER,
    bucket: str | None = "",
    env: Mapping[str, str] | None = None,
    dataset: str = DEFAULT_DATASET,
) -> Settings:
    """Validated settings; an explicit value beats `env`, placeholders fall through to `env`.

    Raises `ConfigError` naming every missing parameter (`PROJECT_ID`, `GCS_BUCKET`).
    """
    env = env or {}
    proj = _pick(project, env, "PROJECT_ID", {PROJECT_PLACEHOLDER})
    missing = []
    if not proj or proj == PROJECT_PLACEHOLDER:
        missing.append("PROJECT_ID (your billing project for BigQuery and Vertex AI)")
    try:
        b = require_bucket(bucket, env)
    except ConfigError as err:
        if "required" not in str(err):
            raise
        b = ""
        missing.append("GCS_BUCKET (the frame bucket linked to your Imagery Insights dataset)")
    if missing:
        raise ConfigError(
            "Set these notebook parameters or environment variables: " + "; ".join(missing)
        )
    if not _PROJECT_RE.match(proj):
        raise ConfigError(f"PROJECT_ID is not a valid project id: {proj!r}")
    if not re.match(r"^[A-Za-z0-9_]+$", dataset or ""):
        raise ConfigError(f"invalid dataset id: {dataset!r}")
    return Settings(project=proj, bucket=b, dataset=dataset)
