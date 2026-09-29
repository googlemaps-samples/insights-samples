# Self-Calibrating the 7-Camera Rosette Intrinsics (`rosette_kb4_v1.json`)

The Street View Insights panoramic tables (`pano_observations_latest` and `pano_observations_all`) publish 7 raw wide-angle portrait frames (`3648 × 5472` pixels) per panoramic capture along with per-camera exterior orientation (`camera_pose`: `latitude`, `longitude`, `altitude`, `heading`, `pitch`, `roll`), but **do not publish camera lens intrinsics** (focal length, principal point, or radial distortion coefficients).

Without lens calibration, treating these wide-angle fisheye frames as rectilinear pinhole images—or asking an LLM to guess `cv2.undistort` parameters—introduces severe angular errors (`30°–70°` near the frame edges), breaks multi-view ray triangulation, and warps straight architectural lines such as roof edges.

This document explains how `svi_geo` **self-calibrates** the 7-camera rosette directly from public panoramic imagery in BigQuery (`svi_geo/intrinsics/rosette_kb4_v1.json`) using deterministic multi-view geometry, and how anyone can reproduce or re-run the calibration test on their own dataset.

---

## 1. Camera & Lens Mathematical Model

### 1.1 The 7-Camera Rosette Geometry
Each panoramic capture (`pano_id`) consists of 7 observations with IDs of the form `o1:<pano_id>_<k>:5001ee` (`k ∈ {0..6}`):
- **Cameras `0..5`**: 6 horizontal cameras arranged in a ring spaced approximately `60°` apart in yaw around a rosette of radius $R_{\text{rosette}} \approx 0.0844\text{ m}$ (`8.44 cm`, measured directly from the per-camera `camera_pose` geographic centers). Adjacent horizontal cameras have alternating slight pitch offsets and share an overlapping field of view at off-axis angles $\theta \in [25^\circ, 42^\circ]$.
- **Camera `6`**: Zenith (sky-facing) camera, excluded from horizontal roadside and building analysis.

### 1.2 Kannala–Brandt (KB4) Fisheye Projection
Because all 6 horizontal sensors (`3648 × 5472`) use identical optics, `svi_geo/rosette.py` models them with a shared **Kannala–Brandt 4-term equidistant fisheye projection** (`KB4`):

Given a 3D ray $\mathbf{d}_{\text{cam}} = (X_c, Y_c, Z_c)^\top$ in the camera frame ($+X_c$ right, $+Y_c$ down, $+Z_c$ forward along the optical axis), the incidence angle $\theta$ from the optical axis is:

$$\theta = \arctan2\!\left(\sqrt{X_c^2 + Y_c^2},\, Z_c\right)$$

The distorted radial distance $r(\theta)$ (in pixels) from the principal point $(c_x, c_y)$ is modeled by the odd polynomial:

$$r(\theta) = f \cdot \left(\theta + k_1 \theta^3 + k_2 \theta^5 + k_3 \theta^7 + k_4 \theta^9\right)$$

where:
- $f = f_x = f_y$ is the focal length in pixels (`px / rad` at $\theta \to 0$),
- $(c_x, c_y)$ is the optical center (principal point) in pixels,
- $(k_1, k_2, k_3, k_4)$ are the radial distortion coefficients, and
- $(u, v) = \left(c_x + r(\theta)\frac{X_c}{\sqrt{X_c^2 + Y_c^2}},\, c_y + r(\theta)\frac{Y_c}{\sqrt{X_c^2 + Y_c^2}}\right)$ are the pixel coordinates.

To absorb small mechanical mounting tolerances between the 6 horizontal sensors and their nominal `camera_pose` metadata, the calibration also fits a small 3-DoF per-camera rotation delta $\Delta \mathbf{r}_k = (\Delta \text{yaw}_k, \Delta \text{pitch}_k, \Delta \text{roll}_k)$ in degrees for $k \in \{0..5\}$ (with $\sum_k \Delta \mathbf{r}_k = \mathbf{0}$ for gauge fixing).

---

## 2. Self-Supervision Signals (Zero Ground-Truth Labels Required)

The calibration pipeline (`svi_geo/calibrate.py`, `svi_geo/calib_features.py`, `svi_geo/calib_real.py`, and `scripts/fit_intrinsics.py`) estimates the parameter vector

$$\Theta = \left(f,\, c_x,\, c_y,\, k_1,\, k_2,\, k_3,\, \{\Delta \mathbf{r}_k\}_{k=0}^5\right)$$

via damped non-linear least squares (`scipy.optimize.least_squares` with Huber robust loss) combining **three geometric constraints** extracted automatically with OpenCV:

1. **Intra-Panorama Adjacent-Camera Ray Agreement (`intra_matches`)**:
   - SIFT/ORB keypoints are matched with Lowe's ratio test and RANSAC between adjacent cameras $k$ and $(k+1) \bmod 6$ within the same `pano_id`.
   - Because the two cameras are separated by only $\sim 8.4\text{ cm}$, distant scene points unproject to nearly parallel world rays $\hat{\mathbf{u}}_k(\Theta)$ and $\hat{\mathbf{u}}_{k+1}(\Theta)$ (corrected for the small rosette baseline).
   - **Residual**: angular discrepancy $\arccos\!\left(\hat{\mathbf{u}}_k(\Theta) \cdot \hat{\mathbf{u}}_{k+1}(\Theta)\right)$ in degrees.

2. **Inter-Panorama Epipolar Consistency Along Drive Sequences (`sequence_matches`)**:
   - Drive sequences are reconstructed by `svi_geo.sequence.build_sequences` (~`10.2–10.7 m` spacing between consecutive panoramas).
   - Keypoints matched between consecutive panoramas $(P_t, P_{t+1})$ with known baseline $\mathbf{t}_{t \to t+1} = \mathbf{C}_{t+1} - \mathbf{C}_t$ must satisfy the coplanarity (epipolar) constraint.
   - **Residual**: across-epipolar angular error $\arcsin\!\left(\left|\hat{\mathbf{b}} \cdot \hat{\mathbf{n}}_{\text{epipolar}}\right|\right)$.

3. **Plumb-Line / Verticality Constraint (`select_chains`)**:
   - In urban and suburban scenes, building walls, window frames, and utility poles are vertical in world East-North-Up (`ENU`) coordinates ($\hat{\mathbf{z}}_{\text{world}} = (0, 0, 1)^\top$).
   - Long edge chains extracted near the horizon must project to great-circle planes containing the gravity vector $\hat{\mathbf{z}}_{\text{world}}$.
   - **Residual**: angle between the fitted plane normal of the unprojected pixel chain and $\hat{\mathbf{z}}_{\text{world}}$.

---

## 3. Fitted Parameters & Safe Rendering Cone

Running `scripts/fit_intrinsics.py` on **82 training panoramas** across 4 geographic snapshots (with **20 whole-sequence held-out panoramas** strictly excluded from training) produces `svi_geo/intrinsics/rosette_kb4_v1.json`:

| Parameter | Fitted Value (`rosette_kb4_v1.json`) | Description |
| :--- | :--- | :--- |
| `width`, `height` | `3648`, `5472` | Portrait frame dimensions in pixels |
| `fx`, `fy` | `2847.13 px` | Fitted focal length (`fx = fy`) |
| `cx`, `cy` | `1903.92 px`, `2721.08 px` | Fitted principal point (optical center) |
| `k1`, `k2`, `k3`, `k4` | `+0.032218`, `-0.036814`, `-0.028218`, `0.0` | Kannala–Brandt polynomial distortion coefficients |
| `rosette_radius_m` | `0.08438 m` (`8.44 cm`) | Horizontal camera ring radius from `camera_pose` centers |
| `max_theta_deg` | `58.19°` (`116.38°` full FOV) | Frame-edge maximum incidence angle |
| **Safe rendering cone** | **`48.9°` half-FOV** (`97.8°` cone) | `99.5th` percentile of matched feature angles; used by notebooks (`off_axis + hfov/2 <= 48.9°`) to guarantee `< 2%` black border and zero corner fold-over |

### Why Notebooks Clamp Crops to the `48.9°` Safe Cone
In `rosette_kb4_v1.json`, `max_theta_deg` is set to `58.19°` so full-frame diagnostic renders can cover the outer corners of the sensor. However, because inter-camera feature matches concentrate at $\theta \le 48.9^\circ$ (the `99.5th` percentile of matched keypoints), the higher-order negative polynomial terms ($k_2 \theta^5 + k_3 \theta^7$) are unconstrained in the extreme sky/hood corners ($\theta \in [49^\circ, 58^\circ]$).

In our 80-batch recursive evaluation (`house_image_discovery_with_cost.ipynb` and `agentic_roof_edge_detection.ipynb`), clamping perspective crop requests to:

$$\text{off\_axis\_deg} + \frac{\text{hfov\_deg}}{2} \le 48.9^\circ$$

eliminated corner fold-over distortion (`0.14°` median roof-edge angle residual) and reduced black-border clipping to `< 2%` (`99.2%` valid crop rate across 1,000 houses).

---

## 4. Held-Out Validation Metrics

Evaluated on the **20 held-out panoramas** (from drive sequences never seen during fitting), comparing the fitted `rosette_kb4_v1.json` model against an uncalibrated default placeholder:

| Held-Out Validation Metric | Uncalibrated Placeholder | Self-Calibrated (`rosette_kb4_v1.json`) | Acceptance Gate |
| :--- | :--- | :--- | :--- |
| **Intra-pano adjacent-camera ray error (median / p90)** | `32.50°` / `33.50°` | **`0.703°`** / `2.012°` | Median `< 1.0°` (**PASS**) |
| **Across-epipolar angular error (median / p90)** | — | **`0.120°`** / `0.380°` | `< 0.5°` (**PASS**) |
| **Inter-pano consecutive capture error (median / p90)** | `1.220°` / `8.000°` | **`0.043°`** / `0.430°` | `< 0.5°` (**PASS**) |
| **Adjacent-camera seam vertical alignment (`0.03°/px` render)** | No valid seam matches | **`2.70 px`** (`0.081°`) | Median `< 3.0 px` (**PASS**) |
| **Plumb-line verticality residual (median)** | `4.100°` | **`0.705°`** | `5.8×` improvement over uncalibrated |

---

## 5. How to Reproduce the Calibration & Run the Tests Yourself

### Step 1: Set Up the Environment
From the repository root (`insights-samples/`):

```bash
python3 -m venv .venv
.venv/bin/pip install -e "street_view_insights/panoramic/svi_geo[dev,notebooks]"
```

### Step 2: Run the Offline Geometry & Calibration Unit Tests
The unit test suite in `tests/test_calibrate.py`, `tests/test_calib_features.py`, `tests/test_calib_real.py`, and `tests/test_rosette.py` verifies synthetic parameter recovery, forward/inverse `project_kb4`/`unproject_kb4` round-trips (`< 1e-6 rad`), and held-out gate assertions without requiring network access:

```bash
.venv/bin/pytest street_view_insights/panoramic/svi_geo/tests/test_rosette.py \
                 street_view_insights/panoramic/svi_geo/tests/test_calibrate.py \
                 street_view_insights/panoramic/svi_geo/tests/test_calib_features.py \
                 street_view_insights/panoramic/svi_geo/tests/test_calib_real.py -v
```

### Step 3: Fetch Calibration Panoramas from BigQuery & GCS (Optional Full Re-Fit)
If you want to re-run the calibration from scratch against `imagery-insights-sandbox.imagery_insights___us.pano_observations_latest`:

```bash
cd street_view_insights/panoramic/svi_geo

# 1. Sample training & whole-sequence held-out panoramas across AOIs (dry-run checked < 2 GB)
../../../.venv/bin/python scripts/fetch_calibration_panos.py \
    --project imagery-insights-sandbox \
    --out data/calib_panos.parquet

# 2. Extract multi-view SIFT/ORB matches, fit KB4 intrinsics, and evaluate on held-out sequences
../../../.venv/bin/python scripts/fit_intrinsics.py \
    --use-sequence \
    --out svi_geo/intrinsics/rosette_kb4_v1.json \
    --report data/calib_report.md
```

### Step 4: Inspect or Compare Against Custom Intrinsics Locally
All intermediate files under `street_view_insights/panoramic/svi_geo/data/` are gitignored (`street_view_insights/panoramic/svi_geo/.gitignore`) so you can store local calibration reports, cached frames, or private reference specifications in `svi_geo/data/` without risk of committing them to git.
