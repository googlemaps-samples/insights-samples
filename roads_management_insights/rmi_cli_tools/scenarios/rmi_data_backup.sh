#!/bin/bash
set -euo pipefail
#
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


###############################################################################
# RMI Data Backup
#
# This script helps back up RMI-related data.
###############################################################################

# Locate and source the bundled utility script
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROADS_SELECTION_UTIL="${_SCRIPT_DIR}/../clients/roadsselection_v1_util.sh"

if [[ -f "$ROADS_SELECTION_UTIL" ]]; then
    source "$ROADS_SELECTION_UTIL"
fi

# Displays usage information and available commands for the backup script.
usage() {
    echo "Usage: $0 <command> [args]"
    echo ""
    echo "Commands:"
    echo "  all <PROJECT_RMI_ID> <PROJECT_CLOUD_ID> <SRC_DATASET_PROJ> <SRC_DATASET_NAME> [OUT_FILE]"
    echo "                                               Run full backup (Routes + BigQuery Copy)"
    echo "  step_initialize_backup <PROJECT_RMI_ID> <PROJECT_CLOUD_ID>"
    echo "                                               Show backup configuration"
    echo "  step_backup_routes <PROJECT_RMI_ID> [OUT_FILE]"
    echo "                                               Backup SelectedRoutes to a JSON file"
    echo "  step_backup_bq <PROJECT_CLOUD_ID> <SRC_PROJECT_ID> <SRC_DATASET_ID> [DEST_DATASET_ID]"
    echo "                                               Copy travel time data to a backup dataset"
    echo "  step_export_to_gcs <PROJECT_CLOUD_ID> <SRC_PROJECT_ID> <SRC_DATASET_ID> <GCS_PATH>"
    echo "                                               Export data to Cloud Storage as JSONL"
}

# Initializes and displays the backup configuration.
step_initialize_backup() {
    local project_rmi_id="${1:-${PROJECT_RMI_ID:-}}"
    local project_cloud_id="${2:-${PROJECT_CLOUD_ID:-}}"
    echo "RMI Data Backup Script"
    echo "Source (RMI Project): $project_rmi_id"
    echo "Destination (Cloud Project): $project_cloud_id"
}

# Backs up Routes of Interest (SelectedRoutes) to a local JSON file.
step_backup_routes() {
    local project_id="${1:-${PROJECT_RMI_ID:-}}"
    local output_file="${2:-selected_routes_backup.json}"
    if [[ -z "$project_id" ]]; then echo "Error: PROJECT_RMI_ID required"; exit 1; fi

    echo "Backing up SelectedRoutes for project $project_id to $output_file..."
    
    if ! command -v roadsselection_v1_projects_selectedRoutes_list_all &> /dev/null; then
        echo "Error: Roads Selection utility not found. Run bundle.sh first."
        return 1
    fi

    local parent="projects/$project_id"
    roadsselection_v1_projects_selectedRoutes_list_all "$parent" "1000" "$project_id" > "$output_file"
    
    local count
    count=$(wc -l < "$output_file")
    echo "Backup complete. $count routes saved to $output_file"
}

# Copies travel time data from a subscribed dataset to a new backup dataset in the cloud project.
step_backup_bq() {
    local project_cloud_id="${1:-${PROJECT_CLOUD_ID:-}}"
    local src_project_id="$2"
    local src_dataset_id="$3"
    local dest_dataset_id="${4:-rmi_backup}"

    if [[ -z "$project_cloud_id" || -z "$src_project_id" || -z "$src_dataset_id" ]]; then
        echo "Usage: step_backup_bq <PROJECT_CLOUD_ID> <SRC_PROJECT_ID> <SRC_DATASET_ID> [DEST_DATASET_ID]"
        exit 1
    fi

    echo "Backing up BigQuery data from $src_project_id.$src_dataset_id to $project_cloud_id.$dest_dataset_id..."

    # 1. Create the backup dataset if it doesn't exist
    echo "Ensuring dataset $dest_dataset_id exists in $project_cloud_id..."
    bq --project_id="$project_cloud_id" mk --dataset --if_exists=true "$dest_dataset_id"

    # 2. Copy tables
    local tables=("routes_status" "historical_travel_time" "recent_roads_data")
    for table in "${tables[@]}"; do
        echo "Copying $table..."
        bq --project_id="$project_cloud_id" query --use_legacy_sql=false \
            "CREATE OR REPLACE TABLE \`$project_cloud_id.$dest_dataset_id.$table\` AS SELECT * FROM \`$src_project_id.$src_dataset_id.$table\`"
    done

    echo "BigQuery backup complete."
}

# Exports travel time data from the subscribed dataset to Google Cloud Storage.
step_export_to_gcs() {
    local project_cloud_id="$1"
    local src_project_id="$2"
    local src_dataset_id="$3"
    local gcs_path="$4"

    if [[ -z "$project_cloud_id" || -z "$src_project_id" || -z "$src_dataset_id" || -z "$gcs_path" ]]; then
        echo "Usage: step_export_to_gcs <PROJECT_CLOUD_ID> <SRC_PROJECT_ID> <SRC_DATASET_ID> <GCS_PATH>"
        exit 1
    fi

    echo "Exporting BigQuery data from $src_project_id.$src_dataset_id to $gcs_path..."

    local tables=("routes_status" "historical_travel_time" "recent_roads_data")
    for table in "${tables[@]}"; do
        echo "Exporting $table..."
        bq --project_id="$project_cloud_id" extract --destination_format=NEWLINE_DELIMITED_JSON \
            "$src_project_id:$src_dataset_id.$table" "$gcs_path/${table}-*.json"
    done

    echo "GCS export complete."
}

# Executes the complete backup pipeline (Routes + BigQuery Copy).
run_all() {
    local project_rmi_id="${1:-}"
    local project_cloud_id="${2:-}"
    local src_dataset_proj="${3:-}"
    local src_dataset_name="${4:-}"
    local output_file="${5:-selected_routes_backup.json}"

    if [[ -z "$project_rmi_id" || -z "$project_cloud_id" || -z "$src_dataset_proj" || -z "$src_dataset_name" ]]; then
        usage
        exit 1
    fi

    step_initialize_backup "$project_rmi_id" "$project_cloud_id"
    step_backup_routes "$project_rmi_id" "$output_file"
    step_backup_bq "$project_cloud_id" "$src_dataset_proj" "$src_dataset_name"
}

# Command dispatcher
if [[ $# -eq 0 ]]; then
    usage
    exit 0
fi

case "$1" in
    all)
        shift
        run_all "$@"
        ;;
    step_*)
        cmd="$1"
        shift
        "$cmd" "$@"
        ;;
    *)
        usage
        exit 1
        ;;
esac
