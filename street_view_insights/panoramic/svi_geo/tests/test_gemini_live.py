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
def rendered_view(svi_project, tmp_path_factory):
    from google.cloud import storage

    creds = auth.get_credentials()
    runner = data.QueryRunner(
        data.make_bigquery_client(svi_project, creds), cache_dir=data.DEFAULT_QUERY_CACHE
    )
    bucket = data.discover_bucket(runner)
    fetcher = images.GcsImageFetcher(
        storage.Client(project=svi_project, credentials=creds),
        cache_dir=tmp_path_factory.mktemp("frames"),
    )
    frame = images.decode(fetcher.fetch(data.gcs_uri_for(bucket, PARIS_SNAPSHOT, KNOWN_OBS)))
    assert frame.shape[:2] == (5472, 3648)
    img, _view = rosette.undistort(frame, rosette.DEFAULT_INTRINSICS, 80.0, pipeline.VIEW_SIZE)
    return img


@pytest.fixture(scope="module")
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
