-- DDL to create the production-optimized recent_roads_data table.
-- Configures daily partitioning on record_time and clustering on selected_route_id.
-- Updated for October 8, 2026 schema evolution (deprecation cutoff January 13, 2027).

CREATE TABLE IF NOT EXISTS `my_project.rmi_realtime.recent_roads_data` (
  selected_route_id STRING OPTIONS(description="The unique identifier for the SelectedRoute resource. Logical primary key."),
  display_name STRING OPTIONS(description="User-provided descriptive name for the route."),
  record_time TIMESTAMP OPTIONS(description="The UTC timestamp representing when the road data was collected, fully reconstructed with microsecond precision via COALESCE."),
  duration_in_seconds FLOAT64 OPTIONS(description="The near real-time traffic-aware duration of the route in seconds. Omitted/NULL when has_road_closure is true."),
  static_duration_in_seconds FLOAT64 OPTIONS(description="The traffic-unaware (static) duration of the route in seconds under free-flow conditions."),
  has_road_closure BOOL OPTIONS(description="Indicates whether the route is subject to a full road closure. When true, duration_in_seconds and speed_reading_offsets are omitted."),
  route_geometry GEOGRAPHY OPTIONS(description="The actual optimal path determined by the routing engine as a native GEOGRAPHY polyline."),
  road_segment_ids ARRAY<STRING> OPTIONS(description="Place IDs along the route in topological order indicating connected road segments."),
  speed_reading_offsets ARRAY<STRUCT<
    start_offset INT64,
    end_offset INT64,
    speed STRING
  >> OPTIONS(description="Linear distance offset intervals in meters along polyline. Speeds: NORMAL, SLOW, TRAFFIC_JAM, TRAFFIC_JAM_HEAVY. Omitted when has_road_closure is true."),
  speed_reading_intervals ARRAY<STRUCT<
    interval_coordinates ARRAY<GEOGRAPHY>,
    speed STRING
  >> OPTIONS(description="Legacy repeated RECORD containing road sub-segments categorized by traffic speed boundaries (deprecated; retained for backward compatibility).")
)
PARTITION BY DATE(record_time)
CLUSTER BY selected_route_id
OPTIONS(
  description="Production-optimized downstream recent_roads_data table for Roads Management Insights (RMI) real-time analytics. Transformed from raw landing table to parse timestamps, support linear speed_reading_offsets, and represent coordinates as native GEOGRAPHY types."
);