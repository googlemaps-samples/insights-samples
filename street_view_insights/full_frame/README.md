# Full Frame

This directory contains Jupyter notebooks and skills for full-frame street view insights analysis and processing.

## Notebooks

- **[Utility Pole Full-Frame Analysis](./notebooks/utility_pole_full_frame_analysis.ipynb)**: Demonstrates how to analyze single full-frame images of utility poles using Gemini 3.5 Flash, overlaying BigQuery-reported bounding boxes, and calculating individual API costs.
- **[Multi-Observation Asset Analysis](./notebooks/multi_observation_asset_analysis.ipynb)**: Demonstrates how to group multiple Street View observations (images) of the same asset ID from BigQuery using `ARRAY_AGG`, pass them combined to Gemini 3.5 Flash in a single multimodal inference prompt, and calculate the combined API cost.
- **[Full-Frame vs Cropped Observation Comparison](./notebooks/full_frame_vs_cropped_comparison.ipynb)**: Demonstrates how to fetch both Full-Frame and Cropped observations for the same asset IDs, display the views side-by-side with bounding boxes drawn, and run concurrent analyses with Gemini 3.5 Flash to compare predictions, token counts, and cost differences.
- **[Full-Frame Contextual Analysis](./notebooks/full_frame_contextual_analysis.ipynb)**: Demonstrates the programmatic crop-then-classify pipeline. It downloads wide-angle Full-Frame images from GCS, crops out the asset using BigQuery bounding box coordinates programmatically in Python (PIL), and passes the cropped image to Gemini 3.5 Flash. This notebook showcases how combining Full-Frame contextual analysis (road type, background) with cropped asset classification resolves spatial density issues and delivers a comprehensive scene-understanding report.

## Skills {#skills}

### Pre-requesites

1. Install the [Antigravity CLI](https://antigravity.google/product/antigravity-cli).

2. Set up your [Application Default Credentials](http://https://docs.cloud.google.com/docs/authentication/provide-credentials-adc) (ADC):

```sh
gcloud auth application-default login
```

3. _(Recommended)_ Set your GCP project ID in your shell environment:

```sh
export GOOGLE_CLOUD_PROJECT="YOUR_PROJECT_ID"
```

4. _(Recommended)_ Use a python [virtual environment](https://docs.python.org/3/library/venv.html) for any python package dependencies
installed by the skill:

```sh
# create virtual environment
$ python3 -m venv .venv
$ source .venv/bin/activate
$ pip install -r requirements.txt
```

### Loading the skill

Run the Antigravity CLI:

```sh
$ agy
```

Load the skills directly (only `analyze_utility_pole` is used in this example):

```
Load skill at 'street_view_insights/full_frame/skills/analyze_utility_pole'
Load skill at 'street_view_insights/full_frame/skills/vegetation_encroachment_detection_using_full_frame_svi'
```

> Alternatively, you can move the code to one of the standard Antigravity CLI folders as described [here](https://antigravity.google/docs/cli/plugins#agent-skills).

Run the skill:

```
/analyze-utility-pole Inspect the utility pole from asset t1:...

/analyze-utility-pole Reconcile images for asset t1:...

/analyze-utility-pole Compare images for asset t1:...
```

### Cleanup

If you created a python virtual environment above, you can easily deactivate and remove it as follows:

```sh
$ deactivate

$ rm -rf .venv
```
