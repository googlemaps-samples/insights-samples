-- Translates raw direct-to-BigQuery Pub/Sub landing records into the production-optimized recent_roads_data structure.
-- Preserves full sub-second precision and converts nested coordinate arrays into native GEOGRAPHY polylines.
-- Supports both legacy and October 8, 2026 schema revisions via COALESCE logic.

SELECT
  selected_route_id,
  display_name,
  -- 1) Reconstruct UTC record timestamp using COALESCE: prefer new RFC 3339 retrieval_timestamp, fallback to legacy retrieval_time
  COALESCE(
    retrieval_timestamp,
    TIMESTAMP_ADD(TIMESTAMP_SECONDS(retrieval_time.seconds), INTERVAL DIV(retrieval_time.nanos, 1000) MICROSECOND)
  ) AS record_time,
  
  -- 2) Duration metrics using COALESCE: prefer top-level fields, fallback to legacy travel_duration block
  COALESCE(duration_in_seconds, travel_duration.duration_in_seconds) AS duration_in_seconds,
  COALESCE(static_duration_in_seconds, travel_duration.static_duration_in_seconds) AS static_duration_in_seconds,
  
  -- 3) Road closure status (omits duration and offsets when true)
  COALESCE(has_road_closure, FALSE) AS has_road_closure,
  
  -- 4) Parse the GeoJSON string route geometry directly into a native BigQuery GEOGRAPHY
  SAFE.ST_GEOGFROMGEOJSON(route_geometry) AS route_geometry,
  
  road_segment_ids,
  
  -- 5) Offset-based speed readings (new as of Oct 8, 2026; supports TRAFFIC_JAM_HEAVY)
  speed_reading_offsets,
  
  -- 6) Transform legacy speed reading interval point coordinate sequences into native GEOGRAPHY polylines (retained for backward compatibility)
  ARRAY(
    SELECT AS STRUCT
      -- Construct a single Linestring polyline from the array of points, wrapped in an array to match the REPEATED GEOGRAPHY field layout
      [ST_MAKELINE(ARRAY(
        SELECT ST_GEOGPOINT(CAST(coord.longitude AS FLOAT64), CAST(coord.latitude AS FLOAT64))
        FROM UNNEST(interv.interval_coordinates) AS coord
      ))] AS interval_coordinates,
      interv.speed AS speed
    FROM UNNEST(speed_reading_intervals) AS interv
  ) AS speed_reading_intervals
FROM
  `my_project.rmi_realtime.roads_information_landing`;