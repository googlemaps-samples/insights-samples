"""Static + unit tests for utility_pole_subclassification_using_panoramic_svi and svi_geo pole sub-classification."""

from __future__ import annotations

import asyncio
import importlib.util
import math
import re
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

from svi_geo import cvchecks, data, gemini_client, geo, rosette, schemas
from svi_geo import simulate as sim
from svi_geo import usecases as uc

SKILL_DIR = (
    Path(__file__).resolve().parents[2]
    / "skills/utility_pole_subclassification_using_panoramic_svi"
)
SKILL_SCRIPT = SKILL_DIR / "scripts/subclassify_poles.py"
SKILL_MD = SKILL_DIR / "SKILL.md"


@pytest.fixture(scope="module")
def sp():
    assert SKILL_SCRIPT.exists(), f"Missing skill script: {SKILL_SCRIPT}"
    spec = importlib.util.spec_from_file_location("subclassify_poles", SKILL_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["subclassify_poles"] = mod
    spec.loader.exec_module(mod)
    yield mod
    sys.modules.pop("subclassify_poles", None)


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
            usage={"prompt_token_count": 420, "candidates_token_count": 95},
        )


def _dummy_fetch(_uri: str) -> bytes:
    img = np.full((5472, 3648, 3), 145, dtype=np.uint8)
    img[:1800, :] = (230, 200, 175)  # sky
    img[2600:, :] = (80, 80, 80)  # road
    # Vertical utility pole shaft in the center with cross-arm at top
    img[1100:4200, 1816:1832] = (35, 35, 35)
    img[1250:1270, 1720:1928] = (45, 45, 45)
    from svi_geo import images

    return images.encode_jpeg(img, quality=85)


def _attach_uris(fr):
    fr = fr.copy()
    fr["gcs_uri"] = [
        data.gcs_uri_for("test-bucket", s, o)
        for s, o in zip(fr["snapshot_id"], fr["observation_id"], strict=True)
    ]
    return fr


def test_pole_subclassification_schemas_and_enums():
    expected_subtypes = [
        "DISTRIBUTION_UTILITY_POLE",
        "JOINT_USE_UTILITY_POLE",
        "TRANSMISSION_POLE",
        "STANDALONE_STREET_LIGHT",
        "TRAFFIC_SIGNAL_MAST_ARM",
        "GUY_STUB_OR_PUSH_BRACE",
        "TELECOM_OR_CELL_MONOPOLE",
        "DOUBLE_POLE_TRANSFER_PAIR",
        "SIGN_POST_OR_OTHER",
    ]
    assert [e.value for e in schemas.PoleSubType] == expected_subtypes

    expected_crossarms = [
        "NONE",
        "SINGLE_ARM",
        "DOUBLE_ARM",
        "ALLEY_ARM",
        "ARMLESS_FRAMING",
        "UNKNOWN",
    ]
    assert [e.value for e in schemas.CrossArmConfig] == expected_crossarms

    expected_equipment = [
        "OVERHEAD_CONDUCTORS",
        "POLE_MOUNT_TRANSFORMER",
        "STREET_LIGHT_LUMINAIRE",
        "RISER_CONDUIT",
        "TELECOM_SPLICE_CASE",
        "GUY_WIRE",
        "CAPACITOR_OR_REGULATOR",
        "STREET_SIGN",
        "TRAFFIC_SIGNAL",
    ]
    assert [e.value for e in schemas.PoleEquipment] == expected_equipment

    obj = schemas.PoleSubClassification(
        pole_subtype=schemas.PoleSubType.JOINT_USE_UTILITY_POLE,
        is_true_utility_pole=True,
        material=schemas.AssetMaterial.WOOD,
        condition=schemas.AssetCondition.GOOD,
        crossarm_config=schemas.CrossArmConfig.SINGLE_ARM,
        attached_equipment=[
            schemas.PoleEquipment.OVERHEAD_CONDUCTORS,
            schemas.PoleEquipment.POLE_MOUNT_TRANSFORMER,
            schemas.PoleEquipment.TELECOM_SPLICE_CASE,
        ],
        is_double_pole=False,
        lean_deg=1.8,
        confidence=0.93,
        evidence_summary="Treated timber pole with primary cross-arm, can transformer, and lower telecom strand.",
    )
    assert obj.is_true_utility_pole is True
    assert obj.lean_deg == pytest.approx(1.8)
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        schemas.PoleSubClassification(
            pole_subtype=schemas.PoleSubType.DISTRIBUTION_UTILITY_POLE,
            is_true_utility_pole=True,
            material=schemas.AssetMaterial.WOOD,
            condition=schemas.AssetCondition.GOOD,
            crossarm_config=schemas.CrossArmConfig.SINGLE_ARM,
            attached_equipment=[],
            is_double_pole=False,
            lean_deg=60.0,  # out of [-45, 45]
            confidence=0.9,
            evidence_summary="Too much lean.",
        )


def test_estimate_post_lean_deg_measures_vertical_and_tilted_shafts():
    # 1. Straight vertical shaft -> ~0.0 deg
    img_v = np.full((400, 300, 3), 200, dtype=np.uint8)
    cv2.line(img_v, (150, 40), (150, 360), (20, 20, 20), 6)
    lean_v = cvchecks.estimate_post_lean_deg(img_v, box=(110, 40, 190, 360))
    assert abs(lean_v) < 1.5

    # 2. Clockwise tilted shaft (+8 deg from vertical: top shifted right of bottom, x_top > x_bot)
    img_cw = np.full((400, 300, 3), 200, dtype=np.uint8)
    dy = 300
    dx = int(round(dy * math.tan(math.radians(8.0))))
    cv2.line(img_cw, (150, 350), (150 + dx, 50), (20, 20, 20), 6)
    # Decoy tilted line far outside box (x=20) must be ignored by midpoint check
    cv2.line(img_cw, (20, 350), (20 - dx, 50), (20, 20, 20), 6)
    lean_cw = cvchecks.estimate_post_lean_deg(img_cw, box=(110, 40, 210, 360))
    assert 5.0 <= lean_cw <= 11.0

    # 3. Counter-clockwise tilted shaft (-8 deg from vertical: top shifted left of bottom, x_top < x_bot)
    img_ccw = np.full((400, 300, 3), 200, dtype=np.uint8)
    cv2.line(img_ccw, (150, 350), (150 - dx, 50), (20, 20, 20), 6)
    lean_ccw = cvchecks.estimate_post_lean_deg(img_ccw, box=(90, 40, 190, 360))
    assert -11.0 <= lean_ccw <= -5.0


def test_render_pole_inspection_composite_produces_three_calibrated_panels():
    fr = _attach_uris(sim.synthetic_frames(3, 12.0, 28.0502, -81.9601, travel_deg=0.0))
    pano_rows = fr[fr["seq_idx"] == 1]
    pole_lat, pole_lng = 28.05030, -81.96004

    comp = uc.render_pole_inspection_composite(
        pano_rows,
        pole_lat,
        pole_lng,
        _dummy_fetch,
        rosette.DEFAULT_INTRINSICS,
        panel_width=360,
        panel_height=480,
    )
    assert comp is not None
    img = comp["composite_img"]
    assert img.shape == (480, 360 * 3, 3)
    assert comp["black_fraction"] < 0.01
    assert 0.0 <= comp["vertical_support"] <= 1.0
    assert -45.0 <= comp["lsd_lean_deg"] <= 45.0
    assert comp["cam_k"] in range(6)
    assert len(comp["panels"]) == 3
    assert "pitch_deg" in comp and "vfov_deg" in comp


def test_render_pole_inspection_composite_seam_bearing_has_under_1pct_black_border():
    intr = rosette.load_intrinsics()
    fr = _attach_uris(sim.synthetic_frames(1, 12.0, 28.0502, -81.9601, travel_deg=0.0))
    pano_rows = fr[fr["seq_idx"] == 0]
    r0 = pano_rows.iloc[0]
    clat, clng = float(r0["lat"]), float(r0["lng"])
    # Place pole at bearing = 30.0 deg (directly on the seam between cam 0 at 0 deg and cam 1 at 60 deg)
    dist_m = 14.0
    az_rad = math.radians(30.0)
    pole_lat, pole_lng, _ = geo.enu_to_lla(
        dist_m * math.sin(az_rad), dist_m * math.cos(az_rad), 0.0, clat, clng, 0.0
    )

    comp = uc.render_pole_inspection_composite(
        pano_rows,
        float(pole_lat),
        float(pole_lng),
        _dummy_fetch,
        intr,
        panel_width=360,
        panel_height=480,
    )
    assert comp is not None
    assert comp["black_fraction"] < 0.01
    assert len(comp["used_cam_ks"]) >= 2


def test_subclassify_poles_fuses_multi_view_parallax_and_deterministic_gates():
    from svi_geo import entities as ent

    fr = _attach_uris(sim.synthetic_frames(4, 12.0, 28.0502, -81.9601, travel_deg=0.0))
    ref = (28.0502, -81.9601, 0.0)

    # Create three triangulated pole candidates:
    # Pole 1: True Joint-Use Utility Pole
    # Pole 2: Standalone Street Light where LLM mistakenly says is_true_utility_pole=True
    # Pole 3: Low-confidence empty-curb false detection (SIGN_POST_OR_OTHER, conf=0.10)
    p0 = fr[(fr["seq_idx"] == 0) & (fr["cam_k"] == 0)].iloc[0]
    p1 = fr[(fr["seq_idx"] == 1) & (fr["cam_k"] == 0)].iloc[0]

    def _make_entity(eid: str, east_m: float, north_m: float) -> ent.Entity:
        target = np.array([east_m, north_m, 0.0])
        pano_ids = [str(p0["capture_id"]), str(p1["capture_id"])]
        lat, lng, _ = geo.enu_to_lla(target[0], target[1], target[2], *ref)
        return ent.Entity(
            entity_id=eid,
            cls="UTILITY_POLE",
            point_enu=target,
            lat=float(lat),
            lng=float(lng),
            obs_ids=[f"{eid}_obs_0", f"{eid}_obs_1"],
            pano_ids=pano_ids,
            method="triangulated",
            rms_m=0.35,
            confidence=0.9,
            attrs={"material": ("WOOD", 1.0), "condition": ("GOOD", 1.0)},
            max_parallax_deg=25.0,
        )

    e1 = _make_entity("utility_pole_01", 8.0, 6.0)
    e2 = _make_entity("utility_pole_02", -8.0, 6.0)
    e3 = _make_entity("utility_pole_03", 10.0, 8.0)

    def _blank_fetch(_uri: str) -> bytes:
        # Featureless image so e3 has 0.0 vertical support
        img = np.full((5472, 3648, 3), 145, dtype=np.uint8)
        from svi_geo import images

        return images.encode_jpeg(img, quality=80)

    def reply_fn(idx, _parts, schema):
        assert schema is schemas.PoleSubClassification
        if idx == 0:
            return (
                '{"pole_subtype": "JOINT_USE_UTILITY_POLE", '
                '"is_true_utility_pole": false, '
                '"material": "WOOD", '
                '"condition": "GOOD", '
                '"crossarm_config": "SINGLE_ARM", '
                '"attached_equipment": ["OVERHEAD_CONDUCTORS", "POLE_MOUNT_TRANSFORMER", "TELECOM_SPLICE_CASE"], '
                '"is_double_pole": false, '
                '"lean_deg": 1.2, '
                '"confidence": 0.94, '
                '"evidence_summary": "Joint-use wooden distribution pole with primary cross-arm, transformer, and lower telecom bundle."}'
            )
        if idx == 1:
            return (
                '{"pole_subtype": "STANDALONE_STREET_LIGHT", '
                '"is_true_utility_pole": true, '
                '"material": "METAL", '
                '"condition": "GOOD", '
                '"crossarm_config": "NONE", '
                '"attached_equipment": ["STREET_LIGHT_LUMINAIRE"], '
                '"is_double_pole": false, '
                '"lean_deg": 0.5, '
                '"confidence": 0.91, '
                '"evidence_summary": "Tapered metal street light pole with cobra-head luminaire and underground feed."}'
            )
        return (
            '{"pole_subtype": "SIGN_POST_OR_OTHER", '
            '"is_true_utility_pole": false, '
            '"material": "UNKNOWN", '
            '"condition": "UNKNOWN", '
            '"crossarm_config": "NONE", '
            '"attached_equipment": [], '
            '"is_double_pole": false, '
            '"lean_deg": 0.0, '
            '"confidence": 0.10, '
            '"evidence_summary": "No vertical structure at the projected bearing; empty curb."}'
        )

    runner = gemini_client.GeminiRunner(_ScriptedBackend(reply_fn), max_calls=10)
    out = asyncio.run(
        uc.subclassify_poles(
            [e1, e2, e3],
            fr,
            _blank_fetch,
            runner,
            rosette.DEFAULT_INTRINSICS,
            max_poles=5,
        )
    )
    assert len(out["records"]) == 3
    assert out["true_utility_pole_count"] == 1
    assert out["non_utility_vertical_count"] == 1
    assert out["false_detection_count"] == 1

    r1, r2, r3 = out["records"][0], out["records"][1], out["records"][2]
    # Deterministic gate: JOINT_USE_UTILITY_POLE forces is_true_utility_pole=True
    assert r1["pole_subtype"] == "JOINT_USE_UTILITY_POLE"
    assert r1["is_true_utility_pole"] is True
    assert r1["is_false_detection"] is False
    # Parallax is strictly between the 2 selected views (not inflated to >100 deg by unselected panos)
    assert 5.0 < r1["max_parallax_deg"] < 90.0
    assert len(r1["composites"]) == 2

    # Deterministic gate: STANDALONE_STREET_LIGHT forces is_true_utility_pole=False
    assert r2["pole_subtype"] == "STANDALONE_STREET_LIGHT"
    assert r2["is_true_utility_pole"] is False
    assert r2["is_false_detection"] is False

    # False detection gate: SIGN_POST_OR_OTHER + low confidence + low vertical support
    assert r3["is_false_detection"] is True
    assert r3["is_true_utility_pole"] is False


def test_skill_script_and_markdown_safety_invariants(sp):
    assert [e.value for e in sp.PoleSubType] == [e.value for e in schemas.PoleSubType]
    assert [e.value for e in sp.CrossArmConfig] == [e.value for e in schemas.CrossArmConfig]
    assert [e.value for e in sp.PoleEquipment] == [e.value for e in schemas.PoleEquipment]
    assert (
        sp.PoleSubClassification.model_json_schema()
        == schemas.PoleSubClassification.model_json_schema()
    )

    src = SKILL_SCRIPT.read_text()
    assert "from_uri" not in src and "file_uri" not in src
    assert not re.search(r"SELECT\s+gcs_uri", src, re.I)
    for leak in ("//depot/", "svms_client", "blade:", "lingendj", "Geo Goldens"):
        assert leak not in src

    md = SKILL_MD.read_text()
    assert md.startswith("---\n")
    frontmatter = md.split("---\n", 2)[1]
    assert "name: utility-pole-subclassification-using-panoramic-svi\n" in frontmatter
    assert "description: >" not in frontmatter
    assert "description: " in frontmatter
    desc_line = next(line for line in frontmatter.splitlines() if line.startswith("description: "))
    desc_val = desc_line.removeprefix("description: ").strip()
    assert len(desc_val) < 500
    assert "Use when" in frontmatter and "Don't use for" in frontmatter
    assert "# Utility Pole Subclassification Using Panoramic SVI" in md
    assert "## How it works" in md
    assert "## Core Principles & Lessons Learned" in md
    assert "## Taxonomy & Sub-Classification Policy" in md
    assert "### Utility Pole vs. Lookalike Decision Policy" in md
    assert "## Prerequisites" in md
    assert "## Instructions (Step-by-Step Agentic Workflow)" in md
    assert "--mode fetch_sv" in md and "--mode triangulate" in md and "--mode render_candidates" in md
    assert "Trigger A" in md and "Trigger B" in md and "Trigger C" in md
    assert "--capture-id" in md and "--pano-id" in md and "--observation-id" in md
    assert "--coordinates" in md and "--output-dir" in md and "--output" in md
    assert "--location" in md and "--model" in md
    assert "saved_composite_images" in md and "false_detection_count" in md
    assert "svi_geo.data.render_sql" not in md
    for leak in ("//depot/", "svms_client", "blade:", "lingendj", "Geo Goldens"):
        assert leak not in md


def test_annotate_calibrated_sv_frame_and_contact_sheet_with_3d_reprojection():
    intr = rosette.DEFAULT_INTRINSICS
    fr = _attach_uris(sim.synthetic_frames(1, 12.0, 28.0502, -81.9601, travel_deg=0.0))
    pano_rows = fr[fr["seq_idx"] == 0]
    r0 = pano_rows[pano_rows["cam_k"] == 0].iloc[0]
    pose = r0["camera_pose"]
    clat, clng = float(pose["latitude"]), float(pose["longitude"])

    # Place a 3D candidate pole 14m ahead of cam 0 (heading ~0 deg = North)
    pole_lat, pole_lng, _ = geo.enu_to_lla(0.0, 14.0, 0.0, clat, clng, 0.0)
    raw_img = np.full((intr.height, intr.width, 3), 120, dtype=np.uint8)
    annotated = uc.annotate_calibrated_sv_frame(
        raw_img,
        intr,
        pose,
        0,
        scale=0.25,
        cap_idx=0,
        capture_id="t1:cap0",
        capture_date="2026-03-01",
        candidates=[
            {
                "pole_id": "P01",
                "lat": float(pole_lat),
                "lng": float(pole_lng),
                "pole_subtype": "JOINT_USE_UTILITY_POLE",
            }
        ],
    )
    assert annotated.shape == (int(round(intr.height * 0.25)), int(round(intr.width * 0.25)), 3)
    # Verify top-edge cyan world compass azimuth text (BGR = (255, 255, 0)) was stamped in top band (y < 20)
    top_band = annotated[:20, :, :]
    cyan_pixels = (top_band[:, :, 0] > 200) & (top_band[:, :, 1] > 200) & (top_band[:, :, 2] < 50)
    assert int(cyan_pixels.sum()) > 10

    # Verify 3D-to-2D reprojected magenta marker (BGR = (128, 0, 255) / (180, 0, 255)) was drawn
    magenta_pixels = (
        (annotated[:, :, 2] > 200)
        & (annotated[:, :, 1] < 90)
        & (annotated[:, :, 0] > 100)
    )
    assert int(magenta_pixels.sum()) > 15

    # Verify contact sheet rendering across all 6 ground cameras
    sheet_out = uc.render_capture_contact_sheet(
        pano_rows,
        _dummy_fetch,
        intr,
        cap_idx=0,
        camera_indices=(0, 1, 2, 3, 4, 5),
        single_scale=0.20,
        sheet_scale=0.15,
        candidates=[{"pole_id": "P01", "lat": float(pole_lat), "lng": float(pole_lng)}],
    )
    assert sheet_out is not None
    assert len(sheet_out["camera_frames"]) == 6
    assert sheet_out["contact_sheet"].shape[2] == 3
    assert set(sheet_out["cameras"].keys()) == {"0", "1", "2", "3", "4", "5"}


def test_triangulate_observations_2d_enu_and_gdop_rule():
    intr = rosette.DEFAULT_INTRINSICS
    fr = _attach_uris(sim.synthetic_frames(3, 15.0, 28.0502, -81.9601, travel_deg=0.0))
    fr["cap_idx"] = fr["seq_idx"]
    r_cap0 = fr[(fr["cap_idx"] == 0) & (fr["cam_k"] == 1)].iloc[0]
    r_cap2 = fr[(fr["cap_idx"] == 2) & (fr["cam_k"] == 2)].iloc[0]

    ref_lat, ref_lng = float(r_cap0["lat"]), float(r_cap0["lng"])
    # Place ground-truth pole at (East=+10m, North=+15m) relative to cap 0 (between cap 0 at N=0m and cap 2 at N=30m)
    true_lat, true_lng, _ = geo.enu_to_lla(10.0, 15.0, 0.0, ref_lat, ref_lng, 0.0)

    def _project_pole_into_row(row):
        pose = row["camera_pose"]
        de, dn, _ = geo.lla_to_enu(
            float(true_lat),
            float(true_lng),
            0.0,
            float(pose["latitude"]),
            float(pose["longitude"]),
            0.0,
        )
        az, el = rosette.dir_to_bearing(
            np.array([float(np.asarray(de).item()), float(np.asarray(dn).item()), -1.0])
        )
        u, v, ok = rosette.bearing_to_pixel(intr, pose, float(az), float(el), int(row["cam_k"]))
        assert bool(ok)
        return float(u), float(v)

    u0, v0 = _project_pole_into_row(r_cap0)
    u2, v2 = _project_pole_into_row(r_cap2)

    tri_out = uc.triangulate_observations_2d_enu(
        {
            "P01": [
                {"cap_idx": 0, "cam_k": 1, "u": u0, "v": v0},
                {"cap_idx": 2, "cam_k": 2, "u": u2, "v": v2},
            ],
            "P02_low_parallax": [
                {"cap_idx": 0, "cam_k": 1, "u": u0, "v": v0},
                {"cap_idx": 0, "cam_k": 1, "u": u0 + 4.0, "v": v0},
            ],
            "P03_single": [
                {"cap_idx": 0, "cam_k": 1, "u": u0, "v": v0},
            ],
        },
        fr,
        intr,
    )
    by_id = {r["pole_id"]: r for r in tri_out}
    p1 = by_id["P01"]
    assert p1["status"] == "OK"
    assert p1["gdop_warning"] is False
    assert p1["behind_camera"] is False
    assert p1["max_parallax_deg"] > 40.0
    assert p1["max_residual_m"] < 0.05
    err_m = float(geo.haversine_m(p1["lat"], p1["lng"], float(true_lat), float(true_lng)))
    assert err_m < 0.15

    p2 = by_id["P02_low_parallax"]
    assert p2["gdop_warning"] is True
    assert p2["status"] == "LOW_PARALLAX_WARNING"

    p3 = by_id["P03_single"]
    assert p3["n_views"] == 1
    assert p3["status"] == "SINGLE_RAY_UNVERIFIED"
    assert p3["gdop_warning"] is True


def test_audit_corridor_span_gaps_flags_over_50m_trigger_b():
    fr = _attach_uris(sim.synthetic_frames(7, 15.0, 28.0502, -81.9601, travel_deg=0.0))
    r0 = fr.iloc[0]
    ref_lat, ref_lng = float(r0["lat"]), float(r0["lng"])
    # Place two right-side poles at station 5m and station 75m (70m gap > 50m threshold)
    p1_lat, p1_lng, _ = geo.enu_to_lla(6.0, 5.0, 0.0, ref_lat, ref_lng, 0.0)
    p2_lat, p2_lng, _ = geo.enu_to_lla(6.0, 75.0, 0.0, ref_lat, ref_lng, 0.0)
    poles = [
        {"entity_id": "P01", "lat": float(p1_lat), "lng": float(p1_lng), "is_true_utility_pole": True},
        {"entity_id": "P02", "lat": float(p2_lat), "lng": float(p2_lng), "is_true_utility_pole": True},
    ]
    audit = uc.audit_corridor_span_gaps(poles, fr, max_span_m=50.0)
    assert audit["trigger_b_required"] is True
    assert len(audit["span_gaps"]) == 1
    gap = audit["span_gaps"][0]
    assert gap["side"] == "RIGHT"
    assert gap["from_entity_id"] == "P01" and gap["to_entity_id"] == "P02"
    assert gap["span_m"] == pytest.approx(70.0, abs=1.0)
    assert len(gap["intermediate_captures"]) >= 3


def test_multi_mode_cli_and_offline_triangulate(sp, tmp_path):
    spec_str = "P01=0:1:1820:2900,2:2:1900:2950;P02=1:4:2100:3100"
    parsed = sp.parse_observation_spec(spec_str)
    assert list(parsed.keys()) == ["P01", "P02"]
    assert len(parsed["P01"]) == 2 and parsed["P01"][0]["cap_idx"] == 0 and parsed["P01"][0]["cam_k"] == 1

    # Write a minimal sv_index.json to tmp_path and run --mode=triangulate completely offline
    sv_index = {
        "captures": [
            {
                "cap_idx": 0,
                "capture_id": "t1:cap0",
                "lat": 28.05020,
                "lng": -81.96010,
                "heading": 0.0,
                "cameras": {
                    "1": {
                        "pose": {
                            "latitude": 28.05020,
                            "longitude": -81.96010,
                            "heading": 60.0,
                            "pitch": 0.0,
                            "roll": 0.0,
                        }
                    }
                },
            },
            {
                "cap_idx": 2,
                "capture_id": "t1:cap2",
                "lat": 28.05045,
                "lng": -81.96010,
                "heading": 0.0,
                "cameras": {
                    "2": {
                        "pose": {
                            "latitude": 28.05045,
                            "longitude": -81.96010,
                            "heading": 120.0,
                            "pitch": 0.0,
                            "roll": 0.0,
                        }
                    }
                },
            },
        ]
    }
    (tmp_path / "sv_index.json").write_text(sp.json.dumps(sv_index))
    args = sp.parse_args(
        [
            "--mode",
            "triangulate",
            "--output-dir",
            str(tmp_path),
            "--observations",
            "P01=0:1:1824:2850,2:2:1824:2850",
        ],
        env={},
    )
    out = asyncio.run(sp.run_pipeline(args))
    assert out["mode"] == "triangulate"
    assert len(out["triangulated_poles"]) == 1
    assert out["triangulated_poles"][0]["pole_id"] == "P01"
    assert out["triangulated_poles"][0]["status"] == "OK"


def test_skill_cli_flags_and_sql_allowlist(sp):
    env = {"PROJECT_ID": "test-proj", "GCS_BUCKET": "test-bucket"}
    args = sp.parse_args(
        [
            "--lat",
            "28.0502",
            "--lng",
            "-81.9601",
            "--radius_m",
            "80",
            "--max_rosettes",
            "6",
            "--max_poles",
            "5",
            "--output_json",
            "/tmp/out.json",
            "--output_dir",
            "/tmp/out_dir",
        ],
        env=env,
    )
    assert args.project == "test-proj"
    assert args.gcs_bucket == "test-bucket"
    assert args.lat == pytest.approx(28.0502)
    assert args.lng == pytest.approx(-81.9601)
    assert args.radius_m == pytest.approx(80.0)
    assert args.max_rosettes == 6
    assert args.max_poles == 5
    assert args.output_json == "/tmp/out.json"
    assert args.output_dir == "/tmp/out_dir"

    # Also support --coordinates lat,lng and hyphenated flags
    args2 = sp.parse_args(
        [
            "--project",
            "p2",
            "--gcs-bucket",
            "gs://b2/",
            "--coordinates",
            "28.0502,-81.9601",
            "--radius-m",
            "60",
            "--max-rosettes",
            "4",
            "--max-poles",
            "3",
        ],
        env={},
    )
    assert args2.project == "p2"
    assert args2.gcs_bucket == "b2"
    assert args2.lat == pytest.approx(28.0502)
    assert args2.lng == pytest.approx(-81.9601)

    # Support --capture-id, --pano-id, and --observation-id (wired to ID_SQL)
    a_cap = sp.parse_args(["--capture-id", "t1:abc"], env=env)
    assert a_cap.capture_id == "t1:abc" and a_cap.lookup_id == "t1:abc"
    a_pano = sp.parse_args(["--pano-id", "pano123"], env=env)
    assert a_pano.pano_id == "pano123" and a_pano.lookup_id == "pano123"
    a_obs = sp.parse_args(["--observation-id", "o1:abc_0:5001ee"], env=env)
    assert a_obs.observation_id == "o1:abc_0:5001ee" and a_obs.lookup_id == "o1:abc_0:5001ee"
    with pytest.raises(SystemExit):
        sp.parse_args(["--observation-id", "x", "--pano-id", "y"], env=env)

    for sql_name in ("COORDS_SQL", "ID_SQL"):
        rendered = sp.render_sql(getattr(sp, sql_name), "my-proj", "imagery_insights___us")
        assert "my-proj.imagery_insights___us.pano_observations_latest" in rendered
        assert not re.search(r"\bgcs_uri\b", rendered)

    with pytest.raises(ValueError, match="dataset"):
        sp.render_sql(sp.COORDS_SQL, "my-proj", "bad_dataset")


def test_render_pole_inspection_composite_distance_adaptive_framing_and_hood_cut():
    intr = rosette.DEFAULT_INTRINSICS
    fr = _attach_uris(sim.synthetic_frames(1, 12.0, 28.0502, -81.9601, travel_deg=0.0))
    pano_rows = fr[fr["seq_idx"] == 0]
    r0 = pano_rows.iloc[0]
    clat, clng = float(r0["lat"]), float(r0["lng"])

    def _hood_painted_fetch(uri: str) -> bytes:
        from svi_geo import images

        m = re.search(r"_(\d)\.jpg$", uri)
        k = int(m.group(1)) if m else 0
        row = pano_rows[pano_rows["cam_k"] == k].iloc[0]
        pose = row["camera_pose"]
        img = np.full((intr.height, intr.width, 3), 180, dtype=np.uint8)
        step = 16
        us = np.arange(0, intr.width, step, dtype=np.float64) + (step - 1) / 2.0
        vs = np.arange(0, intr.height, step, dtype=np.float64) + (step - 1) / 2.0
        u, v = np.meshgrid(np.minimum(us, intr.width - 1), np.minimum(vs, intr.height - 1))
        _, el = rosette.pixel_to_bearing(intr, pose, u, v, k)
        hood_coarse = (el < rosette.HOOD_ELEV_DEG).astype(np.uint8)
        hood_full = cv2.resize(
            hood_coarse,
            (len(us) * step, len(vs) * step),
            interpolation=cv2.INTER_NEAREST,
        )[: intr.height, : intr.width].astype(bool)
        img[hood_full] = (255, 0, 255)
        return images.encode_jpeg(img, quality=92)

    near_lat, near_lng, _ = geo.enu_to_lla(6.0, 0.0, 0.0, clat, clng, 0.0)
    far_lat, far_lng, _ = geo.enu_to_lla(28.0, 0.0, 0.0, clat, clng, 0.0)

    comp_near = uc.render_pole_inspection_composite(
        pano_rows,
        float(near_lat),
        float(near_lng),
        _hood_painted_fetch,
        intr,
        panel_width=360,
        panel_height=480,
    )
    comp_far = uc.render_pole_inspection_composite(
        pano_rows,
        float(far_lat),
        float(far_lng),
        _hood_painted_fetch,
        intr,
        panel_width=360,
        panel_height=480,
    )
    assert comp_near is not None and comp_far is not None
    assert comp_near["pitch_deg"] > 8.0
    assert comp_far["pitch_deg"] < comp_near["pitch_deg"]
    assert "crown_el_range_deg" in comp_near and "base_el_range_deg" in comp_near

    # No vehicle-hood magenta pixels (el < -40 deg) may appear in any panel
    for panel in comp_near["panels"]:
        magenta = (panel[:, :, 0] > 210) & (panel[:, :, 1] < 40) & (panel[:, :, 2] > 210)
        assert float(magenta.mean()) == 0.0


def test_skill_id_lookup_query_path_uses_id_sql_and_byte_cap(sp, monkeypatch):
    from google.cloud import bigquery

    captured_calls: list[tuple[str, object]] = []

    class _FakeJob:
        total_bytes_processed = 123_456_789

        def result(self):
            return [
                {
                    "hit_lat": 28.0502,
                    "hit_lng": -81.9601,
                    "capture_id": "t1:cap0",
                    "pano_id": "t1:cap0",
                    "observation_id": f"o1:cap0_{k}:5001ee",
                    "snapshot_id": "2026_03",
                    "capture_time": "2026-03-01T12:00:00Z",
                    "lat": 28.0502,
                    "lng": -81.9601,
                    "heading": 0.0,
                    "pitch": 0.0,
                    "roll": 0.0,
                }
                for k in range(7)
            ]

    class _FakeBQClient:
        def __init__(self, project=None, credentials=None):
            self.project = project

        def query(self, sql, job_config=None):
            captured_calls.append((sql, job_config))
            return _FakeJob()

    monkeypatch.setattr(bigquery, "Client", _FakeBQClient)
    monkeypatch.setattr(sp._svi_auth, "get_credentials", lambda: None)

    df, gb = sp.query_corridor_frames(
        "my-proj",
        "imagery_insights___us",
        "my-bucket",
        lookup_id="t1:cap0",
        radius_m=80.0,
        max_rosettes=4,
    )
    assert len(captured_calls) == 2
    sql_used, dry_cfg = captured_calls[0]
    _, run_cfg = captured_calls[1]
    assert "WITH hit AS" in sql_used
    assert dry_cfg.dry_run is True
    assert run_cfg.maximum_bytes_billed == sp.MAX_BYTES_BILLED
    assert len(df) == 7
    assert gb == pytest.approx(0.123456789)


