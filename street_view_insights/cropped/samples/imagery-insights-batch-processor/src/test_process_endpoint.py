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

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import main


class GcsAllowlistTests(unittest.TestCase):
    def test_unset_or_placeholder_prefix_fails_closed(self):
        self.assertIsNone(config.normalize_gcs_prefix(""))
        self.assertIsNone(config.normalize_gcs_prefix("   "))
        self.assertIsNone(
            config.normalize_gcs_prefix("gs://your-allowed-imagery-bucket/")
        )
        self.assertIsNone(config.normalize_gcs_prefix("gs://your-imagery-bucket/"))
        self.assertFalse(
            config.is_allowed_gcs_uri("gs://some-bucket/image.jpg", "")
        )

    def test_valid_prefix_and_object_acceptance(self):
        prefix = config.normalize_gcs_prefix("gs://geoai_published_test__us")
        self.assertEqual(prefix, "gs://geoai_published_test__us/")
        self.assertTrue(
            config.is_allowed_gcs_uri(
                "gs://geoai_published_test__us/snap1/v0/obs1.jpg", prefix
            )
        )

    def test_rejects_prefix_collision_traversal_and_non_gcs(self):
        prefix = "gs://allowed-bucket/sub/"
        self.assertFalse(
            config.is_allowed_gcs_uri("gs://allowed-bucket-evil/sub/a.jpg", prefix)
        )
        self.assertFalse(
            config.is_allowed_gcs_uri("gs://allowed-bucket/other/a.jpg", prefix)
        )
        self.assertFalse(
            config.is_allowed_gcs_uri(
                "gs://allowed-bucket/sub/../secret/a.jpg", prefix
            )
        )
        self.assertFalse(
            config.is_allowed_gcs_uri("gs://allowed-bucket/sub//a.jpg", prefix)
        )
        self.assertFalse(
            config.is_allowed_gcs_uri("gs://allowed-bucket/sub/a.jpg?x=1", prefix)
        )
        self.assertFalse(
            config.is_allowed_gcs_uri("gs://allowed-bucket/sub/a.jpg#frag", prefix)
        )
        self.assertFalse(
            config.is_allowed_gcs_uri("https://storage.googleapis.com/a/b.jpg", prefix)
        )


class EndpointSecurityTests(unittest.TestCase):
    def setUp(self):
        self.client = main.app.test_client()
        self.orig_gcp_project = config.GCP_PROJECT
        self.orig_allowed = config.ALLOWED_GCS_PREFIX
        self.orig_require_auth = config.REQUIRE_AUTH
        self.orig_analyze_url = config.ANALYZE_SERVICE_URL
        self.orig_sa_email = config.SERVICE_ACCOUNT_EMAIL
        self.orig_bq_client = main.bq_client
        self.orig_tasks_client = main.tasks_client
        self.orig_model = main.model

        config.GCP_PROJECT = "test-project"
        config.ALLOWED_GCS_PREFIX = "gs://geoai_published_test__us/"
        config.REQUIRE_AUTH = True
        config.ANALYZE_SERVICE_URL = "https://analyze-volume-images-test.run.app"
        config.SERVICE_ACCOUNT_EMAIL = "worker@test-project.iam.gserviceaccount.com"

        self.mock_bq = MagicMock()
        self.mock_bq.insert_rows_json.return_value = []
        self.mock_tasks = MagicMock()
        self.mock_model = MagicMock()
        self.mock_model.generate_content.return_value = MagicMock(
            text='{"width": 640, "height": 480}'
        )

        main.bq_client = self.mock_bq
        main.tasks_client = self.mock_tasks
        main.model = self.mock_model

    def tearDown(self):
        config.GCP_PROJECT = self.orig_gcp_project
        config.ALLOWED_GCS_PREFIX = self.orig_allowed
        config.REQUIRE_AUTH = self.orig_require_auth
        config.ANALYZE_SERVICE_URL = self.orig_analyze_url
        config.SERVICE_ACCOUNT_EMAIL = self.orig_sa_email
        main.bq_client = self.orig_bq_client
        main.tasks_client = self.orig_tasks_client
        main.model = self.orig_model

    def _valid_claims(self):
        return {
            "aud": "https://analyze-volume-images-test.run.app",
            "email": "worker@test-project.iam.gserviceaccount.com",
            "email_verified": True,
        }

    def test_process_requires_bearer_token(self):
        resp = self.client.post(
            "/process",
            json={
                "asset_id": "a1",
                "observations": [
                    {
                        "observation_id": "o1",
                        "gcs_uri": "gs://geoai_published_test__us/snap1/v0/obs1.jpg",
                    }
                ],
            },
        )
        self.assertEqual(resp.status_code, 401)
        self.mock_model.generate_content.assert_not_called()
        self.mock_bq.insert_rows_json.assert_not_called()

    def test_process_rejects_invalid_token_and_wrong_service_account(self):
        with patch.object(
            main.id_token, "verify_oauth2_token", side_effect=ValueError("bad token")
        ):
            resp = self.client.post(
                "/process",
                headers={"Authorization": "Bearer bad-token"},
                json={"observations": []},
            )
            self.assertEqual(resp.status_code, 401)

        with patch.object(
            main.id_token,
            "verify_oauth2_token",
            return_value={
                "aud": "https://analyze-volume-images-test.run.app",
                "email": "attacker@other-project.iam.gserviceaccount.com",
                "email_verified": True,
            },
        ):
            resp = self.client.post(
                "/process",
                headers={"Authorization": "Bearer valid-other-sa"},
                json={"observations": []},
            )
            self.assertEqual(resp.status_code, 403)
        self.mock_model.generate_content.assert_not_called()

    def test_process_rejects_unlisted_gcs_uri_before_vertex_call(self):
        with (
            patch.object(
                main.id_token, "verify_oauth2_token", return_value=self._valid_claims()
            ),
            patch.object(main.Part, "from_uri") as mock_part_from_uri,
        ):
            resp = self.client.post(
                "/process",
                headers={"Authorization": "Bearer valid-token"},
                json={
                    "asset_id": "a1",
                    "observations": [
                        {
                            "observation_id": "o1",
                            "gcs_uri": "gs://private-other-bucket/secret.jpg",
                        }
                    ],
                },
            )
            self.assertEqual(resp.status_code, 400)
            mock_part_from_uri.assert_not_called()
            self.mock_model.generate_content.assert_not_called()
            self.mock_bq.insert_rows_json.assert_not_called()

    def test_process_fails_closed_when_allowlist_unset(self):
        config.ALLOWED_GCS_PREFIX = ""
        with patch.object(
            main.id_token, "verify_oauth2_token", return_value=self._valid_claims()
        ):
            resp = self.client.post(
                "/process",
                headers={"Authorization": "Bearer valid-token"},
                json={
                    "asset_id": "a1",
                    "observations": [
                        {
                            "observation_id": "o1",
                            "gcs_uri": "gs://geoai_published_test__us/snap1/v0/obs1.jpg",
                        }
                    ],
                },
            )
            self.assertEqual(resp.status_code, 500)
            self.mock_model.generate_content.assert_not_called()

    def test_process_accepts_allowlisted_uri_with_valid_oidc(self):
        with (
            patch.object(
                main.id_token, "verify_oauth2_token", return_value=self._valid_claims()
            ),
            patch.object(
                main.Part, "from_uri", return_value="mock-part"
            ) as mock_part_from_uri,
        ):
            resp = self.client.post(
                "/process",
                headers={"Authorization": "Bearer valid-token"},
                json={
                    "asset_id": "a1",
                    "location": "POINT(0 0)",
                    "detection_time": "2026-11-01T00:00:00Z",
                    "observations": [
                        {
                            "observation_id": "obs1",
                            "gcs_uri": "gs://geoai_published_test__us/snap1/v0/obs1.jpg",
                        }
                    ],
                },
            )
            self.assertEqual(resp.status_code, 200)
            mock_part_from_uri.assert_called_once_with(
                "gs://geoai_published_test__us/snap1/v0/obs1.jpg",
                mime_type="image/jpeg",
            )
            self.mock_model.generate_content.assert_called_once()
            self.mock_bq.insert_rows_json.assert_called_once()

    def test_populate_rejects_sqli_and_negative_offset(self):
        with patch.object(
            main.id_token, "verify_oauth2_token", return_value=self._valid_claims()
        ):
            resp_sqli = self.client.post(
                "/populate",
                headers={"Authorization": "Bearer valid-token"},
                json={
                    "task_queue_id": "q1",
                    "offset": "0 UNION ALL SELECT 1",
                },
            )
            self.assertEqual(resp_sqli.status_code, 400)

            resp_neg = self.client.post(
                "/populate",
                headers={"Authorization": "Bearer valid-token"},
                json={"task_queue_id": "q1", "offset": -5},
            )
            self.assertEqual(resp_neg.status_code, 400)

        self.mock_bq.query.assert_not_called()

    def test_teardown_requires_auth_and_accepts_post(self):
        unauth_resp = self.client.post("/teardown", json={"task_queue_id": "q1"})
        self.assertEqual(unauth_resp.status_code, 401)

        with patch.object(
            main.id_token, "verify_oauth2_token", return_value=self._valid_claims()
        ):
            auth_resp = self.client.post(
                "/teardown",
                headers={"Authorization": "Bearer valid-token"},
                json={"task_queue_id": "q1"},
            )
            self.assertEqual(auth_resp.status_code, 200)
            self.mock_bq.delete_table.assert_called_once()
            self.mock_tasks.delete_queue.assert_called_once()


if __name__ == "__main__":
    unittest.main()