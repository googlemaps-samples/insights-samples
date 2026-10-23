# Decision Record: Structured Outputs + Code Execution on Vertex AI (`2026-10-01`)

- **Status:** Adopted (`CodeExecSchemaMode.DEFAULT = CodeExecSchemaMode.SCHEMA_NATIVE`)
- **Artefact:** [`docs/vertex_capabilities_2026-10-01.json`](../../docs/vertex_capabilities_2026-10-01.json)
- **Probe script:** [`scripts/probe_vertex_capabilities.py`](../../scripts/probe_vertex_capabilities.py)
- **Live drift guard:** `tests/test_gemini_live.py::test_pinned_code_exec_schema_mode_still_works`

## Context

Earlier revisions of `svi_geo.gemini_client._build_config` assumed that `response_schema` (`application/json` constrained decoding) and `tools=[Tool(code_execution=ToolCodeExecution())]` could not be combined in a single Vertex AI `generate_content` request, falling back to embedding `schema.model_json_schema()` in the prompt text (`SCHEMA_IN_PROMPT`).

## Live Probe Results (`2026-10-01`, `location="global"`)

Tested on a synthetic `640x480` white image containing 3 solid black rectangles of ground-truth widths `[60, 100, 140]` px (`_RectMeasurement(count: int, widths_px: list[int])`):

| Probe configuration | HTTP | `executable_code` parts | Final outcome | Parsed output | Widths within ±3 px? | `prompt_token_count` | `tool_use_prompt_token_count` | `thoughts_token_count` | `candidates_token_count` | Total tokens |
|---|---:|---:|---|---|---|---:|---:|---:|---:|---:|
| `SCHEMA_NATIVE` (`MEDIUM` thinking, `HIGH` media) | 200 OK | 1 (`PYTHON`) | `OUTCOME_OK` | `{"count": 3, "widths_px": [60, 100, 140]}` | **Yes** (exact) | 1,208 | 1,467 | 77 | 335 | **3,087** |
| `SCHEMA_IN_PROMPT` (`MEDIUM` thinking, `HIGH` media) | 200 OK | 4 (`PYTHON`) | `OUTCOME_OK` (after 2 retries) | `{"count": 3, "widths_px": [60, 100, 140]}` | **Yes** (exact) | 1,220 | 2,167 | 220 | 1,608 | **5,215** |
| Code Exec + `MINIMAL` thinking (`HIGH` media) | 200 OK | 1 (`PYTHON`) | `OUTCOME_OK` | `{"count": 3, "widths_px": [60, 100, 140]}` | **Yes** (exact) | 1,122 | 1,404 | `null` | 432 | **2,958** |
| Plain (`no code exec`, `LOW` thinking, `MEDIUM` media) | 200 OK | 0 | — | `{"count": 3, "widths_px": [94, 156, 219]}` | **No** (+56% error) | 639 | `null` | 366 | 25 | 1,030 |
| Plain (`no code exec`, `MEDIUM` thinking, `MEDIUM` media) | 200 OK | 0 | — | `{"count": 3, "widths_px": [94, 156, 220]}` | **No** (+57% error) | 639 | `null` | 1,141 | 25 | 1,805 |

## Findings & Decision

1. **Native Structured Outputs + Code Execution works on Vertex AI:** `SCHEMA_NATIVE` (`response_mime_type="application/json"` + `response_schema` + `ToolCodeExecution`) is accepted by Vertex AI and produces exact pixel measurements (`[60, 100, 140]`) in a single code-execution turn using **41% fewer total tokens** (3,087 vs 5,215) than `SCHEMA_IN_PROMPT`.
2. **Why Code Execution matters for pixel measurement:** Without code execution, plain visual estimation (`plain_thinking_low` and `plain_thinking_medium`) hallucinated rectangle widths `[94, 156, 219]` (off by > 50% due to internal image tiling/rescaling), whereas code execution measured exact pixel widths `[60, 100, 140]`.
3. **Thinking level & token accounting:**
   - `tool_use_prompt_token_count` is populated on `usage_metadata` (1,467 tokens in `SCHEMA_NATIVE`) and must be summed into `CostTracker.tool_use_prompt_tokens` and `input_tokens`.
   - On plain structured output calls, `thinking_level="LOW"` reduced `thoughts_token_count` from `1,141` (`MEDIUM`) to `366` (**−68%**).
   - Although `MINIMAL` thinking succeeded on the synthetic probe, official Gemini 3 Flash documentation specifies enabling thinking (`MEDIUM`) for code execution with real-world images; we therefore pin `thinking_level="MEDIUM"` for the single agentic measurement cell per notebook.
4. **Shipping Policy:**
   - Pin `CodeExecSchemaMode.DEFAULT = CodeExecSchemaMode.SCHEMA_NATIVE`.
   - Keep `CodeExecSchemaMode.SCHEMA_IN_PROMPT` available as an explicit fallback mode and keep the code-side `validator` mandatory in both modes.
