# Sample Code: Bulk Deletion via `BatchDeleteSelectedRoutes`

This guide demonstrates how to delete up to **1,000 SelectedRoutes** in a single atomic/batched API call using **`BatchDeleteSelectedRoutes` (`POST :batchDelete`)**.

---

## 1. Overview & Use Cases

When retiring old road networks, decommissioning expired detour corridors, or re-aligning regional boundaries, deleting routes one-by-one with `DeleteSelectedRoute` causes long runtimes.

**`BatchDeleteSelectedRoutes`** allows:
* **High-Throughput Cleanup**: Deletes up to **1,000 routes** in a single API call.
* **Simple Resource Name Targeting**: Specify an array of full resource names (`projects/{project}/selectedRoutes/{id}`).
* **Zero Payload Overhead**: Returns an empty response (`{}`) on success.

---

## 2. API Contract & Validation Constraints

* **HTTP Method**: `POST`
* **URL**: `https://roads.googleapis.com/selection/v1/projects/{project}/selectedRoutes:batchDelete`
* **Request Body (`BatchDeleteSelectedRoutesRequest`)**:
  - `parent`: `projects/{project}`
  - `names`: Array of strings (`projects/{project}/selectedRoutes/{id}`), maximum 1,000 items.

> [!IMPORTANT]
> **Parent Project Matching**: Every route name in the `names` array must strictly match the `parent` project identifier specified in the request. If there is a mismatch (e.g. using project name in `parent` but project number in `names`), the API returns `400 INVALID_ARGUMENT: SelectedRoute project does not match the parent project`.

---

## 3. Implementation Examples

### A. Shell Client (`scripts/roadsselection_v1_util.sh`)

```bash
#!/bin/bash
set -euo pipefail

source scripts/roadsselection_v1.sh
source scripts/roadsselection_v1_helpers.sh
source scripts/roadsselection_v1_util.sh

PROJECT_ID="my-roads-project"

# Delete a batch of routes by names
echo "Batch deleting expired detour routes..."
roadsselection_v1_selectedroute_batch_delete_by_names "${PROJECT_ID}" \
  "projects/${PROJECT_ID}/selectedRoutes/detour-corridor-01" \
  "projects/${PROJECT_ID}/selectedRoutes/detour-corridor-02" \
  "projects/${PROJECT_ID}/selectedRoutes/detour-corridor-03"

echo "✅ Successfully executed batchDelete."
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
  "https://roads.googleapis.com/selection/v1/projects/${PROJECT_ID}/selectedRoutes:batchDelete" \
  -d '{
    "parent": "projects/'"${PROJECT_ID}"'",
    "names": [
      "projects/'"${PROJECT_ID}"'/selectedRoutes/detour-corridor-01",
      "projects/'"${PROJECT_ID}"'/selectedRoutes/detour-corridor-02",
      "projects/'"${PROJECT_ID}"'/selectedRoutes/detour-corridor-03"
    ]
  }' | jq .
```

---

### C. Python (`requests` / Bulk Cleanup)

```python
import google.auth
from google.auth.transport.requests import Request
import requests

def batch_delete_routes(project_id: str, route_ids: list) -> bool:
    """Deletes up to 1000 SelectedRoutes in a single request."""
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    credentials.refresh(Request())

    url = f"https://roads.googleapis.com/selection/v1/projects/{project_id}/selectedRoutes:batchDelete"
    headers = {
        "Authorization": f"Bearer {credentials.token}",
        "X-Goog-User-Project": project_id,
        "Content-Type": "application/json"
    }

    names = [f"projects/{project_id}/selectedRoutes/{rid}" for rid in route_ids]
    payload = {
        "parent": f"projects/{project_id}",
        "names": names
    }

    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()
    return True

if __name__ == "__main__":
    routes_to_delete = ["detour-corridor-01", "detour-corridor-02", "detour-corridor-03"]
    success = batch_delete_routes("my-roads-project", routes_to_delete)
    if success:
        print(f"Successfully batch deleted {len(routes_to_delete)} routes.")
```

---

### D. TypeScript (Node.js / Bulk Cleanup)

```typescript
import { GoogleAuth } from 'google-auth-library';

async function batchDeleteSelectedRoutes(
  projectId: string,
  routeIds: string[]
): Promise<void> {
  const auth = new GoogleAuth({
    scopes: ['https://www.googleapis.com/auth/cloud-platform'],
  });
  const client = await auth.getClient();
  const tokenResponse = await client.getAccessToken();
  const accessToken = tokenResponse.token;

  const url = `https://roads.googleapis.com/selection/v1/projects/${projectId}/selectedRoutes:batchDelete`;

  const names = routeIds.map(
    (id) => `projects/${projectId}/selectedRoutes/${id}`
  );

  const payload = {
    parent: `projects/${projectId}`,
    names,
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
    throw new Error(`batchDelete failed [${response.status}]: ${errorText}`);
  }
}

export { batchDeleteSelectedRoutes };
```

---

## 4. Expected API Response

On success, the API returns an empty JSON object:
```json
{}
```
