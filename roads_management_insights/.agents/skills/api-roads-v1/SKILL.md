---
name: api-roads-v1
description: Use this skill for the legacy Google Maps Roads API (v1). It provides procedural knowledge for 'Snap to Roads' and 'Nearest Roads'—essential for cleaning GPS traces before RMI route submission. Make sure to use this skill whenever the user mentions legacy roads, snapping GPS points, or finding the nearest physical road segments to raw coordinates.
---

# Roads API (v1 - Legacy)

This skill covers the legacy Roads API (v1) features used to align raw coordinates with the Google road network. It serves as a crucial data-cleansing pre-processing step before registering segments as `SelectedRoutes` in RMI.

---

## Core Features & Endpoints

### 1. Snap to Roads
Takes up to 100 GPS coordinates (latitude/longitude pairs) and returns the best-fit road geometry that matches the path taken.
- **Endpoint**: `GET https://roads.googleapis.com/v1/snapToRoads`
- **Usage**: Clean raw, noisy vehicle breadcrumbs or GPS traces before submitting them as an RMI `SelectedRoute`.
- **Interpolate Option**: If `interpolate=true`, the API fills in missing road segments along the path (e.g. if the vehicle jumped between points), generating a smooth continuous road path.
- **Critical Limit**: A maximum of **100 GPS points** is allowed per request. If your trace exceeds 100 points, chunk or simplify the path first using spatial simplification.

### 2. Nearest Roads
Returns the closest physical road segments for a given set of latitude/longitude points (up to 100 points).
- **Endpoint**: `GET https://roads.googleapis.com/v1/nearestRoads`
- **Usage**: Identify which road segment a single telemetry coordinate or stationary asset resides on.

---

## Edge Cases & Error Recovery

### 1. Invalid or Mismapped Coordinates
- **Symptom**: Telemetry points recorded off-road, in open water, or inside buildings might snap to distant, incorrect roads.
- **Mitigation**: Filter out outliers (e.g. points with speeds exceeding realistic thresholds, or points located deep in unauthorized water bodies) before calling the API. Set `interpolate=false` if you want to inspect exact raw nearest matches instead of a synthetic continuous route.

### 2. Point Limit Exceeded
- **Symptom**: Calling `snapToRoads` with 101 or more points results in a `400 Bad Request` or an API error.
- **Mitigation**: Implement a sliding-window chunking logic. Process points in batches of 100 with an overlap of 1 point (the last point of batch $N$ is the first point of batch $N+1$) to ensure continuity.

### 3. API Key & Billing Restrictions
- **Symptom**: `403 Forbidden` response or billing errors.
- **Mitigation**: Google Maps Roads API requires a valid API key with billing enabled. Ensure the environment variable `GOOGLE_MAPS_API_KEY` is set and authenticated. For restricted user projects, set the `X-Goog-User-Project` header.

---

## Implementation Reference & Examples

### 1. Snap to Roads (cURL & Bash)
Enables clean, interpolated path snapping of vehicle coordinates:

```bash
# Path of coordinates: lat1,lng1|lat2,lng2|...
PATH_COORDS="37.7749,-122.4194|37.7752,-122.4178|37.7755,-122.4162"

curl -s -X GET \
  "https://roads.googleapis.com/v1/snapToRoads?path=${PATH_COORDS}&interpolate=true&key=${GOOGLE_MAPS_API_KEY}"
```

**Expected JSON Response Outline:**
```json
{
  "snappedPoints": [
    {
      "location": {
        "latitude": 37.77492,
        "longitude": -122.41938
      },
      "originalIndex": 0,
      "placeId": "ChIJIQBpAG2AhYARDBcbXQvCgW0"
    },
    {
      "location": {
        "latitude": 37.77521,
        "longitude": -122.41781
      },
      "originalIndex": 1,
      "placeId": "ChIJIQBpAG2AhYARDBcbXQvCgW0"
    }
  ]
}
```

### 2. Nearest Roads (cURL & Bash)
Identify physical roads neighboring specific standalone coordinate points:

```bash
POINTS="37.7749,-122.4194|37.7752,-122.4178"

curl -s -X GET \
  "https://roads.googleapis.com/v1/nearestRoads?points=${POINTS}&key=${GOOGLE_MAPS_API_KEY}"
```

---

## Architectural Alignment & Hand-off
- **Transition Recommendation**: While functional, this API is considered legacy. For modern physical road network metadata (including Priority, Road Class, Speed Limit guidance), prefer using **`api-roadnetwork-preview`**.
- **Downstream Usage**: Snapped coordinate lists can be directly converted into RMI waypoint structures and used inside the **`api-roadsselection`** (SelectedRoutes API) to build and register persistent monitored RMI segments.

---

## References

- **Official Discovery Document**: [Roads API (v1) Discovery Document](references/discoveryDocs/roads_v1_20260728.json)

