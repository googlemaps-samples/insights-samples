# Self-Calibrating the 7-Camera Rosette Intrinsics (`rosette_kb4_v1.json`)

The Street View Insights panoramic tables (`pano_observations_latest` and `pano_observations_all`) publish 7 raw wide-angle portrait frames (`3648 × 5472` pixels) per panoramic capture along with per-camera exterior orientation (`camera_pose`: `latitude`, `longitude`, `altitude`, `heading`, `pitch`, `roll`), but **do not publish camera lens intrinsics** (focal length, principal point, or radial distortion coefficients).

Without lens calibration, treating these wide-angle frames as rectilinear pinhole images (or asking an LLM to guess `cv2.undistort` parameters) gives large angular errors toward the frame edges, breaks multi-view ray triangulation, and bends straight lines such as roof edges. For reference, the uncalibrated placeholder model in `svi_geo` has a held-out adjacent-camera ray error of `32.5°` median (see Section 4).

This document explains how `svi_geo` **self-calibrates** the 7-camera rosette from panoramic imagery in BigQuery (`svi_geo/intrinsics/rosette_kb4_v1.json`) using deterministic multi-view geometry, and how to reproduce the calibration.

---

## 1. Camera & Lens Mathematical Model

### 1.1 The 7-Camera Rosette Geometry
Each panoramic capture (`pano_id`) consists of 7 observations with IDs of the form `o1:<pano_id>_<k>:5001ee` (`k ∈ {0..6}`):
- **Cameras `0..5`**: 6 horizontal cameras arranged in a ring about `60°` apart in yaw, on a rosette of radius $R_{\text{rosette}} \approx 0.0844\text{ m}$ (`8.44 cm`, measured from the per-camera `camera_pose` positions, not fitted). Adjacent horizontal cameras share an overlapping field of view near their left/right frame edges.
- **Camera `6`**: Zenith (sky-facing) camera, excluded from horizontal roadside and building analysis.

### 1.2 Kannala–Brandt (KB4) Fisheye Projection
`svi_geo/rosette.py` models the 6 horizontal sensors (`3648 × 5472`) with one shared **Kannala–Brandt equidistant fisheye projection** (`KB4`):

Given a 3D ray $\mathbf{d}_{\text{cam}} = (X_c, Y_c, Z_c)^\top$ in the camera frame ($+X_c$ right, $+Y_c$ down, $+Z_c$ forward along the optical axis), the incidence angle $\theta$ from the optical axis is:

$$\theta = \arctan2\!\left(\sqrt{X_c^2 + Y_c^2},\, Z_c\right)$$

The distorted radial distance $r(\theta)$ (in pixels) from the principal point $(c_x, c_y)$ is modeled by the odd polynomial:

$$r(\theta) = f \cdot \left(\theta + k_1 \theta^3 + k_2 \theta^5 + k_3 \theta^7 + k_4 \theta^9\right)$$

where:
- $f = f_x = f_y$ is the focal length in pixels (`px / rad` at $\theta \to 0$),
- $(c_x, c_y)$ is the optical center (principal point) in pixels,
- $(k_1, k_2, k_3, k_4)$ are the radial distortion coefficients, and
- $(u, v) = \left(c_x + r(\theta)\frac{X_c}{\sqrt{X_c^2 + Y_c^2}},\, c_y + r(\theta)\frac{Y_c}{\sqrt{X_c^2 + Y_c^2}}\right)$ are the pixel coordinates.

To absorb small mounting differences between the 6 horizontal sensors and their nominal `camera_pose` metadata, the calibration also fits a small 3-DoF per-camera rotation delta $\Delta \mathbf{r}_k = (\Delta \text{yaw}_k, \Delta \text{pitch}_k, \Delta \text{roll}_k)$ in degrees for $k \in \{0..5\}$ (with $\sum_k \Delta \mathbf{r}_k = \mathbf{0}$ for gauge fixing).

---

## 2. Self-Supervision Signals (No Ground-Truth Labels)

The calibration pipeline (`svi_geo/calibrate.py`, `svi_geo/calib_features.py`, `svi_geo/calib_real.py`, and `scripts/fit_intrinsics.py`) estimates the parameter vector

$$\Theta = \left(f,\, c_x,\, c_y,\, k_1,\, k_2,\, k_3,\, \{\Delta \mathbf{r}_k\}_{k=0}^5\right)$$

with robust non-linear least squares (`scipy.optimize.least_squares`, `loss="soft_l1"`) over **three geometric constraints** extracted with OpenCV:

1. **Intra-Panorama Adjacent-Camera Ray Agreement (`intra_matches`)**:
   - SIFT keypoints are matched with Lowe's ratio test and filtered with RANSAC between adjacent cameras $k$ and $(k+1) \bmod 6$ within the same `pano_id`.
   - Because the two cameras are separated by only $\sim 8.4\text{ cm}$, distant scene points unproject to nearly parallel world rays $\hat{\mathbf{u}}_k(\Theta)$ and $\hat{\mathbf{u}}_{k+1}(\Theta)$ (corrected for the small rosette baseline).
   - **Residual**: angular discrepancy $\arccos\!\left(\hat{\mathbf{u}}_k(\Theta) \cdot \hat{\mathbf{u}}_{k+1}(\Theta)\right)$ in degrees.

2. **Inter-Panorama Epipolar Consistency Along Drive Sequences (`sequence_matches`)**:
   - Drive sequences are reconstructed by `svi_geo.sequence.build_sequences`.
   - Keypoints matched between consecutive panoramas $(P_t, P_{t+1})$ with known baseline $\mathbf{t}_{t \to t+1} = \mathbf{C}_{t+1} - \mathbf{C}_t$ must satisfy the coplanarity (epipolar) constraint.
   - **Residual**: across-epipolar angular error $\arcsin\!\left(\left|\hat{\mathbf{b}} \cdot \hat{\mathbf{n}}_{\text{epipolar}}\right|\right)$.

3. **Plumb-Line / Verticality Constraint (`select_chains`)**:
   - Building walls, window frames and utility poles are vertical in world East-North-Up (`ENU`) coordinates ($\hat{\mathbf{z}}_{\text{world}} = (0, 0, 1)^\top$).
   - Long edge chains extracted near the horizon should project to great-circle planes containing the gravity vector $\hat{\mathbf{z}}_{\text{world}}$.
   - **Residual**: angle between the fitted plane normal of the unprojected pixel chain and $\hat{\mathbf{z}}_{\text{world}}$.

---

## 3. Fitted Parameters & Valid Ray Range

Running `scripts/fit_intrinsics.py` on **82 training panoramas** (4 imagery snapshots) with **20 held-out panoramas** from whole drive sequences excluded from training produces `svi_geo/intrinsics/rosette_kb4_v1.json`:

| Parameter | Fitted Value (`rosette_kb4_v1.json`) | Description |
| :--- | :--- | :--- |
| `width`, `height` | `3648`, `5472` | Portrait frame dimensions in pixels |
| `fx`, `fy` | `2847.13 px` | Fitted focal length (`fx = fy`) |
| `cx`, `cy` | `1903.92 px`, `2721.08 px` | Fitted principal point (optical center) |
| `k1`, `k2`, `k3`, `k4` | `+0.032218`, `-0.036814`, `-0.028218`, `0.0` | Kannala–Brandt distortion coefficients (`k4` fixed at 0) |
| `rosette_radius_m` | `0.08438 m` (`8.44 cm`) | Horizontal camera ring radius from `camera_pose` positions |
| `max_theta_deg` | `58.19°` | Farthest frame-edge midpoint angle (`57.19°`) + `1°`; set after the fit so full-frame renders reach the frame edges |

### Where the model gives valid rays

The fitted model only describes rays that land on the sensor. Unprojecting the frame-edge midpoints with `svi_geo.rosette.theta_of_pixel` gives these off-axis angles:

| Frame edge (pixel) | Off-axis angle $\theta$ |
| :--- | :--- |
| Left edge `(0, cy)` | `38.14°` |
| Right edge `(W-1, cy)` | `34.89°` |
| Top edge `(cx, 0)` | `56.39°` |
| Bottom edge `(cx, H-1)` | `57.19°` |

Because the frames are portrait and the principal point is not centred, the **horizontal half-width is only `34.9°` (right) / `38.1°` (left)**, and it is asymmetric. The frame corners lie farther from the principal point than the radius where the fitted polynomial stops being monotonic (about `3036 px`), so the model gives no valid ray there.

The `48.9°` value that appears in the JSON history and in some code is **not a safe crop cone**. It is only the `99.5th` percentile of the off-axis angles of the matched features used in the fit. It exceeds the horizontal sensor edge on both sides, so a perspective crop sized with `off_axis + hfov/2 <= 48.9°` extends past the left/right sensor edge and contains black (no-data) border. To keep a crop inside the sensor, bound its horizontal extent on each side by the edge angle above for that side, or check the rendered view with `rosette.valid_mask`.

The angles above can be reproduced with `rosette.load_intrinsics()` and `rosette.theta_of_pixel(intr, np.array([u, v]))`. The model is also least constrained at large $\theta$, because few feature matches lie there.

---

## 4. Held-Out Validation Metrics

Evaluated on the **20 held-out panoramas** (from drive sequences never seen during fitting), comparing the fitted `rosette_kb4_v1.json` model against the uncalibrated default placeholder. These are the same numbers as in [`svi_geo/README.md`](svi_geo/README.md), which is the source of truth. Not all gates pass.

| Metric (median / p90) | Fitted | Default placeholder | Gate |
| :--- | :--- | :--- | :--- |
| Intra-pano angular error | `0.70°` / `2.01°` | `32.5°` / `33.5°` | median `< 1°` **PASS**; p90 `< 2°` **FAIL** (just over); stretch median `< 0.5°` **FAIL** |
| Across- / along-epipolar | `0.12°` / `0.38°`, `0.64°` / `1.99°` | — | along-epipolar is inflated by near-field parallax |
| Consecutive-pano error | `0.04°` / `0.43°` | `1.22°` / `8.0°` | consistency check only (matches selected with the fitted model) |
| Verticality | `0.71°` / `4.1°` | `4.1°` / `15.0°` | median `< 0.5°` **FAIL** |
| Seam vertical displacement (`0.03°/px` render) | `2.7 px` / `21 px` | no seam matches | `< 3 px` **PASS** |
| 3× better than default | metric 1 **PASS** | metric 2 not computable (default seams have no matches) | |

---

## 5. How to Reproduce the Calibration

### Step 1: Set Up the Environment
From the repository root (`insights-samples/`):

```bash
python3 -m venv .venv
.venv/bin/pip install -e "street_view_insights/panoramic/svi_geo[dev,notebooks]"
```

### Step 2: Run the Offline Geometry & Calibration Unit Tests
`tests/test_rosette.py`, `tests/test_calibrate.py`, `tests/test_calib_features.py` and `tests/test_calib_real.py` check the KB4 forward/inverse round-trips, agreement with OpenCV's fisheye model, and parameter recovery on synthetic calibration problems. They need no network access:

```bash
.venv/bin/pytest street_view_insights/panoramic/svi_geo/tests/test_rosette.py \
                 street_view_insights/panoramic/svi_geo/tests/test_calibrate.py \
                 street_view_insights/panoramic/svi_geo/tests/test_calib_features.py \
                 street_view_insights/panoramic/svi_geo/tests/test_calib_real.py -v
```

### Step 3: Fetch Calibration Panoramas from BigQuery & GCS (Optional Full Re-Fit)
To re-run the calibration from scratch against `imagery-insights-sandbox.imagery_insights___us.pano_observations_latest` (the default paths below are relative to `svi_geo/`):

```bash
cd street_view_insights/panoramic/svi_geo

# 1. Sample training and whole-sequence held-out panoramas (dry-run checked before querying)
../../../.venv/bin/python scripts/fetch_calibration_panos.py \
    --project imagery-insights-sandbox \
    --out data/calib_panos.parquet

# 2. Extract SIFT matches, fit KB4 intrinsics, and evaluate on the held-out sequences
../../../.venv/bin/python scripts/fit_intrinsics.py \
    --panos data/calib_panos.parquet \
    --use-sequence \
    --out svi_geo/intrinsics/rosette_kb4_v1.json \
    --report data/calib_report.md
```

Other options: `fetch_calibration_panos.py` also accepts `--radius-m`, `--train-per-aoi`, `--pairs-per-aoi`, `--heldout-per-aoi`, `--seed` and `--no-download`; `fit_intrinsics.py` also accepts `--metrics-json`, `--seam-dir`, `--radius-m` and `--iterations`. Run either script with `--help` for the full list.

### Step 4: Keep Local Outputs Out of Git
Everything under `street_view_insights/panoramic/svi_geo/data/` is gitignored (`street_view_insights/panoramic/svi_geo/.gitignore`), so local calibration reports and cached frames stored there are not committed.
