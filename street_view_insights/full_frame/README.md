# Full Frame Notebooks

This directory contains Jupyter notebooks for full-frame street view insights analysis and processing.

## Notebooks

- **[Utility Pole Full-Frame Analysis](file:///Users/sarthakgy/Desktop/insights-samples/street_view_insights/full_frame/utility_pole_full_frame_analysis.ipynb)**: Demonstrates how to analyze single full-frame images of utility poles using Gemini 3.5 Flash, overlaying BigQuery-reported bounding boxes, and calculating individual API costs.
- **[Multi-Observation Asset Analysis](file:///Users/sarthakgy/Desktop/insights-samples/street_view_insights/full_frame/multi_observation_asset_analysis.ipynb)**: Demonstrates how to group multiple Street View observations (images) of the same asset ID from BigQuery using `ARRAY_AGG`, pass them combined to Gemini 3.5 Flash in a single multimodal inference prompt, and calculate the combined API cost.
- **[Full-Frame vs Cropped Observation Comparison](file:///Users/sarthakgy/Desktop/insights-samples/street_view_insights/full_frame/full_frame_vs_cropped_comparison.ipynb)**: Demonstrates how to fetch both Full-Frame and Cropped observations for the same asset IDs, display the views side-by-side with bounding boxes drawn, and run concurrent analyses with Gemini 3.5 Flash to compare predictions, token counts, and cost differences.
- **[Full-Frame Contextual Analysis](file:///Users/sarthakgy/Desktop/insights-samples/street_view_insights/full_frame/full_frame_contextual_analysis.ipynb)**: Demonstrates the programmatic crop-then-classify pipeline. It downloads wide-angle Full-Frame images from GCS, crops out the asset using BigQuery bounding box coordinates programmatically in Python (PIL), and passes the cropped image to Gemini 3.5 Flash. This notebook showcases how combining Full-Frame contextual analysis (road type, background) with cropped asset classification resolves spatial density issues and delivers a comprehensive scene-understanding report.
