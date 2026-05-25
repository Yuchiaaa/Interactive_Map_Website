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

// Buffer Tool State
let bufferToolActive = false;
let activeBuffers = [];   // [{id, polygon, mapLayer, labelMarker, radiusKm}]
let bufferMode = 'OR';
let pendingBufferFeature = null;
let bufferIdCounter = 0;
let bagBuildingCache = null;
let bagUsageCache = null;
let natura2000Cache = null;
let woondealsCache = null;
let grenzenCache = null;
let nnnCache = null;
let brpCache = null;
const BAG_API_LIMIT = 2000;
const BAG_USAGE_API_LIMIT = 3000;
const BAG_DETAIL_MIN_ZOOM = 14;
const NATURA2000_BUFFER_KM = 0.5;
const NATURA2000_API_LIMIT = 250;
const NATURA2000_DETAIL_MIN_ZOOM = 9;

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
function showFeatureInfo(layerName, properties, sourceUrl) {
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

    if (sourceUrl) {
        const linkRow = document.createElement('div');
        linkRow.style = 'padding: 10px 0 2px; font-size: 13px;';
        const link = document.createElement('a');
        link.href = sourceUrl;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.style.color = '#2980b9';
        link.innerText = 'View data source';
        linkRow.appendChild(link);
        panelContent.appendChild(linkRow);
    }

    infoPanel.classList.remove('hidden');
}

function handleFeatureClick(layerName, feature, e, customProperties, sourceUrl) {
    L.DomEvent.stopPropagation(e);
    showFeatureInfo(layerName, customProperties || feature.properties, sourceUrl);
    if (bufferToolActive) showRadiusPicker(feature, e);
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
            handleFeatureClick('BRP Crop Parcel', feature, e, null, 'https://www.pdok.nl/introductie/-/article/basisregistratie-gewaspercelen-brp-');

            // Auto 500m buffer analysis — only when buffer tool is NOT active
            if (!bufferToolActive && typeof turf !== 'undefined') {
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

function getBagUsageColor(usageGoal) {
    const goal = Array.isArray(usageGoal) ? usageGoal.join(',') : (usageGoal || '');
    const text = goal.toLowerCase();
    if (text.includes('woonfunctie')) return '#2980b9';
    if (text.includes('industriefunctie') || text.includes('kantoorfunctie')) return '#8e44ad';
    if (text.includes('winkelfunctie') || text.includes('bijeenkomstfunctie')) return '#f39c12';
    return '#7f8c8d';
}

function getBagDisplayProperties(feature) {
    const p = feature.properties || {};
    const address = [
        p.openbare_ruimte_naam,
        p.huisnummer,
        p.huisletter,
        p.toevoeging
    ].filter(Boolean).join(' ');

    return {
        identificatie: p.identificatie || p.id || 'Unknown',
        address: address || 'N/A',
        postcode: p.postcode || 'N/A',
        woonplaats: p.woonplaats_naam || 'N/A',
        gebruiksdoel: Array.isArray(p.gebruiksdoel) ? p.gebruiksdoel.join(', ') : (p.gebruiksdoel || 'N/A'),
        status: p.status || 'N/A',
        pand_identificatie: p.pand_identificatie || 'N/A',
        oppervlakte: p.oppervlakte || 'N/A'
    };
}

// 3B. BAG Buildings
const bagLayer = L.geoJSON(null, {
    style: { color: '#c0392b', weight: 1.3, fillColor: '#e74c3c', fillOpacity: 0.36 },
    onEachFeature: (feature, layer) => {
        layer.on('click', (e) => {
            const relationships = getBagBuildingRelationships(feature);
            handleFeatureClick(
                'BAG Building',
                feature,
                e,
                { ...(feature.properties || {}), ...relationships },
                'https://www.pdok.nl/introductie/-/article/basisregistraties-adressen-en-gebouwen-bag-'
            );
        });
    }
});

const bagUsageLayer = L.geoJSON(null, {
    pointToLayer: (feature, latlng) => L.circleMarker(latlng, {
        radius: 4,
        fillColor: getBagUsageColor(feature.properties?.gebruiksdoel),
        color: '#2c3e50',
        weight: 1,
        fillOpacity: 0.88
    }),
    onEachFeature: (feature, layer) => {
        layer.on('click', (e) => {
            handleFeatureClick(
                'BAG Usage Location',
                feature,
                e,
                getBagDisplayProperties(feature),
                'https://www.pdok.nl/introductie/-/article/basisregistraties-adressen-en-gebouwen-bag-'
            );
        });
    }
});

// 3C. Natura 2000 Areas
const natura2000Layer = L.geoJSON(null, {
    style: (feature) => {
        if (feature.properties?.layer_type === 'buffer') {
            return {
                color: '#f39c12',
                weight: 2,
                fillColor: '#f1c40f',
                fillOpacity: 0.16,
                dashArray: '8, 5'
            };
        }

        return {
            color: '#117a65',
            weight: 2,
            fillColor: '#16a085',
            fillOpacity: 0.34
        };
    },
    pointToLayer: (feature, latlng) => {
        if (feature.properties?.layer_type === 'center') {
            return L.marker(latlng, {
                icon: L.divIcon({
                    className: 'natura-center-pin',
                    html: '<span></span>',
                    iconSize: [22, 30],
                    iconAnchor: [11, 30],
                    popupAnchor: [0, -26]
                })
            });
        }

        return L.circleMarker(latlng, {
            radius: 5,
            fillColor: '#117a65',
            color: '#0b5345',
            weight: 1,
            fillOpacity: 0.9
        });
    },
    onEachFeature: (feature, layer) => {
        layer.on('click', (e) => {
            const layerType = feature.properties?.layer_type;
            const title = layerType === 'buffer'
                ? 'Natura 2000 Buffer'
                : layerType === 'center'
                    ? 'Natura 2000 Center'
                    : 'Natura 2000 Area';
            handleFeatureClick(title, feature, e, null, 'https://www.pdok.nl/introductie/-/article/natura2000');
        });
    }
});

const natura2000WmsLayer = L.tileLayer.wms('https://service.pdok.nl/rvo/natura2000/wms/v1_0', {
    layers: 'natura2000:lnv_natura2000',
    format: 'image/png',
    transparent: true,
    opacity: 0.62,
    attribution: 'Natura 2000 &copy; RVO/PDOK'
});

// 3D. Bestuurlijke Grenzen (Administrative Boundaries)
const grenzenColors = { 'gemeenten': '#e74c3c', 'provincies': '#000000', 'landsgrens': '#8e44ad' };
const grenzenLayer = L.geoJSON(null, {
    style: (feature) => {
        const color = grenzenColors[feature.properties.layer_type] || '#7f8c8d';
        return { color, weight: 2, fillColor: color, fillOpacity: 0.1 };
    },
    onEachFeature: (feature, layer) => {
        layer.on('click', (e) => {
            console.log("🔍 Grenzen Properties Clicked:", feature.properties);
            handleFeatureClick('Administrative Boundary', feature, e, null, 'https://www.pdok.nl/introductie/-/article/bestuurlijke-grenzen');
        });
    }
});

// 3E. Regionale Woondeals (Regional Housing Agreements)
const woondealsLayer = L.geoJSON(null, {
    // Added fillOpacity 0.1: If it's completely transparent, you won't see it when zoomed in!
    style: { color: '#9b59b6', weight: 4, fillColor: '#9b59b6', fillOpacity: 0.1, dashArray: '5, 5' },
    onEachFeature: (feature, layer) => {
        layer.on('click', (e) => {
            console.log("🔍 Woondeals Properties Clicked:", feature.properties);
            handleFeatureClick('Regional Housing Agreement', feature, e, null, 'https://www.pdok.nl/introductie/-/article/regionale-woondeals');
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
        layer.on('click', (e) => {
            const p = feature.properties;
            const priorityKeys = new Set(['nh3 emissie (kg/j)', 'geur emissie (oue/s)', 'fijnstof emissie (g/j)', 'adres']);
            const hideKeys = new Set(['geometry', 'id', 'bag vbo x', 'bag vbo y', 'gem. emissie x', 'gem. emissie y']);
            const display = {
                'NH3 emissie (kg/j)':     p['nh3 emissie (kg/j)'],
                'Geur emissie (ouE/s)':   p['geur emissie (oue/s)'],
                'Fijnstof emissie (g/j)': p['fijnstof emissie (g/j)'],
                'Adres':                  p['adres'],
            };
            for (const [k, v] of Object.entries(p)) {
                if (!priorityKeys.has(k) && !hideKeys.has(k)) display[k] = v;
            }
            handleFeatureClick('KRD Veehouderij', feature, e, display, 'https://krd.igoview.nl/');
        });
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
        layer.on('click', (e) => { handleFeatureClick('Health Facility', feature, e, null, 'https://data.humdata.org/dataset/hotosm-nld-health-facilities'); });
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
        fillColor: getPesticideColor(feature.properties.exceedance_ratio),
        color: '#2c3e50',
        weight: 1,
        fillOpacity: 0.85
    }),
    onEachFeature: (feature, layer) => {
        layer.on('click', (e) => { handleFeatureClick('Pesticides Station', feature, e, null, 'https://www.bestrijdingsmiddelenatlas.nl/'); });
    }
});

// =========================================================
// 3H. Schools Layer (Education Points)
// =========================================================

function getSchoolColor(schoolType) {
    if (!schoolType) return '#95a5a6';
    switch (schoolType) {
        case 'primary':    return '#2ecc71';
        case 'secondary':  return '#3498db';
        case 'vocational': return '#f39c12';
        case 'university': return '#9b59b6';
        default:           return '#7f8c8d';
    }
}

const schoolsLayer = L.geoJSON(null, {
    pointToLayer: (feature, latlng) => L.circleMarker(latlng, {
        radius: 5,
        fillColor: getSchoolColor(feature.properties.school_type),
        color: '#2c3e50',
        weight: 1,
        fillOpacity: 0.85
    }),

    onEachFeature: (feature, layer) => {
        layer.on('click', (e) => {
            handleFeatureClick('School', feature, e, {
                name:      feature.properties.instellingsnaam || 'Unknown',
                type:      feature.properties.school_type || 'Unknown',
                street:    feature.properties.straatnaam || 'N/A',
                city:      feature.properties.plaatsnaam || 'N/A',
                province:  feature.properties.provincie || 'N/A',
                latitude:  feature.geometry?.coordinates?.[1],
                longitude: feature.geometry?.coordinates?.[0]
            }, 'https://www.duo.nl/open_onderwijsdata/');
        });
    }
});

// 3I. Nature Network Netherlands / Natuurnetwerk Nederland (INSPIRE harmonized)
const nnnLayer = L.geoJSON(null, {
    style: { color: '#1e8449', weight: 2, fillColor: '#27ae60', fillOpacity: 0.25 },
    onEachFeature: (feature, layer) => {
        layer.on('click', (e) => {
            handleFeatureClick('Nature Network NL', feature, e, null, 'https://service.pdok.nl/provincies/natuurnetwerk-nederland/atom/index.xml');
        });
    }
});

// 3J. WFD Surface Water Bodies (INSPIRE harmonised — KRW)
const wfdSurfaceWaterLayer = L.geoJSON(null, {
    style: (feature) => {
        const geomType = feature.geometry?.type || '';
        if (geomType.includes('Polygon')) {
            return { color: '#117a65', weight: 2, fillColor: '#1abc9c', fillOpacity: 0.35 };
        }
        return { color: '#117a65', weight: 2, fillOpacity: 0 };
    },
    onEachFeature: (feature, layer) => {
        layer.on('click', (e) => {
            handleFeatureClick('WFD Surface Water Body', feature, e, null, 'https://service.pdok.nl/ihw/krw-oppervlaktewaterlichaams-geharmoniseerd/wms/v1_0');
        });
    }
});

// 3K. Water Hydrography (INSPIRE harmonized — Water Authorities)
const hydrographyLayer = L.geoJSON(null, {
    style: { color: '#1a6fa8', weight: 1.5, fillColor: '#2980b9', fillOpacity: 0.25 },
    pointToLayer: (feature, latlng) => L.circleMarker(latlng, {
        radius: 5,
        fillColor: '#1a6fa8',
        color: '#154360',
        weight: 1,
        fillOpacity: 0.85
    }),
    onEachFeature: (feature, layer) => {
        layer.on('click', (e) => {
            handleFeatureClick('Water Hydrography', feature, e, null, 'https://api.pdok.nl/hwh/waterschappen-hydrografie/ogc/v1');
        });
    }
});

// Registry linking HTML IDs to Leaflet Layer Objects
const layerRegistry = {
    'brp': brpLayer,
    'bag': bagLayer,
    'natura2000': natura2000Layer,
    'grenzen': grenzenLayer,
    'woondeals': woondealsLayer,
    'krd': krdLayer,
    'pesticides': pesticidesLayer,
    'health': healthLayer,
    'schools': schoolsLayer,
    'nnn': nnnLayer,
    'hydrography': hydrographyLayer,
    'wfd': wfdSurfaceWaterLayer
};


// =========================================================
// 4. Buffer Tool Engine
// =========================================================

function showRadiusPicker(feature, e) {
    pendingBufferFeature = feature;
    const picker = document.getElementById('radius-picker');
    const pt = map.latLngToContainerPoint(e.latlng);
    const rect = map.getContainer().getBoundingClientRect();
    picker.style.left = Math.min(rect.left + pt.x + 15, window.innerWidth - 200) + 'px';
    picker.style.top  = Math.max(rect.top  + pt.y - 80, 10) + 'px';
    picker.style.display = 'block';
}

function createBuffer(radiusKm) {
    if (!pendingBufferFeature) return;
    document.getElementById('radius-picker').style.display = 'none';

    const buffered = turf.buffer(pendingBufferFeature, radiusKm, { units: 'kilometers' });
    const id = ++bufferIdCounter;
    const label = radiusKm >= 1 ? radiusKm + 'km' : (radiusKm * 1000) + 'm';

    const mapLayer = L.geoJSON(buffered, {
        style: { color: '#e74c3c', weight: 2, fillColor: '#e74c3c', fillOpacity: 0.08, dashArray: '8, 4' },
        interactive: false
    }).addTo(map);

    const center = turf.centroid(buffered);
    const labelMarker = L.marker(
        [center.geometry.coordinates[1], center.geometry.coordinates[0]],
        {
            icon: L.divIcon({
                className: '',
                html: `<div style="background:rgba(255,255,255,0.9);padding:2px 8px;border-radius:3px;font-size:11px;font-weight:bold;border:1px solid #e74c3c;white-space:nowrap;">Buffer ${id}: ${label}</div>`,
                iconAnchor: [40, 8]
            }),
            interactive: false
        }
    ).addTo(map);

    activeBuffers.push({ id, polygon: buffered, mapLayer, labelMarker, radiusKm });
    pendingBufferFeature = null;
    document.getElementById('buffer-options').style.display = 'block';
    updateBufferList();
    applyBufferFilter();
}

function removeBuffer(id) {
    const idx = activeBuffers.findIndex(b => b.id === id);
    if (idx === -1) return;
    const buf = activeBuffers[idx];
    map.removeLayer(buf.mapLayer);
    map.removeLayer(buf.labelMarker);
    activeBuffers.splice(idx, 1);
    updateBufferList();
    applyBufferFilter();
}

function clearAllBuffers() {
    activeBuffers.forEach(b => { map.removeLayer(b.mapLayer); map.removeLayer(b.labelMarker); });
    activeBuffers = [];
    updateBufferList();
    applyBufferFilter();
}

function updateBufferList() {
    const list = document.getElementById('buffer-list');
    if (activeBuffers.length === 0) {
        list.innerHTML = '<em style="font-size:12px;color:#7f8c8d;">Click a feature to add a buffer.</em>';
        return;
    }
    list.innerHTML = activeBuffers.map(b => {
        const lbl = b.radiusKm >= 1 ? b.radiusKm + 'km' : (b.radiusKm * 1000) + 'm';
        const stats = b.bagStats
            ? `<div style="margin-top:4px;color:#34495e;line-height:1.35;">
                BAG: <strong>${b.bagStats.usageLocations}</strong> usage locations
                (<strong>${b.bagStats.residentialUsageLocations}</strong> residential),
                <strong>${b.bagStats.buildings}</strong> buildings<br>
                Loaded context: <strong>${b.bagStats.parcels}</strong> parcels,
                <strong>${b.bagStats.naturaAreas}</strong> Natura areas
            </div>`
            : '<div style="margin-top:4px;color:#7f8c8d;">BAG counts update after layer data loads.</div>';
        return `<div style="display:flex;justify-content:space-between;align-items:center;margin:4px 0;font-size:12px;padding:3px 0;border-bottom:1px solid #eee;">
            <span>Buffer ${b.id}: <strong>${lbl}</strong>${stats}</span>
            <button onclick="removeBuffer(${b.id})" style="background:#e74c3c;color:white;border:none;border-radius:3px;padding:1px 6px;cursor:pointer;font-size:11px;">✕</button>
        </div>`;
    }).join('');
}

function getBufferBbox() {
    const collection = turf.featureCollection(activeBuffers.map(b => b.polygon));
    const bbox = turf.bbox(collection);
    return `${bbox[0]},${bbox[1]},${bbox[2]},${bbox[3]}`;
}

function featurePassesFilter(feature) {
    if (activeBuffers.length === 0) return true;
    if (bufferMode === 'OR')  return activeBuffers.some(b  => turf.booleanIntersects(feature, b.polygon));
    else                      return activeBuffers.every(b => turf.booleanIntersects(feature, b.polygon));
}

function addFilteredData(layerObject, data) {
    if (!data || !data.features) return;
    if (activeBuffers.length === 0) { layerObject.addData(data); return; }
    layerObject.addData({ type: 'FeatureCollection', features: data.features.filter(featurePassesFilter) });
}

function isResidentialUsage(feature) {
    const usageGoal = feature.properties?.gebruiksdoel;
    const text = Array.isArray(usageGoal) ? usageGoal.join(',').toLowerCase() : String(usageGoal || '').toLowerCase();
    return text.includes('woonfunctie');
}

function safeIntersects(feature, polygon) {
    try {
        return turf.booleanIntersects(feature, polygon);
    } catch (error) {
        return false;
    }
}

function getBagBuildingRelationships(feature) {
    const usageLocations = bagUsageCache?.features || [];
    const parcels = brpCache?.features || [];
    const naturaAreas = (natura2000Cache?.features || []).filter(item => item.properties?.layer_type !== 'buffer' && item.properties?.layer_type !== 'center');
    const buildingId = feature.properties?.identificatie || feature.properties?.id;
    const linkedUsageLocations = usageLocations.filter(item => {
        const pandId = item.properties?.pand_identificatie || item.properties?.pandIdentificatie;
        if (buildingId && pandId && String(pandId) === String(buildingId)) return true;
        return safeIntersects(item, feature);
    });

    return {
        usage_locations_in_building: linkedUsageLocations.length,
        residential_usage_locations_in_building: linkedUsageLocations.filter(isResidentialUsage).length,
        intersecting_loaded_parcels: parcels.filter(item => safeIntersects(item, feature)).length,
        intersecting_loaded_natura_areas: naturaAreas.filter(item => safeIntersects(item, feature)).length
    };
}

function refreshBagBufferSummaries() {
    if (activeBuffers.length === 0 || typeof turf === 'undefined') return;

    const usageLocations = bagUsageCache?.features || [];
    const buildings = bagBuildingCache?.features || [];
    const parcels = brpCache?.features || [];
    const naturaAreas = (natura2000Cache?.features || []).filter(item => item.properties?.layer_type !== 'buffer' && item.properties?.layer_type !== 'center');

    activeBuffers.forEach(buffer => {
        buffer.bagStats = {
            usageLocations: usageLocations.filter(item => safeIntersects(item, buffer.polygon)).length,
            residentialUsageLocations: usageLocations.filter(item => isResidentialUsage(item) && safeIntersects(item, buffer.polygon)).length,
            buildings: buildings.filter(item => safeIntersects(item, buffer.polygon)).length,
            parcels: parcels.filter(item => safeIntersects(item, buffer.polygon)).length,
            naturaAreas: naturaAreas.filter(item => safeIntersects(item, buffer.polygon)).length
        };
    });

    updateBufferList();
}

function buildNatura2000DisplayData(data, bufferKm = NATURA2000_BUFFER_KM) {
    if (!data || !Array.isArray(data.features)) return data;
    if (data.features.some(feature => feature.properties?.layer_type)) return data;
    if (typeof turf === 'undefined') return data;

    const features = [];

    data.features.forEach((feature, index) => {
        if (!feature || !feature.geometry) return;

        const baseProperties = {
            ...(feature.properties || {}),
            area_id: feature.id || feature.properties?.id || feature.properties?.objectid || index,
            buffer_km: bufferKm
        };

        try {
            const simplifiedFeature = turf.simplify(feature, {
                tolerance: 0.0001,
                highQuality: false,
                mutate: false
            });
            const bufferFeature = turf.buffer(simplifiedFeature, bufferKm, {
                units: 'kilometers',
                steps: 8
            });
            bufferFeature.properties = { ...baseProperties, layer_type: 'buffer' };
            features.push(bufferFeature);
        } catch (error) {
            console.warn('Could not create Natura 2000 buffer:', error);
        }

        features.push({
            type: 'Feature',
            properties: { ...baseProperties, layer_type: 'area' },
            geometry: feature.geometry
        });

        try {
            const centerFeature = turf.pointOnFeature(feature);
            centerFeature.properties = { ...baseProperties, layer_type: 'center' };
            features.push(centerFeature);
        } catch (error) {
            console.warn('Could not create Natura 2000 center point:', error);
        }
    });

    return { type: 'FeatureCollection', features };
}

function prepareLayerData(layerObject, data) {
    if (layerObject === natura2000Layer) return buildNatura2000DisplayData(data);
    return data;
}

function applyBufferFilter() {
    if (map.hasLayer(natura2000Layer) && natura2000Cache) {
        natura2000Layer.clearLayers();
        addFilteredData(natura2000Layer, natura2000Cache);
    }
    if (map.hasLayer(woondealsLayer) && woondealsCache) {
        woondealsLayer.clearLayers();
        addFilteredData(woondealsLayer, woondealsCache);
    }
    if (map.hasLayer(grenzenLayer) && grenzenCache) {
        grenzenLayer.clearLayers();
        addFilteredData(grenzenLayer, grenzenCache);
    }
    if (map.hasLayer(nnnLayer) && nnnCache) {
        nnnLayer.clearLayers();
        addFilteredData(nnnLayer, nnnCache);
    }
    if (map.hasLayer(bagLayer) && bagBuildingCache) {
        bagLayer.clearLayers();
        addFilteredData(bagLayer, bagBuildingCache);
    }
    if (map.hasLayer(bagUsageLayer) && bagUsageCache) {
        bagUsageLayer.clearLayers();
        addFilteredData(bagUsageLayer, bagUsageCache);
    }
    refreshBagBufferSummaries();
    map.fire('moveend');
}

// =========================================================
// 5. Custom UI Control Panel Integration & Nationwide Loading
// =========================================================

// State flags to ensure we only download nationwide data ONCE
let isNaturaLoaded = false;
let isWoondealsLoaded = false;
let isGrenzenLoaded = false;
let isNNNLoaded = false;

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
        
        const data = prepareLayerData(layerObject, await response.json());
        if (data.features && data.features.length > 0) {
            if (layerObject === bagLayer) bagBuildingCache = data;
            if (layerObject === natura2000Layer) natura2000Cache = data;
            if (layerObject === woondealsLayer)  woondealsCache  = data;
            if (layerObject === grenzenLayer)     grenzenCache    = data;
            if (layerObject === nnnLayer)         nnnCache        = data;
            addFilteredData(layerObject, data);
            refreshBagBufferSummaries();
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
            const fallbackData = prepareLayerData(layerObject, await fallbackResponse.json());

            if (fallbackData.features && fallbackData.features.length > 0) {
                if (layerObject === bagLayer) bagBuildingCache = fallbackData;
                if (layerObject === natura2000Layer) natura2000Cache = fallbackData;
                if (layerObject === woondealsLayer)  woondealsCache  = fallbackData;
                if (layerObject === grenzenLayer)     grenzenCache    = fallbackData;
                if (layerObject === nnnLayer)         nnnCache        = fallbackData;
                addFilteredData(layerObject, fallbackData);
                refreshBagBufferSummaries();
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
    const naturaActive = document.getElementById('layer-natura2000').checked;
    const bagActive = document.getElementById('layer-bag').checked;

    document.getElementById('map-legend').style.display      = (healthActive || pesticidesActive || naturaActive || bagActive) ? 'block' : 'none';
    document.getElementById('legend-bag').style.display = bagActive ? 'block' : 'none';
    document.getElementById('legend-natura2000').style.display = naturaActive ? 'block' : 'none';
    document.getElementById('legend-health').style.display    = healthActive     ? 'block' : 'none';
    document.getElementById('legend-pesticides').style.display = pesticidesActive ? 'block' : 'none';
    document.getElementById('legend-divider').style.display = (bagActive && (naturaActive || healthActive || pesticidesActive)) ? 'block' : 'none';
    document.getElementById('legend-divider-tertiary').style.display = (naturaActive && (healthActive || pesticidesActive)) ? 'block' : 'none';
    document.getElementById('legend-divider-secondary').style.display = (healthActive && pesticidesActive) ? 'block' : 'none';
}

// Checkbox Toggles
document.querySelectorAll('.map-layer-toggle').forEach(checkbox => {
    checkbox.addEventListener('change', async function() {
        const layerId = this.value;
        const layer = layerRegistry[layerId];

        if (this.checked) {
            layer.addTo(map);
            if (layerId === 'bag') bagUsageLayer.addTo(map);
            
            // CRS84 forces WFS to return standard [Lon, Lat] GeoJSON, preventing the ocean bug
            const crs84 = 'urn:ogc:def:crs:OGC:1.3:CRS84';

            if (layerId === 'natura2000') {
                natura2000WmsLayer.addTo(map);
                layer.clearLayers();
                map.fire('moveend');
            } 
            else if (layerId === 'woondeals') {
                const woondealsApi = `https://service.pdok.nl/bzk/regionale-woondeals/wfs/v1_0?request=GetFeature&service=WFS&version=2.0.0&typeName=regionale_woondeals:woondeals&outputFormat=application/json&srsName=${crs84}`;
                const woondealsDb = `/api/woondeals?bbox=${bboxNetherlands}`;
                await loadNationwideLayer(layer, 'Woondeals', woondealsApi, woondealsDb, 'isWoondealsLoaded');
            }
            else if (layerId === 'grenzen') {
                const grenzenDb = `/api/grenzen?bbox=${bboxNetherlands}`;
                await loadNationwideLayer(layer, 'Grenzen', grenzenDb, grenzenDb, 'isGrenzenLoaded');
            }
            else if (layerId === 'nnn') {
                const nnnDb = `/api/nnn?bbox=${bboxNetherlands}`;
                await loadNationwideLayer(layer, 'Nature Network NL', nnnDb, nnnDb, 'isNNNLoaded');
            }
            else {
                // Trigger BRP and BAG dynamic loading
                map.fire('moveend'); 
            }
        } else {
            map.removeLayer(layer);
            if (layerId === 'bag') {
                map.removeLayer(bagUsageLayer);
                bagLayer.clearLayers();
                bagUsageLayer.clearLayers();
                bagBuildingCache = null;
                bagUsageCache = null;
                refreshBagBufferSummaries();
            }
            if (layerId === 'natura2000') {
                map.removeLayer(natura2000WmsLayer);
                layer.clearLayers();
                natura2000Cache = null;
            }
            document.getElementById('info-panel').classList.add('hidden');
            // We do NOT clear data for Natura/Woondeals so they remain instantly visible next time
            if (layerId === 'brp' || layerId === 'bag') {
                layer.clearLayers();
            }
            if (layerId === 'brp') {
                brpCache = null;
                refreshBagBufferSummaries();
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

    const bboxPostGIS = `${bounds.getWest()},${bounds.getSouth()},${bounds.getEast()},${bounds.getNorth()}`;
    const effectiveBbox = activeBuffers.length > 0 ? getBufferBbox() : bboxPostGIS;
    
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

            const data = prepareLayerData(layerObject, await response.json());
            
            if (data.features && data.features.length > 0) {
                layerObject.clearLayers();
                if (layerObject === bagLayer) bagBuildingCache = data;
                if (layerObject === natura2000Layer) natura2000Cache = data;
                if (layerObject === woondealsLayer)  woondealsCache  = data;
                if (layerObject === grenzenLayer)     grenzenCache    = data;
                if (layerObject === nnnLayer)         nnnCache        = data;
                addFilteredData(layerObject, data);
                refreshBagBufferSummaries();
                console.log(`[${layerName}] ✅ Loaded dynamically from PDOK API.`);
                return;
            } else {
                throw new Error("API returned 0 features.");
            }
        } catch (error) {
            console.warn(`[${layerName}] ⚠️ API skipped (${error.message}). Switching to Local DB Fallback...`);

            try {
                const finalDbUrl = isNationwide ? fallbackDbUrl.replace(bboxPostGIS, bboxNetherlands) : fallbackDbUrl;

                const fallbackResponse = await fetch(finalDbUrl);
                if (!fallbackResponse.ok) {
                    const errText = await fallbackResponse.text();
                    throw new Error(`DB Error ${fallbackResponse.status}: ${errText}`);
                }
                const fallbackData = prepareLayerData(layerObject, await fallbackResponse.json());

                layerObject.clearLayers();
                if (layerObject === bagLayer) bagBuildingCache = fallbackData;
                if (fallbackData.features && fallbackData.features.length > 0) {
                    if (layerObject === natura2000Layer) natura2000Cache = fallbackData;
                    if (layerObject === woondealsLayer)  woondealsCache  = fallbackData;
                    if (layerObject === grenzenLayer)     grenzenCache    = fallbackData;
                    if (layerObject === nnnLayer)         nnnCache        = fallbackData;
                    addFilteredData(layerObject, fallbackData);
                    refreshBagBufferSummaries();
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
        fetch(`/api/brp_parcels?bbox=${effectiveBbox}&year=${getYear('brp')}`)
            .then(res => res.json())
            .then(data => {
                brpCache = data;
                brpLayer.clearLayers();
                addFilteredData(brpLayer, data);
                refreshBagBufferSummaries();
            })
            .catch(e => console.error("BRP Error:", e));
    }

    // ==========================================
    // 2. BAG Buildings + Usage Locations
    // ==========================================
    if (map.hasLayer(bagLayer) && map.getZoom() < BAG_DETAIL_MIN_ZOOM) {
        bagLayer.clearLayers();
        bagUsageLayer.clearLayers();
        bagBuildingCache = null;
        bagUsageCache = null;
        refreshBagBufferSummaries();
    } else {
        const bagApi = `https://api.pdok.nl/kadaster/bag/ogc/v2/collections/pand/items?f=json&limit=${BAG_API_LIMIT}&bbox=${bboxPostGIS}`;
        const bagDb = `/api/bag_buildings?bbox=${effectiveBbox}&year=${getYear('bag')}`;
        loadDataWithFallback(bagLayer, 'BAG Buildings', bagApi, bagDb, false);

        if (map.hasLayer(bagUsageLayer)) {
            fetch(`https://api.pdok.nl/kadaster/bag/ogc/v2/collections/verblijfsobject/items?f=json&limit=${BAG_USAGE_API_LIMIT}&bbox=${effectiveBbox}`)
                .then(res => {
                    if (!res.ok) throw new Error(`HTTP Error ${res.status}`);
                    return res.json();
                })
                .then(data => {
                    bagUsageCache = data;
                    bagUsageLayer.clearLayers();
                    addFilteredData(bagUsageLayer, data);
                    refreshBagBufferSummaries();
                })
                .catch(e => console.error("BAG Usage Locations Error:", e));
        }
    }

    // ==========================================
    // 3. Natura 2000 (PDOK API with calculated buffers and center pins)
    // ==========================================
    if (map.hasLayer(natura2000Layer) && map.getZoom() < NATURA2000_DETAIL_MIN_ZOOM) {
        natura2000Layer.clearLayers();
        natura2000Cache = null;
    } else {
        const naturaApi = `https://api.pdok.nl/rvo/natura2000/ogc/v1/collections/natura2000/items?f=json&limit=${NATURA2000_API_LIMIT}&bbox=${bboxPostGIS}`;
        const naturaDb = `/api/natura2000_areas?bbox=${effectiveBbox}`;

        loadDataWithFallback(natura2000Layer, 'Natura 2000', naturaApi, naturaDb, false);
    }

    // ==========================================
    // 5. KRD Livestock Farms (Local DB Only)
    // ==========================================
    if (map.hasLayer(krdLayer)) {
        fetch(`/api/krd_farms?bbox=${effectiveBbox}`)
            .then(res => res.json())
            .then(data => { krdLayer.clearLayers(); addFilteredData(krdLayer, data); })
            .catch(e => console.error("KRD Error:", e));
    }

    if (map.hasLayer(pesticidesLayer)) {
        fetch(`/api/pesticides?bbox=${effectiveBbox}`)
            .then(res => res.json())
            .then(data => { pesticidesLayer.clearLayers(); addFilteredData(pesticidesLayer, data); })
            .catch(e => console.error("Pesticides Error:", e));
    }

    if (map.hasLayer(healthLayer)) {
        fetch(`/api/health_facilities?bbox=${effectiveBbox}`)
            .then(res => res.json())
            .then(data => { healthLayer.clearLayers(); addFilteredData(healthLayer, data); })
            .catch(e => console.error("Health Facilities Error:", e));
    }

    if (map.hasLayer(schoolsLayer)) {
        fetch(`/api/schools?bbox=${effectiveBbox}`)
            .then(res => res.json())
            .then(data => { schoolsLayer.clearLayers(); addFilteredData(schoolsLayer, data); })
            .catch(e => console.error("Schools Error:", e));
    }

    // ==========================================
    // Water Hydrography (OGC API primary → DB fallback)
    // Collection: watercourse (INSPIRE HY theme)
    // ==========================================
    const hydrographyApi = `https://api.pdok.nl/hwh/waterschappen-hydrografie/ogc/v1/collections/watercourse/items?f=json&limit=10000&bbox=${bboxPostGIS}`;
    const hydrographyDb  = `/api/hydrography?bbox=${effectiveBbox}`;
    loadDataWithFallback(hydrographyLayer, 'Water Hydrography', hydrographyApi, hydrographyDb, false);

    if (map.hasLayer(wfdSurfaceWaterLayer)) {
        fetch(`/api/wfd_surface_water?bbox=${effectiveBbox}`)
            .then(res => res.json())
            .then(data => { wfdSurfaceWaterLayer.clearLayers(); addFilteredData(wfdSurfaceWaterLayer, data); })
            .catch(e => console.error("WFD Surface Water Error:", e));
    }

    // ==========================================
    // 4. Regionale Woondeals (Nationwide)
    // FACT: PDOK does NOT have a WFS for Woondeals. This API fetch will deliberately fail to trigger DB fallback.
    // ==========================================
    const woondealsApi = `https://service.pdok.nl/bzk/regionale-woondeals/wfs/v1_0?request=GetFeature&service=WFS&version=2.0.0&typeName=woondeals&outputFormat=application/json`;
    const woondealsDb = `/api/woondeals?bbox=${bboxPostGIS}`;
    loadDataWithFallback(woondealsLayer, 'Woondeals', woondealsApi, woondealsDb, true);

    // ==========================================
    // Grenzen (Administrative Boundaries - DB only)
    // ==========================================
    const grenzenDb = `/api/grenzen?bbox=${bboxPostGIS}`;
    loadDataWithFallback(grenzenLayer, 'Grenzen', grenzenDb, grenzenDb, true);
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
        columns: { "stof_naam": "Substance", "year": "Year", "norm_type": "Norm Type", "klasse_omschrijving": "Result", "exceedance_ratio": "Exceedance Ratio" }
    },
    {
        layerObject: healthLayer, sheetName: "Health Facilities",
        buildUrl: (bbox) => `/api/health_facilities?bbox=${bbox}`,
        columns: { "name": "Name", "facility_type": "Type", "addr_city": "City", "operator_type": "Operator" }
    },
    {
        layerObject: schoolsLayer, sheetName: "Schools",
        buildUrl: (bbox) => `/api/schools?bbox=${bbox}`,
        columns: { "instellingsnaam": "School Name", "school_type": "Type", "plaatsnaam": "City", "provincie": "Province" }
    },
    {
        layerObject: nnnLayer, sheetName: "Nature Network NL",
        buildUrl: (bbox) => `/api/nnn?bbox=${bbox}`,
        columns: { "inspireid": "INSPIRE ID", "siteprotectionclassification": "Protection Type", "legalfoundationname": "Legal Basis" }
    },
    {
        layerObject: hydrographyLayer, sheetName: "Water Hydrography",
        buildUrl: (bbox) => `/api/hydrography?bbox=${bbox}`,
        columns: { "localid": "Local ID", "name": "Name", "streamorder": "Stream Order" }
    },
    {
        layerObject: wfdSurfaceWaterLayer, sheetName: "WFD Surface Water",
        buildUrl: (bbox) => `/api/wfd_surface_water?bbox=${bbox}`,
        columns: { "name": "Water Body Name", "specialisedzonetype": "Zone Type", "competentauthority": "Authority" }
    }
];

// =========================================================
// 7. Buffer Tool Event Listeners
// =========================================================

document.getElementById('buffer-tool-btn').addEventListener('click', function() {
    bufferToolActive = !bufferToolActive;
    if (bufferToolActive) {
        this.textContent = '🔴 Buffer Tool ON';
        this.style.backgroundColor = '#e74c3c';
        document.getElementById('buffer-options').style.display = 'block';
        document.getElementById('map').style.cursor = 'crosshair';
        updateBufferList();
    } else {
        this.textContent = '⭕ Buffer Tool';
        this.style.backgroundColor = '#2c3e50';
        document.getElementById('radius-picker').style.display = 'none';
        document.getElementById('map').style.cursor = '';
        pendingBufferFeature = null;
        clearAllBuffers();
    }
});

document.getElementById('buffer-mode-or').addEventListener('click', function() {
    bufferMode = 'OR';
    this.style.cssText = 'flex:1;padding:5px;cursor:pointer;font-weight:bold;background:#2c3e50;color:white;border:none;border-radius:3px;font-size:12px;';
    const andBtn = document.getElementById('buffer-mode-and');
    andBtn.style.cssText = 'flex:1;padding:5px;cursor:pointer;background:#ecf0f1;border:1px solid #bdc3c7;border-radius:3px;font-size:12px;';
    if (activeBuffers.length > 0) applyBufferFilter();
});

document.getElementById('buffer-mode-and').addEventListener('click', function() {
    bufferMode = 'AND';
    this.style.cssText = 'flex:1;padding:5px;cursor:pointer;font-weight:bold;background:#2c3e50;color:white;border:none;border-radius:3px;font-size:12px;';
    const orBtn = document.getElementById('buffer-mode-or');
    orBtn.style.cssText = 'flex:1;padding:5px;cursor:pointer;background:#ecf0f1;border:1px solid #bdc3c7;border-radius:3px;font-size:12px;';
    if (activeBuffers.length > 0) applyBufferFilter();
});

document.querySelectorAll('.radius-btn').forEach(btn => {
    btn.addEventListener('click', function() { createBuffer(parseFloat(this.dataset.km)); });
});

document.getElementById('custom-radius-btn').addEventListener('click', function() {
    const val = parseFloat(document.getElementById('custom-radius').value);
    if (val > 0) { createBuffer(val); document.getElementById('custom-radius').value = ''; }
});

document.getElementById('cancel-radius-btn').addEventListener('click', function() {
    document.getElementById('radius-picker').style.display = 'none';
    pendingBufferFeature = null;
});

document.getElementById('clear-buffers-btn').addEventListener('click', clearAllBuffers);

map.on('click', function() {
    document.getElementById('info-panel').classList.add('hidden');
    if (bufferToolActive) {
        document.getElementById('radius-picker').style.display = 'none';
        pendingBufferFeature = null;
    }
});

// =========================================================
// 8. Excel Export
// =========================================================

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
