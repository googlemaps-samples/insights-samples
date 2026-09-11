---
name: rmi-dataviz
description: "Use this skill for best practices and procedural guidelines for designing high-performance, reactive, and visually stunning map visualizations with Deck.gl and Google Maps."
---

# RMI Data Visualization (rmi-dataviz)

This skill provides expert knowledge and guidelines for developing premium, responsive, and robust geospatial visualizations using Deck.gl, Google Maps Platform, and various geospatial formats.

## 🎨 1. Premium Visual Aesthetics & Themes

To deliver high-impact, premium user experiences, always avoid browser-default colors and simple styling. Use curated, high-contrast palette configurations suited for dark-mode data operations:

* **Obsidian / Dark Themes**: Base map background should be ultra-dark (`#080c14`). Roads and boundaries should use neon or bright, glowing colors (emerald green, cyber cyan, amber yellow, rose red) with high opacity.
* **Discrete Color Schemes**:
  * `CONTROLLED_ACCESS`: Purple (`[168, 85, 247, 255]`)
  * `LIMITED_ACCESS`: Orange (`[249, 115, 22, 255]`)
  * `PRIMARY_HIGHWAY`: Rose Red (`[244, 63, 94, 255]`)
  * `SECONDARY_ROAD`: Amber (`[234, 179, 8, 255]`)
  * `MAJOR_ARTERIAL`: Sky Blue (`[14, 165, 233, 255]`)
  * `MINOR_ARTERIAL`: Indigo (`[99, 102, 241, 255]`)
  * `LOCAL`: Emerald Green (`[34, 197, 94, 255]`)
  * `TERMINAL`: Slate Gray (`[100, 116, 139, 255]`)

* **Line Caps and Corners (Rounded Paths)**:
  To give line layers (e.g. paths, roads, track segments, and incident vectors) a premium, fluid appearance, always style them with rounded line joints and caps.
  * **The Composite Layer Gotcha**: Because `GeoJsonLayer` is a composite layer containing sublayers (such as `PathLayer`), setting properties like `capRounded: true` or `jointRounded: true` directly on the `GeoJsonLayer` configuration will **NOT** be forwarded to the underlying line sublayer.
  * **The Correct Props**: You must explicitly configure the line sublayer using the correct composite layer properties:
    * `lineJointRounded: true` (for rounded corners)
    * `lineCapRounded: true` (for rounded ends)

---

## ⚡ 2. Value-Based Reactivity in Deck.gl

### The Reference Equality Trap

Deck.gl optimizes render loops by performing shallow comparison checks on elements inside the `updateTriggers` object. If parent object references are mutated or shallow-copied, deep changes inside nested properties (such as checking/unchecking checkboxes in a filter sub-array) may not trigger visual attribute re-evaluations.

### The Solution: Robust Stringification

Always serialize complex objects inside `updateTriggers` using `JSON.stringify()`. This turns reference-based comparisons into value-based string comparisons, guaranteeing immediate and flawless rendering updates on user interaction.

#### Implementation Pattern

```javascript
return new GeoJsonLayer({
  id: layer.id,
  data: layer.geojson,
  getLineColor: (f) => getLineColorForFeature(f, template, filters),
  updateTriggers: {
    // Stringify the filters object so any key/value changes trigger updates instantly
    getLineColor: [opacity, template, JSON.stringify(filters || {})],
    getFillColor: [opacity, template, JSON.stringify(filters || {})]
  }
});
```

---

## 📂 3. Lightweight Multi-Format Geospatial Parsing

When working with local user uploads, always build light, dependency-free browser-side parsers to maintain application performance and code security.

### Newline-Delimited GeoJSON (GeoJSONL / JSONL)

Split the input file stream on newline boundaries, trim whitespace, and parse individual lines to construct a standard `FeatureCollection`:

```javascript
function parseGeoJSONLToGeoJSON(textContent) {
  const lines = textContent.split(/\r?\n/);
  const features = [];
  for (const line of lines) {
    if (line.trim()) {
      try {
        features.push(JSON.parse(line));
      } catch (e) {
        console.warn("Skipping invalid JSONL line:", e);
      }
    }
  }
  return { type: "FeatureCollection", features };
}
```

### Keyhole Markup Language (KML)

Leverage browser-native `DOMParser` to parse the KML XML schema, find `<Placemark>` nodes, and map `<Point>`, `<LineString>`, or `<Polygon>` coordinates to standard GeoJSON equivalents.

### Well-Known Text (WKT)

Implement clean, robust regex-based matchers to transform standard coordinate lists into structured GeoJSON arrays.

---

## 🏔️ 4. Advanced 3D Geospatial & Temporal Visualizations

### 4.1 Temporal & Stacked Visualizations

When dealing with historical temporal datasets (like vehicle counts or hourly traffic disruptions), utilize the 3D extrusion capabilities of WebGL to stack features vertically:

* **Height Mapping**: Set `extruded: true` and translate timestamps/hours into elevation values (e.g. 10 or 20 meters per hour block).
* **Z-Value Offset**: Ensure coordinates include vertical `z` offsets so stacked blocks align seamlessly without clipping.
* **Polygons Generation**: For lines (like LineStrings), generate custom thin polygon rings that can be extruded into standard 3D walls.
* **Client-Side Unpacking Registry Maps**: When unpacking nested temporal arrays (such as hourly speeds) on the client side into vertical 3D stacks, **always key the registry map by the unique subsegment identifier (`unpacked_segment_id`)** rather than the route identifier (`selected_route_id` / `road_segment_id`).
  * **The Collision Risk:** A single route contains multiple physical subsegment geometries. If you key your registry map by the shared route ID, different physical subsegment geometries of the same route will collide, causing the registry to discard or overwrite all subsegment geometries except the first one processed, leading to severe visual "partial coverage" or segment-dropout anomalies on the map.

### 4.2 The 3D Architectural Dilemma: Google Maps Vector 3D Tilt vs. Photorealistic 3D Globe (`Map3DElement`)

When designing 3D geospatial applications on Google Maps Platform, developers frequently encounter confusion between two incompatible 3D paradigms:

| Architectural Dimension | Vector Maps 3D Tilt (`google.maps.Map`) | Photorealistic 3D Globe (`<gmp-map-3d>` / `Map3DElement`) |
| :--- | :--- | :--- |
| **API Primitive** | Standard `google.maps.Map` with vector `mapId` | Web Component custom element `<gmp-map-3d>` |
| **Deck.gl Compatibility** | **100% Seamless (`GoogleMapsOverlay`)** | **Incompatible** (requires custom Cesium/Deck 3D bridge) |
| **Basemap Switching** | Seamless (`roadmap`, `hybrid`, `satellite`) via `map.setMapTypeId()` | Separate photorealistic 3D mesh only |
| **Camera Model** | Pitch/Tilt (`0°`–`67.5°`), Heading (`0°`–`360°`), Center, Zoom | `center: {lat, lng, altitude}`, `range`, `tilt`, `roll` |
| **Custom Overlays** | Native InfoWindows, HTML overlays, WebGL layers, Deck.gl | Experimental 3D markers only, restricted DOM overlay support |
| **Performance Profile** | Instant boot, smooth 60 FPS under massive overlay datasets | Heavy initial asset loading, higher GPU memory footprint |

> [!IMPORTANT]
> **The Deck.gl Overlay Rule**: If your application requires rendering Deck.gl spatial data layers (e.g., `S2Layer`, `H3HexagonLayer`, `GeoJsonLayer`, `ScatterplotLayer`, or extruded 3D density towers), **ALWAYS use standard Vector Google Maps with `map.moveCamera({ tilt: 55, heading: -20 })`**. Do **NOT** attempt to use `Map3DElement` for analytical overlay dashboards, as it breaks standard overlay synchronizers and DOM positioning.

### 4.3 Deck.gl `S2Layer` Multi-Resolution 3D Extrusion & Token Performance

When rendering multi-resolution spatial grids (e.g. S2 geometry from macro Level 12 down to urban Level 14 and micro Level 15 city blocks):

1. **Direct Hex Token Indexing**:
   * Never decode S2 cells into GeoJSON boundary polygons on the CPU for rendering.
   * Provide the 16-character S2 hexadecimal token directly to `deck.S2Layer`:

     ```javascript
     new deck.S2Layer({
       id: 's2-layer',
       data: cellRecords,
       getS2Token: d => d.s2_token, // Direct 16-char hex token, e.g. '13a35...'
       pickable: true,
       extruded: isExtruded,
       getFillColor: d => d.colorRgb,
       getElevation: d => computeDynamicElevation(d.metric, currentS2Level)
     });
     ```

   * This cuts serialization payload size by ~85% and eliminates client-side CPU geometry generation, rendering 400,000+ cells at 60 FPS.

2. **Dynamic Multi-Resolution Elevation Scaling**:
   * As S2 resolution deepens, cell surface area shrinks by $4\times$ per level ($64\times$ from L12 to L15).
   * If a static elevation multiplier is used, L12 macro cells will pierce into outer space while L15 city blocks become paper-thin flat slivers.
   * **Pattern**: Scale the vertical height multiplier dynamically based on the active resolution tier, and apply a non-linear root transformation with a maximum ceiling:

     ```javascript
     function computeDynamicElevation(metricValue, s2Level) {
       // Multipliers inversely tuned to cell bounding box dimensions
       const levelMultiplier = s2Level === 15 ? 2.5 : (s2Level === 14 ? 1.0 : 0.25);
       const baseHeight = Math.sqrt(Math.max(0, metricValue)) * 35;
       return Math.min(baseHeight * levelMultiplier, 2500); // meters
     }
     ```

### 4.4 Camera Tilt & Heading Preservation in 3D Flight Transitions

When users toggle into 3D perspective mode (e.g., `tilt: 55`, `heading: -20`), navigating between geographic regions, search locations, or bookmarks must not jarringly snap the camera back to a 2D overhead view (`tilt: 0`).

* **Pattern**: Always query the active camera parameters from the map instance prior to invoking `map.moveCamera()` or `map.panTo()`:

  ```javascript
  function smoothFlyTo(map, targetCoords, targetZoom) {
    const currentTilt = typeof map.getTilt === 'function' ? (map.getTilt() || 0) : 0;
    const currentHeading = typeof map.getHeading === 'function' ? (map.getHeading() || 0) : 0;

    map.moveCamera({
      center: targetCoords,
      zoom: targetZoom,
      tilt: currentTilt,      // Preserves 3D oblique angle (e.g. 55°)
      heading: currentHeading  // Preserves orientation
    });
  }
  ```

---

## 🚗 5. Driving Side & Lateral Offsets (LHT vs. RHD)

When rendering dual-direction roads, multi-lane telemetry, or overlaying direction-specific indicators, paths must be shifted laterally to represent the correct driving side of the road (Left-Hand Traffic vs. Right-Hand Traffic) and prevent overlapping overlap anomalies.

### A. The Multi-Layer Synchronization Trap (PathStyleExtension vs. Companion Layers)

Deck.gl provides `PathStyleExtension({ offset: true })` for GPU vertex shader offsets. However, **in complex GIS applications with companion layers (e.g. directional arrowheads, start/end point circles, extruded 3D ribbons), `PathStyleExtension` creates severe visual desynchronization:**

1. **Width-Coupled Shader Offsets:** `PathStyleExtension` calculates offset as `getOffset * getWidth`. If a road line has a base width of 1 meter or 2 pixels, the shader only shifts it by a tiny fraction (e.g. $0.6\text{ m}$).
2. **Layer Incompatibility:** Companion layers like `ScatterplotLayer` (start dots) or extruded `GeoJsonLayer` (3D ribbons) cannot use `PathStyleExtension`. If they are analytically offset in meters (e.g. $2.5\text{ m}$), arrows and markers will visibly decouple and float far off the road corridor into sidewalks or buildings.
3. **Luma.gl Layout Warnings:** In Deck.gl v9, using `PathStyleExtension` on certain composite layer setups can trigger `luma.gl: Binding pathStyleUniforms not set: Not found in shader layout.` warnings.

### B. The Robust Solution: Unified Analytical Geometry Offsetting

For guaranteed pixel-perfect and meter-accurate alignment across all composite sublayers, perform a **unified analytical coordinate offset** (typically $1.5\text{ m}$ to $2.0\text{ m}$, representing half a standard lane width) at the geometry preparation layer:

```typescript
/**
 * Safely offsets a LineString or Feature<LineString> laterally in meters.
 * Positive distance offsets to the right of travel direction, negative to the left.
 */
function offsetLine(
  geomOrFeature: geojson.LineString | geojson.Feature<geojson.LineString>,
  offsetDistanceMeters: number
): geojson.Feature<geojson.LineString> {
  if (!geomOrFeature || offsetDistanceMeters === 0) {
    return geomOrFeature.type === 'Feature' ? geomOrFeature : turf.lineString(geomOrFeature.coordinates);
  }
  try {
    const feat = geomOrFeature.type === 'Feature' ? geomOrFeature : turf.lineString(geomOrFeature.coordinates);
    const offset = turf.lineOffset(feat, offsetDistanceMeters, { units: 'meters' });
    if (offset?.geometry?.coordinates?.length >= 2) {
      return offset;
    }
  } catch (e) {
    console.warn("offsetLine failed, falling back to original geometry:", e);
  }
  return geomOrFeature.type === 'Feature' ? geomOrFeature : turf.lineString(geomOrFeature.coordinates);
}
```

#### Multi-Layer Pipeline Pattern

1. **Base Road Polylines (`PathLayer`):** Pass `offsetLine(line, isLeftHandTraffic ? -1.5 : 1.5)` into `getPath`.
2. **Directional Arrowheads (`PathLayer`):** Derive arrow vectors from the *same* offset line geometry via `turf.along`.
3. **Start/End Markers (`ScatterplotLayer`):** Anchor marker positions directly on the *same* offset line.
4. **Time-Stacked Traffic (`RecentTrafficLayer`):** Offset 2D coordinates by $\pm 1.5\text{ m}$ *before* mapping vertical elevation ($Z = \text{minutes} \times 1.5$).
5. **3D Ribbon Volumes (`RouteDeviationLayer`):** Apply `offsetLine` *before* `turf.buffer()`, generating perfectly separated, non-colliding parallel 3D extruded volume walls.

### C. Manual Projection Math (Zero-Dependency Offline Fallback)

When Turf.js is unavailable, calculate lateral coordinates manually in meters and project them back into degrees.

Given a segment from `p1` to `p2`:

1. **Direction Vector**:
   $$\Delta x = x_2 - x_1, \quad \Delta y = y_2 - y_1$$
   $$\text{Length} = \sqrt{\Delta x^2 + \Delta y^2}$$
2. **Normalized Normal (Perpendicular Right) Vector**:
   $$n_{dx} = \frac{\Delta x}{\text{Length}}, \quad n_{dy} = \frac{\Delta y}{\text{Length}}$$
   $$p_{dx} = n_{dy}, \quad p_{dy} = -n_{dx}$$
3. **Meters-to-Degrees Projection Scaling**:
   $$\text{degPerMeterLat} = \frac{1}{111111}$$
   $$\text{degPerMeterLon} = \frac{1}{111111 \cdot \cos(\text{lat} \cdot \frac{\pi}{180})}$$
4. **Shifted Coordinates**:
   $$\text{offsetLon} = p_{dx} \cdot \text{offsetMeters} \cdot \text{degPerMeterLon}$$
   $$\text{offsetLat} = p_{dy} \cdot \text{offsetMeters} \cdot \text{degPerMeterLat}$$
   $$p_{\text{offset}} = [x_2 + \text{offsetLon}, \, y_2 + \text{offsetLat}]$$

---

## ⚡ 6. High-Performance GCS Tile Ingestion (PMTiles & MVT)

When streaming vector tiles from secure cloud buckets (like Google Cloud Storage), standard client decoders must be optimized to prevent browser throttling, authentication failures, or redundant network roundtrips.

### A. Secure Range Request Ingestion with Token Injection

Extend standard source loaders to parse `gs://` URIs, dynamically inject OAuth2 bearer tokens, and issue HTTP range headers:

```javascript
async function getBytes(offset, length) {
  const url = translateGcsUrl(this.gcsPath); // gs://bucket/file.pmtiles -> storage.googleapis.com
  const headers = {
    Range: `bytes=${offset}-${offset + length - 1}`
  };
  if (accessToken) {
    headers["Authorization"] = `Bearer ${accessToken}`;
  }
  const res = await fetch(url, { headers });
  return { data: await res.arrayBuffer() };
}
```

### B. Network & Cache Performance Tuning

Deck.gl's default configurations are designed for generic tile services. For complex GIS layers (e.g., dense road network grids), enforce these performance configurations:

* **`maxRequests: 20`**: Increase the concurrent request pool from the browser-default limit of 6 to 20. This allows highly parallelized tile downloading and parsing, significantly reducing initial render lag during zoom changes.
* **`maxCacheSize: 100`**: Raise the internal parsed-tile memory cache size to 100. This caches previously loaded tiles and ensures instant pan-back and zoom-out hits without making repetitive GCS network range requests.

---

## 🕒 7. Timezone-Aware Slicing for Temporal Maps

Temporal map visualizations (such as hourly traffic density, congestion hotspots, or incident distributions) represent localized human behaviors. Displaying them in raw UTC coordinates dilutes morning/evening rush-hour patterns. Geometries must be sliced according to their exact regional timezone.

### A. Dynamic Timezone Resolution

To map UTC events back to local-time bins dynamically, query the coordinates of the tile center or active viewport against the Google Time Zone API:
$$\text{localTimestamp} = \text{utcTimestamp} + \text{rawOffset} + \text{dstOffset}$$

### B. Local Hour Properties Injection

Store the resolved `tz_offset` directly into feature properties at the decoder layer, letting style templates compute active hourly filters reactively:

```javascript
const localDate = new Date(utcDate.getTime() + tzOffset * 1000);
feature.properties.local_hour = localDate.getUTCHours();
feature.properties.tz_offset = tzOffset;
```

This enables filters to slice datasets dynamically (e.g., matching features where `f.properties.local_hour === selectedHour`) regardless of which global region is currently being visualized.

### C. API Key Restrictions & Fetching Gotchas

Direct HTTP `fetch` calls to the Google Maps Time Zone API (`timezone-backend.googleapis.com`) will return a `REQUEST_DENIED` status if executed with an API key restricted strictly to client-side Maps SDKs (`maps-backend.googleapis.com`).

To prevent runtime blockages:

* **Key Separation**: Maintain separate, dedicated keys (such as `TIMEZONE_API_KEY` or generalized `API_KEY`) configured with the correct API permissions for back-end or direct web timezone queries.
* **Graceful Fallback**: Implement robust exception handling that falls back gracefully to standard UTC or browser-local timezone offsets if API calls are blocked or fail due to key restrictions.

### D. Fractional-Hour Timezone Aligner & The Matching Trap

* **The Trap (Strict Matching Window):** When unpacking timeseries/hourly arrays (e.g., matching hourly vehicle counts or travel times against top-of-the-hour database buckets `c.start_time`), using a strict exact matching window (such as `Math.abs(d.getTime() - targetUTC) < 10000`) is highly brittle.
* **The Root Cause:** In fractional-hour timezones (such as Indian Standard Time `Asia/Kolkata` at UTC+5:30, or `Asia/Kabul` at UTC+4:30), local hourly milestones (1:00, 2:00, etc.) map to exact `:30` (or `:45`) minute marks in UTC. Since database hourly buckets are typically stored strictly at the top of the hour (`:00` minutes in UTC), this creates a constant 30-to-45-minute offset, causing strict matchers to fail entirely and render flat baseline/fallback metrics (e.g., zero vehicle counts or dark blue overlays).
* **The Robust Solution:** Use a **minimum absolute distance solver** restricted to a maximum 1-hour search radius, rather than a strict static matching window. This seamlessly aligns target hourly bins with database records regardless of whether the timezone offset is a whole, half, or quarter-hour.

```javascript
let matchedCount = null;
let minDiff = 3600000; // 1 hour max search radius
counts.forEach((c) => {
  const d = parseStartTime(c.start_time);
  if (d) {
    const diff = Math.abs(d.getTime() - targetUTC);
    if (diff < minDiff) {
      minDiff = diff;
      matchedCount = c;
    }
  }
});
```

---

## 🗺️ 8. Google Maps Custom Controls Layout & Race-Condition Hardening

When blending native Google Maps UI controls (such as the Pegman or Fullscreen toggle) with bespoke custom HTML control panels, dynamic renderer race conditions and container alignment gaps can occur.

### A. Defeating Native Control Stacking Race Conditions

Google Maps dynamically measures and computes bounds for its native widgets as the basemap fully loads. If a custom HTML panel is pushed into the map's `controls` array during initial map constructor initialization, native elements and custom elements can collide. This causes native buttons to push custom containers upwards, creating unintended layout stacking and gaping.

#### The Deferral Solution

Wait for the map's `'idle'` event to trigger, and then defer the custom control registration with a small `setTimeout` delay (~300ms). This guarantees that Google Maps has completed its native layout passes first, allowing the custom control panel to dock cleanly at the absolute bottom of the layout stack.

```javascript
map.addListener("idle", () => {
  if (!loggerInjected) {
    setTimeout(() => {
      map.controls[google.maps.ControlPosition.INLINE_END_BLOCK_END].push(loggerElement);
      loggerInjected = true;
    }, 300);
  }
});
```

### B. Eliminating Footer Alignment Gaps

Google Maps natively reserves a bottom margin (~15-20px) on control containers in bottom-right/left quadrants to clear the default Google logo, terms, and copyright lines. For a premium, full-bleed dashboard feel, custom panels can be dropped completely flush to the bottom edge.

#### CSS Spacing Override

Override Google Maps' default layout constraints by using `!important` to force-clear the bottom margins of your container when expanded:

```css
.custom-bottom-panel {
  margin: 0px 10px 0px 0px !important; /* Force margin-bottom to 0px */
}
```

### C. Redundant Control Elimination

Explicitly disabling unneeded basemap controls reduces interface clutter and draws immediate user focus to custom interaction controls:

```javascript
const map = new google.maps.Map(element, {
  // Disable defaults to maximize visualization real estate
  zoomControl: false,
  rotateControl: false,
  tiltControl: false,
  cameraControl: false
});
```

---

## 🕒 9. Timezone Synchronization relative to Map Viewport Center

When presenting tooltips, event logs, or date indicators, all "local" times displayed on-screen must reflect the geographical local timezone of the geographical point currently centered in the map viewport, rather than the visitor's local browser/device timezone.

### Viewport Timezone Mapping Pattern

1. **Track Module-Scoped Timezone State**: Keep a global or module-scoped timezone variable (e.g., `currentMapCenterTimezone`) initialized with a fallback timezone.
2. **Listen to Viewport Idle Changes**: On the map's `idle` event, detect the center coordinates, resolve the current country or timezone offset, and update the state variable.
3. **Standard-Compliant Date Formatting**: Use `Intl.DateTimeFormat` with a neutral, globally recognized, and readable format (such as Sweden's `"sv-SE"` locale) to represent the local time as `YYYY-MM-DD HH:mm:ss`:

```javascript
export function formatLocalTime(date, timeZone) {
  try {
    return new Intl.DateTimeFormat("sv-SE", {
      dateStyle: "short",
      timeStyle: "medium",
      timeZone: timeZone,
    }).format(date);
  } catch (err) {
    // Fall back to standard UTC representation if timezone is invalid
    return date.toUTCString();
  }
}
```

---

## 🔄 10. Real-time Stream State Preservation across Reconnections

Real-time EventSource/Server-Sent Events (SSE) data streams are subject to intermittent network drops. When an EventSource automatically reconnects, the backend database frequently re-broadcasts a full-snapshot data dump (such as a root `/` path payload). This dump can "resurrect" faded features on the client side, causing flickering, duplicate enter-animations, or logging noise.

### Client-Side State Cache Pattern

1. **Persistent State Cache**: Maintain an in-memory Map of active feature states (e.g., `rtdbFeaturesState`) that persists independently of connection state.
2. **Differentiate Incremental vs Initial Syncs**: On stream callbacks, query the persistent cache to evaluate the age, animation status, or fading multipliers (`life`) of incoming features. If an incoming feature is already marked as faded out or deleted, reject re-animation.
3. **Memory Cleanup Hooks**: To prevent persistent memory leaks, always clear the in-memory cache when the layer is explicitly unchecked, removed, or deleted by the user:

```javascript
function clearRealtimeLayer(layerId) {
  const listener = activeRtdbListeners.get(layerId);
  if (listener) {
    listener.stop();
    activeRtdbListeners.delete(layerId);
  }
  rtdbFeaturesState.clear(); // Free up memory
}
```

---

## ⚡ 11. WebGL Interleaved Rendering (deck.gl v9)

When integrating Deck.gl with the Google Maps JavaScript API (specifically using the Vector Map capability via WebGL2), always prefer interleaved rendering to achieve perfect desynchronization-free drawing during map movement.

### A. Perfect Camera Sync Configuration

Set `interleaved: true` on the `GoogleMapsOverlay` constructor. This integrates Deck.gl directly into the Google Maps WebGL2 vector render loop:

```javascript
const overlay = new GoogleMapsOverlay({
  interleaved: true,
  layers: [...]
});
overlay.setMap(map);
```

### B. Compatibility and WebGL State Preservation

In older deck.gl versions, interleaving could cause stencil, blend, or depth-testing state contamination (e.g. flickering, "Hung Labeler" errors, or broken label rendering). In **deck.gl v9**, the WebGL state save-and-restore hygiene is extremely robust, making `interleaved: true` safe and highly recommended for production vector overlays.

---

## 🎨 12. Meters-Scale Styling & Default Layer Opacities

When rendering paths or features utilizing physical real-world measurements (e.g., `lineWidthUnits: "meters"` with a width of $1.0\text{m}$ to $2.0\text{m}$) and applying lateral lane shifts (offsets of $\pm0.6\text{m}$), paths appear extremely narrow at low-to-mid zoom levels.

### A. High Contrast Default Opacity

For any layer or style template using real-world physical dimensions (like "Road Priority" or lanes configuration), **always default to 100% (1.0) opacity**. Lower opacity values cause fine lines to blend aggressively with the base map, rendering the paths faded or invisible.

### B. Decoupled Styling Triggers

Ensure that when a user switches style templates to a physical meters-scale representation, the application reactively sets or overrides the layer's opacity to `1.0`. Add `opacity` and the selected template name to the layer's `updateTriggers` array to force the GPU to re-evaluate the colors instantly.

---

## 📋 13. Dynamic Viewport Query Columns & Tooltip Integration

When binding database rows dynamically to client-side overlays (such as viewport-based BigQuery datasets), there is a strong architectural dependency between the SQL query structure and the map's interactive elements (e.g. hover tooltips or click callbacks).

### A. Explicit SQL Projection Requirement

* **The Gotcha**: Any column defined in the database schema that is omitted from the client-side SQL projection query (the `queryTemplate` or function select statement) will **NOT** be populated in the feature's `properties` map on the client.
* **The Resolution**: If you add new columns to a backend table (e.g. extracting JSON attributes into typed top-level fields), always update the client's SQL template to explicitly request those columns.

### B. Conditional Tooltip Rendering

* **Guideline**: When displaying tooltips for dense or structured features (such as route attributes or incident fields), avoid rendering blank rows or empty tables for fields that are missing or null.
* **Implementation Pattern**: Iterate through the target properties or map arrays dynamically, and construct the HTML string conditionally so only active, non-null values are appended to the tooltip card. This maximizes information density and eliminates visual clutter.

---

---

## 🎨 14. Native Map Controls for Floating Actions & Sleek Interactive Targets

When building custom floating controls (such as file drag-and-drop targets, diagnostic log triggers, or layer presets) on top of a Google Maps Canvas, avoid absolute viewport offsets or CSS floats. These are prone to overlap during window resize events and clash with standard browser container layouts.

### A. Register Native Google Maps Custom Controls

Leverage Google Maps' built-in control stacking layers. This registers elements directly into the native map overlay grid, handling resizing, standard margins, and Z-index layering out-of-the-box:

```javascript
// Register your element as a native map control
map.controls[google.maps.ControlPosition.TOP_RIGHT].push(floatingDropZoneElement);
```

Using native control layouts like `TOP_RIGHT` or `RIGHT_TOP` aligns your custom tool beautifully alongside standard Maps buttons (like Fullscreen, Zoom, and Street View).

### B. Minimalist Visual-Only Targets & Dynamic Emojis

Bulkier rectangular widgets consume valuable viewport space. For drag-and-drop file import zones, prefer an ultra-sleek, circular button template with dynamic, visual-only emojis indicating load states:

* **Button Template**: `40px` to `50px` diameter glassmorphic circle with a dashed border.
* **Micro-Scale Hover Transition**: Scale up slightly on hover/drag (`transform: scale(1.15); transition: transform 0.2s ease-out;`).
* **Intelligent Status Indicators**: Map operational statuses to universal, text-free emoji icons inside the circle:
  * Default/Ready: `📥` (Import)
  * Processing/Loading: `⏳` (Parsing file)
  * Success: `✅` (Loaded successfully)
  * Error/Failure: `❌` (Failed to parse)

---

## 🌐 15. Dynamic URL Query Configuration & State Syncing

To enable seamless multi-environment or multi-project switching without redeploying frontend assets, support parameter injection via the URL query string.

### A. Dynamic Initialization Pattern

On load, parse standard URL parameters (e.g. `project_id`, `layer_id`) to override default application variables:

```javascript
const urlParams = new URLSearchParams(window.location.search);
const projectId = urlParams.get("project_id") || "default-project-id";
```

### B. UI Synchronization & Active Display

Always ensure crucial configuration overrides (like the active Cloud Project ID) are clearly displayed in high-visibility elements, such as the title bar of control panels, to prevent confusion when working across multiple projects:

```javascript
const projectDisplay = document.getElementById("project-id-display");
if (projectDisplay) {
  projectDisplay.textContent = projectId;
}
```

---

## 🥞 16. Interactive Layer Reordering & Rendering Priority

In complex map applications, the vertical stacking order of layers dictates visual legibility (e.g., placing lines on top of polygons).

### A. Sidebar UI vs. Deck.gl Rendering Priority

* **Sidebar order**: Listed sequentially from top to bottom (index `0` at the top, index `n` at the bottom).
* **Deck.gl render order**: Items in the `layers` array are rendered from bottom to top (first item in the array is drawn first/underneath, last item in the array is drawn last/on top of everything else).
* **Aligning Stack Order**: To keep rendering matching the sidebar visual stack intuitively, perform sequential element swaps in the layer configuration list and re-evaluate both the sidebar list rendering and Deck.gl layer stack creation on every change.

### B. Dynamic Move Up / Down Buttons

Render compact `▲` (Up) and `▼` (Down) icons on layer cards, disabling them dynamically at boundaries (index `0` cannot move up, index `n-1` cannot move down):

```javascript
if (idx === 0) {
  upBtn.style.pointerEvents = "none";
  upBtn.style.opacity = "0.15";
}
```

### C. State Reactivity & Event Propagation Control

Always stop event propagation on reordering click events (`e.stopPropagation()`) to prevent triggering card expand/collapse accordions or detail panel toggles. After swapping indices inside the primary layer array, trigger both the sidebar UI redraw and the Deck.gl overlay redraw immediately to reflect changes.

---

## 🥞 17. Concentric Polygon Nesting and WebGL Iteration Direction

When visualizing overlapping concentric polygons (such as drive-time isochrones of 10m, 20m, 30m, 40m, 50m, and 60m), rendering order is critical. If larger outer polygons are drawn on top of smaller inner polygons, the larger solid or semi-transparent fills will completely cover and mask the smaller ones underneath, leading to a "solid fill" visual glitch where inner colors are invisible.

### A. WebGL Layer Sorting Strategy

* **The Root Cause**: WebGL-based canvas pipelines (such as Deck.gl's `GeoJsonLayer` buffers) frequently iterate and draw features in **reverse index order** (from index `length-1` down to `0`).
* **The Solution**: Sorting features in **ascending** order of size/travel duration (`a - b`) ensures that:
  1. The largest boundaries are positioned at the end of the array (e.g., Index 5) and get drawn **first** (at the bottom of the stack).
  2. The smallest boundaries are positioned at the start of the array (e.g., Index 0) and get drawn **last** (on top of everything else).
  3. This nesting exposes all concentric bands and ensures that each region's color fill perfectly matches and aligns with its outline stroke.

---

## 📍 18. Google Maps z-Index Marker Elevation atop WebGL Overlays

Standard Google Maps custom marker layers and WebGL canvas layers (such as interleaved Deck.gl layers) can fight for layout dominance on the map context, occasionally burying spatial center anchors under semi-transparent data fills.

### Standard Marker Elevating Pattern

* Always specify an explicit `zIndex` parameter on standard `google.maps.Marker` or `AdvancedMarkerElement` configurations to elevate them above raw canvas drawing pipelines:

```javascript
const centerMarker = new google.maps.Marker({
  map: map,
  position: anchorLatLng,
  zIndex: 9999, // Explicitly float atop interleaved WebGL data contexts
  icon: { ... }
});
```

---

## 🎨 19. Custom Minimalist Space-Black Cartography

When presenting high-intensity neon geospatial overlays (like isochrones or traffic bottleneck segments), standard dark base maps are too busy and cluttered with labels, POI markers, and transit lines, which compete with the target data for visual dominance.

### Minimalist Dark Styling JSON

Always apply a custom, ultra-minimalist dark JSON stylesheet to eliminate information noise and enhance data contrast:

* **Background Ground**: Slate space-black (`#12131a`).
* **Water Geometries**: Deep obsidian black (`#090a10`).
* **Noise Elimination**: Disable POIs (`featureType: "poi", stylers: [{ visibility: "off" }]`), transit lines (`featureType: "transit", stylers: [{ visibility: "off" }]`), and all street labels.
* **Low-Intensity Grids**: Style secondary roads in subtle dark-gray (`#1c1e2b`) and highways in slightly higher-contrast slate (`#2d3247`), omitting names. This transforms the map background into a clean, low-intensity circuit-board grid.
* **Major Labels Only**: Keep major locality labels (e.g., city/neighborhood names) only, styled in a muted elegant slate (`#4f5a6b`) with a dark stroke outline (`#12131a`).

---

---

## ⚡ 20. Dual Live vs. Cached Telemetry Layer Pattern

To balance instant spatial response times with zero-staleness real-time accuracy:

* **Cached Layers (BigQuery Materialized Views)**: Fast, spatially indexed (`ST_INTERSECTS`) querying across global bounding boxes with zero REST quota usage.
* **Live Layers (REST API Streams)**: Exact real-time ground truth pulled directly from source REST endpoints (e.g. Roads Selection API, Live Disruptions API).
* **On-Demand Interaction Scoping**: Never trigger live REST API queries automatically on map pan/zoom (`idle` event). Scope live API queries **strictly to explicit user checkbox toggles** (`visible: true`), fetching live features once for the viewport active at that exact moment to conserve network bandwidth and browser memory.

---

## 🎛️ 21. Material Design 3 Map UI & Feature Inspection Architecture

When building analytical geospatial dashboards and map tools (such as route setting or corridor inspection consoles), map UI elements must provide clear visual hierarchy, quick copyability of resource identifiers, and self-documenting action triggers.

### A. The Copyable Monospace Resource Container Pattern

* **Problem**: Raw resource identifiers (e.g. `roads/ChIJ-bfSMGoZ...` or `routes/12345`) are lengthy, hard to read, and awkward to select manually from standard text elements without accidental whitespace inclusion.
* **Pattern**: Render resource IDs inside a dedicated monospace container box with an inline 1-click clipboard copy button:
  1. Truncate text visually with `text-overflow: ellipsis` and set `user-select: all`.
  2. Implement direct clipboard writing: `navigator.clipboard.writeText(resourceName)`.
  3. Provide temporary visual confirmation by toggling the icon from `content_copy` to `check` for 1500ms.

### B. Categorized Action Grids vs. Cryptic Icon Rows

* **Problem**: Packing 6 to 8 icon-only buttons into a horizontal strip creates severe cognitive friction; users cannot distinguish nuanced operations (e.g., `unfold_more` vs `compare_arrows` vs `merge_type` vs `alt_route`).
* **Pattern**: Group actions into labeled, 2-column Material Design 3 button grids (`md-filled-tonal-button`, `md-outlined-button`):
  * **`TRACKING`**: Primary tonal button (`+ Track Road`) and secondary outlined button (`Untrack`).
  * **`NETWORK STRETCH`**: Clearly labeled directional actions (`Stretch 1-Way`, `Stretch 2-Way`).
  * **`ROUTE MANAGEMENT` / `ANALYTICS`**: Clear triggers for lifecycle mutations (`Retrack`, `Hide Layer`) and analytics workflows (`Recent Traffic`, `History`).

### C. Modern Google Maps InfoWindow Balloon Overrides

* **Problem**: Standard Google Maps InfoWindows have harsh boxy borders (`.gm-style-iw-c`), rigid padding, and unstyled multi-feature category headers.
* **Pattern**: Override InfoWindow styles cleanly with Material 3 surface elevation:
  1. Set `border-radius: 16px !important;` and soft drop shadows `box-shadow: 0 8px 28px rgba(0,0,0,0.18) !important;` on `.gm-style-iw-c`.
  2. For multi-selection intersections (e.g. overlapping two-way road segments), group features by `FeatureClass` and render styled category headers (`<md-icon>`, category title, and pill count badge).
  3. Render dedicated `GROUP ACTIONS` blocks for bulk multi-feature operations (`Track All`, `Track 2-Way Stretch`).

### D. Floating Pill Search Bars & Control Toolbars

* **Pill Search Bars**: Float search inputs as 24px rounded pill containers (`border-radius: 24px`) with leading category icons (`alt_route` / `route`), subtle border outlines, and smooth focus-within drop shadows.
* **Toolbars**: Replace legacy yellowish/beige headers with clean `#f8f9fa` uppercase headers and 12px rounded container frames.

---

## 📸 22. In-App WebGL & Canvas Snapshot Compositing (`preserveDrawingBuffer`)

### The Blank WebGL Canvas Trap
When building client-side screenshot export buttons (`canvas.toDataURL()` or drawing onto an offscreen canvas with `ctx.drawImage()`), WebGL canvases normally return transparent or pure black images. This occurs because the browser's WebGL rendering context clears its internal drawing buffer immediately after presenting the frame to the compositor (`preserveDrawingBuffer: false` by default for performance).

### The Solution: Explicit WebGL Context Preservation
1. **Enable Buffer Preservation in Deck.gl**: Pass `glOptions: { preserveDrawingBuffer: true }` when instantiating `deck.GoogleMapsOverlay`:
   ```typescript
   const deckOverlay = new (deck as any).GoogleMapsOverlay({
     interleaved: true,
     glOptions: {
       preserveDrawingBuffer: true
     },
     layers: [...]
   });
   ```
2. **Multi-Canvas DOM-Order Compositing**: Map containers contain multiple layered canvases (Google Maps raster/vector base tiles, Deck.gl WebGL layer, vector labels). Query all canvases inside `#map-container` and composite them in DOM order onto an offscreen canvas at device pixel ratio (`window.devicePixelRatio`).
3. **Executive Presentation Badge Watermark**: In presentation modes (`ui=badge`), render a high-contrast dark badge (`rgba(10, 15, 29, 0.88)`) with cyan accents at the bottom-left corner containing dataset name, active cluster archetype name, and filter criteria.

---

## 🤖 23. Headless Chrome Presentation Slide Automation & Ephemeral Ports

### The Zero-Framework Automation Pattern
Generating publication-grade 4K/Retina presentation slides does not require heavy browser automation frameworks like Puppeteer or Playwright. Modern Headless Chrome (`--headless=new`) provides turnkey CLI screenshot capture with zero third-party dependencies:

1. **Ephemeral Local Server on Port 0**: To prevent port collisions with running developer servers or CI pipelines, bind a threaded Python `SimpleHTTPRequestHandler` to `("127.0.0.1", 0)`. The operating system kernel automatically assigns an available ephemeral port.
2. **Headless Chrome Execution Flags**:
   ```bash
   google-chrome \
     --headless=new \
     --disable-gpu \
     --hide-scrollbars \
     --window-size=1920,1080 \
     --force-device-scale-factor=2 \
     --virtual-time-budget=8000 \
     --screenshot=output_slide.png \
     "http://127.0.0.1:<port>?dataset=us_full&model=c_comm&ui=badge"
   ```
   * `--virtual-time-budget=8000`: Freezes time advancement until JavaScript, Google Maps tile loading, and WebGL shader compilation finish rendering.
   * `--force-device-scale-factor=2`: Produces crisp Retina 4K (3840×2160) slide assets from 1080p layout definitions.
   * `--hide-scrollbars`: Eliminates UI scrollbar clipping from canvas edges.

---

## 🏷️ 24. Standardized Semantic Naming for Spatial Visual Assets

### The Asset Ambiguity Problem
Ad-hoc screenshot filenames (e.g. `screenshot_1.png`, `tokyo_map.png`) cause severe confusion when managing multi-region, multi-modal spatial models across international datasets and languages.

### The Standardized Multi-Factor Naming Schema
All generated snapshots and presentation slides must strictly adhere to a standardized, self-describing filename convention:
```
<prefix>_<dataset>_<lang>_<model>_<cluster>_<ui>[_<timestamp>].png
```
* **`<prefix>`**: Lifecycle intent (`pdi_snapshot_` for user-triggered browser downloads; `pdi_slide_` for curated presentation decks; `audit_` for test suites).
* **`<dataset>`**: Explicit geographic scope (`tokyo_sample`, `jp_kanto`, `gb_london`, `us_manhattan`, `us_full`, `australia_full`, `india_full`).
* **`<lang>`**: Interface and typography language (`ja` or `en`).
* **`<model>`**: Analytical model key (`c_comm`, `c_abc`, `c_mkt`, `c_ab`, `c_bc`, `c_ca`, `c_a`, `c_b`, `c_c`).
* **`<cluster>`**: Selected cluster archetype (`cluster3`) or multi-cluster spectrum (`all_clusters`).
* **`<ui>`**: Display layout (`ui_app` for full sidebar, `ui_badge` for executive slide badge, `ui_clean` / `ui_none` for borderless map).
* **`<timestamp>`**: Export timestamp `YYYYMMDD_HHMMSS` (prevents browser download overwrite).

---

## Guidelines

* **Premium Styling Tokens**: Avoid raw visual colors; use the curated, responsive dark-mode palettes defined in the RMI design system.
* **Avoid Overlays Overlap**: Limit concurrent layers to 3 active Deck.gl layers to preserve map responsiveness.
* **Timezone Standardization**: Ensure all map timestamps are dynamically localized to the user's browser offset.
* **Robust Temporal Matching**: Always use a minimum absolute distance solver (with a 1-hour maximum search radius) instead of strict static matching windows when aligning client-side local hours with top-of-the-hour database buckets across fractional-hour timezones.
* **WebGL Interleaved Sync**: Always use `interleaved: true` on `GoogleMapsOverlay` for modern deck.gl v9 deployments.
* **High-Visibility Meters**: Use `1.0` (100%) opacity as the baseline default for meters-scale styling templates.
* **Explicit Property Projection**: Ensure all attributes displayed in hover tooltips or panels are explicitly requested in the client SQL viewport queries.
* **Conditional Tooltips**: Render hover tooltip content dynamically, omitting null or empty values to keep cards clean and readable.
* **Native Custom Controls**: Register custom map interaction widgets directly inside `map.controls[google.maps.ControlPosition.TOP_RIGHT]` or `RIGHT_TOP` to integrate seamlessly with native resizing and controls.
* **Minimalist Status Emojis**: Design drag-and-drop targets as compact, glassmorphic circular buttons, leveraging text-free state transitions (`📥` ➔ `⏳` ➔ `✅` / `❌`) for intuitive, visual-only feedback.
* **Dynamic URL Parameter Override**: Allow setting core variables (like `project_id`) via URL search parameters, and display active values in high-visibility elements like the sidebar control panel title.
* **Reordering Propagation and Boundary Safety**: When implementing up/down layer sorting, disable edge transitions at index `0` and `length - 1`, stop event propagation, and run full UI and WebGL redraw triggers sequentially.
* **Concentric Poly Sorting**: For nested polygon layers, sort features in **ascending** travel duration/size order (`a - b`) to align with WebGL reverse draw directions and avoid masking smaller overlays.
* **Anchor Marker zIndex**: Explicitly set `zIndex: 9999` on standard marker overlays to keep anchors floating above interleaved WebGL contexts.
* **Minimalist Base Cartography**: Ingest a custom slate-black JSON stylesheet to hide POIs, transit networks, and road labels, maximizing visual focus on overlay data.
* **On-Demand Live API Execution**: Scope live API streaming fetches to manual layer checkbox interactions, avoiding automatic execution during map navigation.
* **Monospace Resource Copying**: Package lengthy entity names (`roads/...`, `routes/...`) into monospace containers with 1-click clipboard copying and timeout checkmark confirmation.
* **Categorized Action Grids**: Never rely on raw icon-only toolbars for multi-mode actions; use titled 2-column button grids with explicit text labels.
* **Material 3 InfoWindows**: Style on-map InfoWindows with 16px corner radii, class category headers with count pills, and dedicated bulk group actions.
* **Pill Search Controls**: Design on-map search bars as 24px rounded floating pills with leading domain icons and focus elevation rings.
* **WebGL Buffer Preservation**: Always set `glOptions: { preserveDrawingBuffer: true }` on `GoogleMapsOverlay` to allow high-resolution canvas snapshot exports without blank screens.
* **Headless Slide Automation**: Use modern Headless Chrome (`--headless=new`) with `--virtual-time-budget=8000` and ephemeral local servers (`127.0.0.1:0`) to capture Retina 2x presentation slides deterministically with zero third-party dependencies.
* **Standardized Asset Naming**: Always name exported maps and slides with full semantic parameters (`<prefix>_<dataset>_<lang>_<model>_<cluster>_<ui>[_<timestamp>].png`) to eliminate asset ambiguity.

