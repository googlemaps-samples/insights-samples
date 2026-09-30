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
    --out street_view_insights/panoramic/svi_geo/data/labelfree/20260930/heldout_final
```

### Measured baseline vs final results (`2026-09-30`)

- **Manifests (SHA-256 prefix):** `tune` (`lakeland_fl`) = `6167b26c25b46e0f`, `heldout` (`salt_lake_ut`) = `25bc2b9841a95f0b`, `stress` (`osaka_jp`) = `06ea8f16a01212d5`
- **Logged Vertex AI spend:** `$17.89` across the 6 evaluation runs (`1,703` calls logged in `calls.jsonl`: `tune_baseline` `$3.26` / 306 calls, `tune_final` `$3.32` / 307 calls, `heldout_baseline` `$2.98` / 300 calls, `heldout_final` `$3.01` / 300 calls, `stress_baseline` `$2.61` / 246 calls, `stress_final` `$2.70` / 244 calls).

| Metric | UC | Role | Signal | `lakeland_fl` (Tune) Baseline -> Final | `salt_lake_ut` (Held-Out) Baseline -> Final | `osaka_jp` (Stress Test) Baseline -> Final | What It Measures (and Does Not Measure) |
|---|---|---|---|---|---|---|---|
| `M1.1` Fused attribute test-retest agreement | UC1 | primary | e | `1.000 [1.000, 1.000]` -> `0.889 [0.667, 1.000]` | `0.800 [0.500, 1.000]` -> `0.800 [0.500, 1.000]` | `0.600 [0.500, 0.667]` -> `0.300 [0.000, 0.545]` | Stability of fused `(stories, exterior_material, roof_type)` under yaw/HFOV/paraphrase perturbation (not architectural ground truth). |
| `M1.2` Location repeatability p50 (m, lower is better) | UC1 | primary | a, e | `0.393 [0.324, 0.736]` -> `0.393 [0.318, 0.720]` | `2.672` -> `2.672` | `0.916 [0.639, 1.534]` -> `0.916 [0.639, 1.534]` | Median 3D triangulated house position shift (m) across perturbed reruns / split-half panos (not parcel centroid offset). |
| `M1.3` Held-out reprojection hit rate | UC1 | guard | a | `0.727 [0.455, 1.000]` -> `0.727 [0.455, 1.000]` | `0.400` -> `0.400` | `0.826 [0.680, 0.955]` -> `0.826 [0.680, 0.955]` | Leave-one-view-out 3D house point reprojection hit rate within `3.5 deg` of the held-out box centre. |
| `M1.4` Framing non-truncation rate (teacher in-frame placebo) | UC1 | secondary | d, c | `0.714 [0.375, 1.000]` (teacher `0.500`) -> `0.714 [0.375, 1.000]` (teacher `0.500`) | `0.556 [0.222, 0.875]` (teacher `0.000`) -> `0.556 [0.222, 0.875]` (teacher `0.000`) | `0.043 [0.000, 0.150]` (teacher `0.000`) -> `0.043 [0.000, 0.150]` (teacher `0.000`) | Share of visible house boxes not truncated within 15 px of the crop border (with silver-teacher `fully_in_frame` rate). |
| `M1.5` Entity ID carry-over rate (`<= 3 m`) | UC1 | secondary | e, b | `1.000` -> `1.000` | `missing` (no paired house locations for ID carry-over) | `1.000` -> `1.000` | Stability of `match_house_ids` entity assignment across perturbed reruns. |
| `M1.6` Cross-day / silver-teacher material agreement | UC1 | secondary | b, c | `0.500` -> **`1.000`** (`+0.500`) | `missing` (no multi-pass house attribute pairs) | `1.000` -> `0.500` | Agreement of fused `exterior_material` with high-res zoom-tile teacher / repeat-pass capture (same model family; not accuracy). |
| `M2.1` Held-out-view reprojection support | UC2 | primary | a | `0.711 [0.625, 0.814]` -> **`0.750 [0.667, 0.853]`** (`+0.039`) | **`0.800 [0.600, 1.000]`** -> **`0.800 [0.600, 1.000]`** | `0.525 [0.438, 0.621]` -> `0.525 [0.438, 0.621]` | Share of located multi-view entities whose k-1 triangulated 3D point projects within `3.5 deg` of the k-th held-out detection. |
| `M2.2` Test-retest entity recall (Hungarian matching) | UC2 | guard | e | `0.713` -> **`0.797`** (`+0.084`) | `0.722` -> **`0.802`** (`+0.080`) | `0.570` -> `0.556` | Spatial recall of deduplicated 3D entities across perturbed reruns (`<= 4 m` poles/signs, `<= 8 m` houses). |
| `M2.3` Repeat-pass cross-day entity recall | UC2 | secondary | b | `0.382` -> **`0.424`** (`+0.042`) | `0.257` -> **`0.660`** (`+0.403`) | `0.369` -> **`0.536`** (`+0.167`) | Multi-view entity spatial recall across cross-day repeat passes (`date_a != date_b`) in `pano_observations_all`. |
| `M2.4` OpenCV vertical-post support (vs random-box placebo) | UC2 | secondary | d | `0.947` -> **`1.000`** (placebo `0.000`) | **`1.000`** -> **`1.000`** (placebo `0.025`) | `0.989` (placebo `0.149`) -> **`1.000`** (placebo `0.151`) | Gemini-independent LSD vertical line/edge support inside detected pole/sign boxes vs random boxes of equal size. |
| `M2.5` Multi-view (`>= 2` panos) located share (vs 1-pano HOUSE share) | UC2 | guard | a | `0.649` -> `0.447` (1-pano house `0.556`) | `0.353` -> `0.324` (1-pano house `0.000`) | `0.515` -> `0.344` (1-pano house `0.321`) | Share of located entities observed from `>= 2` panoramas after requiring `min_post_panos=2` for single-view poles/signs. |
| `M2.6` Silver-teacher zoom-tile confirmation | UC2 | secondary | c | `0.500` -> `0.500` | `0.000` -> `0.000` | `0.000` -> `0.000` | Agreement with Gemini 3.1 Pro Preview on 2x2 zoom tiles at the reprojected bearing (same model family; not accuracy). |
| `M3.1` Perturbation Cohen kappa across `(CENTER, LEFT, RIGHT)` | UC3 | primary | e | `1.000` -> `1.000` | `1.000` -> `1.000` | `0.906` -> **`0.954`** (`+0.048`) | Cohen kappa of smoothed road/sidewalk labels under yaw + paraphrase perturbation (`missing` when both sides are constant). |
| `M3.2` Adjacent-pano raw agreement (vs shuffle placebo) | UC3 | secondary | a, e | `1.000` (placebo `1.000`) -> `1.000` (placebo `1.000`) | `1.000` (placebo `1.000`) -> `1.000` (placebo `1.000`) | `0.900` (placebo `0.818`) -> `0.867` (placebo `0.763`) | Along-drive spatial continuity of raw surface labels compared with a within-sequence random permutation baseline. |
| `M3.3` Repeat-pass 20 m bin agreement across capture days | UC3 | secondary | b | `0.875 [0.750, 1.000]` -> **`0.917 [0.792, 1.000]`** (`+0.042`) | `0.733 [0.533, 0.933]` -> **`0.800 [0.667, 0.933]`** (`+0.067`) | `1.000` -> `0.889` | Cross-day 20 m along-road bin agreement of `(ROAD CENTER, SIDEWALK LEFT, SIDEWALK RIGHT)` across `repeat_pairs`. |
| `M3.4` OpenCV Lab+LBP road texture separation | UC3 | secondary | d | `0.015` -> **`0.016`** | `0.011` -> `0.011` | `0.066` -> `0.066` | Gemini-independent Lab colour + LBP texture distance between vs within predicted road surface segments. |
| `M3.5` Sidewalk presence vs OpenCV IPM kerb-line kappa | UC3 | secondary | d | `0.000` -> `0.000` | `0.000` -> `0.000` | `0.000` -> `0.000` | Cohen kappa between Gemini sidewalk presence and bird's-eye IPM longitudinal kerb lines (`missing` when both sides are constant). |
| `M3.6` Silver-teacher slot agreement | UC3 | guard | c | `1.000` -> `1.000` | `missing` -> **`1.000`** | `1.000` -> `1.000` | Agreement with Gemini 3.1 Pro Preview on zoom tiles for `(ROAD CENTER, SIDEWALK LEFT, SIDEWALK RIGHT)` (same model family; not accuracy). |
| `M4.1` Occlusion screen precision vs silver teacher | UC4 | primary | c | `0.625 [0.250, 0.875]` -> `0.625 [0.250, 0.875]` | **`0.875 [0.625, 1.000]`** -> **`0.875 [0.625, 1.000]`** | `0.250 [0.000, 0.500]` -> **`0.750 [0.500, 1.000]`** (`+0.500`) | Mean of `skip_precision` and `pass_precision` of `views.occlusion_screen` (`min_sky_contact=0.25`) against silver-teacher roof visibility. |
| `M4.2` OpenCV wall-decoy false acceptance rate (lower is better) | UC4 | primary | d | `0.196 [0.151, 0.238]` -> **`0.021 [0.007, 0.037]`** (`-0.175`, placebo `0.000`) | `0.228 [0.204, 0.247]` -> **`0.086 [0.052, 0.126]`** (`-0.142`, placebo `0.000`) | `0.224 [0.201, 0.244]` -> **`0.090 [0.060, 0.119]`** (`-0.134`, placebo `0.001`) | Share of non-roof straight edges (`wall_box` LSD lines, horizon, wall base, siding) falsely accepted by `validate_roof_edges`. |
| `M4.3` Validator edge retention rate | UC4 | guard | d | `0.273` -> `0.182` | **`0.364`** -> **`0.364`** | `0.000` -> **`0.062 [0.000, 0.231]`** (`+0.062`) | Share of Gemini-proposed roof edges retained after geometric + gradient + LSD validation (paired with `M4.2`). |
| `M4.4` Test-retest polyline agreement (`<= 5 px`) | UC4 | secondary | e | `0.333` -> **`0.500`** (`+0.167`) | **`0.500`** -> **`0.500`** | `missing` -> `0.000` | Repeatability of validated roof polylines within 5 px across perturbed views. |
| `M4.5` Silver-teacher roof trace F1 (`<= 5 px`) | UC4 | secondary | c | `missing` (no overlapping trace) | **`0.333`** -> **`0.333`** | `missing` (no overlapping trace) | Polyline F1 within 5 px against Gemini 3.1 Pro Preview roof traces on zoom tiles (same model family; not accuracy). |
| `M4.6` 3-view eave triangulation residual (px) | UC4 | secondary | a | `missing` (`< 3` views with accepted EAVE) | `missing` (`< 3` views with accepted EAVE) | `missing` (`< 3` views with accepted EAVE) | Held-out 3rd-view reprojection residual (px) of a 3D eave segment triangulated from 2 views. |

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
