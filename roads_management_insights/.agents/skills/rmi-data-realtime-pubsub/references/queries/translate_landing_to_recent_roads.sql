-- Translates raw direct-to-BigQuery Pub/Sub landing records into the production-optimized recent_roads_data structure.
-- Preserves full sub-second precision and converts nested coordinate arrays into native GEOGRAPHY polylines.

SELECT
  selected_route_id,
  display_name,
  -- 1) Convert the custom nested Timestamp block into a single native BigQuery TIMESTAMP (preserving sub-second precision)
  TIMESTAMP_ADD(TIMESTAMP_SECONDS(retrieval_time.seconds), INTERVAL DIV(retrieval_time.nanos, 1000) MICROSECOND) AS record_time,
  
  travel_duration.duration_in_seconds AS duration_in_seconds,
  travel_duration.static_duration_in_seconds AS static_duration_in_seconds,
  
  -- 2) Parse the GeoJSON string route geometry directly into a native BigQuery GEOGRAPHY
  SAFE.ST_GEOGFROMGEOJSON(route_geometry) AS route_geometry,
  
  road_segment_ids,
  
  -- 3) Transform speed reading interval point coordinate sequences into native GEOGRAPHY polylines
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
  `my_project.rmi_realtime.roads_information_landing`
