#!/usr/bin/env bash
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

###############################################################################
# BigQuery Geospatial Slippy Map & Quadtree Tile Math Deployment Script
#
# Deploys standard Mercator Slippy Map UDFs (tile2lat, tile2lon, lon2tile, lat2tile)
# and a Table-Valued Function (TVF) generate_tile_grid(boundary_geom, zoom)
# that computes tile polygons with hierarchical quadtree pruning directly in BigQuery.
###############################################################################

set -euo pipefail

# Default Configuration
PROJECT_ID="${BIGQUERY_PROJECT:-$(gcloud config get-value project 2>/dev/null || echo "")}"
LOCATION="${BIGQUERY_LOCATION:-us}"
DATASET_ID="geospatial_tiles"

show_help() {
    cat <<EOF
Usage: $0 [options]

Deploys persistent Slippy Map UDFs and generate_tile_grid TVF to BigQuery.

Options:
  --project-id <id>     GCP Project ID (default: ${PROJECT_ID:-current gcloud project})
  --location <region>   BigQuery processing region (default: ${LOCATION})
  --dataset <id>        Target dataset name (default: ${DATASET_ID})
  -h, --help            Show this help documentation
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --project-id)
            PROJECT_ID="$2"
            shift 2
            ;;
        --location)
            LOCATION="$2"
            shift 2
            ;;
        --dataset)
            DATASET_ID="$2"
            shift 2
            ;;
        -h|--help)
            show_help
            ;;
        *)
            echo "Unknown option: $1" >&2
            show_help
            ;;
    esac
done

if [[ -z "${PROJECT_ID}" ]]; then
    echo "Error: Must specify GCP project via --project-id or BIGQUERY_PROJECT environment variable." >&2
    exit 1
fi

echo "================================================================"
echo "DEPLOYING SLIPPY MAP & QUADTREE TILING FUNCTIONS TO BIGQUERY"
echo "================================================================"
echo "Project:  ${PROJECT_ID}"
echo "Location: ${LOCATION}"
echo "Dataset:  ${PROJECT_ID}.${DATASET_ID}"
echo "================================================================"

# 1. Ensure the dataset exists
echo "--> Verifying/Creating dataset ${PROJECT_ID}.${DATASET_ID}..."
bq mk --location="${LOCATION}" --dataset "${PROJECT_ID}:${DATASET_ID}" 2>/dev/null || true

# 2. Deploy tile2lat
echo "--> Deploying tile2lat..."
bq query --location="${LOCATION}" --use_legacy_sql=false "
CREATE OR REPLACE FUNCTION \`${PROJECT_ID}.${DATASET_ID}.tile2lat\`(y INT64, z INT64) RETURNS FLOAT64 AS (
  ATAN(SINH(ACOS(-1) * (1.0 - 2.0 * y / POW(2.0, z)))) * 180.0 / ACOS(-1)
);"

# 3. Deploy tile2lon
echo "--> Deploying tile2lon..."
bq query --location="${LOCATION}" --use_legacy_sql=false "
CREATE OR REPLACE FUNCTION \`${PROJECT_ID}.${DATASET_ID}.tile2lon\`(x INT64, z INT64) RETURNS FLOAT64 AS (
  CAST(x AS FLOAT64) / POW(2.0, z) * 360.0 - 180.0
);"

# 4. Deploy lon2tile
echo "--> Deploying lon2tile..."
bq query --location="${LOCATION}" --use_legacy_sql=false "
CREATE OR REPLACE FUNCTION \`${PROJECT_ID}.${DATASET_ID}.lon2tile\`(lon FLOAT64, z INT64) RETURNS INT64 AS (
  CAST(FLOOR((lon + 180.0) / 360.0 * POW(2.0, z)) AS INT64)
);"

# 5. Deploy lat2tile
echo "--> Deploying lat2tile..."
bq query --location="${LOCATION}" --use_legacy_sql=false "
CREATE OR REPLACE FUNCTION \`${PROJECT_ID}.${DATASET_ID}.lat2tile\`(lat FLOAT64, z INT64) RETURNS INT64 AS (
  CAST(FLOOR(
    (1.0 - LN(TAN(lat * ACOS(-1) / 180.0) + 1.0 / COS(lat * ACOS(-1) / 180.0)) / ACOS(-1)) 
    / 2.0 * POW(2.0, z)
  ) AS INT64)
);"

# 6. Deploy generate_tile_grid Table Function (Hierarchical Quadtree Pruning TVF)
echo "--> Deploying generate_tile_grid table function..."
bq query --location="${LOCATION}" --use_legacy_sql=false "
CREATE OR REPLACE TABLE FUNCTION \`${PROJECT_ID}.${DATASET_ID}.generate_tile_grid\`(
  boundary_geom GEOGRAPHY, 
  zoom INT64
) AS (
  WITH
    -- 1. Calculate Tile Range at Zoom 10 covering the BBox of the area
    z10_params AS (
      SELECT 
          boundary_geom,
          \`${PROJECT_ID}.${DATASET_ID}.lon2tile\`(ST_BOUNDINGBOX(boundary_geom).xmin, 10) as min_x,
          \`${PROJECT_ID}.${DATASET_ID}.lon2tile\`(ST_BOUNDINGBOX(boundary_geom).xmax, 10) as max_x,
          \`${PROJECT_ID}.${DATASET_ID}.lat2tile\`(ST_BOUNDINGBOX(boundary_geom).ymax, 10) as min_y,
          \`${PROJECT_ID}.${DATASET_ID}.lat2tile\`(ST_BOUNDINGBOX(boundary_geom).ymin, 10) as max_y
    ),
    
    -- 2. Generate candidate Zoom 10 tiles
    z10_candidates AS (
      SELECT 
          boundary_geom,
          x, y, 10 as z
      FROM z10_params,
      UNNEST(GENERATE_ARRAY(min_x, max_x)) x,
      UNNEST(GENERATE_ARRAY(min_y, max_y)) y
    ),
    
    -- Calculate geometries for Zoom 10 candidates
    z10_geoms AS (
      SELECT
          x, y, z,
          ST_MAKEPOLYGON(ST_MAKELINE([
              ST_GEOGPOINT(\`${PROJECT_ID}.${DATASET_ID}.tile2lon\`(x, z), \`${PROJECT_ID}.${DATASET_ID}.tile2lat\`(y, z)),
              ST_GEOGPOINT(\`${PROJECT_ID}.${DATASET_ID}.tile2lon\`(x+1, z), \`${PROJECT_ID}.${DATASET_ID}.tile2lat\`(y, z)),
              ST_GEOGPOINT(\`${PROJECT_ID}.${DATASET_ID}.tile2lon\`(x+1, z), \`${PROJECT_ID}.${DATASET_ID}.tile2lat\`(y+1, z)),
              ST_GEOGPOINT(\`${PROJECT_ID}.${DATASET_ID}.tile2lon\`(x, z), \`${PROJECT_ID}.${DATASET_ID}.tile2lat\`(y+1, z)),
              ST_GEOGPOINT(\`${PROJECT_ID}.${DATASET_ID}.tile2lon\`(x, z), \`${PROJECT_ID}.${DATASET_ID}.tile2lat\`(y, z))
          ])) as tile_geom,
          boundary_geom
      FROM z10_candidates
    ),
    
    -- Step 1 Spatial Pruning: Classify Zoom 10 tiles
    z10_classified AS (
      SELECT 
        x, y, z,
        tile_geom,
        CASE 
          WHEN ST_CONTAINS(boundary_geom, tile_geom) THEN \"inside\"
          WHEN ST_INTERSECTS(tile_geom, boundary_geom) THEN \"border\"
          ELSE \"outside\"
        END as status,
        boundary_geom
      FROM z10_geoms
    ),
    
    -- 3. Step 2: Zoom 12 Expansion
    z12_candidates AS (
      -- Expand \"inside\" tiles mathematically
      SELECT 
        cx as x, cy as y, 12 as z,
        \"inside\" as status,
        boundary_geom
      FROM z10_classified,
      UNNEST(GENERATE_ARRAY(x * 4, (x + 1) * 4 - 1)) cx,
      UNNEST(GENERATE_ARRAY(y * 4, (y + 1) * 4 - 1)) cy
      WHERE status = \"inside\"
      
      UNION ALL
      
      -- Expand \"border\" tiles
      SELECT 
        cx as x, cy as y, 12 as z,
        \"candidate\" as status,
        boundary_geom
      FROM z10_classified,
      UNNEST(GENERATE_ARRAY(x * 4, (x + 1) * 4 - 1)) cx,
      UNNEST(GENERATE_ARRAY(y * 4, (y + 1) * 4 - 1)) cy
      WHERE status = \"border\"
    ),
    
    -- Calculate geometries for Zoom 12 candidates
    z12_geoms AS (
      SELECT
        c.x, c.y, c.z,
        ST_MAKEPOLYGON(ST_MAKELINE([
            ST_GEOGPOINT(\`${PROJECT_ID}.${DATASET_ID}.tile2lon\`(c.x, c.z), \`${PROJECT_ID}.${DATASET_ID}.tile2lat\`(c.y, c.z)),
            ST_GEOGPOINT(\`${PROJECT_ID}.${DATASET_ID}.tile2lon\`(c.x+1, c.z), \`${PROJECT_ID}.${DATASET_ID}.tile2lat\`(c.y, c.z)),
            ST_GEOGPOINT(\`${PROJECT_ID}.${DATASET_ID}.tile2lon\`(c.x+1, c.z), \`${PROJECT_ID}.${DATASET_ID}.tile2lat\`(c.y+1, c.z)),
            ST_GEOGPOINT(\`${PROJECT_ID}.${DATASET_ID}.tile2lon\`(c.x, c.z), \`${PROJECT_ID}.${DATASET_ID}.tile2lat\`(c.y+1, c.z)),
            ST_GEOGPOINT(\`${PROJECT_ID}.${DATASET_ID}.tile2lon\`(c.x, c.z), \`${PROJECT_ID}.${DATASET_ID}.tile2lat\`(c.y, c.z))
        ])) as tile_geom,
        c.status as initial_status,
        c.boundary_geom
      FROM z12_candidates c
    ),
    
    -- Step 2 Spatial Pruning: Classify Zoom 12 tiles
    z12_classified AS (
      SELECT 
        x, y, z,
        tile_geom,
        CASE 
          WHEN initial_status = \"inside\" THEN \"inside\"
          WHEN ST_CONTAINS(boundary_geom, tile_geom) THEN \"inside\"
          WHEN ST_INTERSECTS(tile_geom, boundary_geom) THEN \"border\"
          ELSE \"outside\"
        END as status,
        boundary_geom
      FROM z12_geoms
    ),
    
    -- 4. Step 3: Final target Zoom Expansion
    z_final_candidates AS (
      -- Expand \"inside\" tiles mathematically
      SELECT 
        cx as x, cy as y, zoom as z,
        \"inside\" as status,
        boundary_geom
      FROM z12_classified,
      UNNEST(GENERATE_ARRAY(x * CAST(POW(2, zoom - 12) AS INT64), (x + 1) * CAST(POW(2, zoom - 12) AS INT64) - 1)) cx,
      UNNEST(GENERATE_ARRAY(y * CAST(POW(2, zoom - 12) AS INT64), (y + 1) * CAST(POW(2, zoom - 12) AS INT64) - 1)) cy
      WHERE status = \"inside\"
      
      UNION ALL
      
      -- Expand \"border\" tiles
      SELECT 
        cx as x, cy as y, zoom as z,
        \"candidate\" as status,
        boundary_geom
      FROM z12_classified,
      UNNEST(GENERATE_ARRAY(x * CAST(POW(2, zoom - 12) AS INT64), (x + 1) * CAST(POW(2, zoom - 12) AS INT64) - 1)) cx,
      UNNEST(GENERATE_ARRAY(y * CAST(POW(2, zoom - 12) AS INT64), (y + 1) * CAST(POW(2, zoom - 12) AS INT64) - 1)) cy
      WHERE status = \"border\"
    ),
    
    -- Calculate geometries for final target tiles
    z_final_geoms AS (
      SELECT
        c.x, c.y, c.z,
        ST_MAKEPOLYGON(ST_MAKELINE([
            ST_GEOGPOINT(\`${PROJECT_ID}.${DATASET_ID}.tile2lon\`(c.x, c.z), \`${PROJECT_ID}.${DATASET_ID}.tile2lat\`(c.y, c.z)),
            ST_GEOGPOINT(\`${PROJECT_ID}.${DATASET_ID}.tile2lon\`(c.x+1, c.z), \`${PROJECT_ID}.${DATASET_ID}.tile2lat\`(c.y, c.z)),
            ST_GEOGPOINT(\`${PROJECT_ID}.${DATASET_ID}.tile2lon\`(c.x+1, c.z), \`${PROJECT_ID}.${DATASET_ID}.tile2lat\`(c.y+1, c.z)),
            ST_GEOGPOINT(\`${PROJECT_ID}.${DATASET_ID}.tile2lon\`(c.x, c.z), \`${PROJECT_ID}.${DATASET_ID}.tile2lat\`(c.y+1, c.z)),
            ST_GEOGPOINT(\`${PROJECT_ID}.${DATASET_ID}.tile2lon\`(c.x, c.z), \`${PROJECT_ID}.${DATASET_ID}.tile2lat\`(c.y, c.z))
        ])) as tile_geom,
        c.status as initial_status,
        c.boundary_geom
      FROM z_final_candidates c
    ),
    
    -- Step 3 Spatial Pruning: Classify and Clip final target tiles
    z_final_classified AS (
      SELECT 
        x, y, z,
        tile_geom,
        CASE 
          WHEN initial_status = \"inside\" THEN \"inside\"
          WHEN ST_CONTAINS(boundary_geom, tile_geom) THEN \"inside\"
          WHEN ST_INTERSECTS(tile_geom, boundary_geom) THEN \"border\"
          ELSE \"outside\"
        END as status,
        boundary_geom
      FROM z_final_geoms
    )

  -- Output result sets
  SELECT
      \"MASTER_BOUNDARY\" as id,
      ST_ASGEOJSON(boundary_geom) as geometry,
      CAST(NULL AS STRING) as boundary
  UNION ALL
  SELECT
      format(\"%d-%d-%d.1\", z, x, y) as id,
      ST_ASGEOJSON(tile_geom) as geometry,
      CASE 
        WHEN status = \"inside\" THEN ST_ASGEOJSON(tile_geom)
        ELSE ST_ASGEOJSON(ST_INTERSECTION(tile_geom, boundary_geom))
      END as boundary
  FROM z_final_classified
  WHERE status IN (\"inside\", \"border\")
);"

echo ""
echo "================================================================"
echo "DEPLOYMENT COMPLETE! Slippy tile functions ready in ${PROJECT_ID}.${DATASET_ID}"
echo "================================================================"
