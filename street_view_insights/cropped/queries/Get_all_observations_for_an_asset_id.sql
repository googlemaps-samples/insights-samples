-- This query retrieves all observations for a specific asset ID from the 'cropped_observations_latest' table.
-- It returns details such as the snapshot_id, location, detection time, and GCS URI of the observation.
-- Results ordered by recency of when the observation was captured (capture_time).

-- Query Parameters:
--  @asset_id_to_query: ID for the asset (format is t1:a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0a0:a0a0a0a0)

SELECT
  t0.snapshot_id,
  t0.asset_id,
  t0.asset_type,
  t0.location,
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', t0.detection_time) AS formatted_detection_time,
  t0.observation_id,
  t0.bbox,
  t0.camera_pose,
  FORMAT_TIMESTAMP('%Y-%m-%d %H:%M:%S', t0.capture_time) AS formatted_capture_time,
  t0.gcs_uri,
  t0.map_url
FROM
  `cropped_observations_latest` AS t0
WHERE
  t0.asset_id = @asset_id_to_query
ORDER BY
  t0.capture_time DESC;
