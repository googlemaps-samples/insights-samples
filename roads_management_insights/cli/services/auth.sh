#!/bin/bash

set -euo pipefail

# Gets an access token from gcloud.
# gcloud automatically handles caching and refreshing the token.
#
# Globals:
#   None
# Arguments:
#   None
# Outputs:
#   Writes the access token to stdout.
get_access_token() {
  gcloud auth application-default print-access-token
}

# Internal function to call a Google Cloud API.
# It includes logic to retry once if the API returns a 401 Unauthorized error.
# This function is compatible with Bash 3.2+.
#
# Arguments:
#   $1 - The HTTP method (e.g., GET, POST).
#   $2 - The full URL for the API endpoint.
#   $3 - (Optional) The request body for POST requests.
#   $4 - (Optional) The project ID to be used in the X-Goog-User-Project header.
# Outputs:
#   Writes the API response to stdout on success.
#   Writes an error to stderr and returns 1 on failure.
_call_api() {
    local HTTP_METHOD="$1"
    local URL="$2"
    local BODY="${3:-}"
    local PROJECT_ID="${4:-}"

    local ACCESS_TOKEN
    ACCESS_TOKEN=$(get_access_token)

    local RESPONSE_FILE
    RESPONSE_FILE=$(mktemp)
    local STATUS_CODE
    
    # Ensure the temp file is cleaned up on exit
    trap 'rm -f "${RESPONSE_FILE}"' RETURN

    local CURL_ARGS=(
        --request "${HTTP_METHOD}"
        --silent
        --write-out "%{http_code}"
        --output "${RESPONSE_FILE}"
        --header "Authorization: Bearer ${ACCESS_TOKEN}"
        --header "Accept: application/json"
        --header "Content-Type: application/json"
        --compressed
    )

    # Add the user project header if a project ID was provided.
    if [[ -n "${PROJECT_ID}" ]]; then
        CURL_ARGS+=(--header "X-Goog-User-Project: ${PROJECT_ID}")
    fi

    if [[ -n "${BODY}" ]]; then
        CURL_ARGS+=(--data-binary "${BODY}")
    fi

    STATUS_CODE=$(curl "${CURL_ARGS[@]}" "${URL}")

    # Retry logic for expired token
    if [[ "${STATUS_CODE}" -eq 401 ]]; then
        echo "Access token may have expired. Refreshing and retrying..." >&2
        ACCESS_TOKEN=$(get_access_token)
        
        # Rebuild args with the new token for the retry.
        local RETRY_CURL_ARGS=(
            --request "${HTTP_METHOD}"
            --silent
            --write-out "%{http_code}"
            --output "${RESPONSE_FILE}"
            --header "Authorization: Bearer ${ACCESS_TOKEN}"
            --header "Accept: application/json"
            --header "Content-Type: application/json"
            --compressed
        )
        if [[ -n "${PROJECT_ID}" ]]; then
            RETRY_CURL_ARGS+=(--header "X-Goog-User-Project: ${PROJECT_ID}")
        fi
        if [[ -n "${BODY}" ]]; then
            RETRY_CURL_ARGS+=(--data-binary "${BODY}")
        fi
        STATUS_CODE=$(curl "${RETRY_CURL_ARGS[@]}" "${URL}")
    fi

    # Check for non-2xx status codes after potential retry.
    if [[ "${STATUS_CODE}" -lt 200 || "${STATUS_CODE}" -ge 300 ]]; then
        echo "API call to ${URL} failed with status code ${STATUS_CODE}:" >&2
        cat "${RESPONSE_FILE}" >&2
        return 1
    fi

    cat "${RESPONSE_FILE}"
}