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
- **LineString Endpoint Safety (`SAFE.ST_STARTPOINT` / `SAFE.ST_ENDPOINT`)**: `ST_STARTPOINT(geog)` and `ST_ENDPOINT(geog)` throw a fatal runtime error (`The input is not a single LINESTRING`) if even a single row in a table is a `MultiLineString`, `Polygon`, or `GeometryCollection` (common in Overture Maps `transportation_segment` and municipal GIS exports). Always guard point-anchor extraction with `COALESCE(SAFE.ST_STARTPOINT(geometry), ST_CENTROID(geometry))`.

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

### 2.6 Point-Driven vs. Polygon-Driven Administrative Joins (Zero-Event Selection Bias Trap)

- **The Anti-Pattern**: When aggregating point events (e.g. street crime incidents, crash points, store transactions) into S2/H3 grid cells and assigning each cell to an administrative jurisdiction for grouped cross-validation (`GroupKFold`), **never infer the cell's jurisdiction from the point events inside it** (e.g. `APPROX_TOP_COUNT(p.jurisdiction_id, 1)`).
- **Why it Fails**: Grid cells with zero recorded events (e.g. **16.3%** of onshore S2 Level 12 cells in England & Wales) receive `NULL` jurisdiction and are silently dropped from grouped hold-outs, truncating the lower tail of the target distribution and biasing rural/suburban evaluation metrics.
- **The Solution**: Always assign administrative jurisdictions via an independent polygon intersection (`ST_INTERSECTS(cell.boundary, admin.geom)`) against official boundary polygons *before* left-joining point counts (`IFNULL(n, 0)`), and pre-filter multi-agency panel archives for complete temporal coverage (`COUNT(DISTINCT month) = expected_months`):

  ```sql
  WITH cell_admin AS (
    SELECT
      c.geo_id,
      APPROX_TOP_COUNT(a.admin_name, 1)[SAFE_OFFSET(0)].value AS admin_name
    FROM `my_project.my_dataset.s2_cells` c
    INNER JOIN `my_project.my_dataset.admin_boundaries` a
      ON ST_INTERSECTS(c.boundary, a.geom)
    GROUP BY 1
  ),
  point_counts AS (
    SELECT
      S2_CELLIDFROMPOINT(ST_GEOGPOINT(lng, lat), 12) AS cell_id,
      COUNT(1) AS event_count
    FROM `my_project.my_dataset.point_events`
    GROUP BY 1
  )
  SELECT
    c.geo_id,
    ca.admin_name,
    IFNULL(pc.event_count, 0) AS event_count
  FROM `my_project.my_dataset.s2_cells` c
  LEFT JOIN cell_admin ca USING (geo_id)
  LEFT JOIN point_counts pc USING (cell_id);
  ```

### 2.7 Slippy Map Tile Math & Quadtree Hierarchical Pruning Table Function (`generate_tile_grid`)

- **The Problem**: Dividing an irregular, multi-county or national boundary polygon into Web Mercator (EPSG:3857) Slippy Map tiles $(z, x, y)$ for parallel API extractions or spatial partition batching typically requires massive external GIS scripts or millions of bounding box tests.
- **The Solution**: Native BigQuery spatial functions (`ST_MAKEPOLYGON`, `ST_BOUNDINGBOX`, `ST_CONTAINS`, `ST_INTERSECTS`) combined with Mercator trigonometric UDFs can generate and classify thousands of tile cells inside BigQuery SQL in seconds.
- **Hierarchical Quadtree Pruning Pattern**:
  1. **Zoom 10 Coarse Sweep**: Computes tile range across the boundary bounding box at Zoom 10. Classifies candidate tiles into `inside`, `border`, or `outside`.
  2. **Zoom 12 Sub-expansion**: Mathematically expands `inside` tiles by multiplying coordinates by 4 ($2^{12-10}$) without recalculating boundary containment. Only tests spatial intersection on the narrow set of `border` tiles.
  3. **Target Zoom Expansion (e.g. Zoom 14)**: Mathematically expands verified inside tiles to the final zoom level and clips border tiles against the master boundary.
- **Persistent Deployment Script**: Deploy the UDFs (`tile2lat`, `tile2lon`, `lon2tile`, `lat2tile`) and the `generate_tile_grid(boundary_geom, zoom)` TVF using [`scripts/deploy_slippy_tiles.sh`](scripts/deploy_slippy_tiles.sh):

  ```sql
  -- Querying all Zoom 14 tiles covering a boundary polygon:
  SELECT 
    id AS tile_id, 
    ST_GEOGFROMGEOJSON(geometry) AS tile_geom,
    ST_GEOGFROMGEOJSON(boundary) AS clipped_tile_geom
  FROM `my_project.geospatial_tiles.generate_tile_grid`(
    (SELECT geometry FROM `my_project.boundaries.region_polygon`),
    14
  )
  WHERE id != 'MASTER_BOUNDARY';
  ```

### 2.8 Composite `(Enum, GEOGRAPHY)` Clustering & The Relational Spatial Join Pruning Trap

When a spatial table is clustered by a composite key with a leading low-cardinality enum/class and a secondary `GEOGRAPHY` column (e.g., `CLUSTER BY priority, geometry`):

- **Single-Class vs. Unfiltered Viewport Multiplier**: Filtering by a single leading enum value (`WHERE priority = 'PRIORITY_CONTROLLED_ACCESS'`) alongside `ST_INTERSECTS(geometry, box)` prunes `99.9%` of Capacitor blocks (`0.1%` scanned). However, omitting the `priority` filter forces BigQuery to probe S2 spatial blocks across every `priority` sort bucket separately (`~7.5x` scan multiplier across 8 priority classes).
- **The Relational Spatial Join Pruning Trap**: Joining the clustered road table directly against a boundary table (`FROM road_segments r JOIN boundaries b ON ST_INTERSECTS(r.geometry, b.geom) WHERE b.state_code = 'MA'`) prevents static S2 block pruning on the secondary `geometry` cluster key—causing a **100% full-table scan** when `priority` is omitted.
- **Canonical Workaround (`DECLARE` Scalar Polygon Pre-Fetch)**: Pre-fetch the target boundary polygon into a scalar `GEOGRAPHY` variable in a multi-statement script before querying the clustered table. Passing a scalar `GEOGRAPHY` constant to `ST_INTERSECTS` restores static S2 block pruning across all enum buckets:

  ```sql
  DECLARE target_poly GEOGRAPHY;
  SET target_poly = (
    SELECT ST_UNION_AGG(geometry)
    FROM `bigquery-public-data.overture_maps.division_area`
    WHERE subtype = 'region' AND region = 'US-MA'
  );

  SELECT road_segment_id, priority, geometry
  FROM `my_project.road_network.road_segments_latest`
  WHERE ST_INTERSECTS(geometry, target_poly);
  ```

### 2.9 WKB Byte Hashing (`ST_ASBINARY`) vs. Topological `ST_EQUALS` Mismatch

- **The Collinear Vertex Trap**: BigQuery's `ST_EQUALS(g1, g2)` evaluates topological point-set equality on the sphere and ignores redundant collinear vertices along a straight segment (`ST_EQUALS(LINESTRING(0 0, 1 1, 2 2), LINESTRING(0 0, 2 2)) = TRUE`). By contrast, `ST_ASBINARY(g)` / `ST_ASTEXT(g)` serializes the exact vertex array (`3` points vs. `2` points).
- **Phantom Change-Detection Rows**: If an ETL pipeline detects modified rows using `FARM_FINGERPRINT(TO_HEX(ST_ASBINARY(geometry)))` but populates the changed-column array using `IF(NOT ST_EQUALS(prev.geometry, curr.geometry), 'geometry', NULL)`, collinear vertex insertions/simplifications produce rows marked `change_type = 'MODIFIED'` with an empty `changes = []` array.
- **Best Practice**: Ensure the row-level change detector and column-level diff expression use the **same equality semantics** (either both `NOT ST_EQUALS(a, b)` for topological changes, or both `ST_ASBINARY(a) != ST_ASBINARY(b)` if vertex-level changes matter), and guard downstream consumers with `WHERE ARRAY_LENGTH(changes) > 0`.

### 2.10 2D `ST_DWITHIN` Overpass False Positives & Endpoint-Coincidence Filtering

- **The 2D Overpass Pitfall**: Because BigQuery `GEOGRAPHY` is strictly 2D (no Z-elevation / grade-level attribute in spatial predicates), finding road segments connected to a highway corridor via `ST_DWITHIN(seg.geometry, corridor_geom, 5.0)` returns **60%–82% false positives** from grade-separated overpasses, underpasses, and parallel frontage roads whose 2D centerlines cross or run within 5 meters of the highway without a physical ramp connection.
- **Endpoint-Coincidence Pattern**: In a topologically split road network (where segments split at physical junctions), true physical connections share a segment startpoint or endpoint with the corridor geometry. Filter by endpoint proximity (`1.0m`) to eliminate crossing overpasses:

  ```sql
  WHERE ST_DWITHIN(seg.geometry, corridor_geom, 5.0)
    AND (
      ST_DWITHIN(ST_STARTPOINT(seg.geometry), corridor_geom, 1.0)
      OR ST_DWITHIN(ST_ENDPOINT(seg.geometry), corridor_geom, 1.0)
    )
  ```

### 2.11 Local DuckDB Execution Engine for BigQuery Spatial Pipelines (R-Tree `SPATIAL_JOIN` & Parquet Parity)

When transpiling multi-stage BigQuery GIS pipelines (`ST_DWITHIN`, `ST_INTERSECTS`, `ST_DISTANCE`, `ST_LINESUBSTRING`) to run locally on **DuckDB** (`spatial` extension) via `sqlglot` before pushing final Parquet tables back to BigQuery:

1. **Why `FilterPushdown` Disables DuckDB's `SpatialJoinOptimizer` ($O(N^2)$ Fallback Trap)**:
   - DuckDB's `SpatialJoinOptimizer` rewrites `LogicalComparisonJoin` into an R-tree `SPATIAL_JOIN` **only** when `join.conditions` contains no regular comparison conditions (`has_Only_Spatial_Conditions`).
   - If a spatial `JOIN` (`ON ST_DWITHIN(...)` or `WHERE ST_DWITHIN(...)`) also includes non-spatial cross-table column comparisons—such as `e.from_node != n.node_id`, `n1.node_id < n2.node_id`, or `e1.pair_id < e2.pair_id`—DuckDB's `FilterPushdown` attaches those inequalities to `join.conditions`. This silently disables `SpatialJoinOptimizer` and forces an $O(N^2)$ `Piecewise Merge Join` or `Nested Loop Join` (e.g. `1,383 s` vs. **`0.7 s`**, a **`1,975x` speedup** on `195k × 161k` road edges and nodes).
   - **AST Rewriter Fix (`COALESCE(pred, FALSE)`)**: In your `sqlglot` BigQuery $\to$ DuckDB translator, wrap every non-spatial conjunct in `ON` or `WHERE` that references columns from $\ge 2$ table qualifiers inside `COALESCE(pred, FALSE)`. Because `COALESCE` is a function call rather than a bare `Comparison`, `FilterPushdown` leaves it in a post-join `Filter` operator while `SpatialJoinOptimizer` builds the R-tree `SPATIAL_JOIN`.
2. **Single-Condition `ST_DWithin` Macro for `LEFT JOIN` Acceleration**:
   - Expanding a `bq_st_dwithin(a, b, d)` macro into two `AND`-ed spatial predicates (`ST_DWithin(a_wgs84, b_wgs84, deg) AND ST_DWithin(bq_m(a), bq_m(b), d)`) prevents DuckDB from planning `SPATIAL_JOIN` on `LEFT JOIN`.
   - Define `bq_st_dwithin(a, b, d)` as a single projected metric predicate `ST_DWithin(bq_m(a), bq_m(b), d)` (where `bq_m(g)` scales `(lon, lat)` to equirectangular meters at the AOI reference latitude `lat0`), enabling R-tree `SPATIAL_JOIN` on both `INNER` and `LEFT` joins.
3. **`sqlglot` 30+ Boolean AST Rewriting Gotchas**:
   - In `sqlglot` 30+, `issubclass(exp.And, exp.Func)` is `True` (`exp.Connector` inherits from `exp.Func`), and `node.walk()` yields `node` itself first. Always check `not isinstance(n, exp.Connector)` and skip `sub is node` when recursively guarding `AND` trees.
4. **DuckDB $\to$ BigQuery Parquet `ARRAY` NULL Coercion**:
   - DuckDB permits `NULL` inside `LIST` columns (`T[]`), whereas BigQuery `REPEATED` columns reject `NULL` arrays during Parquet loads (`Field ... is non-nullable, but row ... is null`). Always project `LIST` columns as `COALESCE("col", []) AS "col"` when exporting DuckDB tables to Parquet for `bigquery.Client.load_table_from_file`.

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

- **Display Name Formatting Rule**: When appending index suffixes (e.g. `(1/3)`), ONLY append if `display_name != ""` so blank names remain clean empty strings.

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

## 6. Field Lessons: Spatial Joins, Bearings & Endpoint Graphs
* **Never pair `ST_DWITHIN` with a low-cardinality equality join** (e.g. `a.region = b.region` with 2 values). BigQuery may evaluate the spatial predicate for every pair inside each group, and jobs ran for 15–30 min before timing out. Use a bare `ST_DWITHIN` join and filter by region afterwards.
* **Use `ST_AZIMUTH` for bearings and direction labels.** Comparing raw `|Δlng|` with `|Δlat|` in degrees ignores `cos(lat)`. It mislabels diagonals (an NW segment labelled NB) and biases high latitudes. Bucket the geodesic azimuth. Near ±10° of a diagonal, fall back to a longer-context bearing.
* **Building a graph from shared endpoints:**
  * Include **all** road classes or priorities. Dropping one tier (e.g. `PRIORITY_LIMITED_ACCESS`) made 517 connected ramps look disconnected.
  * Before calling something a "near-miss" or "gap" defect, verify that the endpoints are **not** bit-exactly shared (`ST_ASTEXT` endpoint counts >= 2).
  * Snap only dangling (degree-1) endpoints within a small tolerance (e.g. 0.5 m). Record lineage (`snapped_node`, `snap_distance_m`).
* **Grade separation:** 2D intersection or proximity between road lines produces many false junctions at over/underpasses (61–82% in the RMI evaluation). Require endpoint coincidence for connectivity.

## References

### Official Google Cloud Documentation

- [BigQuery Geospatial Analytics Overview](https://cloud.google.com/bigquery/docs/geospatial-data)
- [BigQuery Geography Functions Reference (`ST_*`)](https://cloud.google.com/bigquery/docs/reference/standard-sql/geography_functions)
- [Working with BigQuery Spatial Data](https://cloud.google.com/bigquery/docs/geospatial-analysis)
- [Clustering Tables by Geography](https://cloud.google.com/bigquery/docs/clustered-tables#geography_clustering)

### Official CARTO Analytics Toolbox Documentation

- [CARTO Analytics Toolbox for BigQuery Overview](https://docs.carto.com/analytics-toolbox-bigquery)
- [CARTO S2 Spatial Index Reference](https://docs.carto.com/analytics-toolbox-bigquery/overview/spatial-indexes#s2)
- [CARTO H3 & Quadbin Spatial Indexes](https://docs.carto.com/analytics-toolbox-bigquery/overview/spatial-indexes)

## Related Skills

- **[`bigquery-practices`](../bigquery-practices/SKILL.md)**: Foundational BigQuery best practices, partition pruning, storage billing models, and execution diagnostics.
- **`bigquery-overturemaps`**: Querying Overture Maps Foundation global divisions, transportation, and building datasets in BigQuery.
- **`bigquery-geospatial-catalog`**: Discovering and querying public geographic census boundaries and regional datasets.

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
