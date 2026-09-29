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
def test_derived_uri_exists_and_downloads(live_clients, tmp_path):
    runner, storage_client = live_clients
    bucket = data.discover_bucket(runner)
    uri = data.gcs_uri_for(bucket, PARIS_SNAPSHOT, KNOWN_OBS)
    fetcher = images.GcsImageFetcher(storage_client, cache_dir=tmp_path)
    assert fetcher.exists(uri)
    img = images.decode(fetcher.fetch(uri))
    assert img.shape[:2] == (5472, 3648)
