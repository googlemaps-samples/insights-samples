# Table: routes_status

## 1. Overview
The `routes_status` table contains the definition, current metadata, and operational status for your selected routes. It is the central registry used to filter RMI performance data based on route validity, custom attributes, and lifecycle state.

## 2. Core Definitions
- **Selected Route ID**: The unique identifier for the route, corresponding to the Roads Selection API resource name.
- **Display Name**: A human-readable label provided by the user during route creation.
- **Route Attributes**: Custom JSON or string attributes associated with the route (e.g., region tags, project codes).

## 3. Operational Statuses
| Status | Interpretation |
| :--- | :--- |
| `STATUS_RUNNING` | The route is active and periodically collecting traffic data. |
| `STATUS_INVALID` | The route configuration is invalid (e.g., origin/destination no longer routable). |
| `STATUS_EXPIRED` | The route has reached its predefined expiration date. |

*Note: Status values in this table start with `STATUS_` for consistency with API responses.*

## 4. Technical Behaviors & Facts
- **Filtering**: Only routes in `STATUS_RUNNING` or `STATUS_INVALID` are typically included in this table.
- **Update Frequency**: Metadata and status are updated **every hour, non-stop**.
- **Data Latency**: Up to 1-hour wait for status to reflect changes made via the Roads Selection API.
- **Cleanup**: Once a route is deleted from the API, it is automatically removed from this table within 1 hour.
- **Joining**: This table should be joined with `historical_travel_time` or `recent_roads_data` to map performance metrics back to their physical route definitions.

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
  route_geometry
FROM `routes_status`
WHERE status = 'STATUS_RUNNING'
  AND route_attributes LIKE '%Project:OniGroup%';
```
