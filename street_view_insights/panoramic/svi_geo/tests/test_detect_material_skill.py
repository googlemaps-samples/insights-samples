"""T10: static + pure-function tests for the surface-material skill script (no network)."""

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
    assert dm.pick_front_camera(frames, travel_deg=None)["cam_k"] == 0


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
