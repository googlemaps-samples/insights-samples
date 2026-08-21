# Capability: BigQuery Core
**Stage**: GA (General Availability)
**Product Source**: BigQuery

## 1. General BigQuery Capabilities
Fundamental analytical features provided by the BigQuery SQL and Geospatial engines.

### Data Manipulation & Windowing
- **Standard SQL**: Complex joins (`INNER`, `LEFT`, `CROSS`), multi-level aggregations, and CTE-based structuring.
- **Unnesting Repeated Data**: Using `CROSS JOIN UNNEST(repeated_field)` to flatten nested structures (essential for segment-level analysis).
- **Window Functions**: Row-by-row comparisons using `LAG`, `LEAD`, `RANK`, and `OVER`.
- **Advanced Statistics**: Native support for standard deviation (`STDDEV`), variance, and exact/approximate percentiles (`PERCENTILE_CONT`).

### Geospatial Functions & Logic
- **`GEOGRAPHY` Data Type**: Default type for spatial columns (Points, Polylines, Polygons).
- **Topological Predicates**: `ST_INTERSECTS`, `ST_CONTAINS`, `ST_WITHIN`, `ST_COVERS`, `ST_EQUALS`. 
    - **Expert Tip**: Prioritize `ST_INTERSECTS` for general proximity; it is the most performant.
    - **ST_EQUALS Note**: Geometries can be equal even if point ordering or vertices differ.
- **Spatial Parsing & Repair**: 
    - `ST_GEOGFROMTEXT` and `ST_GEOGFROMGEOJSON`.
    - **Coordinate Order Warning**: BigQuery requires **Longitude-Latitude (x, y)** order.
    - **Automatic Repair**: Use `make_valid => TRUE` to fix self-intersecting polygons during ingestion.
- **Measurement & Simplification**:
    - Physical metrics: `ST_LENGTH`, `ST_DISTANCE`, `ST_AREA` (all in meters).
    - **Visual Optimization**: Use `ST_Simplify(geog, tolerance_meters)` to reduce payload size before sending data to visualization tools (GeoViz, Looker).
- **`GROUP BY` Workarounds**:
    - BigQuery does not support `GROUP BY` on `GEOGRAPHY` types.
    - **Workaround A**: Convert to string (`ST_ASTEXT`) to group, then convert back (`ST_GEOGFROMTEXT`).
    - **Workaround B**: Use `ANY_VALUE(geog_column)` when grouping by a unique non-spatial key.

### Temporal Engineering
- **Time-series Logic**: Truncating timestamps (`TIMESTAMP_TRUNC`) and extracting components (`EXTRACT(HOUR FROM ...)`).
- **Timezone Casting**: Converting UTC to local time: `DATETIME(record_time, "America/New_York")`.

### Performance Optimization
- **Clustering (S2)**: Always `CLUSTER BY` your geography or primary ID columns to organize data physically.
- **Join Optimization**: Avoid mixing equality joins (e.g., `a.id = b.id`) with spatial predicates in the same `JOIN` clause to prevent bypassing the spatial optimizer.
- **The `DECLARE` Trick**: When filtering by a geometry from another table, use `DECLARE` to store the constant first. This ensures BigQuery utilizes clustered indexes:
    ```sql
    DECLARE area GEOGRAPHY DEFAULT (SELECT geometry FROM boundaries WHERE id = 'boston');
    SELECT * FROM rmi_table WHERE ST_INTERSECTS(route_geometry, area);
    ```

## 2. General Best Practices
- **Scan Volume**: Monitor `total_bytes_billed` in `INFORMATION_SCHEMA.JOBS` to detect inefficient patterns.
- **Job IDs**: Follow consistent naming conventions for auditing and cost attribution.
