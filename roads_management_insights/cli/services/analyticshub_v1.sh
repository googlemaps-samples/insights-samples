#!/bin/bash

set -euo pipefail

# Creates a new data exchange.
#
# Official Documentation:
# https://cloud.google.com/bigquery/docs/reference/analytics-hub/rest/v1/projects.locations.dataExchanges/create
#
# Arguments:
#   $1 (PROJECT):     Required. The project ID where the data exchange will be created.
#   $2 (LOCATION):     Required. The location for the new data exchange.
#   $3 (EXCHANGE_ID):  Required. The ID for the new data exchange.
#   $4 (BODY_FILE):    Required. Path to a JSON file with the request body defining the data exchange.
# Outputs:
#   Writes the API response JSON to stdout.
function exchange_create {
    local PROJECT=$1
    local LOCATION=$2
    local EXCHANGE_ID=$3
    local BODY_FILE=$4 # Path to a JSON file with the request body

    local PARENT="projects/${PROJECT}/locations/${LOCATION}"
    local URL="https://analyticshub.googleapis.com/v1/${PARENT}/dataExchanges?dataExchangeId=${EXCHANGE_ID}"
    
    local BODY
    BODY=$(cat "${BODY_FILE}")

    _call_api "POST" "${URL}" "${BODY}" "${PROJECT}"
}

# Deletes an existing data exchange.
#
# Official Documentation:
# https://cloud.google.com/bigquery/docs/reference/analytics-hub/rest/v1/projects.locations.dataExchanges/delete
#
# Arguments:
#   $1 (PROJECT):  Required. The project ID of the data exchange.
#   $2 (LOCATION):  Required. The location of the data exchange.
#   $3 (EXCHANGE):  Required. The ID of the data exchange to delete.
# Outputs:
#   Writes the API response JSON to stdout.
function exchange_delete {
    local PROJECT=$1
    local LOCATION=$2
    local EXCHANGE=$3

    local NAME="projects/${PROJECT}/locations/${LOCATION}/dataExchanges/${EXCHANGE}"
    local URL="https://analyticshub.googleapis.com/v1/${NAME}"

    _call_api "DELETE" "${URL}" "" "${PROJECT}"
}

# Gets the details of a data exchange.
#
# Official Documentation:
# https://cloud.google.com/bigquery/docs/reference/analytics-hub/rest/v1/projects.locations.dataExchanges/get
#
# Arguments:
#   $1 (PROJECT):  Required. The project ID of the data exchange.
#   $2 (LOCATION):  Required. The location of the data exchange.
#   $3 (EXCHANGE):  Required. The ID of the data exchange to get.
# Outputs:
#   Writes the API response JSON to stdout.
function exchange_get {
    local PROJECT=$1
    local LOCATION=$2
    local EXCHANGE=$3

    local NAME="projects/${PROJECT}/locations/${LOCATION}/dataExchanges/${EXCHANGE}"
    local URL="https://analyticshub.googleapis.com/v1/${NAME}"

    _call_api "GET" "${URL}" "" "${PROJECT}"
}

# Gets the IAM policy for a data exchange.
#
# Official Documentation:
# https://cloud.google.com/bigquery/docs/reference/analytics-hub/rest/v1/projects.locations.dataExchanges/getIamPolicy
#
# Arguments:
#   $1 (PROJECT):  Required. The project ID of the data exchange.
#   $2 (LOCATION):  Required. The location of the data exchange.
#   $3 (EXCHANGE):  Required. The ID of the data exchange.
# Outputs:
#   Writes the API response JSON to stdout.
function exchange_get_iam_policy {
    local PROJECT=$1
    local LOCATION=$2
    local EXCHANGE=$3

    local RESOURCE="projects/${PROJECT}/locations/${LOCATION}/dataExchanges/${EXCHANGE}"
    local URL="https://analyticshub.googleapis.com/v1/${RESOURCE}:getIamPolicy"

    local BODY="{}"

    _call_api "POST" "${URL}" "${BODY}" "${PROJECT}"
}

# Lists all data exchanges in a given project and location.
#
# Official Documentation:
# https://cloud.google.com/bigquery/docs/reference/analytics-hub/rest/v1/projects.locations.dataExchanges/list
#
# Arguments:
#   $1 (PROJECT): Required. The project ID to list data exchanges from.
#   $2 (LOCATION): Required. The location to list data exchanges in.
# Outputs:
#   Writes the API response JSON to stdout.
function exchange_list {
    local PROJECT=$1
    local LOCATION=$2

    local PARENT="projects/${PROJECT}/locations/${LOCATION}"
    local URL="https://analyticshub.googleapis.com/v1/${PARENT}/dataExchanges"
    
    _call_api "GET" "${URL}" "" "${PROJECT}"
}

# Updates an existing data exchange.
#
# Official Documentation:
# https://cloud.google.com/bigquery/docs/reference/analytics-hub/rest/v1/projects.locations.dataExchanges/patch
#
# Arguments:
#   $1 (PROJECT):     Required. The project ID of the data exchange.
#   $2 (LOCATION):     Required. The location of the data exchange.
#   $3 (EXCHANGE):     Required. The ID of the data exchange to update.
#   $4 (UPDATE_MASK):  Required. Comma-separated list of field names to update (e.g., "description,displayName").
#   $5 (BODY_FILE):    Required. Path to a JSON file with the request body containing the new data.
# Outputs:
#   Writes the API response JSON to stdout.
function exchange_patch {
    local PROJECT=$1
    local LOCATION=$2
    local EXCHANGE=$3
    local UPDATE_MASK=$4 # Comma-separated field names to update
    local BODY_FILE=$5   # Path to a JSON file with the request body

    local NAME="projects/${PROJECT}/locations/${LOCATION}/dataExchanges/${EXCHANGE}"
    local URL="https://analyticshub.googleapis.com/v1/${NAME}?updateMask=${UPDATE_MASK}"

    local BODY
    BODY=$(cat "${BODY_FILE}")

    _call_api "PATCH" "${URL}" "${BODY}" "${PROJECT}"
}

# Lists all subscriptions on a given Data Exchange.
#
# Official Documentation:
# https://cloud.google.com/bigquery/docs/reference/analytics-hub/rest/v1/projects.locations.dataExchanges/listSubscriptions
#
# Arguments:
#   $1 (PROJECT): Required. The project ID of the data exchange.
#   $2 (LOCATION): Required. The location of the data exchange.
#   $3 (EXCHANGE): Required. The ID of the data exchange.
# Outputs:
#   Writes the API response JSON to stdout.
function exchange_subscriptions_list {
    local PROJECT=$1
    local LOCATION=$2
    local EXCHANGE=$3

    local RESOURCE="projects/${PROJECT}/locations/${LOCATION}/dataExchanges/${EXCHANGE}"
    local URL="https://analyticshub.googleapis.com/v1/${RESOURCE}:listSubscriptions"

    _call_api "GET" "${URL}" "" "${PROJECT}"
}

# Creates a new listing.
#
# Official Documentation:
# https://cloud.google.com/bigquery/docs/reference/analytics-hub/rest/v1/projects.locations.dataExchanges.listings/create
#
# Arguments:
#   $1 (PROJECT):     Required. The project ID where the listing will be created.
#   $2 (LOCATION):     Required. The location for the new listing.
#   $3 (EXCHANGE):     Required. The ID of the data exchange to contain the listing.
#   $4 (LISTING_ID):   Required. The ID for the new listing.
#   $5 (BODY_FILE):    Required. Path to a JSON file with the request body defining the listing.
# Outputs:
#   Writes the API response JSON to stdout.
function listings_create {
    local PROJECT=$1
    local LOCATION=$2
    local EXCHANGE=$3
    local LISTING_ID=$4
    local BODY_FILE=$5 # Path to a JSON file with the request body

    local PARENT="projects/${PROJECT}/locations/${LOCATION}/dataExchanges/${EXCHANGE}"
    local URL="https://analyticshub.googleapis.com/v1/${PARENT}/listings?listingId=${LISTING_ID}"

    local BODY
    BODY=$(cat "${BODY_FILE}")

    _call_api "POST" "${URL}" "${BODY}" "${PROJECT}"
}

# Deletes a listing.
#
# Official Documentation:
# https://cloud.google.com/bigquery/docs/reference/analytics-hub/rest/v1/projects.locations.dataExchanges.listings/delete
#
# Arguments:
#   $1 (PROJECT):  Required. The project ID of the listing.
#   $2 (LOCATION):  Required. The location of the listing.
#   $3 (EXCHANGE):  Required. The ID of the data exchange containing the listing.
#   $4 (LISTING):   Required. The ID of the listing to delete.
# Outputs:
#   Writes the API response JSON to stdout.
function listings_delete {
    local PROJECT=$1
    local LOCATION=$2
    local EXCHANGE=$3
    local LISTING=$4

    local NAME="projects/${PROJECT}/locations/${LOCATION}/dataExchanges/${EXCHANGE}/listings/${LISTING}"
    local URL="https://analyticshub.googleapis.com/v1/${NAME}"

    _call_api "DELETE" "${URL}" "" "${PROJECT}"
}

# Gets the details of a listing.
#
# Official Documentation:
# https://cloud.google.com/bigquery/docs/reference/analytics-hub/rest/v1/projects.locations.dataExchanges.listings/get
#
# Arguments:
#   $1 (PROJECT): Required. The project ID of the listing.
#   $2 (LOCATION): Required. The location of the listing.
#   $3 (EXCHANGE): Required. The ID of the data exchange containing the listing.
#   $4 (LISTING):  Required. The ID of the listing to get.
# Outputs:
#   Writes the API response JSON to stdout.
function listings_get {
    local PROJECT=$1
    local LOCATION=$2
    local EXCHANGE=$3
    local LISTING=$4

    local NAME="projects/${PROJECT}/locations/${LOCATION}/dataExchanges/${EXCHANGE}/listings/${LISTING}"
    local URL="https://analyticshub.googleapis.com/v1/${NAME}"

    _call_api "GET" "${URL}" "" "${PROJECT}"
}

# Gets the IAM policy for a listing.
#
# Official Documentation:
# https://cloud.google.com/bigquery/docs/reference/analytics-hub/rest/v1/projects.locations.dataExchanges.listings/getIamPolicy
#
# Arguments:
#   $1 (PROJECT):  Required. The project ID of the listing.
#   $2 (LOCATION):  Required. The location of the listing.
#   $3 (EXCHANGE):  Required. The ID of the data exchange containing the listing.
#   $4 (LISTING):   Required. The ID of the listing.
# Outputs:
#   Writes the API response JSON to stdout.
function listings_get_iam_policy {
    local PROJECT=$1
    local LOCATION=$2
    local EXCHANGE=$3
    local LISTING=$4

    local RESOURCE="projects/${PROJECT}/locations/${LOCATION}/dataExchanges/${EXCHANGE}/listings/${LISTING}"
    local URL="https://analyticshub.googleapis.com/v1/${RESOURCE}:getIamPolicy"

    local BODY="{}"

    _call_api "POST" "${URL}" "${BODY}" "${PROJECT}"
}
function listings_get_iam_policy_byname {
    local PROJECT=$1
    local NAME=$2

    local RESOURCE=$NAME
    local URL="https://analyticshub.googleapis.com/v1/${RESOURCE}:getIamPolicy"

    local BODY="{}"

    _call_api "POST" "${URL}" "${BODY}" "${PROJECT}"
}
# Lists all listings in a given data exchange.
#
# Official Documentation:
# https://cloud.google.com/bigquery/docs/reference/analytics-hub/rest/v1/projects.locations.dataExchanges.listings/list
#
# Arguments:
#   $1 (PROJECT): Required. The project ID of the data exchange.
#   $2 (LOCATION): Required. The location of the data exchange.
#   $3 (EXCHANGE): Required. The ID of the data exchange to list listings from.
# Outputs:
#   Writes the API response JSON to stdout.
function listings_list {
    local PROJECT=$1
    local LOCATION=$2
    local EXCHANGE=$3

    local PARENT="projects/${PROJECT}/locations/${LOCATION}/dataExchanges/${EXCHANGE}"
    local URL="https://analyticshub.googleapis.com/v1/${PARENT}/listings"

    _call_api "GET" "${URL}" "" "${PROJECT}"
}

# Updates an existing listing.
#
# Official Documentation:
# https://cloud.google.com/bigquery/docs/reference/analytics-hub/rest/v1/projects.locations.dataExchanges.listings/patch
#
# Arguments:
#   $1 (PROJECT):     Required. The project ID of the listing.
#   $2 (LOCATION):     Required. The location of the listing.
#   $3 (EXCHANGE):     Required. The ID of the data exchange containing the listing.
#   $4 (LISTING):      Required. The ID of the listing to update.
#   $5 (UPDATE_MASK):  Required. Comma-separated list of field names to update.
#   $6 (BODY_FILE):    Required. Path to a JSON file with the request body containing the new data.
# Outputs:
#   Writes the API response JSON to stdout.
function listings_patch {
    local PROJECT=$1
    local LOCATION=$2
    local EXCHANGE=$3
    local LISTING=$4
    local UPDATE_MASK=$5 # Comma-separated field names to update
    local BODY_FILE=$6   # Path to a JSON file with the request body

    local NAME="projects/${PROJECT}/locations/${LOCATION}/dataExchanges/${EXCHANGE}/listings/${LISTING}"
    local URL="https://analyticshub.googleapis.com/v1/${NAME}?updateMask=${UPDATE_MASK}"

    local BODY
    BODY=$(cat "${BODY_FILE}")

    _call_api "PATCH" "${URL}" "${BODY}" "${PROJECT}"
}

# Lists all subscriptions on a given Listing.
#
# Official Documentation:
# https://cloud.google.com/bigquery/docs/reference/analytics-hub/rest/v1/projects.locations.dataExchanges.listings/listSubscriptions
#
# Arguments:
#   $1 (PROJECT): Required. The project ID of the listing.
#   $2 (LOCATION): Required. The location of the listing.
#   $3 (EXCHANGE): Required. The ID of the data exchange containing the listing.
#   $4 (LISTING):  Required. The ID of the listing.
# Outputs:
#   Writes the API response JSON to stdout.
function listings_subscriptions_list {
    local PROJECT=$1
    local LOCATION=$2
    local EXCHANGE=$3
    local LISTING=$4

    local RESOURCE="projects/${PROJECT}/locations/${LOCATION}/dataExchanges/${EXCHANGE}/listings/${LISTING}"
    local URL="https://analyticshub.googleapis.com/v1/${RESOURCE}:listSubscriptions"

    _call_api "GET" "${URL}" "" "${PROJECT}"
}

function listings_subscriptions_list_byname {
    local PROJECT=$1
    local NAME=$2

    local RESOURCE=$NAME
    local URL="https://analyticshub.googleapis.com/v1/${RESOURCE}:listSubscriptions"

    _call_api "GET" "${URL}" "" "${PROJECT}"
}
# Subscribes to a listing.
#
# Official Documentation:
# https://cloud.google.com/bigquery/docs/reference/analytics-hub/rest/v1/projects.locations.dataExchanges.listings/subscribe
#
# Arguments:
#   $1 (PROJECT):     Required. The project ID of the listing to subscribe to.
#   $2 (LOCATION):     Required. The location of the listing.
#   $3 (EXCHANGE):     Required. The ID of the data exchange containing the listing.
#   $4 (LISTING):      Required. The ID of the listing to subscribe to.
#   $5 (BODY_FILE):    Required. Path to a JSON file with the request body.
#   $6 (USER_PROJECT): Optional. The project ID to use for billing. Defaults to PROJECT.
# Outputs:
#   Writes the API response JSON to stdout.
function listing_subscribe {
    local PROJECT=$1
    local LOCATION=$2
    local EXCHANGE=$3
    local LISTING=$4
    local BODY_FILE=$5
    local USER_PROJECT=${6:-}
        
    local NAME="projects/${PROJECT}/locations/${LOCATION}/dataExchanges/${EXCHANGE}/listings/${LISTING}"
    local URL="https://analyticshub.googleapis.com/v1/${NAME}:subscribe"

    local BODY
    BODY=$(cat "${BODY_FILE}")

    local BILLING_PROJECT=${USER_PROJECT:-$PROJECT}

    _call_api "POST" "${URL}" "${BODY}" "${BILLING_PROJECT}"
}

# Deletes a subscription.
#
# Official Documentation:
# https://cloud.google.com/bigquery/docs/reference/analytics-hub/rest/v1/projects.locations.subscriptions/delete
#
# Arguments:
#   $1 (PROJECT):       Required. The project ID of the subscription.
#   $2 (LOCATION):      Required. The location of the subscription.
#   $3 (SUBSCRIPTION):  Required. The ID of the subscription to delete.
# Outputs:
#   Writes the API response JSON to stdout.
function subscriptions_delete {
    local PROJECT=$1
    local LOCATION=$2
    local SUBSCRIPTION=$3

    local NAME="projects/${PROJECT}/locations/${LOCATION}/subscriptions/${SUBSCRIPTION}"
    local URL="https://analyticshub.googleapis.com/v1/${NAME}"

    _call_api "DELETE" "${URL}" "" "${PROJECT}"
}

# Gets the details of a Subscription.
#
# Official Documentation:
# https://cloud.google.com/bigquery/docs/reference/analytics-hub/rest/v1/projects.locations.subscriptions/get
#
# Arguments:
#   $1 (PROJECT):       Required. The project ID of the subscription.
#   $2 (LOCATION):      Required. The location of the subscription.
#   $3 (SUBSCRIPTION):  Required. The ID of the subscription to get.
# Outputs:
#   Writes the API response JSON to stdout.
function subscriptions_get {
    local PROJECT=$1
    local LOCATION=$2
    local SUBSCRIPTION=$3

    local NAME="projects/${PROJECT}/locations/${LOCATION}/subscriptions/${SUBSCRIPTION}"
    local URL="https://analyticshub.googleapis.com/v1/${NAME}"

    _call_api "GET" "${URL}" "" "${PROJECT}"
}

# Lists all subscriptions in a given project and location.
#
# Official Documentation:
# https://cloud.google.com/bigquery/docs/reference/analytics-hub/rest/v1/projects.locations.subscriptions/list
#
# Arguments:
#   $1 (PROJECT):   Required. The project ID to list subscriptions from.
#   $2 (LOCATION):  Required. The location to list subscriptions in.
# Outputs:
#   Writes the API response JSON to stdout.
function subscriptions_list {
    local PROJECT=$1
    local LOCATION=$2

    local PARENT="projects/${PROJECT}/locations/${LOCATION}"
    local URL="https://analyticshub.googleapis.com/v1/${PARENT}/subscriptions"

    _call_api "GET" "${URL}" "" "${PROJECT}"
}

# Refreshes a Subscription to a Data Exchange.
#
# Official Documentation:
# https://cloud.google.com/bigquery/docs/reference/analytics-hub/rest/v1/projects.locations.subscriptions/refresh
#
# Arguments:
#   $1 (PROJECT):       Required. The project ID of the subscription.
#   $2 (LOCATION):      Required. The location of the subscription.
#   $3 (SUBSCRIPTION):  Required. The ID of the subscription to refresh.
# Outputs:
#   Writes the API response JSON to stdout.
function subscriptions_refresh {
    local PROJECT=$1
    local LOCATION=$2
    local SUBSCRIPTION=$3

    local NAME="projects/${PROJECT}/locations/${LOCATION}/subscriptions/${SUBSCRIPTION}"
    local URL="https://analyticshub.googleapis.com/v1/${NAME}:refresh"

    local BODY="{}"

    _call_api "POST" "${URL}" "${BODY}" "${PROJECT}"
}

# Revokes a given subscription.
#
# Official Documentation:
# https://cloud.google.com/bigquery/docs/reference/analytics-hub/rest/v1/projects.locations.subscriptions/revoke
#
# Arguments:
#   $1 (PROJECT):       Required. The project ID of the subscription.
#   $2 (LOCATION):      Required. The location of the subscription.
#   $3 (SUBSCRIPTION):  Required. The ID of the subscription to revoke.
# Outputs:
#   Writes the API response JSON to stdout.
function subscriptions_revoke {
    local PROJECT=$1
    local LOCATION=$2
    local SUBSCRIPTION=$3

    local NAME="projects/${PROJECT}/locations/${LOCATION}/subscriptions/${SUBSCRIPTION}"
    local URL="https://analyticshub.googleapis.com/v1/${NAME}:revoke"

    local BODY="{}"

    _call_api "POST" "${URL}" "${BODY}" "${PROJECT}"
}
