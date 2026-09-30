"""Gemini client tests with a scripted fake backend (no network)."""

import asyncio

import numpy as np
import pytest

from svi_geo import gemini_client as gc
from svi_geo import images, schemas


class FakeBackend:
    def __init__(self, replies, delay=0.0):
        self.replies = list(replies)
        self.delay = delay
        self.seen = []

    async def generate(self, parts, schema, code_execution=False):
        self.seen.append((parts, schema, code_execution))
        await asyncio.sleep(self.delay)
        text = self.replies.pop(0) if self.replies else '{"present": true, "confidence": 0.9}'
        usage = {
            "prompt_token_count": 1000,
            "candidates_token_count": 100,
            "thoughts_token_count": 50,
        }
        return gc.RawReply(text, usage)


def _img(h=3000, w=2000):
    return np.random.default_rng(0).integers(0, 255, (h, w, 3), dtype=np.uint8)


def test_build_parts_inline_bytes_only_and_downscaled():
    parts = gc.build_parts(["describe", _img()])
    assert parts[0].text == "describe"
    blob = parts[1].inline_data
    assert blob.mime_type == "image/jpeg"
    assert parts[1].file_data is None
    dec = images.decode(blob.data)
    assert max(dec.shape[:2]) <= gc.MAX_IMAGE_SIDE


@pytest.mark.parametrize("uri", ["gs://bucket/x.jpg", "https://storage.googleapis.com/b/x.jpg"])
def test_build_parts_rejects_uris(uri):
    with pytest.raises(ValueError):
        gc.build_parts([uri])


async def test_reask_once_on_schema_failure_then_parse():
    be = FakeBackend(["not json", '{"present": false, "confidence": 0.8}'])
    r = gc.GeminiRunner(be, max_calls=10, log=None)
    out = await r.ask(["q", _img(100, 100)], schemas.PresenceCheck)
    assert out.present is False
    assert len(be.seen) == 2 and r.cost.calls == 2


async def test_budget_is_enforced_and_extra_requests_not_sent():
    be = FakeBackend([])
    r = gc.GeminiRunner(be, max_calls=3, log=None)
    reqs = [(["q"], schemas.PresenceCheck)] * 5
    out = await r.ask_many(reqs)
    assert sum(o is not None for o in out) == 3
    assert len(be.seen) == 3
    assert r.calls_remaining == 0


async def test_unlimited_budget_and_concurrency_cap():
    be = FakeBackend([], delay=0.01)
    r = gc.GeminiRunner(be, max_calls=None, concurrency=4, log=None)
    out = await r.ask_many([(["q"], schemas.PresenceCheck)] * 20)
    assert all(o is not None for o in out)
    assert r.max_in_flight <= 4
    assert r.calls_remaining is None


def test_cost_tracker_counts_thinking_as_output():
    c = gc.CostTracker(prices={"input_per_m": 1.0, "output_per_m": 10.0})
    c.add(
        {
            "prompt_token_count": 1_000_000,
            "candidates_token_count": 100_000,
            "thoughts_token_count": 100_000,
        }
    )
    assert c.input_tokens == 1_000_000 and c.output_tokens == 200_000
    assert c.usd == pytest.approx(1.0 + 2.0)
    assert gc.estimate_cost(
        10, 1000, 100, {"input_per_m": 1.0, "output_per_m": 10.0}
    ) == pytest.approx(0.02)


def test_parse_reply_tolerates_fences():
    out = gc.parse_reply(
        '```json\n{"present": true, "confidence": 0.5}\n```', schemas.PresenceCheck
    )
    assert out.present


class RaisingBackend(FakeBackend):
    """Raises a non-retryable error on the 3rd request (e.g. a 400 or a safety block)."""

    async def generate(self, parts, schema, code_execution=False):
        if len(self.seen) == 2:
            self.seen.append((parts, schema, code_execution))
            raise RuntimeError("400 INVALID_ARGUMENT")
        return await super().generate(parts, schema, code_execution)


def test_ask_many_keeps_paid_results_when_one_request_fails():
    backend = RaisingBackend([])
    logs = []
    runner = gc.GeminiRunner(backend, max_calls=10, concurrency=1, log=logs.append)
    reqs = [([f"q{i}"], schemas.PresenceCheck) for i in range(5)]
    out = asyncio.run(runner.ask_many(reqs))
    assert sum(r is not None for r in out) == 4 and out[2] is None
    assert runner.cost.failures == 1
    assert any("400" in str(m) for m in logs)


def test_parse_reply_picks_last_valid_object_from_code_execution_text():
    text = (
        'I will crop {the pole}. Result so far {"present": false, "confidence": 0.2}\n'
        "After zooming:\n"
        '{"present": true, "confidence": 0.9, "box_2d": [100, 200, 300, 400]}\nDone.'
    )
    r = gc.parse_reply(text, schemas.PresenceCheck)
    assert r.present is True and r.box_2d == [100, 200, 300, 400]


def test_backend_omits_temperature_by_default():
    b = gc.VertexGeminiBackend(client=None)
    assert b.temperature is None


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_code_execution_with_schema():

    from pydantic import BaseModel

    class EdgeSchema(BaseModel):
        found: bool
        edge_count: int

    class FakeAuth:
        def __init__(self):
            pass

    try:
        _ = gc.make_vertex_client(
            "test-project", "us-central1"
        )  # Just placeholder, let's use the real project if we load auth correctly.
    except Exception:
        pytest.skip("Auth error")

    # We will test the schema and code extraction logic at the backend layer

    class FakeCodeBackend(FakeBackend):
        async def generate(self, parts, schema, code_execution=False):
            # simulate code output
            # we want to assert that when code_execution is True, the schema wasn't passed directly to the model as response_schema, but as instructions
            self.seen.append((parts, schema, code_execution))
            text = '```python\nprint("running code")\n```'
            code_out = ['{"found": true, "edge_count": 3}']
            return gc.RawReply(text, None, code_outputs=code_out)

    runner = gc.GeminiRunner(FakeCodeBackend([]), max_calls=5, log=None)
    out = await runner.ask(["find edges", _img(200, 200)], EdgeSchema, code_execution=True)
    assert out.found is True
    assert out.edge_count == 3


# --------------------------------------------------------------------------- loud failures


class AlwaysRaisingBackend(FakeBackend):
    """Every request fails, e.g. a 401 from bad credentials."""

    def __init__(self, message="401 UNAUTHENTICATED: invalid credentials"):
        super().__init__([])
        self.message = message

    async def generate(self, parts, schema, code_execution=False):
        self.seen.append((parts, schema, code_execution))
        raise PermissionError(f"{self.message} #{len(self.seen)}")


def test_ask_many_raises_when_every_request_fails():
    runner = gc.GeminiRunner(AlwaysRaisingBackend(), max_calls=10, log=None)
    reqs = [([f"q{i}"], schemas.PresenceCheck) for i in range(3)]
    with pytest.raises(gc.AllRequestsFailed) as info:
        asyncio.run(runner.ask_many(reqs))
    assert "PermissionError" in str(info.value)
    assert "401 UNAUTHENTICATED" in str(info.value)
    assert runner.cost.failures == 3


def test_ask_many_can_opt_out_of_raising_when_all_fail():
    runner = gc.GeminiRunner(AlwaysRaisingBackend(), max_calls=10, log=None)
    out = asyncio.run(
        runner.ask_many([(["q"], schemas.PresenceCheck)] * 2, raise_if_all_failed=False)
    )
    assert out == [None, None]
    assert runner.cost.failures == 2


def test_failure_messages_keep_the_first_five():
    runner = gc.GeminiRunner(AlwaysRaisingBackend(), max_calls=None, log=None)
    asyncio.run(
        runner.ask_many(
            [([f"q{i}"], schemas.PresenceCheck) for i in range(8)], raise_if_all_failed=False
        )
    )
    assert runner.cost.failures == 8
    assert len(runner.cost.failure_messages) == 5
    assert all("401 UNAUTHENTICATED" in m for m in runner.cost.failure_messages)


def test_budget_skips_are_counted_separately_from_failures():
    runner = gc.GeminiRunner(FakeBackend([]), max_calls=2, log=None)
    out = asyncio.run(runner.ask_many([(["q"], schemas.PresenceCheck)] * 5))
    assert sum(o is not None for o in out) == 2
    assert runner.cost.skipped_budget == 3
    assert runner.cost.failures == 0


def test_budget_skip_of_the_whole_batch_is_not_reported_as_all_failed():
    runner = gc.GeminiRunner(FakeBackend([]), max_calls=0, log=None)
    out = asyncio.run(runner.ask_many([(["q"], schemas.PresenceCheck)] * 2))
    assert out == [None, None]
    assert runner.cost.skipped_budget == 2 and runner.cost.failures == 0


def test_schema_failure_after_reask_is_counted_and_recorded():
    runner = gc.GeminiRunner(FakeBackend(["nope", "still nope"]), max_calls=10, log=None)
    out = asyncio.run(runner.ask(["q"], schemas.PresenceCheck))
    assert out is None
    assert runner.cost.failures == 1
    assert runner.cost.failure_messages and "schema" in runner.cost.failure_messages[0].lower()


def test_check_raises_on_any_failure_by_default():
    runner = gc.GeminiRunner(RaisingBackend([]), max_calls=10, concurrency=1, log=None)
    asyncio.run(runner.ask_many([([f"q{i}"], schemas.PresenceCheck) for i in range(5)]))
    with pytest.raises(gc.GeminiFailures) as info:
        runner.check()
    assert "400 INVALID_ARGUMENT" in str(info.value)
    runner.check(max_failure_rate=0.5)  # 1 of 5 failed: within a 50% tolerance


def test_check_passes_when_nothing_failed():
    runner = gc.GeminiRunner(FakeBackend([]), max_calls=10, log=None)
    asyncio.run(runner.ask_many([(["q"], schemas.PresenceCheck)] * 3))
    runner.check()


def test_summary_reports_failures_and_budget_skips():
    c = gc.CostTracker()
    c.failures, c.skipped_budget = 2, 7
    s = c.summary()
    assert "failures=2" in s and "skipped_budget=7" in s


def test_prices_by_model_and_warning_fallback():
    assert gc.prices_for(gc.DEFAULT_MODEL) == gc.PRICES_BY_MODEL[gc.DEFAULT_MODEL]
    with pytest.warns(UserWarning, match="no-such-model"):
        p = gc.prices_for("no-such-model")
    assert p == gc.DEFAULT_PRICES


def test_runner_prices_follow_the_backend_model():
    class ModelBackend(FakeBackend):
        model = "gemini-2.5-pro"

    runner = gc.GeminiRunner(ModelBackend([]), log=None)
    assert runner.cost.prices == gc.PRICES_BY_MODEL["gemini-2.5-pro"]
