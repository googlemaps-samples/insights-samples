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

"""Security and model tests for measure_height_from_cloud_run."""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze_images  # noqa: E402


class MeasureHeightSecurityTests(unittest.TestCase):
    def setUp(self):
        self.client = analyze_images.app.test_client()
        self.orig = (
            analyze_images.PROJECT_ID,
            analyze_images.ALLOWED_GCS_PREFIX,
            analyze_images.SERVICE_URL,
            analyze_images.REQUIRE_AUTH,
            analyze_images._bq_client,
            analyze_images._genai_client,
        )
        analyze_images.PROJECT_ID = "test-project-123"
        analyze_images.ALLOWED_GCS_PREFIX = "gs://geoai_published_test__us/"
        analyze_images.SERVICE_URL = "https://height-test.run.app"
        analyze_images.REQUIRE_AUTH = True
        self.mock_bq = MagicMock()
        self.mock_genai = MagicMock()
        self.mock_genai.models.generate_content.return_value = MagicMock(text="38 ft")
        analyze_images._bq_client = self.mock_bq
        analyze_images._genai_client = self.mock_genai

    def tearDown(self):
        (
            analyze_images.PROJECT_ID,
            analyze_images.ALLOWED_GCS_PREFIX,
            analyze_images.SERVICE_URL,
            analyze_images.REQUIRE_AUTH,
            analyze_images._bq_client,
            analyze_images._genai_client,
        ) = self.orig

    def test_defaults_to_gemini_4_hydrogen_global(self):
        self.assertEqual(analyze_images.GEMINI_MODEL, "gemini-4-hydrogen")
        self.assertEqual(analyze_images.GEMINI_LOCATION, "global")

    def test_rejects_unauthenticated_post(self):
        resp = self.client.post("/", json={})
        self.assertEqual(resp.status_code, 401)
        self.mock_bq.query.assert_not_called()
        self.mock_genai.models.generate_content.assert_not_called()

    def test_rejects_unlisted_gcs_uri_from_table(self):
        self.mock_bq.query.return_value.result.return_value = [
            {"gcs_uri": "gs://other-private-bucket/secret.jpg"}
        ]
        with patch.object(
            analyze_images.id_token,
            "verify_oauth2_token",
            return_value={
                "aud": "https://height-test.run.app",
                "email": "caller@example.com",
                "email_verified": True,
            },
        ):
            resp = self.client.post(
                "/",
                headers={"Authorization": "Bearer valid-token"},
                json={},
            )
        self.assertEqual(resp.status_code, 400)
        self.mock_genai.models.generate_content.assert_not_called()

    def test_authenticated_valid_request_calls_gemini_4_hydrogen(self):
        self.mock_bq.query.return_value.result.return_value = [
            {"gcs_uri": "gs://geoai_published_test__us/snap1/v0/obs1.jpg"}
        ]
        with patch.object(
            analyze_images.id_token,
            "verify_oauth2_token",
            return_value={
                "aud": "https://height-test.run.app",
                "email": "caller@example.com",
                "email_verified": True,
            },
        ):
            resp = self.client.post(
                "/",
                headers={"Authorization": "Bearer valid-token"},
                json={},
            )
        self.assertEqual(resp.status_code, 200)
        self.mock_genai.models.generate_content.assert_called_once()
        kwargs = self.mock_genai.models.generate_content.call_args.kwargs
        self.assertEqual(kwargs["model"], "gemini-4-hydrogen")


if __name__ == "__main__":
    unittest.main()
