from google.cloud import bigquery

PROMPT = """You have been provided with an image file for analysis.

Your task is to determine the exact pixel resolution of this image (width and height) by writing and executing code. Follow these steps exactly:

Load the Image: Access the provided image file using a standard image processing library (e.g., Pillow/PIL or openCV2).
Extract Dimensions: Read the width and height (in pixels) directly from the loaded image object.
Format the Output: Construct a JSON object using the extracted width and height values. The keys must be width and height.
Your final output must be ONLY the calculated JSON object. Do not include any preceding text, explanation, or code block markers.
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
    bigquery.SchemaField("width", "INTEGER", mode="NULLABLE"),
    bigquery.SchemaField("height", "INTEGER", mode="NULLABLE"),
]