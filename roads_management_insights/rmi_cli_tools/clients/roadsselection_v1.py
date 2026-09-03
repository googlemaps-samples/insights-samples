#!/usr/bin/env python3
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

"""
Roads Selection API v1 Reference Client for Python.

Provides an enterprise, strongly typed client library and CLI for managing
SelectedRoute resources within the Roads Selection API (Google Maps Platform).

Service Details:
  - Canonical Service Base: https://roads.googleapis.com/selection/v1
  - Service Package: google.maps.roads.selection.v1
  - Supported Methods:
      1. CreateSelectedRoute (POST /projects/{project}/selectedRoutes)
      2. BatchCreateSelectedRoutes (POST /projects/{project}/selectedRoutes:batchCreate)
      3. GetSelectedRoute (GET /projects/{project}/selectedRoutes/{id})
      4. UpdateSelectedRoute (PATCH /projects/{project}/selectedRoutes/{id}?updateMask=...)
      5. BatchUpdateSelectedRoutes (POST /projects/{project}/selectedRoutes:batchUpdate)
      6. ListSelectedRoutes (GET /projects/{project}/selectedRoutes)
      7. DeleteSelectedRoute (DELETE /projects/{project}/selectedRoutes/{id})
      8. BatchDeleteSelectedRoutes (POST /projects/{project}/selectedRoutes:batchDelete)

Authentication & Headers:
  - OAuth 2.0 Access Token: Required with scope https://www.googleapis.com/auth/cloud-platform
  - X-Goog-User-Project: Required for billable quota allocation.
"""

import os
import re
import time
from typing import Any, Dict, Iterator, List, Optional, Tuple

try:
    import google.auth
    from google.auth.transport.requests import Request
    import requests
except ImportError:
    pass


def validate_route_attributes(attributes: Dict[str, str]) -> None:
    """Validates routeAttributes dictionary according to the proto specification.

    Constraints enforced:
      - Maximum 10 key-value pairs (len <= 10).
      - Keys and values must be strings between 1 and 100 bytes (UTF-8 encoded).
      - Keys must not start with the reserved prefix 'goog' (case-sensitive).

    Args:
        attributes: Dictionary of string key-value pairs representing custom metadata.

    Raises:
        TypeError: If attributes is not a dict or if any key/value is not a string.
        ValueError: If constraints on byte length or reserved prefixes are violated.
    """
    if not isinstance(attributes, dict):
        raise TypeError(f"route_attributes must be a dictionary, got {type(attributes).__name__}")
    if len(attributes) > 10:
        raise ValueError(f"route_attributes cannot exceed 10 entries (got {len(attributes)})")
    for k, v in attributes.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise TypeError(f"Attribute key and value must be strings: {k!r}={v!r}")
        k_bytes = len(k.encode("utf-8"))
        v_bytes = len(v.encode("utf-8"))
        if k_bytes < 1 or k_bytes > 100:
            raise ValueError(f"Attribute key '{k}' must be 1-100 bytes UTF-8 (byte length: {k_bytes})")
        if v_bytes > 100:
            raise ValueError(f"Attribute value for key '{k}' exceeds 100 bytes UTF-8 (byte length: {v_bytes})")
        if k.startswith("goog"):
            raise ValueError(f"Attribute key '{k}' cannot start with reserved prefix 'goog'")


class RoadsSelectionClient:
    """Enterprise Reference Python Client for the Roads Selection API v1.

    Manages SelectedRoute resources, handles OAuth authentication, quota header
    injection, in-place PATCH with FieldMasks, batch provisioning/deleting,
    and asynchronous lifecycle state polling.

    Attributes:
        project_id (str): The Google Cloud Project ID owning the routes.
        quota_project_id (str): The billing/quota project ID passed via X-Goog-User-Project.
        base_url (str): The base REST endpoint URL (defaults to production API or environment).
        credentials (Any): Google Auth credentials object (auto-discovered if omitted).
    """

    def __init__(
        self,
        project_id: str,
        credentials: Optional[Any] = None,
        base_url: Optional[str] = None,
        quota_project_id: Optional[str] = None,
    ):
        """Initializes the RoadsSelectionClient.

        Args:
            project_id: Google Cloud Project ID (e.g. 'my-transportation-project').
            credentials: Optional google.auth credentials instance. If None, uses ADC.
            base_url: Optional endpoint override (defaults to https://roads.googleapis.com/selection/v1).
            quota_project_id: Optional project for X-Goog-User-Project header (defaults to project_id).
        """
        self.project_id = project_id
        self.quota_project_id = quota_project_id or project_id
        self.base_url = (
            base_url
            or os.environ.get("ROADS_SELECTION_BASE_URL")
            or "https://roads.googleapis.com/selection/v1"
        ).rstrip("/")
        self.credentials = credentials

    def _ensure_auth(self) -> Dict[str, str]:
        """Ensures valid OAuth access token and returns standard request headers.

        Returns:
            Dictionary containing Authorization, X-Goog-User-Project, and Content-Type headers.
        """
        if self.credentials is None:
            self.credentials, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
        if hasattr(self.credentials, "refresh") and (
            not hasattr(self.credentials, "token") or not self.credentials.token
        ):
            self.credentials.refresh(Request())
        token = getattr(self.credentials, "token", "mock-token")
        return {
            "Authorization": f"Bearer {token}",
            "X-Goog-User-Project": self.quota_project_id,
            "Content-Type": "application/json",
        }

    # -------------------------------------------------------------------------
    # Core CRUD Operations
    # -------------------------------------------------------------------------

    def create_selected_route(
        self,
        route_id: str,
        display_name: str,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
        intermediates: Optional[List[Tuple[float, float]]] = None,
        route_attributes: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Creates a single SelectedRoute resource.

        RPC: CreateSelectedRoute (POST /selection/v1/projects/{project}/selectedRoutes)

        Args:
            route_id: Unique route ID (4-63 chars, [a-zA-Z0-9-], no underscores).
            display_name: Human-readable route label (max 100 bytes UTF-8).
            origin: (latitude, longitude) tuple for the corridor starting point.
            destination: (latitude, longitude) tuple for the corridor ending point.
            intermediates: Optional list of up to 25 (latitude, longitude) waypoint tuples.
            route_attributes: Optional dictionary of up to 10 metadata key-value pairs.

        Returns:
            Dictionary representing the created SelectedRoute resource from Google Cloud.

        Raises:
            ValueError: If intermediate count exceeds 25, displayName exceeds 100 bytes, or attribute validation fails.
            requests.HTTPError: If the server returns a non-2xx status code.
        """
        if len(display_name.encode("utf-8")) > 100:
            raise ValueError(f"displayName UTF-8 byte length ({len(display_name.encode('utf-8'))}) exceeds 100 bytes limit")

        if route_attributes:
            validate_route_attributes(route_attributes)

        dynamic_route: Dict[str, Any] = {
            "origin": {"latitude": origin[0], "longitude": origin[1]},
            "destination": {"latitude": destination[0], "longitude": destination[1]},
        }
        if intermediates:
            if len(intermediates) > 25:
                raise ValueError(f"intermediates cannot exceed 25 waypoints (got {len(intermediates)})")
            dynamic_route["intermediates"] = [
                {"latitude": pt[0], "longitude": pt[1]} for pt in intermediates
            ]

        payload: Dict[str, Any] = {
            "displayName": display_name,
            "dynamicRoute": dynamic_route,
        }
        if route_attributes:
            payload["routeAttributes"] = route_attributes

        url = f"{self.base_url}/projects/{self.project_id}/selectedRoutes"
        params = {"selectedRouteId": route_id}
        headers = self._ensure_auth()

        res = requests.post(url, params=params, headers=headers, json=payload)
        res.raise_for_status()
        return res.json()

    def get_selected_route(self, route_id: str) -> Dict[str, Any]:
        """Retrieves a SelectedRoute definition by resource name or route ID.

        RPC: GetSelectedRoute (GET /selection/v1/projects/{project}/selectedRoutes/{id})

        Args:
            route_id: The route ID or full resource name ('projects/.../selectedRoutes/...').

        Returns:
            Dictionary containing the SelectedRoute definition and current lifecycle state.

        Raises:
            requests.HTTPError: If the route is not found or credentials lack permissions.
        """
        clean_id = route_id.split("/")[-1]
        url = f"{self.base_url}/projects/{self.project_id}/selectedRoutes/{clean_id}"
        headers = self._ensure_auth()

        res = requests.get(url, headers=headers)
        res.raise_for_status()
        return res.json()

    def list_selected_routes(
        self, page_size: int = 100, page_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """Lists a single page of SelectedRoutes for the project.

        RPC: ListSelectedRoutes (GET /selection/v1/projects/{project}/selectedRoutes)

        Args:
            page_size: Maximum number of routes to return per page (default 100, max 5,000).
            page_token: Continuation page token received from a previous list response.

        Returns:
            Dictionary with 'selectedRoutes' array and optional 'nextPageToken'.

        Raises:
            requests.HTTPError: If the request fails.
        """
        url = f"{self.base_url}/projects/{self.project_id}/selectedRoutes"
        params: Dict[str, Any] = {"pageSize": page_size}
        if page_token:
            params["pageToken"] = page_token
        headers = self._ensure_auth()

        res = requests.get(url, params=params, headers=headers)
        res.raise_for_status()
        return res.json()

    def list_all_selected_routes(self, page_size: int = 500) -> Iterator[Dict[str, Any]]:
        """Generator that transparently paginates through all SelectedRoutes.

        Handles pagination token tracking automatically until all routes have been yielded.

        Args:
            page_size: Batch size requested on each underlying page call (default 500).

        Yields:
            Each SelectedRoute dictionary individually.
        """
        page_token: Optional[str] = None
        while True:
            res = self.list_selected_routes(page_size=page_size, page_token=page_token)
            routes = res.get("selectedRoutes", [])
            for r in routes:
                yield r
            page_token = res.get("nextPageToken")
            if not page_token or not routes:
                break

    def delete_selected_route(self, route_id: str) -> bool:
        """Deletes a single SelectedRoute resource and halts telemetry caching.

        RPC: DeleteSelectedRoute (DELETE /selection/v1/projects/{project}/selectedRoutes/{id})

        Args:
            route_id: The route ID or full resource name to delete.

        Returns:
            True if deletion was successfully processed.

        Raises:
            requests.HTTPError: If deletion fails.
        """
        clean_id = route_id.split("/")[-1]
        url = f"{self.base_url}/projects/{self.project_id}/selectedRoutes/{clean_id}"
        headers = self._ensure_auth()

        res = requests.delete(url, headers=headers)
        res.raise_for_status()
        return True

    # -------------------------------------------------------------------------
    # Updates & FieldMask Operations
    # -------------------------------------------------------------------------

    def update_selected_route(
        self,
        route_id: str,
        update_mask: Optional[str] = None,
        display_name: Optional[str] = None,
        dynamic_route: Optional[Dict[str, Any]] = None,
        route_attributes: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Natively updates specified route fields in-place using PATCH and FieldMask.

        RPC: UpdateSelectedRoute (PATCH /selection/v1/projects/{project}/selectedRoutes/{id})

        Args:
            route_id: The route identifier or full resource path.
            update_mask: Optional explicit comma-separated FieldMask (e.g. 'displayName,routeAttributes').
                         If omitted, computed automatically from the non-None kwargs provided.
            display_name: Optional updated display name.
            dynamic_route: Optional updated dynamicRoute geometry object.
            route_attributes: Optional updated custom metadata attributes dictionary.

        Returns:
            Dictionary containing the updated SelectedRoute object.

        Raises:
            ValueError: If no update fields are specified or attribute constraints are violated.
            requests.HTTPError: If the update fails.
        """
        clean_id = route_id.split("/")[-1]
        payload: Dict[str, Any] = {
            "name": f"projects/{self.project_id}/selectedRoutes/{clean_id}"
        }
        computed_mask_fields = []

        if display_name is not None:
            payload["displayName"] = display_name
            computed_mask_fields.append("displayName")
        if dynamic_route is not None:
            payload["dynamicRoute"] = dynamic_route
            computed_mask_fields.append("dynamicRoute")
        if route_attributes is not None:
            validate_route_attributes(route_attributes)
            payload["routeAttributes"] = route_attributes
            computed_mask_fields.append("routeAttributes")

        mask = update_mask or ",".join(computed_mask_fields)
        if not mask:
            raise ValueError("No fields specified to update in update_selected_route")

        url = f"{self.base_url}/projects/{self.project_id}/selectedRoutes/{clean_id}"
        params = {"updateMask": mask}
        headers = self._ensure_auth()

        res = requests.patch(url, params=params, headers=headers, json=payload)
        res.raise_for_status()
        return res.json()

    # -------------------------------------------------------------------------
    # Batch Operations (up to 1,000 routes)
    # -------------------------------------------------------------------------

    def batch_create_selected_routes(
        self, routes: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Atomically provisions up to 1,000 SelectedRoutes in a single API round-trip.

        RPC: BatchCreateSelectedRoutes (POST /selection/v1/projects/{project}/selectedRoutes:batchCreate)

        Args:
            routes: List of route dictionaries, each containing:
                    - 'route_id' or 'selectedRouteId': Custom 4-63 char route ID.
                    - 'display_name': Route label.
                    - 'origin': (latitude, longitude) tuple.
                    - 'destination': (latitude, longitude) tuple.
                    - 'attributes' or 'routeAttributes': Optional metadata dictionary.

        Returns:
            Dictionary containing 'selectedRoutes' array of created resources.

        Raises:
            ValueError: If route count exceeds 1,000.
            requests.HTTPError: If batch provisioning fails.
        """
        if len(routes) > 1000:
            raise ValueError(f"batchCreate exceeds maximum 1,000 routes limit (got {len(routes)})")

        requests_payload = []
        for item in routes:
            rid = item.get("route_id") or item.get("selectedRouteId")
            sr = item.get("selectedRoute", {})
            if not sr:
                sr = {
                    "displayName": item.get("display_name", ""),
                    "dynamicRoute": {
                        "origin": {
                            "latitude": item["origin"][0],
                            "longitude": item["origin"][1],
                        },
                        "destination": {
                            "latitude": item["destination"][0],
                            "longitude": item["destination"][1],
                        },
                    },
                }
                if "attributes" in item or "routeAttributes" in item:
                    attrs = item.get("attributes") or item.get("routeAttributes", {})
                    validate_route_attributes(attrs)
                    sr["routeAttributes"] = attrs

            req: Dict[str, Any] = {
                "parent": f"projects/{self.project_id}",
                "selectedRoute": sr,
            }
            if rid:
                req["selectedRouteId"] = rid
            requests_payload.append(req)

        url = f"{self.base_url}/projects/{self.project_id}/selectedRoutes:batchCreate"
        payload = {
            "parent": f"projects/{self.project_id}",
            "requests": requests_payload,
        }
        headers = self._ensure_auth()

        res = requests.post(url, headers=headers, json=payload)
        res.raise_for_status()
        return res.json()

    def batch_update_selected_routes(
        self,
        updates: List[Dict[str, Any]],
        update_mask: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Batch updates up to 1,000 SelectedRoutes in a single API round-trip.

        RPC: BatchUpdateSelectedRoutes (POST /selection/v1/projects/{project}/selectedRoutes:batchUpdate)

        Args:
            updates: List of update dictionaries, each containing:
                     - 'route_id' or 'name': Identifier of the route to modify.
                     - 'display_name': Optional updated label.
                     - 'attributes': Optional updated metadata dictionary.
                     - 'update_mask': Optional per-item FieldMask string.
            update_mask: Optional default top-level FieldMask applied across all items.

        Returns:
            Dictionary containing 'selectedRoutes' array of updated resources.

        Raises:
            ValueError: If update count exceeds 1,000.
            requests.HTTPError: If batch update fails.
        """
        if len(updates) > 1000:
            raise ValueError(f"batchUpdate exceeds maximum 1,000 routes limit (got {len(updates)})")

        requests_payload = []
        for item in updates:
            rid = item.get("route_id") or item.get("name", "").split("/")[-1]
            sr: Dict[str, Any] = {
                "name": f"projects/{self.project_id}/selectedRoutes/{rid}"
            }
            if "display_name" in item:
                sr["displayName"] = item["display_name"]
            elif "displayName" in item:
                sr["displayName"] = item["displayName"]

            if "attributes" in item or "routeAttributes" in item:
                attrs = item.get("attributes") or item.get("routeAttributes", {})
                validate_route_attributes(attrs)
                sr["routeAttributes"] = attrs

            req = {
                "selectedRoute": sr,
                "updateMask": item.get("update_mask") or item.get("updateMask", update_mask or "displayName,routeAttributes"),
            }
            requests_payload.append(req)

        url = f"{self.base_url}/projects/{self.project_id}/selectedRoutes:batchUpdate"
        payload = {
            "parent": f"projects/{self.project_id}",
            "requests": requests_payload,
        }
        if update_mask:
            payload["updateMask"] = update_mask

        headers = self._ensure_auth()
        res = requests.post(url, headers=headers, json=payload)
        res.raise_for_status()
        return res.json()

    def batch_delete_selected_routes(self, route_ids: List[str]) -> bool:
        """Atomically deletes up to 1,000 SelectedRoutes in a single API round-trip.

        RPC: BatchDeleteSelectedRoutes (POST /selection/v1/projects/{project}/selectedRoutes:batchDelete)

        Args:
            route_ids: List of route IDs or resource names (up to 1,000 items).

        Returns:
            True if all routes in batch were deleted.

        Raises:
            ValueError: If route count exceeds 1,000.
            requests.HTTPError: If batch deletion fails.
        """
        if len(route_ids) > 1000:
            raise ValueError(f"batchDelete exceeds maximum 1,000 routes limit (got {len(route_ids)})")

        full_names = [
            r if r.startswith("projects/") else f"projects/{self.project_id}/selectedRoutes/{r}"
            for r in route_ids
        ]
        url = f"{self.base_url}/projects/{self.project_id}/selectedRoutes:batchDelete"
        payload = {
            "parent": f"projects/{self.project_id}",
            "names": full_names,
        }
        headers = self._ensure_auth()

        res = requests.post(url, headers=headers, json=payload)
        res.raise_for_status()
        return True

    # -------------------------------------------------------------------------
    # High-Level Utilities
    # -------------------------------------------------------------------------

    def wait_for_route_state(
        self,
        route_id: str,
        target_state: str = "STATE_RUNNING",
        timeout_seconds: int = 30,
        poll_interval_seconds: float = 2.0,
    ) -> Dict[str, Any]:
        """Polls route status until it reaches target_state or raises on failure.

        Args:
            route_id: Identifier of the route to monitor.
            target_state: Expected Lifecycle State enum (defaults to 'STATE_RUNNING').
            timeout_seconds: Maximum duration in seconds to poll before timing out.
            poll_interval_seconds: Sleep duration between consecutive get calls.

        Returns:
            The final SelectedRoute dictionary upon reaching target_state.

        Raises:
            RuntimeError: If route enters 'STATE_INVALID' with the reason from validationError.
            TimeoutError: If route does not reach target_state within timeout_seconds.
        """
        start_time = time.time()
        while time.time() - start_time < timeout_seconds:
            route = self.get_selected_route(route_id)
            state = route.get("state", "STATE_UNSPECIFIED")
            if state == target_state:
                return route
            if state == "STATE_INVALID":
                err = route.get("validationError", "VALIDATION_ERROR_UNSPECIFIED")
                raise RuntimeError(
                    f"Route '{route_id}' entered STATE_INVALID: {err}"
                )
            time.sleep(poll_interval_seconds)

        raise TimeoutError(
            f"Route '{route_id}' did not reach {target_state} within {timeout_seconds}s"
        )


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 2:
        print("Usage: python3 roadsselection_v1.py <project_id>")
        sys.exit(1)

    pid = sys.argv[1]
    client = RoadsSelectionClient(project_id=pid)
    print(f"Listing routes for project {pid}...")
    page = client.list_selected_routes(page_size=5)
    print(json.dumps(page, indent=2))
