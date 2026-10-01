# Colab Compatibility & Packaging Gate (`U17`)

**Date:** `2026-10-01`

## 1. Static & Constraint Compatibility (`tests/test_colab_compat.py` + `tests/test_packaging.py`)

Command:

```bash
.venv/bin/pytest -q --run-slow tests/test_colab_compat.py tests/test_packaging.py
```

Result: **`12 passed, 1 skipped` (`0.61s`)**:

- `test_lower_bounds_admit_colab_versions[colab-2026.07.txt]` — **PASS** (`numpy 2.0.2`, `pandas 2.2.2`, `scipy`, `scikit-learn`, `pyarrow`, `google-genai` all accepted without upgrades).
- `test_lower_bounds_admit_colab_versions[colab-current.txt]` — **PASS** (`numpy 2.1.3`, `pandas 2.2.3`, `scipy`, `scikit-learn`, `pyarrow`, `google-genai` all accepted without upgrades).
- `test_constraint_files_have_provenance[colab-2026.07.txt]` — **PASS** (full `googlecolab/backend-info` SHA provenance).
- `test_constraint_files_have_provenance[colab-current.txt]` — **PASS** (full `googlecolab/backend-info` SHA provenance).
- `test_no_new_numpy_pandas_only_apis` — **PASS** (zero usages of post-NumPy-2.0 or post-Pandas-2.2 APIs across `svi_geo/`, `scripts/`, and `tests/`).
- `test_notebook_install_cell_mentions_colab_preinstalled_versions` — **PASS** across all 5 notebooks (`00_explore_coverage.ipynb`, `house_image_discovery_with_cost.ipynb`, `analyze_sequential_images.ipynb`, `surface_material_detection.ipynb`, `roof_edge_tracing.ipynb`).
- `test_pyproject_ranges_and_extras` (`tests/test_packaging.py`) — **PASS** (`[notebooks]` and `[dev]` extras verified, `SVI_GEO_REF` pinned to commit SHA, no execution outputs in committed `.ipynb` files).
- `test_colab_venv_runs_offline_suite` (`--run-slow`) — skipped cleanly when `uv` / `python3.12` binary is absent on the gLinux host (`pytest.skip("neither uv nor python3.12 is available to build a Python 3.12 venv")`).
