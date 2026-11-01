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


SELECTED_ROUTE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{4,63}$")


def validate_selected_route_id(route_id: Optional[str]) -> None:
    """Validates selectedRouteId according to Discovery Document 20261101.

    Constraints enforced when route_id is provided and non-empty:
      - Length must be between 4 and 63 characters.
      - Valid characters are 'a-z', 'A-Z', '0-9', '-', or '_'.
      - If None or empty string '', server auto-generates a UUID upon creation.

    Args:
        route_id: Optional client-chosen route identifier.

    Raises:
        TypeError: If route_id is neither None nor a string.
        ValueError: If length or character constraints are violated.
    """
    if route_id is None or route_id == "":
        return
    if not isinstance(route_id, str):
        raise TypeError(f"route_id must be a string or None, got {type(route_id).__name__}")
    if len(route_id) < 4 or len(route_id) > 63:
        raise ValueError(f"route_id '{route_id}' must be 4-63 characters (got {len(route_id)})")
    if not SELECTED_ROUTE_ID_PATTERN.match(route_id):
        raise ValueError(
            f"route_id '{route_id}' contains invalid characters; valid characters are 'a-z', 'A-Z', '0-9', '-', or '_'"
        )


def validate_route_attributes(attributes: Dict[str, str]) -> None:
    """Validates routeAttributes dictionary according to Discovery Document 20261101.

    Constraints enforced:
      - Maximum 25 key-value pairs (len <= 25).
      - Keys and values must be non-empty strings between 1 and 100 characters
        (counted in Unicode code points).
      - Keys must not start with the reserved prefix 'goog' (case-sensitive).

    Args:
        attributes: Dictionary of string key-value pairs representing custom metadata.

    Raises:
        TypeError: If attributes is not a dict or if any key/value is not a string.
        ValueError: If constraints on length, count, or reserved prefixes are violated.
    """
    if not isinstance(attributes, dict):
        raise TypeError(f"route_attributes must be a dictionary, got {type(attributes).__name__}")
    if len(attributes) > 25:
        raise ValueError(f"route_attributes cannot exceed 25 entries (got {len(attributes)})")
    for k, v in attributes.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise TypeError(f"Attribute key and value must be strings: {k!r}={v!r}")
        if len(k) < 1 or len(k) > 100:
            raise ValueError(f"Attribute key '{k}' must be 1-100 characters (got {len(k)})")
        if len(v) < 1 or len(v) > 100:
            raise ValueError(f"Attribute value for key '{k}' must be a non-empty string of 1-100 characters (got {len(v)})")
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
        route_id: Optional[str],
        display_name: str,
        origin: Tuple[float, float],
        destination: Tuple[float, float],
        intermediates: Optional[List[Tuple[float, float]]] = None,
        route_attributes: Optional[Dict[str, str]] = None,
        dynamic_routing: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Creates a single SelectedRoute resource.

        RPC: CreateSelectedRoute (POST /selection/v1/projects/{project}/selectedRoutes)

        Args:
            route_id: Optional unique route ID (4-63 chars, [a-zA-Z0-9_-]). If None or empty,
                      the API generates a UUID automatically.
            display_name: Human-readable route label (max 100 Unicode code points).
            origin: (latitude, longitude) tuple for the corridor starting point.
            destination: (latitude, longitude) tuple for the corridor ending point.
            intermediates: Optional list of up to 25 (latitude, longitude) waypoint tuples.
            route_attributes: Optional dictionary of up to 25 metadata key-value pairs.
            dynamic_routing: Optional boolean controlling dynamic routing (False by default for
                             fixed traffic-unaware geometry; True for live-traffic rerouting).

        Returns:
            Dictionary representing the created SelectedRoute resource from Google Cloud.

        Raises:
            ValueError: If route_id, intermediate count, displayName, or attributes violate limits.
            requests.HTTPError: If the server returns a non-2xx status code.
        """
        validate_selected_route_id(route_id)
        if display_name and len(display_name) > 100:
            raise ValueError(f"displayName length ({len(display_name)}) exceeds 100 characters limit")

        if route_attributes is not None:
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
        if dynamic_routing is not None:
            payload["dynamicRouting"] = bool(dynamic_routing)
        if route_attributes:
            payload["routeAttributes"] = route_attributes

        url = f"{self.base_url}/projects/{self.project_id}/selectedRoutes"
        params: Optional[Dict[str, str]] = {"selectedRouteId": route_id} if route_id else None
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
        dynamic_routing: Optional[bool] = None,
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
            dynamic_routing: Optional boolean flag controlling dynamic routing (False pins exact path).
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
            if len(display_name) > 100:
                raise ValueError(f"displayName length ({len(display_name)}) exceeds 100 characters limit")
            payload["displayName"] = display_name
            computed_mask_fields.append("displayName")
        if dynamic_route is not None:
            payload["dynamicRoute"] = dynamic_route
            computed_mask_fields.append("dynamicRoute")
        if dynamic_routing is not None:
            payload["dynamicRouting"] = bool(dynamic_routing)
            computed_mask_fields.append("dynamicRouting")
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
                    - 'route_id' or 'selectedRouteId': Optional 4-63 char ID ([a-zA-Z0-9_-]; auto-UUID if omitted).
                    - 'display_name': Optional route label (<= 100 Unicode code points).
                    - 'origin': (latitude, longitude) tuple.
                    - 'destination': (latitude, longitude) tuple.
                    - 'intermediates': Optional list of up to 25 (lat, lng) tuples.
                    - 'dynamic_routing' or 'dynamicRouting': Optional boolean.
                    - 'attributes' or 'routeAttributes': Optional metadata dictionary.

        Returns:
            Dictionary containing 'selectedRoutes' array of created resources.

        Raises:
            ValueError: If route count exceeds 1,000 or route constraints fail.
            requests.HTTPError: If batch provisioning fails.
        """
        if len(routes) > 1000:
            raise ValueError(f"batchCreate exceeds maximum 1,000 routes limit (got {len(routes)})")

        requests_payload = []
        for item in routes:
            rid = item.get("route_id") or item.get("selectedRouteId")
            validate_selected_route_id(rid)
            sr = item.get("selectedRoute", {})
            if not sr:
                dname = item.get("display_name", item.get("displayName", ""))
                if dname and len(dname) > 100:
                    raise ValueError(f"displayName length ({len(dname)}) exceeds 100 characters limit")
                dyn_route: Dict[str, Any] = {
                    "origin": {
                        "latitude": item["origin"][0],
                        "longitude": item["origin"][1],
                    },
                    "destination": {
                        "latitude": item["destination"][0],
                        "longitude": item["destination"][1],
                    },
                }
                if item.get("intermediates"):
                    ints = item["intermediates"]
                    if len(ints) > 25:
                        raise ValueError(f"intermediates cannot exceed 25 waypoints (got {len(ints)})")
                    dyn_route["intermediates"] = [
                        {"latitude": pt[0], "longitude": pt[1]} for pt in ints
                    ]
                sr = {
                    "displayName": dname,
                    "dynamicRoute": dyn_route,
                }
                if "dynamic_routing" in item or "dynamicRouting" in item:
                    dyn_flag = item["dynamic_routing"] if "dynamic_routing" in item else item["dynamicRouting"]
                    if dyn_flag is not None:
                        sr["dynamicRouting"] = bool(dyn_flag)
                if "attributes" in item or "routeAttributes" in item:
                    attrs = item["attributes"] if "attributes" in item else item["routeAttributes"]
                    if attrs is not None:
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
        payload: Dict[str, Any] = {
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
                     - 'display_name' or 'displayName': Optional updated label.
                     - 'dynamic_route' or 'dynamicRoute': Optional updated geometry dict.
                     - 'dynamic_routing' or 'dynamicRouting': Optional boolean flag.
                     - 'attributes' or 'routeAttributes': Optional updated metadata dictionary.
                     - 'update_mask' or 'updateMask': Optional per-item FieldMask string.
            update_mask: Optional shared top-level FieldMask applied across child requests
                         that omit their own updateMask (if both are set, they must match).

        Returns:
            Dictionary containing 'selectedRoutes' array of updated resources.

        Raises:
            ValueError: If update count exceeds 1,000 or batch/child masks conflict.
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
            item_fields: List[str] = []
            if "display_name" in item or "displayName" in item:
                dname = item["display_name"] if "display_name" in item else item["displayName"]
                if dname is not None and len(dname) > 100:
                    raise ValueError(f"displayName length ({len(dname)}) exceeds 100 characters limit")
                sr["displayName"] = dname
                item_fields.append("displayName")

            if "dynamic_route" in item or "dynamicRoute" in item:
                sr["dynamicRoute"] = item["dynamic_route"] if "dynamic_route" in item else item["dynamicRoute"]
                item_fields.append("dynamicRoute")

            if "dynamic_routing" in item or "dynamicRouting" in item:
                dyn_flag = item["dynamic_routing"] if "dynamic_routing" in item else item["dynamicRouting"]
                if dyn_flag is not None:
                    sr["dynamicRouting"] = bool(dyn_flag)
                    item_fields.append("dynamicRouting")

            if "attributes" in item or "routeAttributes" in item:
                attrs = item["attributes"] if "attributes" in item else item["routeAttributes"]
                if attrs is not None:
                    validate_route_attributes(attrs)
                    sr["routeAttributes"] = attrs
                    item_fields.append("routeAttributes")

            child_mask = item.get("update_mask") or item.get("updateMask")
            if update_mask and child_mask and child_mask != update_mask:
                raise ValueError(
                    f"Child updateMask '{child_mask}' must match batch updateMask '{update_mask}' when both are set"
                )

            req: Dict[str, Any] = {"selectedRoute": sr}
            if child_mask:
                req["updateMask"] = child_mask
            elif not update_mask:
                req["updateMask"] = ",".join(item_fields) if item_fields else "displayName,routeAttributes"
            requests_payload.append(req)

        url = f"{self.base_url}/projects/{self.project_id}/selectedRoutes:batchUpdate"
        payload: Dict[str, Any] = {
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
        payload: Dict[str, Any] = {
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
