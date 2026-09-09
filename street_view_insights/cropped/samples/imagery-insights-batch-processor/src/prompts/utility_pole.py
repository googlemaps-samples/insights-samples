from google.cloud import bigquery

PROMPT = """
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

SCHEMA = [
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
]