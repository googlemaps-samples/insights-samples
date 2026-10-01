"""Gemini access: inline image bytes only, schema-validated replies, budget + cost accounting.

Hard rules (tested in tests/test_no_uri_parts.py and here):
* Images are downloaded with the user's own credentials and sent inline as bytes
  (`Part.from_bytes`). No URI parts, no file uploads, no batch prediction.
* Every request declares a pydantic `response_schema` (JSON mode, constrained decoding);
  replies are validated in code, then by an optional per-call `validator` (e.g. geometry
  range checks), with one re-ask on either failure. Only the model's final text is parsed:
  tool stdout never counts as the answer. The code-execution tool cannot be combined with
  `response_schema`, so asking for it with a schema requires a `validator`.
* `MAX_GEMINI_CALLS` (default 500, `None` = unlimited) and a concurrency semaphore (default
  16) bound each run; `CostTracker` sums `usage_metadata` (thinking tokens billed as output).
* Failures are loud: a batch in which every request fails raises `AllRequestsFailed`, every
  failure is counted with its first messages kept, and `GeminiRunner.check()` raises
  `GeminiFailures` so a notebook cell cannot silently continue on missing results.
"""

from __future__ import annotations

import asyncio
import dataclasses
import enum
import json
import re
import warnings
from collections.abc import Callable, Sequence
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
DEFAULT_CONCURRENCY = 16
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

_URI_RE = re.compile(r"^\s*(gs|https?)://", re.I)


class BudgetExceeded(RuntimeError):
    """The run hit MAX_GEMINI_CALLS or max_usd; no further requests are sent."""


class AllRequestsFailed(RuntimeError):
    """Every request of a batch failed (e.g. 401/403 credentials, wrong model or region)."""


class GeminiFailures(RuntimeError):
    """`GeminiRunner.check()` found more failed requests than the caller tolerates."""


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


# --------------------------------------------------------------------------- cost


@dataclasses.dataclass
class CostTracker:
    prices: dict[str, float] = dataclasses.field(default_factory=lambda: dict(DEFAULT_PRICES))
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0  # candidates + thoughts
    thoughts_tokens: int = 0
    requests: int = 0  # logical requests (a re-ask is a second call, not a second request)
    failures: int = 0
    skipped_budget: int = 0  # requests not sent because MAX_GEMINI_CALLS was reached
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
        prompt = (get("prompt_token_count") or 0) + (get("tool_use_prompt_token_count") or 0)
        thoughts = get("thoughts_token_count") or 0
        self.input_tokens += int(prompt)
        self.output_tokens += int((get("candidates_token_count") or 0) + thoughts)
        self.thoughts_tokens += int(thoughts)

    @property
    def usd(self) -> float:
        return (
            self.input_tokens / 1e6 * self.prices["input_per_m"]
            + self.output_tokens / 1e6 * self.prices["output_per_m"]
        )

    def summary(self) -> str:
        return (
            f"Gemini calls={self.calls} requests={self.requests} failures={self.failures} "
            f"skipped_budget={self.skipped_budget} input_tokens={self.input_tokens:,} "
            f"output_tokens={self.output_tokens:,} (thinking {self.thoughts_tokens:,}) "
            f"est_cost=${self.usd:.4f}"
        )


def estimate_cost(
    n_calls: int,
    input_tokens_per_call: int = 1800,
    output_tokens_per_call: int = 800,
    prices: dict[str, float] | None = None,
) -> float:
    """Pre-run USD estimate (an image of <=1536 px is ~1-2k input tokens)."""
    p = prices or DEFAULT_PRICES
    return n_calls * (
        input_tokens_per_call / 1e6 * p["input_per_m"]
        + output_tokens_per_call / 1e6 * p["output_per_m"]
    )


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


class ModelBackend(Protocol):
    async def generate(
        self, parts: list[Any], schema: type[BaseModel] | None, code_execution: bool
    ) -> RawReply: ...


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
    ):
        """`temperature=None` keeps the model default (Google recommends the default 1.0 for
        Gemini 3.x; low values can cause looping or degraded reasoning)."""
        self.client = client
        self.model = model
        self.temperature = temperature
        self.thinking_level = thinking_level
        self.media_resolution = media_resolution
        self.code_exec_schema_mode = code_exec_schema_mode
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
        fallback_models = [m for m in PRICES_BY_MODEL if "2.5" in m and "pro" in m]
        for attempt in range(3):
            use_model = (
                fallback_models[0]
                if (attempt >= 1 and "3.1" in self.model and fallback_models)
                else self.model
            )
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
        texts, code_out = [], []
        for cand in resp.candidates or []:
            for p in (cand.content.parts if cand.content else None) or []:
                if getattr(p, "text", None):
                    texts.append(p.text)
                if getattr(p, "code_execution_result", None) is not None:
                    code_out.append(p.code_execution_result.output or "")
        return RawReply("\n".join(texts), resp.usage_metadata, code_out)


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
        self._sem = asyncio.Semaphore(concurrency)
        self._reserved = 0
        self.log = log
        self.in_flight = 0
        self.max_in_flight = 0

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

    async def _call(
        self, parts, schema, code_execution, validator=None, seed: int | None = None
    ) -> RawReply:
        self._reserve()
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
                reply = await self.backend.generate(parts, schema, bool(code_execution), **kw)
            finally:
                self.in_flight -= 1
        self.cost.add(reply.usage)
        return reply

    async def ask(
        self,
        items: Sequence[str | bytes | np.ndarray],
        schema: type[BaseModel],
        code_execution: bool = False,
        reask: bool = True,
        validator: Callable[[Any], None] | None = None,
        seed: int | None = None,
    ) -> BaseModel | None:
        """One request (+ at most one re-ask if the reply fails schema or `validator` checks).

        `validator(parsed)` raises ValueError to reject a reply (e.g. degenerate geometry).
        A reply that still fails is counted as a failure and returns None."""
        _build_config(
            schema, code_execution, validator, seed=seed
        )  # refuse unvalidated code-tool use
        self.cost.requests += 1
        parts = build_parts(items)

        def accept(reply: RawReply) -> BaseModel:
            parsed = parse_reply(reply.text, schema)
            if validator is not None:
                validator(parsed)
            return parsed

        reply = await self._call(parts, schema, code_execution, validator, seed=seed)
        try:
            return accept(reply)
        except (ValidationError, ValueError) as err:
            if not reask:
                self.cost.record_failure(f"schema validation failed: {str(err)[:300]}")
                return None
            fix = build_parts(
                [
                    f"Your previous reply did not match the required JSON schema ({str(err)[:300]}). "
                    f"Reply again with only valid JSON for this schema:\n"
                    f"{json.dumps(schema.model_json_schema())[:4000]}"
                ]
            )
            reply2 = await self._call(parts + fix, schema, code_execution, validator, seed=seed)
            try:
                return accept(reply2)
            except (ValidationError, ValueError) as err2:
                self.cost.record_failure(
                    f"schema validation failed after re-ask: {str(err2)[:300]}"
                )
                return None

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

    def check(self, max_failure_rate: float = 0.0) -> None:
        """Raise `GeminiFailures` if the failed share of requests exceeds `max_failure_rate`."""
        c = self.cost
        if c.failures == 0:
            return
        rate = c.failures / max(1, c.requests)
        if rate > max_failure_rate:
            raise GeminiFailures(
                f"{c.failures} of {c.requests} Gemini requests failed "
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
