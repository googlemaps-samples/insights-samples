"""Live Gemini checks (needs --run-live, ADC and Vertex access): inline bytes, schemas, cost.

One frame download and 3 small Gemini calls. Every image is a code-rendered perspective view
(never a raw 3648x5472 frame) sent inline as JPEG bytes.
"""

import asyncio

import pytest

from svi_geo import auth, data, gemini_client, images, pipeline, rosette, schemas

PARIS_SNAPSHOT = "21d75cd4-5841-436a-a7c1-7722959141e1"
KNOWN_OBS = "o1:---zLYmNYEHVW4MKF1YhYA_0:5001ee"


@pytest.fixture(scope="module")
def rendered_view(svi_project, svi_bucket, tmp_path_factory):
    from google.cloud import storage

    creds = auth.get_credentials()
    bucket = svi_bucket
    fetcher = images.GcsImageFetcher(
        storage.Client(project=svi_project, credentials=creds),
        cache_dir=tmp_path_factory.mktemp("frames"),
    )
    frame = images.decode(fetcher.fetch(data.gcs_uri_for(bucket, PARIS_SNAPSHOT, KNOWN_OBS)))
    assert frame.shape[:2] == (5472, 3648)
    img, _view = rosette.undistort(frame, rosette.DEFAULT_INTRINSICS, 80.0, pipeline.VIEW_SIZE)
    return img


@pytest.fixture
def runner(svi_project):
    client = gemini_client.make_vertex_client(svi_project, credentials=auth.get_credentials())
    backend = gemini_client.VertexGeminiBackend(client)
    return gemini_client.GeminiRunner(backend, max_calls=6, concurrency=3)


@pytest.mark.live
def test_inline_bytes_detection_and_presence(rendered_view, runner):
    assert max(rendered_view.shape[:2]) <= 1536
    prompt = pipeline.detection_prompt()
    fd, pc, sm = asyncio.run(
        runner.ask_many(
            [
                ([prompt, rendered_view], schemas.FrameDetections),
                (
                    ["Is a road or street surface visible in this image?", rendered_view],
                    schemas.PresenceCheck,
                ),
                (
                    [
                        "Classify the road surface material in this street-level image.",
                        rendered_view,
                    ],
                    schemas.SurfaceMaterialResult,
                ),
            ]
        )
    )
    # schema handling: genai accepted the pydantic schemas (incl. SkipJsonSchema n_dropped)
    assert isinstance(fd, schemas.FrameDetections)
    assert fd.n_dropped >= 0
    for d in fd.detections:
        assert 0 <= d.box_2d[0] < d.box_2d[2] <= 1000
    assert isinstance(pc, schemas.PresenceCheck)
    assert isinstance(sm, schemas.SurfaceMaterialResult)
    assert runner.cost.calls >= 3
    assert runner.cost.input_tokens > 0 and runner.cost.usd > 0
    print(runner.cost.summary())


@pytest.mark.live
def test_live_call_emits_no_afc_warning(runner, caplog):
    import logging
    import warnings

    with (
        caplog.at_level(logging.INFO, logger="google_genai.models"),
        warnings.catch_warnings(record=True) as caught,
    ):
        warnings.simplefilter("always")
        ans = asyncio.run(
            runner.ask(
                [
                    "Is the number 2 even? Answer present=true if yes.",
                ],
                schemas.PresenceCheck,
                seed=7,
            )
        )
    assert isinstance(ans, schemas.PresenceCheck)
    afc_logs = [
        r.getMessage()
        for r in caplog.records
        if "afc" in r.getMessage().lower() or "automatic function calling" in r.getMessage().lower()
    ]
    afc_warns = [
        str(w.message)
        for w in caught
        if "afc" in str(w.message).lower() or "automatic function calling" in str(w.message).lower()
    ]
    assert not afc_logs, f"Unexpected AFC log messages: {afc_logs}"
    assert not afc_warns, f"Unexpected AFC warnings: {afc_warns}"


def _synthetic_three_rects() -> tuple[bytes, list[int]]:
    """640x480 white image with 3 solid black rectangles of widths [60, 100, 140] px."""
    import cv2
    import numpy as np

    img = np.full((480, 640, 3), 255, dtype=np.uint8)
    widths = [60, 100, 140]
    x_starts = [40, 160, 340]
    for x0, w in zip(x_starts, widths, strict=True):
        cv2.rectangle(img, (x0, 120), (x0 + w - 1, 320), (0, 0, 0), -1)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return bytes(buf), widths


class _RectMeasurement(schemas.BaseModel):
    count: int
    widths_px: list[int]


@pytest.mark.live
def test_schema_plus_code_execution_on_vertex(svi_project):
    """U1 capability probe: structured output + ToolCodeExecution + thinking_level + media_resolution."""
    from google.genai import types

    mode = gemini_client.CodeExecSchemaMode.DEFAULT
    assert mode in (
        gemini_client.CodeExecSchemaMode.SCHEMA_NATIVE,
        gemini_client.CodeExecSchemaMode.SCHEMA_IN_PROMPT,
    )
    png_bytes, expected_widths = _synthetic_three_rects()
    client = gemini_client.make_vertex_client(svi_project, credentials=auth.get_credentials())
    prompt = (
        "Use Python code execution (with cv2 or numpy/PIL) to load the attached image, threshold "
        "the black rectangles on the white background, measure the exact pixel width of each "
        "rectangle (sorted ascending), print 'MEASURE: ' followed by JSON, and return count and widths_px."
    )
    cfg, extra = gemini_client._build_config(
        _RectMeasurement,
        code_execution=True,
        validator=lambda r: None,
        thinking_level="MEDIUM",
        media_resolution="HIGH",
        mode=mode,
    )
    parts = [
        types.Part.from_text(text=prompt),
        types.Part.from_bytes(data=png_bytes, mime_type="image/png"),
    ]
    if extra is not None:
        parts.append(types.Part.from_text(text=extra))
    resp = client.models.generate_content(
        model=gemini_client.DEFAULT_MODEL,
        contents=[types.Content(role="user", parts=parts)],
        config=types.GenerateContentConfig(**cfg),
    )
    exec_parts = []
    outcomes = []
    texts = []
    for cand in resp.candidates or []:
        for p in (cand.content.parts if cand.content else None) or []:
            if getattr(p, "executable_code", None) is not None:
                exec_parts.append(p.executable_code)
            if getattr(p, "code_execution_result", None) is not None:
                outcomes.append(str(p.code_execution_result.outcome))
            if getattr(p, "text", None):
                texts.append(p.text)
    assert len(exec_parts) >= 1, "Expected >= 1 executable_code part"
    assert any("OUTCOME_OK" in o for o in outcomes), f"Expected OUTCOME_OK, got {outcomes}"
    parsed = gemini_client.parse_reply("\n".join(texts), _RectMeasurement)
    assert parsed.count == 3
    got_widths = sorted(parsed.widths_px)
    assert len(got_widths) == 3
    for got, exp in zip(got_widths, expected_widths, strict=True):
        assert abs(got - exp) <= 3, f"Width {got} not within +-3 px of {exp}"
    usage = resp.usage_metadata
    assert getattr(usage, "tool_use_prompt_token_count", None) is not None


@pytest.mark.live
def test_pinned_code_exec_schema_mode_still_works(svi_project):
    """Drift-guard live test for CodeExecSchemaMode.DEFAULT."""
    png_bytes, expected_widths = _synthetic_three_rects()
    client = gemini_client.make_vertex_client(svi_project, credentials=auth.get_credentials())
    backend = gemini_client.VertexGeminiBackend(
        client, thinking_level="MEDIUM", media_resolution="HIGH"
    )
    runner = gemini_client.GeminiRunner(backend, max_calls=3, concurrency=1)

    def _validate(r: _RectMeasurement) -> None:
        if r.count != 3 or len(r.widths_px) != 3:
            raise ValueError(f"expected 3 widths, got {r}")

    prompt = (
        "Use Python code execution to measure the pixel widths of the 3 black rectangles in the "
        'white image. Print \'MEASURE: {"count": ..., "widths_px": [...]}\' from Python and '
        "return the JSON."
    )
    out = asyncio.run(
        runner.ask(
            [prompt, png_bytes],
            _RectMeasurement,
            code_execution=True,
            validator=_validate,
        )
    )
    assert out is not None
    assert out.count == 3
    for got, exp in zip(sorted(out.widths_px), expected_widths, strict=True):
        assert abs(got - exp) <= 3


@pytest.mark.live
def test_low_thinking_uses_fewer_thought_tokens_than_medium(svi_project, rendered_view):
    """U5 live check: LOW thinking_level uses <= thought tokens than MEDIUM on the same input."""
    client = gemini_client.make_vertex_client(svi_project, credentials=auth.get_credentials())
    prompt = pipeline.detection_prompt()

    be_low = gemini_client.VertexGeminiBackend(
        client, thinking_level="LOW", media_resolution="MEDIUM"
    )
    r_low = gemini_client.GeminiRunner(be_low, max_calls=2, concurrency=1)

    be_med = gemini_client.VertexGeminiBackend(
        client, thinking_level="MEDIUM", media_resolution="MEDIUM"
    )
    r_med = gemini_client.GeminiRunner(be_med, max_calls=2, concurrency=1)

    async def _run_both():
        low = await r_low.ask([prompt, rendered_view], schemas.FrameDetections, seed=42)
        med = await r_med.ask([prompt, rendered_view], schemas.FrameDetections, seed=42)
        return low, med

    out_low, out_med = asyncio.run(_run_both())
    assert out_low is not None and out_med is not None
    print(f"thoughts_tokens: LOW={r_low.cost.thoughts_tokens} MEDIUM={r_med.cost.thoughts_tokens}")
    assert r_low.cost.thoughts_tokens <= r_med.cost.thoughts_tokens


@pytest.mark.live
def test_live_uc4_measure_roof_angles_within_4deg(svi_project):
    """U11 live check: uc4_measure_roof_angles eave angle agrees within +-4 deg of roof.py fitLine."""
    import cv2
    import numpy as np

    from svi_geo import usecases as uc

    # Synthetic 640x480 house facade + roof with a clear horizontal eave line at row 160 (angle 0.0 deg)
    img = np.full((480, 640, 3), 235, dtype=np.uint8)
    img[160:380, 80:560] = (140, 155, 175)  # facade wall below eave
    img[80:160, 80:560] = (70, 80, 95)  # roof band above eave
    cv2.line(img, (80, 160), (560, 160), (20, 20, 20), 4)

    client = gemini_client.make_vertex_client(svi_project, credentials=auth.get_credentials())
    backend = gemini_client.VertexGeminiBackend(
        client, thinking_level="MEDIUM", media_resolution="HIGH"
    )
    r = gemini_client.GeminiRunner(backend, max_calls=3, concurrency=1)
    res = asyncio.run(uc.uc4_measure_roof_angles(img, r, tol_deg=4.0))
    assert res["agree"] is True, f"Expected agreement within 4 deg, got {res['agreement_line']}"
    assert res["delta_deg"] <= 4.0
    assert r.cost.code_exec_runs >= 1
    assert r.cost.code_exec_ok == r.cost.code_exec_runs
