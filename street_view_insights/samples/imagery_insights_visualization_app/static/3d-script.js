/**
 * Copyright 2025 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * https://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */


let dataset = [];
let map;
let markers = [];
const gmp = {};

async function initMap() {
    const { Map3DElement, MapMode, Marker3DElement } = await google.maps.importLibrary("maps3d");
    const { PinElement } = await google.maps.importLibrary("marker");

    gmp.Marker3DElement = Marker3DElement;
    gmp.PinElement = PinElement;

    map = new Map3DElement({
        center: { lat: 45.5017, lng: -73.5673, altitude: 0 },
        tilt: 45,
        range: 5000,
        mode: MapMode.HYBRID
    });

    document.getElementById('map').appendChild(map);

    loadData();
}

async function loadData() {
    const filename = 'ga_sample.json';
    try {
        const response = await fetch(`/data/${filename}`);
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        const jsonData = await response.json();
        
        dataset = [];
        if (jsonData && Array.isArray(jsonData)) {
            jsonData.forEach(asset => {
                if (asset.observations && Array.isArray(asset.observations)) {
                    asset.observations.forEach(obs => {
                        const lat = parseFloat(obs.latitude);
                        const lon = parseFloat(obs.longitude);

                        if (!isNaN(lat) && !isNaN(lon)) {
                            dataset.push({
                                latitude: lat,
                                longitude: lon,
                                ObservationID: obs.observation_id,
                                TrackID: asset.asset_id
                            });
                        }
                    });
                }
            });
        }
    } catch (error) {
        console.error(`Error loading data file (${filename}).`, error);
        dataset = [];
    }
    renderMarkers();
}

function clearMarkers() {
    markers.forEach(marker => marker.remove());
    markers = [];
}

function renderMarkers() {
    clearMarkers();
    if (!map || dataset.length === 0 || !gmp.Marker3DElement || !gmp.PinElement) return;

    const tooltip = document.getElementById('tooltip');
    let totalLat = 0;
    let totalLng = 0;
    let markerCount = 0;

    dataset.forEach(item => {
        const location = { lat: item.latitude, lng: item.longitude };
        if (location) {
            const marker = new gmp.Marker3DElement({
                position: location,
            });

            const glyphImgUrl = 'https://www.gstatic.com/images/branding/productlogos/maps/v7/192px.svg';
            const pin = new gmp.PinElement({
                background: '#e11d48',
                borderColor: '#ffffff',
                glyph: new URL(glyphImgUrl)
            });
            marker.appendChild(pin);
            
            marker.addEventListener('pointerenter', () => {
                tooltip.textContent = `Track ID: ${item.TrackID}`;
                tooltip.style.display = 'block';
            });

            marker.addEventListener('pointerleave', () => {
                tooltip.style.display = 'none';
            });

            document.addEventListener('mousemove', (e) => {
                tooltip.style.left = `${e.clientX + 15}px`;
                tooltip.style.top = `${e.clientY}px`;
            });

            map.append(marker);
            markers.push(marker);

            totalLat += location.lat;
            totalLng += location.lng;
            markerCount++;
        }
    });

    if (markerCount > 0) {
        const avgLat = totalLat / markerCount;
        const avgLng = totalLng / markerCount;
        map.center = { lat: avgLat, lng: avgLng, altitude: 0 };
    }
}