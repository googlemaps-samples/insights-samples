import os
import json
import argparse
import random
import string
from google.cloud import bigquery
from google.cloud import storage

# Default configuration
DATASET_ID = "imagery_insights_sample_dataset___us"
TABLE_ID = "cropped_observations_latest"
GCS_DESTINATION_FOLDER = "street_view_insights"
LIMIT_URLS = 10

def export_to_vertex_jsonl(project_id, table_path, bucket_name, gcs_folder, output_filename, include_labels, limit):
    """
    Queries BigQuery for image URLs and creates a JSONL file for Vertex AI Managed Datasets.
    """
    print(f"Querying BigQuery table: {table_path} with limit: {limit}")
    bq_client = bigquery.Client(project=project_id)

    limit_clause = f"LIMIT {limit}" if limit and limit > 0 else ""

    if include_labels:
        # Group by gcs_uri and collect unique labels for multi-label image classification
        query = f"""
            SELECT
                gcs_uri,
                ARRAY_AGG(DISTINCT asset_type IGNORE NULLS) as labels
            FROM {table_path}
            WHERE gcs_uri IS NOT NULL AND gcs_uri LIKE 'gs://%'
            GROUP BY gcs_uri
            {limit_clause}
        """
        print("Including labels (multi-label image classification format)...")
    else:
        # Just grab unique image URIs for an unlabelled dataset
        query = f"""
            SELECT DISTINCT gcs_uri
            FROM {table_path}
            WHERE gcs_uri IS NOT NULL AND gcs_uri LIKE 'gs://%'
            {limit_clause}
        """
        print("Extracting only image URIs (unlabeled dataset format)...")

    query_job = bq_client.query(query)
    results = query_job.result()

    print(f"Writing results to local file: {output_filename}")
    count = 0
    with open(output_filename, 'w') as f:
        for row in results:
            if include_labels:
                # Vertex AI multi-label image classification format
                annotations = [{"displayName": label} for label in row.labels if label]
                if not annotations:
                    continue # Skip images with no labels if we explicitly requested labels
                json_record = {
                    "imageGcsUri": row.gcs_uri,
                    "classificationAnnotations": annotations
                }
            else:
                # Vertex AI unlabeled image format
                json_record = {
                    "imageGcsUri": row.gcs_uri
                }
            f.write(json.dumps(json_record) + "\n")
            count += 1

    print(f"Successfully wrote {count} records to {output_filename}")

    if count == 0:
        print("No records found. Exiting without uploading.")
        return

    # Upload to GCS
    destination_blob_name = f"{gcs_folder}/{output_filename}" if gcs_folder else output_filename
    print(f"Uploading {output_filename} to gs://{bucket_name}/{destination_blob_name} ...")

    storage_client = storage.Client(project=project_id)
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(destination_blob_name)

    blob.upload_from_filename(output_filename)

    print(f"Upload complete!")
    print(f"GCS URI: gs://{bucket_name}/{destination_blob_name}")
    print("You can now use this URI to import data into a Managed Dataset in Vertex AI.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export image URLs from BigQuery to a JSONL file for Vertex AI.")
    parser.add_argument("--project_id", type=str, required=True, help="Google Cloud Project ID")
    parser.add_argument("--table_id", type=str, default=TABLE_ID, help="BigQuery Table ID")
    parser.add_argument("--dataset_id", type=str, default=DATASET_ID, help="BigQuery Dataset ID")
    parser.add_argument("--bucket_name", type=str, required=True, help="Destination GCS Bucket Name")
    parser.add_argument("--gcs_folder", type=str, default=GCS_DESTINATION_FOLDER, help="Destination GCS Folder Path")
    parser.add_argument("--limit", type=int, default=LIMIT_URLS, help="Maximum number of URLs to fetch")
    parser.add_argument("--include_labels", action="store_true", help="Include asset_class as labels in Vertex AI Multi-Label Classification format.")

    args = parser.parse_args()

    # Construct dynamic output filename: dataset_limit_random4.jsonl
    random_suffix = ''.join(random.choices(string.ascii_lowercase, k=4))
    table_path = f"`{args.project_id}`.`{args.dataset_id}`.`{args.table_id}`"
    out_file = f"{args.dataset_id}_{args.limit}_{random_suffix}.jsonl"

    export_to_vertex_jsonl(
        project_id=args.project_id,
        table_path=table_path,
        bucket_name=args.bucket_name,
        gcs_folder=args.gcs_folder,
        output_filename=out_file,
        include_labels=args.include_labels,
        limit=args.limit
    )
