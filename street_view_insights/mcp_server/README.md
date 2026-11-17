# Street View Imagery Insights MCP Server

This Model Context Protocol (MCP) server enables AI models and agents to securely search, query, and visually analyze Google Maps Platform Street View Insights asset datasets (`full_frame_assets_latest`, `full_frame_observations_latest`, and `pano_observations_latest`) using **`gemini-4-hydrogen`**.

It enforces **defense-in-depth security controls**:
- **Authenticated Access Only**: Deployed with `--no-allow-unauthenticated` on Cloud Run plus application-layer Google OIDC Bearer token verification (`BearerAuthMiddleware`).
- **Strict Identifier & Dataset Allowlisting**: Rejects SQL injection and restricts queries to allowlisted Street View Insights datasets (`imagery_insights___us`, `imagery_insights___eu`) under a per-query `maximum_bytes_billed` cap.
- **Confused-Deputy GCS Guard & Zero Disk Caching**: Enforces an explicit `ALLOWED_GCS_PREFIX` bucket allowlist and streams Street View imagery strictly in memory (`io.BytesIO`, zero `/tmp` disk writes) so raw imagery never leaves GCP.

---

## 1. Deploying Your Own Authenticated Cloud Run Instance

### Prerequisites
* A GCP project with Cloud Run, Cloud Build, BigQuery, Cloud Storage, and Vertex AI APIs enabled.
* A dedicated least-privilege service account granted:
  * `roles/bigquery.jobUser` on `PROJECT_ID`
  * `roles/bigquery.dataViewer` on your subscribed Street View Insights dataset
  * `roles/storage.objectViewer` on your Street View Insights imagery bucket
  * `roles/aiplatform.user` on `PROJECT_ID`

### Deployment
```bash
cd street_view_insights/mcp_server

export PROJECT_ID="YOUR_PROJECT_ID"
export REGION="us-central1"
export SERVICE_ACCOUNT_EMAIL="svi-mcp-sa@${PROJECT_ID}.iam.gserviceaccount.com"
export ALLOWED_GCS_PREFIX="gs://YOUR_SVI_IMAGERY_BUCKET/"
export ALLOWED_CALLER_EMAILS="your-user@example.com"

./deploy.sh
```

---

## 2. Connecting Your MCP Client

### Option A: Local Authenticated Cloud Run Proxy (Recommended)
Run the Cloud Run local proxy, which attaches your `gcloud` OIDC identity token automatically:

```bash
gcloud run services proxy streetview-imagery-insights-mcp \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --port=8080 \
  --quiet
```

Then point your `mcp_config.json` at the local authenticated proxy:

```json
{
  "mcpServers": {
    "streetview-imagery-insights": {
      "url": "http://127.0.0.1:8080/sse"
    }
  }
}
```

### Option B: Local `stdio` Transport
```bash
pip install -r requirements.txt
export PROJECT_ID="YOUR_PROJECT_ID"
export ALLOWED_GCS_PREFIX="gs://YOUR_SVI_IMAGERY_BUCKET/"
export MCP_TRANSPORT="stdio"
python main.py
```

### Supported Tools
1. **`list_assets`**: Find assets by type or within a geographic radius (`full_frame_assets_latest`).
2. **`get_asset_observations`**: Retrieve latest image observations for an asset (`full_frame_observations_latest`).
3. **`analyze_cropped_asset`**: Streams the full-frame image in memory, crops to `bbox`, and runs `gemini-4-hydrogen`.
4. **`analyze_full_frame_context`**: Streams the full-frame image (with optional `bbox` overlay) and runs `gemini-4-hydrogen`.
5. **`analyze_panorama_perspective`**: Extracts an in-memory perspective crop from `pano_observations_latest` and runs `gemini-4-hydrogen`.
