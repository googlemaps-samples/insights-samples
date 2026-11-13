---
name: rmi-routesetting
description: Use this skill when discussing, explaining, or implementing RMI route setting, route setting strategies, selected route setting strategies, route registration strategies, or route selection. It provides foundational strategies (SINGLE_ROUTE_UNIFORM_INTERMEDIATES, SIMPLE_ORIGIN_DESTINATION, MATCH_AND_SPLIT_BY_ROAD, BUS_ROUTE_MONITORING, BYO_POLYLINE) for transforming geographical intent into monitored SelectedRoute objects using GA-stage Routes API, Roads API (v1), and Roads Selection API. Do not use for Road Network API v2 or topology-aware graph partitioning (use rmi-routesetting-preview instead).
dependencies:
  - api-roads-v1
  - api-routes
  - api-roadsselection
---

# RMI Route Setting (Technical Strategies)

This skill governs the orchestration pipeline for RMI route registration. It defines the technical strategies, algorithmic workflows, and step-by-step implementation logic used to transform geographical intent into monitored `SelectedRoute` objects on Google Maps Platform.

## Strategy Relationship Map

```mermaid
graph TD
    %% Entry Points
    EntryPL["Polyline Based<br/>(Internal GIS / Open Data)"] --> Feasibility{"Spatial Alignment Assessment<br/>(Feasibility Gate)"}
    EntryOD["Origin/Destination Based<br/>(Geographical Intent)"] --> Pathfinding{"Pathfinding Baseline<br/>(Routes API v2 ComputeRoutes<br/>TRAFFIC_UNAWARE)"}
    EntryTransit["Transit Schedule<br/>(GTFS Feed / Agency Stops)"] --> BusHops["Stop Sequence Partitioning<br/>(Stop_i to Stop_i+1)"]

    %% Intermediate Processing & Fallback
    Feasibility -- "Aligned" --> Snapping["Snapping & Cleaning<br/>(Roads API v1 snapToRoads)"]
    Feasibility -- "Divergent" --> FallbackIntent["Intent-Based Recreation<br/>(Fallback to Routes v2 ComputeRoutes)"]
    FallbackIntent --> Pathfinding
    Snapping --> BYOPLY["BYO_POLYLINE Ingestion"]
    Pathfinding --> RouteGeom["High-Quality Linestring"]

    %% Primary Registration Strategies (The Outputs)
    RouteGeom --> SplitDistance["SINGLE_ROUTE_UNIFORM_INTERMEDIATES<br/>(25-Point Authentic Vertex Pinning<br/>dynamicRouting: false)"]
    RouteGeom --> SplitRoad["MATCH_AND_SPLIT_BY_ROAD<br/>(Place ID Cluster Midpoints<br/>Roads API v1 snapToRoads<br/>dynamicRouting: false)"]
    Pathfinding --> OD["SIMPLE_ORIGIN_DESTINATION<br/>(A-to-B Natural Path Drift<br/>dynamicRouting: true)"]
    BusHops --> BusSeq["BUS_ROUTE_MONITORING<br/>(Stop-to-Stop SelectedRoute Sequence<br/>dynamicRouting: false)"]
    BYOPLY --> SplitDistance

    %% Registration Gate
    SplitDistance --> Registration["Roads Selection API<br/>(roadsselection_v1_selectedroute_create / batchcreate)"]
    SplitRoad --> Registration
    OD --> Registration
    BusSeq --> Registration

    %% BigQuery Telemetry Storage
    Registration --> BQStatus["BigQuery routes_status<br/>(static_route_geometry, road_segment_ids)"]
    Registration --> BQTelemetry["BigQuery historical_travel_time & recent_roads_data<br/>(travel_duration, SRI speed, observed segments)"]
```

---

## 1. Foundational Orchestration Pipeline

The end-to-end route creation workflow coordinates three GA-stage services:

1. **Pathfinding (`api-routes`)**: Invokes `ComputeRoutes` (Routes API v2) with `routingPreference: "TRAFFIC_UNAWARE"` for a deterministic, un-congested baseline distance and duration calculation at route setting time.
   > [!NOTE]
   > **Monitoring Runtime vs. Route Setting**: While `TRAFFIC_UNAWARE` is recommended at the initial route setting stage to establish clean physical baselines, RMI internally operates using `TRAFFIC_AWARE` (not `TRAFFIC_AWARE_OPTIMAL`) during active, ongoing telemetry collection.
2. **Snapping & Alignment (`api-roads-v1`)**: Cleanses raw coordinate traces against Google's road network using `snapToRoads` or `nearestRoads`.
3. **Registration & Packaging (`api-roadsselection`)**: Constructs standard JSON/JSONL `SelectedRoute` resources with structured metadata tags and registers them via the Roads Selection API using canonical helper scripts or polyglot SDKs.

### Route Dynamism: Fixed vs. Dynamic Routes (`dynamicRouting`)

When creating a `SelectedRoute`, the `dynamicRouting` boolean parameter controls how the RMI monitoring engine evaluates the route over time:

* **Fixed Corridor (`dynamicRouting: false` — Default)**:
  * **Behavior**: Pinned to the deterministic, un-congested physical geometry established at route creation time. RMI continuously monitors the exact roadway corridor specified by the waypoints without path deviation.
  * **When to Use**: Trunk corridors, highways, arterials, bridge/tunnel links, transit lines, and before-and-after infrastructure evaluations where tracking a specific physical path is mandatory.
  * **Associated Strategies**: `SINGLE_ROUTE_UNIFORM_INTERMEDIATES`, `MATCH_AND_SPLIT_BY_ROAD`, `BUS_ROUTE_MONITORING`, `BYO_POLYLINE`.
* **Dynamic Route (`dynamicRouting: true`)**:
  * **Behavior**: RMI dynamically re-evaluates the optimal route between origin and destination (and any intermediates) in real time using live traffic conditions. If congestion or incidents occur on the primary artery, RMI reflects the alternative path taken by navigation traffic (**path drift**).
  * **When to Use**: High-level regional corridors (e.g. Airport-to-CBD, suburb-to-downtown) where understanding alternative arterial usage and travel time divergence under incident conditions is the primary goal.
  * **Associated Strategies**: `SIMPLE_ORIGIN_DESTINATION`.
* **Switching an existing route (no re-registration needed)**: `dynamicRouting` can be flipped in place with `UpdateSelectedRoute` or `BatchUpdateSelectedRoutes` (`updateMask=dynamicRouting`). Only geometry changes trigger re-validation, so the flip keeps `state` and BigQuery telemetry continuity. Do not delete and recreate routes to change this flag. For bulk migrations (e.g. dynamic → fixed), follow the bulk in-place mutation playbook in `rmi-operations`.

### BigQuery Output Fields & Road Network Maintenance Mechanics

Once registered, route definitions and telemetry materialize in the customer's BigQuery linked dataset:

| Output Field | Table | Type | Maintenance Mechanics |
| :--- | :--- | :--- | :--- |
| `static_route_geometry` | `routes_status` | `GEOGRAPHY` (LineString) | Static baseline geometry computed at creation time via un-congested routing (`TRAFFIC_UNAWARE`). |
| `road_segment_ids` | `routes_status` | `REPEATED STRING` (Place IDs) | **Fixed Routes (`dynamic_routing: false`)**: Google automatically heals and maintains this array as Google's underlying road network evolves over time (e.g., segment renumbering, construction, geometry realignments).<br/>**Dynamic Routes (`dynamic_routing: true`)**: This field is **not updated or maintained** in `routes_status` because the traversed corridor changes dynamically. |
| `road_segment_ids` | `historical_travel_time`<br/>`recent_roads_data` | `REPEATED STRING` (Place IDs) | For dynamic routes (`dynamic_routing: true`), the actually traversed Google road segments are dynamically recorded per aggregation interval directly in telemetry rows. |

### Post-Registration Lifecycle & Error Diagnostics

After submission to Roads Selection API, a route progresses through an asynchronous validation state machine:

```mermaid
stateDiagram-v2
    [*] --> STATE_SCHEDULING: roadsselection_v1_selectedroute_create
    STATE_SCHEDULING --> STATE_VALIDATING: Queued for Google Road Graph Solver
    STATE_VALIDATING --> STATE_RUNNING: Validated on Road Network & Jurisdiction
    STATE_VALIDATING --> STATE_INVALID: Validation Failure
    STATE_RUNNING --> [*]: Active Telemetry Collection
    STATE_INVALID --> [*]: Inspect validationError
```

* **Lifecycle States (`state`)**:
  1. `STATE_SCHEDULING`: Initial queuing state immediately following API submission.
  2. `STATE_VALIDATING`: The Google road network engine evaluates coordinate routability, segment connectivity, and jurisdictional licensing.
  3. `STATE_RUNNING`: Route successfully registered. Ongoing 5-minute telemetry intervals will populate BigQuery `historical_travel_time` and real-time Pub/Sub feeds.
  4. `STATE_INVALID`: Route rejected. Telemetry will not be collected.
* **State Polling**: Use `roadsselection_v1_selectedroute_wait_for_state` from `api-roadsselection` to poll until terminal state (`STATE_RUNNING` or `STATE_INVALID`).
* **Validation Error Diagnostics (`validationError`)**:
  * `VALIDATION_ERROR_LOW_ROAD_USAGE`: Traffic volume or probe vehicle density along the submitted road segments is too low to produce statistically significant, privacy-safe traffic metrics.
  * `VALIDATION_ERROR_ROUTE_OUTSIDE_JURISDICTION`: The proposed corridor extends beyond the customer's contracted or licensed geographical jurisdiction boundary.
* **Synchronous Solver Limit**: The Google road network routing solver synchronously rejects route payloads with cumulative length exceeding **~150–180 km** (returning HTTP `400 INVALID_ARGUMENT`). Corridors longer than this threshold or routes with severe detour loops must be partitioned into shorter sub-corridors.

### Canonical Tooling & Polyglot SDKs

Always use canonical tooling from [`api-roadsselection`](../api-roadsselection/SKILL.md) instead of manual HTTP requests:
* **Single Route Creation**: `roadsselection_v1_selectedroute_create` creates a route and optionally accepts a custom `selectedRouteId` (or auto-generates a server UUID).
* **High-Throughput Batch Creation**: `roadsselection_v1_selectedroute_batchcreate` (`BatchCreateSelectedRoutes`) registers up to **1,000 routes** in a single atomic REST call.
* **5-Language Polyglot Reference SDKs**:
  * **POSIX Bash**: [`roadsselection_v1.sh`](../api-roadsselection/scripts/roadsselection_v1.sh), [`roadsselection_v1_helpers.sh`](../api-roadsselection/scripts/roadsselection_v1_helpers.sh), [`roadsselection_v1_util.sh`](../api-roadsselection/scripts/roadsselection_v1_util.sh)
  * **Python**: [`roadsselection_v1.py`](../api-roadsselection/scripts/roadsselection_v1.py) (`RoadsSelectionClient`)
  * **TypeScript / Node 22**: [`roadsselection_v1.ts`](../api-roadsselection/scripts/roadsselection_v1.ts) (`RoadsSelectionClient`)
  * **Go**: [`roadsselection_v1.go`](../api-roadsselection/scripts/roadsselection_v1.go) (`RoadsSelectionClient`)
  * **Rust**: [`roadsselection_v1.rs`](../api-roadsselection/scripts/roadsselection_v1.rs) (`RoadsSelectionClient`)

---

## 2. Core Registration Strategies & Implementation Steps

> [!TIP]
> **Optional Route Attributes & Downstream Utility**: All custom key-value pairs populated in `routeAttributes` are completely optional. Attribute names should be chosen deliberately based on downstream analytical utility, reporting filters, and dashboard slicing requirements (e.g., standardizing on snake_case attributes like `sampledataset`, `priority`, `route_length_meters`, `create_time`, `origin`, `destination` as used in public sample datasets).

### A. Path-Based Strategies (Heuristic & Geometry Pinning)

---

#### 1. `SIMPLE_ORIGIN_DESTINATION` (A-to-B Dynamic Route Monitoring)

* **Objective**: Monitor the end-to-end travel performance between two key geographical hubs without intermediate waypoints, allowing RMI to capture natural **path drift** (how Google Maps dynamically re-routes traffic across alternate arteries in response to real-time incidents).
* **Routing Dynamism**: Explicitly set `"dynamicRouting": true`.
* **When to Use**: High-level corridor audits (e.g. Airport-to-Downtown corridors like Manhattan to JFK/LGA/EWR), where observing alternative routing behavior is the primary analytical goal.
* **Output Scale**: 1 `SelectedRoute` per Origin-Destination pair (very low route count).
* **Implementation Steps**:
  1. **Compute Baseline Route Metrics**: Call Routes API v2 `ComputeRoutes` (`routes_computeRoutes`) with `travelMode: "DRIVE"` and `routingPreference: "TRAFFIC_UNAWARE"` to extract reference un-congested distance (`routes[0].distanceMeters`) and baseline duration (`routes[0].duration`).
  2. **Assemble SelectedRoute Dynamic Payload**: Construct the JSON object specifying `dynamicRouting: true` and `dynamicRoute` with strictly the `origin` and `destination` coordinates (`latitude`, `longitude`). Leave `intermediates` empty or omitted.
  3. **Populate Contextual Metadata (`routeAttributes`)**: Attach optional downstream metadata tags (aligned with sample dataset conventions):
     * `strategy`: `"SIMPLE_ORIGIN_DESTINATION"`
     * `route_length_meters`: baseline distance string
     * `base_duration`: baseline duration string
     * `origin`: origin coordinates string (`"lat,lng"`)
     * `destination`: destination coordinates string (`"lat,lng"`)
     * `create_time`: registration timestamp string
     * `creator`: provenance tag
  4. **Register SelectedRoute**: Write payload to `${PREFIX}_selected_route.json` and submit via Roads Selection API (`roadsselection_v1_selectedroute_create`).
* **Reference Implementation Script**: [`scripts/strategy_simple_origin_destination.sh`](scripts/strategy_simple_origin_destination.sh)

---

#### 2. `SINGLE_ROUTE_UNIFORM_INTERMEDIATES` (Equidistant Waypoint Pinning)

* **Objective**: Force the RMI engine to monitor one specific physical roadway corridor without path deviation by placing up to 25 evenly spaced intermediate waypoints along the route polyline.
* **Routing Dynamism**: Explicitly set `"dynamicRouting": false` for deterministic fixed corridor tracking.
* **When to Use**: Trunk corridors, highways, and specific arterials where you want a single unified `SelectedRoute` entity but need to eliminate routing ambiguity across parallel roads or local shortcut diversions.
* **Output Scale**: 1 `SelectedRoute` per corridor, containing up to 25 intermediate waypoints.
* **Implementation Steps**:
  1. **Retrieve High-Quality Linestring**: Invoke Routes API v2 `ComputeRoutes` with `routingPreference: "TRAFFIC_UNAWARE"`, requesting `polylineQuality: "HIGH_QUALITY"` and `polylineEncoding: "GEO_JSON_LINESTRING"` to obtain dense coordinates grounded directly on Google's road network.
  2. **Execute Distance-Aware Existing Vertex Subsampling (Zero Synthetic Interpolation)**:
     * Compute the cumulative geodesic length $L$ along the returned coordinate sequence.
     * **Adaptive Waypoint Count**: Determine target count $N = \min(25, \lfloor L / \text{minSpacing} \rfloor)$ with a sensible spacing threshold ($\text{minSpacing} \ge 200\text{m}$) to prevent over-granular waypoints on short corridors. If $L < \text{minSpacing}$, omit intermediates ($N=0$).
     * **Sparse Vertex Retention**: If the total internal coordinate count $(M - 2) \le N$, retain all authentic internal vertices directly without downsampling.
     * **Authentic Vertex Selection**: When downsampling is required, calculate equidistant milestones $d_k = k \times \frac{L}{N+1}$ and select the **actual existing polyline vertex** closest to each milestone. Never synthesize fractional points between vertices, ensuring 100% road graph alignment.
  3. **Construct SelectedRoute Payload**: Assemble `dynamicRouting: false` and `dynamicRoute` with `origin`, the ordered array of up to 25 authentic `intermediates` (`{ latitude, longitude }`), and `destination`.
  4. **Enrich Metadata**: Tag optional `routeAttributes` with:
     * `strategy`: `"SINGLE_ROUTE_UNIFORM_INTERMEDIATES"`
     * `intermediate_count`: count of generated waypoints
     * `logic`: `"sample route vertices"`
     * `route_length_meters`: baseline length
     * `base_duration`: baseline duration
     * `create_time`: timestamp
  5. **Register & Validate**: Write payload to `${PREFIX}_selected_route.json` and submit via `roadsselection_v1_selectedroute_create`. Verify alignment in `geospatial-viz`.
* **Reference Implementation Script**: [`scripts/strategy_single_route_uniform_intermediates.sh`](scripts/strategy_single_route_uniform_intermediates.sh)

---

#### 3. `MATCH_AND_SPLIT_BY_ROAD` (Road Segment Midpoint Pinning)

* **Objective**: Use Roads API v1 (`snapToRoads`) to divide a navigated polyline into traversed Google road segments (`placeId` clusters) and place intermediate waypoints at the **middle vertex** of each segment. Since an individual road segment does not split or fork internally, connecting single segment midpoints forms a highly efficient corridor route with zero redundant waypoints.
* **Routing Dynamism**: Explicitly set `"dynamicRouting": false` for deterministic fixed corridor tracking.
* **When to Use**: Arterials, urban avenues, and complex corridors where you want segment-guided intermediate waypoints without placing multiple redundant waypoints on the same uninterrupted road segment.
* **Output Scale**: 1 unified `SelectedRoute` entity pinned across traversed road segments (with adaptive capping at 25 waypoints).
* **Implementation Steps**:
  1. **Generate Path Polyline**: Query Routes API v2 `ComputeRoutes` (`TRAFFIC_UNAWARE`, `HIGH_QUALITY`) to extract the navigated coordinate sequence.
  2. **Snap Coordinates via Roads API v1**: Format polyline points as a pipe-separated string (`lat,lng|lat,lng|...`) and call `roads_v1_snapToRoads` with `interpolate=true`.
  3. **Group Contiguous Points by `placeId`**: Parse the returned `snappedPoints` array and group adjacent points sharing the same `placeId` into distinct road segment clusters.
  4. **Extract Segment Middle Vertices**:
     * For each intermediate road segment (excluding origin and destination terminal segments), pick its middle vertex (`segment.points[length / 2]`).
     * **Adaptive 25-Waypoint Limit**: If the total count of traversed internal road segments $K \le 25$, retain all $K$ segment midpoints. Only when $K > 25$, stride-subsample the segment midpoints down to 25 to respect the `SelectedRoute` quota.
  5. **Assemble SelectedRoute Payload**: Construct `dynamicRouting: false` and `dynamicRoute` with `origin`, the ordered segment midpoint `intermediates`, and `destination`.
  6. **Enrich Metadata**: Tag optional `routeAttributes` with:
     * `strategy`: `"MATCH_AND_SPLIT_BY_ROAD"`
     * `total_road_segments`: total count of traversed Google road segments
     * `intermediate_count`: count of midpoint waypoints
     * `logic`: `"road segment middle vertices"`
     * `route_length_meters` and `base_duration`: baseline metrics
     * `create_time`: timestamp
  7. **Register & Validate**: Write payload to `${PREFIX}_selected_route.json` and submit via Roads Selection API (`roadsselection_v1_selectedroute_create`).
* **Reference Implementation Script**: [`scripts/strategy_match_and_split_by_road.sh`](scripts/strategy_match_and_split_by_road.sh)

---

### B. Use-Case Specific Strategies

---

#### 4. `BUS_ROUTE_MONITORING` (Transit Stop-to-Stop Sequence)

* **Objective**: Monitor public transit lines by registering each consecutive bus stop pair as an independent `SelectedRoute`, enabling stop-by-stop transit delay auditing and timetable reliability analysis.
* **Routing Dynamism**: Explicitly set `"dynamicRouting": false`.
* **When to Use**: Municipal bus transit networks, BRT (Bus Rapid Transit) corridors, and shuttle loops.
* **Output Scale**: $K - 1$ `SelectedRoute` objects for a bus route with $K$ consecutive stops.
* **Implementation Steps**:
  1. **Ingest GTFS / Transit Stop Sequence**: Extract ordered stop records containing `stop_id`, `stop_name`, `stop_lat`, `stop_lon`, and `stop_sequence` from GTFS feeds or agency databases.
  2. **Iterate Consecutive Stop Pairs**: For each index $i \in [1, K-1]$, define a pair from $Stop_i$ to $Stop_{i+1}$.
  3. **Optional Turn Verification**: If transit vehicles take a dedicated turn/loop between stops, query Routes API v2 between $(Stop_i, Stop_{i+1})$ to identify intermediate guidance points.
  4. **Generate SelectedRoute Object**:
     * `dynamicRouting`: `false`
     * `origin`: coordinates of $Stop_i$
     * `destination`: coordinates of $Stop_{i+1}$
     * `displayName`: `Bus Route {route_id}: {Stop_i} -> {Stop_{i+1}}`
     * `routeAttributes`: `route_id`, `trip_id`, `from_stop_id`, `to_stop_id`, `stop_sequence`
  5. **Atomic Batch Registration**: Submit all $K-1$ route objects in a single call via `roadsselection_v1_selectedroute_batchcreate` (supporting up to 1,000 routes per batch).
  6. **BigQuery Interval Analytics**: In BigQuery, analyze travel time progression between stops using SQL window functions (`LAG()`).

---

### C. Integration Strategies

---

#### 5. `BYO_POLYLINE` (Bring Your Own Polyline / Open GIS Ingestion)

* **Objective**: Ingest existing vector road centerlines or historical GPS traces from municipal GIS systems (ESRI Shapefile, GeoJSON, OpenStreetMap) and convert them into RMI-compliant `SelectedRoute` definitions.
* **Routing Dynamism**: Explicitly set `"dynamicRouting": false`.
* **When to Use**: Enterprise onboarding where a client provides pre-mapped road geometry assets.
* **Prerequisite Assessment (Source Data Feasibility & Alignment Check)**:
  > [!IMPORTANT]
  > **Early Geometric Overlay Assessment**: Always run an initial feasibility assessment on a representative sample of source polylines against Google Maps road network before undertaking batch ingestion.
  > * **Alignment Risk**: If the source GIS layer is derived from divergent, outdated, or low-precision coordinate geometry, automated `snapToRoads` calls can snap coordinates to adjacent parallel service roads, overpasses, or fail.
  > * **Intent-Based Recreation Alternative**: If the source network fails the alignment assessment (low geometric overlay), **do not force-snap defective polylines**. Instead, understand the original operational intent (e.g., from *Origin Zone A* to *Destination Zone B* via *Corridor C*) and recreate the route directly on Google's native road graph using Routes API v2 `ComputeRoutes` (`TRAFFIC_UNAWARE`) with strategy `SINGLE_ROUTE_UNIFORM_INTERMEDIATES` or `MATCH_AND_SPLIT_BY_ROAD`.
* **Implementation Steps**:
  1. **Source Data Feasibility Assessment**: Check spatial overlay against Google Maps road network. If divergent, pivot to Intent-Based Recreation.
  2. **Parse Vector GIS Layer**: Extract coordinate vertices from the source GIS LineString or WKT geometry.
  3. **Coordinate Snapping & Road Alignment**: Send raw coordinates through `roads_v1_snapToRoads` (`interpolate=true`) to eliminate GIS digitizing offsets and snap to Google Maps road centerlines. Never place intermediate waypoints inside tunnel bores or across split toll-plaza islands.
  4. **Vertex Decimation (25-Point Quota)**: Downsample the snapped coordinate chain to a maximum of 25 intermediate waypoints plus origin and destination.
  5. **Mandatory Directional Routability Gate (`computeRoutes`)**: Because `snapToRoads` snaps purely by spatial proximity without checking directional routability, query `POST https://routes.googleapis.com/directions/v2:computeRoutes` (`X-Goog-FieldMask: routes.distanceMeters,routes.legs.distanceMeters,routes.legs.steps.navigationInstruction.instructions`) with the candidate `[origin, ...intermediates, destination]`:
     * Verify `routes.distanceMeters` is within `1.0x–1.3x` of the source GIS segment length (cumulative detour loops >150–180 km will cause `CreateSelectedRoute` to fail synchronously with `400 INVALID_ARGUMENT`).
     * Inspect `routes.legs[i].distanceMeters` and `navigationInstruction.instructions` to confirm no waypoint snapped to the opposing divided carriageway or diverted onto a parallel surface road.
  6. **Assemble & Register**: Structure into standard `dynamicRoute` format (`dynamicRouting: false`) and annotate optional `routeAttributes` with external asset IDs (`gis_layer`, `asset_id`, `source_crs`, `logic: "byo_gis_snapped"`). Register via `roadsselection_v1_selectedroute_create` or `batchcreate`.

---

## 3. Quota, Limits & Technical Constraints

| Constraint | Limit / Rule | Rationale & Handling |
| :--- | :--- | :--- |
| **Max Intermediates** | **25 waypoints** per `SelectedRoute` | Hard API limit for `dynamicRoute.intermediates`. Always apply decimation when processing dense paths. |
| **Routing Preference** | `TRAFFIC_UNAWARE` for baseline pathing | Ensures static, reproducible route geometries without temporary incident warping at route creation time. |
| **Runtime Monitoring** | `TRAFFIC_AWARE` ongoing telemetry | RMI telemetry engine tracks real-time traffic speeds and delays continuously. |
| **Dynamic Routing Flag** | `dynamicRouting: true` vs `false` | Explicit boolean flag: `true` for live-traffic path drift (A-to-B audits); `false` for fixed physical corridor monitoring. |
| **Identifier Format** | Hyphens only (`[a-zA-Z0-9-]`, 4–63 chars) | Selected Route IDs must match regex constraints. While API permits underscores, standardizing on letters, numbers, and hyphens ensures seamless BigQuery table/query compatibility. |
| **Attribute Governance** | `map<string, string>` (Max 25 pairs) | Keys and values must be non-empty strings between 1 and 100 Unicode code points. Keys must NOT start with reserved prefix `goog` (`^(?!goog).*`). Values must be stringified (numeric attributes require `SAFE_CAST()` in BigQuery SQL). |
| **Synchronous Solver Limit** | Cumulative route length **< 150–180 km** | Google road network solver synchronously rejects routes longer than ~150–180 km with HTTP `400 INVALID_ARGUMENT`. Divide long routes into sub-corridors. |
| **Batch Registration** | **Up to 1,000 routes** per batch | `BatchCreateSelectedRoutes` atomically processes up to 1,000 route registrations in a single call. |

---

## 4. Analytical Patterns (BigQuery)

When analyzing stop-to-stop transit segments or subdivided corridors in BigQuery, use window functions like `LAG()` to calculate inter-stop distances and speed deltas:

```sql
SELECT 
  selected_route_id,
  JSON_VALUE(route_attributes, '$.route_id') AS transit_line,
  SAFE_CAST(JSON_VALUE(route_attributes, '$.stop_sequence') AS INT64) AS stop_seq,
  JSON_VALUE(route_attributes, '$.from_stop_id') AS from_stop,
  JSON_VALUE(route_attributes, '$.to_stop_id') AS to_stop,
  AVG(duration_in_seconds) AS avg_duration_sec,
  -- Calculate incremental distance using LAG
  ROUND(
    SAFE_CAST(JSON_VALUE(route_attributes, '$.baseDistanceMeters') AS FLOAT64) - 
    LAG(SAFE_CAST(JSON_VALUE(route_attributes, '$.baseDistanceMeters') AS FLOAT64), 1, 0.0) 
      OVER (PARTITION BY JSON_VALUE(route_attributes, '$.route_id') ORDER BY SAFE_CAST(JSON_VALUE(route_attributes, '$.stop_sequence') AS INT64)),
    2
  ) AS segment_distance_meters
FROM 
  `LINKED_DATASET_NAME.historical_travel_time` htt
JOIN 
  `LINKED_DATASET_NAME.routes_status` rs 
  ON htt.selected_route_id = rs.selected_route_id
WHERE 
  htt.record_time BETWEEN '2026-06-01' AND '2026-07-01'
GROUP BY 
  selected_route_id,
  transit_line,
  stop_seq,
  from_stop,
  to_stop,
  route_attributes;
```

---

## 5. Topology-Only Route Segmentation from Road Network on BigQuery (Field-Validated)

> [!IMPORTANT]
> **Scope Clarification**: This section applies strictly to **offline pre-segmentation and topology modeling of custom road network tables in BigQuery** (e.g. Overture, OpenStreetMap, or customer GIS road tables). For **online topology-aware route generation and graph stretching using the live Road Network API (v2)**, use the dedicated skill `rmi-routesetting-preview` instead.

* **Chain by network topology only.** Names are labels only. Don't use angle thresholds and don't impose a length limit; splitting by length is a separate post-processing step (`split_stretched_route(max_length_m, max_segments)`).
* **Rules:**
  * Continue only to segments with the **same priority**, applied on healed data so data blips don't split routes.
  * Require a **symmetric single continuation**: exactly 1 same-priority way out AND exactly 1 way in. Otherwise stop with `AMBIGUOUS_FORK` or `SAME_PRIORITY_MERGE_CONVERGENCE`.
  * Exclude U-turns: 1-hop (heading reversal >= 150°) and **2-hop dual-carriageway crossovers** (A→X→B with X < 60 m, heading reversed >= 150°, ends < 40 m apart). Separate carriageway polylines defeat opposite-ID twin filters.
* **`PRIORITY_AWARE_SPLIT` (user-approved default):**
  * Controlled/limited-access highways split at **every ramp merge/diverge**, so each ramp-to-ramp section can be monitored.
  * Other tiers ignore `LOCAL`/`TERMINAL` side roads and split wherever any other road meets them.
* **Corridor identity boundary:** where expressway-to-expressway connectors carry a lower priority than the expressways, add a name-change stop on controlled-access roads only. Use it as a stop signal, never as a requirement to continue.
* **Route IDs must be content-derived**, e.g. `'sr-<cc>-' || SUBSTR(TO_HEX(MD5(priority||'|'||first_seg||'|'||last_seg)),1,16)`.
  * Rank-based IDs renumbered 99% of routes on rebuild; content IDs kept 99.3–99.7%.
  * The Roads Selection API `selectedRouteId` allows only `[a-zA-Z0-9-]`, 4–63 characters. **No underscores.**
* **Keep demo/prototype route tables as filters of the nationwide table.** Separate chaining logic drifts and overwrites results.
* **Gaps to warn about when rebuilding a network from the dataset:** no turn restrictions (Routes API detoured on ~52–64% of turns Overture flags), no junction IDs, no grade separation, no ramp/link flag.

---

## 6. References

* **SelectedRoute Schema Contract**: [`references/selected_route_schema.json`](references/selected_route_schema.json)
* **Roads Selection API Client & Polyglot Guides**: [`api-roadsselection`](../api-roadsselection/SKILL.md)
* **Routes API v2 Pathfinding**: [`api-routes`](../api-routes/SKILL.md)
* **Roads API v1 Snapping**: [`api-roads-v1`](../api-roads-v1/SKILL.md)
* **Advanced Topology-Aware Route Setting (Preview)**: `rmi-routesetting-preview`
