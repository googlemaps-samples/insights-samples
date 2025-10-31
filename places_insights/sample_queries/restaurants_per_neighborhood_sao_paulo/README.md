### Description
This query provides a simple and efficient way to count the number of restaurants in each neighborhood of São Paulo, Brazil. It leverages the built-in address components of the Brazil-specific schema to produce a table of neighborhood names and their corresponding restaurant counts. This output is ideal for generating a ranked list or a bar chart, but does not include the geographic shapes needed for a choropleth map.

### Key Concepts
*   **Country-Specific Table:** Correctly uses the `places_insights___br.places` table for analysis in Brazil.
*   **Record-Based Access:** Demonstrates the correct `record.field` syntax (e.g., `sublocality_level_1.name`) for accessing data from `STRUCT` type columns, which is common in country-specific schemas.
*   **Efficient Grouping:** Avoids complex and costly geospatial joins by grouping directly on the neighborhood name field provided in the data.
*   **Tabular Analysis:** This pattern is best suited for creating tables and charts, as it does not retrieve the polygon geometries required for map-based visualizations like choropleths.
