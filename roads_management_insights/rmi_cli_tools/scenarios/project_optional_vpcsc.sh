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
# Project Optional VPC-SC Setup
#
# This script provides guidance and YAML generation for VPC Service Controls (VPC-SC)
# configuration required to consume RMI data.
# References: https://developers.google.com/maps/documentation/roads-management-insights/vpc-sc
###############################################################################

# Displays usage information and available commands for the VPC-SC setup script.
usage() {
    echo "Usage: $0 <command> [args]"
    echo ""
    echo "Commands:"
    echo "  all <PROJECT_CLOUD_ID> <MEMBER_LIST>  Generate all VPC-SC rule snippets"
    echo "  step_show_restricted_services         Show required restricted services"
    echo "  step_generate_ingress <PROJECT_CLOUD_ID> <MEMBER_LIST>  Generate Ingress Rule YAML"
    echo "  step_generate_egress <MEMBER_LIST>                      Generate Egress Rule YAML"
    echo ""
    echo "MEMBER_LIST: Comma-separated identities (e.g. user:email@addr,serviceAccount:sa@proj.iam.gserviceaccount.com)"
}

# Displays the list of services that must be restricted within the VPC-SC perimeter.
step_show_restricted_services() {
    echo "Ensure the following services are added to the 'Restricted Services' list in your perimeter:"
    echo "  - analyticshub.googleapis.com"
    echo "  - bigquery.googleapis.com"
    echo "  - pubsub.googleapis.com"
    echo "  - roads.googleapis.com"
}

# Generates the YAML snippet for a VPC-SC Ingress Rule.
step_generate_ingress() {
    local project_cloud_id="$1"
    local members_csv="$2"
    if [[ -z "$project_cloud_id" || -z "$members_csv" ]]; then echo "Usage: step_generate_ingress <PROJECT_CLOUD_ID> <MEMBER_LIST>"; exit 1; fi

    # Get project number
    echo "Fetching project number for $project_cloud_id..." >&2
    local project_number
    project_number=$(gcloud projects describe "$project_cloud_id" --format="value(projectNumber)")

    echo "--- Ingress Rule YAML ---"
    echo "- ingressFrom:"
    echo "    identities:"
    IFS=',' read -ra ADDR <<< "$members_csv"
    for member in "${ADDR[@]}"; do
        echo "    - $member"
    done
    echo "    sources:"
    echo "    - accessLevel: '*'"
    echo "  ingressTo:"
    echo "    operations:"
    echo "    - serviceName: analyticshub.googleapis.com"
    echo "      methodSelectors:"
    echo "      - method: '*'"
    echo "    - serviceName: bigquery.googleapis.com"
    echo "      methodSelectors:"
    echo "      - method: '*'"
    echo "    - serviceName: pubsub.googleapis.com"
    echo "      methodSelectors:"
    echo "      - method: '*'"
    echo "    - serviceName: roads.googleapis.com"
    echo "      methodSelectors:"
    echo "      - method: '*'"
    echo "    resources:"
    echo "    - projects/$project_number"
}

# Generates the YAML snippet for a VPC-SC Egress Rule.
step_generate_egress() {
    local members_csv="$1"
    if [[ -z "$members_csv" ]]; then echo "Usage: step_generate_egress <MEMBER_LIST>"; exit 1; fi

    echo "--- Egress Rule YAML ---"
    echo "- egressTo:"
    echo "    operations:"
    echo "    - serviceName: analyticshub.googleapis.com"
    echo "      methodSelectors:"
    echo "      - method: '*'"
    echo "    - serviceName: bigquery.googleapis.com"
    echo "      methodSelectors:"
    echo "      - method: '*'"
    echo "    - serviceName: pubsub.googleapis.com"
    echo "      methodSelectors:"
    echo "      - method: '*'"
    echo "    - serviceName: roads.googleapis.com"
    echo "      methodSelectors:"
    echo "      - method: '*'"
    echo "    resources:"
    echo "    - projects/maps-platform-roads-management"
    echo "  egressFrom:"
    echo "    identities:"
    IFS=',' read -ra ADDR <<< "$members_csv"
    for member in "${ADDR[@]}"; do
        echo "    - $member"
    done
}

# Runs the complete VPC-SC configuration guidance pipeline.
run_all() {
    local project_cloud_id="$1"
    local members_csv="$2"

    echo "=== RMI VPC-SC Configuration Guide ==="
    echo ""
    step_show_restricted_services
    echo ""
    step_generate_ingress "$project_cloud_id" "$members_csv"
    echo ""
    step_generate_egress "$members_csv"
    echo ""
    echo "VPC-SC configuration rules generated. Please provide these to your Security Administrator."
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
