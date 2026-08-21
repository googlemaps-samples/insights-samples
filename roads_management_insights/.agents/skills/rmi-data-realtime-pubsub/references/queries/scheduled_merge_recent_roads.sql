-- ====================================================================================
-- BigQuery Scheduled Query - Option B: Incremental MERGE Translation Pipeline
-- ====================================================================================
-- Description:
--   Transforms raw landing payloads from 'roads_information_landing' into the
--   production-optimized 'recent_roads_data' table on a periodic schedule.
--   Performs in-flight timestamp reconstruction, GeoJSON coordinate sequence parsing
--   into native GEOGRAPHY polylines, and inline deduplication.
--
-- Setup & Configuration Guide (Google Cloud Console / bq CLI):
--   1. Destination Table: Select "None" (the MERGE statement handles target insertion/updating).
--   2. Write Preference: Not applicable for MERGE queries.
--   3. Query Schedule: Set to run periodically (e.g., "Every 10 minutes" or "Every 15 minutes").
--   4. Service Account: Ensure the service account running this scheduled query holds
--      "BigQuery Data Editor" on the target dataset and "BigQuery Job User" on the project.
-- ====================================================================================

MERGE `my_project.rmi_realtime.recent_roads_data` T
USING (
  WITH raw_dedup AS (
    SELECT
      selected_route_id,
      display_name,
      -- Reconstruct UTC timestamp with microsecond precision from custom Timestamp nested fields
      TIMESTAMP_ADD(TIMESTAMP_SECONDS(retrieval_time.seconds), INTERVAL DIV(retrieval_time.nanos, 1000) MICROSECOND) AS record_time,
      travel_duration.duration_in_seconds AS duration_in_seconds,
      travel_duration.static_duration_in_seconds AS static_duration_in_seconds,
      SAFE.ST_GEOGFROMGEOJSON(route_geometry) AS route_geometry,
      road_segment_ids,
      speed_reading_intervals,
      publish_time,
      -- Deduplicate within the batch (keeps only the most recent Pub/Sub message in case of duplicates)
      ROW_NUMBER() OVER (
        PARTITION BY selected_route_id, retrieval_time.seconds 
        ORDER BY publish_time DESC
      ) AS rn
    FROM
      `my_project.rmi_realtime.roads_information_landing`
    WHERE
      -- Watermark: Restrict scan to the last 1 hour of landed data to minimize query costs and keep execution fast.
      -- Adjust the interval duration (e.g., 2 HOUR) if your scheduled query runs less frequently.
      publish_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
  )
  SELECT
    selected_route_id,
    display_name,
    record_time,
    duration_in_seconds,
    static_duration_in_seconds,
    route_geometry,
    road_segment_ids,
    ARRAY(
      SELECT AS STRUCT
        -- Construct a single Linestring polyline from the array of point coordinates
        [ST_MAKELINE(ARRAY(
          SELECT ST_GEOGPOINT(CAST(coord.longitude AS FLOAT64), CAST(coord.latitude AS FLOAT64))
          FROM UNNEST(interv.interval_coordinates) AS coord
        ))] AS interval_coordinates,
        interv.speed AS speed
      FROM UNNEST(speed_reading_intervals) AS interv
    ) AS speed_reading_intervals
  FROM raw_dedup
  WHERE rn = 1
) S
ON T.selected_route_id = S.selected_route_id AND T.record_time = S.record_time
WHEN NOT MATCHED THEN
  INSERT (selected_route_id, display_name, record_time, duration_in_seconds, static_duration_in_seconds, route_geometry, road_segment_ids, speed_reading_intervals)
  VALUES (selected_route_id, display_name, record_time, duration_in_seconds, static_duration_in_seconds, route_geometry, road_segment_ids, speed_reading_intervals);
