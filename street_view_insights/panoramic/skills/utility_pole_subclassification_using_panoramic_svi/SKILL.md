---
name: utility-pole-subclassification-using-panoramic-svi
description: Sub-classify roadside vertical poles from panoramic Street View Insights (`pano_observations_latest`) into electric distribution, joint-use, transmission, and double-pole transfer structures vs. standalone street lights, signal mast arms, guy stubs, cell monopoles, and sign posts using 2D ENU triangulation and in-memory 3-panel crops. Use when auditing pole sub-types, cross-arms, equipment, or lean angles around coordinates or capture/observation IDs. Don't use for road surface material audits.
---

# Utility Pole Subclassification Using Panoramic SVI

Use this skill to locate, verify, and sub-classify roadside vertical poles along a street corridor using the Street View Insights **panoramic** view (`pano_observations_latest`), separating true overhead power/telecom utility poles from non-utility lookalikes (standalone cobra-head street lights, traffic signal mast arms, guy stubs, cell monopoles, and sign posts) and auditing pole material, cross-arm framing, attached hardware, double-pole transfers, and structural lean angle **100% in-memory** (never saving Street View or composite images to disk).

---

## Step-by-Step Pole Subclassification Methodology

Every candidate pole is verified and sub-classified through a deterministic 6-step pipeline combining multi-rosette 2D horizontal ENU geometry, in-memory multi-zone cropping, and 4 visual/geometric inspection gates:

1. **Step 1 — Corridor Discovery & 2D Horizontal ENU Triangulation**:
   - Query `pano_observations_latest` with parameterized SQL under a 2 GB dry-run cap, deriving `gs://<bucket>/<snapshot_id>/v0/<observation_id>.jpg` directly without selecting `gcs_uri`.
   - Spatially deduplicate overlapping multi-year Street View passes (`~8 m` minimum spacing) and detect candidate vertical shafts across rectified ground cameras (`cam_k in 0..5`).
   - Triangulate 3D ground coordinates using **height-invariant 2D horizontal `(East, North)` ray intersection** (`triangulate_horizontal_enu`). Because single-ray flat-ground projection drifts by `3 m–15 m` on sloped curbs and uneven terrain, every pole is intersected from `>= 2` views enforcing the **`> 10°` Parallax Rule (GDOP)** and `<= 1.5 m` residual gate, with automatic targeted `40°` zoom infill on adjacent rosettes (`K-1` / `K+1`) for single-view detections.
2. **Step 2 — In-Memory 3-Panel Multi-Zone Crop Generation**:
   - Select up to 2 rosettes per pole with maximum approach + recede azimuth parallax (`5.5 m <= dist <= 38 m`).
   - Slice an **in-memory** 3-panel inspection composite (`[1: Full Vertical Shaft | 2: Crown & Cross-Arm Zoom (2x) | 3: Base & Ground Collar Zoom (2x)]`) cropped above the capture-vehicle hood (`el >= -40°`, `< 1%` black border) and pass it **inline as bytes** (`types.Part.from_bytes`) to Gemini without writing any imagery to disk.
3. **Step 3 — Gate 1: True Utility Pole vs. False-Positive Exclusion**:
   - Verify physical overhead wire attachment or pole-mounted grid hardware.
   - **Exclude lookalikes (`is_true_utility_pole = false`)**: Reject standalone cobra-head street lights (hollow tapered metal or smooth concrete shafts fed underground with zero overhead wires), traffic signal mast arms, unenergized guy stubs, standalone sign posts, flagpoles, bollards, and tree trunks.
4. **Step 4 — Gate 2: Crown & Cross-Arm Voltage-Tier Classification**:
   - Inspect **Panel 2 (`Crown & Cross-Arm 2x Zoom`)** to classify the pole's voltage tier and crown framing (`SINGLE_ARM`, `DOUBLE_ARM`, `ALLEY_ARM`, `ARMLESS_FRAMING`, `NONE`):
     - `TRANSMISSION_POLE`: Tall lattice steel, tubular steel, or H-frame structures carrying high-voltage sub-transmission/transmission lines on long suspension or post insulator strings.
     - `DISTRIBUTION_UTILITY_POLE`: Primary distribution phase conductors mounted on pin/post insulators or cross-arms at the pole top (`has_primary_conductors = true`) and/or secondary triplex/open-wire distribution below (`has_secondary_conductors = true`), without a lower communications tier.
     - `JOINT_USE_UTILITY_POLE`: Electric distribution conductors at the upper crown plus lower-tier communication/fiber bundles (`has_telecom_attach = true`) or a street-light luminaire bracket sharing the same shaft.
     - `TELECOM_OR_CELL_MONOPOLE`: Dedicated small-cell/5G antenna monopole or telecom-only drop pole carrying low-sag communication cables at mid-span with a bare crown (`has_primary_conductors = false`).
5. **Step 5 — Gate 3: Mid-Shaft Equipment & Riser Audit**:
   - Inspect **Panel 1 (`Full Vertical Shaft`)** and **Panel 2 (`Crown & Cross-Arm 2x Zoom`)** to inventory attached grid and telecom hardware (`equipment`):
     - `OVERHEAD_CONDUCTORS`, `POLE_MOUNT_TRANSFORMER` (single-phase cylindrical can or 3-phase cluster bank), `RISER_CONDUIT` (vertical PVC/steel U-guard transitioning overhead lines underground), `CAPACITOR_OR_REGULATOR`, `GUY_WIRE` (`GUY_STUB_OR_PUSH_BRACE` if an unenergized anchor stub), `STREET_LIGHT_LUMINAIRE`, `TELECOM_SPLICE_CASE`, `STREET_SIGN`, `TRAFFIC_SIGNAL`.
6. **Step 6 — Gate 4: Base Material, Buddy-Pole & Structural Lean Audit**:
   - Inspect **Panel 3 (`Base & Ground Collar 2x Zoom`)** and fuse with deterministic OpenCV Line Segment Detector (`estimate_post_lean_deg` / `vertical_post_support`):
     - Classify shaft material (`WOOD`, `METAL`, `CONCRETE`, `COMPOSITE`) and structural condition (`GOOD`, `FAIR`, `POOR`).
     - Detect **"Buddy Poles" / "Cut-and-Kick" pole transfers** (`0.5 m–1.2 m` spacing or an old topped pole strapped/lashed to a new replacement pole -> `DOUBLE_POLE_TRANSFER_PAIR`, `is_double_pole = true`).
     - Flag structural anomalies (`structural_anomaly = true`) when `abs(lean_angle_deg) > 8.0°`, `condition == "POOR"`, `is_double_pole == true`, or visible split top / broken cross-arm / base rot is present.

---

## Sub-Classification Taxonomy

| `sub_type` | `is_true_utility_pole` | Visual & Structural Signature |
| :--- | :---: | :--- |
| `DISTRIBUTION_UTILITY_POLE` | `true` | Carries overhead primary/secondary electric distribution conductors, pin/post insulators, transformers, or risers without a lower telecom tier |
| `JOINT_USE_UTILITY_POLE` | `true` | Carries electric distribution at the upper crown **plus** mid-span telecom/fiber cables, splice closures, or a street-light luminaire arm |
| `TRANSMISSION_POLE` | `true` | Tall sub-transmission or transmission structure with multi-circuit cross-arms and long suspension/post insulator strings |
| `DOUBLE_POLE_TRANSFER_PAIR` | `true` | Two adjacent utility poles (`0.5 m–1.2 m` apart) or a topped old pole strapped to a replacement pole mid-transfer (`is_double_pole = true`) |
| `STANDALONE_STREET_LIGHT` | `false` | Dedicated roadway/pedestrian lighting standard with luminaire arm fed underground and **no** overhead utility conductors |
| `TRAFFIC_SIGNAL_MAST_ARM` | `false` | Heavy structural steel/concrete pole supporting traffic signal heads or intersection mast arms with no overhead power distribution |
| `GUY_STUB_OR_PUSH_BRACE` | `false` | Unenergized stub pole or angled push-brace pole used purely for mechanical guying/bracing |
| `TELECOM_OR_CELL_MONOPOLE` | `false` | Dedicated small-cell/5G antenna monopole or standalone telecom drop pole with no electric power distribution |
| `SIGN_POST_OR_OTHER` | `false` | Thin street sign post, bollard, flagpole, or tree trunk |

---

## Prerequisites

- `google-genai`, `google-cloud-bigquery`, `google-cloud-storage`, `pydantic`, `opencv-python-headless`, `numpy`, and `pandas` (`pip install -e street_view_insights/panoramic/svi_geo`).
- Application Default Credentials with BigQuery access, read access to your Street View Insights Cloud Storage bucket, and Vertex AI enabled in your project.

---

## Instructions

Run from the repository root:

```bash
export PROJECT_ID=YOUR_PROJECT_ID GCS_BUCKET=YOUR_FRAME_BUCKET

# 1. By GPS coordinates (searches rosettes within --radius-m, default 60 m)
python3 street_view_insights/panoramic/skills/utility_pole_subclassification_using_panoramic_svi/scripts/subclassify_poles.py \
  --project "$PROJECT_ID" \
  --gcs-bucket "$GCS_BUCKET" \
  --coordinates 28.0572,-81.9521

# 2. By panoramic capture_id (rosette key)
python3 street_view_insights/panoramic/skills/utility_pole_subclassification_using_panoramic_svi/scripts/subclassify_poles.py \
  --project "$PROJECT_ID" \
  --gcs-bucket "$GCS_BUCKET" \
  --capture-id <capture_id>

# 3. By panoramic observation_id
python3 street_view_insights/panoramic/skills/utility_pole_subclassification_using_panoramic_svi/scripts/subclassify_poles.py \
  --project "$PROJECT_ID" \
  --gcs-bucket "$GCS_BUCKET" \
  --observation-id <observation_id>
```

### Optional arguments

- `--radius-m`: Search radius in meters around `--coordinates` or the looked-up ID (default: `60.0`).
- `--dataset`: BigQuery dataset name (default: `imagery_insights___us`).
- `--model`: Gemini model name (default: `gemini_client.DEFAULT_MODEL`).
- `--location`: Vertex AI region (default: `global`).
- `--output`: Output JSON file path (prints to stdout if omitted).

### Output

```json
{
  "pole_count": 2,
  "poles": [
    {
      "pole_id": "utility_pole_73ad077b77",
      "lat": 28.057305,
      "lng": -81.952248,
      "is_true_utility_pole": true,
      "sub_type": "JOINT_USE_UTILITY_POLE",
      "material": "WOOD",
      "condition": "GOOD",
      "cross_arm": "SINGLE_ARM",
      "equipment": [
        "OVERHEAD_CONDUCTORS",
        "STREET_LIGHT_LUMINAIRE",
        "GUY_WIRE"
      ],
      "has_primary_conductors": true,
      "has_secondary_conductors": true,
      "has_telecom_attach": true,
      "is_double_pole": false,
      "lean_angle_deg": 1.1,
      "structural_anomaly": false,
      "confidence": 0.95,
      "views_used": 2,
      "parallax_deg": 24.6,
      "evidence": "Single wood cross-arm with 3 top primary phase conductors on insulators, secondary triplex below, telecom attachment at mid-span, street-light arm, and down-guy wire."
    }
  ]
}
```
