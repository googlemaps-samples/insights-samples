"""Shared pytest configuration: the `live` / `slow` markers and `--run-live` / `--run-slow`."""

import os

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--run-live",
        action="store_true",
        default=False,
        help="Run tests that hit BigQuery / GCS / Vertex AI (need ADC).",
    )
    parser.addoption(
        "--run-slow",
        action="store_true",
        default=False,
        help="Run slow tests (e.g. building Colab-equivalent virtualenvs, several minutes).",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "live: needs network + Google Cloud credentials")
    config.addinivalue_line("markers", "slow: takes minutes (builds virtualenvs); --run-slow")


def pytest_collection_modifyitems(config, items):
    skip_live = pytest.mark.skip(reason="live test: pass --run-live to run")
    skip_slow = pytest.mark.skip(reason="slow test: pass --run-slow to run")
    for item in items:
        if "live" in item.keywords and not config.getoption("--run-live"):
            item.add_marker(skip_live)
        if "slow" in item.keywords and not config.getoption("--run-slow"):
            item.add_marker(skip_slow)


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
