# Changelog — `svi_geo` & Street View Insights Panoramic Reference Notebooks

## v2.0.0 — 2026-10-01 (`capture_id` Reference Architecture, Agentic Vision, & BigQuery Pushdown)

### Highlights

- **Re-keyed on `capture_id` (`INCLUDE_UNPUBLISHED_PANOS=True`):**
  - Replaced `pano_id`-only grouping with `capture_id` across `svi_geo` (`data.py`, `rosette.py`,
    `sequence.py`, `pipeline.py`, `entities.py`, `views.py`, `usecases.py`, `labelfree.py`, and
    all notebooks), recovering ~69% of panoramic captures whose `pano_id IS NULL` while retaining
    nullable `pano_id` + `map_url` for attribution metadata.
  - Added `data.frames_from_rosettes` to expand 1-row-per-rosette BigQuery results (`cams`
    `ARRAY<STRUCT<k, observation_id, heading, pitch, roll, cam_lat, cam_lng>>`) into frame rows
    with `gcs_uri` constructed locally (`0 B` `gcs_uri` column scan).
- **BigQuery SQL Pushdown & Cost Safety (`svi_geo/data.py`):**
  - Added canonical `rosette_sql` (`capture_id` key, server-side `LAG` gaps-and-islands `seq_id` /
    `seq_idx` / `step_m` / `travel_deg`, `ST_DISTANCE`, `ST_AZIMUTH`, `ST_ASTEXT(geog) AS wkt`,
    `ST_GEOHASH(geog, 7) AS gh7`; 1.83 GB cold scan).
  - Added `snapshot_catalog_sql` (2.3 KB), `coverage_sql` (1.04 GB), `tracks_sql` (1.43 GB),
    `repeat_pairs_sql` (1.89 GB), `multi_aoi_sql` (1.83 GB), `assets_in_aoi_sql` (0.053 GB), and
    `0 B` table-free `cluster_points_sql` (`ST_CLUSTERDBSCAN` over `UNNEST(@points)` with
    `allow_table_free=True`).
  - Added snapshot-keyed Parquet query cache with 35-day TTL cap (`MAX_QUERY_CACHE_TTL_S`),
    bytes sidecar (`bq.last_cost()`), and `svi_geo/data/bytes_manifest.json`.
- **Gemini 3 Flash & Validated Agentic Vision (`svi_geo/gemini_client.py`, `svi_geo/usecases.py`):**
  - Added `thinking_level`, `media_resolution`, `CodeExecSchemaMode` (`DEFAULT` native
    `tools=[code_execution]` + `response_schema`), `CodeExecTrace`, and `check_code_exec_trace`
    (verifying `>= 1` Python `executable_code`, `OUTCOME_OK`, no network imports, `MEASURE: {...}`
    stdout, and sandbox overlay dimensions).
  - Added `tool_use_prompt_tokens`, `cached_tokens`, and `media_tokens` cost accounting,
    `preview_tokens` via `count_tokens`, `CONCURRENCY=8` with automatic 429 semaphore halving,
    and removed silent `gemini-2.5-pro` fallback (`fallback_model=None` default).
  - Added one scoped, deterministically cross-checked agentic vision (`code_execution=True`)
    function per notebook (`uc4_measure_roof_angles`, `uc1_count_storeys`,
    `uc2_measure_post_lean`, `uc3_locate_material_boundary`).
- **Image Pipeline & Shared Map Helpers (`svi_geo/images.py`, `svi_geo/rosette.py`, `svi_geo/maps.py`):**
  - Added sub-scale JPEG decoding (`images.decode(..., scale=s*)` + `Intrinsics.scaled(s*)`),
    Gaussian anti-aliased perspective remapping (`antialias=True`), `rosette.render_equirect_strip`,
    geometric `views.zoom_view`, `views.redaction_overlap` (`privacy_blob_mask`), and `maps.py`
    Folium builders (`rosette_tracks_map`, `uc1_house_map`, `uc2_entities_map`, `uc3_segments_map`,
    `uc4_roof_map`) with mandatory `"Imagery © Google"` attribution.
- **5 Canonical Reference Notebooks (`street_view_insights/panoramic/notebooks/`):**
  - Added `00_explore_coverage.ipynb` (`O4`, zero-Gemini warm-up) and restructured all 4 UC
    notebooks around the 7 `concept:*` cells (`sql`, `geometry`, `prompt_schema`, `code_exec`,
    `validator`, `map`, `cost`), including `O1` (repeat-pass pairs), `O2` (`cropped_assets_latest`
    audit), and `O3` (clustered index doc appendix).
- **26-Metric Label-Free Evaluation (`svi_geo/EVALUATION.md`):**
  - Regenerated `capture_id`-keyed manifests (`lakeland_fl`, `salt_lake_ut`, `osaka_jp`), added
    explicit cross-day repeat-pass agreement signals (`M1.7`, `M3.7`), and ran 7 live evaluation
    passes (`$22.16` total logged spend across `tune`, `heldout`, `stress`, and thinking/media
    ablation).
