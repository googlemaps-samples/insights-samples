SELECT
  h3_index,
  `carto-os.carto.H3_BOUNDARY`(h3_index) AS h3_geo,
  place_count
FROM (
  SELECT WITH AGGREGATION_THRESHOLD
    `carto-os.carto.H3_FROMGEOGPOINT`(point, 8) AS h3_index,
    COUNT(*) AS place_count
  FROM
    `places_insights___in.places`
  WHERE
    -- First, filter for places within a 10km radius of the specified point
    ST_DWITHIN(point, ST_GEOGPOINT(72.82659778844332, 18.96337985829327), 10000)
    -- Then, filter for only restaurants
    AND primary_type = 'restaurant'
  GROUP BY
    h3_index
)
