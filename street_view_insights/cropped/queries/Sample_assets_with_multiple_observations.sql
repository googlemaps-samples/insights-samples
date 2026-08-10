-- This query retrieves observations from the lates for a sample of 10 utility pole assets that have multiple observations.
-- It first identifies assets of a specified type that appear more than once in the all_observations table.

-- Query Parameters:
--  @asset_to_analyze: asset type to analyze (ASSET_CLASS_UTILITY_POLE, ASSET_CLASS_ROAD_SIGN, ASSET_CLASS_MAINTENANCE_COVERS)

SELECT
  t1.asset_id,
  t1.detection_time,
  t1.observation_id,
  t1.capture_time,
  t1.location,
  t1.gcs_uri
FROM
  `cropped_observations_latest` AS t1
WHERE
  t1.asset_id IN (
  SELECT
    asset_id
  FROM
    `cropped_observations_latest`
  WHERE
    asset_type = @asset_to_analyze
  GROUP BY
    asset_id
  HAVING
    COUNT(observation_id) > 1
  ORDER BY
    asset_id  -- Add an ORDER BY for deterministic LIMIT behavior
  LIMIT
    10
  );
