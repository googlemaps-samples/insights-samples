# Sample Code: Bulk Route Provisioning via `BatchCreateSelectedRoutes`

This guide demonstrates how to create up to **1,000 SelectedRoutes** in a single API round-trip using **`BatchCreateSelectedRoutes` (`POST :batchCreate`)**.

---

## 1. Overview & Use Cases

When setting up monitoring for large regional networks (e.g. hundreds of highway sectors across a state), issuing individual `CreateSelectedRoute` calls incurs sequential latency and risk of partial timeouts.

**`BatchCreateSelectedRoutes`** enables:
* **High-Throughput Ingestion**: Provision up to **1,000 routes** in a single HTTP payload.
* **Autonomous Scheduling**: Initiates background validation and caching schedules in parallel for all created routes.
* **Deterministic Resource IDs**: Specify custom `selectedRouteId` values for every route in the batch.

---

## 2. API Contract

* **HTTP Method**: `POST`
* **URL**: `https://roads.googleapis.com/selection/v1/projects/{project}/selectedRoutes:batchCreate`
* **Request Body (`BatchCreateSelectedRoutesRequest`)**:
  - `parent`: `projects/{project}`
  - `requests`: Array of `CreateSelectedRouteRequest` objects (max 1,000), each specifying:
    - `parent`: `projects/{project}`
    - `selectedRoute`: Full `SelectedRoute` object (`displayName`, `dynamicRoute`, `routeAttributes`).
    - `selectedRouteId`: (Optional) Unique 4-63 character route identifier.

---

## 3. Implementation Examples

### A. Shell Client (`scripts/roadsselection_v1.sh`)

```bash
#!/bin/bash
set -euo pipefail

source scripts/roadsselection_v1.sh
source scripts/roadsselection_v1_helpers.sh

PROJECT_ID="my-roads-project"

# 1. Build route payloads
DYN1=$(roadsselection_v1_dynamicroute_json 37.7749 -122.4194 37.7833 -122.4067 '[]')
ROUTE1=$(roadsselection_v1_selectedroute_json "US-101 Segment A" "${DYN1}" '{"corridor":"US-101"}')
REQ1=$(roadsselection_v1_selectedroute_create_request_json "projects/${PROJECT_ID}" "${ROUTE1}" "corridor-101-a")

DYN2=$(roadsselection_v1_dynamicroute_json 37.7833 -122.4067 37.7900 -122.3950 '[]')
ROUTE2=$(roadsselection_v1_selectedroute_json "US-101 Segment B" "${DYN2}" '{"corridor":"US-101"}')
REQ2=$(roadsselection_v1_selectedroute_create_request_json "projects/${PROJECT_ID}" "${ROUTE2}" "corridor-101-b")

# 2. Build BatchCreateSelectedRoutesRequest
BATCH_REQ=$(roadsselection_v1_selectedroute_batchcreate_request_json \
  "[${REQ1}, ${REQ2}]" \
  "projects/${PROJECT_ID}")

# 3. Execute batchCreate
echo "Batch creating 2 routes..."
RESPONSE=$(roadsselection_v1_selectedroute_batchcreate "${PROJECT_ID}" "${BATCH_REQ}")
echo "Batch Create Result:"
echo "${RESPONSE}" | jq .
```

---

### B. Direct REST Call (`curl`)

```bash
PROJECT_ID="my-roads-project"
ACCESS_TOKEN=$(gcloud auth application-default print-access-token)

curl -s -X POST \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "X-Goog-User-Project: ${PROJECT_ID}" \
  -H "Content-Type: application/json" \
  "https://roads.googleapis.com/selection/v1/projects/${PROJECT_ID}/selectedRoutes:batchCreate" \
  -d '{
    "parent": "projects/'"${PROJECT_ID}"'",
    "requests": [
      {
        "parent": "projects/'"${PROJECT_ID}"'",
        "selectedRouteId": "corridor-101-a",
        "selectedRoute": {
          "displayName": "US-101 Segment A",
          "dynamicRoute": {
            "origin": { "latitude": 37.7749, "longitude": -122.4194 },
            "destination": { "latitude": 37.7833, "longitude": -122.4067 }
          }
        }
      },
      {
        "parent": "projects/'"${PROJECT_ID}"'",
        "selectedRouteId": "corridor-101-b",
        "selectedRoute": {
          "displayName": "US-101 Segment B",
          "dynamicRoute": {
            "origin": { "latitude": 37.7833, "longitude": -122.4067 },
            "destination": { "latitude": 37.7900, "longitude": -122.3950 }
          }
        }
      }
    ]
  }' | jq .
```

---

### C. Python (`requests` / Batch Provisioner)

```python
import json
import google.auth
from google.auth.transport.requests import Request
import requests

def batch_create_routes(project_id: str, routes_data: list) -> dict:
    """Batch creates up to 1,000 SelectedRoutes in a single request."""
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    credentials.refresh(Request())

    url = f"https://roads.googleapis.com/selection/v1/projects/{project_id}/selectedRoutes:batchCreate"
    headers = {
        "Authorization": f"Bearer {credentials.token}",
        "X-Goog-User-Project": project_id,
        "Content-Type": "application/json"
    }

    requests_payload = []
    for item in routes_data:
        requests_payload.append({
            "parent": f"projects/{project_id}",
            "selectedRouteId": item["route_id"],
            "selectedRoute": {
                "displayName": item["display_name"],
                "dynamicRoute": {
                    "origin": {"latitude": item["origin"][0], "longitude": item["origin"][1]},
                    "destination": {"latitude": item["destination"][0], "longitude": item["destination"][1]}
                },
                "routeAttributes": item.get("attributes", {})
            }
        })

    payload = {
        "parent": f"projects/{project_id}",
        "requests": requests_payload
    }

    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    return response.json()

if __name__ == "__main__":
    routes = [
        {
            "route_id": "corridor-101-a",
            "display_name": "US-101 Segment A",
            "origin": (37.7749, -122.4194),
            "destination": (37.7833, -122.4067),
            "attributes": {"corridor": "US-101"}
        },
        {
            "route_id": "corridor-101-b",
            "display_name": "US-101 Segment B",
            "origin": (37.7833, -122.4067),
            "destination": (37.7900, -122.3950),
            "attributes": {"corridor": "US-101"}
        }
    ]
    res = batch_create_routes("my-roads-project", routes)
    print("Batch Created Routes:\n", json.dumps(res, indent=2))
```

---

### D. TypeScript (Node.js / Batch Provisioner)

```typescript
import { GoogleAuth } from 'google-auth-library';

interface RouteCreateItem {
  routeId: string;
  displayName: string;
  origin: { latitude: number; longitude: number };
  destination: { latitude: number; longitude: number };
  attributes?: Record<string, string>;
}

interface BatchCreateResponse {
  selectedRoutes: Array<{
    name: string;
    displayName: string;
    state: string;
    createTime: string;
  }>;
}

async function batchCreateSelectedRoutes(
  projectId: string,
  items: RouteCreateItem[]
): Promise<BatchCreateResponse> {
  const auth = new GoogleAuth({
    scopes: ['https://www.googleapis.com/auth/cloud-platform'],
  });
  const client = await auth.getClient();
  const tokenResponse = await client.getAccessToken();
  const accessToken = tokenResponse.token;

  const url = `https://roads.googleapis.com/selection/v1/projects/${projectId}/selectedRoutes:batchCreate`;

  const payload = {
    parent: `projects/${projectId}`,
    requests: items.map((item) => ({
      parent: `projects/${projectId}`,
      selectedRouteId: item.routeId,
      selectedRoute: {
        displayName: item.displayName,
        dynamicRoute: {
          origin: item.origin,
          destination: item.destination,
        },
        routeAttributes: item.attributes ?? {},
      },
    })),
  };

  const response = await fetch(url, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${accessToken}`,
      'X-Goog-User-Project': projectId,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`batchCreate failed [${response.status}]: ${errorText}`);
  }

  return (await response.json()) as BatchCreateResponse;
}

export { batchCreateSelectedRoutes, type RouteCreateItem, type BatchCreateResponse };
```

---

## 4. Expected API Response

```json
{
  "selectedRoutes": [
    {
      "name": "projects/35571336328/selectedRoutes/corridor-101-a",
      "displayName": "US-101 Segment A",
      "createTime": "2026-09-01T00:00:00.000000Z",
      "state": "STATE_VALIDATING"
    },
    {
      "name": "projects/35571336328/selectedRoutes/corridor-101-b",
      "displayName": "US-101 Segment B",
      "createTime": "2026-09-01T00:00:00.000000Z",
      "state": "STATE_VALIDATING"
    }
  ]
}
```
