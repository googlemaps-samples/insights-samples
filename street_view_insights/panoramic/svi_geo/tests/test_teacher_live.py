"""Live Gemini tests for silver teacher schemas (Task T6, requires --run-live)."""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

from svi_geo import auth, gemini_client, schemas
from svi_geo import labelfree as lf
from svi_geo import teacher as tea


@pytest.mark.live
def test_teacher_live_one_call_per_schema(svi_project, tmp_path):
    # Create a clean synthetic street/house view so no GCS download is needed for schema check
    img = np.full((384, 512, 3), 200, dtype=np.uint8)
    img[220:, :] = (90, 90, 90)  # road
    img[100:220, 140:380] = (150, 120, 110)  # house wall
    img[60:100, 130:390] = (80, 70, 70)  # roof

    model = tea.teacher_model()
    client = gemini_client.make_vertex_client(svi_project, credentials=auth.get_credentials())
    backend = gemini_client.VertexGeminiBackend(client, model=model)
    runner = gemini_client.GeminiRunner(backend, max_calls=10, concurrency=5)
    cache = tea.TeacherCache(tmp_path / "live_teacher_cache.jsonl")

    tasks = [
        ("house_framing", schemas.HouseFramingVerdict, {}),
        ("entity_confirm", schemas.EntityConfirm, {"target_class": "HOUSE"}),
        ("surface_slot", schemas.SurfaceSlotVerdict, {"side": "CENTER"}),
        ("roof_visibility", schemas.RoofVisibility, {}),
        ("roof_trace", schemas.RoofTrace, {}),
    ]

    async def run_all():
        return await asyncio.gather(
            *(
                tea.ask_teacher(runner, cache=cache, task=t, image=img, schema=s, **kw)
                for t, s, kw in tasks
            )
        )

    records = asyncio.run(run_all())
    assert len(records) == 5
    for rec, (_, schema_cls, _) in zip(records, tasks, strict=True):
        assert rec["disclosure"] == lf.TEACHER_DISCLOSURE
        assert rec["result"] is not None
        validated = schema_cls.model_validate(rec["result"])
        assert isinstance(validated, schema_cls)
