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
