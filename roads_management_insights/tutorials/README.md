# RMI Tutorial Series: From Setup to Insight

This directory contains a progressive series of Jupyter notebooks designed to onboard developers to the **Roads Management Insights (RMI)** ecosystem.

## 🚀 Learning Path

| Module | Notebook | Audience | Open | Key Learning |
| :--- | :--- | :--- | :--- | :--- |
| **01** | [Project Setup](./01_project_setup.ipynb) | New Users | [![Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/googlemaps-samples/insights-samples/blob/main/roads_management_insights/tutorials/01_project_setup.ipynb) | Auth, API, and IAM roles. |
| **02** | [Route Setting](./02_route_setting.ipynb) | Developers | [![Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/googlemaps-samples/insights-samples/blob/main/roads_management_insights/tutorials/02_route_setting.ipynb) | Registering routes via REST. |
| **03** | [BigQuery Verification](./03_bq_verification.ipynb) | Data Analysts | [![Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/googlemaps-samples/insights-samples/blob/main/roads_management_insights/tutorials/03_bq_verification.ipynb) | Trend analysis and SQL audits. |
| **04** | [Pub/Sub Real-time](./04_pubsub_verification.ipynb) | Operations | [![Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/googlemaps-samples/insights-samples/blob/main/roads_management_insights/tutorials/04_pubsub_verification.ipynb) | JSON traffic feeds & BQ subs. |
| **05** | [Roads v2 Preview](./05_roads_v2_testing.ipynb) | Partners | [![Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/googlemaps-samples/insights-samples/blob/main/roads_management_insights/tutorials/05_roads_v2_testing.ipynb) | Topology and GPS snapping. |

## 🛠 Prerequisites

To execute these notebooks, you will need:
1.  **Google Cloud Project**: With billing enabled.
2.  **RMI Onboarding**: Your Project Number must be registered with the Google RMI team.
3.  **Permissions**: `roles/roads.roadsSelectionAdmin` or equivalent.
4.  **Environment**: [Google Colab](https://colab.research.google.com/) (Recommended) or a local Jupyter environment.

## 💡 Best Practices

- **CLI-First**: These tutorials prioritize the `gcloud` CLI and BigQuery magics for transparency and ease of automation.
- **Cost Efficiency**: See Tutorial 03 for the "Gold Standard" partition pruning patterns to minimize query costs.
- **Real-time Scale**: See Tutorial 04 for how to use Pub/Sub filters to reduce ingestion volume.

---
**For more advanced RMI query patterns, visit the official [RMI Sample Queries Repository](https://github.com/googlemaps-samples/insights-samples/tree/main/roads_management_insights/rmi_sample_queries).**
