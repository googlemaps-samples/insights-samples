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

// Maps Places API Types to their exact BigQuery Columns and Data Types
const REGION_TYPE_TO_BQ_COLUMN = {
  'administrative_area_level_1': { column: 'administrative_area_level_1_id', type: 'STRING' },
  'administrative_area_level_2': { column: 'administrative_area_level_2_id', type: 'STRING' },
  'administrative_area_level_3': { column: 'administrative_area_level_3_id', type: 'STRING' },
  'administrative_area_level_4': { column: 'administrative_area_level_4_id', type: 'STRING' },
  'administrative_area_level_5': { column: 'administrative_area_level_5_id', type: 'STRING' },
  'administrative_area_level_6': { column: 'administrative_area_level_6_id', type: 'STRING' },
  'administrative_area_level_7': { column: 'administrative_area_level_7_id', type: 'STRING' },
  'locality': { column: 'locality_ids', type: 'ARRAY' },
  'sublocality': { column: 'sublocality_level_1_ids', type: 'ARRAY' },
  'sublocality_level_1': { column: 'sublocality_level_1_ids', type: 'ARRAY' },
  'sublocality_level_2': { column: 'sublocality_level_2_ids', type: 'ARRAY' },
  'sublocality_level_3': { column: 'sublocality_level_3_ids', type: 'ARRAY' },
  'sublocality_level_4': { column: 'sublocality_level_4_ids', type: 'ARRAY' },
  'sublocality_level_5': { column: 'sublocality_level_5_ids', type: 'ARRAY' },
  'neighborhood': { column: 'neighborhood_ids', type: 'ARRAY' },
  'postal_code': { column: 'postal_code_ids', type: 'ARRAY' },
  'postal_town': { column: 'postal_town_ids', type: 'ARRAY' }
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