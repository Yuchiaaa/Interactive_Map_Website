// =========================================================
// 1. Map Initialization & Base Layer
// =========================================================
const map = L.map('map', {
    center: [52.336, 4.653], // Haarlemmermeer
    zoom: 15,
    minZoom: 5,
    preferCanvas: true, // Crucial for rendering thousands of local polygons
    zoomControl: false
});
L.control.zoom({ position: 'topright' }).addTo(map);

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
let grenzenCache = null;
let nnnCache = null;
let kadastraalPerceelCache = null;
let brpCache = null;
let pesticidesCache = null;
const BAG_API_LIMIT = 2000;
const BAG_USAGE_API_LIMIT = 3000;
const BAG_DETAIL_MIN_ZOOM = 14;
let n2000BufferKm = 0.5;
const NATURA2000_API_LIMIT = 250;
const NATURA2000_DETAIL_MIN_ZOOM = 9;
const CADASTRAL_MIN_ZOOM = 14;

// KRD → Natura 2000 distance filter state
let krdN2000FilterKm = 0;
let n2000KrdBufferCache = { km: -1, count: -1, buffers: [] };

// =========================================================
// Dataset Info Metadata
// =========================================================
const DATASET_INFO = {
    brp: {
        name:        'BRP Crop Parcels',
        summary:     'The Basisregistratie Gewaspercelen (BRP) registers all agricultural parcels and their declared crops across the Netherlands each year. Used for EU subsidy administration and agricultural policy monitoring.',
        lastUpdated: 'Annually (latest: 2024)',
        source:      'RVO / Nationaal Georegister',
        readMore:    'https://www.nationaalgeoregister.nl/geonetwork/srv/dut/catalog.search#/metadata/44e6d4d3-8fc5-47d6-8712-33dd6d244eef'
    },
    bag: {
        name:        'BAG Buildings',
        summary:     'The Basisregistraties Adressen en Gebouwen (BAG) is the national register of all addresses and buildings in the Netherlands, including construction year, usage type, and official status.',
        lastUpdated: 'Continuously updated',
        source:      'Kadaster / PDOK',
        readMore:    'https://www.pdok.nl/introductie/-/article/basisregistraties-adressen-en-gebouwen-bag-'
    },
    natura2000: {
        name:        'Natura 2000',
        summary:     'EU-designated protected nature areas under the Birds and Habitats Directives. Activities within or near these boundaries are subject to strict environmental permit requirements.',
        lastUpdated: 'Periodically updated',
        source:      'Ministerie van LNV / PDOK',
        readMore:    'https://www.pdok.nl/introductie/-/article/natura2000'
    },
    nnn: {
        name:        'Nature Network Netherlands (NNN)',
        summary:     'The Natuurnetwerk Nederland (NNN) is a national network of nature areas aimed at protecting and connecting biodiversity, defined per province under the Dutch Nature Protection Act.',
        lastUpdated: 'Periodically updated per province',
        source:      'Provincies / PDOK INSPIRE',
        readMore:    'https://service.pdok.nl/provincies/natuurnetwerk-nederland/atom/index.xml'
    },
    kadastralekaart: {
        name:        'Kadastrale Kaart',
        summary:     'The Kadastrale Kaart shows official cadastral parcel boundaries and sizes across the Netherlands. Essential for identifying land ownership in legal and environmental disputes.',
        lastUpdated: 'Continuously updated',
        source:      'Kadaster / PDOK',
        readMore:    'https://www.nationaalgeoregister.nl/geonetwork/srv/dut/catalog.search#/metadata/a29917b9-3426-4041-a11b-69bcb2256904'
    },
    grenzen: {
        name:        'Bestuurlijke Grenzen',
        summary:     'Official administrative boundaries of Dutch municipalities, provinces, and the national border, sourced from the Basisregistratie Kadaster (BRK).',
        lastUpdated: 'Annually',
        source:      'Kadaster / PDOK',
        readMore:    'https://www.pdok.nl/introductie/-/article/bestuurlijke-grenzen'
    },
    krd: {
        name:        'KRD Veehouderijen',
        summary:     'Registered livestock farms in the Netherlands with their NH3 (ammonia), odour, and particulate matter emission values. Used in legal assessments of cumulative farm impact on nature areas.',
        lastUpdated: '2023',
        source:      'KRD / iGoView',
        readMore:    'https://krd.igoview.nl/'
    },
    pesticides: {
        name:        'Pesticides Atlas',
        summary:     'Pesticide concentration measurements in Dutch surface water from the Bestrijdingsmiddelenatlas, showing which substances exceed environmental quality standards and by how much.',
        lastUpdated: 'Annually (latest: 2022)',
        source:      'Bestrijdingsmiddelenatlas',
        readMore:    'https://www.bestrijdingsmiddelenatlas.nl/'
    },
    health: {
        name:        'Health Facilities',
        summary:     'Locations of hospitals, clinics, pharmacies, and other health facilities in the Netherlands, derived from OpenStreetMap contributions via the Humanitarian OpenStreetMap Team (HOTOSM).',
        lastUpdated: 'Continuously updated via OSM',
        source:      'HOTOSM / OpenStreetMap',
        readMore:    'https://data.humdata.org/dataset/hotosm-nld-health-facilities'
    },
    schools: {
        name:        'Schools',
        summary:     'All registered educational institutions in the Netherlands — from primary schools (basisonderwijs) to universities — as registered by DUO (Dienst Uitvoering Onderwijs).',
        lastUpdated: '2024',
        source:      'DUO — Dienst Uitvoering Onderwijs',
        readMore:    'https://www.duo.nl/open_onderwijsdata/'
    },
    hydrography: {
        name:        'Water Hydrography',
        summary:     'INSPIRE-harmonised watercourse data from Dutch water authorities (waterschappen), covering rivers, canals, and drainage channels with stream order and condition attributes.',
        lastUpdated: 'Periodically updated',
        source:      'Waterschappen / PDOK INSPIRE',
        readMore:    'https://api.pdok.nl/hwh/waterschappen-hydrografie/ogc/v1'
    },
    wfd: {
        name:        'WFD Surface Water',
        summary:     'Water Framework Directive (WFD) surface water body boundaries covering rivers, lakes, and coastal waters assessed for ecological and chemical status under EU law.',
        lastUpdated: 'Per WFD reporting cycle (6 years)',
        source:      'Rijkswaterstaat / INSPIRE',
        readMore:    'https://service.pdok.nl/ihw/krw-oppervlaktewaterlichaams-geharmoniseerd/wms/v1_0'
    },
    waterschappen: {
        name:        'Waterschappen',
        summary:     'Administrative boundary areas of the 21 Dutch water authorities (waterschappen), responsible for water management, flood protection, and water quality.',
        lastUpdated: 'Periodically updated',
        source:      'Unie van Waterschappen / PDOK',
        readMore:    'https://api.pdok.nl/hwh/waterschappen/ogc/v1'
    }
};

// Returns a hex colour for a KRD farm based on the 'bedrijfstype' field (animal type).
// Colours match the sidebar legend and the map legend — keep them in sync if you change one.
// 'bedrijfstype' values come directly from the KRD export (Dutch strings like 'Vleesvarkens').
// Returns a hex colour for a KRD farm based on the 'bedrijfstype' field (animal type).
// Colours match the sidebar legend and the map legend — keep them in sync if you change one.
// 'bedrijfstype' values come directly from the KRD export (Dutch strings like 'Vleesvarkens').
//
// Spelling note: Dutch plurals drop letters — "dekbeer" (boar) → "dekberen", not "dekbeeren";
// "schaap" (sheep) → "schapen", not "schaaapen". Both forms must be matched explicitly.
function getKrdColor(bedrijfstype) {
    if (!bedrijfstype) return '#95a5a6';
    const t = bedrijfstype.toLowerCase();
    if (t.includes('varken') || t.includes('zeug') || t.includes('bigg') || t.includes('dekbeer') || t.includes('dekberen')) return '#e74c3c';
    if (t.includes('rundvee') || t.includes('melk') || t.includes('vleesvee'))                                               return '#8b5e3c';
    if (t.includes('pluimvee') || t.includes('leghen') || t.includes('kuiken'))                                              return '#f39c12';
    if (t.includes('geit') || t.includes('schaap') || t.includes('schapen'))                                                 return '#1abc9c';
    if (t.includes('paard'))                                                                                                  return '#3498db';
    if (t.includes('konijn') || t.includes('nerts'))                                                                         return '#9b59b6';
    return '#95a5a6';
}

// Returns an emoji for the animal type — used alongside getKrdColor() in the map marker.
// Goats and sheep share a colour but get distinct icons so you can tell them apart.
// Same Dutch plural spelling fixes apply here as in getKrdColor().
function getKrdEmoji(bedrijfstype) {
    if (!bedrijfstype) return '❓';
    const t = bedrijfstype.toLowerCase();
    if (t.includes('varken') || t.includes('zeug') || t.includes('bigg') || t.includes('dekbeer') || t.includes('dekberen')) return '🐷';
    if (t.includes('rundvee') || t.includes('melk') || t.includes('vleesvee'))                                               return '🐄';
    if (t.includes('pluimvee') || t.includes('leghen') || t.includes('kuiken'))                                              return '🐔';
    if (t.includes('geit'))                                                                                                   return '🐐';
    if (t.includes('schaap') || t.includes('schapen'))                                                                       return '🐑';
    if (t.includes('paard'))                                                                                                  return '🐴';
    if (t.includes('konijn') || t.includes('nerts'))                                                                         return '🐰';
    // ❓ = animal type unknown or unclassifiable — NULL from Gelderland/Twente export,
    //      'Overige' (no standard category), or 'zeer gering van omvang' (regulatory label).
    //      These are real active farms with real emissions, just uncategorised.
    return '❓';
}

// Seven crop categories with their display label, filter key, and hex colour.
// These must match the filter chips in the sidebar and the map legend in the HTML.
const CROP_CATEGORIES = [
    { key: 'grassland', label: 'Grassland',      color: '#27ae60' },
    { key: 'maize',     label: 'Maize',           color: '#f1c40f' },
    { key: 'potato',    label: 'Potato',           color: '#d35400' },
    { key: 'wheat',     label: 'Wheat / Grain',   color: '#e67e22' },
    { key: 'beets',     label: 'Beets',            color: '#8e44ad' },
    { key: 'flowers',   label: 'Flowers / Bulbs', color: '#e74c3c' },
    { key: 'other',     label: 'Other',            color: '#3498db' },
];

// Returns the hex colour for a Dutch gewas name.
function getCropColor(cropName) {
    if (!cropName) return '#7f8c8d';
    const name = cropName.toLowerCase();
    if (name.includes('gras') || name.includes('weide')) return '#27ae60';
    if (name.includes('mais') || name.includes('maïs')) return '#f1c40f';
    if (name.includes('aardappel'))                      return '#d35400';
    if (name.includes('tarwe') || name.includes('graan')) return '#e67e22';
    if (name.includes('bieten'))                          return '#8e44ad';
    if (name.includes('bloem') || name.includes('bollen')) return '#e74c3c';
    return '#3498db';
}

// Sidebar Engine: Injects clicked feature properties into the HTML panel
function showFeatureInfo(layerName, properties, sourceUrl) {
    const infoPanel    = document.getElementById('info-panel');
    const panelTitle   = document.getElementById('panel-title');
    const panelContent = document.getElementById('panel-content');
    if (!infoPanel || !panelTitle || !panelContent) return;

    panelTitle.innerText   = layerName;
    panelContent.innerHTML = '';

    const SKIP = new Set(['id', 'geometry', 'layer_type', 'buffer_km']);

    for (const [key, value] of Object.entries(properties)) {
        if (SKIP.has(key)) continue;

        const row = document.createElement('div');
        row.className = 'data-row';

        const keyDiv = document.createElement('div');
        keyDiv.className  = 'data-key';
        keyDiv.innerText  = key;

        const valueDiv = document.createElement('div');
        valueDiv.className = 'data-value';
        valueDiv.innerText = (value !== null && value !== undefined && value !== '') ? value : '—';

        row.appendChild(keyDiv);
        row.appendChild(valueDiv);
        panelContent.appendChild(row);
    }

    if (sourceUrl) {
        const link = document.createElement('a');
        link.href      = sourceUrl;
        link.target    = '_blank';
        link.rel       = 'noopener noreferrer';
        link.className = 'panel-source-btn';
        link.innerText = '↗ View Data Source';
        panelContent.appendChild(link);
    }

    infoPanel.classList.remove('hidden');
}

function handleFeatureClick(layerName, feature, e, customProperties, sourceUrl) {
    L.DomEvent.stopPropagation(e);
    showFeatureInfo(layerName, customProperties || feature.properties, sourceUrl);
    if (bufferToolActive) {
        const geomType = feature?.geometry?.type;
        if (geomType === 'Polygon' || geomType === 'MultiPolygon') {
            const panelContent = document.getElementById('panel-content');
            if (panelContent) {
                const btn = document.createElement('button');
                btn.className = 'panel-source-btn';
                btn.style.cssText = 'background:#1B512D;color:#DEF4C6;border:none;margin-top:8px;width:100%;';
                btn.innerText = '⬡ Use Boundary as Area Filter';
                btn.onclick = () => {
                    const areaName = feature.properties?.gemeentenaam
                        || feature.properties?.naam
                        || feature.properties?.name
                        || layerName;
                    createBoundaryFilter(feature, areaName);
                };
                panelContent.appendChild(btn);
            }
        }
        showRadiusPicker(feature, e);
    }
}

// Appends a linked-data section below the main sidebar properties
function appendSidebarSection(title, rows) {
    const panelContent = document.getElementById('panel-content');
    if (!panelContent) return;

    const section = document.createElement('div');
    section.style.cssText = 'margin-top: 12px; border-top: 2px solid #2c3e50; padding-top: 8px;';

    const header = document.createElement('div');
    header.style.cssText = 'font-weight: bold; color: #2c3e50; margin-bottom: 6px; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px;';
    header.innerText = title;
    section.appendChild(header);

    if (rows.length === 0) {
        const empty = document.createElement('div');
        empty.style.cssText = 'font-size: 12px; color: #7f8c8d; font-style: italic; padding: 4px 0;';
        empty.innerText = 'No linked data found in viewport.';
        section.appendChild(empty);
    } else {
        rows.forEach(item => {
            if (typeof item === 'string') {
                // Sub-header row (parcel label etc.)
                const sub = document.createElement('div');
                sub.style.cssText = 'font-size: 11px; font-weight: bold; color: #7f8c8d; margin: 6px 0 2px; text-transform: uppercase;';
                sub.innerText = item;
                section.appendChild(sub);
            } else {
                const [key, value] = item;
                const row = document.createElement('div');
                row.style.cssText = 'display: flex; justify-content: space-between; padding: 3px 0; border-bottom: 1px solid #eee; font-size: 13px;';
                const keyDiv = document.createElement('div');
                keyDiv.style.fontWeight = 'bold';
                keyDiv.innerText = key;
                const valueDiv = document.createElement('div');
                valueDiv.style.cssText = 'text-align: right; max-width: 60%;';
                valueDiv.innerText = value !== null && value !== undefined ? String(value) : 'N/A';
                row.appendChild(keyDiv);
                row.appendChild(valueDiv);
                section.appendChild(row);
            }
        });
    }
    panelContent.appendChild(section);
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
        layer.on('click', async function(e) {
            const p = feature.properties || {};
            // Build a clean display object so the sidebar shows human-readable labels
            // and a pre-formatted area value instead of raw keys like 'area_ha'.
            const displayProps = {
                'Year':      p.jaar     ?? '—',
                'Crop':      p.gewas    ?? '—',
                'Crop Code': p.gewascode ?? '—',
                'Area':      p.area_ha != null ? p.area_ha.toFixed(2) + ' ha' : '—',
            };
            handleFeatureClick('BRP Crop Parcel', feature, e, displayProps,
                'https://www.pdok.nl/introductie/-/article/basisregistratie-gewaspercelen-brp-');

            // Fetch cadastral references that intersect this BRP parcel
            try {
                const b = layer.getBounds();
                const bbox = `${b.getWest()},${b.getSouth()},${b.getEast()},${b.getNorth()}`;
                const res = await fetch(`/api/kadastralekaart?bbox=${bbox}`);
                const data = await res.json();
                const candidates = data.features || [];
                const intersecting = typeof turf !== 'undefined'
                    ? candidates.filter(f => { try { return turf.booleanIntersects(feature, f); } catch { return false; } })
                    : candidates;

                const rows = intersecting.flatMap((f, i) => {
                    const p = f.properties || {};
                    return [
                        `Perceel ${i + 1}`,
                        ['Identificatie',   p.identificatie  || 'N/A'],
                        ['Sectie-Nummer',   `${p.sectie || '?'}-${p.perceelnummer || '?'}`],
                        ['Gemeente',        p.gemeente       || 'N/A'],
                        ['Grootte',         p.kadastralegrootte != null ? `${p.kadastralegrootte} m²` : 'N/A'],
                    ];
                });
                appendSidebarSection(`Kadastrale Referenties (${intersecting.length})`, rows);
            } catch (err) {
                console.warn('Could not fetch cadastral refs:', err);
            }

            // Show nearby pesticide stations if pesticides data is loaded
            if (pesticidesCache && typeof turf !== 'undefined') {
                const centroid = turf.centroid(feature);
                const nearbyStations = (pesticidesCache.features || []).filter(f => {
                    try { return turf.distance(centroid, f, { units: 'kilometers' }) <= 1; }
                    catch { return false; }
                }).slice(0, 8);
                const stationRows = nearbyStations.flatMap((f, i) => {
                    const sp = f.properties || {};
                    return [
                        `Station ${i + 1}: ${sp.stof_naam_sam || '?'}`,
                        ['Norm Class',  sp.normklas || '?'],
                        ['Exceedance',  sp.exceedance_ratio != null ? String(sp.exceedance_ratio) : '?'],
                    ];
                });
                appendSidebarSection(`Pesticide Stations within 1 km (${nearbyStations.length})`, stationRows);
            }

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

// 3C. Kadastrale Kaart — WMS tile layer (visual) + invisible GeoJSON layer (hover/click)
const kadastralekaartWmsLayer = L.tileLayer.wms('https://service.pdok.nl/kadaster/kadastralekaart/wms/v5_0', {
    layers: 'kadastralekaart:perceel,kadastralekaart:kadastralegrens',
    format: 'image/png',
    transparent: true,
    opacity: 0.7,
    attribution: 'Kadastrale Kaart &copy; Kadaster/PDOK'
});

const kadastralekaartLayer = L.geoJSON(null, {
    style: () => ({ fillColor: '#e67e22', fillOpacity: 0.15, color: '#e67e22', weight: 1 }),
    onEachFeature: (feature, layer) => {
        layer.on('mouseover', function() {
            this.setStyle({ fillColor: '#e67e22', fillOpacity: 0.45, color: '#e67e22', weight: 2 });
        });
        layer.on('mouseout', function() {
            this.setStyle({ fillColor: '#e67e22', fillOpacity: 0.15, color: '#e67e22', weight: 1 });
        });
        layer.on('click', async (e) => {
            handleFeatureClick('Kadastraal Perceel', feature, e, null,
                'https://www.nationaalgeoregister.nl/geonetwork/srv/dut/catalog.search#/metadata/a29917b9-3426-4041-a11b-69bcb2256904');

            // Fetch BRP crop parcels that overlap this cadastral parcel
            try {
                const b = layer.getBounds();
                const bbox = `${b.getWest()},${b.getSouth()},${b.getEast()},${b.getNorth()}`;
                const year = document.getElementById('year-brp')?.value || '2020';
                const res = await fetch(`/api/brp_parcels?bbox=${bbox}&year=${year}`);
                const data = await res.json();
                const candidates = data.features || [];
                const intersecting = typeof turf !== 'undefined'
                    ? candidates.filter(f => { try { return turf.booleanIntersects(feature, f); } catch { return false; } })
                    : candidates;

                // Group by crop name and count overlapping parcels
                const cropCounts = {};
                intersecting.forEach(f => {
                    const crop = f.properties?.gewas || 'Unknown crop';
                    cropCounts[crop] = (cropCounts[crop] || 0) + 1;
                });
                const rows = Object.entries(cropCounts).map(([crop, count]) => [
                    crop, count > 1 ? `${count} percelen` : '1 perceel'
                ]);
                appendSidebarSection(`BRP Gewaspercelen (${year})`, rows);
            } catch (err) {
                console.warn('Could not fetch BRP data for cadastral parcel:', err);
            }
        });
    }
});

// 3D. Bestuurlijke Grenzen (Administrative Boundaries)
const grenzenColors = { 'gemeenten': '#e74c3c', 'provincies': '#000000', 'landsgrens': '#8e44ad' };
const grenzenLayer = L.geoJSON(null, {
    style: (feature) => {
        const color = grenzenColors[feature.properties?.layer_type] || '#7f8c8d';
        return { color, weight: 2, fillColor: color, fillOpacity: 0.1 };
    },
    onEachFeature: (feature, layer) => {
        layer.on('click', (e) => {
            console.log("🔍 Grenzen Properties Clicked:", feature.properties);
            handleFeatureClick('Administrative Boundary', feature, e, null, 'https://www.pdok.nl/introductie/-/article/bestuurlijke-grenzen');
        });
    }
});

// 3E. KRD Livestock Farms (Veehouderijen)
// One point per farm, loaded from the krd_farms table (ETL: etl/load_krd.py).
// Colour-coded by animal type using getKrdColor(). Filtered by the sidebar dropdown.
const krdLayer = L.geoJSON(null, {
    pointToLayer: (feature, latlng) => {
        const color = getKrdColor(feature.properties?.bedrijfstype);
        const emoji = getKrdEmoji(feature.properties?.bedrijfstype);
        return L.marker(latlng, {
            icon: L.divIcon({
                // 'krd-icon-wrapper' strips Leaflet's default white square background
                // (leaflet-div-icon always adds background:#fff and border:1px — see style.css)
                className: 'krd-icon-wrapper',
                html: `<div class="krd-marker" style="background:${color};">${emoji}</div>`,
                iconSize:   [26, 26],
                iconAnchor: [13, 13]
            })
        });
    },
    onEachFeature: (feature, layer) => {
        layer.on('click', (e) => {
            const p = feature.properties || {};

            // The 'beëindigd' column name has an encoding quirk in the KRD export:
            // the ë is stored as a raw \xeb byte (Latin-1), and the 'i' in 'beëindigd'
            // is dropped — so the actual column name is 'beëndigd' (8 chars), not
            // 'beëindigd' (9 chars). Searching for 'ndigd' catches it regardless.
            const beeindigdKey = Object.keys(p).find(k => k.includes('eindigd') || k.includes('ndigd'));
            const beeindigdRaw = beeindigdKey ? p[beeindigdKey] : null;
            // 'Ja' = permit or activity has been terminated (vergunning beëindigd).
            // 'Nee' = the farm is still active under the current permit.
            const beeindigdVal = beeindigdRaw === 'Ja'
                ? 'Ja — vergunning / activiteit beëindigd'
                : (beeindigdRaw || '—');

            const display = {
                'Adres':                    p['adres']                   || '—',
                'Gemeente':                 p['gemeente']                || '—',
                'Provincie':                p['provincie']               || '—',
                'Diersoort / Bedrijfstype': p['bedrijfstype']            || '—',
                'Aantal stallen':           p['aantal stallen']          || '—',
                // Emission figures as published by the competent authority in the permit.
                // NH3 = nitrogen (relevant for Natura 2000 deposit calculations).
                'NH3 emissie (kg/j)':       p['nh3 emissie (kg/j)']     || '—',
                'Geur emissie (ouE/s)':     p['geur emissie (oue/s)']   || '—',
                'Fijnstof emissie (g/j)':   p['fijnstof emissie (g/j)'] || '—',
                'Beëindigd':                beeindigdVal,
                // besluitdatum = date of the most recent permit decision, not the farm opening date.
                'Datum besluit':            p['besluitdatum']            || '—',
                'IPPC-installatie':         p['ippc']                    || '—',
            };
            handleFeatureClick('KRD Veehouderij', feature, e, display, 'https://krd.igoview.nl/');
        });
    }
});

// 3E-b. KRD Stallen (individual housing units, sub-layer of krdLayer)
const stallenLayer = L.geoJSON(null, {
    pointToLayer: (feature, latlng) => L.circleMarker(latlng, {
        radius: 4,
        fillColor: '#8e44ad',
        color: '#5b2c6f',
        weight: 1,
        fillOpacity: 0.8
    }),
    onEachFeature: (feature, layer) => {
        layer.on('click', (e) => {
            const p = feature.properties || {};
            const display = {
                'Adres':                p['adres']                   || '—',
                'Diersoort':            p['diersoort']               || '—',
                'Diercategorie':        p['diercategorie']           || '—',
                'NH3 emissie (kg/j)':   p['nh3 emissie (kg/j)']     || '—',
                'Geur emissie (ouE/s)': p['geur emissie (oue/s)']   || '—',
                'Fijnstof (g/j)':       p['fijnstof emissie (g/j)'] || '—',
            };
            handleFeatureClick('KRD Stal (housing unit)', feature, e, display, 'https://krd.igoview.nl/');
        });
    }
});

function loadStallenData(effectiveBbox) {
    stallenLayer.clearLayers();
    fetch(`/api/krd_stallen?bbox=${effectiveBbox}`)
        .then(r => r.json())
        .then(data => { addFilteredData(stallenLayer, data); })
        .catch(e => console.error('Stallen Error:', e));
}

document.getElementById('krd-stallen-toggle').addEventListener('change', function () {
    if (this.checked) {
        stallenLayer.addTo(map);
        const eBbox = activeBuffers.length > 0 ? getBufferBbox() : `${map.getBounds().getWest()},${map.getBounds().getSouth()},${map.getBounds().getEast()},${map.getBounds().getNorth()}`;
        loadStallenData(eBbox);
    } else {
        map.removeLayer(stallenLayer);
        stallenLayer.clearLayers();
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
        layer.on('click', (e) => {
            handleFeatureClick('Pesticides Station', feature, e, null, 'https://www.bestrijdingsmiddelenatlas.nl/');
            if (brpCache && typeof turf !== 'undefined') {
                const nearby = (brpCache.features || []).filter(f => {
                    try { return turf.distance(feature, turf.centroid(f), { units: 'kilometers' }) <= 1; }
                    catch { return false; }
                }).slice(0, 8);
                const rows = nearby.flatMap((f, i) => {
                    const bp = f.properties || {};
                    return [
                        `Parcel ${i + 1}: ${bp.gewas || '?'}`,
                        ['Area', bp.area_ha != null ? bp.area_ha.toFixed(2) + ' ha' : '?'],
                    ];
                });
                appendSidebarSection(`BRP Parcels within 1 km (${nearby.length})`, rows);
            }
        });
    }
});

// =========================================================
// 3H. Schools Layer (Education Points)
// =========================================================

let activeSchoolType = null;

function getSchoolColor(schoolType) {
    if (!schoolType) return '#95a5a6';
    switch (schoolType) {
        case 'Basisonderwijs':                                      return '#2ecc71';
        case 'Voortgezet Onderwijs':                                return '#3498db';
        case 'Middelbaar Beroepsonderwijs':                         return '#f39c12';
        case 'Hoger Beroepsonderwijs en Wetenschappelijk Onderwijs': return '#9b59b6';
        default:                                                    return '#7f8c8d';
    }
}

function updateSchoolLegendUI() {
    document.querySelectorAll('.school-legend-item').forEach(function(el) {
        const isActive = activeSchoolType && el.dataset.type === activeSchoolType;
        el.style.background  = isActive ? '#eaf4fb' : '';
        el.style.fontWeight  = isActive ? 'bold'    : '';
        el.style.borderLeft  = isActive ? '3px solid #2c3e50' : '3px solid transparent';
        el.style.paddingLeft = '6px';
    });
}

function applySchoolTypeFilter() {
    schoolsLayer.eachLayer(function(layer) {
        const type = layer.feature?.properties?.onderwijstype;
        const visible = !activeSchoolType || type === activeSchoolType;
        const el = layer.getElement();
        if (el) {
            el.style.opacity      = visible ? '1' : '0';
            el.style.pointerEvents = visible ? '' : 'none';
        }
    });
    updateSchoolLegendUI();
}

const schoolsLayer = L.geoJSON(null, {
    pointToLayer: (feature, latlng) => {
        const color = getSchoolColor(feature.properties.onderwijstype);
        return L.marker(latlng, {
            icon: L.divIcon({
                className: 'school-marker',
                html: `<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 28 28">
                         <circle cx="14" cy="14" r="12.5" fill="${color}" stroke="white" stroke-width="2"/>
                         <path d="M14 7 L21 11 L14 13 L7 11 Z" fill="white"/>
                         <path d="M10 12 L10 18.5 Q14 21 18 18.5 L18 12"
                               fill="none" stroke="white" stroke-width="1.5" stroke-linejoin="round"/>
                         <line x1="21" y1="11" x2="21" y2="17" stroke="white" stroke-width="1.4" stroke-linecap="round"/>
                         <circle cx="21" cy="18" r="1.3" fill="white"/>
                       </svg>`,
                iconSize:    [28, 28],
                iconAnchor:  [14, 14],
                popupAnchor: [0, -18]
            })
        });
    },

    onEachFeature: (feature, layer) => {
        layer.on('click', (e) => {
            const p = feature.properties;
            handleFeatureClick('School', feature, e, {
                'Institution Name':       p.instellingsnaam        || 'N/A',
                'Education Type':         p.onderwijstype          || 'N/A',
                'Street Address':         p.straatnaam             || 'N/A',
                'House Number Extension': p.huisnummer_toevoeging  || 'N/A',
                'Postal Code':            p.postcode               || 'N/A',
                'City':                   p.plaatsnaam             || 'N/A',
                'Province':               p.provincie              || 'N/A',
                'Municipality Number':    p.gemeentenummer         || 'N/A',
                'Municipality Name':      p.gemeentenaam           || 'N/A',
                'Phone Number':           p.telefoonnummer         || 'N/A',
            }, 'https://www.duo.nl/open_onderwijsdata/');
        });
    }
});

// 3I. Nature Network Netherlands / Natuurnetwerk Nederland (INSPIRE harmonized)
// Purple colour scheme to distinguish from Natura 2000 (teal).
// Buffer/center built client-side via buildNNNDisplayData (see prepareLayerData).
const nnnLayer = L.geoJSON(null, {
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
            color: '#6c3483',
            weight: 2,
            fillColor: '#9b59b6',
            fillOpacity: 0.34
        };
    },
    pointToLayer: (feature, latlng) => {
        if (feature.properties?.layer_type === 'center') {
            return L.marker(latlng, {
                icon: L.divIcon({
                    className: 'nnn-center-pin',
                    html: '<span></span>',
                    iconSize: [22, 30],
                    iconAnchor: [11, 30],
                    popupAnchor: [0, -26]
                })
            });
        }

        return L.circleMarker(latlng, {
            radius: 5,
            fillColor: '#9b59b6',
            color: '#6c3483',
            weight: 1,
            fillOpacity: 0.9
        });
    },
    onEachFeature: (feature, layer) => {
        layer.on('click', (e) => {
            const layerType = feature.properties?.layer_type;
            const title = layerType === 'buffer'
                ? 'Nature Network NL Buffer'
                : layerType === 'center'
                    ? 'Nature Network NL Center'
                    : 'Nature Network NL';
            handleFeatureClick(title, feature, e, null, 'https://service.pdok.nl/provincies/natuurnetwerk-nederland/atom/index.xml');
        });
    }
});

// 3J. WFD Surface Water Bodies (INSPIRE harmonised — KRW)
const wfdSurfaceWaterLayer = L.geoJSON(null, {
    renderer: L.svg(),
    style: (feature) => {
        const geomType = feature.geometry?.type || '';
        if (geomType.includes('Polygon')) {
            return { color: '#117a65', weight: 2, fillColor: '#1abc9c', fillOpacity: 0.35 };
        }
        return { color: '#117a65', weight: 2, fillOpacity: 0 };
    },
    onEachFeature: (feature, layer) => {
        layer.on('click', (e) => {
            const p = feature.properties || {};
            const display = {
                'Name':           p.name          || 'N/A',
                'Local ID':       p.localid        || 'N/A',
                'Language':       p.language       || 'N/A',
                'Nativeness':     p.nativeness     || 'N/A',
                'Name Status':    p.namestatus     || 'N/A',
                'Source of Name': p.sourceofname   || 'N/A',
                'Date':           p.date           || 'N/A',
                'Link':           p.link           || 'N/A',
            };
            handleFeatureClick('WFD Surface Water Body', feature, e, display, 'https://service.pdok.nl/ihw/krw-oppervlaktewaterlichaams-geharmoniseerd/wms/v1_0');
        });
    }
});

// 3K. Water Hydrography (INSPIRE harmonized — Water Authorities)
const hydrographyLayer = L.geoJSON(null, {
    renderer: L.svg(),
    style: { color: '#1a6fa8', weight: 3, fillColor: '#2980b9', fillOpacity: 0.25 },
    pointToLayer: (feature, latlng) => L.circleMarker(latlng, {
        radius: 5,
        fillColor: '#1a6fa8',
        color: '#154360',
        weight: 1,
        fillOpacity: 0.85
    }),
    onEachFeature: (feature, layer) => {
        layer.on('click', (e) => {
            const p = feature.properties || {};
            const display = {
                'Name':            p.name         || 'N/A',
                'Type':            p.localtype    || 'N/A',
                'Condition':       p.condition    || 'N/A',
                'Level':           p.level        || 'N/A',
                'Length (m)':      p.length       ?? 'N/A',
                'Width Range (m)': p.widthrange   ?? 'N/A',
                'Stream Order':    p.streamorder  || 'N/A',
                'Tidal':           p.tidal        || 'N/A',
                'Origin':          p.origin       || 'N/A',
                'Persistence':     p.persistence  || 'N/A',
            };
            handleFeatureClick('Water Hydrography', feature, e, display, 'https://api.pdok.nl/hwh/waterschappen-hydrografie/ogc/v1');
        });
    }
});

// Registry linking HTML IDs to Leaflet Layer Objects
const layerRegistry = {
    'brp': brpLayer,
    'bag': bagLayer,
    'natura2000': natura2000Layer,
    'grenzen': grenzenLayer,
    'krd': krdLayer,
    'pesticides': pesticidesLayer,
    'health': healthLayer,
    'schools': schoolsLayer,
    'nnn': nnnLayer,
    'hydrography': hydrographyLayer,
    'wfd': wfdSurfaceWaterLayer,
    'kadastralekaart': kadastralekaartLayer
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

function createBoundaryFilter(feature, label) {
    document.getElementById('radius-picker').style.display = 'none';
    if (!feature || !feature.geometry) return;

    const id = ++bufferIdCounter;
    const mapLayer = L.geoJSON(feature, {
        style: { color: '#3498db', weight: 2.5, fillColor: '#3498db', fillOpacity: 0.07, dashArray: '6, 3' },
        interactive: false
    }).addTo(map);

    const center = turf.centroid(feature);
    const areaName = label || 'Area';
    const labelMarker = L.marker(
        [center.geometry.coordinates[1], center.geometry.coordinates[0]],
        {
            icon: L.divIcon({
                className: '',
                html: `<div style="background:rgba(255,255,255,0.92);padding:2px 8px;border-radius:3px;font-size:11px;font-weight:bold;border:1px solid #3498db;white-space:nowrap;max-width:160px;overflow:hidden;text-overflow:ellipsis;">⬡ ${areaName}</div>`,
                iconAnchor: [40, 8]
            }),
            interactive: false
        }
    ).addTo(map);

    activeBuffers.push({ id, polygon: feature, mapLayer, labelMarker, radiusKm: null, label: areaName });
    document.getElementById('buffer-options').style.display = 'block';
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
        const isAreaFilter = b.radiusKm === null;
        const lbl = isAreaFilter
            ? `Area: <strong>${b.label || 'Boundary'}</strong>`
            : (b.radiusKm >= 1 ? `Buffer: <strong>${b.radiusKm}km</strong>` : `Buffer: <strong>${b.radiusKm * 1000}m</strong>`);
        const stats = b.bagStats
            ? `<div style="margin-top:4px;color:#34495e;line-height:1.35;">
                BAG: <strong>${b.bagStats.usageLocations}</strong> usage locations
                (<strong>${b.bagStats.residentialUsageLocations}</strong> residential),
                <strong>${b.bagStats.buildings}</strong> buildings<br>
                Loaded context: <strong>${b.bagStats.parcels}</strong> parcels,
                <strong>${b.bagStats.naturaAreas}</strong> Natura areas
            </div>`
            : '<div style="margin-top:4px;color:#7f8c8d;">Counts update after layer data loads.</div>';
        return `<div style="margin:4px 0;font-size:12px;padding:3px 0;border-bottom:1px solid #eee;">
            <div style="display:flex;justify-content:space-between;align-items:center;">
                <span>${lbl}</span>
                <button onclick="removeBuffer(${b.id})" style="background:#e74c3c;color:white;border:none;border-radius:3px;padding:1px 6px;cursor:pointer;font-size:11px;flex-shrink:0;margin-left:6px;">✕</button>
            </div>
            ${stats}
        </div>`;
    }).join('');
}

function getN2000KrdBuffers(km) {
    const n2000Areas = (natura2000Cache?.features || [])
        .filter(f => f.properties?.layer_type === 'area' || !f.properties?.layer_type);
    const count = n2000Areas.length;
    if (n2000KrdBufferCache.km === km && n2000KrdBufferCache.count === count && count > 0) {
        return n2000KrdBufferCache.buffers;
    }
    if (count === 0) return [];
    const buffers = n2000Areas.map(f => {
        try { return turf.buffer(f, km, { units: 'kilometers', steps: 8 }); }
        catch { return null; }
    }).filter(Boolean);
    n2000KrdBufferCache = { km, count, buffers };
    return buffers;
}

function filterKrdByN2000Distance(krdData) {
    if (krdN2000FilterKm <= 0 || typeof turf === 'undefined') return krdData;
    if (!natura2000Cache || !natura2000Cache.features) return krdData;
    const n2000Buffers = getN2000KrdBuffers(krdN2000FilterKm);
    if (n2000Buffers.length === 0) return krdData;
    return {
        ...krdData,
        features: (krdData.features || []).filter(f => {
            try {
                return n2000Buffers.some(buf => turf.booleanPointInPolygon(f, buf));
            } catch { return false; }
        })
    };
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

function buildNatura2000DisplayData(data, bufferKm = 0.5) {
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

// NNN display builder — same output shape as buildNatura2000DisplayData but
// skips client-side turf.simplify so the buffer follows the actual polygon
// outline rather than a collapsed/circular approximation.
// The server already applies the appropriate simplification tolerance.
function buildNNNDisplayData(data, bufferKm = 0.25) {
    if (!data || !Array.isArray(data.features)) return data;
    if (data.features.some(f => f.properties?.layer_type)) return data;
    if (typeof turf === 'undefined') return data;

    const features = [];

    data.features.forEach((feature, index) => {
        if (!feature || !feature.geometry) return;

        const baseProperties = {
            ...(feature.properties || {}),
            area_id: feature.id || feature.properties?.id || index,
            buffer_km: bufferKm
        };

        // Buffer is pushed first so Leaflet renders it behind the area polygon
        try {
            const bufferFeature = turf.buffer(feature, bufferKm, {
                units: 'kilometers',
                steps: 32   // enough resolution to follow polygon edges without circles
            });
            if (bufferFeature) {
                bufferFeature.properties = { ...baseProperties, layer_type: 'buffer' };
                features.push(bufferFeature);
            }
        } catch (err) {
            console.warn('Could not create NNN buffer:', err);
        }

        // Area polygon on top of the buffer
        features.push({
            type: 'Feature',
            properties: { ...baseProperties, layer_type: 'area' },
            geometry: feature.geometry
        });

        // Center pin on top of everything
        try {
            const centerFeature = turf.pointOnFeature(feature);
            centerFeature.properties = { ...baseProperties, layer_type: 'center' };
            features.push(centerFeature);
        } catch (err) {
            console.warn('Could not create NNN center point:', err);
        }
    });

    return { type: 'FeatureCollection', features };
}

function prepareLayerData(layerObject, data) {
    if (layerObject === natura2000Layer) return buildNatura2000DisplayData(data, n2000BufferKm);
    if (layerObject === nnnLayer)        return buildNNNDisplayData(data, 0.25);
    return data;
}

function applyBufferFilter() {
    if (map.hasLayer(natura2000Layer) && natura2000Cache) {
        natura2000Layer.clearLayers();
        addFilteredData(natura2000Layer, natura2000Cache);
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

function updateKrdN2000Status(totalLoaded) {
    const el = document.getElementById('krd-n2000-status');
    if (!el) return;
    if (krdN2000FilterKm <= 0) { el.textContent = ''; return; }
    const n2000Areas = (natura2000Cache?.features || [])
        .filter(f => f.properties?.layer_type === 'area' || !f.properties?.layer_type);
    if (n2000Areas.length === 0) {
        el.textContent = '⚠ Enable Natura 2000 layer first';
        el.style.color = '#e67e22';
        return;
    }
    el.style.color = '#607060';
    const visible = krdLayer.getLayers().length;
    el.textContent = `${visible} of ${totalLoaded} farms within ${krdN2000FilterKm}km of N2000`;
}

function refreshN2000BufferLabel() {
    const lbl = n2000BufferKm >= 1 ? n2000BufferKm + ' km' : (n2000BufferKm * 1000) + ' m';
    const el = document.querySelector('.natura-filter-item[data-natura-filter="buffer"]');
    if (el) {
        const swatch = el.querySelector('span');
        el.innerHTML = '';
        if (swatch) el.appendChild(swatch);
        el.appendChild(document.createTextNode(lbl + ' buffer'));
    }
}

// =========================================================
// 5. Custom UI Control Panel Integration & Nationwide Loading
// =========================================================

// State flags to ensure we only download nationwide data ONCE
let isNaturaLoaded = false;
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
    const healthActive      = document.getElementById('layer-health').checked;
    const pesticidesActive  = document.getElementById('layer-pesticides').checked;
    const naturaActive      = document.getElementById('layer-natura2000').checked;
    const bagActive         = document.getElementById('layer-bag').checked;
    const nnnActive         = document.getElementById('layer-nnn').checked;
    const schoolsActive     = document.getElementById('layer-schools').checked;
    const krdActive         = document.getElementById('layer-krd').checked;

    document.getElementById('schools-legend').style.display = schoolsActive ? 'block' : 'none';

    document.getElementById('map-legend').style.display = (healthActive || pesticidesActive || naturaActive || bagActive || nnnActive || krdActive) ? 'block' : 'none';
    document.getElementById('legend-bag').style.display = bagActive ? 'block' : 'none';
    document.getElementById('legend-natura2000').style.display = naturaActive ? 'block' : 'none';
    document.getElementById('legend-nnn').style.display = nnnActive ? 'block' : 'none';
    document.getElementById('legend-health').style.display = healthActive ? 'block' : 'none';
    document.getElementById('legend-pesticides').style.display = pesticidesActive ? 'block' : 'none';
    document.getElementById('legend-krd').style.display = krdActive ? 'block' : 'none';
    document.getElementById('legend-divider').style.display = (bagActive && (naturaActive || nnnActive || healthActive || pesticidesActive || krdActive)) ? 'block' : 'none';
    document.getElementById('legend-divider-nnn').style.display = (naturaActive && (nnnActive || healthActive || pesticidesActive || krdActive)) ? 'block' : 'none';
    document.getElementById('legend-divider-tertiary').style.display = (nnnActive && (healthActive || pesticidesActive || krdActive)) ? 'block' : 'none';
    document.getElementById('legend-divider-secondary').style.display = (healthActive && (pesticidesActive || krdActive)) ? 'block' : 'none';
    document.getElementById('legend-divider-krd').style.display = (krdActive && pesticidesActive) ? 'block' : 'none';
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
            else if (layerId === 'kadastralekaart') {
                kadastralekaartWmsLayer.addTo(map);
                layer.clearLayers();
                map.fire('moveend');
            }
            else if (layerId === 'grenzen') {
                const grenzenDb = `/api/grenzen?bbox=${bboxNetherlands}`;
                await loadNationwideLayer(layer, 'Grenzen', grenzenDb, grenzenDb, 'isGrenzenLoaded');
            }
            else if (layerId === 'nnn') {
                layer.clearLayers();
                map.fire('moveend');
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
            if (layerId === 'kadastralekaart') {
                map.removeLayer(kadastralekaartWmsLayer);
                layer.clearLayers();
                kadastraalPerceelCache = null;
            }
            if (layerId === 'nnn') {
                layer.clearLayers();
                nnnCache = null;
                isNNNLoaded = false;
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

// Populate BRP gemeente dropdown from grenzen table
fetch('/api/brp_gemeenten')
    .then(r => r.json())
    .then(names => {
        const sel = document.getElementById('brp-gemeente-filter');
        if (!sel) return;
        names.forEach(name => {
            const opt = document.createElement('option');
            opt.value = name;
            opt.textContent = name;
            sel.appendChild(opt);
        });
    })
    .catch(() => {});

document.getElementById('brp-gemeente-filter')?.addEventListener('change', function () {
    if (map.hasLayer(brpLayer)) {
        brpLayer.clearLayers();
        brpCache = null;
        map.fire('moveend');
    }
});

// When the sidebar animal-type dropdown changes, clear the layer and re-fire moveend
// so the fetch picks up the new ?animal_type= parameter and reloads within the current bbox.
document.getElementById('filter-krd-animal').addEventListener('change', function() {
    if (map.hasLayer(krdLayer)) {
        krdLayer.clearLayers();
        map.fire('moveend');
    }
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

                if (fallbackData.features && fallbackData.features.length > 0) {
                    layerObject.clearLayers();
                    if (layerObject === bagLayer) bagBuildingCache = fallbackData;
                    if (layerObject === natura2000Layer) natura2000Cache = fallbackData;
                    if (layerObject === grenzenLayer)     grenzenCache    = fallbackData;
                    if (layerObject === nnnLayer)         nnnCache        = fallbackData;
                    addFilteredData(layerObject, fallbackData);
                    refreshBagBufferSummaries();
                    console.log(`[${layerName}] 🛡️ Loaded from Local Database.`);
                } else if (layerObject === bagLayer) {
                    layerObject.clearLayers();
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
        const brpGemeente = document.getElementById('brp-gemeente-filter')?.value || '';
        const brpGemeenteParam = brpGemeente ? `&gemeente=${encodeURIComponent(brpGemeente)}` : '';
        fetch(`/api/brp_parcels?bbox=${effectiveBbox}&year=${getYear('brp')}${brpGemeenteParam}`)
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
        const bagApi = `https://api.pdok.nl/kadaster/bag/ogc/v2/collections/pand/items?f=json&limit=${BAG_API_LIMIT}&bbox=${effectiveBbox}`;
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
        const naturaApi = `https://api.pdok.nl/rvo/natura2000/ogc/v1/collections/natura2000/items?f=json&limit=${NATURA2000_API_LIMIT}&bbox=${effectiveBbox}`;
        const naturaDb = `/api/natura2000_areas?bbox=${effectiveBbox}&buffer_km=${n2000BufferKm}`;

        loadDataWithFallback(natura2000Layer, 'Natura 2000', naturaApi, naturaDb, false);
    }

    // ==========================================
    // 3I. Nature Network NL (DB only — simplified nationwide, buffers at detail zoom)
    // ==========================================
    if (map.hasLayer(nnnLayer)) {
        const nnnDb = `/api/nnn?bbox=${effectiveBbox}`;
        loadDataWithFallback(nnnLayer, 'Nature Network NL', nnnDb, nnnDb, false);
    }

    // ==========================================
    // 5. KRD Livestock Farms (Local DB only — no public tile/WMS fallback)
    // animal_type filter is appended only if the dropdown has a selection;
    // an empty string means "show all", so the parameter is omitted entirely.
    // ==========================================
    if (map.hasLayer(krdLayer)) {
        const krdAnimalFilter = document.getElementById('filter-krd-animal')?.value || '';
        const krdAnimalParam  = krdAnimalFilter ? `&animal_type=${encodeURIComponent(krdAnimalFilter)}` : '';
        fetch(`/api/krd_farms?bbox=${effectiveBbox}${krdAnimalParam}`)
            .then(res => res.json())
            .then(data => {
                krdLayer.clearLayers();
                addFilteredData(krdLayer, filterKrdByN2000Distance(data));
                updateKrdN2000Status(data.features?.length || 0);
                if (document.getElementById('krd-stallen-toggle')?.checked) {
                    loadStallenData(effectiveBbox);
                }
            })
            .catch(e => console.error("KRD Error:", e));
    }

    if (map.hasLayer(pesticidesLayer)) {
        fetch(`/api/pesticides?bbox=${effectiveBbox}`)
            .then(res => res.json())
            .then(data => { pesticidesCache = data; pesticidesLayer.clearLayers(); addFilteredData(pesticidesLayer, data); })
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
            .then(data => { schoolsLayer.clearLayers(); addFilteredData(schoolsLayer, data); applySchoolTypeFilter(); })
            .catch(e => console.error("Schools Error:", e));
    }

    // ==========================================
    // Water Hydrography (OGC API primary → DB fallback)
    // Collection: watercourse (INSPIRE HY theme)
    // ==========================================
    const hydrographyApi = `https://api.pdok.nl/hwh/waterschappen-hydrografie/ogc/v1/collections/watercourse/items?f=json&limit=10000&bbox=${effectiveBbox}`;
    const hydrographyDb  = `/api/hydrography?bbox=${effectiveBbox}`;
    loadDataWithFallback(hydrographyLayer, 'Water Hydrography', hydrographyApi, hydrographyDb, false);

    if (map.hasLayer(wfdSurfaceWaterLayer)) {
        fetch(`/api/wfd_surface_water?bbox=${effectiveBbox}`)
            .then(res => res.json())
            .then(data => { wfdSurfaceWaterLayer.clearLayers(); addFilteredData(wfdSurfaceWaterLayer, data); })
            .catch(e => console.error("WFD Surface Water Error:", e));
    }

    // ==========================================
    // Kadastrale Kaart (DB only — only load at high zoom to limit result set)
    // ==========================================
    if (map.hasLayer(kadastralekaartLayer)) {
        if (map.getZoom() >= CADASTRAL_MIN_ZOOM) {
            fetch(`/api/kadastralekaart?bbox=${effectiveBbox}`)
                .then(res => res.json())
                .then(data => {
                    kadastraalPerceelCache = data;
                    kadastralekaartLayer.clearLayers();
                    addFilteredData(kadastralekaartLayer, data);
                })
                .catch(e => console.error("Kadastralekaart Error:", e));
        } else {
            kadastralekaartLayer.clearLayers();
            kadastraalPerceelCache = null;
        }
    }

    // ==========================================
    // Grenzen (Administrative Boundaries - DB only)
    // ==========================================
    const grenzenDb = `/api/grenzen?bbox=${bboxPostGIS}`;
    loadDataWithFallback(grenzenLayer, 'Grenzen', grenzenDb, grenzenDb, true);
});

// =========================================================
// Waterschappen (Water Authority Borders)
// =========================================================
const waterschappenLayer = L.geoJSON(null, {
    style: { color: '#1565c0', weight: 2, fillColor: '#42a5f5', fillOpacity: 0.12, dashArray: '6, 4' },
    onEachFeature: (feature, layer) => {
        layer.on('click', (e) => {
            handleFeatureClick('Waterschap', feature, e, null, 'https://api.pdok.nl/hwh/waterschappen/ogc/v1');
        });
    }
});

layerRegistry['waterschappen'] = waterschappenLayer;

document.getElementById('layer-waterschappen').addEventListener('change', async function() {
    if (this.checked) {
        waterschappenLayer.addTo(map);
        await loadNationwideLayer(
            waterschappenLayer, 'Waterschappen',
            `/api/waterschappen?bbox=${bboxNetherlands}`,
            `/api/waterschappen?bbox=${bboxNetherlands}`,
            'isWaterschappenLoaded'
        );
    } else {
        map.removeLayer(waterschappenLayer);
        document.getElementById('info-panel').classList.add('hidden');
    }
    updateLegend();
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

// Export Controls (Excel + PNG)
const excelControl = L.control({position: 'bottomright'});
excelControl.onAdd = function () {
    const div = L.DomUtil.create('div', 'excel-control');
    div.style.cssText = 'display:flex;flex-direction:column;gap:6px;';
    const btnStyle = 'border:none;padding:10px 15px;cursor:pointer;font-size:14px;font-weight:bold;border-radius:4px;box-shadow:0 2px 4px rgba(0,0,0,0.3);width:100%;';
    div.innerHTML = `
        <button id="export-excel-btn" style="background-color:#27ae60;color:white;${btnStyle}">📊 Export Data to Excel</button>
        <button id="export-png-btn" style="background-color:#2980b9;color:white;${btnStyle}">🗺 Export Map as PNG</button>
    `;
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
        columns: { "instellingsnaam": "School Name", "onderwijstype": "Type", "plaatsnaam": "City", "provincie": "Province" }
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
    },
    {
        layerObject: waterschappenLayer, sheetName: 'Waterschappen',
        buildUrl: (bbox) => `/api/waterschappen?bbox=${bbox}`,
        columns: { 'code': 'Code', 'naam': 'Naam' }
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

// =========================================================
// Rectangle Draw Tool (dependency-free area selection)
// =========================================================
let drawRectMode   = false;
let drawRectStart  = null;
let drawRectLayer  = null;

function startRectDraw() {
    drawRectMode = true;
    drawRectStart = null;
    map.getContainer().style.cursor = 'crosshair';
    map.dragging.disable();
    map.doubleClickZoom.disable();
    const btn = document.getElementById('draw-rect-btn');
    if (btn) { btn.textContent = '✕ Cancel Draw'; btn.style.background = '#c0392b'; }
}

function stopRectDraw() {
    drawRectMode = false;
    drawRectStart = null;
    if (drawRectLayer) { map.removeLayer(drawRectLayer); drawRectLayer = null; }
    map.getContainer().style.cursor = '';
    map.dragging.enable();
    map.doubleClickZoom.enable();
    const btn = document.getElementById('draw-rect-btn');
    if (btn) { btn.textContent = '✏ Draw Rectangle Area'; btn.style.background = '#2980b9'; }
}

document.getElementById('draw-rect-btn').addEventListener('click', function () {
    if (drawRectMode) { stopRectDraw(); return; }
    if (!bufferToolActive) {
        document.getElementById('buffer-tool-btn').click();
    }
    startRectDraw();
});

map.on('mousedown', function (e) {
    if (!drawRectMode) return;
    L.DomEvent.stop(e);
    drawRectStart = e.latlng;
    if (drawRectLayer) map.removeLayer(drawRectLayer);
    drawRectLayer = L.rectangle([drawRectStart, drawRectStart], {
        color: '#2980b9', weight: 2, fillColor: '#2980b9', fillOpacity: 0.08, interactive: false
    }).addTo(map);
});

map.on('mousemove', function (e) {
    if (!drawRectMode || !drawRectStart) return;
    drawRectLayer.setBounds([drawRectStart, e.latlng]);
});

map.on('mouseup', function (e) {
    if (!drawRectMode || !drawRectStart) return;
    L.DomEvent.stop(e);
    const bounds = drawRectLayer.getBounds();
    const sw = bounds.getSouthWest();
    const ne = bounds.getNorthEast();
    if (Math.abs(ne.lat - sw.lat) < 0.0001 || Math.abs(ne.lng - sw.lng) < 0.0001) {
        stopRectDraw();
        return;
    }
    const drawnFeature = turf.bboxPolygon([sw.lng, sw.lat, ne.lng, ne.lat]);
    stopRectDraw();
    createBoundaryFilter(drawnFeature, 'Drawn Rectangle');
    document.getElementById('buffer-options').style.display = 'block';
});

// =========================================================
// N2000 Buffer Distance Controls
// =========================================================
function applyN2000BufferDistance(km) {
    const val = parseFloat(km);
    if (isNaN(val) || val <= 0) return;
    n2000BufferKm = val;
    refreshN2000BufferLabel();
    const slider = document.getElementById('n2000-buffer-slider');
    const input  = document.getElementById('n2000-buffer-input');
    if (slider) slider.value = Math.min(val, parseFloat(slider.max));
    if (input)  input.value  = val;
    if (map.hasLayer(natura2000Layer)) {
        natura2000Layer.clearLayers();
        natura2000Cache = null;
        map.fire('moveend');
    }
}

document.getElementById('n2000-buffer-slider')?.addEventListener('input', function() {
    applyN2000BufferDistance(this.value);
});
document.getElementById('n2000-buffer-input')?.addEventListener('change', function() {
    applyN2000BufferDistance(this.value);
});

// =========================================================
// KRD → Natura 2000 Distance Filter
// =========================================================
document.getElementById('krd-n2000-filter-btn')?.addEventListener('click', function() {
    const val = parseFloat(document.getElementById('krd-n2000-max-km')?.value);
    if (isNaN(val) || val <= 0) return;
    krdN2000FilterKm = val;
    n2000KrdBufferCache = { km: -1, buffers: [] };
    if (map.hasLayer(krdLayer)) map.fire('moveend');
});

document.getElementById('krd-n2000-clear-btn')?.addEventListener('click', function() {
    krdN2000FilterKm = 0;
    n2000KrdBufferCache = { km: -1, buffers: [] };
    const el = document.getElementById('krd-n2000-status');
    if (el) el.textContent = '';
    if (map.hasLayer(krdLayer)) map.fire('moveend');
});

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

    // When buffers are active, compute their union polygon and send to backend
    // so the export only contains data intersecting the buffer zone.
    let bufferGeom = null;
    if (activeBuffers.length > 0) {
        try {
            let union = activeBuffers[0].polygon;
            for (let i = 1; i < activeBuffers.length; i++) {
                union = turf.union(union, activeBuffers[i].polygon);
            }
            bufferGeom = JSON.stringify(union.geometry);
        } catch (e) {
            console.warn('Buffer union failed; falling back to viewport bbox:', e);
        }
    }

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
            body: JSON.stringify({ bbox, layers: activeLayers, buffer_geom: bufferGeom })
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

// PNG Map Export
document.getElementById('export-png-btn').addEventListener('click', async function () {
    const btn = this;
    const originalText = btn.innerText;
    btn.innerText = '⏳ Capturing...';
    btn.disabled = true;
    try {
        const canvas = await html2canvas(document.getElementById('map'), {
            useCORS: true,
            allowTaint: true,
            logging: false
        });
        const a = document.createElement('a');
        a.href = canvas.toDataURL('image/png');
        a.download = `Environmental_Map_${new Date().toISOString().split('T')[0]}.png`;
        a.click();
    } catch (e) {
        alert('Map export failed: ' + e.message);
    } finally {
        btn.innerText = originalText;
        btn.disabled = false;
    }
});

// =========================================================
// Layer Opacity Sliders
// =========================================================

// Maps layer checkbox value → Leaflet layer objects to control
const opacityLayerMap = {
    brp:          [brpLayer],
    bag:          [bagLayer, bagUsageLayer],
    natura2000:   [natura2000Layer],
    krd:          [krdLayer],
    pesticides:   [pesticidesLayer],
    schools:      [schoolsLayer],
    health:       [healthLayer],
    grenzen:      [grenzenLayer],
    kadastralekaart: [kadastralekaartLayer],
    waterschappen:[waterschappenLayer],
    hydrography:  [hydrographyLayer],
    nnn:          [nnnLayer],
    wfd:          [wfdSurfaceWaterLayer],
};

function applyLayerOpacity(key, val) {
    (opacityLayerMap[key] || []).forEach(layer => {
        layer.eachLayer(sub => {
            if (!sub.setStyle) return;
            if (sub._origFillOpacity === undefined) {
                sub._origFillOpacity = sub.options.fillOpacity ?? 0.6;
            }
            sub.setStyle({ opacity: val, fillOpacity: sub._origFillOpacity * val });
        });
    });
}

// Inject opacity slider into every matching expand panel
document.querySelectorAll('.layer-row').forEach(row => {
    const checkbox = row.querySelector('.map-layer-toggle');
    const panel    = row.querySelector('.layer-expand-panel');
    if (!checkbox || !panel || !opacityLayerMap[checkbox.value]) return;
    const key = checkbox.value;

    const wrap = document.createElement('div');
    wrap.style.cssText = 'margin-top:8px;padding-top:8px;border-top:1px solid #e8f0e4;';
    wrap.innerHTML = `
        <label class="expand-label" style="display:flex;justify-content:space-between;margin-bottom:3px;">
            <span>Opacity</span><span id="opacity-label-${key}">100%</span>
        </label>
        <input type="range" min="0" max="100" step="5" value="100"
               data-opacity-for="${key}"
               style="width:100%;accent-color:#1B512D;cursor:pointer;">
    `;
    panel.appendChild(wrap);
});

document.getElementById('layer-controls').addEventListener('input', function (e) {
    const slider = e.target.closest('[data-opacity-for]');
    if (!slider) return;
    const key = slider.dataset.opacityFor;
    const val = slider.value / 100;
    const label = document.getElementById(`opacity-label-${key}`);
    if (label) label.textContent = Math.round(val * 100) + '%';
    applyLayerOpacity(key, val);
});

// =========================================================
// Dataset Info Modal
// =========================================================
function openDatasetModal(key) {
    const info = DATASET_INFO[key];
    if (!info) return;
    document.getElementById('dmi-name').textContent    = info.name;
    document.getElementById('dmi-summary').textContent = info.summary;
    document.getElementById('dmi-updated').textContent = info.lastUpdated;
    document.getElementById('dmi-source').textContent  = info.source;
    document.getElementById('dmi-readmore').href       = info.readMore;
    document.getElementById('dataset-modal-overlay').classList.remove('hidden');
}

function closeDatasetModal() {
    document.getElementById('dataset-modal-overlay').classList.add('hidden');
}


