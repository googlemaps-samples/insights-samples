# Full Frame Notebooks

This directory contains Jupyter notebooks for full-frame street view insights analysis and processing.

## Notebooks

- **[Utility Pole Full-Frame Analysis](file:///Users/sarthakgy/Desktop/insights-samples/street_view_insights/full_frame/utility_pole_full_frame_analysis.ipynb)**: Demonstrates how to analyze single full-frame images of utility poles using Gemini 3.5 Flash, overlaying BigQuery-reported bounding boxes, and calculating individual API costs.
- **[Multi-Observation Asset Analysis](file:///Users/sarthakgy/Desktop/insights-samples/street_view_insights/full_frame/multi_observation_asset_analysis.ipynb)**: Demonstrates how to group multiple Street View observations (images) of the same asset ID from BigQuery using `ARRAY_AGG`, pass them combined to Gemini 3.5 Flash in a single multimodal inference prompt, and calculate the combined API cost.
