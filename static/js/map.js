// =========================================================
// 1. Map Initialization & Base Layer
// =========================================================
const map = L.map('map', {
    center: [52.336, 4.653], // Haarlemmermeer
    zoom: 15,
    minZoom: 5,
    preferCanvas: true // Crucial for rendering thousands of local polygons
});

// Standard OpenStreetMap base layer
const baseLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    crossOrigin: 'anonymous', 
    attribution: '&copy; OpenStreetMap contributors'
}).addTo(map);


// =========================================================
// 2. Sidebar Engine & Helpers
// =========================================================
let currentBufferLayer = null;
let isProgrammaticMove = false; 

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

    if (!infoPanel || !panelTitle || !panelContent) return;

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

// Close Sidebar Logic
document.getElementById('close-panel-btn').addEventListener('click', () => {
    document.getElementById('info-panel').classList.add('hidden');
});


// =========================================================
// 3. Local Database Vector Layers Initialization
// =========================================================

const brpLayer = L.geoJSON(null, {
    style: (feature) => ({ color: getCropColor(feature.properties.gewas), weight: 2, fillOpacity: 0.4 }),
    onEachFeature: function(feature, layer) {
        layer.on('click', function(e) {
            L.DomEvent.stopPropagation(e);
            showFeatureInfo('BRP Crop Parcel', feature.properties);
            
            // Turf.js Spatial Analysis (500m Buffer)
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

const bagLayer = L.geoJSON(null, {
    style: { color: '#e74c3c', weight: 1, fillColor: '#e74c3c', fillOpacity: 0.6 },
    onEachFeature: (feature, layer) => {
        layer.on('click', (e) => { L.DomEvent.stopPropagation(e); showFeatureInfo('BAG Building', feature.properties); });
    }
});

const natura2000Layer = L.geoJSON(null, {
    style: { color: '#16a085', weight: 2, fillColor: '#1abc9c', fillOpacity: 0.3 },
    onEachFeature: (feature, layer) => {
        layer.on('click', (e) => { L.DomEvent.stopPropagation(e); showFeatureInfo('Natura 2000 Area', feature.properties); });
    }
});

const kadasterLayer = L.geoJSON(null, {
    style: { color: '#34495e', weight: 1, fillOpacity: 0.05 },
    onEachFeature: (feature, layer) => {
        layer.on('click', (e) => { L.DomEvent.stopPropagation(e); showFeatureInfo('Kadaster Parcel', feature.properties); });
    }
});

// NEW: Regionale Woondeals Layer
const woondealsLayer = L.geoJSON(null, {
    style: { color: '#9b59b6', weight: 2, fillColor: '#8e44ad', fillOpacity: 0.3, dashArray: '5, 5' },
    onEachFeature: (feature, layer) => {
        layer.on('click', (e) => { L.DomEvent.stopPropagation(e); showFeatureInfo('Regional Housing Agreement', feature.properties); });
    }
});

// Registry linking HTML IDs to Leaflet Layer Objects
const layerRegistry = {
    'brp': brpLayer,
    'bag': bagLayer,
    'natura2000': natura2000Layer,
    'kadaster': kadasterLayer,
    'woondeals': woondealsLayer
};


// =========================================================
// 4. Custom UI Control Panel Integration (Dynamic Setup)
// =========================================================

// A. Fetch Dynamic Years from PostGIS
async function initializeDynamicYears() {
    try {
        const response = await fetch('/api/available_years');
        const data = await response.json();
        
        for (const [layerId, years] of Object.entries(data)) {
            const selectElement = document.getElementById(`year-${layerId}`);
            if (selectElement) {
                if (years.length > 0) {
                    selectElement.innerHTML = ''; 
                    years.forEach(year => {
                        const option = document.createElement('option');
                        option.value = year;
                        option.textContent = year;
                        selectElement.appendChild(option);
                    });
                    selectElement.style.display = 'inline-block';
                } else {
                    selectElement.style.display = 'none'; // Hide if static dataset
                }
            }
        }
    } catch (error) {
        console.error("❌ Failed to fetch dynamic years from backend:", error);
    }
}

document.addEventListener('DOMContentLoaded', initializeDynamicYears);

// B. Checkbox Toggles (Turn layers on/off)
document.querySelectorAll('.map-layer-toggle').forEach(checkbox => {
    checkbox.addEventListener('change', function() {
        const layer = layerRegistry[this.value];
        if (this.checked) {
            layer.addTo(map);
            map.fire('moveend'); // Instantly fetch data for current view
        } else {
            map.removeLayer(layer);
            layer.clearLayers();
        }
    });
});

// C. Dropdown Changes (Refresh layer when year is changed)
document.querySelectorAll('.layer-year-select').forEach(select => {
    select.addEventListener('change', function() {
        const layerId = this.id.replace('year-', '');
        const layer = layerRegistry[layerId];
        if (map.hasLayer(layer)) {
            layer.clearLayers();
            map.fire('moveend'); 
        }
    });
});


// =========================================================
// 5. Dynamic Data Fetching Engine (Triggers on Map Move)
// =========================================================
map.on('moveend', async function() {
    if (isProgrammaticMove) {
        isProgrammaticMove = false; 
        return; 
    }

    // Safety lock: Don't fetch vector heavy data if zoomed out too far
    if (map.getZoom() < 13) {
        Object.values(layerRegistry).forEach(layer => layer.clearLayers());
        return;
    }

    const bounds = map.getBounds();
    const bbox = `${bounds.getWest()},${bounds.getSouth()},${bounds.getEast()},${bounds.getNorth()}`;

    // Helper: Safely get the selected year from the dropdown, fallback to a default if still loading
    const getYear = (layerId) => {
        const select = document.getElementById(`year-${layerId}`);
        return select && select.value ? select.value : '2026';
    };

    async function loadDataIfActive(layerObject, apiUrl) {
        if (!map.hasLayer(layerObject)) return;
        try {
            const response = await fetch(apiUrl);
            if (!response.ok) throw new Error("Server response not OK");
            const data = await response.json();
            
            layerObject.clearLayers(); 
            if (data.features && data.features.length > 0) {
                layerObject.addData(data);
            }
        } catch (error) {
            console.error(`Failed to load data from ${apiUrl}:`, error);
        }
    }

    // Fire all active requests concurrently
    loadDataIfActive(brpLayer, `/api/brp_parcels?bbox=${bbox}&year=${getYear('brp')}`);
    loadDataIfActive(bagLayer, `/api/bag_buildings?bbox=${bbox}&year=${getYear('bag')}`);
    loadDataIfActive(natura2000Layer, `/api/natura2000_areas?bbox=${bbox}`);
    loadDataIfActive(kadasterLayer, `/api/kadaster_parcels?bbox=${bbox}`);
    loadDataIfActive(woondealsLayer, `/api/woondeals?bbox=${bbox}`);
});


// =========================================================
// 6. Evidence Export Tools (PDF & Excel)
// =========================================================

// PDF Export Control
const exportControl = L.control({position: 'bottomleft'});
exportControl.onAdd = function () {
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
    const customControls = document.getElementById('layer-controls'); // Hide our custom panel

    try {
        if (leafletControls) leafletControls.style.display = 'none';
        if (customControls) customControls.style.display = 'none';
        
        await new Promise(resolve => setTimeout(resolve, 800));

        const canvas = await html2canvas(document.getElementById('map'), { 
            useCORS: true, allowTaint: false, scale: 2, backgroundColor: '#ffffff', logging: false 
        });

        if (leafletControls) leafletControls.style.display = '';
        if (customControls) customControls.style.display = '';
        
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
                                "Data Provenance: Spatial data securely aggregated from local PostGIS data warehouse.\n" +
                                "Date Generated: " + new Date().toLocaleString();
        
        pdf.text(attributionText, 10, pdfHeight - 20);
        pdf.save(`Environmental_Evidence_${new Date().toISOString().split('T')[0]}.pdf`);

    } catch (error) {
        alert("An error occurred while generating the PDF.");
    } finally {
        if (leafletControls) leafletControls.style.display = '';
        if (customControls) customControls.style.display = '';
        btn.innerText = originalText;
        btn.disabled = false;
    }
});

// Excel Export Control
const excelControl = L.control({position: 'bottomright'});
excelControl.onAdd = function () {
    const div = L.DomUtil.create('div', 'excel-control');
    div.innerHTML = `<button id="export-excel-btn" style="background-color: #27ae60; color: white; border: none; padding: 10px 15px; cursor: pointer; font-size: 14px; font-weight: bold; border-radius: 4px; box-shadow: 0 2px 4px rgba(0,0,0,0.3);">📊 Export Data to Excel</button>`;
    return div;
};
excelControl.addTo(map);

const exportRegistry = [
    {
        layerObject: brpLayer, sheetName: "BRP Parcels",
        buildUrl: (bbox) => `/api/brp_parcels?bbox=${bbox}&year=${document.getElementById('year-brp').value}`,
        columns: { "jaar": "Registration Year", "gewas": "Crop Type", "gewascode": "Crop Code" }
    },
    {
        layerObject: bagLayer, sheetName: "BAG Buildings",
        buildUrl: (bbox) => `/api/bag_buildings?bbox=${bbox}&year=${document.getElementById('year-bag').value}`,
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
    },
    {
        layerObject: woondealsLayer, sheetName: "Woondeals",
        buildUrl: (bbox) => `/api/woondeals?bbox=${bbox}`,
        columns: { "regio": "Region", "aantal_woningen": "Planned Houses", "status": "Status" } // Customize based on exact columns
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
        a.download = `Local_Evidence_Data_${new Date().toISOString().split('T')[0]}.xlsx`;
        document.body.appendChild(a);
        a.click();
        a.remove();
    } catch (error) { 
        alert("Failed to export data.");
    } finally { 
        btn.innerText = originalText; btn.disabled = false; 
    }
});