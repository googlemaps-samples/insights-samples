# Real-imagery evaluation protocol

This page documents two complementary evaluation protocols on real Street View Insights imagery:

1. **Label-free evaluation** (measured and reported below): multi-view geometric consistency,
   cross-day repeat-pass stability, OpenCV image-evidence checks, perturbation repeatability,
   and zoom-tile silver-teacher agreement across three disjoint AOIs (`lakeland_fl` tune,
   `salt_lake_ut` held-out decision split, and `osaka_jp` dense urban stress test).
2. **Hand-label protocol** (for ground-truth accuracy): human annotation kit and scorer
   (`scripts/make_label_kit.py` and `scripts/score_labels.py`). **No ground-truth accuracy
   numbers are published here yet**: they will be added only after human labels exist.

## Retraction

Commit `c2b057c` ("... and 4-scene live eval") described a 4-scene live evaluation. Those
figures came from `scripts/run_notebook_eval.py` / `notebook_eval.py`, which filled in
missing results with generated values rather than measuring them. That code has been deleted
and the 4-scene figures are **retracted**. Do not quote them.

The synthetic and self-consistency modes of `run_eval.py` (see [`README.md`](README.md)) measure
different things (simulated scenes, and agreement of the model with itself). They are not
accuracy against ground truth; their old result tables were removed from the README.

## Label-free evaluation

> **Disclosure:** Label-free evaluation. No human labels, no external map data. All numbers measure multi-view geometric consistency, cross-day repeat-pass stability, OpenCV image-evidence support, or agreement with Gemini 3.1 Pro Preview (same model family as student Gemini 3.5 Flash; not accuracy).

### Signal families

- **`a` — Multi-view geometric & photometric consistency**: leave-one-view-out 3D reprojection (`M1.3`, `M2.1`), split-half pano triangulation (`M1.2`), along-drive spatial continuity (`M3.2`), and 3-view eave line triangulation (`M4.6`).
- **`b` — Cross-day repeat-pass consistency (`pano_observations_all`)**: spatial entity recall (`M1.5`, `M2.3`) and attribute/surface agreement (`M1.6`, `M3.3`) across independent drives captured on different calendar days (`>= 1` day apart, matched within `<= 6 m` and `<= 25 deg` heading).
- **`c` — High-resolution zoom-tile silver teacher (`gemini-3.1-pro-preview`)**: agreement on 2x2 high-resolution zoom crops (`640x640` per tile at `0.5x` field of view) for house framing (`M1.4`), object presence (`M2.6`), surface slots (`M3.6`), roof visibility (`M4.1`), and roof traces (`M4.5`). **Same model family as the student (`gemini-3-flash-preview`); measures zoom-tile teacher agreement, not ground-truth accuracy.**
- **`d` — Classical OpenCV image-evidence cross-checks (`svi_geo/cvchecks.py`)**: Gemini-independent sky-contact above roof ridges (`M1.4`), LSD vertical post/edge support vs random-box placebo (`M2.4`), Lab+LBP road texture/colour separation (`M3.4`), ground-plane IPM kerb-line evidence (`M3.5`), and wall-box LSD decoy rejection (`M4.2`, `M4.3`).
- **`e` — Perturbation repeatability**: test-retest stability across yaw (`+-3 deg`), field of view (`+-10%`), prompt paraphrase, and seed perturbations (`M1.1`, `M1.2`, `M2.2`, `M3.1`, `M4.4`).

### Reproducing the label-free evaluation

```sh
export PROJECT_ID=imagery-insights-sandbox
export GCS_BUCKET=geoai_published_337c66da-39c4-4aed-8d89-61492ec39eb0__us
.venv/bin/python street_view_insights/panoramic/svi_geo/scripts/run_labelfree_eval.py \
    --uc all --aoi heldout --variant final \
    --out street_view_insights/panoramic/svi_geo/data/labelfree/20261001/heldout_final
```

### Measured baseline vs final results (`2026-10-01`, `capture_id`-keyed with `INCLUDE_UNPUBLISHED_PANOS=True`)

- **Configuration identity:** `configuration evaluated == configuration shipped` (`usecases.DEFAULT_VARIANT = Variant.final()`, view sizes `UC1=1024x768`, `UC2=640x480`, `UC3=1024x576`, `UC4=1200x900`, `rosette_sql` keyed on `capture_id` with `INCLUDE_UNPUBLISHED_PANOS=True`, recovering ~69% of rosettes whose `pano_id IS NULL`).
- **Manifests (SHA-256 prefix):** `tune` (`lakeland_fl`) = `79bc094492ca33e5` (20 primary rosettes, 10 repeat pairs; 2,243 total rosettes across 274 sequences), `heldout` (`salt_lake_ut`) = `3ca122785f46ed12` (20 primary rosettes, 6 repeat pairs; 1,909 total rosettes across 232 sequences), `stress` (`osaka_jp`) = `849321fcec7d54d2` (20 primary rosettes, 7 repeat pairs; 1,871 total rosettes across 228 sequences).
- **Logged Vertex AI spend:** `$20.60` across the 6 primary evaluation runs (`2,073` calls logged in `calls.jsonl`: `tune_baseline` `$3.48` / 384 calls, `tune_final` `$3.55` / 387 calls, `heldout_baseline` `$3.66` / 369 calls, `heldout_final` `$3.37` / 351 calls, `stress_baseline` `$3.36` / 299 calls, `stress_final` `$3.18` / 283 calls), plus `$2.14` (`393` calls) for the U13 thinking/media ablation run (`tune_final_low_med`), totalling `$22.74` (`2,466` calls).

| Metric | UC | Role | Signal | `lakeland_fl` (Tune) Baseline -> Final | `salt_lake_ut` (Held-Out) Baseline -> Final | `osaka_jp` (Stress Test) Baseline -> Final | What It Measures (and Does Not Measure) |
|---|---|---|---|---|---|---|---|
| `M1.1` Fused attribute test-retest agreement | UC1 | primary | e | `1.000 [1.000, 1.000]` -> `0.889 [0.727, 1.000]` | `0.833 [0.667, 1.000]` -> `0.833 [0.667, 1.000]` | `0.727 [0.556, 0.917]` -> **`0.818 [0.667, 1.000]`** (`+0.091`) | Stability of fused `(stories, exterior_material, roof_type)` under yaw/HFOV/paraphrase perturbation (not architectural ground truth). |
| `M1.2` Location repeatability p50 (m, lower is better) | UC1 | primary | a, e | `0.239 [0.239, 0.239]` -> **`0.223 [0.223, 0.223]`** (`-0.016`) | `missing` (fewer than 2 located house reruns) -> `missing` (fewer than 2 located house reruns) | `0.420 [0.276, 0.646]` -> `0.420 [0.276, 0.646]` | Median 3D triangulated house position shift (m) across perturbed reruns / split-half panos (not parcel centroid offset). |
| `M1.3` Held-out reprojection hit rate | UC1 | guard | a | `0.667` -> `0.667` | `0.000` -> `0.000` | `0.810 [0.632, 0.957]` -> `0.810 [0.632, 0.957]` | Leave-one-view-out 3D house point reprojection hit rate within `3.5 deg` of the held-out box centre. |
| `M1.4` Framing non-truncation rate (teacher in-frame placebo) | UC1 | secondary | d, c | `0.643 [0.333, 0.875]` (placebo `0.000`) -> `0.643 [0.333, 0.875]` (placebo `0.000`) | `0.833 [0.500, 1.000]` (placebo `0.000`) -> `0.833 [0.500, 1.000]` (placebo `0.000`) | `0.136 [0.000, 0.333]` (placebo `0.000`) -> `0.136 [0.000, 0.333]` (placebo `0.000`) | Share of visible house boxes not truncated within 15 px of the crop border (with silver-teacher `fully_in_frame` rate). |
| `M1.5` Entity ID carry-over rate (`<= 3 m`) | UC1 | secondary | e, b | `1.000` -> `1.000` | `missing` (no paired house locations for ID carry-over) -> `missing` (no paired house locations for ID carry-over) | `1.000` -> `1.000` | Stability of `match_house_ids` entity assignment across perturbed reruns. |
| `M1.6` Repeat-pass attribute agreement across capture days | UC1 | secondary | b | `0.778` -> `0.778` | `0.333` -> `0.333` | `0.714` -> `0.429` | Cross-day reproducibility of fused house attributes (`stories`, `exterior_material`, `roof_type`) on true cross-day `repeat_pairs` (`date_a != date_b`). |
| `M1.7` Cross-day repeat-pass house attribute agreement (vs shuffled-pair placebo) | UC1 | secondary | b | `0.778 [0.333, 1.000]` (placebo `0.557`) -> `0.778 [0.333, 1.000]` (placebo `0.557`) | `0.333 [0.000, 0.667]` (placebo `0.305`) -> `0.333 [0.000, 0.667]` (placebo `0.342`) | `0.714 [0.250, 1.000]` (placebo `0.426`) -> `0.429 [0.200, 0.750]` (placebo `0.354`) | Cross-day house attribute agreement on matched capture pairs compared with an attribute-stratified permutation placebo (`cross-day repeat-pass consistency != accuracy`). |
| `M2.1` Held-out-view reprojection support | UC2 | primary | a | `0.686 [0.520, 0.773]` -> `0.676 [0.500, 0.776]` | `0.600 [0.421, 0.800]` -> `0.562 [0.333, 0.812]` | `0.723 [0.625, 0.800]` -> `0.705 [0.647, 0.745]` | Share of located multi-view entities whose k-1 triangulated 3D point projects within `3.5 deg` of the k-th held-out detection. |
| `M2.2` Test-retest entity recall (Hungarian matching) | UC2 | guard | e | `0.602` -> **`0.664`** (`+0.062`) | `0.550` -> **`0.757`** (`+0.207`) | `0.499` -> **`0.508`** (`+0.009`) | Spatial recall of deduplicated 3D entities across perturbed reruns (`<= 4 m` poles/signs, `<= 8 m` houses). |
| `M2.3` Repeat-pass cross-day entity recall | UC2 | secondary | b | `0.267` -> `0.108` | `0.237` -> **`0.282`** (`+0.045`) | `0.311` -> **`0.464`** (`+0.153`) | Multi-view entity spatial recall across cross-day repeat passes (`date_a != date_b`) in `pano_observations_all`. |
| `M2.4` OpenCV vertical-post support (vs random-box placebo) | UC2 | secondary | d | `0.972` (placebo `0.111`) -> **`1.000` (placebo `0.114`)** (`+0.028`) | `1.000` (placebo `0.018`) -> `1.000` (placebo `0.018`) | `1.000` (placebo `0.241`) -> `1.000` (placebo `0.243`) | Gemini-independent LSD vertical line/edge support inside detected pole/sign boxes vs random boxes of equal size. |
| `M2.5` Multi-view (`>= 2` panos) located share (vs 1-pano HOUSE share) | UC2 | guard | a | `0.548` (placebo `0.619`) -> `0.349` (placebo `0.619`) | `0.395` (placebo `0.667`) -> `0.186` (placebo `1.000`) | `0.633` (placebo `0.650`) -> `0.385` (placebo `0.650`) | Share of located entities observed from `>= 2` panoramas after requiring `min_post_panos=2` for single-view poles/signs. |
| `M2.6` Silver-teacher zoom-tile confirmation | UC2 | secondary | c | `0.500` -> `0.500` | `0.000` -> `0.000` | `0.000` -> `0.000` | Agreement with Gemini 3.1 Pro Preview on 2x2 zoom tiles at the reprojected bearing (same model family; not accuracy). |
| `M3.1` Perturbation Cohen kappa across `(CENTER, LEFT, RIGHT)` | UC3 | primary | e | `1.000` -> `1.000` | `0.940` -> **`1.000`** (`+0.060`) | `0.833` -> **`0.885`** (`+0.052`) | Cohen kappa of smoothed road/sidewalk labels under yaw + paraphrase perturbation (`missing` when both sides are constant). |
| `M3.2` Adjacent-pano raw agreement (vs shuffle placebo) | UC3 | secondary | a, e | `1.000` (placebo `1.000`) -> `1.000` (placebo `1.000`) | `1.000` (placebo `1.000`) -> `0.967` (placebo `0.944`) | `1.000` (placebo `1.000`) -> `1.000` (placebo `1.000`) | Along-drive spatial continuity of raw surface labels compared with a within-sequence random permutation baseline. |
| `M3.3` Repeat-pass 20 m bin agreement across capture days | UC3 | secondary | b | `0.750` -> **`0.833`** (`+0.083`) | `0.583` -> **`0.667`** (`+0.084`) | `1.000` -> `1.000` | Cross-day 20 m along-road bin agreement of `(ROAD CENTER, SIDEWALK LEFT, SIDEWALK RIGHT)` across `repeat_pairs`. |
| `M3.4` OpenCV Lab+LBP road texture separation | UC3 | secondary | d | `0.051` -> **`0.056`** (`+0.005`) | `0.015` -> **`0.016`** (`+0.001`) | `0.030` -> `0.029` | Gemini-independent Lab colour + LBP texture distance between vs within predicted road surface segments. |
| `M3.5` Sidewalk presence vs OpenCV IPM kerb-line kappa | UC3 | secondary | d | `-0.040` -> **`0.000`** (`+0.040`) | `0.000` -> `-0.083` | `0.000` -> `0.000` | Cohen kappa between Gemini sidewalk presence and bird's-eye IPM longitudinal kerb lines (`missing` when both sides are constant). |
| `M3.6` Silver-teacher slot agreement | UC3 | guard | c | `1.000` -> `1.000` | `1.000` -> `1.000` | `1.000` -> `1.000` | Agreement with Gemini 3.1 Pro Preview on zoom tiles for `(ROAD CENTER, SIDEWALK LEFT, SIDEWALK RIGHT)` (same model family; not accuracy). |
| `M3.7` Cross-day repeat-pass surface agreement (vs shuffled-pair placebo) | UC3 | secondary | b | `0.750 [0.667, 0.917]` (placebo `0.627`) -> **`0.833 [0.667, 1.000]` (placebo `0.625`)** (`+0.083`) | `0.583 [0.333, 0.833]` (placebo `0.583`) -> **`0.667 [0.333, 1.000]` (placebo `0.667`)** (`+0.084`) | `1.000 [1.000, 1.000]` (placebo `1.000`) -> `1.000 [1.000, 1.000]` (placebo `1.000`) | Cross-day 20 m bin agreement compared with a slot-stratified permutation placebo (`cross-day repeat-pass consistency != accuracy`). |
| `M4.1` Occlusion screen precision vs silver teacher | UC4 | primary | c | `0.375 [0.125, 0.750]` -> `0.375 [0.125, 0.750]` | `0.125 [0.000, 0.375]` -> `0.125 [0.000, 0.375]` | `0.375 [0.125, 0.750]` -> **`0.500 [0.125, 0.875]`** (`+0.125`) | Mean of `skip_precision` and `pass_precision` of `views.occlusion_screen` (`min_sky_contact=0.25`) against silver-teacher roof visibility. |
| `M4.2` OpenCV wall-decoy false acceptance rate (lower is better) | UC4 | primary | d | `0.105 [0.060, 0.144]` (placebo `0.000`) -> **`0.042 [0.026, 0.059]` (placebo `0.000`)** (`-0.063`) | `0.223 [0.207, 0.238]` (placebo `0.001`) -> **`0.077 [0.063, 0.089]` (placebo `0.001`)** (`-0.146`) | `0.209 [0.176, 0.239]` (placebo `0.001`) -> **`0.121 [0.080, 0.167]` (placebo `0.001`)** (`-0.088`) | Share of non-roof straight edges (`wall_box` LSD lines, horizon, wall base, siding) falsely accepted by `validate_roof_edges`. |
| `M4.3` Validator edge retention rate | UC4 | guard | d | `0.250` -> `0.167` | `0.125` -> `0.125` | `0.250` -> `0.143 [0.000, 0.444]` | Share of Gemini-proposed roof edges retained after geometric + gradient + LSD validation (paired with `M4.2`). |
| `M4.4` Test-retest polyline agreement (`<= 5 px`) | UC4 | secondary | e | `0.000` -> `0.000` | `0.000` -> `0.000` | `0.500` -> `0.500` | Repeatability of validated roof polylines within 5 px across perturbed views. |
| `M4.5` Silver-teacher roof trace F1 (`<= 5 px`) | UC4 | secondary | c | `0.000` -> `0.000` | `missing` (no overlapping student/teacher roof traces) -> `missing` (no overlapping student/teacher roof traces) | `0.000` -> `0.000` | Polyline F1 within 5 px against Gemini 3.1 Pro Preview roof traces on zoom tiles (same model family; not accuracy). |
| `M4.6` 3-view eave reprojection hit rate (`@5 deg`) | UC4 | secondary | a | `missing` (fewer than 3 views with accepted EAVE edges) -> `missing` (fewer than 3 views with accepted EAVE edges) | `missing` (fewer than 3 views with accepted EAVE edges) -> `missing` (fewer than 3 views with accepted EAVE edges) | `missing` (fewer than 3 views with accepted EAVE edges) -> `missing` (fewer than 3 views with accepted EAVE edges) | Fraction of 3-view eave endpoints whose reprojected line angle in view 3 is within `5 deg`. |

### Thinking level & media resolution ablation on `tune` (`lakeland_fl`, Task U13)

| Use Case | Setting (`thinking_level` / `media_resolution`) | Primary Metric(s) (`MEDIUM/HIGH` -> `LOW/MEDIUM`) | Guard Metric(s) (`MEDIUM/HIGH` -> `LOW/MEDIUM`) | Output Tokens (`tune` suite) | `decide_keep` Decision |
|---|---|---|---|---|---|
| UC1 (`house_image_discovery_with_cost`) | `MEDIUM` / `MEDIUM` vs `LOW` / `MEDIUM` | `M1.1`: `0.889` -> `0.778`; `M1.2`: `0.223 m` -> `1.444 m` | `M1.3`: `0.667` -> `0.000` (regresses at `LOW`) | `264,312` -> `157,130` (`-40.6%`) | **Keep `THINKING_LEVEL="MEDIUM"`** for UC1 (dropping to `LOW` regresses `M1.1`, `M1.2`, and `M1.3`). |
| UC2 (`analyze_sequential_images`) | `LOW` / `MEDIUM` vs `MEDIUM` / `HIGH` | `M2.1`: `0.676` -> `0.593` | `M2.2`: `0.664` -> `0.575`; `M2.5`: `0.349` -> `0.355` | `-40.6%` suite-wide (`$3.55` -> `$2.14`) | **Keep `LOW` / `MEDIUM`** in interactive notebook (`640x480` dense multi-camera batch stays under `$0.60` ceiling). |
| UC3 (`surface_material_detection`) | `LOW` / `MEDIUM` vs `MEDIUM` / `HIGH` | `M3.1`: `1.000` -> `1.000` (`+0.000`) | `M3.6`: `1.000` -> `1.000`; `M3.7`: `0.833` -> **`0.917`** | `-40.6%` suite-wide | **Keep `LOW` / `MEDIUM`** in interactive notebook (`0` quality loss, higher cross-day stability, lower latency and token spend). |
| UC4 (`roof_edge_tracing`) | `MEDIUM` / `HIGH` vs `LOW` / `MEDIUM` | `M4.1`: `0.375` -> `0.375`; `M4.2`: `0.042` -> `0.042` | `M4.3`: `0.167` -> `0.071` (regresses at `LOW/MEDIUM`) | `264,312` | **Keep `MEDIUM` / `HIGH`** for UC4 (`1200x900` roof polyline tracing requires `HIGH` media resolution to retain valid roof edges). |

### Superseded `pano_id`-keyed summary (`2026-09-30`, pre-U3 re-keying)

- Prior to Task U3 (`capture_id` re-keying with `INCLUDE_UNPUBLISHED_PANOS=True`), the `2026-09-30` run (`tune`=`6167b26c25b46e0f`, `heldout`=`25bc2b9841a95f0b`, `stress`=`06ea8f16a01212d5`, `$17.89` across `1,703` calls) filtered out unpublished rosettes (`pano_id IS NULL`, ~69% of captures). Those numbers are superseded by the `2026-10-01` `capture_id`-keyed table above and retained in `data/labelfree/20260930/` for provenance.

---

## Hand-label protocol (for accuracy against ground truth)

### Sample

| item | size | used for |
|---|---|---|
| neighbourhoods | 2, each with 20 consecutive panos from different drive sequences (40 panos) | all |
| level views | 240 (6 ground cameras per pano) | UC2 boxes |
| road/sidewalk slots | 120 (pano × road CENTER / sidewalk LEFT / sidewalk RIGHT) | UC3 |
| target houses | 10, every candidate view rated | UC1 |
| roof views | 10, every roof edge traced | UC4 |
| second labeller | 20% of the panos, repeated independently | inter-annotator agreement |

BigQuery access follows the notebooks: pano tables only, parameterised SQL, a dry run first,
a 2 GB cap, and no `gcs_uri` column.

### Workflow

1. **Render the kit.**

   ```sh
   ../../../.venv/bin/python scripts/make_label_kit.py \
       --aoi LAT1,LNG1 --aoi LAT2,LNG2 --houses houses.csv
   ```

   `houses.csv` has the columns `house_id,lat,lng`. The script renders the views with the
   same field-of-view rules as the notebooks (every view has less than 1% black border) into
   `~/svi_label_kit/<date>/`, outside the repository. It writes one HTML page per use case, a
   pre-filled `labels.csv` and `second_labeller_panos.txt`. **It generates no labels.**
2. **Label.** Fill in `labels.csv`. Its header is
   `label_id,pano_id,observation_id,view_yaw_deg,class,x0,y0,x1,y1,object_key,material,condition,notes`
   followed by the optional columns `side,present,edge_type,points_json,labeller`.
   - UC2: copy the view row once per object, and enter the box in view pixels and the class.
     `object_key` links the same physical object across panos.
   - UC3: for each slot, enter `material`, and `present=false` if there is no sidewalk on that
     side.
   - UC1: for each candidate view, record whether the house is visible and centred, plus its
     attributes in `notes`/`material`.
   - UC4: add one `ROOF_EDGE` row per edge, with `edge_type` and `points_json` (a pixel
     polyline).
   - Fill in `labeller` on every row.
3. **Second labeller.** A second person labels the panos in `second_labeller_panos.txt` into a
   separate sheet.
4. **Score.**

   ```sh
   ../../../.venv/bin/python scripts/score_labels.py --labels labels.csv \
       --pipeline-output run.json --roof-output roof.json --second-labels labels_b.csv
   ```

Labels and images stay on the labeller's machine. Only aggregate metrics are published.

### Hand-label metrics

Every rate is reported with a 95% bootstrap confidence interval over panos
(`eval.bootstrap_ci`, fed by `eval.per_pano_counts`).

| use case | metric |
|---|---|
| UC2 | per-class detection precision and recall at IoU ≥ 0.3; dedup purity and completeness against `object_key`; duplicate rate; share of objects located |
| UC3 | material accuracy per (asset, side); sidewalk presence F1 (`present=false` is scored as ABSENT); side-swap rate |
| UC1 | visible/centred accuracy per view; attribute accuracy |
| UC4 | edge precision and recall at a mean polyline distance ≤ 5 px (same view and edge type, one-to-one); the validator's accept/reject confusion matrix |
| all | inter-annotator agreement on the repeated 20% of panos |

### Hand-label results

None yet. This section will be filled in from `score_labels.py` output once real human labels
exist. It will never contain generated or placeholder values.
