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

// --- MAIN APPLICATION ENTRY POINT ---

/**
 * Hides the "View Query" button and clears the last executed query state.
 * This is called whenever a search parameter is changed.
 */
function invalidateQueryState() {
    document.getElementById('view-query-btn').classList.add('hidden');
    lastExecutedQuery = null;
}

/**
 * Populates the country/city selection dropdown based on the configuration mode.
 */
function populateLocationSelect() {
    const select = document.getElementById("country-select");
    const title = document.getElementById("selector-title");
    const changeBtn = document.getElementById("change-country-btn");
    
    // Clear existing options (keep the default disabled one)
    while (select.options.length > 1) {
        select.remove(1);
    }

    if (DATASET === 'SAMPLE') {
        title.textContent = "Select a City for the Demo";
        if (changeBtn) changeBtn.textContent = "Change City";
        
        Object.keys(SAMPLE_LOCATIONS).sort().forEach(location => {
            const option = document.createElement("option");
            option.value = location;
            option.textContent = location;
            select.appendChild(option);
        });
    } else {
        // FULL dataset mode
        title.textContent = "Select a Country for the Demo";
        if (changeBtn) changeBtn.textContent = "Change Country";

        Object.keys(COUNTRY_CODES).sort().forEach(location => {
            const option = document.createElement("option");
            option.value = location;
            option.textContent = location;
            select.appendChild(option);
        });
    }
}

/**
 * Handles the initial start of the demo after a location is selected from the modal.
 */
function handleStartDemo() {
    selectedCountryName = document.getElementById("country-select").value;
    if (selectedCountryName) {
      document.getElementById("country-selector-modal").classList.add("hidden");
      document.getElementById("sidebar").classList.remove("hidden");
      
      const brandFilters = document.getElementById('brand-filters');
      // Logic for Brand Filters visibility
      let isUS = false;
      let countryCode;
      if (DATASET === 'SAMPLE') {
          countryCode = SAMPLE_LOCATIONS[selectedCountryName];
          isUS = countryCode === 'us';
      } else {
          countryCode = COUNTRY_CODES[selectedCountryName];
          isUS = selectedCountryName === 'United States';
      }

      if (isUS) {
        brandFilters.classList.remove('hidden');
      } else {
        brandFilters.classList.add('hidden');
      }

      // Restrict Region Autocomplete to the active country
      if (window.regionAutocomplete) {
          window.regionAutocomplete.includedRegionCodes = [countryCode];
      }

      startDemo(selectedCountryName);
    } else { 
      alert("Please select a location to begin."); 
    }
}

/**
 * Handles clicks on the "Change Country/City" button.
 */
function handleChangeCountryClick() {
    document.getElementById('country-selector-modal').classList.remove('hidden');
    document.getElementById('sidebar').classList.add('hidden');
    resetSidebarUI();
    clearAllOverlays(true);
    invalidateQueryState();
}

/**
 * Handles clicks on the "+" button to add a brand to the list.
 */
function handleAddBrandClick() {
    const brandInput = document.getElementById('brand-name-input');
    const brandList = document.getElementById('selected-brands-list');
    const brandName = brandInput.value.trim();

    if (brandName) {
        addTag(brandName, brandList); // Keep original case for brands
        brandInput.value = '';
        brandInput.focus();
        invalidateQueryState();
    }
}

/**
 * Generates the help HTML via help.js and displays the modal.
 */
function showHelpModal() {
    const guideModal = document.getElementById('guide-modal');
    const guideContent = document.getElementById('guide-content');

    // Use the function from help.js to generate fresh HTML based on current config
    try {
        guideContent.innerHTML = generateGuideHtml();
    } catch (error) {
        console.error(error);
        guideContent.innerHTML = '<p>Error: Could not load the user guide.</p>';
    }
    
    guideModal.classList.remove('hidden');
}

/**
 * Hides the specified modal.
 * @param {string} modalId The ID of the modal to hide.
 */
function hideModal(modalId) {
    document.getElementById(modalId).classList.add('hidden');
}

/**
 * Displays the last executed query in a modal.
 */
function showQueryModal() {
    if (lastExecutedQuery) {
        document.getElementById('query-content').textContent = lastExecutedQuery;
        document.getElementById('query-modal').classList.remove('hidden');
    } else {
        alert("No valid query has been executed yet.");
    }
}

/**
 * Copies the displayed SQL query to the clipboard.
 */
function handleCopyQueryClick() {
    const queryText = document.getElementById('query-content').textContent;
    const copyButton = document.getElementById('copy-query-btn');

    navigator.clipboard.writeText(queryText).then(() => {
        copyButton.textContent = 'Copied!';
        setTimeout(() => {
            copyButton.textContent = 'Copy SQL';
        }, 2000); // Revert text after 2 seconds
    }).catch(err => {
        console.error('Failed to copy text: ', err);
        alert('Failed to copy query to clipboard.');
    });
}


/**
 * Initializes the Place Autocomplete (New) web components for Region search.
 */
async function initializeRegionSearch() {
    const { PlaceAutocompleteElement } = await google.maps.importLibrary("places");
    const container = document.getElementById('region-autocomplete-container');

    const autocomplete = new PlaceAutocompleteElement();
    container.appendChild(autocomplete);

    autocomplete.addEventListener('gmp-select', async ({ placePrediction }) => {
        if (!placePrediction) return;
        invalidateQueryState();
        
        const place = placePrediction.toPlace();
        // Request the viewport field to properly frame the region on the map
        await place.fetchFields({ fields: ['id', 'displayName', 'types', 'location', 'viewport'] });
        
        let targetColumn = null;
        if (place.types) {
            for (const type of place.types) {
                if (REGION_TYPE_TO_BQ_COLUMN[type]) {
                    targetColumn = REGION_TYPE_TO_BQ_COLUMN[type];
                    break;
                }
            }
        }

        if (!targetColumn) {
            alert(`The selected place type is not supported as a search region. Please select a valid city, state, or neighborhood.`);
            autocomplete.inputValue = '';
            return;
        }

        if (place.location || place.viewport) {
            addRegionTag(place.displayName, place.id, targetColumn, place.location, place.viewport);
        } else {
            alert("Could not retrieve location for this place.");
        }
        
        autocomplete.inputValue = '';
    });
    
    window.regionAutocomplete = autocomplete;
}

/**
 * Initializes the Place Autocomplete (New) web components for route search.
 */
async function initializeRouteSearch() {
    const { PlaceAutocompleteElement } = await google.maps.importLibrary("places");
    
    const originContainer = document.getElementById('origin-input-container');
    const destinationContainer = document.getElementById('destination-input-container');

    const originAutocomplete = new PlaceAutocompleteElement();
    const destinationAutocomplete = new PlaceAutocompleteElement();

    originContainer.appendChild(originAutocomplete);
    destinationContainer.appendChild(destinationAutocomplete);

    originAutocomplete.addEventListener('gmp-select', async ({ placePrediction }) => {
        invalidateQueryState();
        const place = placePrediction.toPlace();
        await place.fetchFields({ fields: ['location'] });
        originPlace = place;
    });

    destinationAutocomplete.addEventListener('gmp-select', async ({ placePrediction }) => {
        invalidateQueryState();
        const place = placePrediction.toPlace();
        await place.fetchFields({ fields: ['location'] });
        destinationPlace = place;
    });
}


/**
 * Sets up the accordion functionality for collapsible fieldsets.
 */
function initializeAccordion() {
    const fieldsets = document.querySelectorAll('.collapsible-fieldset');
    fieldsets.forEach(fieldset => {
        const legend = fieldset.querySelector('legend');
        legend.addEventListener('click', () => {
            const wasOpen = fieldset.classList.contains('is-open');

            fieldsets.forEach(fs => fs.classList.remove('is-open'));

            if (!wasOpen) {
                fieldset.classList.add('is-open');
            }
        });
    });
}


/**
 * This function runs once the entire page, including all external scripts, has finished loading.
 */
window.onload = () => {
  // Populate the selector based on config
  populateLocationSelect();

  const elements = {
    sidebar: document.getElementById('sidebar'),
    authButton: document.getElementById('auth-button'),
    runQueryBtn: document.getElementById('run-query-btn'),
    viewQueryBtn: document.getElementById('view-query-btn'),
    copyQueryBtn: document.getElementById('copy-query-btn'),
    demoTypeSelect: document.getElementById('demo-type-select'),
    startButton: document.getElementById("start-demo-btn"),
    changeCountryBtn: document.getElementById('change-country-btn'),
    addBrandBtn: document.getElementById('add-brand-btn'),
    showHelpBtn: document.getElementById('show-help-btn'),
    guideModal: document.getElementById('guide-modal'),
    queryModal: document.getElementById('query-modal'),
    closeHelpBtn: document.querySelector('#guide-modal .close-modal-btn'),
    closeQueryBtn: document.querySelector('#query-modal .close-modal-btn'),
    h3Toggle: document.getElementById('h3-density-toggle'),
    h3Controls: document.getElementById('h3-resolution-controls'),
    h3Slider: document.getElementById('h3-resolution-slider'),
    h3Value: document.getElementById('h3-resolution-value'),
    wktInput: document.getElementById('wkt-input'),
    clearPolygonBtn: document.getElementById('clear-polygon-btn'),
    startDrawingBtn: document.getElementById('start-drawing-btn'),
    finishDrawingBtn: document.getElementById('finish-drawing-btn'),
    dayOfWeekSelect: document.getElementById('day-of-week-select'),
    startTimeInput: document.getElementById('start-time-input'),
    endTimeInput: document.getElementById('end-time-input')
  };

  // Central invalidation listener for any change within the sidebar.
  elements.sidebar.addEventListener('input', invalidateQueryState);

  elements.authButton.addEventListener('click', handleAuthClick);
  elements.runQueryBtn.addEventListener('click', runQuery);
  elements.viewQueryBtn.addEventListener('click', showQueryModal);
  elements.copyQueryBtn.addEventListener('click', handleCopyQueryClick);
  elements.startButton.addEventListener("click", handleStartDemo);
  elements.changeCountryBtn.addEventListener('click', handleChangeCountryClick);
  elements.addBrandBtn.addEventListener('click', handleAddBrandClick);
  elements.showHelpBtn.addEventListener('click', showHelpModal);
  elements.closeHelpBtn.addEventListener('click', () => hideModal('guide-modal'));
  elements.closeQueryBtn.addEventListener('click', () => hideModal('query-modal'));
  elements.guideModal.addEventListener('click', (e) => {
      if (e.target === elements.guideModal) hideModal('guide-modal');
  });
  elements.queryModal.addEventListener('click', (e) => {
      if (e.target === elements.queryModal) hideModal('query-modal');
  });
  elements.demoTypeSelect.addEventListener('change', handleDemoTypeChange);
  
  elements.h3Toggle.addEventListener('change', (e) => {
    elements.h3Controls.classList.toggle('hidden', !e.target.checked);
  });
  elements.h3Slider.addEventListener('input', (e) => {
    elements.h3Value.textContent = e.target.value;
  });
  
  elements.clearPolygonBtn.addEventListener('click', clearPolygon);
  elements.startDrawingBtn.addEventListener('click', startDrawing);
  elements.finishDrawingBtn.addEventListener('click', finishDrawing);
  
  // New: Event listener for opening hours filter
  elements.dayOfWeekSelect.addEventListener('change', (e) => {
    const daySelected = e.target.value !== '';
    elements.startTimeInput.disabled = !daySelected;
    elements.endTimeInput.disabled = !daySelected;
    if (!daySelected) {
      elements.startTimeInput.value = '';
      elements.endTimeInput.value = '';
    }
  });

  initializeIdentityServices();
  initializeAutocomplete(document.getElementById('place-type-input'));
  initializeRegionSearch();
  initializeRouteSearch();
  initializeAccordion();

  // Set initial state for time inputs
  elements.startTimeInput.disabled = true;
  elements.endTimeInput.disabled = true;
};