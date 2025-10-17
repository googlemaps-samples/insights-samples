# GCP Project Configuration
GCP_PROJECT = "sarthaks-lab"
LOCATION = "us-central1"

from google.cloud import bigquery

# BigQuery Configuration
BIGQUERY_RESULTS_DATASET = "imagery_insights_analysis"
BIGQUERY_RESULTS_TABLE = "road_pole_evaluations"
BIGQUERY_CLOUD_TASKS_TABLE = "populate_tasks_from_bq"
BIGQUERY_SOURCE_DATASET = "imagery_insights___preview___us"
BIGQUERY_SOURCE_TABLE = "latest_observations"
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
SERVICE_URL = "https://analyze-volume-images-635092392839.us-central1.run.app" # Replace with your main service URL after deployment
POPULATE_SERVICE_URL = "https://populate-tasks-635092392839.us-central1.run.app" # Replace with your populate service URL after deployment
SERVICE_ACCOUNT_EMAIL = "635092392839-compute@developer.gserviceaccount.com" # Replace with your service account email

# Gemini Model Configuration
GEMINI_MODEL = "gemini-2.5-flash"

# Gemini Model Prompt
UTILITY_POLE_PROMPT = """
You will be provided with a series of photos of a utility pole.
 
Instructions:
 
1. Analyze the provided images. If the images do not clearly show a utility pole, return: {\"error\": \"No utility pole detected in the images.\"}
2. Detect and count the following across all images, providing a consolidated count:
    * Transformers
    * Power lines coming from the pole
    * Street lamps attached to the pole
    * Telephone or junction boxes
3. Assess the overall condition of the pole. Look for visible damage, bird nests, or other issues. If the pole appears to be in good condition, note \"OK\".
4. Note the material with which the pole is made.
5. Determine the primary type of pole. Report this in the type field:
  * Street light
  * High tension power transmission
  * Electricity pole
  * Other
6. Provide your findings in the following JSON format:
 
```json
{
  \"pole_condition\": \"OK/Damaged/Other Issues\",
  \"type\": \"<pole_type>\",
  \"material\": \"<material>\",
  \"transformers\": <number_of_transformers>,
  \"power_lines\": <number_of_power_lines>,
  \"street_lamps\": <number_of_street_lamps>,
  \"junction_boxes\": <number_of_junction_boxes>,
  \"additional_notes\": \"<any_other_observations>\"
}
```
"""

ROAD_SIGNS_PROMPT = """Classify the road sign in this image into one of the following categories:
                     * Stop,
                     * Yield,
                     * Speed Limit,
                     * Pedestrian Crossing,
                     * No Parking,
                     * Turn,
                     * Do not enter,
                     * Street name
                     * Other
                   Provide the category and a description in JSON format.
                   Provide a field called "sign_quality" where you should list if the sign in good condition, bad etc. Report using the followng categories:
                     * Good
                     * Fair
                     * Poor
                     * Critical
                     * Other
                   If the image quality is poor, include notes about that in "image_quality_notes", and do your best to analyze the sign.
                   Return the result as a json object.
                   Example:
                   ```json
                   {
                       "category": "Stop",
                       "sign_quality": "Good"
                       "description": "A red octagonal stop sign is clearly visible.",
                       "image_quality_notes": "image is clear"
                   }
"""

# Prompt Selection
PROMPTS = {
    "UTILITY_POLE": UTILITY_POLE_PROMPT,
    "ROAD_SIGNS": ROAD_SIGNS_PROMPT,
}

# Change this value to 'ROAD_SIGNS' to use the road signs prompt
SELECTED_PROMPT_KEY = "ROAD_SIGNS"

# The GEMINI_PROMPT used in the application is now selected dynamically
GEMINI_PROMPT = PROMPTS[SELECTED_PROMPT_KEY]

# BigQuery Schemas
BIGQUERY_SCHEMAS = {
    "UTILITY_POLE": [
        bigquery.SchemaField("asset_id", "STRING", mode="NULLABLE"),
        bigquery.SchemaField(
            "location",
            "RECORD",
            mode="NULLABLE",
            fields=[
                bigquery.SchemaField("latitude", "FLOAT", mode="NULLABLE"),
                bigquery.SchemaField("longitude", "FLOAT", mode="NULLABLE"),
            ],
        ),
        bigquery.SchemaField("observation_ids", "STRING", mode="REPEATED"),
        bigquery.SchemaField("gcs_uris", "STRING", mode="REPEATED"),
        bigquery.SchemaField("detection_time", "TIMESTAMP", mode="NULLABLE"),
        bigquery.SchemaField("pole_condition", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("type", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("material", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("transformers", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("power_lines", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("street_lamps", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("junction_boxes", "INTEGER", mode="NULLABLE"),
        bigquery.SchemaField("additional_notes", "STRING", mode="NULLABLE"),
    ],
    "ROAD_SIGNS": [
        bigquery.SchemaField("asset_id", "STRING", mode="NULLABLE"),
        bigquery.SchemaField(
            "location",
            "RECORD",
            mode="NULLABLE",
            fields=[
                bigquery.SchemaField("latitude", "FLOAT", mode="NULLABLE"),
                bigquery.SchemaField("longitude", "FLOAT", mode="NULLABLE"),
            ],
        ),
        bigquery.SchemaField("observation_ids", "STRING", mode="REPEATED"),
        bigquery.SchemaField("gcs_uris", "STRING", mode="REPEATED"),
        bigquery.SchemaField("detection_time", "TIMESTAMP", mode="NULLABLE"),
        bigquery.SchemaField("category", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("sign_quality", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("description", "STRING", mode="NULLABLE"),
        bigquery.SchemaField("image_quality_notes", "STRING", mode="NULLABLE"),
    ],
}