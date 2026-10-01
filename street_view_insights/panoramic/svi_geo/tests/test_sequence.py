import dataclasses
import math

import numpy as np
import pandas as pd
import pytest

from svi_geo import geo, sequence

T0 = pd.Timestamp("2024-06-01T10:00:00Z")


def _track(
    n, spacing_m, dt_s, bearing_deg=90.0, start_enu=(0.0, 0.0), t0=T0, snap="s1", prefix="p"
):
    rows = []
    b = math.radians(bearing_deg)
    for i in range(n):
        e = start_enu[0] + i * spacing_m * math.sin(b)
        nn = start_enu[1] + i * spacing_m * math.cos(b)
        lat, lng, _ = geo.enu_to_lla(e, nn, 0.0, 48.8, 2.37)
        rows.append(
            {
                "pano_id": f"{prefix}{i:03d}",
                "snapshot_id": snap,
                "capture_time": t0 + pd.Timedelta(seconds=i * dt_s),
                "lat": float(lat),
                "lng": float(lng),
            }
        )
    return pd.DataFrame(rows)


def _n_seq(out):
    return out["seq_id"].nunique()


@pytest.mark.parametrize("spacing,dt", [(10.0, 1.2), (5.0, 0.6)])
def test_single_track_is_one_ordered_sequence(spacing, dt):
    df = _track(20, spacing, dt).sample(frac=1.0, random_state=0)  # shuffled input
    out = sequence.build_sequences(df)
    assert _n_seq(out) == 1
    assert list(out.sort_values("seq_idx")["pano_id"]) == [f"p{i:03d}" for i in range(20)]
    stats = sequence.spacing_stats(df)
    assert stats["median_m"] == pytest.approx(spacing, rel=0.01)


def test_long_time_gap_splits():
    a = _track(10, 10.0, 1.2)
    b = _track(
        10,
        10.0,
        1.2,
        start_enu=(100.0, 0.0),
        t0=T0 + pd.Timedelta(seconds=11 * 1.2 + 40),
        prefix="q",
    )
    out = sequence.build_sequences(pd.concat([a, b]))
    assert _n_seq(out) == 2


def test_spatial_jump_splits():
    a = _track(10, 10.0, 1.2)
    b = _track(
        10, 10.0, 1.2, start_enu=(90.0 + 60.0, 0.0), t0=T0 + pd.Timedelta(seconds=12.0), prefix="q"
    )
    out = sequence.build_sequences(pd.concat([a, b]))
    assert _n_seq(out) == 2


def test_interleaved_vehicles_split():
    a = _track(15, 10.0, 1.2)
    b = _track(
        15,
        10.0,
        1.2,
        bearing_deg=0.0,
        start_enu=(0.0, 300.0),
        t0=T0 + pd.Timedelta(seconds=0.6),
        prefix="q",
    )
    out = sequence.build_sequences(pd.concat([a, b]))
    assert _n_seq(out) == 2
    for _, g in out.groupby("seq_id"):
        assert g["pano_id"].str[0].nunique() == 1


def test_snapshots_are_partitioned():
    a = _track(10, 10.0, 1.2, snap="s1")
    b = _track(10, 10.0, 1.2, snap="s2", prefix="q")
    out = sequence.build_sequences(pd.concat([a, b]))
    assert _n_seq(out) == 2


def test_travel_bearing_eastbound_and_ends_safe():
    out = sequence.build_sequences(_track(10, 10.0, 1.2, bearing_deg=90.0))
    tb = sequence.travel_bearing(out)
    np.testing.assert_allclose(tb, 90.0, atol=0.01)
    single = sequence.build_sequences(_track(1, 10.0, 1.2))
    assert np.isnan(sequence.travel_bearing(single)).all()


def test_neighbours():
    out = sequence.build_sequences(_track(10, 10.0, 1.2))
    nb = sequence.neighbours(out, "p005", k=2)
    assert list(nb["pano_id"]) == ["p003", "p004", "p006", "p007"]
    assert list(sequence.neighbours(out, "p000", k=2)["pano_id"]) == ["p001", "p002"]


def test_camera_roles_eastbound():
    headings = [55, 115, 175, -125, -65, -5]
    frames = pd.DataFrame(
        {
            "observation_id": [f"o1:P_{k}:5001ee" for k in range(7)],
            "camera_pose": [{"heading": h, "pitch": 0.0} for h in headings]
            + [{"heading": 0.0, "pitch": 87.0}],
        }
    )
    roles = sequence.camera_roles(frames, 90.0)
    assert roles["front"]["camera_pose"]["heading"] == 115
    assert roles["back"]["camera_pose"]["heading"] == -65
    assert roles["right"]["camera_pose"]["heading"] == 175
    assert roles["left"]["camera_pose"]["heading"] == -5
    assert "sky" not in roles
    assert "sky" in sequence.camera_roles(frames, 90.0, include_sky=True)


@pytest.mark.live
def test_spacing_paris_live():
    from svi_geo import auth, data

    runner = data.QueryRunner(
        data.make_bigquery_client(credentials=auth.get_credentials()),
        cache_dir=data.DEFAULT_QUERY_CACHE,
    )
    frames = runner.run(
        data.PANO_META_SQL,
        data.pano_meta_params(lat=48.81, lng=2.45, radius_m=500.0),
    )
    panos = data.panos_from_frames(frames)
    stats = sequence.spacing_stats(panos)
    print("Paris 500 m spacing stats:", stats)
    assert 4.0 <= stats["median_m"] <= 12.0
    seqs = sequence.build_sequences(panos)
    assert seqs["seq_id"].nunique() >= 1


def test_identical_capture_times_do_not_crash_or_merge_far_panos():
    """Two panos sharing a timestamp (duplicate rows / two vehicles) are handled deterministically."""
    a = _track(10, 10.0, 1.2)
    b = _track(1, 10.0, 1.2, start_enu=(5.0, 0.0), prefix="dup")  # same time as a's first pano
    far = _track(1, 10.0, 1.2, start_enu=(0.0, 5000.0), prefix="far")  # same time, 5 km away
    out = sequence.build_sequences(pd.concat([a, b, far], ignore_index=True))
    assert len(out) == 12
    assert out["seq_id"].notna().all()
    far_seq = out.loc[out["pano_id"] == "far000", "seq_id"].item()
    assert (out["seq_id"] == far_seq).sum() == 1
    ids = out.loc[out["seq_id"] == out.loc[out["pano_id"] == "p005", "seq_id"].item()]
    assert ids["seq_idx"].is_unique


# ----------------------------------------------------------------------------- Task 9

from svi_geo import rosette  # noqa: E402

INTR = rosette.DEFAULT_INTRINSICS


def _rows(heading0):
    rows = []
    for k in range(7):
        pitch = 90.0 if k == rosette.SKY_CAMERA else 0.0
        pose = {"heading": (heading0 + 60.0 * k) % 360, "pitch": pitch, "roll": 0.0,
                "latitude": 48.85, "longitude": 2.35, "altitude": 35.0}  # fmt: skip
        rows.append({"observation_id": f"o1:PANO_{k}:5001ee", "cam_k": k, "camera_pose": pose})
    return rows


@pytest.mark.parametrize(("role", "off"), [("front", 0.0), ("left", -90.0), ("right", 90.0)])
def test_road_view_yaw_is_travel_plus_role_offset(role, off):
    assert sequence.road_view_yaw(80.0, role) == pytest.approx((80.0 + off) % 360)


def test_road_view_is_centred_on_travel_even_when_cameras_are_25_deg_off():
    travel = 80.0
    rv = sequence.road_view(_rows(travel + 25.0), INTR, travel, "front", pitch_deg=-22.0)
    assert rv is not None
    assert rv.view.yaw_deg == pytest.approx(travel)
    assert rv.view.pitch_deg == -22.0
    black = rosette.view_black_fraction(
        INTR, rv.choice.row["camera_pose"], rv.view, rv.choice.cam_k
    )
    assert black < 0.01


def test_hood_row_masks_rows_below_the_hood_elevation():
    pose = {"heading": 0.0, "pitch": 0.0, "roll": 0.0}
    k = 0
    yaw = INTR.cam_rot_delta_deg.get(k, (0.0,))[0]
    view = rosette.PerspectiveView(yaw, -22.0, 70.0, 512, 384)  # bottom edge ~-50 deg
    row = rosette.hood_row(view, pose, INTR, -40.0, cam_k=k)
    assert 0 < row < view.height
    _, el_at = view.pixel_to_bearing(view.cx, row)
    assert float(el_at) == pytest.approx(-40.0, abs=1.5)
    level = rosette.PerspectiveView(yaw, 0.0, 70.0, 512, 384)  # bottom edge ~-27 deg
    assert rosette.hood_row(level, pose, INTR, -40.0, cam_k=k) == level.height


def test_road_view_crops_rows_below_the_hood():
    rv = sequence.road_view(_rows(0.0), INTR, 0.0, "front", pitch_deg=-22.0, hood_elev_deg=-40.0)
    assert 0 < rv.keep_rows < rv.view.height
    img = np.full((5472 // 8, 3648 // 8, 3), 90, np.uint8)
    out = sequence.render_road_view(img, INTR, rv)
    assert out.shape[0] == rv.keep_rows


# ----------------------------------------------------------------------------- Task 12 (live)
# On the real rosette the travel direction falls on the seam between two cameras (headings
# travel +-30 deg), so no single camera can show a 40 deg front view. NARROW limits every
# camera to a 45 deg cone, like the real sensor's horizontal extent.
NARROW = dataclasses.replace(INTR, max_theta_deg=45.0)


def test_front_view_on_a_camera_seam_is_composited_from_the_two_flanking_cameras():
    travel = 80.0
    rows = _rows(travel + 30.0)  # cameras at travel +-30, +-90, +-150
    single = rosette.best_camera_for_view(rows, NARROW, travel, -22.0, 4 / 3, min_hfov=40.0)
    assert single is None  # the seam defeats every single camera
    rv = sequence.road_view(rows, NARROW, travel, "front", pitch_deg=-22.0)
    assert rv is not None
    assert rv.view.yaw_deg == pytest.approx(travel) and rv.view.hfov_deg >= 40.0
    assert sorted(int(r["cam_k"]) for r in rv.rows) == [0, 5]
    assert rv.black < 0.01
    assert rv.black == pytest.approx(rosette.view_black_fraction_multi(NARROW, rv.rows, rv.view))


def test_composited_road_view_takes_each_half_from_the_nearer_camera():
    travel = 80.0
    rv = sequence.road_view(_rows(travel + 30.0), NARROW, travel, "front", pitch_deg=-22.0)
    imgs = {int(r["cam_k"]): np.full((5472 // 8, 3648 // 8, 3), 20 + 10 * int(r["cam_k"]),
                                     np.uint8) for r in rv.rows}  # fmt: skip
    out = sequence.render_road_view(imgs, NARROW, rv)
    assert out.shape[0] == rv.keep_rows
    w = out.shape[1]
    assert np.all(out[: rv.keep_rows // 2, : w // 4] == 70)  # left: camera 5 (travel - 30)
    assert np.all(out[: rv.keep_rows // 2, 3 * w // 4 :] == 20)  # right: camera 0 (travel + 30)
    assert np.mean(out == 0) < 0.01


def test_road_view_uses_one_camera_when_one_covers_the_view():
    rv = sequence.road_view(_rows(80.0), NARROW, 80.0, "front", pitch_deg=-22.0)
    assert len(rv.rows) == 1 and rv.rows[0] is rv.choice.row
    assert rv.black == pytest.approx(
        rosette.view_black_fraction(NARROW, rv.choice.row["camera_pose"], rv.view, rv.choice.cam_k)
    )


# ----------------------------------------------------------------------------- F5
@pytest.mark.parametrize(("offset", "n_rows"), [(30.0, 2), (0.0, 1)], ids=["seam", "single"])
def test_black_sent_is_the_black_share_of_the_cropped_image(offset, n_rows):
    travel = 80.0
    rv = sequence.road_view(_rows(travel + offset), NARROW, travel, "front", pitch_deg=-22.0,
                            hood_elev_deg=-32.0)  # fmt: skip
    assert len(rv.rows) == n_rows and 0 < rv.keep_rows < rv.view.height
    full = np.full((NARROW.height, NARROW.width, 3), 200, np.uint8)
    out = sequence.render_road_view({int(r["cam_k"]): full for r in rv.rows}, NARROW, rv)
    measured = float(np.mean(out.max(axis=2) == 0))
    assert rv.black_sent == pytest.approx(measured, abs=0.005)
    if n_rows == 2:
        expect = rosette.view_black_fraction_multi(NARROW, rv.rows, rv.view, max_row=rv.keep_rows)
    else:
        expect = rosette.view_black_fraction(NARROW, rv.choice.row["camera_pose"], rv.view,
                                             rv.choice.cam_k, max_row=rv.keep_rows)  # fmt: skip
    assert rv.black_sent == pytest.approx(expect)


# ----------------------------------------------------------------------------- U3: capture_id re-keying


def test_null_pano_id_rosettes_are_kept_and_sequenced():
    from svi_geo import data

    # 7 rows of one rosette with pano_id=None -> 1 rosette
    t0 = pd.Timestamp("2024-06-01T10:00:00Z")
    frames_single = pd.DataFrame(
        [
            {
                "capture_id": "cap_null_1",
                "pano_id": None,
                "observation_id": f"o1:cap_null_1_{k}:5001ee",
                "snapshot_id": "snap_1",
                "capture_time": t0,
                "lat": 28.0500,
                "lng": -81.9600,
                "heading": 60.0 * k if k < 6 else 0.0,
                "pitch": 0.0 if k < 6 else 90.0,
                "roll": 0.0,
                "cam_lat": 28.0500,
                "cam_lng": -81.9600,
                "cam_alt": 35.0,
            }
            for k in range(7)
        ]
    )
    panos_single = data.panos_from_frames(frames_single)
    assert len(panos_single) == 1
    assert panos_single.iloc[0]["capture_id"] == "cap_null_1"
    assert pd.isna(panos_single.iloc[0]["pano_id"])

    # Two published panos with a NULL-pano_id capture between -> one sequence of 3
    lat1, lng1, _ = geo.enu_to_lla(10.0, 0.0, 0.0, 28.0500, -81.9600)
    lat2, lng2, _ = geo.enu_to_lla(20.0, 0.0, 0.0, 28.0500, -81.9600)
    three = pd.DataFrame(
        [
            {
                "capture_id": "cap_0",
                "pano_id": "pub_0",
                "snapshot_id": "snap_1",
                "capture_time": t0,
                "lat": 28.0500,
                "lng": -81.9600,
            },
            {
                "capture_id": "cap_1",
                "pano_id": None,
                "snapshot_id": "snap_1",
                "capture_time": t0 + pd.Timedelta(seconds=1.5),
                "lat": float(lat1),
                "lng": float(lng1),
            },
            {
                "capture_id": "cap_2",
                "pano_id": "pub_2",
                "snapshot_id": "snap_1",
                "capture_time": t0 + pd.Timedelta(seconds=3.0),
                "lat": float(lat2),
                "lng": float(lng2),
            },
        ]
    )
    seqs = sequence.build_sequences(three)
    assert len(seqs) == 3
    assert seqs["seq_id"].nunique() == 1
    assert list(seqs.sort_values("seq_idx")["capture_id"]) == ["cap_0", "cap_1", "cap_2"]


def test_sql_islands_match_python_islands_on_fixture():
    from pathlib import Path

    from sklearn.metrics import adjusted_rand_score

    from svi_geo import data

    fixture_path = Path(__file__).resolve().parent / "fixtures" / "rosettes_lakeland_hashed.parquet"
    assert fixture_path.is_file()
    df = pd.read_parquet(fixture_path)
    assert len(df) == 1010
    assert df["seq_id"].nunique() == 125
    assert int(df.groupby("seq_id").size().max()) == 81
    assert int(df["pano_id"].isna().sum()) == 668

    # Also verify frames_from_rosettes explodes 1010 * 7 = 7070 frames
    frames = data.frames_from_rosettes(df.head(5), bucket="test-bucket")
    assert len(frames) == 35
    assert "capture_id" in frames.columns and "camera_pose" in frames.columns
    assert all(str(u).startswith("gs://test-bucket/") for u in frames["gcs_uri"])

    # Compare SQL islands (seq_id) vs Python build_sequences(max_dt_s=5, max_gap_m=35)
    py_seqs = sequence.build_sequences(df, max_dt_s=5.0, max_gap_m=35.0)
    merged = df[["capture_id", "seq_id", "travel_deg", "lat", "lng"]].merge(
        py_seqs[["capture_id", "seq_id", "seq_idx"]],
        on="capture_id",
        suffixes=("_sql", "_py"),
    )
    assert len(merged) == 1010
    ari = adjusted_rand_score(merged["seq_id_sql"], merged["seq_id_py"])
    assert ari >= 0.95, f"SQL vs Python sequence partition ARI={ari:.4f} < 0.95"

    # Compare SQL travel_deg vs Python sequence.travel_bearing median abs diff < 1 deg
    py_tb = sequence.travel_bearing(py_seqs)
    py_seqs = py_seqs.assign(py_travel_deg=py_tb)
    comp = df[["capture_id", "travel_deg"]].merge(
        py_seqs[["capture_id", "py_travel_deg"]], on="capture_id"
    )
    valid = comp.dropna(subset=["travel_deg", "py_travel_deg"])
    diffs = np.abs(
        geo.angdiff(
            valid["travel_deg"].to_numpy(dtype=float),
            valid["py_travel_deg"].to_numpy(dtype=float),
        )
    )
    med_diff = float(np.median(diffs))
    assert med_diff < 1.0, f"median abs travel bearing diff {med_diff:.3f} deg >= 1.0 deg"


def test_no_module_groups_by_pano_id():
    import re
    from pathlib import Path

    pkg_dir = Path(sequence.__file__).resolve().parent
    forbidden = re.compile(
        r"""groupby\(\s*["']pano_id["']|drop_duplicates\(\s*["']pano_id["']|merge\([^)]*on\s*=\s*["']pano_id["']"""
    )
    offenders = []
    unguarded_pano_filter = re.compile(
        r"(?<!@include_unpublished OR )\bpano_id\s+IS\s+NOT\s+NULL\b"
    )
    for py_file in sorted(pkg_dir.glob("*.py")):
        text = py_file.read_text(encoding="utf-8")
        if forbidden.search(text):
            offenders.append(py_file.name)
        assert not unguarded_pano_filter.search(text), f"stale filter in {py_file.name}"
    assert not offenders, f"modules still grouping/deduping/merging by pano_id: {offenders}"


def test_stride_selects_target_spacing():
    from pathlib import Path

    fixture_path = Path(__file__).resolve().parent / "fixtures" / "rosettes_lakeland_hashed.parquet"
    df = pd.read_parquet(fixture_path)
    longest_sid = df.groupby("seq_id").size().idxmax()
    seq_df = df[df["seq_id"] == longest_sid].sort_values("seq_idx").reset_index(drop=True)
    assert len(seq_df) == 81

    selected = sequence.select_by_spacing(seq_df, target_spacing_m=10.0, max_panos=12)
    assert len(selected) == 12
    assert list(selected["seq_idx"]) == sorted(selected["seq_idx"])
    steps = np.diff(selected["cum_m"].to_numpy(dtype=float))
    assert float(np.median(steps)) >= 8.5
