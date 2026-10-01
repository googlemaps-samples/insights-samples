"""U1 Vertex AI capability spike: structured output + code execution + thinking_level + media_resolution.

Probes `gemini_client.DEFAULT_MODEL` on Vertex AI for:
1. `SCHEMA_NATIVE`: `response_mime_type='application/json'` + `response_schema` + `ToolCodeExecution`
   + `thinking_level='MEDIUM'` + `media_resolution='HIGH'` on a synthetic 640x480 3-rectangle image.
2. `SCHEMA_IN_PROMPT`: `ToolCodeExecution` + JSON schema embedded in prompt + `thinking_level='MEDIUM'`.
3. `thinking_level='MINIMAL'` + `ToolCodeExecution` (records whether it executes code or errors).
4. `thinking_level='LOW'` vs `'MEDIUM'` thought token counts on the same image/prompt.
5. Per-part `Part.from_bytes(..., media_resolution=...)` vs config-level `media_resolution`.

Writes JSON report to `docs/vertex_capabilities_2026-10-01.json` (or path passed as argv[1]).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from google.genai import types
from pydantic import BaseModel

from svi_geo import auth, gemini_client


class RectMeasurement(BaseModel):
    count: int
    widths_px: list[int]


def make_synthetic_three_rects() -> tuple[bytes, list[int]]:
    """640x480 white image with 3 solid black rectangles of widths [60, 100, 140] px."""
    img = np.full((480, 640, 3), 255, dtype=np.uint8)
    widths = [60, 100, 140]
    x_starts = [40, 160, 340]
    for x0, w in zip(x_starts, widths, strict=True):
        cv2.rectangle(img, (x0, 120), (x0 + w - 1, 320), (0, 0, 0), -1)
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("cv2.imencode failed")
    return bytes(buf), widths


def _extract_response_summary(resp: Any, expected_widths: list[int]) -> dict[str, Any]:
    exec_codes: list[str] = []
    exec_langs: list[str] = []
    outcomes: list[str] = []
    stdouts: list[str] = []
    texts: list[str] = []
    inline_images: int = 0
    for cand in resp.candidates or []:
        for p in (cand.content.parts if cand.content else None) or []:
            ec = getattr(p, "executable_code", None)
            if ec is not None:
                exec_codes.append(getattr(ec, "code", "") or "")
                exec_langs.append(str(getattr(ec, "language", "")))
            cer = getattr(p, "code_execution_result", None)
            if cer is not None:
                outcomes.append(str(getattr(cer, "outcome", "")))
                stdouts.append(getattr(cer, "output", "") or "")
            if getattr(p, "text", None):
                texts.append(p.text)
            if getattr(p, "inline_data", None) is not None:
                inline_images += 1
    full_text = "\n".join(texts)
    parsed_dict = None
    widths_within_3px = False
    try:
        parsed = gemini_client.parse_reply(full_text, RectMeasurement)
        parsed_dict = parsed.model_dump()
        got = sorted(parsed.widths_px)
        widths_within_3px = (
            parsed.count == 3
            and len(got) == 3
            and all(abs(g - e) <= 3 for g, e in zip(got, expected_widths, strict=True))
        )
    except Exception as err:  # noqa: BLE001
        parsed_dict = {"parse_error": str(err)[:300]}

    u = resp.usage_metadata
    usage_dict = {
        "prompt_token_count": getattr(u, "prompt_token_count", None),
        "candidates_token_count": getattr(u, "candidates_token_count", None),
        "thoughts_token_count": getattr(u, "thoughts_token_count", None),
        "tool_use_prompt_token_count": getattr(u, "tool_use_prompt_token_count", None),
        "cached_content_token_count": getattr(u, "cached_content_token_count", None),
        "total_token_count": getattr(u, "total_token_count", None),
    }
    return {
        "http_ok": True,
        "executable_code_count": len(exec_codes),
        "executable_code_languages": exec_langs,
        "outcomes": outcomes,
        "outcome_ok": any("OUTCOME_OK" in o for o in outcomes),
        "stdout_preview": [s[:300] for s in stdouts],
        "inline_image_parts": inline_images,
        "parsed": parsed_dict,
        "widths_within_3px": widths_within_3px,
        "usage_metadata": usage_dict,
    }


def run_probe(project: str) -> dict[str, Any]:
    creds = auth.get_credentials()
    client = gemini_client.make_vertex_client(project, credentials=creds)
    png_bytes, expected_widths = make_synthetic_three_rects()
    base_prompt = (
        "Use Python code execution (with cv2 or numpy/PIL) to load the attached image, threshold "
        "the black rectangles on the white background, measure the exact pixel width of each "
        "rectangle (sorted ascending), print 'MEASURE: ' followed by JSON, and return count and widths_px."
    )
    img_part = types.Part.from_bytes(data=png_bytes, mime_type="image/png")
    results: dict[str, Any] = {
        "date": dt.date.today().isoformat(),
        "project": project,
        "model": gemini_client.DEFAULT_MODEL,
        "location": gemini_client.DEFAULT_LOCATION,
        "sdk_version": getattr(types, "__version__", "google-genai"),
        "expected_widths_px": expected_widths,
        "probes": {},
    }

    # Probe 1: SCHEMA_NATIVE (response_schema + ToolCodeExecution + MEDIUM thinking + HIGH media)
    try:
        cfg_native = types.GenerateContentConfig(
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            response_mime_type="application/json",
            response_schema=RectMeasurement,
            tools=[types.Tool(code_execution=types.ToolCodeExecution())],
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.MEDIUM),
            media_resolution=types.MediaResolution.MEDIA_RESOLUTION_HIGH,
            seed=7,
        )
        resp1 = client.models.generate_content(
            model=gemini_client.DEFAULT_MODEL,
            contents=[
                types.Content(role="user", parts=[types.Part.from_text(text=base_prompt), img_part])
            ],
            config=cfg_native,
        )
        results["probes"]["schema_native_medium_high"] = _extract_response_summary(
            resp1, expected_widths
        )
    except Exception as err:  # noqa: BLE001
        results["probes"]["schema_native_medium_high"] = {
            "http_ok": False,
            "error_type": type(err).__name__,
            "error": str(err)[:500],
        }

    # Probe 2: SCHEMA_IN_PROMPT (ToolCodeExecution + prompt schema + MEDIUM thinking + HIGH media)
    try:
        extra = (
            "You may use Python code execution to inspect the image. End your reply with ONLY a "
            "single JSON object matching this JSON schema:\n"
            + json.dumps(RectMeasurement.model_json_schema())
        )
        cfg_prompt = types.GenerateContentConfig(
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            tools=[types.Tool(code_execution=types.ToolCodeExecution())],
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.MEDIUM),
            media_resolution=types.MediaResolution.MEDIA_RESOLUTION_HIGH,
            seed=7,
        )
        resp2 = client.models.generate_content(
            model=gemini_client.DEFAULT_MODEL,
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(text=base_prompt),
                        img_part,
                        types.Part.from_text(text=extra),
                    ],
                )
            ],
            config=cfg_prompt,
        )
        results["probes"]["schema_in_prompt_medium_high"] = _extract_response_summary(
            resp2, expected_widths
        )
    except Exception as err:  # noqa: BLE001
        results["probes"]["schema_in_prompt_medium_high"] = {
            "http_ok": False,
            "error_type": type(err).__name__,
            "error": str(err)[:500],
        }

    # Probe 3: MINIMAL thinking + code execution
    try:
        cfg_min = types.GenerateContentConfig(
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            tools=[types.Tool(code_execution=types.ToolCodeExecution())],
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.MINIMAL),
            media_resolution=types.MediaResolution.MEDIA_RESOLUTION_HIGH,
            seed=7,
        )
        resp3 = client.models.generate_content(
            model=gemini_client.DEFAULT_MODEL,
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(text=base_prompt),
                        img_part,
                    ],
                )
            ],
            config=cfg_min,
        )
        results["probes"]["code_exec_minimal_thinking"] = _extract_response_summary(
            resp3, expected_widths
        )
    except Exception as err:  # noqa: BLE001
        results["probes"]["code_exec_minimal_thinking"] = {
            "http_ok": False,
            "error_type": type(err).__name__,
            "error": str(err)[:500],
        }

    # Probe 4: LOW vs MEDIUM thinking on plain structured output (no code exec)
    plain_prompt = "Count the black rectangles in this image and estimate their pixel widths."
    for lvl_name, lvl_enum in [
        ("LOW", types.ThinkingLevel.LOW),
        ("MEDIUM", types.ThinkingLevel.MEDIUM),
    ]:
        try:
            cfg_plain = types.GenerateContentConfig(
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                response_mime_type="application/json",
                response_schema=RectMeasurement,
                thinking_config=types.ThinkingConfig(thinking_level=lvl_enum),
                media_resolution=types.MediaResolution.MEDIA_RESOLUTION_MEDIUM,
                seed=7,
            )
            resp_p = client.models.generate_content(
                model=gemini_client.DEFAULT_MODEL,
                contents=[
                    types.Content(
                        role="user", parts=[types.Part.from_text(text=plain_prompt), img_part]
                    )
                ],
                config=cfg_plain,
            )
            results["probes"][f"plain_thinking_{lvl_name.lower()}"] = _extract_response_summary(
                resp_p, expected_widths
            )
        except Exception as err:  # noqa: BLE001
            results["probes"][f"plain_thinking_{lvl_name.lower()}"] = {
                "http_ok": False,
                "error_type": type(err).__name__,
                "error": str(err)[:500],
            }

    native = results["probes"].get("schema_native_medium_high", {})
    if (
        native.get("http_ok")
        and native.get("executable_code_count", 0) >= 1
        and native.get("outcome_ok")
        and native.get("widths_within_3px")
    ):
        results["recommended_mode"] = "SCHEMA_NATIVE"
    else:
        results["recommended_mode"] = "SCHEMA_IN_PROMPT"
    return results


def main() -> None:
    project = (
        os.environ.get("PROJECT_ID") or os.environ.get("SVI_PROJECT") or "imagery-insights-sandbox"
    )
    out_path = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else Path(__file__).resolve().parent.parent / "docs" / "vertex_capabilities_2026-10-01.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    report = run_probe(project)
    out_path.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Wrote {out_path} (recommended_mode={report['recommended_mode']})")


if __name__ == "__main__":
    main()
