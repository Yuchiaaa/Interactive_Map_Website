// =========================================================
// 1. Map Initialization & Base Layer
// =========================================================
const map = L.map('map', {
    center: [52.336, 4.653], // Haarlemmermeer
    zoom: 15,
    minZoom: 5,
    preferCanvas: true // Crucial for rendering thousands of local polygons
});

// Standard OpenStreetMap base layer (The only external network request)
const baseLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    crossOrigin: 'anonymous', 
    attribution: '&copy; OpenStreetMap contributors'
}).addTo(map);


// =========================================================
// 2. Global State & Sidebar Engine
// =========================================================
let currentBufferLayer = null;
let isProgrammaticMove = false; 
let globalSelectedYear = '2026'; // Controls both BRP and BAG temporal data

// Helper: Assign specific colors based on Dutch crop names
function getCropColor(cropName) {
    if (!cropName) return '#7f8c8d'; 
    const name = cropName.toLowerCase();
    if (name.includes('gras') || name.includes('weide')) return '#27ae60'; 
    if (name.includes('mais') || name.includes('maïs')) return '#f1c40f'; 
    if (name.includes('aardappel')) return '#d35400'; 
    if (name.includes('tarwe') || name.includes('graan')) return '#e67e22'; 
    if (name.includes('bieten')) return '#8e44ad'; 
    if (name.includes('bloem') || name.includes('bollen')) return '#e74c3c'; 
    return '#3498db'; // Default blue
}

// Sidebar Engine: Injects clicked feature properties into the HTML panel
function showFeatureInfo(layerName, properties) {
    const infoPanel = document.getElementById('info-panel');
    const panelTitle = document.getElementById('panel-title');
    const panelContent = document.getElementById('panel-content');

    if (!infoPanel || !panelTitle || !panelContent) {
        console.warn("Sidebar HTML elements not found. Please add them to index.html.");
        return;
    }

    panelTitle.innerText = layerName;
    panelContent.innerHTML = ''; 
    
    for (const [key, value] of Object.entries(properties)) {
        if (key === 'id' || key === 'geometry') continue; 
        
        const row = document.createElement('div');
        row.className = 'data-row';
        row.style = 'display: flex; justify-content: space-between; padding: 5px 0; border-bottom: 1px solid #eee; font-size: 14px;';
        
        const keyDiv = document.createElement('div');
        keyDiv.style.fontWeight = 'bold';
        keyDiv.style.textTransform = 'capitalize';
        keyDiv.innerText = key;
        
        const valueDiv = document.createElement('div');
        valueDiv.innerText = value !== null ? value : 'N/A';
        
        row.appendChild(keyDiv);
        row.appendChild(valueDiv);
        panelContent.appendChild(row);
    }
    
    infoPanel.classList.remove('hidden');
}


// =========================================================
// 3. UI Controls (Year Selector)
// =========================================================
const yearControl = L.control({position: 'topright'});
yearControl.onAdd = function (map) {
    const div = L.DomUtil.create('div', 'year-control');
    div.innerHTML = `
        <div style="background: white; padding: 8px 12px; border-radius: 4px; box-shadow: 0 2px 5px rgba(0,0,0,0.3); font-family: Arial, sans-serif;">
            <label for="global-year-select" style="font-weight: bold; font-size: 14px; color: #2c3e50;">Select Year: </label>
            <select id="global-year-select" style="padding: 4px; font-size: 14px; border-radius: 4px; border: 1px solid #ccc;">
                <option value="2026" selected>2026</option>
                <option value="2025">2025</option>
                <option value="2024">2024</option>
                <option value="2023">2023</option>
                <option value="2022">2022</option>
                <option value="2021">2021</option>
            </select>
        </div>
    `;
    L.DomEvent.disableClickPropagation(div);
    return div;
};
yearControl.addTo(map);

// Trigger full map data refresh when year changes
document.getElementById('global-year-select').addEventListener('change', function(e) {
    globalSelectedYear = e.target.value;
    brpLayer.clearLayers();
    bagLayer.clearLayers(); // BAG is also temporally filtered now!
    map.fire('moveend');
});


// =========================================================
// 4. Local Database Vector Layers Initialization
// =========================================================

// 4A. BRP Crop Parcels (Includes Turf.js Buffer Analysis)
const brpLayer = L.geoJSON(null, {
    style: function(feature) {
        return {
            color: getCropColor(feature.properties.gewas), 
            weight: 2,
            fillOpacity: 0.4 
        };
    },
    onEachFeature: function(feature, layer) {
        layer.on('click', function(e) {
            L.DomEvent.stopPropagation(e);
            
            // 1. Show Data in Sidebar
            showFeatureInfo('BRP Crop Parcel', feature.properties);

            // 2. Turf.js Spatial Analysis (500m Buffer)
            if (typeof turf !== 'undefined') {
                if (currentBufferLayer) map.removeLayer(currentBufferLayer);
                
                const bufferFeature = turf.buffer(feature, 0.5, { units: 'kilometers' });
                currentBufferLayer = L.geoJSON(bufferFeature, {
                    style: { color: '#27ae60', weight: 2, dashArray: '4, 6', fillColor: '#2ecc71', fillOpacity: 0.15 },
                    interactive: false 
                }).addTo(map);

                isProgrammaticMove = true;
                map.flyToBounds(currentBufferLayer.getBounds(), { padding: [30, 30], duration: 0.5 });
            }
        });
    }
});

// 4B. BAG Buildings
const bagLayer = L.geoJSON(null, {
    style: { color: '#e74c3c', weight: 1, fillColor: '#e74c3c', fillOpacity: 0.6 },
    onEachFeature: function(feature, layer) {
        layer.on('click', function(e) {
            L.DomEvent.stopPropagation(e);
            showFeatureInfo('BAG Building', feature.properties);
        });
    }
});

// 4C. Natura 2000 Areas
const natura2000Layer = L.geoJSON(null, {
    style: { color: '#16a085', weight: 2, fillColor: '#1abc9c', fillOpacity: 0.3 },
    onEachFeature: function(feature, layer) {
        layer.on('click', function(e) {
            L.DomEvent.stopPropagation(e);
            showFeatureInfo('Natura 2000 Protected Area', feature.properties);
        });
    }
});

// 4D. Kadastrale Kaart (Cadastral Parcels)
const kadasterLayer = L.geoJSON(null, {
    style: { color: '#34495e', weight: 1, fillOpacity: 0.05 },
    onEachFeature: function(feature, layer) {
        layer.on('click', function(e) {
            L.DomEvent.stopPropagation(e);
            showFeatureInfo('Kadaster Parcel', feature.properties);
        });
    }
});


// =========================================================
// 5. Layer Controls
// =========================================================
const baseMaps = { "OpenStreetMap": baseLayer };
const overlayMaps = {
    "BRP Crop Parcels": brpLayer,
    "BAG Buildings": bagLayer,
    "Natura 2000 Areas": natura2000Layer,
    "Cadastral Parcels": kadasterLayer
};
L.control.layers(baseMaps, overlayMaps, { collapsed: false }).addTo(map);


// =========================================================
// 6. Dynamic Data Fetching Engine (Triggers on Map Move)
// =========================================================
map.on('moveend', async function() {
    if (isProgrammaticMove) {
        isProgrammaticMove = false; 
        return; 
    }

    // Safety lock: Don't fetch if zoomed out too far (protects PostGIS from crashing)
    if (map.getZoom() < 13) {
        brpLayer.clearLayers();
        bagLayer.clearLayers();
        natura2000Layer.clearLayers();
        kadasterLayer.clearLayers();
        return;
    }

    const bounds = map.getBounds();
    const bbox = `${bounds.getWest()},${bounds.getSouth()},${bounds.getEast()},${bounds.getNorth()}`;

    // Helper function to fetch and load data for active layers
    async function loadDataIfActive(layerObject, apiUrl) {
        if (!map.hasLayer(layerObject)) return;
        try {
            const response = await fetch(apiUrl);
            if (!response.ok) throw new Error("Server response not OK");
            const data = await response.json();
            
            layerObject.clearLayers(); // Remove old polygons outside viewport
            if (data.features && data.features.length > 0) {
                layerObject.addData(data);
            }
        } catch (error) {
            console.error(`Failed to load data from ${apiUrl}:`, error);
        }
    }

    // Fire all requests concurrently for maximum speed
    loadDataIfActive(brpLayer, `/api/brp_parcels?bbox=${bbox}&year=${globalSelectedYear}`);
    loadDataIfActive(bagLayer, `/api/bag_buildings?bbox=${bbox}&year=${globalSelectedYear}`);
    loadDataIfActive(natura2000Layer, `/api/natura2000_areas?bbox=${bbox}`);
    loadDataIfActive(kadasterLayer, `/api/kadaster_parcels?bbox=${bbox}`);
});

// Immediately load data if a user turns on a layer checkbox in the UI
map.on('overlayadd', function(e) {
    map.fire('moveend'); 
});


// =========================================================
// 7. Evidence Export Tools (PDF & Excel)
// =========================================================

// PDF Export Control
const exportControl = L.control({position: 'bottomleft'});
exportControl.onAdd = function (map) {
    const div = L.DomUtil.create('div', 'export-control');
    div.innerHTML = `<button id="export-pdf-btn" style="background-color: #2c3e50; color: white; border: none; padding: 10px 15px; cursor: pointer; font-size: 14px; font-weight: bold; border-radius: 4px; box-shadow: 0 2px 4px rgba(0,0,0,0.3);">📄 Export Evidence to PDF</button>`;
    return div;
};
exportControl.addTo(map);

document.getElementById('export-pdf-btn').addEventListener('click', async function() {
    const btn = this;
    const originalText = btn.innerText;
    btn.innerText = "⏳ Preparing Legal PDF...";
    btn.disabled = true;

    const leafletControls = document.querySelector('.leaflet-control-container');

    try {
        if (leafletControls) leafletControls.style.display = 'none';
        await new Promise(resolve => setTimeout(resolve, 800));

        const canvas = await html2canvas(document.getElementById('map'), { 
            useCORS: true, allowTaint: false, scale: 2, backgroundColor: '#ffffff', logging: false 
        });

        if (leafletControls) leafletControls.style.display = '';
        btn.innerText = "⏳ Generating Document...";

        const imgData = canvas.toDataURL('image/jpeg', 0.95); 
        const jsPDFConstructor = window.jspdf ? window.jspdf.jsPDF : window.jsPDF;
        const pdf = new jsPDFConstructor('l', 'mm', 'a4');
        
        const pdfWidth = pdf.internal.pageSize.getWidth();
        const pdfHeight = pdf.internal.pageSize.getHeight();
        const mapHeightInPdf = pdfHeight - 40; 
        const ratio = canvas.width / canvas.height;
        const mapWidthInPdf = mapHeightInPdf * ratio;
        
        pdf.addImage(imgData, 'JPEG', (pdfWidth - mapWidthInPdf) / 2, 10, mapWidthInPdf, mapHeightInPdf);
        
        pdf.setFontSize(10);
        pdf.setTextColor(80);
        const attributionText = "EVIDENCE DOCUMENT - ADVOCAAT VAN DE AARDE & STICHTING MOB\n" +
                                `Temporal Context: Data rendered for year ${globalSelectedYear}\n` +
                                "Data Provenance: Spatial data securely aggregated from local PostGIS data warehouse.\n" +
                                "Date Generated: " + new Date().toLocaleString();
        
        pdf.text(attributionText, 10, pdfHeight - 20);
        pdf.save(`Environmental_Evidence_${globalSelectedYear}.pdf`);

    } catch (error) {
        alert("An error occurred while generating the PDF.");
    } finally {
        if (leafletControls) leafletControls.style.display = '';
        btn.innerText = originalText;
        btn.disabled = false;
    }
});

// Excel Export Control (Now points entirely to local PostGIS API routes!)
const excelControl = L.control({position: 'bottomright'});
excelControl.onAdd = function (map) {
    const div = L.DomUtil.create('div', 'excel-control');
    div.innerHTML = `<button id="export-excel-btn" style="background-color: #27ae60; color: white; border: none; padding: 10px 15px; cursor: pointer; font-size: 14px; font-weight: bold; border-radius: 4px; box-shadow: 0 2px 4px rgba(0,0,0,0.3);">📊 Export Data to Excel</button>`;
    return div;
};
excelControl.addTo(map);

// IMPORTANT: Excel URLs now point to our own internal Flask routes, not PDOK!
const exportRegistry = [
    {
        layerObject: brpLayer, sheetName: "BRP Parcels",
        buildUrl: (bbox) => `/api/brp_parcels?bbox=${bbox}&year=${globalSelectedYear}`,
        columns: { "jaar": "Registration Year", "gewas": "Crop Type", "gewascode": "Crop Code" }
    },
    {
        layerObject: bagLayer, sheetName: "BAG Buildings",
        buildUrl: (bbox) => `/api/bag_buildings?bbox=${bbox}&year=${globalSelectedYear}`,
        columns: { "identificatie": "Building ID", "bouwjaar": "Construction Year", "status": "Building Status" }
    },
    {
        layerObject: natura2000Layer, sheetName: "Natura 2000",
        buildUrl: (bbox) => `/api/natura2000_areas?bbox=${bbox}`,
        columns: { "naam": "Area Name", "type": "Protection Type" }
    },
    {
        layerObject: kadasterLayer, sheetName: "Kadaster",
        buildUrl: (bbox) => `/api/kadaster_parcels?bbox=${bbox}`,
        columns: { "gemeente": "Municipality", "sectie": "Section", "perceelnummer": "Parcel Number", "area": "Area" }
    }
];

document.getElementById('export-excel-btn').addEventListener('click', async function() {
    const btn = this;
    const originalText = btn.innerText;
    btn.innerText = "⏳ Compiling Local Data...";
    btn.disabled = true;

    const bounds = map.getBounds();
    const bbox = `${bounds.getWest()},${bounds.getSouth()},${bounds.getEast()},${bounds.getNorth()}`;

    const layersToExport = [];
    exportRegistry.forEach(config => {
        if (map.hasLayer(config.layerObject)) {
            layersToExport.push({ sheet_name: config.sheetName, url: config.buildUrl(bbox), columns: config.columns });
        }
    });

    if (layersToExport.length === 0) {
        alert("Please enable at least one data layer to export.");
        btn.innerText = originalText; btn.disabled = false; return;
    }

    try {
        const response = await fetch('/api/export_excel', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ layers: layersToExport })
        });
        if (!response.ok) throw new Error("Backend export processing failed.");

        const blob = await response.blob();
        const a = document.createElement('a');
        a.href = window.URL.createObjectURL(blob);
        a.download = `Local_Evidence_Data_${globalSelectedYear}.xlsx`;
        document.body.appendChild(a);
        a.click();
        a.remove();
    } catch (error) { 
        alert("Failed to export data.");
    } finally { 
        btn.innerText = originalText; btn.disabled = false; 
    }
});