"""Static checks for the panoramic reference notebooks (no execution, no network)."""

import json
import re
from pathlib import Path

import nbformat
import pytest

from svi_geo import data
from svi_geo import gemini_client as gc

NOTEBOOK_DIR = Path(__file__).resolve().parents[2] / "notebooks"
NOTEBOOKS = sorted(NOTEBOOK_DIR.glob("*.ipynb"))
UC_STEMS = {
    "analyze_sequential_images",
    "house_image_discovery_with_cost",
    "roof_edge_tracing",
    "surface_material_detection",
}
UC_NOTEBOOKS = [p for p in NOTEBOOKS if p.stem in UC_STEMS]

BANNED = ["from_uri", "file_uri", "urls_new", "all_observations", "all_assets", "sleep(15)"]
BANNED_TABLES = re.compile(r"full_frame_observations|cropped_observations", re.I)
FSTRING_SQL = re.compile(
    r"\bf(\"\"\"|'''|\"|')\s*(SELECT|WITH)\b|\bf(\"\"\"|''').*?\bFROM\b", re.I | re.S
)
GCS_URI_SELECT = re.compile(r"SELECT\b[^;]*?\bgcs_uri\b", re.I | re.S)
SQL_BLOCK = re.compile(r"(\"\"\"|''')(\s*(?:SELECT|WITH)\b.*?)\1", re.I | re.S)
UUID_LITERAL = re.compile(
    r"[\"'][0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}[\"']", re.I
)
MODEL_LITERAL = re.compile(r"[\"']gemini-\d[\w.\-]*[\"']", re.I)

CONCEPT_ORDER = [
    "concept:sql",
    "concept:geometry",
    "concept:prompt_schema",
    "concept:code_exec",
    "concept:validator",
    "concept:map",
    "concept:cost",
]


def _code(nb) -> str:
    return "\n".join(c.source for c in nb.cells if c.cell_type == "code")


def _md(nb) -> str:
    return "\n".join(c.source for c in nb.cells if c.cell_type == "markdown")


def _all(nb) -> str:
    return "\n".join(c.source for c in nb.cells)


def _cell_concepts(c) -> list[str]:
    tags = list(c.get("metadata", {}).get("tags", []))
    for m in re.finditer(r"^#\s*(concept:[a-z_]+)\b", c.source, re.M):
        if m.group(1) not in tags:
            tags.append(m.group(1))
    return [t for t in tags if t.startswith("concept:")]


def test_there_are_five_notebooks():
    assert {p.stem for p in NOTEBOOKS} == UC_STEMS | {"00_explore_coverage"}


@pytest.fixture(params=NOTEBOOKS, ids=lambda p: p.stem)
def nb(request):
    return nbformat.read(request.param, as_version=4)


@pytest.fixture(params=UC_NOTEBOOKS, ids=lambda p: p.stem)
def uc_nb(request):
    return nbformat.read(request.param, as_version=4)


def test_valid_and_output_free(nb):
    nbformat.validate(nb)
    for c in nb.cells:
        if c.cell_type == "code":
            assert c.outputs == [] and c.execution_count is None


def test_project_placeholder_and_parameters(nb):
    code = _code(nb)
    assert "YOUR_PROJECT_ID" in code
    assert re.search(r"^GCS_BUCKET\s*=", code, re.M)
    assert re.search(r"^INCLUDE_UNPUBLISHED_PANOS\s*=", code, re.M)
    assert re.search(r"^OUT_DIR\s*=", code, re.M)


def test_uc_parameters_and_model_source_of_truth(uc_nb):
    code = _code(uc_nb)
    assert re.search(r"^MAX_GEMINI_CALLS\s*(:\s*[\w| ]+)?=", code, re.M), "MAX_GEMINI_CALLS param"
    assert re.search(r"^MAX_USD\s*(:\s*[\w| ]+)?=", code, re.M), "MAX_USD param"
    assert re.search(r"^MODEL\s*=\s*gc\.DEFAULT_MODEL\b", code, re.M), "MODEL = gc.DEFAULT_MODEL"
    assert re.search(r"^THINKING_LEVEL\s*=", code, re.M)
    assert re.search(r"^MEDIA_RESOLUTION\s*=", code, re.M)
    assert re.search(r"^SEED\s*=", code, re.M)


def test_model_literal_equals_default_model(nb):
    code = _code(nb)
    assert not MODEL_LITERAL.search(code), (
        f"literal model string found in notebook code; use gc.DEFAULT_MODEL ({gc.DEFAULT_MODEL})"
    )


def test_no_snapshot_uuid_literals(nb):
    code = _code(nb)
    for m in UUID_LITERAL.finditer(code):
        assert "geoai_published_" in code[max(0, m.start() - 25) : m.end() + 5], (
            f"hard-coded snapshot UUID in notebook code: {m.group(0)}"
        )
    assert "snapshot_catalog_sql(" in code or "summarize_snapshots(" in code


def test_banned_patterns_absent(nb):
    text = _all(nb)
    for b in BANNED:
        assert b not in text, b
    assert not BANNED_TABLES.search(text)


def test_sql_is_parameterised_and_rosette_keyed(nb):
    code = _code(nb)
    assert not FSTRING_SQL.search(code), "f-string SQL"
    assert "rosette_sql(" in code or "coverage_sql(" in code
    assert "pano_id IS NOT NULL" not in code
    assert not GCS_URI_SELECT.search(code), "select gcs_uri -> use data.gcs_uri_for"
    assert "gcs_uri_for" in code or "frames_from_rosettes" in code
    allowed = set(data.ALLOWED_TABLES) | {
        t.replace(data.PROJECT, "YOUR_PROJECT_ID") for t in data.ALLOWED_TABLES
    }
    for m in SQL_BLOCK.finditer(code):
        tables = data.referenced_tables(m.group(2))
        assert tables <= allowed, tables


def test_images_are_prepared_in_code_and_costs_reported(uc_nb):
    code = _code(uc_nb)
    assert "rosette." in code or "pipeline." in code, "views must be rendered in code"
    assert "estimate_cost" in code and ".cost.summary(" in code
    assert "preview_tokens" in code
    assert "GeminiRunner" in code and "max_usd=" in code


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
    md = _md(nb)
    for s in (
        "authenticate_user",
        "gcloud auth application-default login",
        "SVI_USE_GCLOUD_TOKEN",
        "SVI_ECP_PROXY_URL",
        "roles/",
    ):
        assert s in md, s


def test_notebooks_call_usecases_with_default_variant(uc_nb):
    code = _code(uc_nb)
    assert "VARIANT = usecases.DEFAULT_VARIANT" in code
    assert "VARIANT.describe()" in code
    assert re.search(r"usecases\.uc[1234]_run\([^)]*variant=VARIANT", code, re.S)


def test_no_inline_duplicates_of_usecase_steps(uc_nb):
    code = _code(uc_nb)
    for banned_call in (
        "pipeline.detect_panos(",
        "views.triangulate_house(",
        "UC3_PROMPT_V0",
        "ent.cluster(",
        "sequence.build_sequences(",
    ):
        assert banned_call not in code, f"inline duplicate found: {banned_call}"


def test_each_notebook_has_the_seven_concept_cells_in_order(uc_nb):
    found = []
    for c in uc_nb.cells:
        if c.cell_type == "code":
            found.extend(_cell_concepts(c))
    assert found == CONCEPT_ORDER, f"expected {CONCEPT_ORDER}, got {found}"


def test_cell_count_limit(nb):
    assert len(nb.cells) <= 26, f"cell count {len(nb.cells)} > 26"


def test_banner_states_expected_runtime_and_cost(nb):
    banner = nb.cells[0].source
    assert "Runtime" in banner or "runtime" in banner
    assert "min" in banner and "$" in banner
    assert "peak_rss_mb=" in _code(nb)


def test_markdown_bytes_match_manifest(nb):
    manifest_path = Path(__file__).resolve().parents[1] / "data" / "bytes_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rosette_gb = f"{manifest['templates']['rosette_sql']['dry_run_gb']:.2f} GB"
    coverage_gb = f"{manifest['templates']['coverage_sql']['dry_run_gb']:.2f} GB"
    text = _all(nb)
    for stale in ("1.6 GB", "~1.9 GB", "2.5-pro"):
        assert stale not in text, f"stale literal {stale!r} present"
    md = _md(nb)
    assert "$6.25/TB" in md
    assert rosette_gb in md or coverage_gb in md


def test_code_execution_calls_are_scoped_and_validated():
    """Replaces test_uc1_uc4_do_not_use_code_execution with a stricter agentic-vision contract:
    each UC notebook has exactly one `concept:code_exec` cell where `code_execution=True` passes
    `validator=` and `expect_stdout=`, is followed by `check_code_exec_trace(`, and prints
    `code_exec_agreement=`; `00_explore_coverage` has no code execution and no 'agentic' claim."""
    for p in NOTEBOOKS:
        book = nbformat.read(p, as_version=4)
        ce_cells = [
            c
            for c in book.cells
            if c.cell_type == "code" and "concept:code_exec" in _cell_concepts(c)
        ]
        other_cells = [
            c
            for c in book.cells
            if c.cell_type == "code" and "concept:code_exec" not in _cell_concepts(c)
        ]
        if p.stem == "00_explore_coverage":
            assert len(ce_cells) == 0
            assert "code_execution" not in _code(book)
            assert "agentic" not in _md(book).lower()
            continue

        assert len(ce_cells) == 1, f"{p.stem}: expected 1 concept:code_exec cell"
        src = ce_cells[0].source
        assert "code_execution=True" in src
        assert "validator=" in src and "expect_stdout=" in src
        assert "check_code_exec_trace(" in src
        assert "code_exec_agreement=" in src
        for oc in other_cells:
            assert "code_execution" not in oc.source, (
                f"{p.stem}: code_execution outside concept:code_exec"
            )
        assert "agentic" in _md(book).lower()


def _uc1():
    return nbformat.read(
        next(p for p in NOTEBOOKS if p.stem == "house_image_discovery_with_cost"), as_version=4
    )


def test_uc1_uses_shared_view_geometry_and_triangulated_id():
    code = _code(_uc1())
    assert "usecases.uc1_run(" in code
    assert "views.house_view_candidates" in code and "views.rank_house_views" in code
    assert 'ent.entity_id_for("HOUSE", LAT, LNG)' not in code
    assert "SEARCH_RADIUS_M" not in code
    assert not re.search(r"PerspectiveView\([^)]*\b8\.0\b", code)


def test_uc1_guards_empty_candidates_and_reports_black_fraction():
    code = _code(_uc1())
    assert re.search(r"if\s+\w+\.empty:", code)
    assert "view_black_fraction" in code and "black_fraction_max" in code


def test_uc1_markdown_claims_only_what_runs():
    md = _md(_uc1()).lower()
    for claim in ("deduplication", "smoothing", "lens undistortion"):
        assert claim not in md, claim
    assert "triangulat" in md


def _uc4():
    return nbformat.read(next(p for p in NOTEBOOKS if p.stem == "roof_edge_tracing"), as_version=4)


def test_uc4_colours_edges_by_type_and_draws_rejected_edges():
    code = _code(_uc4())
    assert "EDGE_COLORS[" in code
    assert "rejected_edges" in code
    assert "random_acceptance" in code and "mean_gradient_support" in code
    assert "views.rank_roof_views" in code and "views.occlusion_screen" in code


def test_uc4_guards_empty_views_and_has_no_fixed_pitch_or_long_lines():
    nb = _uc4()
    code = _code(nb)
    assert re.search(r"if not \w*views\b|if \w*views\.empty|if not chosen\b", code)
    assert "pitch_deg=14.0" not in code
    for c in nb.cells:
        for line in c.source.splitlines():
            assert len(line) <= 100, line


def test_uc4_markdown_is_accurate():
    md = _md(_uc4()).lower()
    assert "rosette.undistort" not in md
    assert "valid" in md and "snap" in md and "reject" in md


def _uc2():
    return nbformat.read(
        next(p for p in NOTEBOOKS if p.stem == "analyze_sequential_images"), as_version=4
    )


def test_uc2_uses_default_eps_merges_single_views_and_maps_located_only():
    code = _code(_uc2())
    assert "eps_by_class" not in code
    assert "merge_single_view=False" not in code
    assert "ent.located_entities(" in code
    assert '"unlocated"' in code
    assert "range_m" in code
    assert "TARGET_SPACING_M" in code
    assert "cluster_points_sql" in code and "sql_clusters=" in code


def test_uc2_counts_unlocated_detections_separately_from_entities():
    code = _code(_uc2())
    assert "{len(entities)} entities" not in code
    assert 'print(f"located_entities={len(located)} unlocated_detections={len(unlocated)}' in code
    assert "posts_located=" in code and "trees_located=" in code


def test_uc2_notebook_is_pure_public_row_and_uses_visual_fewshot():
    nb = _uc2()
    text = _all(nb)
    code = _code(nb)
    assert "HOUSE" not in text
    assert "STREET_TREE" in text
    assert "usecases.build_uc2_fewshot_parts(" in code
    assert "usecases.select_best_post_for_lean(" in code
    assert "cvchecks.street_tree_support(" in code


def test_uc2_does_not_claim_a_residential_street_and_fails_when_no_check_ran():
    nb = _uc2()
    assert "residential" not in _all(nb).lower()
    code = _code(nb)
    assert "len(tasks_df) == 0 or" not in code
    assert 'assert cv["n_asked"] > 0' in code


def test_uc2_self_check_is_labelled_consistency_with_bound_and_black_fraction():
    nb = _uc2()
    md = _md(nb).lower()
    assert "cross-view consistency (not accuracy)" in md
    code = _code(nb)
    assert "selection_bound_deg" in code and "n_unrenderable" in code
    assert "black_fraction_max" in code
    assert "per-class" in code


def _uc3():
    return nbformat.read(
        next(p for p in NOTEBOOKS if p.stem == "surface_material_detection"), as_version=4
    )


def test_uc3_sides_use_side_offset_and_no_numeric_side_literals():
    code = _code(_uc3())
    assert "smoothing.side_offset_m(" in code
    assert not re.search(r'"(LEFT|RIGHT)",\s*-?\d', code)
    assert "TARGET_SPACING_M" in code


def test_uc3_absent_state_gap_breaks_and_travel_centred_views():
    code = _code(_uc3())
    assert "absent_label=smoothing.ABSENT" in code and "breaks=" in code
    assert "smoothing.drive_length_m(" in code
    assert "sequence.road_view(" in code and "sequence.render_road_view(" in code
    assert "max(i - 1, 0)" not in code and "min(i + 1," not in code
    assert "black_fraction_max" in code


def test_uc3_reports_black_fraction_of_the_cropped_images_sent_to_gemini():
    code = _code(_uc3())
    assert "rv.black_sent" in code and "blacks.append(rv.black)" not in code
    assert "images.dark_pixel_fraction(" in code


def test_uc3_reports_smoothing_effect_not_flicker_as_quality():
    nb = _uc3()
    code = _code(nb)
    text = _all(nb).lower()
    assert "flicker" not in code
    assert "changed_by_smoothing" in code and "raw_smoothed_agreement" in code
    assert "absent_share" in code
    assert "not accuracy" in text and "schematic" in text


def test_figures_and_maps_carry_imagery_attribution(nb):
    for c in nb.cells:
        if c.cell_type != "code":
            continue
        if "imshow(" in c.source:
            assert (
                "attribution.add_to_axes(" in c.source or "attribution.save_figure(" in c.source
            ), c.source[:200]
        for call in re.findall(r"folium\.Map\((.*?)\)\n", c.source, re.S):
            assert "attr=" in call, call


def test_notebooks_state_terms_of_use(nb):
    md = _md(nb).lower()
    assert "terms" in md and "redistribut" in md and "attribution" in md


RESULT_PRINTS = {
    "00_explore_coverage": 'print(f"coverage_cells=',
    "house_image_discovery_with_cost": 'print(f"centred_views=',
    "analyze_sequential_images": 'print(f"located_entities=',
    "surface_material_detection": 'print(f"segments=',
    "roof_edge_tracing": 'print(f"accepted_edges=',
}


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: p.stem)
def test_notebooks_print_the_lines_the_live_checker_reads(path):
    code = _code(nbformat.read(path, as_version=4))
    assert RESULT_PRINTS[path.stem] in code
    assert "rosettes=" in code and "null_pano_id=" in code
    assert "map_rendered=1" in code and "peak_rss_mb=" in code
    if path.stem in UC_STEMS:
        assert "black_fraction_max=" in code and "runner.cost.summary(" in code


@pytest.mark.parametrize("path", UC_NOTEBOOKS, ids=lambda p: p.stem)
def test_notebooks_measure_dark_pixels_of_sent_views_besides_sensor_coverage(path):
    code = _code(nbformat.read(path, as_version=4))
    assert "images.dark_pixel_fraction(" in code or "dark_pixel_max=" in code


def _division_of_labour(nb) -> str:
    return next(
        c.source
        for c in nb.cells
        if c.cell_type == "markdown" and "division of labour" in c.source.lower()
    ).lower()


def test_division_of_labour_lists_only_steps_the_notebook_runs():
    uc2, uc3 = _division_of_labour(_uc2()), _division_of_labour(_uc3())
    assert "smoothing" not in uc2
    assert "triangulation" in uc2 and "deduplication" in uc2
    for step in ("triangulation", "deduplication", "box -> bearing"):
        assert step not in uc3, step
    assert "smoothing" in uc3 and "segments" in uc3
