# Visual QA Sign-Off Log — SVI Panoramic Reference Notebooks

Every executed notebook writes an attribution-stamped overlay grid (`OUT_DIR/overlay_grid.png` and `data/qa/<date>/<notebook>_overlay_grid.png`) via `scripts/make_overlay_grid.py`. Accepted boxes/edges are drawn in green (`#2ea043`); rejected items are drawn in red (`#d93025`) with their deterministic rejection reason (`low_post_support`, `wall_decoy`, `outside_roof_band`, `foliage`, `sky`, etc.).

## Checklist per Notebook

| Notebook | Use Case | Framing Centred? | No Visible Seams / Black Borders (`<1%`)? | Rejected Items Labelled in Red? | Agentic Code-Exec Overlay Plausible? | Attribution Present (`Imagery © Google`)? | Overlay Grid Path | Metrics / Artefact SHA-256 | Reviewer & Date |
|---|---|---|---|---|---|---|---|---|---|
| `00_explore_coverage.ipynb` | O4 Warm-up | PASS (360° strip + 7-cam sheet) | PASS (`black_fraction_max=0.0000`) | PASS (`sky_zenith_cam6`, `accepted=6, rejected=1`) | N/A (zero-Gemini) | PASS | `data/qa/2026-10-01/00_explore_coverage_overlay_grid.png` | `cd9a92205a894387` (`strip=6d0d9e8b44729a1c`) | sarthakgy (2026-10-01) |
| `house_image_discovery_with_cost.ipynb` | UC1 | PASS (`centred_views=5`) | PASS (`black_fraction_max=0.0000`) | PASS (`truncated`, `accepted=2, rejected=1`) | PASS (`agree(stories_delta=0,tol=1)`) | PASS | `data/qa/2026-10-01/house_image_discovery_with_cost_overlay_grid.png` | `86f3212a63087a9f` | sarthakgy (2026-10-01) |
| `analyze_sequential_images.ipynb` | UC2 | PASS (`located_entities=17`) | PASS (`black_fraction_max=0.0035`) | PASS (`low_post_support`, `unlocated_*`, `accepted=8, rejected=4`) | PASS (`disagree(lean_delta_deg=15.25,tol=3.0)` flagged) | PASS | `data/qa/2026-10-01/analyze_sequential_images_overlay_grid.png` | `aa90e9f76b145c6b` (`diff=7f77a54bd838f631`) | sarthakgy (2026-10-01) |
| `surface_material_detection.ipynb` | UC3 | PASS (`segments=2`) | PASS (`black_fraction_max=0.0079`) | PASS (`sidewalk_absent`, `accepted=3, rejected=3`) | PASS (`agree(luma_rel_err=0.033,grad_rel_err=0.006,tol=0.10)`) | PASS | `data/qa/2026-10-01/surface_material_detection_overlay_grid.png` | `91fcc6efcbee63eb` | sarthakgy (2026-10-01) |
| `roof_edge_tracing.ipynb` | UC4 | PASS (`accepted_edges=1`) | PASS (`black_fraction_max=0.0000`) | PASS (`foliage`, `low_sky_contact`, `no_line_segment`, `accepted=1, rejected=4`) | PASS (`agree(eave_delta_deg=1.16,tol=4.0)`) | PASS | `data/qa/2026-10-01/roof_edge_tracing_overlay_grid.png` | `8c1340928bf07f4f` | sarthakgy (2026-10-01) |
