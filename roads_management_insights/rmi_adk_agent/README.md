# RMI ADK Agent

This directory contains a demo AI agent for the Roads Management Insights (RMI) service built using Google's Agent Development Kit (ADK). The agent is designed to answer questions about RMI data residing in BigQuery and can execute SQL queries to retrieve relevant information.

## Prerequisites

- [uv](https://github.com/astral-sh/uv) installed on your machine.
- [Google Cloud SDK (gcloud)](https://cloud.google.com/sdk/docs/install) installed and authenticated.

## Setup

1.  **Clone the repository** (if you haven't already).
2.  **Navigate to the agent directory**:
    ```bash
    cd roads_management_insights/rmi_adk_agent
    ```
3.  **Create and sync the virtual environment**:
    Using `uv`, you can quickly set up the environment and install dependencies:
    ```bash
    uv sync
    ```
    This will create a `.venv` directory and install all required packages listed in `pyproject.toml`.

## Environment Variables

The agent requires several environment variables and configurations to function correctly:

### 1. Google Cloud Authentication
The agent uses Application Default Credentials (ADC). Authenticate your local environment:
```bash
gcloud auth application-default login
```

### 2. Configuration via `.env` file
The agent can also be configured using a `.env` file in the project root. This is the recommended way to manage environment-specific settings. 

Create a file named `.env` in the `roads_management_insights/rmi_adk_agent/` directory with the following content:

```bash
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=your-region
RMI_DATASET=your-rmi-dataset-id
GOOGLE_GENAI_USE_VERTEXAI=TRUE
# GOOGLE_API_KEY=your-api-key (if not using ADC)
```

- `GOOGLE_CLOUD_PROJECT`: The ID of your Google Cloud project.
- `RMI_DATASET`: The ID of the BigQuery dataset containing RMI data.
- `GOOGLE_CLOUD_LOCATION`: The region where your Google Cloud resources are located (e.g., `us-central1`).
- `GOOGLE_GENAI_USE_VERTEXAI`: Set to `TRUE` to use Vertex AI for the agent's language model.

These variables are automatically loaded by the agent upon startup.


## Running the Agent

You can run the agent using the `uv run` command. Since the agent is defined in `src/agent.py`, you can interact with it using the ADK CLI or by importing it into a script.

### Using the ADK built-in runtimes (Recommended)
If you have the `google-adk` package installed, you can use its built-in tools to chat with the agent using either the web UI 

```bash
uv run adk web
```

or the CLI interface

```bash
uv run adk run src
```
