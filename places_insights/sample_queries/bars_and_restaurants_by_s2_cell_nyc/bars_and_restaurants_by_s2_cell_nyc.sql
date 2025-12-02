-- Step 2: Join the aggregated counts with the S2 cell boundary for visualization
SELECT
  s2_cell_id,
  -- Use the stable CARTO function to get the S2 cell's geography
  `carto-os.carto.S2_BOUNDARY`(s2_cell_id) AS s2_geography,
  bar_count,
  restaurant_count,
  total_count
FROM (
  -- Step 1: Calculate the counts per S2 cell
  SELECT
  WITH
    AGGREGATION_THRESHOLD
    -- Get the S2 Cell ID at level 14 for each place's point
    S2_CELLIDFROMPOINT(point, 14) AS s2_cell_id,
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
    s2_cell_id
)
ORDER BY
  total_count DESC;
