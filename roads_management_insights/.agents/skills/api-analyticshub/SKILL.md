---
name: api-analyticshub
description: Expert guidance on BigQuery Analytics Hub. Use this skill when the user asks about shared datasets, linked datasets, data exchange, subscribing to listings, discovering public datasets, or querying tables with privacy policies like AGGREGATION_THRESHOLD. Also handles resource management (CRUD operations) for Exchanges, Listings, and Subscriptions. Make sure to use this skill whenever the user mentions Analytics Hub, data sharing exchanges, creating listings, public datasets exchange, or subscribing to linked datasets.
---

# BigQuery Analytics Hub

Analytics Hub enables zero-copy data sharing between organizations via linked datasets. This skill covers discovering data exchanges (including the central Google Cloud Public Datasets Exchange), listing and subscribing to datasets, managing exchange/listing resources, and querying shared data.

---

## 1. Resource Management (CRUD Operations)

Since BigQuery Analytics Hub does **not** have a native `gcloud` CLI command family (`gcloud analyticshub` does not exist), all programmatic operations must use the provided POSIX bash client (`scripts/analyticshub_v1.sh`), Terraform, or direct REST API calls.

### Core Client & Utilities

* **Client Script**: [`scripts/analyticshub_v1.sh`](scripts/analyticshub_v1.sh) — Full 35/35 method coverage across `organizations.locations.dataExchanges`, `projects.locations.dataExchanges`, `projects.locations.dataExchanges.listings`, `projects.locations.dataExchanges.queryTemplates`, and `projects.locations.subscriptions` (sources [`scripts/api-common.sh`](scripts/api-common.sh) and [`scripts/analyticshub_v1_helpers.sh`](scripts/analyticshub_v1_helpers.sh)). Supports both library sourcing (`analyticshub_projects_locations_...` and `analyticshub_v1_projects_locations_...`) and direct CLI dispatch (`bash scripts/analyticshub_v1.sh <method_id> ...`).
* **Payload Helpers**: [`scripts/analyticshub_v1_helpers.sh`](scripts/analyticshub_v1_helpers.sh) — Deterministic JSON payload builders (`create_data_exchange_json`, `create_listing_json`, `create_destination_dataset_json`, `create_subscribe_listing_request_json`, `create_subscribe_data_exchange_request_json`, `create_bigtable_config_json`, `create_column_family_mapping_json`, `create_delimited_key_json`, `create_query_template_json`, `create_encryption_config_json`, etc., plus `analyticshub_v1_*` aliases).
* **Automatic Paginator**: [`scripts/list_all_pages.sh`](scripts/list_all_pages.sh) (automatically pages through `nextPageToken` until all resources are fetched).
* **API Discovery Contract**: [Discovery Documents](references/discoveryDocs/) (see [`references/discoveryDocs/analyticshub_v1_20261026.json`](references/discoveryDocs/analyticshub_v1_20261026.json)).

---

## 2. Common Operations & Practical Workflows

### 1. Discover Data Exchanges

#### A. List Data Exchanges in a Project (All Pages)

```bash
source scripts/list_all_pages.sh
list_all_pages analyticshub_projects_locations_dataExchanges_list "my-project" "us"
```

#### B. Get Details of a Data Exchange

```bash
source scripts/analyticshub_v1.sh
analyticshub_projects_locations_dataExchanges_get "1057666841514" "us" "google_cloud_public_datasets_17e74966199"
```

---

### 2. Discover & List Datasets in a Data Exchange

Google Cloud hosts a central, publicly accessible Data Exchange containing **176+ freely adoptable public datasets**:

* **Web UI / Exchange Path**: `/exchanges/projects/1057666841514/locations/us/dataExchanges/google_cloud_public_datasets_17e74966199`
* **Resource Path**: `projects/1057666841514/locations/us/dataExchanges/google_cloud_public_datasets_17e74966199`
* **Host Project Number**: `1057666841514`
* **Location**: `us`
* **Data Exchange ID**: `google_cloud_public_datasets_17e74966199`
* **Catalog Highlights**: 176 datasets including AlphaFold Protein Structures, American Community Survey (ACS) / Census, NOAA Global Surface Weather, OpenStreetMap / Overture Maps, COVID-19 Public Data, Google Trends, and Cryptocurrency Analytics.

#### A. List First Page of Listings in the Public Exchange

```bash
source scripts/analyticshub_v1.sh

# List the first 20 listings in the Google Cloud Public Datasets Exchange
analyticshub_projects_locations_dataExchanges_listings_list \
  "1057666841514" "us" "google_cloud_public_datasets_17e74966199" 20
```

#### B. List All 176 Public Datasets (Auto-Paging) with Clean Formatting

```bash
source scripts/list_all_pages.sh

# Stream and format all 176 listings: [Listing ID] Display Name (Provider)
list_all_pages analyticshub_projects_locations_dataExchanges_listings_list \
  "1057666841514" "us" "google_cloud_public_datasets_17e74966199" | \
  jq -r '. | "\(.name | split("/")[-1]): \(.displayName) (\(.dataProvider.name // .publisher.name // "Google"))"'
```

#### C. Get Full Metadata for a Specific Listing

```bash
source scripts/analyticshub_v1.sh

# Inspect a specific public dataset listing (e.g., American Community Survey)
analyticshub_projects_locations_dataExchanges_listings_get \
  "1057666841514" "us" "google_cloud_public_datasets_17e74966199" "d2d533e16f204c62b7e122d1cf837e39"
```

---

### 3. Subscribe to a Listing

Subscribing provisions a **linked dataset** inside your destination BigQuery project. Queries run against the publisher's zero-copy storage without ingestion or copy costs.

#### A. Subscribe to a Public Dataset Listing (Recommended: Structured Payload)

```bash
source scripts/analyticshub_v1.sh
source scripts/analyticshub_v1_helpers.sh

# 1. Build the DestinationDataset configuration
# Parameters: dataset_id, project_id, location, friendly_name, description
dest_ds=$(create_destination_dataset_json \
  "linked_census_acs" \
  "my-subscriber-project" \
  "us" \
  "American Community Survey Public Dataset" \
  "Subscribed from Google Cloud Public Datasets Exchange")

# 2. Build the SubscribeListingRequest payload
sub_request=$(create_subscribe_listing_request_json "${dest_ds}")

# 3. Subscribe to the listing in the public exchange
analyticshub_projects_locations_dataExchanges_listings_subscribe \
  "1057666841514" \
  "us" \
  "google_cloud_public_datasets_17e74966199" \
  "d2d533e16f204c62b7e122d1cf837e39" \
  "${sub_request}"
```

#### B. Subscribe using Shorthand Resource Path

```bash
source scripts/analyticshub_v1.sh
source scripts/analyticshub_v1_helpers.sh

# 1. Create subscription payload directly from destination dataset path
sub_request=$(create_subscribe_listing_request_json \
  "projects/my-subscriber-project/datasets/linked_alphafold" "us")

# 2. Subscribe to listing (e.g. AlphaFold Protein Structure Database)
analyticshub_projects_locations_dataExchanges_listings_subscribe \
  "1057666841514" \
  "us" \
  "google_cloud_public_datasets_17e74966199" \
  "alphafold_protein_structure_database_18245cca049" \
  "${sub_request}"
```

#### C. Pub/Sub Topic Listing with Advanced Subscriptions (Bigtable / ColumnFamilyMapping / Compression)

```bash
source scripts/analyticshub_v1.sh
source scripts/analyticshub_v1_helpers.sh

# 1. Build Bigtable ColumnFamilyMapping & output configuration (Optional)
# Supports structured rowKeySchema ("rowKeySchema") or DelimitedKey from JSON fields
dk=$(create_delimited_key_json '["tenant_id","event_id"]' "#")
cfm=$(create_column_family_mapping_json "${dk}")
btc=$(create_bigtable_config_json "default" "sa@example.com" "projects/p/instances/i/tables/t" "true" "${cfm}")

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
analyticshub_projects_locations_dataExchanges_listings_subscribe \
  "publisher-project" "us" "exchange-id" "listing-id" "${sub_request}"
```

#### D. Clean Room Query Templates (with Optional Cloud KMS `EncryptionConfig`)

```bash
source scripts/analyticshub_v1.sh
source scripts/analyticshub_v1_helpers.sh

# 1. Build EncryptionConfig and QueryTemplate payload
enc=$(create_encryption_config_json "projects/my-project/locations/us/keyRings/kr1/cryptoKeys/k1")
routine='{"routineType":"TABLE_VALUED_FUNCTION","definitionBody":"SELECT category, COUNT(*) FROM `proj.ds.tbl` GROUP BY 1"}'
qt_body=$(create_query_template_json \
  "Aggregated Category Counts" \
  "Privacy-safe clean room TVF" \
  "analyst@example.com" \
  "https://docs.example.com/cleanroom" \
  "${routine}" \
  "${enc}")

# 2. Create, submit, and approve QueryTemplate
analyticshub_projects_locations_dataExchanges_queryTemplates_create \
  "my-project" "us" "my-cleanroom-exchange" "qt_category_counts" "${qt_body}"
analyticshub_projects_locations_dataExchanges_queryTemplates_submit \
  "my-project" "us" "my-cleanroom-exchange" "qt_category_counts"
analyticshub_projects_locations_dataExchanges_queryTemplates_approve \
  "my-project" "us" "my-cleanroom-exchange" "qt_category_counts"
```

---

### 4. Create & Publish Listings

#### A. Create a BigQuery Dataset Listing

```bash
source scripts/analyticshub_v1.sh
source scripts/analyticshub_v1_helpers.sh

# 1. Create the dataset source JSON
dataset_json=$(create_big_query_dataset_source_json "projects/my-project/datasets/my_dataset")

# 2. Create the listing JSON
listing_json=$(create_listing_json "My Shared Data" "Description" "contact@example.com" "https://docs.example.com" "${dataset_json}")

# 3. Register the listing in your exchange
analyticshub_projects_locations_dataExchanges_listings_create \
  "my-project" "us" "my-exchange" "my-listing" "${listing_json}"
```

#### Listing Validation & Display Name Constraints

* **Allowed Characters**: `displayName` MUST contain ONLY unicode letters, numbers, underscores, dashes, ampersands, and spaces.
* **Prohibited Characters**: Parentheses `(`, `)` are strictly FORBIDDEN in `displayName` and cause `INVALID_ARGUMENT` API rejections.
* **Spacing**: `displayName` must NOT start or end with spaces.

---

### 5. Manage Subscriptions

```bash
source scripts/analyticshub_v1.sh

# List all active subscriptions in subscriber project
analyticshub_projects_locations_subscriptions_list "my-subscriber-project" "us"

# Get details of an active subscription
analyticshub_projects_locations_subscriptions_get "my-subscriber-project" "us" "sub-12345"

# Refresh a subscription (synchronizes schema alterations)
analyticshub_projects_locations_subscriptions_refresh "my-subscriber-project" "us" "sub-12345" "{}"

# Revoke a subscription
analyticshub_projects_locations_subscriptions_revoke "my-subscriber-project" "us" "sub-12345" "{}"

# Delete a subscription record
analyticshub_projects_locations_subscriptions_delete "my-subscriber-project" "us" "sub-12345"
```

---

## 3. Privacy Policies & Querying Shared Data

Shared datasets often implement an **Aggregation Threshold Policy** to preserve privacy.

### Mandatory Syntax

When an aggregation policy is active, queries **MUST** include the `WITH AGGREGATION_THRESHOLD` clause:

```sql
SELECT WITH AGGREGATION_THRESHOLD
  category,
  COUNT(id) AS total_count
FROM
  `my-subscriber-project.linked_dataset.table`
GROUP BY
  category
```

### Key Constraints

* **Mandatory Aggregation**: Every selected column must either appear in `GROUP BY` or be inside an aggregate function (`COUNT`, `SUM`, `AVG`).
* **Privacy Unit Column**: BigQuery evaluates distinct privacy unit values (e.g. `id`). Rows below the publisher's threshold (e.g. < 5 unique entities) are omitted.
* **Data Egress Protection**: When publishers enable data egress restrictions, `EXPORT DATA` and `CREATE TABLE AS SELECT` (CTAS) are blocked.

---

## 4. Best Practices

* **Dataset Naming**: Prefix linked datasets with `ah_` or `ext_` (e.g., `ah_census_acs`, `ah_alphafold`).
* **IAM Roles**:
  * **Discovery**: Grant `roles/analyticshub.viewer` to search exchanges and listings.
  * **Subscription**: Grant `roles/analyticshub.subscriber` and `roles/bigquery.admin` (or `roles/bigquery.dataEditor`) to link datasets into a project.
  * **Querying**: Grant `roles/bigquery.dataViewer` on the **linked dataset** and `roles/bigquery.jobUser` on the subscriber project.
* **Automation**: Always use the `create_*_json` helper functions to construct valid API payloads.
* **Resource Name Normalization (`projects/<project_number>/...` vs. `projects/<project_id>/...`)**: When querying `https://analyticshub.googleapis.com/v1/projects/<project_id>/locations/<loc>/dataExchanges` (and its child `listings`), the REST API returns `exchange.name` and `listing.name` formatted with the **numeric project number** (`projects/123456789012/locations/<loc>/dataExchanges/<id>`), even when the request URL used the **alphanumeric project ID** and `bigqueryDataset.dataset` is formatted as `projects/<project_id>/datasets/<dataset_id>`. Pipelines joining or diffing live REST responses against warehouse tables must normalize `^projects/[0-9]+/` to `projects/<project_id>/` (or extract the trailing exchange/listing ID slugs via `REGEXP_EXTRACT`).
* **No `locations/-` wildcard for exchange discovery (verified live 2026-11)**: `GET .../projects/<p>/locations/-/dataExchanges` does not return exchanges across locations. Loop over candidate locations (start with the shared dataset's own location, since a dataset listing must sit in the same location as its exchange, then the rest of [supported_locations.json](references/supported_locations.json)) and collect **all** matches, because one owner can have exchanges in several replica locations. Run the per-location calls in parallel with a timeout.
* **Subscriptions are read with GET, behind dedicated permissions**: `dataExchanges:listSubscriptions` and `listings:listSubscriptions` are `GET` in REST (`includeDeletedSubscriptions` query param). They need `analyticshub.dataExchanges.viewSubscriptions` / `analyticshub.listings.viewSubscriptions`, which a plain `roles/analyticshub.viewer` holder may not have. Treat 403 here as "not visible", not "no subscriptions".
* **Find exchanges by what they share, not only by name**: naming conventions drift (legacy or typo'd exchange and listing IDs exist). When a name-prefix search finds nothing, scan listings and match `bigqueryDataset.dataset` (or `pubsubTopic.topic`) against the target resource; bound the scan (max exchanges, time budget, concurrency).

---

### 4.1 Supported Locations (Validate Before Provisioning)
- Analytics Hub (BigQuery sharing) is available only in a subset of BigQuery locations. The machine-readable snapshot is [references/supported_locations.json](references/supported_locations.json), with its source URL and retrieval date inside. The 2026-09-27 snapshot has 42 regions plus the multi-regions `us` and `eu`.
- **Source of truth**: https://docs.cloud.google.com/bigquery/docs/analytics-hub-introduction#supported-regions. Refresh the JSON when the docs change; don't hardcode lists in code.
- Match case-insensitively: BigQuery accepts `US` and `us`.
- **Omni regions** (`aws-*`, `azure-*`) support sharing, but multi-region listings and dataset replicas are not supported there. Exclude them when provisioning native BigQuery datasets.
- **Multi-region listings** are supported only for shared datasets and linked dataset replicas, not for Pub/Sub topics. So when a dataset has cross-region replicas meant to be shareable, validate the replica locations against the same list.
- Terraform: load the JSON with `jsondecode(file("${path.module}/data/<file>.json"))` into a local, and check `contains(local.supported, lower(var.region))` in a `validation` block. This needs Terraform >= 1.9, because validation must reference a local. Bash: `jq -r '.multi_regions[], (.regions[]|.[])' supported_locations.json`.

## 5. Execution Strategy & Determinism Protocol

### Tier 1: Deterministic Client Scripts (Primary / Recommended)

Whenever POSIX shell execution is available, agents **MUST** prioritize using the pre-tested helper and client scripts located in `scripts/`:

* Sourcing client: `source scripts/analyticshub_v1.sh`
* Sourcing helpers: `source scripts/analyticshub_v1_helpers.sh`

*Why:* Eliminates code hallucination risks, guarantees exact payload structure for Data Exchanges and Listings, manages OAuth2 tokens and `X-Goog-User-Project` quota headers, and automatically handles regional endpoint routing.

### Tier 2: Direct REST / Discovery Contract (Polyglot Fallback)

If executing in environments without shell access (e.g., pure Python/Node.js runtimes, notebooks, or backend microservices):

* Refer directly to the canonical Discovery Document in [`references/discoveryDocs/analyticshub_v1_20261026.json`](references/discoveryDocs/analyticshub_v1_20261026.json) for parameter schemas, data types, and HTTP methods.
* Issue requests directly via your runtime's native HTTP client without inventing ungrounded parameters.

---

## References

* [Google Cloud Analytics Hub Documentation](https://cloud.google.com/bigquery/docs/analytics-hub-introduction)
* [Analytics Hub REST API Reference](https://cloud.google.com/bigquery/docs/reference/analytics-hub/rest)
* [Google Cloud Public Datasets Exchange](https://cloud.google.com/bigquery/public-data)
* [Discovery Documents](references/discoveryDocs/)
* [Public API Discovery Document (v1)](https://analyticshub.googleapis.com/$discovery/rest?version=v1)
