# Sample Code: Multi-Route Updates via `BatchUpdateSelectedRoutes`

This guide demonstrates how to update up to **1,000 SelectedRoutes** in a single API round-trip using **`BatchUpdateSelectedRoutes` (`POST :batchUpdate`)**.

---

## 1. Overview & Use Cases

When managing large fleets of monitored corridors (e.g. 5,000+ regional roads across a state or country), updating metadata individually creates rate-limit exhaustion and excessive network latency.

**`BatchUpdateSelectedRoutes`** allows:
* **Atomic Batching**: Update up to **1,000 routes** in a single HTTP request.
* **Shared or Granular FieldMasks**: Apply a single `updateMask` across all items or specify custom per-item masks.
* **Metadata Re-indexing**: Bulk-update custom attributes (e.g. updating `jurisdiction`, `maintenance_window`, or `priority` tags).

---

## 2. API Contract

* **HTTP Method**: `POST`
* **URL**: `https://roads.googleapis.com/selection/v1/projects/{project}/selectedRoutes:batchUpdate`
* **Request Body (`BatchUpdateSelectedRoutesRequest`)**:
  - `parent`: `projects/{project}` (must match child resource parents).
  - `requests`: Array of `UpdateSelectedRouteRequest` objects (max 1,000).
  - `updateMask`: (Optional) Shared field mask applied to all items in the batch.

---

## 3. Implementation Examples

### A. Shell Client (`scripts/roadsselection_v1.sh`)

```bash
#!/bin/bash
set -euo pipefail

source scripts/roadsselection_v1.sh
source scripts/roadsselection_v1_helpers.sh

PROJECT_ID="my-roads-project"

# 1. Build individual UpdateSelectedRouteRequest objects
REQ1=$(roadsselection_v1_selectedroute_update_request_json \
  '{
    "name": "projects/'"${PROJECT_ID}"'/selectedRoutes/corridor-101-north",
    "displayName": "US-101 North Express",
    "routeAttributes": {"corridor": "US-101", "tier": "TIER_1"}
  }' \
  "displayName,routeAttributes")

REQ2=$(roadsselection_v1_selectedroute_update_request_json \
  '{
    "name": "projects/'"${PROJECT_ID}"'/selectedRoutes/corridor-280-south",
    "displayName": "I-280 South Scenic",
    "routeAttributes": {"corridor": "I-280", "tier": "TIER_1"}
  }' \
  "displayName,routeAttributes")

# 2. Build BatchUpdateSelectedRoutesRequest
BATCH_REQUEST=$(roadsselection_v1_selectedroute_batchupdate_request_json \
  "[${REQ1}, ${REQ2}]" \
  "projects/${PROJECT_ID}")

# 3. Execute batchUpdate
echo "Submitting batch update for 2 routes..."
RESPONSE=$(roadsselection_v1_selectedroute_batchupdate "${PROJECT_ID}" "${BATCH_REQUEST}")

echo "Batch Update Result:"
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
  "https://roads.googleapis.com/selection/v1/projects/${PROJECT_ID}/selectedRoutes:batchUpdate" \
  -d '{
    "parent": "projects/'"${PROJECT_ID}"'",
    "updateMask": "displayName,routeAttributes",
    "requests": [
      {
        "selectedRoute": {
          "name": "projects/'"${PROJECT_ID}"'/selectedRoutes/corridor-101-north",
          "displayName": "US-101 North Express",
          "routeAttributes": {
            "corridor": "US-101",
            "tier": "TIER_1"
          }
        }
      },
      {
        "selectedRoute": {
          "name": "projects/'"${PROJECT_ID}"'/selectedRoutes/corridor-280-south",
          "displayName": "I-280 South Scenic",
          "routeAttributes": {
            "corridor": "I-280",
            "tier": "TIER_1"
          }
        }
      }
    ]
  }' | jq .
```

---

### C. Python (`requests` / Batch Processor)

```python
import json
import google.auth
from google.auth.transport.requests import Request
import requests

def batch_update_routes(project_id: str, updates: list) -> dict:
    """Batch updates up to 1000 SelectedRoutes in a single request."""
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    credentials.refresh(Request())

    url = f"https://roads.googleapis.com/selection/v1/projects/{project_id}/selectedRoutes:batchUpdate"
    headers = {
        "Authorization": f"Bearer {credentials.token}",
        "X-Goog-User-Project": project_id,
        "Content-Type": "application/json"
    }

    requests_payload = []
    for item in updates:
        requests_payload.append({
            "selectedRoute": {
                "name": f"projects/{project_id}/selectedRoutes/{item['route_id']}",
                "displayName": item.get("display_name", ""),
                "routeAttributes": item.get("attributes", {})
            }
        })

    payload = {
        "parent": f"projects/{project_id}",
        "updateMask": "displayName,routeAttributes",
        "requests": requests_payload
    }

    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    return response.json()

if __name__ == "__main__":
    updates_list = [
        {
            "route_id": "corridor-101-north",
            "display_name": "US-101 North Express",
            "attributes": {"corridor": "US-101", "tier": "TIER_1"}
        },
        {
            "route_id": "corridor-280-south",
            "display_name": "I-280 South Scenic",
            "attributes": {"corridor": "I-280", "tier": "TIER_1"}
        }
    ]
    result = batch_update_routes("my-roads-project", updates_list)
    print("Batch Updated Routes:\n", json.dumps(result, indent=2))
```

---

### D. TypeScript (Node.js / Batch Processor)

```typescript
import { GoogleAuth } from 'google-auth-library';

interface RouteUpdateItem {
  routeId: string;
  displayName?: string;
  attributes?: Record<string, string>;
}

interface BatchUpdateResponse {
  selectedRoutes: Array<{
    name: string;
    displayName?: string;
    state: string;
    routeAttributes?: Record<string, string>;
  }>;
}

async function batchUpdateSelectedRoutes(
  projectId: string,
  updates: RouteUpdateItem[],
  updateMask: string = 'displayName,routeAttributes'
): Promise<BatchUpdateResponse> {
  const auth = new GoogleAuth({
    scopes: ['https://www.googleapis.com/auth/cloud-platform'],
  });
  const client = await auth.getClient();
  const tokenResponse = await client.getAccessToken();
  const accessToken = tokenResponse.token;

  const url = `https://roads.googleapis.com/selection/v1/projects/${projectId}/selectedRoutes:batchUpdate`;

  const payload = {
    parent: `projects/${projectId}`,
    updateMask,
    requests: updates.map((item) => ({
      selectedRoute: {
        name: `projects/${projectId}/selectedRoutes/${item.routeId}`,
        displayName: item.displayName,
        routeAttributes: item.attributes ?? {},
      },
    })),
  };

  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${accessToken}`,
      'X-Goog-User-Project': projectId,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`batchUpdate failed [${response.status}]: ${errorText}`);
  }

  return (await response.json()) as BatchUpdateResponse;
}

export { batchUpdateSelectedRoutes, type RouteUpdateItem, type BatchUpdateResponse };
```

---

## 4. Expected API Response

```json
{
  "selectedRoutes": [
    {
      "name": "projects/35571336328/selectedRoutes/corridor-101-north",
      "displayName": "US-101 North Express",
      "createTime": "2026-08-25T02:11:25.998215Z",
      "state": "STATE_RUNNING",
      "routeAttributes": {
        "corridor": "US-101",
        "tier": "TIER_1"
      }
    },
    {
      "name": "projects/35571336328/selectedRoutes/corridor-280-south",
      "displayName": "I-280 South Scenic",
      "createTime": "2026-08-25T02:11:25.998215Z",
      "state": "STATE_RUNNING",
      "routeAttributes": {
        "corridor": "I-280",
        "tier": "TIER_1"
      }
    }
  ]
}
```
