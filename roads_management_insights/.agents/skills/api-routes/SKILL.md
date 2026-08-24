---
name: api-routes
description: Use this skill for pathfinding, travel time estimation, and distance matrix calculations. Essential for understanding how RMI snaps waypoints to the road network using the Routes v2 engine. Make sure to use this skill whenever the user mentions Routes API v2, route calculation, travel duration, distance matrices, or directions pathfinding.
---

# Routes API Skill

This skill provides expert guidance and specialized tools for working with the Google Maps Platform Routes API v2, with specific context for its role in the Roads Management Insights (RMI) ecosystem.

---

## 1. Core Endpoints & Performance

The Routes API (v2) is a fast, robust engine for calculating travel routes and spatial distances. It features two primary endpoints:

### 1. Compute Routes
Get primary and alternate routes between an origin and destination, with up to 25 intermediate waypoints.
- **Endpoint**: `POST https://routes.googleapis.com/v1/computeRoutes`
- **Supported Modes**: `DRIVE`, `BICYCLE`, `WALK`, and `TWO_WHEELER`.

### 2. Compute Route Matrix
Get distance and duration for a set of origins and destinations (many-to-many matrix).
- **Endpoint**: `POST https://routes.googleapis.com/v1/computeRouteMatrix`

---

## 2. API Schema and JSON Layouts

### Compute Routes Request Body
The JSON body requires a structured origin, destination, and travel options:

```json
{
  "origin": {
    "location": {
      "latLng": {
        "latitude": 37.419,
        "longitude": -122.082
      }
    }
  },
  "destination": {
    "location": {
      "latLng": {
        "latitude": 37.417,
        "longitude": -122.079
      }
    }
  },
  "travelMode": "DRIVE",
  "routingPreference": "TRAFFIC_AWARE",
  "routeModifiers": {
    "avoidTolls": true,
    "avoidHighways": false,
    "avoidFerries": false,
    "avoidTunnels": true
  },
  "extraComputations": ["TRAFFIC_ON_ROUTE", "POLYLINE_DETAILS"]
}
```

### Route Modifiers & Advanced Road Structures
- **Route Modifiers**: Use `routeModifiers` to customize routing constraints:
  - `avoidTolls`: Avoid toll roads.
  - `avoidHighways`: Avoid highways.
  - `avoidFerries`: Avoid ferry crossings.
  - `avoidIndoor`: Avoid indoor navigation.
  - `avoidTunnels`: Avoid tunnels along the route.
- **Polyline Details (Structure Intelligence)**: When requesting `POLYLINE_DETAILS`, inspect structural metadata across route spans:
  - `bridgeInfo`: Bridge infrastructure spans.
  - `skywayInfo`: Skyway/elevated roadway spans.
  - `tunnelInfo`: Tunnel infrastructure spans.

---

## 3. The Crucial Field Mask Requirement

The Routes API v2 **strictly requires** a Field Mask header (`X-Goog-FieldMask`). If this header is missing or incorrect, the API returns a `400 Bad Request`.
- **For full details**: Use `*` (not recommended for high-performance production as it inflates response payload size).
- **For optimized routing**: Use explicit fields, e.g. `routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline`.

---

## 4. Error Reference & Troubleshooting

| Error Status / Issue | Root Cause | Exact Resolution Path |
| :--- | :--- | :--- |
| `400 BAD_REQUEST` (Missing mask) | `X-Goog-FieldMask` header was omitted | Add `-H "X-Goog-FieldMask: routes.duration,routes.distanceMeters"` to the cURL call. |
| `INVALID_ARGUMENT` (Waypoint limit) | > 25 intermediate waypoints supplied | Simplify the coordinates list using a path simplification utility. |
| `403 FORBIDDEN` | Missing API authorization or restricted keys | Set `gcloud auth application-default login` and set a valid API Key. |

---

## 5. Execution Examples (Bash & cURL)

### Basic Directions Calculation
Calculate driving time and return distance:

```bash
PROJECT_ID="my-project-id"
API_KEY="${GOOGLE_MAPS_API_KEY}"

curl -s -X POST \
  -H "Content-Type: application/json" \
  -H "X-Goog-FieldMask: routes.duration,routes.distanceMeters,routes.polyline" \
  -d '{
    "origin": {"location": {"latLng": {"latitude": 37.4198, "longitude": -122.0822}}},
    "destination": {"location": {"latLng": {"latitude": 37.4175, "longitude": -122.0791}}},
    "travelMode": "DRIVE"
  }' \
  "https://routes.googleapis.com/v1/computeRoutes?key=${API_KEY}"
```
