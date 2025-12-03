import os
import sys
import requests
from google.cloud import bigquery

# Add the parent directory to the Python path to allow importing 'config'
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    GCP_PROJECT,
    BIGQUERY_SOURCE_DATASET,
    BIGQUERY_SOURCE_TABLE,
    SERVICE_URL,
)


def get_test_data():
    """Fetches a single row of test data from the source BigQuery table."""
    client = bigquery.Client(project=GCP_PROJECT)
    query = f"""
        SELECT
            t0.asset_id,
            ARRAY_AGG(STRUCT(t0.observation_id, t0.gcs_uri)) AS observations
        FROM
            `{GCP_PROJECT}.{BIGQUERY_SOURCE_DATASET}.{BIGQUERY_SOURCE_TABLE}` AS t0
        GROUP BY
            t0.asset_id
        LIMIT 1
    """
    rows = client.query(query).result()
    for row in rows:
        print("--- BigQuery Row ---")
        print(row)
        print("--- End BigQuery Row ---")
    return None


def test_process_endpoint():
    """Tests the /process endpoint of the Cloud Run service."""
    test_data = get_test_data()
    if not test_data:
        print("Could not fetch test data from BigQuery.")
        return

    response = requests.post(
        f"{SERVICE_URL}/process",
        json=test_data,
        headers={"Content-Type": "application/json"},
    )

    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.text}")


if __name__ == "__main__":
    test_process_endpoint()