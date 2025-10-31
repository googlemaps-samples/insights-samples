-- STEP 1: Create a temporary table of all São Paulo macrohood boundaries.
WITH neighborhood_geometries AS (
  SELECT
    neighborhoods.id,
    neighborhoods.names.primary AS macrohood_name,
    neighborhoods.geometry AS macrohood_geography
  FROM
    `bigquery-public-data.overture_maps.division_area` AS neighborhoods
  WHERE
    neighborhoods.subtype = 'macrohood'
    AND ST_CONTAINS(
      (
        SELECT geometry FROM `bigquery-public-data.overture_maps.division_area`
        WHERE country = 'BR'
          AND region = 'BR-SP'
          AND subtype = 'locality'
          AND names.primary = 'São Paulo'
        LIMIT 1
      ),
      neighborhoods.geometry
    )
),

-- STEP 2: Perform the join and aggregation. This CTE calculates the counts.
counts_by_neighborhood AS (
  SELECT WITH AGGREGATION_THRESHOLD
    -- We only select the columns we can group by: the neighborhood's ID and name.
    neighborhoods.id AS neighborhood_id,
    neighborhoods.macrohood_name,
    -- Perform the count of restaurants for each group.
    COUNT(restaurants.id) AS restaurant_count
  FROM
    -- We start from the boundaries we defined in the first CTE.
    neighborhood_geometries AS neighborhoods
  JOIN
    -- Join to the Brazil Places Insights data.
    `places_insights___br.places` AS restaurants
    ON ST_CONTAINS(neighborhoods.macrohood_geography, restaurants.point)
  WHERE
    -- Filter for restaurants.
    'restaurant' IN UNNEST(restaurants.types)
  GROUP BY
    neighborhoods.id,
    neighborhoods.macrohood_name
)

-- STEP 3: Join the calculated counts back to the geometries to create the final output.
SELECT
  counts.macrohood_name,
  counts.restaurant_count,
  
  -- Now we retrieve the geometry by joining on the ID, and we can safely simplify it for mapping.
  ST_SIMPLIFY(geometries.macrohood_geography, 100) AS geography_for_map
FROM
  -- Start with our table of counts.
  counts_by_neighborhood AS counts
JOIN
  -- Join back to our table of geometries using the unique ID.
  neighborhood_geometries AS geometries
  ON counts.neighborhood_id = geometries.id
ORDER BY
  -- Order the results to show the most dense restaurant areas first.
  restaurant_count DESC;
