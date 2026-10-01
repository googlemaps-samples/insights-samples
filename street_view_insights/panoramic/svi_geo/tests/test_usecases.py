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
    # Horizontal roof eave line
    img[1800:2600, 1200:2400] = (120, 100, 90)
    # Green textured tree canopy + trunk to the left of centre
    rng = np.random.default_rng(17)
    img[1400:2650, 1200:1600, 0] = rng.integers(30, 60, size=(1250, 400), dtype=np.uint8)
    img[1400:2650, 1200:1600, 1] = rng.integers(120, 180, size=(1250, 400), dtype=np.uint8)
    img[1400:2650, 1200:1600, 2] = rng.integers(35, 75, size=(1250, 400), dtype=np.uint8)
    img[2550:4000, 1392:1408] = (35, 45, 55)
    # Vertical post in the middle spanning both +9 and -9 deg camera pitches
    img[1200:4200, 1820:1828] = (30, 30, 30)
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


def test_default_variant_enables_validated_improvements():
    dv = uc.DEFAULT_VARIANT
    assert dv.name == "final"
    assert dv.uc1_framing_weighted_fusion is True
    assert dv.uc1_facade_edge_triangulation is True
    assert dv.uc2_min_post_panos == 2
    assert dv.uc2_cv_post_gate is True
    assert dv.uc3_prompt_version == "v1"
    assert dv.uc3_kerb_sidewalk_prior is True
    assert dv.uc4_sky_contact_min == pytest.approx(0.25)
    assert dv.uc4_validator_gates is True


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
            '{"label": "UTILITY_POLE", "box_2d": [200, 480, 643, 520], "confidence": 0.9, "material": "WOOD"},'
            '{"label": "STREET_TREE", "box_2d": [180, 320, 643, 440], "confidence": 0.88, "condition": "GOOD"},'
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
    assert all(e.cls != "HOUSE" for e in out["entities"])
    assert "trees_located" in out and "trees_unlocated" in out
    assert "posts_located" in out and "posts_unlocated" in out
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


def test_uc3_v1_prompt_and_kerb_sidewalk_prior_survives_viterbi():
    fr = _attach_uris(sim.synthetic_frames(5, 10.0, 28.0502, -81.9601, travel_deg=0.0))
    panos = sequence.build_sequences(fr.drop_duplicates("pano_id"))
    panos["travel_deg"] = sequence.travel_bearing(panos)
    sel = panos.sort_values("seq_idx").reset_index(drop=True)
    sel_frames = fr.drop(columns=["seq_id", "seq_idx"]).merge(
        sel[["pano_id", "seq_idx", "travel_deg"]], on="pano_id"
    )
    seen_prompts = []

    def reply_fn(idx, parts, _schema):
        seen_prompts.append(parts[0])
        # Middle pano has a weak false-positive sidewalk on RIGHT (0.65), others say ABSENT (0.92)
        if idx == 2:
            return (
                '{"observations": ['
                '{"asset": "ROAD", "side": "CENTER", "present": true, "material": "Paved Asphalt", "condition": "Good", "confidence": 0.95},'
                '{"asset": "SIDEWALK", "side": "LEFT", "present": true, "material": "Concrete", "condition": "Good", "confidence": 0.9},'
                '{"asset": "SIDEWALK", "side": "RIGHT", "present": true, "material": "Concrete", "condition": "Fair", "confidence": 0.65}'
                "]}"
            )
        return (
            '{"observations": ['
            '{"asset": "ROAD", "side": "CENTER", "present": true, "material": "Paved Asphalt", "condition": "Good", "confidence": 0.95},'
            '{"asset": "SIDEWALK", "side": "LEFT", "present": true, "material": "Concrete", "condition": "Good", "confidence": 0.9},'
            '{"asset": "SIDEWALK", "side": "RIGHT", "present": false, "material": null, "condition": null, "confidence": 0.92}'
            "]}"
        )

    v3 = uc.Variant(name="v3b", uc3_prompt_version="v1", uc3_kerb_sidewalk_prior=True)
    runner = gemini_client.GeminiRunner(_ScriptedBackend(reply_fn), max_calls=20)
    out = asyncio.run(
        uc.uc3_run(
            sel,
            sel_frames,
            _dummy_fetch,
            runner,
            rosette.DEFAULT_INTRINSICS,
            variant=v3,
        )
    )
    assert out["prompt_version"] == "uc3_v1"
    first_txt = getattr(seen_prompts[0], "text", str(seen_prompts[0]))
    assert "MUST set present=false" in first_txt
    assert all(x == "ABSENT" for x in out["smooth_by_slot"]["RIGHT"])


def test_variant_describe_lists_all_tuned_fields():
    desc = uc.DEFAULT_VARIANT.describe()
    assert desc.splitlines()[0].strip() == "variant=final"
    for field_name in (
        "uc1_view_size",
        "uc1_sky_contact_weight",
        "uc1_truncation_penalty",
        "uc1_framing_weighted_fusion",
        "uc1_facade_edge_triangulation",
        "uc1_clahe",
        "uc2_min_post_panos",
        "uc2_cv_post_gate",
        "uc3_prompt_version",
        "uc3_road_view_size",
        "uc3_kerb_sidewalk_prior",
        "uc4_view_size",
        "uc4_sky_contact_min",
        "uc4_validator_gates",
        "uc4_clahe",
        "antialias",
        "thinking_level",
        "media_resolution",
    ):
        assert field_name in desc, f"missing {field_name} in Variant.describe()"


def test_uc1_run_honours_variant_view_size():
    fr = _attach_uris(sim.synthetic_frames(6, 10.0, 28.0502, -81.9601, travel_deg=0.0))
    panos = sequence.build_sequences(fr.drop_duplicates("capture_id"))
    fr = fr.drop(columns=["seq_id", "seq_idx"]).merge(
        panos[["capture_id", "seq_id", "seq_idx"]], on="capture_id", how="left"
    )
    _, ranked = uc.uc1_select_views(
        fr, 28.0504, -81.9599, rosette.DEFAULT_INTRINSICS, max_per_seq=2, n=2
    )

    def reply_fn(_idx, _parts, _schema):
        return (
            '{"house_visible": true, "box_2d": [250, 350, 750, 650], '
            '"occlusion": "NONE", "facade_visible_fraction": 0.85, '
            '"stories": 2, "exterior_material": "STUCCO", "roof_type": "GABLE", '
            '"confidence": 0.9}'
        )

    v_custom = uc.Variant(name="custom_sz", uc1_view_size=(640, 480), uc1_clahe=True)
    runner = gemini_client.GeminiRunner(_ScriptedBackend(reply_fn), max_calls=10)
    out = asyncio.run(
        uc.uc1_run(ranked, _dummy_fetch, runner, rosette.DEFAULT_INTRINSICS, variant=v_custom)
    )
    assert out["crops"][0].shape == (480, 640, 3)
    assert "redaction_overlap_max" in out
    assert 0.0 <= out["redaction_overlap_max"] <= 1.0


def test_uc2_peak_rss_reduced_with_scaled_decode():
    import tracemalloc

    from svi_geo import images, pipeline

    fr = _attach_uris(sim.synthetic_frames(1, 10.0, 28.0502, -81.9601, travel_deg=0.0))
    specs = pipeline.views_for_pano(fr.to_dict("records"), rosette.DEFAULT_INTRINSICS)
    jpeg_bytes = _dummy_fetch("dummy")

    tracemalloc.start()
    frames_full = [images.decode(jpeg_bytes, scale=1.0) for _ in specs]
    views_full = [
        pipeline.render_view(im, rosette.DEFAULT_INTRINSICS, s)
        for im, s in zip(frames_full, specs, strict=True)
    ]
    _, peak_full = tracemalloc.get_traced_memory()
    del frames_full, views_full
    tracemalloc.stop()

    tracemalloc.start()
    scale = images.decode_scale_for_view(specs[0].view.width, specs[0].view.hfov_deg)
    frames_scaled = [images.decode(jpeg_bytes, scale=scale) for _ in specs]
    views_scaled = [
        pipeline.render_view(im, rosette.DEFAULT_INTRINSICS, s)
        for im, s in zip(frames_scaled, specs, strict=True)
    ]
    _, peak_scaled = tracemalloc.get_traced_memory()
    del frames_scaled, views_scaled
    tracemalloc.stop()

    assert scale == 0.5
    assert peak_scaled <= 0.60 * peak_full


class _ScriptedCodeExecBackend:
    def __init__(self, reply_text: str, stdout_text: str | None = 'MEASURE: {"ok": 1}\n'):
        self.reply_text = reply_text
        self.stdout_text = stdout_text
        self.model = gemini_client.DEFAULT_MODEL
        self.location = "global"

    async def generate(self, parts, schema, code_execution=False, **kw):
        steps = []
        if code_execution and self.stdout_text is not None:
            steps.append(
                gemini_client.CodeExecStep(
                    language="PYTHON",
                    code="import cv2, numpy as np\nprint('MEASURE: {\"ok\": 1}')",
                    outcome="OUTCOME_OK",
                    stdout=self.stdout_text,
                )
            )
        return gemini_client.RawReply(
            text=self.reply_text,
            usage={
                "prompt_token_count": 300,
                "tool_use_prompt_token_count": 120,
                "candidates_token_count": 60,
                "thoughts_token_count": 80,
            },
            code_outputs=[self.stdout_text] if self.stdout_text else [],
            exec_trace=gemini_client.CodeExecTrace(steps=steps),
        )


def test_uc4_measure_roof_angles_validates_trace_and_flags_disagreement():
    img = images_from_dummy()
    # Agreeing model angle (0.5 deg vs horizontal 0.0 deg line, tolerance 4.0 deg)
    b_ok = _ScriptedCodeExecBackend(
        '{"eave_angle_deg": 0.5, "rake_angle_deg": null, "lsd_overlap_fraction": 0.75, "n_segments": 3, "confidence": 0.92}',
        'MEASURE: {"eave_angle_deg": 0.5, "lsd_overlap_fraction": 0.75}\n',
    )
    runner_ok = gemini_client.GeminiRunner(b_ok, max_calls=5)
    res_ok = asyncio.run(uc.uc4_measure_roof_angles(img, runner_ok))
    assert res_ok["agree"] is True
    assert res_ok["agreement_line"].startswith("code_exec_agreement=agree(")
    assert runner_ok.cost.code_exec_runs == 1
    assert runner_ok.cost.code_exec_ok == 1

    # Disagreeing model angle (18.0 deg vs 0.0 deg -> > 4.0 deg tolerance)
    b_bad = _ScriptedCodeExecBackend(
        '{"eave_angle_deg": 18.0, "rake_angle_deg": null, "lsd_overlap_fraction": 0.75, "n_segments": 3, "confidence": 0.92}',
        'MEASURE: {"eave_angle_deg": 18.0, "lsd_overlap_fraction": 0.75}\n',
    )
    runner_bad = gemini_client.GeminiRunner(b_bad, max_calls=5)
    res_bad = asyncio.run(uc.uc4_measure_roof_angles(img, runner_bad))
    assert res_bad["agree"] is False
    assert res_bad["agreement_line"].startswith("code_exec_agreement=disagree(")

    # Model skips code execution -> CodeExecNotUsed counted as failure
    b_skip = _ScriptedCodeExecBackend(
        '{"eave_angle_deg": 0.5, "rake_angle_deg": null, "lsd_overlap_fraction": 0.75, "n_segments": 3, "confidence": 0.92}',
        stdout_text=None,
    )
    runner_skip = gemini_client.GeminiRunner(b_skip, max_calls=5)
    with pytest.raises(gemini_client.CodeExecNotUsed):
        asyncio.run(uc.uc4_measure_roof_angles(img, runner_skip))
    assert runner_skip.cost.failures >= 1


def images_from_dummy() -> np.ndarray:
    from svi_geo import images

    return images.decode(_dummy_fetch("dummy"), scale=0.25)


def test_uc1_uc2_uc3_agentic_measurements_validate_and_crosscheck():
    img = images_from_dummy()
    h, w = img.shape[:2]

    # UC1 storey count
    b_uc1 = _ScriptedCodeExecBackend(
        '{"window_rows": 2, "estimated_stories": 2, "row_y_centres_norm": [350, 650], "confidence": 0.9}',
        'MEASURE: {"window_rows": 2, "estimated_stories": 2}\n',
    )
    r_uc1 = gemini_client.GeminiRunner(b_uc1, max_calls=5)
    out_uc1 = asyncio.run(
        uc.uc1_count_storeys(img, r_uc1, box_2d=[200, 300, 800, 700], fused_stories=2)
    )
    assert "code_exec_agreement=" in out_uc1["agreement_line"]

    # UC2 pole lean angle
    b_uc2 = _ScriptedCodeExecBackend(
        '{"lean_angle_deg": 0.4, "vertical_support": 0.85, "confidence": 0.91}',
        'MEASURE: {"lean_angle_deg": 0.4, "vertical_support": 0.85}\n',
    )
    r_uc2 = gemini_client.GeminiRunner(b_uc2, max_calls=5)
    out_uc2 = asyncio.run(
        uc.uc2_measure_post_lean(img, r_uc2, box_px=(0.45 * w, 0.30 * h, 0.55 * w, 0.65 * h))
    )
    assert out_uc2["agree"] is True
    assert out_uc2["agreement_line"].startswith("code_exec_agreement=agree(")

    # UC3 road texture / material boundary
    import cv2

    from svi_geo import cvchecks as cvc

    desc = cvc.road_descriptor(img)
    expected_luma = float(desc[0] * 255.0)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    gx = cv2.Sobel(gray.astype(np.float32), cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray.astype(np.float32), cv2.CV_32F, 0, 1, ksize=3)
    expected_grad = float(np.hypot(gx, gy).mean())
    b_uc3 = _ScriptedCodeExecBackend(
        f'{{"change_row_norm": 500, "mean_luma": {expected_luma:.2f}, "grad_mean": {expected_grad:.2f}, "confidence": 0.9}}',
        f'MEASURE: {{"change_row_norm": 500, "mean_luma": {expected_luma:.2f}, "grad_mean": {expected_grad:.2f}}}\n',
    )
    r_uc3 = gemini_client.GeminiRunner(b_uc3, max_calls=5)
    out_uc3 = asyncio.run(
        uc.uc3_locate_material_boundary(img, r_uc3, viterbi_boundary_m=10.5, tol_m=1.0)
    )
    assert out_uc3["agree"] is True
    assert out_uc3["agreement_line"].startswith("code_exec_agreement=agree(")

    # Disagreeing Viterbi boundary (> 1.0 m off) flips agree to False
    r_uc3_bad = gemini_client.GeminiRunner(b_uc3, max_calls=5)
    out_uc3_bad = asyncio.run(
        uc.uc3_locate_material_boundary(img, r_uc3_bad, viterbi_boundary_m=15.0, tol_m=1.0)
    )
    assert out_uc3_bad["agree"] is False


def test_uc2_repeat_pass_diff_and_asset_audit():
    import pandas as pd

    fr = _attach_uris(sim.synthetic_frames(4, 10.0, 28.0502, -81.9601, travel_deg=0.0))
    cids = fr["capture_id"].unique().tolist()
    rp_df = pd.DataFrame([{"a_id": cids[0], "b_id": cids[1], "days_apart": 14, "sep_m": 2.1}])

    def reply_fn(_idx, _parts, schema):
        if schema is schemas.RepeatPassDiff:
            return '{"change_detected": false, "change_summary": "Same utility pole, seasonal shadow shift only.", "changed_box_2d": null, "confidence": 0.91}'
        return '{"present": true, "confidence": 0.93, "box_2d": [300, 400, 700, 600]}'

    runner = gemini_client.GeminiRunner(_ScriptedBackend(reply_fn), max_calls=10)
    diff_out = asyncio.run(
        uc.uc2_repeat_pass_diff(
            rp_df, fr, rosette.DEFAULT_INTRINSICS, _dummy_fetch, runner, width=320, height=240
        )
    )
    assert -1.0 <= diff_out["ssim"] <= 1.0
    assert diff_out["diff_heatmap"].shape == (240, 320, 3)
    assert diff_out["verdict"].change_detected is False

    assets_df = pd.DataFrame(
        [
            {
                "asset_id": "a1",
                "asset_type": "ASSET_CLASS_UTILITY_POLE",
                "lat": 28.05022,
                "lng": -81.96010,
                "wkt": "POINT(-81.96010 28.05022)",
                "dist_m": 2.5,
            }
        ]
    )
    loc_ents = [{"entity_id": "e1", "lat": 28.05023, "lng": -81.96010}]
    audit_out = asyncio.run(
        uc.uc2_asset_audit(
            assets_df, loc_ents, fr, rosette.DEFAULT_INTRINSICS, _dummy_fetch, runner
        )
    )
    assert audit_out["matched_count"] == 1
    assert audit_out["gemini_confirmed"] is True
    assert len(audit_out["audit_df"]) == 1


def test_agentic_helpers_signature_defaults():
    import inspect

    for fn in (
        uc.uc4_measure_roof_angles,
        uc.uc1_count_storeys,
        uc.uc2_measure_post_lean,
        uc.uc3_locate_material_boundary,
    ):
        sig = inspect.signature(fn)
        assert sig.parameters["thinking_level"].default == "MEDIUM", fn.__name__
        assert sig.parameters["media_resolution"].default == "HIGH", fn.__name__


def test_build_uc2_fewshot_parts_and_select_best_post_for_lean():
    import cv2

    h, w = 400, 400
    img1 = np.full((h, w, 3), 185, dtype=np.uint8)
    cv2.rectangle(img1, (198, 60), (202, 340), (30, 30, 30), -1)  # strong vertical pole
    img2 = np.full((h, w, 3), (220, 195, 175), dtype=np.uint8)
    rng = np.random.default_rng(23)
    canopy = np.zeros((150, 120, 3), dtype=np.uint8)
    canopy[..., 0] = rng.integers(25, 65, size=(150, 120))
    canopy[..., 1] = rng.integers(110, 185, size=(150, 120))
    canopy[..., 2] = rng.integers(30, 80, size=(150, 120))
    img2[50:200, 140:260] = canopy
    cv2.rectangle(img2, (195, 190), (205, 340), (35, 45, 55), -1)

    records = [
        {
            "image": img1,
            "detections": [
                schemas.Detection(
                    label="ROAD_SIGN",
                    box_2d=[150, 100, 850, 200],
                    confidence=0.80,
                    material="METAL",
                ),
                schemas.Detection(
                    label="UTILITY_POLE",
                    box_2d=[150, 470, 850, 530],
                    confidence=0.92,
                    material="WOOD",
                ),
            ],
        },
        {
            "image": img2,
            "detections": [
                schemas.Detection(
                    label="STREET_TREE",
                    box_2d=[125, 350, 850, 650],
                    confidence=0.89,
                    condition="GOOD",
                ),
            ],
        },
    ]

    parts, meta = uc.build_uc2_fewshot_parts(records)
    assert len(parts) == 9
    assert meta["n_examples"] == 2
    assert "UTILITY_POLE" in parts[3]
    assert "STREET_TREE" in parts[6]

    best_img, best_box, best_label, best_sup = uc.select_best_post_for_lean(records)
    assert best_img is img1
    assert best_label == "UTILITY_POLE"
    assert best_sup >= 0.6
    assert len(best_box) == 4
