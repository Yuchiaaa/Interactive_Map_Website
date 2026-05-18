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

// 3A. BRP Crop Parcels (Includes Turf.js Buffer Analysis)
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

// 3B. BAG Buildings
const bagLayer = L.geoJSON(null, {
    style: { color: '#e74c3c', weight: 1, fillColor: '#e74c3c', fillOpacity: 0.6 },
    onEachFeature: (feature, layer) => {
        layer.on('click', (e) => { L.DomEvent.stopPropagation(e); showFeatureInfo('BAG Building', feature.properties); });
    }
});

// 3C. Natura 2000 Areas
const natura2000Layer = L.geoJSON(null, {
    style: { color: '#16a085', weight: 2, fillColor: '#1abc9c', fillOpacity: 0.3 },
    onEachFeature: (feature, layer) => {
        layer.on('click', (e) => { L.DomEvent.stopPropagation(e); showFeatureInfo('Natura 2000 Area', feature.properties); });
    }
});

// 3D. Regionale Woondeals (Regional Housing Agreements)
const woondealsLayer = L.geoJSON(null, {
    // Added fillOpacity 0.1: If it's completely transparent, you won't see it when zoomed in!
    style: { color: '#9b59b6', weight: 4, fillColor: '#9b59b6', fillOpacity: 0.1, dashArray: '5, 5' },
    onEachFeature: (feature, layer) => {
        layer.on('click', (e) => { 
            L.DomEvent.stopPropagation(e); 
            console.log("🔍 Woondeals Properties Clicked:", feature.properties);
            showFeatureInfo('Regional Housing Agreement', feature.properties); 
        });
    }
});

// 3E. KRD Livestock Farms (Veehouderijen)
const krdLayer = L.geoJSON(null, {
    pointToLayer: (feature, latlng) => L.circleMarker(latlng, {
        radius: 6,
        fillColor: '#e67e22',
        color: '#d35400',
        weight: 1,
        fillOpacity: 0.8
    }),
    onEachFeature: (feature, layer) => {
        layer.on('click', (e) => { L.DomEvent.stopPropagation(e); showFeatureInfo('KRD Veehouderij', feature.properties); });
    }
});

// 3F. Health Facilities (HOTOSM Netherlands)
function getHealthColor(facilityType) {
    if (!facilityType) return '#95a5a6';
    switch (facilityType) {
        case 'hospital':  return '#c0392b';
        case 'clinic':    return '#e74c3c';
        case 'doctor':    return '#2980b9';
        case 'pharmacy':  return '#27ae60';
        case 'dentist':   return '#8e44ad';
        default:          return '#7f8c8d';
    }
}

const healthLayer = L.geoJSON(null, {
    pointToLayer: (feature, latlng) => L.circleMarker(latlng, {
        radius: 6,
        fillColor: getHealthColor(feature.properties.facility_type),
        color: '#2c3e50',
        weight: 1,
        fillOpacity: 0.85
    }),
    onEachFeature: (feature, layer) => {
        layer.on('click', (e) => { L.DomEvent.stopPropagation(e); showFeatureInfo('Health Facility', feature.properties); });
    }
});

// 3G. Pesticides Atlas Measurements
function getPesticideColor(mateNormov) {
    if (mateNormov === null || mateNormov === undefined) return '#95a5a6';
    if (mateNormov > 10) return '#c0392b';  // Dark red: severe exceedance
    if (mateNormov > 1)  return '#e67e22';  // Orange: above norm
    return '#27ae60';                        // Green: within norm
}

const pesticidesLayer = L.geoJSON(null, {
    pointToLayer: (feature, latlng) => L.circleMarker(latlng, {
        radius: 5,
        fillColor: getPesticideColor(feature.properties.mate_normov),
        color: '#2c3e50',
        weight: 1,
        fillOpacity: 0.85
    }),
    onEachFeature: (feature, layer) => {
        layer.on('click', (e) => { L.DomEvent.stopPropagation(e); showFeatureInfo('Pesticides Station', feature.properties); });
    }
});

// Registry linking HTML IDs to Leaflet Layer Objects
const layerRegistry = {
    'brp': brpLayer,
    'bag': bagLayer,
    'natura2000': natura2000Layer,
    'woondeals': woondealsLayer,
    'krd': krdLayer,
    'pesticides': pesticidesLayer,
    'health': healthLayer
};


// =========================================================
// 4. Custom UI Control Panel Integration & Nationwide Loading
// =========================================================

// State flags to ensure we only download nationwide data ONCE
let isNaturaLoaded = false;
let isWoondealsLoaded = false;

// Bounding box for the entire Netherlands (West, South, East, North)
// Used to trick the local backend into returning the whole country if the API fails
const bboxNetherlands = "3.3,50.75,7.22,53.7";

// Fetch Dynamic Years from PostGIS
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
                    selectElement.style.display = 'none'; 
                }
            }
        }
    } catch (error) {
        console.error("Failed to fetch dynamic years:", error);
    }
}

document.addEventListener('DOMContentLoaded', initializeDynamicYears);

// Engine for Nationwide Layers (API Primary -> DB Fallback)
async function loadNationwideLayer(layerObject, layerName, primaryApiUrl, fallbackDbUrl, flagName) {
    if (window[flagName]) return; // Already loaded in memory

    try {
        console.log(`[${layerName}] 🌐 Fetching Nationwide API...`);
        const response = await fetch(primaryApiUrl);
        if (!response.ok) throw new Error(`HTTP Error: ${response.status}`);
        
        const data = await response.json();
        if (data.features && data.features.length > 0) {
            layerObject.addData(data);
            window[flagName] = true;
            console.log(`[${layerName}] ✅ Nationwide API Loaded successfully.`);
        } else {
            throw new Error("API returned 0 features.");
        }
    } catch (error) {
        console.warn(`[${layerName}] ⚠️ API failed (${error.message}). Falling back to Local DB...`);
        try {
            const fallbackResponse = await fetch(fallbackDbUrl);
            if (!fallbackResponse.ok) throw new Error(`DB Error: ${fallbackResponse.status}`);
            const fallbackData = await fallbackResponse.json();
            
            if (fallbackData.features && fallbackData.features.length > 0) {
                layerObject.addData(fallbackData);
                window[flagName] = true;
                console.log(`[${layerName}] 🛡️ Nationwide Local Database Loaded successfully.`);
            }
        } catch (fallbackError) {
            console.error(`[${layerName}] ❌ Both API and Database failed!`, fallbackError);
        }
    }
}

function updateLegend() {
    const healthActive = document.getElementById('layer-health').checked;
    const pesticidesActive = document.getElementById('layer-pesticides').checked;

    document.getElementById('map-legend').style.display      = (healthActive || pesticidesActive) ? 'block' : 'none';
    document.getElementById('legend-health').style.display    = healthActive     ? 'block' : 'none';
    document.getElementById('legend-pesticides').style.display = pesticidesActive ? 'block' : 'none';
    document.getElementById('legend-divider').style.display   = (healthActive && pesticidesActive) ? 'block' : 'none';
}

// Checkbox Toggles
document.querySelectorAll('.map-layer-toggle').forEach(checkbox => {
    checkbox.addEventListener('change', async function() {
        const layerId = this.value;
        const layer = layerRegistry[layerId];

        if (this.checked) {
            layer.addTo(map);
            
            // CRS84 forces WFS to return standard [Lon, Lat] GeoJSON, preventing the ocean bug
            const crs84 = 'urn:ogc:def:crs:OGC:1.3:CRS84';

            if (layerId === 'natura2000') {
                const naturaApi = `https://service.pdok.nl/minlnv/natura2000/wfs/v1_0?request=GetFeature&service=WFS&version=2.0.0&typeName=natura2000:natura2000&outputFormat=application/json&srsName=${crs84}`;
                const naturaDb = `/api/natura2000_areas?bbox=${bboxNetherlands}`;
                await loadNationwideLayer(layer, 'Natura 2000', naturaApi, naturaDb, 'isNaturaLoaded');
            } 
            else if (layerId === 'woondeals') {
                const woondealsApi = `https://service.pdok.nl/bzk/regionale-woondeals/wfs/v1_0?request=GetFeature&service=WFS&version=2.0.0&typeName=regionale_woondeals:woondeals&outputFormat=application/json&srsName=${crs84}`;
                const woondealsDb = `/api/woondeals?bbox=${bboxNetherlands}`;
                await loadNationwideLayer(layer, 'Woondeals', woondealsApi, woondealsDb, 'isWoondealsLoaded');
            } 
            else {
                // Trigger BRP and BAG dynamic loading
                map.fire('moveend'); 
            }
        } else {
            map.removeLayer(layer);
            // We do NOT clear data for Natura/Woondeals so they remain instantly visible next time
            if (layerId === 'brp' || layerId === 'bag') {
                layer.clearLayers();
            }
        }

        updateLegend();
    });
});

// Dropdown Changes
document.querySelectorAll('.layer-year-select').forEach(select => {
    select.addEventListener('change', function() {
        const layerId = this.id.replace('year-', '');
        const layer = layerRegistry[layerId];
        if (layer && map.hasLayer(layer)) {
            layer.clearLayers();
            map.fire('moveend'); 
        }
    });
});


// =========================================================
// 5. Dynamic Data Fetching Engine (API Priority -> DB Fallback)
// =========================================================
map.on('moveend', async function() {
    if (isProgrammaticMove) {
        isProgrammaticMove = false; 
        return; 
    }

    const bounds = map.getBounds();
    
    // Standard Lon/Lat BBOX (Used for PostGIS)
    const bboxPostGIS = `${bounds.getWest()},${bounds.getSouth()},${bounds.getEast()},${bounds.getNorth()}`;
    
    // Strict Lat/Lon BBOX (Required ONLY for BAG WFS 2.0.0)
    const bboxBAG = `${bounds.getSouth()},${bounds.getWest()},${bounds.getNorth()},${bounds.getEast()}`;
    
    // BBOX for the entire Netherlands (Used to trick the DB into returning nationwide data)
    const bboxNetherlands = "3.3,50.75,7.22,53.7"; 

    const getYear = (layerId) => {
        const select = document.getElementById(`year-${layerId}`);
        return select && select.value ? select.value : '2026';
    };

    // Advanced Engine: Tries API first, gracefully falls back to Local DB
    async function loadDataWithFallback(layerObject, layerName, primaryApiUrl, fallbackDbUrl, isNationwide = false) {
        if (!map.hasLayer(layerObject)) return;
        
        try {
            console.log(`[${layerName}] 🌐 Requesting PDOK API...`);
            const response = await fetch(primaryApiUrl);
            
            if (!response.ok) throw new Error(`HTTP Error ${response.status}`);
            
            // PDOK sometimes returns XML when hitting zoom scale limits
            const contentType = response.headers.get("content-type");
            if (contentType && contentType.includes("xml")) throw new Error("API returned XML instead of GeoJSON.");

            const data = await response.json();
            
            if (data.features && data.features.length > 0) {
                layerObject.clearLayers();
                layerObject.addData(data);
                console.log(`[${layerName}] ✅ Loaded dynamically from PDOK API.`);
                return; // Execution stops here if API is successful
            } else {
                throw new Error("API returned 0 features.");
            }
        } catch (error) {
            console.warn(`[${layerName}] ⚠️ API skipped (${error.message}). Switching to Local DB Fallback...`);
            
            try {
                // For Nationwide layers, inject the massive BBOX to load the whole country from your database
                const finalDbUrl = isNationwide ? fallbackDbUrl.replace(bboxPostGIS, bboxNetherlands) : fallbackDbUrl;
                
                const fallbackResponse = await fetch(finalDbUrl);
                if (!fallbackResponse.ok) {
                    const errText = await fallbackResponse.text();
                    throw new Error(`DB Error ${fallbackResponse.status}: ${errText}`);
                }
                const fallbackData = await fallbackResponse.json();
                
                layerObject.clearLayers();
                if (fallbackData.features && fallbackData.features.length > 0) {
                    layerObject.addData(fallbackData);
                    console.log(`[${layerName}] 🛡️ Loaded from Local Database.`);
                }
            } catch (fallbackError) {
                console.error(`[${layerName}] ❌ FATAL ERROR: Both API and DB failed!`, fallbackError);
            }
        }
    }

    // ==========================================
    // 1. BRP Parcels (Local DB Only - Time Machine)
    // ==========================================
    if (map.hasLayer(brpLayer)) {
        fetch(`/api/brp_parcels?bbox=${bboxPostGIS}&year=${getYear('brp')}`)
            .then(res => res.json())
            .then(data => { brpLayer.clearLayers(); if (data.features) brpLayer.addData(data); })
            .catch(e => console.error("BRP Error:", e));
    }

    // ==========================================
    // 2. BAG Buildings (Your Stable Working Format!)
    // ==========================================
    const bagApi = `https://service.pdok.nl/lv/bag/wfs/v2_0?request=GetFeature&service=WFS&version=2.0.0&typeName=bag:pand&outputFormat=application/json&srsName=EPSG:4326&bbox=${bboxBAG},EPSG:4326`;
    const bagDb = `/api/bag_buildings?bbox=${bboxPostGIS}&year=${getYear('bag')}`;
    loadDataWithFallback(bagLayer, 'BAG Buildings', bagApi, bagDb, false);

    // ==========================================
    // 3. Natura 2000 (API FIRST for visualization)
    // ==========================================
    const naturaApi = `https://service.pdok.nl/rvo/natura2000/wfs/v1_0?request=GetFeature&service=WFS&version=2.0.0&typeName=natura2000:natura2000&outputFormat=application/json&srsName=EPSG:4326&bbox=${bboxBAG},EPSG:4326`;
    
    const naturaDb = `/api/natura2000_areas?bbox=${bboxPostGIS}`;

    // Load data from API first.
    loadDataWithFallback(natura2000Layer, 'Natura 2000', naturaApi, naturaDb, false);

    // ==========================================
    // 5. KRD Livestock Farms (Local DB Only)
    // ==========================================
    if (map.hasLayer(krdLayer)) {
        fetch(`/api/krd_farms?bbox=${bboxPostGIS}`)
            .then(res => res.json())
            .then(data => { krdLayer.clearLayers(); if (data.features) krdLayer.addData(data); })
            .catch(e => console.error("KRD Error:", e));
    }

    // ==========================================
    // 6. Pesticides Atlas (Local DB Only)
    // ==========================================
    if (map.hasLayer(pesticidesLayer)) {
        fetch(`/api/pesticides?bbox=${bboxPostGIS}`)
            .then(res => res.json())
            .then(data => { pesticidesLayer.clearLayers(); if (data.features) pesticidesLayer.addData(data); })
            .catch(e => console.error("Pesticides Error:", e));
    }

    // ==========================================
    // 7. Health Facilities (Local DB Only)
    // ==========================================
    if (map.hasLayer(healthLayer)) {
        fetch(`/api/health_facilities?bbox=${bboxPostGIS}`)
            .then(res => res.json())
            .then(data => { healthLayer.clearLayers(); if (data.features) healthLayer.addData(data); })
            .catch(e => console.error("Health Facilities Error:", e));
    }

    // ==========================================
    // 4. Regionale Woondeals (Nationwide)
    // FACT: PDOK does NOT have a WFS for Woondeals. This API fetch will deliberately fail to trigger DB fallback.
    // ==========================================
    const woondealsApi = `https://service.pdok.nl/bzk/regionale-woondeals/wfs/v1_0?request=GetFeature&service=WFS&version=2.0.0&typeName=woondeals&outputFormat=application/json`;
    const woondealsDb = `/api/woondeals?bbox=${bboxPostGIS}`;
    loadDataWithFallback(woondealsLayer, 'Woondeals', woondealsApi, woondealsDb, true);
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
    const customControls = document.getElementById('layer-controls');

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

// Excel Export Registry (Safely handles dynamic years from dropdowns)
const getDynamicYear = (layerId) => {
    const select = document.getElementById(`year-${layerId}`);
    return select && select.value ? select.value : '2026';
};

const exportRegistry = [
    {
        layerObject: brpLayer, sheetName: "BRP Parcels",
        buildUrl: (bbox) => `/api/brp_parcels?bbox=${bbox}&year=${getDynamicYear('brp')}`,
        columns: { "jaar": "Registration Year", "gewas": "Crop Type", "gewascode": "Crop Code" }
    },
    {
        layerObject: bagLayer, sheetName: "BAG Buildings",
        buildUrl: (bbox) => `/api/bag_buildings?bbox=${bbox}&year=${getDynamicYear('bag')}`,
        columns: { "identificatie": "Building ID", "bouwjaar": "Construction Year", "status": "Building Status" }
    },
    {
        layerObject: natura2000Layer, sheetName: "Natura 2000",
        buildUrl: (bbox) => `/api/natura2000_areas?bbox=${bbox}`,
        columns: { "naam": "Area Name", "type": "Protection Type" }
    },
    {
        layerObject: woondealsLayer, sheetName: "Woondeals",
        buildUrl: (bbox) => `/api/woondeals?bbox=${bbox}`,
        columns: { "regio": "Region", "aantal_woningen": "Planned Houses", "status": "Status" }
    },
    {
        layerObject: krdLayer, sheetName: "KRD Veehouderijen",
        buildUrl: (bbox) => `/api/krd_farms?bbox=${bbox}`,
        columns: { "provincie": "Provincie" }
    },
    {
        layerObject: pesticidesLayer, sheetName: "Pesticides Atlas",
        buildUrl: (bbox) => `/api/pesticides?bbox=${bbox}`,
        columns: { "stof_naam": "Substance", "jaar": "Year", "norm_omschrijving": "Norm Type", "klasse_omschrijving": "Result", "mate_normov": "Exceedance Ratio" }
    },
    {
        layerObject: healthLayer, sheetName: "Health Facilities",
        buildUrl: (bbox) => `/api/health_facilities?bbox=${bbox}`,
        columns: { "name": "Name", "facility_type": "Type", "addr_city": "City", "operator_type": "Operator" }
    }
];

document.getElementById('export-excel-btn').addEventListener('click', async function() {
    const btn = this;
    const originalText = btn.innerText;

    const bounds = map.getBounds();
    const bbox = `${bounds.getWest()},${bounds.getSouth()},${bounds.getEast()},${bounds.getNorth()}`;

    const activeLayers = exportRegistry
        .filter(c => map.hasLayer(c.layerObject))
        .map(c => c.sheetName);

    if (!activeLayers.length) {
        alert("Please enable at least one data layer to export.");
        return;
    }

    btn.innerText = "⏳ Generating Excel...";
    btn.disabled = true;

    try {
        const response = await fetch('/api/export_excel', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ bbox, layers: activeLayers })
        });
        if (!response.ok) throw new Error();

        const blob = await response.blob();
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `Environmental_Evidence_${new Date().toISOString().split('T')[0]}.xlsx`;
        a.click();
        URL.revokeObjectURL(a.href);
    } catch {
        alert("Export failed.");
    } finally {
        btn.innerText = originalText;
        btn.disabled = false;
    }
});