// Initialize the map, lock it to a high zoom level (15), and set a minimum zoom (14)
// This strictly prevents the map from zooming out to a level where PDOK hides the data
const map = L.map('map', {
    center: [52.336, 4.653], // Haarlemmermeer
    zoom: 15,
    minZoom: 3,
    preferCanvas: true
});

// Add standard OpenStreetMap as the base layer
const baseLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    crossOrigin: 'anonymous', // Crucial for html2canvas PDF export
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
}).addTo(map);

// ---------------------------------------------------------
// Global Variables & State Locks
// ---------------------------------------------------------
let currentBufferLayer = null;
let isProgrammaticMove = false; // Flag to prevent data wiping when the camera moves automatically
let currentBrpYear = '2026';    // Default selected year for BRP data

// Helper function to assign specific colors based on Dutch crop names
function getCropColor(cropName) {
    if (!cropName) return '#7f8c8d'; 
    const name = cropName.toLowerCase();
    
    if (name.includes('gras') || name.includes('weide')) return '#27ae60'; 
    if (name.includes('mais') || name.includes('maïs')) return '#f1c40f'; 
    if (name.includes('aardappel')) return '#d35400'; 
    if (name.includes('tarwe') || name.includes('graan')) return '#e67e22'; 
    if (name.includes('bieten')) return '#8e44ad'; 
    if (name.includes('bloem') || name.includes('bollen')) return '#e74c3c'; 

    let hash = 0;
    for (let i = 0; i < cropName.length; i++) {
        hash = cropName.charCodeAt(i) + ((hash << 5) - hash);
    }
    const colorHex = (hash & 0x00FFFFFF).toString(16).toUpperCase();
    return '#' + '00000'.substring(0, 6 - colorHex.length) + colorHex;
}

// ---------------------------------------------------------
// TEMPORAL CONTROL: Year Selector UI
// ---------------------------------------------------------
const yearControl = L.control({position: 'topright'});
yearControl.onAdd = function (map) {
    const div = L.DomUtil.create('div', 'year-control');
    div.innerHTML = `
        <div style="background: white; padding: 8px 12px; border-radius: 4px; box-shadow: 0 2px 5px rgba(0,0,0,0.3); font-family: Arial, sans-serif;">
            <label for="brp-year-select" style="font-weight: bold; font-size: 14px; color: #2c3e50;">Select Year: </label>
            <select id="brp-year-select" style="padding: 4px; font-size: 14px; border-radius: 4px; border: 1px solid #ccc;">
                <option value="2026" selected>2026</option>
                <option value="2025">2025</option>
                <option value="2024">2024</option>
                <option value="2023">2023</option>
                <option value="2022">2022</option>
                <option value="2021">2021</option>
            </select>
        </div>
    `;
    // Prevent map clicks/drags when interacting with the dropdown
    L.DomEvent.disableClickPropagation(div);
    return div;
};
yearControl.addTo(map);

// Listen for year changes
document.getElementById('brp-year-select').addEventListener('change', function(e) {
    currentBrpYear = e.target.value;
    // Clear old data and trigger a new network fetch
    brpLayer.clearLayers();
    map.fire('moveend');
});

// ---------------------------------------------------------
// 1. BRP Gewaspercelen (Crop Parcels) - Vector Layer
// ---------------------------------------------------------
const brpLayer = L.geoJSON(null, {
    style: function(feature) {
        const cropType = feature.properties.gewas || 'Unknown';
        const parcelColor = getCropColor(cropType);

        return {
            color: parcelColor, 
            weight: 3,
            dashArray: '5, 5', 
            fillColor: parcelColor,
            fillOpacity: 0.4 
        };
    },
    onEachFeature: function(feature, layer) {
        if (typeof turf !== 'undefined') {
            const areaSqM = turf.area(feature);
            const areaHa = (areaSqM / 10000).toFixed(2);
            const gewas = feature.properties.gewas || 'Unknown';
            const jaar = feature.properties.jaar || 'N/A';
            const titleColor = getCropColor(gewas);

            // Sticky popup (does not close automatically)
            layer.bindPopup(`
                <div style="font-family: Arial, sans-serif;">
                    <h3 style="margin: 0 0 5px 0; color: ${titleColor};">BRP Crop Parcel</h3>
                    <b>Registration Year:</b> ${jaar}<br>
                    <b>Crop Type:</b> ${gewas}<br>
                    <b>Calculated Area:</b> ${areaHa} ha<br>
                    <hr style="margin: 5px 0;">
                    <small>Source: PDOK OGC API</small>
                </div>
            `, { autoClose: false, closeOnClick: false });

            // Spatial analysis click event
            layer.on('click', function(e) {
                if (currentBufferLayer) {
                    map.removeLayer(currentBufferLayer);
                }

                const bufferFeature = turf.buffer(feature, 0.5, { units: 'kilometers' });

                currentBufferLayer = L.geoJSON(bufferFeature, {
                    style: {
                        color: '#27ae60', 
                        weight: 2,
                        dashArray: '4, 6', 
                        fillColor: '#2ecc71',
                        fillOpacity: 0.15 
                    },
                    interactive: false 
                }).addTo(map);

                // Lock the moveend event before animating the camera
                isProgrammaticMove = true;
                map.flyToBounds(currentBufferLayer.getBounds(), { padding: [30, 30], duration: 0.5 });
            });
        }
    }
});

// Dynamic Network Request for BRP vector parcels
map.on('moveend', async function() {
    // INTERCEPTOR: Prevent data wipe if camera moved programmatically (buffer zoom)
    if (isProgrammaticMove) {
        isProgrammaticMove = false; 
        return; 
    }

    if (map.getZoom() < 14) {
        brpLayer.clearLayers();
        return;
    }
    if (!map.hasLayer(brpLayer)) return;

    const bounds = map.getBounds();
    const bbox = `${bounds.getWest()},${bounds.getSouth()},${bounds.getEast()},${bounds.getNorth()}`;

    const apiUrl = `/api/brp_parcels?bbox=${bbox}&year=${currentBrpYear}`;
    
 
    try {
        const response = await fetch(apiUrl, { headers: { 'Accept': 'application/json' } });
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
    layers: 'pand', 
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

// ---------------------------------------------------------
// Export to PDF with Legal Credentials (Optimized Version)
// ---------------------------------------------------------
document.getElementById('export-pdf-btn').addEventListener('click', async function() {
    const btn = this;
    const originalText = btn.innerText;
    btn.innerText = "⏳ Preparing Legal PDF...";
    btn.disabled = true;

    // 1. Target the Leaflet UI controls container
    const leafletControls = document.querySelector('.leaflet-control-container');

    try {
        // 2. Hide all UI controls (zoom buttons, layer toggles, year selector)
        if (leafletControls) {
            leafletControls.style.display = 'none';
        }

        // 3. Force a tiny delay to let the DOM settle and map tiles finish rendering
        // This solves the "incomplete map" issue
        await new Promise(resolve => setTimeout(resolve, 800));

        const mapElement = document.getElementById('map');
        
        // 4. Capture with ultra-high resolution settings
        const canvas = await html2canvas(mapElement, { 
            useCORS: true, 
            allowTaint: false,
            scale: 2, // Doubles the pixel density for a Retina-quality sharp image
            backgroundColor: '#ffffff',
            logging: false // Keep console clean
        });

        // 5. Instantly restore UI controls after the snapshot is taken
        if (leafletControls) {
            leafletControls.style.display = '';
        }

        btn.innerText = "⏳ Generating Document...";

        // 6. Generate the PDF
        const imgData = canvas.toDataURL('image/jpeg', 0.95); // Use JPEG for smaller file size without losing much quality

        const jsPDFConstructor = window.jspdf ? window.jspdf.jsPDF : window.jsPDF;
        if (!jsPDFConstructor) throw new Error("jsPDF library is not loaded properly.");
        const pdf = new jsPDFConstructor('l', 'mm', 'a4');
        
        const pdfWidth = pdf.internal.pageSize.getWidth();
        const pdfHeight = pdf.internal.pageSize.getHeight();
        const mapHeightInPdf = pdfHeight - 40; 
        const ratio = canvas.width / canvas.height;
        const mapWidthInPdf = mapHeightInPdf * ratio;
        const xOffset = (pdfWidth - mapWidthInPdf) / 2;

        // Add the clean, high-res map image
        pdf.addImage(imgData, 'JPEG', xOffset, 10, mapWidthInPdf, mapHeightInPdf);
        
        // 1. Safely grab the current year directly from the UI dropdown (fallback to 2026)
        const yearSelect = document.getElementById('global-year-select');
        const exportYear = yearSelect ? yearSelect.value : '2026';

        // Add formal legal footer
        pdf.setFontSize(10);
        pdf.setTextColor(80);
        
        // 2. Use 'exportYear' instead of 'currentYear'
        const attributionText = "EVIDENCE DOCUMENT - ADVOCAAT VAN DE AARDE & STICHTING MOB\n" +
                                `Temporal Context: Data rendered for year ${exportYear}\n` +
                                "Data Provenance: Spatial data aggregated from public government registries via PostGIS.\n" +
                                "Date Generated: " + new Date().toLocaleString();
        
        pdf.text(attributionText, 10, pdfHeight - 20);
        
        // 3. Trigger download with the correct year in the filename
        pdf.save(`Environmental_Evidence_${exportYear}.pdf`);



    } catch (error) {
        console.error("Error generating PDF:", error);
        alert("An error occurred while generating the PDF. Please check the console.");
        // Ensure UI controls are restored even if an error occurs
        if (leafletControls) {
            leafletControls.style.display = '';
        }
    } finally {
        btn.innerText = originalText;
        btn.disabled = false;
    }
});

// ---------------------------------------------------------
// Export to Excel (Hybrid Architecture)
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

const exportRegistry = [
    {
        layerObject: brpLayer, 
        sheetName: "BRP Parcels",
        buildUrl: (bbox) => `/api/brp_parcels?bbox=${bbox}&year=${currentBrpYear}`,
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