---
name: utility-pole-subclassification-using-panoramic-svi
description: Sub-classify and triangulate roadside utility poles vs. lookalikes (street lights, mast arms, guy stubs, monopoles, sign posts) from panoramic Street View Insights rosettes while auditing material, condition, cross-arms, equipment, double-pole pairs, and lean. Use when auditing utility poles along a corridor, separating overhead utility poles from street lights, or triangulating poles from pano_observations_latest. Don't use for pavement materials, single-asset reconciliation, or Static API.
---

# Utility Pole Subclassification Using Panoramic SVI

Use this skill to locate, triangulate in 2D horizontal East-North-Up (`ENU`), and sub-classify roadside utility poles versus non-utility vertical lookalikes along a street corridor, using the Street View Insights **panoramic** table (`pano_observations_latest`).

## How it works

1.  **Metadata lookup, spatial deduplication & calibrated `(u, v)` + azimuth grids (code).** A parameterised, dry-run-checked BigQuery query (capped at 2 GB billed) reads frame metadata for 7-camera `SV_PANO` rosettes within `--radius-m` of `--coordinates` (or around `--observation-id`, `--capture-id`, or `--pano-id`). Rosettes are keyed on `capture_id` (`pano_id` is kept as nullable publishable metadata; keeping `pano_id IS NULL` rosettes recovers ~69% of captures). It never selects `gcs_uri`: the object path is derived deterministically from `gs://<bucket>/<snapshot_id>/v0/<observation_id>.jpg`. When `--mode fetch_sv` or `--min-spacing-m 8` is used, overlapping multi-year Street View passes are spatially deduplicated (~8 m spacing, sorted geographically North-to-South, West-to-East) and rendered with calibrated `(u, v)` pixel coordinate rulers (`200px` minor green grid, `400px` major labeled lines, `100px` yellow sub-ticks) plus top-edge cyan world compass azimuth (`{az:03.0f}deg`) labels (`sv_index.json`).
2.  **2D Horizontal ENU Multi-View Triangulation & Adaptive Infill Triggers A/B (code).** Candidate vertical structures (`UTILITY_POLE`, `STREET_LIGHT`) are detected on calibrated Kannala-Brandt (`KB4`) ground views (`svi_geo.usecases.uc2_run`) or passed as pixel observations (`--mode triangulate`) and intersected in a height-invariant 2D horizontal `(East, North)` metric frame (`triangulate_observations_2d_enu`). Single-view candidates trigger targeted $40^\circ$ zoom infill from adjacent rosettes (`Trigger A`, `infill_unlocated_poles`), and consecutive same-side pole spans are audited against a `> 50 m` continuity threshold (`Trigger B`, `audit_corridor_span_gaps`).
3.  **3-panel perspective composite, closed-loop 3D-to-2D reprojection & OpenCV LSD gates (code).** For each located pole candidate, `_select_parallax_panos_for_pole` selects up to two supporting rosettes (`>= 5.5 m` preferred) maximizing azimuth parallax (`max_parallax_deg`). From each rosette, `render_pole_inspection_composite` renders a distance-adaptive vertical perspective view (`< 1%` black border enforced via `rosette.best_camera_for_view` or `rosette.render_perspective_multi`, cropped above the $-40^\circ$ vehicle hood) and assembles an attribution-stamped (`"Imagery (c) Google"`) 3-panel composite:
    -   **Panel 1 (Left) — Full Vertical Shaft:** Entire vertical profile from ground collar to overhead crown with a center-shaft reference line, a **reprojected magenta circle with a white center dot** marking the 3D ground base (`reprojected_base_px`), and OpenCV Line Segment Detector (`LSD`) verticality (`vertical_post_support`) and clockwise-positive lean (`estimate_post_lean_deg`) measurements.
    -   **Panel 2 (Center) — Crown & Cross-Arm Zoom (2x):** Projected $+3.5\text{ m}\dots+9.0\text{ m}$ elevation window resolving primary/secondary conductors, pin/post insulators, cross-arms, cutouts, and pole-mount transformers.
    -   **Panel 3 (Right) — Base & Ground Zoom (2x):** Projected $-2.6\text{ m}\dots+2.2\text{ m}$ elevation window resolving the ground collar, timber decay/splitting, riser conduits, guy wires, and double-pole transfer bases.
4.  **Structured sub-classification & visual verification (Gemini + agent).** The multi-view 3-panel composites are sent **inline as bytes** to Gemini with `response_schema=PoleSubClassification`. Deterministic post-gates enforce `is_true_utility_pole`, `is_double_pole`, `gdop_warning` (`max_parallax_deg < 10.0`), OpenCV LSD lean fusion, and low-confidence false-detection filtering (`is_false_detection`).

## Core Principles & Lessons Learned

1.  **2D Horizontal ENU Multi-View Triangulation vs. Single-Ray Flat-Ground Drift:**
    -   *Why Single-Ray Projections Drift:* Estimating a pole's 3D position from a single Street View frame requires intersecting the base ray with a flat-ground plane (`z = -2.5 m` below the camera). On sloped roads, raised sidewalks, or behind curb grades, a $1^\circ\text{--}2^\circ$ pitch or elevation error causes **3 m to 8 m of range drift**.
    -   *Why 2D Horizontal ENU Triangulation Wins:* Intersecting the horizontal `(East, North)` unit bearing rays from **2 or more Street View captures** in a local East-North-Up (`ENU`) plane (`triangulate_observations_2d_enu`) is **completely independent of ground elevation and camera height**. Pointing at the pole shaft at *any* height `(u, v)` in Capture A and Capture B yields the exact horizontal `(East, North)` intersection where the vertical pole stands.
2.  **The `> 10°` Parallax Rule (Geometric Dilution of Precision / GDOP):**
    -   *Why Same-Side Approach Views Fail:* Observing a distant pole from two captures that are both approaching it from nearly the same angle (`parallax < 5°`) creates nearly parallel rays where a `20px` horizontal pixel error translates to `3 m–6 m` of depth error (`gdop_warning: true`).
    -   *Best Practice:* Always pair **one approaching capture** (pole in front/side-front camera) with **one receding or passing capture** (pole in side or rear-quarter camera) so the horizontal bearing difference exceeds **`10°` (`max_parallax_deg >= 10.0`, ideally `20°–90°`)**, keeping horizontal residuals `<= 1.5 m`.
3.  **The Double-Pole ("Buddy Pole") Policy (`0.5m–1.2m` Separation):**
    -   In utility maintenance, an older pole is frequently cut or topped and lashed alongside a newer replacement pole (`0.5 m–1.2 m` apart) while awaiting telecom/conductor transfer.
    -   **Never merge** two distinct ground-contact pole shafts into a single generic record without noting the pair: when Panel 3 (`BASE & GROUND`) shows two adjacent ground-contact shafts, classify as `DOUBLE_POLE_TRANSFER_PAIR` (`is_double_pole: true`) or triangulate both shafts as separate pole IDs (`P01a`, `P01b`).
4.  **Multi-Zone Visual Inspection (Crown + Mid-Shaft + Base):**
    -   Always inspect all three vertical zones of the pole:
        -   **Top / Crown (Panel 2):** Cross-arms (`SINGLE_ARM`, `DOUBLE_ARM`, `ALLEY_ARM`, `ARMLESS_FRAMING`), pin/post insulators, primary/secondary conductors, fused cutouts, and pole-mounted transformers.
        -   **Mid-Shaft (Panel 1):** Secondary service drops, telecom/CATV strand bundles with splice enclosures (`TELECOM_SPLICE_CASE`), street-light cobra-head brackets (`STREET_LIGHT_LUMINAIRE`), and shaft material/lean.
        -   **Bottom / Base (Panel 3):** Ground collar contact, U-guard riser conduits (`RISER_CONDUIT`), guy anchors (`GUY_WIRE`), bolt-down metal bases, and double-pole transfer pairs.

## Taxonomy & Sub-Classification Policy (TRUE UTILITY_POLE vs. FALSE POSITIVE — EXCLUDE!)

### Utility Pole vs. Lookalike Decision Policy

| Subtype (`pole_subtype`) | `is_true_utility_pole` | Distinguishing Visual Evidence (Crown & Base Panels) |
| :--- | :---: | :--- |
| `DISTRIBUTION_UTILITY_POLE` | `true` | Overhead primary/secondary electric distribution wires, pin/post insulators, fused cutouts, or pole-mount can transformers at the crown (Panel 2) without a lower telecom strand. |
| `JOINT_USE_UTILITY_POLE` | `true` | Overhead electric distribution at the upper crown **and** lower-tier telecom/fiber cables, splice enclosures, or a cobra-head luminaire bracket on the same shaft. |
| `TRANSMISSION_POLE` | `true` | Tall sub-transmission or transmission structure with multi-circuit cross-arms, suspension/post insulators, and high-voltage conductors. |
| `DOUBLE_POLE_TRANSFER_PAIR` | `true` | Two adjacent utility pole shafts standing side-by-side in Panel 1 / Panel 3 (an older or topped pole strapped to a replacement pole awaiting conductor transfer; forces `is_double_pole: true`). |
| `STANDALONE_STREET_LIGHT` | `false` | Dedicated metal, concrete, or composite lighting standard with a luminaire arm fed underground (base bolt flange or handhole cover in Panel 3, **zero** overhead distribution conductors or insulators in Panel 2). |
| `TRAFFIC_SIGNAL_MAST_ARM` | `false` | Heavy structural steel shaft supporting horizontal traffic signal mast arms, signal heads, or pedestrian pushbuttons at an intersection without overhead electric distribution lines. |
| `GUY_STUB_OR_PUSH_BRACE` | `false` | Unwired wooden stub pole or angled push-brace pole used purely for mechanical guying (`GUY_WIRE` anchored near the top cap in Panel 2 with no insulators, cross-arms, or line conductors). |
| `TELECOM_OR_CELL_MONOPOLE` | `false` | Dedicated small-cell/5G shroud antenna monopole or standalone telecom drop pole with no electric distribution hardware. |
| `SIGN_POST_OR_OTHER` | `false` | Roadside sign post, bollard, flagpole, tree trunk, or empty-curb false candidate (`is_false_detection: true` when `confidence < 0.35` and `opencv_vertical_support < 0.25`). |

### True Utility Poles (`is_true_utility_pole: true`)

-   **`DISTRIBUTION_UTILITY_POLE` / `JOINT_USE_UTILITY_POLE` / `TRANSMISSION_POLE` / `DOUBLE_POLE_TRANSFER_PAIR`:** Any wood, concrete, steel, or composite pole that is part of the **overhead wire/cable corridor** (carrying primary/secondary power lines, telecom/fiber messenger strands, cross-arms, insulators, transformers, or riser conduits)—**even if it also has a street light luminaire, road sign, or traffic signal attached to it**.

### Non-Utility Lookalikes (`is_true_utility_pole: false` — Exclude from Pole Inventory!)

-   **`STANDALONE_STREET_LIGHT`:** Metal, concrete, or fiberglass luminaire pole with an overhanging light arm fed by underground conduit (**no overhead line wires passing through or attaching to the crown**). *Look closely at Panel 2: background wires passing behind a street light without insulators or attachment hardware do NOT make it a utility pole.*
-   **`TRAFFIC_SIGNAL_MAST_ARM`:** Dedicated heavy metal mast-arm pole at an intersection supporting traffic signal heads/pedestrian crossings without overhead utility lines.
-   **`GUY_STUB_OR_PUSH_BRACE` / `TELECOM_OR_CELL_MONOPOLE` / `SIGN_POST_OR_OTHER`:** Unwired guy stubs, standalone small-cell monopoles without distribution framing, street signs, bollards, flagpoles, or tree trunks.
-   **Supporting Attributes:** Each record also audits `material` (`WOOD`, `CONCRETE`, `METAL`, `COMPOSITE`, `OTHER`, `UNKNOWN`), `condition` (`GOOD`, `FAIR`, `POOR`, `UNKNOWN`), `crossarm_config` (`NONE`, `SINGLE_ARM`, `DOUBLE_ARM`, `ALLEY_ARM`, `ARMLESS_FRAMING`, `UNKNOWN`), `attached_equipment` (`OVERHEAD_CONDUCTORS`, `POLE_MOUNT_TRANSFORMER`, `STREET_LIGHT_LUMINAIRE`, `RISER_CONDUIT`, `TELECOM_SPLICE_CASE`, `GUY_WIRE`, `CAPACITOR_OR_REGULATOR`, `STREET_SIGN`, `TRAFFIC_SIGNAL`), and clockwise-positive `lean_deg` (`[-45.0, 45.0]`).

## Prerequisites

-   `google-genai`, `google-cloud-bigquery`, `google-cloud-storage`, `pydantic`, `opencv-python-headless`, `pandas`, and `numpy` (`pip install -e street_view_insights/panoramic/svi_geo` installs all of them plus the calibrated fisheye rectification package).
-   Application Default Credentials with BigQuery (`roles/bigquery.jobUser`, `roles/bigquery.dataViewer`), read access to the frame bucket (`roles/storage.objectViewer`), and Vertex AI (`roles/aiplatform.user`) in your project.
-   Your billing project (`--project`, or `$PROJECT_ID`, then `$GOOGLE_CLOUD_PROJECT`) and the frame bucket linked to your Imagery Insights dataset (`--gcs-bucket` or `$GCS_BUCKET`). The bucket is never looked up by selecting `gcs_uri`.

## Instructions (Step-by-Step Agentic Workflow)

Run from the repository root:

### Step 1: Run Full End-to-End Corridor Audit (`--mode audit`) or Fetch Calibrated Contact Sheets (`--mode fetch_sv`)

```bash
export PROJECT_ID=YOUR_PROJECT_ID GCS_BUCKET=YOUR_FRAME_BUCKET

# Mode A (Default): Full automated corridor discovery, 2D ENU triangulation, 3-panel composites, and Gemini sub-classification
python3 street_view_insights/panoramic/skills/utility_pole_subclassification_using_panoramic_svi/scripts/subclassify_poles.py \
  --mode audit \
  --coordinates <lat,lng> \
  --output-dir ./pole_composites \
  --output ./pole_audit.json

# Or audit around a known observation_id, capture_id, or pano_id
python3 street_view_insights/panoramic/skills/utility_pole_subclassification_using_panoramic_svi/scripts/subclassify_poles.py \
  --observation-id <observation_id> \
  --output-dir ./pole_composites
python3 street_view_insights/panoramic/skills/utility_pole_subclassification_using_panoramic_svi/scripts/subclassify_poles.py \
  --capture-id <capture_id> \
  --output-dir ./pole_composites
python3 street_view_insights/panoramic/skills/utility_pole_subclassification_using_panoramic_svi/scripts/subclassify_poles.py \
  --pano-id <pano_id> \
  --output-dir ./pole_composites

# Mode B: Fetch spatially deduplicated (~8m) Street View contact sheets & frames with (u,v) + cyan azimuth grids
python3 street_view_insights/panoramic/skills/utility_pole_subclassification_using_panoramic_svi/scripts/subclassify_poles.py \
  --mode fetch_sv \
  --coordinates <lat,lng> \
  --min-spacing-m 8 \
  --output-dir ./sv_inspection
```

### Step 2: Visual Inspection of `(u, v)` + Compass Azimuth Grids & 3-Panel Composites

1.  **Inspect saved 3-panel composites (`inspection_composite_files`) with `view_file`.** Verify:
    -   **Panel 1 (`FULL SHAFT`):** Check that the reprojected magenta circle with a white center dot (`reprojected_base_px`) sits on the pole's ground base and that the shaft aligns with the vertical reference line.
    -   **Panel 2 (`CROWN & CROSS-ARM`):** Confirm whether overhead conductors physically attach via insulators/cross-arms (`DISTRIBUTION_UTILITY_POLE` / `JOINT_USE_UTILITY_POLE`) or merely pass behind a standalone street light (`STANDALONE_STREET_LIGHT`) or guy stub (`GUY_STUB_OR_PUSH_BRACE`).
    -   **Panel 3 (`BASE & GROUND`):** Check the ground collar for side-by-side transfer poles (`DOUBLE_POLE_TRANSFER_PAIR`), U-guard riser conduits (`RISER_CONDUIT`), or bolt-down metal bases.
2.  **Read `(u, v)` pixel coordinates & world compass azimuths from contact sheets (`sv_images/cap_XXX_sheet.jpg`).**
    -   Green grid lines mark original `(u, v)` pixel coordinates every `200px` (labeled every `400px` with `100px` yellow sub-ticks).
    -   **Cyan labels along the top edge (`{az:03.0f}deg`)** show the exact world compass azimuth (`000deg = North`, `090deg = East`, `180deg = South`, `270deg = West`) at each `400px` column, allowing you to match the same physical pole across consecutive captures without confusion.

### Step 3: Adaptive Infill Triggers A, B, and C

Before finalizing the corridor inventory, check three adaptive infill triggers:

-   **Trigger A — Single-Ray Parallax Infill (`gdop_warning: true` or `n_panos == 1`):** If any pole candidate was observed from only 1 capture or has `max_parallax_deg < 10.0`, inspect the adjacent capture `12 m–35 m` away (`cap_{k-1}` or `cap_{k+1}`) or re-run with `--radius-m 120 --max-rosettes 10` to obtain an opposing approach/recede bearing `>= 10°` apart.
-   **Trigger B — Span Continuity (`> 50 m` Wire Gap Investigation):** Inspect `corridor_span_audit.span_gaps` in the JSON output. Standard urban/suburban distribution pole spans are `25 m–45 m`. Whenever two consecutive same-side utility poles are **`> 50 m` apart** (`trigger_b_required: true`), follow the overhead wires across the `intermediate_captures` listed in `span_gaps` to check for a foliage-occluded intermediate pole.
-   **Trigger C — Secondary Branch Coverage:** If overhead conductors or cross-arms branch onto a side street or alley within `--radius-m`, fetch the nearest capture on that branch (`--mode fetch_sv --capture-indices ...`) so branch poles are not missed.

### Step 4: Multi-Ray 2D ENU Triangulation (`--mode triangulate`) & Closed-Loop 3D-to-2D Reprojection (`--mode render_candidates`)

```bash
# Triangulate pixel observations (pole_id=cap_idx:cam_k:u:v,...) in 2D horizontal ENU and audit >50m span gaps
python3 street_view_insights/panoramic/skills/utility_pole_subclassification_using_panoramic_svi/scripts/subclassify_poles.py \
  --mode triangulate \
  --output-dir ./sv_inspection \
  --observations "P01=0:4:2240:3120,2:5:1850:3200;P02=1:1:1420:2980,3:2:2110:3050" \
  --output ./triangulated_poles.json

# Closed-loop 3D-to-2D verification: reproject 3D candidates as magenta circles onto SV sheets + render 3-panel composites
python3 street_view_insights/panoramic/skills/utility_pole_subclassification_using_panoramic_svi/scripts/subclassify_poles.py \
  --mode render_candidates \
  --coordinates <lat,lng> \
  --candidates-json ./pole_audit.json \
  --output-dir ./sv_reprojection
```

-   **Quality Gates on `--mode triangulate`:**
    -   `status == "OK"`: `max_parallax_deg >= 10.0`, `max_residual_m <= 1.5`, and `behind_camera == false`.
    -   `status == "LOW_PARALLAX_WARNING"` (`gdop_warning: true`): Add an observation from a closer or receding capture.
    -   `status == "HIGH_RESIDUAL_WARNING"` (`max_residual_m > 1.5`): Two different poles were mismatched across captures; check the top-edge cyan compass azimuths (`{az:03.0f}deg`) and re-pair.
-   **Closed-Loop 3D-to-2D Check on `--mode render_candidates`:** View `reproj_cap_XXX_sheet.jpg` to verify that every magenta circle (`P{id}:{subtype}`) lands directly on the base of the intended utility pole shaft.

### Optional arguments

-   `--mode`: `audit` (default), `fetch_sv`, `triangulate`, or `render_candidates`.
-   `--project` (alias `--project-id`, `--project_id`): billing project (default `$PROJECT_ID`, then `$GOOGLE_CLOUD_PROJECT`).
-   `--gcs-bucket` (alias `--gcs_bucket`): Street View Insights frame bucket (default `$GCS_BUCKET`).
-   `--coordinates` (or `--lat` and `--lng`): corridor center WGS84 coordinates (`lat,lng`).
-   `--observation-id`, `--capture-id`, `--pano-id`: look up the corridor center from a known `observation_id`, `capture_id`, or `pano_id`.
-   `--radius-m` (alias `--radius_m`): corridor search radius in metres (default `80.0`).
-   `--max-rosettes` (alias `--max_rosettes`): maximum 7-camera rosettes to inspect along the corridor (default `6`).
-   `--min-spacing-m` (alias `--min_spacing_m`): minimum spatial spacing in metres when deduplicating overlapping multi-year passes (default `0.0` for `audit`, `8.0` for `fetch_sv`).
-   `--max-poles` (alias `--max_poles`): maximum candidate vertical structures to sub-classify (default `5`).
-   `--capture-indices`, `--camera-indices`: filter specific capture or horizontal camera indices (`0,1,2,3,4,5`) for `fetch_sv` or `render_candidates`.
-   `--observations`, `--observations-json`: pixel observations (`P01=cap:cam:u:v,...`) for `--mode triangulate`.
-   `--candidates-json`, `--candidates-csv`: 3D pole candidates for `--mode render_candidates`.
-   `--output` (alias `--output-json`, `--output_json`): path to save the structured JSON report.
-   `--output-dir` (alias `--output_dir`): directory to save 3-panel composites, calibrated SV contact sheets, and `sv_index.json`.
-   `--dataset`: BigQuery dataset (default `imagery_insights___us`).
-   `--model` (default `gemini-3.5-flash`) and `--location` (default `global`).

### Output

```json
{
  "corridor": {
    "center_lat": 28.0502,
    "center_lng": -81.9601,
    "radius_m": 80.0,
    "rosettes_inspected": 6,
    "frames_inspected": 42,
    "bq_dry_run_gb": 1.6272
  },
  "summary": {
    "candidates_evaluated": 4,
    "true_utility_pole_count": 3,
    "non_utility_vertical_count": 1,
    "false_detection_count": 0,
    "infill_recovered_poles": 4,
    "corridor_span_gaps_over_50m": 0
  },
  "corridor_span_audit": {
    "max_span_threshold_m": 50.0,
    "left_pole_count": 1,
    "right_pole_count": 2,
    "span_gaps": [],
    "trigger_b_required": false
  },
  "poles": [
    {
      "entity_id": "utility_pole_73ad077b77",
      "initial_cls": "UTILITY_POLE",
      "lat": 28.050161,
      "lng": -81.9598167,
      "n_panos": 6,
      "supporting_rosettes": ["t1:sP6u1Bhc3ak3sevNuJuUsg", "t1:H4_IkJyb29zKG_v-NYVs2g"],
      "supporting_observations": ["o1:sP6u1Bhc3ak3sevNuJuUsg_0:5001ee", "o1:H4_IkJyb29zKG_v-NYVs2g_0:5001ee"],
      "max_parallax_deg": 18.4,
      "gdop_warning": false,
      "opencv_vertical_support": 0.907,
      "opencv_lsd_lean_deg": -2.74,
      "pole_subtype": "JOINT_USE_UTILITY_POLE",
      "is_true_utility_pole": true,
      "is_false_detection": false,
      "material": "WOOD",
      "condition": "GOOD",
      "crossarm_config": "ARMLESS_FRAMING",
      "attached_equipment": [
        "OVERHEAD_CONDUCTORS",
        "POLE_MOUNT_TRANSFORMER",
        "STREET_LIGHT_LUMINAIRE",
        "TELECOM_SPLICE_CASE"
      ],
      "is_double_pole": false,
      "lean_deg": -2.74,
      "confidence": 0.95,
      "evidence_summary": "Wooden joint-use utility pole with armless primary framing, a single-phase pole-mounted transformer, a street-light luminaire bracket, and a lower-tier telecom strand with a splice enclosure.",
      "inspection_composite_files": [
        "./pole_composites/utility_pole_73ad077b77_view1_t1:sP6u1Bhc3.png",
        "./pole_composites/utility_pole_73ad077b77_view2_t1:H4_IkJyb2.png"
      ]
    }
  ],
  "saved_composite_images": [
    "./pole_composites/utility_pole_73ad077b77_view1_t1:sP6u1Bhc3.png",
    "./pole_composites/utility_pole_73ad077b77_view2_t1:H4_IkJyb2.png"
  ],
  "cost": {
    "model": "gemini-3.5-flash",
    "calls": 48,
    "input_tokens": 95716,
    "output_tokens": 50450,
    "usd": 0.59762
  }
}
```
