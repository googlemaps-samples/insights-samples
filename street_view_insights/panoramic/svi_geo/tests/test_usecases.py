"""Unit tests for svi_geo/usecases.py (Task T7)."""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

from svi_geo import data, gemini_client, rosette, schemas, sequence
from svi_geo import simulate as sim
from svi_geo import usecases as uc


class _ScriptedBackend:
    def __init__(self, reply_fn):
        self.reply_fn = reply_fn
        self.model = gemini_client.DEFAULT_MODEL
        self.location = "global"
        self.calls = 0

    async def generate(self, parts, schema, code_execution=False, **kw):
        idx = self.calls
        self.calls += 1
        text = self.reply_fn(idx, parts, schema)
        return gemini_client.RawReply(
            text=text,
            usage={"prompt_token_count": 300, "candidates_token_count": 60},
        )


def _dummy_fetch(_uri: str) -> bytes:
    img = np.full((5472, 3648, 3), 140, dtype=np.uint8)
    img[:1800, :] = (230, 200, 175)  # sky
    img[2600:, :] = (80, 80, 80)  # road
    # Vertical post in the middle
    img[1900:3400, 1820:1828] = (30, 30, 30)
    # Horizontal roof eave line
    img[1800:2600, 1200:2400] = (120, 100, 90)
    from svi_geo import images

    return images.encode_jpeg(img, quality=85)


def _attach_uris(fr):
    fr = fr.copy()
    fr["gcs_uri"] = [
        data.gcs_uri_for("test-bucket", s, o)
        for s, o in zip(fr["snapshot_id"], fr["observation_id"], strict=True)
    ]
    return fr


def test_variant_defaults_preserve_current_parameters():
    v = uc.Variant()
    assert v.name == "baseline"
    assert v.uc1_sky_contact_weight == 0.0
    assert v.uc1_min_agree_views == 1
    assert v.uc2_min_post_panos == 1
    assert v.uc2_cv_post_gate is False
    assert v.uc2_house_facade_edges is False
    assert v.uc3_prompt_version == "v0"
    assert v.uc3_kerb_sidewalk_prior is False
    assert v.uc3_window_size == 3
    assert v.uc4_sky_contact_min == 0.0
    assert v.uc4_validator_gates is False


def test_uc1_select_and_run_with_recorded_replies():
    fr = _attach_uris(sim.synthetic_frames(8, 10.0, 28.0502, -81.9601, travel_deg=0.0))
    panos = sequence.build_sequences(fr.drop_duplicates("pano_id"))
    fr = fr.drop(columns=["seq_id", "seq_idx"]).merge(
        panos[["pano_id", "seq_id", "seq_idx"]], on="pano_id", how="left"
    )
    lat_h, lng_h = 28.0504, -81.9599
    cands, ranked = uc.uc1_select_views(
        fr, lat_h, lng_h, rosette.DEFAULT_INTRINSICS, max_per_seq=4, n=4
    )
    assert len(ranked) >= 2

    def reply_fn(idx, _parts, _schema):
        return (
            '{"house_visible": true, "box_2d": [250, 350, 750, 650], '
            '"occlusion": "NONE", "facade_visible_fraction": 0.85, '
            '"stories": 2, "exterior_material": "STUCCO", "roof_type": "GABLE", '
            '"confidence": 0.9}'
        )

    runner = gemini_client.GeminiRunner(_ScriptedBackend(reply_fn), max_calls=20)
    out = asyncio.run(
        uc.uc1_run(
            ranked,
            _dummy_fetch,
            runner,
            rosette.DEFAULT_INTRINSICS,
            width=512,
            height=384,
        )
    )
    assert int(out["res"]["centred"].sum()) == len(ranked)
    assert out["attrs"]["stories"][0] == 2
    assert out["attrs"]["exterior_material"][0] == "STUCCO"
    assert out["black_fraction_max"] < 0.01


def test_uc2_run_reproduces_located_and_house_counts():
    fr = _attach_uris(sim.synthetic_frames(6, 10.0, 28.0502, -81.9601, travel_deg=0.0))
    ref = sim.scene_ref(fr)

    def reply_fn(idx, _parts, schema):
        if schema is schemas.PresenceCheck:
            return '{"present": true, "confidence": 0.9, "box_2d": [300, 400, 700, 600]}'
        return (
            '{"detections": ['
            '{"label": "UTILITY_POLE", "box_2d": [200, 480, 850, 520], "confidence": 0.9, "material": "WOOD"},'
            '{"label": "HOUSE", "box_2d": [250, 300, 750, 700], "confidence": 0.88, "material": "BRICK"}'
            "]}"
        )

    runner = gemini_client.GeminiRunner(_ScriptedBackend(reply_fn), max_calls=100)
    out = asyncio.run(
        uc.uc2_run(
            fr,
            _dummy_fetch,
            runner,
            rosette.DEFAULT_INTRINSICS,
            ref,
            max_presence_checks=4,
        )
    )
    assert len(out["entities"]) > 0
    assert len(out["located"]) >= 1
    assert "houses_located" in out and "houses_unlocated" in out


def test_uc3_run_with_recorded_window_labels():
    fr = _attach_uris(sim.synthetic_frames(5, 10.0, 28.0502, -81.9601, travel_deg=0.0))
    panos = sequence.build_sequences(fr.drop_duplicates("pano_id"))
    panos["travel_deg"] = sequence.travel_bearing(panos)
    sel = panos.sort_values("seq_idx").reset_index(drop=True)
    sel_frames = fr.drop(columns=["seq_id", "seq_idx"]).merge(
        sel[["pano_id", "seq_idx", "travel_deg"]], on="pano_id"
    )

    def reply_fn(_idx, _parts, _schema):
        return (
            '{"observations": ['
            '{"asset": "ROAD", "side": "CENTER", "present": true, "material": "Paved Asphalt", "condition": "Good", "confidence": 0.95},'
            '{"asset": "SIDEWALK", "side": "LEFT", "present": true, "material": "Concrete", "condition": "Good", "confidence": 0.9},'
            '{"asset": "SIDEWALK", "side": "RIGHT", "present": false, "material": null, "condition": null, "confidence": 0.92}'
            "]}"
        )

    runner = gemini_client.GeminiRunner(_ScriptedBackend(reply_fn), max_calls=20)
    out = asyncio.run(
        uc.uc3_run(
            sel,
            sel_frames,
            _dummy_fetch,
            runner,
            rosette.DEFAULT_INTRINSICS,
        )
    )
    assert out["n_segments"] >= 1
    summary = out["summary"]
    right_row = summary[summary["side"] == "RIGHT"].iloc[0]
    assert right_row["absent_share"] == pytest.approx(1.0)


def test_uc4_select_and_run_with_recorded_edges():
    fr = _attach_uris(sim.synthetic_frames(6, 10.0, 28.0502, -81.9601, travel_deg=0.0))
    panos = sequence.build_sequences(fr.drop_duplicates("pano_id"))
    fr = fr.drop(columns=["seq_id", "seq_idx"]).merge(
        panos[["pano_id", "seq_id", "seq_idx"]], on="pano_id", how="left"
    )
    lat_b, lng_b = 28.0504, -81.9599
    roof_views, chosen, screen_records = uc.uc4_select_views(
        fr,
        lat_b,
        lng_b,
        _dummy_fetch,
        rosette.DEFAULT_INTRINSICS,
        n_views=2,
        width=600,
        height=450,
    )
    assert len(chosen) >= 1
    assert len(screen_records) >= len(chosen)

    def reply_fn(_idx, _parts, _schema):
        return (
            '{"roof_visible": true, "edges": ['
            '{"edge_type": "EAVE", "points": [[400, 200], [400, 800]]}'
            '], "confidence": 0.9}'
        )

    runner = gemini_client.GeminiRunner(_ScriptedBackend(reply_fn), max_calls=10)
    out = asyncio.run(
        uc.uc4_run(
            chosen,
            runner,
            width=600,
            height=450,
        )
    )
    assert len(out["results"]) == len(chosen)
    assert len(out["decoy_rates"]) == len(chosen)
