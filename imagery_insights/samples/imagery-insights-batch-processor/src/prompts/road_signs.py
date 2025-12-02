from google.cloud import bigquery

PROMPT = """Classify the road sign in this image into one of the following categories:
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
    bigquery.SchemaField("category", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("sign_quality", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("description", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("image_quality_notes", "STRING", mode="NULLABLE"),
]