### Description
This query creates a density map of tourist attractions in Paris by dynamically loading the city's official boundary from the Overture Maps public dataset. It then filters the French Places data to find all attractions within that boundary, aggregating them into H3 cells for a high-resolution heatmap visualization.

### Key Concepts
*   **Dynamic Boundary Loading:** Uses `DECLARE` and `SET` to load the official geometry for Paris from the `overture_maps` public dataset into a variable. This ensures the analysis uses a precise and official boundary without hardcoding.
*   **Country-Specific Table:** Correctly uses `places_insights___fr.places` to query data in France.
*   **Geospatial Filtering:** Employs `ST_CONTAINS` to efficiently select only the places whose points fall within the pre-loaded Paris boundary polygon.
*   **CTE for Logical Flow:** A Common Table Expression (CTE) neatly isolates the logic of finding and binning the attractions within Paris before the final aggregation step.
*   **H3 Indexing for Visualization:** Uses `carto-os.carto.H3_FROMGEOGPOINT` to bin attractions into H3 cells and `carto-os.carto.H3_BOUNDARY` to generate the corresponding hexagonal polygons for mapping.
