// --- ROUTES API LOGIC ---

/**
 * Calls the Routes API to get a route between an origin and destination,
 * draws it on the map, and returns the route as a WKT LINESTRING.
 * @param {google.maps.places.Place} origin The origin Place object.
 * @param {google.maps.places.Place} destination The destination Place object.
 * @returns {Promise<{wktString: string, bounds: google.maps.LatLngBounds}>}
 */
async function fetchRouteAsWkt(origin, destination) {
    const API_KEY = MAPS_API_KEY; 
    const URL = 'https://routes.googleapis.com/directions/v2:computeRoutes';

    const originLatLng = origin.location.toJSON();
    const destinationLatLng = destination.location.toJSON();

    const requestBody = {
        origin: { location: { latLng: { latitude: originLatLng.lat, longitude: originLatLng.lng }}},
        destination: { location: { latLng: { latitude: destinationLatLng.lat, longitude: destinationLatLng.lng }}},
        travelMode: 'DRIVE',
        routingPreference: 'TRAFFIC_AWARE',
        polylineEncoding: 'GEO_JSON_LINESTRING',
        computeAlternativeRoutes: false,
    };

    const response = await fetch(URL, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-Goog-Api-Key': API_KEY,
            'X-Goog-FieldMask': 'routes.polyline.geoJsonLinestring,routes.viewport',
        },
        body: JSON.stringify(requestBody),
    });

    if (!response.ok) {
        const errorBody = await response.json();
        console.error('Error from Routes API:', errorBody);
        throw new Error(`Routes API request failed: ${errorBody.error?.message || response.status}`);
    }

    const data = await response.json();
    if (!data.routes || data.routes.length === 0) {
        throw new Error('No routes found between the selected origin and destination.');
    }

    const route = data.routes[0];
    const coordinates = route.polyline.geoJsonLinestring.coordinates;
    const wktCoordinatePairs = coordinates.map(coord => `${coord[0]} ${coord[1]}`);
    const wktString = `LINESTRING(${wktCoordinatePairs.join(', ')})`;

    if (routePolyline) routePolyline.setMap(null);
    const path = coordinates.map(coord => ({ lng: coord[0], lat: coord[1] }));
    routePolyline = new google.maps.Polyline({
        path: path,
        strokeColor: '#4285F4',
        strokeOpacity: 0.8,
        strokeWeight: 6,
        map: map,
    });
    
    const viewport = route.viewport;
    const lowPoint = { lat: viewport.low.latitude, lng: viewport.low.longitude };
    const highPoint = { lat: viewport.high.latitude, lng: viewport.high.longitude };
    const bounds = new google.maps.LatLngBounds(lowPoint, highPoint);
    map.fitBounds(bounds);
    
    return { wktString, bounds };
}