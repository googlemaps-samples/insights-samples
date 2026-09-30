# Real-imagery evaluation protocol

This page describes how the four panoramic notebooks are evaluated against human labels on
real Street View Insights imagery. **No accuracy numbers are published here yet**: they will
be added only after real labels exist and have been scored with `scripts/score_labels.py`.

## Retraction

Commit `c2b057c` ("... and 4-scene live eval") described a 4-scene live evaluation. Those
figures came from `scripts/run_notebook_eval.py` / `notebook_eval.py`, which filled in
missing results with generated values rather than measuring them. That code has been deleted
and the 4-scene figures are **retracted**. Do not quote them.

The synthetic and self-consistency tables in [`README.md`](README.md) measure different things
(simulated scenes, and agreement of the model with itself). They are not accuracy against
ground truth, and they are marked stale until `run_eval.py` is re-run.

## Sample

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

## Workflow

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

## Metrics

Every rate is reported with a 95% bootstrap confidence interval over panos
(`eval.bootstrap_ci`, fed by `eval.per_pano_counts`).

| use case | metric |
|---|---|
| UC2 | per-class detection precision and recall at IoU ≥ 0.3; dedup purity and completeness against `object_key`; duplicate rate; share of objects located |
| UC3 | material accuracy per (asset, side); sidewalk presence F1 (`present=false` is scored as ABSENT); side-swap rate |
| UC1 | visible/centred accuracy per view; attribute accuracy |
| UC4 | edge precision and recall at a mean polyline distance ≤ 5 px (same view and edge type, one-to-one); the validator's accept/reject confusion matrix |
| all | inter-annotator agreement on the repeated 20% of panos |

## Results

None yet. This section will be filled in from `score_labels.py` output once real labels
exist. It will never contain generated or placeholder values.
