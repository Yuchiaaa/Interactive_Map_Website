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
let isProgrammaticMove = false;

let bagBuildingCache = null;
let bagUsageCache = null;
let natura2000Cache = null;
let grenzenCache = null;
let nnnCache = null;
let kadastraalPerceelCache = null;
let brpCache = null;
let pesticidesCache = null;
let healthCache = null;
let schoolsCache = null;
const BAG_API_LIMIT = 2000;
const BAG_USAGE_API_LIMIT = 3000;
const BAG_DETAIL_MIN_ZOOM = 14;
const NATURA2000_API_LIMIT = 250;
const NATURA2000_DETAIL_MIN_ZOOM = 9;
const CADASTRAL_MIN_ZOOM = 14;

// Debounce timer for moveend data fetching
let _moveendTimer = null;

// =========================================================
// Dataset Info Metadata
// =========================================================
const DATASET_INFO = {
    brp: {
        name:        'BRP Crop Parcels',
        summary:     'The Basisregistratie Gewaspercelen (BRP) registers all agricultural parcels and their declared crops across the Netherlands each year. Used for EU subsidy administration and agricultural policy monitoring.',
        lastUpdated: 'Annually (latest: 2025)',
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
    { key: 'grassland',  label: 'Grassland',           color: '#27ae60' },
    { key: 'maize',      label: 'Maize',                color: '#f1c40f' },
    { key: 'potato',     label: 'Potato',               color: '#d35400' },
    { key: 'cereals',    label: 'Cereals',              color: '#e67e22' },
    { key: 'beets',      label: 'Beets',                color: '#8e44ad' },
    { key: 'flowers',    label: 'Flowers / Bulbs',      color: '#e74c3c' },
    { key: 'vegetables', label: 'Vegetables',           color: '#17a589' },
    { key: 'fruit',      label: 'Fruit & Orchards',     color: '#cb4335' },
    { key: 'legumes',    label: 'Legumes',              color: '#1a5276' },
    { key: 'nursery',    label: 'Tree Nurseries',       color: '#2980b9' },
    { key: 'industrial', label: 'Industrial Crops',     color: '#d4ac0d' },
    { key: 'nature',     label: 'Nature & Forest',      color: '#566573' },
    { key: 'other',      label: 'Other',                color: '#95a5a6' },
];

// Returns the hex colour for a Dutch gewas name.
function getCropColor(cropName) {
    if (!cropName) return '#95a5a6';
    const n = cropName.toLowerCase();
    if (n.includes('gras') || n.includes('weide'))                        return '#27ae60';
    if (n.includes('mais') || n.includes('maïs'))                         return '#f1c40f';
    if (n.includes('aardappel'))                                           return '#d35400';
    if (n.includes('tarwe') || n.includes('graan') || n.includes('gerst') ||
        n.includes('haver') || n.includes('rogge') || n.includes('triticale') ||
        n.includes('spelt') || n.includes('raaigras') || n.includes('zwenkgras') ||
        n.includes('boekweit') || n.includes('soedangras') || n.includes('sorghum')) return '#e67e22';
    if (n.includes('bieten'))                                              return '#8e44ad';
    // industrial before flowers — zonnebloem contains 'bloem' but is industrial
    if (n.includes('koolzaad') || n.includes('raapzaad') || n.includes('vlas') ||
        n.includes('hennep') || n.includes('zonnebloem') || n.includes('miscanthus') ||
        n.includes('luzerne') || n.includes('cichorei') || n.includes('mosterd') ||
        n.includes('groenbemester') || n.includes('facelia') || n.includes('tagetes') ||
        n.includes('bladrammenas') || n.includes('drachtplant') || n.includes('raketblad') ||
        n.includes('japanse haver') || n.includes('soja') || n.includes('quinoa') ||
        n.includes('teunisbloem') || n.includes('lisdodde') || n.includes('hop')) return '#d4ac0d';
    // flowers: fix bloemkool bug — cauliflower contains 'bloem' but is a vegetable
    if (n.includes('bollen') || (n.includes('bloem') && !n.includes('bloemkool'))) return '#e74c3c';
    if (n.includes('erwten') || n.includes('bonen') || n.includes('lupinen') ||
        n.includes('klaver') || n.includes('wikke') || n.includes('kapucijner') ||
        n.includes('esparcette') || n.includes('rolklaver'))               return '#1a5276';
    if (n.includes('kool') || n.includes('prei') || n.includes('ui') ||
        n.includes('wortel') || n.includes('peen') || n.includes('spinazie') ||
        n.includes('selderij') || n.includes('schorseneer') || n.includes('witlof') ||
        n.includes('broc') || n.includes('asperge') || n.includes('pompoen') ||
        n.includes('courgette') || n.includes('komkommer') || n.includes('andijvie') ||
        n.includes('rabarber') || n.includes('knoflook') || n.includes('sjalot') ||
        n.includes('radijs') || n.includes('paksoi') || n.includes('venkel') ||
        n.includes('peterselie') || n.includes('kroten') || n.includes('pastinaak') ||
        n.includes('aardpeer') || n.includes('kruiden') || n.includes('snijgroen') ||
        n.includes('valeriaan'))                                            return '#17a589';
    if (n.includes('appel') || n.includes('peer') || n.includes('kers') ||
        n.includes('pruim') || n.includes('bessen') || n.includes('aardbei') ||
        n.includes('framboos') || n.includes('bramen') || n.includes('druif') ||
        n.includes('noten') || n.includes('cranberry') || n.includes('vruchtboom')) return '#cb4335';
    if (n.includes('laanboom') || n.includes('laanbomen') || n.includes('sierheesters') ||
        n.includes('sierconiferen') || n.includes('vaste planten') || n.includes('buxus') ||
        n.includes('rozenstruik') || n.includes('bosplant') || n.includes('haagplant') ||
        n.includes('trek- en') || n.includes('ericac') || n.includes('onderstam') ||
        n.includes('kerstboom') || n.includes('moerboom'))                 return '#2980b9';
    if (n.startsWith('bos') || n.includes('natuur') || n.includes('riet') ||
        n.includes('wilgenhak') || n.includes('voedselbos') || n.includes('woudboom') ||
        n.startsWith('rand,') || n.startsWith('rand ') || n.includes('bufferstrook') ||
        n.includes('onbeteeld') || n.includes('sloot'))                    return '#566573';
    return '#95a5a6';
}

const FEATURE_INFO_LAYER_BY_NAME = {
    'BRP Crop Parcel': 'brp',
    'BAG Building': 'bag',
    'BAG Usage': 'bag',
    'Natura 2000 Area': 'natura2000',
    'Nature Network NL': 'nnn',
    'Kadastraal Perceel': 'kadastralekaart',
    'Administrative Boundary': 'grenzen',
    'KRD Veehouderij': 'krd',
    'KRD Stal (housing unit)': 'krd',
    'Health Facility': 'health',
    'Pesticides Station': 'pesticides',
    'School': 'schools',
    'WFD Surface Water Body': 'wfd',
    'Water Hydrography': 'hydrography',
    'Waterschap': 'waterschappen'
};

function closeFeatureInfoForLayer(layerId) {
    const infoPanel = document.getElementById('info-panel');
    if (!infoPanel || infoPanel.classList.contains('hidden')) return;
    if (infoPanel.dataset.layerId === layerId) {
        infoPanel.classList.add('hidden');
        delete infoPanel.dataset.layerId;
        removeHighlight(_lastHighlightedLayer);
        _lastHighlightedLayer = null;
    }
}

// Sidebar Engine: Injects clicked feature properties into the HTML panel
function showFeatureInfo(layerName, properties, sourceUrl, layerId) {
    const infoPanel    = document.getElementById('info-panel');
    const panelTitle   = document.getElementById('panel-title');
    const panelContent = document.getElementById('panel-content');
    if (!infoPanel || !panelTitle || !panelContent) return;

    infoPanel.dataset.layerId = layerId || FEATURE_INFO_LAYER_BY_NAME[layerName] || '';
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

function handleFeatureClick(layerName, feature, e, customProperties, sourceUrl, layerId) {
    L.DomEvent.stopPropagation(e);
    if (_lastHighlightedLayer && _lastHighlightedLayer !== e.target) {
        removeHighlight(_lastHighlightedLayer);
    }
    applyHighlight(e.target);
    _lastHighlightedLayer = e.target;

    const centroid = getFeatureCentroid(feature);
    if (centroid) {
        isProgrammaticMove = true;
        map.panTo(centroid, { animate: true, duration: 0.45 });
    }

    showFeatureInfo(layerName, customProperties || feature.properties, sourceUrl, layerId);
}

// Appends a linked-data section below the main sidebar properties
function appendSidebarSection(title, rows) {
    const panelContent = document.getElementById('panel-content');
    if (!panelContent) return;

    const section = document.createElement('div');
    section.className = 'linked-data-section';

    const header = document.createElement('div');
    header.className = 'linked-data-title';
    header.innerText = title;
    section.appendChild(header);

    if (rows.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'linked-data-empty';
        empty.innerText = 'No linked data found in viewport.';
        section.appendChild(empty);
    } else {
        rows.forEach(item => {
            if (typeof item === 'string') {
                // Sub-header row (parcel label etc.)
                const sub = document.createElement('div');
                sub.className = 'linked-data-subtitle';
                sub.innerText = item;
                section.appendChild(sub);
            } else {
                const [key, value] = item;
                const row = document.createElement('div');
                row.className = 'linked-data-row';
                const keyDiv = document.createElement('div');
                keyDiv.className = 'linked-data-key';
                keyDiv.innerText = key;
                const valueDiv = document.createElement('div');
                valueDiv.className = 'linked-data-value';
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
    removeHighlight(_lastHighlightedLayer);
    _lastHighlightedLayer = null;
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
            triggerFeatureBuffer('brp', feature, layer, '#27ae60');

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

function getBagUsageType(usageGoal) {
    const goal = Array.isArray(usageGoal) ? usageGoal.join(',') : (usageGoal || '');
    const text = goal.toLowerCase();
    if (text.includes('woonfunctie'))             return 'residential';
    if (text.includes('kantoorfunctie'))           return 'office';
    if (text.includes('industriefunctie'))         return 'industrial';
    if (text.includes('winkelfunctie'))            return 'retail';
    if (text.includes('bijeenkomstfunctie'))       return 'assembly';
    if (text.includes('gezondheidszorgfunctie'))   return 'healthcare';
    if (text.includes('onderwijsfunctie'))         return 'education';
    if (text.includes('sportfunctie'))             return 'sports';
    if (text.includes('logiesfunctie'))            return 'lodging';
    return 'other';
}

// Fallback lookup: pandId → usage type — populated from verblijfsobject cache
const bagUsageTypeMap = {};

const BAG_FILL = {
    residential: '#2980b9', office: '#8e44ad', industrial: '#717d7e',
    retail: '#f39c12',      assembly: '#1abc9c', healthcare: '#e74c3c',
    education: '#27ae60',   sports: '#f1c40f',   lodging: '#d35400',
    other: '#95a5a6'
};
const BAG_BORDER = {
    residential: '#2471a3', office: '#76359d', industrial: '#5d6d7e',
    retail: '#d4920a',      assembly: '#17a589', healthcare: '#c0392b',
    education: '#1e8449',   sports: '#d4ac0d',   lodging: '#a84300',
    other: '#7f8c8d'
};

function getBagFeatureType(feature) {
    const props = feature && feature.properties;
    if (props && props.gebruiksdoel) return getBagUsageType(props.gebruiksdoel);
    const id = props && props.identificatie;
    return (id && bagUsageTypeMap[id]) || 'other';
}

function getBagPolygonStyle(feature) {
    const type = getBagFeatureType(feature);
    return { color: BAG_BORDER[type], weight: 1.3, fillColor: BAG_FILL[type], fillOpacity: 0.55 };
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
    style: getBagPolygonStyle,
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
            triggerFeatureBuffer('bag', feature, layer, '#555555');
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
            triggerFeatureBuffer('bag_usage', feature, layer, '#8e44ad');
        });
    }
});

// 3C. Natura 2000 Areas
const natura2000Layer = L.geoJSON(null, {
    style: (feature) => feature.properties?.layer_type === 'center' ? {} : ({
        color: '#117a65',
        weight: 2,
        fillColor: '#16a085',
        fillOpacity: 0.34
    }),
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
            fillColor: '#16a085',
            color: '#117a65',
            weight: 1,
            fillOpacity: 0.9
        });
    },
    onEachFeature: (feature, layer) => {
        layer.on('click', (e) => {
            const p = feature.properties || {};
            const isCenter = p.layer_type === 'center';
            const displayProps = {
                'Name':         p.naam_n2k || p.naam || '—',
                'Site code':    p.sitecode_h || p.sitecode_v || '—',
                'Status':       p.status || '—',
                'Protection':   p.beschermin || '—',
                'Nr':           p.nr ?? '—',
            };
            handleFeatureClick(isCenter ? 'Natura 2000 Center' : 'Natura 2000 Area', feature, e, displayProps, 'https://www.pdok.nl/introductie/-/article/natura2000', 'natura2000');
            triggerFeatureBuffer('natura2000', feature, layer, '#16a085');
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

// NNN WMS — 46k+ polygons, WMS handles full-country visual; GeoJSON handles click/hover
const nnnWmsLayer = L.tileLayer.wms('https://service.pdok.nl/provincies/natuurnetwerk-nederland/wms/v1_0', {
    layers: 'PS.ProtectedSite',
    format: 'image/png',
    transparent: true,
    opacity: 0.55,
    attribution: 'Natuurnetwerk Nederland &copy; BIJ12/PDOK'
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
            triggerFeatureBuffer('kadastralekaart', feature, layer, '#e67e22');

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
// 12 distinct province colors (assigned by ogc_fid index — exactly 12 provinces)
const GRENZEN_PROVINCE_PALETTE = [
    '#c0392b','#2980b9','#27ae60','#d35400','#8e44ad','#16a085',
    '#2c3e50','#f39c12','#1a5276','#117a65','#784212','#4a235a'
];
// 10-color palette for 352 municipalities (hash-distributed)
const GRENZEN_GEMEENTE_PALETTE = [
    '#e74c3c','#3498db','#2ecc71','#f39c12','#9b59b6',
    '#1abc9c','#e67e22','#d35400','#2980b9','#16a085'
];
function grenzenHash(str) {
    let h = 0;
    for (let i = 0; i < str.length; i++) h = (Math.imul(31, h) + str.charCodeAt(i)) | 0;
    return Math.abs(h);
}
function getGrenzenColor(feature) {
    const lt   = feature?.properties?.layer_type;
    const name = feature?.properties?.gemeentenaam || '';
    const id   = feature?.properties?.id || 0;
    if (lt === 'landsgrens') return '#8e44ad';
    if (lt === 'provincies') return GRENZEN_PROVINCE_PALETTE[id % GRENZEN_PROVINCE_PALETTE.length];
    return GRENZEN_GEMEENTE_PALETTE[grenzenHash(name) % GRENZEN_GEMEENTE_PALETTE.length];
}
const GRENZEN_WEIGHTS = { gemeenten: 1.2, provincies: 2.5, landsgrens: 3.5 };

const grenzenLayer = L.geoJSON(null, {
    style: (feature) => ({
        color:   getGrenzenColor(feature),
        weight:  GRENZEN_WEIGHTS[feature?.properties?.layer_type] || 1.5,
        fill:    false,
        opacity: 0.9
    }),
    onEachFeature: (feature, layer) => {
        layer.on('click', (e) => {
            handleFeatureClick('Administrative Boundary', feature, e, null, 'https://www.pdok.nl/introductie/-/article/bestuurlijke-grenzen');
            triggerFeatureBuffer('grenzen', feature, layer, '#8e44ad');
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
            triggerFeatureBuffer('krd', feature, layer, '#e67e22');
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
            triggerFeatureBuffer('krd_stallen', feature, layer, '#8e44ad');
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
        const eBbox = `${map.getBounds().getWest()},${map.getBounds().getSouth()},${map.getBounds().getEast()},${map.getBounds().getNorth()}`;
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
    pointToLayer: (feature, latlng) => {
        const color = getHealthColor(feature.properties.facility_type);
        return L.marker(latlng, {
            icon: L.divIcon({
                className: 'health-marker',
                html: `<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 28 28">
                         <circle cx="14" cy="14" r="12.5" fill="${color}" stroke="white" stroke-width="2"/>
                         <rect x="12" y="7" width="4" height="14" rx="1" fill="white"/>
                         <rect x="7" y="12" width="14" height="4" rx="1" fill="white"/>
                       </svg>`,
                iconSize:    [28, 28],
                iconAnchor:  [14, 14],
                popupAnchor: [0, -18]
            })
        });
    },
    onEachFeature: (feature, layer) => {
        layer.on('click', (e) => {
            handleFeatureClick('Health Facility', feature, e, null, 'https://data.humdata.org/dataset/hotosm-nld-health-facilities');
            triggerFeatureBuffer('health', feature, layer, '#e91e8c');
        });
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
            triggerFeatureBuffer('pesticides', feature, layer, '#f39c12');
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

let activeSchoolTypes = new Set();

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
    const layerOn = !!document.getElementById('layer-schools')?.checked;
    document.querySelectorAll('.school-legend-item').forEach(function(el) {
        const isActive = layerOn && (activeSchoolTypes.size === 0 || activeSchoolTypes.has(el.dataset.type));
        el.style.background  = isActive ? '#eaf4fb' : '';
        el.style.fontWeight  = isActive ? 'bold'    : '';
        el.style.borderLeft  = isActive ? '3px solid #2c3e50' : '3px solid transparent';
        el.style.paddingLeft = '6px';
    });
}

function applySchoolTypeFilter() {
    schoolsLayer.eachLayer(function(layer) {
        const type = layer.feature?.properties?.onderwijstype;
        const visible = activeSchoolTypes.size === 0 || activeSchoolTypes.has(type);
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
            triggerFeatureBuffer('schools', feature, layer, '#16a085');
        });
    }
});

// 3I. Nature Network Netherlands / Natuurnetwerk Nederland (INSPIRE harmonized)
// Purple colour scheme to distinguish from Natura 2000 (teal).
const nnnLayer = L.geoJSON(null, {
    style: (feature) => feature.properties?.layer_type === 'center' ? {} : ({
        color: '#6c3483',
        weight: 2,
        fillColor: '#9b59b6',
        fillOpacity: 0.34
    }),
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
            const isCenter = feature.properties?.layer_type === 'center';
            handleFeatureClick(isCenter ? 'Nature Network NL Center' : 'Nature Network NL', feature, e, null, 'https://service.pdok.nl/provincies/natuurnetwerk-nederland/atom/index.xml', 'nnn');
            triggerFeatureBuffer('nnn', feature, layer, '#9b59b6');
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
            const rawType = (p.specialisedzonetype || '').split('/').pop().replace(/WaterBody$/i, '') || null;
            const typeLabel = rawType ? rawType.charAt(0).toUpperCase() + rawType.slice(1) : 'N/A';
            const display = {
                'Water Body Name': p.text              || 'N/A',
                'Water Body Type': typeLabel,
                'Authority':       p.characterstring   || 'N/A',
                'Local ID':        p.localid           || 'N/A',
                'Date':            p.beginlifespanversion || p.date || 'N/A',
                'Link':            p.link              || 'N/A',
            };
            handleFeatureClick('WFD Surface Water Body', feature, e, display, 'https://service.pdok.nl/ihw/krw-oppervlaktewaterlichaams-geharmoniseerd/wms/v1_0');
            triggerFeatureBuffer('wfd', feature, layer, '#1a5276');
        });
    }
});


// 3K. Water Hydrography (INSPIRE harmonized — Water Authorities)
// Only types confirmed present in the DB (from SELECT DISTINCT localtype query).
const HYDRO_TYPE_LABELS = {
    'rivier':                           'Rivier (river)',
    'kanaal':                           'Kanaal (canal)',
    'gracht':                           'Gracht (urban canal)',
    'primair boezemwater':              'Primair boezemwater (primary channel)',
    'secundair boezemwater':            'Secundair boezemwater (secondary channel)',
    'hoofdwaterloop':                   'Hoofdwaterloop (main waterway)',
    'boezemwater':                      'Boezemwater (storage waterway)',
    'tertiair boezemwater':             'Tertiair boezemwater (tertiary channel)',
    'waterloop (watergang)':            'Waterloop / watergang (waterway)',
    'polderwaterloop (polderwatergang)': 'Polderwaterloop (polder waterway)',
    'beek':                             'Beek (stream / brook)',
    'watervoerende weg':                'Watervoerende weg (roadside waterway)',
    'sloot':                            'Sloot (drainage ditch)',
    'schouwsloot':                      'Schouwsloot (inspected ditch)',
    'wegsloot':                         'Wegsloot (roadside ditch)',
    'dijksloot':                        'Dijksloot (dike ditch)',
    'bermsloot':                        'Bermsloot (verge ditch)',
    'spoorsloot':                       'Spoorsloot (railway ditch)',
    'greppel':                          'Greppel (shallow drain)',
    'te verlanden sloot':               'Te verlanden sloot (silting ditch)',
    'perceelsloot':                     'Perceelsloot (parcel ditch)',
    'boezemdijksloot':                  'Boezemdijksloot (boezem dike ditch)',
    'scheisloot':                       'Scheisloot (boundary ditch)',
    'poldersloot':                      'Poldersloot (polder ditch)',
    'kavelsloot':                       'Kavelsloot (plot ditch)',
    'boezemsloot':                      'Boezemsloot (boezem ditch)',
    'vijver':                           'Vijver (pond)',
    'stadsvijver':                      'Stadsvijver (urban pond)',
    'bergingsvijver':                   'Bergingsvijver (retention pond)',
    'plas':                             'Plas (open water)',
    'duinmeer':                         'Duinmeer (dune lake)',
    'meer':                             'Meer (lake)',
    'poel':                             'Poel (small pond)',
    'ven':                              'Ven (moorland pool)',
    'wiel':                             'Wiel (ox-bow lake)',
    'dobbe':                            'Dobbe (village pond)',
    'spaarbekken':                      'Spaarbekken (reservoir)',
    'moeras':                           'Moeras (marsh / wetland)',
    'uitmonding':                       'Uitmonding (outflow / mouth)',
};

function getHydrographyStyle(feature) {
    const lt = (feature?.properties?.localtype || '').toLowerCase();
    const gt = feature?.geometry?.type || '';

    // Polygon geometry → filled standing water
    if (gt === 'Polygon' || gt === 'MultiPolygon') {
        return { color: '#388e3c', weight: 1, fill: true, fillColor: '#66bb6a', fillOpacity: 0.5 };
    }
    // Standing water (vijver, plas, meer, poel, ven, wiel, dobbe, spaarbekken, moeras, duinmeer)
    if (lt.includes('vijver') || lt.includes('plas') || lt === 'meer' || lt === 'duinmeer' ||
        lt === 'poel' || lt === 'ven' || lt === 'wiel' || lt === 'dobbe' ||
        lt === 'spaarbekken' || lt === 'moeras' || lt === 'bergingsvijver') {
        return { color: '#2e7d32', weight: 4, fill: false, opacity: 0.9, lineCap: 'round' };
    }
    // Main channels — rivier, kanaal, gracht, primair/secundair boezemwater
    if (lt === 'rivier' || lt === 'kanaal' || lt === 'gracht' ||
        lt === 'primair boezemwater' || lt === 'secundair boezemwater') {
        return { color: '#1565c0', weight: 6, fill: false, opacity: 1.0 };
    }
    // Major waterways — hoofdwaterloop, boezemwater, tertiair boezemwater
    if (lt === 'hoofdwaterloop' || lt === 'boezemwater' || lt === 'tertiair boezemwater') {
        return { color: '#e65100', weight: 2.2, fill: false, opacity: 0.95 };
    }
    // General waterways — watergang, polderwaterloop, beek, watervoerende weg
    if (lt === 'waterloop (watergang)' || lt === 'polderwaterloop (polderwatergang)' ||
        lt === 'beek' || lt === 'watervoerende weg') {
        return { color: '#00695c', weight: 1.5, fill: false, opacity: 0.9 };
    }
    // Ditches — all sloot variants + greppel
    if (lt.includes('sloot') || lt === 'greppel') {
        return { color: '#4e342e', weight: 0.8, fill: false, opacity: 0.8 };
    }
    // Unlabelled (null) — largest group at 761k features
    return { color: '#90a4ae', weight: 1.8, fill: false, opacity: 0.75 };
}

const hydrographyLayer = L.geoJSON(null, {
    renderer: L.svg(),
    style: getHydrographyStyle,
    pointToLayer: (feature, latlng) => L.circleMarker(latlng, {
        radius: 5,
        fillColor: '#1a6fa8',
        color: '#154360',
        weight: 1,
        fillOpacity: 0.85
    }),
    onEachFeature: (feature, layer) => {
        layer.on('click', (e) => {
            const p  = feature.properties || {};
            const lt = (p.localtype || '').toLowerCase();
            const typeLabel = HYDRO_TYPE_LABELS[lt] || p.localtype || 'N/A';
            const display = {
                'Name':            p.name         || 'N/A',
                'Type':            typeLabel,
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
            triggerFeatureBuffer('hydrography', feature, layer, '#1a6fa8');
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
// 4. Spatial Utility Functions
// =========================================================

function addFilteredData(layerObject, data) {
    if (!data || !data.features) return;
    if (layerObject === natura2000Layer || layerObject === nnnLayer) {
        layerObject.addData(addCenterPointFeatures(data));
        applyCenterPointVisibility(layerObject);
        return;
    }
    layerObject.addData(data);
}

function addCenterPointFeatures(data) {
    if (typeof turf === 'undefined') return data;
    const features = [];
    data.features.forEach(feature => {
        features.push(feature);
        if (!feature?.geometry || feature.properties?.layer_type === 'center') return;
        const geomType = feature.geometry.type;
        if (geomType !== 'Polygon' && geomType !== 'MultiPolygon') return;
        try {
            const center = turf.pointOnFeature(feature);
            center.properties = {
                ...(feature.properties || {}),
                layer_type: 'center',
                parent_layer_type: feature.properties?.layer_type || 'area'
            };
            features.push(center);
        } catch (err) {
            console.warn('Center point generation failed:', err);
        }
    });
    return { ...data, features };
}

function isCenterPointEnabled(layerObject) {
    if (layerObject === natura2000Layer) return document.getElementById('natura-center-toggle')?.classList.contains('selected') !== false;
    if (layerObject === nnnLayer) return document.getElementById('nnn-center-toggle')?.classList.contains('selected') !== false;
    return true;
}

function applyCenterPointVisibility(layerObject) {
    const visible = isCenterPointEnabled(layerObject);
    layerObject.eachLayer(layer => {
        if (layer.feature?.properties?.layer_type !== 'center') return;
        if (!visible && layer === _lastHighlightedLayer) {
            removeHighlight(_lastHighlightedLayer);
            _lastHighlightedLayer = null;
            document.getElementById('info-panel')?.classList.add('hidden');
        }
        if (typeof layer.setOpacity === 'function') {
            layer.setOpacity(visible ? 1 : 0);
        }
        if (typeof layer.getElement === 'function') {
            const el = layer.getElement();
            if (el) {
                el.style.display = visible ? '' : 'none';
                el.style.pointerEvents = visible ? '' : 'none';
            }
        }
    });
}

document.getElementById('natura-center-toggle')?.addEventListener('click', function() {
    this.classList.toggle('selected');
    applyCenterPointVisibility(natura2000Layer);
    document.dispatchEvent(new CustomEvent('summary:refresh:natura'));
});

document.getElementById('nnn-center-toggle')?.addEventListener('click', function() {
    this.classList.toggle('selected');
    applyCenterPointVisibility(nnnLayer);
    document.dispatchEvent(new CustomEvent('summary:refresh:nnn'));
});

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
    const naturaAreas = (natura2000Cache?.features || []);
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
        
        let needsRefresh = false;
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
                    needsRefresh = true;
                } else {
                    selectElement.style.display = 'none'; 
                }
            }
        }
        
        // If years were updated, re-trigger the data fetch so we don't query a default year (like 2025) that isn't in the DB
        if (needsRefresh && !isProgrammaticMove) {
            map.fire('moveend');
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
        const response = await fetch(primaryApiUrl);
        if (!response.ok) throw new Error(`HTTP Error: ${response.status}`);

        const data = await response.json();
        if (data.features && data.features.length > 0) {
            if (layerObject === bagLayer)         bagBuildingCache = data;
            if (layerObject === natura2000Layer)  natura2000Cache  = data;
            if (layerObject === grenzenLayer)     grenzenCache     = data;
            if (layerObject === nnnLayer)         nnnCache         = data;
            if (layerObject === healthLayer)      healthCache      = data;
            if (layerObject === schoolsLayer)     schoolsCache     = data;
            if (layerObject === pesticidesLayer)  pesticidesCache  = data;
            addFilteredData(layerObject, data);
            window[flagName] = true;
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
                if (layerObject === bagLayer)         bagBuildingCache = fallbackData;
                if (layerObject === natura2000Layer)  natura2000Cache  = fallbackData;
                if (layerObject === grenzenLayer)     grenzenCache     = fallbackData;
                if (layerObject === nnnLayer)         nnnCache         = fallbackData;
                if (layerObject === healthLayer)      healthCache      = fallbackData;
                if (layerObject === schoolsLayer)     schoolsCache     = fallbackData;
                if (layerObject === pesticidesLayer)  pesticidesCache  = fallbackData;
                addFilteredData(layerObject, fallbackData);
                window[flagName] = true;
            }
        } catch (fallbackError) {
            console.error(`[${layerName}] ❌ Both API and Database failed!`, fallbackError);
        }
    }
}

function updateLegend() {
    const schoolsActive = document.getElementById('layer-schools').checked;
    const grenzenActive = document.getElementById('layer-grenzen').checked;
    document.getElementById('schools-legend').style.display = schoolsActive ? 'block' : 'none';
    document.getElementById('legend-grenzen').style.display = grenzenActive ? 'block' : 'none';
}

function setLayerRowExpanded(checkbox, expanded) {
    const row = checkbox?.closest('.layer-row');
    const panel = row?.querySelector('.layer-expand-panel');
    if (!row || !panel) return;
    if (expanded) {
        document.querySelectorAll('#layer-controls .layer-row.expanded').forEach(openRow => {
            if (openRow === row) return;
            openRow.classList.remove('expanded');
            openRow.querySelector('.layer-expand-panel')?.setAttribute('hidden', '');
        });
    }
    row.classList.toggle('expanded', expanded);
    if (expanded) panel.removeAttribute('hidden');
    else panel.setAttribute('hidden', '');
}

let gemeenteHighlightLayer = null;

function clearGemeenteHighlight() {
    if (gemeenteHighlightLayer) {
        map.removeLayer(gemeenteHighlightLayer);
        gemeenteHighlightLayer = null;
    }
}

async function focusGemeente(gemeente, options = {}) {
    if (!gemeente) {
        clearGemeenteHighlight();
        return null;
    }

    const resp = await fetch(`/api/gemeente_boundary?gemeente=${encodeURIComponent(gemeente)}`);
    if (!resp.ok) throw new Error(`Could not load boundary for ${gemeente}`);
    const feature = await resp.json();

    clearGemeenteHighlight();
    gemeenteHighlightLayer = L.geoJSON(feature, {
        style: {
            color: '#f59e0b',
            weight: 4,
            fillColor: '#f59e0b',
            fillOpacity: 0.08,
            opacity: 1,
            dashArray: '8 5'
        },
        interactive: false
    }).addTo(map);

    const bounds = gemeenteHighlightLayer.getBounds();
    if (bounds.isValid()) {
        isProgrammaticMove = true;
        map.fitBounds(bounds, { padding: [28, 28], maxZoom: options.maxZoom ?? 13, animate: false });
    }
    return feature;
}

// Checkbox Toggles
document.querySelectorAll('.map-layer-toggle').forEach(checkbox => {
    checkbox.addEventListener('change', async function() {
        const layerId = this.value;
        const layer = layerRegistry[layerId];

        if (this.checked) {
            setLayerRowExpanded(this, true);
            layer.addTo(map);
            // bagUsageLayer is NOT added to map — usage data loads into bagUsageTypeMap and colors the polygons directly
            
            // CRS84 forces WFS to return standard [Lon, Lat] GeoJSON, preventing the ocean bug
            const crs84 = 'urn:ogc:def:crs:OGC:1.3:CRS84';

            if (layerId === 'natura2000') {
                natura2000WmsLayer.addTo(map);
                layer.clearLayers();
                const naturaApi = `https://api.pdok.nl/rvo/natura2000/ogc/v1/collections/natura2000/items?f=json&limit=${NATURA2000_API_LIMIT}&bbox=${bboxNetherlands}`;
                const naturaDb  = `/api/natura2000_areas?bbox=${bboxNetherlands}`;
                await loadNationwideLayer(layer, 'Natura 2000', naturaApi, naturaDb, 'isNaturaLoaded');
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
                nnnWmsLayer.addTo(map);
                layer.clearLayers();
                map.fire('moveend');
            }
            else if (layerId === 'health') {
                const healthDb = `/api/health_facilities?bbox=${bboxNetherlands}`;
                await loadNationwideLayer(layer, 'Health Facilities', healthDb, healthDb, 'isHealthLoaded');
            }
            else if (layerId === 'schools') {
                const schoolsDb = `/api/schools?bbox=${bboxNetherlands}`;
                await loadNationwideLayer(layer, 'Schools', schoolsDb, schoolsDb, 'isSchoolsLoaded');
            }
            else if (layerId === 'pesticides') {
                const pesticidesDb = `/api/pesticides?bbox=${bboxNetherlands}`;
                await loadNationwideLayer(layer, 'Pesticides', pesticidesDb, pesticidesDb, 'isPesticidesLoaded');
            }
            else {
                // Trigger BRP and BAG dynamic loading
                map.fire('moveend');
            }
        } else {
            setLayerRowExpanded(this, false);
            map.removeLayer(layer);
            if (layerId === 'bag') {
                bagLayer.clearLayers();
                bagUsageLayer.clearLayers();
                bagBuildingCache = null;
                bagUsageCache = null;
                for (const k in bagUsageTypeMap) delete bagUsageTypeMap[k];
                        }
            if (layerId === 'natura2000') {
                map.removeLayer(natura2000WmsLayer);
                layer.clearLayers();
                natura2000Cache = null;
                window.isNaturaLoaded = false;
            }
            if (layerId === 'kadastralekaart') {
                map.removeLayer(kadastralekaartWmsLayer);
                layer.clearLayers();
                kadastraalPerceelCache = null;
            }
            if (layerId === 'nnn') {
                map.removeLayer(nnnWmsLayer);
                layer.clearLayers();
                nnnCache = null;
                isNNNLoaded = false;
            }
            if (layerId === 'health') {
                layer.clearLayers();
                healthCache = null;
                window.isHealthLoaded = false;
            }
            if (layerId === 'schools') {
                layer.clearLayers();
                schoolsCache = null;
                window.isSchoolsLoaded = false;
            }
            if (layerId === 'pesticides') {
                layer.clearLayers();
                pesticidesCache = null;
                window.isPesticidesLoaded = false;
            }
            closeFeatureInfoForLayer(layerId);
            // We do NOT clear data for Natura/Woondeals so they remain instantly visible next time
            if (layerId === 'brp' || layerId === 'bag') {
                layer.clearLayers();
            }
            if (layerId === 'brp') {
                brpCache = null;
                        }
        }

        updateLegend();
    });
});

// =========================================================
// BRP Crop Filter Chips
// =========================================================
const BRP_ALL_CATEGORIES = ['grassland', 'maize', 'potato', 'cereals', 'beets', 'flowers', 'vegetables', 'fruit', 'legumes', 'nursery', 'industrial', 'nature', 'other'];
const brpActiveFilters = new Set(BRP_ALL_CATEGORIES);

function applyBrpFilter() {
    const showAll = brpActiveFilters.size === BRP_ALL_CATEGORIES.length;
    if (typeof brpLayer === 'undefined') return;
    brpLayer.eachLayer(function(layer) {
        const cat = getBrpCropTypeName(layer.feature?.properties?.gewas);
        const show = showAll || brpActiveFilters.has(cat);
        if (typeof layer.setStyle === 'function') {
            layer.setStyle({
                opacity: show ? 1 : 0,
                fillOpacity: show ? (layer._origFillOpacity ?? 0.4) : 0
            });
        }
        const el = layer.getElement();
        if (el) {
            el.style.pointerEvents = show ? '' : 'none';
        }
    });
}

document.querySelectorAll('.brp-filter-item').forEach(function(item) {
    item.addEventListener('click', function() {
        const filter = this.dataset.brpFilter;
        if (!filter) return;
        const allSelected = brpActiveFilters.size === BRP_ALL_CATEGORIES.length;

        if (allSelected) {
            brpActiveFilters.clear();
            document.querySelectorAll('.brp-filter-item').forEach(i => i.classList.remove('selected'));
            brpActiveFilters.add(filter);
            this.classList.add('selected');
        } else if (brpActiveFilters.has(filter)) {
            brpActiveFilters.delete(filter);
            this.classList.remove('selected');
            if (brpActiveFilters.size === 0) {
                BRP_ALL_CATEGORIES.forEach(c => brpActiveFilters.add(c));
                document.querySelectorAll('.brp-filter-item').forEach(i => i.classList.add('selected'));
            }
        } else {
            brpActiveFilters.add(filter);
            this.classList.add('selected');
        }
        applyBrpFilter();
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

document.getElementById('brp-gemeente-filter')?.addEventListener('change', async function () {
    const gemeente = this.value;
    try {
        if (gemeente) await focusGemeente(gemeente);
        else clearGemeenteHighlight();
    } catch (err) {
        console.warn('Gemeente focus failed:', err);
    }
    if (map.hasLayer(brpLayer)) {
        brpLayer.clearLayers();
        brpCache = null;
        map.fire('moveend');
    }
});

let selectedKadGemeente = '';

function applyKadastralGemeenteFilter() {
    if (typeof kadastralekaartLayer === 'undefined') return;
    kadastralekaartLayer.eachLayer(layer => {
        const gemeente = layer.feature?.properties?.gemeente || '';
        const show = !selectedKadGemeente || gemeente === selectedKadGemeente;
        if (typeof layer.setStyle === 'function') {
            layer.setStyle({
                fillOpacity: show ? 0.15 : 0,
                opacity: show ? 1 : 0,
                weight: show ? 1 : 0
            });
        }
    });
}

fetch('/api/kad_gemeenten')
    .then(r => r.json())
    .then(names => {
        const sel = document.getElementById('kad-gemeente-filter');
        if (!sel || !Array.isArray(names)) return;
        names.forEach(name => {
            const opt = document.createElement('option');
            opt.value = name;
            opt.textContent = name;
            sel.appendChild(opt);
        });
    });

document.getElementById('kad-gemeente-filter')?.addEventListener('change', async function() {
    selectedKadGemeente = this.value || '';
    try {
        if (selectedKadGemeente) await focusGemeente(selectedKadGemeente, { maxZoom: CADASTRAL_MIN_ZOOM });
        else clearGemeenteHighlight();
    } catch (err) {
        console.warn('Gemeente focus failed:', err);
    }
    applyKadastralGemeenteFilter();
    if (map.hasLayer(kadastralekaartLayer)) map.fire('moveend');
});

// KRD exact bedrijfstype dropdown — re-fetches data and syncs chip highlights.
const KRD_BEDRIJFSTYPE_CATEGORY = {
    'Biggen': 'varkens', 'Dekberen': 'varkens', 'Zeugen': 'varkens', 'Vleesvarkens': 'varkens',
    'Melkrundvee': 'rundvee', 'Vleesvee': 'rundvee',
    'Leghennen': 'pluimvee', 'Vleeskuikens': 'pluimvee', 'Ov.Pluimvee': 'pluimvee',
    'Geiten': 'geiten', 'Schapen': 'geiten',
    'Paarden': 'paarden',
    'Konijnen': 'konijnen', 'Nerts Vos': 'konijnen',
    'Overige': 'overig', 'zeer gering van omvang': 'overig',
};

function syncKrdChipsToDropdown(selectedValue) {
    if (!selectedValue) {
        // "Alle diersoorten" — restore all chips
        KRD_ALL_CATEGORIES.forEach(c => krdActiveFilters.add(c));
        document.querySelectorAll('.krd-filter-item').forEach(i => i.classList.add('selected'));
    } else {
        const cat = KRD_BEDRIJFSTYPE_CATEGORY[selectedValue];
        if (cat) {
            krdActiveFilters.clear();
            document.querySelectorAll('.krd-filter-item').forEach(i => i.classList.remove('selected'));
            krdActiveFilters.add(cat);
            document.querySelector(`.krd-filter-item[data-krd-filter="${cat}"]`)?.classList.add('selected');
        }
    }
}

document.getElementById('filter-krd-animal').addEventListener('change', function() {
    syncKrdChipsToDropdown(this.value);
    applyKrdFilter();
    if (map.hasLayer(krdLayer)) {
        krdLayer.clearLayers();
        map.fire('moveend');
    }
});

// KRD animal-type filter chips — client-side show/hide, no re-fetch needed.
// Category keys match data-krd-filter attributes on .krd-filter-item elements.
const KRD_ALL_CATEGORIES = ['varkens','rundvee','pluimvee','geiten','paarden','konijnen','overig'];
const krdActiveFilters = new Set(KRD_ALL_CATEGORIES);

function getKrdCategory(bedrijfstype) {
    if (!bedrijfstype) return 'overig';
    const t = bedrijfstype.toLowerCase();
    if (t.includes('varken') || t.includes('zeug') || t.includes('bigg') || t.includes('dekbeer') || t.includes('dekberen')) return 'varkens';
    if (t.includes('rundvee') || t.includes('melk') || t.includes('vleesvee'))  return 'rundvee';
    if (t.includes('pluimvee') || t.includes('leghen') || t.includes('kuiken')) return 'pluimvee';
    if (t.includes('geit') || t.includes('schaap') || t.includes('schapen'))    return 'geiten';
    if (t.includes('paard'))                                                     return 'paarden';
    if (t.includes('konijn') || t.includes('nerts'))                             return 'konijnen';
    return 'overig';
}

function applyKrdFilter() {
    const showAll = krdActiveFilters.size === KRD_ALL_CATEGORIES.length;
    krdLayer.eachLayer(function(layer) {
        const cat = getKrdCategory(layer.feature?.properties?.bedrijfstype);
        const show = showAll || krdActiveFilters.has(cat);
        const el = layer.getElement();
        if (el) {
            el.style.opacity      = show ? '1' : '0';
            el.style.pointerEvents = show ? '' : 'none';
        }
    });
}

document.querySelectorAll('.krd-filter-item').forEach(function(item) {
    item.addEventListener('click', function() {
        const filter = this.dataset.krdFilter;
        const allSelected = krdActiveFilters.size === KRD_ALL_CATEGORIES.length;

        if (allSelected) {
            // Exclusive-select: show only this category
            krdActiveFilters.clear();
            document.querySelectorAll('.krd-filter-item').forEach(i => i.classList.remove('selected'));
            krdActiveFilters.add(filter);
            this.classList.add('selected');
        } else if (krdActiveFilters.has(filter)) {
            krdActiveFilters.delete(filter);
            this.classList.remove('selected');
            if (krdActiveFilters.size === 0) {
                // Last chip deselected — snap back to show-all
                KRD_ALL_CATEGORIES.forEach(c => krdActiveFilters.add(c));
                document.querySelectorAll('.krd-filter-item').forEach(i => i.classList.add('selected'));
            }
        } else {
            krdActiveFilters.add(filter);
            this.classList.add('selected');
        }
        applyKrdFilter();
    });
});

// Re-apply chip filter whenever krdLayer is reloaded (moveend re-fetch)
krdLayer.on('layeradd', function() {
    if (krdActiveFilters.size < KRD_ALL_CATEGORIES.length) {
        setTimeout(applyKrdFilter, 50);
    }
});


// =========================================================
// 5. Dynamic Data Fetching Engine (API Priority -> DB Fallback)
// =========================================================
map.on('moveend', function() {
    if (isProgrammaticMove) {
        isProgrammaticMove = false;
        return;
    }
    clearTimeout(_moveendTimer);
    _moveendTimer = setTimeout(async function() {

    const bounds = map.getBounds();

    const bboxPostGIS = `${bounds.getWest()},${bounds.getSouth()},${bounds.getEast()},${bounds.getNorth()}`;
    const effectiveBbox = bboxPostGIS;
    
    // BBOX for the entire Netherlands (Used to trick the DB into returning nationwide data)
    const bboxNetherlands = "3.3,50.75,7.22,53.7"; 

    const getYear = (layerId) => {
        const select = document.getElementById(`year-${layerId}`);
        return select && select.value ? select.value : '2025';
    };

    // Advanced Engine: Tries API first, gracefully falls back to Local DB
    async function loadDataWithFallback(layerObject, layerName, primaryApiUrl, fallbackDbUrl, isNationwide = false) {
        if (!map.hasLayer(layerObject)) return;
        
        try {
            const response = await fetch(primaryApiUrl);

            if (!response.ok) throw new Error(`HTTP Error ${response.status}`);

            // PDOK sometimes returns XML when hitting zoom scale limits
            const contentType = response.headers.get("content-type");
            if (contentType && contentType.includes("xml")) throw new Error("API returned XML instead of GeoJSON.");

            const data = await response.json();

            if (data.features && data.features.length > 0) {
                layerObject.clearLayers();
                if (layerObject === bagLayer) bagBuildingCache = data;
                if (layerObject === natura2000Layer) natura2000Cache = data;
                if (layerObject === grenzenLayer)     grenzenCache    = data;
                if (layerObject === nnnLayer)         nnnCache        = data;
                addFilteredData(layerObject, data);
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
                const fallbackData = await fallbackResponse.json();

                if (fallbackData.features && fallbackData.features.length > 0) {
                    layerObject.clearLayers();
                    if (layerObject === bagLayer) bagBuildingCache = fallbackData;
                    if (layerObject === natura2000Layer) natura2000Cache = fallbackData;
                    if (layerObject === grenzenLayer)     grenzenCache    = fallbackData;
                    if (layerObject === nnnLayer)         nnnCache        = fallbackData;
                    addFilteredData(layerObject, fallbackData);
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
            if (typeof applyBrpFilter === 'function') applyBrpFilter();
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
        } else {
        const bagApi = `https://api.pdok.nl/kadaster/bag/ogc/v2/collections/pand/items?f=json&limit=${BAG_API_LIMIT}&bbox=${effectiveBbox}`;
        const bagDb = `/api/bag_buildings?bbox=${effectiveBbox}&year=${getYear('bag')}`;
        loadDataWithFallback(bagLayer, 'BAG Buildings', bagApi, bagDb, false);

        if (map.hasLayer(bagLayer)) {
            fetch(`https://api.pdok.nl/kadaster/bag/ogc/v2/collections/verblijfsobject/items?f=json&limit=${BAG_USAGE_API_LIMIT}&bbox=${effectiveBbox}`)
                .then(res => {
                    if (!res.ok) throw new Error(`HTTP Error ${res.status}`);
                    return res.json();
                })
                .then(data => {
                    bagUsageCache = data;
                    bagUsageLayer.clearLayers();
                    addFilteredData(bagUsageLayer, data);
                    // Populate type map — handle pandidentificatie as string or array
                    if (data && data.features) {
                        data.features.forEach(f => {
                            if (!f.properties) return;
                            const type = getBagUsageType(f.properties.gebruiksdoel);
                            let ids = f.properties.pandidentificatie || f.properties.pand_identificatie;
                            if (!ids) return;
                            if (!Array.isArray(ids)) ids = [ids];
                            ids.forEach(id => { if (!bagUsageTypeMap[id]) bagUsageTypeMap[id] = type; });
                        });
                    }
                    bagLayer.eachLayer(layer => { if (layer.setStyle) layer.setStyle(getBagPolygonStyle(layer.feature)); });
                                })
                .catch(e => console.error("BAG Usage Locations Error:", e));
        }
    }

    // ==========================================
    // 3. Natura 2000 — loaded once nationwide on enable; no per-bbox re-fetch
    // ==========================================

    // ==========================================
    // 3I. Nature Network NL (46k+ polygons — viewport-based with row limit)
    // WMS handles visual coverage; GeoJSON layer handles click/hover for current viewport
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
                addFilteredData(krdLayer, data);
                if (document.getElementById('krd-stallen-toggle')?.checked) {
                    loadStallenData(effectiveBbox);
                }
            })
            .catch(e => console.error("KRD Error:", e));
    }

    // Pesticides/Health/Schools are loaded once nationwide — skip re-fetch on pan/zoom
    if (map.hasLayer(pesticidesLayer) && !window.isPesticidesLoaded) {
        fetch(`/api/pesticides?bbox=${effectiveBbox}`)
            .then(res => res.json())
            .then(data => { pesticidesCache = data; pesticidesLayer.clearLayers(); addFilteredData(pesticidesLayer, data); })
            .catch(e => console.error("Pesticides Error:", e));
    }

    if (map.hasLayer(healthLayer) && !window.isHealthLoaded) {
        fetch(`/api/health_facilities?bbox=${effectiveBbox}`)
            .then(res => res.json())
            .then(data => { healthCache = data; healthLayer.clearLayers(); addFilteredData(healthLayer, data); })
            .catch(e => console.error("Health Facilities Error:", e));
    }

    if (map.hasLayer(schoolsLayer) && !window.isSchoolsLoaded) {
        fetch(`/api/schools?bbox=${effectiveBbox}`)
            .then(res => res.json())
            .then(data => { schoolsCache = data; schoolsLayer.clearLayers(); addFilteredData(schoolsLayer, data); applySchoolTypeFilter(); })
            .catch(e => console.error("Schools Error:", e));
    }

    // ==========================================
    // Water Hydrography — two parallel fetches:
    //   1. Main channels (rivier/kanaal/gracht/boezem) — no row limit, always present
    //   2. Everything else — capped at 8000 so ditches don't crowd out named types
    // ==========================================
    if (map.hasLayer(hydrographyLayer)) {
        hydrographyLayer.clearLayers();

        const hydFetch = (url) => fetch(url).then(r => { if (!r.ok) throw new Error(r.status); return r.json(); });

        Promise.allSettled([
            hydFetch(`/api/hydrography_main?bbox=${effectiveBbox}`),
            hydFetch(`/api/hydrography_other?bbox=${effectiveBbox}`)
        ]).then(([mainResult, otherResult]) => {
            const anyFailed = mainResult.status === 'rejected' || otherResult.status === 'rejected';

            if (!anyFailed) {
                // Both split endpoints succeeded
                if (mainResult.value?.features)  hydrographyLayer.addData(mainResult.value);
                if (otherResult.value?.features) hydrographyLayer.addData(otherResult.value);
            } else {
                // At least one failed — fall back to combined DB endpoint
                console.warn('Hydrography split failed, falling back to combined DB endpoint');
                hydFetch(`/api/hydrography?bbox=${effectiveBbox}`)
                    .then(data => { if (data.features) hydrographyLayer.addData(data); })
                    .catch(e => console.error('Hydrography fallback error:', e));
            }
        });
    }

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
                    applyKadastralGemeenteFilter();
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
    }, 300);
});

// =========================================================
// Waterschappen (Water Authority Borders)
// =========================================================
const waterschappenLayer = L.geoJSON(null, {
    style: { color: '#1565c0', weight: 1.8, fillColor: '#42a5f5', fillOpacity: 0.07, dashArray: '10, 6', opacity: 0.85 },
    onEachFeature: (feature, layer) => {
        layer.on('click', (e) => {
            const p = feature.properties || {};
            handleFeatureClick('Waterschap', feature, e, {
                'Name': p.naam || 'N/A',
                'Code': p.code || 'N/A',
            }, 'https://api.pdok.nl/hwh/waterschappen/ogc/v1');
            triggerFeatureBuffer('waterschappen', feature, layer, '#1565c0');
        });
    }
});

layerRegistry['waterschappen'] = waterschappenLayer;

document.getElementById('layer-waterschappen').addEventListener('change', async function() {
    if (this.checked) {
        setLayerRowExpanded(this, true);
        waterschappenLayer.addTo(map);
        await loadNationwideLayer(
            waterschappenLayer, 'Waterschappen',
            `/api/waterschappen?bbox=${bboxNetherlands}`,
            `/api/waterschappen?bbox=${bboxNetherlands}`,
            'isWaterschappenLoaded'
        );
    } else {
        setLayerRowExpanded(this, false);
        map.removeLayer(waterschappenLayer);
        closeFeatureInfoForLayer('waterschappen');
    }
    updateLegend();
});

// =========================================================
// 6. Evidence Export Tools (PDF & Excel)
// =========================================================

// Scale indicator — added first so Leaflet stacks it at the bottom of the bottom-right group
L.control.scale({position: 'bottomright', imperial: false, maxWidth: 150}).addTo(map);

async function captureMapCanvas() {
    const leafletControls = document.querySelector('.leaflet-control-container');
    const customControls = document.getElementById('layer-controls');

    try {
        if (leafletControls) leafletControls.style.display = 'none';
        if (customControls) customControls.style.display = 'none';
        
        await new Promise(resolve => setTimeout(resolve, 800));

        return await html2canvas(document.getElementById('map'), {
            useCORS: true, allowTaint: false, scale: 2, backgroundColor: '#ffffff', logging: false 
        });
    } finally {
        if (leafletControls) leafletControls.style.display = '';
        if (customControls) customControls.style.display = '';
    }
}

async function exportMapViewAsPdf() {
    const canvas = await captureMapCanvas();
    const jsPDFConstructor = window.jspdf ? window.jspdf.jsPDF : window.jsPDF;
    if (!jsPDFConstructor) throw new Error('PDF export library is not available.');

    const pdf = new jsPDFConstructor('l', 'mm', 'a4');
    const pdfWidth = pdf.internal.pageSize.getWidth();
    const pdfHeight = pdf.internal.pageSize.getHeight();
    const mapHeightInPdf = pdfHeight - 40;
    const ratio = canvas.width / canvas.height;
    const mapWidthInPdf = Math.min(pdfWidth - 20, mapHeightInPdf * ratio);
    const mapHeight = mapWidthInPdf / ratio;

    pdf.addImage(
        canvas.toDataURL('image/jpeg', 0.95),
        'JPEG',
        (pdfWidth - mapWidthInPdf) / 2,
        10,
        mapWidthInPdf,
        mapHeight
    );

    pdf.setFontSize(10);
    pdf.setTextColor(80);
    const attributionText = "EVIDENCE DOCUMENT - ADVOCAAT VAN DE AARDE & STICHTING MOB\n" +
                            "Data Provenance: Spatial data securely aggregated from local PostGIS data warehouse.\n" +
                            "Date Generated: " + new Date().toLocaleString();

    pdf.text(attributionText, 10, pdfHeight - 20);
    pdf.save(`Environmental_Evidence_${new Date().toISOString().split('T')[0]}.pdf`);
}

async function exportMapViewAsPng() {
    const canvas = await captureMapCanvas();
    const a = document.createElement('a');
    a.href = canvas.toDataURL('image/png');
    a.download = `Environmental_Map_${new Date().toISOString().split('T')[0]}.png`;
    a.click();
}

async function runExportAction(button, loadingText, action) {
    const originalText = button.textContent;
    button.textContent = loadingText;
    button.disabled = true;
    try {
        await action();
    } catch (error) {
        alert(`Export failed: ${error.message || error}`);
    } finally {
        button.textContent = originalText;
        button.disabled = false;
        closeExportMenu();
    }
}

const exportMenuControl = L.control({position: 'bottomright'});
exportMenuControl.onAdd = function () {
    const div = L.DomUtil.create('div', 'export-menu-control');
    div.innerHTML = `
        <div id="export-actions-menu" class="export-actions-menu" role="menu" aria-hidden="true" hidden>
            <div class="export-menu-group">
                <div class="export-menu-header">Map View (Images)</div>
                <button id="export-pdf-btn" class="export-action-btn" type="button" role="menuitem">
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 6px; vertical-align: middle;"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
                    Capture view as PDF
                </button>
                <button id="export-png-btn" class="export-action-btn" type="button" role="menuitem">
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 6px; vertical-align: middle;"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>
                    Capture view as PNG
                </button>
            </div>
            <div class="export-menu-group">
                <div class="export-menu-header">Datasets (Excel)</div>
                <button id="export-excel-active-btn" class="export-action-btn" type="button" role="menuitem">
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 6px; vertical-align: middle;"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                    Export active layers
                </button>
                <button id="export-excel-all-btn" class="export-action-btn" type="button" role="menuitem">
                    <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 6px; vertical-align: middle;"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                    Export all layers
                </button>
            </div>
        </div>
        <button id="export-menu-toggle" class="export-menu-toggle" type="button" aria-haspopup="menu" aria-controls="export-actions-menu" aria-expanded="false">
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 6px;"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
            Export
        </button>
    `;
    L.DomEvent.disableClickPropagation(div);
    L.DomEvent.disableScrollPropagation(div);
    return div;
};
exportMenuControl.addTo(map);

const exportMenuToggle = document.getElementById('export-menu-toggle');
const exportActionsMenu = document.getElementById('export-actions-menu');

function closeExportMenu() {
    exportActionsMenu?.setAttribute('hidden', '');
    exportActionsMenu?.setAttribute('aria-hidden', 'true');
    exportMenuToggle?.setAttribute('aria-expanded', 'false');
}

exportMenuToggle?.addEventListener('click', function () {
    const isClosed = exportActionsMenu?.hasAttribute('hidden');
    if (isClosed) {
        exportActionsMenu.removeAttribute('hidden');
        exportActionsMenu.setAttribute('aria-hidden', 'false');
        this.setAttribute('aria-expanded', 'true');
    } else {
        closeExportMenu();
    }
});

document.addEventListener('keydown', event => {
    if (event.key === 'Escape') closeExportMenu();
});

document.getElementById('export-pdf-btn')?.addEventListener('click', function () {
    runExportAction(this, 'Preparing PDF...', exportMapViewAsPdf);
});

document.getElementById('export-png-btn')?.addEventListener('click', function () {
    runExportAction(this, 'Capturing PNG...', exportMapViewAsPng);
});

document.getElementById('export-excel-active-btn')?.addEventListener('click', function () {
    runExportAction(this, 'Generating Excel…', () => exportExcel(false));
});

document.getElementById('export-excel-all-btn')?.addEventListener('click', function () {
    runExportAction(this, 'Generating Excel…', () => exportExcel(true));
});

map.on('click', closeExportMenu);

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
        layerObject: grenzenLayer, sheetName: "Bestuurlijke Grenzen",
        buildUrl: (bbox) => `/api/grenzen?bbox=${bbox}`,
        columns: { "gemeentenaam": "Boundary Name", "layer_type": "Boundary Type", "code": "Code" }
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
        layerObject: kadastralekaartLayer, sheetName: 'Kadastrale Kaart',
        buildUrl: (bbox) => `/api/kadastralekaart?bbox=${bbox}`,
        columns: { 'identificatie': 'Parcel ID', 'gemeente': 'Municipality', 'sectie': 'Section', 'perceelnummer': 'Parcel Number' }
    },
    {
        layerObject: waterschappenLayer, sheetName: 'Waterschappen',
        buildUrl: (bbox) => `/api/waterschappen?bbox=${bbox}`,
        columns: { 'code': 'Code', 'naam': 'Naam' }
    }
];

map.on('click', function() {
    document.getElementById('info-panel').classList.add('hidden');
    removeHighlight(_lastHighlightedLayer);
    _lastHighlightedLayer = null;
});

// =========================================================
// 7B. Per-Layer Buffer System
// =========================================================

let globalBufferRadiusKm = 1.0;
let isBufferModeOn = false;
let _bufferExportData = [];   // built by buildWithinBufferSection for export
let _activeBufferTarget = null;
let _bufferContextTimer = null;

// One Leaflet LayerGroup per layer-id — each holds at most one buffer polygon
const _bufferGroups = {};
function getBufferGroup(layerId) {
    if (!_bufferGroups[layerId]) {
        _bufferGroups[layerId] = L.layerGroup().addTo(map);
    }
    return _bufferGroups[layerId];
}

// Single vivid buffer style — visually distinct from all layer colors
const BUFFER_STYLE = {
    color:       '#f59e0b',  // amber-gold stroke
    weight:      3,
    dashArray:   '10 6',
    fillColor:   '#fcd34d',
    fillOpacity: 0.14,
    opacity:     1
};

function computeBufferFeature(feature, radiusKm) {
    if (typeof turf === 'undefined') return null;
    try {
        const geomType = feature?.geometry?.type || '';
        if (geomType === 'Point' || geomType === 'MultiPoint') {
            const coords = geomType === 'Point'
                ? feature.geometry.coordinates
                : feature.geometry.coordinates[0];
            return turf.circle(coords, radiusKm, { steps: 64, units: 'kilometers' });
        }
        return turf.buffer(feature, radiusKm, { units: 'kilometers', steps: 32 });
    } catch (err) {
        console.warn('Buffer compute failed:', err);
        return null;
    }
}

function getFeatureCentroid(feature) {
    try {
        if (typeof turf !== 'undefined') {
            const c = turf.centroid(feature);
            return L.latLng(c.geometry.coordinates[1], c.geometry.coordinates[0]);
        }
    } catch (_) {}
    return null;
}

let _lastHighlightedLayer = null;

function applyHighlight(leafletLayer) {
    if (!leafletLayer || leafletLayer._origStyle || leafletLayer._origMarkerAura) return;
    const opts = leafletLayer.options || {};

    if (typeof leafletLayer.setRadius !== 'function' && typeof leafletLayer.setStyle !== 'function' && typeof leafletLayer.getElement === 'function') {
        const el = leafletLayer.getElement();
        if (!el) return;
        const markerDot = el.querySelector('.krd-marker');
        const svgCircle = el.querySelector('svg circle');

        leafletLayer._origMarkerAura = {
            filter: el.style.filter || '',
            markerBorderColor: markerDot?.style.borderColor || '',
            markerBorderWidth: markerDot?.style.borderWidth || '',
            markerBoxShadow: markerDot?.style.boxShadow || '',
            svgStroke: svgCircle?.getAttribute('stroke'),
            svgStrokeWidth: svgCircle?.getAttribute('stroke-width')
        };

        el.style.filter = 'drop-shadow(0 0 5px rgba(245, 158, 11, 0.95))';
        if (markerDot) {
            markerDot.style.borderColor = '#f59e0b';
            markerDot.style.borderWidth = '3px';
            markerDot.style.boxShadow = '0 0 0 3px rgba(245, 158, 11, 0.28)';
        }
        if (svgCircle) {
            svgCircle.setAttribute('stroke', '#f59e0b');
            svgCircle.setAttribute('stroke-width', '4');
        }
        return;
    }

    leafletLayer._origStyle = {
        weight:      opts.weight,
        color:       opts.color,
        fillColor:   opts.fillColor,
        fillOpacity: opts.fillOpacity,
        opacity:     opts.opacity,
        dashArray:   opts.dashArray || null,
        radius:      opts.radius,
    };

    const strongerColor = opts.color || opts.fillColor;
    const strongerFill = opts.fillColor || opts.color;

    try {
        if (typeof leafletLayer.setRadius === 'function') {
            leafletLayer.setStyle({
                weight: Math.max((opts.weight || 1) + 2, 4),
                color: '#f59e0b',
                fillColor: strongerFill,
                fillOpacity: opts.fillOpacity ?? 0.75,
                opacity: 1
            });
        } else if (typeof leafletLayer.setStyle === 'function') {
            leafletLayer.setStyle({
                weight: Math.max((opts.weight || 1) + 2, 3),
                color: strongerColor,
                fillColor: strongerFill,
                fillOpacity: Math.min((opts.fillOpacity ?? 0.35) + 0.25, 0.9),
                opacity: 1,
                dashArray: opts.dashArray || null
            });
        }
    } catch (_) {}
}

function removeHighlight(leafletLayer) {
    if (leafletLayer?._origMarkerAura) {
        const s = leafletLayer._origMarkerAura;
        const el = typeof leafletLayer.getElement === 'function' ? leafletLayer.getElement() : null;
        const markerDot = el?.querySelector('.krd-marker');
        const svgCircle = el?.querySelector('svg circle');
        if (el) el.style.filter = s.filter;
        if (markerDot) {
            markerDot.style.borderColor = s.markerBorderColor;
            markerDot.style.borderWidth = s.markerBorderWidth;
            markerDot.style.boxShadow = s.markerBoxShadow;
        }
        if (svgCircle) {
            if (s.svgStroke == null) svgCircle.removeAttribute('stroke');
            else svgCircle.setAttribute('stroke', s.svgStroke);
            if (s.svgStrokeWidth == null) svgCircle.removeAttribute('stroke-width');
            else svgCircle.setAttribute('stroke-width', s.svgStrokeWidth);
        }
        delete leafletLayer._origMarkerAura;
    }
    if (!leafletLayer?._origStyle) return;
    const s = leafletLayer._origStyle;
    try {
        if (typeof leafletLayer.setRadius === 'function') {
            leafletLayer.setStyle({ weight: s.weight, color: s.color, fillColor: s.fillColor, fillOpacity: s.fillOpacity, opacity: s.opacity });
            if (s.radius != null) leafletLayer.setRadius(s.radius);
        } else if (typeof leafletLayer.setStyle === 'function') {
            leafletLayer.setStyle({ weight: s.weight, color: s.color, fillColor: s.fillColor, fillOpacity: s.fillOpacity, opacity: s.opacity, dashArray: s.dashArray });
        }
    } catch (_) {}
    delete leafletLayer._origStyle;
}

function clearLayerBuffer(layerId) {
    if (_bufferGroups[layerId]) _bufferGroups[layerId].clearLayers();
}

function clearRenderedBuffers() {
    Object.keys(_bufferGroups).forEach(id => _bufferGroups[id].clearLayers());
    removeHighlight(_lastHighlightedLayer);
    _lastHighlightedLayer = null;
    _bufferExportData = [];
}

function clearAllBuffers() {
    clearRenderedBuffers();
    _activeBufferTarget = null;
    if (_bufferContextTimer) clearTimeout(_bufferContextTimer);
    document.getElementById('buffer-info-panel')?.setAttribute('hidden', '');
}

function showBufferOffAlert() {
    window.alert('Please turn Buffer On before adjusting the radius.');
}

function setBufferMode(enabled) {
    isBufferModeOn = enabled;

    const onBtn = document.getElementById('buffer-on-btn');
    const offBtn = document.getElementById('buffer-off-btn');
    const radiusControls = document.getElementById('buffer-radius-controls');
    const radiusSlider = document.getElementById('buffer-radius-slider');
    const radiusInput = document.getElementById('buffer-radius-input');
    const helpText = document.getElementById('buffer-help-text');

    if (onBtn && offBtn) {
        onBtn.classList.toggle('active', enabled);
        offBtn.classList.toggle('active', !enabled);
        onBtn.style.background = enabled ? '#1B512D' : '#fff';
        onBtn.style.color = enabled ? 'white' : '#1B512D';
        onBtn.style.borderColor = enabled ? '#1B512D' : '#dce8d4';
        offBtn.style.background = enabled ? '#fff' : '#1B512D';
        offBtn.style.color = enabled ? '#1B512D' : 'white';
        offBtn.style.borderColor = enabled ? '#dce8d4' : '#1B512D';
    }

    if (radiusControls) {
        radiusControls.classList.toggle('buffer-radius-disabled', !enabled);
        radiusControls.setAttribute('aria-disabled', String(!enabled));
    }
    [radiusSlider, radiusInput].forEach(control => {
        if (!control) return;
        control.setAttribute('aria-disabled', String(!enabled));
    });
    if (helpText) {
        helpText.textContent = enabled
            ? 'Click one feature on the map to draw a buffer and see its spatial context.'
            : 'Turn buffer on, then click one feature on the map to draw a buffer and see its spatial context.';
    }

    if (!enabled) clearAllBuffers();
}

function updateBufferRadiusDisplay(radiusKm) {
    const label = document.getElementById('buffer-radius-label');
    if (label) {
        label.textContent = radiusKm >= 1 ? radiusKm + ' km' : (radiusKm * 1000).toFixed(0) + ' m';
    }
    const panelRadius = document.getElementById('buffer-info-radius');
    if (panelRadius && !document.getElementById('buffer-info-panel')?.hasAttribute('hidden')) {
        panelRadius.textContent = radiusKm >= 1 ? radiusKm + ' km' : (radiusKm * 1000).toFixed(0) + ' m';
    }
}

function drawBufferForTarget(target, radiusKm) {
    if (!target?.feature) return null;
    const bufferFeature = computeBufferFeature(target.feature, radiusKm);
    if (bufferFeature) {
        L.geoJSON(bufferFeature, { style: BUFFER_STYLE, interactive: false })
            .addTo(getBufferGroup(target.layerId));
    }
    return bufferFeature;
}

function refreshActiveBufferForRadius() {
    if (!_activeBufferTarget) return;

    clearRenderedBuffers();
    const bufferFeature = drawBufferForTarget(_activeBufferTarget, globalBufferRadiusKm);
    applyHighlight(_activeBufferTarget.leafletLayer);
    _lastHighlightedLayer = _activeBufferTarget.leafletLayer;
    updateBufferRadiusDisplay(globalBufferRadiusKm);

    if (bufferFeature) buildWithinBufferSection(bufferFeature);

    const panel = document.getElementById('buffer-info-panel');
    if (panel && !panel.hasAttribute('hidden')) {
        document.getElementById('buffer-info-n2000-within').textContent = '...';
    }

    if (_bufferContextTimer) clearTimeout(_bufferContextTimer);
    _bufferContextTimer = setTimeout(() => {
        loadBufferContext(_activeBufferTarget.feature, globalBufferRadiusKm);
    }, 350);
}

// ─── Dataset configs for within-buffer summaries ──────────────────────────────
const BUFFER_DATASETS = [
    {
        id: 'brp', label: 'BRP Crop Parcels', color: '#27ae60',
        isActive: () => typeof brpLayer !== 'undefined' && map.hasLayer(brpLayer),
        getFeatures: () => brpCache?.features || [],
        summarize: feats => {
            const crops = {};
            feats.forEach(f => {
                const crop = f.properties?.gewas || 'Unknown';
                if (!crops[crop]) crops[crop] = { parcels: 0, area: 0 };
                crops[crop].parcels++;
                crops[crop].area += f.properties?.area_ha || 0;
            });
            return Object.entries(crops).sort((a,b) => b[1].area - a[1].area)
                .map(([crop,d]) => ({ Crop: crop, Parcels: d.parcels, 'Area (ha)': d.area.toFixed(2) }));
        }
    },
    {
        id: 'bag', label: 'BAG Buildings', color: '#555555',
        isActive: () => typeof bagLayer !== 'undefined' && map.hasLayer(bagLayer),
        getFeatures: () => { const f=[]; if (typeof bagLayer!=='undefined') bagLayer.eachLayer(l=>l.feature&&f.push(l.feature)); return f; },
        summarize: feats => {
            const types = {};
            feats.forEach(f => {
                const g = f.properties?.gebruiksdoel || '';
                const t = (Array.isArray(g) ? g.join(',') : String(g)).toLowerCase();
                const type = t.includes('woonfunctie') ? 'Residential'
                    : t.includes('kantoorfunctie') ? 'Office'
                    : t.includes('industriefunctie') ? 'Industrial'
                    : t.includes('winkelfunctie') ? 'Retail'
                    : t.includes('bijeenkomstfunctie') ? 'Assembly'
                    : t.includes('gezondheidszorgfunctie') ? 'Healthcare'
                    : t.includes('onderwijsfunctie') ? 'Education' : 'Other';
                types[type] = (types[type] || 0) + 1;
            });
            return Object.entries(types).sort((a,b)=>b[1]-a[1]).map(([Type,Count])=>({Type,Count}));
        }
    },
    {
        id: 'natura2000', label: 'Natura 2000', color: '#16a085',
        isActive: () => typeof natura2000Layer !== 'undefined' && map.hasLayer(natura2000Layer),
        getFeatures: () => natura2000Cache?.features || [],
        summarize: feats => feats.map(f => ({
            'Area Name': f.properties?.naam_n2k || f.properties?.naam || '—',
            Status: f.properties?.status || '—',
            Protection: f.properties?.beschermin || '—'
        }))
    },
    {
        id: 'nnn', label: 'Nature Network NL', color: '#9b59b6',
        isActive: () => typeof nnnLayer !== 'undefined' && map.hasLayer(nnnLayer),
        getFeatures: () => nnnCache?.features || [],
        summarize: feats => feats.map(f => ({ 'Area Name': f.properties?.name || f.properties?.naam || '—' }))
    },
    {
        id: 'krd', label: 'KRD Veehouderijen', color: '#e67e22',
        isActive: () => typeof krdLayer !== 'undefined' && map.hasLayer(krdLayer),
        getFeatures: () => { const f=[]; if (typeof krdLayer!=='undefined') krdLayer.eachLayer(l=>l.feature&&f.push(l.feature)); return f; },
        summarize: feats => {
            const types = {};
            feats.forEach(f => {
                const t = f.properties?.bedrijfstype || 'Unknown';
                if (!types[t]) types[t] = { count: 0, nh3: 0 };
                types[t].count++;
                types[t].nh3 += parseFloat(f.properties?.['nh3 emissie (kg/j)'] || 0);
            });
            return Object.entries(types).sort((a,b)=>b[1].count-a[1].count)
                .map(([Type,d]) => ({ 'Farm Type': Type, Count: d.count, 'NH3 (kg/j)': Math.round(d.nh3).toLocaleString() }));
        }
    },
    {
        id: 'pesticides', label: 'Pesticides Atlas', color: '#f39c12',
        isActive: () => typeof pesticidesLayer !== 'undefined' && map.hasLayer(pesticidesLayer),
        getFeatures: () => pesticidesCache?.features || [],
        summarize: feats => {
            const c = { 'Within norm (≤1×)': 0, 'Above norm (1–10×)': 0, 'Severe (>10×)': 0, 'No data': 0 };
            feats.forEach(f => {
                const r = f.properties?.exceedance_ratio;
                if (r == null) c['No data']++;
                else if (r > 10) c['Severe (>10×)']++;
                else if (r > 1) c['Above norm (1–10×)']++;
                else c['Within norm (≤1×)']++;
            });
            return Object.entries(c).filter(e=>e[1]>0).map(([Level,Stations])=>({Level,Stations}));
        }
    },
    {
        id: 'health', label: 'Health Facilities', color: '#e91e8c',
        isActive: () => typeof healthLayer !== 'undefined' && map.hasLayer(healthLayer),
        getFeatures: () => healthCache?.features || [],
        summarize: feats => feats.slice(0,30).map(f => ({
            Name: f.properties?.name || '—',
            Type: f.properties?.facility_type || '—',
            City: f.properties?.addr_city || '—'
        }))
    },
    {
        id: 'schools', label: 'Schools', color: '#2ecc71',
        isActive: () => typeof schoolsLayer !== 'undefined' && map.hasLayer(schoolsLayer),
        getFeatures: () => schoolsCache?.features || [],
        summarize: feats => feats.slice(0,30).map(f => ({
            School: f.properties?.instellingsnaam || '—',
            Type: f.properties?.onderwijstype || '—',
            City: f.properties?.plaatsnaam || '—'
        }))
    },
    {
        id: 'grenzen', label: 'Bestuurlijke Grenzen', color: '#8e44ad',
        isActive: () => typeof grenzenLayer !== 'undefined' && map.hasLayer(grenzenLayer),
        getFeatures: () => grenzenCache?.features || [],
        summarize: feats => {
            const out = [];
            feats.forEach(f => { const n=f.properties?.gemeentenaam||f.properties?.code; if(n) out.push({'Name':n,'Type':f.properties?.layer_type||'—'}); });
            return out;
        }
    },
    {
        id: 'kadastralekaart', label: 'Kadastrale Kaart', color: '#e67e22',
        isActive: () => typeof kadastralekaartLayer !== 'undefined' && map.hasLayer(kadastralekaartLayer),
        getFeatures: () => { const f=[]; if(typeof kadastralekaartLayer!=='undefined') kadastralekaartLayer.eachLayer(l=>l.feature&&f.push(l.feature)); return f; },
        summarize: feats => feats.slice(0,30).map(f => ({
            Parcel: f.properties?.identificatie || '—',
            Municipality: f.properties?.gemeente || '—',
            'Area (m²)': f.properties?.kadastralegrootte ?? '—'
        }))
    },
    {
        id: 'hydrography', label: 'Water Hydrography', color: '#1a6fa8',
        isActive: () => typeof hydrographyLayer !== 'undefined' && map.hasLayer(hydrographyLayer),
        getFeatures: () => { const f=[]; if(typeof hydrographyLayer!=='undefined') hydrographyLayer.eachLayer(l=>l.feature&&f.push(l.feature)); return f; },
        summarize: feats => feats.slice(0,30).map(f => ({
            Name: f.properties?.name || '—',
            Type: f.properties?.localtype || '—'
        }))
    },
    {
        id: 'wfd', label: 'WFD Surface Water', color: '#1a5276',
        isActive: () => typeof wfdSurfaceWaterLayer !== 'undefined' && map.hasLayer(wfdSurfaceWaterLayer),
        getFeatures: () => { const f=[]; if(typeof wfdSurfaceWaterLayer!=='undefined') wfdSurfaceWaterLayer.eachLayer(l=>l.feature&&f.push(l.feature)); return f; },
        summarize: feats => feats.slice(0,20).map(f => ({ 'Water Body': f.properties?.text || f.properties?.name || '—' }))
    },
    {
        id: 'waterschappen', label: 'Waterschappen', color: '#1565c0',
        isActive: () => typeof waterschappenLayer !== 'undefined' && map.hasLayer(waterschappenLayer),
        getFeatures: () => { const f=[]; if(typeof waterschappenLayer!=='undefined') waterschappenLayer.eachLayer(l=>l.feature&&f.push(l.feature)); return f; },
        summarize: feats => feats.map(f => ({ Authority: f.properties?.naam || '—', Code: f.properties?.code || '—' }))
    }
];

function getFeaturesInBuffer(dataset, bufferGeom) {
    if (!dataset.isActive()) return [];
    const features = dataset.getFeatures();
    if (!features.length || typeof turf === 'undefined') return [];
    return features.filter(f => {
        if (!f?.geometry) return false;
        try {
            const gt = f.geometry.type;
            if (gt === 'Point' || gt === 'MultiPoint') return turf.booleanPointInPolygon(f, bufferGeom);
            return turf.booleanIntersects(f, bufferGeom);
        } catch (_) { return false; }
    });
}

function buildWithinBufferSection(bufferGeom) {
    const container = document.getElementById('buffer-within-sections');
    if (!container) return;
    container.innerHTML = '';
    _bufferExportData = [];
    let hasAny = false;

    BUFFER_DATASETS.forEach(ds => {
        const inBuf = getFeaturesInBuffer(ds, bufferGeom);
        if (!inBuf.length) return;
        const rows = ds.summarize(inBuf);
        if (!rows.length) return;
        hasAny = true;

        // Accumulate for export
        rows.forEach(r => _bufferExportData.push({ Dataset: ds.label, ...r }));

        // Build collapsible section
        const section = document.createElement('div');
        section.style.cssText = 'border-top:1px solid #e8f0e4;';

        const arrow = document.createElement('span');
        arrow.style.cssText = 'font-size:12px;color:#a0a0a0;transition:transform 0.15s;flex-shrink:0;';
        arrow.textContent = '›';

        const hdr = document.createElement('div');
        hdr.style.cssText = 'display:flex;align-items:center;gap:7px;padding:7px 14px;cursor:pointer;background:#f8fbf6;user-select:none;';
        hdr.innerHTML = `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${ds.color};flex-shrink:0;"></span>
            <strong style="font-size:11px;flex:1;color:#1B512D;">${ds.label}</strong>
            <span style="font-size:11px;color:#607060;">${inBuf.length} feature${inBuf.length!==1?'s':''}</span>`;
        hdr.appendChild(arrow);

        const body = document.createElement('div');
        body.style.display = 'none';
        body.style.cssText = 'display:none;';

        const cols = Object.keys(rows[0]);
        let html = '<div style="overflow-x:auto;padding:0 14px 8px;"><table class="brp-pivot-table" style="width:100%;font-size:11px;"><thead><tr>';
        cols.forEach(c => { html += `<th>${c}</th>`; });
        html += '</tr></thead><tbody>';
        rows.slice(0, 30).forEach(row => {
            html += '<tr>';
            cols.forEach(c => { html += `<td>${row[c] ?? '—'}</td>`; });
            html += '</tr>';
        });
        html += '</tbody></table></div>';
        if (rows.length > 30) html += `<p style="font-size:10px;color:#999;padding:0 14px 6px;margin:0;">${rows.length-30} more — export for full data.</p>`;
        body.innerHTML = html;

        hdr.addEventListener('click', () => {
            const open = body.style.display !== 'none';
            body.style.display = open ? 'none' : '';
            arrow.style.transform = open ? '' : 'rotate(90deg)';
        });

        section.appendChild(hdr);
        section.appendChild(body);
        container.appendChild(section);
    });

    if (!hasAny) {
        container.innerHTML = '<p style="font-size:11px;color:#999;padding:8px 14px;margin:0;">No active layer data found within buffer.</p>';
    }
}

async function triggerFeatureBuffer(layerId, feature, leafletLayer, accentColor) {
    if (!isBufferModeOn) {
        return;
    }

    const radiusKm = globalBufferRadiusKm;

    // Keep only one buffer visible at a time, regardless of source layer.
    clearRenderedBuffers();
    _activeBufferTarget = { layerId, feature, leafletLayer, accentColor };

    // Remember the selected layer without changing its visual style.
    applyHighlight(leafletLayer, accentColor);
    _lastHighlightedLayer = leafletLayer;

    // Compute and draw buffer with unified vivid style
    const bufferFeature = drawBufferForTarget(_activeBufferTarget, radiusKm);

    // Center map on feature
    const centroid = getFeatureCentroid(feature);
    if (centroid) {
        isProgrammaticMove = true;
        map.panTo(centroid, { animate: true, duration: 0.5 });
    }

    // Show panel with loading state, then fill in data
    showBufferInfoPanel(layerId, feature, radiusKm);
    if (bufferFeature) buildWithinBufferSection(bufferFeature);
    await loadBufferContext(feature, radiusKm);
}

function showBufferInfoPanel(layerId, feature, radiusKm) {
    const panel = document.getElementById('buffer-info-panel');
    if (!panel) return;

    const p = feature.properties || {};
    const featureName = p.naam_n2k || p.naam || p.name || p.instellingsnaam || p.gewas
        || p.gemeentenaam || p.text || p.adres || p.identificatie || p.lokaalid || layerId;

    const layerLabel = {
        brp:'BRP Parcels', bag:'BAG Buildings', bag_usage:'BAG Usage',
        natura2000:'Natura 2000', nnn:'Nature Network NL', kadastralekaart:'Kadastrale Kaart',
        grenzen:'Bestuurlijke Grenzen', krd:'KRD Veehouderijen', krd_stallen:'KRD Stallen',
        health:'Health Facilities', pesticides:'Pesticides Atlas', schools:'Schools',
        wfd:'WFD Surface Water', hydrography:'Hydrography', waterschappen:'Waterschappen'
    }[layerId] || layerId.replace(/_/g,' ').replace(/\b\w/g,c=>c.toUpperCase());

    document.getElementById('buffer-info-layer').textContent  = layerLabel;
    document.getElementById('buffer-info-name').textContent   = featureName || '—';
    document.getElementById('buffer-info-radius').textContent = radiusKm >= 1 ? radiusKm + ' km' : (radiusKm * 1000).toFixed(0) + ' m';
    document.getElementById('buffer-info-gemeente').textContent       = '…';
    document.getElementById('buffer-info-provincie').textContent      = '…';
    document.getElementById('buffer-info-n2000-nearest').textContent  = '…';
    document.getElementById('buffer-info-n2000-within').textContent   = '…';

    const within = document.getElementById('buffer-within-sections');
    if (within) within.innerHTML = '<p style="font-size:11px;color:#999;padding:8px 14px;margin:0;">Loading…</p>';

    const sidebar = document.getElementById('layer-controls');
    panel.style.left = (sidebar.classList.contains('collapsed') ? 8 : sidebar.offsetWidth + 8) + 'px';
    panel.removeAttribute('hidden');
}

async function loadBufferContext(feature, radiusKm) {
    const centroid = getFeatureCentroid(feature);
    if (!centroid) return;
    try {
        const resp = await fetch(
            `/api/buffer_context?lat=${centroid.lat.toFixed(6)}&lng=${centroid.lng.toFixed(6)}&radius_km=${radiusKm}`
        );
        if (!resp.ok) return;
        const ctx = await resp.json();
        document.getElementById('buffer-info-gemeente').textContent  = ctx.gemeente  || '—';
        document.getElementById('buffer-info-provincie').textContent = ctx.provincie || '—';
        document.getElementById('buffer-info-n2000-nearest').textContent =
            ctx.nearest_n2000 ? `${ctx.nearest_n2000} (${ctx.nearest_n2000_km ?? '?'} km)` : '—';
        const within = ctx.n2000_within_buffer || [];
        document.getElementById('buffer-info-n2000-within').textContent =
            within.length ? within.join(', ') : `None within ${radiusKm} km`;
    } catch (err) {
        console.warn('Buffer context fetch failed:', err);
    }
}

document.getElementById('buffer-radius-slider')?.addEventListener('input', function() {
    if (!isBufferModeOn) {
        this.value = globalBufferRadiusKm;
        showBufferOffAlert();
        return;
    }
    globalBufferRadiusKm = parseFloat(this.value) || 1.0;
    const inp = document.getElementById('buffer-radius-input');
    if (inp) inp.value = globalBufferRadiusKm;
    updateBufferRadiusDisplay(globalBufferRadiusKm);
    refreshActiveBufferForRadius();
});

document.getElementById('buffer-radius-input')?.addEventListener('change', function() {
    if (!isBufferModeOn) {
        this.value = globalBufferRadiusKm;
        showBufferOffAlert();
        return;
    }
    const val = parseFloat(this.value);
    if (isNaN(val) || val <= 0) return;
    globalBufferRadiusKm = val;
    const slider = document.getElementById('buffer-radius-slider');
    if (slider) slider.value = Math.min(val, parseFloat(slider.max));
    updateBufferRadiusDisplay(val);
    refreshActiveBufferForRadius();
});

['pointerdown', 'keydown', 'beforeinput'].forEach(eventName => {
    document.getElementById('buffer-radius-slider')?.addEventListener(eventName, function(event) {
        if (isBufferModeOn) return;
        event.preventDefault();
        showBufferOffAlert();
    });
    document.getElementById('buffer-radius-input')?.addEventListener(eventName, function(event) {
        if (isBufferModeOn) return;
        event.preventDefault();
        this.blur();
        showBufferOffAlert();
    });
});

document.getElementById('buffer-on-btn')?.addEventListener('click', function() {
    setBufferMode(true);
});

document.getElementById('buffer-off-btn')?.addEventListener('click', function() {
    setBufferMode(false);
});

setBufferMode(false);

document.getElementById('buffer-clear-all-btn')?.addEventListener('click', clearAllBuffers);

document.getElementById('buffer-info-close')?.addEventListener('click', function() {
    document.getElementById('buffer-info-panel')?.setAttribute('hidden', '');
});

function ensureXlsxLoaded() {
    if (typeof XLSX !== 'undefined') return Promise.resolve();
    return new Promise((resolve, reject) => {
        const existingScript = document.querySelector('script[data-xlsx-loader]');
        if (existingScript) {
            existingScript.addEventListener('load', resolve, { once: true });
            existingScript.addEventListener('error', reject, { once: true });
            return;
        }

        const script = document.createElement('script');
        script.src = 'https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js';
        script.async = true;
        script.dataset.xlsxLoader = 'true';
        script.onload = resolve;
        script.onerror = () => reject(new Error('The Excel export library could not be loaded.'));
        document.head.appendChild(script);
    });
}

function csvEscape(value) {
    const text = value == null ? '' : String(value);
    return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

function downloadRowsAsCsv(rows, fileName) {
    if (!rows.length) return;
    const columns = Array.from(rows.reduce((keys, row) => {
        Object.keys(row).forEach(key => keys.add(key));
        return keys;
    }, new Set()));
    const csv = [
        columns.map(csvEscape).join(','),
        ...rows.map(row => columns.map(col => csvEscape(row[col])).join(','))
    ].join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = fileName;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
}

async function downloadRowsAsWorkbook(rows, sheetName, fileName) {
    if (!rows.length) {
        alert('No data available to export for the selected filters.');
        return;
    }
    try {
        await ensureXlsxLoaded();
        const wb = XLSX.utils.book_new();
        XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(rows), sheetName.slice(0, 31));
        XLSX.writeFile(wb, fileName);
    } catch (err) {
        console.warn('Excel export failed; using CSV fallback.', err);
        downloadRowsAsCsv(rows, fileName.replace(/\.xlsx$/i, '.csv'));
    }
}

function flattenFeatureProperties(feature, datasetName) {
    const props = feature?.properties || {};
    const row = { Dataset: datasetName };
    Object.entries(props).forEach(([key, value]) => {
        row[key] = Array.isArray(value) ? value.join(', ') : value;
    });

    const geometry = feature?.geometry;
    if (geometry?.type) row.geometry_type = geometry.type;
    if (geometry?.type === 'Point' && Array.isArray(geometry.coordinates)) {
        row.longitude = geometry.coordinates[0];
        row.latitude = geometry.coordinates[1];
    }
    return row;
}

async function fetchGeoJsonFeatures(url) {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    return Array.isArray(data?.features) ? data.features : [];
}

function selectedDatasetFilters(selector, dataAttr) {
    return Array.from(document.querySelectorAll(`${selector}.selected`))
        .map(el => el.dataset[dataAttr])
        .filter(Boolean);
}

function getSelectedLayerYear(layerId, fallbackYear) {
    return document.getElementById(`year-${layerId}`)?.value || fallbackYear;
}

function getBrpCropTypeName(value) {
    const n = String(value || '').toLowerCase();
    if (n.includes('gras') || n.includes('weide')) return 'grassland';
    if (n.includes('mais') || n.includes('maïs')) return 'maize';
    if (n.includes('aardappel')) return 'potato';
    if (n.includes('tarwe') || n.includes('graan') || n.includes('gerst') ||
        n.includes('haver') || n.includes('rogge') || n.includes('triticale') ||
        n.includes('spelt') || n.includes('raaigras') || n.includes('zwenkgras') ||
        n.includes('boekweit') || n.includes('soedangras') || n.includes('sorghum')) return 'cereals';
    if (n.includes('bieten')) return 'beets';
    if (n.includes('koolzaad') || n.includes('raapzaad') || n.includes('vlas') ||
        n.includes('hennep') || n.includes('zonnebloem') || n.includes('miscanthus') ||
        n.includes('luzerne') || n.includes('cichorei') || n.includes('mosterd') ||
        n.includes('groenbemester') || n.includes('facelia') || n.includes('tagetes') ||
        n.includes('bladrammenas') || n.includes('drachtplant') || n.includes('raketblad') ||
        n.includes('japanse haver') || n.includes('soja') || n.includes('quinoa') ||
        n.includes('teunisbloem') || n.includes('lisdodde') || n.includes('hop')) return 'industrial';
    if (n.includes('bollen') || (n.includes('bloem') && !n.includes('bloemkool'))) return 'flowers';
    if (n.includes('erwten') || n.includes('bonen') || n.includes('lupinen') ||
        n.includes('klaver') || n.includes('wikke') || n.includes('kapucijner') ||
        n.includes('esparcette') || n.includes('rolklaver')) return 'legumes';
    if (n.includes('kool') || n.includes('prei') || n.includes('ui') ||
        n.includes('wortel') || n.includes('peen') || n.includes('spinazie') ||
        n.includes('selderij') || n.includes('schorseneer') || n.includes('witlof') ||
        n.includes('broc') || n.includes('asperge') || n.includes('pompoen') ||
        n.includes('courgette') || n.includes('komkommer') || n.includes('andijvie') ||
        n.includes('rabarber') || n.includes('knoflook') || n.includes('sjalot') ||
        n.includes('radijs') || n.includes('paksoi') || n.includes('venkel') ||
        n.includes('peterselie') || n.includes('kroten') || n.includes('pastinaak') ||
        n.includes('aardpeer') || n.includes('kruiden') || n.includes('snijgroen') ||
        n.includes('valeriaan')) return 'vegetables';
    if (n.includes('appel') || n.includes('peer') || n.includes('kers') ||
        n.includes('pruim') || n.includes('bessen') || n.includes('aardbei') ||
        n.includes('framboos') || n.includes('bramen') || n.includes('druif') ||
        n.includes('noten') || n.includes('cranberry') || n.includes('vruchtboom')) return 'fruit';
    if (n.includes('laanboom') || n.includes('laanbomen') || n.includes('sierheesters') ||
        n.includes('sierconiferen') || n.includes('vaste planten') || n.includes('buxus') ||
        n.includes('rozenstruik') || n.includes('bosplant') || n.includes('haagplant') ||
        n.includes('trek- en') || n.includes('ericac') || n.includes('onderstam') ||
        n.includes('kerstboom') || n.includes('moerboom')) return 'nursery';
    if (n.startsWith('bos') || n.includes('natuur') || n.includes('riet') ||
        n.includes('wilgenhak') || n.includes('voedselbos') || n.includes('woudboom') ||
        n.startsWith('rand,') || n.startsWith('rand ') || n.includes('bufferstrook') ||
        n.includes('onbeteeld') || n.includes('sloot')) return 'nature';
    return 'other';
}

function getPesticideExportType(ratio) {
    if (ratio === null || ratio === undefined || ratio === '') return 'nodata';
    const n = Number(ratio);
    if (!Number.isFinite(n)) return 'nodata';
    if (n > 10) return 'severe';
    if (n > 1) return 'above';
    return 'within';
}

function getHydroExportGroup(feature) {
    let t = feature?.properties?.localtype || '';
    t = String(t).toLowerCase();
    if (t.includes('vijver') || t.includes('plas') || t === 'meer' || t === 'duinmeer' ||
        t === 'poel' || t === 'ven' || t === 'wiel' || t === 'dobbe' ||
        t === 'spaarbekken' || t === 'moeras' || t === 'bergingsvijver') return 'pond';
    if (t === 'rivier' || t === 'kanaal' || t === 'gracht' ||
        t === 'primair boezemwater' || t === 'secundair boezemwater') return 'main';
    if (t === 'hoofdwaterloop' || t === 'boezemwater' ||
        t === 'tertiair boezemwater') return 'major';
    if (t === 'waterloop (watergang)' || t === 'polderwaterloop (polderwatergang)' ||
        t === 'beek' || t === 'watervoerende weg') return 'waterway';
    if (t.includes('sloot') || t === 'greppel') return 'ditch';
    return 'other';
}

function getHealthExportType(feature) {
    const value = feature?.properties?.facility_type;
    if (!value) return 'other';
    const type = String(value).toLowerCase();
    return ['hospital', 'clinic', 'doctor', 'pharmacy', 'dentist'].includes(type) ? type : 'other';
}

function setExportButtonLabel(button, label) {
    const nodes = Array.from(button.childNodes);
    const textNode = nodes.reverse().find(node => node.nodeType === Node.TEXT_NODE);
    if (textNode) textNode.textContent = ` ${label}`;
    else button.appendChild(document.createTextNode(` ${label}`));
}

function fullSummaryExportConfig(datasetId) {
    const allBbox = typeof bboxNetherlands !== 'undefined' ? bboxNetherlands : '3.3,50.75,7.22,53.7';
    const plain = (name, url, sheet, file) => ({
        name,
        sheet,
        file,
        load: async () => (await fetchGeoJsonFeatures(url)).map(f => flattenFeatureProperties(f, name))
    });

    const configs = {
        brp: {
            name: 'BRP Crop Parcels',
            sheet: 'BRP all dataset points',
            file: `brp_all_dataset_points_${getSelectedLayerYear('brp', '2025')}.xlsx`,
            load: async () => {
                const year = getSelectedLayerYear('brp', '2025');
                const gemeente = document.getElementById('brp-gemeente-filter')?.value || '';
                const url = `/api/brp_parcels?bbox=${allBbox}&year=${encodeURIComponent(year)}${gemeente ? `&gemeente=${encodeURIComponent(gemeente)}` : ''}`;
                const selected = selectedDatasetFilters('.brp-filter-item', 'brpFilter');
                const allSelected = selected.length === document.querySelectorAll('.brp-filter-item').length;
                return (await fetchGeoJsonFeatures(url))
                    .filter(f => !selected.length || allSelected || selected.includes(getBrpCropTypeName(f.properties?.gewas)))
                    .map(f => flattenFeatureProperties(f, 'BRP Crop Parcels'));
            }
        },
        grenzen: {
            name: 'Bestuurlijke Grenzen',
            sheet: 'Grenzen all dataset points',
            file: 'grenzen_all_dataset_points.xlsx',
            load: async () => {
                const selected = selectedDatasetFilters('.grenzen-filter-item', 'grenzenFilter');
                return (await fetchGeoJsonFeatures(`/api/grenzen?bbox=${allBbox}`))
                    .filter(f => !selected.length || selected.includes(f.properties?.layer_type))
                    .map(f => flattenFeatureProperties(f, 'Bestuurlijke Grenzen'));
            }
        },
        kad: {
            name: 'Kadastrale Kaart',
            sheet: 'Kadastral all dataset points',
            file: 'kadastralekaart_all_dataset_points.xlsx',
            load: async () => {
                const gemeente = document.getElementById('kad-gemeente-filter')?.value || '';
                return (await fetchGeoJsonFeatures(`/api/kadastralekaart?bbox=${allBbox}`))
                    .filter(f => !gemeente || f.properties?.gemeente === gemeente)
                    .map(f => flattenFeatureProperties(f, 'Kadastrale Kaart'));
            }
        },
        natura: plain('Natura 2000', `/api/natura2000_areas?bbox=${allBbox}`, 'Natura all dataset points', 'natura2000_all_dataset_points.xlsx'),
        nnn: plain('Nature Network NL', `/api/nnn?bbox=${allBbox}`, 'NNN all dataset points', 'nnn_all_dataset_points.xlsx'),
        bag: {
            name: 'BAG Buildings',
            sheet: 'BAG all dataset points',
            file: `bag_all_dataset_points_${getSelectedLayerYear('bag', '2026')}.xlsx`,
            load: async () => {
                const year = getSelectedLayerYear('bag', '2026');
                const selected = selectedDatasetFilters('.bag-filter-item', 'bagFilter');
                const allSelected = selected.length === document.querySelectorAll('.bag-filter-item').length;
                if (selected.length && !allSelected) {
                    const limit = typeof BAG_USAGE_API_LIMIT !== 'undefined' ? BAG_USAGE_API_LIMIT : 3000;
                    const usageUrl = `https://api.pdok.nl/kadaster/bag/ogc/v2/collections/verblijfsobject/items?f=json&limit=${limit}&bbox=${allBbox}`;
                    return (await fetchGeoJsonFeatures(usageUrl))
                        .filter(f => selected.includes(getBagUsageType(f.properties?.gebruiksdoel)))
                        .map(f => flattenFeatureProperties(f, 'BAG Usage Locations'));
                }
                const features = await fetchGeoJsonFeatures(`/api/bag_buildings?bbox=${allBbox}&year=${encodeURIComponent(year)}`);
                return features.map(f => flattenFeatureProperties(f, 'BAG Buildings'));
            }
        },
        hydro: {
            name: 'Water Hydrography',
            sheet: 'Hydro all dataset points',
            file: 'hydrography_all_dataset_points.xlsx',
            load: async () => {
                const selected = selectedDatasetFilters('.hydro-filter-item', 'hydroFilter');
                return (await fetchGeoJsonFeatures(`/api/hydrography?bbox=${allBbox}`))
                    .filter(f => !selected.length || selected.includes(getHydroExportGroup(f)))
                    .map(f => flattenFeatureProperties(f, 'Water Hydrography'));
            }
        },
        schools: plain('Schools', `/api/schools?bbox=${allBbox}`, 'Schools all dataset points', 'schools_all_dataset_points.xlsx'),
        health: {
            name: 'Health Facilities',
            sheet: 'Health all dataset points',
            file: 'health_facilities_all_dataset_points.xlsx',
            load: async () => {
                const selected = selectedDatasetFilters('.health-filter-item', 'healthFilter');
                return (await fetchGeoJsonFeatures(`/api/health_facilities?bbox=${allBbox}`))
                    .filter(f => !selected.length || selected.includes(getHealthExportType(f)))
                    .map(f => flattenFeatureProperties(f, 'Health Facilities'));
            }
        },
        pesticides: {
            name: 'Pesticides Atlas',
            sheet: 'Pesticides all dataset points',
            file: 'pesticides_all_dataset_points.xlsx',
            load: async () => {
                const selected = selectedDatasetFilters('.pesticides-filter-item', 'pestFilter');
                return (await fetchGeoJsonFeatures(`/api/pesticides?bbox=${allBbox}`))
                    .filter(f => !selected.length || selected.includes(getPesticideExportType(f.properties?.exceedance_ratio)))
                    .map(f => flattenFeatureProperties(f, 'Pesticides Atlas'));
            }
        },
        wfd: plain('WFD Surface Water', `/api/wfd_surface_water?bbox=${allBbox}`, 'WFD all dataset points', 'wfd_surface_water_all_dataset_points.xlsx'),
        waterschappen: plain('Waterschappen', `/api/waterschappen?bbox=${allBbox}`, 'Waterschappen all dataset points', 'waterschappen_all_dataset_points.xlsx'),
        krd: {
            name: 'KRD Veehouderijen',
            sheet: 'KRD all dataset points',
            file: 'krd_veehouderijen_all_dataset_points.xlsx',
            load: async () => {
                const selected = selectedDatasetFilters('.krd-filter-item', 'krdFilter');
                return (await fetchGeoJsonFeatures(`/api/krd_farms?bbox=${allBbox}`))
                    .filter(f => !selected.length || selected.includes(getKrdCategory(f.properties?.bedrijfstype)))
                    .map(f => flattenFeatureProperties(f, 'KRD Veehouderijen'));
            }
        }
    };

    return configs[datasetId] || null;
}

function setupSummaryFullExportButtons() {
    document.querySelectorAll('[id$="-pivot-xlsx-btn"]').forEach(button => {
        if (button.dataset.fullExportReady) return;
        button.dataset.fullExportReady = 'true';
        const datasetId = button.id.replace('-pivot-xlsx-btn', '');
        setExportButtonLabel(button, 'Export summary');
        button.addEventListener('click', event => {
            if (typeof XLSX !== 'undefined' || button.dataset.xlsxRetrying === 'true') {
                button.dataset.xlsxRetrying = 'false';
                return;
            }
            event.preventDefault();
            event.stopImmediatePropagation();
            const label = button.textContent;
            button.disabled = true;
            setExportButtonLabel(button, 'Preparing...');
            ensureXlsxLoaded()
                .then(() => {
                    button.dataset.xlsxRetrying = 'true';
                    button.disabled = false;
                    button.click();
                })
                .catch(err => alert(`Export failed: ${err.message || err}`))
                .finally(() => {
                    button.disabled = false;
                    setExportButtonLabel(button, label.trim() || 'Export summary');
                });
        }, true);

        const fullButton = button.cloneNode(true);
        fullButton.id = `${datasetId}-pivot-full-xlsx-btn`;
        fullButton.dataset.fullExportButton = 'true';
        setExportButtonLabel(fullButton, 'Export all dataset points');
        fullButton.title = 'Download all available dataset points using the active filters';
        button.insertAdjacentElement('afterend', fullButton);

        fullButton.addEventListener('click', async event => {
            event.stopPropagation();
            const cfg = fullSummaryExportConfig(datasetId);
            if (!cfg) return;
            fullButton.disabled = true;
            setExportButtonLabel(fullButton, 'Exporting...');
            try {
                const rows = await cfg.load();
                await downloadRowsAsWorkbook(rows, cfg.sheet, cfg.file);
            } catch (err) {
                console.error(`${cfg.name} full export failed`, err);
                alert(`Export failed: ${err.message || err}`);
            } finally {
                fullButton.disabled = false;
                setExportButtonLabel(fullButton, 'Export all dataset points');
            }
        });
    });
}

// setupSummaryFullExportButtons removed — "Export all dataset points" is now
// injected directly into each layer's expand panel by the opacity slider loop above.

document.getElementById('buffer-info-export-btn')?.addEventListener('click', async function() {
    const btn = this;
    btn.textContent = 'Exporting…';
    btn.disabled = true;
    const exportDate = new Date().toISOString().split('T')[0];
    const contextRows = [
        { Field: 'Layer',               Value: document.getElementById('buffer-info-layer').textContent },
        { Field: 'Feature',             Value: document.getElementById('buffer-info-name').textContent },
        { Field: 'Buffer radius',       Value: document.getElementById('buffer-info-radius').textContent },
        { Field: 'Municipality',        Value: document.getElementById('buffer-info-gemeente').textContent },
        { Field: 'Province',            Value: document.getElementById('buffer-info-provincie').textContent },
        { Field: 'Nearest Natura 2000', Value: document.getElementById('buffer-info-n2000-nearest').textContent },
        { Field: 'N2000 within buffer', Value: document.getElementById('buffer-info-n2000-within').textContent },
    ];
    try {
        await ensureXlsxLoaded();
        const wb = XLSX.utils.book_new();

        // Sheet 1: Context summary
        XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(contextRows), 'Context');

        // Sheet 2: All datasets within buffer
        if (_bufferExportData.length) {
            XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(_bufferExportData), 'Within Buffer');
        }

        XLSX.writeFile(wb, `Buffer_Analysis_${exportDate}.xlsx`);
    } catch (err) {
        const csvRows = [
            ...contextRows.map(row => ({ Sheet: 'Context', ...row })),
            ..._bufferExportData.map(row => ({ Sheet: 'Within Buffer', ...row }))
        ];
        if (csvRows.length) {
            downloadRowsAsCsv(csvRows, `Buffer_Analysis_${exportDate}.csv`);
            alert('Excel export library was unavailable, so the buffer data was exported as CSV instead.');
        } else {
            alert('Export failed: ' + err.message);
        }
    } finally {
        btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="12" y1="18" x2="12" y2="12"/><line x1="9" y1="15" x2="15" y2="15"/></svg> Export to Excel';
        btn.disabled = false;
    }
});

// Reposition panel when sidebar collapses
(function() {
    const sidebar = document.getElementById('layer-controls');
    const panel   = document.getElementById('buffer-info-panel');
    if (!sidebar || !panel) return;
    new MutationObserver(() => {
        if (!panel.hasAttribute('hidden'))
            panel.style.left = (sidebar.classList.contains('collapsed') ? 8 : sidebar.offsetWidth + 8) + 'px';
    }).observe(sidebar, { attributes: true, attributeFilter: ['class'] });
})();

// =========================================================
// 8. Excel Export - Active or All Layers
// =========================================================

async function exportExcel(exportAll = false) {
    let activeLayers = [];
    if (exportAll) {
        activeLayers = exportRegistry.map(c => c.sheetName);
    } else {
        activeLayers = exportRegistry
            .filter(c => map.hasLayer(c.layerObject))
            .map(c => c.sheetName);

        if (!activeLayers.length) {
            alert("Please enable at least one data layer to export.");
            return;
        }
    }

    const bounds = map.getBounds();
    const bbox = `${bounds.getWest()},${bounds.getSouth()},${bounds.getEast()},${bounds.getNorth()}`;

    try {
        const response = await fetch('/api/export_excel', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ bbox, layers: activeLayers, merges: [] })
        });
        if (!response.ok) {
            let message = 'Workbook export failed. The database might not be connecting.';
            try { const d = await response.json(); if (d?.error) message = d.error; } catch (_) {}
            alert(`Database Connection Error: ${message}`);
            return;
        }
        const blob = await response.blob();
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `Environmental_Evidence_${new Date().toISOString().split('T')[0]}.xlsx`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(a.href);
    } catch (error) {
        alert(`Database connection failed or network error: ${error.message}`);
    }
}

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
