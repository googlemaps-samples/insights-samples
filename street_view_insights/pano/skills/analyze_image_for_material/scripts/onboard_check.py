#!/usr/bin/env python3
# Copyright 2026 Google LLC
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

import os
import sys

def check_package(package_name):
    try:
        __import__(package_name)
        return True
    except ImportError:
        return False

def check_table_exists(client_bq, project_id, dataset, table_name) -> bool:
    """Check if a table or view exists in the BigQuery dataset."""
    from google.cloud import bigquery
    query = f"""
    SELECT table_name 
    FROM `{project_id}`.`{dataset}`.INFORMATION_SCHEMA.TABLES 
    WHERE table_name = @table_name
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("table_name", "STRING", table_name)]
    )
    try:
        rows = list(client_bq.query(query, job_config=job_config).result())
        return len(rows) > 0
    except Exception:
        return False

def main():
    print("=== ONBOARDING SYSTEM & CONFIGURATION CHECK ===")
    
    # 1. Check Python Dependencies
    required_packages = {
        "google.genai": "google-genai",
        "google.cloud.bigquery": "google-cloud-bigquery",
        "PIL": "pillow"
    }
    
    print("\n[1] Checking Python package dependencies...")
    missing_packages = []
    for module, pip_name in required_packages.items():
        if check_package(module):
            print(f"  ✓ {pip_name} is installed.")
        else:
            print(f"  ✗ {pip_name} is missing!")
            missing_packages.append(pip_name)
            
    if missing_packages:
        print(f"\nError: Missing packages. Please install them using:\n  pip install {' '.join(missing_packages)}")
        sys.exit(1)
        
    # 2. Check GCP Authentication & Project Configurations
    print("\n[2] Checking Google Cloud Project parameters...")
    
    # Try to resolve project from environment or BigQuery default credentials
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    if not project:
        try:
            from google.cloud import bigquery
            client_bq = bigquery.Client()
            project = client_bq.project
        except Exception:
            pass
            
    dataset = os.getenv("BIGQUERY_DATASET", "home_depot_full_scene")
    tracks_table = os.getenv("BIGQUERY_TRACKS_TABLE", "tracks")
    urls_table = os.getenv("BIGQUERY_URLS_TABLE", "urls_new")
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    
    if not project:
        print("  ✗ Could not auto-resolve Google Cloud project ID from credentials or environment!")
        print("    Please set GOOGLE_CLOUD_PROJECT or authenticate using 'gcloud auth application-default login'.")
        sys.exit(1)
    else:
        print(f"  ✓ Target Project: {project} (Auto-resolved)")
        
    print(f"  ✓ Target Dataset: {dataset}")
    print(f"  - Vertex Region:  {location}")
    
    # 3. Check BigQuery Access
    print("\n[3] Verifying BigQuery dataset and schema alignment...")
    try:
        from google.cloud import bigquery
        client_bq = bigquery.Client(project=project)
        
        # Test dataset access
        dataset_ref = client_bq.dataset(dataset)
        client_bq.get_dataset(dataset_ref)
        print(f"  ✓ Dataset '{dataset}' found.")
        
        # Detect Schema Style
        is_new_schema = check_table_exists(client_bq, project, dataset, "pano_observations_latest")
        
        if is_new_schema:
            print("  ✓ Detected Pano Observations schema style (New single-table view).")
            table_ref = dataset_ref.table("pano_observations_latest")
            table = client_bq.get_table(table_ref)
            cols = [f.name for f in table.schema]
            
            required_cols = ["capture_id", "observation_id", "capture_location", "gcs_uri"]
            missing = [c for c in required_cols if c not in cols]
            if not missing:
                print("  ✓ Table 'pano_observations_latest' schema aligns (capture_id, observation_id, capture_location, gcs_uri present).")
            else:
                print(f"  ✗ Table 'pano_observations_latest' is missing required columns: {missing}")
                sys.exit(1)
        else:
            print("  ✓ Detected Classic Tracks/URLs schema style.")
            # Test tracks table columns
            tracks_ref = dataset_ref.table(tracks_table)
            t_table = client_bq.get_table(tracks_ref)
            t_cols = [f.name for f in t_table.schema]
            required_tracks = ["trackId", "observationIds", "geometry"]
            missing_t = [c for c in required_tracks if c not in t_cols]
            if not missing_t:
                print(f"  ✓ Table '{tracks_table}' schema aligns (trackId, observationIds, geometry present).")
            else:
                print(f"  ✗ Table '{tracks_table}' is missing required columns: {missing_t}")
                sys.exit(1)
                
            # Test URLs table columns
            urls_ref = dataset_ref.table(urls_table)
            u_table = client_bq.get_table(urls_ref)
            u_cols = [f.name for f in u_table.schema]
            required_urls = ["observationId", "signedUrl"]
            missing_u = [c for c in required_urls if c not in u_cols]
            if not missing_u:
                print(f"  ✓ Table '{urls_table}' schema aligns (observationId, signedUrl present).")
            else:
                print(f"  ✗ Table '{urls_table}' is missing required columns: {missing_u}")
                sys.exit(1)
            
    except Exception as e:
        print(f"  ✗ BigQuery verification failed: {e}")
        print("  Please check that application default credentials are configured correctly.")
        sys.exit(1)
        
    # 4. Check Vertex AI Client Initialization
    print("\n[4] Verifying Vertex AI connection & model availability...")
    try:
        from google import genai
        client_genai = genai.Client(vertexai=True, project=project, location=location)
        client_genai.models.generate_content(
            model="gemini-2.5-flash",
            contents="hello",
        )
        print("  ✓ Vertex AI Client initialized and model is responsive.")
    except Exception as e:
        print(f"  ✗ Vertex AI verification failed: {e}")
        print("  Verify you have the IAM role 'roles/aiplatform.user' on this project.")
        sys.exit(1)
        
    print("\n🎉 ONBOARDING VERIFICATION SUCCESSFUL! Project is fully ready to run the skill.")

if __name__ == "__main__":
    main()
