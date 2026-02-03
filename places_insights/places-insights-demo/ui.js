// Copyright 2026 Google LLC
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     https://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

// --- UI HELPERS ---

/**
 * Converts a string to Title Case.
 * @param {string} str The string to convert.
 * @returns {string} The Title Cased string.
 */
function toTitleCase(str) {
  if (!str) return '';
  return str.toLowerCase().split(' ').map(word => {
    return word.charAt(0).toUpperCase() + word.slice(1);
  }).join(' ');
}

/**
 * Resets the sidebar UI to a specific mode's default state.
 * Clears input values and toggles the appropriate control sections.
 * @param {string} targetMode The demo mode to switch to (e.g., 'circle-search'). Defaults to 'circle-search'.
 */
function resetSidebarUI(targetMode = 'circle-search') {
    const select = document.getElementById('demo-type-select');
    if (select.value !== targetMode) {
        select.value = targetMode;
    }

    // Map modes to their control container IDs
    const modeToControls = {
        'circle-search': 'circle-search-controls',
        'h3-function': 'circle-search-controls', // H3 function uses circle inputs
        'polygon-search': 'polygon-search-controls',
        'region-search': 'region-search-controls',
        'route-search': 'route-search-controls'
    };

    const activeControlId = modeToControls[targetMode];

    // Hide all control sections first
    ['circle-search-controls', 'polygon-search-controls', 'region-search-controls', 'route-search-controls']
        .forEach(id => {
            const el = document.getElementById(id);
            if (id === activeControlId) {
                el.classList.remove('hidden');
            } else {
                el.classList.add('hidden');
            }
        });

    // Reset Input Values
    // Set default radius to 5000m for H3 Function, 1000m for others
    if (targetMode === 'h3-function') {
        document.getElementById('radius-input').value = '5000';
    } else {
        document.getElementById('radius-input').value = '1000';
    }

    document.getElementById('wkt-input').value = '';
    document.getElementById('wkt-input').classList.remove('invalid');
    document.getElementById('region-name-input').value = '';
    document.getElementById('selected-regions-list').innerHTML = '';
    document.getElementById('route-radius-input').value = '100';
    
    // Reset Filters
    document.getElementById('place-type-input').value = '';
    document.getElementById('selected-types-list').innerHTML = '';
    // Reset Type Checkbox
    document.getElementById('primary-type-checkbox').checked = false;

    document.getElementById('min-rating-input').value = '';
    document.getElementById('max-rating-input').value = '';
    document.getElementById('business-status-select').value = 'OPERATIONAL';
    document.querySelectorAll('.attribute-filter').forEach(cb => cb.checked = false);
    
    // Reset Time
    const daySelect = document.getElementById('day-of-week-select');
    const startInput = document.getElementById('start-time-input');
    const endInput = document.getElementById('end-time-input');
    daySelect.value = '';
    startInput.value = '';
    endInput.value = '';
    startInput.disabled = true;
    endInput.disabled = true;

    // Reset Brands
    document.getElementById('brand-category-select').value = '';
    document.getElementById('brand-name-input').value = '';
    document.getElementById('selected-brands-list').innerHTML = '';

    // Reset H3 Controls (Default State)
    // Specific overrides for 'h3-function' are handled in map.js after this call.
    const h3Toggle = document.getElementById('h3-density-toggle');
    h3Toggle.checked = false;
    h3Toggle.disabled = false;
    
    document.getElementById('h3-resolution-controls').classList.add('hidden');
    const h3Slider = document.getElementById('h3-resolution-slider');
    h3Slider.max = '12'; 
    h3Slider.value = '8';
    document.getElementById('h3-resolution-value').textContent = '8';

    // Close Accordions
    document.querySelectorAll('.collapsible-fieldset').forEach(fs => fs.classList.remove('is-open'));
}


/**
 * A generic function to add a removable "tag" to a list.
 */
function addTag(text, listElement) {
    if ([...listElement.querySelectorAll('span')].some(el => el.textContent === text)) return;

    const tag = document.createElement('li');
    tag.className = 'selected-type-tag';
    const textSpan = document.createElement('span');
    textSpan.textContent = text;
    const removeBtn = document.createElement('button');
    removeBtn.className = 'remove-tag-btn';
    removeBtn.innerHTML = '&times;';
    removeBtn.onclick = () => {
        tag.remove();
        invalidateQueryState(); // Invalidate when a tag is removed
    };

    tag.appendChild(textSpan);
    tag.appendChild(removeBtn);
    listElement.appendChild(tag);
}

/**
 * Initializes the place type autocomplete functionality.
 */
function initializeAutocomplete(inputElement) {
    const suggestionsContainer = document.getElementById('autocomplete-suggestions');
    const selectedTypesList = document.getElementById('selected-types-list');

    inputElement.addEventListener('input', () => {
        const query = inputElement.value.toLowerCase();
        suggestionsContainer.innerHTML = '';
        if (!query) return;

        const filteredTypes = PLACE_TYPES
            .filter(t => t.toLowerCase().includes(query))
            .sort((a, b) => {
                const aL = a.toLowerCase(), bL = b.toLowerCase();
                const sA = (aL === query) ? 1 : (aL.startsWith(query) ? 2 : 3);
                const sB = (bL === query) ? 1 : (bL.startsWith(query) ? 2 : 3);
                if (sA !== sB) return sA - sB;
                return a.localeCompare(b);
            }).slice(0, 10);

        filteredTypes.forEach(type => {
            const item = document.createElement('div');
            item.className = 'suggestion-item';
            item.textContent = type;
            item.addEventListener('click', () => {
                addTag(type, selectedTypesList);
                inputElement.value = '';
                suggestionsContainer.innerHTML = '';
                invalidateQueryState(); // Invalidate on add
            });
            suggestionsContainer.appendChild(item);
        });
    });

    document.addEventListener('click', e => {
        if (!e.target.closest('.autocomplete-container')) {
            suggestionsContainer.innerHTML = '';
        }
    });
}


/**
 * Populates the brand category dropdown from the loaded brand data.
 */
function populateBrandCategories() {
    const categorySelect = document.getElementById('brand-category-select');
    const categories = [...new Set(BRANDS_DATA.map(brand => brand.category))].sort();
    categories.forEach(category => {
        const option = document.createElement('option');
        option.value = category;
        option.textContent = category;
        categorySelect.appendChild(option);
    });
}

/**
 * Initializes the brand name autocomplete functionality for multi-selection.
 */
function initializeBrandAutocomplete() {
    const inputElement = document.getElementById('brand-name-input');
    const categorySelect = document.getElementById('brand-category-select');
    const suggestionsContainer = document.getElementById('brand-autocomplete-suggestions');
    const selectedBrandsList = document.getElementById('selected-brands-list');

    const updateSuggestions = () => {
        const query = inputElement.value.toLowerCase();
        const category = categorySelect.value;
        suggestionsContainer.innerHTML = '';
        if (!query) return;

        const filteredBrands = BRANDS_DATA
            .filter(brand => !category || brand.category === category)
            .filter(brand => brand.name.toLowerCase().includes(query))
            .slice(0, 10);

        filteredBrands.forEach(brand => {
            const item = document.createElement('div');
            item.className = 'suggestion-item';
            item.textContent = brand.name;
            item.addEventListener('click', () => {
                addTag(brand.name, selectedBrandsList);
                inputElement.value = '';
                suggestionsContainer.innerHTML = '';
                invalidateQueryState(); // Invalidate on add
            });
            suggestionsContainer.appendChild(item);
        });
    };

    inputElement.addEventListener('input', updateSuggestions);

    categorySelect.addEventListener('change', () => {
        inputElement.value = '';
        suggestionsContainer.innerHTML = '';
    });
}


/**
 * Converts a google.maps.Polygon object to a WKT string and updates the textarea.
 */
function updateWktFromPolygon(polygon) {
    const path = polygon.getPath().getArray();
    const wktInput = document.getElementById('wkt-input');
    if (path.length < 3) {
        wktInput.value = '';
        return;
    }
    let wkt = "POLYGON((";
    wkt += path.map(p => `${p.lng()} ${p.lat()}`).join(', ');
    wkt += `, ${path[0].lng()} ${path[0].lat()}`;
    wkt += "))";
    wktInput.value = wkt;
    wktInput.classList.remove('invalid');
}

/**
 * Handles user input in the WKT textarea, parsing it and drawing a polygon on the map.
 */
function handleWktInputChange(e) {
    const wktString = e.target.value;
    const wktInput = e.target;
    try {
        const coords = wktString.match(/\(\((.*)\)\)/)[1].split(',').map(c => {
            const parts = c.trim().split(' ');
            return { lng: parseFloat(parts[0]), lat: parseFloat(parts[1]) };
        });

        if (coords.length < 4 || isNaN(coords[0].lat)) throw new Error("Invalid coordinate format");
        
        clearAllOverlays();

        searchPolygon = new google.maps.Polygon({
            paths: coords,
            editable: true, draggable: true, fillColor: '#5599FF', fillOpacity: 0.3,
            strokeColor: '#0000FF', strokeWeight: 2, map: map
        });

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

        wktInput.classList.remove('invalid');
    } catch (err) {
        wktInput.classList.add('invalid');
    }
}

// --- STATUS & AUTH UI HELPERS ---

/**
 * Updates the status message in the sidebar.
 * @param {string} message The text to display.
 * @param {string} type 'info', 'success', or 'error'.
 */
function updateStatus(message, type = 'info') {
  const statusDisplay = document.getElementById('status');
  if (statusDisplay) {
    statusDisplay.textContent = message;
    statusDisplay.className = type;
  }
}

/**
 * Updates the UI to a "signed-in" state.
 */
function setSignedInUi() {
  userSignedIn = true;
  document.getElementById('auth-button').textContent = 'Sign Out';
  document.getElementById('run-query-btn').disabled = false;
  updateStatus('Authorized successfully.', 'success');
}

/**
 * Updates the UI to a "signed-out" state.
 */
function resetSignedInUi() {
  userSignedIn = false;
  document.getElementById('auth-button').textContent = 'Authorize with Google';
  document.getElementById('run-query-btn').disabled = true;
  accessToken = null;
  updateStatus('Please authorize to run a query.');
}