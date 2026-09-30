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

## Black fraction vs dark pixels

`rosette.view_black_fraction` (and `black_fraction_max` in the notebooks) is analytic sensor
coverage only: the share of view pixels whose ray misses the sensor or the lens model. It
does not see the dataset's black redaction blobs inside a frame, which are image content.
The notebooks therefore also print `dark_pixel_max`, measured on the images sent to Gemini
with `images.dark_pixel_fraction` (every channel <= 8). It counts coverage gaps, redaction
blobs and any genuinely black object alike.

## Evaluation (`scripts/run_eval.py`)

Accuracy against human labels on real imagery is measured with the label kit described in
[`EVALUATION.md`](EVALUATION.md) (`scripts/make_label_kit.py`, `scripts/score_labels.py`).
The 4-scene live evaluation from commit `c2b057c` is retracted there.

Earlier versions of this README carried result tables for the synthetic dedup benchmark and a
two-drive self-consistency run, with pass/fail gates. They were produced before the
clustering fixes (8 m house eps, a fixed 15 m single-view house range) and the self-consistency
numbers measure agreement between two answers of the same model family, not accuracy, so the
tables have been removed rather than kept as passing gates. Re-run the modes below to get
current numbers:

- `--synthetic`: dedup on simulated detections along real drive paths (purity, completeness,
  duplicate rate, location error against the simulated truth). The simulator places objects
  with the same ground assumption as the pipeline, so it is not an independent check.
- `--self-consistency`: cross-view presence checks and repeat-pass recall on real imagery.
  These measure consistency only; the presence prompt bounds confirmed offsets by hfov / 6
  (`selection_bound_deg`).

### Hand labels (`--labels`)

The eval can score against hand labels in the CSV format of
`tests/fixtures/labels_small.csv` (one row per box, with `object_key` linking
boxes of the same object):

```bash
python scripts/run_eval.py --labels my_labels.csv --pipeline-output entities.json
```

`scripts/make_label_kit.py` renders the views to label and writes the CSV template; see
[`EVALUATION.md`](EVALUATION.md).
