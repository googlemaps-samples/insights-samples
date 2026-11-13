# Table: routes_status

## 1. Overview

The `routes_status` table contains the complete definition, topological representation, and operational lifecycle status for all registered selected routes. It serves as the authoritative, high-efficiency route extraction and discovery registry across your monitored network. With the inclusion of full waypoints (`origin`, `destination`, `intermediates`), polyline geography (`static_route_geometry`), road segment Place IDs (`road_segment_ids`), and routing behavior (`dynamic_routing`), `routes_status` supersedes repetitive REST API `selectedRoutes.list` calls, enabling instant multi-criteria filtering, spatial indexing, and corridor discovery directly within BigQuery without API rate limits or pagination latency.

## 2. Core Definitions

- **Selected Route ID (`selected_route_id`)**: The unique identifier for the route, corresponding to the Roads Selection API resource name.
- **Display Name (`display_name`)**: A human-readable label provided during route creation.
- **Status (`status`)**: Operational lifecycle state of the route (`STATUS_RUNNING`, `STATUS_INVALID`, `STATUS_EXPIRED`).
- **Validation Error (`validation_error`)**: Error description if the route configuration failed validation.
- **Low Road Usage Start Time (`low_road_usage_start_time`)**: Timestamp when low road usage / traffic data shortage was first detected.
- **Route Attributes (`route_attributes`)**: Custom serialized JSON string containing user-defined metadata (e.g., tier, region, corridor type).
- **Dynamic Routing (`dynamic_routing`)**: Boolean indicating whether the route is dynamic (`true`) or fixed (`false`).
- **Origin (`origin`)**: Origin waypoint coordinate of the route as a BigQuery `GEOGRAPHY` point.
- **Destination (`destination`)**: Destination waypoint coordinate of the route as a BigQuery `GEOGRAPHY` point.
- **Intermediates (`intermediates`)**: Repeated array of intermediate waypoint coordinates along the route as `GEOGRAPHY` points.
- **Static Route Geometry (`static_route_geometry`)**: The polyline geometry of the static route calculated without live traffic from the waypoints.
- **Road Segment IDs (`road_segment_ids`)**: Repeated array of Place IDs representing topological road segments along the static route calculated without live traffic. For fixed routes (`dynamic_routing: false`), Place IDs automatically update to reflect changes in Google's road network; for dynamic routes (`dynamic_routing: true`), they are not updated.

## 3. Operational Statuses

| Status | Interpretation |
| :--- | :--- |
| `STATUS_RUNNING` | The route is active and periodically collecting traffic data. |
| `STATUS_INVALID` | The route configuration is invalid (e.g., origin/destination no longer routable). |
| `STATUS_EXPIRED` | The route has reached its predefined expiration date. |

*Note: Status values in this table start with `STATUS_` for consistency with API responses.*

## 4. Technical Behaviors & Facts

- **Authoritative Route Extraction & Discovery Engine**: Supersedes repetitive REST API `selectedRoutes.list` calls for route inventory discovery. Enables zero-quota multi-criteria queries slicing routes by spatial intersections (`ST_INTERSECTS`, `ST_DWITHIN`), name prefixes (`display_name LIKE ...`), JSON attributes (`JSON_EXTRACT_SCALAR`), dynamic routing mode (`dynamic_routing`), and traversed segment Place IDs (`UNNEST(road_segment_ids)`).
- **Filtering**: Only routes in `STATUS_RUNNING` or `STATUS_INVALID` are typically included in this table.
- **Update Frequency**: Metadata and status are updated **every hour, non-stop**.
- **Data Latency**: Up to 1-hour wait for status to reflect changes made via the Roads Selection API.
- **Cleanup**: Once a route is deleted from the API, it is automatically removed from this table within 1 hour.
- **Joining**: This table should be joined with `historical_travel_time` or `recent_roads_data` to map performance metrics back to their physical route definitions.
- **Road Segment IDs Maintenance**: For fixed routes (`dynamic_routing: false`), the Place IDs in `road_segment_ids` automatically update to reflect changes in Google's road network while still representing the same route. For dynamic routes (`dynamic_routing: true`), `road_segment_ids` is not updated.

## 5. Usage Example: Identifying Invalid Routes

```sql
-- List all routes that are currently failing validation
SELECT 
  selected_route_id,
  display_name,
  validation_error,
  low_road_usage_start_time
FROM `routes_status`
WHERE status = 'STATUS_INVALID'
ORDER BY low_road_usage_start_time DESC;
```

## 6. Usage Example: Filtering by Custom Attribute

```sql
-- Filter active routes belonging to a specific internal project
SELECT 
  selected_route_id,
  display_name,
  static_route_geometry
FROM `routes_status`
WHERE status = 'STATUS_RUNNING'
  AND route_attributes LIKE '%Project:OniGroup%';
```

## 7. Usage Example: Spatial Corridor Extraction and Segment Traversal

Querying `routes_status` directly in BigQuery replaces calling `selectedRoutes.list` over REST. This query extracts active, fixed corridors intersecting a municipal bounding polygon and traversing a key highway segment:

```sql
-- Extract corridors intersecting a bounding polygon and traversing a specific road segment
SELECT 
  selected_route_id,
  display_name,
  dynamic_routing,
  JSON_EXTRACT_SCALAR(route_attributes, '$.corridor_type') AS corridor_type,
  ST_LENGTH(static_route_geometry) AS length_meters,
  road_segment_ids
FROM `routes_status`
WHERE status = 'STATUS_RUNNING'
  AND dynamic_routing = FALSE
  AND display_name LIKE 'corridor-boston-%'
  -- Spatial boundary filtering with BigQuery GIS
  AND ST_INTERSECTS(
    static_route_geometry,
    ST_GEOGFROMTEXT('POLYGON((-71.12 42.32, -71.02 42.32, -71.02 42.40, -71.12 42.40, -71.12 42.32))')
  )
  -- Segment traversal filtering
  AND EXISTS (
    SELECT 1 
    FROM UNNEST(road_segment_ids) AS seg 
    WHERE seg = 'ChIJ25e1g4hw44kR5UfM8pY61-E'
  )
ORDER BY length_meters DESC;
```
