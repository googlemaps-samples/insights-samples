---
name: bigquery-geospatial
description: Expert guidance on BigQuery Geospatial (GIS) capabilities. Use this skill when the user asks about GEOGRAPHY types, spatial functions (ST_*), proximity analysis, spatial joins, or spatial indexing (S2/H3/Quadbin) in BigQuery.
dependencies:
  - bigquery-practices
---

# BigQuery Geospatial (GIS)

BigQuery provides native spatial data processing capabilities built around the `GEOGRAPHY` data type and standard OpenGIS `ST_*` functions, internally powered by the **S2 Geometry Library** and extensible via the **CARTO Analytics Toolbox**.

---

## 1. Native BigQuery GIS Primitives & Spatial Indexing

### 1.1 Native S2 Indexing & Geography Clustering
- **Native S2 Indexing**: BigQuery internally partitions and indexes spatial data on the **S2 Spherical Geometry** grid. Spatial join predicates (`ST_INTERSECTS`, `ST_CONTAINS`, `ST_COVERS`) and proximity searches (`ST_DWITHIN`) automatically leverage S2 cell containment to eliminate non-overlapping table partitions.
- **Geography Clustering**: Always `CLUSTER BY <geography_column>` on physical tables to colocated records within the same S2 spatial hierarchy, drastically reducing byte scan volumes during bounding box or viewport queries.

### 1.2 Coordinate Standards & Auto-Repair
- **Coordinate Order Mandate**: BigQuery strictly enforces **Longitude-Latitude (x, y)** order (`ST_GEOGPOINT(longitude, latitude)` or `POINT(lon lat)` in WKT). Swapping coordinates leads to invalid points or out-of-range errors.
- **Automatic Geometry Repair (`make_valid => TRUE`)**: Always include `make_valid => TRUE` when parsing external WKT or GeoJSON strings (`ST_GEOGFROMTEXT(wkt, make_valid => TRUE)`) to automatically heal self-intersecting polygon boundaries, coincident collinear vertices, and winding order anomalies at ingestion time.

### 1.3 Native Proximity & Measurement Predicates
- **`ST_DWITHIN(geog1, geog2, distance_meters)`**: Returns `TRUE` if the geodesic distance between two geometries is within the specified distance in meters. **Always prefer `ST_DWITHIN` over `ST_DISTANCE(...) <= radius`** because `ST_DWITHIN` utilizes spatial index acceleration.
- **`ST_DISTANCE(geog1, geog2)`**: Computes the shortest geodesic distance in meters on the WGS84 ellipsoid.
- **`ST_AREA(geog)` & `ST_LENGTH(geog)`**: Native geodesic area (square meters) and length (meters) calculations.

---

## 2. High-Performance Spatial Query Patterns

### 2.1 Spatial Predicate Optimization & The Two-Join Trick
- **Spatial Join Predicate Rules**: Always prioritize `ST_INTERSECTS` for high-performance joins. Avoid mixing standard equality joins (e.g. `a.id = b.id`) with spatial predicates inside the same `ON` clause to prevent the optimizer from bypassing the spatial index.
- **The Two-Join Trick for Spatial Outer Joins**: BigQuery's spatial optimizer is strictly tuned for **INNER** spatial joins. Direct `LEFT OUTER JOIN` on spatial predicates can bypass index pruning and become slow.
  - *The Pattern*: Perform an accelerated spatial **INNER JOIN** first, aggregate the result (e.g. `COUNT` or array aggregation), and then **LEFT JOIN** back to the primary base table on standard non-spatial primary keys:
    ```sql
    WITH matched_points AS (
      SELECT 
        b.boundary_id,
        COUNT(p.point_id) AS incident_count
      FROM `my_project.my_dataset.boundaries` b
      INNER JOIN `my_project.my_dataset.points` p
        ON ST_INTERSECTS(b.geometry, p.geog_point)
      GROUP BY 1
    )
    SELECT 
      b.boundary_id,
      b.boundary_name,
      COALESCE(m.incident_count, 0) AS total_incidents
    FROM `my_project.my_dataset.boundaries` b
    LEFT JOIN matched_points m
      ON b.boundary_id = m.boundary_id;
    ```

### 2.2 Avoid `ST_UNION_AGG` on Large Datasets (Scalar Bounding Box Aggregation)
- **The Problem**: On high-volume spatial tables (>100,000 rows), executing `ST_UNION_AGG(geometry)` to compute a global bounding box leads to slot memory exhaustion and query timeouts.
- **The Solution**: Extract bounding box coordinate components using `ST_BOUNDINGBOX(geometry)` and compute fast scalar `MIN`/`MAX` aggregations across the component coordinate floats:
  ```sql
  WITH bbox_parts AS (
    SELECT ST_BOUNDINGBOX(geometry) AS bbox
    FROM `my_project.my_dataset.large_spatial_table`
  )
  SELECT 
    MIN(bbox.xmin) AS min_lon,
    MIN(bbox.ymin) AS min_lat,
    MAX(bbox.xmax) AS max_lon,
    MAX(bbox.ymax) AS max_lat
  FROM bbox_parts;
  ```

### 2.3 Grouping by Geography (`ANY_VALUE` Workaround)
- **The Constraint**: BigQuery disallows direct `GROUP BY` operations on columns of type `GEOGRAPHY`.
- **The Workarounds**:
  - *Pattern A*: Group by a unique non-spatial primary key (or S2/H3 index token) and wrap the geography in **`ANY_VALUE(geog_column)`**.
  - *Pattern B*: Convert the geometry to WKT string (`ST_ASTEXT(geog)`) for grouping, then restore via `ST_GEOGFROMTEXT` in the outer query.

### 2.4 Subdividing Heavy Geometries (`ST_SUBDIVIDE`)
- **The Pattern**: Massive multi-thousand-vertex polygons degrade join performance. Break complex regional boundaries into simpler sub-polygons at ingestion time. BigQuery's S2 index processes many simple sub-polygons significantly faster than a single monolithic boundary.

### 2.5 Efficient Nearest Neighbor (Iterative Search Loop)
- **The Pattern**: Avoid costly cross-joins when searching for the single nearest neighbor to a point. Use BigQuery procedural SQL with a `WHILE` loop: start with a small `ST_DWITHIN` radius (e.g. 500m), check row count, and incrementally double the search radius until a match is found.

---

## 3. Boundary, Corridor & Polyline Engineering

### 3.1 Localized Centroid Buffer Clipping (Excluding Distant Islands / Exclaves)
Administrative boundaries frequently include distant islands, reefs, or outer exclaves irrelevant to urban corridor analysis, producing bloated bounding boxes ($>5\times$ actual landmass).
- **The Pattern**: Intersect (`ST_INTERSECTION`) the administrative geometry with a localized `ST_BUFFER` centered at the urban centroid:
  ```sql
  WITH raw_data AS (
    SELECT geometry FROM `my_project.my_dataset.regional_boundaries` WHERE region_code = "ID-JK"
  )
  SELECT 
    ST_INTERSECTION(
      ST_UNION_AGG(geometry),
      ST_BUFFER(ST_GEOGPOINT(106.8342, -6.2063), 25000) -- 25km circular urban buffer
    ) AS boundary_geom 
  FROM raw_data;
  ```
- **Comparative Multi-Version Carousel Guidelines**: When evaluating fragmented regions, generate markdown preview carousels contrasting:
  1. *Original Boundary*: Raw administrative polygon without filtering.
  2. *Version A (Conservative)*: Size filter discarding fragments $< 0.1\%$ of landmass (ideal for archipelago cities like Seattle, Osaka).
  3. *Version B (Moderate)*: Size filter discarding fragments $< 1\%$ with scale-aware distance buffers.
  4. *Version C (Aggressive / Centroid Buffer)*: Fixed radial buffer (e.g., 25km circular clip for mainland-focused metros).

### 3.2 Equal-Length Line Slicing via JavaScript UDF
When corridor route segments exceed target lengths (e.g., 0.5 miles / 804.672m), slice a `GEOGRAPHY` LineString into $N$ equal parts while interpolating intermediate points and preserving authentic internal vertices:
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
- **Display Name Formatting Rule**: When appending index suffixes (e.g. ` (1/3)`), ONLY append if `display_name != ""` so blank names remain clean empty strings.

### 3.3 Tile Extraction Edge-Redundancy & Coordinate Deduplication
When extracting regional road networks using multi-tile grid strategies (e.g., Zoom 12/13 tile grids), border-crossing segments are retrieved redundantly across adjacent queries with slight centimeter-level coordinate offsets. Left unchecked, downstream graph fusion engines treat these offsets as distinct physical lanes, bloating network length by 1% to 4%.
- **The Solution**: Implement a POSIX-compliant compound hash filter (e.g., compound hash of `name` and exact `coordinates`) at Step 1 of baseline ingestion to purge tile-edge coordinate offsets before running topological healing.

---

## 4. CARTO Analytics Toolbox for BigQuery

While BigQuery provides basic native S2 primitives (`S2_CELLIDFROMPOINT`, `S2_COVERINGCELLIDS`), native BigQuery **lacks the ability to convert S2 cell IDs back into polygon boundaries or navigate S2 cell hierarchies**. The **CARTO Analytics Toolbox** provides comprehensive S2, H3, and Quadbin spatial indexing functions directly inside BigQuery SQL.

### 4.1 CARTO S2 Hierarchical Spatial Indexing
- **`carto.s2.ST_BOUNDARY(s2_id)`**: **Computes the exact polygon boundary `GEOGRAPHY` of an S2 cell ID/token**. Crucial for visualizing S2 spatial partitions, rendering grid cells, or joining S2 cells to municipal polygons.
- **`carto.s2.FROMGEOGPOINT(geog_point, resolution)`**: Converts a `GEOGRAPHY` point to an S2 cell ID at a specified level (0 to 30).
- **`carto.s2.POLYFILL(polygon_geog, resolution)`**: Generates an array of S2 cell IDs covering a given polygon boundary.
- **`carto.s2.TOPARENT(s2_id, parent_resolution)`**: Traverses up the S2 spatial hierarchy to aggregate data into coarser parent cells.
- **`carto.s2.TOCHILDREN(s2_id, child_resolution)`**: Expands a parent S2 cell into its sub-grid children cells.
- **`carto.s2.KRING(s2_id, ring_distance)`**: Returns neighboring S2 cells within distance $K$.

### 4.2 CARTO Hexagonal H3 & Quadbin Indexing
BigQuery does not support native H3 hexagonal indexing. Use CARTO for hexagonal and square spatial binning:
- **`carto.h3.ST_ASH3(geog_point, resolution)`**: Converts a `GEOGRAPHY` point to an H3 index string.
- **`carto.h3.ST_BOUNDARY(h3_id)`**: Computes the hexagon boundary `GEOGRAPHY` of an H3 cell.
- **`carto.h3.POLYFILL(polygon_geog, resolution)`**: Fills a polygon with covering H3 cell identifiers.
- **`carto.h3.KRING(h3_id, ring_distance)`**: Returns neighbor H3 cells within radius $K$.
- **`carto.quadbin.QUADBIN_FROMGEOGPOINT(geog_point, resolution)`** & **`carto.quadbin.QUADBIN_BOUNDARY(quadbin_id)`**: Quadkey/quadbin hierarchical indexing.

---

## 5. Native vs. CARTO Decision Matrix

| Task | Recommendation | Primary Function |
| :--- | :--- | :--- |
| **Standard Spatial Joins & Point in Polygon** | Use **Native BigQuery** | `ST_INTERSECTS`, `ST_CONTAINS` |
| **Proximity & Distance Filtering** | Use **Native BigQuery** | `ST_DWITHIN(geog1, geog2, meters)` |
| **Ellipsoidal Geodesic Math** | Use **Native BigQuery** | `ST_AREA`, `ST_LENGTH`, `ST_DISTANCE` |
| **Point to S2 Cell ID** | Use **Native BigQuery** or **CARTO** | `S2_CELLIDFROMPOINT(geog)` / `carto.s2.FROMGEOGPOINT(geog, level)` |
| **S2 Cell Boundary Polygon Generation** | Use **CARTO S2** | `carto.s2.ST_BOUNDARY(s2_id)` *(Native BigQuery lacks this)* |
| **S2 Polygon Polyfill & Hierarchy Traversal** | Use **CARTO S2** | `carto.s2.POLYFILL`, `carto.s2.TOPARENT` |
| **Hexagonal H3 / Quadbin Indexing & Boundaries** | Use **CARTO H3/Quadbin** | `carto.h3.ST_ASH3`, `carto.h3.ST_BOUNDARY`, `carto.h3.POLYFILL` |

---

## References

### Official Google Cloud Documentation
* [BigQuery Geospatial Analytics Overview](https://cloud.google.com/bigquery/docs/geospatial-data)
* [BigQuery Geography Functions Reference (`ST_*`)](https://cloud.google.com/bigquery/docs/reference/standard-sql/geography_functions)
* [Working with BigQuery Spatial Data](https://cloud.google.com/bigquery/docs/geospatial-analysis)
* [Clustering Tables by Geography](https://cloud.google.com/bigquery/docs/clustered-tables#geography_clustering)

### Official CARTO Analytics Toolbox Documentation
* [CARTO Analytics Toolbox for BigQuery Overview](https://docs.carto.com/analytics-toolbox-bigquery)
* [CARTO S2 Spatial Index Reference](https://docs.carto.com/analytics-toolbox-bigquery/overview/spatial-indexes#s2)
* [CARTO H3 & Quadbin Spatial Indexes](https://docs.carto.com/analytics-toolbox-bigquery/overview/spatial-indexes)

## Related Skills

- **[`bigquery-practices`](../bigquery-practices/SKILL.md)**: Foundational BigQuery best practices, partition pruning, storage billing models, and execution diagnostics.
- **[`bigquery-overturemaps`](../bigquery-overturemaps/SKILL.md)**: Querying Overture Maps Foundation global divisions, transportation, and building datasets in BigQuery.
- **[`bigquery-geospatial-catalog`](../bigquery-geospatial-catalog/SKILL.md)**: Discovering and querying public geographic census boundaries and regional datasets.

---

## Examples

### Example 1: Accelerated Spatial Point-in-Polygon Join
```sql
SELECT 
  p.point_id, 
  b.boundary_name,
  b.boundary_id
FROM 
  `my_project.my_dataset.points` p
INNER JOIN 
  `my_project.my_dataset.boundaries` b
ON 
  ST_CONTAINS(b.geometry, p.geog_point)
WHERE 
  p.partition_date = "2026-06-12";
```

### Example 2: Geodesic Proximity Filtering with ST_DWithin
```sql
SELECT 
  incident_id, 
  incident_type,
  ST_DISTANCE(geog_point, ST_GEOGPOINT(-122.4194, 37.7749)) AS distance_meters
FROM 
  `my_project.my_dataset.traffic_incidents`
WHERE 
  ST_DWITHIN(geog_point, ST_GEOGPOINT(-122.4194, 37.7749), 1000.0)
  AND partition_date >= "2026-06-01";
```

### Example 3: S2 Spatial Binning & Boundary Generation via CARTO
Aggregate telemetry observations into S2 Level 14 cells and compute polygon boundaries for map visualization:
```sql
WITH cell_metrics AS (
  SELECT 
    carto.s2.FROMGEOGPOINT(geog_point, 14) AS s2_cell_id,
    AVG(speed_mph) AS avg_speed,
    COUNT(1) AS observation_count
  FROM 
    `my_project.my_dataset.telemetry_points`
  WHERE 
    partition_date = "2026-06-12"
  GROUP BY 1
)
SELECT 
  s2_cell_id,
  -- Generate the physical polygon boundary of the S2 cell for visual rendering
  carto.s2.ST_BOUNDARY(s2_cell_id) AS cell_boundary,
  avg_speed,
  observation_count
FROM 
  cell_metrics;
```

