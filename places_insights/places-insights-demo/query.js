// --- BIGQUERY QUERY LOGIC ---

// Note: fetchRouteAsWkt is imported from routes.js

// --- SEARCH PARAMETER HELPERS ---

function getCircleSearchParams() {
    if (!searchCenter) {
        return { success: false, message: "Click a location on the map to set the search center." };
    }
    const radius = parseInt(document.getElementById('radius-input').value, 10);
    const filter = `ST_DWITHIN(ST_GEOGPOINT(${searchCenter.lng()}, ${searchCenter.lat()}), places.point, ${radius})`;
    return { success: true, filter, center: searchCenter, searchAreaVar: '' };
}

function getPolygonSearchParams() {
    if (!searchPolygon) {
        return { success: false, message: "Draw or paste a polygon to define the search area." };
    }
    const wkt = document.getElementById('wkt-input').value;
    const searchAreaVar = `DECLARE search_area GEOGRAPHY; SET search_area = ST_GEOGFROMTEXT("""${wkt}""");`;
    const filter = 'ST_CONTAINS(search_area, places.point)';
    return { success: true, filter, center: searchPolygon.getPath().getAt(0), searchAreaVar };
}

async function getRegionSearchParams() {
    const regionInputValue = document.getElementById('region-type-select').value;
    const regionNameInput = toTitleCase(document.getElementById('region-name-input').value.trim());
    const regionTags = [...document.querySelectorAll('#selected-regions-list span')].map(s => s.textContent);
    
    if (!regionInputValue || (!regionNameInput && regionTags.length === 0)) {
        return { success: false, message: "Select a Region Type and enter at least one Region Name." };
    }
    
    const uniqueRegionNames = [...new Set([...regionTags, regionNameInput].filter(Boolean))];
    const [field, dataType] = regionInputValue.split('|');
    const filter = buildRegionFilter(field, dataType, uniqueRegionNames);

    updateStatus('Geocoding regions...');
    const { Geocoder } = await google.maps.importLibrary("geocoding");
    const bounds = new google.maps.LatLngBounds();
    const geocodePromises = uniqueRegionNames.map(name => new Geocoder().geocode({ address: `${name}, ${selectedCountryName}` }));
    
    const resultsArray = await Promise.all(geocodePromises);
    resultsArray.forEach(({ results }) => {
        if (results.length > 0) bounds.union(results[0].geometry.viewport);
    });

    if (bounds.isEmpty()) {
        throw new Error(`Could not geocode any of the specified regions.`);
    }
    map.fitBounds(bounds);

    return {
        success: true, filter, center: bounds.getCenter(), searchAreaVar: '',
        isMultiRegion: uniqueRegionNames.length > 1, regionType: field, regionDataType: dataType
    };
}

async function getRouteSearchParams() {
    if (!originPlace || !destinationPlace) {
        return { success: false, message: "Select both an origin and a destination for the route." };
    }
    updateStatus('Calculating route...');
    // Call helper from routes.js
    const routeData = await fetchRouteAsWkt(originPlace, destinationPlace);
    const radius = parseInt(document.getElementById('route-radius-input').value, 10);
    const searchAreaVar = `DECLARE route GEOGRAPHY; SET route = ST_GEOGFROMTEXT("""${routeData.wktString}""");`;
    const filter = `ST_DWITHIN(route, places.point, ${radius})`;
    return { success: true, filter, center: routeData.bounds.getCenter(), searchAreaVar };
}


/**
 * The main function to execute a query. It's called when the "Run Search" button is clicked.
 */
async function runQuery() {
    const runQueryBtn = document.getElementById('run-query-btn');
    runQueryBtn.disabled = true;
    runQueryBtn.textContent = 'Running...';
    updateStatus('Validating inputs...');

    try {
        const demoType = document.getElementById('demo-type-select').value;
        
        let countryCode;
        if (DATASET === 'SAMPLE') {
            countryCode = SAMPLE_LOCATIONS[selectedCountryName];
        } else {
            countryCode = COUNTRY_CODES[selectedCountryName];
        }

        let sqlQuery;
        
        // Clean up any existing sample markers from H3 interaction
        if (typeof clearSampleMarkers === 'function') {
            clearSampleMarkers();
        }

        // 1. Branch for H3 Function (Special Case)
        if (demoType === 'h3-function') {
            if (!searchCenter) {
                throw new Error("Click a location on the map to set the search center.");
            }
            updateStatus('Checking authorization...');
            const token = await ensureAccessToken();
            
            updateStatus('Building function query...');
            sqlQuery = buildH3FunctionQuery(countryCode);
            lastExecutedQuery = sqlQuery;

            if (infoWindow) infoWindow.close();
            if (deckglOverlay) deckglOverlay.setProps({ layers: [] });

            updateStatus('Executing function...');
            const response = await fetch(`https://bigquery.googleapis.com/bigquery/v2/projects/${GCP_PROJECT_ID}/queries`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                body: JSON.stringify({ query: sqlQuery, useLegacySql: false, maxResults: 100000 })
            });
            
            const result = await response.json();
            if (!response.ok) throw new Error(result.error?.message || 'API request failed.');

            document.getElementById('view-query-btn').classList.remove('hidden');
            if (searchCircle) searchCircle.setMap(null); // Hide circle so heatmap is visible
            
            displayH3FunctionResults(result);
            updateStatus('Query successful.', 'success');
        
        } else {
            // 2. Standard SQL Logic (Circle, Polygon, Region, Route)
            
            // Get Geometry Parameters
            let searchParams;
            switch (demoType) {
                case 'circle-search': searchParams = getCircleSearchParams(); break;
                case 'polygon-search': searchParams = getPolygonSearchParams(); break;
                case 'region-search': searchParams = await getRegionSearchParams(); break;
                case 'route-search': searchParams = await getRouteSearchParams(); break;
                default: throw new Error("Invalid demo type selected.");
            }

            if (!searchParams.success) {
                updateStatus(searchParams.message, 'error');
                return;
            }

            // Clear previous results and Authorize
            if (infoWindow) infoWindow.close();
            if (deckglOverlay) deckglOverlay.setProps({ layers: [] });
            updateStatus('Checking authorization...');
            const token = await ensureAccessToken();
            
            // Gather all other filters
            updateStatus('Building query...');
            const allFilters = [searchParams.filter];
            
            // Place Types Logic (Primary vs Included)
            const placeTypes = [...document.querySelectorAll('#selected-types-list span')].map(s => s.textContent);
            // Use new Checkbox
            const usePrimaryType = document.getElementById('primary-type-checkbox').checked;
            
            if (placeTypes.length > 0) {
                if (usePrimaryType) {
                    // Primary Type filter
                    const typeList = placeTypes.map(t => `'${t}'`).join(', ');
                    allFilters.push(`places.primary_type IN (${typeList})`);
                } else {
                    // Included Type (Standard) filter
                    allFilters.push(`(${placeTypes.map(t => `'${t}' IN UNNEST(places.types)`).join(' OR ')})`);
                }
            }

            const attributes = [...document.querySelectorAll('.attribute-filter:checked')].map(cb => cb.name);
            if (attributes.length > 0) allFilters.push(...buildAttributeFilter(attributes));
            const ratingFilter = buildRatingFilter(parseFloat(document.getElementById('min-rating-input').value), parseFloat(document.getElementById('max-rating-input').value));
            if (ratingFilter) allFilters.push(ratingFilter);
            
            const bizStatus = document.getElementById('business-status-select').value;
            if (bizStatus) allFilters.push(`places.business_status = '${bizStatus}'`);
            
            // Brand Filters (only applicable here, not in H3 Function)
            const brandNames = [...document.querySelectorAll('#selected-brands-list span')].map(s => s.textContent);
            if (brandNames.length > 0) allFilters.push(buildBrandFilter(brandNames));
            const brandCategory = document.getElementById('brand-category-select').value;
            if (brandCategory) allFilters.push(buildBrandCategoryFilter(brandCategory));
            
            const openingDay = document.getElementById('day-of-week-select').value;
            const hoursFilter = buildOpeningHoursFilter(openingDay, document.getElementById('start-time-input').value, document.getElementById('end-time-input').value);
            if (hoursFilter.whereClause) allFilters.push(hoursFilter.whereClause);

            // Assemble FROM clause dynamically based on dataset type
            let tableName;
            if (DATASET === 'SAMPLE') {
                tableName = `places_insights___${countryCode}___sample.places_sample`;
            } else {
                tableName = `places_insights___${countryCode}.places`;
            }

            let fromClause = `FROM \`${tableName}\` places`;
            
            if (openingDay) fromClause += ` ${hoursFilter.unnestClause}`;
            
            // Brands Join Logic
            const isBrandQuery = brandNames.length > 0 || !!brandCategory;
            if (isBrandQuery) {
                let brandsTable;
                if (DATASET === 'SAMPLE') {
                    brandsTable = 'places_insights___us___sample.brands';
                } else {
                    brandsTable = 'places_insights___us.brands';
                }
                
                fromClause += `, UNNEST(places.brand_ids) AS brand_id LEFT JOIN \`${brandsTable}\` brands ON brand_id = brands.id`;
            }
            
            const whereClause = allFilters.length > 0 ? `WHERE ${allFilters.join(' AND ')}` : '';
            
            // Build the final SQL Query
            const useH3 = document.getElementById('h3-density-toggle').checked;
            
            if (useH3) {
                const h3Res = parseInt(document.getElementById('h3-resolution-slider').value, 10);
                sqlQuery = buildH3DensityQuery(searchParams.searchAreaVar, fromClause, whereClause, h3Res);
            } else {
                sqlQuery = buildAggregateQuery(searchParams.searchAreaVar, fromClause, whereClause, placeTypes, isBrandQuery, searchParams.isMultiRegion, searchParams.regionType, searchParams.regionDataType);
            }
            lastExecutedQuery = sqlQuery;

            // Execute Query and Display Results
            updateStatus('Executing query...');
            const response = await fetch(`https://bigquery.googleapis.com/bigquery/v2/projects/${GCP_PROJECT_ID}/queries`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
                body: JSON.stringify({ query: sqlQuery, useLegacySql: false, maxResults: 100000 })
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.error?.message || 'API request failed.');
            
            document.getElementById('view-query-btn').classList.remove('hidden');
            
            if (useH3) {
                if (searchCircle) searchCircle.setMap(null);
                if (searchPolygon) searchPolygon.setMap(null);
                displayH3Results(result);
            } else {
                if (searchCircle) searchCircle.setMap(map);
                if (searchPolygon) searchPolygon.setMap(map);
                displayResultsOnMap(result, searchParams.center);
            }

            let successMessage = 'Query successful.';
            if (!useH3 && result.rows && Number(result.totalRows) > result.rows.length) {
                successMessage += ` Warning: Displaying ${result.rows.length.toLocaleString()} of ${Number(result.totalRows).toLocaleString()} total rows.`;
            }
            updateStatus(successMessage, 'success');
        }

    } catch (error) {
        console.error('Query failed:', error);
        updateStatus(`Error: ${error.message}`, 'error');
    } finally {
        runQueryBtn.disabled = false;
        runQueryBtn.textContent = 'Run Search';
    }
}


// --- FILTER BUILDERS ---

function buildBrandFilter(brandNames) {
    if (!brandNames || brandNames.length === 0) return '';
    const sanitizedNames = brandNames.map(name => `"${name.replace(/"/g, '\\"')}"`).join(', ');
    return `brands.name IN (${sanitizedNames})`;
}

function buildBrandCategoryFilter(brandCategory) {
    if (!brandCategory) return '';
    const sanitizedCategory = brandCategory.replace(/"/g, '\\"');
    return `brands.category = "${sanitizedCategory}"`;
}

function buildOpeningHoursFilter(day, startTime, endTime) {
    if (!day || (!startTime && !endTime)) return { unnestClause: '', whereClause: '' };
    const unnestClause = `, UNNEST(places.regular_opening_hours.${day}) AS opening_period`;
    let conditions = [];
    if (startTime) conditions.push(`opening_period.start_time <= TIME '${startTime}:00'`);
    if (endTime) conditions.push(`opening_period.end_time >= TIME '${endTime}:00'`);
    return { unnestClause, whereClause: conditions.join(' AND ') };
}

function buildAttributeFilter(attributes) {
    if (!attributes || attributes.length === 0) return [];
    return attributes.map(attr => `places.${attr} = TRUE`);
}

function buildRatingFilter(min, max) {
    const hasMin = !isNaN(min);
    const hasMax = !isNaN(max);
    if (hasMin && hasMax) return `places.rating BETWEEN ${min} AND ${max}`;
    if (hasMin) return `places.rating >= ${min}`;
    if (hasMax) return `places.rating <= ${max}`;
    return '';
}

function buildRegionFilter(regionType, regionDataType, regionNames) {
    if (!regionType || !regionNames || regionNames.length === 0) return '';
    const sanitizedNames = regionNames.map(name => `'${name.replace(/'/g, "\\'")}'`).join(', ');
    if (regionDataType === 'STRING') {
        return `places.${regionType} IN (${sanitizedNames})`;
    }
    return `EXISTS (SELECT 1 FROM UNNEST(places.${regionType}) AS name WHERE name IN (${sanitizedNames}))`;
}

// --- UNIFIED QUERY BUILDERS ---

function buildAggregateQuery(searchAreaVar, fromClause, whereClause, types, isBrandQuery, isMultiRegion, regionType, regionDataType) {
    if (isMultiRegion && regionDataType === 'STRING') {
        return `${searchAreaVar} SELECT WITH AGGREGATION_THRESHOLD places.${regionType} AS region_name, COUNT(*) AS count ${fromClause} ${whereClause} GROUP BY region_name ORDER BY count DESC`;
    }
    if (isBrandQuery) {
        return `${searchAreaVar} SELECT WITH AGGREGATION_THRESHOLD brands.name, COUNT(places.id) AS count ${fromClause} ${whereClause} GROUP BY brands.name ORDER BY count DESC`;
    }
    if (types.length <= 1) {
        return `${searchAreaVar} SELECT WITH AGGREGATION_THRESHOLD COUNT(*) AS total_count ${fromClause} ${whereClause}`;
    }
    const select = types.map(t => `COUNTIF('${t}' IN UNNEST(places.types)) AS ${t.replace(/ /g, '_')}_count`).join(',\n  ');
    return `${searchAreaVar} SELECT WITH AGGREGATION_THRESHOLD ${select}, COUNT(*) AS total_count ${fromClause} ${whereClause}`;
}

function buildH3DensityQuery(searchAreaVar, fromClause, whereClause, resolution) {
    // This is the inner query that performs the main aggregation.
    const innerQuery = `
      SELECT WITH AGGREGATION_THRESHOLD
        \`carto-os.carto.H3_FROMGEOGPOINT\`(places.point, ${resolution}) AS h3_index,
        COUNT(*) AS place_count
      ${fromClause}
      ${whereClause}
      GROUP BY h3_index
    `;

    // This outer query wraps the inner one to aggregate results into arrays.
    return `${searchAreaVar}
      SELECT 
        ARRAY_AGG(h3_index) as indices, 
        ARRAY_AGG(place_count) as counts
      FROM (${innerQuery})
      WHERE h3_index IS NOT NULL
    `;
}

// --- NEW FUNCTION QUERY BUILDER ---

function buildH3FunctionQuery(countryCode) {
    const radius = parseInt(document.getElementById('radius-input').value, 10);
    const h3Resolution = parseInt(document.getElementById('h3-resolution-slider').value, 10);
    
    // Construct JSON_OBJECT fields
    let jsonParts = [];
    
    // Geography (Point + Radius)
    jsonParts.push(`'geography', ST_GEOGPOINT(${searchCenter.lng()}, ${searchCenter.lat()})`);
    jsonParts.push(`'geography_radius', ${radius}`);
    jsonParts.push(`'h3_resolution', ${h3Resolution}`);

    // Standard Filters
    // 1. Business Status
    const bizStatus = document.getElementById('business-status-select').value;
    if (bizStatus) {
        jsonParts.push(`'business_status', ['${bizStatus}']`);
    }

    // 2. Place Types (Toggle logic)
    const placeTypes = [...document.querySelectorAll('#selected-types-list span')].map(s => s.textContent);
    // Use new Checkbox
    const usePrimaryType = document.getElementById('primary-type-checkbox').checked;

    if (placeTypes.length > 0) {
        const formattedTypes = placeTypes.map(t => `"${t}"`).join(', ');
        if (usePrimaryType) {
            jsonParts.push(`'primary_type', [${formattedTypes}]`);
        } else {
            jsonParts.push(`'types', [${formattedTypes}]`);
        }
    }

    // 3. Ratings
    const minRating = parseFloat(document.getElementById('min-rating-input').value);
    const maxRating = parseFloat(document.getElementById('max-rating-input').value);
    if (!isNaN(minRating)) jsonParts.push(`'min_rating', ${minRating}`);
    if (!isNaN(maxRating)) jsonParts.push(`'max_rating', ${maxRating}`);

    // 4. Boolean Attributes
    const attributes = [...document.querySelectorAll('.attribute-filter:checked')].map(cb => cb.name);
    attributes.forEach(attr => {
        jsonParts.push(`'${attr}', TRUE`);
    });

    // Note: Brand filters are strictly excluded here.
    
    // Dynamic table name based on dataset configuration
    let tableName;
    if (DATASET === 'SAMPLE') {
        tableName = `places_insights___${countryCode}___sample`;
    } else {
        tableName = `places_insights___${countryCode}`;
    }

    return `
      SELECT * FROM \`${tableName}.PLACES_COUNT_PER_H3\`(
        JSON_OBJECT(
          ${jsonParts.join(',\n          ')}
        )
      )
    `;
}