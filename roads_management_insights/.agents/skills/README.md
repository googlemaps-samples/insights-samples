# Roads Management Insights (RMI) Agentic Skills Suite

> **Bundle ID**: `rmi-core` | **Version**: `1.0.0`
> **Generated**: `2026-08-21 07:38:48Z`

## Overview
Curated suite of agentic skills for Roads Management Insights (RMI) development, APIs, data analytics, and operational runbooks.

## 📦 Installed Skills Catalog

| Skill Name | Scope & Trigger Overview |
| :--- | :--- |
| [`api-analyticshub`](./api-analyticshub/SKILL.md) | Expert guidance on BigQuery Analytics Hub. Use this skill when the user asks about shared datasets, linked datasets, data exchange, subscribing to listings, or querying tables with privacy policies like AGGREGATION_THRESHOLD. Also handles resource management (CRUD operations) for Exchanges, Listings, and Subscriptions. Make sure to use this skill whenever the user mentions Analytics Hub, data sharing exchanges, creating listings, or subscribing to linked datasets. |
| [`api-discovery`](./api-discovery/SKILL.md) |  |
| [`api-roadsselection`](./api-roadsselection/SKILL.md) | Use this skill for creating, listing, retrieving, and managing SelectedRoutes (SelectedRoute) in RMI (Roads Management Insights). This includes defining routes with up to 25 intermediate waypoints, batch creation (up to 1000 routes), listing registered routes, syncing routes, and troubleshooting validation errors within authorized jurisdictions. Make sure to use this skill whenever the user mentions SelectedRoutes, SelectedRoute, registering monitored routes, roadsselection, routes of interest, routes_of_interest, sync_routes_of_interest, list routes, listing routes, or configuring RMI paths for segment telemetry. |
| [`bigquery-geospatial`](./bigquery-geospatial/SKILL.md) | Expert guidance on BigQuery Geospatial (GIS) capabilities. Use this skill when the user asks about GEOGRAPHY types, spatial functions (ST_*), proximity analysis, spatial joins, or spatial indexing (S2/H3/Quadbin) in BigQuery. |
| [`bigquery-practices`](./bigquery-practices/SKILL.md) | Use this skill for general, product-agnostic BigQuery foundational knowledge, including SQL best practices, geospatial tips (ST_ functions), performance optimization (partition pruning, clustering), block-level table sampling, and temporal engineering. |
| [`data-rmi-sampledatasets`](./data-rmi-sampledatasets/SKILL.md) | Specialized guidance for working with RMI sample datasets, particularly the Boston October 2025 snapshot. Use when Gemini CLI needs to validate queries against sample data, estimate production costs based on sample baselines, or ensure correct temporal filtering for static snapshots. |
| [`rmi-data-foundation-bigquery`](./rmi-data-foundation-bigquery/SKILL.md) | Use this skill for querying and analyzing the foundational RMI (Roads Management Insights) BigQuery datasets, specifically route status (routes_status) and long-term/historical traffic duration metrics (historical_travel_time). Activate when querying RMI historical datasets, managing route registration definitions, or reviewing base schema designs. |
| [`rmi-data-realtime-bigquery`](./rmi-data-realtime-bigquery/SKILL.md) | Use this skill for near real-time traffic analysis using the recent_roads_data table. This is a superset of the foundation data, enabling granular Speed Reading Interval (SRI) analysis and 60-day rolling performance audits. |
| [`rmi-data-realtime-pubsub`](./rmi-data-realtime-pubsub/SKILL.md) | Use this skill for technical details about the RMI Real-Time Pub/Sub stream, including message schema (Protobuf), key fields (SRIs, travel_duration), and integration patterns for live traffic operations. |
| [`rmi-dataviz`](./rmi-dataviz/SKILL.md) | Best practices and procedural guidelines for designing high-performance, reactive, and visually stunning map visualizations with Deck.gl and Google Maps. |
| [`rmi-routesetting`](./rmi-routesetting/SKILL.md) | Use this skill when discussing, explaining, or implementing RMI route setting, route setting strategies, selected route setting strategies, route registration strategies, or route selection. It provides foundational strategies (SINGLE_ROUTE_UNIFORM_INTERMEDIATES, SIMPLE_ORIGIN_DESTINATION, BUS_ROUTE_MONITORING, BYO_POLYLINE) for transforming geographical intent into monitored SelectedRoute objects using GA-stage Routes API, Roads API (v1), and Roads Selection API. |
| [`rmi-sql`](./rmi-sql/SKILL.md) | Use this skill for RMI-specific SQL design, including SRI analysis, route metadata parsing, bottleneck detection, and complex traffic metrics. This is the expert guide for writing high-quality queries against RMI BigQuery datasets. |

---

## 🤖 Agent Discovery & Usage

Coding assistants (Jetski, Antigravity, Gemini CLI, Cursor, Claude Code) automatically discover these skills via hierarchical upward traversal.

### How to Activate a Skill in Conversation
- Mention or prompt the agent with the relevant domain task (e.g., *'Analyze Trip Durations in BigQuery'*, *'Configure Roads Selection API'*).
- The agent's progressive disclosure mechanism will dynamically load the corresponding `SKILL.md` runbook and execute pre-validated scripts.

---

## 🧹 Lifecycle & Clean Removal

Because this bundle is self-contained within this directory, removing or updating it produces **zero side-effects** on the surrounding monorepo codebase:

```bash
# To clean uninstall all skills in this product folder:
rm -rf /Users/moritani/agentic-skills-dev/_staging/insights-samples/roads_management_insights/.agents/skills
```
