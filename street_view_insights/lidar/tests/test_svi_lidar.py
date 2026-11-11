# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Offline unit, CLI smoke, and zero-leak hygiene tests for `svi_lidar`."""

from __future__ import annotations

import io
import json
from pathlib import Path
import re
import subprocess
import sys

import laspy
import numpy as np
import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

from svi_lidar import (
    FOCAL_LENGTH_PX,
    IMAGE_HEIGHT,
    IMAGE_WIDTH,
    PRINCIPAL_X,
    PRINCIPAL_Y,
    analyze_building_and_driveway_scene,
    build_depth_gated_crop,
    build_observation_lidar_sql,
    build_pano_rosette_lidar_sql,
    cast_2d_box_to_3d_cluster,
    classify_depth_gated_crop_with_gemini,
    colorize_multiview_point_cloud,
    colorize_points_zbuffer,
    deduplicate_enu_voxels,
    discover_roadside_assets_3d,
    ecef_to_enu,
    enu_to_camera,
    enu_to_ecef,
    estimate_local_ground_z,
    export_colored_ply,
    filter_front_surface_overlay,
    infer_lidar_mode,
    lla_to_ecef,
    measure_corridor_cross_section,
    measure_facade_3d,
    measure_point_to_point_3d,
    measure_pole_3d,
    measure_sign_3d,
    measure_tree_3d,
    parse_pano_observation_id,
    project_cam_to_uv,
    project_points_to_image,
    select_pano_rosette_laz_and_cameras,
    select_same_pass_laz_rows,
    stream_laz_from_gcs,
)
from svi_lidar.synthetic_scene import make_synthetic_street_scene


def test_ecef_enu_roundtrip_millimeter_precision() -> None:
    lat, lon, alt = 40.7608, -111.8910, 1305.2
    enu_in = np.array(
        [[0.0, 0.0, 0.0], [12.345, -8.765, 4.321], [-25.001, 41.999, -2.450]],
        dtype=np.float64,
    )
    ecef = enu_to_ecef(enu_in, lat, lon, alt)
    enu_out = ecef_to_enu(ecef, lat, lon, alt, dtype=np.float64)
    np.testing.assert_allclose(enu_out, enu_in, atol=1e-4)

    origin_ecef = lla_to_ecef(lat, lon, alt)
    np.testing.assert_allclose(ecef[0], origin_ecef, atol=1e-5)


def test_camera_frame_and_fisheye_optical_center() -> None:
    # A point directly due North at camera height projects onto (cx, cy) when heading=0, pitch=0.
    pts_enu = np.array([[0.0, 15.0, 0.0]], dtype=np.float64)
    pts_cam = enu_to_camera(pts_enu, heading_deg=0.0, pitch_deg=0.0, roll_deg=0.0)
    np.testing.assert_allclose(pts_cam[0], [0.0, 15.0, 0.0], atol=1e-6)

    u, v = project_cam_to_uv(0.0, 0.0)
    assert u == pytest.approx(PRINCIPAL_X)
    assert v == pytest.approx(PRINCIPAL_Y)
    assert FOCAL_LENGTH_PX == pytest.approx(2964.42)


def test_voxel_dedup_keeps_highest_intensity_hit() -> None:
    pts = np.array(
        [[1.001, 2.001, 0.501], [1.004, 2.003, 0.504], [5.0, 5.0, 1.0]],
        dtype=np.float32,
    )
    inten = np.array([25, 1850, 40], dtype=np.uint16)
    dedup = deduplicate_enu_voxels(pts, intensity=inten, voxel_size_m=0.02)
    assert len(dedup["enu"]) == 2
    assert 1850 in dedup["intensity"].tolist()


def test_rig_selection_2_sensor_vs_4_sensor_and_sql_hygiene() -> None:
    sql = build_observation_lidar_sql("demo-gcp-project")
    assert "full_frame_observations_latest" in sql
    assert "full_frame_lidar_metadata_latest" in sql
    assert "NOT IS_NAN(centroid_lat)" in sql
    assert "@observation_id" in sql

    with pytest.raises(ValueError):
        build_observation_lidar_sql("YOUR_PROJECT_ID")

    two_sensor = select_same_pass_laz_rows(
        [
            {"device_number": 0, "laz_gcs_uri": "gs://b/0.laz", "laz_start_gps_sec": 1000},
            {"device_number": 1, "laz_gcs_uri": "gs://b/1.laz", "laz_start_gps_sec": 1000},
            # Duplicate row from second asset in same photo:
            {"device_number": 0, "laz_gcs_uri": "gs://b/0.laz", "laz_start_gps_sec": 1000},
        ],
        neighbor_rows=[
            {"laz_gcs_uri": "gs://b/near.laz", "laz_start_gps_sec": 1005},
            {"laz_gcs_uri": "gs://b/other_year.laz", "laz_start_gps_sec": 999999},
        ],
    )
    assert two_sensor["rig_type"] == "2-sensor"
    assert two_sensor["laz_uris"] == ["gs://b/0.laz", "gs://b/1.laz", "gs://b/near.laz"]

    four_sensor = select_same_pass_laz_rows(
        [{"device_number": d, "laz_gcs_uri": f"gs://b/{d}.laz", "laz_start_gps_sec": 2000} for d in range(4)],
        neighbor_rows=[{"laz_gcs_uri": "gs://b/too_far_5s.laz", "laz_start_gps_sec": 2005}],
    )
    assert four_sensor["rig_type"] == "4-sensor"
    assert len(four_sensor["laz_uris"]) == 4


def test_in_memory_laz_streaming_with_mock_storage_client() -> None:
    header = laspy.LasHeader(point_format=1, version="1.4")
    header.scales = np.array([0.001, 0.001, 0.001])
    header.offsets = np.array([-1800000.0, -4400000.0, 4100000.0])
    las = laspy.LasData(header)
    las.x = np.array([-1799995.123, -1799990.456])
    las.y = np.array([-4399998.001, -4399992.500])
    las.z = np.array([4100002.250, 4100008.750])
    las.intensity = np.array([34, 2400], dtype=np.uint16)
    las.gps_time = np.array([1400000000.0, 1400000000.5])

    buf = io.BytesIO()
    las.write(buf)
    payload = buf.getvalue()

    class _FakeBlob:
        def download_as_bytes(self) -> bytes:
            return payload

    class _FakeBucket:
        def blob(self, _path: str) -> _FakeBlob:
            return _FakeBlob()

    class _FakeClient:
        def bucket(self, _name: str) -> _FakeBucket:
            return _FakeBucket()

    out = stream_laz_from_gcs("gs://example-bucket/scan_0.laz", storage_client=_FakeClient())
    assert out["ecef"].shape == (2, 3)
    assert out["intensity"].tolist() == [34, 2400]
    np.testing.assert_allclose(out["ecef"][0, 0], -1799995.123, atol=1e-3)


def test_zbuffer_rgb_prevents_foreground_color_bleeding_and_exports_ply(tmp_path: Path) -> None:
    pose = {"latitude": 40.76, "longitude": -111.89, "altitude": 1300.0, "heading": 0.0, "pitch": 0.0, "roll": 0.0}
    # Foreground point at y=6 m and occluded background wall point directly behind it at y=18 m along optical axis.
    pts_enu = np.array([[0.0, 6.0, 0.0], [0.0, 18.0, 0.0]], dtype=np.float32)
    img_rgb = np.full((IMAGE_HEIGHT // 4, IMAGE_WIDTH // 4, 3), (220, 30, 30), dtype=np.uint8)

    colors, vis = colorize_points_zbuffer(
        points=pts_enu,
        img_rgb=img_rgb,
        camera_pose=pose,
        is_enu=True,
        full_res_wh=(IMAGE_WIDTH, IMAGE_HEIGHT),
    )
    assert bool(vis[0]) is True
    assert bool(vis[1]) is False, "Occluded wall point behind foreground object must not inherit foreground RGB!"
    assert colors[0].tolist() == [220, 30, 30]
    assert colors[1].tolist() == [0, 0, 0]

    # Second camera stop past the obstacle at y=10 m sees the y=18 m point cleanly in green!
    pose_stop2 = {
        "latitude": 40.76 + (10.0 / 111111.0),
        "longitude": -111.89,
        "altitude": 1300.0,
        "heading": 0.0,
        "pitch": 0.0,
        "roll": 0.0,
    }
    img_green = np.full_like(img_rgb, (30, 200, 60))
    fused = colorize_multiview_point_cloud(
        points=pts_enu,
        camera_views=[
            {"img_rgb": img_rgb, "camera_pose": pose},
            {"img_rgb": img_green, "camera_pose": pose_stop2},
        ],
        is_enu=True,
        anchor_pose=pose,
        full_res_wh=(IMAGE_WIDTH, IMAGE_HEIGHT),
    )
    assert fused["colored_mask"].tolist() == [True, True]
    assert fused["colors_rgb"][0].tolist() == [220, 30, 30]
    assert fused["colors_rgb"][1].tolist() == [30, 200, 60]

    ply_path = export_colored_ply(tmp_path / "cloud.ply", pts_enu, fused["colors_rgb"])
    assert ply_path.exists() and ply_path.stat().st_size > 80


def test_pure_3d_measurements_and_corridor_cross_sections() -> None:
    scene = make_synthetic_street_scene()
    pts_enu = scene["pts_enu"]
    intensity = scene["intensity"]
    ranges = scene["label_ranges"]

    # Add subterranean multipath glare (-22 m) to confirm `estimate_local_ground_z` strips it.
    glare = np.array([[0.0, 10.0, -22.5], [0.5, 11.0, -19.0]], dtype=np.float32)
    z_ground, _ = estimate_local_ground_z(np.vstack([pts_enu, glare]), center_xy=(0.0, 12.0))
    assert z_ground == pytest.approx(-2.50, abs=0.12)

    p_lo, _ = ranges["pole"]
    _, w_hi = ranges["wire"]
    pole = measure_pole_3d(pts_enu[p_lo:w_hi], z_ground_m=z_ground)
    assert pole["valid"] is True
    assert pole["height_m"] == pytest.approx(10.45, abs=0.30)  # Excludes 12.4 m wire!
    assert pole["lean_deg"] == pytest.approx(3.5, abs=1.2)

    sp_lo, _ = ranges["sign_post"]
    _, sf_hi = ranges["sign_face"]
    sign = measure_sign_3d(pts_enu[sp_lo:sf_hi], intensity[sp_lo:sf_hi], z_ground_m=z_ground)
    assert sign["valid"] is True
    assert sign["width_m"] == pytest.approx(0.72, abs=0.10)
    assert sign["height_m"] == pytest.approx(0.86, abs=0.12)
    assert sign["retro_p90_intensity"] >= 900.0

    tt_lo, _ = ranges["tree_trunk"]
    _, tc_hi = ranges["tree_canopy"]
    tree = measure_tree_3d(pts_enu[tt_lo:tc_hi], z_ground_m=z_ground)
    assert tree["valid"] is True
    assert tree["height_m"] == pytest.approx(9.1, abs=0.4)
    assert tree["crown_width_m"] == pytest.approx(5.0, abs=0.6)

    bf_lo, bf_hi = ranges["building_facade"]
    facade = measure_facade_3d(pts_enu[bf_lo:bf_hi], z_ground_m=z_ground)
    assert facade["valid"] is True
    assert facade["wall_height_m"] == pytest.approx(7.65, abs=0.35)
    assert facade["flatness_rms_cm"] < 3.5

    # Cross-section at y = 8.0 m (outside driveway): ~8.0 m road, ~14 cm curb reveal, ~1.75 m sidewalk!
    cs = measure_corridor_cross_section(pts_enu, intensity, heading_deg=0.0, station_along_m=8.0)
    assert cs["valid"] is True
    assert cs["roadway_width_m"] == pytest.approx(8.1, abs=0.5)
    assert cs["right_side"]["curb_reveal_cm"] == pytest.approx(15.0, abs=5.0)
    assert cs["right_side"]["sidewalk_width_m"] == pytest.approx(1.75, abs=0.35)

    d3 = measure_point_to_point_3d([0.0, 0.0, 0.0], [3.0, 4.0, 12.0])
    assert d3["distance_3d_m"] == pytest.approx(13.0)


def test_multimodal_fusion_and_building_driveway_scene() -> None:
    scene = make_synthetic_street_scene()
    pts_enu = scene["pts_enu"]
    intensity = scene["intensity"]
    pose = scene["camera_pose"]
    img_rgb = scene["img_rgb"]
    img_h, img_w = img_rgb.shape[:2]

    overlay = filter_front_surface_overlay(
        pts_enu, heading_deg=pose["heading"], pitch_deg=pose["pitch"], roll_deg=pose["roll"]
    )
    assert 50 < len(overlay["keep_indices"]) <= len(pts_enu)

    t_lo, _ = scene["label_ranges"]["tree_trunk"]
    _, t_hi = scene["label_ranges"]["tree_canopy"]
    gated = build_depth_gated_crop(
        img_rgb=img_rgb,
        pts_enu=pts_enu,
        cluster_indices=np.arange(t_lo, t_hi),
        camera_pose=pose,
        full_res_wh=(img_w, img_h),
    )
    assert gated["valid"] is True
    assert gated["background_eliminated_fraction"] > 0.25

    class _FakeUsage:
        prompt_token_count = 310
        candidates_token_count = 42

    class _FakeResp:
        text = json.dumps(
            {
                "confirmed": True,
                "detected_label": "street_tree",
                "material": "deciduous_foliage",
                "condition": "healthy",
                "summary": "Healthy mature street tree.",
            }
        )
        usage_metadata = _FakeUsage()

    class _FakeModels:
        def generate_content(self, **_kwargs):
            return _FakeResp()

    class _FakeGenAI:
        models = _FakeModels()

    gem_out = classify_depth_gated_crop_with_gemini(
        gated["crop_rgb"], asset_class="street_tree", genai_client=_FakeGenAI()
    )
    assert gem_out["result"]["confirmed"] is True
    assert gem_out["prompt_tokens"] == 310

    s_lo, s_hi = scene["label_ranges"]["sign_face"]
    proj = project_points_to_image(
        pts_enu[s_lo:s_hi], pose["heading"], pose["pitch"], pose["roll"], image_wh=(img_w, img_h)
    )
    box_norm = [
        float(proj["v"].min() / img_h * 1000.0 - 10.0),
        float(proj["u"].min() / img_w * 1000.0 - 10.0),
        float(proj["v"].max() / img_h * 1000.0 + 10.0),
        float(proj["u"].max() / img_w * 1000.0 + 10.0),
    ]
    cast = cast_2d_box_to_3d_cluster(
        box_norm, pts_enu, intensity, pose, z_ground_m=scene["z_road_m"], image_wh=(img_w, img_h)
    )
    assert cast["valid"] is True
    assert cast["intensity_p90"] >= 900.0

    bldg = analyze_building_and_driveway_scene(pts_enu, intensity, heading_deg=pose["heading"])
    assert bldg["valid"] is True
    assert bldg["driveway_width_m"] >= 3.5
    assert bldg["vehicle_clearance_verdicts"]["service_van"]["can_pull_in"] is True
    assert bldg["vehicle_clearance_verdicts"]["box_truck"]["can_pull_in"] is True


SKILLS_ROOT = PACKAGE_ROOT / "skills"
LIDAR_SKILLS = [
    ("project_and_colorize_3d_lidar", "project-and-colorize-3d-lidar", "project_and_colorize_lidar.py"),
    ("measure_roadside_assets_3d_lidar", "measure-roadside-assets-3d-lidar", "measure_roadside_assets_3d.py"),
    ("slice_road_curb_and_sidewalk_3d_lidar", "slice-road-curb-and-sidewalk-3d-lidar", "slice_corridor_cross_sections.py"),
    ("fuse_image_and_3d_lidar", "fuse-image-and-3d-lidar", "fuse_image_and_lidar.py"),
    ("analyze_building_and_driveway_clearance_3d_lidar", "analyze-building-and-driveway-clearance-3d-lidar", "analyze_building_and_driveway.py"),
]


def test_pano_rosette_mode_sql_stub_filtering_and_3d_discovery() -> None:
    assert parse_pano_observation_id("o1:abc123_3:5001ee") == ("abc123", 3)
    assert parse_pano_observation_id("o1:ff_obs:0001") == (None, None)
    assert infer_lidar_mode("auto", observation_id="o1:abc123_0:5001ee") == "pano"
    assert infer_lidar_mode("auto", capture_id="t1:cap_1") == "pano"
    assert infer_lidar_mode("auto", observation_id="o1:ff_obs:0001") == "full_frame"

    pano_sql = build_pano_rosette_lidar_sql("demo-gcp-project", lookup_by="capture_id")
    assert "pano_observations_latest" in pano_sql
    assert "pano_lidar_metadata_latest" in pano_sql
    assert "@target_id" in pano_sql

    # Simulate 7-camera rosette where k=0 has a 4-pt stub, k=2/3 have rich 800k-pt sweeps, and k=6 is sky.
    rosette_rows = [
        {
            "observation_id": f"o1:stemA_{k}:5001ee",
            "capture_id": "t1:stemA",
            "pano_id": "panoA",
            "lens_k": k,
            "capture_time": "2026-06-01T00:00:00Z",
            "image_gcs_uri": f"gs://b/cam_{k}.jpg",
            "camera_pose": {"latitude": -37.88, "longitude": 145.15, "altitude": 80.0, "heading": k * 60.0, "pitch": 87.0 if k == 6 else 1.5, "roll": 0.0},
            "device_number": k % 2,
            "laz_gcs_uri": f"gs://b/stub_{k}.laz" if k in (0, 5) else f"gs://b/rich_{k % 2}.laz",
            "count_points": 5 if k in (0, 5) else 850_000,
        }
        for k in range(7)
    ]
    parsed = select_pano_rosette_laz_and_cameras(rosette_rows, requested_observation_id="o1:stemA_0:5001ee")
    assert parsed["mode"] == "pano"
    assert len(parsed["rosette_cameras"]) == 6  # Excludes zenith camera k=6!
    assert all(c["lens_k"] < 6 for c in parsed["rosette_cameras"])
    assert set(parsed["laz_uris"]) == {"gs://b/rich_0.laz", "gs://b/rich_1.laz"}  # Drops <500-pt stubs!

    scene = make_synthetic_street_scene()
    disc = discover_roadside_assets_3d(
        scene["pts_enu"], scene["intensity"], z_ground_m=scene["z_road_m"]
    )
    found_types = {d["asset_type"] for d in disc}
    assert "ASSET_CLASS_ROAD_SIGN" in found_types
    assert "ASSET_CLASS_BUILDING" in found_types


@pytest.mark.parametrize("folder_name,expected_skill_name,script_name", LIDAR_SKILLS)
def test_lidar_skills_frontmatter_and_cli_smoke(
    folder_name: str, expected_skill_name: str, script_name: str
) -> None:
    skill_dir = SKILLS_ROOT / folder_name
    skill_md = skill_dir / "SKILL.md"
    req_txt = skill_dir / "requirements.txt"
    script_path = skill_dir / "scripts" / script_name

    assert skill_md.exists(), f"Missing SKILL.md in {skill_dir}"
    assert req_txt.exists(), f"Missing requirements.txt in {skill_dir}"
    assert script_path.exists(), f"Missing script {script_path}"

    md_text = skill_md.read_text(encoding="utf-8")
    assert md_text.startswith("---\n"), f"Missing YAML frontmatter in {skill_md}"
    assert f"name: {expected_skill_name}\n" in md_text
    assert "description:" in md_text and "Use when" in md_text and "Don't use" in md_text

    proc = subprocess.run(
        [sys.executable, str(script_path), "--synthetic"],
        check=True,
        capture_output=True,
        text=True,
    )
    parsed = json.loads(proc.stdout)
    assert isinstance(parsed, dict) and len(parsed) > 0


def test_public_repo_hygiene_zero_internal_leaks() -> None:
    forbidden_patterns = [
        r"\bHerschel\b",
        r"\bPenrose\b",
        r"\bDustbuster\b",
        r"\bS1C\b",
        r"\bCityblock\b",
        r"\bGeoTracker\b",
        r"\bimagery-insights-sandbox\b",
        r"\bgeoai_published_[A-Za-z0-9_\-]+",
        r"\bgemini-4-[A-Za-z0-9_\-]+",
        r"\bgemini-3\.[78]-[A-Za-z0-9_\-]+",
        r"Gemini\s+[Vv]ision",
        r"\.corp\.google\.com",
        r"\.googlers\.com",
        r"\bAIza[0-9A-Za-z\-_]{20,}",
    ]
    combined = re.compile("|".join(forbidden_patterns))
    for path in PACKAGE_ROOT.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts or path.name == "test_svi_lidar.py":
            continue
        if path.suffix in {".py", ".md", ".toml", ".txt"}:
            text = path.read_text(encoding="utf-8")
            match = combined.search(text)
            assert match is None, f"Forbidden internal/ToS pattern {match.group(0)!r} in {path}"
