#!/usr/bin/env python3
import sys
import os
os.environ["GOOGLE_CLOUD_PROJECT"] = "imagery-insights-sandbox"
from svi_geo.notebook_eval import evaluate_notebook_v2
from svi_geo import data, auth
from google.cloud import bigquery

if __name__ == "__main__":
    creds = auth.get_credentials()
    bq_client = bigquery.Client(project="imagery-insights-sandbox", credentials=creds)
    evaluate_notebook_v2(bq_client)
