-- This query creates a high-resolution density map of pubs within the official Overture Maps boundary for London.

-- Step 1: Declare a variable to hold the geometry of London.
DECLARE london_boundary GEOGRAPHY;

-- Step 2: Set the variable by querying the Overture Maps public dataset for London's shape.
-- The subquery ensures we get a single GEOGRAPHY value. We add LIMIT 1 as a safeguard.
SET london_boundary = (
  SELECT
  ST_MAKEPOLYGON(ST_EXTERIORRING(geometry)) as geometry
  FROM `bigquery-public-data.overture_maps.division_area` area , unnest (names.common.key_value) kv
  WHERE
  country = 'GB' and class="land"
  and (kv.key="en" and kv.value = "London")

);
-- Step 3: Use a Common Table Expression (CTE) to find all pubs inside the London boundary
-- and calculate their H3 index.
WITH pubs_in_london AS (
  SELECT
    -- For each pub's geographic point, calculate its corresponding H3 index at resolution 7.
    `carto-os.carto.H3_FROMGEOGPOINT`(point, 7) as h3_index
  FROM
    -- CRITICAL: We must use the 'gb' table for the United Kingdom.
    `places_insights___gb.places`
  WHERE
    -- Filter 1: The place must be a 'pub'.
    'pub' IN UNNEST(types)
    -- Filter 2: The place's point must be geographically contained within the London boundary we just defined.
    AND ST_CONTAINS(london_boundary, point)
)

-- Step 4: Aggregate the results from the CTE to get the final counts and cell geometries.
SELECT WITH AGGREGATION_THRESHOLD
  -- The H3 cell identifier.
  h3_index,
  
  -- The total count of pubs found within this cell.
  COUNT(*) AS pub_count,
  
  -- This function takes the H3 index and returns its actual hexagonal polygon shape for visualization.
  `carto-os.carto.H3_BOUNDARY`(h3_index) AS h3_geography
FROM
  pubs_in_london
GROUP BY
  -- Group by the H3 index to count how many pubs fall into each unique cell.
  h3_index
ORDER BY
  -- Show the most dense pub areas first.
  pub_count DESC;
