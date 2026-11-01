-- DDL to create the raw direct-to-BigQuery landing table for Pub/Sub subscriptions.
-- Configures daily partitioning on Pub/Sub's native publish_time and clustering on selected_route_id.
-- Updated for October 8, 2026 schema evolution (deprecation cutoff January 13, 2027).

CREATE TABLE IF NOT EXISTS `my_project.rmi_realtime.roads_information_landing` (
  selected_route_id STRING OPTIONS(description="The unique identifier for the SelectedRoute resource. Logical primary key. Format: ^[a-zA-Z0-9-]+$, length 4-63."),
  display_name STRING OPTIONS(description="User-provided descriptive name for the route. Non-unique; for human readability."),
  speed_reading_intervals ARRAY<STRUCT<
    interval_coordinates ARRAY<STRUCT<
      latitude FLOAT64,
      longitude FLOAT64
    >>,
    speed STRING
  >> OPTIONS(description="Legacy nested speed reading intervals. Deprecated in favor of speed_reading_offsets; sunset Jan 13, 2027."),
  travel_duration STRUCT<
    duration_in_seconds FLOAT64,
    static_duration_in_seconds FLOAT64
  > OPTIONS(description="Legacy travel time block containing real-time and static durations. Deprecated in favor of top-level duration_in_seconds and static_duration_in_seconds; sunset Jan 13, 2027."),
  retrieval_time STRUCT<
    seconds INT64,
    nanos INT64
  > OPTIONS(description="Legacy collection time as custom Timestamp (seconds and nanos). Deprecated in favor of retrieval_timestamp; sunset Jan 13, 2027."),
  route_geometry STRING OPTIONS(description="Contains a GeoJSON polyline string representing the optimal route path determined by the routing engine."),
  road_segment_ids ARRAY<STRING> OPTIONS(description="Place IDs along the route in topological order indicating connected road segments."),
  
  -- New fields (effective October 8, 2026; deprecation cutoff January 13, 2027)
  speed_reading_offsets ARRAY<STRUCT<
    start_offset INT64,
    end_offset INT64,
    speed STRING
  >> OPTIONS(description="Speed reading intervals defined by linear distance offsets along route polyline (in meters). Speeds: NORMAL, SLOW, TRAFFIC_JAM, TRAFFIC_JAM_HEAVY. Omitted when has_road_closure is true."),
  duration_in_seconds FLOAT64 OPTIONS(description="Real-time travel duration in seconds. Omitted when has_road_closure is true."),
  static_duration_in_seconds FLOAT64 OPTIONS(description="Traffic-unaware baseline travel duration in seconds under free-flow conditions."),
  retrieval_timestamp TIMESTAMP OPTIONS(description="RFC 3339 formatted UTC timestamp indicating when road data was retrieved."),
  has_road_closure BOOL OPTIONS(description="True if route has a full road closure; duration_in_seconds and speed_reading_offsets are omitted when true."),
  
  -- Pub/Sub direct-to-BigQuery subscription metadata fields
  subscription_name STRING OPTIONS(description="Pub/Sub metadata: Name of the subscription that delivered the message."),
  message_id STRING OPTIONS(description="Pub/Sub metadata: Unique identifier of the delivered message, useful for deduplication."),
  publish_time TIMESTAMP OPTIONS(description="Pub/Sub metadata: UTC timestamp representing when the message was published to the topic. Configured as the partitioning column."),
  attributes STRING OPTIONS(description="Pub/Sub metadata: JSON-formatted string of any user-defined message attributes.")
)
PARTITION BY DATE(publish_time)
CLUSTER BY selected_route_id
OPTIONS(
  description="Raw landing table for Google Maps Roads Management Insights (RMI) Pub/Sub subscription direct-to-BigQuery ingestion. Configured with daily partitioning on publish_time and clustered on selected_route_id."
);