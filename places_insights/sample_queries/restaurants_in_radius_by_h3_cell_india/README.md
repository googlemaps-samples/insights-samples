### Description
This query first identifies all restaurants within a specific circular area (a 10km radius around a point in Mumbai, India) and then aggregates them into H3 cells. The result is a list of H3 cells, their geometries, and the count of restaurants within each, perfect for creating a fine-grained density heatmap of a specific point of interest.

### Key Concepts
*   **Country-Specific Table:** This query uses the `places_insights___in.places` table to analyze data specifically for India.
*   **Circular Geospatial Filter:** Leverages `ST_DWITHIN` to efficiently filter for all places within a given radius (10,000 meters) of a central point. This is the most performant way to conduct a radius search.
*   **H3 Spatial Indexing:** Uses `carto-os.carto.H3_FROMGEOGPOINT` to bin the filtered restaurants into H3 cells (at resolution 8), which are then counted.
*   **Two-Step Geometry Generation:** As with other heatmap queries, it first aggregates the counts by H3 index and then uses `carto-os.carto.H3_BOUNDARY` in an outer query to generate the cell polygon for visualization.
