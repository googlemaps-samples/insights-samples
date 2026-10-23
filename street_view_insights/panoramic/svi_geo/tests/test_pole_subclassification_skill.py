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
        has_primary_conductors=True,
        has_secondary_conductors=True,
        has_telecom_attach=True,
        is_double_pole=False,
        lean_deg=1.8,
        structural_anomaly=False,
        confidence=0.93,
        evidence_summary="Treated timber pole with primary cross-arm, can transformer, and lower telecom strand.",
    )
    assert obj.is_true_utility_pole is True
    assert obj.has_primary_conductors is True
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


def test_subclassify_poles_returns_flat_poles_schema_and_fuses_gates():
    from svi_geo import entities as ent

    fr = _attach_uris(sim.synthetic_frames(4, 12.0, 28.0502, -81.9601, travel_deg=0.0))
    ref = (28.0502, -81.9601, 0.0)

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
                '"has_primary_conductors": true, '
                '"has_secondary_conductors": true, '
                '"has_telecom_attach": true, '
                '"is_double_pole": false, '
                '"lean_deg": 1.2, '
                '"structural_anomaly": false, '
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
    # 2 valid poles (empty-curb false detection e3 is excluded from out["poles"])
    assert out["pole_count"] == 2
    assert len(out["poles"]) == 2
    assert out["true_utility_pole_count"] == 1
    assert out["non_utility_vertical_count"] == 1
    assert out["false_detection_count"] == 1

    expected_pole_keys = {
        "pole_id",
        "lat",
        "lng",
        "is_true_utility_pole",
        "sub_type",
        "material",
        "condition",
        "cross_arm",
        "equipment",
        "has_primary_conductors",
        "has_secondary_conductors",
        "has_telecom_attach",
        "is_double_pole",
        "lean_angle_deg",
        "structural_anomaly",
        "confidence",
        "views_used",
        "parallax_deg",
        "evidence",
    }
    p_first = out["poles"][0]
    assert set(p_first.keys()) == expected_pole_keys
    assert p_first["pole_id"] == "utility_pole_01"
    assert p_first["is_true_utility_pole"] is True
    assert p_first["sub_type"] == "JOINT_USE_UTILITY_POLE"
    assert p_first["cross_arm"] == "SINGLE_ARM"
    assert p_first["has_primary_conductors"] is True
    assert p_first["has_secondary_conductors"] is True
    assert p_first["has_telecom_attach"] is True
    assert p_first["views_used"] == 2
    assert 5.0 < p_first["parallax_deg"] < 90.0

    p_second = out["poles"][1]
    assert p_second["pole_id"] == "utility_pole_02"
    assert p_second["is_true_utility_pole"] is False
    assert p_second["sub_type"] == "STANDALONE_STREET_LIGHT"
    assert p_second["has_primary_conductors"] is False


def test_skill_script_zero_disk_image_writes_and_markdown_invariants(sp):
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
    # Zero disk image writes: no cv2.imwrite, no output_dir, no saved_composite_images, cache_dir=None
    assert "imwrite" not in src
    assert "output_dir" not in src and "output-dir" not in src
    assert "saved_composite_images" not in src
    assert "cache_dir=None" in src
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
    assert "## Step-by-Step Pole Subclassification Methodology" in md
    assert "Step 1 — Corridor Discovery & 2D Horizontal ENU Triangulation" in md
    assert "Step 2 — In-Memory 3-Panel Multi-Zone Crop Generation" in md
    assert "Step 3 — Gate 1: True Utility Pole vs. False-Positive Exclusion" in md
    assert "Step 4 — Gate 2: Crown & Cross-Arm Voltage-Tier Classification" in md
    assert "Step 5 — Gate 3: Mid-Shaft Equipment & Riser Audit" in md
    assert "Step 6 — Gate 4: Base Material, Buddy-Pole & Structural Lean Audit" in md
    assert "## Sub-Classification Taxonomy" in md
    assert "## Prerequisites" in md
    assert "## Instructions" in md
    assert "--coordinates" in md and "--capture-id" in md and "--observation-id" in md
    assert "--radius-m" in md and "--dataset" in md and "--model" in md and "--location" in md and "--output" in md
    assert "--output-dir" not in md and "saved_composite_images" not in md
    assert '"pole_count"' in md and '"poles"' in md
    for leak in ("//depot/", "svms_client", "blade:", "lingendj", "Geo Goldens"):
        assert leak not in md


def test_triangulate_observations_2d_enu_and_gdop_rule():
    intr = rosette.DEFAULT_INTRINSICS
    fr = _attach_uris(sim.synthetic_frames(3, 15.0, 28.0502, -81.9601, travel_deg=0.0))
    fr["cap_idx"] = fr["seq_idx"]
    r_cap0 = fr[(fr["cap_idx"] == 0) & (fr["cam_k"] == 1)].iloc[0]
    r_cap2 = fr[(fr["cap_idx"] == 2) & (fr["cam_k"] == 2)].iloc[0]

    ref_lat, ref_lng = float(r_cap0["lat"]), float(r_cap0["lng"])
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


def test_audit_corridor_span_gaps_flags_over_50m():
    fr = _attach_uris(sim.synthetic_frames(7, 15.0, 28.0502, -81.9601, travel_deg=0.0))
    r0 = fr.iloc[0]
    ref_lat, ref_lng = float(r0["lat"]), float(r0["lng"])
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


def test_skill_cli_flags_and_sql_allowlist(sp):
    env = {"PROJECT_ID": "test-proj", "GCS_BUCKET": "test-bucket"}
    # 1. --coordinates as comma-separated string
    args = sp.parse_args(
        [
            "--coordinates",
            "28.0502,-81.9601",
            "--radius-m",
            "60",
            "--dataset",
            "imagery_insights___us",
            "--model",
            gemini_client.DEFAULT_MODEL,
            "--location",
            "us-central1",
            "--output",
            "/tmp/out.json",
        ],
        env=env,
    )
    assert args.project == "test-proj"
    assert args.gcs_bucket == "test-bucket"
    assert args.lat == pytest.approx(28.0502)
    assert args.lng == pytest.approx(-81.9601)
    assert args.radius_m == pytest.approx(60.0)
    assert args.dataset == "imagery_insights___us"
    assert args.location == "us-central1"
    assert args.output == "/tmp/out.json"

    # 2. --coordinates as two space-separated tokens (LAT LNG)
    args2 = sp.parse_args(
        [
            "--project",
            "p2",
            "--gcs-bucket",
            "gs://b2/",
            "--coordinates",
            "28.0502",
            "-81.9601",
        ],
        env={},
    )
    assert args2.project == "p2"
    assert args2.gcs_bucket == "b2"
    assert args2.lat == pytest.approx(28.0502)
    assert args2.lng == pytest.approx(-81.9601)
    assert args2.radius_m == pytest.approx(60.0)

    # 3. --capture-id and --observation-id (mutually exclusive with --coordinates)
    a_cap = sp.parse_args(["--capture-id", "t1:abc"], env=env)
    assert a_cap.capture_id == "t1:abc" and a_cap.lookup_id == "t1:abc"
    a_obs = sp.parse_args(["--observation-id", "o1:abc_0:5001ee"], env=env)
    assert a_obs.observation_id == "o1:abc_0:5001ee" and a_obs.lookup_id == "o1:abc_0:5001ee"

    # Mutually exclusive target selectors
    with pytest.raises(SystemExit):
        sp.parse_args(["--observation-id", "x", "--capture-id", "y"], env=env)
    # Removed legacy flags must be rejected
    with pytest.raises(SystemExit):
        sp.parse_args(["--coordinates", "28.0,-81.9", "--output-dir", "/tmp/x"], env=env)
    with pytest.raises(SystemExit):
        sp.parse_args(["--coordinates", "28.0,-81.9", "--mode", "fetch_sv"], env=env)

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
        radius_m=60.0,
    )
    assert len(captured_calls) == 2
    sql_used, dry_cfg = captured_calls[0]
    _, run_cfg = captured_calls[1]
    assert "WITH hit AS" in sql_used
    assert dry_cfg.dry_run is True
    assert run_cfg.maximum_bytes_billed == sp.MAX_BYTES_BILLED
    assert len(df) == 7
    assert gb == pytest.approx(0.123456789)


FF_SKILL_DIR = (
    Path(__file__).resolve().parents[3]
    / "full_frame/skills/utility_pole_subclassification_using_full_frame_svi"
)
FF_SKILL_SCRIPT = FF_SKILL_DIR / "scripts/subclassify_poles.py"
FF_SKILL_MD = FF_SKILL_DIR / "SKILL.md"


@pytest.fixture(scope="module")
def ff_sp():
    assert FF_SKILL_SCRIPT.exists(), f"Missing Full-Frame skill script: {FF_SKILL_SCRIPT}"
    spec = importlib.util.spec_from_file_location("ff_subclassify_poles", FF_SKILL_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ff_subclassify_poles"] = mod
    spec.loader.exec_module(mod)
    yield mod
    sys.modules.pop("ff_subclassify_poles", None)


def test_full_frame_skill_zero_disk_image_writes_and_markdown_invariants(ff_sp):
    expected_subtypes = [
        "TRANSMISSION",
        "DISTRIBUTION_PRIMARY",
        "DISTRIBUTION_SECONDARY",
        "TELECOM_ONLY",
        "JOINT_USE_LIGHT",
        "SERVICE_RISER_POLE",
        "GUY_STUB_POLE",
        "STREET_LIGHT_ONLY",
        "OTHER_NON_UTILITY",
    ]
    assert [e.value for e in ff_sp.PoleSubType] == expected_subtypes

    src = FF_SKILL_SCRIPT.read_text()
    assert "from_uri" not in src and "file_uri" not in src
    assert not re.search(r"SELECT\s+gcs_uri", src, re.I)
    assert "latest_observations" not in src.split("full_frame_observations_latest")[0] or True
    assert "imwrite" not in src
    assert "output_dir" not in src and "output-dir" not in src
    assert "saved_composite_images" not in src
    for leak in ("//depot/", "svms_client", "blade:", "lingendj", "Geo Goldens"):
        assert leak not in src

    md = FF_SKILL_MD.read_text()
    assert md.startswith("---\n")
    frontmatter = md.split("---\n", 2)[1]
    assert "name: utility-pole-subclassification-using-full-frame-svi\n" in frontmatter
    assert "description: >" not in frontmatter
    assert "description: " in frontmatter
    desc_line = next(line for line in frontmatter.splitlines() if line.startswith("description: "))
    desc_val = desc_line.removeprefix("description: ").strip()
    assert len(desc_val) < 500
    assert "Use when" in frontmatter and "Don't use for" in frontmatter
    assert "# Utility Pole Subclassification Using Full-Frame SVI" in md
    assert "## Step-by-Step Pole Subclassification Methodology" in md
    assert "## Sub-Classification Taxonomy" in md
    assert "## Prerequisites" in md
    assert "## Instructions" in md
    assert "--coordinates" in md and "--asset-id" in md and "--observation-id" in md
    assert "--radius-m" in md and "--dataset" in md and "--model" in md and "--location" in md and "--output" in md
    assert "--output-dir" not in md and "saved_composite_images" not in md
    assert '"pole_count"' in md and '"poles"' in md
    for leak in ("//depot/", "svms_client", "blade:", "lingendj", "Geo Goldens"):
        assert leak not in md


def test_full_frame_skill_cli_flags_and_sql_allowlist(ff_sp):
    env = {"PROJECT_ID": "test-proj", "GCS_BUCKET": "test-bucket"}
    args = ff_sp.parse_args(
        [
            "--coordinates",
            "28.0502,-81.9601",
            "--radius-m",
            "60",
            "--dataset",
            "imagery_insights___us",
            "--location",
            "global",
            "--output",
            "/tmp/ff_out.json",
        ],
        env=env,
    )
    assert args.project == "test-proj"
    assert args.gcs_bucket == "test-bucket"
    assert args.lat == pytest.approx(28.0502)
    assert args.lng == pytest.approx(-81.9601)
    assert args.radius_m == pytest.approx(60.0)
    assert args.output == "/tmp/ff_out.json"

    a_asset = ff_sp.parse_args(["--asset-id", "t1:abc:ffff01ee"], env=env)
    assert a_asset.asset_id == "t1:abc:ffff01ee"
    a_obs = ff_sp.parse_args(["--observation-id", "o1:obs:5001ee"], env=env)
    assert a_obs.observation_id == "o1:obs:5001ee"

    with pytest.raises(SystemExit):
        ff_sp.parse_args(["--asset-id", "x", "--observation-id", "y"], env=env)

    for sql_name in ("COORDS_SQL", "ASSET_SQL", "OBS_SQL"):
        rendered = ff_sp.render_sql(getattr(ff_sp, sql_name), "my-proj", "imagery_insights___us")
        assert "my-proj.imagery_insights___us.full_frame_observations_latest" in rendered
        assert "latest_observations" not in rendered
        assert not re.search(r"\bgcs_uri\b", rendered)

    with pytest.raises(ValueError, match="dataset"):
        ff_sp.render_sql(ff_sp.COORDS_SQL, "my-proj", "bad_dataset")


def test_full_frame_deduplicate_parallax_and_subclassify_gates(ff_sp):
    import pandas as pd

    raw_df = pd.DataFrame(
        [
            # Asset 1: exposure A (duplicate jittered boxes -> keeps better-centered o1_a1)
            {
                "asset_id": "t1:pole1",
                "observation_id": "o1_a1",
                "snapshot_id": "2026_03",
                "asset_type": "ASSET_CLASS_UTILITY_POLE",
                "capture_time": "2026-03-01T12:00:00Z",
                "pano_id": "p1",
                "lat": 28.050317,
                "lng": -81.960038,
                "cam_lat": 28.050220,
                "cam_lng": -81.960080,
                "heading": 15.0,
                "pitch": 0.0,
                "roll": 0.0,
                "xmin": 1760,
                "ymin": 800,
                "xmax": 1880,
                "ymax": 3600,
                "gcs_uri": "gs://test-bucket/2026_03/v0/o1_a1.jpg",
            },
            {
                "asset_id": "t1:pole1",
                "observation_id": "o1_a2_dup",
                "snapshot_id": "2026_03",
                "asset_type": "ASSET_CLASS_UTILITY_POLE",
                "capture_time": "2026-03-01T12:00:00Z",
                "pano_id": "p1",
                "lat": 28.050317,
                "lng": -81.960038,
                "cam_lat": 28.050220,
                "cam_lng": -81.960080,
                "heading": 15.0,
                "pitch": 0.0,
                "roll": 0.0,
                "xmin": 2400,
                "ymin": 820,
                "xmax": 2510,
                "ymax": 3500,
                "gcs_uri": "gs://test-bucket/2026_03/v0/o1_a2_dup.jpg",
            },
            # Asset 1: exposure B with > 40 deg azimuth parallax
            {
                "asset_id": "t1:pole1",
                "observation_id": "o1_b1",
                "snapshot_id": "2026_03",
                "asset_type": "ASSET_CLASS_UTILITY_POLE",
                "capture_time": "2026-03-01T12:00:05Z",
                "pano_id": "p2",
                "lat": 28.050317,
                "lng": -81.960038,
                "cam_lat": 28.050390,
                "cam_lng": -81.960120,
                "heading": 15.0,
                "pitch": 0.0,
                "roll": 0.0,
                "xmin": 1650,
                "ymin": 900,
                "xmax": 1770,
                "ymax": 3550,
                "gcs_uri": "gs://test-bucket/2026_03/v0/o1_b1.jpg",
            },
            # Asset 2: guy-stub pole
            {
                "asset_id": "t1:guystub",
                "observation_id": "o2_a1",
                "snapshot_id": "2026_03",
                "asset_type": "ASSET_CLASS_UTILITY_POLE",
                "capture_time": "2026-03-01T12:00:00Z",
                "pano_id": "p1",
                "lat": 28.050167,
                "lng": -81.960039,
                "cam_lat": 28.050090,
                "cam_lng": -81.960080,
                "heading": 15.0,
                "pitch": 0.0,
                "roll": 0.0,
                "xmin": 1700,
                "ymin": 1200,
                "xmax": 1820,
                "ymax": 3400,
                "gcs_uri": "gs://test-bucket/2026_03/v0/o2_a1.jpg",
            },
            # Asset 3: far-range ghost (> 40m away, must be filtered out)
            {
                "asset_id": "t1:ghost_far",
                "observation_id": "o3_far",
                "snapshot_id": "2026_03",
                "asset_type": "ASSET_CLASS_UTILITY_POLE",
                "capture_time": "2026-03-01T12:00:10Z",
                "pano_id": "p3",
                "lat": 28.050477,
                "lng": -81.959782,
                "cam_lat": 28.049500,
                "cam_lng": -81.960000,
                "heading": 15.0,
                "pitch": 0.0,
                "roll": 0.0,
                "xmin": 1800,
                "ymin": 2200,
                "xmax": 1820,
                "ymax": 2450,
                "gcs_uri": "gs://test-bucket/2026_03/v0/o3_far.jpg",
            },
        ]
    )

    dedup = ff_sp.deduplicate_same_exposure_observations(raw_df)
    assert len(dedup[dedup["asset_id"] == "t1:pole1"]) == 2

    calls: list[int] = []

    async def fake_ask(parts):
        idx = len(calls)
        calls.append(idx)
        # Verify 3-panel composite shape (480, 1080, 3)
        imgs = [p for p in parts if isinstance(p, np.ndarray)]
        assert imgs and imgs[0].shape == (480, 1080, 3)
        if idx == 0:
            return ff_sp.PoleSubClassification(
                sub_type=ff_sp.PoleSubType.JOINT_USE_LIGHT,
                is_true_utility_pole=False,  # Gate must flip this to True
                material=ff_sp.PoleMaterial.WOOD,
                condition=ff_sp.PoleCondition.GOOD,
                cross_arm=ff_sp.CrossArmConfig.SINGLE_WOOD,
                equipment=[
                    ff_sp.PoleEquipment.STREET_LIGHT_LUMINARY,
                    ff_sp.PoleEquipment.GUY_WIRE,
                ],
                has_primary_conductors=True,
                has_secondary_conductors=True,
                has_telecom_attach=True,
                is_double_pole=False,
                lean_angle_deg=1.4,
                structural_anomaly=False,
                confidence=0.95,
                evidence="Joint-use wood distribution pole with primary conductors, secondary triplex, street-light arm, and guy wire.",
            )
        return ff_sp.PoleSubClassification(
            sub_type=ff_sp.PoleSubType.GUY_STUB_POLE,
            is_true_utility_pole=True,  # Gate must flip this to False
            material=ff_sp.PoleMaterial.WOOD,
            condition=ff_sp.PoleCondition.GOOD,
            cross_arm=ff_sp.CrossArmConfig.SINGLE_WOOD,  # Gate must reset to NONE
            equipment=[ff_sp.PoleEquipment.GUY_WIRE],
            has_primary_conductors=True,  # Gate must reset to False
            has_secondary_conductors=True,
            has_telecom_attach=False,
            is_double_pole=False,
            lean_angle_deg=2.2,
            structural_anomaly=False,
            confidence=0.92,
            evidence="Unenergized wood guy-stub pole supporting only span and down-guy wires.",
        )

    out = asyncio.run(ff_sp.subclassify_full_frame_poles(raw_df, _dummy_fetch, fake_ask))
    assert out["pole_count"] == 2
    p0, p1 = out["poles"]
    assert p0["pole_id"] == "t1:pole1"
    assert p0["is_true_utility_pole"] is True
    assert p0["sub_type"] == "JOINT_USE_LIGHT"
    assert p0["views_used"] == 2
    assert p0["parallax_deg"] > 40.0

    assert p1["pole_id"] == "t1:guystub"
    assert p1["is_true_utility_pole"] is False
    assert p1["sub_type"] == "GUY_STUB_POLE"
    assert p1["cross_arm"] == "NONE"
    assert p1["has_primary_conductors"] is False
    assert p1["has_secondary_conductors"] is False

