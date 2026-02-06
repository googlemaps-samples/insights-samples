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
# Project Cloud Setup
#
# This script helps configure a Google Cloud project for accumulated data access.
# References: https://developers.google.com/maps/documentation/roads-management-insights/accumulated-data
###############################################################################

# Locate and source the bundled utility script
_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# This path works in the 'dist' directory structure
ANALYTICSHUB_UTIL="${_SCRIPT_DIR}/../clients/analyticshub_v1_util.sh"

if [[ -f "$ANALYTICSHUB_UTIL" ]]; then
    source "$ANALYTICSHUB_UTIL"
fi

# Displays usage information and available commands for the script.
usage() {
    echo "Usage: $0 <command> [args]"
    echo ""
    echo "Commands:"
    echo "  all <PROJECT_CLOUD_ID> [MEMBER]              Run setup and grant roles (e.g. user:email@addr)"
    echo "  step_enable_apis <PROJECT_CLOUD_ID>          Enable BigQuery, Analytics Hub, Pub/Sub"
    echo "  step_verify_apis <PROJECT_CLOUD_ID>          Verify APIs are enabled"
    echo "  step_configure_iam <PROJECT_CLOUD_ID> <MEMBER> Grant required roles to a member"
    echo ""
    echo "IAM Helpers (MEMBER format: user:EMAIL, serviceAccount:EMAIL, group:EMAIL):"
    echo "  grant_roles_to_user <PROJECT_CLOUD_ID> <EMAIL>"
    echo "  grant_roles_to_group <PROJECT_CLOUD_ID> <EMAIL>"
    echo "  grant_roles_to_service_account <PROJECT_CLOUD_ID> <EMAIL>"
    echo ""
    echo "Pub/Sub Helpers:"
    echo "  create_rmi_json_subscription <PROJECT_RMI_ID> <PROJECT_CLOUD_ID> [SUB_ID]"
    echo "  create_rmi_binary_subscription <PROJECT_RMI_ID> <PROJECT_CLOUD_ID> [SUB_ID]"
    echo ""
    echo "Analytics Hub Helpers:"
    echo "  subscribe_from_console_url <URL> <PROJECT_CLOUD_ID> [DATASET] [LOC]"
    echo "  subscribe_from_params <SRC_PROJ> <SRC_LOC> <SRC_EXCH> <PROJECT_CLOUD_ID> [DATASET] [LOC]"
}

# Enables the required Google Cloud APIs (BigQuery, Analytics Hub, Pub/Sub) for the data project.
step_enable_apis() {
    local project_id="${1:-${PROJECT_CLOUD_ID:-}}"
    if [[ -z "$project_id" ]]; then echo "Error: PROJECT_CLOUD_ID required"; exit 1; fi
    echo "Enabling APIs for $project_id..."
    gcloud services enable bigquery.googleapis.com --project "$project_id"
    gcloud services enable analyticshub.googleapis.com --project "$project_id"
    gcloud services enable pubsub.googleapis.com --project "$project_id"
    echo "APIs enabled."
}

# Verifies that the required APIs are successfully enabled in the project.
step_verify_apis() {
    local project_id="${1:-${PROJECT_CLOUD_ID:-}}"
    if [[ -z "$project_id" ]]; then echo "Error: PROJECT_CLOUD_ID required"; exit 1; fi
    echo "Verifying enabled APIs for $project_id..."
    gcloud services list --project "$project_id" --filter="config.name:bigquery.googleapis.com"
    gcloud services list --project "$project_id" --filter="config.name:analyticshub.googleapis.com"
    gcloud services list --project "$project_id" --filter="config.name:pubsub.googleapis.com"
}

# Internal helper to grant a specific IAM role to a member.
_grant_role() {
    local project_id="$1"
    local member="$2"
    local role="$3"
    echo "Granting $role to $member on project $project_id..."
    
    if ! gcloud projects add-iam-policy-binding "$project_id" --member="$member" --role="$role" --quiet > /dev/null 2> /tmp/gcloud_error.log; then
        local error_msg
        error_msg=$(cat /tmp/gcloud_error.log)
        if [[ "$error_msg" == *"PERMISSION_DENIED"* ]]; then
            echo "Error: Permission Denied while granting $role."
            echo "Your account may lack 'resourcemanager.projects.setIamPolicy' on project $project_id."
            echo "Please ask a Project Owner or IAM Admin to run this command for you:"
            echo "  gcloud projects add-iam-policy-binding $project_id --member='$member' --role='$role'"
            return 1
        else
            echo "Error: $error_msg"
            return 1
        fi
    fi
}

# Configures the necessary IAM roles for a member in the data project.
step_configure_iam() {
    local project_id="$1"
    local member="$2"
    if [[ -z "$project_id" || -z "$member" ]]; then echo "Usage: step_configure_iam <PROJECT_CLOUD_ID> <MEMBER>"; exit 1; fi

    echo "Configuring IAM roles for $member on $project_id..."
    local failed=0
    _grant_role "$project_id" "$member" "roles/analyticshub.subscriber" || failed=1
    _grant_role "$project_id" "$member" "roles/bigquery.user" || failed=1
    _grant_role "$project_id" "$member" "roles/pubsub.editor" || failed=1
    
    if [[ $failed -eq 1 ]]; then
        echo "IAM configuration partially or fully failed. See errors above."
        return 1
    fi
    echo "IAM configuration complete."
}

# Helper to grant roles specifically to a user account.
grant_roles_to_user() {
    step_configure_iam "$1" "user:$2"
}

# Helper to grant roles specifically to a Google Group.
grant_roles_to_group() {
    step_configure_iam "$1" "group:$2"
}

# Helper to grant roles specifically to a Service Account.
grant_roles_to_service_account() {
    step_configure_iam "$1" "serviceAccount:$2"
}

# Runs the complete setup pipeline sequentially.
run_all() {
    local project_cloud_id="${1:-}"
    local member="${2:-}" # Optional: user:email@example.com

    if [[ -z "$project_cloud_id" ]]; then
        usage
        exit 1
    fi

    echo "Configuring Data Project (Cloud): $project_cloud_id"
    step_enable_apis "$project_cloud_id"
    step_verify_apis "$project_cloud_id"
    
    if [[ -n "$member" ]]; then
        step_configure_iam "$project_cloud_id" "$member"
    else
        echo "----------------------------------------------------------------"
        echo "INFO: No member provided. To grant roles, run:"
        echo "  $0 step_configure_iam $project_cloud_id user:YOUR_EMAIL"
        echo "----------------------------------------------------------------"
    fi
    
    echo "Data Project Configuration Helper Complete."
}

# Internal function to handle subscription logic to an Analytics Hub data exchange.
_subscribe_to_exchange() {
    local exchange_path="$1"
    local project_cloud_id="$2"
    local dest_dataset="$3"
    local dest_location="$4"

    echo "Target Exchange: $exchange_path"
    
    if ! command -v analyticshub_v1_projects_locations_dataExchanges_listings_list &> /dev/null; then
        echo "Error: Analytics Hub client not found. Ensure you are running from the 'dist' folder."
        return 1
    fi

    echo "Fetching listings for exchange..."
    local listings_json
    listings_json=$(analyticshub_v1_projects_locations_dataExchanges_listings_list "$exchange_path" "" "" "$project_cloud_id")
    
    local listing_name
    listing_name=$(echo "$listings_json" | jq -r '.listings[0].name // empty')

    if [[ -z "$listing_name" ]]; then
        echo "Error: No listings found in this exchange."
        return 1
    fi

    echo "Found Listing: $listing_name"
    
    # Prepare Subscription Request
    local dest_ref
    dest_ref=$(create_destination_dataset_reference "$project_cloud_id" "$dest_dataset")
    local dest_ds
    dest_ds=$(create_destination_dataset "$dest_ref" "$dest_location")
    local sub_req
    sub_req=$(create_subscribe_listing_request "$dest_ds")

    echo "Subscribing to listing..."
    analyticshub_v1_projects_locations_dataExchanges_listings_subscribe "$listing_name" "$sub_req" "$project_cloud_id"
}

# Subscribes to a data exchange using a URL from the Google Cloud Console.
subscribe_from_console_url() {
    local url="$1"
    local project_cloud_id="$2"
    local dest_dataset="${3:-rmi_data_dataset}"
    local dest_location="${4:-us}"

    # Extract components from Console URL
    if [[ "$url" =~ projects/([^/]+)/locations/([^/]+)/dataExchanges/([^/]+) ]]; then
        local src_project="${BASH_REMATCH[1]}"
        local src_location="${BASH_REMATCH[2]}"
        local src_exchange="${BASH_REMATCH[3]}"
        local exchange_path="projects/$src_project/locations/$src_location/dataExchanges/$src_exchange"
        
        _subscribe_to_exchange "$exchange_path" "$project_cloud_id" "$dest_dataset" "$dest_location"
    else
        echo "Error: Could not parse Analytics Hub URL."
        echo "Expected format: https://console.cloud.google.com/bigquery/analytics-hub/exchanges/projects/.../locations/.../dataExchanges/..."
    fi
}

# Subscribes to a data exchange using explicit project, location, and exchange IDs.
subscribe_from_params() {
    local src_project="$1"
    local src_location="$2"
    local src_exchange="$3"
    local project_cloud_id="$4"
    local dest_dataset="${5:-rmi_data_dataset}"
    local dest_location="${6:-us}"

    local exchange_path="projects/$src_project/locations/$src_location/dataExchanges/$src_exchange"
    _subscribe_to_exchange "$exchange_path" "$project_cloud_id" "$dest_dataset" "$dest_location"
}

# Creates a Pub/Sub subscription to the RMI real-time topic in JSON format.
create_rmi_json_subscription() {
    local project_rmi_id="$1"
    local project_cloud_id="$2"
    local sub_id="${3:-rmi-real-time-json-sub}"

    # Get RMI project number
    local project_number
    project_number=$(gcloud projects describe "$project_rmi_id" --format="value(projectNumber)")
    
    local topic="projects/maps-platform-roads-management/topics/rmi-roadsinformation-$project_number-json"

    echo "Creating JSON subscription '$sub_id' in $project_cloud_id for topic $topic..."
    gcloud pubsub subscriptions create "$sub_id" --topic="$topic" --project="$project_cloud_id"
}

# Creates a Pub/Sub subscription to the RMI real-time topic in Binary (Proto) format.
create_rmi_binary_subscription() {
    local project_rmi_id="$1"
    local project_cloud_id="$2"
    local sub_id="${3:-rmi-real-time-sub}"

    # Get RMI project number
    local project_number
    project_number=$(gcloud projects describe "$project_rmi_id" --format="value(projectNumber)")
    
    local topic="projects/maps-platform-roads-management/topics/rmi-roadsinformation-$project_number"

    echo "Creating Binary subscription '$sub_id' in $project_cloud_id for topic $topic..."
    gcloud pubsub subscriptions create "$sub_id" --topic="$topic" --project="$project_cloud_id"
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
    step_*|subscribe_*|create_*|grant_*)
        cmd="$1"
        shift
        "$cmd" "$@"
        ;;
    *)
        usage
        exit 1
        ;;
esac
