-- This query generates a table of S2 cells in Paris, each containing a count of bars.
-- The output is ready for visualization in a heatmap.

-- Step 2: The outer query takes the S2 cell IDs and counts, and generates the actual
-- polygon shape for each cell, which is needed for mapping tools.
SELECT
  s2_cell_id,
  bar_count,
  -- This CARTO function turns the S2 cell ID into a visual geography (a polygon).
  `carto-os.carto.S2_BOUNDARY`(s2_cell_id) AS s2_geography
FROM (
  -- Step 1: The inner query finds all bars in Paris, assigns them to an S2 cell,
  -- and counts how many are in each cell.
  SELECT WITH AGGREGATION_THRESHOLD
    -- S2_CELLIDFROMPOINT groups each place's location into a specific S2 cell.
    -- Level 14 is a good size for city blocks. Higher numbers = smaller cells.
    S2_CELLIDFROMPOINT(point, 14) AS s2_cell_id,
    COUNT(*) AS bar_count
  FROM
    -- We must use the 'fr' table for data in France.
    `places_insights___fr.places`
  WHERE
    -- Filter down to the city of Paris.
    locality.name = 'Paris'
    -- And select only places that have 'bar' in their list of types.
    AND 'bar' IN UNNEST(types)
  GROUP BY
    s2_cell_id
)
ORDER BY
  bar_count DESC;
