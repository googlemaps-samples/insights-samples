# Visual QA Sign-Off Log — SVI Panoramic Reference Notebooks

Every executed notebook writes an attribution-stamped overlay grid (`OUT_DIR/overlay_grid.png` and `data/qa/<date>/<notebook>_overlay_grid.png`) via `scripts/make_overlay_grid.py`. Accepted boxes/edges are drawn in green (`#2ea043`); rejected items are drawn in red (`#d93025`) with their deterministic rejection reason (`low_post_support`, `wall_decoy`, `outside_roof_band`, `foliage`, `sky`, etc.).

## Checklist per Notebook

| Notebook | Use Case | Framing Centred? | No Visible Seams / Black Borders (`<1%`)? | Rejected Items Labelled in Red? | Agentic Code-Exec Overlay Plausible? | Attribution Present (`Imagery © Google`)? | Overlay Grid Path | Metrics / Artefact SHA-256 | Reviewer & Date |
|---|---|---|---|---|---|---|---|---|---|
| `00_explore_coverage.ipynb` | O4 Warm-up | PASS (360° strip + 7-cam sheet) | PASS (`black_fraction_max=0.0000`) | N/A (zero-Gemini warm-up) | N/A (zero-Gemini) | PASS | `~/tmp/svi_qa/00_explore_coverage/equirect_strip.png` | `8ed180eaf2794188` | sarthakgy (2026-10-01) |
| `house_image_discovery_with_cost.ipynb` | UC1 | PASS (`centred_views=5`) | PASS (`black_fraction_max=0.0000`) | PASS | PASS (`agree(stories_delta=0,tol=1)`) | PASS | `~/tmp/svi_qa/uc1_house/overlay_grid.png` | `d813bb283b05e9b2` | sarthakgy (2026-10-01) |
| `analyze_sequential_images.ipynb` | UC2 | PASS (`located_entities=14`) | PASS (`black_fraction_max=0.0035`) | PASS (`low_post_support` shown) | PASS (`agree(lean_delta_deg=2.52,tol=3.0)`) | PASS | `~/tmp/svi_qa/uc2_seq/overlay_grid.png` | `b27dd74e9395565b` | sarthakgy (2026-10-01) |
| `surface_material_detection.ipynb` | UC3 | PASS (`segments=2`) | PASS (`black_fraction_max=0.0079`) | PASS (kerb prior down-weight) | PASS (`agree(luma_rel_err=0.060,tol=0.10)`) | PASS | `~/tmp/svi_qa/uc3_surface/overlay_grid.png` | `a1a8ba7434a17183` | sarthakgy (2026-10-01) |
| `roof_edge_tracing.ipynb` | UC4 | PASS (`accepted_edges=2`) | PASS (`black_fraction_max=0.0000`) | PASS (`wall_decoy` / `outside_roof_band` shown) | PASS (`agree(eave_delta_deg=1.18,tol=4.0)`) | PASS | `~/tmp/svi_qa/uc4_roof/overlay_grid.png` | `a2aa026be1993968` | sarthakgy (2026-10-01) |
