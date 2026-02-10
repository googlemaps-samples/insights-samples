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
# Project RMI Setup
#
# This script helps configure a Google Cloud project for RMI.
# References: https://developers.google.com/maps/documentation/roads-management-insights/cloud-setup
###############################################################################

# Displays usage information and available commands for the script.
usage() {
    echo "Usage: $0 <command> [args]"
    echo ""
    echo "Commands:"
    echo "  all <PROJECT_RMI_ID> [MEMBER]        Run all steps sequentially (MEMBER: user:EMAIL, etc.)"
    echo "  step_check_billing <PROJECT_RMI_ID>  Check if billing is enabled"
    echo "  step_enable_apis <PROJECT_RMI_ID>    Enable required GCP APIs"
    echo "  step_verify_apis <PROJECT_RMI_ID>    Verify APIs are enabled"
    echo "  step_configure_iam <PROJECT_RMI_ID> <MEMBER>  Configure IAM roles for a member"
    echo ""
    echo "IAM Helpers (MEMBER format: user:EMAIL, serviceAccount:EMAIL, group:EMAIL):"
    echo "  grant_roles_to_user <PROJECT_RMI_ID> <EMAIL>"
    echo "  grant_roles_to_group <PROJECT_RMI_ID> <EMAIL>"
    echo "  grant_roles_to_service_account <PROJECT_RMI_ID> <EMAIL>"
}

# Checks if billing is enabled for the specified Google Cloud project.
step_check_billing() {
    local project_id="${1:-${PROJECT_RMI_ID:-}}"
    if [[ -z "$project_id" ]]; then echo "Error: PROJECT_RMI_ID required"; exit 1; fi
    echo "Checking billing status for $project_id..."
    local billing_enabled
    billing_enabled=$(gcloud beta billing projects describe "$project_id" --format="value(billingEnabled)" 2>/dev/null || echo "false")
    if [[ "$billing_enabled" != "true" ]]; then
        echo "Error: Billing is not enabled for project $project_id."
        echo "Please enable billing in the Google Cloud Console."
        exit 1
    fi
    echo "Billing is enabled."
}

# Enables the required Google Cloud APIs for the RMI project.
step_enable_apis() {
    local project_id="${1:-${PROJECT_RMI_ID:-}}"
    if [[ -z "$project_id" ]]; then echo "Error: PROJECT_RMI_ID required"; exit 1; fi
    echo "Enabling APIs for $project_id..."
    gcloud services enable roadsselection.googleapis.com --project "$project_id"
    gcloud services enable analyticshub.googleapis.com --project "$project_id"
    echo "APIs enabled."
}

# Verifies that the required APIs are successfully enabled in the project.
step_verify_apis() {
    local project_id="${1:-${PROJECT_RMI_ID:-}}"
    if [[ -z "$project_id" ]]; then echo "Error: PROJECT_RMI_ID required"; exit 1; fi
    echo "Verifying enabled APIs for $project_id..."
    gcloud services list --project "$project_id" --filter="config.name:roadsselection.googleapis.com"
    gcloud services list --project "$project_id" --filter="config.name:analyticshub.googleapis.com"
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

# Configures the necessary IAM roles for a member in the RMI project.
step_configure_iam() {
    local project_id="$1"
    local member="$2"
    if [[ -z "$project_id" || -z "$member" ]]; then echo "Usage: step_configure_iam <PROJECT_RMI_ID> <MEMBER>"; exit 1; fi

    echo "Configuring IAM roles for $member on $project_id..."
    _grant_role "$project_id" "$member" "roles/roads.roadsSelectionAdmin"
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
    local project_rmi_id="${1:-}"
    local member="${2:-}"

    if [[ -z "$project_rmi_id" ]]; then
        usage
        exit 1
    fi

    echo "Configuring RMI project: $project_rmi_id"
    
    step_check_billing "$project_rmi_id"
    step_enable_apis "$project_rmi_id"
    step_verify_apis "$project_rmi_id"
    
    if [[ -n "$member" ]]; then
        step_configure_iam "$project_rmi_id" "$member"
    else
        echo "No member provided. To grant admin access to a member, run:"
        echo "  $0 step_configure_iam $project_rmi_id user:USER_EMAIL"
    fi

    echo "RMI Project Configuration Complete."
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
    step_*|grant_*)
        cmd="$1"
        shift
        "$cmd" "$@"
        ;;
    *)
        usage
        exit 1
        ;;
esac
