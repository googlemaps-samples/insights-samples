import os
import importlib.util
import google.auth
from google.cloud import bigquery

# --- FIX 1: GCP Project Configuration ---
# Use environment variables instead of hardcoded 'sarthaks-lab'
_, auth_project = google.auth.default()
GCP_PROJECT = os.environ.get("PROJECT_ID", os.environ.get("GCP_PROJECT", auth_project))
LOCATION = os.environ.get("REGION", "us-central1")

# BigQuery Configuration
BIGQUERY_RESULTS_DATASET = "imagery_insights_analysis"
BIGQUERY_RESULTS_TABLE = "resolution_road_signs_evaluations"
BIGQUERY_CLOUD_TASKS_TABLE = "populate_tasks_from_bq"

# --- FIX 2: Apply the new schema workaround for the Cropped variant ---
BIGQUERY_SOURCE_DATASET = "imagery_insights___us"
BIGQUERY_SOURCE_TABLE = "cropped_observations_latest"

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

# --- FIX 3: Cloud Run Configuration ---
# Load from environment variables instead of hardcoded URLs!
BATCH_SIZE = 100
STATE_FILE = "populate_state.json"
SERVICE_URL = os.environ.get("SERVICE_URL")
POPULATE_SERVICE_URL = os.environ.get("POPULATE_SERVICE_URL")
SERVICE_ACCOUNT_EMAIL = os.environ.get("SERVICE_ACCOUNT_EMAIL")

# --- FIX 4: Gemini Model Configuration ---
# Upgraded to 3.5 flash to prevent deprecation 404 errors
GEMINI_MODEL = "gemini-3.5-flash"

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
