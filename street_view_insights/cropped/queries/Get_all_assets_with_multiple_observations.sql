-- This query retrieves all observations for a sample of 10 utility pole assets that have multiple observations.
-- It first identifies assets of a specified type that appear more than once in the all_observations table.
-- Then, it fetches the gcs_uri, asset_id, observation_id, detection_time, and location for all observations corresponding to the first 10 of these assets.

-- Define a variable for the asset type to analyze.
DECLARE asset_to_analyze STRING DEFAULT 'ASSET_CLASS_UTILITY_POLE';

-- TODO: Replace '<project_id>' with your project ID and '<dataset_id>' with your dataset ID.
SELECT
  t1.gcs_uri,
  t1.asset_id,
  t1.observation_id,
  t1.detection_time,
  t1.location
FROM
  `<project_id>`.`<dataset_id>`.`all_observations` AS t1
WHERE
  t1.asset_type = asset_to_analyze
  AND t1.asset_id IN (
  SELECT
    asset_id
  FROM
    `<project_id>`.`<dataset_id>`.`all_observations`
  WHERE
    asset_type = asset_to_analyze
  GROUP BY
    asset_id
  HAVING
    COUNT(observation_id) > 1
  ORDER BY
    asset_id  -- Add an ORDER BY for deterministic LIMIT behavior
  LIMIT
    10 );