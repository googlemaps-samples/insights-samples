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

import importlib.util
import os
import re
import google.auth


def _resolve_default_project():
    project = os.environ.get("PROJECT_ID") or os.environ.get("GCP_PROJECT")
    if project:
        return project
    try:
        _, auth_project = google.auth.default()
        return auth_project
    except Exception:
        return None


GCP_PROJECT = _resolve_default_project()
LOCATION = os.environ.get("REGION", "us-central1")

# BigQuery Configuration
BIGQUERY_RESULTS_DATASET = "imagery_insights_analysis"
BIGQUERY_RESULTS_TABLE = "resolution_road_signs_evaluations"
BIGQUERY_CLOUD_TASKS_TABLE = "populate_tasks_from_bq"

BIGQUERY_SOURCE_DATASET = os.environ.get("BIGQUERY_SOURCE_DATASET", "imagery_insights___us")
BIGQUERY_SOURCE_TABLE = os.environ.get("BIGQUERY_SOURCE_TABLE", "cropped_observations_latest")

BIGQUERY_SOURCE_QUERY = """
SELECT
  t1.asset_id,
  t1.location,
  MAX(t1.detection_time) as detection_time,
  ARRAY_AGG(STRUCT(t1.observation_id,
      t1.gcs_uri)) AS observations
FROM
  `{source_table}` AS t1
WHERE
  t1.asset_type = 'ASSET_CLASS_ROAD_SIGN'
GROUP BY
  t1.asset_id,
  t1.location
"""
BIGQUERY_COUNT_QUERY = """
SELECT
  COUNT(*) as total_rows
FROM
  `{source_table}` AS t1
WHERE
  t1.asset_type = 'ASSET_CLASS_ROAD_SIGN'
"""

# Cloud Tasks Configuration
TASK_QUEUE_PREFIX = "image-analysis-queue-"
SHARD_SIZE = 50
POPULATE_TOPIC_ID_PREFIX = "populate-tasks-topic-"
SUBSCRIPTION_ID_PREFIX = "populate-tasks-sub-"

# Cloud Run Configuration
BATCH_SIZE = 100
STATE_FILE = "populate_state.json"
ANALYZE_SERVICE_URL = os.environ.get("ANALYZE_SERVICE_URL") or os.environ.get("SERVICE_URL")
SERVICE_URL = ANALYZE_SERVICE_URL
POPULATE_SERVICE_URL = os.environ.get("POPULATE_SERVICE_URL")
SERVICE_ACCOUNT_EMAIL = os.environ.get("SERVICE_ACCOUNT_EMAIL")
REQUIRE_AUTH = os.environ.get("REQUIRE_AUTH", "true").lower() != "false"

# Only gs:// URIs under this configured bucket/prefix may be analyzed by /process.
# Fail closed when unset or left as a placeholder value.
ALLOWED_GCS_PREFIX = os.environ.get("ALLOWED_GCS_PREFIX", "").strip()

_GCS_BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,220}[a-z0-9]$")
_PLACEHOLDER_BUCKETS = frozenset(
    {"your-allowed-imagery-bucket", "your-imagery-bucket"}
)


def _has_unsafe_uri_chars(value):
    return any(c.isspace() or ord(c) < 32 or ord(c) == 127 or c in "\\?#" for c in value)


def normalize_gcs_prefix(prefix):
    """Validates and normalizes an allowed gs://bucket[/prefix]/ string."""
    if not isinstance(prefix, str):
        return None
    candidate = prefix.strip()
    if not candidate.startswith("gs://") or _has_unsafe_uri_chars(candidate):
        return None
    rest = candidate[5:]
    if not rest:
        return None
    if rest.endswith("/"):
        rest = rest[:-1]
        if rest.endswith("/"):
            return None
    parts = rest.split("/")
    bucket = parts[0]
    if (
        not _GCS_BUCKET_RE.match(bucket)
        or ".." in bucket
        or bucket in _PLACEHOLDER_BUCKETS
    ):
        return None
    if any(not seg or seg in {".", ".."} for seg in parts[1:]):
        return None
    return f"gs://{rest}/"


def is_allowed_gcs_uri(uri, allowed_prefix=None):
    """Returns True iff uri is a clean gs:// object path under the allowed prefix."""
    normalized_prefix = normalize_gcs_prefix(
        ALLOWED_GCS_PREFIX if allowed_prefix is None else allowed_prefix
    )
    if normalized_prefix is None:
        return False
    if not isinstance(uri, str) or not uri.startswith("gs://"):
        return False
    if _has_unsafe_uri_chars(uri):
        return False
    rest = uri[5:]
    segments = rest.split("/")
    if len(segments) < 2 or any(seg in {"", ".", ".."} for seg in segments):
        return False
    return uri.startswith(normalized_prefix) and len(uri) > len(normalized_prefix)


# Gemini Model Configuration
GEMINI_MODEL = "gemini-3.7-flash"


def load_prompts_from_directory(directory):
    prompts = {}
    schemas = {}
    for filename in os.listdir(directory):
        if filename.endswith(".py"):
            module_name = filename[:-3]
            module_path = os.path.join(directory, filename)
            spec = importlib.util.spec_from_file_location(module_name, module_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if hasattr(module, "PROMPT"):
                prompts[module_name.upper()] = module.PROMPT
            if hasattr(module, "SCHEMA"):
                schemas[module_name.upper()] = module.SCHEMA
    return prompts, schemas


PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")
PROMPTS, BIGQUERY_SCHEMAS = load_prompts_from_directory(PROMPTS_DIR)

# Change this value to 'ROAD_SIGNS' to use the road signs prompt
SELECTED_PROMPT_KEY = "RESOLUTION"

# The GEMINI_PROMPT used in the application is now selected dynamically
GEMINI_PROMPT = PROMPTS[SELECTED_PROMPT_KEY]