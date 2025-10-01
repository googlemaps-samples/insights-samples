# GCP Project Configuration
GCP_PROJECT = "sarthaks-lab"
LOCATION = "us-central1"

# BigQuery Configuration
BIGQUERY_RESULTS_DATASET = "imagery_insights_analysis"
BIGQUERY_RESULTS_TABLE = "utility_pole_evaluations"
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
  t1.asset_type = 'ASSET_CLASS_UTILITY_POLE'
GROUP BY
  t1.asset_id,
  t1.location
"""

# Cloud Tasks Configuration
TASK_QUEUE_PREFIX = "image-analysis-queue-"

# Cloud Run Configuration
BATCH_SIZE = 100
STATE_FILE = "populate_state.json"
SERVICE_URL = "https://analyze-volume-images-635092392839.us-central1.run.app" # Replace with your main service URL after deployment
POPULATE_SERVICE_URL = "https://populate-tasks-635092392839.us-central1.run.app" # Replace with your populate service URL after deployment
SERVICE_ACCOUNT_EMAIL = "635092392839-compute@developer.gserviceaccount.com" # Replace with your service account email

# Gemini Model Prompt
GEMINI_PROMPT = """
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