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

* **`selectedRouteId`**: Optional in Create; 4–63 characters (`[a-zA-Z0-9_-]*` — alphanumeric, hyphens `-`, and underscores `_` are valid). If omitted or empty, a UUID is generated automatically.
* **`dynamicRouting`**: Optional boolean on `SelectedRoute`; defaults to `false` (fixed traffic-unaware route computed at creation time) or `true` (live-traffic dynamic rerouting across waypoints).
* **`pageSize`**: Optional in List; default 100 (`0` defaults to 100), maximum 5,000 (values above 5,000 are clamped to 5,000).
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

### E. Go (`net/http` / Reference Client)

```go
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
)

type LatLng struct {
	Latitude  float64 `json:"latitude"`
	Longitude float64 `json:"longitude"`
}

type DynamicRoute struct {
	Origin      LatLng   `json:"origin"`
	Destination LatLng   `json:"destination"`
	Intermediates []LatLng `json:"intermediates,omitempty"`
}

type SelectedRoute struct {
	Name           string            `json:"name,omitempty"`
	DisplayName    string            `json:"displayName,omitempty"`
	DynamicRoute   *DynamicRoute     `json:"dynamicRoute,omitempty"`
	DynamicRouting *bool             `json:"dynamicRouting,omitempty"`
	RouteAttributes map[string]string `json:"routeAttributes,omitempty"`
	State          string            `json:"state,omitempty"`
}

func doRequest(ctx context.Context, method, endpoint, projectID, token string, body any) ([]byte, error) {
	var reader io.Reader
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			return nil, err
		}
		reader = bytes.NewReader(b)
	}
	req, err := http.NewRequestWithContext(ctx, method, endpoint, reader)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("X-Goog-User-Project", projectID)
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, fmt.Errorf("%s %s failed [%d]: %s", method, endpoint, resp.StatusCode, string(raw))
	}
	return raw, nil
}

func main() {
	ctx := context.Background()
	projectID := "my-roads-project"
	routeID := "corridor_market_st"
	token := os.Getenv("GOOGLE_OAUTH_ACCESS_TOKEN")
	baseURL := "https://roads.googleapis.com/selection/v1"
	fixedRouting := false

	// 1. CreateSelectedRoute (omit selectedRouteId query param to auto-generate a server UUID)
	createURL := fmt.Sprintf("%s/projects/%s/selectedRoutes?selectedRouteId=%s",
		baseURL, url.PathEscape(projectID), url.QueryEscape(routeID))
	payload := SelectedRoute{
		DisplayName:    "Market Street Corridor",
		DynamicRouting: &fixedRouting,
		DynamicRoute: &DynamicRoute{
			Origin:      LatLng{Latitude: 37.7749, Longitude: -122.4194},
			Destination: LatLng{Latitude: 37.7833, Longitude: -122.4067},
		},
	}
	createdBytes, err := doRequest(ctx, http.MethodPost, createURL, projectID, token, payload)
	if err != nil {
		panic(err)
	}
	fmt.Println("Created:", string(createdBytes))

	// 2. GetSelectedRoute
	itemURL := fmt.Sprintf("%s/projects/%s/selectedRoutes/%s", baseURL, url.PathEscape(projectID), url.PathEscape(routeID))
	fetchedBytes, err := doRequest(ctx, http.MethodGet, itemURL, projectID, token, nil)
	if err != nil {
		panic(err)
	}
	fmt.Println("Fetched:", string(fetchedBytes))

	// 3. ListSelectedRoutes
	listURL := fmt.Sprintf("%s/projects/%s/selectedRoutes?pageSize=100", baseURL, url.PathEscape(projectID))
	listedBytes, err := doRequest(ctx, http.MethodGet, listURL, projectID, token, nil)
	if err != nil {
		panic(err)
	}
	fmt.Println("Listed:", string(listedBytes))

	// 4. DeleteSelectedRoute
	if _, err := doRequest(ctx, http.MethodDelete, itemURL, projectID, token, nil); err != nil {
		panic(err)
	}
	fmt.Println("Deleted successfully.")
}
```

---

### F. Rust (`RoadsSelectionClient` / REST)

```rust
use std::collections::BTreeMap;
use std::process::Command;

fn curl_rest(method: &str, url: &str, project_id: &str, token: &str, body: Option<&str>) -> Result<String, String> {
    let mut cmd = Command::new("curl");
    cmd.args(["-sS", "-X", method])
        .arg("-H")
        .arg(format!("Authorization: Bearer {}", token))
        .arg("-H")
        .arg(format!("X-Goog-User-Project: {}", project_id));
    if let Some(json_body) = body {
        cmd.args(["-H", "Content-Type: application/json", "--data-raw", json_body]);
    }
    cmd.arg(url);
    let out = cmd.output().map_err(|e| e.to_string())?;
    if !out.status.success() {
        return Err(String::from_utf8_lossy(&out.stderr).into_owned());
    }
    Ok(String::from_utf8_lossy(&out.stdout).into_owned())
}

fn main() -> Result<(), String> {
    let project_id = "my-roads-project";
    let route_id = "corridor_market_st";
    let token = std::env::var("GOOGLE_OAUTH_ACCESS_TOKEN").unwrap_or_default();
    let base = "https://roads.googleapis.com/selection/v1";

    let mut attrs = BTreeMap::new();
    attrs.insert("corridor", "market_st");

    // 1. CreateSelectedRoute (POST)
    let create_url = format!("{}/projects/{}/selectedRoutes?selectedRouteId={}", base, project_id, route_id);
    let create_body = r#"{
      "displayName": "Market Street Corridor",
      "dynamicRouting": false,
      "dynamicRoute": {
        "origin": { "latitude": 37.7749, "longitude": -122.4194 },
        "destination": { "latitude": 37.7833, "longitude": -122.4067 }
      },
      "routeAttributes": { "corridor": "market_st" }
    }"#;
    let created = curl_rest("POST", &create_url, project_id, &token, Some(create_body))?;
    println!("Created: {}", created);

    // 2. GetSelectedRoute (GET)
    let item_url = format!("{}/projects/{}/selectedRoutes/{}", base, project_id, route_id);
    let fetched = curl_rest("GET", &item_url, project_id, &token, None)?;
    println!("Fetched: {}", fetched);

    // 3. ListSelectedRoutes (GET)
    let list_url = format!("{}/projects/{}/selectedRoutes?pageSize=100", base, project_id);
    let listed = curl_rest("GET", &list_url, project_id, &token, None)?;
    println!("Listed: {}", listed);

    // 4. DeleteSelectedRoute (DELETE)
    curl_rest("DELETE", &item_url, project_id, &token, None)?;
    println!("Deleted successfully (attributes count: {}).", attrs.len());
    Ok(())
}
```

---

## 4. Expected API Response (Create / Get)

```json
{
  "name": "projects/123456789012/selectedRoutes/corridor-market-st",
  "displayName": "Market Street Corridor",
  "dynamicRoute": {
    "origin": { "latitude": 37.7749, "longitude": -122.4194 },
    "destination": { "latitude": 37.7833, "longitude": -122.4067 }
  },
  "dynamicRouting": false,
  "createTime": "2026-09-01T00:00:00.000000Z",
  "state": "STATE_VALIDATING"
}
```
