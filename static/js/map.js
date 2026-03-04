// Initialize the map and set the initial view to the Netherlands
const map = L.map('map').setView([52.1326, 5.2913], 8);

// Add standard OpenStreetMap as the base layer
const baseLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
}).addTo(map);

// ---------------------------------------------------------
// Integrate PDOK Real-time WMS Datasets
// ---------------------------------------------------------

// Example 1: BRP Gewaspercelen (Crop Parcels) via PDOK WMS
const brpLayer = L.tileLayer.wms('https://service.pdok.nl/rvo/brp/wms/v1_0?', {
    layers: 'gewaspercelen',
    format: 'image/png',
    transparent: true,
    attribution: 'Data: &copy; <a href="https://www.pdok.nl/">PDOK</a> / RVO'
});

// Example 2: Kadastrale Kaart (Cadastral Parcels) via PDOK WMS
const kadasterLayer = L.tileLayer.wms('https://service.pdok.nl/kadaster/kadastralekaart/wms/v5_0?', {
    layers: 'kadastralekaart',
    format: 'image/png',
    transparent: true,
    attribution: 'Data: &copy; <a href="https://www.pdok.nl/">PDOK</a> / Kadaster'
});

// Example 3: Natura 2000 Areas via PDOK WMS
const natura2000Layer = L.tileLayer.wms('https://service.pdok.nl/minez/natura2000/wms/v1_0?', {
    layers: 'natura2000',
    format: 'image/png',
    transparent: true,
    attribution: 'Data: &copy; <a href="https://www.pdok.nl/">PDOK</a> / MinEZK'
});

// ---------------------------------------------------------
// Add Layer Controls (Requirement: switch map layers on and off)
// ---------------------------------------------------------

// Define base maps (radio buttons - only one active at a time)
const baseMaps = {
    "OpenStreetMap": baseLayer
};

// Define overlay maps (checkboxes - multiple can be active)
const overlayMaps = {
    "BRP Crop Parcels (Gewaspercelen)": brpLayer,
    "Cadastral Parcels (Kadaster)": kadasterLayer,
    "Natura 2000 Areas": natura2000Layer
};

// Add the control to the map UI
L.control.layers(baseMaps, overlayMaps, { collapsed: false }).addTo(map);

// ---------------------------------------------------------
// Example: Interacting with the Backend API
// ---------------------------------------------------------

// Fetching data from the Flask proxy route to demonstrate backend connection
fetch('/api/proxy/pdok_example')
    .then(response => response.json())
    .then(data => {
        // Log the backend response to the console for debugging
        console.log("Backend connection successful:", data.message);
    })
    .catch(error => {
        // Handle any errors that occur during the fetch process
        console.error("Error connecting to backend:", error);
    });