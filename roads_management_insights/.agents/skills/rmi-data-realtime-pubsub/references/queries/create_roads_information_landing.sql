-- DDL to create the raw direct-to-BigQuery landing table for Pub/Sub subscriptions.
-- Configures daily partitioning on Pub/Sub's native publish_time and clustering on selected_route_id.

CREATE TABLE IF NOT EXISTS `my_project.rmi_realtime.roads_information_landing` (
  selected_route_id STRING OPTIONS(description="The unique identifier for the SelectedRoute resource. Logical primary key. Format: ^[a-zA-Z0-9-]+$, length 4-63."),
  display_name STRING OPTIONS(description="User-provided descriptive name for the route. Non-unique; for human readability."),
  speed_reading_intervals ARRAY<STRUCT<
    interval_coordinates ARRAY<STRUCT<
      latitude FLOAT64,
      longitude FLOAT64
    >>,
    speed STRING
  >> OPTIONS(description="Nested speed reading intervals representing the road density/traffic across the route. Query using LEFT JOIN UNNEST to avoid row dropping."),
  travel_duration STRUCT<
    duration_in_seconds FLOAT64,
    static_duration_in_seconds FLOAT64
  > OPTIONS(description="Travel time information message block containing real-time and static durations."),
  retrieval_time STRUCT<
    seconds INT64,
    nanos INT64
  > OPTIONS(description="The time the road data was collected, represented as a custom Timestamp (seconds and nanos)."),
  route_geometry STRING OPTIONS(description="Contains a GeoJSON polyline string representing the optimal route path determined by the routing engine."),
  road_segment_ids ARRAY<STRING> OPTIONS(description="Place IDs along the route in topological order indicating connected road segments."),
  
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
