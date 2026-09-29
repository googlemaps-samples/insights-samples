"""Gemini access: inline image bytes only, schema-validated replies, budget + cost accounting.

Hard rules (tested in tests/test_no_uri_parts.py and here):
* Images are downloaded with the user's own credentials and sent inline as bytes
  (`Part.from_bytes`). No URI parts, no file uploads, no batch prediction.
* Every request declares a pydantic `response_schema`; replies are validated in code with one
  re-ask on a schema failure. With the code-execution tool (agentic vision, where the model
  may crop/zoom with Python) the schema is enforced on the final JSON text instead, and any
  geometry it returns must be re-checked by the caller in code.
* `MAX_GEMINI_CALLS` (default 500, `None` = unlimited) and a concurrency semaphore (default
  16) bound each run; `CostTracker` sums `usage_metadata` (thinking tokens billed as output).
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import re
from collections.abc import Sequence
from typing import Any, Protocol

import cv2
import numpy as np
from pydantic import BaseModel, ValidationError

from svi_geo import auth, images

DEFAULT_MODEL = "gemini-3.5-flash"
DEFAULT_LOCATION = "global"
DEFAULT_MAX_CALLS = 500
DEFAULT_CONCURRENCY = 16
MAX_IMAGE_SIDE = 1536
# USD per 1M tokens. ESTIMATES ONLY - check current Vertex AI pricing for your model/region and
# pass your own `prices=` to CostTracker.
DEFAULT_PRICES = {"input_per_m": 0.30, "output_per_m": 2.50}

_URI_RE = re.compile(r"^\s*(gs|https?)://", re.I)


class BudgetExceeded(RuntimeError):
    """The run hit MAX_GEMINI_CALLS; no further requests are sent."""


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
    failures: int = 0

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
            f"Gemini calls={self.calls} (failures={self.failures}) input_tokens={self.input_tokens:,} "
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

    def __init__(self, client: Any, model: str = DEFAULT_MODEL, temperature: float | None = None):
        """`temperature=None` keeps the model default (Google recommends the default 1.0 for
        Gemini 3.x; low values can cause looping or degraded reasoning)."""
        self.client = client
        self.model = model
        self.temperature = temperature

    async def generate(self, parts, schema, code_execution=False) -> RawReply:
        from google.genai import types

        cfg: dict[str, Any] = {}
        if self.temperature is not None:
            cfg["temperature"] = self.temperature
        if code_execution:
            cfg["tools"] = [types.Tool(code_execution=types.ToolCodeExecution())]
        if schema is not None:
            if not code_execution:
                cfg["response_mime_type"] = "application/json"
                cfg["response_schema"] = schema
            else:
                parts = parts + [
                    types.Part.from_text(
                        text="Use Python code execution (cv2, numpy, PIL) to inspect, crop/zoom small regions, "
                        "and verify visual details on the image. At the end of your code or response, output ONLY a single JSON object matching this exact JSON schema:\n"
                        + json.dumps(schema.model_json_schema())
                    )
                ]
        resp = await self.client.aio.models.generate_content(
            model=self.model,
            contents=[types.Content(role="user", parts=parts)],
            config=types.GenerateContentConfig(**cfg),
        )
        texts, code_out = [], []
        for cand in resp.candidates or []:
            for p in (cand.content.parts if cand.content else None) or []:
                if getattr(p, "text", None):
                    texts.append(p.text)
                if getattr(p, "code_execution_result", None) is not None:
                    code_out.append(p.code_execution_result.output or "")
        return RawReply("\n".join(texts), resp.usage_metadata, code_out)


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
    """Validate a reply against `schema`; tolerates ```json fences / prose around the object.

    With prose (e.g. code-execution transcripts) the LAST object that validates wins, since
    the final answer comes last."""
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
    ):
        self.backend = backend
        self.max_calls = max_calls
        self.cost = cost or CostTracker()
        self._sem = asyncio.Semaphore(concurrency)
        self._reserved = 0
        self.log = log
        self.in_flight = 0
        self.max_in_flight = 0

    @property
    def calls_remaining(self) -> int | None:
        return None if self.max_calls is None else max(0, self.max_calls - self._reserved)

    def _reserve(self) -> None:
        if self.max_calls is not None and self._reserved >= self.max_calls:
            raise BudgetExceeded(f"MAX_GEMINI_CALLS={self.max_calls} reached")
        self._reserved += 1

    async def _call(self, parts, schema, code_execution) -> RawReply:
        self._reserve()
        async with self._sem:
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
            try:
                reply = await self.backend.generate(parts, schema, code_execution)
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
    ) -> BaseModel | None:
        """One request (+ at most one re-ask if the reply fails schema validation)."""
        parts = build_parts(items)
        reply = await self._call(parts, schema, code_execution)
        try:
            return parse_reply("\n".join(reply.code_outputs + [reply.text]), schema)
        except (ValidationError, ValueError) as err:
            if not reask:
                self.cost.failures += 1
                return None
            fix = build_parts(
                [
                    f"Your previous reply did not match the required JSON schema ({str(err)[:300]}). "
                    f"Reply again with only valid JSON for this schema:\n"
                    f"{json.dumps(schema.model_json_schema())[:4000]}"
                ]
            )
            reply2 = await self._call(parts + fix, schema, code_execution)
            try:
                return parse_reply("\n".join(reply2.code_outputs + [reply2.text]), schema)
            except (ValidationError, ValueError):
                self.cost.failures += 1
                return None

    async def ask_many(self, requests: Sequence[tuple[Sequence[Any], type[BaseModel]]], **kw):
        """Concurrent `ask` calls; requests beyond the budget return None (not sent), and a
        request that errors (400, safety block, exhausted retries) returns None without
        discarding the rest of the batch (QA F9)."""

        async def one(items, schema):
            try:
                return await self.ask(items, schema, **kw)
            except BudgetExceeded:
                return None
            except Exception as err:  # noqa: BLE001 - keep the batch's already-paid results
                self.cost.failures += 1
                self.log(f"[gemini] request failed, result dropped: {type(err).__name__}: {err}")
                return None

        return await asyncio.gather(*(one(i, s) for i, s in requests))


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
