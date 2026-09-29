"""Credential helpers.

`google.auth.default()` (ADC) is the normal path, and the notebooks use it. On machines where
ADC is unavailable but the gcloud CLI is logged in (e.g. some managed workstations), set
`SVI_USE_GCLOUD_TOKEN=1` and `get_credentials()` will mint short-lived user tokens with
`gcloud auth print-access-token`. No credentials are ever written to disk by this module.
"""

from __future__ import annotations

import datetime as _dt
import os
import subprocess
import threading
from collections.abc import Callable, Sequence

import google.auth
from google.auth import credentials as ga_credentials

_TOKEN_LIFETIME = _dt.timedelta(minutes=45)


def _run_gcloud(cmd: Sequence[str]) -> str:
    return subprocess.run(list(cmd), check=True, capture_output=True, text=True).stdout.strip()


class GcloudTokenCredentials(ga_credentials.Credentials):
    """Credentials that refresh by shelling out to `gcloud auth print-access-token`."""

    def __init__(
        self,
        command: Sequence[str] = ("gcloud", "auth", "print-access-token"),
        runner: Callable[[Sequence[str]], str] = _run_gcloud,
    ):
        super().__init__()
        self._command = tuple(command)
        self._runner = runner
        self._lock = threading.Lock()

    def refresh(self, request) -> None:  # noqa: ARG002 - signature fixed by google-auth
        with self._lock:
            if self.token and self.expiry and not self.expired:
                return  # another thread refreshed while we waited
            token = self._runner(self._command)
            # google-auth compares expiry against a naive UTC "now".
            self.expiry = _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None) + _TOKEN_LIFETIME
            self.token = token

    @property
    def requires_scopes(self) -> bool:
        return False


def get_credentials() -> ga_credentials.Credentials | None:
    """Return credentials for Google Cloud clients, or None to let each client use ADC."""
    if os.environ.get("SVI_USE_GCLOUD_TOKEN") == "1":
        return GcloudTokenCredentials()
    return None


def default_project(fallback: str | None = None) -> str | None:
    """Project from ADC if available, else `fallback`."""
    try:
        _, project = google.auth.default()
        return project or fallback
    except Exception:  # noqa: BLE001 - ADC missing is an expected condition
        return fallback


def genai_http_options_kwargs() -> dict:
    """Extra `HttpOptions` kwargs for google-genai, from the environment.

    If `SVI_ECP_PROXY_URL` is set (e.g. `http://localhost:18555`, a locally running
    `ecp_http_proxy` for enterprise-certificate mTLS), Vertex requests are routed through it.
    Returns `{}` otherwise, so the normal public endpoint is used.
    """
    proxy = os.environ.get("SVI_ECP_PROXY_URL")
    if not proxy:
        return {}
    return {
        "base_url": proxy,
        "headers": {"x-goog-ecpproxy-target-host": "aiplatform.mtls.googleapis.com"},
    }
