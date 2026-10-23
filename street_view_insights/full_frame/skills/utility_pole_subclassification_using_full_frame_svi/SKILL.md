---
name: utility-pole-subclassification-using-full-frame-svi
description: Sub-classify cataloged ASSET_CLASS_UTILITY_POLE entities in Street View Insights full_frame_observations_latest using pixel bbox and multi-angle 3648x5472 Full-Frame views into 9 utility and lookalike sub-types with in-memory 3-panel crops. Use when auditing pole sub-types, cross-arms, equipment, or lean around coordinates, asset_id, or observation_id. Don't use for unindexed poles in SV_PANO (use utility-pole-subclassification-using-panoramic-svi) or SV_CROPPED_ASSETS.
---

# Utility Pole Subclassification Using Full-Frame SVI

Use this skill to verify and sub-classify cataloged utility pole candidates (`asset_type = 'ASSET_CLASS_UTILITY_POLE'`) in the Street View Insights **Full-Frame** view (`full_frame_observations_latest`). By combining pre-computed BigQuery pixel bounding boxes (`bbox`) with the full `3648 × 5472` camera frame across multiple viewing angles, this skill slices **in-memory** 3-panel multi-zone composites (`[1: Contextual Full Shaft | 2: Crown & Cross-Arm Zoom (2x) | 3: Base & Ground Collar Zoom (2x)]`) without writing any imagery to disk, separating true energized/telecom utility poles from cataloged lookalikes (such as unenergized guy-stub poles and standalone street lights) at ~10× lower token cost than raw panoramic discovery.

---

## Step-by-Step Pole Subclassification Methodology

Every cataloged `ASSET_CLASS_UTILITY_POLE` candidate is verified and sub-classified through a deterministic 6-step pipeline:

1. **Step 1 — Catalog Discovery & Same-Exposure Proposal Deduplication**:
   - Query `full_frame_observations_latest` directly (`~0.75–1.08 GB` dry-run scan under a 2 GB safety cap, avoiding the `2.31 GB` `latest_observations` UNION view) for `asset_type = 'ASSET_CLASS_UTILITY_POLE'` without selecting `gcs_uri` (reconstructed via `gs://{gcs_bucket}/{snapshot_id}/v0/{observation_id}.jpg`).
   - Collapse jittered duplicate `observation_id` bounding-box proposals generated on the exact same camera exposure by grouping on `(asset_id, capture_time, round(cam_lat, 5), round(cam_lng, 5))` and retaining the best-centered box.
2. **Step 2 — Multi-View Hygiene & `> 10°` Azimuth Parallax Selection**:
   - Filter valid exposures to `4.5 m <= distance_m <= 40.0 m` and non-edge-clipped `bbox` height `>= 300 px` (eliminating single-view far-range ghosts `> 40 m` away).
   - Compute the camera-to-pole azimuth bearing from `camera_pose.(latitude, longitude)` to `location.(latitude, longitude)` and select the sharpest primary view near the horizontal frame center (`|bbox_cx - 1824| < 1200`) plus a secondary view separated by `>= 10°` in azimuth parallax.
   - Check `< 3.5 m` pairwise asset proximity across the corridor to flag potential buddy poles (`is_double_pole`) or duplicate catalog entries.
3. **Step 3 — In-Memory 3-Panel Multi-Zone Crop Slicing around `bbox`**:
   - Fetch the `3648 × 5472` Full-Frame JPEG into memory (zero disk writes) and use the pre-computed pixel `bbox` (`xmin, ymin, xmax, ymax`) to slice a 3-panel composite:
     - **Panel 1 (`1: FULL SHAFT`)**: Full pole height plus contextual margins, stamped with subtle cyan corner ticks on `bbox` to anchor Gemini to the exact target `asset_id`.
     - **Panel 2 (`2: CROWN & CROSS-ARM (2X)`)**: Upper crown (`ymin - 0.18*h_box` to `ymin + 0.45*h_box`) with wide `±1.8*w_box` horizontal context so full cross-arms, insulators, and luminaire arms are never clipped.
     - **Panel 3 (`3: BASE & GROUND (2X)`)**: Lower shaft and ground collar (`ymax - 0.40*h_box` to `ymax + 0.15*h_box`) with `±1.8*w_box` horizontal context to reveal riser conduits, down-guy anchors, and adjacent buddy-pole bases.
4. **Step 4 — Gate 1: True Utility Pole vs. False-Positive Exclusion**:
   - Confirm physical overhead conductor attachment or pole-mounted utility hardware.
   - **Exclude lookalikes (`is_true_utility_pole = false`)**: Reject unenergized `GUY_STUB_POLE`s (short wood brace/anchor stubs supporting only a guy wire and diagonal down-guy anchor with zero energized conductors), standalone cobra-head street lights (`STREET_LIGHT_ONLY` with underground feed), traffic signals, sign posts, and trees (`OTHER_NON_UTILITY`).
5. **Step 5 — Gate 2 & Gate 3: Crown Voltage-Tier & Mid-Shaft Equipment Audit**:
   - Inspect **Panel 2 (`Crown & Cross-Arm 2x Zoom`)** and **Panel 1 (`Full Shaft`)** to classify:
     - `sub_type`: `TRANSMISSION`, `DISTRIBUTION_PRIMARY`, `DISTRIBUTION_SECONDARY`, `TELECOM_ONLY`, `JOINT_USE_LIGHT`, `SERVICE_RISER_POLE`, `GUY_STUB_POLE`, `STREET_LIGHT_ONLY`, or `OTHER_NON_UTILITY`.
     - `cross_arm`: `NONE`, `SINGLE_WOOD`, `DOUBLE_WOOD`, `STEEL_DAVIT`, `FIBERGLASS_BRACKET`, or `H_FRAME`.
     - `equipment`: `TRANSFORMER_CAN`, `RISER_CONDUIT`, `CAPACITOR_BANK`, `RECLOSER_SWITCH`, `FUSE_CUTOUT`, `GUY_WIRE`, `STREET_LIGHT_LUMINARY`, `SPLICE_CLOSURE`.
     - Conductor tiers: `has_primary_conductors`, `has_secondary_conductors`, and `has_telecom_attach`.
6. **Step 6 — Gate 4: Base Material, Buddy-Pole & Structural Lean Audit**:
   - Inspect **Panel 3 (`Base & Ground 2x Zoom`)** and fuse with OpenCV Line Segment Detector (`LSD`) shaft geometry to classify:
     - `material` (`WOOD`, `METAL`, `CONCRETE`, `FIBERGLASS`) and `condition` (`GOOD`, `FAIR`, `DAMAGED`).
     - `is_double_pole`: `"Buddy Poles"` / `"Cut-and-Kick"` pole transfers (`0.5 m–1.2 m` spacing or an old topped pole lashed to a replacement pole).
     - `lean_angle_deg` and `structural_anomaly` (`true` when `abs(lean_angle_deg) > 8.0°`, `condition == "DAMAGED"`, or `is_double_pole == true`).

---

## Sub-Classification Taxonomy

| `sub_type` | `is_true_utility_pole` | Visual & Structural Signature |
| :--- | :---: | :--- |
| `TRANSMISSION` | `true` | Tall lattice/tubular steel, concrete, or H-frame structure with long suspension/post insulator strings carrying high-voltage lines |
| `DISTRIBUTION_PRIMARY` | `true` | Carries 1–3+ high-voltage primary phase conductors on pin/post insulators or cross-arms at the pole top |
| `DISTRIBUTION_SECONDARY` | `true` | Carries low-voltage open-wire or multiplexed triplex secondary distribution and residential service drops below primary height |
| `TELECOM_ONLY` | `true` | Supports communication/fiber-optic bundles (thick black insulated cables with splice closures at mid-span) and a bare crown |
| `JOINT_USE_LIGHT` | `true` | Carries overhead electric/telecom utility conductors **plus** a cobra-head or decorative street-light luminary arm |
| `SERVICE_RISER_POLE` | `true` | Utility pole with a heavy vertical riser conduit (`RISER_CONDUIT` U-guard/PVC pipe) transitioning overhead lines underground |
| `GUY_STUB_POLE` | `false` | Short, unenergized stub/brace pole supporting only overhead guy strands and a diagonal down-guy anchor wire (`GUY_WIRE`) |
| `STREET_LIGHT_ONLY` | `false` | Standalone roadway lighting pole fed by underground conduit with **zero** overhead utility wires |
| `OTHER_NON_UTILITY` | `false` | Traffic signal mast arm, standalone sign post, camera pole, flagpole, or tree trunk |

---

## Prerequisites

- `google-genai`, `google-cloud-bigquery`, `google-cloud-storage`, `pydantic`, `opencv-python-headless`, `pillow`, and `numpy`.
- Application Default Credentials with BigQuery access, read access to your Street View Insights Cloud Storage bucket, and Vertex AI enabled in your project.

---

## Instructions

Run from the repository root:

```bash
export PROJECT_ID=YOUR_PROJECT_ID GCS_BUCKET=YOUR_FRAME_BUCKET

# 1. By GPS coordinates (audits cataloged poles within --radius-m, default 60 m)
python3 street_view_insights/full_frame/skills/utility_pole_subclassification_using_full_frame_svi/scripts/subclassify_poles.py \
  --project "$PROJECT_ID" \
  --gcs-bucket "$GCS_BUCKET" \
  --coordinates 28.0502,-81.9601

# 2. By cataloged asset_id
python3 street_view_insights/full_frame/skills/utility_pole_subclassification_using_full_frame_svi/scripts/subclassify_poles.py \
  --project "$PROJECT_ID" \
  --gcs-bucket "$GCS_BUCKET" \
  --asset-id "t1:f6fcefb3890686f307aa7fa909672ba1:ffff01ee"

# 3. By full-frame observation_id
python3 street_view_insights/full_frame/skills/utility_pole_subclassification_using_full_frame_svi/scripts/subclassify_poles.py \
  --project "$PROJECT_ID" \
  --gcs-bucket "$GCS_BUCKET" \
  --observation-id <observation_id>
```

### Optional arguments

- `--radius-m`: Search radius in meters around `--coordinates` (default: `60.0`).
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
      "pole_id": "t1:f6fcefb3890686f307aa7fa909672ba1:ffff01ee",
      "lat": 28.050317,
      "lng": -81.960038,
      "is_true_utility_pole": true,
      "sub_type": "JOINT_USE_LIGHT",
      "material": "WOOD",
      "condition": "GOOD",
      "cross_arm": "SINGLE_WOOD",
      "equipment": [
        "STREET_LIGHT_LUMINARY",
        "GUY_WIRE"
      ],
      "has_primary_conductors": true,
      "has_secondary_conductors": true,
      "has_telecom_attach": true,
      "is_double_pole": false,
      "lean_angle_deg": 1.2,
      "structural_anomaly": false,
      "confidence": 0.95,
      "views_used": 2,
      "parallax_deg": 51.3,
      "evidence": "Treated wood joint-use distribution pole with top primary conductors, secondary triplex, street-light luminary arm, telecom cable, and down-guy wire."
    },
    {
      "pole_id": "t1:d59ecc1fe527dd837ccb421b0611fef7:ffff01ee",
      "lat": 28.050167,
      "lng": -81.960039,
      "is_true_utility_pole": false,
      "sub_type": "GUY_STUB_POLE",
      "material": "WOOD",
      "condition": "GOOD",
      "cross_arm": "NONE",
      "equipment": [
        "GUY_WIRE"
      ],
      "has_primary_conductors": false,
      "has_secondary_conductors": false,
      "has_telecom_attach": false,
      "is_double_pole": false,
      "lean_angle_deg": 2.4,
      "structural_anomaly": false,
      "confidence": 0.93,
      "views_used": 2,
      "parallax_deg": 48.7,
      "evidence": "Unenergized wood guy-stub pole terminating at an overhead span guy strand with a diagonal down-guy anchored into the grass and zero energized conductors."
    }
  ]
}
```
