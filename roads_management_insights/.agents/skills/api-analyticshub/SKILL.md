---
name: api-analyticshub
description: Expert guidance on BigQuery Analytics Hub. Use this skill when the user asks about shared datasets, linked datasets, data exchange, subscribing to listings, or querying tables with privacy policies like AGGREGATION_THRESHOLD. Also handles resource management (CRUD operations) for Exchanges, Listings, and Subscriptions. Make sure to use this skill whenever the user mentions Analytics Hub, data sharing exchanges, creating listings, or subscribing to linked datasets.
---

# BigQuery Analytics Hub

Analytics Hub allows for zero-copy data sharing between organizations via linked datasets. This skill covers both querying shared data and managing Analytics Hub resources.

## Resource Management (CRUD Operations)

Since `gcloud` and `gmp-cli` do not natively support Analytics Hub, use the provided bash client or direct API calls.

### Core Client
The `scripts/analyticshub_v1.sh` script provides functions for all API operations.
- **Location**: `scripts/analyticshub_v1.sh` (sources `api-common.sh` and `analyticshub_v1_helpers.sh`).
- **Pagination**: Use `scripts/list_all_pages.sh` to automatically page through results until all items are retrieved.
- **Reference**: See `references/analyticshub_v1_20260721.json` for full method signatures and resource schemas.

### Common Operations

#### 1. List Data Exchanges (All Pages)
```bash
source api-analyticshub/scripts/list_all_pages.sh
list_all_pages analyticshub_projects_locations_dataExchanges_list "my-project" "us"
```

#### 2. Create a Listing

##### BigQuery Dataset Listing
```bash
source api-analyticshub/scripts/analyticshub_v1.sh

# 1. Create the dataset source JSON
dataset_json=$(create_big_query_dataset_source_json "projects/my-project/datasets/my_dataset")

# 2. Create the listing JSON
listing_json=$(create_listing_json "My Shared Data" "Description" "contact@example.com" "http://docs" "${dataset_json}")

# 3. Call the API
analyticshub_projects_locations_dataExchanges_listings_create "my-project" "us" "my-exchange" "my-listing" "${listing_json}"
```

##### Listing Validation & Display Name Constraints
* **Allowed Characters**: `displayName` MUST contain ONLY unicode letters, numbers, underscores, dashes, ampersands, and spaces.
* **Prohibited Characters**: Parentheses `(`, `)` are strictly FORBIDDEN in `displayName` and cause `INVALID_ARGUMENT` API rejections.
* **Spacing**: `displayName` must NOT start or end with spaces.

#### 3. Subscribe to a Listing

##### Standard BigQuery Dataset Listing
```bash
source api-analyticshub/scripts/analyticshub_v1.sh

# 1. Create the subscription request JSON (destination dataset)
sub_request=$(create_subscribe_listing_request_json "projects/my-project/datasets/linked_dataset")

# 2. Subscribe
analyticshub_projects_locations_dataExchanges_listings_subscribe "publisher-project" "us" "exchange-id" "listing-id" "${sub_request}"
```

##### Pub/Sub Topic Listing with Advanced Subscriptions (Bigtable / Compression)
```bash
source api-analyticshub/scripts/analyticshub_v1.sh

# 1. Build Bigtable output configuration (Optional)
btc=$(create_bigtable_config_json "default" "sa@example.com" "projects/p/instances/i/tables/t" "true")

# 2. Build Compression transform configuration (Optional)
comp=$(create_compression_json "ZLIB" "COMPRESS")
mt=$(create_message_transform_json "${comp}" "false")

# 3. Create the GooglePubsubV1Subscription object
sub=$(create_pubsub_subscription_json "projects/my-project/subscriptions/my-sub" "${btc}" "[${mt}]")

# 4. Wrap it in DestinationPubSubSubscription
dest=$(create_destination_pubsub_subscription_json "${sub}")

# 5. Build the SubscribeListingRequest payload
sub_request=$(create_subscribe_listing_request_pubsub_json "${dest}")

# 6. Subscribe
analyticshub_projects_locations_dataExchanges_listings_subscribe "publisher-project" "us" "exchange-id" "listing-id" "${sub_request}"
```

## Privacy Policies & Querying

Shared datasets often use an **Aggregation Threshold Policy**.

### Mandatory Syntax
When a policy is active, you **MUST** use the `WITH AGGREGATION_THRESHOLD` clause.

```sql
SELECT WITH AGGREGATION_THRESHOLD
  category,
  COUNT(id) AS total_count
FROM
  `subscriber-project.linked_dataset.table`
GROUP BY
  category
```

### Constraints
- **Mandatory Aggregation**: Every selected column must be in the `GROUP BY` or be an aggregate function.
- **Privacy Unit Column**: BigQuery counts the unique entities in this column (e.g., `id`). If the count is below the threshold (e.g., 5), the row is omitted.
- **Data Egress**: Publishers may enable "Data Egress Restriction," preventing `EXPORT DATA` or `CREATE TABLE AS SELECT` (CTAS).

## Best Practices
- **Dataset Naming**: Prefix linked datasets with `ah_` or `ext_` (e.g., `ah_places_insights`).
- **IAM Roles**: 
    - **Platform Access**: Grant `roles/analyticshub.viewer` (discovery) or `roles/analyticshub.subscriber` (subscription management).
    - **Query Access**: Grant `roles/bigquery.dataViewer` on the **linked dataset** and `roles/bigquery.jobUser` in the local project.
- **Automation**: Use the `create_*_json` helpers to ensure valid request payloads.

### 3. Automated Listing Registration & Dynamic Lineage Documentation

To eliminate human error and accelerate delivery of complex data products, automate the formulation of rich listing metadata payloads:
*   **Dynamic Configurations**: Maintain a central mapping file (e.g., JSON) linking locality IDs to metadata defaults (descriptions, snapshot suffixes, contacts).
*   **Automated Lineage Extraction**: Use robust stream parsing (`sed`/`awk`) to extract the exact spatial boundary definition SQL block (`closed_geom AS ...`) directly from regional SQL sources to embed live documentation.
*   **Dynamic Markdown Templating**: Compile a professional markdown overview detailing schemas, disclaimers, topological simplifications, and lineage queries, then read and format it into a valid JSON string payload.
*   **Idempotent Execution**: Check for existing listings before attempting creation to support seamless retries and prevent "Resource already exists" failures.

### 4. Robust GCS Ingestion Recovery (ECP Proxy Resumption Pattern)

When transferring massive dataset files (>4 GB) in parallel to GCS, network or proxy components like the ECP Proxy may throw transient errors:
`ERROR: Task 'gs://bucket/file.jsonl' failed: ECP Proxy indicated an internal error: Failed to forward request`
*   **Recovery Rule**: Under the *Data Preservation Mandate*, do **NOT** delete local processed source files or rerun long-running pipeline steps on a transfer failure.
*   **Idempotent Resumption**: Execute a targeted, idempotent GCS copy resume:
    ```bash
    find /local/data/dir -maxdepth 1 -type f | gcloud storage cp --read-paths-from-stdin gs://target-bucket/dir/
    ```
    This automatically resumes incomplete stream transfers, verifying hash checksums of already uploaded segments and only transmitting remaining packets, reducing recovery time to seconds.


