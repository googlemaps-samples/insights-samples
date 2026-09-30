"""Shared pytest configuration: the `live` marker and `--run-live` flag."""

import os

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--run-live",
        action="store_true",
        default=False,
        help="Run tests that hit BigQuery / GCS / Vertex AI (need ADC).",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "live: needs network + Google Cloud credentials")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-live"):
        return
    skip_live = pytest.mark.skip(reason="live test: pass --run-live to run")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


@pytest.fixture(scope="session")
def svi_project() -> str:
    return os.environ.get("SVI_PROJECT", "imagery-insights-sandbox")


@pytest.fixture(scope="session")
def svi_bucket() -> str:
    """Frame bucket for live tests: `GCS_BUCKET` is required (never discovered by a scan)."""
    from svi_geo import config

    try:
        return config.require_bucket(None, env=dict(os.environ))
    except config.ConfigError as err:
        pytest.fail(f"live tests need GCS_BUCKET: {err}")
