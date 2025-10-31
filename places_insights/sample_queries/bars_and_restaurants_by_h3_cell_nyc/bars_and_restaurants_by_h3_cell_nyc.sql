-- Step 2: Join the aggregated counts with the H3 cell boundary for visualization
SELECT
  h3_index,
  `carto-os.carto.H3_BOUNDARY`(h3_index) AS h3_geography,
  bar_count,
  restaurant_count,
  total_count
FROM (
  -- Step 1: Calculate the counts per H3 cell
  SELECT
  WITH
    AGGREGATION_THRESHOLD
    `carto-os.carto.H3_FROMGEOGPOINT`(point, 8) AS h3_index,
    COUNTIF('bar' IN UNNEST(types)) AS bar_count,
    COUNTIF('restaurant' IN UNNEST(types)) AS restaurant_count,
    COUNT(*) AS total_count
  FROM
    `places_insights___us.places`
  WHERE
    -- Filter for NYC
    'New York' IN UNNEST(locality_names)
    AND administrative_area_level_1_name = 'New York'
    -- Pre-filter to only include places that are either a bar or a restaurant for efficiency
    AND ('bar' IN UNNEST(types)
      OR 'restaurant' IN UNNEST(types))
  GROUP BY
    h3_index
)
ORDER BY
  total_count DESC;
