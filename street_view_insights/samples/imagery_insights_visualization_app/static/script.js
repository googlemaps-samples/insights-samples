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


const API_KEY = "";
let panorama, map;
let currentItemIndex = 0;
let currentOverlayOrMarker = null;
let dataset = [];
let useCameraPose = false;
let useHeading = true;
let usePitch = false;
let useRoll = false; // Note: Roll is not supported by the Street View API's setPov function.
let loadPhotographerPov = false;
let ArrowMarkerOverlay;

async function loadData() {
    // If you are still seeing errors, please do a hard refresh of your browser (Ctrl+Shift+R or Cmd+Shift+R).
    const filename = 'ga_sample.json';
    try {
        const response = await fetch(`/data/${filename}`);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        const jsonData = await response.json();
        
        dataset = [];
        if (jsonData && Array.isArray(jsonData)) {
            jsonData.forEach(asset => {
                if (asset.observations && Array.isArray(asset.observations)) {
                    asset.observations.forEach(obs => {
                        const lat = parseFloat(obs.latitude);
                        const lon = parseFloat(obs.longitude);

                        if (obs.camera_pose && !isNaN(lat) && !isNaN(lon)) {
                            const cameraPose = {
                                lat: parseFloat(obs.camera_pose.latitude),
                                lng: parseFloat(obs.camera_pose.longitude),
                                altMeters: parseFloat(obs.camera_pose.altitude),
                                headingDeg: parseFloat(obs.camera_pose.heading),
                                pitchDeg: parseFloat(obs.camera_pose.pitch)
                            };
                            
                            dataset.push({
                                latitude: lat,
                                longitude: lon,
                                cameraPose: cameraPose,
                                captureTimestamp: obs.detection_time,
                                TrackID: asset.asset_id,
                                ObservationID: obs.observation_id,
                                mapUrl: obs.map_url
                            });
                        } else {
                            console.warn('Skipping observation with invalid or missing coordinates:', obs.observation_id);
                        }
                    });
                }
            });
            console.log(`Successfully loaded and processed data from: ${filename}`);
        } else {
            console.warn(`Data file (${filename}) is empty or invalid.`);
        }
    } catch (error) {
        console.error(`Error loading data file (${filename}). Error:`, error);
        dataset = [];
    }
    currentItemIndex = 0;
    displayCurrentItem();
}

function displayCurrentItem() {
    const viewContainer = document.getElementById('view-container');
    if (!panorama || !map || !dataset || dataset.length === 0) {
        document.getElementById('infoTitle').textContent = "No data loaded or dataset is empty.";
        if(viewContainer) viewContainer.style.display = 'none';
        return;
    }
    if(viewContainer) viewContainer.style.display = 'flex';

     if (currentItemIndex < 0 || currentItemIndex >= dataset.length) {
        currentItemIndex = 0;
    }

    panorama.setVisible(true);
    const item = dataset[currentItemIndex];
    
    if (!item || isNaN(item.latitude) || isNaN(item.longitude)) {
        console.error("Current item has invalid coordinates:", item);
        return;
    }

    const markerLocationLatLng = new google.maps.LatLng(item.latitude, item.longitude);

    map.setCenter(markerLocationLatLng);
    if (useCameraPose && item.cameraPose) {
        const cameraLocation = new google.maps.LatLng(item.cameraPose.lat, item.cameraPose.lng);
        panorama.setPosition(cameraLocation);
        const pov = { heading: 0, pitch: 0 };
        if (useHeading) pov.heading = item.cameraPose.headingDeg;
        if (usePitch) pov.pitch = item.cameraPose.pitchDeg;
        // Note: The 'roll' property is not supported by the Google Maps Street View API's setPov function.
        panorama.setPov(pov);

        if (loadPhotographerPov) {
            const photographerPov = panorama.getPhotographerPov();
            if (photographerPov && photographerPov.latLng) {
                const photographerLocation = photographerPov.latLng;
                map.setCenter(photographerLocation);
                panorama.setPosition(photographerLocation);
            }
        }
    } else {
        panorama.setPosition(markerLocationLatLng);
        panorama.setPov({ heading: 0, pitch: 0 });
    }
    panorama.setZoom(0);

    if (currentOverlayOrMarker) {
        currentOverlayOrMarker.setMap(null);
    }

    currentOverlayOrMarker = new ArrowMarkerOverlay(markerLocationLatLng, item.ObservationID);
    currentOverlayOrMarker.setMap(panorama);

    document.getElementById('infoTrackId').textContent = `Track ID: ${item.TrackID || 'N/A'}`;
    document.getElementById('infoObservationId').textContent = `Observation ID: ${item.ObservationID || 'N/A'}`;
    document.getElementById('infoLatLon').textContent = `Point Latitude, Longitude (Marker Location): ${item.latitude.toFixed(7)}, ${item.longitude.toFixed(7)}`;
    document.getElementById('infoCaptureTimestamp').textContent = `Capture Timestamp: ${item.captureTimestamp || 'N/A'}`;
    if (item.cameraPose) {
        const cp = item.cameraPose;
        document.getElementById('infoCameraPose').textContent =
            `Camera Pose (Lat, Lng, Alt, Hdg, Ptch): ${cp.lat}, ${cp.lng}, ${cp.altMeters}, ${cp.headingDeg}, ${cp.pitchDeg}`;
    } else {
         document.getElementById('infoCameraPose').textContent = `Camera Pose: N/A`;
    }

    const mapUrlElement = document.getElementById('infoMapUrl');
    if (item.mapUrl) {
        mapUrlElement.href = item.mapUrl;
        mapUrlElement.textContent = item.mapUrl;
        mapUrlElement.parentElement.style.display = 'block';
    } else {
        mapUrlElement.parentElement.style.display = 'none';
    }
}

function initMap() {
    ArrowMarkerOverlay = class ArrowMarkerOverlay extends google.maps.OverlayView {
        constructor(position, observationId) {
            super();
            this.position = position;
            this.observationId = observationId;
            this.containerDiv = null;
        }
        onAdd() {
            this.containerDiv = document.createElement("div");
            this.containerDiv.className = "arrow-marker-container";
            const label = document.createElement("div");
            label.className = "arrow-marker-label";
            label.textContent = this.observationId;
            this.containerDiv.appendChild(label);
            const arrowWrapper = document.createElement("div");
            arrowWrapper.className = "enhanced-arrow";
            const arrowMain = document.createElement("div");
            arrowMain.className = "enhanced-arrow-main";
            arrowWrapper.appendChild(arrowMain);
            const arrowSide = document.createElement("div");
            arrowSide.className = "enhanced-arrow-side";
            arrowWrapper.appendChild(arrowSide);
            this.containerDiv.appendChild(arrowWrapper);
            this.getPanes().overlayMouseTarget.appendChild(this.containerDiv);
        }
        draw() {
            const pixelPosition = this.getProjection().fromLatLngToDivPixel(this.position);
            if (pixelPosition) {
                this.containerDiv.style.left = pixelPosition.x + "px";
                this.containerDiv.style.top = pixelPosition.y + "px";
                this.containerDiv.style.display = "flex";
            } else {
                this.containerDiv.style.display = "none";
            }
        }
        onRemove() {
            if (this.containerDiv) {
                this.containerDiv.parentNode.removeChild(this.containerDiv);
                this.containerDiv = null;
            }
        }
    }

    const initialCenter = { lat: 45.5017, lng: -73.5673 }; // Default to Montreal

    map = new google.maps.Map(document.getElementById("map"), {
        center: initialCenter,
        zoom: 16,
        streetViewControl: true,
    });

    panorama = new google.maps.StreetViewPanorama(
        document.getElementById('pano'), {
            position: initialCenter,
            pov: { heading: 0, pitch: 0 },
            zoom: 0,
            streetViewControl: true,
            fullscreenControl: true,
            addressControl: false,
            panControl: true,
            zoomControl: true,
            motionTracking: false,
            motionTrackingControl: true,
            disableDefaultUI: false,
            clickToGo: true
        });
    
    map.setStreetView(panorama);

    const takePhotoButton = document.getElementById('takePhotoButton');
    const photoModal = document.getElementById('photo-modal');
    const staticImage = document.getElementById('static-streetview-image');
    const closeModal = document.getElementById('close-modal');

    takePhotoButton.addEventListener('click', () => {
        if (!dataset || dataset.length === 0) return;
        const item = dataset[currentItemIndex];
        const location = { lat: item.latitude, lng: item.longitude };
        const heading = item.cameraPose ? item.cameraPose.headingDeg : 0;
        const fov = 120;
        const imageUrl = `https://maps.googleapis.com/maps/api/streetview?size=640x480&location=${location.lat},${location.lng}&heading=${heading}&fov=${fov}&pitch=0&key=${API_KEY}`;
        staticImage.src = imageUrl;
        photoModal.style.display = 'flex';
    });

    closeModal.addEventListener('click', () => {
        photoModal.style.display = 'none';
    });

    photoModal.addEventListener('click', (e) => {
        if (e.target === photoModal) {
            photoModal.style.display = 'none';
        }
    });

    const useCameraPoseToggle = document.getElementById('useCameraPoseToggle');
    const cameraPoseControls = document.getElementById('camera-pose-controls');
    const useHeadingToggle = document.getElementById('useHeadingToggle');
    const usePitchToggle = document.getElementById('usePitchToggle');
    const useRollToggle = document.getElementById('useRollToggle');
    const loadPhotographerPovToggle = document.getElementById('loadPhotographerPovToggle');

    useCameraPoseToggle.addEventListener('change', (event) => {
        useCameraPose = event.target.checked;
        cameraPoseControls.style.display = useCameraPose ? 'flex' : 'none';
        displayCurrentItem();
    });

    useHeadingToggle.addEventListener('change', (event) => {
        useHeading = event.target.checked;
        displayCurrentItem();
    });

    usePitchToggle.addEventListener('change', (event) => {
        usePitch = event.target.checked;
        displayCurrentItem();
    });

    useRollToggle.addEventListener('change', (event) => {
        useRoll = event.target.checked;
        // No need to call displayCurrentItem() as roll is not used in setPov.
    });

    loadPhotographerPovToggle.addEventListener('change', (event) => {
        loadPhotographerPov = event.target.checked;
        displayCurrentItem();
    });

    document.getElementById('prevButton').addEventListener('click', () => {
        currentItemIndex = (currentItemIndex - 1 + dataset.length) % dataset.length;
        displayCurrentItem();
    });

    document.getElementById('nextButton').addEventListener('click', () => {
        currentItemIndex = (currentItemIndex + 1) % dataset.length;
        displayCurrentItem();
    });

    loadData();
}