---
name: api-roadsselection
description: "Developer guide, reference clients (Python, TypeScript, Go, Rust, POSIX Bash; RoadsSelectionClient), and examples for the Google Maps Platform Roads Selection API (roads.googleapis.com/selection/v1). Use when creating, registering, updating, patch with updateMask, listing, or deleting SelectedRoute resources, configuring dynamicRouting or selectedRouteId, running BatchCreate (up to 1,000 routes), BatchUpdate, or BatchDelete, managing routeAttributes, inspecting STATE_RUNNING or STATE_INVALID states, or diagnosing VALIDATION_ERROR_ROUTE_OUTSIDE_JURISDICTION and route validation errors. Do not use for turn-by-turn directions or ComputeRoutes pathfinding (use api-routes), legacy Roads API v1 snapToRoads or nearestRoads (use api-roads-v1), Road Network API v2 roads:list or matchPaths segment lookup (use api-roadnetwork), MATCH_AND_SPLIT_BY_ROAD waypoint sampling strategies (use rmi-routesetting), or BigQuery SQL queries on routes_status and historical_travel_time, Pub/Sub feeds, or Analytics Hub cost estimates (use rmi-sql)."
---

# Roads Selection API Skill

This skill provides reference client implementations (Python, TypeScript, Go, Rust, POSIX Bash), developer runbooks, and example guides for the **Roads Selection API (`roads.googleapis.com`)**, grounded directly in the canonical service definition.

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
| **`CreateSelectedRoute`** | `POST /selection/v1/{parent=projects/*}/selectedRoutes` | Creates a single `SelectedRoute` and begins caching. | Body: `SelectedRoute`, Query: `selectedRouteId` (optional; auto-UUID if omitted) |
| **`BatchCreateSelectedRoutes`** | `POST /selection/v1/{parent=projects/*}/selectedRoutes:batchCreate` | Atomically creates up to **1,000 routes**. | Body: `BatchCreateSelectedRoutesRequest` (`requests: [...]`) |
| **`GetSelectedRoute`** | `GET /selection/v1/{name=projects/*/selectedRoutes/*}` | Retrieves a route by resource name. | Path: `name` |
| **`UpdateSelectedRoute`** | `PATCH /selection/v1/{selected_route.name=projects/*/selectedRoutes/*}` | Natively updates specified route fields via `updateMask`. | Body: `SelectedRoute`, Query: `updateMask` (`google-fieldmask`) |
| **`BatchUpdateSelectedRoutes`** | `POST /selection/v1/{parent=projects/*}/selectedRoutes:batchUpdate` | Updates up to **1,000 routes** in a single batch. | Body: `BatchUpdateSelectedRoutesRequest` (`requests: [...]`, optional `updateMask`) |
| **`ListSelectedRoutes`** | `GET /selection/v1/{parent=projects/*}/selectedRoutes` | Lists routes for a project with pagination. | Query: `pageSize` (default 100; `0` -> 100; `>5,000` clamped to 5,000), `pageToken` |
| **`DeleteSelectedRoute`** | `DELETE /selection/v1/{name=projects/*/selectedRoutes/*}` | Deletes a single route. | Path: `name` |
| **`BatchDeleteSelectedRoutes`** | `POST /selection/v1/{parent=projects/*}/selectedRoutes:batchDelete` | Deletes up to **1,000 routes** atomically. | Body: `BatchDeleteSelectedRoutesRequest` (`names: [...]`) |

---

## 2. Strict Service Validation Rules & Limits

Validation rules (grounded in `references/discoveryDocs/generated_road_selection_v1.json`, revision `20261101`):

1. **`selected_route_id` / `selectedRouteId`**:
   - Length: **4 to 63 characters** when provided.
   - Allowed Characters: `[a-zA-Z0-9_-]*` (**alphanumeric, hyphens `-`, and underscores `_` are valid**).
   - If omitted or empty, Google Cloud automatically generates a UUID upon resource creation.
2. **`display_name` / `displayName`**:
   - Optional and does not have to be unique.
   - Maximum **100 characters** (counted in **Unicode code points**).
   - Best practice: populate a clear, non-empty `display_name` (including deterministic fallback labels for unnamed slip lanes or connector ramps).
3. **`dynamic_route` / `dynamicRoute` (`DynamicRoute`)**:
   - Required `origin` and `destination` (`LatLng`), plus optional `intermediates`.
   - Maximum **25 intermediate waypoints** (`count <= 25`).
   - Coordinate boundaries: Latitude `[-90, 90]`, Longitude `[-180, 180]`.
4. **`dynamic_routing` / `dynamicRouting` (`boolean`)**:
   - Optional top-level boolean on `SelectedRoute` (`"dynamicRouting"` in `camelCase` or `"dynamic_routing"` in `snake_case`).
   - Defaults to **`false`** when omitted: fixes the corridor to the traffic-unaware path computed at creation time, agnostic to live traffic (recommended for pinned physical corridor and road-segment monitoring).
   - When set to **`true`**, the route can dynamically reroute based on live traffic conditions while still passing through all input waypoints.
5. **`route_attributes` / `routeAttributes` (`map<string, string>`)**:
   - Maximum **25 key-value pairs** per route (`count <= 25`).
   - Each key and value must be a **non-empty string** of **1 to 100 characters** (counted in **Unicode code points**). Numeric values must be stringified (e.g. `"14200"`).
   - Keys **must NOT start with `goog`** (case-sensitive prefix `^goog.*`).
6. **`updateMask` (`google-fieldmask`) & Batch Request Envelopes**:
   - Updatable fields relative to `SelectedRoute`: `display_name` (`displayName`), `route_attributes` (`routeAttributes`), `dynamic_routing` (`dynamicRouting`), and `dynamic_route` (`dynamicRoute`, including `origin`, `destination`, and `intermediates`).
   - Specifying `*` performs a full replacement of all updatable fields; omitting `updateMask` implies updating all populated updatable fields in the payload.
   - In `BatchUpdateSelectedRoutesRequest`, a top-level `updateMask` applies to child requests that omit their own `updateMask`. If both batch-level and child-level `updateMask` fields are set, they **must match**.
   - Across all three batch endpoints (`:batchCreate`, `:batchUpdate`, `:batchDelete`), the top-level `parent` (`projects/{project}`) is bound in the URL path and is **not** a top-level field in the HTTP POST JSON body (`{"requests": [...]}` or `{"names": [...]}`). Child `parent` (in `CreateSelectedRouteRequest`, optional/empty allowed) or child `selectedRoute.name` / `names` project segments must match the URL `parent`.
7. **Strict Writable Top-Level Field Allowlist (No Top-Level `priority` or `geometry`)**:
   - Writable `SelectedRoute` JSON objects accept **only** `name` (identifier on update), `display_name` (`displayName`), `dynamic_route` (`dynamicRoute`), `dynamic_routing` (`dynamicRouting`), and `route_attributes` (`routeAttributes`). Output-only fields are `createTime`, `state`, and `validationError`.
   - Upstream GIS/BigQuery columns such as `priority` and WKT/GeoJSON `geometry` are **not** top-level fields in `SelectedRoute` and trigger `HTTP 400 INVALID_ARGUMENT: Invalid JSON payload received. Unknown name`:
     - Store `priority` exclusively inside `route_attributes.priority` (fits within `<= 100` characters).
     - Drop `geometry` completely (corridor geometry is defined by `dynamic_route.origin`, `intermediates`, and `destination`, and polylines exceed the 100-character `route_attributes` value limit).
8. **Lifecycle `State` Enum (Output Only)**:
   - `STATE_UNSPECIFIED (0)`: State is not set.
   - `STATE_SCHEDULING (1)`: Created and being scheduled.
   - `STATE_RUNNING (2)`: Active telemetry schedule running.
   - `STATE_DELETING (3)`: Marked for deletion.
   - `STATE_VALIDATING (4)`: Under validation.
   - `STATE_INVALID (5)`: Route failed validation criteria.
9. **`ValidationError` Enum (Output Only when state is `STATE_INVALID`)**:
   - `VALIDATION_ERROR_UNSPECIFIED (0)`: No error set.
   - `VALIDATION_ERROR_ROUTE_OUTSIDE_JURISDICTION (1)`: Route lies outside authorized project boundary.
   - `VALIDATION_ERROR_LOW_ROAD_USAGE (2)`: Very low traffic density (fails privacy/volume thresholds).
10. **Synchronous Route-Solver Validation & Cumulative Distance Threshold**:
   - During `CreateSelectedRoute` / `BatchCreateSelectedRoutes`, the backend synchronously computes the routed path across `[origin, ...intermediates, destination]`.
   - If waypoints snap to an opposing divided-highway carriageway or blocked tunnel bore and force repeated turnaround loops, the **cumulative routed length** can exceed RMI's internal maximum length threshold (~150–180 km), causing a synchronous `HTTP 400 INVALID_ARGUMENT` even when every individual 2-point leg is valid and `len(intermediates) <= 25`.
   - Note: The JSON protobuf parser accepts both `camelCase` (`dynamicRoute`, `dynamicRouting`, `routeAttributes`) and `snake_case` (`dynamic_route`, `dynamic_routing`, `route_attributes`), and both hyphens (`-`, including `--`) and underscores (`_`) in `selectedRouteId` are valid.

---

## 3. Dedicated Feature Sample Code Guides

Comprehensive guides and polyglot sample code (Shell, cURL, Python, TypeScript, Go, Rust) are available for all 8 RPC methods:

1. **[00: Core CRUD Operations (`Create`, `Get`, `List`, `Delete`)](examples/00_create_get_list_delete_selected_routes.md)**
   - Foundational route lifecycle operations with pagination token handling.
2. **[01: Native Route Modification via `UpdateSelectedRoute` (PATCH) & `FieldMask`](examples/01_update_selected_route_patch.md)**
   - In-place field updates (`displayName`, `routeAttributes`, `dynamicRouting`, `dynamicRoute`) without delete/recreate cycles.
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

### Required Roles

- **Roads Selection Admin (`roles/roads.roadsSelectionAdmin`)**: Full read/write access to create, update, batch-modify, and delete routes.
- **Roads Selection Viewer (`roles/roads.roadsSelectionViewer`)**: Read-only access to get and list routes.
- **Service Usage Consumer (`roles/serviceusage.serviceUsageConsumer`)**: Required on the quota project for `X-Goog-User-Project`.

### Sample `gcloud` Assignment Commands

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

### Sample `gcloud` Role Verification Commands

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
| **[`scripts/roadsselection_v1.py`](scripts/roadsselection_v1.py)** | Object-oriented Python reference client (`RoadsSelectionClient`) with automatic ADC token refreshing and type hinting. | Python 3.10+ |
| **[`scripts/roadsselection_v1.ts`](scripts/roadsselection_v1.ts)** | Zero-build TypeScript reference client (`RoadsSelectionClient`) with native Node 22 type-stripping support. | TypeScript (Node 22+) |
| **[`scripts/roadsselection_v1.go`](scripts/roadsselection_v1.go)** | Zero-dependency standard-library Go reference client (`RoadsSelectionClient`, module in [`scripts/go.mod`](scripts/go.mod)) with `context.Context`, Unicode rune validation, pagination, and state polling. | Go 1.22+ (`net/http`) |
| **[`scripts/roadsselection_v1.rs`](scripts/roadsselection_v1.rs)** | Zero-crate `std`-only Rust reference client (`RoadsSelectionClient`) with pluggable `HttpTransport`, RFC-8259 JSON codec, Unicode code-point validators, and embedded `#[cfg(test)]` suite. | Rust (Edition 2021) |
| **[`scripts/api-common.sh`](scripts/api-common.sh)** | Shared authentication discovery (`_get_access_token`) and quota routing (`X-Goog-User-Project`). | Pure Bash |

---

## 6. References

- **SelectedRoute REST Resource Schema**: [SelectedRoute REST Reference](https://developers.google.com/maps/documentation/roads-management-insights/reference/rest/v1/selection.v1.projects.selectedRoutes#SelectedRoute)
- **Release Notes**: [Roads Management Insights Release Notes](https://developers.google.com/maps/documentation/roads-management-insights/release-notes)
- **Google Cloud IAM & Authentication**: [Google Cloud Service Account Authentication Guide](https://cloud.google.com/docs/authentication)
