"""Live checks for the derived gcs_uri pattern (needs --run-live and credentials)."""

import pytest

from svi_geo import auth, data, images

PARIS_SNAPSHOT = "21d75cd4-5841-436a-a7c1-7722959141e1"
KNOWN_OBS = "o1:---zLYmNYEHVW4MKF1YhYA_0:5001ee"


@pytest.fixture(scope="module")
def live_clients(svi_project):
    from google.cloud import storage

    creds = auth.get_credentials()
    runner = data.QueryRunner(
        data.make_bigquery_client(svi_project, creds), cache_dir=data.DEFAULT_QUERY_CACHE
    )
    return runner, storage.Client(project=svi_project, credentials=creds)


@pytest.mark.live
def test_derived_uri_exists_and_downloads(live_clients, svi_bucket, tmp_path):
    runner, storage_client = live_clients
    bucket = svi_bucket
    uri = data.gcs_uri_for(bucket, PARIS_SNAPSHOT, KNOWN_OBS)
    fetcher = images.GcsImageFetcher(storage_client, cache_dir=tmp_path)
    assert fetcher.exists(uri)
    img = images.decode(fetcher.fetch(uri))
    assert img.shape[:2] == (5472, 3648)


@pytest.mark.live
def test_rosette_sql_dry_run_under_ceiling(live_clients):
    runner, _ = live_clients
    n_bytes = runner.dry_run(
        data.rosette_sql(),
        data.rosette_params(lat=28.0502, lng=-81.9601, radius_m=250.0),
    )
    assert 0 < n_bytes <= 1_950_000_000, f"rosette_sql dry-run {n_bytes:,} > 1.95 GB ceiling"


@pytest.mark.live
def test_snapshot_catalog_sql_dry_run_tiny(live_clients):
    runner, _ = live_clients
    n_bytes = runner.dry_run(data.snapshot_catalog_sql())
    assert 0 < n_bytes <= 1_000_000, f"snapshot_catalog_sql dry-run {n_bytes:,} > 0.001 GB ceiling"


@pytest.mark.live
def test_all_templates_dry_run_and_bytes_manifest(live_clients):
    runner, _ = live_clients
    manifest = data.compute_bytes_manifest(runner)
    for name, entry in manifest["templates"].items():
        assert entry["dry_run_bytes"] <= entry["ceiling_bytes"], (
            f"{name}: {entry['dry_run_bytes']} > {entry['ceiling_bytes']}"
        )
    assert manifest["templates"]["cluster_points_sql"]["dry_run_bytes"] == 0
    assert data.BYTES_MANIFEST_PATH.is_file()
