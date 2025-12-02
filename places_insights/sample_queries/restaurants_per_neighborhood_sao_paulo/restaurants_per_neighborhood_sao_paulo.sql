-- This query counts restaurants per neighborhood in São Paulo using the built-in address components.
-- NOTE: This produces a table of counts but does not include neighborhood geometries for mapping.

SELECT WITH AGGREGATION_THRESHOLD
  -- Access the .name field directly from the sublocality_level_1 record.
  sublocality_level_1.name AS neighborhood_name,
  -- The total count of restaurants found in that neighborhood.
  COUNT(*) AS restaurant_count
FROM
  -- The FROM clause now only needs the main table.
  `places_insights___br.places`
WHERE
  -- Filter 1: The place must be a 'restaurant'.
  'restaurant' IN UNNEST(types)
  -- Filter 2: The place must be located within the city of São Paulo.
  AND administrative_area_level_2.name = 'São Paulo'
GROUP BY
  -- Group by the neighborhood name to get the count for each one.
  neighborhood_name
ORDER BY
  -- Show the neighborhoods with the most restaurants first.
  restaurant_count DESC;
