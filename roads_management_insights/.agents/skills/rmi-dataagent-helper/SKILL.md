---
name: rmi-dataagent-helper
description: Use this skill to configure, optimize, and ground BigQuery Conversational Data Agents for RMI. When invoked, helps users select a persona profile (TOM, Urban Planner, BQ Admin, Data Engineer, Data Scientist, or RMI Planner) to receive tailored grounding mantras, glossary definitions, and verified golden queries.
dependencies:
  - api-geminidataanalytics
  - rmi-sql
---


# RMI BigQuery Data Agent Helper

> [!NOTE]
> **Conceptual Layer vs. NLP Implementation Layer**:
> - **[`rmi-personas`](../rmi-personas/SKILL.md)** serves as the **Conceptual Layer**, defining high-level business challenges, quantitative SLAs, and cross-persona lifecycles.
> - **`rmi-dataagent-helper`** serves as the **NLP Implementation Layer**. It translates those conceptual personas into machine-readable prompts, grounding indices, glossary terms, and verified golden queries (**[`rmi-sql`](../rmi-sql/SKILL.md)**) to optimize BigQuery Conversational Data Agents.

This skill provides expert guidance and tooling to configure, ground, and programmatically manage BigQuery Conversational Data Agents for Roads Management Insights.

---

## 1. Persona-Driven Activation Workflow

When assisting a user with configuring a BigQuery Data Agent:
1. **Identify Target Persona**: Determine which of the 6 GA personas (or preview roles) the agent is being configured for:
   - **Traffic Operations Manager (TOM)**: Real-time incidents, bottlenecks, detour detection.
   - **Urban Planner (UP)**: Infrastructure ROI, before-and-after studies, TTI/PTI indices.
   - **BigQuery Admin (BQA)**: Spend governance, slot contention, zero-cost audits.
   - **Data Engineer (DE)**: Ingestion lag, geometry validation, 2-stage SRI pre-aggregations.
   - **Data Scientist (DS)**: Z-score anomalies, predictive forecasting (TimesFM/ARIMA_PLUS), reliability ranking.
   - **RMI Planner (RMIP)**: Total Addressable Monitoring (TAM) coverage, commercial tier SLAs, compute growth budgeting.
2. **Retrieve Grounding Mantra & Glossary**: Load the corresponding section from [`references/persona_setup_guides.md`](references/persona_setup_guides.md).
3. **Inject Verified Golden Queries**: Map the corresponding SQL assets from **[`rmi-sql`](../rmi-sql/SKILL.md)** into the Data Agent's `sampleQueries` field.

---

## 2. Global Grounding & Schema Annotation Principles

Regardless of persona, all RMI Conversational Data Agents require strong metadata grounding:

### 2.1 Metadata-Enriched Views
Annotate views and underlying physical tables using `ALTER VIEW ... SET OPTIONS` so the LLM semantic parser accurately interprets column semantics:
```sql
ALTER VIEW `my_project.rmi.cleaned_routes`
SET OPTIONS (
  description="Main analytical view for RMI route performance, travel times, and SRI sub-segment speeds."
);

ALTER COLUMN duration_in_seconds 
SET OPTIONS(description="Traffic-aware actual trip duration in seconds.")
ON `my_project.rmi.cleaned_routes`;
```

### 2.2 Standard Job ID Headers
Instruct the Data Agent to prepend standardized `rmisqlfactory_` Job IDs to all generated SQL:
```sql
-- Job ID: rmisqlfactory_<persona>_YYYYMMDD_HHMMSS
```

---

## 3. Grounding Index & Golden Query Assets

To prevent hallucinated column names and unpartitioned scans, ground the conversational agent with verified golden queries from **[`rmi-sql`](../rmi-sql/SKILL.md)**:

| Persona | Primary Grounding Focus | Key Golden Queries (`rmi-sql`) | Reference Guide |
| :--- | :--- | :--- | :--- |
| **Traffic Ops Manager** | Incidents, SRIs, Detour Fingerprints | `tom1_peak_hour_delay.sql`, `tom2_persistent_bottlenecks.sql`, `tom6_dynamic_detour_detection.sql` | [TOM Guide](references/persona_setup_guides.md#1-traffic-operations-manager-traffic-ops-expert) |
| **Urban Planner** | Before/After ROI, TTI/PTI, Emissions | `up1_corridor_trend.sql`, `up2_impact_analysis.sql`, `up4_weekend_vs_weekday.sql` | [UP Guide](references/persona_setup_guides.md#2-urban-planner-infrastructure--policy-analyst) |
| **BigQuery Admin** | Spend, Slots, `INFORMATION_SCHEMA` | `bqa0_metadata_inventory.sql`, `bqa1_scan_volume.sql`, `bqa2_cost_attribution.sql`, `bqa5_partition_pruning.sql` | [BQA Guide](references/persona_setup_guides.md#3-bigquery-admin-platform-cost--governance-custodian) |
| **Data Engineer** | Geometry Integrity, SRI Flattening | `de1_materialized_view.sql`, `de2_data_cleaning.sql`, `de3_sri_flattening.sql`, `de6_hourly_preaggregation.sql` | [DE Guide](references/persona_setup_guides.md#4-data-engineer-pipeline--spatial-integrity-architect) |
| **Data Scientist** | Outlier Z-Scores, Predictive Forecasts | `ds1_outlier_detection.sql`, `ds5_reliability_ranking.sql`, `ds6_travel_time_forecasting.sql` | [DS Guide](references/persona_setup_guides.md#5-data-scientist-predictive-modeling--anomaly-researcher) |
| **RMI Planner** | TAM Network Coverage, Tier Delay SLAs | `rmip1_usage_projection.sql`, `rmip2_customer_roi.sql`, `rmip3_segment_estimation.sql` | [RMIP Guide](references/persona_setup_guides.md#6-rmi-planner-commercial-tam--capacity-strategist) |

---


## 4. Multi-Persona Provisioning & Execution (`scripts/provision_data_agent.sh`)

Automate the lifecycle, provisioning, and conversational querying of all 6 RMI persona Data Agents using [`scripts/provision_data_agent.sh`](scripts/provision_data_agent.sh) (which leverages **[`api-geminidataanalytics`](../api-geminidataanalytics/SKILL.md)**):

### Option A: Direct CLI Provisioning

Provision any of the 6 RMI personas in a single shell command:

```bash
# Provision a Traffic Operations Manager (TOM) agent:
bash scripts/provision_data_agent.sh --persona tom --location projects/my-project/locations/us-central1 --project my-project --dataset src_boston_ga

# Provision an Urban Planner (UP) agent:
bash scripts/provision_data_agent.sh --persona up --location projects/my-project/locations/us-central1 --project my-project --dataset src_boston_ga

# Provision a BigQuery Admin (BQA) FinOps agent:
bash scripts/provision_data_agent.sh --persona bqa --location projects/my-project/locations/us-central1 --project my-project --dataset src_boston_ga

# Provision a Data Engineer (DE) spatial ETL agent:
bash scripts/provision_data_agent.sh --persona de --location projects/my-project/locations/us-central1 --project my-project --dataset src_boston_ga

# Provision a Data Scientist (DS) predictive modeling agent:
bash scripts/provision_data_agent.sh --persona ds --location projects/my-project/locations/us-central1 --project my-project --dataset src_boston_ga

# Provision an RMI Planner (RMIP) network capacity agent:
bash scripts/provision_data_agent.sh --persona rmip --location projects/my-project/locations/us-central1 --project my-project --dataset src_boston_ga
```

### Option B: Sourced Bash Operations

```bash
source scripts/provision_data_agent.sh

# Provision via generic function or persona wrapper:
setup_persona_agent "tom" "projects/my-project/locations/us-central1" "my-project" "src_boston_ga"

# Converse with the provisioned Data Agent:
chat_with_rmi_agent \
  "projects/my-project/locations/us-central1" \
  "projects/my-project/locations/us-central1/dataAgents/rmi-tom-agent" \
  "Which corridors are experiencing severe congestion (TTR > 1.5) right now?" \
  "my-project"
```




---

## 5. Tooling & Reasoning Safety Patterns

1. **SQL Transparency**: Instruct the conversational agent to always display the generated SQL so users can verify partition pruning before execution.
2. **Iterative Context Hinting**: When schema drift occurs, inject "Contextual Hints" via the BigQuery console or API patch operations.
3. **Partition Bounds Enforcement**: Alert users whenever a query omits `record_time` bounds on high-volume partitioned tables.

---

## References

- [`references/persona_setup_guides.md`](references/persona_setup_guides.md): Concrete setup steps and grounding mantras for all 6 RMI personas.
- [`references/data_agent_best_practices.md`](references/data_agent_best_practices.md): General BigQuery Conversational Data Agent grounding guidelines.
- [`references/instructions.md`](references/instructions.md): System instructions and schema mapping reference.
- [BigQuery Data Agent Official Documentation](https://cloud.google.com/bigquery/docs/create-data-agents)
- [BigQuery Conversational Analytics API](https://cloud.google.com/bigquery/docs/conversational-analytics-api)

## Related Skills

- **[`rmi-personas`](../rmi-personas/SKILL.md)**: Conceptual definitions, business challenges, and SLAs for RMI personas.
- **[`rmi-sql`](../rmi-sql/SKILL.md)**: Production SQL asset library and golden queries.
- **[`bigquery-practices`](../bigquery-practices/SKILL.md)**: Foundational BigQuery performance, security, and governance best practices.
