import json

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


def test_discover_bucket_uses_override_then_cache_then_query(tmp_path, monkeypatch):
    cache = tmp_path / "bucket.json"
    monkeypatch.delenv("GCS_BUCKET", raising=False)
    df = pd.DataFrame({"gcs_uri": ["gs://geoai_published_x__us/snap/v0/o1:p_0:5001ee.jpg"]})
    client = FakeClient(1_900_000_000, df)
    runner = data.QueryRunner(client)
    assert data.discover_bucket(runner, cache_path=cache) == "geoai_published_x__us"
    assert len(client.calls) == 2
    assert json.loads(cache.read_text())[PANO_LATEST] == "geoai_published_x__us"
    # cached: no new query
    assert data.discover_bucket(runner, cache_path=cache) == "geoai_published_x__us"
    assert len(client.calls) == 2
    monkeypatch.setenv("GCS_BUCKET", "envbucket")
    assert data.discover_bucket(runner, cache_path=cache) == "envbucket"
    assert data.discover_bucket(runner, cache_path=cache, override="given") == "given"
    assert len(client.calls) == 2


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
