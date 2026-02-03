/**
 * Generates the HTML content for the User Guide modal dynamically based on the configuration.
 * @returns {string} HTML string for the guide.
 */
function generateGuideHtml() {
  const isSample = DATASET === 'SAMPLE';
  const locationType = isSample ? 'City' : 'Country';
  const locationTypeLower = locationType.toLowerCase();
  
  // Example dataset name for explanation
  const exampleLocation = isSample ? 'London, United Kingdom' : 'United Kingdom';
  const exampleDataset = isSample ? 'places_insights___gb___sample' : 'places_insights___gb';

  return `
    <h2>1. Introduction</h2>
    <p>
      Welcome to the Places Insights Demo! This interactive web application is designed to help you explore and visualize Google's rich geospatial data without needing to write any code. Using a simple interface, you can define search areas on a map, apply powerful filters, and get aggregated insights directly from Google BigQuery, displayed visually on Google Maps.
    </p>
    <p>
      This guide will walk you through all the features of the application, from getting started to running advanced queries.
    </p>

    <h2>2. Getting Started</h2>
    <p>
      Before you can run a query, there are two initial steps you must complete.
    </p>
    <h3>Step 1: Select a ${locationType}</h3>
    <p>
      When you first load the application, you will be greeted by a modal window prompting you to select a ${locationTypeLower}.
    </p>
    <ul>
      <li><strong>Why is this important?</strong> The ${locationTypeLower} you choose determines which BigQuery dataset your queries will run against (e.g., selecting "${exampleLocation}" targets the <code>${exampleDataset}</code> dataset).</li>
      <li><strong>Action:</strong> Choose a ${locationTypeLower} from the dropdown menu and click <strong>Show Map</strong>.</li>
    </ul>

    <h3>Step 2: Authorize with Google</h3>
    <p>
      Once the map loads, you will see a control sidebar on the left. To run queries, you must grant the application permission to use your Google account.
    </p>
    <ul>
      <li><strong>Why is this important?</strong> This is a purely client-side application. It runs queries in BigQuery on your behalf, and the costs associated with those queries are billed to your Google Cloud project. Authorization is required to securely link your actions in the browser to your BigQuery account.</li>
      <li><strong>Action:</strong> Click the green <strong>Authorize with Google</strong> button and follow the prompts in the Google sign-in window. Once successful, the button will change to <strong>Sign Out</strong> and the status message will turn green.</li>
    </ul>

    <h2>3. Defining Your Search Area (Demo Types)</h2>
    <p>
      The "Demo Type" dropdown is the primary way to define the geographic area for your search.
    </p>
    <h3>A. Circle Search</h3>
    <p>
      This is the simplest search method, ideal for analyzing the area around a specific point.
    </p>
    <ol>
      <li>Select <strong>Circle Search</strong> from the "Demo Type" dropdown.</li>
      <li>Set a <strong>Radius (meters)</strong> in the input box.</li>
      <li><strong>Click anywhere on the map.</strong> A blue circle will appear, defining your search area. Clicking a new location will move the circle.</li>
    </ol>

    <h3>B. Polygon Search</h3>
    <p>
      This mode allows you to define a custom, multi-sided search area. You can do this in two ways:
    </p>
    <ul>
      <li><strong>By Drawing:</strong>
        <ol>
          <li>Select <strong>Polygon Search</strong> from the "Demo Type" dropdown.</li>
          <li>Click the <strong>Start Drawing</strong> button. Your cursor will turn into a crosshair.</li>
          <li>Click on the map to place the corners (vertices) of your polygon.</li>
          <li>When you are done, click the <strong>Finish Drawing</strong> button. An editable blue polygon will appear. You can drag the corners or edges to refine the shape.</li>
          <li>Click <strong>Clear Polygon</strong> to start over.</li>
        </ol>
      </li>
      <li><strong>By Pasting WKT:</strong>
        <ol>
          <li>If you have a polygon in Well-Known Text (WKT) format (e.g., <code>POLYGON((lng lat, ...))</code>), you can paste it directly into the <strong>Polygon (WKT)</strong> text area. The map will automatically draw the shape.</li>
          <li>Conversely, as you draw or edit a polygon on the map, its WKT representation will automatically appear in the text area.</li>
        </ol>
      </li>
    </ul>

    <h3>C. Region Search</h3>
    <p>
      This powerful mode allows you to search by administrative names like cities, states, or postal codes instead of drawing on the map.
    </p>
    <ol>
      <li>Select <strong>Region Search</strong> from the "Demo Type" dropdown.</li>
      <li>Choose a <strong>Region Type</strong> from the dropdown. This list is dynamically populated based on the selected ${locationTypeLower}.</li>
      <li>Enter a name in the <strong>Region Name(s)</strong> input box (e.g., "London").</li>
      <li><strong>(Optional) Add Multiple Regions:</strong> To search across several regions at once, click the <code>+</code> button after typing each name.</li>
    </ol>

    <h3>D. Route Search</h3>
    <p>
      This mode is designed for analyzing a corridor along a driving route.
    </p>
    <ol>
      <li>Select <strong>Route Search</strong> from the "Demo Type" dropdown.</li>
      <li>In the <strong>Origin</strong> input, start typing an address or place name and select a location from the autocomplete suggestions.</li>
      <li>Do the same for the <strong>Destination</strong> input.</li>
      <li>Set a <strong>Radius (meters)</strong> to define the buffer around the route.</li>
    </ol>

    <h3>E. Places Count Per H3 (Function)</h3>
    <p>
      This advanced mode uses BigQuery's server-side functions to generate high-performance density maps.
    </p>
    <ul>
      <li><strong>Low Counts:</strong> Unlike standard aggregation, this mode can return counts lower than 5 (including 0).</li>
      <li><strong>Sample Places:</strong> This mode returns sample Place IDs. <strong>Click on any hexagon</strong> on the map to load markers for up to 20 sample places in that cell. Clicking a marker will reveal full place details.</li>
      <li><strong>Limitations:</strong> Brand filters and Opening Hours are not supported in this mode.</li>
    </ul>

    <h2>4. Refining Your Search with Filters</h2>
    <p>
      The filter sections are collapsible; click on any filter title to expand it.
    </p>
    <ul>
      <li><strong>Included Place Types:</strong> Start typing a place category (e.g., <code>restaurant</code>, <code>park</code>) and click a suggestion to add it as a tag.</li>
      <li><strong>Match Primary Type Only:</strong> Check this box to search strictly for places where the selected type is their <em>primary</em> classification (e.g., finding a "Restaurant" that is primarily a restaurant, not a hotel with a restaurant).</li>
      <li><strong>Business Status:</strong> Filter places by their operational status (Operational, Closed Temporarily, Closed Permanently, or Any). Default is <strong>Operational</strong>.</li>
      <li><strong>Attribute Filters:</strong> Set min/max ratings or select checkboxes for amenities (e.g., "Offers Delivery").</li>
      <li><strong>Opening Hours:</strong> Select a <strong>Day of Week</strong> and time window (Not available in H3 Function mode).</li>
      <li><strong>Brand Filters (US Only):</strong> Filter by Brand Category or Brand Name (Not available in H3 Function mode).</li>
    </ul>

    <h2>5. Choosing Your Visualization</h2>
    <ul>
      <li><strong>Simple Count (Default):</strong> Results are displayed as numbers in a pop-up window.</li>
      <li><strong>H3 Density Map:</strong> Check the <strong>Show H3 Density Map</strong> box to see a heatmap. Use the <strong>H3 Resolution</strong> slider to change the cell size. (This is always enabled in H3 Function mode).</li>
    </ul>

    <h2>6. Running a Query and Managing the App</h2>
    <ul>
        <li><strong>Run Search:</strong> Click the blue <strong>Run Search</strong> button to execute the query.</li>
        <li><strong>View/Copy Query:</strong> After running a query, click <strong>View Query</strong> to see the SQL code. You can copy this SQL to run it directly in the BigQuery console.</li>
        <li><strong>Change ${locationType}:</strong> Click <strong>Change ${locationType}</strong> to restart with a different dataset.</li>
    </ul>
  `;
}