// --- DISPLAY & DATA HELPERS ---

/**
 * Displays the result of a simple aggregate query in a Google Maps InfoWindow.
 * This function is now capable of handling multiple rows for brand queries.
 * @param {object} bqResult The JSON response from the BigQuery API.
 * @param {google.maps.LatLng} center The location to anchor the InfoWindow.
 */
function displayResultsOnMap(bqResult, center) {
    if (infoWindow) infoWindow.close();

    // Handle cases where the query returns no rows (e.g., count < 5).
    if (!bqResult.rows || bqResult.rows.length === 0) {
        infoWindow = new google.maps.InfoWindow({
            content: "<p>Query returned no results.<br>(Note: Aggregations may require a minimum count to appear).</p>"
        });
        infoWindow.setPosition(center);
        infoWindow.open(map);
        return;
    }

    const schema = bqResult.schema.fields;
    
    // Build an HTML string from all rows in the result.
    let content = '<div style="font-size: 14px; line-height: 1.6;">';

    bqResult.rows.forEach((row, rowIndex) => {
        if (rowIndex > 0) {
            content += '<hr style="margin: 8px 0; border: none; border-top: 1px solid #ccc;">';
        }
        const rowData = row.f;
        schema.forEach((field, index) => {
            const name = field.name.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
            content += `<strong>${name}:</strong> ${rowData[index].v}<br>`;
        });
    });

    content += '</div>';

    infoWindow = new google.maps.InfoWindow({ content });
    infoWindow.setPosition(center);
    infoWindow.open(map);
}

/**
 * Displays the results of an H3 density query as a deck.gl heatmap layer.
 * This version processes parallel arrays of h3 indices and counts from a single-row ARRAY_AGG result.
 * @param {object} bqResult The JSON response from the BigQuery API.
 */
function displayH3Results(bqResult) {
    const tooltip = document.getElementById('tooltip');
    
    // With ARRAY_AGG, we expect exactly one row.
    if (!bqResult.rows || bqResult.rows.length === 0) {
        updateStatus("Query returned no results. Try a larger search area or different filters.", 'info');
        return;
    }

    const rowData = bqResult.rows[0].f;
    const indices = rowData[0].v; // Array of h3_index objects: [{v: '...'}, {v: '...'}]
    const counts = rowData[1].v;  // Array of count objects: [{v: '...'}, {v: '...'}]

    // If the first index is null or the array is empty, it means the ARRAY_AGG was empty.
    if (!indices || indices.length === 0 || indices[0].v === null) {
        updateStatus("Query returned no results. Try a larger search area or different filters.", 'info');
        return;
    }

    const h3Data = [];
    for (let i = 0; i < indices.length; i++) {
        h3Data.push({
            h3_index: indices[i].v,
            count: parseInt(counts[i].v, 10),
        });
    }

    const maxCount = Math.max(...h3Data.map(d => d.count));

    // Create a new deck.gl GeoJsonLayer for the H3 cells.
    const layer = new deck.GeoJsonLayer({
        id: 'h3-layer',
        data: h3Data.map(d => {
            const boundary = h3.cellToBoundary(d.h3_index);
            const coordinates = boundary.map(p => [p[1], p[0]]); // Swap to [lng, lat]
            coordinates.push(coordinates[0]); // Close the polygon ring

            return {
                type: 'Feature',
                geometry: {
                    type: 'Polygon',
                    coordinates: [coordinates]
                },
                properties: { count: d.count }
            };
        }),
        wrapLongitude: true,
        pickable: true,
        stroked: true,
        filled: true,
        lineWidthMinPixels: 1,
        getFillColor: d => colorScale(d.properties.count, maxCount),
        getLineColor: [255, 255, 255, 100],
        onHover: info => {
            isHoveringH3 = !!info.object; // Track hover state to prevent map click conflicts
            
            if (info.object) {
                tooltip.style.display = 'block';
                tooltip.style.left = `${info.x}px`;
                tooltip.style.top = `${info.y}px`;
                tooltip.innerHTML = `Count: ${info.object.properties.count}`;
            } else {
                tooltip.style.display = 'none';
            }
        }
    });

    deckglOverlay.setProps({ layers: [layer] });
}


/**
 * Parses a WKT Polygon string (e.g., "POLYGON((lng lat, ...))") into a GeoJSON coordinates array.
 * Uses Regex to robustly handle optional spaces after POLYGON.
 * @param {string} wkt The WKT string.
 * @returns {Array} Array of [lng, lat] pairs.
 */
function parseWktPolygon(wkt) {
    if (!wkt) return [];
    
    // Match POLYGON((...)) or POLYGON ((...)) case-insensitive
    const match = wkt.match(/POLYGON\s*\(\((.*)\)\)/i);
    
    if (!match || !match[1]) {
        console.error("Failed to parse WKT:", wkt);
        return [];
    }

    try {
        const content = match[1];
        return [content.split(',').map(pair => {
            const [lng, lat] = pair.trim().split(/\s+/); // Split by any whitespace
            return [parseFloat(lng), parseFloat(lat)];
        })];
    } catch (e) {
        console.error("Failed to parse WKT coordinates:", wkt, e);
        return [];
    }
}

/**
 * Displays results from the PLACES_COUNT_PER_H3 function.
 * Uses the server-side 'geography' geometry directly.
 * @param {object} bqResult 
 */
function displayH3FunctionResults(bqResult) {
    const tooltip = document.getElementById('tooltip');

    if (!bqResult.rows || bqResult.rows.length === 0) {
        updateStatus("Query returned no results.", 'info');
        return;
    }

    // Map rows to GeoJSON features
    const features = bqResult.rows.map(row => {
        const cols = row.f;
        // Schema assumed: h3_cell_index (0), geography (1), count (2), place_ids (3)
        const wkt = cols[1].v;
        const count = parseInt(cols[2].v, 10);
        
        // Parse place_ids. BigQuery returns arrays as {v: [{v: 'id1'}, {v: 'id2'}]}
        let placeIds = [];
        if (cols[3] && cols[3].v) {
            placeIds = cols[3].v.map(item => item.v);
        }
        
        return {
            type: 'Feature',
            geometry: {
                type: 'Polygon',
                coordinates: parseWktPolygon(wkt)
            },
            properties: { 
                count: count,
                place_ids: placeIds
            }
        };
    });

    const maxCount = Math.max(...features.map(f => f.properties.count));

    const layer = new deck.GeoJsonLayer({
        id: 'h3-func-layer',
        data: features,
        pickable: true,
        stroked: true,
        filled: true,
        lineWidthMinPixels: 1,
        getFillColor: d => colorScale(d.properties.count, maxCount),
        getLineColor: [255, 255, 255, 150],
        onHover: info => {
            isHoveringH3 = !!info.object; // Track hover state
            
            if (info.object) {
                tooltip.style.display = 'block';
                tooltip.style.left = `${info.x}px`;
                tooltip.style.top = `${info.y}px`;
                let html = `Count: ${info.object.properties.count}`;
                if (info.object.properties.place_ids && info.object.properties.place_ids.length > 0) {
                    html += `<br><span style="color:#ccc; font-size:11px;">Click to show sample places</span>`;
                }
                tooltip.innerHTML = html;
            } else {
                tooltip.style.display = 'none';
            }
        },
        onClick: info => {
            if (info.object && info.object.properties.place_ids) {
                loadPlaceMarkers(info.object.properties.place_ids);
            }
        }
    });

    deckglOverlay.setProps({ layers: [layer] });
}

/**
 * Calculates a color for a heatmap cell based on its value relative to the max value.
 * @param {number} value The count for the current cell.
 * @param {number} max The maximum count in the dataset.
 * @returns {Array<number>} An RGBA color array.
 */
function colorScale(value, max) {
    const percentage = Math.sqrt(value / max); // Use sqrt for better visual distribution of colors.
    const r = 255;
    const g = 255 - (200 * percentage);
    const b = 0;
    return [r, g, b, 180]; // Yellow to Red, with some transparency
}