#!/bin/bash

set -euo pipefail

. ./services/auth.sh
. ./services/roads_selection.sh
. ./services/analyticshub_v1.sh

# Displays usage information for the script.
usage() {
    echo "Usage: $0 <command> [arguments...]"
    echo
    echo "Available commands:"
    echo "  rmi_exchange_get <RMI_PROJECT_ID> <LOCATION>"
    echo "    Finds the RMI data exchange for a given project and location."
    echo
    echo "  rmi_listing_list <RMI_PROJECT_ID> <LOCATION>"
    echo "    Lists the available datasets (listings) in the RMI data exchange."
    echo
    echo "  rmi_subscribe_bigquery <RMI_PROJECT_ID> <LOCATION> <BQ_PROJECT_ID> <BQ_DATASET_ID> [BODY_FILE]"
    echo "    Subscribes to a BigQuery listing in the RMI data exchange."
    echo
    echo "  help"
    echo "    Displays this help message."
}

# The project ID of the Google owned "Roads Management Insights" project.
PROJECT_GOOGLE_RMI=maps-platform-roads-management

## 
## BigQuery Sharing (formaly known as Analytics Hub) 
##

# Retrieves the RMI data exchange for a specific project and location.
#
# Arguments:
#   $1: The RMI project ID.
#   $2: The location (e.g., `us`).
#
# Outputs:
#   A JSON object representing the data exchange.
function rmi_exchange_get {
    local RMI_PROJECT_ID=$1
    local LOCATION=$2

    local RMI_PROJECT_NUMBER
    RMI_PROJECT_NUMBER=$(gcloud --format 'value(projectNumber)' projects describe "$RMI_PROJECT_ID")
    
    exchange_list "$PROJECT_GOOGLE_RMI" "$LOCATION" | jq --arg p "$RMI_PROJECT_NUMBER" '.dataExchanges[] | select(.name| contains($p))'
}

# Lists all available listings (datasets) within the RMI data exchange for a given project and location.
#
# Arguments:
#   $1: The RMI project ID.
#   $2: The location.
#
# Outputs:
#   A JSON array of listing objects.
function rmi_listing_list {
    local RMI_PROJECT_ID=$1
    local LOCATION=$2

    local RMI_PROJECT_NUMBER
    RMI_PROJECT_NUMBER=$(gcloud --format 'value(projectNumber)' projects describe "$RMI_PROJECT_ID")
    
    local EXCHANGE
    EXCHANGE=$(exchange_list "$PROJECT_GOOGLE_RMI" "$LOCATION" | jq -r --arg p "$RMI_PROJECT_NUMBER" '.dataExchanges[] | select(.name| contains($p)) | .name | split("/")[-1]')

    listings_list "$PROJECT_GOOGLE_RMI" "$LOCATION" "$EXCHANGE" | jq
}

# Filters the listings from rmi_listing_list to show only BigQuery datasets.
#
# Arguments:
#   $1: The RMI project ID.
#   $2: The location.
#
# Outputs:
#   A JSON array of BigQuery listing objects.
function rmi_listings_bigquery {
    local RMI_PROJECT_ID=$1
    local LOCATION=$2

    rmi_listing_list "$RMI_PROJECT_ID" "$LOCATION"  | jq '.listings[] | select(.resourceType=="BIGQUERY_DATASET")'
}

# Filters the listings from rmi_listing_list to show only Pub/Sub topics.
#
# Arguments:
#   $1: The RMI project ID.
#   $2: The location.
#
# Outputs:
#   A JSON array of Pub/Sub listing objects.
function rmi_listings_pubsub {
    local RMI_PROJECT_ID=$1
    local LOCATION=$2

    rmi_listing_list "$RMI_PROJECT_ID" "$LOCATION"  | jq '.listings[] | select(.resourceType=="PUBSUB_TOPIC")'
}

# Lists the subscriptions for BigQuery listings in the RMI data exchange.
#
# Arguments:
#   $1: The RMI project ID.
#   $2: The location.
#
# Outputs:
#   A JSON array of subscription objects.
function rmi_subscriptions_bigquery {
    local RMI_PROJECT_ID=$1
    local LOCATION=$2

    local NAME
    NAME=$(rmi_listings_bigquery "$RMI_PROJECT_ID" "$LOCATION" | jq -r '.name')

    listings_subscriptions_list_byname "$RMI_PROJECT_ID" "$NAME" | jq
}

# Subscribes to a BigQuery listing in the RMI data exchange, creating a linked dataset in the user's project.
#
# This function provides flexibility for the request body. If a file path is provided as the 5th argument,
# its content will be used as the request body. Otherwise, a default body will be generated.
#
# Arguments:
#   $1: The RMI project ID.
#   $2: The location.
#   $3: The BigQuery project ID where the linked dataset will be created.
#   $4: The ID for the new BigQuery dataset.
#   $5: (Optional) Path to a JSON file with the request body.
#
# Outputs:
#   The JSON response from the API call.
function rmi_subscribe_bigquery {
    local RMI_PROJECT_ID=$1
    local LOCATION=$2
    local GCP_PROJECT_ID=$3
    local BQ_DATASET=$4
    local BODY_FILE_ARG=${5:-}

    local JSON_INFO
    JSON_INFO=$(rmi_listings_bigquery "$RMI_PROJECT_ID" "$LOCATION")
    
    local LISTING_NAME
    LISTING_NAME=$(echo "$JSON_INFO" | jq -r '.name')
    
    local DISPLAY_NAME
    DISPLAY_NAME=$(echo "$JSON_INFO" | jq -r '.displayName')

    local EXCHANGE
    EXCHANGE=$(echo "$LISTING_NAME" | cut -d'/' -f6)
    
    local LISTING
    LISTING=$(echo "$LISTING_NAME" | cut -d'/' -f8)

    local BODY_FILE
    local IS_TEMP_FILE=false

    if [[ -n "$BODY_FILE_ARG" ]]; then
        BODY_FILE="$BODY_FILE_ARG"
    else
        BODY_FILE=$(mktemp)
        IS_TEMP_FILE=true
        
        # Create the default JSON body
        cat > "$BODY_FILE" <<EOM
{
  "destinationDataset": {
    "datasetReference":{
      "projectId": "$GCP_PROJECT_ID",
      "datasetId": "$BQ_DATASET"
    },
    "friendlyName":"$DISPLAY_NAME",
    "description":"Roads Management Insights - $DISPLAY_NAME - subscribed",
    "labels":{
        "subscribed_by":"$(whoami)"
    },
    "location":"$LOCATION"
  }
}
EOM
    fi

    #cat $BODY_FILE
    # Call the service script function
    listing_subscribe "$PROJECT_GOOGLE_RMI" "$LOCATION" "$EXCHANGE" "$LISTING" "$BODY_FILE" "$RMI_PROJECT_ID"

    if [[ "$IS_TEMP_FILE" == true ]]; then
        rm -f "$BODY_FILE"
    fi
}

# Retrieves the IAM policy for each listing in the RMI data exchange.
#
# Arguments:
#   $1: The RMI project ID.
#   $2: The location.
#
# Outputs:
#   The IAM policy for each listing as a JSON object.
function rmi_listing_iam_policy_get {
    local RMI_PROJECT_ID=$1
    local LOCATION=$2

    rmi_listing_list "$RMI_PROJECT_ID" "$LOCATION" | jq -c -r '.listings[].name' | while read -r L; do
        echo "$L"
        listings_get_iam_policy_byname "$RMI_PROJECT_ID" "$L" | jq
    done
}



# Main execution block
if [[ $# -eq 0 || "$1" == "help" ]]; then
    usage
    exit
else 
    "$@"
fi
