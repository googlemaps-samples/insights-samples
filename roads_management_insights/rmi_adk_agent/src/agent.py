# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from google.adk.agents import Agent
from google.adk.planners import BuiltInPlanner
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools.bigquery import BigQueryCredentialsConfig
from google.adk.tools.bigquery import BigQueryToolset
from google.adk.tools.bigquery.config import BigQueryToolConfig
from google.adk.tools.bigquery.config import WriteMode
import google.auth
from google.genai import types

from src import prompts

# Define a tool configuration to block any write operations for safety
tool_config = BigQueryToolConfig(write_mode=WriteMode.BLOCKED)

# Use application default credentials
# This will use the credentials from the gcloud CLI
try:
    application_default_credentials, project_id = google.auth.default()
    credentials_config = BigQueryCredentialsConfig(
        credentials=application_default_credentials
    )
    print(f"Successfully loaded Google Cloud credentials for project: {project_id}")
except Exception as e:
    print(f"Error loading Google Cloud credentials: {e}")
    print("Please make sure you have authenticated with 'gcloud auth application-default login'")
    # Handle the case where credentials are not available
    application_default_credentials = None
    credentials_config = None

# Instantiate a BigQuery toolset
if credentials_config:
    bigquery_toolset = BigQueryToolset(
        credentials_config=credentials_config, bigquery_tool_config=tool_config
    )
else:
    bigquery_toolset = []


# Agent Definition
bq_agent = Agent(
    model="gemini-3-flash-preview",
    name="bigquery_agent",
    description=(
        "Agent to answer questions about BigQuery data and execute SQL queries."
    ),
    instruction=prompts.BQ_AGENT_PROMPT,
    tools=[bigquery_toolset] if bigquery_toolset else [],
)

root_agent = Agent(
    model="gemini-3-flash-preview",
    name="RMI_agent",
    description=(
        "Agent to answer questions about RMI data residing in BigQuery."
    ),
    planner=BuiltInPlanner(
        thinking_config=types.ThinkingConfig(
            include_thoughts=True,
            thinking_level='medium',
        )
    ),
    instruction=prompts.RMI_AGENT_PROMPT,
    tools=[AgentTool(bq_agent)],
)