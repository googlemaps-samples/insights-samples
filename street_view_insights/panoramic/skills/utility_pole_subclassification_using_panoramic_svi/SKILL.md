---
name: utility_pole_subclassification_using_panoramic_svi
description: >
  Sub-classify roadside vertical structures from Google Maps Platform Street View
  Insights (`SV_PANO`) 7-camera rosettes into fine-grained utility pole subtypes
  (`DISTRIBUTION_UTILITY_POLE`, `JOINT_USE_UTILITY_POLE`, `TRANSMISSION_POLE`,
  `DOUBLE_POLE_TRANSFER_PAIR`) versus non-utility lookalikes
  (`STANDALONE_STREET_LIGHT`, `TRAFFIC_SIGNAL_MAST_ARM`, `GUY_STUB_OR_PUSH_BRACE`,
  `TELECOM_OR_CELL_MONOPOLE`, `SIGN_POST_OR_OTHER`), while auditing material,
  structural condition, cross-arm framing, attached equipment, and lean angle.
  Use when a user wants to audit electric or telecom utility poles along a corridor,
  separate true overhead utility poles from street lights or traffic signal mast arms,
  detect double-pole transfer pairs or pole-mount transformers, or measure pole lean
  from `pano_observations_latest`. Don't use for road or sidewalk pavement material
  classification (use `surface_material_detection_using_panoramic_svi`), building
  roofline extraction, or Street View Static API requests.
---

# Utility Pole Sub-Classification and Equipment Audit (`SV_PANO`)

Generic street-level object detectors frequently conflate **true overhead utility poles** with other tall roadside vertical structures—such as standalone cobra-head street lights fed underground, traffic-signal mast arms, guy stubs, small-cell monopoles, and tall sign posts. Furthermore, single wide-angle fisheye frames foreshorten the upper crown where insulators, cross-arms, and transformers sit, and can hide a second pole shaft directly behind the first in a **double-pole ("buddy pole") transfer pair**.

This skill resolves both failure modes by combining **multi-rosette 3D East-North-Up (ENU) triangulation**, **approach + recede azimuth parallax view selection**, a **calibrated 3-panel perspective inspection composite**, **constrained Gemini structured output (`PoleSubClassification`)**, and **deterministic OpenCV Line Segment Detector (LSD) geometric gates**.

---

## 1. End-to-End 4-Stage Architecture

1. **Corridor Rosette Discovery & 3D ENU Triangulation (`svi_geo.usecases.uc2_run`)**
   - Queries `pano_observations_latest` within `@radius_m` of `(@lat, @lng)` with a mandatory BigQuery dry-run byte cap (`<= 2 GB`).
   - Groups complete 7-camera rosettes by `capture_id` (`cam_k = 0..5` horizontal ground cameras + `cam_k = 6` sky camera), rectifies ground views with the calibrated Kannala-Brandt (`KB4`) fisheye lens model, and detects candidate roadside vertical structures (`UTILITY_POLE`, `STREET_LIGHT`).
   - Converts 2D bounding boxes into 3D rays in a local East-North-Up (`ENU`) metric frame, clusters and triangulates multi-view intersections, and runs single-view $40^\circ$ zoom infill (`infill_unlocated_poles`) to recover poles occluded in adjacent views.

2. **Maximum Azimuth Parallax View Selection (`approach` + `recede`)**
   - For each candidate pole at `(lat, lng)`, selects up to **2 supporting rosettes** that maximize azimuth parallax (`max_parallax_deg`):
     - **Primary View**: Observed rosette closest to the optimal $14\text{ m}$ inspection distance.
     - **Secondary View**: Adjacent rosette offering the widest azimuth baseline relative to the primary view (viewing the pole from the opposite approach/recede angle to expose occluded cross-arms, rear-mounted transformers, and side-by-side double poles).

3. **Calibrated 3-Panel Inspection Composite (`render_pole_inspection_composite`)**
   - From each selected rosette, computes a **distance-adaptive vertical framing** (`pitch_deg` and `vfov_deg` derived from `dist_m` so close poles `< 10 m` tilt upward to capture the crown while cropping above the $-40^\circ$ capture-vehicle hood).
   - Enforces `< 1%` black sensor border (`max_black = 0.01`): when a pole's bearing sits near a $30^\circ$ seam between adjacent horizontal cameras (`cam_k = 0..5`), automatically composites the two covering ground cameras via `rosette.composite_rows` + `rosette.render_perspective_multi`.
   - Assembles a side-by-side **3-panel inspection composite** stamped with `"Imagery (c) Google"`:
     - **Panel 1 (Left) — Full Vertical Shaft View**: Captures the entire vertical profile from ground collar to overhead conductors with a center-shaft reference guide.
     - **Panel 2 (Center) — Crown & Cross-Arm Zoom (Projected $+3.5\text{ m}..+9.0\text{ m}$ Elevation Window at 2x Optical Resolution)**: Resolves primary/secondary cross-arms, pin/post insulators, fused cutouts, can transformers, and overhead conductor attachments.
     - **Panel 3 (Right) — Base & Ground-Contact Zoom (Projected $-2.6\text{ m}..+2.2\text{ m}$ Elevation Window at 2x Optical Resolution)**: Resolves the ground-line collar, timber decay/splitting, riser conduits, guy-wire anchors, and side-by-side double-pole bases.

4. **Gemini `PoleSubClassification` + Deterministic Geometric Gates (`subclassify_poles`)**
   - Sends the approach + recede 3-panel composites to Gemini on Vertex AI (`response_schema=PoleSubClassification`) alongside OpenCV LSD verticality telemetry.
   - Fuses the model response with deterministic geometric and taxonomy gates:
     - **True Utility Pole Gate**: `is_true_utility_pole` is deterministically enforced as `pole_subtype in {DISTRIBUTION_UTILITY_POLE, JOINT_USE_UTILITY_POLE, TRANSMISSION_POLE, DOUBLE_POLE_TRANSFER_PAIR}`.
     - **False-Detection Gate**: When a single-view infill candidate has low visual confidence (`confidence < 0.35`), weak OpenCV vertical support (`opencv_vertical_support < 0.25`), and `pole_subtype == SIGN_POST_OR_OTHER` (e.g., an empty building facade or sky), marks `is_false_detection = True` and separates it into `false_detection_count` rather than inflating `non_utility_vertical_count`.
     - **Double-Pole Gate**: `is_double_pole` is enforced `True` whenever `pole_subtype == DOUBLE_POLE_TRANSFER_PAIR`.
     - **OpenCV LSD Lean-Angle Gate**: Cross-checks Gemini's `lean_deg` against `cvchecks.estimate_post_lean_deg` (length-weighted median angle of near-vertical LSD segments within $\pm 15^\circ$ of vertical, clockwise-positive, gated by `cvchecks.vertical_post_support`).

---

## 2. Taxonomy & Schema (`PoleSubClassification`)

### `PoleSubType`

| Enum Value | `is_true_utility_pole` | Visual & Structural Criteria |
| :--- | :---: | :--- |
| `DISTRIBUTION_UTILITY_POLE` | `true` | Carries overhead primary/secondary electric distribution conductors, insulators, pole-mount transformers, or cutouts without a lower telecom strand. |
| `JOINT_USE_UTILITY_POLE` | `true` | Carries electric distribution at the upper crown **and** lower-tier telecom/fiber cables, splice cases, or street-light luminaires on the same shaft. |
| `TRANSMISSION_POLE` | `true` | Tall sub-transmission or transmission pole with multi-circuit cross-arms, suspension/post insulators, and high-voltage conductors. |
| `DOUBLE_POLE_TRANSFER_PAIR` | `true` | Two adjacent utility poles standing side-by-side (e.g., an older or topped pole strapped to or awaiting transfer to a replacement pole). |
| `STANDALONE_STREET_LIGHT` | `false` | Dedicated roadway/pedestrian lighting standard (metal, concrete, or fiberglass shaft with luminaire arm, fed underground with **no** overhead distribution wires). |
| `TRAFFIC_SIGNAL_MAST_ARM` | `false` | Heavy structural pole supporting traffic signal heads, pedestrian signals, or intersection mast arms without overhead power distribution lines. |
| `GUY_STUB_OR_PUSH_BRACE` | `false` | Unwired stub pole or angled push-brace pole used purely for mechanical guying/bracing. |
| `TELECOM_OR_CELL_MONOPOLE` | `false` | Dedicated small-cell/5G antenna monopole or standalone telecom drop pole with no electric distribution conductors. |
| `SIGN_POST_OR_OTHER` | `false` | Sign post, bollard, flagpole, or tree trunk mistaken for a pole. |

### Supporting Attributes

- **`material` (`AssetMaterial`)**: `WOOD`, `CONCRETE`, `METAL`, `COMPOSITE`, `BRICK`, `STONE`, `PLASTIC`, `OTHER`, `UNKNOWN`
- **`condition` (`AssetCondition`)**: `GOOD`, `FAIR`, `POOR`, `UNKNOWN`
- **`crossarm_config` (`CrossArmConfig`)**: `NONE`, `SINGLE_ARM`, `DOUBLE_ARM`, `ALLEY_ARM`, `ARMLESS_FRAMING`, `UNKNOWN`
- **`attached_equipment` (`list[PoleEquipment]`)**:
  - `OVERHEAD_CONDUCTORS`
  - `POLE_MOUNT_TRANSFORMER`
  - `STREET_LIGHT_LUMINAIRE`
  - `RISER_CONDUIT`
  - `TELECOM_SPLICE_CASE`
  - `GUY_WIRE`
  - `CAPACITOR_OR_REGULATOR`
  - `STREET_SIGN`
  - `TRAFFIC_SIGNAL`
- **`lean_deg` (`float`, `[-45.0, 45.0]`)**: Signed lean angle in degrees from vertical (clockwise-positive), fused with OpenCV LSD `estimate_post_lean_deg`.

---

## 3. BigQuery, Cloud Storage, and Vertex AI Guardrails

1. **Allow-Listed Table Only**: Query `pano_observations_latest` via `svi_geo.data.render_sql`. Key rosettes on `capture_id` (do not filter with `WHERE pano_id IS NOT NULL`).
2. **Never Select `gcs_uri`**: Always derive the Cloud Storage object path in code:
   ```
   gs://<GCS_BUCKET>/<snapshot_id>/v0/<observation_id>.jpg
   ```
3. **Dry-Run & Byte Cap**: Every BigQuery query runs with `dry_run=True` first and enforces `maximum_bytes_billed = 2_000_000_000` (`2 GB`).
4. **Inline Image Bytes Only**: Fetch JPEG bytes from Cloud Storage and pass rectified perspective composites as inline bytes (`types.Part.from_bytes`); never pass `gs://` URIs directly to Vertex AI.

---

## 4. Running the Standalone CLI (`scripts/subclassify_poles.py`)

### Prerequisites

```bash
export PROJECT_ID="your-gcp-project-id"
export GCS_BUCKET="your-svi-published-bucket"
```

### Command-Line Invocation

```bash
python street_view_insights/panoramic/skills/utility_pole_subclassification_using_panoramic_svi/scripts/subclassify_poles.py \
  --project_id "$PROJECT_ID" \
  --gcs_bucket "$GCS_BUCKET" \
  --lat 28.0502 \
  --lng -81.9601 \
  --radius_m 80 \
  --max_rosettes 6 \
  --max_poles 5 \
  --output_json ./pole_audit.json \
  --output_dir ./pole_composites
```

### CLI Flags

| Flag | Description | Default |
| :--- | :--- | :--- |
| `--project`, `--project_id`, `--project-id` | Google Cloud project ID for BigQuery and Vertex AI | `$PROJECT_ID` or `$GOOGLE_CLOUD_PROJECT` |
| `--gcs-bucket`, `--gcs_bucket` | Street View Insights Cloud Storage bucket name | `$GCS_BUCKET` |
| `--dataset` | BigQuery dataset (`imagery_insights___us` or `imagery_insights___eu`) | `imagery_insights___us` |
| `--location` | Vertex AI location | `global` (`$VERTEX_LOCATION`) |
| `--model` | Gemini model name | `gemini-3.5-flash` (`$GEMINI_MODEL`) |
| `--lat` / `--lng` or `--coordinates` | Corridor center WGS84 coordinates | Required (unless ID flag given) |
| `--capture-id`, `--pano-id`, `--observation-id` | Look up corridor center from a specific `capture_id`, `pano_id`, or `observation_id` (`ID_SQL`) | `None` |
| `--radius-m`, `--radius_m` | Search radius in metres around `(lat, lng)` or ID lookup | `80.0` |
| `--max-rosettes`, `--max_rosettes` | Maximum 7-camera rosettes to inspect along the corridor | `6` |
| `--max-poles`, `--max_poles` | Maximum candidate poles to sub-classify | `5` |
| `--output-json`, `--output_json`, `--output` | Path to write structured JSON audit report | `None` (prints to stdout) |
| `--output-dir`, `--output_dir` | Directory to save 3-panel composite PNGs | `None` |

---

## 5. Example Output JSON

```json
{
  "corridor": {
    "center_lat": 28.0502,
    "center_lng": -81.9601,
    "radius_m": 80.0,
    "rosettes_inspected": 6,
    "frames_inspected": 42,
    "bq_dry_run_gb": 0.412
  },
  "summary": {
    "candidates_evaluated": 3,
    "true_utility_pole_count": 2,
    "non_utility_vertical_count": 1,
    "false_detection_count": 0,
    "infill_recovered_poles": 1
  },
  "poles": [
    {
      "entity_id": "utility_pole_01",
      "initial_cls": "UTILITY_POLE",
      "lat": 28.050312,
      "lng": -81.960045,
      "n_panos": 3,
      "supporting_rosettes": ["cap_01", "cap_03"],
      "supporting_observations": ["o1:cap_01_1:5001ee", "o1:cap_03_2:5001ee"],
      "max_parallax_deg": 42.6,
      "opencv_vertical_support": 0.782,
      "opencv_lsd_lean_deg": 1.4,
      "pole_subtype": "JOINT_USE_UTILITY_POLE",
      "is_true_utility_pole": true,
      "is_false_detection": false,
      "material": "WOOD",
      "condition": "GOOD",
      "crossarm_config": "SINGLE_ARM",
      "attached_equipment": [
        "OVERHEAD_CONDUCTORS",
        "POLE_MOUNT_TRANSFORMER",
        "STREET_LIGHT_LUMINAIRE",
        "TELECOM_SPLICE_CASE"
      ],
      "is_double_pole": false,
      "lean_deg": 1.5,
      "confidence": 0.94,
      "evidence_summary": "Treated wooden pole carrying primary overhead distribution on a single cross-arm, a pole-mounted can transformer, a cobra-head luminaire, and a lower-tier telecom strand.",
      "inspection_composite_files": [
        "./pole_composites/utility_pole_01_view1_cap_01.png",
        "./pole_composites/utility_pole_01_view2_cap_03.png"
      ]
    }
  ],
  "saved_composite_images": [
    "./pole_composites/utility_pole_01_view1_cap_01.png",
    "./pole_composites/utility_pole_01_view2_cap_03.png"
  ],
  "cost": {
    "model": "gemini-3.5-flash",
    "calls": 18,
    "input_tokens": 14200,
    "output_tokens": 1650,
    "usd": 0.0089
  }
}
```
