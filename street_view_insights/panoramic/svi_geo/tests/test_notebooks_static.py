"""T11: static checks for the panoramic notebooks (no execution, no network)."""

import json
import re
from pathlib import Path

import nbformat
import pytest

from svi_geo import data

NOTEBOOKS = sorted((Path(__file__).resolve().parents[2] / "notebooks").glob("*.ipynb"))
BANNED = ["from_uri", "file_uri", "urls_new", "all_observations", "all_assets", "sleep(15)"]
BANNED_TABLES = re.compile(r"full_frame_observations|cropped_observations", re.I)
FSTRING_SQL = re.compile(
    r"\bf(\"\"\"|'''|\"|')\s*(SELECT|WITH)\b|\bf(\"\"\"|''').*?\bFROM\b", re.I | re.S
)
GCS_URI_SELECT = re.compile(r"SELECT\b[^;]*?\bgcs_uri\b", re.I | re.S)
SQL_BLOCK = re.compile(r"(\"\"\"|''')(\s*(?:SELECT|WITH)\b.*?)\1", re.I | re.S)


def _code(nb) -> str:
    return "\n".join(c.source for c in nb.cells if c.cell_type == "code")


def _all(nb) -> str:
    return "\n".join(c.source for c in nb.cells)


def test_there_are_four_notebooks():
    assert {p.stem for p in NOTEBOOKS} == {
        "agentic_roof_edge_detection",
        "analyze_sequential_images",
        "house_image_discovery_with_cost",
        "surface_material_detection",
    }


@pytest.fixture(params=NOTEBOOKS, ids=lambda p: p.stem)
def nb(request):
    return nbformat.read(request.param, as_version=4)


def test_valid_and_output_free(nb):
    nbformat.validate(nb)
    for c in nb.cells:
        if c.cell_type == "code":
            assert c.outputs == [] and c.execution_count is None


def test_project_placeholder_and_parameters(nb):
    code = _code(nb)
    assert "YOUR_PROJECT_ID" in code
    assert re.search(r"^MAX_GEMINI_CALLS\s*(:\s*[\w| ]+)?=", code, re.M), "MAX_GEMINI_CALLS param"
    assert re.search(r"^MODEL\w*\s*=\s*[\"']gemini-3\.5-flash[\"']", code, re.M)
    assert re.search(r"^GCS_BUCKET\s*=", code, re.M)


def test_banned_patterns_absent(nb):
    text = _all(nb)
    for b in BANNED:
        assert b not in text, b
    assert not BANNED_TABLES.search(text)


def test_sql_is_parameterised_and_pano_only(nb):
    code = _code(nb)
    assert not FSTRING_SQL.search(code), "f-string SQL"
    assert "PANO_META_SQL" in code or "ScalarQueryParameter" in code
    assert not GCS_URI_SELECT.search(code), "select gcs_uri -> use data.gcs_uri_for"
    assert "gcs_uri_for" in code
    for m in SQL_BLOCK.finditer(code):
        tables = data.referenced_tables(m.group(2))
        assert tables <= set(data.ALLOWED_TABLES) | {
            t.replace(data.PROJECT, "YOUR_PROJECT_ID") for t in data.ALLOWED_TABLES
        }, tables


def test_images_are_prepared_in_code_and_costs_reported(nb):
    code = _code(nb)
    assert "rosette." in code or "pipeline." in code, "views must be rendered in code"
    assert "estimate_cost" in code and ".cost.summary()" in code
    assert "GeminiRunner" in code


def test_notebook_json_has_no_secrets():
    for p in NOTEBOOKS:
        raw = p.read_text()
        assert not re.search(r"AIza[0-9A-Za-z_\-]{30,}", raw)
        assert "imagery-insights-sandbox" not in json.dumps(json.loads(raw)["cells"])


def test_install_ref_is_a_single_pinned_parameter(nb):
    code = _code(nb)
    assert len(re.findall(r"^SVI_GEO_REF\s*=", code, re.M)) == 1
    assert "@{SVI_GEO_REF}#subdirectory=street_view_insights/panoramic/svi_geo" in code
    assert 'TODO(after-merge): set to "main"' in code
    assert not re.search(r"^SVI_GEO_REF\s*=\s*[\"']main[\"']", code, re.M)


def test_local_svi_geo_is_found_by_env_or_path_check_not_bare_cwd(nb):
    code = _code(nb)
    assert re.search(r"LOCAL_SVI_GEO\s*=", code)
    assert 'os.path.join("..", "svi_geo")' not in code
    assert "SVI_GEO_LOCAL_PATH" in code
    assert "street_view_insights/panoramic/svi_geo" in code


def test_project_and_bucket_are_explicit_and_validated(nb):
    code = _code(nb)
    assert re.search(
        r'^PROJECT_ID\s*=\s*os\.environ\.get\("PROJECT_ID",\s*"YOUR_PROJECT_ID"\)', code, re.M
    )
    assert re.search(r'^GCS_BUCKET\s*=\s*os\.environ\.get\("GCS_BUCKET",\s*""\)', code, re.M)
    assert "config.resolve_settings(" in code
    assert "GOOGLE_CLOUD_PROJECT" not in code and "default_project" not in code
    assert "discover_bucket" not in _all(nb)


def test_auth_options_are_documented(nb):
    md = "\n".join(c.source for c in nb.cells if c.cell_type == "markdown")
    for s in (
        "authenticate_user",
        "gcloud auth application-default login",
        "SVI_USE_GCLOUD_TOKEN",
        "SVI_ECP_PROXY_URL",
        "roles/",
    ):
        assert s in md, s


GEMINI_CALL = re.compile(r"\b(ask_many|detect_panos|self_consistency)\(")


def test_every_gemini_cell_checks_failures_and_asserts_results(nb):
    cells = [c.source for c in nb.cells if c.cell_type == "code" and GEMINI_CALL.search(c.source)]
    assert cells, "expected at least one Gemini cell"
    for src in cells:
        assert "runner.check(" in src, f"Gemini cell without runner.check():\n{src[:200]}"
        assert re.search(r"\bassert (len|any)\(", src), f"Gemini cell without assert:\n{src[:200]}"


@pytest.mark.parametrize("schema", ["schemas.HouseView", "schemas.RoofEdges"])
def test_uc1_uc4_do_not_use_code_execution(schema):
    """UC1 (HouseView) and UC4 (RoofEdges) use response_schema, not the code tool."""
    books = [nbformat.read(p, as_version=4) for p in NOTEBOOKS]
    matches = [b for b in books if schema in _code(b)]
    assert len(matches) == 1, schema
    text = _all(matches[0])
    assert "code_execution=True" not in text
    assert "code execution" not in text.lower()
