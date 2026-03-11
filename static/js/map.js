// Initialize the map, lock it to a high zoom level (15), and set a minimum zoom (14)
// This strictly prevents the map from zooming out to a level where PDOK hides the data
// Initialize the map, allowing users to zoom out to the whole country
const map = L.map('map', {
    center: [52.336, 4.653], // Haarlemmermeer
    zoom: 15,
    minZoom: 3
});

// Add standard OpenStreetMap as the base layer
const baseLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
}).addTo(map);

// ---------------------------------------------------------
// WMS Layers with standard settings
// ---------------------------------------------------------

// ---------------------------------------------------------
// 1. BRP Gewaspercelen (Crop Parcels) - Upgraded to OGC API Features
// ---------------------------------------------------------

// Create an empty GeoJSON layer to hold the dynamically downloaded vector parcels
const brpLayer = L.geoJSON(null, {
    style: function(feature) {
        return {
            color: '#d35400', // High contrast bright orange border for legal clarity
            weight: 3,
            dashArray: '5, 5', // Dashed line to represent property boundaries
            fillColor: '#e67e22',
            fillOpacity: 0.4 // Semi-transparent so underlying map remains visible
        };
    },
    // Automatically bind Turf.js calculations when each parcel polygon is loaded
    onEachFeature: function(feature, layer) {
        // Ensure Turf.js is loaded and working
        if (typeof turf !== 'undefined') {
            // Calculate exact area in square meters, then convert to hectares
            const areaSqM = turf.area(feature);
            const areaHa = (areaSqM / 10000).toFixed(2);
            
            // Extract crop attributes from the PDOK OGC API response
            const gewas = feature.properties.gewas || 'Unknown';
            const jaar = feature.properties.jaar || 'N/A';

            // Bind a popup with legally relevant data
            layer.bindPopup(`
                <div style="font-family: Arial, sans-serif;">
                    <h3 style="margin: 0 0 5px 0; color: #d35400;">BRP Crop Parcel</h3>
                    <b>Registration Year:</b> ${jaar}<br>
                    <b>Crop Type:</b> ${gewas}<br>
                    <b>Calculated Area:</b> ${areaHa} ha<br>
                    <hr style="margin: 5px 0;">
                    <small>Source: PDOK OGC API Features</small>
                </div>
            `);
        }
    }
});

// ---------------------------------------------------------
// Dynamic Network Request: Fetch parcels when map movement ends
// ---------------------------------------------------------
map.on('moveend', async function() {
    // Keep the zoom lock: prevent downloading data for the entire country
    if (map.getZoom() < 14) {
        brpLayer.clearLayers();
        return;
    }
    
    // Do not waste network resources if the user hasn't enabled this layer
    if (!map.hasLayer(brpLayer)) return;

    // Get the current map bounding box to request only visible parcels
    const bounds = map.getBounds();
    
    // OGC API format: min_lon, min_lat, max_lon, max_lat
    const bbox = `${bounds.getWest()},${bounds.getSouth()},${bounds.getEast()},${bounds.getNorth()}`;
    
    // Construct the modern OGC API Features URL (RESTful JSON, highly stable)
    // CORRECTED OGC API URL: The path is 'gewaspercelen' and collection is 'brpgewas'
    const apiUrl = `https://api.pdok.nl/rvo/gewaspercelen/ogc/v1/collections/brpgewas/items?bbox=${bbox}&limit=1000`;

    try {
        // Fetch data explicitly requesting GeoJSON format
        const response = await fetch(apiUrl, {
            headers: { 'Accept': 'application/geo+json' }
        });
        
        const data = await response.json();
        
        // Clear old parcels from previous view and draw the new ones
        brpLayer.clearLayers();
        
        // Verify that features were actually returned before adding them
        if (data.features && data.features.length > 0) {
            brpLayer.addData(data);
        }
    } catch (error) {
        console.error("Failed to download vector data via OGC API:", error);
    }
});

// Trigger a download immediately when the user toggles the layer ON
map.on('overlayadd', function(e) {
    if (e.name === "BRP Crop Parcels") {
        map.fire('moveend'); 
    }
});

// 2. Kadastrale Kaart (Cadastral Parcels)
const kadasterLayer = L.tileLayer.wms('https://service.pdok.nl/kadaster/kadastralekaart/wms/v5_0', {
    layers: 'kadastralekaart',
    format: 'image/png',
    transparent: true,
    version: '1.3.0',
    attribution: 'Data: PDOK / Kadaster'
});

// 3. Natura 2000 Areas
const natura2000Layer = L.tileLayer.wms('https://service.pdok.nl/rvo/natura2000/wms/v1_0', {
    layers: 'natura2000',
    format: 'image/png',
    transparent: true,
    version: '1.3.0',
    attribution: 'Data: PDOK / RVO'
});

// ---------------------------------------------------------
// Debugging: Listen for tile loading errors
// ---------------------------------------------------------
brpLayer.on('tileerror', function(error, tile) {
    console.error('BRP Layer failed to load a tile. Check network tab for details.', error);
});

kadasterLayer.on('tileerror', function(error, tile) {
    console.error('Kadaster Layer failed to load a tile. Check network tab for details.', error);
});

// ---------------------------------------------------------
// Layer Controls
// ---------------------------------------------------------
const baseMaps = { "OpenStreetMap": baseLayer };
const overlayMaps = {
    "BRP Crop Parcels": brpLayer,
    "Cadastral Parcels": kadasterLayer,
    "Natura 2000 Areas": natura2000Layer
};

L.control.layers(baseMaps, overlayMaps, { collapsed: false }).addTo(map);


// ---------------------------------------------------------
// Export to PDF with Legal Credentials
// ---------------------------------------------------------

// Create a custom control for the export button positioned at the bottom left
const exportControl = L.control({position: 'bottomleft'});

exportControl.onAdd = function (map) {
    const div = L.DomUtil.create('div', 'export-control');
    // Button styling for a professional look
    div.innerHTML = `
        <button id="export-pdf-btn" style="
            background-color: #2c3e50; 
            color: white; 
            border: none; 
            padding: 10px 15px; 
            cursor: pointer; 
            font-size: 14px; 
            font-weight: bold;
            border-radius: 4px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.3);
        ">📄 Export Evidence to PDF</button>
    `;
    return div;
};

exportControl.addTo(map);

// Add event listener to the export button
document.getElementById('export-pdf-btn').addEventListener('click', async function() {
    const btn = this;
    const originalText = btn.innerText;
    
    // Provide user feedback during the export process
    btn.innerText = "⏳ Generating PDF...";
    btn.disabled = true;

    try {
        // Target the map container
        const mapElement = document.getElementById('map');
        
        // Use html2canvas to capture the map as an image
        // useCORS is strictly required to capture external map tiles
        const canvas = await html2canvas(mapElement, {
            useCORS: true,
            allowTaint: true
        });
        
        // Convert canvas to base64 image data
        const imgData = canvas.toDataURL('image/png');

        // Initialize jsPDF (Landscape, millimeters, A4 size)
        const { jsPDF } = window.jspdf;
        const pdf = new jsPDF('l', 'mm', 'a4');
        
        const pdfWidth = pdf.internal.pageSize.getWidth();
        const pdfHeight = pdf.internal.pageSize.getHeight();
        
        // Calculate image dimensions to fit the top portion of the A4 page
        // Leave room at the bottom for legal credentials
        const mapHeightInPdf = pdfHeight - 40; 
        const ratio = canvas.width / canvas.height;
        const mapWidthInPdf = mapHeightInPdf * ratio;
        
        // Center the map image horizontally
        const xOffset = (pdfWidth - mapWidthInPdf) / 2;

        // Add the map screenshot to the PDF
        pdf.addImage(imgData, 'PNG', xOffset, 10, mapWidthInPdf, mapHeightInPdf);

        // Append legal credentials and data provenance at the bottom
        pdf.setFontSize(10);
        pdf.setTextColor(100);
        
        // Standardized legal attribution required by the project brief
        const attributionText = "EVIDENCE DOCUMENT - ADVOCAAT VAN DE AARDE & STICHTING MOB\n" +
                                "Data Provenance: Maps and spatial data generated using public datasets via PDOK.nl.\n" +
                                "Sources: RVO (Basisregistratie Gewaspercelen), Kadaster (Kadastrale Kaart v5), MinEZK (Natura 2000).\n" +
                                "Date Generated: " + new Date().toLocaleString();
        
        pdf.text(attributionText, 10, pdfHeight - 20);

        // Trigger the file download
        pdf.save('environmental_evidence_map.pdf');

    } catch (error) {
        console.error("Error generating PDF:", error);
        alert("An error occurred while generating the PDF. Please check the console.");
    } finally {
        // Restore button state
        btn.innerText = originalText;
        btn.disabled = false;
    }
});

// ---------------------------------------------------------
// Export Visible Parcels to Excel (Legal Requirement)
// ---------------------------------------------------------

// Create a custom control for the Excel export button
const excelControl = L.control({position: 'bottomright'});

excelControl.onAdd = function (map) {
    const div = L.DomUtil.create('div', 'excel-control');
    // Button styling matching the green theme of agricultural data
    div.innerHTML = `
        <button id="export-excel-btn" style="
            background-color: #27ae60; 
            color: white; 
            border: none; 
            padding: 10px 15px; 
            cursor: pointer; 
            font-size: 14px; 
            font-weight: bold;
            border-radius: 4px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.3);
        ">📊 Export Data to Excel</button>
    `;
    return div;
};

// Add the control to the map UI
excelControl.addTo(map);



// Add event listener to trigger the Excel export process
document.getElementById('export-excel-btn').addEventListener('click', function() {
    // Ensure the SheetJS library is loaded correctly
    if (typeof XLSX === 'undefined') {
        console.error("SheetJS library is not loaded.");
        alert("Excel export library missing. Please check your internet connection.");
        return;
    }

    const parcelData = [];

    // Loop through all currently rendered parcels in the BRP layer
    brpLayer.eachLayer(function(layer) {
        const feature = layer.feature;
        if (feature && feature.properties) {
            // Calculate exact area using Turf.js
            const areaSqM = turf.area(feature);
            const areaHa = (areaSqM / 10000).toFixed(2);
            
            // Push structured and standardized data to the array
            parcelData.push({
                "Year (Jaar)": feature.properties.jaar || 'N/A',
                "Crop Code (Gewascode)": feature.properties.gewascode || 'N/A',
                "Crop Type (Gewas)": feature.properties.gewas || 'Unknown',
                "Area (Hectares)": parseFloat(areaHa),
                "Data Source": "PDOK OGC API - BRP Gewaspercelen"
            });
        }
    });

    // Prevent exporting an empty file if no parcels are loaded
    if (parcelData.length === 0) {
        alert("No parcels currently visible on the map. Please zoom in and enable the BRP Crop Parcels layer.");
        return;
    }

    // Convert the JSON data array into an Excel worksheet
    const worksheet = XLSX.utils.json_to_sheet(parcelData);
    
    // Create a new workbook and append the worksheet
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, worksheet, "Parcel Evidence");

    // Trigger the browser to download the compiled Excel file
    XLSX.writeFile(workbook, "Environmental_Evidence_Data.xlsx");
});