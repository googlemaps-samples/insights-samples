#!/bin/bash
set -euo pipefail
#
# Helper functions for the Google API Discovery Service.
# It is meant to be sourced by other scripts.
#
# For more information, see the official documentation:
# https://developers.google.com/discovery/v1/getting_started

# --- Helper Functions ---

# Extracts the revision ID from a discovery document JSON.
#
# @param string discovery_doc_json The JSON content of a discovery document.
# @return string The revision ID string.
discovery_v1_extract_revision() {
    local json="$1"
    echo "$json" | jq -r '.revision'
}

# Extracts the base URL from a discovery document JSON.
#
# @param string discovery_doc_json The JSON content of a discovery document.
# @return string The baseUrl string.
discovery_v1_extract_base_url() {
    local json="$1"
    echo "$json" | jq -r '.baseUrl'
}
