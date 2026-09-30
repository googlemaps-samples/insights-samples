"""config.resolve_settings: explicit project and bucket, no silent fallbacks (no network)."""

import pytest

from svi_geo import config


def test_placeholders_fail_fast_naming_both_parameters():
    with pytest.raises(config.ConfigError) as err:
        config.resolve_settings(project="YOUR_PROJECT_ID", bucket="", env={})
    assert "PROJECT_ID" in str(err.value) and "GCS_BUCKET" in str(err.value)


def test_env_overrides_placeholder_but_explicit_value_wins():
    s = config.resolve_settings(
        project="YOUR_PROJECT_ID", bucket="", env={"PROJECT_ID": "p", "GCS_BUCKET": "b"}
    )
    assert (s.project, s.bucket) == ("p", "b")
    s = config.resolve_settings(
        project="mine", bucket="mybucket", env={"PROJECT_ID": "p", "GCS_BUCKET": "b"}
    )
    assert (s.project, s.bucket) == ("mine", "mybucket")


def test_google_cloud_project_and_adc_are_not_silent_fallbacks(monkeypatch):
    monkeypatch.setenv("PROJECT_ID", "from-process-env")  # must be ignored: env is explicit
    with pytest.raises(config.ConfigError, match="PROJECT_ID"):
        config.resolve_settings(
            project="YOUR_PROJECT_ID", bucket="b", env={"GOOGLE_CLOUD_PROJECT": "adc-project"}
        )


def test_bucket_is_normalised():
    s = config.resolve_settings(project="p", bucket="gs://b/", env={})
    assert s.bucket == "b"
    s = config.resolve_settings(project="p", bucket="", env={"GCS_BUCKET": "gs://envb"})
    assert s.bucket == "envb"


def test_env_defaults_to_empty_mapping_not_process_environment(monkeypatch):
    monkeypatch.setenv("PROJECT_ID", "leak")
    monkeypatch.setenv("GCS_BUCKET", "leak")
    with pytest.raises(config.ConfigError):
        config.resolve_settings(project="YOUR_PROJECT_ID", bucket="")


def test_invalid_identifiers_are_rejected():
    with pytest.raises(config.ConfigError):
        config.resolve_settings(project="p; DROP", bucket="b", env={})
    with pytest.raises(config.ConfigError):
        config.resolve_settings(project="p", bucket="b/../c", env={})


def test_require_bucket_for_scripts():
    assert config.require_bucket("gs://x/", env={}) == "x"
    assert config.require_bucket(None, env={"GCS_BUCKET": "y"}) == "y"
    with pytest.raises(config.ConfigError, match="GCS_BUCKET"):
        config.require_bucket(None, env={})
