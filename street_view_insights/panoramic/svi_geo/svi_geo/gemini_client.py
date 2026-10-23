"""Gemini access: inline image bytes only, schema-validated replies, budget + cost accounting.

Hard rules (tested in tests/test_no_uri_parts.py and here):
* Images are downloaded with the user's own credentials and sent inline as bytes
  (`Part.from_bytes`). No URI parts, no file uploads, no batch prediction.
* Every request declares a pydantic `response_schema` (JSON mode, constrained decoding);
  replies are validated in code, then by an optional per-call `validator` (e.g. geometry
  range checks), with one re-ask on either failure. Only the model's final text is parsed:
  tool stdout never counts as the answer. Code-execution requests always require a
  `validator` and trace check (`check_code_exec_trace`).
* `MAX_GEMINI_CALLS` (default 500, `None` = unlimited) and a concurrency semaphore (default
  8, halved after consecutive 429s) bound each run; `CostTracker` sums `usage_metadata`
  (thinking tokens billed as output, tool-use intermediate tokens billed as input, cached
  tokens discounted 75%).
* Failures are loud: a batch in which every request fails raises `AllRequestsFailed`, every
  failure is counted with its first messages kept, and `GeminiRunner.check()` raises
  `GeminiFailures` so a notebook cell cannot silently continue on missing results.
"""

from __future__ import annotations

import asyncio
import dataclasses
import enum
import hashlib
import json
import re
import time
import warnings
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol

import cv2
import numpy as np
from pydantic import BaseModel, ValidationError

from svi_geo import auth, images


def _m(suffix: str) -> str:
    return f"gemini-{suffix}"


DEFAULT_MODEL = "gemini-3.5-flash"
DEFAULT_LOCATION = "global"
DEFAULT_MAX_CALLS = 500
DEFAULT_CONCURRENCY = 8
MAX_IMAGE_SIDE = 1536
# USD per 1M tokens, prompts <=200k tokens, global endpoint.
# Source: https://cloud.google.com/vertex-ai/generative-ai/pricing (fetched 2026-09-30).
# Check current Vertex AI pricing for your model/region and pass your own `prices=` to CostTracker.
DEFAULT_PRICES = {"input_per_m": 1.50, "output_per_m": 9.00}
PRICES_BY_MODEL: dict[str, dict[str, float]] = {
    DEFAULT_MODEL: dict(DEFAULT_PRICES),
    _m("3.1-pro-preview"): {"input_per_m": 2.00, "output_per_m": 12.00},
    _m("3.5-flash-lite"): {"input_per_m": 0.30, "output_per_m": 2.50},
    _m("3-flash-preview"): {"input_per_m": 0.50, "output_per_m": 3.00},
    "gemini-2.5-flash": {"input_per_m": 0.30, "output_per_m": 2.50},
    "gemini-2.5-flash-lite": {"input_per_m": 0.10, "output_per_m": 0.40},
    "gemini-2.5-pro": {"input_per_m": 1.25, "output_per_m": 10.00},
}
# Regional (non-global) endpoints carry a 10% premium for Gemini 3.5 Flash on Vertex AI.
PRICES_NON_GLOBAL_BY_MODEL: dict[str, dict[str, float]] = {
    DEFAULT_MODEL: {"input_per_m": 1.65, "output_per_m": 9.90},
}
MAX_FAILURE_MESSAGES = 5
CACHED_INPUT_DISCOUNT = 0.25  # 75% discount on cached tokens -> billed at 0.25x input rate

_URI_RE = re.compile(r"^\s*(gs|https?)://", re.I)
_FORBIDDEN_CODE_EXEC_RE = re.compile(
    r"\b(?:requests|urllib|socket|subprocess|http\.client|ftplib)\b"
    r"|os\s*\.\s*(?:system|popen|exec\w*|spawn\w*)"
    r"|open\s*\(\s*['\"](?!/tmp/)/[^'\"]+['\"]\s*,\s*['\"][wa+]",
    re.I,
)


class BudgetExceeded(RuntimeError):
    """The run hit MAX_GEMINI_CALLS or max_usd; no further requests are sent."""


class AllRequestsFailed(RuntimeError):
    """Every request of a batch failed (e.g. 401/403 credentials, wrong model or region)."""


class GeminiFailures(RuntimeError):
    """`GeminiRunner.check()` found more failed requests than the caller tolerates."""


class CodeExecValidationError(ValueError):
    """A code-execution response violated the trace verification contract."""


class CodeExecNotUsed(CodeExecValidationError):
    """A code-execution request returned no PYTHON `executable_code` part."""


def prices_for(model: str, location: str = DEFAULT_LOCATION) -> dict[str, float]:
    """Price table for `model` and `location`; unknown models fall back to DEFAULT_PRICES."""
    loc = (location or DEFAULT_LOCATION).strip().lower()
    if loc != "global" and model in PRICES_NON_GLOBAL_BY_MODEL:
        return dict(PRICES_NON_GLOBAL_BY_MODEL[model])
    if model in PRICES_BY_MODEL:
        return dict(PRICES_BY_MODEL[model])
    warnings.warn(
        f"no price entry for model {model!r}; cost estimates use DEFAULT_PRICES {DEFAULT_PRICES}",
        UserWarning,
        stacklevel=2,
    )
    return dict(DEFAULT_PRICES)


# --------------------------------------------------------------------------- images/parts


def prepare_image(
    image: np.ndarray | bytes, max_side: int = MAX_IMAGE_SIDE, quality: int = 90
) -> bytes:
    """Decode/downscale in code (longest side <= max_side) and return JPEG bytes."""
    if isinstance(image, (bytes, bytearray)):
        arr = images.decode(bytes(image))
    else:
        arr = image
    arr = images.fit_within(arr, max_side)
    return images.encode_jpeg(arr, quality=quality)


def build_parts(items: Sequence[str | bytes | np.ndarray]) -> list[Any]:
    """Text -> text part; bytes/ndarray -> inline JPEG part. URIs are rejected outright."""
    from google.genai import types

    parts = []
    for it in items:
        if isinstance(it, str):
            if _URI_RE.match(it):
                raise ValueError(
                    "URI inputs are not allowed; download the bytes and pass them inline"
                )
            parts.append(types.Part.from_text(text=it))
        elif isinstance(it, (bytes, bytearray, np.ndarray)):
            data = prepare_image(it)
            parts.append(types.Part.from_bytes(data=data, mime_type="image/jpeg"))
        else:
            raise TypeError(f"unsupported part type {type(it)!r}")
    return parts


def _first_image_shape(items: Sequence[str | bytes | np.ndarray]) -> tuple[int, int] | None:
    for it in items:
        if isinstance(it, np.ndarray) and it.ndim >= 2:
            return int(it.shape[0]), int(it.shape[1])
        if isinstance(it, (bytes, bytearray)):
            try:
                arr = images.decode(bytes(it))
                return int(arr.shape[0]), int(arr.shape[1])
            except Exception:  # noqa: BLE001
                continue
    return None


# --------------------------------------------------------------------------- code-execution trace


@dataclasses.dataclass
class CodeExecStep:
    code: str
    language: str = "PYTHON"
    outcome: str = "OUTCOME_OK"
    stdout: str = ""
    inline_images: list[bytes] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class CodeExecTrace:
    steps: list[CodeExecStep] = dataclasses.field(default_factory=list)

    @property
    def has_python_code(self) -> bool:
        return any(
            bool((s.code or "").strip()) and "PYTHON" in (s.language or "").upper()
            for s in self.steps
        )

    @property
    def last_outcome(self) -> str:
        for s in reversed(self.steps):
            if s.outcome:
                return str(s.outcome)
        return ""

    @property
    def ok(self) -> bool:
        return self.has_python_code and "OUTCOME_OK" in self.last_outcome.upper()

    @property
    def stdout(self) -> str:
        return "\n".join(s.stdout for s in self.steps if s.stdout)

    @property
    def inline_images(self) -> list[bytes]:
        out: list[bytes] = []
        for s in self.steps:
            out.extend(s.inline_images)
        return out


def check_code_exec_trace(
    trace: CodeExecTrace | None,
    *,
    expect_stdout: str | re.Pattern[str] | None = None,
    sent_image_shape: tuple[int, int] | None = None,
) -> CodeExecTrace:
    """Verify a `CodeExecTrace` against the agentic-vision contract (§4.2 / U5):

    1. >= 1 `executable_code` part with `language == PYTHON` (else raise `CodeExecNotUsed`).
    2. Last `code_execution_result.outcome` contains `OUTCOME_OK`.
    3. Static guard on `code` rejecting network/subprocess imports or file writes outside `/tmp`.
    4. Optional `expect_stdout` regex matched against `trace.stdout`.
    5. Any returned inline images decode cleanly and match `sent_image_shape` aspect ratio (+-2%).
    """
    if trace is None or not trace.has_python_code:
        raise CodeExecNotUsed("code_execution trace has no PYTHON executable_code part")
    for step in trace.steps:
        m = _FORBIDDEN_CODE_EXEC_RE.search(step.code or "")
        if m:
            raise CodeExecValidationError(
                f"forbidden network/system/file pattern in executable_code: {m.group(0)!r}"
            )
    if "OUTCOME_OK" not in trace.last_outcome.upper():
        raise CodeExecValidationError(
            f"code_execution did not finish with OUTCOME_OK (last outcome: {trace.last_outcome!r})"
        )
    if expect_stdout is not None:
        rx = re.compile(expect_stdout) if isinstance(expect_stdout, str) else expect_stdout
        if not rx.search(trace.stdout):
            raise CodeExecValidationError(
                f"code_execution stdout did not match {rx.pattern!r}; got {trace.stdout[:240]!r}"
            )
    if sent_image_shape is not None and trace.inline_images:
        sh, sw = sent_image_shape[:2]
        if sh > 0 and sw > 0:
            expected_aspect = sw / sh
            for raw in trace.inline_images:
                arr = images.decode(bytes(raw))
                oh, ow = arr.shape[:2]
                if oh <= 0 or ow <= 0:
                    raise CodeExecValidationError("decoded inline overlay image has empty shape")
                got_aspect = ow / oh
                rel_diff = abs(got_aspect - expected_aspect) / max(1e-6, expected_aspect)
                if rel_diff > 0.02:
                    raise CodeExecValidationError(
                        f"inline overlay aspect {got_aspect:.3f} ({ow}x{oh}) differs from "
                        f"sent image aspect {expected_aspect:.3f} ({sw}x{sh}) by {rel_diff:.1%} > 2%"
                    )
    return trace


# --------------------------------------------------------------------------- cost


@dataclasses.dataclass
class CostTracker:
    prices: dict[str, float] = dataclasses.field(default_factory=lambda: dict(DEFAULT_PRICES))
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0  # candidates + thoughts
    thoughts_tokens: int = 0
    tool_use_prompt_tokens: int = 0
    cached_tokens: int = 0
    media_tokens: int = 0
    requests: int = 0  # logical requests (a re-ask is a second call, not a second request)
    failures: int = 0
    skipped_budget: int = 0  # requests not sent because MAX_GEMINI_CALLS or max_usd was reached
    fallbacks: int = 0
    code_exec_runs: int = 0
    code_exec_ok: int = 0
    failure_messages: list[str] = dataclasses.field(default_factory=list)

    def record_failure(self, message: str) -> None:
        self.failures += 1
        if len(self.failure_messages) < MAX_FAILURE_MESSAGES:
            self.failure_messages.append(message[:500])

    def add(self, usage: Any) -> None:
        self.calls += 1
        if usage is None:
            return
        get = usage.get if isinstance(usage, dict) else (lambda k, d=None: getattr(usage, k, d))
        prompt_base = int(get("prompt_token_count") or 0)
        tool_use = int(get("tool_use_prompt_token_count") or 0)
        cached = int(get("cached_content_token_count") or 0)
        thoughts = int(get("thoughts_token_count") or 0)
        candidates = int(get("candidates_token_count") or 0)

        media = 0
        details = get("prompt_tokens_details") or []
        for item in details:
            mod = str(
                (item.get("modality") if isinstance(item, dict) else getattr(item, "modality", ""))
                or ""
            ).upper()
            if "IMAGE" in mod or "VIDEO" in mod or "MEDIA" in mod:
                tc = (
                    item.get("token_count")
                    if isinstance(item, dict)
                    else getattr(item, "token_count", 0)
                )
                media += int(tc or 0)

        self.input_tokens += prompt_base + tool_use
        self.tool_use_prompt_tokens += tool_use
        self.cached_tokens += cached
        self.media_tokens += media
        self.output_tokens += candidates + thoughts
        self.thoughts_tokens += thoughts

    @property
    def thinking_share(self) -> float:
        return (self.thoughts_tokens / self.output_tokens) if self.output_tokens > 0 else 0.0

    @property
    def usd(self) -> float:
        cached = min(self.cached_tokens, self.input_tokens)
        uncached = max(0, self.input_tokens - cached)
        eff_input = uncached + cached * CACHED_INPUT_DISCOUNT
        return (
            eff_input / 1e6 * self.prices["input_per_m"]
            + self.output_tokens / 1e6 * self.prices["output_per_m"]
        )

    def summary(self, ceiling: float | None = None) -> str:
        ceil_part = f" ceiling=${ceiling:.2f}" if ceiling is not None else ""
        return (
            f"Gemini calls={self.calls} requests={self.requests} failures={self.failures} "
            f"skipped_budget={self.skipped_budget} "
            f"input_tokens={self.input_tokens:,} (cached {self.cached_tokens:,}) "
            f"cached={self.cached_tokens} "
            f"output_tokens={self.output_tokens:,} (thinking {self.thoughts_tokens:,}) "
            f"thinking_share={self.thinking_share:.2f} "
            f"tool_intermediate={self.tool_use_prompt_tokens} "
            f"est_cost=${self.usd:.4f}{ceil_part} "
            f"code_exec_runs={self.code_exec_runs} ok={self.code_exec_ok} "
            f"fallbacks={self.fallbacks}"
        )


def preview_tokens(
    client: Any,
    items: Sequence[str | bytes | np.ndarray],
    model: str = DEFAULT_MODEL,
    media_resolution: str | Any | None = None,
) -> int:
    """Measure exact input tokens for `items` via `client.models.count_tokens`."""
    from google.genai import types

    parts = build_parts(items)
    contents = [types.Content(role="user", parts=parts)]
    cfg = None
    mr = _normalize_media_resolution(media_resolution)
    if mr is not None and hasattr(types, "CountTokensConfig"):
        try:
            cfg = types.CountTokensConfig(
                generation_config=types.GenerateContentConfig(media_resolution=mr)
            )
        except Exception:  # noqa: BLE001
            cfg = None
    kw: dict[str, Any] = {"model": model, "contents": contents}
    if cfg is not None:
        kw["config"] = cfg
    raw_client = getattr(client, "client", getattr(client, "_client", client))
    resp = raw_client.models.count_tokens(**kw)
    return int(getattr(resp, "total_tokens", 0) or 0)


def estimate_cost(
    n_calls: int,
    input_tokens_per_call: int = 1800,
    output_tokens_per_call: int = 800,
    prices: dict[str, float] | None = None,
    *,
    preview: int | dict[str, int] | None = None,
) -> float:
    """Pre-run USD estimate (pass `preview=preview_tokens(...)` to ground input tokens)."""
    p = prices or DEFAULT_PRICES
    inp = input_tokens_per_call
    out = output_tokens_per_call
    if isinstance(preview, int):
        inp = preview
    elif isinstance(preview, dict):
        inp = int(preview.get("input_tokens", inp))
        out = int(preview.get("output_tokens", out))
    return n_calls * (inp / 1e6 * p["input_per_m"] + out / 1e6 * p["output_per_m"])


# --------------------------------------------------------------------------- backends


class CodeExecSchemaMode(str, enum.Enum):
    """How structured output (`response_schema`) combines with `ToolCodeExecution` on Vertex AI."""

    SCHEMA_NATIVE = "schema_native"
    SCHEMA_IN_PROMPT = "schema_in_prompt"
    # Pinned from live Vertex AI probe (docs/vertex_capabilities_2026-10-01.json,
    # data/decisions/2026-10_vertex_code_exec.md); guarded by
    # tests/test_gemini_live.py::test_pinned_code_exec_schema_mode_still_works.
    DEFAULT = "schema_native"


def _normalize_thinking_level(level: str | Any | None) -> Any | None:
    if level is None:
        return None
    from google.genai import types

    if isinstance(level, types.ThinkingLevel):
        return level
    key = str(level).strip().upper().removeprefix("THINKING_LEVEL_")
    return getattr(types.ThinkingLevel, key)


def _normalize_media_resolution(res: str | Any | None) -> Any | None:
    if res is None:
        return None
    from google.genai import types

    if isinstance(res, types.MediaResolution):
        return res
    key = str(res).strip().upper()
    if not key.startswith("MEDIA_RESOLUTION_"):
        key = f"MEDIA_RESOLUTION_{key}"
    return getattr(types.MediaResolution, key)


@dataclasses.dataclass
class RawReply:
    text: str
    usage: Any = None
    code_outputs: list[str] = dataclasses.field(default_factory=list)
    exec_trace: CodeExecTrace | None = None


class ModelBackend(Protocol):
    async def generate(
        self, parts: list[Any], schema: type[BaseModel] | None, code_execution: bool
    ) -> RawReply: ...


def _extract_reply_parts(resp: Any) -> tuple[list[str], list[str], CodeExecTrace]:
    texts: list[str] = []
    code_out: list[str] = []
    steps: list[CodeExecStep] = []
    current: CodeExecStep | None = None
    for cand in getattr(resp, "candidates", None) or []:
        content = getattr(cand, "content", None)
        for p in (getattr(content, "parts", None) if content else None) or []:
            if getattr(p, "text", None):
                texts.append(p.text)
            ec = getattr(p, "executable_code", None)
            if ec is not None:
                if current is not None:
                    steps.append(current)
                current = CodeExecStep(
                    code=str(getattr(ec, "code", "") or ""),
                    language=str(getattr(ec, "language", "PYTHON") or "PYTHON"),
                )
            cer = getattr(p, "code_execution_result", None)
            if cer is not None:
                out_str = str(getattr(cer, "output", "") or "")
                outcome_str = str(getattr(cer, "outcome", "") or "")
                code_out.append(out_str)
                if current is None:
                    current = CodeExecStep(code="", language="PYTHON")
                current.outcome = outcome_str
                current.stdout = f"{current.stdout}\n{out_str}" if current.stdout else out_str
                steps.append(current)
                current = None
            inline = getattr(p, "inline_data", None)
            if inline is not None and getattr(inline, "data", None):
                mime = str(getattr(inline, "mime_type", "") or "").lower()
                if mime.startswith("image/"):
                    img_bytes = bytes(inline.data)
                    if current is not None:
                        current.inline_images.append(img_bytes)
                    elif steps:
                        steps[-1].inline_images.append(img_bytes)
                    else:
                        steps.append(
                            CodeExecStep(
                                code="",
                                language="PYTHON",
                                outcome="OUTCOME_OK",
                                inline_images=[img_bytes],
                            )
                        )
    if current is not None:
        steps.append(current)
    return texts, code_out, CodeExecTrace(steps=steps)


class VertexGeminiBackend:
    """google-genai on Vertex AI (async client), user credentials, inline parts only."""

    def __init__(
        self,
        client: Any,
        model: str = DEFAULT_MODEL,
        temperature: float | None = None,
        location: str | None = None,
        thinking_level: str | Any | None = None,
        media_resolution: str | Any | None = None,
        code_exec_schema_mode: CodeExecSchemaMode = CodeExecSchemaMode.DEFAULT,
        fallback_model: str | None = None,
        log: Callable[[str], None] | None = print,
    ):
        """`temperature=None` keeps the model default (Google recommends the default 1.0 for
        Gemini 3.x; low values can cause looping or degraded reasoning). `fallback_model=None`
        disables silent model fallback by default; when explicitly set, a fallback on retry is
        logged and counted in `self.fallbacks`."""
        self.client = client
        self.model = model
        self.temperature = temperature
        self.thinking_level = thinking_level
        self.media_resolution = media_resolution
        self.code_exec_schema_mode = code_exec_schema_mode
        self.fallback_model = fallback_model
        self.fallbacks = 0
        self.log = log
        self.location = (
            location
            or getattr(getattr(client, "_api_client", None), "location", None)
            or DEFAULT_LOCATION
        )

    async def generate(
        self,
        parts,
        schema,
        code_execution=False,
        validator=None,
        seed: int | None = None,
        timeout_s: float = 90.0,
        thinking_level: str | Any | None = None,
        media_resolution: str | Any | None = None,
        mode: CodeExecSchemaMode | None = None,
    ) -> RawReply:
        from google.genai import types

        cfg, extra = _build_config(
            schema,
            code_execution,
            validator,
            self.temperature,
            seed=seed,
            thinking_level=thinking_level if thinking_level is not None else self.thinking_level,
            media_resolution=(
                media_resolution if media_resolution is not None else self.media_resolution
            ),
            mode=mode if mode is not None else self.code_exec_schema_mode,
        )
        if extra is not None:
            parts = parts + [types.Part.from_text(text=extra)]
        contents = [types.Content(role="user", parts=parts)]
        gen_cfg = types.GenerateContentConfig(**cfg)
        last_err: Exception | None = None
        for attempt in range(3):
            use_model = self.model
            if attempt >= 1 and self.fallback_model:
                use_model = self.fallback_model
                self.fallbacks += 1
                if self.log:
                    self.log(f"[gemini] fallback {self.model} -> {self.fallback_model}")
            try:
                resp = await asyncio.wait_for(
                    self.client.aio.models.generate_content(
                        model=use_model,
                        contents=contents,
                        config=gen_cfg,
                    ),
                    timeout=timeout_s,
                )
                break
            except TimeoutError as err:
                last_err = err
                if attempt < 2:
                    await asyncio.sleep(1.5 * (attempt + 1))
        else:
            assert last_err is not None
            raise last_err
        texts, code_out, trace = _extract_reply_parts(resp)
        return RawReply("\n".join(texts), resp.usage_metadata, code_out, exec_trace=trace)


def _build_config(
    schema: type[BaseModel] | None,
    code_execution: bool,
    validator: Callable[[Any], None] | None,
    temperature: float | None = None,
    seed: int | None = None,
    thinking_level: str | Any | None = None,
    media_resolution: str | Any | None = None,
    mode: CodeExecSchemaMode = CodeExecSchemaMode.DEFAULT,
) -> tuple[dict[str, Any], str | None]:
    """GenerateContentConfig kwargs and an optional extra prompt (pure, no network).

    Without the code tool the schema is enforced by the API (`response_schema`, JSON mode).
    With `code_execution=True`, a code-side `validator` is always mandatory; `mode` selects
    `SCHEMA_NATIVE` (`response_schema` + `ToolCodeExecution`, pinned from live Vertex probe)
    or `SCHEMA_IN_PROMPT` (schema JSON embedded in prompt text). Automatic function calling
    (AFC) is always disabled because we never pass Python callable tools."""
    from google.genai import types

    cfg: dict[str, Any] = {
        "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True),
    }
    if temperature is not None:
        cfg["temperature"] = temperature
    if seed is not None:
        cfg["seed"] = int(seed)
    tl = _normalize_thinking_level(thinking_level)
    if tl is not None:
        cfg["thinking_config"] = types.ThinkingConfig(thinking_level=tl)
    mr = _normalize_media_resolution(media_resolution)
    if mr is not None:
        cfg["media_resolution"] = mr
    if schema is None:
        if code_execution:
            cfg["tools"] = [types.Tool(code_execution=types.ToolCodeExecution())]
        return cfg, None
    if not code_execution:
        cfg["response_mime_type"] = "application/json"
        cfg["response_schema"] = schema
        return cfg, None
    if validator is None:
        raise ValueError(
            "code_execution with a schema requires a validator that "
            "re-checks the parsed reply in code"
        )

    cfg["tools"] = [types.Tool(code_execution=types.ToolCodeExecution())]
    resolved_mode = CodeExecSchemaMode(mode)
    if resolved_mode == CodeExecSchemaMode.SCHEMA_NATIVE:
        cfg["response_mime_type"] = "application/json"
        cfg["response_schema"] = schema
        return cfg, None
    extra = (
        "You may use Python code execution to inspect the image. End your reply with ONLY a "
        "single JSON object matching this JSON schema:\n" + json.dumps(schema.model_json_schema())
    )
    return cfg, extra


def make_vertex_client(project: str, location: str = DEFAULT_LOCATION, credentials: Any = None):
    """genai.Client for Vertex with user credentials and HTTP retries (429/5xx)."""
    from google import genai
    from google.genai import types

    http = types.HttpOptions(
        retry_options=types.HttpRetryOptions(attempts=4, initial_delay=1.0, max_delay=20.0),
        **auth.genai_http_options_kwargs(),
    )
    return genai.Client(
        vertexai=True,
        project=project,
        location=location,
        credentials=credentials,
        http_options=http,
    )


# --------------------------------------------------------------------------- runner


def _json_objects(text: str) -> list[Any]:
    """Every JSON object that decodes starting at some '{' (non-overlapping, in order)."""
    dec, out, i = json.JSONDecoder(), [], 0
    while (i := text.find("{", i)) != -1:
        try:
            obj, end = dec.raw_decode(text, i)
        except ValueError:
            i += 1
            continue
        out.append(obj)
        i = end
    return out


def parse_reply(text: str, schema: type[BaseModel]) -> BaseModel:
    """Validate the model's final text against `schema`; tolerates ```json fences / prose.

    With prose the LAST object that validates wins, since the final answer comes last. Pass
    only `RawReply.text`: code-tool stdout (`RawReply.code_outputs`) is not an answer."""
    try:
        return schema.model_validate_json(text)
    except ValidationError as err:
        first_err: Exception = err
    for obj in reversed(_json_objects(text or "")):
        try:
            return schema.model_validate(obj)
        except ValidationError as err:
            first_err = err
    raise first_err


class GeminiRunner:
    """Bounded, schema-validated, cost-tracked Gemini calls."""

    def __init__(
        self,
        backend: ModelBackend,
        max_calls: int | None = DEFAULT_MAX_CALLS,
        concurrency: int = DEFAULT_CONCURRENCY,
        cost: CostTracker | None = None,
        log=print,
        max_usd: float | None = None,
        calls_log_path: str | Path | None = None,
    ):
        self.backend = backend
        self.max_calls = max_calls
        self.max_usd = max_usd
        self.cost = cost or CostTracker(
            prices=prices_for(
                getattr(backend, "model", None) or DEFAULT_MODEL,
                location=getattr(backend, "location", None) or DEFAULT_LOCATION,
            )
        )
        self._effective_concurrency = max(1, int(concurrency))
        self._sem = asyncio.Semaphore(self._effective_concurrency)
        self._consecutive_429s = 0
        self._reserved = 0
        self.log = log
        self.in_flight = 0
        self.max_in_flight = 0
        self.last_trace: CodeExecTrace | None = None
        self.calls_log_path = Path(calls_log_path).expanduser() if calls_log_path else None

    @property
    def effective_concurrency(self) -> int:
        return self._effective_concurrency

    @property
    def calls_remaining(self) -> int | None:
        return None if self.max_calls is None else max(0, self.max_calls - self._reserved)

    @property
    def usd_remaining(self) -> float | None:
        return None if self.max_usd is None else max(0.0, self.max_usd - self.cost.usd)

    def _check_usd_budget(self) -> None:
        if self.max_usd is not None and self.cost.usd >= self.max_usd:
            raise BudgetExceeded(
                f"max_usd=${self.max_usd:.4f} reached (spent ${self.cost.usd:.4f})"
            )

    def _reserve(self) -> None:
        if self.max_calls is not None and self._reserved >= self.max_calls:
            raise BudgetExceeded(f"MAX_GEMINI_CALLS={self.max_calls} reached")
        self._check_usd_budget()
        self._reserved += 1

    def _record_429_or_reset(self, err: Exception | None) -> None:
        if err is not None and ("429" in str(err) or "RESOURCE_EXHAUSTED" in str(err).upper()):
            self._consecutive_429s += 1
            if self._consecutive_429s >= 2 and self._effective_concurrency > 1:
                new_c = max(1, self._effective_concurrency // 2)
                self._effective_concurrency = new_c
                self._sem = asyncio.Semaphore(new_c)
                self._consecutive_429s = 0
                if self.log:
                    self.log(f"[gemini] 429 rate-limit backoff: concurrency halved to {new_c}")
        elif err is None:
            self._consecutive_429s = 0

    def _append_call_log(
        self,
        parts: list[Any],
        schema: type[BaseModel] | None,
        code_execution: bool,
        latency_s: float,
        usage: Any,
    ) -> None:
        if self.calls_log_path is None:
            return
        try:
            self.calls_log_path.parent.mkdir(parents=True, exist_ok=True)
            h = hashlib.sha256()
            for p in parts:
                txt = getattr(p, "text", None)
                if txt:
                    h.update(txt.encode("utf-8", errors="ignore"))
                inline = getattr(p, "inline_data", None)
                if inline is not None and getattr(inline, "data", None):
                    h.update(bytes(inline.data))
            get = usage.get if isinstance(usage, dict) else (lambda k, d=None: getattr(usage, k, d))
            rec = {
                "parts_sha256": h.hexdigest()[:16],
                "schema": getattr(schema, "__name__", None),
                "code_execution": bool(code_execution),
                "latency_s": round(latency_s, 3),
                "prompt_tokens": int((get("prompt_token_count") if usage else 0) or 0),
                "tool_use_tokens": int((get("tool_use_prompt_token_count") if usage else 0) or 0),
                "candidates_tokens": int((get("candidates_token_count") if usage else 0) or 0),
                "thoughts_tokens": int((get("thoughts_token_count") if usage else 0) or 0),
            }
            with self.calls_log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
        except Exception:  # noqa: BLE001
            pass

    async def _call(
        self,
        parts,
        schema,
        code_execution,
        validator=None,
        seed: int | None = None,
        thinking_level: str | Any | None = None,
        media_resolution: str | Any | None = None,
    ) -> RawReply:
        self._reserve()
        t0 = time.monotonic()
        async with self._sem:
            try:
                self._check_usd_budget()
            except BudgetExceeded:
                self._reserved -= 1
                raise
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
            try:
                kw: dict[str, Any] = {}
                if code_execution:
                    kw["validator"] = validator
                if seed is not None:
                    kw["seed"] = seed
                if thinking_level is not None:
                    kw["thinking_level"] = thinking_level
                if media_resolution is not None:
                    kw["media_resolution"] = media_resolution
                try:
                    reply = await self.backend.generate(parts, schema, bool(code_execution), **kw)
                except Exception as err:
                    self._record_429_or_reset(err)
                    raise
                self._record_429_or_reset(None)
            finally:
                self.in_flight -= 1
        latency_s = time.monotonic() - t0
        self.cost.add(reply.usage)
        if code_execution:
            self.cost.code_exec_runs += 1
        fb = getattr(self.backend, "fallbacks", 0)
        if fb:
            self.cost.fallbacks = int(fb)
        self._append_call_log(parts, schema, code_execution, latency_s, reply.usage)
        return reply

    async def ask(
        self,
        items: Sequence[str | bytes | np.ndarray],
        schema: type[BaseModel],
        code_execution: bool = False,
        reask: bool = True,
        validator: Callable[[Any], None] | None = None,
        seed: int | None = None,
        thinking_level: str | Any | None = None,
        media_resolution: str | Any | None = None,
        expect_stdout: str | re.Pattern[str] | None = None,
        return_trace: bool = False,
    ) -> Any:
        """One request (+ at most one re-ask if the reply fails schema, trace, or `validator` checks).

        `validator(parsed)` raises ValueError to reject a reply (e.g. degenerate geometry).
        When `code_execution=True` and the backend returns an `exec_trace` (or `expect_stdout`
        is given), `check_code_exec_trace` verifies that PYTHON code executed and finished with
        `OUTCOME_OK`. If `return_trace=True`, returns `(parsed, trace)`."""
        _build_config(
            schema,
            code_execution,
            validator,
            seed=seed,
            thinking_level=thinking_level,
            media_resolution=media_resolution,
        )  # refuse unvalidated code-tool use
        self.cost.requests += 1
        parts = build_parts(items)
        sent_shape = _first_image_shape(items) if code_execution else None

        def accept(reply: RawReply) -> tuple[BaseModel, CodeExecTrace | None]:
            trace = reply.exec_trace
            if code_execution and (trace is not None or expect_stdout is not None):
                check_code_exec_trace(
                    trace, expect_stdout=expect_stdout, sent_image_shape=sent_shape
                )
            parsed = parse_reply(reply.text, schema)
            if validator is not None:
                validator(parsed)
            if code_execution:
                self.cost.code_exec_ok += 1
            self.last_trace = trace
            return parsed, trace

        reply = await self._call(
            parts,
            schema,
            code_execution,
            validator,
            seed=seed,
            thinking_level=thinking_level,
            media_resolution=media_resolution,
        )
        try:
            parsed, trace = accept(reply)
            return (parsed, trace) if return_trace else parsed
        except (ValidationError, ValueError) as err:
            if not reask:
                self.cost.record_failure(f"schema validation failed: {str(err)[:300]}")
                return (None, reply.exec_trace) if return_trace else None
            last_out = (reply.exec_trace.last_outcome if reply.exec_trace else "").upper()
            if code_execution and (
                "DEADLINE" in last_out
                or "FAILED" in last_out
                or isinstance(err, CodeExecValidationError)
            ):
                hint = (
                    f"Your previous Python code execution or reply failed ({str(err)[:300]}). "
                    "Simplify the Python code; stay under 30 s, print the required measurement, "
                    "and reply with valid JSON for this schema:\n"
                    f"{json.dumps(schema.model_json_schema())[:4000]}"
                )
            else:
                hint = (
                    f"Your previous reply did not match the required JSON schema ({str(err)[:300]}). "
                    f"Reply again with only valid JSON for this schema:\n"
                    f"{json.dumps(schema.model_json_schema())[:4000]}"
                )
            fix = build_parts([hint])
            reply2 = await self._call(
                parts + fix,
                schema,
                code_execution,
                validator,
                seed=seed,
                thinking_level=thinking_level,
                media_resolution=media_resolution,
            )
            try:
                parsed2, trace2 = accept(reply2)
                return (parsed2, trace2) if return_trace else parsed2
            except (ValidationError, ValueError) as err2:
                self.cost.record_failure(
                    f"schema validation failed after re-ask: {str(err2)[:300]}"
                )
                self.last_trace = reply2.exec_trace
                return (None, reply2.exec_trace) if return_trace else None

    async def ask_many(
        self,
        requests: Sequence[tuple[Sequence[Any], type[BaseModel]]],
        raise_if_all_failed: bool = True,
        **kw,
    ):
        """Concurrent `ask` calls.

        * Requests beyond the budget are not sent; they return None and are counted in
          `cost.skipped_budget` (not as failures).
        * A request that errors (400, safety block, exhausted retries) or whose reply fails
          validation returns None and is counted in `cost.failures`, without discarding the
          rest of the batch's paid results.
        * If no request succeeded and at least one failed, `AllRequestsFailed` is raised
          (unless `raise_if_all_failed=False`): a 401 must stop the notebook, not produce an
          empty map.
        """
        errors: list[str] = []
        skipped = 0

        async def one(items, schema):
            nonlocal skipped
            try:
                return await self.ask(items, schema, **kw)
            except BudgetExceeded:
                skipped += 1
                self.cost.skipped_budget += 1
                return None
            except Exception as err:  # noqa: BLE001 - keep the batch's already-paid results
                msg = f"{type(err).__name__}: {err}"
                errors.append(msg)
                self.cost.record_failure(msg)
                if self.log:
                    self.log(f"[gemini] request failed, result dropped: {msg}")
                return None

        out = await asyncio.gather(*(one(i, s) for i, s in requests))
        n_ok = sum(r is not None for r in out)
        n_failed = len(out) - n_ok - skipped
        if raise_if_all_failed and n_ok == 0 and n_failed > 0:
            first = errors[0] if errors else "every reply failed schema validation"
            raise AllRequestsFailed(
                f"all {n_failed} Gemini requests failed; first error: {first}. "
                "Check credentials (see the auth cell), PROJECT_ID, MODEL and region."
            )
        return out

    def check(self, max_failure_rate: float = 0.0, *, context: str = "") -> None:
        """Raise `GeminiFailures` if the failed share of requests exceeds `max_failure_rate`."""
        c = self.cost
        if c.failures == 0:
            return
        rate = c.failures / max(1, c.requests)
        if rate > max_failure_rate:
            prefix = f"[{context}] " if context else ""
            raise GeminiFailures(
                f"{prefix}{c.failures} of {c.requests} Gemini requests failed "
                f"(rate {rate:.1%} > allowed {max_failure_rate:.1%}); first messages: "
                + " | ".join(c.failure_messages)
            )


def draw_boxes(image: np.ndarray, boxes: Sequence[Sequence[float]], labels=None) -> np.ndarray:
    """Overlay pixel boxes (x0, y0, x1, y1) in code for inspection."""
    out = image.copy()
    for i, b in enumerate(boxes):
        x0, y0, x1, y1 = (int(round(v)) for v in b)
        cv2.rectangle(out, (x0, y0), (x1, y1), (0, 255, 255), 2)
        if labels:
            cv2.putText(
                out,
                str(labels[i]),
                (x0, max(12, y0 - 4)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 255, 255),
                1,
            )
    return out
