from pathlib import Path

import pandas as pd
import pytest

from svi_geo import data

PANO_LATEST = "imagery-insights-sandbox.imagery_insights___us.pano_observations_latest"


class FakeJob:
    def __init__(self, bytes_processed, df=None):
        self.total_bytes_processed = bytes_processed
        self._df = df if df is not None else pd.DataFrame()

    def to_dataframe(self, **_):
        return self._df

    def result(self):
        return self._df.itertuples(index=False)


class FakeClient:
    def __init__(self, dry_bytes, df=None):
        self.dry_bytes = dry_bytes
        self.df = df
        self.calls = []

    def query(self, sql, job_config=None):
        self.calls.append((sql, job_config))
        if job_config is not None and job_config.dry_run:
            return FakeJob(self.dry_bytes)
        return FakeJob(self.dry_bytes, self.df)


def test_over_cap_raises_and_real_query_never_runs():
    client = FakeClient(dry_bytes=3_000_000_000)
    runner = data.QueryRunner(client, max_bytes=2_000_000_000)
    with pytest.raises(data.QueryTooExpensive):
        runner.run(data.PANO_META_SQL, data.pano_meta_params(snapshot_id="x"))
    assert len(client.calls) == 1
    assert client.calls[0][1].dry_run is True
    assert client.calls[0][1].use_query_cache is False


def test_under_cap_runs_with_bytes_billed_and_params():
    df = pd.DataFrame({"a": [1]})
    client = FakeClient(dry_bytes=1_000, df=df)
    runner = data.QueryRunner(client, max_bytes=2_000_000_000)
    out = runner.run(data.PANO_META_SQL, data.pano_meta_params(lat=48.8, lng=2.37, radius_m=500))
    assert out.equals(df)
    assert len(client.calls) == 2
    cfg = client.calls[1][1]
    assert cfg.maximum_bytes_billed == 2_000_000_000
    names = {p.name: p for p in cfg.query_parameters}
    assert names["radius_m"].type_ == "FLOAT64" and names["radius_m"].value == 500
    assert names["snapshot_id"].type_ == "STRING" and names["snapshot_id"].value is None
    assert runner.last_dry_run_bytes == 1_000


def test_max_bytes_cannot_exceed_2gb():
    with pytest.raises(ValueError):
        data.QueryRunner(FakeClient(0), max_bytes=3_000_000_000)


@pytest.mark.parametrize(
    "table",
    [
        "imagery-insights-sandbox.imagery_insights___us.full_frame_observations_latest",
        "imagery-insights-sandbox.imagery_insights___us.cropped_observations_latest",
        "imagery-insights-sandbox.imagery_insights___us.all_observations",
        "imagery-insights-sandbox.imagery_insights___us.all_assets",
        "imagery-insights-sandbox.montreal_full_scene.observations",
        "imagery-insights-sandbox.other_dataset.pano_observations_latest",
    ],
)
def test_disallowed_tables_raise(table):
    runner = data.QueryRunner(FakeClient(1))
    with pytest.raises(data.DisallowedTable):
        runner.run(f"SELECT 1 FROM `{table}`", {})
    with pytest.raises(data.DisallowedTable):
        data.assert_allowed_table(f"SELECT 1 FROM {table} t JOIN `{PANO_LATEST}` p USING (x)")


def test_allowed_tables_pass():
    data.assert_allowed_table(f"SELECT 1 FROM `{PANO_LATEST}`")
    data.assert_allowed_table(
        "SELECT 1 FROM `imagery-insights-sandbox.imagery_insights___us.pano_observations_all`"
    )


def test_sql_without_table_is_rejected():
    with pytest.raises(data.DisallowedTable):
        data.assert_allowed_table("SELECT 1")


def test_brace_fails_fstring_guard():
    runner = data.QueryRunner(FakeClient(1))
    with pytest.raises(data.UnsafeSql):
        runner.run(f"SELECT {{x}} FROM `{PANO_LATEST}`", {})


def test_gcs_uri_for():
    assert (
        data.gcs_uri_for("b", "21d75cd4-aaaa", "o1:pH6Vw35Syoz67z7D4AyaXg_0:5001ee")
        == "gs://b/21d75cd4-aaaa/v0/o1:pH6Vw35Syoz67z7D4AyaXg_0:5001ee.jpg"
    )
    assert data.gcs_uri_for("gs://b/", "s", "o") == "gs://b/s/v0/o.jpg"


def test_pano_meta_sql_never_selects_gcs_uri():
    assert "gcs_uri" not in data.PANO_META_SQL.lower()
    assert "{" not in data.PANO_META_SQL
    data.assert_allowed_table(data.PANO_META_SQL)
    assert "@radius_m" in data.PANO_META_SQL and "FARM_FINGERPRINT" in data.PANO_META_SQL


def test_bucket_discovery_by_gcs_uri_scan_is_gone():
    # GCS_BUCKET is a required, documented parameter; nothing may SELECT gcs_uri (~1.9 GB).
    assert hasattr(data, "discover_bucket") is False
    assert not hasattr(data, "_BUCKET_SQL_TEMPLATE")
    assert not hasattr(data, "DEFAULT_BUCKET_CACHE")
    assert "select gcs_uri" not in Path(data.__file__).read_text().lower()


def test_rows_to_frames_adds_camera_index_and_pose():
    df = pd.DataFrame(
        {
            "pano_id": ["P", "P"],
            "observation_id": ["o1:P_0:5001ee", "o1:P_6:5001ee"],
            "snapshot_id": ["s", "s"],
            "capture_time": pd.to_datetime(["2024-01-01T00:00:00Z"] * 2),
            "lat": [48.8, 48.8],
            "lng": [2.37, 2.37],
            "heading": [10.0, 20.0],
            "pitch": [9.0, 87.0],
            "roll": [0.1, 0.2],
            "cam_lat": [48.8, 48.8],
            "cam_lng": [2.37, 2.37],
            "cam_alt": [60.0, 60.0],
        }
    )
    out = data.normalize_frames(df)
    assert list(out["cam_k"]) == [0, 6]
    assert out.iloc[0]["camera_pose"]["heading"] == 10.0
    assert out.iloc[0]["camera_pose"]["altitude"] == 60.0


def test_result_cache_avoids_rebilling(tmp_path):
    df = pd.DataFrame({"a": [1, 2]})
    client = FakeClient(dry_bytes=10, df=df)
    runner = data.QueryRunner(client, cache_dir=tmp_path)
    p = data.pano_meta_params(snapshot_id="s")
    assert runner.run(data.PANO_META_SQL, p).equals(df)
    assert len(client.calls) == 2
    assert runner.run(data.PANO_META_SQL, p).equals(df)
    assert len(client.calls) == 2
    runner.run(data.PANO_META_SQL, data.pano_meta_params(snapshot_id="other"))
    assert len(client.calls) == 4


def test_allow_list_cannot_be_widened():
    with pytest.raises(data.DisallowedTable):
        data.QueryRunner(FakeClient(1), allowed_tables=frozenset({"p.d.other_table"}))
    with pytest.raises(data.DisallowedTable):
        data.QueryRunner(FakeClient(1), allowed_tables=frozenset())
    narrowed = data.QueryRunner(FakeClient(1), allowed_tables=frozenset({data.PANO_LATEST}))
    with pytest.raises(data.DisallowedTable):
        narrowed.dry_run(f"SELECT 1 FROM `{data.PANO_ALL}`")


def test_cache_ttl_and_refresh(tmp_path):
    import os
    import time

    df = pd.DataFrame({"a": [1]})
    client = FakeClient(dry_bytes=10, df=df)
    runner = data.QueryRunner(client, cache_dir=tmp_path, cache_ttl_s=3600)
    p = data.pano_meta_params(snapshot_id="s")
    runner.run(data.PANO_META_SQL, p)
    assert len(client.calls) == 2
    runner.run(data.PANO_META_SQL, p, refresh=True)
    assert len(client.calls) == 4
    (cache_file,) = list(tmp_path.glob("*.parquet"))
    old = time.time() - 7200
    os.utime(cache_file, (old, old))
    runner.run(data.PANO_META_SQL, p)
    assert len(client.calls) == 6
    assert runner.total_billed_estimate == 30


def test_multi_aoi_sql_single_query_with_array_param():
    sql = data.multi_aoi_meta_sql(data.PANO_LATEST)
    assert "gcs_uri" not in sql
    assert "UNNEST(@aois)" in sql and "EXISTS" in sql
    data.assert_allowed_table(sql)
    params = data.multi_aoi_params([(48.81, 2.45), (28.05, -81.96)], radius_m=300)
    client = FakeClient(dry_bytes=10, df=pd.DataFrame({"a": [1]}))
    runner = data.QueryRunner(client)
    runner.run(sql, params)
    cfg = client.calls[1][1]
    names = {p.name: p for p in cfg.query_parameters}
    assert names["aois"].array_type == "STRUCT"
    assert len(names["aois"].values) == 2
    assert names["radius_m"].value == 300.0
    with pytest.raises(data.DisallowedTable):
        data.multi_aoi_meta_sql("p.d.other")


def test_assign_nearest_aoi():
    frames = pd.DataFrame({"lat": [48.8101, 28.0499, 40.0], "lng": [2.4502, -81.9601, 0.0]})
    aois = {"paris": (48.81, 2.45), "lakeland": (28.05, -81.96)}
    out = data.assign_nearest_aoi(frames, aois, max_dist_m=1000)
    assert list(out["aoi"][:2]) == ["paris", "lakeland"]
    assert out["aoi"].isna().iloc[2]


def test_user_project_pano_tables_are_allowed_but_nothing_else():
    t = data.pano_table("my-proj", "imagery_insights___us")
    assert t == "my-proj.imagery_insights___us.pano_observations_latest"
    assert data.is_pano_table(t) and data.is_pano_table(data.PANO_ALL)
    for bad in (
        "p.d.other_table",
        "p.d.full_frame_observations_latest",
        "pano_observations_latest",
    ):
        assert not data.is_pano_table(bad)
    with pytest.raises(ValueError):
        data.pano_table("proj`; DROP", "ds")
    with pytest.raises(data.DisallowedTable):
        data.pano_table("p", "d", view="cropped_observations_latest")
    sql = data.pano_meta_sql(t)
    assert "`my-proj.imagery_insights___us.pano_observations_latest`" in sql
    r = data.QueryRunner(FakeClient(1), allowed_tables=data.pano_tables("my-proj"))
    r.dry_run(sql, data.pano_meta_params(radius_m=10.0, lat=1.0, lng=2.0))
    with pytest.raises(data.DisallowedTable):
        r.dry_run(data.PANO_META_SQL, data.pano_meta_params())


def test_pano_dataset_allow_list_is_configurable_and_defaults_to_the_us_dataset():
    assert data.DEFAULT_ALLOWED_DATASETS == ("imagery_insights___us",)
    assert data.allowed_datasets(env={}) == ("imagery_insights___us",)
    env = {"SVI_ALLOWED_DATASETS": "imagery_insights___us, imagery_insights___eu"}
    assert data.allowed_datasets(env=env) == ("imagery_insights___us", "imagery_insights___eu")
    eu = "p.imagery_insights___eu.pano_observations_latest"
    assert not data.is_pano_table(eu, datasets=data.allowed_datasets(env={}))
    assert data.is_pano_table(eu, datasets=data.allowed_datasets(env=env))
    assert not data.is_pano_table(
        "p.imagery_insights___eu.cropped_x", datasets=("imagery_insights___eu",)
    )
    with pytest.raises(data.DisallowedTable, match="SVI_ALLOWED_DATASETS"):
        data.pano_table("p", "imagery_insights___eu", datasets=("imagery_insights___us",))
    assert data.pano_table("p", "imagery_insights___eu", datasets=("imagery_insights___eu",)) == eu
    with pytest.raises(ValueError):
        data.allowed_datasets(env={"SVI_ALLOWED_DATASETS": "bad`name"})


def test_guarded_client_accepts_a_configured_dataset():
    eu = data.pano_tables("p", "imagery_insights___eu", datasets=("imagery_insights___eu",))
    with pytest.raises(data.DisallowedTable):
        data.QueryRunner(
            client=None, allowed_tables=eu, allowed_datasets=("imagery_insights___us",)
        )
    g = data.QueryRunner(
        client=None, allowed_tables=eu, allowed_datasets=("imagery_insights___eu",)
    )
    assert g.allowed_tables == eu


def test_rosette_sql_groups_by_capture_id_and_never_filters_pano_id():
    sql = data.rosette_sql(data.PANO_LATEST)
    assert "GROUP BY capture_id, snapshot_id" in sql
    assert (
        "ARRAY_AGG(STRUCT(k, observation_id, heading, pitch, roll, cam_lat, cam_lng) ORDER BY k)"
        in sql
    )
    assert "ST_AZIMUTH" in sql
    assert "ST_DISTANCE" in sql
    assert "ST_ASTEXT(geog) AS wkt" in sql
    assert "ST_GEOHASH(geog, 7) AS gh7" in sql
    assert "cam_lat" in sql and "cam_lng" in sql
    assert "@include_unpublished" in sql
    assert "WHERE pano_id IS NOT NULL" not in sql
    assert "AND pano_id IS NOT NULL" not in sql
    assert "gcs_uri" not in sql.lower()
    assert "{" not in sql and "}" not in sql
    data.assert_allowed_table(sql)

    params = data.rosette_params(lat=28.0502, lng=-81.9601, radius_m=250.0)
    built = {p.name: p for p in data.build_params(params)}
    assert built["include_unpublished"].value is True
    assert built["max_dt_ms"].value == 5000
    assert built["max_step_m"].value == 35.0


def test_all_canonical_sql_templates_pass_guards_and_never_select_gcs_uri():
    templates = {
        "rosette_sql": data.rosette_sql(),
        "rosette_target_sql": data.rosette_sql(include_target=True),
        "snapshot_catalog_sql": data.snapshot_catalog_sql(),
        "repeat_pairs_sql": data.repeat_pairs_sql(),
        "coverage_sql": data.coverage_sql(),
        "tracks_sql": data.tracks_sql(),
        "multi_aoi_sql": data.multi_aoi_sql(),
        "assets_in_aoi_sql": data.assets_in_aoi_sql(),
    }
    for name, sql in templates.items():
        assert "gcs_uri" not in sql.lower(), name
        assert "{" not in sql and "}" not in sql, name
        data.assert_allowed_table(sql)
    cluster_sql = data.cluster_points_sql()
    assert "ST_CLUSTERDBSCAN" in cluster_sql and "UNNEST(@points)" in cluster_sql


def test_snapshot_catalog_sql_and_expiry():
    import datetime as dt
    import warnings

    sql = data.snapshot_catalog_sql()
    assert "SV_PANO" in sql and "expires_about" in sql and "INTERVAL 35 DAY" in sql
    now = dt.datetime(2026, 10, 1, 12, 0, tzinfo=dt.timezone.utc)
    catalog = pd.DataFrame(
        [
            {
                "snapshot_id": "21d75cd4-aaaa-bbbb-cccc-000000000001",
                "creation_time": now - dt.timedelta(days=34),
                "expires_about": now + dt.timedelta(days=1),
                "description": "expiring soon",
            },
            {
                "snapshot_id": "99e81ab2-aaaa-bbbb-cccc-000000000002",
                "creation_time": now - dt.timedelta(days=5),
                "expires_about": now + dt.timedelta(days=30),
                "description": "fresh",
            },
        ]
    )
    rosettes = pd.DataFrame(
        {
            "capture_id": ["c1", "c2", "c3"],
            "pano_id": ["p1", None, None],
            "snapshot_id": [
                "21d75cd4-aaaa-bbbb-cccc-000000000001",
                "21d75cd4-aaaa-bbbb-cccc-000000000001",
                "99e81ab2-aaaa-bbbb-cccc-000000000002",
            ],
            "seq_id": ["s1", "s1", "s2"],
            "capture_time": [now, now, now],
        }
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        info = data.summarize_snapshots(
            rosettes, catalog, now=now, bq_bytes=1830539988, bq_cached=False
        )
    assert (
        info["summary_line"]
        == "snapshots=21d75cd4,99e81ab2 rosettes=3 null_pano_id=2 sequences=2 bq_bytes=1830539988 bq_cached=0"
    )
    assert len(info["warnings"]) == 1 and "21d75cd4" in info["warnings"][0]
    assert len(caught) == 1

    # Empty rosettes raises with available snapshot list
    with pytest.raises(ValueError, match="21d75cd4"):
        data.summarize_snapshots(rosettes.iloc[0:0], catalog, now=now)


def test_cache_key_includes_snapshot_set_version_template_and_ttl_capped_35d(tmp_path, monkeypatch):
    import json

    import svi_geo

    df = pd.DataFrame({"a": [1, 2]})
    client = FakeClient(dry_bytes=1234, df=df)
    runner = data.QueryRunner(
        client,
        cache_dir=tmp_path,
        cache_ttl_s=90 * 86400,  # > 35 days -> capped to 35 days
        snapshot_ids=["snap_b", "snap_a"],
    )
    assert runner.cache_ttl_s == pytest.approx(35 * 86400.0)

    params = data.rosette_params(lat=28.05, lng=-81.96, radius_m=250.0)
    sql = data.rosette_sql()
    p1 = runner._cache_file(sql, params, template_name="rosette_sql")
    p_same = runner._cache_file(
        sql, params, template_name="rosette_sql", snapshot_ids=["snap_a", "snap_b"]
    )
    assert p1 == p_same

    p_diff_snap = runner._cache_file(
        sql, params, template_name="rosette_sql", snapshot_ids=["snap_a", "snap_c"]
    )
    p_diff_tpl = runner._cache_file(sql, params, template_name="other_template")
    assert p1 != p_diff_snap
    assert p1 != p_diff_tpl

    monkeypatch.setattr(svi_geo, "__version__", "9.9.9")
    p_diff_ver = runner._cache_file(sql, params, template_name="rosette_sql")
    assert p1 != p_diff_ver
    monkeypatch.undo()

    # Running writes both .parquet and .json sidecar
    out = runner.run(sql, params, template_name="rosette_sql")
    assert out.equals(df)
    assert p1.exists()
    sidecar = p1.with_suffix(".json")
    assert sidecar.exists()
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    assert meta["dry_run_bytes"] == 1234
    assert meta["billed_bytes"] == 1234
    assert meta["snapshot_ids"] == ["snap_a", "snap_b"]
    assert meta["template_name"] == "rosette_sql"


def test_last_cost_reports_bytes_usd(tmp_path):
    df = pd.DataFrame({"a": [1]})
    client = FakeClient(dry_bytes=1_830_539_988, df=df)
    runner = data.QueryRunner(client, cache_dir=tmp_path, snapshot_ids=["snap_1"])
    sql = data.rosette_sql()
    params = data.rosette_params()

    runner.run(sql, params, template_name="rosette_sql")
    cost_cold = runner.last_cost()
    assert cost_cold["bytes"] == 1_830_539_988
    assert cost_cold["dry_run_bytes"] == 1_830_539_988
    assert cost_cold["cached"] is False
    expected_usd = 1_830_539_988 / (1024**4) * 6.25
    assert cost_cold["usd"] == pytest.approx(expected_usd)

    # Second run hits local parquet cache -> 0 bytes billed, $0.00, cached=True
    runner.run(sql, params, template_name="rosette_sql")
    cost_cached = runner.last_cost()
    assert cost_cached["bytes"] == 0
    assert cost_cached["dry_run_bytes"] == 1_830_539_988
    assert cost_cached["usd"] == 0.0
    assert cost_cached["cached"] is True


def test_include_unpublished_param_toggles_predicate():
    sql = data.rosette_sql()
    assert "@include_unpublished" in sql
    p_true = {p.name: p for p in data.build_params(data.rosette_params(include_unpublished=True))}
    p_false = {p.name: p for p in data.build_params(data.rosette_params(include_unpublished=False))}
    assert p_true["include_unpublished"].type_ == "BOOL"
    assert p_true["include_unpublished"].value is True
    assert p_false["include_unpublished"].type_ == "BOOL"
    assert p_false["include_unpublished"].value is False


def test_unnest_only_sql_allowed_only_with_explicit_flag_and_zero_bytes():
    sql = data.cluster_points_sql()
    # Without allow_table_free=True, table-free SQL is rejected
    with pytest.raises(data.DisallowedTable):
        data.assert_allowed_table(sql, allow_table_free=False)
    # With allow_table_free=True, UNNEST(@points) SQL is accepted
    data.assert_allowed_table(sql, allow_table_free=True)
    # Table references or backticks are rejected when allow_table_free=True
    with pytest.raises(data.DisallowedTable):
        data.assert_allowed_table(
            f"SELECT capture_id FROM `{data.PANO_LATEST}`, UNNEST(@points)", allow_table_free=True
        )
    with pytest.raises(data.DisallowedTable):
        data.assert_allowed_table("SELECT 1", allow_table_free=True)

    # Dry-run must be 0 bytes when allow_table_free=True
    pts = [{"entity_id": "e1", "cls": "HOUSE", "lat": 28.05, "lng": -81.96}]
    params = data.cluster_points_params(pts)
    runner_zero = data.QueryRunner(FakeClient(dry_bytes=0, df=pd.DataFrame()))
    assert runner_zero.dry_run(sql, params, allow_table_free=True) == 0

    runner_nonzero = data.QueryRunner(FakeClient(dry_bytes=1024, df=pd.DataFrame()))
    with pytest.raises(data.QueryTooExpensive, match="0 bytes"):
        runner_nonzero.dry_run(sql, params, allow_table_free=True)


def test_dbscan_sql_param_shape_and_point_cap():
    pts = [
        {"entity_id": "e1", "cls": "UTILITY_POLE", "lat": 28.0502, "lng": -81.9601},
        {"entity_id": "e2", "cls": "ROAD_SIGN", "lat": 28.0503, "lng": -81.9602},
    ]
    params = {p.name: p for p in data.cluster_points_params(pts, eps_m=4.5, min_pts=2)}
    assert set(params) == {"points", "eps_m", "min_pts"}
    assert params["points"].array_type == "STRUCT"
    assert len(params["points"].values) == 2
    assert params["eps_m"].value == pytest.approx(4.5)
    assert params["min_pts"].value == 2

    too_many = [
        {"entity_id": f"e{i}", "cls": "UTILITY_POLE", "lat": 28.05, "lng": -81.96}
        for i in range(data.MAX_UNNEST_POINTS + 1)
    ]
    with pytest.raises(ValueError, match="exceeds cap"):
        data.cluster_points_params(too_many)


def test_target_framing_columns_present_and_bearing_matches_geo_bearing():
    from pathlib import Path

    from svi_geo import geo

    sql = data.rosette_sql(include_target=True)
    for col in ("target_dist_m", "target_bearing_deg", "best_cam"):
        assert col in sql

    fix_path = Path(__file__).resolve().parent / "fixtures" / "rosettes_lakeland_hashed.parquet"
    rosettes = pd.read_parquet(fix_path).head(25)
    tlat, tlng = 28.05047, -81.96015
    framed = data.attach_target_framing(rosettes, tlat=tlat, tlng=tlng)
    for col in ("target_dist_m", "target_bearing_deg", "best_cam"):
        assert col in framed.columns
    for row in framed.itertuples():
        expected_brg = float(geo.bearing_deg(row.lat, row.lng, tlat, tlng))
        assert abs(float(geo.angdiff(row.target_bearing_deg, expected_brg))) <= 0.5
        bc = row.best_cam
        assert isinstance(bc, dict)
        assert 0 <= int(bc["k"]) < 6
        assert float(bc["off_axis_deg"]) <= 40.0


def test_rosette_sql_supports_t_start_t_end_and_skill_templates():
    import datetime as dt

    sql = data.rosette_sql()
    assert "@t_start" in sql and "@t_end" in sql
    assert "COALESCE(pano_id, '')" not in sql
    assert "(@include_unpublished OR pano_id IS NOT NULL)" in sql

    t0 = dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)
    t1 = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)
    params = {p.name: p for p in data.build_params(data.rosette_params(t_start=t0, t_end=t1))}
    assert params["t_start"].type_ == "TIMESTAMP"
    assert params["t_start"].value == t0
    assert params["t_end"].type_ == "TIMESTAMP"
    assert params["t_end"].value == t1

    # pano_meta_sql and multi_aoi_meta_sql also select capture_id and use @include_unpublished
    p_sql = data.pano_meta_sql()
    assert "capture_id" in p_sql and "@include_unpublished" in p_sql
    assert "COALESCE(pano_id, '')" not in p_sql
    m_sql = data.multi_aoi_meta_sql()
    assert "capture_id" in m_sql and "@include_unpublished" in m_sql
    assert "COALESCE(pano_id, '')" not in m_sql

    # skill templates are registered in TEMPLATE_CEILINGS_BYTES
    assert "skill_coords_sql" in data.TEMPLATE_CEILINGS_BYTES
    assert "skill_id_sql" in data.TEMPLATE_CEILINGS_BYTES
    data.assert_allowed_table(data.skill_coords_sql())
    data.assert_allowed_table(data.skill_id_sql())
