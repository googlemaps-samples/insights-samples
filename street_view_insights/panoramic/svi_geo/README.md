# svi_geo

`svi_geo` holds the geometry, drive-sequence, de-duplication and Gemini helpers
used by the Street View Insights **panoramic** notebooks in `../notebooks/`.

Install (from the repo root):

```bash
python3 -m venv .venv
.venv/bin/pip install -e "street_view_insights/panoramic/svi_geo[dev,notebooks]"
.venv/bin/pytest street_view_insights/panoramic/svi_geo/tests -q            # offline
GCS_BUCKET=YOUR_FRAME_BUCKET SVI_PROJECT=YOUR_PROJECT_ID \
  .venv/bin/pytest street_view_insights/panoramic/svi_geo/tests -q -m live --run-live  # BigQuery/GCS/Gemini
```

The scripts in `scripts/` take the frame bucket from `--gcs-bucket` or `$GCS_BUCKET`; the
bucket is never discovered by selecting `gcs_uri`.

## Modules

| module | purpose |
|---|---|
| `config` | explicit `PROJECT_ID` / `GCS_BUCKET` resolution; fails fast on placeholders |
| `geo` | ENU / haversine / bearing helpers |
| `rosette` | KB4 fisheye model for the 7-camera rosette, per-camera pose, perspective rendering, `undistort`, camera selection |
| `data` | parameterized, dry-run-first, byte-capped queries on the pano tables; cheap `gcs_uri_for` |
| `sequence` | drive-sequence reconstruction, measured spacing, camera roles |
| `images` | GCS fetch (opt-in disk cache with a 24 h TTL), fast JPEG decode |
| `attribution` | "Imagery © Google" credit for figures and folium maps |
| `triangulate`, `entities` | multi-view ray triangulation and per-class entity clustering / dedup |
| `smoothing` | HMM / Viterbi smoothing of per-pano labels along a drive; segments |
| `schemas`, `gemini_client` | typed Gemini outputs; async runner with call cap, concurrency and cost log |
| `simulate`, `eval`, `pipeline` | synthetic scenes on real drive paths, metrics, end-to-end pipeline |
| `calibrate`, `calib_features`, `calib_real` | rosette intrinsics fitting (`scripts/fit_intrinsics.py`) |

## Rosette calibration (`intrinsics/rosette_kb4_v1.json`)

The pano tables have no intrinsics, so the model is fitted with
`scripts/fit_intrinsics.py`. The fit uses feature matches between neighbouring
cameras of the same panorama and between consecutive panoramas: 82 training
panoramas, and 20 held-out panoramas from whole drive sequences.

**Held-out split (deviation).** The plan split on `FARM_FINGERPRINT(pano_id)`.
The fit instead holds out every drive sequence with `sha1(seq_id) < 0.25`, so
no training panorama shares a drive with a held-out one.

**Fitted values.** f = 2847 px, cx = 1904, cy = 2721,
k = (0.0322, −0.0368, −0.0282, 0). The rosette radius is 0.084 m, measured
from `camera_pose`.

**`max_theta` (deviation).** In the fit, the 99.5th-percentile feature angle
was 48.9°. `max_theta` was then set to the frame-edge angle, 58.2°, so that
renders cover the whole frame (see the JSON `notes`). Neither number is a safe
crop cone: the horizontal sensor edges are at 38.1° (left) and 34.9° (right).
Size views with `rosette.max_view_fov` / `rosette.best_camera_for_view`, which
check each side of the sensor.

Held-out metrics:

| metric (median / p90) | fitted | default placeholder | gate |
|---|---|---|---|
| intra-pano angular error | 0.70° / 2.01° | 32.5° / 33.5° | median < 1° PASS; p90 < 2° FAIL (just over); stretch < 0.5° FAIL |
| across- / along-epipolar | 0.12° / 0.38°, 0.64° / 1.99° | | along-epipolar is inflated by near-field parallax |
| consecutive-pano error | 0.04° / 0.43° | 1.22° / 8.0° | consistency check only (matches selected with the fitted model) |
| verticality | 0.71° / 4.1° | 4.1° / 15.0° | median < 0.5° FAIL |
| seam vertical displacement (0.03°/px) | 2.7 px / 21 px | no seam matches | < 3 px PASS |
| 3× better than default | metric 1 PASS | metric 2 not computable (default seams have no matches) | |

Notes on the seam check:

- It uses 0.03°/px renders; the plan's 0.09°/px figure was an arithmetic error.
- Only the vertical component is scored, because the rosette baseline
  produces horizontal parallax.

## Evaluation (`scripts/run_eval.py`)

> **Stale results.** The tables below were produced before the clustering fixes: at that time
> houses were clustered with an 8 m eps, and single-view houses were placed at a fixed 15 m
> range (the "single-view only" p90 of 15.0 m is that constant). Houses now use a 5 m eps.
> A single-view house is placed only from an untruncated box bottom and is `unlocated`
> otherwise. The tables have not been re-run with the current code, so treat them as
> historical until `run_eval.py` is re-run.

### Synthetic dedup (`--synthetic`)

The synthetic scenes use real drive paths and per-camera poses: up to 150
panoramas per AOI in 3 AOIs (Paris, Salt Lake City, Osaka), with 2 seeds.

Noise model:

- pose noise of 0.5 m / 0.3°;
- 20 % dropout, 10 % false positives, 5 % class confusion.

Results at σ = 1° bearing noise, as means over AOIs × seeds:

| method | purity | completeness | dup rate | V-measure | loc err median / p90 (m) |
|---|---|---|---|---|---|
| **pipeline (calibrated)** | **0.939** | **0.875** | **0.480** | **0.936** | **0.56 / 2.70** |
| pipeline (placeholder intrinsics) | 0.810 | 0.253 | 5.88 | 0.756 | 11.3 / 25.9 |
| single-view only | 0.784 | 0.633 | 2.77 | 0.819 | 2.04 / 15.0 |
| B1: 12 m + DBSCAN 3 m | 0.778 | 0.194 | 6.14 | 0.737 | 9.9 / 23.4 |
| B1 with calibrated intrinsics | 0.773 | 0.199 | 6.23 | 0.735 | 5.3 / 22.5 |
| B0: no dedup | 1.000 | 0.092 | 10.2 | 0.767 | 13.7 / 24.8 |

Acceptance checks (calibrated pipeline at σ = 1°):

- purity ≥ 0.9: PASS
- completeness ≥ 0.8: PASS
- median location error ≤ 1.5 m: PASS
- p90 location error ≤ 4 m: PASS
- V-measure ≥ 1.25 × B1: PASS
- duplicate rate ≤ B1 / 2: PASS
- duplicate rate ≤ 0.15: **FAIL (0.48)**

Most remaining duplicates come from the simulated 10 % false positives and
from class-confused single views, not from splits of real objects. With bearing noise alone the duplicate rate is 0.03–0.12 (Paris diagnostic
run).

Caveat: the simulator places objects on the ground using the same
nearest-camera ground assumption as the pipeline.

Results at σ = 0.5° and σ = 2° are in `data/eval_<date>_synthetic.md`.

### Real-data self-consistency (`--self-consistency`)

Run on Osaka with 9 + 9 panoramas from two drives over the same road, using
Gemini `gemini-3.5-flash`. There is no ground truth, so these checks measure
consistency only.

| metric | run 1 | run 2 | target |
|---|---|---|---|
| cross-view confirmation (Gemini re-asks at the projected location) | 0.875 (32 checks) | 0.865 (37 checks) | ≥ 0.75 PASS |
| median azimuth offset | 3.29° | 3.23° (signed −0.59°; houses 4.1°, signs 3.1°, poles 3.2°) | < 2° FAIL |
| repeat-pass entity recall A in B | 0.32 | 0.24 (multi-view only: 0.26) | ≥ 0.7 FAIL |
| Gemini calls / est. cost | 140 / $0.37 | 145 / $0.37 | |

What the results show:

- The signed offset is close to 0, so there is no systematic heading error.
  The absolute offset is mainly box-centre noise, which is largest for wide
  objects such as houses.
- Repeat-pass recall is low even for multi-view entities. Gemini's detections
  from one pass to the next are unstable: the per-class stability is 0.35–0.59.
  The two drives also cover only about 90 m, so overlap at the ends is
  partial.
- Only Osaka had two drives over the same road with at least 9 panoramas
  each.
- Presence checks are answered by the same model family, so they are
  correlated with its own errors.
- The presence prompt only accepts an object in the central third of the
  crop, so confirmed offsets are bounded by hfov / 6 (`selection_bound_deg`,
  6.7° for the 40° crops). The offsets are partly set by that bound, not
  purely measured.

### Hand labels (`--labels`)

The eval can score against hand labels in the CSV format of
`tests/fixtures/labels_small.csv` (one row per box, with `object_key` linking
boxes of the same object):

```bash
python scripts/run_eval.py --labels my_labels.csv --pipeline-output entities.json
```

A label-kit generator script was not written (deviation from the plan).
