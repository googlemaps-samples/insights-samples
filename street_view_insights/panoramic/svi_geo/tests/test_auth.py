import datetime as dt

from svi_geo import auth


def test_gcloud_credentials_refresh_uses_runner():
    calls = []

    def runner(cmd):
        calls.append(tuple(cmd))
        return "tok123"

    creds = auth.GcloudTokenCredentials(runner=runner)
    assert not creds.valid
    creds.refresh(None)
    assert creds.token == "tok123"
    assert creds.valid
    assert creds.expiry > dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    assert calls == [("gcloud", "auth", "print-access-token")]


def test_get_credentials_env_switch(monkeypatch):
    monkeypatch.delenv("SVI_USE_GCLOUD_TOKEN", raising=False)
    assert auth.get_credentials() is None
    monkeypatch.setenv("SVI_USE_GCLOUD_TOKEN", "1")
    assert isinstance(auth.get_credentials(), auth.GcloudTokenCredentials)


def test_genai_http_options_kwargs(monkeypatch):
    monkeypatch.delenv("SVI_ECP_PROXY_URL", raising=False)
    assert auth.genai_http_options_kwargs() == {}
    monkeypatch.setenv("SVI_ECP_PROXY_URL", "http://localhost:1")
    kw = auth.genai_http_options_kwargs()
    assert kw["base_url"] == "http://localhost:1"
    assert kw["headers"]["x-goog-ecpproxy-target-host"] == "aiplatform.mtls.googleapis.com"
