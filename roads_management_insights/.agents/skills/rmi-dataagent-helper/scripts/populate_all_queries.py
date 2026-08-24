#!/usr/bin/env python3
"""
Populates all 36 golden SQL queries from rmi-sql into the corresponding persona
asset templates for rmi-dataagent-helper.
"""

import glob
import json
import os
import re

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
QUERIES_BASE = os.path.join(REPO_ROOT, "src/rmi-sql/assets/queries")
ASSETS_BASE = os.path.join(REPO_ROOT, "src/rmi-dataagent-helper/assets")

PERSONA_MAPPING = {
    "traffic_ops_agent_expert.json": "traffic_operations_manager",
    "urban_planner_agent_expert.json": "urban_planner",
    "bigquery_admin_agent_expert.json": "bigquery_admin",
    "data_engineer_agent_expert.json": "data_engineer",
    "data_scientist_agent_expert.json": "data_scientist",
    "rmi_planner_agent_expert.json": "rmi_planner",
}

def parse_sql_file(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # Extract business question
    bq_match = re.search(r"--\s*Business Question:\s*(.+)", content)
    if bq_match:
        question = bq_match.group(1).strip()
    else:
        title_match = re.search(r"--\s*.*Query \d+:\s*(.+)", content)
        question = title_match.group(1).strip() if title_match else os.path.basename(filepath)

    # Extract SQL part
    lines = content.split("\n")
    sql_lines = []
    in_block_comment = False
    start_collecting = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("/*"):
            in_block_comment = True
            continue
        if in_block_comment:
            if "*/" in stripped:
                in_block_comment = False
            continue
        if not start_collecting:
            if stripped.startswith("--") or not stripped:
                continue
            start_collecting = True

        sql_lines.append(line)

    sql_body = "\n".join(sql_lines).strip()
    # Normalize dataset placeholders
    sql_body = sql_body.replace("`LINKED_DATASET_NAME.", "`my_project.src_boston_ga.")
    sql_body = sql_body.replace("`your-project.your-dataset.", "`my_project.src_boston_ga.")

    return {
        "naturalLanguageQuestion": question,
        "sqlQuery": sql_body
    }

def main():
    total_queries = 0
    for template_name, query_folder in PERSONA_MAPPING.items():
        template_path = os.path.join(ASSETS_BASE, template_name)
        folder_path = os.path.join(QUERIES_BASE, query_folder)
        sql_files = sorted(glob.glob(os.path.join(folder_path, "*.sql")))

        if not os.path.exists(template_path):
            print(f"❌ Template not found: {template_path}")
            continue

        with open(template_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        example_queries = []
        for sql_file in sql_files:
            parsed = parse_sql_file(sql_file)
            example_queries.append(parsed)

        data["dataAnalyticsAgent"]["stagingContext"]["exampleQueries"] = example_queries
        
        # Ensure all 3 core tables are bound
        data["dataAnalyticsAgent"]["stagingContext"]["datasourceReferences"] = {
            "bq": {
                "tableReferences": [
                    {"projectId": "my_project", "datasetId": "src_boston_ga", "tableId": "recent_roads_data"},
                    {"projectId": "my_project", "datasetId": "src_boston_ga", "tableId": "historical_travel_time"},
                    {"projectId": "my_project", "datasetId": "src_boston_ga", "tableId": "routes_status"}
                ]
            }
        }

        with open(template_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        print(f"✅ {template_name}: Injected {len(example_queries)} queries from {query_folder}")
        total_queries += len(example_queries)

    print(f"\n🎉 Successfully injected all {total_queries} golden SQL queries across all 6 persona templates!")

if __name__ == "__main__":
    main()
