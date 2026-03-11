// Initialize the map, lock it to a high zoom level (15), and set a minimum zoom (14)
// This strictly prevents the map from zooming out to a level where PDOK hides the data
const map = L.map('map', {
    center: [52.336, 4.653], // Haarlemmermeer
    zoom: 15,
    minZoom: 3
});

// Add standard OpenStreetMap as the base layer
const baseLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    crossOrigin: true, // Crucial for html2canvas PDF export
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
}).addTo(map);

// Global variable to keep track of the active buffer zone so we can clear it on the next click
let currentBufferLayer = null;

// ---------------------------------------------------------
// 1. BRP Gewaspercelen (Crop Parcels) - Vector Layer
// ---------------------------------------------------------
const brpLayer = L.geoJSON(null, {
    style: function(feature) {
        return {
            color: '#d35400', 
            weight: 3,
            dashArray: '5, 5', 
            fillColor: '#e67e22',
            fillOpacity: 0.4 
        };
    },
    onEachFeature: function(feature, layer) {
        // Ensure Turf.js is loaded before attempting spatial calculations
        if (typeof turf !== 'undefined') {
            const areaSqM = turf.area(feature);
            const areaHa = (areaSqM / 10000).toFixed(2);
            const gewas = feature.properties.gewas || 'Unknown';
            const jaar = feature.properties.jaar || 'N/A';

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

            // Attach a click event listener to each individual polygon
            layer.on('click', function(e) {
                // Step 1: Remove the previous buffer layer from the map if it exists
                if (currentBufferLayer) {
                    map.removeLayer(currentBufferLayer);
                }

                // Step 2: Calculate a 500-meter buffer around the clicked geometry
                // Turf.js uses kilometers as the standard unit, so 500 meters is 0.5 km
                const bufferFeature = turf.buffer(feature, 0.5, { units: 'kilometers' });

                // Step 3: Create a new Leaflet GeoJSON layer for the buffer geometry
                currentBufferLayer = L.geoJSON(bufferFeature, {
                    style: {
                        color: '#27ae60', // Strict green border for the legal buffer
                        weight: 2,
                        dashArray: '4, 6', // Dotted line to indicate it is a calculated zone
                        fillColor: '#2ecc71',
                        fillOpacity: 0.15 // Highly transparent so underlying map is still visible
                    },
                    // Disable clicks on the buffer itself so the user can click parcels underneath
                    interactive: false 
                }).addTo(map);

                // Optional: Smoothly pan and zoom the map to fit the newly created buffer zone
                map.flyToBounds(currentBufferLayer.getBounds(), { padding: [30, 30], duration: 0.5 });
            });
        }
    }
});

// Dynamic Network Request for BRP vector parcels
map.on('moveend', async function() {
    if (map.getZoom() < 14) {
        brpLayer.clearLayers();
        return;
    }
    if (!map.hasLayer(brpLayer)) return;

    const bounds = map.getBounds();
    const bbox = `${bounds.getWest()},${bounds.getSouth()},${bounds.getEast()},${bounds.getNorth()}`;
    const apiUrl = `https://api.pdok.nl/rvo/gewaspercelen/ogc/v1/collections/brpgewas/items?bbox=${bbox}&limit=1000`;

    try {
        const response = await fetch(apiUrl, { headers: { 'Accept': 'application/geo+json' } });
        const data = await response.json();
        brpLayer.clearLayers();
        if (data.features && data.features.length > 0) {
            brpLayer.addData(data);
        }
    } catch (error) {
        console.error("Failed to download vector data via OGC API:", error);
    }
});

map.on('overlayadd', function(e) {
    if (e.name === "BRP Crop Parcels") map.fire('moveend'); 
});

// ---------------------------------------------------------
// 2. Kadastrale Kaart (Cadastral Parcels) - WMS
// ---------------------------------------------------------
const kadasterLayer = L.tileLayer.wms('https://service.pdok.nl/kadaster/kadastralekaart/wms/v5_0', {
    layers: 'kadastralekaart',
    format: 'image/png',
    transparent: true,
    version: '1.3.0',
    attribution: 'Data: PDOK / Kadaster'
});

// ---------------------------------------------------------
// 3. Natura 2000 Areas - WMS
// ---------------------------------------------------------
const natura2000Layer = L.tileLayer.wms('https://service.pdok.nl/rvo/natura2000/wms/v1_0', {
    layers: 'natura2000',
    format: 'image/png',
    transparent: true,
    version: '1.3.0',
    attribution: 'Data: PDOK / RVO'
});

// ---------------------------------------------------------
// 4. BAG Buildings - WMS
// ---------------------------------------------------------
const bagLayer = L.tileLayer.wms('https://service.pdok.nl/lv/bag/wms/v2_0', {
    layers: 'pand', // 'pand' means building polygon
    format: 'image/png',
    transparent: true,
    version: '1.3.0',
    attribution: 'Data: PDOK / BAG'
});

// ---------------------------------------------------------
// Layer Controls
// ---------------------------------------------------------
const baseMaps = { "OpenStreetMap": baseLayer };
const overlayMaps = {
    "BRP Crop Parcels": brpLayer,
    "Cadastral Parcels": kadasterLayer,
    "Natura 2000 Areas": natura2000Layer,
    "BAG Buildings": bagLayer
};
L.control.layers(baseMaps, overlayMaps, { collapsed: false }).addTo(map);

// ---------------------------------------------------------
// Export to PDF with Legal Credentials
// ---------------------------------------------------------
const exportControl = L.control({position: 'bottomleft'});
exportControl.onAdd = function (map) {
    const div = L.DomUtil.create('div', 'export-control');
    div.innerHTML = `
        <button id="export-pdf-btn" style="
            background-color: #2c3e50; color: white; border: none; padding: 10px 15px; 
            cursor: pointer; font-size: 14px; font-weight: bold; border-radius: 4px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.3);
        ">📄 Export Evidence to PDF</button>
    `;
    return div;
};
exportControl.addTo(map);

document.getElementById('export-pdf-btn').addEventListener('click', async function() {
    const btn = this;
    const originalText = btn.innerText;
    btn.innerText = "⏳ Generating PDF...";
    btn.disabled = true;

    try {
        const mapElement = document.getElementById('map');
        const canvas = await html2canvas(mapElement, { useCORS: true, allowTaint: true });
        const imgData = canvas.toDataURL('image/png');

        const { jsPDF } = window.jspdf;
        const pdf = new jsPDF('l', 'mm', 'a4');
        
        const pdfWidth = pdf.internal.pageSize.getWidth();
        const pdfHeight = pdf.internal.pageSize.getHeight();
        const mapHeightInPdf = pdfHeight - 40; 
        const ratio = canvas.width / canvas.height;
        const mapWidthInPdf = mapHeightInPdf * ratio;
        const xOffset = (pdfWidth - mapWidthInPdf) / 2;

        pdf.addImage(imgData, 'PNG', xOffset, 10, mapWidthInPdf, mapHeightInPdf);
        pdf.setFontSize(10);
        pdf.setTextColor(100);
        
        const attributionText = "EVIDENCE DOCUMENT - ADVOCAAT VAN DE AARDE & STICHTING MOB\n" +
                                "Data Provenance: Maps and spatial data generated using public datasets via PDOK.nl.\n" +
                                "Sources: RVO, Kadaster, MinEZK, BAG.\n" +
                                "Date Generated: " + new Date().toLocaleString();
        
        pdf.text(attributionText, 10, pdfHeight - 20);
        pdf.save('environmental_evidence_map.pdf');

    } catch (error) {
        console.error("Error generating PDF:", error);
        alert("An error occurred while generating the PDF.");
    } finally {
        btn.innerText = originalText;
        btn.disabled = false;
    }
});

// ---------------------------------------------------------
// Export to Excel (Hybrid Architecture)
// Visuals are WMS/Vector, Data export is WFS/API via Backend
// ---------------------------------------------------------
const excelControl = L.control({position: 'bottomright'});
excelControl.onAdd = function (map) {
    const div = L.DomUtil.create('div', 'excel-control');
    div.innerHTML = `
        <button id="export-excel-btn" style="
            background-color: #27ae60; color: white; border: none; padding: 10px 15px; 
            cursor: pointer; font-size: 14px; font-weight: bold; border-radius: 4px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.3);
        ">📊 Export Data to Excel</button>
    `;
    return div;
};
excelControl.addTo(map);

// EXTENSIBLE ARCHITECTURE: The Export Registry
const exportRegistry = [
    {
        layerObject: brpLayer, 
        sheetName: "BRP Parcels",
        buildUrl: (bbox) => `https://api.pdok.nl/rvo/gewaspercelen/ogc/v1/collections/brpgewas/items?bbox=${bbox}&limit=1000`,
        columns: { "jaar": "Registration Year", "gewas": "Crop Type", "gewascode": "Crop Code" }
    },
    {
        layerObject: kadasterLayer, 
        sheetName: "Kadaster",
        buildUrl: (bbox) => `https://service.pdok.nl/kadaster/kadastralekaart/wfs/v5_0?service=WFS&version=1.0.0&request=GetFeature&typeName=kadastralekaartv5:perceel&outputFormat=application/json&srsName=EPSG:4326&bbox=${bbox},EPSG:4326`,
        columns: { "kadastraleGemeentecode": "Municipality Code", "sectie": "Section", "perceelnummer": "Parcel Number", "kadastraleGrootte": "Registered Area (m2)" }
    },
    {
        layerObject: natura2000Layer,
        sheetName: "Natura 2000",
        buildUrl: (bbox) => `https://service.pdok.nl/rvo/natura2000/wfs/v1_0?service=WFS&version=1.0.0&request=GetFeature&typeName=natura2000&outputFormat=application/json&srsName=EPSG:4326&bbox=${bbox},EPSG:4326`,
        columns: { "naam": "Area Name", "type": "Protection Type" }
    },
    {
        layerObject: bagLayer,
        sheetName: "BAG Buildings",
        buildUrl: (bbox) => `https://service.pdok.nl/lv/bag/wfs/v2_0?service=WFS&version=2.0.0&request=GetFeature&typeName=bag:pand&outputFormat=application/json&srsName=EPSG:4326&bbox=${bbox},EPSG:4326`,
        columns: { "identificatie": "Building ID", "oorspronkelijkbouwjaar": "Construction Year", "status": "Building Status" }
    }
];

document.getElementById('export-excel-btn').addEventListener('click', async function() {
    const btn = this;
    const originalText = btn.innerText;
    
    btn.innerText = "⏳ Compiling Data on Server...";
    btn.disabled = true;

    const bounds = map.getBounds();
    const bbox = `${bounds.getWest()},${bounds.getSouth()},${bounds.getEast()},${bounds.getNorth()}`;

    const layersToExport = [];
    exportRegistry.forEach(config => {
        if (map.hasLayer(config.layerObject)) {
            layersToExport.push({ 
                sheet_name: config.sheetName, 
                url: config.buildUrl(bbox), 
                columns: config.columns 
            });
        }
    });

    if (layersToExport.length === 0) {
        alert("Please enable at least one data layer to export.");
        btn.innerText = originalText; 
        btn.disabled = false; 
        return;
    }

    try {
        const response = await fetch('/api/export_excel', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ layers: layersToExport })
        });

        if (!response.ok) throw new Error("Backend export processing failed.");

        const blob = await response.blob();
        const downloadUrl = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = downloadUrl;
        a.download = "Environmental_Evidence_Data.xlsx";
        document.body.appendChild(a);
        a.click();
        
        a.remove();
        window.URL.revokeObjectURL(downloadUrl);

    } catch (error) { 
        console.error("Export Error:", error); 
        alert("Failed to export data. Please check the terminal running Flask for details.");
    } finally { 
        btn.innerText = originalText; 
        btn.disabled = false; 
    }
});