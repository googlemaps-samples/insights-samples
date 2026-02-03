// --- CONFIGURATION CONSTANTS ---
// These are loaded from config.js and treated as constants throughout the app.
const config = window.APP_CONFIG || {};
const GCP_PROJECT_ID = config.GCP_PROJECT_ID || '';
const OAUTH_CLIENT_ID = config.OAUTH_CLIENT_ID || '';
const MAPS_API_KEY = config.MAPS_API_KEY || '';
const DATASET = config.DATASET || 'FULL';
const BQ_SCOPES = 'https://www.googleapis.com/auth/bigquery';

// --- APPLICATION STATE ---
// Holds the name of the country/city selected in the initial modal.
let selectedCountryName = '';

// Maps full country names to their two-letter codes for BigQuery table names (FULL Dataset).
const COUNTRY_CODES = {
  'Australia': 'au', 'Brazil': 'br', 'Canada': 'ca', 'France': 'fr', 'Germany': 'de',
  'India': 'in', 'Indonesia': 'id', 'Italy': 'it', 'Japan': 'jp', 'Mexico': 'mx',
  'Spain': 'es', 'Switzerland': 'ch', 'United Kingdom': 'gb', 'United States': 'us'
};

// Maps sample city locations to their country codes (SAMPLE Dataset).
const SAMPLE_LOCATIONS = {
  'Sydney, Australia': 'au',
  'Sao Paulo, Brazil': 'br',
  'Toronto, Canada': 'ca',
  'Paris, France': 'fr',
  'Berlin, Germany': 'de',
  'Mumbai, India': 'in',
  'Jakarta, Indonesia': 'id',
  'Rome, Italy': 'it',
  'Tokyo, Japan': 'jp',
  'Mexico City, Mexico': 'mx',
  'Madrid, Spain': 'es',
  'Zurich, Switzerland': 'ch',
  'London, United Kingdom': 'gb',
  'New York City, United States': 'us'
};

// Holds the data from brands.json, loaded at startup.
let BRANDS_DATA = [];
// Configuration for country-specific region search fields, now with explicit types.
const REGION_FIELD_CONFIG = {
  'au': [
    { label: 'State / Territory', field: 'administrative_area_level_1_name', type: 'STRING' },
    { label: 'City / Locality', field: 'locality_names', type: 'ARRAY' },
    { label: 'Postal Code', field: 'postal_code_names', type: 'ARRAY' }
  ],
  'br': [
    { label: 'State', field: 'administrative_area_level_1_name', type: 'STRING' },
    { label: 'City / Municipality', field: 'administrative_area_level_2_name', type: 'STRING' },
    { label: 'Locality', field: 'locality_names', type: 'ARRAY' },
    { label: 'Postal Code', field: 'postal_code_names', type: 'ARRAY' },
    { label: 'Neighborhood', field: 'sublocality_level_1_names', type: 'ARRAY' }
  ],
  'ca': [
    { label: 'Province / Territory', field: 'administrative_area_level_1_name', type: 'STRING' },
    { label: 'City / Locality', field: 'locality_names', type: 'ARRAY' },
    { label: 'Neighborhood', field: 'neighborhood_names', type: 'ARRAY' },
    { label: 'Postal Code', field: 'postal_code_names', type: 'ARRAY' }
  ],
  'de': [
    { label: 'State', field: 'administrative_area_level_1_name', type: 'STRING' },
    { label: 'District', field: 'administrative_area_level_3_name', type: 'STRING' },
    { label: 'City / Locality', field: 'locality_names', type: 'ARRAY' },
    { label: 'Postal Code', field: 'postal_code_names', type: 'ARRAY' },
    { label: 'Sublocality / Borough', field: 'sublocality_level_1_names', type: 'ARRAY' }
  ],
  'es': [
    { label: 'Autonomous Community', field: 'administrative_area_level_1_name', type: 'STRING' },
    { label: 'Province', field: 'administrative_area_level_2_name', type: 'STRING' },
    { label: 'City / Locality', field: 'locality_names', type: 'ARRAY' },
    { label: 'Neighborhood', field: 'neighborhood_names', type: 'ARRAY' },
    { label: 'Postal Code', field: 'postal_code_names', type: 'ARRAY' }
  ],
  'fr': [
    { label: 'Region', field: 'administrative_area_level_1_name', type: 'STRING' },
    { label: 'Department', field: 'administrative_area_level_2_name', type: 'STRING' },
    { label: 'City / Locality', field: 'locality_names', type: 'ARRAY' },
    { label: 'Postal Code', field: 'postal_code_names', type: 'ARRAY' },
    { label: 'Sublocality', field: 'sublocality_level_1_names', type: 'ARRAY' }
  ],
  'gb': [
    { label: 'Country', field: 'administrative_area_level_1_name', type: 'STRING' },
    { label: 'City / Locality', field: 'locality_names', type: 'ARRAY' },
    { label: 'Postal Town', field: 'postal_town_names', type: 'ARRAY' },
    { label: 'Postal Code', field: 'postal_code_names', type: 'ARRAY' }
  ],
  'in': [
    { label: 'State', field: 'administrative_area_level_1_name', type: 'STRING' },
    { label: 'District', field: 'administrative_area_level_3_name', type: 'STRING' },
    { label: 'City / Locality', field: 'locality_names', type: 'ARRAY' },
    { label: 'Postal Code (PIN)', field: 'postal_code_names', type: 'ARRAY' },
    { label: 'Sublocality', field: 'sublocality_level_1_names', type: 'ARRAY' }
  ],
  'id': [
    { label: 'Province', field: 'administrative_area_level_1_name', type: 'STRING' },
    { label: 'Regency / City', field: 'administrative_area_level_2_name', type: 'STRING' },
    { label: 'District', field: 'administrative_area_level_3_name', type: 'STRING' },
    { label: 'Village / Kelurahan', field: 'administrative_area_level_4_name', type: 'STRING' },
    { label: 'City / Locality', field: 'locality_names', type: 'ARRAY' },
    { label: 'Postal Code', field: 'postal_code_names', type: 'ARRAY' }
  ],
  'it': [
    { label: 'Region', field: 'administrative_area_level_1_name', type: 'STRING' },
    { label: 'Province', field: 'administrative_area_level_2_name', type: 'STRING' },
    { label: 'Municipality (Comune)', field: 'administrative_area_level_3_name', type: 'STRING' },
    { label: 'Postal Code', field: 'postal_code_names', type: 'ARRAY' }
  ],
  'jp': [
    { label: 'Prefecture', field: 'administrative_area_level_1_name', type: 'STRING' },
    { label: 'City / Locality', field: 'locality_names', type: 'ARRAY' },
    { label: 'Postal Code', field: 'postal_code_names', type: 'ARRAY' },
    { label: 'Sublocality', field: 'sublocality_level_1_names', type: 'ARRAY' }
  ],
  'mx': [
    { label: 'State', field: 'administrative_area_level_1_name', type: 'STRING' },
    { label: 'Municipality', field: 'administrative_area_level_2_name', type: 'STRING' },
    { label: 'City / Locality', field: 'locality_names', type: 'ARRAY' },
    { label: 'Postal Code', field: 'postal_code_names', type: 'ARRAY' }
  ],
  'ch': [
    { label: 'Canton', field: 'administrative_area_level_1_name', type: 'STRING' },
    { label: 'District', field: 'administrative_area_level_2_name', type: 'STRING' },
    { label: 'Municipality / Locality', field: 'locality_names', type: 'ARRAY' },
    { label: 'Postal Code', field: 'postal_code_names', type: 'ARRAY' }
  ],
  'us': [
    { label: 'State', field: 'administrative_area_level_1_name', type: 'STRING' },
    { label: 'County', field: 'administrative_area_level_2_name', type: 'STRING' },
    { label: 'City / Locality', field: 'locality_names', type: 'ARRAY' },
    { label: 'Neighborhood', field: 'neighborhood_names', type: 'ARRAY' },
    { label: 'Postal Code', field: 'postal_code_names', type: 'ARRAY' }
  ]
};


// --- MAP & OVERLAY STATE ---
// References to Google Maps and deck.gl objects.
let map, searchCenter, searchCircle, searchPolygon, infoWindow, deckglOverlay;

// Route Search State
let originPlace = null, destinationPlace = null, routePolyline = null;

// --- DRAWING STATE ---
// Manages the custom polygon drawing process.
let isDrawing = false;
let polygonVertices = [];
let tempPolyline;

// --- AUTHENTICATION STATE ---
// Manages the user's sign-in status and access token.
let tokenClient, accessToken = null, userSignedIn = false;

// --- UI STATE ---
// Caches the content of guide.html to avoid re-fetching.
let guideContentHtml = null;
// Caches the last successfully executed query.
let lastExecutedQuery = null;
// Tracks if mouse is hovering over an H3 cell to prevent map click conflicts
let isHoveringH3 = false;