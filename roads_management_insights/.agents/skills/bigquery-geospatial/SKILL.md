---
name: bigquery-geospatial
description: Expert guidance on BigQuery Geospatial (GIS) capabilities. Use this skill when the user asks about GEOGRAPHY types, spatial functions (ST_*), proximity analysis, spatial joins, or spatial indexing (S2/H3/Quadbin) in BigQuery.
dependencies:
  - bigquery-practices
---

# BigQuery Geospatial (GIS)

BigQuery supports `GEOGRAPHY` as a native data type and provides a suite of `ST_*` functions for geospatial analysis.

## Core Functions & Indexing

### 1. Native S2 Indexing
BigQuery uses the **S2 Geometry Library** for internal spatial indexing. 
- While native S2 function support is limited (e.g., `S2_CELLIDFROMPOINT`), the engine automatically leverages S2 cells to optimize spatial joins (`ST_INTERSECTS`) and proximity searches (`ST_DWITHIN`).
- Clustering a table by a `GEOGRAPHY` column organizes data by S2 cell, which is critical for query performance.

### 2. Proximity & Distance
- `ST_DWITHIN(geog1, geog2, distance_meters)`: Returns TRUE if the distance between two geographies is within the specified meters. **Highly recommended for spatial filtering.**
- `ST_DISTANCE(geog1, geog2)`: Returns the shortest distance in meters between two geographies.

### 3. Geometry Creation & Predicates
- `ST_GEOGPOINT(longitude, latitude)`, `ST_GEOGFROMTEXT(wkt)`, `ST_GEOGFROMGEOJSON(json)`.
- `ST_CONTAINS`, `ST_INTERSECTS`, `ST_COVERS`, `ST_DISJOINT`.

## Expert Tips & Performance Tuning

### 1. Optimize Spatial Outer Joins (The Two-Join Trick)
BigQuery's optimizer is highly specialized for **INNER** spatial joins. Direct `LEFT OUTER JOIN` on spatial predicates can be slow.
- **The Trick**: Perform a spatial **INNER JOIN** first, aggregate the results (e.g., `COUNT`), and then **LEFT JOIN** that result back to your original table using a standard ID. This forces the use of the spatial index.

### 2. Subdivide "Heavy" Geometries
Extremely complex polygons (thousands of vertices) can slow down joins and hit memory limits.
- **The Trick**: Break large polygons into smaller, simpler pieces (e.g., using an `ST_Subdivide` pattern) at ingestion time. BigQuery's S2-based index handles many simple polygons much faster than one massive one.

### 3. Efficient Nearest Neighbor (Iterative Search)
Avoid full cross-joins for nearest neighbor searches.
- **The Trick**: Use BigQuery Scripting with a `WHILE` loop. Start with a small `ST_DWITHIN` radius. If no results are found, increase the radius and repeat.

### 4. Grouping by Geography
BigQuery does not allow `GROUP BY` on a `GEOGRAPHY` column.
- **The Trick**: Group by a unique identifier (ID or S2/H3 cell) and use **`ANY_VALUE(geog_column)`** to retrieve the geography.

### 5. Localized Regional Buffer Clipping (Excluding Fragmented Islands / Sub-regions)
Administrative boundaries for a region can sometimes contain distant fragments (e.g., islands or outer exclaves) that are irrelevant to the target urban center. Using pure administrative boundaries in these cases results in overly large bounding boxes and wastes API query limits / processing resource.
- **The Solution**: Intersect (`ST_INTERSECTION`) the administrative geometry aggregates with a localized `ST_BUFFER` around the primary urban centroid.
- **Interactive Multi-Version Visual Comparison Design**:
  When a highly fragmented region is detected (i.e., bounding box is $>5\times$ larger than the actual land area), generate and display a comparative markdown carousel presenting the raw option along with multiple suggested simplifications testing different thresholds to adapt to different target geographies:
  1. **Original Boundary**: The complete raw administrative region (no fragments omitted).
  2. **Suggested Simplified (Version A - Conservative Filtering)**: Tests a tight size threshold (e.g., discarding parts $< 0.1\%$ of dominant landmass area) and a loose distance buffer. Excellent for archipelago-dense urban environments (e.g., Osaka, Seattle).
  3. **Suggested Simplified (Version B - Moderate Filtering)**: Tests a moderate size threshold (e.g., discarding parts $< 1\%$ of dominant landmass area) and a scale-aware distance buffer.
  4. **Suggested Simplified (Version C - Aggressive Filtering / Centroid Buffer)**: Tests an aggressive threshold (e.g., discarding parts $< 5\%$) or applies a fixed radial mainland buffer (e.g., 25km circular clip from center point). Ideal for mainland-isolated cities (e.g., Jakarta, Melbourne).
  
  The user is presented with a visual preview of each version side-by-side (rendered via static maps) to choose the best configuration interactively.
- **Example (Clipped Jakarta Mainland Ingestion via Centroid Buffer)**:
  ```sql
  WITH raw_data AS (
    SELECT geometry FROM `my_project.my_dataset.regional_boundaries` WHERE region_code = "ID-JK"
  ),
  unified AS (
    SELECT 
      ST_INTERSECTION(
        ST_UNION_AGG(geometry),
        ST_BUFFER(ST_GEOGPOINT(106.83423619852961, -6.206387954448808), 25000) -- 25km mainland buffer
      ) as boundary_geom 
    FROM raw_data
  )
  ```

### 6. Equal-Length Line Slicing via JavaScript UDF
When corridor route segments exceed a maximum length threshold (e.g. 0.5 miles / 804.672m), BigQuery SQL can slice a `GEOGRAPHY` LineString into $N$ equal parts while interpolating intermediate points and keeping original internal vertices.
- **JavaScript UDF Pattern**:
  ```sql
  CREATE OR REPLACE FUNCTION `my_project.my_dataset.slice_line_geojson`(geojson STRING, N INT64)
  RETURNS ARRAY<STRING>
  LANGUAGE js AS """
  if (!geojson || N <= 0) return [];
  const geom = JSON.parse(geojson);
  if (geom.type !== "LineString" || !geom.coordinates || geom.coordinates.length < 2) return [geojson];
  const coords = geom.coordinates;

  function haversine(p1, p2) {
    const R = 6371008.8; // meters
    const dLat = (p2[1] - p1[1]) * Math.PI / 180;
    const dLon = (p2[0] - p1[0]) * Math.PI / 180;
    const a = Math.sin(dLat/2) * Math.sin(dLat/2) +
              Math.cos(p1[1] * Math.PI / 180) * Math.cos(p2[1] * Math.PI / 180) *
              Math.sin(dLon/2) * Math.sin(dLon/2);
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
  }

  let totalLen = 0;
  const dists = [0];
  for (let i = 0; i < coords.length - 1; i++) {
    const d = haversine(coords[i], coords[i+1]);
    totalLen += d;
    dists.push(totalLen);
  }

  if (N === 1 || totalLen === 0) return [geojson];

  function getPointAtDist(targetD) {
    if (targetD <= 0) return coords[0];
    if (targetD >= totalLen) return coords[coords.length - 1];
    for (let i = 0; i < dists.length - 1; i++) {
      if (targetD >= dists[i] && targetD <= dists[i+1]) {
        const segLen = dists[i+1] - dists[i];
        if (segLen === 0) return coords[i];
        const t = (targetD - dists[i]) / segLen;
        return [coords[i][0] + t * (coords[i+1][0] - coords[i][0]), coords[i][1] + t * (coords[i+1][1] - coords[i][1])];
      }
    }
    return coords[coords.length - 1];
  }

  const results = [];
  const stepLen = totalLen / N;
  for (let k = 0; k < N; k++) {
    const startD = k * stepLen;
    const endD = (k === N - 1) ? totalLen : (k + 1) * stepLen;
    const subCoords = [getPointAtDist(startD)];
    for (let i = 1; i < coords.length - 1; i++) {
      if (dists[i] > startD + 1e-7 && dists[i] < endD - 1e-7) subCoords.push(coords[i]);
    }
    subCoords.push(getPointAtDist(endD));
    results.push(JSON.stringify({ type: "LineString", coordinates: subCoords }));
  }
  return results;
  """;
  ```
- **Display Name Formatting Rule**: When appending an index suffix (e.g. ` (1/3)`) to sub-segments, ONLY append the suffix if `display_name != ""` so that blank/unnamed segments remain clean empty strings.

## CARTO Analytics Toolbox for BigQuery
Since BigQuery's native advanced function support is focused on core primitives, the **CARTO Analytics Toolbox** is the primary source for rich geospatial extensions.

### 1. Advanced Spatial Indexing (H3 & Quadbin)
BigQuery does **not** have native H3 support. Use CARTO for hexagonal and square-based indexing.
- `carto.h3.ST_ASH3(geog, res)`: Convert geography to H3 cells.
- `carto.h3.POLYFILL(geog, res)`: Fill a polygon with H3 cells.
- `carto.h3.KRING(h3, r)`: Find neighbors within radius `r`.

### 2. Location Data Services (LDS)
- **Geocoding**: `carto.lds.GEOCODE_REVERSE(point)`
- **Isolines**: Generate travel-time or travel-distance buffers (e.g., `carto.lds.CREATE_ISOLINE`).

### 3. Spatial Statistics & Tiler
- **Advanced Stats**: `carto.statistics.GETIS_ORD`, `carto.statistics.MORANS_I`.
- **Large-Scale Visualization**: `carto.tiler.CREATE_TILESET` generates vector tiles directly in BigQuery.

## Native vs. CARTO: When to use what?

| Task | Recommendation |
| :--- | :--- |
| **Standard Joins & Distance** | Use **Native BigQuery** (`ST_INTERSECTS`, `ST_DWITHIN`). |
| **Geodesic Geometry Math** | Use **Native BigQuery** (`ST_AREA`, `ST_LENGTH`). |
| **S2 Indexing / Logic** | Use **Native BigQuery** (`S2_CELLIDFROMPOINT`). |
| **H3 / Quadbin Analysis** | Use **CARTO** (`carto.h3.*`, `carto.quadbin.*`). |
| **Travel Time / Isolines** | Use **CARTO LDS** (`carto.lds.*`). |
| **Hotspot/Clustering Stats** | Use **CARTO Statistics** (`carto.statistics.*`). |
| **Large-Scale Tiling** | Use **CARTO Tiler** (`carto.tiler.CREATE_TILESET`). |

## Best Practices
- **Use `GEOGRAPHY` Over Lat/Lng**: Always prefer `GEOGRAPHY` columns and spatial functions. BigQuery uses an internal S2 spatial index for these.
- **Spatial Clustering**: Cluster your tables on a `GEOGRAPHY` column to colocate data by S2 cell.
- **Simplify Geometries**: Use `ST_SIMPLIFY` for complex polygons to improve query performance.

## Examples

### 1. Spatial Join: Point in Polygon
Join a table of coordinates with a boundary polygon dataset:
```sql
SELECT 
  p.point_id, 
  b.boundary_name
FROM 
  `my_project.my_dataset.points` p
INNER JOIN 
  `my_project.my_dataset.boundaries` b
ON 
  ST_CONTAINS(b.geom, p.geog_point)
WHERE 
  p.partition_date = "2026-06-12";
```

### 2. Spatial Proximity: ST_DWithin
Filter elements within a 500-meter radius of a spatial point:
```sql
SELECT 
  incident_id, 
  incident_type
FROM 
  `my_project.my_dataset.incidents`
WHERE 
  ST_DWITHIN(geog_point, ST_GEOGPOINT(-122.4194, 37.7749), 500.0)
  AND partition_date >= "2026-06-01";
```

## Related Skills

- **[`bigquery-overturemaps`](../bigquery-overturemaps/SKILL.md)**: Querying Overture Maps Foundation datasets (divisions, transportation, places, buildings) in BigQuery, including `division_area` land filtering (`is_land = true`) and schema unwrapping.
- **[`bigquery-geospatial-catalog`](../bigquery-geospatial-catalog/SKILL.md)**: Public geographic datasets, census boundaries, and regional catalog joins.
- **[`bigquery-practices`](../bigquery-practices/SKILL.md)**: Query optimization, job tagging, cost management, and partitioned MERGE patterns.
