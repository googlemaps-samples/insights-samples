"""svi_geo: geometry + Gemini helpers for Street View Insights panoramic (rosette) imagery.

Modules:
  geo            WGS84 / ECEF / local ENU conversions, bearings.
  rosette        7-camera rosette model: KB4 fisheye intrinsics, pixel <-> world bearing.
  data           Guarded BigQuery access to the pano views only; gcs_uri derivation.
  calibrate      Pano-only self-calibration of the shared rosette intrinsics.
  sequence       Drive-sequence reconstruction from capture time + distance.
  triangulate    Multi-view ray intersection and single-view ranging.
  entities       Cross-view dedup of discrete objects (poles, signs, houses).
  smoothing      Continuous-asset (road/sidewalk/...) label smoothing and segments.
  schemas        Pydantic response schemas shared with Gemini.
  gemini_client  Inline-bytes Gemini runner with concurrency, budget and cost tracking.
  simulate/eval  Synthetic scenes and evaluation metrics.
"""

__version__ = "0.1.0"
