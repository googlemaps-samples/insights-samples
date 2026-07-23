# Area Analysis: Google ADK Parallel Agent on Vertex AI Agent Engine

This document details the **Field Auditor Parallel Agent**, an intelligent area-level auditing system built on the **Google Agent Development Kit (ADK)** and deployed to **Vertex AI Agent Engine (Reasoning Engine)**.

---

## 🏛️ System Architecture

The agent leverages ADK's native `ParallelAgent` class (`google.adk.agents.ParallelAgent`) to execute concurrent image track evaluations across an entire geographical area.

```
                          +----------------------------------------------+
                          |      FieldAuditorAgent (Root Orchestrator)   |
                          |      Model: gemini-3-flash / gemini-3.1-pro  |
                          +----------------------------------------------+
                                                 |
                                                 v
                          +----------------------------------------------+
                          |       google.adk.agents.ParallelAgent        |
                          |       (Isolated Concurrent Sub-Agents)       |
                          +----------------------------------------------+
                                    |                      |
                   +----------------+                      +---------------+
                   v                                                       v
   +-------------------------------+                       +-------------------------------+
   |   Sub-Agent 1: Track Seq A    |                       |   Sub-Agent N: Track Seq N    |
   |   - Driveway Obstructions     |                       |   - Clearance Signage         |
   |   - Gate Mechanism Auditing   |                       |   - Roadblock Detection       |
   +-------------------------------+                       +-------------------------------+
                   \                                                       /
                    +----------------------+------------------------------+
                                           |
                                           v
                          +----------------------------------------------+
                          |    Synthesized Area Accessibility Report     |
                          +----------------------------------------------+
```

---

## 🛠️ Core Agent Components & ADK Primitives

1. **Root Orchestrator (`google.adk.agents.llm_agent.Agent`)**:
   * Directs the high-level workflow from target GPS inputs to final synthesized reports.
   * Invokes spatial discovery tools, parallel vision analysis, and image visualization overlays.

2. **Parallel Sub-Agent Execution (`google.adk.agents.ParallelAgent`)**:
   * Native ADK shell agent that runs sub-agents concurrently in an isolated manner.
   * Enables analyzing hundreds of Street View image frames simultaneously without bottlenecking a single LLM context.

3. **Tool Suite**:
   * **`execute_spatial_query`**: Queries BigQuery (`home_depot_full_scene.tracks_unnested`) to find vehicle tracks and calculate camera relative bearings.
   * **`execute_vision_analysis`**: Dispatches image sequences to Gemini Pro Vision across concurrent track workers.
   * **`execute_visualization`**: Correlates detected features across frames and renders 2D bounding boxes (`box_2d: [ymin, xmin, ymax, xmax]`).

---

## 🔍 Area Auditing Checks & Visual Reasoning

For any target geographical site, the parallel agent evaluates:
* **Vehicle Scale Constraints**: Checks if heavy-duty delivery trucks (height > 4.5m, width > 4.0m) can navigate access points.
* **Barriers & Obstructions**: Distinguishes permanent physical barriers (fences, concrete curbs, low-hanging canopies) from temporary obstacles (parked cars, trash bins).
* **Clearance Signage**: Transcribes and extracts restriction text (e.g., "Max Clearance 14ft", "No Trucks", "Weight Limit").
* **Gated Access**: Identifies gate mechanism (Manual, Keypad/Electronic, Guard-controlled) and real-time state (Open/Closed).

---

## 🚀 Deployment to Vertex AI Agent Engine (Reasoning Engine)

The ADK agent application is packaged and registered on Vertex AI using `vertexai.preview.reasoning_engines.ReasoningEngine.create`:

```python
import vertexai
from vertexai.preview import reasoning_engines
from deploy_custom_agent import FieldAuditorEngine

# Initialize Vertex AI
vertexai.init(project="imagery-insights-sandbox", location="us-central1", staging_bucket="gs://imagery-insights-sandbox_cloudbuild")

# Deploy to Agent Engine
remote_app = reasoning_engines.ReasoningEngine.create(
    FieldAuditorEngine(project_id="imagery-insights-sandbox", location="global"),
    requirements=[
        "google-cloud-aiplatform>=1.136.0",
        "google-adk==1.24.0",
        "google-cloud-bigquery",
        "google-genai",
        "Pillow",
        "geopy",
        "pydantic"
    ],
    extra_packages=["./agents", "./tools", "./adk_app_main.py"],
    display_name="Imagery Insights Custom Agent",
    description="A Google ADK parallel agent that audits vehicle accessibility in Vertex AI Agent Engine.",
)
```

---

## 📂 Codebase File References

* **Agent Orchestrator**: [`agents/field_auditor_agent.py`](file:///Users/sarthakgy/Desktop/temporary_projects/adk_imagery_insights/agents/field_auditor_agent.py)
* **ADK Application Root**: [`adk_app_main.py`](file:///Users/sarthakgy/Desktop/temporary_projects/adk_imagery_insights/adk_app_main.py)
* **Parallel Vision Inference**: [`tools/vision_tools.py`](file:///Users/sarthakgy/Desktop/temporary_projects/adk_imagery_insights/tools/vision_tools.py)
* **Spatial BigQuery Triangulation**: [`tools/bq_tools.py`](file:///Users/sarthakgy/Desktop/temporary_projects/adk_imagery_insights/tools/bq_tools.py)
* **Agent Engine Deployer**: [`deploy_custom_agent.py`](file:///Users/sarthakgy/Desktop/temporary_projects/adk_imagery_insights/deploy_custom_agent.py)
