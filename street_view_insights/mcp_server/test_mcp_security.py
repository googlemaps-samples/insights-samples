# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Unit tests for MCP server security controls and gemini-4-hydrogen defaults."""

import asyncio
import json
import os
import sys
import types as pytypes
import unittest
from unittest.mock import MagicMock, patch

# Provide lightweight stub if mcp/uvicorn are not installed in the test runner venv.
if "mcp.server.fastmcp" not in sys.modules:
    mcp_mod = pytypes.ModuleType("mcp")
    mcp_server_mod = pytypes.ModuleType("mcp.server")
    fastmcp_mod = pytypes.ModuleType("mcp.server.fastmcp")

    class _StubFastMCP:
        def __init__(self, *args, **kwargs):
            pass

        def tool(self):
            def _dec(fn):
                return fn
            return _dec

        def sse_app(self):
            async def _inner(scope, receive, send):
                await send({"type": "http.response.start", "status": 200, "headers": []})
                await send({"type": "http.response.body", "body": b"ok"})
            return _inner

    fastmcp_mod.FastMCP = _StubFastMCP
    sys.modules["mcp"] = mcp_mod
    sys.modules["mcp.server"] = mcp_server_mod
    sys.modules["mcp.server.fastmcp"] = fastmcp_mod

if "uvicorn" not in sys.modules:
    sys.modules["uvicorn"] = pytypes.ModuleType("uvicorn")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import main as mcp_main  # noqa: E402


class McpSecurityTests(unittest.TestCase):
    def setUp(self):
        self.orig_prefix = mcp_main.ALLOWED_GCS_PREFIX
        self.orig_require_auth = mcp_main.REQUIRE_AUTH
        self.orig_service_url = mcp_main.MCP_SERVICE_URL
        mcp_main.ALLOWED_GCS_PREFIX = "gs://geoai_published_test__us/"
        mcp_main.REQUIRE_AUTH = True
        mcp_main.MCP_SERVICE_URL = "https://mcp-test.run.app"

    def tearDown(self):
        mcp_main.ALLOWED_GCS_PREFIX = self.orig_prefix
        mcp_main.REQUIRE_AUTH = self.orig_require_auth
        mcp_main.MCP_SERVICE_URL = self.orig_service_url

    def test_default_model_is_gemini_4_hydrogen(self):
        self.assertEqual(mcp_main.DEFAULT_MODEL, "gemini-4-hydrogen")
        model, prompt = mcp_main.validate_model_and_prompt("", "Inspect pole")
        self.assertEqual(model, "gemini-4-hydrogen")
        self.assertEqual(prompt, "Inspect pole")

    def test_rejects_unlisted_model_and_oversized_prompt(self):
        with self.assertRaises(ValueError):
            mcp_main.validate_model_and_prompt("projects/evil/endpoints/123", "ok")
        with self.assertRaises(ValueError):
            mcp_main.validate_model_and_prompt("gemini-4-hydrogen", "x" * 5000)

    def test_rejects_sqli_and_unlisted_dataset(self):
        with self.assertRaises(ValueError):
            mcp_main.validate_project_and_dataset(
                "valid-project-123",
                "imagery_insights___us` UNION ALL SELECT 1 --",
            )
        with self.assertRaises(ValueError):
            mcp_main.validate_project_and_dataset(
                "valid-project-123",
                "other_untrusted_dataset",
            )
        proj, ds = mcp_main.validate_project_and_dataset(
            "valid-project-123", "imagery_insights___us"
        )
        self.assertEqual((proj, ds), ("valid-project-123", "imagery_insights___us"))

    def test_gcs_allowlist_blocks_confused_deputy(self):
        self.assertTrue(
            mcp_main.is_allowed_gcs_uri(
                "gs://geoai_published_test__us/snap/v0/obs1.jpg"
            )
        )
        self.assertFalse(
            mcp_main.is_allowed_gcs_uri("gs://private-secret-bucket/secret.jpg")
        )
        self.assertFalse(
            mcp_main.is_allowed_gcs_uri(
                "gs://geoai_published_test__us/../secret.jpg"
            )
        )
        self.assertFalse(
            mcp_main.is_allowed_gcs_uri("https://storage.googleapis.com/a/b.jpg")
        )
        with patch.object(mcp_main.storage, "Client") as mock_storage:
            with self.assertRaises(ValueError):
                mcp_main.download_image_bytes("gs://private-secret-bucket/secret.jpg")
            mock_storage.assert_not_called()

    def test_list_assets_blocks_sql_injection_before_bq_query(self):
        mock_bq = MagicMock()
        mock_bq.project = "valid-project-123"
        with patch.object(mcp_main, "_get_bq_client", return_value=mock_bq):
            out = json.loads(
                mcp_main.list_assets(
                    dataset_id="imagery_insights___us.all_assets` WHERE 1=1 --"
                )
            )
            self.assertIn("error", out)
            mock_bq.query.assert_not_called()

    def test_bearer_auth_middleware_enforces_oidc_and_audience(self):
        captured = []

        async def send(msg):
            captured.append(msg)

        async def receive():
            return {"type": "http.request", "body": b""}

        # Missing Authorization -> 401
        asyncio.run(
            mcp_main.app({"type": "http", "headers": []}, receive, send)
        )
        self.assertEqual(captured[0]["status"], 401)

        # Wrong audience -> 403
        captured.clear()
        with patch.object(
            mcp_main.id_token,
            "verify_oauth2_token",
            return_value={
                "aud": "https://unrelated-app.example.com",
                "email": "user@example.com",
                "email_verified": True,
            },
        ):
            asyncio.run(
                mcp_main.app(
                    {
                        "type": "http",
                        "headers": [(b"authorization", b"Bearer valid-token")],
                    },
                    receive,
                    send,
                )
            )
        self.assertEqual(captured[0]["status"], 403)


if __name__ == "__main__":
    unittest.main()
