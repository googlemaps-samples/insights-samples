# Sample Code: Core CRUD Operations (`Create`, `Get`, `List`, `Delete`)

This guide demonstrates the foundational CRUD operations for **`SelectedRoute`** resources in the Roads Selection API v1: creating a single route, retrieving route details, listing routes with pagination, and deleting a route.

---

## 1. Overview & RPC Method Matrix

| Operation | RPC Method | HTTP Verb & Path | Description |
| :--- | :--- | :--- | :--- |
| **Create** | `CreateSelectedRoute` | `POST /selection/v1/projects/{project}/selectedRoutes?selectedRouteId={id}` | Creates a single route and begins telemetry scheduling. |
| **Get** | `GetSelectedRoute` | `GET /selection/v1/projects/{project}/selectedRoutes/{id}` | Retrieves a route definition by resource name. |
| **List** | `ListSelectedRoutes` | `GET /selection/v1/projects/{project}/selectedRoutes?pageSize={size}&pageToken={token}` | Lists routes for a project with automated page tokens. |
| **Delete** | `DeleteSelectedRoute` | `DELETE /selection/v1/projects/{project}/selectedRoutes/{id}` | Deletes a route and halts telemetry caching. |

---

## 2. API Contract & Constraints

* **`selectedRouteId`**: Optional in Create; 4-63 alphanumeric/hyphen characters (`[a-zA-Z0-9-]*`). No underscores (`_`).
* **`pageSize`**: Optional in List; default 100, maximum 5,000.
* **`pageToken`**: Opaque pagination continuation token returned by the server.

---

## 3. Implementation Examples

### A. Shell Client (`scripts/roadsselection_v1.sh`)

```bash
#!/bin/bash
set -euo pipefail

source scripts/roadsselection_v1.sh
source scripts/roadsselection_v1_helpers.sh

PROJECT_ID="my-roads-project"
ROUTE_ID="corridor-market-st"
ROUTE_NAME="projects/${PROJECT_ID}/selectedRoutes/${ROUTE_ID}"

# 1. Create a SelectedRoute
DYN_JSON=$(roadsselection_v1_dynamicroute_json 37.7749 -122.4194 37.7833 -122.4067 '[]')
ROUTE_JSON=$(roadsselection_v1_selectedroute_json "Market Street Corridor" "${DYN_JSON}" '{"corridor":"market-st"}')

echo "Creating SelectedRoute..."
CREATED=$(roadsselection_v1_selectedroute_create "${PROJECT_ID}" "${ROUTE_JSON}" "${ROUTE_ID}")
echo "Created: $(echo "${CREATED}" | jq -r .name)"

# 2. Get the SelectedRoute
echo "Retrieving SelectedRoute..."
FETCHED=$(roadsselection_v1_selectedroute_get "${ROUTE_NAME}" "${PROJECT_ID}")
echo "State: $(echo "${FETCHED}" | jq -r .state)"

# 3. List SelectedRoutes (first page)
echo "Listing SelectedRoutes..."
LIST_RES=$(roadsselection_v1_selectedroute_list "${PROJECT_ID}" 50 "")
echo "Found $(echo "${LIST_RES}" | jq '.selectedRoutes | length // 0') routes on page."

# 4. Delete the SelectedRoute
echo "Deleting SelectedRoute..."
roadsselection_v1_selectedroute_delete "${ROUTE_NAME}" "${PROJECT_ID}"
echo "Deleted successfully."
```

---

### B. Direct REST Calls (`curl`)

```bash
PROJECT_ID="my-roads-project"
ROUTE_ID="corridor-market-st"
ACCESS_TOKEN=$(gcloud auth application-default print-access-token)

# 1. Create
curl -s -X POST \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "X-Goog-User-Project: ${PROJECT_ID}" \
  -H "Content-Type: application/json" \
  "https://roads.googleapis.com/selection/v1/projects/${PROJECT_ID}/selectedRoutes?selectedRouteId=${ROUTE_ID}" \
  -d '{
    "displayName": "Market Street Corridor",
    "dynamicRoute": {
      "origin": { "latitude": 37.7749, "longitude": -122.4194 },
      "destination": { "latitude": 37.7833, "longitude": -122.4067 }
    }
  }' | jq .

# 2. Get
curl -s -X GET \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "X-Goog-User-Project: ${PROJECT_ID}" \
  "https://roads.googleapis.com/selection/v1/projects/${PROJECT_ID}/selectedRoutes/${ROUTE_ID}" | jq .

# 3. List
curl -s -X GET \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "X-Goog-User-Project: ${PROJECT_ID}" \
  "https://roads.googleapis.com/selection/v1/projects/${PROJECT_ID}/selectedRoutes?pageSize=100" | jq .

# 4. Delete
curl -s -X DELETE \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "X-Goog-User-Project: ${PROJECT_ID}" \
  "https://roads.googleapis.com/selection/v1/projects/${PROJECT_ID}/selectedRoutes/${ROUTE_ID}" | jq .
```

---

### C. Python (`requests` / Core CRUD Manager)

```python
import json
import google.auth
from google.auth.transport.requests import Request
import requests

def create_selected_route(project_id: str, route_id: str, display_name: str, origin: tuple, destination: tuple) -> dict:
    """Creates a SelectedRoute using POST."""
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    credentials.refresh(Request())

    url = f"https://roads.googleapis.com/selection/v1/projects/{project_id}/selectedRoutes"
    params = {"selectedRouteId": route_id}
    headers = {
        "Authorization": f"Bearer {credentials.token}",
        "X-Goog-User-Project": project_id,
        "Content-Type": "application/json"
    }
    payload = {
        "displayName": display_name,
        "dynamicRoute": {
            "origin": {"latitude": origin[0], "longitude": origin[1]},
            "destination": {"latitude": destination[0], "longitude": destination[1]}
        }
    }
    response = requests.post(url, params=params, headers=headers, json=payload)
    response.raise_for_status()
    return response.json()

def get_selected_route(project_id: str, route_id: str) -> dict:
    """Retrieves a SelectedRoute by ID."""
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    credentials.refresh(Request())

    url = f"https://roads.googleapis.com/selection/v1/projects/{project_id}/selectedRoutes/{route_id}"
    headers = {
        "Authorization": f"Bearer {credentials.token}",
        "X-Goog-User-Project": project_id
    }
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()

def list_selected_routes(project_id: str, page_size: int = 100, page_token: str = "") -> dict:
    """Lists SelectedRoutes for a project."""
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    credentials.refresh(Request())

    url = f"https://roads.googleapis.com/selection/v1/projects/{project_id}/selectedRoutes"
    params = {"pageSize": page_size}
    if page_token:
        params["pageToken"] = page_token

    headers = {
        "Authorization": f"Bearer {credentials.token}",
        "X-Goog-User-Project": project_id
    }
    response = requests.get(url, params=params, headers=headers)
    response.raise_for_status()
    return response.json()

def delete_selected_route(project_id: str, route_id: str) -> bool:
    """Deletes a SelectedRoute by ID."""
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    credentials.refresh(Request())

    url = f"https://roads.googleapis.com/selection/v1/projects/{project_id}/selectedRoutes/{route_id}"
    headers = {
        "Authorization": f"Bearer {credentials.token}",
        "X-Goog-User-Project": project_id
    }
    response = requests.delete(url, headers=headers)
    response.raise_for_status()
    return True

if __name__ == "__main__":
    pid = "my-roads-project"
    rid = "corridor-market-st"
    created = create_selected_route(pid, rid, "Market Street", (37.7749, -122.4194), (37.7833, -122.4067))
    print("Created:", json.dumps(created, indent=2))
    fetched = get_selected_route(pid, rid)
    print("Fetched State:", fetched.get("state"))
    routes_page = list_selected_routes(pid, page_size=10)
    print("Listed count:", len(routes_page.get("selectedRoutes", [])))
    delete_selected_route(pid, rid)
    print("Deleted successfully.")
```

---

### D. TypeScript (Node.js / Core CRUD Operations)

```typescript
import { GoogleAuth } from 'google-auth-library';

interface LatLng {
  latitude: number;
  longitude: number;
}

interface SelectedRoute {
  name: string;
  displayName: string;
  dynamicRoute: {
    origin: LatLng;
    destination: LatLng;
    intermediates?: LatLng[];
  };
  state?: string;
  createTime?: string;
}

interface ListRoutesResponse {
  selectedRoutes?: SelectedRoute[];
  nextPageToken?: string;
}

async function getAuthHeader(projectId: string): Promise<Record<string, string>> {
  const auth = new GoogleAuth({
    scopes: ['https://www.googleapis.com/auth/cloud-platform'],
  });
  const client = await auth.getClient();
  const tokenResponse = await client.getAccessToken();
  return {
    Authorization: `Bearer ${tokenResponse.token}`,
    'X-Goog-User-Project': projectId,
  };
}

async function createSelectedRoute(
  projectId: string,
  routeId: string,
  displayName: string,
  origin: LatLng,
  destination: LatLng
): Promise<SelectedRoute> {
  const headers = await getAuthHeader(projectId);
  const url = `https://roads.googleapis.com/selection/v1/projects/${projectId}/selectedRoutes?selectedRouteId=${encodeURIComponent(routeId)}`;
  const body = {
    displayName,
    dynamicRoute: { origin, destination },
  };

  const response = await fetch(url, {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    throw new Error(`Create failed [${response.status}]: ${await response.text()}`);
  }
  return (await response.json()) as SelectedRoute;
}

async function getSelectedRoute(projectId: string, routeId: string): Promise<SelectedRoute> {
  const headers = await getAuthHeader(projectId);
  const url = `https://roads.googleapis.com/selection/v1/projects/${projectId}/selectedRoutes/${routeId}`;
  const response = await fetch(url, { method: 'GET', headers });

  if (!response.ok) {
    throw new Error(`Get failed [${response.status}]: ${await response.text()}`);
  }
  return (await response.json()) as SelectedRoute;
}

async function listSelectedRoutes(
  projectId: string,
  pageSize: number = 100,
  pageToken?: string
): Promise<ListRoutesResponse> {
  const headers = await getAuthHeader(projectId);
  let url = `https://roads.googleapis.com/selection/v1/projects/${projectId}/selectedRoutes?pageSize=${pageSize}`;
  if (pageToken) url += `&pageToken=${encodeURIComponent(pageToken)}`;

  const response = await fetch(url, { method: 'GET', headers });
  if (!response.ok) {
    throw new Error(`List failed [${response.status}]: ${await response.text()}`);
  }
  return (await response.json()) as ListRoutesResponse;
}

async function deleteSelectedRoute(projectId: string, routeId: string): Promise<void> {
  const headers = await getAuthHeader(projectId);
  const url = `https://roads.googleapis.com/selection/v1/projects/${projectId}/selectedRoutes/${routeId}`;
  const response = await fetch(url, { method: 'DELETE', headers });

  if (!response.ok) {
    throw new Error(`Delete failed [${response.status}]: ${await response.text()}`);
  }
}

export {
  createSelectedRoute,
  getSelectedRoute,
  listSelectedRoutes,
  deleteSelectedRoute,
  type SelectedRoute,
  type ListRoutesResponse,
};
```

---

## 4. Expected API Response (Create / Get)

```json
{
  "name": "projects/35571336328/selectedRoutes/corridor-market-st",
  "displayName": "Market Street Corridor",
  "dynamicRoute": {
    "origin": { "latitude": 37.7749, "longitude": -122.4194 },
    "destination": { "latitude": 37.7833, "longitude": -122.4067 }
  },
  "createTime": "2026-09-01T00:00:00.000000Z",
  "state": "STATE_VALIDATING"
}
```
