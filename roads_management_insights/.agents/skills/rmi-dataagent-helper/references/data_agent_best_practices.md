# BigQuery Data Agent: RMI Operational Best Practices & Grounding Protocol

This guide details enterprise-grade architectural patterns and operational runbooks for provisioning, grounding, and maintaining BigQuery Conversational Data Agents for Roads Management Insights (RMI).

---

## 1. Location & Hierarchy Governance

The Gemini Data Analytics API (`geminidataanalytics.googleapis.com`) enforces a **global location hierarchy**:
```text
projects/<PROJECT_ID>/locations/global/dataAgents/<AGENT_ID>
```

> [!IMPORTANT]
> Do not attempt to provision or list Data Agents under regional locations (such as `us-central1` or `asia-east1`). Doing so will trigger `403 PERMISSION_DENIED` with `location is not allowed (must be one of map[global:true])`.

---

## 2. Pre-Flight Datasource Validation

Before invoking `createSync` or `patch`, ensure that all BigQuery tables declared in `datasourceReferences.bq.tableReferences` exist in the target dataset and are readable by the service account or authenticated user.

```json
{
  "datasourceReferences": {
    "bq": {
      "tableReferences": [
        { "projectId": "my_project", "datasetId": "my_dataset", "tableId": "recent_roads_data" },
        { "projectId": "my_project", "datasetId": "my_dataset", "tableId": "historical_travel_time" },
        { "projectId": "my_project", "datasetId": "my_dataset", "tableId": "routes_status" }
      ]
    }
  }
}
```

If any table is missing or invalid, the API rejects provisioning immediately with:
`400 INVALID_ARGUMENT: User does not have read access to one or more BigQuery resources referenced in agent configuration, or one or more of these resources are invalid.`

---

## 3. Metadata Anchoring & Schema Annotations

BigQuery Data Agents interpret table schemas via GoogleSQL metadata. Annotate your analytical views to guide LLM semantic translation:

```sql
ALTER VIEW `my_project.rmi.cleaned_routes`
SET OPTIONS (
  description="Main view for analyzing RMI route performance. Use this for travel time and SRI analysis."
);

ALTER COLUMN duration_in_seconds 
SET OPTIONS(description="The actual traffic-aware travel time in seconds.")
ON `my_project.rmi.cleaned_routes`;
```

---

## 4. Full Catalog Golden Query Ingestion

To eliminate SQL hallucinations, unpartitioned full scans, and syntax errors, inject 100% of verified analytical queries (from `rmi-sql`) into the agent's `exampleQueries`:

1. **Natural Language Question**: Formulate clear, real-world business questions (`-- Business Question:`).
2. **Deterministic SQL Template**: Include required partition bounds (`record_time BETWEEN ...`), spatial integrity checks (`ST_GEOMETRYTYPE(route_geometry) = 'ST_LineString'`), and standard FinOps Job ID headers.

---

## 5. Traceability Job ID Standard

Enforce standardized `rmisqlfactory_` job ID prefixes in the agent's system instructions:
```sql
-- Job ID: rmisqlfactory_<persona><N>_YYYYMMDD_HHMMSS
```
This enables BigQuery Administrators (`bqa`) to attribute scan bytes, query concurrency, and compute costs directly to specific agent personas via `INFORMATION_SCHEMA.JOBS`.

---

## 6. Safe Mutation via Asynchronous Patch (`updateMask`)

When updating existing agents (instructions, golden queries, or table bindings), use `geminidataanalytics_v1_dataAgents_patch` with explicit `updateMask`:

```bash
geminidataanalytics_v1_dataAgents_patch \
  "projects/${PROJECT_ID}/locations/global/dataAgents/${AGENT_ID}" \
  "${PAYLOAD_JSON}" \
  "displayName,description,dataAnalyticsAgent.stagingContext" \
  "${PROJECT_ID}"
```

This triggers an asynchronous Long Running Operation (`OperationMetadata` with `verb: "update"`), preventing state corruption or `already exists` conflicts.
