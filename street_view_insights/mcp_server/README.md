# Street View Imagery Insights MCP Server

This Model Context Protocol (MCP) server enables AI models and agents to securely search, query, and visually analyze Google Street View physical asset datasets (like utility poles and road signs) and panoramas. 

It implements a **strict Data Loss Prevention (DLP) boundary**: no raw images or crops are ever sent out of the Google Cloud Platform (GCP) network. Instead, the server fetches the images from GCS, crops or rectifies them, runs Vertex AI Gemini directly inside GCP, and returns only the text or structured JSON results back to the client.

---

## 1. Using the Hosted MCP Server

To use the already-deployed instance in your MCP-compatible IDE or [Antigravity CLI](https://antigravity.google/docs/cli/mcp#antigravity-cli), add the following configuration to your `mcp_config.json` file:

```json
{
  "mcpServers": {
    "streetview-imagery-insights": {
      "url": "<use the service url generated from your deployment>"
    }
  }
}
```

Your service url (after deployment) can be retrieved using:

```
gcloud run services describe streetview-imagery-insights-mcp \
  --project "${PROJECT_ID}" \
  --region "${REGION}"
```

### Supported Tools

Once connected, your agent will have access to the following 5 tools:
1. **`list_assets`**: Find assets by type or within a geographic radius (uses BigQuery).
   * **Example:**
     ```bash
     streetview-imagery-insights list_assets <gcp-project>.imagery_insights___us
     ```
2. **`get_asset_observations`**: Retrieve all historical image captures/observations for a specific asset.
3. **`analyze_cropped_asset`**: Downloads full-frame image, crops to asset bounding box, runs Gemini analysis in GCP, and returns text results.
4. **`analyze_full_frame_context`**: Submits full-frame image (optionally with bounding box drawn) to Gemini for contextual scene understanding.
5. **`analyze_panorama_perspective`**: Extracts a perspective crop from a spherical panorama (heading, pitch, fov) and runs Gemini analysis.

---

## 2. Deploying a New Instance to Cloud Run

If you wish to host your own instance of the MCP server, follow these steps:

### Prerequisites
* A GCP Project with the following APIs enabled:
  * Cloud Run API
  * Cloud Build API
  * Vertex AI API
  * BigQuery API
* The Google Cloud SDK (`gcloud` CLI) installed locally.
* Valid Google Cloud credentials:
  ```bash
  gcloud auth login
  gcloud auth application-default login
  gcloud config set project <YOUR_PROJECT_ID>
  ```

### Local Development / Running Locally
To test the server locally:
1. Configure the harness by updating the JSON as follows:
   ```json
   {
     "mcpServers": {
       "streetview-imagery-insights": {
         "url": "http://localhost:8080/mcp"
       }
     }
   }
   ```
2. Create a virtual environment and activate it:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Run the server to override the SSE transport with plain unauthenticated HTTP:
   ```bash
   MCP_TRANSPORT=http python main.py
   ```
   *Note: Ensure your terminal has access to GCP credentials (`GOOGLE_APPLICATION_CREDENTIALS` or configured via `gcloud`).*
5. To deactivate and clean up the virtual environment:
   ```bash
   deactivate
   rm -rf .venv
   ```

### Cloud Run Deployment
1. Navigate to the `mcp_server` directory:
   ```bash
   cd street_view_insights/mcp_server
   ```
2. Run the deployment script:
   ```bash
   ./deploy.sh
   ```

The script will automatically:
1. Package the source code.
2. Submit a build to Google Cloud Build to create the container image.
3. Push the container image to GCP Artifact Registry.
4. Deploy the container to a new Google Cloud Run service named `streetview-imagery-insights-mcp` with unauthenticated access allowed.

> If your GCP project or organization does not allow unauthenticated applications, modify the `--allow-unauthenticated` flag (in `deploy.sh`)  with `--no-allow-unauthenticated` when you deploy.  You can then use [gcloud run services proxy](https://docs.cloud.google.com/sdk/gcloud/reference/run/services/proxy) to connect from your local machine to the Cloud Run application.
