#!/bin/bash
set -euo pipefail
#
# This script provides a client for the Google API Discovery Service.
# It is not meant to be used directly, but rather to be sourced by other scripts.
#
# For more information, see the official documentation:
# https://developers.google.com/discovery/v1/getting_started

# Source the internal helper script
# shellcheck source=/dev/null
source "$(dirname "${BASH_SOURCE[0]}")/api-common.sh"

# --- API Discovery Service v1 ---

# --- Methods ---

# Retrieve the description of a particular version of an API.
#
# @param string api Required. The name of the API.
# @param string version Required. The version of the API.
# @param string project_id Optional. The project ID for auth and billing.
# @see https://developers.google.com/discovery/v1/reference/apis/getRest
function discovery_v1_get_rest() {
    local api="$1"
    local version="$2"
    local project_id="${3:-}"
    local URL="https://${api}.googleapis.com/\$discovery/rest?version=${version}"

    _call_api "GET" "${URL}" "" "${project_id}"
}

# Retrieve the list of APIs supported at this endpoint.
#
# @param string name Optional. Only include APIs with the given name.
# @param string preferred Optional. Return only the preferred version of an API.
# @param string project_id Optional. The project ID for auth and billing.
# @see https://developers.google.com/discovery/v1/reference/apis/list
function discovery_v1_list() {
    local name="${1:-}"
    local preferred="${2:-}"
    local project_id="${3:-}"
    local query_params=""

    if [[ -n "${name}" ]]; then
        query_params+="name=${name}&"
    fi
    if [[ -n "${preferred}" ]]; then
        query_params+="preferred=${preferred}&"
    fi

    local URL="https://discovery.googleapis.com/discovery/v1/apis"
    if [[ -n "${query_params}" ]]; then
        # Remove trailing ampersand
        query_params=${query_params%&}
        URL+="?${query_params}"
    fi

    _call_api "GET" "${URL}" "" "${project_id}"
}
