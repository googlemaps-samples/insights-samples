# Sample Code: Native Route Modification via `UpdateSelectedRoute` (`PATCH`)

This guide demonstrates how to mutate existing **`SelectedRoute`** definitions in-place using the native `UpdateSelectedRoute` RPC method (`PATCH`) with Google Cloud Standard **`FieldMask`** semantics.

---

## 1. Overview & Architectural Benefits

Historically, updating an RMI SelectedRoute required deleting the route and creating a new one, which broke continuous telemetry series, reset historical telemetry anchors, and triggered asynchronous re-validation schedules.

With native **`PATCH` / `UpdateSelectedRoute`**:
* **In-Place Mutation**: Directly modify `displayName`, `routeAttributes`, and/or `dynamicRoute` (waypoints) without deleting the route entity.
* **Granular FieldMasks**: Specify exactly which fields to overwrite via the `updateMask` query parameter.
* **Zero Telemetry Interruption**: Preserves the route's creation timestamp and continuous monitoring state.

---

## 2. API Contract & FieldMask Semantics

* **HTTP Method**: `PATCH`
* **URL**: `https://roads.googleapis.com/selection/v1/projects/{project}/selectedRoutes/{selectedRouteId}?updateMask={fieldPaths}`
* **Updatable Fields**:
  - `displayName`: Route human-readable label (max 100 characters).
  - `routeAttributes`: Key-value string map (max 10 pairs).
  - `dynamicRoute`: Geometry including `origin`, `destination`, and `intermediates`.
  - `*`: Full replacement of all updatable fields.

> [!NOTE]
> If `updateMask` is omitted from the request, all fields populated in the request payload are implied to be updated.

---

## 3. Implementation Examples

### A. Shell Client (`scripts/roadsselection_v1.sh`)

```bash
#!/bin/bash
set -euo pipefail

# Source the Roads Selection v1 client library
source scripts/roadsselection_v1.sh
source scripts/roadsselection_v1_helpers.sh

PROJECT_ID="my-roads-project"
ROUTE_NAME="projects/${PROJECT_ID}/selectedRoutes/corridor-market-st"

# 1. Define updated route payload
DYN_ROUTE=$(roadsselection_v1_dynamicroute_json 37.7749 -122.4194 37.7833 -122.4067 '[]')
UPDATED_ROUTE=$(roadsselection_v1_selectedroute_json \
  "Market Street Transit Priority Corridor" \
  "${DYN_ROUTE}" \
  '{"corridor":"market-st","priority":"HIGH","status":"OPTIMIZED"}')

# 2. Execute PATCH with explicit updateMask
echo "Applying in-place patch to ${ROUTE_NAME}..."
RESPONSE=$(roadsselection_v1_selectedroute_patch \
  "${ROUTE_NAME}" \
  "${UPDATED_ROUTE}" \
  "displayName,routeAttributes" \
  "${PROJECT_ID}")

echo "Result:"
echo "${RESPONSE}" | jq .
```

---

### B. Direct REST Call (`curl`)

```bash
PROJECT_ID="my-roads-project"
ROUTE_ID="corridor-market-st"
ACCESS_TOKEN=$(gcloud auth application-default print-access-token)

curl -s -X PATCH \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "X-Goog-User-Project: ${PROJECT_ID}" \
  -H "Content-Type: application/json" \
  "https://roads.googleapis.com/selection/v1/projects/${PROJECT_ID}/selectedRoutes/${ROUTE_ID}?updateMask=displayName,routeAttributes" \
  -d '{
    "displayName": "Market Street Transit Priority Corridor",
    "routeAttributes": {
      "corridor": "market-st",
      "priority": "HIGH",
      "status": "OPTIMIZED"
    }
  }' | jq .
```

---

### C. Python (`requests` / Google Auth)

```python
import json
import google.auth
from google.auth.transport.requests import Request
import requests

def patch_selected_route(project_id: str, route_id: str, display_name: str, attributes: dict) -> dict:
    """Updates a SelectedRoute in-place using PATCH with updateMask."""
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    credentials.refresh(Request())

    url = f"https://roads.googleapis.com/selection/v1/projects/{project_id}/selectedRoutes/{route_id}"
    params = {
        "updateMask": "displayName,routeAttributes"
    }
    headers = {
        "Authorization": f"Bearer {credentials.token}",
        "X-Goog-User-Project": project_id,
        "Content-Type": "application/json"
    }
    payload = {
        "displayName": display_name,
        "routeAttributes": attributes
    }

    response = requests.patch(url, params=params, headers=headers, json=payload)
    response.raise_for_status()
    return response.json()

if __name__ == "__main__":
    result = patch_selected_route(
        project_id="my-roads-project",
        route_id="corridor-market-st",
        display_name="Market Street Transit Priority Corridor",
        attributes={"corridor": "market-st", "priority": "HIGH"}
    )
    print("Patched Route:\n", json.dumps(result, indent=2))
```

---

### D. TypeScript (Node.js / `google-auth-library` & Native `fetch`)

```typescript
import { GoogleAuth } from 'google-auth-library';

interface SelectedRoutePatchRequest {
  displayName?: string;
  routeAttributes?: Record<string, string>;
}

interface SelectedRouteResponse {
  name: string;
  displayName?: string;
  state: string;
  routeAttributes?: Record<string, string>;
}

async function patchSelectedRoute(
  projectId: string,
  routeId: string,
  updates: SelectedRoutePatchRequest,
  updateMask: string = 'displayName,routeAttributes'
): Promise<SelectedRouteResponse> {
  const auth = new GoogleAuth({
    scopes: ['https://www.googleapis.com/auth/cloud-platform'],
  });
  const client = await auth.getClient();
  const tokenResponse = await client.getAccessToken();
  const accessToken = tokenResponse.token;

  const url = `https://roads.googleapis.com/selection/v1/projects/${projectId}/selectedRoutes/${routeId}?updateMask=${encodeURIComponent(updateMask)}`;

  const response = await fetch(url, {
    method: 'PATCH',
    headers: {
      'Authorization': `Bearer ${accessToken}`,
      'X-Goog-User-Project': projectId,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(updates),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`PATCH ${url} failed [${response.status}]: ${errorText}`);
  }

  return (await response.json()) as SelectedRouteResponse;
}

export { patchSelectedRoute, type SelectedRoutePatchRequest, type SelectedRouteResponse };
```

---

## 4. Expected API Response

```json
{
  "name": "projects/35571336328/selectedRoutes/corridor-market-st",
  "displayName": "Market Street Transit Priority Corridor",
  "dynamicRoute": {
    "origin": {
      "latitude": 37.7749,
      "longitude": -122.4194
    },
    "destination": {
      "latitude": 37.7833,
      "longitude": -122.4067
    }
  },
  "createTime": "2026-08-25T02:11:25.998215Z",
  "state": "STATE_RUNNING",
  "routeAttributes": {
    "corridor": "market-st",
    "priority": "HIGH",
    "status": "OPTIMIZED"
  }
}
```
