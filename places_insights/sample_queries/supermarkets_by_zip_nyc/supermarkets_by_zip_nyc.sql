-- This query counts the number of supermarkets in each ZIP code in New York City.
-- STEP 1: Join places to ZIP code boundaries, filter for New York City and the place type,
-- and then perform the aggregation.
WITH counts_in_zip_boundaries AS (
  SELECT WITH AGGREGATION_THRESHOLD
    zip_boundaries.zip_code AS zip_code,
    COUNT(places_table.id) AS supermarket_count
  FROM
    -- Start with the public table of ZIP code shapes
    `bigquery-public-data.geo_us_boundaries.zip_codes` AS zip_boundaries
  JOIN
    -- Join to the Places Insights data
    `places_insights___us.places` AS places_table
    -- The join condition finds which ZIP code polygon each place's point is inside
    ON ST_CONTAINS(zip_boundaries.zip_code_geom, places_table.point)
  WHERE
    -- Use the precise filter on the public boundaries table
    zip_boundaries.state_code = 'NY'
    AND zip_boundaries.city = 'New York city'
    -- And filter for places that are supermarkets
    AND 'supermarket' IN UNNEST(places_table.types)
  GROUP BY
    -- We group by the column from the public table
    zip_boundaries.zip_code
)

-- STEP 2: Now, join the aggregated counts back to the boundaries table a second time
-- to retrieve the geometry for mapping.
SELECT
  counts.zip_code,
  counts.supermarket_count,
  -- We simplify the geometry to make it render faster in visualization tools.
  ST_SIMPLIFY(zip_boundaries_2.zip_code_geom, 100) AS geography
FROM
  counts_in_zip_boundaries AS counts
JOIN
  `bigquery-public-data.geo_us_boundaries.zip_codes` AS zip_boundaries_2
  ON counts.zip_code = zip_boundaries_2.zip_code
ORDER BY
  supermarket_count DESC;
