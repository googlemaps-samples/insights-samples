-- This query retrieves all observations for a specific asset ID from the all_observations table.
-- It returns details such as the snapshot_id, location, detection time, and GCS URI of the observation.

-- Define a variable for the asset ID to query.
DECLARE asset_id_to_query STRING DEFAULT 'your_specific_asset_id';

-- TODO: Replace '<project_id>' with your project ID and '<dataset_id>' with your dataset ID.
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
  `<project_id>`.`<dataset_id>`.`all_observations` AS t0
WHERE
  t0.asset_id = asset_id_to_query
ORDER BY
  t0.detection_time DESC;
