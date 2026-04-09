# Copyright 2025 Google LLC
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

import requests
import json
import time
from datetime import datetime
import sys
import traceback
import os
import subprocess
import re
import argparse
import csv
import random
import string
import yaml

# --- Configuration ---

# API Configuration (from your curl example)
# Ensure your project ID is correctly set here if it differs from the URL
# The selectedRouteId will be appended as a query parameter

# --- Custom Exception ---
class TokenGenerationError(Exception):
    """Custom exception for gcloud token generation failures."""
    pass

class APIRequestError(Exception):
    """Custom exception for API request failures."""
    pass

# --- Global Variables ---
LOG_FILE = "route_creator_log.txt"

# --- Logging Function ---
def write_log(message):
    """Writes a message to the log file with a timestamp."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {message}\n"
    print(log_entry.strip()) # Also print to console
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(log_entry)

# --- Get gcloud Access Token ---
def get_gcloud_token():
    """Fetches an access token using gcloud."""
    try:
        # Ensure gcloud is in the PATH or provide full path
        # Using shell=True can be a security risk if command is from untrusted input,
        # but here it's a fixed command. For production, consider alternatives if concerned.
        # Splitting the command into a list is generally safer if shell=False can be used.
        command = "gcloud auth application-default print-access-token"
        write_log("Attempting to fetch gcloud access token...")
        process = subprocess.run(command, shell=True, capture_output=True, text=True, check=False)
        
        if process.returncode == 0:
            token = process.stdout.strip()
            if not token:
                write_log("Error: gcloud command ran but produced an empty token.")
                raise TokenGenerationError("gcloud produced an empty token.")
            write_log("Successfully fetched gcloud access token.")
            return token
        else:
            error_message = f"gcloud command failed with return code {process.returncode}.\n" \
                            f"Stderr: {process.stderr.strip()}"
            write_log(error_message)
            raise TokenGenerationError(error_message)
    except FileNotFoundError:
        write_log("Error: gcloud command not found. Ensure gcloud SDK is installed and in your PATH.")
        raise TokenGenerationError("gcloud command not found.")
    except Exception as e:
        write_log(f"An unexpected error occurred during token generation: {e}")
        raise TokenGenerationError(f"Unexpected error during token generation: {e}")


# --- File Parsing ---
def load_config(filepath="config.yaml"):
    """Loads the configuration from a YAML file."""
    try:
        with open(filepath, 'r') as f:
            config = yaml.safe_load(f)
        return config
    except FileNotFoundError:
        write_log(f"Error: Configuration file '{filepath}' not found.")
        return None
    except yaml.YAMLError as e:
        write_log(f"Error parsing YAML file '{filepath}': {e}")
        return None

def parse_coordinate_file(filepath, config):
    """Parses the CSV file based on the configuration."""
    parsed_data = []
    csv_format = config.get("csv_format", {})
    coord_regex = re.compile(r"\(\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)\s*\)")

    with open(filepath, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames
        
        # Determine which coordinate format to use based on headers
        use_combined = False
        use_separate = False

        if "combined_coordinates" in csv_format:
            combined_cols = csv_format["combined_coordinates"]
            if combined_cols["origin_coord_column"] in headers and combined_cols["destination_coord_column"] in headers:
                use_combined = True
        
        if not use_combined and "separate_coordinates" in csv_format:
            separate_cols = csv_format["separate_coordinates"]
            if all(col in headers for col in [separate_cols["origin_lat_column"], separate_cols["origin_lon_column"], separate_cols["destination_lat_column"], separate_cols["destination_lon_column"]]):
                use_separate = True

        if not use_combined and not use_separate:
            write_log("Error: CSV headers do not match any coordinate format in the config file.")
            return None

        for line_num, row in enumerate(reader, 2):
            try:
                display_name_col = csv_format.get("segment_name_column")
                display_name = row.get(display_name_col) if display_name_col else None

                if use_combined:
                    combined_config = csv_format["combined_coordinates"]
                    origin_str = row[combined_config["origin_coord_column"]]
                    dest_str = row[combined_config["destination_coord_column"]]
                    
                    origin_match = coord_regex.search(origin_str)
                    dest_match = coord_regex.search(dest_str)

                    if origin_match and dest_match:
                        origin_lat = float(origin_match.group(1))
                        origin_lon = float(origin_match.group(2))
                        dest_lat = float(dest_match.group(1))
                        dest_lon = float(dest_match.group(2))
                    else:
                        raise ValueError("Could not parse combined coordinates.")

                elif use_separate:
                    separate_config = csv_format["separate_coordinates"]
                    origin_lat = float(row[separate_config["origin_lat_column"]])
                    origin_lon = float(row[separate_config["origin_lon_column"]])
                    dest_lat = float(row[separate_config["destination_lat_column"]])
                    dest_lon = float(row[separate_config["destination_lon_column"]])
                
                parsed_data.append(((origin_lat, origin_lon), (dest_lat, dest_lon), display_name))

            except (ValueError, KeyError) as e:
                write_log(f"Warning: Skipping row {line_num} due to error: {e}. Row: {row}")
            except Exception as e:
                write_log(f"An unexpected error occurred at row {line_num}: {e}. Row: {row}")

    return parsed_data


# --- Create Route Segment ---
def create_route_segment(token, origin, destination, display_name, route_id_counter, google_project_id, config):
    """Makes the API call to create a single route segment."""
    prefix = config.get("route_name_prefix", "")
    if display_name:
        # Format display name: lowercase, replace spaces with hyphens
        route_name = display_name.lower().replace(' ', '-')
        # Remove any characters that are not letters, numbers, or hyphens
        route_name = re.sub(r'[^a-z0-9-]', '', route_name)
        selected_route_id = f"{prefix}{route_name}-{route_id_counter}"
    else:
        # Fallback to the original naming scheme
        selected_route_id = f"{prefix}salt-lake-city-{route_id_counter}"

    url = f"https://roads.googleapis.com/selection/v1/projects/{google_project_id}/selectedRoutes?selectedRouteId={selected_route_id}"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Goog-User-Project": google_project_id,
        "Content-Type": "application/json"
    }
    
    payload = {
        "dynamic_route": {
            "origin": {"latitude": origin[0], "longitude": origin[1]},
            "destination": {"latitude": destination[0], "longitude": destination[1]}
        }
    }
    
    write_log(f"Attempting to create route: {selected_route_id} with Origin: {origin}, Dest: {destination}")
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        
        # Check API documentation for expected success codes (e.g., 200, 201)
        # For creating a resource, 201 Created is common, but 200 OK might also be used.
        if response.status_code in [200, 201]: 
            write_log(f"Successfully created route: {selected_route_id}. Status: {response.status_code}")
            # write_log(f"Response: {response.text[:200]}...") # Log part of the response if needed
            return True
        else:
            error_detail = f"Failed to create route {selected_route_id}. Status: {response.status_code}.\n" \
                           f"URL: {url}\n" \
                           f"Payload: {json.dumps(payload, indent=2)}\n" \
                           f"Response: {response.text[:1000]}" # Log more of the error response and payload
            write_log(error_detail)
            return False # Indicate failure for this specific route
            
    except requests.exceptions.RequestException as e:
        write_log(f"RequestException for route {selected_route_id}: {e}")
        return False # Indicate failure for this specific route
    except Exception as e:
        write_log(f"Unexpected error for route {selected_route_id}: {e}")
        return False


# --- Main Script Logic ---
def main_route_creator(input_filepath, config_filepath):
    """Main function to orchestrate route creation."""
    write_log("Route Creator Script started.")

    config = load_config(config_filepath)
    if not config:
        sys.exit(1)

    google_project_id = config.get("google_project_id")
    if not google_project_id:
        write_log("Error: 'google_project_id' not found in config.")
        sys.exit(1)

    log_file = config.get("log_file", "route_creator_log.txt")
    max_routes = config.get("max_routes_to_create", 100)

    # Initialize/clear log file at start
    with open(log_file, 'w', encoding='utf-8') as f:
        f.write("")

    parsed_data = parse_coordinate_file(input_filepath, config)
    if parsed_data is None:
        write_log("Exiting due to error in parsing the input file.")
        sys.exit(1)
        
    if not parsed_data:
        write_log("No data found in the input file. Exiting.")
        return

    routes_created_count = 0
    routes_attempted_count = 0
    
    for origin, destination, display_name in parsed_data:
        if routes_created_count >= max_routes:
            write_log(f"Reached maximum of {max_routes} routes to create. Stopping.")
            break
        
        routes_attempted_count += 1
        
        try:
            current_token = get_gcloud_token()
        except TokenGenerationError:
            write_log("Failed to obtain gcloud token. Skipping further route creations.")
            break
            
        if create_route_segment(current_token, origin, destination, display_name, routes_attempted_count, google_project_id, config):
            routes_created_count += 1
        
        time.sleep(0.2)

    write_log("Route Creator Script finished.")
    write_log(f"Total entries processed: {routes_attempted_count} (out of {len(parsed_data)} available).")
    write_log(f"Total routes successfully created: {routes_created_count}.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create Google Roads routes from a coordinate file.")
    parser.add_argument("input_file", help="Path to the input CSV file.")
    parser.add_argument("--config", default="config.yaml", help="Path to the configuration file.")
    args = parser.parse_args()

    try:
        main_route_creator(args.input_file, args.config)
    except Exception as e: # Catch-all for any unhandled exceptions in main logic
        log_file_path = os.path.abspath(LOG_FILE)
        error_name = e.__class__.__name__
        write_log(f"CRITICAL SCRIPT ERROR ({error_name}): {e}")
        write_log(f"See stack trace below. Also check log file: {log_file_path}")
        
        print("\n" + "="*20 + f" CRITICAL SCRIPT ERROR - {error_name} - STACK TRACE " + "="*20, file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        print("="* (42 + len(error_name) + 18) + "\n", file=sys.stderr) # Adjust length of separator
        sys.exit(1)
