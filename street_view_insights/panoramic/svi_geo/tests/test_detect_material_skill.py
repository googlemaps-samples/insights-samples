"""T10: static + pure-function tests for the surface-material skill script (no network)."""

import dataclasses
import importlib.util
import re
import sys
from pathlib import Path

import numpy as np
import pytest

from svi_geo import data, schemas

SKILL = (
    Path(__file__).resolve().parents[2]
    / "skills/surface_material_detection_using_panoramic_svi/scripts/detect_material.py"
)


@pytest.fixture(scope="module")
def dm():
    spec = importlib.util.spec_from_file_location("detect_material", SKILL)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["detect_material"] = mod  # pydantic resolves postponed annotations here
    spec.loader.exec_module(mod)
    yield mod
    sys.modules.pop("detect_material", None)


def test_enums_match_the_shared_taxonomy_and_include_turf(dm):
    assert [e.value for e in dm.SurfaceMaterial] == [e.value for e in schemas.SurfaceMaterial]
    assert [e.value for e in dm.SurfaceCondition] == [e.value for e in schemas.SurfaceCondition]
    assert "Turf" in {e.value for e in dm.SurfaceMaterial}
    assert (
        dm.SurfaceMaterialResult.model_json_schema()
        == schemas.SurfaceMaterialResult.model_json_schema()
    )


def test_no_uri_parts_and_numeric_confidence(dm):
    src = SKILL.read_text()
    assert "from_uri" not in src and "file_uri" not in src
    assert "response_schema" in src
    assert dm.SurfaceMaterialResult.model_fields["confidence"].annotation is float


def test_sql_is_parameterised_pano_latest_only_without_gcs_uri(dm):
    for name in ("COORDS_SQL", "ID_SQL"):
        sql = dm.render_sql(getattr(dm, name), "my-proj", "imagery_insights___us")
        assert "{" not in getattr(dm, name) and "{" not in sql
        assert not re.search(r"\bgcs_uri\b", sql)
        tables = data.referenced_tables(sql)
        assert tables == {"my-proj.imagery_insights___us.pano_observations_latest"}
        assert "pano_id IS NOT NULL" in sql
    assert "@radius_m" in dm.COORDS_SQL and "ST_DWITHIN" in dm.COORDS_SQL
    assert "ORDER BY ST_DISTANCE" not in dm.COORDS_SQL.split("WHERE")[0]


def test_render_sql_rejects_injection(dm):
    with pytest.raises(ValueError):
        dm.render_sql(dm.COORDS_SQL, "proj`; DROP TABLE x; --", "ds")


def test_front_camera_follows_travel_direction(dm):
    frames = [{"cam_k": k, "heading": (100.0 + 60 * k) % 360} for k in range(7)]
    assert dm.pick_front_camera(frames, travel_deg=225.0)["cam_k"] == 2  # heading 220
    with pytest.raises(ValueError, match="travel"):
        dm.pick_front_camera(frames, travel_deg=None)  # no silent camera-0 fallback


def test_gcs_uri_is_derived_not_selected(dm):
    assert dm.gcs_uri_for("b", "snap", "o1:p_0:5001ee") == "gs://b/snap/v0/o1:p_0:5001ee.jpg"


def test_no_gcs_uri_select_and_no_bucket_discovery():
    src = SKILL.read_text()
    assert not re.search(r"SELECT\s+gcs_uri", src, re.I)
    assert "discover_bucket" not in src
    md = SKILL.parents[1].joinpath("SKILL.md").read_text()
    assert "discover" not in md.lower() and "bucket.json" not in md


def test_gcs_bucket_is_required_unless_image(dm):
    env = {"PROJECT_ID": "p"}
    with pytest.raises(SystemExit):
        dm.parse_args(["--coordinates", "1,2"], env=env)
    a = dm.parse_args(["--coordinates", "1,2", "--gcs-bucket", "gs://b/"], env=env)
    assert a.gcs_bucket == "b"
    a = dm.parse_args(["--coordinates", "1,2"], env={**env, "GCS_BUCKET": "eb"})
    assert a.gcs_bucket == "eb"
    a = dm.parse_args(["--image", "x.jpg"], env=env)
    assert a.image == "x.jpg"


def test_project_defaults_from_project_id_then_google_cloud_project(dm):
    args = ["--image", "x.jpg"]
    assert dm.parse_args(args, env={"PROJECT_ID": "a", "GOOGLE_CLOUD_PROJECT": "b"}).project == "a"
    assert dm.parse_args(args, env={"GOOGLE_CLOUD_PROJECT": "b"}).project == "b"
    assert dm.parse_args([*args, "--project", "c"], env={"PROJECT_ID": "a"}).project == "c"
    with pytest.raises(SystemExit):
        dm.parse_args(args, env={})


def test_road_crop_is_deterministic_code(dm):
    img = np.full((5472, 3648, 3), 40, np.uint8)  # non-zero everywhere: black = off-lens
    img[3000:, :] = 200
    out = dm.road_view(img)
    assert out.shape[0] <= 1536 and out.shape[1] <= 1536
    assert out.mean() > 100  # lower (road) part of the frame
    assert (out.max(axis=2) > 0).mean() > 0.9  # the view stays inside the lens FOV


# ----------------------------------------------------------------------------- Task 9

from svi_geo import rosette  # noqa: E402

INTR = rosette.load_intrinsics()


def test_road_view_uses_the_real_pose_camera_delta_and_world_pitch(dm):
    pose = {"heading": 130.0, "pitch": 1.5, "roll": -0.8}
    k = 2
    view = dm.road_view_spec(pose, k, INTR)
    assert view.yaw_deg == pytest.approx(130.0 + INTR.cam_rot_delta_deg.get(k, (0.0,))[0])
    assert view.pitch_deg == dm.ROAD_PITCH_DEG  # world-relative (PerspectiveView is world)
    img = np.full((5472 // 4, 3648 // 4, 3), 90, np.uint8)
    img[: img.shape[0] // 2] = 30
    out = dm.road_view(img, pose=pose, cam_k=k)
    ref = rosette.render_perspective(img, INTR, pose, view, k)
    keep = rosette.hood_row(view, pose, INTR, rosette.HOOD_ELEV_DEG, k)
    np.testing.assert_array_equal(out, dm._fit_within(ref[:keep]))
    assert (out.max(axis=2) == 0).mean() < 0.01


def test_road_view_docstring_matches_the_code(dm):
    doc = dm.road_view.__doc__
    assert f"{abs(dm.ROAD_PITCH_DEG):g} deg" in doc
    assert "25 deg" not in doc or dm.ROAD_PITCH_DEG == -25


def test_skill_selects_the_full_pose_and_excludes_capture_id(dm):
    assert "camera_pose.pitch" in dm._FIELDS and "camera_pose.roll" in dm._FIELDS
    assert "capture_id" not in dm.ID_SQL
    assert "capture_id" not in dm.COORDS_SQL
    md = SKILL.parents[1].joinpath("SKILL.md").read_text()
    assert "capture_id" not in md


# ----------------------------------------------------------------------------- round 2 partial


def test_id_sql_looks_up_the_id_once_and_filters_by_that_location(dm):
    sql = dm.render_sql(dm.ID_SQL, "my-proj", "imagery_insights___us")
    assert "ANY_VALUE(capture_location)" not in sql  # a STRUCT, not a GEOGRAPHY: it failed
    assert "WITH hit AS" in sql and "LIMIT 1" in sql
    assert "ST_GEOGPOINT(hit.lng, hit.lat)" in sql and "@radius_m" in sql
    assert "@id" in sql and not re.search(r"\bgcs_uri\b", sql)
    assert "capture_id" not in sql
    assert "observation_id = @id OR pano_id = @id" in sql


def test_render_sql_validates_dataset_allowlist(dm):
    with pytest.raises(ValueError, match="dataset"):
        dm.render_sql(dm.COORDS_SQL, "my-proj", "not_allowed_dataset")


def test_pano_id_and_observation_id_are_separate_or_aliased_flags(dm):
    env = {"PROJECT_ID": "p", "GCS_BUCKET": "b"}
    a1 = dm.parse_args(["--observation-id", "o1:abc_0:5001ee"], env=env)
    assert a1.observation_id == "o1:abc_0:5001ee"
    a2 = dm.parse_args(["--pano-id", "pano123"], env=env)
    assert a2.pano_id == "pano123"
    with pytest.raises(SystemExit):
        dm.parse_args(["--observation-id", "x", "--pano-id", "y"], env=env)


@pytest.mark.live
def test_id_sql_dry_run_under_145gb(dm):
    import os

    from google.cloud import bigquery

    project = os.environ.get("PROJECT_ID") or "imagery-insights-sandbox"
    client = bigquery.Client(project=project)
    sql = dm.render_sql(dm.ID_SQL, project, dm.DEFAULT_DATASET)
    params = [
        bigquery.ScalarQueryParameter("id", "STRING", "o1:test_0:5001ee"),
        bigquery.ScalarQueryParameter("radius_m", "FLOAT64", 30.0),
    ]
    dry = client.query(
        sql, job_config=bigquery.QueryJobConfig(dry_run=True, query_parameters=params)
    )
    gb = dry.total_bytes_processed / 1e9
    assert gb <= 1.45, f"expected ID_SQL dry run <= 1.45 GB, got {gb:.3f} GB"


def _rosette_rows(heading0):
    rows = []
    for k in range(7):
        pose = {"heading": (heading0 + 60.0 * k) % 360, "pitch": 90.0 if k == 6 else 0.0,
                "roll": 0.0}  # fmt: skip
        rows.append({"observation_id": f"o1:PANO_{k}:5001ee", "cam_k": k, "camera_pose": pose,
                     "snapshot_id": "s"})  # fmt: skip
    return rows


def test_road_view_is_centred_on_travel_and_composited_on_the_seam(dm):
    travel = 80.0
    rv = dm.plan_road_view(_rosette_rows(travel + 30.0), travel)  # cameras at travel +-30
    assert rv.view.yaw_deg == pytest.approx(travel)
    assert len(rv.rows) == 2 and rv.black_sent < 0.01
    single = dm.plan_road_view(_rosette_rows(travel), travel)
    assert single.view.yaw_deg == pytest.approx(travel) and len(single.rows) == 1


def test_black_border_check_rejects_views_past_the_sensor(dm):
    rv = dm.plan_road_view(_rosette_rows(110.0), 80.0)
    dm.check_black(rv)  # passes
    with pytest.raises(ValueError, match="black"):
        dm.check_black(dataclasses.replace(rv, black_sent=0.05))


def test_travel_direction_is_required_not_guessed(dm):
    with pytest.raises(ValueError, match="--travel-deg"):
        dm.resolve_travel(None, None)
    assert dm.resolve_travel(None, 12.5) == 12.5
    assert dm.resolve_travel(40.0, None) == 40.0
    a = dm.parse_args(["--coordinates", "1,2", "--travel-deg", "90"],
                      env={"PROJECT_ID": "p", "GCS_BUCKET": "b"})  # fmt: skip
    assert a.travel_deg == 90.0


def test_cost_line_reports_tokens_and_usd(dm):
    usage = {"prompt_token_count": 1000, "candidates_token_count": 200, "thoughts_token_count": 50}
    line = dm.cost_line(usage, "gemini-3.5-flash")
    assert "calls=1" in line and "input_tokens=1,000" in line and "output_tokens=250" in line
    assert "$" in line


def test_frame_rows_carry_the_real_pose_of_each_ground_frame(dm):
    import datetime as dt

    t = dt.datetime(2024, 1, 1)
    rows = [
        {"pano_id": "P", "observation_id": f"o1:P_{k}:5001ee", "snapshot_id": "s",
         "capture_time": t, "lat": 1.0, "lng": 2.0, "heading": 10.0 * k,
         "pitch": None if k == 0 else 1.5, "roll": None}
        for k in range(7)
    ] + [{"pano_id": "Q", "observation_id": "o1:Q_0:5001ee", "snapshot_id": "s",
          "capture_time": t, "lat": 1.0, "lng": 2.0, "heading": 0.0, "pitch": 0.0,
          "roll": 0.0}]  # fmt: skip
    frames = dm.frame_rows(rows, "P")
    assert [f["cam_k"] for f in frames] == list(range(7))
    assert frames[0]["camera_pose"] == {"heading": 0.0, "pitch": 0.0, "roll": 0.0,
                                        "latitude": 1.0, "longitude": 2.0}  # fmt: skip
    assert frames[3]["camera_pose"]["heading"] == 30.0
    assert frames[3]["camera_pose"]["pitch"] == 1.5


def test_skill_doc_describes_the_travel_centred_view_not_a_camera_fallback(dm):
    md = SKILL.parents[1].joinpath("SKILL.md").read_text()
    assert "camera 0 is the fallback" not in md
    assert "--travel-deg" in md
    assert "black" in md and "cost" in md
