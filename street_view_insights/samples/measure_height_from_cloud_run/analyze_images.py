# Copyright 2023 Google LLC
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

# -*- coding: utf-8 -*-
"""
# Image Classification Service with Gemini 2.5 Flash

This script provides a web service for classifying images from GCS URIs using
the Gemini 2.5 Flash model via Google Cloud's Vertex AI. It is designed to be
deployed as a container on Google Cloud Run.
"""

# Import required libraries
import json
import os
from flask import Flask, jsonify, request
from google.cloud import bigquery
import vertexai
from vertexai.generative_models import GenerativeModel, Part

# --- Configuration ---
# IMPORTANT: Replace with your actual GCP Project ID and Region
PROJECT_ID = 'sarthaks-lab'
REGION = 'us-central1'

# Initialize Flask app
app = Flask(__name__)

# --- BigQuery Configuration ---
BIGQUERY_SQL_QUERY = """
SELECT
  *
FROM
  `sarthaks-lab.imagery_insights___preview___us.latest_observations`
  WHERE asset_type = "ASSET_CLASS_UTILITY_POLE"

LIMIT 10;
"""

def measure_height_with_gemini(gcs_uri: str, prompt: str) -> str:
    """
    Measures the height of a pole in an image using the Gemini 1.5 Pro model.
    """
    try:
        model = GenerativeModel("gemini-2.5-pro")
        image_part = Part.from_uri(uri=gcs_uri, mime_type="image/jpeg")
        responses = model.generate_content([image_part, prompt],
                                           generation_config={
                                               "temperature": 0.0,
                                           },
                                           tools=[
                                               vertexai.generative_models.Tool.from_google_search_retrieval(
                                                   vertexai.generative_models.grounding.GoogleSearchRetrieval()
                                               )
                                           ]
                                           )
        return responses.text
    except Exception as e:
        app.logger.error(f"Error measuring height from URI {gcs_uri}: {e}")
        return "Height measurement failed."

@app.route('/', methods=['POST'])
def main():
    """
    Main endpoint to execute the BigQuery query, extract URIs,
    and measure pole height using Gemini 2.5 Pro.
    """
    # Initialize Vertex AI
    vertexai.init(project=PROJECT_ID, location=REGION)

    # Execute BigQuery Query
    try:
        bigquery_client = bigquery.Client(project=PROJECT_ID)
        query_job = bigquery_client.query(BIGQUERY_SQL_QUERY)
        query_response_data = [dict(row) for row in query_job]
        gcs_uris = [item.get("gcs_uri") for item in query_response_data if item.get("gcs_uri")]
    except Exception as e:
        app.logger.error(f"Error executing BigQuery query: {e}")
        return jsonify({"error": "BigQuery query failed"}), 500

    # Height Measurement Process
    measurement_results = []
    if not gcs_uris:
        return jsonify({"message": "No GCS URIs found to measure."})

    # Get prompt from request, with a default value
    data = request.get_json()
    prompt = data.get("prompt", """
Follow these steps to analyze the image and calculate the height of the utility pole:
1.  Identify the utility pole in the image.
2.  Find a reference object in the image with a known or easily estimable real-world size (e.g., a car, a person, a standard door).
3.  Measure the height of the utility pole in pixels.
4.  Measure the height of the reference object in pixels.
5.  State the estimated real-world height of the reference object.
6.  Calculate the real-world height of the utility pole using the pixel ratio and the reference object's height.
7.  Provide the final calculated height of the pole in feet.
""")

    for uri in gcs_uris:
        result = measure_height_with_gemini(uri, prompt)
        measurement_results.append({"gcs_uri": uri, "height_measurement": result})

    return jsonify(measurement_results)

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
