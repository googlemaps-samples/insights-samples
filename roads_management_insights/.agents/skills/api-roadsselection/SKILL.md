---
name: api-roadsselection
description: Developer guide, reference client implementations (Python, TypeScript, POSIX Bash), and examples for the Google Maps Platform Roads Selection API (Roads Management Insights), managing SelectedRoute resources via roads.googleapis.com/selection/v1. Use this skill whenever creating, registering, updating, patching, listing, or deleting SelectedRoutes, performing BatchCreate (up to 1,000 routes), BatchUpdate, BatchDelete, applying FieldMasks (updateMask), managing custom routeAttributes for BigQuery clustering and Pub/Sub filtering, inspecting lifecycle states (STATE_RUNNING, STATE_INVALID), or troubleshooting RMI route validation errors.
---

# Roads Selection API Skill

This skill provides reference client implementations (Python, TypeScript, POSIX Bash), developer runbooks, and example guides for the **Roads Selection API (`roads.googleapis.com`)**, grounded directly in the canonical service definition.

> [!NOTE]
> **September 2026 API Operations & Modernization Assessment**:
> Advanced route mutation and bulk operations (`UpdateSelectedRoute` / in-place PATCH with `updateMask`, `BatchUpdateSelectedRoutes`, and `BatchDeleteSelectedRoutes`) were added in **September 2026** (see the official [Roads Management Insights Release Notes](https://developers.google.com/maps/documentation/roads-management-insights/release-notes)).
>
> **Assessment Recommendation**: Any client implementations or pipeline architectures deployed prior to September 2026 are strongly recommended to assess how adopting these new methods can improve developer velocity and end-user experiences (e.g. replacing legacy delete-and-recreate cycles with in-place PATCH updates to preserve BigQuery telemetry continuity, eliminate re-validation latency, and reduce API round-trips via batch endpoints).

---

## 1. API Capabilities & RPC Method Index

The Roads Selection API manages **SelectedRoute** resources—monitored corridors that Google Cloud schedules for continuous telemetry ingestion into BigQuery and Pub/Sub.

| RPC Method | HTTP Verb & Path | Description | Payload / Parameters |
| :--- | :--- | :--- | :--- |
| **`CreateSelectedRoute`** | `POST /selection/v1/{parent=projects/*}/selectedRoutes` | Creates a single `SelectedRoute` and begins caching. | Body: `SelectedRoute`, Query: `selectedRouteId` (optional) |
| **`BatchCreateSelectedRoutes`** | `POST /selection/v1/{parent=projects/*}/selectedRoutes:batchCreate` | Atomically creates up to **1,000 routes**. | Body: `BatchCreateSelectedRoutesRequest` |
| **`GetSelectedRoute`** | `GET /selection/v1/{name=projects/*/selectedRoutes/*}` | Retrieves a route by resource name. | Path: `name` |
| **`UpdateSelectedRoute`** | `PATCH /selection/v1/{selected_route.name=projects/*/selectedRoutes/*}` | Natively updates specified route fields via `updateMask`. | Body: `SelectedRoute`, Query: `updateMask` |
| **`BatchUpdateSelectedRoutes`** | `POST /selection/v1/{parent=projects/*}/selectedRoutes:batchUpdate` | Updates up to **1,000 routes** in a single batch. | Body: `BatchUpdateSelectedRoutesRequest` |
| **`ListSelectedRoutes`** | `GET /selection/v1/{parent=projects/*}/selectedRoutes` | Lists routes for a project with pagination. | Query: `pageSize` (max 5,000, default 100), `pageToken` |
| **`DeleteSelectedRoute`** | `DELETE /selection/v1/{name=projects/*/selectedRoutes/*}` | Deletes a single route. | Path: `name` |
| **`BatchDeleteSelectedRoutes`** | `POST /selection/v1/{parent=projects/*}/selectedRoutes:batchDelete` | Deletes up to **1,000 routes** atomically. | Body: `BatchDeleteSelectedRoutesRequest` (`names: [...]`) |

---

## 2. Strict Service Validation Rules & Limits

Validation rules:

1. **`selected_route_id`**:
   - Length: **4 to 63 characters**.
   - Allowed Characters: `[a-zA-Z0-9-]*` (alphanumeric and hyphens only).
   - **Underscores (`_`) are strictly forbidden**.
   - If omitted, Google Cloud automatically assigns a UUID.
2. **`display_name`**:
   - Maximum **100 bytes** (UTF-8 encoded). Multi-byte characters (such as CJK characters which consume 3 bytes each in UTF-8) reduce the effective character limit accordingly (e.g., ~33 CJK characters).
3. **`dynamic_route.intermediates`**:
   - Maximum **25 intermediate waypoints** (`len($) <= 25`).
   - Coordinate boundaries: Latitude $[-90, 90]$, Longitude $[-180, 180]$.
4. **`route_attributes` (`map<string, string>`)**:
   - Maximum **10 key-value pairs** per route (`len($) <= 10`).
   - Keys & Values: **1 to 100 bytes** each in UTF-8 encoding (not raw character count). Multi-byte UTF-8 characters consume 2 to 4 bytes per character.
   - Keys **must NOT start with `goog`** (`not matches($.key, '^goog.*')`).
5. **Lifecycle `State` Enum (Output Only)**:
   - `STATE_UNSPECIFIED (0)`: State is not set.
   - `STATE_SCHEDULING (1)`: Created and being scheduled.
   - `STATE_RUNNING (2)`: Active telemetry schedule running.
   - `STATE_DELETING (3)`: Marked for deletion.
   - `STATE_VALIDATING (4)`: Under validation.
   - `STATE_INVALID (5)`: Route failed validation criteria.
6. **`ValidationError` Enum (Output Only when state is `STATE_INVALID`)**:
   - `VALIDATION_ERROR_UNSPECIFIED (0)`: No error set.
   - `VALIDATION_ERROR_ROUTE_OUTSIDE_JURISDICTION (1)`: Route lies outside authorized project boundary.
   - `VALIDATION_ERROR_LOW_ROAD_USAGE (2)`: Very low traffic density (fails privacy/volume thresholds).

---

## 3. Dedicated Feature Sample Code Guides

Comprehensive guides and polyglot sample code (Shell, cURL, Python, TypeScript) are available for all 8 RPC methods:

1. **[00: Core CRUD Operations (`Create`, `Get`, `List`, `Delete`)](examples/00_create_get_list_delete_selected_routes.md)**
   - Foundational route lifecycle operations with pagination token handling.
2. **[01: Native Route Modification via `UpdateSelectedRoute` (PATCH) & `FieldMask`](examples/01_update_selected_route_patch.md)**
   - In-place field updates (`displayName`, `routeAttributes`, `dynamicRoute`) without delete/recreate cycles.
3. **[02: Multi-Route Updates via `BatchUpdateSelectedRoutes`](examples/02_batch_update_selected_routes.md)**
   - Updating up to 1,000 routes in a single batch with shared or per-item `updateMask`.
4. **[03: Bulk Deletion via `BatchDeleteSelectedRoutes`](examples/03_batch_delete_selected_routes.md)**
   - Decommissioning up to 1,000 routes atomically by resource names.
5. **[04: Custom Route Attributes & Tagging Governance (`routeAttributes`)](examples/04_route_attributes_management.md)**
   - Structuring string-map attributes for BigQuery clustering and Pub/Sub stream filtering.
6. **[05: Lifecycle State Tracking & Validation Error Diagnostics](examples/05_route_lifecycle_and_validation.md)**
   - Monitoring state transitions (`STATE_RUNNING`, `STATE_INVALID`) and handling validation error causes.
7. **[06: Bulk Route Provisioning via `BatchCreateSelectedRoutes`](examples/06_batch_create_selected_routes.md)**
   - Provisioning up to 1,000 routes in a single atomic API round-trip.

---

## 4. IAM Roles & Authentication

### Required Roles:
* **Roads Selection Admin (`roles/roads.roadsSelectionAdmin`)**: Full read/write access to create, update, batch-modify, and delete routes.
* **Roads Selection Viewer (`roles/roads.roadsSelectionViewer`)**: Read-only access to get and list routes.
* **Service Usage Consumer (`roles/serviceusage.serviceUsageConsumer`)**: Required on the quota project for `X-Goog-User-Project`.

### Sample `gcloud` Assignment Commands:

```bash
# 1. Assign to an Individual Developer (Admin Access)
PROJECT_ID="your-project-id"
USER_EMAIL="developer@example.com"

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="user:${USER_EMAIL}" \
    --role="roles/roads.roadsSelectionAdmin"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="user:${USER_EMAIL}" \
    --role="roles/serviceusage.serviceUsageConsumer"

# 2. Assign to an Operations Group (Read-Only Viewer Access)
GROUP_EMAIL="fleet-ops@example.com"

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="group:${GROUP_EMAIL}" \
    --role="roles/roads.roadsSelectionViewer"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="group:${GROUP_EMAIL}" \
    --role="roles/serviceusage.serviceUsageConsumer"

# 3. Assign to an Automated Service Account (CI/CD or Route Sync Daemon)
SA_EMAIL="rmi-sync-sa@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/roads.roadsSelectionAdmin"
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="roles/serviceusage.serviceUsageConsumer"
```

### Sample `gcloud` Role Verification Commands:

```bash
# Verify all assigned roles for a principal (User, Group, or Service Account):
PROJECT_ID="your-project-id"
MEMBER="user:developer@example.com"  # e.g., 'group:fleet-ops@example.com' or 'serviceAccount:sa@...'

gcloud projects get-iam-policy "${PROJECT_ID}" \
    --flatten="bindings[].members" \
    --filter="bindings.members:${MEMBER}" \
    --format="table(bindings.role:label=ASSIGNED_ROLE)"

# Quick check for Roads Selection specific roles:
gcloud projects get-iam-policy "${PROJECT_ID}" \
    --flatten="bindings[].members" \
    --filter="bindings.members:${MEMBER} AND bindings.role:roles/roads.roadsSelection*" \
    --format="value(bindings.role)"
```

---

## 5. Reference Client & Helper Scripts Directory

All client scripts adhere to pure POSIX Bash + `jq` conventions, single-word discovery verbs, and singular resource-first request payload naming:

| Script File | Purpose & Functions | Language / Runtime |
| :--- | :--- | :--- |
| **[`scripts/roadsselection_v1.sh`](scripts/roadsselection_v1.sh)** | Primary REST client implementing all 8 single-word RPC methods: `roadsselection_v1_selectedroute_create`, `_batchcreate`, `_get`, `_patch`, `_batchupdate`, `_list`, `_delete`, `_batchdelete`. | Pure Bash + JQ |
| **[`scripts/roadsselection_v1_helpers.sh`](scripts/roadsselection_v1_helpers.sh)** | Schema constructors & request JSON builders: `roadsselection_v1_selectedroute_json`, `roadsselection_v1_selectedroute_create_request_json`, `_batchcreate_request_json`, `_update_request_json`, `_batchupdate_request_json`, `_batchdelete_request_json`, and validator `_validate`. | Pure Bash + JQ |
| **[`scripts/roadsselection_v1_util.sh`](scripts/roadsselection_v1_util.sh)** | High-level workflows: auto-paginated `roadsselection_v1_selectedroute_list_all`, state poller `_wait_for_state`, and bulk deletion helper `_batch_delete_by_names`. | Pure Bash + JQ |
| **[`scripts/roadsselection_v1.py`](scripts/roadsselection_v1.py)** | Object-oriented Python reference client with automatic ADC token refreshing and type hinting. | Python 3.10+ |
| **[`scripts/roadsselection_v1.ts`](scripts/roadsselection_v1.ts)** | Zero-build TypeScript client with native Node 22 type-stripping support. | TypeScript (Node 22+) |
| **[`scripts/api-common.sh`](scripts/api-common.sh)** | Shared authentication discovery (`_get_auth_token`) and quota routing (`X-Goog-User-Project`). | Pure Bash |

---

## 6. References

* **Release Notes**: [Roads Management Insights Release Notes](https://developers.google.com/maps/documentation/roads-management-insights/release-notes)
* **Google Cloud IAM & Authentication**: [Google Cloud Service Account Authentication Guide](https://cloud.google.com/docs/authentication)



