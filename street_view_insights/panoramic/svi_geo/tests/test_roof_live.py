"""Live check of the roof validator's false-accept rate on real frames (needs --run-live).

Frames are fetched at runtime with the user's credentials and never cached or committed.
"""

import numpy as np
import pytest

from svi_geo import auth, data, images, roof, rosette

LAT, LNG = 28.05047, -81.96015  # residential street used by the UC1 notebook
RADIUS_M = 80.0
N_FRAMES = 8


@pytest.mark.live
def test_random_segment_acceptance_on_real_frames_is_below_five_percent(svi_project, svi_bucket):
    from google.cloud import storage

    creds = auth.get_credentials()
    bq = data.QueryRunner(
        data.make_bigquery_client(svi_project, creds),
        allowed_tables=data.pano_tables(svi_project),
        cache_dir=None,
    )
    sql = data.pano_meta_sql(data.pano_table(svi_project))
    params = data.pano_meta_params(lat=LAT, lng=LNG, radius_m=RADIUS_M)
    assert bq.dry_run(sql, params) <= 2e9
    frames = data.normalize_frames(bq.run(sql, params))
    ground = frames[frames["cam_k"].between(0, 5)].sort_values("observation_id")
    assert len(ground) >= N_FRAMES
    fetcher = images.GcsImageFetcher(
        storage.Client(project=svi_project, credentials=creds), cache_dir=None
    )
    intr = rosette.load_intrinsics()
    rates = []
    for r in ground.head(N_FRAMES).to_dict("records"):
        uri = data.gcs_uri_for(svi_bucket, r["snapshot_id"], r["observation_id"])
        img = images.decode(fetcher.fetch(uri))
        pose = r["camera_pose"]
        axis = pose["heading"] + intr.cam_rot_delta_deg.get(int(r["cam_k"]), (0.0,))[0]
        view_img, view, black = roof.render_roof_view(img, intr, pose, axis, int(r["cam_k"]))
        assert black < 0.01
        valid = view_img.max(axis=2) > 0
        rates.append(
            roof.random_line_baseline(
                view_img, 200, seed=len(rates), valid_mask=valid,
                horizon_row=roof.horizon_row_for(view),
            )
        )  # fmt: skip
    print("random acceptance per frame:", [round(x, 3) for x in rates])
    assert float(np.mean(rates)) < 0.05


@pytest.mark.live
def test_roof_band_random_and_decoy_acceptance_on_real_roof_views(svi_project, svi_bucket):
    """Measures, on the UC4 roof views, how often the validator accepts random segments inside
    the expected roof band and level non-roof decoys (horizon, wall base, siding). These are
    reported, not gated: the validator checks that a straight image edge exists, not that it
    is a roof edge. Lines at assumed rows rarely sit on a real edge, so the LSD segments
    found in the wall zone (`wall_lines`: siding, windows, wall base) are measured as well."""
    from google.cloud import storage

    from svi_geo import sequence, views

    creds = auth.get_credentials()
    bq = data.QueryRunner(
        data.make_bigquery_client(svi_project, creds),
        allowed_tables=data.pano_tables(svi_project),
        cache_dir=None,
    )
    sql = data.pano_meta_sql(data.pano_table(svi_project))
    params = data.pano_meta_params(lat=LAT, lng=LNG, radius_m=60.0)
    assert bq.dry_run(sql, params) <= 2e9
    frames = data.normalize_frames(bq.run(sql, params))
    frames["gcs_uri"] = [
        data.gcs_uri_for(svi_bucket, s, o)
        for s, o in zip(frames["snapshot_id"], frames["observation_id"], strict=True)
    ]
    panos = sequence.build_sequences(data.panos_from_frames(frames))
    frames = frames.merge(panos[["pano_id", "seq_id"]], on="pano_id", how="left")
    intr = rosette.load_intrinsics()
    ranked = views.rank_roof_views(frames, LAT, LNG, intr, n=6, aspect=1200 / 900, max_dist_m=60.0)
    assert len(ranked) >= 2
    fetcher = images.GcsImageFetcher(
        storage.Client(project=svi_project, credentials=creds), cache_dir=None
    )
    rows = []
    for i, row in enumerate(ranked.to_dict("records")):
        img = images.decode(fetcher.fetch(row["gcs_uri"]))
        view_img, view, black = roof.render_roof_view(
            img, intr, row["camera_pose"], float(row["bearing"]), int(row["cam_k"]),
            pitch_deg=float(row["pitch"]), hfov_deg=float(row["hfov"]),
        )  # fmt: skip
        assert black < 0.01
        valid = view_img.max(axis=2) > 0
        hz = roof.horizon_row_for(view)
        band = views.roof_box(row, view)
        whole = roof.random_line_baseline(view_img, 200, i, valid, hz)
        in_band = roof.random_line_baseline(view_img, 200, i, valid, hz, region=band)
        lines = roof.straight_lines_in(view_img, views.wall_box(row, view))
        named = {**views.roof_decoys(row, view), "wall_lines": lines}
        decoys = roof.decoy_acceptance(view_img, named, valid, hz)
        decoys["n_wall_lines"] = len(lines)
        rows.append({"whole": whole, "band": in_band, **decoys})
    for k in ("whole", "band", "horizon", "wall_base", "siding", "wall_lines", "n_wall_lines"):
        vals = [r[k] for r in rows if k in r]
        mean = float(np.mean(vals)) if vals else float("nan")
        print(f"{k}: per view {[round(v, 3) for v in vals]}, mean {mean:.3f}")
    assert all(0.0 <= r["band"] <= 1.0 for r in rows)
    assert any("wall_lines" in r for r in rows), "no straight wall-zone line to measure"
    # Measured 2026-09-30 on 6 views: random in band 0.000, level decoys 0.000, wall-zone
    # LSD lines 0.529 accepted (4-150 lines per view).
