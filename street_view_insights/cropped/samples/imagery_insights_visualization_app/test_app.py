# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Security unit tests for imagery_insights_visualization_app."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app as viz_app  # noqa: E402


class VisualizationAppSecurityTests(unittest.TestCase):
    def setUp(self):
        self.client = viz_app.app.test_client()

    def test_templates_auto_reload_disabled_and_security_headers_set(self):
        self.assertFalse(viz_app.app.config.get("TEMPLATES_AUTO_RELOAD"))
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(resp.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(
            resp.headers.get("Referrer-Policy"), "strict-origin-when-cross-origin"
        )
        self.assertIn(b'rel="noopener noreferrer"', resp.data)

    def test_data_route_allows_only_ga_sample_json(self):
        ok_resp = self.client.get("/data/ga_sample.json")
        self.assertEqual(ok_resp.status_code, 200)
        blocked_resp = self.client.get("/data/app.py")
        self.assertEqual(blocked_resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
