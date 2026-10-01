# Visual QA Sign-Off Log — SVI Panoramic Reference Notebooks

Every executed notebook writes an attribution-stamped overlay grid (`OUT_DIR/overlay_grid.png` and `data/qa/<date>/<notebook>_overlay_grid.png`) via `scripts/make_overlay_grid.py`. Accepted boxes/edges are drawn in green (`#2ea043`); rejected items are drawn in red (`#d93025`) with their deterministic rejection reason (`low_post_support`, `wall_decoy`, `outside_roof_band`, `foliage`, `sky`, etc.).

## Checklist per Notebook

| Notebook | Use Case | Framing Centred? | No Visible Seams / Black Borders (`<1%`)? | Rejected Items Labelled in Red? | Agentic Code-Exec Overlay Plausible? | Attribution Present (`Imagery © Google`)? | Overlay Grid Path | Metrics / Artefact SHA-256 | Reviewer & Date |
|---|---|---|---|---|---|---|---|---|---|
| `00_explore_coverage.ipynb` | O4 Warm-up | PASS (360° strip + 7-cam sheet) | PASS (`black_fraction_max=0.0000`) | N/A (zero-Gemini warm-up) | N/A (zero-Gemini) | PASS | `~/tmp/svi_qa/00_explore_coverage/contact_sheet.png` | `cd9a92205a894387` (`strip=6d0d9e8b44729a1c`) | sarthakgy (2026-10-01) |
| `house_image_discovery_with_cost.ipynb` | UC1 | PASS (`centred_views=5`) | PASS (`black_fraction_max=0.0000`) | PASS | PASS (`agree(stories_delta=1,tol=1)`) | PASS | `~/tmp/svi_qa/uc1_house/overlay_grid.png` | `2791b6229b5f2b10` | sarthakgy (2026-10-01) |
| `analyze_sequential_images.ipynb` | UC2 | PASS (`located_entities=14`) | PASS (`black_fraction_max=0.0035`) | PASS (`low_post_support` shown) | PASS (`agree(lean_delta_deg=2.52,tol=3.0)`) | PASS | `~/tmp/svi_qa/uc2_seq/overlay_grid.png` | `692139331bf20747` (`diff=7f77a54bd838f631`) | sarthakgy (2026-10-01) |
| `surface_material_detection.ipynb` | UC3 | PASS (`segments=3`) | PASS (`black_fraction_max=0.0079`) | PASS (`viterbi_smoothed` / `sidewalk_absent`) | PASS (`agree(luma_rel_err=0.033,grad_rel_err=0.006,tol=0.10)`) | PASS | `~/tmp/svi_qa/uc3_surface/overlay_grid.png` | `91fcc6efcbee63eb` | sarthakgy (2026-10-01) |
| `roof_edge_tracing.ipynb` | UC4 | PASS (`accepted_edges=2`) | PASS (`black_fraction_max=0.0000`) | PASS (`wall_decoy` / `outside_roof_band` shown) | PASS (`agree(eave_delta_deg=0.83,tol=4.0)`) | PASS | `~/tmp/svi_qa/uc4_roof/overlay_grid.png` | `bda1d157c77ee597` | sarthakgy (2026-10-01) |
