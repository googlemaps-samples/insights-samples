# Roads Management Insights (RMI) Agentic Plugins Catalog

This directory hosts modular, multi-platform Agent Plugins for **Google Maps Platform — Roads Management Insights (RMI)**, adhering to the open [Agent Plugins Specification](https://agent-plugins.org/) and compatible with **Antigravity**, **Claude Code**, and **OpenAI Codex CLI**.

---

## 🧭 Available Plugins (1)

```mermaid
flowchart TD
  %% Status: Current State
  RMI_CORE["<b>rmi-core</b> (15 Skills)<br/><i>Roads Management Insights (RMI)</i>"]
  AGENTS_MIRROR[".agents/skills/<br/><i>Workspace auto-discovery mirror</i>"] -->|mirrors| RMI_CORE
```

| Plugin ID | Stage | Version | Skills | Description |
| :--- | :---: | :---: | :---: | :--- |
| **[`rmi-core`](./rmi-core/README.md)** | **GA** | `2026.11.13` | `15` | Curated suite of agentic skills for Roads Management Insights (RMI) development, APIs, data analytics, and operational runbooks. |

---

## 🚀 Installation Instructions

### 1. Default Repository Clone Discovery (`.agents/skills/`)

`.agents/skills/` holds a copy of the `rmi-core` GA skills for workspace auto-discovery when the repo is cloned. `plugins/rmi-core/skills/` is the source, and both are kept identical by the publishing pipeline.

### 2. Installing via Agent Plugin CLIs

#### `rmi-core`

- **Antigravity**:
  ```bash
  # From a local clone of insights-samples:
  agy plugin install ./roads_management_insights/plugins/rmi-core
  # Remote GitHub tree URL (untested):
  agy plugin install https://github.com/googlemaps-samples/insights-samples/tree/main/roads_management_insights/plugins/rmi-core
  ```
- **Claude Code**:
  ```bash
  claude --plugin-dir ./roads_management_insights/plugins/rmi-core
  ```
- **OpenAI Codex CLI**:
  Copy or symlink `./roads_management_insights/plugins/rmi-core` into your Codex plugins directory.

