-- This query creates a high-resolution density map of tourist attractions within the official Overture Maps boundary for Paris.

-- Step 1: Declare a variable to hold the GEOGRAPHY of Paris.
DECLARE paris_boundary GEOGRAPHY;

-- Step 2: Set the variable by querying the Overture Maps public dataset for Paris's shape.
-- The subquery ensures we get a single GEOGRAPHY value.
SET paris_boundary = (
  SELECT geometry FROM `bigquery-public-data.overture_maps.division_area`
  WHERE country = 'FR' AND names.primary = 'Paris'
  LIMIT 1
);
-- Step 3: Use a Common Table Expression (CTE) to find all tourist attractions inside the Paris boundary
-- and calculate their H3 index.
WITH attractions_in_paris AS (
  SELECT
    -- For each attraction's geographic point, calculate its corresponding H3 index.
    -- Resolution 9 is a good size for city analysis.
    `carto-os.carto.H3_FROMGEOGPOINT`(point, 9) as h3_index
  FROM
    -- We must use the 'fr' table for data in France.
    `places_insights___fr.places`
  WHERE
    -- Filter 1: The place must be a 'tourist_attraction'. THIS IS THE LINE WE CHANGED.
    'tourist_attraction' IN UNNEST(types)
    -- Filter 2: The place's point must be geographically contained within the Paris boundary we just defined.
    AND ST_CONTAINS(paris_boundary, point)
)

-- Step 4: Aggregate the results from the CTE to get the final counts and cell geometries.
SELECT WITH AGGREGATION_THRESHOLD
  -- The H3 cell identifier.
  h3_index,
  -- The total count of tourist attractions found within this cell.
  COUNT(*) AS tourist_attraction_count,
  -- This function takes the H3 index and returns its actual hexagonal polygon shape for visualization.
  `carto-os.carto.H3_BOUNDARY`(h3_index) AS h3_geography
FROM
  attractions_in_paris
GROUP BY
  -- Group by the H3 index to count how many attractions fall into each unique cell.
  h3_index
ORDER BY
  -- Show the most dense tourist areas first.
  tourist_attraction_count DESC;
