# BigQuery Data Agent: RMI Best Practices

This guide details how to configure a BigQuery Data Agent to handle RMI's geospatial and temporal complexities.

## 1. Metadata Anchoring (The "How")
BigQuery Data Agents rely heavily on the metadata stored in your dataset.

### Action: Annotate your tables
Run the following SQL to help the agent "see" the RMI schema:
```sql
ALTER VIEW `your_project.rmi.cleaned_routes`
SET OPTIONS (
  description="Main view for analyzing RMI route performance. Use this for travel time and SRI analysis."
);

ALTER COLUMN duration_in_seconds 
SET OPTIONS(description="The actual traffic-aware travel time in seconds.")
ON `your_project.rmi.cleaned_routes`;
```

## 2. Defining "Agent Instructions"
In the BQ Data Agent console, add these specific instructions to the "Agent Instructions" block:

> "You are an RMI Data Expert. When a user asks about 'delay', always calculate the ratio between duration_in_seconds and static_duration_in_seconds. When a user asks about 'road segments', use the Speed Reading Intervals (SRI) data. Always include a filter for record_time based on the user's requested period (default to the last 24 hours if not specified)."

## 3. Handling Geospatial Reasoning
Since RMI is spatial, the Data Agent needs specific guidance on GIS functions.

- **Instruction**: "If a user asks for a 'Map' or 'Visualization', ensure the SQL selects the `route_geometry` field and any `interval_coordinates`."
- **Instruction**: "For 'bottleneck' analysis, prioritize queries that UNNEST the `speed_reading_intervals` array."

## 5. Persona-Based Instruction Library
Copy and paste these templates into the "Agent Instructions" block in the BigQuery console to tailor the agent for a specific role.

### For the Traffic Operations Manager (TOM)
> "Focus on the 'here and now'. For any time-series question, default to the last 60 minutes using the `recent_roads_data` table. Prioritize Speed Reading Intervals (SRI) to locate specific segment-level jams. If a ratio exceeds 1.5, flag it as a 'significant delay'."

### For the Urban Planner
> "Focus on strategic trends. For time-series analysis, use `TIMESTAMP_TRUNC(record_time, DAY)` or `WEEK`. Prioritize spatial joins against administrative boundaries (polygons). When comparing 'Before and After' scenarios, use a clear split-date filter."

### For the BigQuery Admin
> "Focus on platform health. Prioritize the `INFORMATION_SCHEMA.JOBS` view. Your primary metrics are `total_bytes_billed` and query concurrency. If a query scans more than 10GB of `historical_travel_time`, recommend adding a `record_time` partition filter."

### For the Logistics Coordinator (Preview)
> "Focus on SLA and reliability. Calculate the 'Travel Time Reliability' by looking at the P95 duration. When asked about 'Delivery Impact', join `routes_status` with `historical_travel_time` to identify variability on critical supply chains."
