"""Zero-mock geometry tests for the detection pipeline, with a scripted Gemini backend."""

import asyncio
import math

import numpy as np
import pytest

from svi_geo import gemini_client as gc
from svi_geo import images, pipeline, rosette, schemas
from svi_geo import simulate as sim

INTR = rosette.DEFAULT_INTRINSICS


def _frames():
    fr = sim.synthetic_frames(2, 10.0, 48.85, 2.35, travel_deg=0.0)
    fr["gcs_uri"] = [f"gs://b/s/v0/{o}.jpg" for o in fr["observation_id"]]
    return fr


def test_views_cover_the_six_ground_cameras_level():
    fr = _frames()
    rows = fr[fr["pano_id"] == fr["pano_id"].iloc[0]].to_dict("records")
    specs = pipeline.views_for_pano(rows, INTR)
    assert [s.cam_k for s in specs] == list(range(6))
    assert all(s.view.pitch_deg == 0.0 for s in specs)
    yaws = sorted(s.view.yaw_deg for s in specs)
    np.testing.assert_allclose(np.diff(yaws), 60.0, atol=1e-9)


def test_box_to_observation_uses_view_geometry_and_camera_centre():
    fr = _frames()
    ref = sim.scene_ref(fr)
    rows = fr[fr["pano_id"] == fr["pano_id"].iloc[0]].to_dict("records")
    spec = pipeline.views_for_pano(rows, INTR)[1]
    fd = schemas.FrameDetections(
        detections=[
            {"label": "UTILITY_POLE", "box_2d": [200, 480, 700, 520], "confidence": 0.9},
            {"label": "UTILITY_POLE", "box_2d": [200, 100, 1000, 140], "confidence": 0.9},
            {"label": "HOUSE", "box_2d": [100, 600, 500, 900], "confidence": 0.1},  # low conf
        ]
    )
    obs = pipeline.detections_to_observations(fd, spec, ref)
    assert len(obs) == 2
    o = obs[0]
    w, h = spec.view.width, spec.view.height
    az, el_b = spec.view.pixel_to_bearing(0.5 * w, 0.7 * h)
    assert abs(o.ray.az_deg - float(az)) < 0.1
    assert o.ray.el_deg == pytest.approx(float(el_b)) == pytest.approx(o.el_bottom_deg)
    np.testing.assert_allclose(o.ray.origin, rosette.camera_center_enu(spec.pose, ref))
    assert obs[1].el_bottom_deg is None  # box touches the view bottom: no ground contact


def test_merge_intra_pano_keeps_most_confident_duplicate():
    fr = _frames()
    ref = sim.scene_ref(fr)
    rows = fr[fr["pano_id"] == fr["pano_id"].iloc[0]].to_dict("records")
    s0, s1 = pipeline.views_for_pano(rows, INTR)[:2]
    # the seam between views 0 and 1 is at +30 deg; a pole there appears in both views
    az = 30.0
    u0, v0, _ = s0.view.bearing_to_pixel(az, -10.0)
    u1, v1, _ = s1.view.bearing_to_pixel(az, -10.0)

    def box(u, v, w, h):
        return [int(1000 * (v - 200) / h), int(1000 * (u - 10) / w), int(1000 * v / h),
                int(1000 * (u + 10) / w)]  # fmt: skip

    w, h = s0.view.width, s0.view.height
    fd0 = schemas.FrameDetections(
        detections=[{"label": "UTILITY_POLE", "box_2d": box(u0, v0, w, h), "confidence": 0.6}]
    )
    fd1 = schemas.FrameDetections(
        detections=[{"label": "UTILITY_POLE", "box_2d": box(u1, v1, w, h), "confidence": 0.8}]
    )
    obs = pipeline.detections_to_observations(fd0, s0, ref)
    obs += pipeline.detections_to_observations(fd1, s1, ref)
    merged = pipeline.merge_intra_pano(obs)
    assert len(merged) == 1 and merged[0].confidence == 0.8


class BoxBackend:
    def __init__(self):
        self.n = 0

    async def generate(self, parts, schema, code_execution=False):
        self.n += 1
        text = (
            '{"detections": [{"label": "ROAD_SIGN", "box_2d": [400, 490, 600, 510], '
            '"confidence": 0.7, "material": "METAL"}]}'
        )
        return gc.RawReply(text, {"prompt_token_count": 1000, "candidates_token_count": 50})


def test_detect_panos_renders_in_code_and_sends_inline_images():
    fr = _frames()
    ref = sim.scene_ref(fr)
    jpg = images.encode_jpeg(np.full((INTR.height // 8, INTR.width // 8, 3), 120, np.uint8))
    fetched = []

    def fetch(uri):
        fetched.append(uri)
        return jpg

    backend = BoxBackend()
    runner = gc.GeminiRunner(backend, max_calls=100, log=lambda *_: None)
    run = asyncio.run(pipeline.detect_panos(fr, fetch, runner, INTR, ref))
    assert backend.n == 12  # 2 panos x 6 ground views, sky camera skipped
    assert all(not u.endswith("_6:5001ee.jpg") for u in fetched)
    assert len(run.records) == 12
    # one sign per view, but views of one pano never repeat an azimuth -> 12 observations
    assert len(run.observations) == 12
    assert {o.attrs["material"] for o in run.observations} == {"METAL"}
    assert all(math.isfinite(o.ray.az_deg) for o in run.observations)


def test_task_renderer_centres_a_small_view_on_the_predicted_bearing():
    from svi_geo import eval as ev

    fr = _frames()
    frame = np.full((5472 // 8, 3648 // 8, 3), 90, np.uint8)
    blob = images.encode_jpeg(frame)
    fetched = []

    def fetch(uri):
        fetched.append(uri)
        return blob

    render = pipeline.task_renderer(fr, fetch, INTR)
    row = fr.iloc[2]
    task = ev.ViewTask(
        "e1", "UTILITY_POLE", row.pano_id, int(row.cam_k), 123.0, -10.0, 8.0, row.observation_id
    )
    img, view = render(task)
    assert img.shape[:2] == (768, 768)
    assert view.yaw_deg == 123.0 and view.hfov_deg == 40.0
    # poles/signs are centred ~2 m above the ground point, so the view looks up from -10 deg
    assert -10.0 < view.pitch_deg < 10.0
    assert fetched == [row.gcs_uri]
