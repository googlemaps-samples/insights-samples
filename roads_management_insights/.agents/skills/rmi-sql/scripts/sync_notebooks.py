import os
import json
import re

script_dir = os.path.dirname(os.path.abspath(__file__))
skill_dir = os.path.dirname(script_dir)
queries_dir = os.path.join(skill_dir, "assets", "queries")
nb_dir = os.path.join(skill_dir, "assets", "notebooks")

def extract_sql_metadata_and_body(fpath):
    with open(fpath, "r", encoding="utf-8") as f:
        content = f.read()
    
    lines = content.splitlines()
    body_start_idx = len(lines)
    
    title = ""
    b_question = ""
    u_case = ""
    stage = "GA"
    
    for i, line in enumerate(lines):
        if "Query " in line and line.startswith("--"):
            title = line.replace("--", "").strip()
        elif line.startswith("-- Business Question:"):
            b_question = line.replace("-- Business Question:", "").strip()
        elif line.startswith("-- Use Case:"):
            u_case = line.replace("-- Use Case:", "").strip()
        elif line.startswith("-- Product Stage:"):
            stage = line.replace("-- Product Stage:", "").strip()
            
        if (line.startswith("-- Job ID:") or
            line.startswith("-- Persona:") or
            line.startswith("-- Purpose:") or
            line.startswith("-- Copyright") or
            line.startswith("-- Licensed") or
            line.startswith("-- you may not") or
            line.startswith("-- You may obtain") or
            line.startswith("--     https://") or
            line.startswith("-- Unless required") or
            line.startswith("-- distributed under") or
            line.startswith("-- WITHOUT WARRANTIES") or
            line.startswith("-- See the License") or
            line.startswith("-- limitations under") or
            line.strip() == "--" or
            ("Query " in line and line.startswith("--")) or
            line.startswith("-- Business Question:") or
            line.startswith("-- Use Case:") or
            line.startswith("-- Product Stage:") or
            line.startswith("-- Estimated Bytes") or
            line.startswith("-- Metadata:") or
            line.startswith("-- Optimization Impact:") or
            (not line.strip() and body_start_idx == len(lines))):
            continue
        else:
            body_start_idx = i
            break
            
    body = "\n".join(lines[body_start_idx:]).strip()
    return {"title": title, "b_question": b_question, "u_case": u_case, "stage": stage, "body": body}

# Map all sql files
sql_files = {}
for root, _, files in os.walk(queries_dir):
    for f in sorted(files):
        if f.endswith(".sql"):
            p = os.path.join(root, f)
            qid = f.split("_")[0]
            name_no_ext = f[:-4]
            meta = extract_sql_metadata_and_body(p)
            sql_files[qid] = meta
            sql_files[name_no_ext] = meta
            sql_files[f] = meta

for nb_file in sorted(os.listdir(nb_dir)):
    if not nb_file.endswith(".ipynb"):
        continue
    nb_path = os.path.join(nb_dir, nb_file)
    with open(nb_path, "r", encoding="utf-8") as fp:
        nb = json.load(fp)
        
    updated_count = 0
    cells = nb.get("cells", [])
    
    for i, cell in enumerate(cells):
        if cell["cell_type"] == "code":
            src = "".join(cell.get("source", []))
            if "%%bigquery" in src:
                # Find query name
                m = re.search(r"%%bigquery\s+(?:--project\s+\{project_id\}\s+)?(?:df_)?([a-zA-Z0-9_]+)", src)
                qname = m.group(1) if (m and m.group(1) and m.group(1) != "--") else ""
                
                # Check preceding markdown cell if qname is empty
                if not qname and i > 0 and cells[i-1]["cell_type"] == "markdown":
                    prev_src = "".join(cells[i-1].get("source", []))
                    m_prev = re.search(r"(?:###|Query\s+\d+:?)\s+([a-zA-Z0-9_]+)(?:\.sql)?", prev_src)
                    if m_prev:
                        qname = m_prev.group(1)
                    if "Hourly Pre-Aggregation" in prev_src or "Query 6" in prev_src:
                        qname = "de6_hourly_preaggregation"
                
                if not qname and "de6" in src:
                    qname = "de6_hourly_preaggregation"
                
                if qname:
                    qid = qname.split("_")[0]
                    matched_meta = sql_files.get(qname) or sql_files.get(qid)
                    if matched_meta:
                        magic_line = f"%%bigquery --project {{project_id}} df_{qname}\n"
                        sql_body = matched_meta["body"]
                        lines = [magic_line]
                        for l in sql_body.splitlines():
                            lines.append(l + "\n")
                        cell["source"] = lines
                        updated_count += 1
                        
                        # Update preceding markdown cell if present
                        if i > 0 and cells[i-1]["cell_type"] == "markdown":
                            md_lines = [f"### {qname}.sql\n"]
                            if matched_meta["b_question"]:
                                md_lines.append(f"**Business Question**: {matched_meta['b_question']}\n")
                            if matched_meta["u_case"]:
                                md_lines.append(f"**Use Case**: {matched_meta['u_case']}\n")
                            cells[i-1]["source"] = md_lines

    with open(nb_path, "w", encoding="utf-8") as fp:
        json.dump(nb, fp, indent=1)
    print(f"Refreshed {nb_file}: {updated_count} queries refreshed from source SQL.")
