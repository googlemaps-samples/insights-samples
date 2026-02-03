// --- MAP & DRAWING LOGIC ---

// New state for sample markers
let sampleMarkers = [];
let detailsInfoWindow = null;

/**
 * Main entry point for map initialization after country selection.
 */
async function startDemo(countryName) {
  try {
    await initMap(countryName);
  } catch (error) {
    console.error("Error starting the demo:", error);
    alert("Map initialization failed. Check console for details.");
    document.getElementById("country-selector-modal").classList.remove("hidden");
    document.getElementById("sidebar").classList.add("hidden");
  }
}

/**
 * Initializes the Google Map, deck.gl overlay, and main click listener.
 */
async function initMap(countryName) {
  const { Map, Circle, InfoWindow, Polyline, Polygon } = await google.maps.importLibrary("maps");
  const { Geocoder } = await google.maps.importLibrary("geocoding");
  const geocoder = new Geocoder();
  const { results } = await geocoder.geocode({ address: countryName });

  if (results.length > 0) {
    map = new Map(document.getElementById("map"), {
      mapId: "DEMO_MAP_ID",
      mapTypeControl: false,
      streetViewControl: false
    });
    map.fitBounds(results[0].geometry.viewport);

    deckglOverlay = new deck.GoogleMapsOverlay({});
    deckglOverlay.setMap(map);
    map.addListener('click', handleMapClick);
  } else {
    throw new Error("Geocoding failed for the selected country.");
  }
}

/**
 * Handles the user changing the demo type (Circle vs. Polygon vs. Region vs. Route).
 */
function handleDemoTypeChange(e) {
    const demoType = e.target.value;
    const isH3Function = demoType === 'h3-function';
    
    // 1. Reset UI to the selected mode (clears inputs, sets correct visibility)
    resetSidebarUI(demoType);

    // 2. Apply Special Rules for H3 Function
    if (isH3Function) {
        // Force H3 Toggle ON and disabled
        const h3Toggle = document.getElementById('h3-density-toggle');
        h3Toggle.checked = true;
        h3Toggle.disabled = true;
        
        // Show Slider with Max 8
        document.getElementById('h3-resolution-controls').classList.remove('hidden');
        const h3Slider = document.getElementById('h3-resolution-slider');
        h3Slider.max = '8';
        if (parseInt(h3Slider.value) > 8) {
            h3Slider.value = '8';
            document.getElementById('h3-resolution-value').textContent = '8';
        }
        
        // Always Hide Brand Filters for Function mode
        document.getElementById('brand-filters').classList.add('hidden');
        
        // Hide Opening Hours for Function mode
        document.getElementById('opening-hours-filters').classList.add('hidden');

    } else {
        // 3. Restore Standard State (if not handled by resetSidebarUI defaults)
        // Ensure Country-specific Brand Filters are visible if applicable (US)
        const brandFilters = document.getElementById('brand-filters');
        if (selectedCountryName === 'United States') {
            brandFilters.classList.remove('hidden');
        }
        
        // Show Opening Hours
        document.getElementById('opening-hours-filters').classList.remove('hidden');
    }
    
    map.setOptions({ draggableCursor: 'grab' });
    clearAllOverlays(true);
    invalidateQueryState();
}

/**
 * Central handler for all clicks on the map.
 */
function handleMapClick(e) {
    // If we are hovering over an H3 cell (and likely clicking it), ignore the map click
    // This prevents the map background click from clearing the H3 overlay
    if (isHoveringH3) return;

    const demoType = document.getElementById('demo-type-select').value;
    // Allow circle placement for both standard Circle Search AND the new H3 Function
    if (demoType === 'circle-search' || demoType === 'h3-function') {
        invalidateQueryState();
        clearAllOverlays(true);
        searchCenter = e.latLng;
        const radius = parseInt(document.getElementById('radius-input').value, 10);
        searchCircle = new google.maps.Circle({
            strokeColor: "#4285F4", strokeOpacity: 0.8, strokeWeight: 2,
            fillColor: "transparent", map, center: searchCenter, radius: radius,
        });
    } else if (demoType === 'polygon-search' && isDrawing) {
        invalidateQueryState();
        polygonVertices.push(e.latLng);
        tempPolyline.setPath(polygonVertices);
    }
}

/**
 * Puts the application into "drawing mode".
 */
function startDrawing() {
    invalidateQueryState();
    clearPolygon();
    isDrawing = true;
    polygonVertices = [];
    map.setOptions({ draggableCursor: 'crosshair' });
    tempPolyline = new google.maps.Polyline({ map: map, strokeColor: "#0000FF", strokeWeight: 2 });

    document.getElementById('start-drawing-btn').classList.add('hidden');
    document.getElementById('finish-drawing-btn').classList.remove('hidden');
    document.getElementById('polygon-instructions').textContent = "Click points on the map. Click 'Finish' when done.";
}

/**
 * Exits "drawing mode" and finalizes the polygon shape.
 */
function finishDrawing() {
    if (!isDrawing) return;
    isDrawing = false;
    map.setOptions({ draggableCursor: 'grab' });

    if (tempPolyline) tempPolyline.setMap(null);
    tempPolyline = null;

    document.getElementById('start-drawing-btn').classList.remove('hidden');
    document.getElementById('finish-drawing-btn').classList.add('hidden');
    document.getElementById('polygon-instructions').textContent = "Define a search area by drawing or pasting WKT.";

    if (polygonVertices.length < 3) {
        polygonVertices = [];
        return;
    }

    searchPolygon = new google.maps.Polygon({
        paths: polygonVertices, editable: true, draggable: true, fillColor: '#5599FF',
        fillOpacity: 0.3, strokeColor: '#0000FF', strokeWeight: 2, map: map,
    });

    updateWktFromPolygon(searchPolygon);

    searchPolygon.getPaths().forEach(path => {
        google.maps.event.addListener(path, 'set_at', () => {
            updateWktFromPolygon(searchPolygon);
            invalidateQueryState();
        });
        google.maps.event.addListener(path, 'insert_at', () => {
            updateWktFromPolygon(searchPolygon);
            invalidateQueryState();
        });
    });
    invalidateQueryState();
}

/**
 * Clears all visual overlays from the map.
 * @param {boolean} fullReset If true, also nullifies state variables for search geometry.
 */
function clearAllOverlays(fullReset = false) {
    if (isDrawing) finishDrawing();
    if (searchCircle) searchCircle.setMap(null);
    if (searchPolygon) searchPolygon.setMap(null);
    if (routePolyline) routePolyline.setMap(null);
    if (infoWindow) infoWindow.close();
    if (deckglOverlay) deckglOverlay.setProps({ layers: [] });
    
    clearSampleMarkers();

    if (fullReset) {
        searchCenter = null; 
        searchCircle = null; 
        searchPolygon = null;
        routePolyline = null;
        originPlace = null;
        destinationPlace = null;
    }
}

/**
 * Clears only the polygon and its associated state.
 */
function clearPolygon() {
    invalidateQueryState();
    if (isDrawing) finishDrawing();
    if (searchPolygon) searchPolygon.setMap(null);
    searchPolygon = null;
    document.getElementById('wkt-input').value = '';
    document.getElementById('wkt-input').classList.remove('invalid');
}

/**
 * Clears all sample place markers from the map.
 */
function clearSampleMarkers() {
    sampleMarkers.forEach(m => m.map = null);
    sampleMarkers = [];
    if (detailsInfoWindow) {
        detailsInfoWindow.close();
    }
}

/**
 * Fetches details for a list of place IDs and puts markers on the map.
 * @param {string[]} placeIds List of Place IDs to show.
 */
async function loadPlaceMarkers(placeIds) {
    clearSampleMarkers();
    
    if (!placeIds || placeIds.length === 0) return;

    // Limit to top 20 to ensure performance/rate limits
    const limit = 20;
    const subset = placeIds.slice(0, limit);
    
    updateStatus(`Fetching locations for ${subset.length} places...`);
    
    try {
        const { Place } = await google.maps.importLibrary("places");
        const { AdvancedMarkerElement, PinElement } = await google.maps.importLibrary("marker");
        // Import to register web components for InfoWindow
        await google.maps.importLibrary("places"); 

        if (!detailsInfoWindow) {
            detailsInfoWindow = new google.maps.InfoWindow();
        }

        const bounds = new google.maps.LatLngBounds();

        for (const id of subset) {
            // Individual try/catch so one failure doesn't stop the loop
            try {
                const place = new Place({ id: id });
                await place.fetchFields({ fields: ['location'] });
                
                if (!place.location) continue;

                const pin = new PinElement({
                    scale: 0.8,
                    background: "#FBBC04",
                    borderColor: "#137333",
                    glyphColor: "white"
                });

                const marker = new AdvancedMarkerElement({
                    map: map,
                    position: place.location,
                    content: pin.element,
                    title: "Click for details"
                });
                
                // Click Listener: Create Web Component in InfoWindow
                marker.addListener('click', () => {
                    const container = document.createElement('div');
                    container.className = 'info-window-component-container';
                    
                    const details = document.createElement('gmp-place-details-compact');
                    details.setAttribute('orientation', 'vertical');
                    
                    const request = document.createElement('gmp-place-details-place-request');
                    request.setAttribute('place', id);
                    
                    const allContent = document.createElement('gmp-place-all-content');
                    
                    details.appendChild(request);
                    details.appendChild(allContent);
                    container.appendChild(details);

                    detailsInfoWindow.setContent(container);
                    detailsInfoWindow.open(map, marker);
                });

                sampleMarkers.push(marker);
                bounds.extend(place.location);

            } catch (e) {
                console.warn(`Failed to fetch place ${id}`, e);
            }
        }
        
        updateStatus(`Showing ${sampleMarkers.length} sample places. Click a marker for details.`, 'success');
        
    } catch (error) {
        console.error("Error loading markers:", error);
        updateStatus("Error loading sample markers.", 'error');
    }
}