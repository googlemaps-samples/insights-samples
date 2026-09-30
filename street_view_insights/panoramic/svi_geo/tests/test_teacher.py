"""Unit tests for silver-teacher schemas, zoom tiling, image-hash caching, and disclosure (Task T6)."""

from __future__ import annotations

import asyncio

import numpy as np
import pytest
from pydantic import ValidationError

from svi_geo import gemini_client, schemas
from svi_geo import labelfree as lf
from svi_geo import teacher as tea


class _ScriptedBackend:
    def __init__(self, reply_text: str, model: str | None = None):
        self.reply_text = reply_text
        self.model = model or tea.teacher_model()
        self.location = "global"
        self.calls = 0

    async def generate(self, parts, schema, code_execution=False, **kw):
        self.calls += 1
        return gemini_client.RawReply(
            text=self.reply_text,
            usage={"prompt_token_count": 200, "candidates_token_count": 50},
        )


def test_teacher_schemas_validation():
    hf = schemas.HouseFramingVerdict(
        house_visible=True,
        fully_in_frame=True,
        truncation="NONE",
        occlusion=schemas.Occlusion.NONE,
        stories=2,
        exterior_material=schemas.ExteriorMaterial.BRICK,
        roof_type=schemas.RoofType.GABLE,
        confidence=0.9,
        visual_evidence="Two-story brick facade with unobstructed gable roof.",
    )
    assert hf.fully_in_frame is True

    ec = schemas.EntityConfirm(
        target_class=schemas.AssetClass.UTILITY_POLE,
        confirmed=True,
        box_2d=[100, 450, 900, 520],
        confidence=0.95,
        visual_evidence="Vertical wooden pole with crossarm.",
    )
    assert ec.confirmed is True

    with pytest.raises(ValidationError):
        schemas.EntityConfirm(
            target_class=schemas.AssetClass.UTILITY_POLE,
            confirmed=True,
            box_2d=[900, 450, 100, 520],  # ymin >= ymax
            confidence=0.95,
            visual_evidence="Bad box.",
        )

    sv = schemas.SurfaceSlotVerdict(
        side=schemas.Side.LEFT,
        present=False,
        material=None,
        condition=None,
        confidence=0.92,
        visual_evidence="Grass verge abuts asphalt road with no paved walkway.",
    )
    assert sv.present is False

    rv = schemas.RoofVisibility(
        roof_visible=True,
        visible_fraction=0.75,
        edge_50pct_visible=True,
        occlusion_reason="NONE",
        confidence=0.88,
    )
    assert rv.edge_50pct_visible is True

    rt = schemas.RoofTrace(
        roof_visible=True,
        edges=[
            schemas.RoofEdge(edge_type="EAVE", points=[[300, 100], [300, 900]]),
        ],
        confidence=0.85,
    )
    assert len(rt.edges) == 1


def test_tiles_cover_image_exactly_and_exceed_1_5x_resolution():
    # Student view size is 512x384; pass a 1024x768 high-res source image (2.0x >= 1.5x)
    rng = np.random.default_rng(42)
    img = rng.integers(0, 256, size=(768, 1024, 3), dtype=np.uint8)
    tile_list = tea.tiles(img, student_size=(512, 384))
    assert len(tile_list) == 4
    covered = np.zeros((768, 1024), dtype=bool)
    for t in tile_list:
        x0, y0, x1, y1 = t["bbox_px"]
        covered[y0:y1, x0:x1] = True
        assert t["image"].shape == (y1 - y0, x1 - x0, 3)
        assert np.array_equal(t["image"], img[y0:y1, x0:x1])
    assert bool(np.all(covered))
    assert tea.effective_scale(img.shape[:2], (512, 384)) >= 1.5


def test_cache_hit_makes_no_backend_call_and_carries_disclosure(tmp_path):
    reply_json = (
        '{"roof_visible": true, "visible_fraction": 0.8, "edge_50pct_visible": true, '
        '"occlusion_reason": "NONE", "confidence": 0.9}'
    )
    backend = _ScriptedBackend(reply_json)
    runner = gemini_client.GeminiRunner(backend, max_calls=10)
    cache = tea.TeacherCache(tmp_path / "teacher_cache.jsonl")
    img = np.full((384, 512, 3), 128, dtype=np.uint8)

    rec1 = asyncio.run(
        tea.ask_teacher(
            runner,
            cache=cache,
            task="roof_visibility",
            image=img,
            schema=schemas.RoofVisibility,
        )
    )
    assert backend.calls == 1
    assert rec1["cached"] is False
    assert rec1["disclosure"] == lf.TEACHER_DISCLOSURE
    assert rec1["prompt_version"] == tea.PROMPT_VERSIONS["roof_visibility"]
    assert rec1["result"]["edge_50pct_visible"] is True

    # Second identical call hits disk/memory cache without invoking backend
    rec2 = asyncio.run(
        tea.ask_teacher(
            runner,
            cache=cache,
            task="roof_visibility",
            image=img,
            schema=schemas.RoofVisibility,
        )
    )
    assert backend.calls == 1
    assert rec2["cached"] is True
    assert rec2["disclosure"] == lf.TEACHER_DISCLOSURE
    assert rec2["image_sha256"] == rec1["image_sha256"]
