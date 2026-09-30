"""Live check of the UC4 vegetation screen on the audit's real roof views (needs --run-live).

The three views are the ones the UC4 notebook chose in the first live run: two are filled with
tree canopy (the old HSV screen scored them 0.30 and 0.48 and let them through) and one shows
the roof clearly. Frames are fetched at runtime with the user's credentials and never cached
or committed.
"""

import pytest

from svi_geo import auth, data, images, roof, rosette, sequence, views

LAT, LNG = 28.05047, -81.96015  # the UC4 notebook's target building (Lakeland, FL)
RADIUS_M = 60.0
VIEW_W, VIEW_H = 1200, 900
# pano id prefix -> expected rejection (canopy-hidden True, clear roof False)
AUDIT_VIEWS = {"-twF4vBR": True, "7rEQBqep": False, "yFEJH1Mw": True}


@pytest.mark.live
def test_vegetation_screen_rejects_the_canopy_views_and_keeps_the_clear_roof(
    svi_project, svi_bucket
):
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
    frames["gcs_uri"] = [
        data.gcs_uri_for(svi_bucket, s, o)
        for s, o in zip(frames["snapshot_id"], frames["observation_id"], strict=True)
    ]
    panos = sequence.build_sequences(data.panos_from_frames(frames))
    frames = frames.merge(panos[["pano_id", "seq_id"]], on="pano_id", how="left")
    intr = rosette.load_intrinsics()
    ranked = views.rank_roof_views(
        frames, LAT, LNG, intr, n=12, aspect=VIEW_W / VIEW_H, max_dist_m=RADIUS_M
    )
    fetcher = images.GcsImageFetcher(
        storage.Client(project=svi_project, credentials=creds), cache_dir=None
    )
    seen = {}
    for row in ranked.to_dict("records"):
        key = next((k for k in AUDIT_VIEWS if row["pano_id"].startswith(k)), None)
        if key is None:
            continue
        img = images.decode(fetcher.fetch(row["gcs_uri"]))
        rimg, view, _ = roof.render_roof_view(
            img, intr, row["camera_pose"], float(row["bearing"]), int(row["cam_k"]),
            pitch_deg=float(row["pitch"]), hfov_deg=float(row["hfov"]),
            width=VIEW_W, height=VIEW_H,
        )  # fmt: skip
        seen[key] = views.occlusion_screen(rimg, views.roof_box(row, view))
    print({k: round(v["foliage_frac"], 3) for k, v in seen.items()})
    assert set(seen) == set(AUDIT_VIEWS), f"audit views not found: {set(AUDIT_VIEWS) - set(seen)}"
    for key, hidden in AUDIT_VIEWS.items():
        assert seen[key]["rejected"] is hidden, (key, seen[key])
