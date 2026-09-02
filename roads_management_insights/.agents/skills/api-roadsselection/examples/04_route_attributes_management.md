# Sample Code: Custom Route Attributes & Tagging Governance (`routeAttributes`)

This guide demonstrates how to configure, structure, and govern custom metadata tags (**`routeAttributes`**) on **`SelectedRoute`** resources in the Roads Selection API v1.

---

## 1. Overview & Business Value

Custom `routeAttributes` attach arbitrary domain metadata to monitored corridors. These attributes flow directly into downstream telemetry pipelines:
* **BigQuery Column Mapping**: Automatically populated into BigQuery tables (`routes_status`, `historical_travel_times`) for SQL partitioning and clustering.
* **Pub/Sub Telemetry Filtering**: Emitted in real-time message metadata for streaming topic subscription filters.
* **Regional & Multi-Country Governance**: Tag corridors by country (`country: "JP"`), district, maintenance tier, or speed limit.

---

## 2. Strict Proto Validation Rules

According to the canonical Protobuf service definition:

| Rule | Constraint | Failure Consequence |
| :--- | :--- | :--- |
| **Max Attribute Pairs** | Up to **10 key-value pairs** per route (`len($) <= 10`). | `400 INVALID_ARGUMENT: Route attributes must be 10 or less.` |
| **Key & Value Length** | **1 to 100 bytes** each in UTF-8 (`len(key.encode('utf-8')) <= 100`). Multi-byte characters (e.g. CJK 3 bytes/char) reduce effective character count. | `400 INVALID_ARGUMENT: Route attribute key/value must be between 1 and 100 bytes.` |
| **Prohibited Prefix** | Keys **must NOT start with `goog`** (`not matches(key, '^goog.*')`). | `400 INVALID_ARGUMENT: Route attribute key must not start with 'goog'.` |
| **Type Constraint** | Values must strictly be **strings** (numeric values like speed limits must be stringified, e.g. `"65"`). | JSON type deserialization error. |

---

## 3. Implementation Examples

### A. Creating a Route with Full Enterprise Attributes (Shell)

```bash
#!/bin/bash
set -euo pipefail

source scripts/roadsselection_v1.sh
source scripts/roadsselection_v1_helpers.sh

PROJECT_ID="my-roads-project"
ROUTE_ID="us-ca-baybridge-wb"

# 1. Define geometry
DYN_JSON=$(roadsselection_v1_dynamicroute_json 37.8270 -122.3780 37.7950 -122.3930 '[]')

# 2. Define custom attributes map (Max 10 pairs, stringified values, no 'goog' prefix)
ROUTE_JSON=$(roadsselection_v1_selectedroute_json \
  "I-80 Bay Bridge Westbound Express" \
  "${DYN_JSON}" \
  '{
    "country": "US",
    "state": "CA",
    "jurisdiction": "caltrans_d4",
    "corridor": "I-80",
    "direction": "WESTBOUND",
    "priority": "HIGHWAY",
    "toll_managed": "true",
    "speed_limit_mph": "50",
    "asset_tag": "SF-OAK-001"
  }')

# 3. Create route
roadsselection_v1_selectedroute_create "${PROJECT_ID}" "${ROUTE_JSON}" "${ROUTE_ID}"
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
  "https://roads.googleapis.com/selection/v1/projects/${PROJECT_ID}/selectedRoutes?selectedRouteId=us-ca-baybridge-wb" \
  -d '{
    "displayName": "I-80 Bay Bridge Westbound Express",
    "dynamicRoute": {
      "origin": { "latitude": 37.8270, "longitude": -122.3780 },
      "destination": { "latitude": 37.7950, "longitude": -122.3930 }
    },
    "routeAttributes": {
      "country": "US",
      "state": "CA",
      "jurisdiction": "caltrans_d4",
      "corridor": "I-80",
      "direction": "WESTBOUND",
      "priority": "HIGHWAY",
      "toll_managed": "true",
      "speed_limit_mph": "50",
      "asset_tag": "SF-OAK-001"
    }
  }' | jq .
```

---

### C. Python (`requests` / Attribute Validator)

```python
import json
import re
import google.auth
from google.auth.transport.requests import Request
import requests

def validate_route_attributes(attributes: dict):
    """Validates attributes against Proto constraints before API dispatch."""
    if len(attributes) > 10:
        raise ValueError(f"Too many attributes: {len(attributes)} (max 10 allowed)")
    
    for k, v in attributes.items():
        if not (1 <= len(k) <= 100):
            raise ValueError(f"Attribute key '{k}' must be 1-100 characters")
        if not (1 <= len(str(v)) <= 100):
            raise ValueError(f"Attribute value for '{k}' must be 1-100 characters")
        if re.match(r"^goog", k, re.IGNORECASE):
            raise ValueError(f"Attribute key '{k}' cannot start with 'goog'")
        if not isinstance(v, str):
            raise TypeError(f"Attribute value for '{k}' must be a string, got {type(v).__name__}")

def create_tagged_route(project_id: str, route_id: str, display_name: str, origin: tuple, destination: tuple, attributes: dict) -> dict:
    validate_route_attributes(attributes)

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
        },
        "routeAttributes": attributes
    }

    response = requests.post(url, params=params, headers=headers, json=payload)
    response.raise_for_status()
    return response.json()

if __name__ == "__main__":
    attrs = {
        "country": "JP",
        "corridor": "shutoko_c1",
        "priority": "HIGHWAY",
        "speed_limit_kmh": "60"
    }
    res = create_tagged_route(
        project_id="my-roads-project",
        route_id="jp-tokyo-shutoko-c1",
        display_name="Tokyo Shuto C1 Loop",
        origin=(35.6895, 139.6917),
        destination=(35.6899, 139.6950),
        attributes=attrs
    )
    print("Created Tagged Route:\n", json.dumps(res, indent=2))
```

---

### D. TypeScript (Node.js / Strong Typing & Validation)

```typescript
import { GoogleAuth } from 'google-auth-library';

type RouteAttributes = Record<string, string>;

interface LatLng {
  latitude: number;
  longitude: number;
}

interface CreateRouteOptions {
  projectId: string;
  routeId: string;
  displayName: string;
  origin: LatLng;
  destination: LatLng;
  intermediates?: LatLng[];
  attributes?: RouteAttributes;
}

function validateRouteAttributes(attributes?: RouteAttributes): void {
  if (!attributes) return;

  const entries = Object.entries(attributes);
  if (entries.length > 10) {
    throw new Error(`routeAttributes cannot exceed 10 entries (got ${entries.length})`);
  }

  for (const [key, value] of entries) {
    if (key.length < 1 || key.length > 100) {
      throw new Error(`Attribute key '${key}' length must be 1-100 characters.`);
    }
    if (value.length < 1 || value.length > 100) {
      throw new Error(`Attribute value for '${key}' must be 1-100 characters.`);
    }
    if (/^goog/i.test(key)) {
      throw new Error(`Attribute key '${key}' cannot start with 'goog'.`);
    }
  }
}

async function createTaggedRoute(options: CreateRouteOptions): Promise<any> {
  validateRouteAttributes(options.attributes);

  const auth = new GoogleAuth({
    scopes: ['https://www.googleapis.com/auth/cloud-platform'],
  });
  const client = await auth.getClient();
  const tokenResponse = await client.getAccessToken();
  const accessToken = tokenResponse.token;

  const url = `https://roads.googleapis.com/selection/v1/projects/${options.projectId}/selectedRoutes?selectedRouteId=${encodeURIComponent(options.routeId)}`;

  const body = {
    displayName: options.displayName,
    dynamicRoute: {
      origin: options.origin,
      destination: options.destination,
      intermediates: options.intermediates ?? [],
    },
    routeAttributes: options.attributes ?? {},
  };

  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${accessToken}`,
      'X-Goog-User-Project': options.projectId,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`createRoute failed [${response.status}]: ${errorText}`);
  }

  return await response.json();
}

export { createTaggedRoute, validateRouteAttributes, type CreateRouteOptions, type RouteAttributes };
```

---

## 4. Expected API Response

```json
{
  "name": "projects/35571336328/selectedRoutes/jp-tokyo-shutoko-c1",
  "displayName": "Tokyo Shuto C1 Loop",
  "dynamicRoute": {
    "origin": { "latitude": 35.6895, "longitude": 139.6917 },
    "destination": { "latitude": 35.6899, "longitude": 139.6950 }
  },
  "createTime": "2026-08-30T05:28:40.983311Z",
  "state": "STATE_VALIDATING",
  "routeAttributes": {
    "country": "JP",
    "corridor": "shutoko_c1",
    "priority": "HIGHWAY",
    "speed_limit_kmh": "60"
  }
}
```
