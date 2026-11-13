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
| **Max Attribute Pairs** | Up to **25 key-value pairs** per route (`count <= 25`). | `400 INVALID_ARGUMENT: Route attributes must be 25 or less.` |
| **Key & Value Length** | Non-empty strings of **1 to 100 characters** each (counted in **Unicode code points**). | `400 INVALID_ARGUMENT: Route attribute key/value must be between 1 and 100 characters.` |
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

# 2. Define custom attributes map (Max 25 pairs, stringified values, no 'goog' prefix)
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
    """Validates attributes against Discovery Document 20261104 constraints before API dispatch."""
    if len(attributes) > 25:
        raise ValueError(f"Too many attributes: {len(attributes)} (max 25 allowed)")
    
    for k, v in attributes.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise TypeError(f"Attribute key/value for '{k}' must be a string, got {type(v).__name__}")
        if not (1 <= len(k) <= 100):
            raise ValueError(f"Attribute key '{k}' must be 1-100 characters")
        if not (1 <= len(v) <= 100):
            raise ValueError(f"Attribute value for '{k}' must be 1-100 characters")
        if re.match(r"^goog", k):
            raise ValueError(f"Attribute key '{k}' cannot start with 'goog'")

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
  if (entries.length > 25) {
    throw new Error(`routeAttributes cannot exceed 25 entries (got ${entries.length})`);
  }

  for (const [key, value] of entries) {
    const keyLen = Array.from(key).length;
    const valLen = Array.from(value).length;
    if (keyLen < 1 || keyLen > 100) {
      throw new Error(`Attribute key '${key}' length must be 1-100 characters.`);
    }
    if (valLen < 1 || valLen > 100) {
      throw new Error(`Attribute value for '${key}' must be 1-100 characters.`);
    }
    if (key.startsWith('goog')) {
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

### E. Go (`net/http` / Unicode Attribute Governance)

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
	"strings"
	"unicode/utf8"
)

func validateRouteAttributes(attrs map[string]string) error {
	if len(attrs) > 25 {
		return fmt.Errorf("routeAttributes cannot exceed 25 entries (got %d)", len(attrs))
	}
	for k, v := range attrs {
		if n := utf8.RuneCountInString(k); n < 1 || n > 100 {
			return fmt.Errorf("attribute key %q must be 1-100 Unicode code points", k)
		}
		if n := utf8.RuneCountInString(v); n < 1 || n > 100 {
			return fmt.Errorf("attribute value for %q must be 1-100 Unicode code points", k)
		}
		if strings.HasPrefix(k, "goog") {
			return fmt.Errorf("attribute key %q cannot start with reserved prefix 'goog'", k)
		}
	}
	return nil
}

func createTaggedRoute(ctx context.Context, projectID, routeID, displayName, token string, attrs map[string]string) ([]byte, error) {
	if err := validateRouteAttributes(attrs); err != nil {
		return nil, err
	}
	payload := map[string]any{
		"displayName": displayName,
		"dynamicRoute": map[string]any{
			"origin":      map[string]float64{"latitude": 35.6895, "longitude": 139.6917},
			"destination": map[string]float64{"latitude": 35.6899, "longitude": 139.6950},
		},
		"routeAttributes": attrs,
	}
	encoded, err := json.Marshal(payload)
	if err != nil {
		return nil, err
	}
	endpoint := fmt.Sprintf(
		"https://roads.googleapis.com/selection/v1/projects/%s/selectedRoutes?selectedRouteId=%s",
		url.PathEscape(projectID),
		url.QueryEscape(routeID),
	)
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, bytes.NewReader(encoded))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", "Bearer "+token)
	req.Header.Set("X-Goog-User-Project", projectID)
	req.Header.Set("Content-Type", "application/json")

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
		return nil, fmt.Errorf("createTaggedRoute failed [%d]: %s", resp.StatusCode, string(raw))
	}
	return raw, nil
}

func main() {
	res, err := createTaggedRoute(
		context.Background(),
		"my-roads-project",
		"jp_tokyo_shutoko_c1",
		"Tokyo Shuto C1 Loop",
		os.Getenv("GOOGLE_OAUTH_ACCESS_TOKEN"),
		map[string]string{
			"country":         "JP",
			"corridor":        "shutoko_c1",
			"priority":        "HIGHWAY",
			"speed_limit_kmh": "60",
		},
	)
	if err != nil {
		panic(err)
	}
	fmt.Println("Created Tagged Route:", string(res))
}
```

---

### F. Rust (`RoadsSelectionClient` / Unicode Attribute Validator)

```rust
use std::collections::BTreeMap;
use std::process::Command;

pub fn validate_route_attributes(attrs: &BTreeMap<String, String>) -> Result<(), String> {
    if attrs.len() > 25 {
        return Err(format!("routeAttributes cannot exceed 25 entries (got {})", attrs.len()));
    }
    for (k, v) in attrs {
        let key_len = k.chars().count();
        let val_len = v.chars().count();
        if !(1..=100).contains(&key_len) {
            return Err(format!("attribute key '{}' must be 1-100 Unicode code points", k));
        }
        if !(1..=100).contains(&val_len) {
            return Err(format!("attribute value for '{}' must be 1-100 Unicode code points", k));
        }
        if k.starts_with("goog") {
            return Err(format!("attribute key '{}' cannot start with reserved prefix 'goog'", k));
        }
    }
    Ok(())
}

fn main() -> Result<(), String> {
    let mut attrs = BTreeMap::new();
    attrs.insert("country".to_string(), "JP".to_string());
    attrs.insert("corridor".to_string(), "shutoko_c1".to_string());
    attrs.insert("priority".to_string(), "HIGHWAY".to_string());
    attrs.insert("speed_limit_kmh".to_string(), "60".to_string());
    validate_route_attributes(&attrs)?;

    let project_id = "my-roads-project";
    let token = std::env::var("GOOGLE_OAUTH_ACCESS_TOKEN").unwrap_or_default();
    let url = format!(
        "https://roads.googleapis.com/selection/v1/projects/{}/selectedRoutes?selectedRouteId=jp_tokyo_shutoko_c1",
        project_id
    );
    let body = r#"{
      "displayName": "Tokyo Shuto C1 Loop",
      "dynamicRoute": {
        "origin": { "latitude": 35.6895, "longitude": 139.6917 },
        "destination": { "latitude": 35.6899, "longitude": 139.6950 }
      },
      "routeAttributes": {
        "country": "JP",
        "corridor": "shutoko_c1",
        "priority": "HIGHWAY",
        "speed_limit_kmh": "60"
      }
    }"#;

    let out = Command::new("curl")
        .args(["-sS", "-X", "POST"])
        .arg("-H")
        .arg(format!("Authorization: Bearer {}", token))
        .arg("-H")
        .arg(format!("X-Goog-User-Project: {}", project_id))
        .args(["-H", "Content-Type: application/json", "--data-raw", body])
        .arg(&url)
        .output()
        .map_err(|e| e.to_string())?;

    if !out.status.success() {
        return Err(String::from_utf8_lossy(&out.stderr).into_owned());
    }
    println!("Created Tagged Route: {}", String::from_utf8_lossy(&out.stdout));
    Ok(())
}
```

---

## 4. Expected API Response

```json
{
  "name": "projects/123456789012/selectedRoutes/jp-tokyo-shutoko-c1",
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
