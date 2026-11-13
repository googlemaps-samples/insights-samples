#!/bin/bash
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
#
set -euo pipefail
# Sibling resolution
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "${DIR}/api-common.sh" ]]; then
  source "${DIR}/api-common.sh"
fi



# --- Request Body Helper Functions ---

# Creates a JSON object for a DataExchange.
# @param string display_name
# @param string description
# @param string primary_contact
# @param string documentation
# @param string icon
create_data_exchange_json() {
    jq -n --arg dn "$1" --arg desc "$2" --arg pc "$3" --arg doc "$4" --arg icon "$5" \
        '{displayName: $dn, description: $desc, primaryContact: $pc, documentation: $doc, icon: $icon}'
}

# Creates a JSON object for a BigQueryDatasetSource.
# @param string dataset
create_big_query_dataset_source_json() {
    jq -n --arg ds "$1" '{dataset: $ds}'
}

# Creates a JSON object for a Listing.
# @param string display_name
# @param string description
# @param string primary_contact
# @param string documentation
# @param string bigquery_dataset_source_json
# @param string data_provider_json
create_listing_json() {
    local display_name="$1"
    local description="$2"
    local primary_contact="$3"
    local documentation="$4"
    local bigquery_dataset_source_json="$5"
    local data_provider_json="$6"

    local json_output="{}"
    json_output=$(echo "${json_output}" | jq --arg dn "$display_name" '.displayName = $dn')
    json_output=$(echo "${json_output}" | jq --arg desc "$description" '.description = $desc')
    json_output=$(echo "${json_output}" | jq --arg pc "$primary_contact" '.primaryContact = $pc')
    json_output=$(echo "${json_output}" | jq --arg doc "$documentation" '.documentation = $doc')

    if [[ -n "${bigquery_dataset_source_json}" ]]; then
        json_output=$(echo "${json_output}" | jq --argjson bqds "${bigquery_dataset_source_json}" '.bigqueryDataset = $bqds')
    fi

    if [[ -n "${data_provider_json}" ]]; then
        json_output=$(echo "${json_output}" | jq --argjson dp "${data_provider_json}" '.dataProvider = $dp')
    fi

    local pubsub_topic_source_json="${7:-}"
    if [[ -n "${pubsub_topic_source_json}" ]]; then
        json_output=$(echo "${json_output}" | jq --argjson psts "${pubsub_topic_source_json}" '.pubsubTopic = $psts')
    fi

    echo "${json_output}"
}

# Creates a JSON object for a PubSubTopicSource.
# @param string topic
create_pubsub_topic_source_json() {
    jq -n --arg tp "$1" '{topic: $tp}'
}

# Creates a JSON object for a DataProvider.
# @param string name
# @param string primary_contact
create_data_provider_json() {
    jq -n --arg name "$1" --arg pc "$2" '{name: $name, primaryContact: $pc}'
}

# Creates a JSON object for a DestinationDataset.
# @param string dataset_id Required. The ID of the dataset to create. e.g. "my_linked_dataset"
# @param string project_id Required. The project ID containing the destination dataset. e.g. "my-project"
# @param string location Optional. Geographic location where the dataset should reside (default: "us").
# @param string friendly_name Optional. A descriptive name for the dataset.
# @param string description Optional. A user-friendly description of the dataset.
create_destination_dataset_json() {
    local dataset_id="$1"
    local project_id="$2"
    local location="${3:-us}"
    local friendly_name="${4:-}"
    local description="${5:-}"

    local json_output
    json_output=$(jq -n \
        --arg did "$dataset_id" \
        --arg pid "$project_id" \
        --arg loc "$location" \
        '{datasetReference: {datasetId: $did, projectId: $pid}, location: $loc}')

    if [[ -n "${friendly_name}" ]]; then
        json_output=$(echo "${json_output}" | jq --arg fn "$friendly_name" '.friendlyName = $fn')
    fi
    if [[ -n "${description}" ]]; then
        json_output=$(echo "${json_output}" | jq --arg desc "$description" '.description = $desc')
    fi
    echo "${json_output}"
}

# Creates a JSON object for a SubscribeListingRequest.
# @param string destination_dataset_or_json (Accepts DestinationDataset JSON or dataset resource path "projects/P/datasets/D")
# @param string location Optional. Location of the destination dataset (default: "us").
create_subscribe_listing_request_json() {
    local arg="$1"
    local location="${2:-us}"
    if [[ "${arg}" =~ ^[[:space:]]*\{ ]]; then
        jq -n --argjson dd "${arg}" '{destinationDataset: $dd}'
    elif [[ "${arg}" =~ ^projects/([^/]+)/datasets/([^/]+)$ ]]; then
        local pid="${BASH_REMATCH[1]}"
        local did="${BASH_REMATCH[2]}"
        jq -n --arg pid "$pid" --arg did "$did" --arg loc "$location" \
            '{destinationDataset: {datasetReference: {projectId: $pid, datasetId: $did}, location: $loc}}'
    else
        jq -n --arg dd "${arg}" '{destinationDataset: $dd}'
    fi
}

# Creates a JSON object for a DelimitedKey.
# @param string key_fields_json Required. JSON array of key field strings (e.g. '["id","region"]') or single field name.
# @param string delimiter Optional. Byte sequence used to delimit concatenated fields (1-50 chars).
create_delimited_key_json() {
    local key_fields_json="$1"
    local delimiter="${2:-}"

    local json_output
    if [[ "${key_fields_json}" =~ ^[[:space:]]*\[ ]]; then
        json_output=$(jq -n --argjson kf "${key_fields_json}" '{keyFields: $kf}')
    else
        json_output=$(jq -n --arg kf "${key_fields_json}" '{keyFields: [$kf]}')
    fi

    if [[ -n "${delimiter}" ]]; then
        json_output=$(echo "${json_output}" | jq --arg del "${delimiter}" '.delimiter = $del')
    fi
    echo "${json_output}"
}

# Creates a JSON object for a ColumnFamilyMapping.
# @param string mode_or_delimited_key_json Required. Pass "rowKeySchema" (or "ROW_KEY_SCHEMA" or "{}") for structured row key schema mode, or a DelimitedKey JSON object (or full ColumnFamilyMapping JSON).
create_column_family_mapping_json() {
    local arg="$1"
    if [[ "${arg}" == "rowKeySchema" || "${arg}" == "ROW_KEY_SCHEMA" || "${arg}" == "{}" ]]; then
        jq -n '{rowKeySchema: {}}'
    elif [[ "${arg}" =~ ^[[:space:]]*\{ ]]; then
        if echo "${arg}" | jq -e 'has("rowKeySchema") or has("delimitedKey")' >/dev/null 2>&1; then
            echo "${arg}" | jq '.'
        else
            jq -n --argjson dk "${arg}" '{delimitedKey: $dk}'
        fi
    else
        jq -n --arg kf "${arg}" '{delimitedKey: {keyFields: [$kf]}}'
    fi
}

# Creates a JSON object for a BigtableConfig.
# @param string app_profile_id Optional.
# @param string service_account_email Optional.
# @param string table Optional.
# @param boolean write_metadata Optional. (true/false)
# @param string column_family_mapping_json Optional. (ColumnFamilyMapping JSON object)
create_bigtable_config_json() {
    local app_profile_id="${1:-}"
    local service_account_email="${2:-}"
    local table="${3:-}"
    local write_metadata="${4:-}"
    local column_family_mapping_json="${5:-}"

    local json_output="{}"
    if [[ -n "${app_profile_id}" ]]; then
        json_output=$(echo "${json_output}" | jq --arg ap "${app_profile_id}" '.appProfileId = $ap')
    fi
    if [[ -n "${service_account_email}" ]]; then
        json_output=$(echo "${json_output}" | jq --arg sae "${service_account_email}" '.serviceAccountEmail = $sae')
    fi
    if [[ -n "${table}" ]]; then
        json_output=$(echo "${json_output}" | jq --arg t "${table}" '.table = $t')
    fi
    if [[ -n "${write_metadata}" ]]; then
        json_output=$(echo "${json_output}" | jq --argjson wm "${write_metadata}" '.writeMetadata = $wm')
    fi
    if [[ -n "${column_family_mapping_json}" ]]; then
        json_output=$(echo "${json_output}" | jq --argjson cfm "${column_family_mapping_json}" '.columnFamilyMapping = $cfm')
    fi
    echo "${json_output}"
}

# Creates a JSON object for a Compression.
# @param string compression_algorithm Required. (e.g. COMPRESSION_ALGORITHM_UNSPECIFIED, ZLIB)
# @param string compression_mode Required. (e.g. COMPRESSION_MODE_UNSPECIFIED, COMPRESS, DECOMPRESS)
create_compression_json() {
    jq -n --arg ca "$1" --arg cm "$2" '{compressionAlgorithm: $ca, compressionMode: $cm}'
}

# Creates a JSON object for a MessageTransform with Compression.
# @param string compression_json Required.
# @param boolean disabled Optional. (true/false)
create_message_transform_json() {
    local compression_json="$1"
    local disabled="${2:-}"

    local json_output="{}"
    if [[ -n "${compression_json}" ]]; then
        json_output=$(echo "${json_output}" | jq --argjson comp "${compression_json}" '.compression = $comp')
    fi
    if [[ -n "${disabled}" ]]; then
        json_output=$(echo "${json_output}" | jq --argjson dis "${disabled}" '.disabled = $dis')
    fi
    echo "${json_output}"
}

# Creates a JSON object for a GooglePubsubV1Subscription.
# @param string name Required. (e.g. projects/{project}/subscriptions/{sub})
# @param string bigtable_config_json Optional.
# @param string message_transforms_json_array Optional. (e.g. [{"compression": ...}])
create_pubsub_subscription_json() {
    local name="$1"
    local bigtable_config_json="${2:-}"
    local message_transforms_json_array="${3:-}"

    local json_output="{}"
    json_output=$(echo "${json_output}" | jq --arg n "$name" '.name = $n')

    if [[ -n "${bigtable_config_json}" ]]; then
        json_output=$(echo "${json_output}" | jq --argjson btc "${bigtable_config_json}" '.bigtableConfig = $btc')
    fi
    if [[ -n "${message_transforms_json_array}" ]]; then
        json_output=$(echo "${json_output}" | jq --argjson mt "${message_transforms_json_array}" '.messageTransforms = $mt')
    fi
    echo "${json_output}"
}

# Creates a JSON object for a DestinationPubSubSubscription.
# @param string pubsub_subscription_json Required. (GooglePubsubV1Subscription)
create_destination_pubsub_subscription_json() {
    jq -n --argjson ps "$1" '{pubsubSubscription: $ps}'
}

# Creates a JSON object for a SubscribeListingRequest with Pub/Sub.
# @param string destination_pubsub_subscription_json Required. (DestinationPubSubSubscription)
create_subscribe_listing_request_pubsub_json() {
    jq -n --argjson dps "$1" '{destinationPubsubSubscription: $dps}'
}

# Creates a JSON object for an EncryptionConfig.
# @param string kms_key_name Required. KMS key resource name (projects/{p}/locations/{l}/keyRings/{kr}/cryptoKeys/{k}).
create_encryption_config_json() {
    jq -n --arg kms "$1" '{kmsKeyName: $kms}'
}

# Creates a JSON object for a QueryTemplate.
# @param string display_name Required. Human-readable display name (max 63 bytes).
# @param string description Optional. Short description (max 2000 bytes).
# @param string primary_contact Optional. Email or URL of the primary point of contact.
# @param string documentation Optional. Documentation describing the QueryTemplate.
# @param string routine_json Optional. JSON string for Routine (e.g. '{"routineType":"TABLE_VALUED_FUNCTION","definitionBody":"..."}').
# @param string encryption_config_json Optional. JSON string for EncryptionConfig or KMS key resource name.
create_query_template_json() {
    local display_name="$1"
    local description="${2:-}"
    local primary_contact="${3:-}"
    local documentation="${4:-}"
    local routine_json="${5:-}"
    local encryption_config_json="${6:-}"

    local json_output
    json_output=$(jq -n --arg dn "${display_name}" '{displayName: $dn}')

    if [[ -n "${description}" ]]; then
        json_output=$(echo "${json_output}" | jq --arg desc "${description}" '.description = $desc')
    fi
    if [[ -n "${primary_contact}" ]]; then
        json_output=$(echo "${json_output}" | jq --arg pc "${primary_contact}" '.primaryContact = $pc')
    fi
    if [[ -n "${documentation}" ]]; then
        json_output=$(echo "${json_output}" | jq --arg doc "${documentation}" '.documentation = $doc')
    fi
    if [[ -n "${routine_json}" ]]; then
        json_output=$(echo "${json_output}" | jq --argjson rt "${routine_json}" '.routine = $rt')
    fi
    if [[ -n "${encryption_config_json}" ]]; then
        if [[ "${encryption_config_json}" =~ ^[[:space:]]*\{ ]]; then
            json_output=$(echo "${json_output}" | jq --argjson ec "${encryption_config_json}" '.encryptionConfiguration = $ec')
        else
            json_output=$(echo "${json_output}" | jq --arg kms "${encryption_config_json}" '.encryptionConfiguration = {kmsKeyName: $kms}')
        fi
    fi

    echo "${json_output}"
}

# Creates a JSON object for a SubscribeDataExchangeRequest.
# @param string destination Required. Parent resource path of the Subscription (e.g. "projects/subscriberproject/locations/us").
# @param string subscription Required. Name of the subscription to create (e.g. "subscription1").
# @param string subscriber_contact Optional. Email of the subscriber.
# @param string destination_dataset_json Optional. JSON string for DestinationDataset.
create_subscribe_data_exchange_request_json() {
    local destination="$1"
    local subscription="$2"
    local subscriber_contact="${3:-}"
    local destination_dataset_json="${4:-}"

    local json_output
    json_output=$(jq -n --arg dest "${destination}" --arg sub "${subscription}" \
        '{destination: $dest, subscription: $sub}')

    if [[ -n "${subscriber_contact}" ]]; then
        json_output=$(echo "${json_output}" | jq --arg sc "${subscriber_contact}" '.subscriberContact = $sc')
    fi
    if [[ -n "${destination_dataset_json}" ]]; then
        json_output=$(echo "${json_output}" | jq --argjson dd "${destination_dataset_json}" '.destinationDataset = $dd')
    fi

    echo "${json_output}"
}

# --- Canonical Option A Helper Aliases ---
analyticshub_v1_dataexchange_json() { create_data_exchange_json "$@"; }
analyticshub_v1_bigquerydatasetsource_json() { create_big_query_dataset_source_json "$@"; }
analyticshub_v1_listing_json() { create_listing_json "$@"; }
analyticshub_v1_pubsubtopicsource_json() { create_pubsub_topic_source_json "$@"; }
analyticshub_v1_dataprovider_json() { create_data_provider_json "$@"; }
analyticshub_v1_destinationdataset_json() { create_destination_dataset_json "$@"; }
analyticshub_v1_subscribelisting_request_json() { create_subscribe_listing_request_json "$@"; }
analyticshub_v1_subscribelisting_pubsub_request_json() { create_subscribe_listing_request_pubsub_json "$@"; }
analyticshub_v1_delimitedkey_json() { create_delimited_key_json "$@"; }
analyticshub_v1_delimited_key_json() { create_delimited_key_json "$@"; }
analyticshub_v1_columnfamilymapping_json() { create_column_family_mapping_json "$@"; }
analyticshub_v1_column_family_mapping_json() { create_column_family_mapping_json "$@"; }
analyticshub_v1_bigtableconfig_json() { create_bigtable_config_json "$@"; }
analyticshub_v1_bigtable_config_json() { create_bigtable_config_json "$@"; }
analyticshub_v1_compression_json() { create_compression_json "$@"; }
analyticshub_v1_messagetransform_json() { create_message_transform_json "$@"; }
analyticshub_v1_pubsubsubscription_json() { create_pubsub_subscription_json "$@"; }
analyticshub_v1_destinationpubsubsubscription_json() { create_destination_pubsub_subscription_json "$@"; }
analyticshub_v1_encryptionconfig_json() { create_encryption_config_json "$@"; }
analyticshub_v1_encryption_config_json() { create_encryption_config_json "$@"; }
analyticshub_v1_querytemplate_json() { create_query_template_json "$@"; }
analyticshub_v1_query_template_json() { create_query_template_json "$@"; }
analyticshub_v1_subscribedataexchange_request_json() { create_subscribe_data_exchange_request_json "$@"; }
analyticshub_v1_subscribe_data_exchange_request_json() { create_subscribe_data_exchange_request_json "$@"; }



