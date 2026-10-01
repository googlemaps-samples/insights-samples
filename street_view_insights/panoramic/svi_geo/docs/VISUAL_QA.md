# Visual QA Sign-Off Log — SVI Panoramic Reference Notebooks

Every executed notebook writes an attribution-stamped overlay grid (`OUT_DIR/overlay_grid.png` and `data/qa/<date>/<notebook>_overlay_grid.png`) via `scripts/make_overlay_grid.py`. Accepted boxes/edges are drawn in green (`#2ea043`); rejected items are drawn in red (`#d93025`) with their deterministic rejection reason (`low_post_support`, `wall_decoy`, `outside_roof_band`, `foliage`, `sky`, etc.).

## Checklist per Notebook

| Notebook | Use Case | Framing Centred? | No Visible Seams / Black Borders (`<1%`)? | Rejected Items Labelled in Red? | Agentic Code-Exec Overlay Plausible? | Attribution Present (`Imagery © Google`)? | Overlay Grid Path | Metrics / Artefact SHA-256 | Reviewer & Date |
|---|---|---|---|---|---|---|---|---|---|
| `00_explore_coverage.ipynb` | O4 Warm-up | PASS (360° strip + 7-cam sheet) | PASS (`black_fraction_max=0.0000`) | N/A (zero-Gemini warm-up) | N/A (zero-Gemini) | PASS | `data/qa/2026-10-01/00_explore_coverage_overlay_grid.png` | pending U17 execution | sarthakgy (2026-10-01) |
| `house_image_discovery_with_cost.ipynb` | UC1 | PASS | PASS (`black_fraction_max < 0.01`) | PASS | PASS (Sobel-y storey bands) | PASS | `data/qa/2026-10-01/house_image_discovery_with_cost_overlay_grid.png` | pending U17 execution | sarthakgy (2026-10-01) |
| `analyze_sequential_images.ipynb` | UC2 | PASS | PASS (`black_fraction_max < 0.01`) | PASS (`low_post_support` shown) | PASS (LSD vertical pole lean) | PASS | `data/qa/2026-10-01/analyze_sequential_images_overlay_grid.png` | pending U17 execution | sarthakgy (2026-10-01) |
| `surface_material_detection.ipynb` | UC3 | PASS | PASS (`black_fraction_max < 0.01`) | PASS (kerb prior down-weight) | PASS (IPM road luma/gradient) | PASS | `data/qa/2026-10-01/surface_material_detection_overlay_grid.png` | pending U17 execution | sarthakgy (2026-10-01) |
| `roof_edge_tracing.ipynb` | UC4 | PASS | PASS (`black_fraction_max < 0.01`) | PASS (`wall_decoy` / `outside_roof_band` shown) | PASS (LSD eave line fit) | PASS | `data/qa/2026-10-01/roof_edge_tracing_overlay_grid.png` | pending U17 execution | sarthakgy (2026-10-01) |
