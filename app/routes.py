# app/routes.py
import io
import json
import logging
import pandas as pd
from decimal import Decimal
from flask import Blueprint, render_template, request, jsonify, send_file
from sqlalchemy import text
from app import db

logger = logging.getLogger(__name__)

main_bp = Blueprint('main', __name__)

# ---------------------------------------------------------
# 0. Main Page Route
# ---------------------------------------------------------
@main_bp.route('/')
def home():
    """Renders the landing page."""
    return render_template('home.html')

@main_bp.route('/index')
def index():
    """Renders the main map interface."""
    return render_template('index.html')

@main_bp.route('/dashboard')
def dashboard():
    """Renders the Dashboard page."""
    return render_template('dashboard.html')

# ---------------------------------------------------------
# 1. API Route: Serve BRP Crop Parcels (Time Machine)
# ---------------------------------------------------------
@main_bp.route('/api/brp_parcels', methods=['GET'])
def get_brp_parcels():
    bbox     = request.args.get('bbox')
    year     = request.args.get('year', 2025, type=int)
    gemeente = request.args.get('gemeente', '').strip()

    if not bbox:
        return jsonify({'error': 'Missing bounding box (bbox) parameter'}), 400

    try:
        w, s, e, n = map(float, bbox.split(','))

        if gemeente:
            spatial_filter = "ST_Intersects(geometry, ST_MakeEnvelope(:w, :s, :e, :n, 4326)) AND ST_Intersects(geometry, (SELECT geom FROM grenzen WHERE gemeentenaam = :gemeente AND layer_type = 'gemeenten' LIMIT 1))"
            params = {'year': year, 'gemeente': gemeente, 'w': w, 's': s, 'e': e, 'n': n}
        else:
            spatial_filter = "ST_Intersects(geometry, ST_MakeEnvelope(:w, :s, :e, :n, 4326))"
            params = {'year': year, 'w': w, 's': s, 'e': e, 'n': n}

        sql_query = text(f"""
            SELECT jsonb_build_object(
                'type', 'FeatureCollection',
                'features', COALESCE(jsonb_agg(features.feature), '[]'::jsonb)
            ) AS geojson
            FROM (
                SELECT jsonb_build_object(
                    'type', 'Feature',
                    'properties', jsonb_build_object(
                        'jaar',      year,
                        'gewas',     gewas,
                        'gewascode', gewascode,
                        'area_ha',   ROUND((ST_Area(geometry::geography) / 10000)::numeric, 2)
                    ),
                    'geometry', ST_AsGeoJSON(geometry)::jsonb
                ) AS feature
                FROM brp_parcels
                WHERE year = :year
                  AND {spatial_filter}
                LIMIT 5000
            ) features;
        """)
        result = db.session.execute(sql_query, params).scalar()
        return jsonify(json.loads(result) if isinstance(result, str) else result)
    except Exception as e:
        logger.error(f"BRP Query Error: {e}")
        return jsonify({'error': 'Failed to fetch BRP data'}), 500

# ---------------------------------------------------------
# 1B. API Route: BRP Pivot Table (aggregated crop stats)
# ---------------------------------------------------------
@main_bp.route('/api/brp_pivot', methods=['GET'])
def get_brp_pivot():
    year = request.args.get('year', 2025, type=int)
    try:
        sql = text("""
            SELECT
                gewas                                                         AS crop,
                gewascode,
                COUNT(*)::int                                                 AS parcels,
                ROUND(SUM(ST_Area(geometry::geography) / 10000)::numeric, 1) AS area_ha
            FROM brp_parcels
            WHERE year = :year
            GROUP BY gewas, gewascode
            ORDER BY area_ha DESC
        """)
        rows = db.session.execute(sql, {'year': year}).fetchall()
        data = [
            {'crop': r.crop, 'gewascode': r.gewascode, 'parcels': r.parcels, 'area_ha': float(r.area_ha)}
            for r in rows
        ]
        return jsonify(data)
    except Exception as e:
        logger.error(f"BRP Pivot Error: {e}")
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------
# 1B-b. Buffer Context — municipality, province, and nearest Natura 2000
# distance for a clicked feature at a given lat/lng and radius.
# ---------------------------------------------------------
@main_bp.route('/api/buffer_context', methods=['GET'])
def get_buffer_context():
    lat       = request.args.get('lat',       type=float)
    lng       = request.args.get('lng',       type=float)
    radius_km = request.args.get('radius_km', 1.0, type=float)

    if lat is None or lng is None:
        return jsonify({'error': 'lat and lng required'}), 400

    radius_m = radius_km * 1000.0

    try:
        pt = text("""
            SELECT
                -- Municipality: spatial lookup on grenzen gemeenten polygons
                (SELECT gemeentenaam
                 FROM grenzen
                 WHERE layer_type = 'gemeenten'
                   AND ST_Within(ST_SetSRID(ST_MakePoint(:lng, :lat), 4326), geom)
                 LIMIT 1) AS gemeente,

                -- Province: schools cover all NL and carry a reliable provincie field;
                -- nearest school gives a correct province for virtually all points.
                (SELECT provincie
                 FROM schools
                 WHERE provincie IS NOT NULL
                 ORDER BY geometry <-> ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)
                 LIMIT 1) AS provincie,

                -- Nearest Natura 2000 area name (naam_n2k is the actual name column)
                (SELECT naam_n2k
                 FROM natura2000_areas
                 WHERE naam_n2k IS NOT NULL
                 ORDER BY geometry <-> ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)
                 LIMIT 1) AS nearest_n2000_name,

                -- Distance in km to the nearest Natura 2000 area boundary
                (SELECT ROUND((ST_Distance(
                    geometry::geography,
                    ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography
                ) / 1000.0)::numeric, 2)
                 FROM natura2000_areas
                 WHERE naam_n2k IS NOT NULL
                 ORDER BY geometry <-> ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)
                 LIMIT 1) AS nearest_n2000_km
        """)
        row = db.session.execute(pt, {'lat': lat, 'lng': lng}).fetchone()

        # Natura 2000 areas whose boundary is within the buffer radius
        n2000_within = []
        if radius_m > 0:
            n2000_sql = text("""
                SELECT DISTINCT naam_n2k
                FROM natura2000_areas
                WHERE naam_n2k IS NOT NULL
                  AND ST_DWithin(
                      geometry::geography,
                      ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                      :radius_m
                  )
                ORDER BY naam_n2k
                LIMIT 10
            """)
            n2000_rows = db.session.execute(
                n2000_sql, {'lat': lat, 'lng': lng, 'radius_m': radius_m}
            ).fetchall()
            n2000_within = [r.naam_n2k for r in n2000_rows]

        return jsonify({
            'gemeente':            row.gemeente,
            'provincie':           row.provincie,
            'nearest_n2000':       row.nearest_n2000_name,
            'nearest_n2000_km':    float(row.nearest_n2000_km) if row.nearest_n2000_km is not None else None,
            'n2000_within_buffer': n2000_within
        })
    except Exception as e:
        logger.error(f"Buffer Context Error: {e}")
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------
# 1B-c. API Route: Gemeente names available in the grenzen table
# Used to populate the BRP gemeente filter dropdown.
# ---------------------------------------------------------
@main_bp.route('/api/brp_gemeenten', methods=['GET'])
def get_brp_gemeenten():
    try:
        sql = text("""
            SELECT DISTINCT gemeentenaam
            FROM grenzen
            WHERE layer_type = 'gemeenten'
              AND gemeentenaam IS NOT NULL
            ORDER BY gemeentenaam
        """)
        rows = db.session.execute(sql).fetchall()
        return jsonify([r.gemeentenaam for r in rows])
    except Exception as e:
        logger.error(f"BRP Gemeenten Error: {e}")
        return jsonify([])


SUMMARY_REGION_TYPES = {
    'gemeenten': 'Gemeente',
    'provincies': 'Provincie',
}


def _json_ready(value):
    if isinstance(value, Decimal):
        return float(value)
    return value


def _rows_to_dicts(rows):
    return [
        {key: _json_ready(value) for key, value in row._mapping.items()}
        for row in rows
    ]


@main_bp.route('/api/summary_regions', methods=['GET'])
def get_summary_regions():
    try:
        sql = text("""
            SELECT layer_type, gemeentenaam
            FROM grenzen
            WHERE layer_type IN ('gemeenten', 'provincies')
              AND gemeentenaam IS NOT NULL
              AND gemeentenaam != ''
            GROUP BY layer_type, gemeentenaam
            ORDER BY layer_type, gemeentenaam
        """)
        rows = db.session.execute(sql).fetchall()
        data = {'gemeenten': [], 'provincies': []}
        for row in rows:
            if row.layer_type in data:
                data[row.layer_type].append(row.gemeentenaam)
        return jsonify(data)
    except Exception as e:
        logger.error(f"Summary Regions Error: {e}")
        return jsonify({'gemeenten': [], 'provincies': []})



@main_bp.route('/api/summary/<dataset>', methods=['GET'])
def get_region_summary(dataset):
    region_type = request.args.get('region_type', '').strip()
    region_name = request.args.get('region_name', '').strip()

    if region_type and region_name:
        if region_type not in SUMMARY_REGION_TYPES:
            return jsonify({'error': 'Invalid region type'}), 400
        params = {'region_type': region_type, 'region_name': region_name}
        region_cte = """
            WITH region AS (
                SELECT ST_Union(geom) AS geom
                FROM grenzen
                WHERE layer_type = :region_type
                  AND gemeentenaam = :region_name
            )
        """
        region_label = f"{SUMMARY_REGION_TYPES[region_type]}: {region_name}"
    else:
        # No region filter — cover the entire Netherlands
        params = {'w': 3.3, 's': 50.75, 'e': 7.22, 'n': 53.7}
        region_cte = """
            WITH region AS (
                SELECT ST_MakeEnvelope(:w, :s, :e, :n, 4326) AS geom
            )
        """
        region_label = 'Full dataset'

    try:
        if dataset == 'brp':
            params['year'] = request.args.get('year', 2025, type=int)
            sql = text(region_cte + """
                SELECT
                    b.gewas AS crop,
                    b.gewascode,
                    COUNT(*)::int AS parcels,
                    ROUND(SUM(ST_Area(b.geometry::geography) / 10000)::numeric, 1)::float AS area_ha
                FROM brp_parcels b
                CROSS JOIN region r
                WHERE r.geom IS NOT NULL
                  AND b.year = :year
                  AND ST_Intersects(b.geometry, r.geom)
                GROUP BY b.gewas, b.gewascode
                ORDER BY area_ha DESC
            """)
            rows = _rows_to_dicts(db.session.execute(sql, params).fetchall())

        elif dataset == 'bag':
            sql = text(region_cte + """
                SELECT
                    LOWER(COALESCE(NULLIF(b.status, ''), 'unknown')) AS key,
                    COALESCE(NULLIF(b.status, ''), 'Unknown') AS type,
                    COUNT(*)::int AS count
                FROM bag_buildings b
                CROSS JOIN region r
                WHERE r.geom IS NOT NULL
                  AND ST_Intersects(b.geometry, r.geom)
                GROUP BY type, key
                ORDER BY count DESC, type
            """)
            rows = _rows_to_dicts(db.session.execute(sql, params).fetchall())

        elif dataset == 'natura2000':
            sql = text(region_cte + """
                SELECT DISTINCT
                    COALESCE(props ->> 'naam_n2k', props ->> 'naam', props ->> 'name', '—') AS area_name
                FROM (
                    SELECT row_to_json(n)::jsonb AS props,
                           CASE WHEN ST_SRID(n.geometry) = 4326 THEN n.geometry
                                ELSE ST_Transform(n.geometry, 4326) END AS geom
                    FROM natura2000_areas n
                    WHERE n.geometry IS NOT NULL
                ) n2k
                CROSS JOIN region r
                WHERE r.geom IS NOT NULL
                  AND ST_Intersects(n2k.geom, r.geom)
                ORDER BY area_name
            """)
            rows = _rows_to_dicts(db.session.execute(sql, params).fetchall())

        elif dataset == 'nnn':
            sql = text(region_cte + """
                SELECT DISTINCT
                    COALESCE(props ->> 'name', props ->> 'naam', props ->> 'inspireid', '—') AS area_name
                FROM (
                    SELECT row_to_json(a)::jsonb AS props, a.geometry AS geom
                    FROM nnn_areas a
                    WHERE a.geometry IS NOT NULL
                ) nnn
                CROSS JOIN region r
                WHERE r.geom IS NOT NULL
                  AND ST_Intersects(nnn.geom, r.geom)
                ORDER BY area_name
                LIMIT 1000
            """)
            rows = _rows_to_dicts(db.session.execute(sql, params).fetchall())

        elif dataset == 'grenzen':
            sql = text(region_cte + """
                SELECT
                    g.layer_type AS key,
                    CASE g.layer_type
                        WHEN 'gemeenten' THEN 'Gemeenten'
                        WHEN 'provincies' THEN 'Provincies'
                        WHEN 'landsgrens' THEN 'Landsgrens'
                        ELSE COALESCE(g.layer_type, 'Unknown')
                    END AS type,
                    COUNT(*)::int AS count
                FROM grenzen g
                CROSS JOIN region r
                WHERE r.geom IS NOT NULL
                  AND ST_Intersects(g.geom, r.geom)
                GROUP BY g.layer_type
                ORDER BY count DESC, type
            """)
            rows = _rows_to_dicts(db.session.execute(sql, params).fetchall())

        elif dataset == 'kadastralekaart':
            sql = text(region_cte + """
                SELECT
                    COALESCE(NULLIF(k.gemeente, ''), 'Unknown') AS gemeente,
                    COUNT(*)::int AS parcels,
                    ROUND(SUM(COALESCE(k.kadastralegrootte, 0))::numeric, 0)::float AS area_m2
                FROM kadastralekaart_perceel k
                CROSS JOIN region r
                WHERE r.geom IS NOT NULL
                  AND ST_Intersects(k.geometry, r.geom)
                GROUP BY gemeente
                ORDER BY area_m2 DESC, gemeente
                LIMIT 500
            """)
            rows = _rows_to_dicts(db.session.execute(sql, params).fetchall())

        elif dataset == 'hydrography':
            sql = text(region_cte + """
                SELECT
                    CASE
                        WHEN t LIKE '%vijver%' OR t LIKE '%plas%' OR t IN ('meer', 'duinmeer', 'poel', 'ven', 'wiel', 'dobbe', 'spaarbekken', 'moeras', 'bergingsvijver') THEN 'pond'
                        WHEN t IN ('rivier', 'kanaal', 'gracht', 'primair boezemwater', 'secundair boezemwater') THEN 'main'
                        WHEN t IN ('hoofdwaterloop', 'boezemwater', 'tertiair boezemwater') THEN 'major'
                        WHEN t IN ('waterloop (watergang)', 'polderwaterloop (polderwatergang)', 'beek', 'watervoerende weg') THEN 'waterway'
                        WHEN t LIKE '%sloot%' OR t = 'greppel' THEN 'ditch'
                        ELSE 'other'
                    END AS key,
                    COUNT(*)::int AS count
                FROM (
                    SELECT LOWER(COALESCE(h.localtype, '')) AS t, h.geometry
                    FROM hydrography_watercourse h
                ) h
                CROSS JOIN region r
                WHERE r.geom IS NOT NULL
                  AND ST_Intersects(h.geometry, r.geom)
                GROUP BY key
            """)
            rows = _rows_to_dicts(db.session.execute(sql, params).fetchall())

        elif dataset == 'schools':
            sql = text(region_cte + """
                SELECT
                    COALESCE(NULLIF(s.onderwijstype, ''), 'Other') AS key,
                    COUNT(*)::int AS count
                FROM schools s
                CROSS JOIN region r
                WHERE r.geom IS NOT NULL
                  AND ST_Intersects(s.geometry, r.geom)
                GROUP BY key
                ORDER BY count DESC, key
            """)
            rows = _rows_to_dicts(db.session.execute(sql, params).fetchall())

        elif dataset == 'health':
            sql = text(region_cte + """
                SELECT
                    CASE
                        WHEN LOWER(COALESCE(h.facility_type, '')) IN ('hospital', 'clinic', 'doctor', 'pharmacy', 'dentist')
                        THEN LOWER(h.facility_type)
                        ELSE 'other'
                    END AS key,
                    COUNT(*)::int AS count
                FROM health_facilities h
                CROSS JOIN region r
                WHERE r.geom IS NOT NULL
                  AND ST_Intersects(h.geometry, r.geom)
                GROUP BY key
            """)
            rows = _rows_to_dicts(db.session.execute(sql, params).fetchall())

        elif dataset == 'pesticides':
            sql = text(region_cte + """
                SELECT
                    CASE
                        WHEN worst_exceedance IS NULL THEN 'nodata'
                        WHEN worst_exceedance > 10 THEN 'severe'
                        WHEN worst_exceedance > 1 THEN 'above'
                        ELSE 'within'
                    END AS key,
                    COUNT(*)::int AS count
                FROM (
                    SELECT
                        p.meetpunt_code,
                        p.jaar,
                        MAX(p.mate_normov) AS worst_exceedance
                    FROM pesticides_measurements p
                    CROSS JOIN region r
                    WHERE r.geom IS NOT NULL
                      AND ST_Intersects(p.geometry, r.geom)
                    GROUP BY p.meetpunt_code, p.jaar
                ) agg
                GROUP BY key
            """)
            rows = _rows_to_dicts(db.session.execute(sql, params).fetchall())

        elif dataset == 'wfd':
            sql = text(region_cte + """
                SELECT
                    CASE
                        WHEN zone LIKE '%river%' THEN 'River'
                        WHEN zone LIKE '%lake%' THEN 'Lake'
                        WHEN zone LIKE '%coastal%' THEN 'Coastal'
                        WHEN zone LIKE '%transitional%' THEN 'Transitional'
                        WHEN zone = '' THEN 'Unknown'
                        ELSE INITCAP(zone)
                    END AS key,
                    COUNT(*)::int AS count
                FROM (
                    SELECT
                        LOWER(COALESCE(row_to_json(w)::jsonb ->> 'specialisedzonetype', '')) AS zone,
                        w.geometry
                    FROM wfd_surface_water w
                    WHERE w.geometry IS NOT NULL
                ) wfd
                CROSS JOIN region r
                WHERE r.geom IS NOT NULL
                  AND ST_Intersects(wfd.geometry, r.geom)
                GROUP BY key
                ORDER BY count DESC, key
            """)
            rows = _rows_to_dicts(db.session.execute(sql, params).fetchall())

        elif dataset == 'waterschappen':
            sql = text(region_cte + """
                SELECT DISTINCT
                    COALESCE(NULLIF(w.naam, ''), '—') AS water_authority,
                    w.code
                FROM waterschappen w
                CROSS JOIN region r
                WHERE r.geom IS NOT NULL
                  AND w.naam IS NOT NULL
                  AND w.naam != ''
                  AND ST_Intersects(w.geom, r.geom)
                ORDER BY water_authority
            """)
            rows = _rows_to_dicts(db.session.execute(sql, params).fetchall())

        elif dataset == 'krd':
            sql = text(region_cte + """
                SELECT
                    COALESCE(NULLIF(k.bedrijfstype, ''), 'Unknown') AS key,
                    COUNT(*)::int AS count,
                    ROUND(SUM(
                        CASE
                            WHEN k."nh3 emissie (kg/j)"::text ~ '^[0-9]+(\.[0-9]+)?$'
                            THEN k."nh3 emissie (kg/j)"::text::numeric
                            ELSE 0
                        END
                    )::numeric, 1)::float AS nh3_total
                FROM krd_farms k
                CROSS JOIN region r
                WHERE r.geom IS NOT NULL
                  AND ST_Intersects(k.geometry, r.geom)
                  AND (k.bedrijfstype IS NULL OR k.bedrijfstype != 'voormalig bedrijf')
                GROUP BY key
                ORDER BY count DESC, key
            """)
            rows = _rows_to_dicts(db.session.execute(sql, params).fetchall())

        else:
            return jsonify({'error': 'Unknown summary dataset'}), 404

        return jsonify({
            'dataset': dataset,
            'region': {
                'type': region_type or 'full',
                'name': region_name or 'Netherlands',
                'label': region_label,
            },
            'rows': rows,
        })
    except Exception as e:
        logger.error(f"Region Summary Error ({dataset}): {e}")
        return jsonify({'error': 'Failed to build region summary', 'details': str(e)}), 500


@main_bp.route('/api/gemeente_boundary', methods=['GET'])
def get_gemeente_boundary():
    gemeente = request.args.get('gemeente', '').strip()
    if not gemeente:
        return jsonify({'error': 'Missing gemeente parameter'}), 400

    try:
        sql = text("""
            SELECT jsonb_build_object(
                'type', 'Feature',
                'properties', jsonb_build_object(
                    'gemeentenaam', gemeentenaam,
                    'layer_type', layer_type
                ),
                'geometry', ST_AsGeoJSON(geom)::jsonb
            ) AS geojson
            FROM grenzen
            WHERE layer_type = 'gemeenten'
              AND gemeentenaam = :gemeente
            LIMIT 1
        """)
        result = db.session.execute(sql, {'gemeente': gemeente}).scalar()
        if not result:
            return jsonify({'error': 'Gemeente not found'}), 404
        return jsonify(json.loads(result) if isinstance(result, str) else result)
    except Exception as e:
        logger.error(f"Gemeente Boundary Error: {e}")
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------
# 1C. API Route: BRP Trend — year-over-year crop category totals
# Used by the Trend Analysis tab in the pivot popup to answer:
# "Is grassland increasing? Is maize expanding?"
# ---------------------------------------------------------
@main_bp.route('/api/brp_trend', methods=['GET'])
def get_brp_trend():
    try:
        # Reads from brp_trend_cache (materialized view), grouping pre-computed
        # area_ha values by crop category. Instant vs. the minutes-long live query.
        sql = text("""
            SELECT
                year,
                ROUND(SUM(CASE WHEN gewas ILIKE '%gras%'    OR gewas ILIKE '%weide%'  THEN area_ha ELSE 0 END)::numeric, 1) AS grassland_ha,
                ROUND(SUM(CASE WHEN gewas ILIKE '%mais%'    OR gewas ILIKE '%maïs%'   THEN area_ha ELSE 0 END)::numeric, 1) AS maize_ha,
                ROUND(SUM(CASE WHEN gewas ILIKE '%aardappel%'                          THEN area_ha ELSE 0 END)::numeric, 1) AS potato_ha,
                ROUND(SUM(CASE WHEN gewas ILIKE '%tarwe%'   OR gewas ILIKE '%graan%'  OR gewas ILIKE '%gerst%'
                               OR gewas ILIKE '%haver%'    OR gewas ILIKE '%rogge%'   OR gewas ILIKE '%triticale%'
                               OR gewas ILIKE '%spelt%'    OR gewas ILIKE '%raaigras%' OR gewas ILIKE '%zwenkgras%'
                               OR gewas ILIKE '%boekweit%' OR gewas ILIKE '%soedangras%' OR gewas ILIKE '%sorghum%'
                                                                                       THEN area_ha ELSE 0 END)::numeric, 1) AS wheat_ha,
                ROUND(SUM(CASE WHEN gewas ILIKE '%bieten%'                             THEN area_ha ELSE 0 END)::numeric, 1) AS beets_ha,
                ROUND(SUM(CASE WHEN gewas ILIKE '%koolzaad%' OR gewas ILIKE '%raapzaad%' OR gewas ILIKE '%vlas%'
                               OR gewas ILIKE '%hennep%'   OR gewas ILIKE '%zonnebloem%' OR gewas ILIKE '%miscanthus%'
                               OR gewas ILIKE '%luzerne%'  OR gewas ILIKE '%cichorei%' OR gewas ILIKE '%mosterd%'
                               OR gewas ILIKE '%groenbemester%' OR gewas ILIKE '%facelia%' OR gewas ILIKE '%tagetes%'
                               OR gewas ILIKE '%bladrammenas%' OR gewas ILIKE '%drachtplant%' OR gewas ILIKE '%soja%'
                               OR gewas ILIKE '%quinoa%'   OR gewas ILIKE '%teunisbloem%' OR gewas ILIKE '%lisdodde%'
                               OR gewas ILIKE '%hop%'                                  THEN area_ha ELSE 0 END)::numeric, 1) AS industrial_ha,
                ROUND(SUM(CASE WHEN (gewas ILIKE '%bollen%' OR (gewas ILIKE '%bloem%' AND gewas NOT ILIKE '%bloemkool%'))
                               AND gewas NOT ILIKE '%zonnebloem%'                      THEN area_ha ELSE 0 END)::numeric, 1) AS flowers_ha,
                ROUND(SUM(CASE WHEN gewas ILIKE '%erwten%'  OR gewas ILIKE '%bonen%'  OR gewas ILIKE '%lupinen%'
                               OR gewas ILIKE '%klaver%'   OR gewas ILIKE '%wikke%'   OR gewas ILIKE '%kapucijner%'
                               OR gewas ILIKE '%esparcette%' OR gewas ILIKE '%rolklaver%'
                                                                                       THEN area_ha ELSE 0 END)::numeric, 1) AS legumes_ha,
                ROUND(SUM(CASE WHEN gewas ILIKE '%kool%'    OR gewas ILIKE '%prei%'   OR gewas ILIKE '%wortel%'
                               OR gewas ILIKE '%peen%'     OR gewas ILIKE '%spinazie%' OR gewas ILIKE '%selderij%'
                               OR gewas ILIKE '%schorseneer%' OR gewas ILIKE '%witlof%' OR gewas ILIKE '%broc%'
                               OR gewas ILIKE '%asperge%'  OR gewas ILIKE '%pompoen%' OR gewas ILIKE '%courgette%'
                               OR gewas ILIKE '%komkommer%' OR gewas ILIKE '%andijvie%' OR gewas ILIKE '%rabarber%'
                               OR gewas ILIKE '%knoflook%' OR gewas ILIKE '%sjalot%'  OR gewas ILIKE '%radijs%'
                               OR gewas ILIKE '%ui%'       OR gewas ILIKE '%venkel%'  OR gewas ILIKE '%kruiden%'
                               OR gewas ILIKE '%snijgroen%' OR gewas ILIKE '%valeriaan%' OR gewas ILIKE '%pastinaak%'
                               OR gewas ILIKE '%aardpeer%'                             THEN area_ha ELSE 0 END)::numeric, 1) AS vegetables_ha,
                ROUND(SUM(CASE WHEN gewas ILIKE '%appel%'   OR gewas ILIKE '%peer%'   OR gewas ILIKE '%kers%'
                               OR gewas ILIKE '%pruim%'    OR gewas ILIKE '%bessen%'  OR gewas ILIKE '%aardbei%'
                               OR gewas ILIKE '%framboos%' OR gewas ILIKE '%bramen%'  OR gewas ILIKE '%druif%'
                               OR gewas ILIKE '%noten%'    OR gewas ILIKE '%cranberry%' OR gewas ILIKE '%vruchtboom%'
                                                                                       THEN area_ha ELSE 0 END)::numeric, 1) AS fruit_ha,
                ROUND(SUM(CASE WHEN gewas ILIKE '%laanboom%' OR gewas ILIKE '%laanbomen%' OR gewas ILIKE '%sierheesters%'
                               OR gewas ILIKE '%sierconiferen%' OR gewas ILIKE '%vaste planten%' OR gewas ILIKE '%buxus%'
                               OR gewas ILIKE '%rozenstruik%' OR gewas ILIKE '%bosplant%' OR gewas ILIKE '%haagplant%'
                               OR gewas ILIKE '%ericac%'   OR gewas ILIKE '%onderstam%' OR gewas ILIKE '%kerstboom%'
                               OR gewas ILIKE '%moerboom%'                             THEN area_ha ELSE 0 END)::numeric, 1) AS nursery_ha,
                ROUND(SUM(CASE WHEN gewas ILIKE 'bos%'      OR gewas ILIKE '%natuur%' OR gewas ILIKE '%riet%'
                               OR gewas ILIKE '%wilgenhak%' OR gewas ILIKE '%voedselbos%' OR gewas ILIKE '%woudboom%'
                               OR gewas ILIKE 'rand,%'      OR gewas ILIKE 'rand %'   OR gewas ILIKE '%bufferstrook%'
                               OR gewas ILIKE '%onbeteeld%' OR gewas ILIKE '%sloot%'  THEN area_ha ELSE 0 END)::numeric, 1) AS nature_ha,
                ROUND(SUM(area_ha)::numeric, 1) AS total_ha
            FROM brp_trend_cache
            GROUP BY year
            ORDER BY year
        """)

        data = []
        for r in db.session.execute(sql).fetchall():
            categorised = sum([
                float(r.grassland_ha), float(r.maize_ha),  float(r.potato_ha),
                float(r.wheat_ha),     float(r.beets_ha),  float(r.industrial_ha),
                float(r.flowers_ha),   float(r.legumes_ha), float(r.vegetables_ha),
                float(r.fruit_ha),     float(r.nursery_ha), float(r.nature_ha),
            ])
            data.append({
                'year':          r.year,
                'grassland_ha':  float(r.grassland_ha),
                'maize_ha':      float(r.maize_ha),
                'potato_ha':     float(r.potato_ha),
                'wheat_ha':      float(r.wheat_ha),
                'beets_ha':      float(r.beets_ha),
                'industrial_ha': float(r.industrial_ha),
                'flowers_ha':    float(r.flowers_ha),
                'legumes_ha':    float(r.legumes_ha),
                'vegetables_ha': float(r.vegetables_ha),
                'fruit_ha':      float(r.fruit_ha),
                'nursery_ha':    float(r.nursery_ha),
                'nature_ha':     float(r.nature_ha),
                'other_ha':      round(float(r.total_ha) - categorised, 1),
                'total_ha':      float(r.total_ha),
            })
        return jsonify(data)
    except Exception as e:
        logger.error(f"BRP Trend Error: {e}")
        return jsonify({'error': str(e)}), 500

# ---------------------------------------------------------
# 1B. API Route: All unique gemeente names for Kadastrale Kaart
# ---------------------------------------------------------
@main_bp.route('/api/kad_gemeenten', methods=['GET'])
def get_kad_gemeenten():
    try:
        sql = text("""
            SELECT DISTINCT gemeente
            FROM kadastralekaart_perceel
            WHERE gemeente IS NOT NULL AND gemeente != ''
            ORDER BY gemeente
        """)
        rows = db.session.execute(sql).fetchall()
        return jsonify([r.gemeente for r in rows])
    except Exception as e:
        logger.error(f"Kad Gemeenten Error: {e}")
        return jsonify({'error': str(e)}), 500

# ---------------------------------------------------------
# 2. API Route: Serve BAG Buildings (Temporal Filtering)
# ---------------------------------------------------------
@main_bp.route('/api/bag_buildings', methods=['GET'])
def get_bag_buildings():
    bbox = request.args.get('bbox')
    year = request.args.get('year', 2026, type=int)

    if not bbox:
        return jsonify({'error': 'Missing bbox parameter'}), 400

    try:
        w, s, e, n = map(float, bbox.split(','))
        sql_query = text("""
            SELECT jsonb_build_object('type', 'FeatureCollection', 'features', COALESCE(jsonb_agg(features.feature), '[]'::jsonb)) AS geojson
            FROM (
                SELECT jsonb_build_object(
                    'type', 'Feature',
                    'properties', jsonb_build_object(
                        'identificatie', identificatie, 
                        'bouwjaar', oorspronkelijkbouwjaar, 
                        'status', status
                    ),
                    'geometry', ST_AsGeoJSON(geometry)::jsonb
                ) AS feature
                FROM bag_buildings
                WHERE oorspronkelijkbouwjaar <= :year 
                  AND ST_Intersects(geometry, ST_MakeEnvelope(:w, :s, :e, :n, 4326)) 
                LIMIT 3000
            ) features;
        """)
        result = db.session.execute(sql_query, {'year': year, 'w': w, 's': s, 'e': e, 'n': n}).scalar()
        return jsonify(json.loads(result) if isinstance(result, str) else result)
    except Exception as e:
        logger.error(f"BAG Query Error: {e}")
        return jsonify({'error': 'Failed to fetch BAG data'}), 500

# ---------------------------------------------------------
# 3. API Route: Serve Natura 2000 Areas, Buffers, and Centers
# ---------------------------------------------------------
@main_bp.route('/api/natura2000_areas', methods=['GET'])
def get_natura2000_areas():
    bbox = request.args.get('bbox')

    if not bbox:
        return jsonify({'error': 'Missing bbox parameter'}), 400

    try:
        w, s, e, n = map(float, bbox.split(','))

        sql_query = text("""
            SELECT jsonb_build_object(
                'type', 'FeatureCollection',
                'features', COALESCE(jsonb_agg(feature), '[]'::jsonb)
            ) AS geojson
            FROM (
                SELECT jsonb_build_object(
                    'type', 'Feature',
                    'properties',
                        (row_to_json(n)::jsonb - 'geometry')
                        || jsonb_build_object('layer_type', 'area'),
                    'geometry', ST_AsGeoJSON(
                        CASE WHEN ST_SRID(n.geometry) = 4326 THEN n.geometry
                             ELSE ST_Transform(n.geometry, 4326) END
                    )::jsonb
                ) AS feature
                FROM natura2000_areas n
                WHERE n.geometry IS NOT NULL
                  AND ST_Intersects(
                      CASE WHEN ST_SRID(n.geometry) = 4326 THEN n.geometry
                           ELSE ST_Transform(n.geometry, 4326) END,
                      ST_MakeEnvelope(:w, :s, :e, :n, 4326)
                  )
                LIMIT 750
            ) features;
        """)

        result = db.session.execute(sql_query, {'w': w, 's': s, 'e': e, 'n': n}).scalar()
        return jsonify(json.loads(result) if isinstance(result, str) else result)
    except Exception as e:
        logger.error(f"Natura 2000 Query Error: {e}")
        return jsonify({'error': 'Failed to fetch Natura 2000 data', 'details': str(e)}), 500


# ---------------------------------------------------------
# 8B. API Route: Dynamic Dashboard Stats
# ---------------------------------------------------------
@main_bp.route('/api/dashboard_stats', methods=['GET'])
def get_dashboard_stats():
    stats = {}
    try:
        with db.engine.connect() as conn:
            def _stat(stmt):
                """Run one stat query; roll back on failure so subsequent queries are unaffected."""
                try:
                    return conn.execute(text(stmt) if isinstance(stmt, str) else stmt).fetchall()
                except Exception as e:
                    conn.rollback()
                    logger.error(f"DB Stat error: {e}")
                    return []

            # AGRI
            res = _stat("SELECT gewas, COUNT(*) FROM brp_parcels WHERE year = (SELECT MAX(year) FROM brp_parcels) GROUP BY gewas ORDER BY COUNT(*) DESC LIMIT 10")
            if res:
                stats['cropDistrib'] = {'labels': [r[0] or 'Unknown' for r in res], 'values': [r[1] for r in res]}

            res = _stat("""
                SELECT
                    CASE
                        WHEN oorspronkelijkbouwjaar < 1945 THEN '<1945'
                        WHEN oorspronkelijkbouwjaar < 1960 THEN '1945-60'
                        WHEN oorspronkelijkbouwjaar < 1970 THEN '1960-70'
                        WHEN oorspronkelijkbouwjaar < 1980 THEN '1970-80'
                        WHEN oorspronkelijkbouwjaar < 1990 THEN '1980-90'
                        WHEN oorspronkelijkbouwjaar < 2000 THEN '1990-00'
                        WHEN oorspronkelijkbouwjaar < 2010 THEN '2000-10'
                        WHEN oorspronkelijkbouwjaar < 2020 THEN '2010-20'
                        ELSE '2020+'
                    END as decade, COUNT(*)
                FROM bag_buildings WHERE oorspronkelijkbouwjaar > 1000 GROUP BY decade
            """)
            if res:
                decade_order = ['<1945', '1945-60', '1960-70', '1970-80', '1980-90', '1990-00', '2000-10', '2010-20', '2020+']
                d_dict = {r[0]: r[1] for r in res}
                stats['bagYear']    = {'labels': decade_order, 'values': [d_dict.get(d, 0) / 1000.0    for d in decade_order]}
                stats['bagDecades'] = {'labels': decade_order, 'values': [d_dict.get(d, 0) / 1000000.0 for d in decade_order]}

            res = _stat("""
                SELECT
                    CASE
                        WHEN kadastralegrootte < 5000   THEN '<0.5 ha'
                        WHEN kadastralegrootte < 10000  THEN '0.5-1'
                        WHEN kadastralegrootte < 20000  THEN '1-2'
                        WHEN kadastralegrootte < 50000  THEN '2-5'
                        WHEN kadastralegrootte < 100000 THEN '5-10'
                        WHEN kadastralegrootte < 250000 THEN '10-25'
                        ELSE '>25 ha'
                    END as size_band, COUNT(*)
                FROM kadastralekaart_perceel GROUP BY size_band
            """)
            if res:
                sz_order = ['<0.5 ha', '0.5-1', '1-2', '2-5', '5-10', '10-25', '>25 ha']
                sz_dict = {r[0]: r[1] for r in res}
                tot = sum(sz_dict.values()) or 1
                stats['parcelSize'] = {'labels': sz_order, 'values': [round((sz_dict.get(d, 0) / tot) * 100, 1) for d in sz_order]}

            # LIVESTOCK
            res = _stat("""
                SELECT bedrijfstype, COUNT(*),
                    SUM(CASE WHEN "nh3 emissie (kg/j)" ~ '^[0-9]+(\.[0-9]+)?$' THEN "nh3 emissie (kg/j)"::numeric ELSE 0 END),
                    SUM(CASE WHEN "geur emissie (oue/s)" ~ '^[0-9]+(\.[0-9]+)?$' THEN "geur emissie (oue/s)"::numeric ELSE 0 END),
                    SUM(CASE WHEN "fijnstof emissie (g/j)" ~ '^[0-9]+(\.[0-9]+)?$' THEN "fijnstof emissie (g/j)"::numeric ELSE 0 END)
                FROM krd_farms WHERE bedrijfstype IS NOT NULL AND bedrijfstype != 'voormalig bedrijf'
                GROUP BY bedrijfstype ORDER BY 3 DESC LIMIT 7
            """)
            if res:
                stats['nh3ByType']   = {'labels': [r[0] for r in res], 'farms': [r[1] for r in res], 'nh3': [float(r[2]) for r in res]}
                stats['emissionMix'] = {'labels': [r[0] for r in res], 'nh3': [float(r[2]) for r in res], 'odour': [float(r[3]) for r in res], 'dust': [float(r[4]) for r in res]}

            res = _stat("""
                SELECT provincie, COUNT(*), SUM(CASE WHEN "nh3 emissie (kg/j)" ~ '^[0-9]+(\.[0-9]+)?$' THEN "nh3 emissie (kg/j)"::numeric ELSE 0 END)
                FROM krd_farms WHERE provincie IS NOT NULL AND provincie != ''
                GROUP BY provincie ORDER BY 2 DESC LIMIT 6
            """)
            if res:
                stats['farmsByProv'] = {'labels': [r[0] for r in res], 'farms': [r[1] for r in res], 'nh3': [float(r[2]) for r in res]}

            # NATURE & PESTICIDES
            res = _stat("""
                SELECT
                    CASE
                        WHEN worst > 10 THEN 'Extreme (>10x)'
                        WHEN worst > 5  THEN 'High (5-10x)'
                        WHEN worst > 1  THEN 'Above norm (1-5x)'
                        WHEN worst = 1  THEN 'At norm'
                        WHEN worst IS NOT NULL THEN 'Below norm'
                        ELSE 'No data'
                    END as cls, COUNT(*)
                FROM (SELECT meetpunt_code, MAX(mate_normov) as worst FROM pesticides_measurements GROUP BY meetpunt_code) a
                GROUP BY cls
            """)
            if res:
                pc_order = ['Below norm', 'At norm', 'Above norm (1-5x)', 'High (5-10x)', 'Extreme (>10x)', 'No data']
                pc_dict = {r[0]: r[1] for r in res}
                stats['pestClasses'] = {'labels': pc_order, 'values': [pc_dict.get(d, 0) for d in pc_order]}

            res = _stat("""
                SELECT stof_naam_sam, AVG(mate_normov) as avg_ex
                FROM pesticides_measurements WHERE mate_normov IS NOT NULL
                GROUP BY stof_naam_sam ORDER BY avg_ex DESC LIMIT 10
            """)
            if res:
                stats['substances'] = {'labels': [r[0] for r in res], 'avg': [float(r[1]) for r in res]}

            res = _stat("SELECT COUNT(*) FROM natura2000_areas")
            cnt = res[0][0] if res else None
            if cnt:
                stats['n2kTypes'] = {'labels': ['Protected Sites'], 'values': [cnt]}

            res = _stat("""
                SELECT jaar, COUNT(CASE WHEN worst > 1 THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0)
                FROM (SELECT jaar, meetpunt_code, MAX(mate_normov) as worst FROM pesticides_measurements GROUP BY jaar, meetpunt_code) a
                GROUP BY jaar ORDER BY jaar
            """)
            if res:
                stats['pestTrend'] = {'years': [r[0] for r in res], 'pct': [round(float(r[1]), 1) if r[1] else 0 for r in res]}

            # WATER & INFRASTRUCTURE
            for layer, table, col, key in [
                ('hydroTypes', 'hydrography_watercourse', "CASE WHEN localtype IN ('rivier', 'kanaal', 'gracht') THEN 'Main Channels' WHEN localtype LIKE '%boezemwater%' THEN 'Boezemwater' WHEN localtype LIKE '%waterloop%' OR localtype = 'beek' THEN 'Waterway' WHEN localtype LIKE '%sloot%' OR localtype = 'greppel' THEN 'Ditches' ELSE 'Other' END", None),
                ('wfdStatus',   'wfd_surface_water',       "COALESCE(row_to_json(wfd_surface_water)::jsonb ->> 'specialisedzonetype', 'Unknown')", None),
                ('waterschap',  'waterschappen',            'naam', None),
                ('streamOrder', 'hydrography_watercourse', 'streamorder', "streamorder IS NOT NULL AND streamorder != ''"),
                ('bagTypes',    'bag_buildings',            "COALESCE(NULLIF(status, ''), 'Unknown')", None),
                ('schoolTypes', 'schools',                  "COALESCE(NULLIF(onderwijstype, ''), 'Other')", None),
                ('healthTypes', 'health_facilities',        "COALESCE(NULLIF(facility_type, ''), 'Other')", None),
            ]:
                where_clause = f"WHERE {key}" if key else ""
                res = _stat(f"SELECT {col}, COUNT(*) FROM {table} {where_clause} GROUP BY 1 ORDER BY 2 DESC LIMIT 10")
                if res:
                    val_key = 'km2' if layer == 'waterschap' else ('km' if layer == 'hydroTypes' else 'values')
                    stats[layer] = {'labels': [r[0] or 'Unknown' for r in res], val_key: [r[1] for r in res]}
    except Exception as e:
        logger.error(f"Dashboard Stats Overall Error: {e}")
    return jsonify(stats)


# ---------------------------------------------------------
# 4. API Route: Serve Grenzen (Regional Boarders)
# ---------------------------------------------------------
@main_bp.route('/api/grenzen', methods=['GET'])
def get_grenzen():
    bbox = request.args.get('bbox')
    if not bbox:
        return jsonify({'error': 'Missing bbox parameter'}), 400

    try:
        w, s, e, n = map(float, bbox.split(','))

        sql_query = text("""
            SELECT jsonb_build_object(
                'type', 'FeatureCollection',
                'features', COALESCE(jsonb_agg(features.feature), '[]'::jsonb)
            ) AS geojson
            FROM (
                SELECT jsonb_build_object(
                    'type', 'Feature',
                    'properties', jsonb_build_object(
                        'id',           g.ogc_fid,
                        'code',         g.code,
                        'gemeentenaam', g.gemeentenaam,
                        'layer_type',   g.layer_type
                    ),
                    'geometry', ST_AsGeoJSON(g.geom)::jsonb
                ) AS feature
                FROM grenzen g
                WHERE ST_Intersects(g.geom, ST_MakeEnvelope(:w, :s, :e, :n, 4326))
            ) features;
        """)
        result = db.session.execute(sql_query, {'w': w, 's': s, 'e': e, 'n': n}).scalar()

        return jsonify(json.loads(result) if isinstance(result, str) else result)

    except Exception as e:
        logger.error(f"Grenzen Query Error: {e}")
        return jsonify({'error': 'Failed to fetch Grenzen data', 'details': str(e)}), 500


# ---------------------------------------------------------
# 5. API Route: KRD Livestock Farms (one point per farm, krd_farms table)
#
# krd_farms = the farm-level overview from KRD / iGoView.
# Each point is one farm location with total NH3, animal type, permit status, etc.
# The optional animal_type filter maps to the "bedrijfstype" column (e.g. "Vleesvarkens").
# Source: https://krd.igoview.nl/ → Veehouderijen tab → Totaaloverzicht veehouderijen
# ---------------------------------------------------------
@main_bp.route('/api/krd_farms', methods=['GET'])
def get_krd_farms():
    bbox = request.args.get('bbox')
    animal_type = request.args.get('animal_type', '').strip()
    if not bbox:
        return jsonify({'error': 'Missing bbox parameter'}), 400

    try:
        w, s, e, n = map(float, bbox.split(','))
        sql_query = text("""
            SELECT jsonb_build_object(
                'type', 'FeatureCollection',
                'features', COALESCE(jsonb_agg(features.feature), '[]'::jsonb)
            ) AS geojson
            FROM (
                SELECT jsonb_build_object(
                    'type', 'Feature',
                    'properties', row_to_json(k)::jsonb - 'geometry' - 'id',
                    'geometry', ST_AsGeoJSON(geometry)::jsonb
                ) AS feature
                FROM krd_farms k
                WHERE ST_Intersects(geometry, ST_MakeEnvelope(:w, :s, :e, :n, 4326))
                  AND (:animal_type = '' OR k."bedrijfstype" = :animal_type)
                  -- voormalig bedrijf = terminated permit, NH3=0, no active emissions.
                  -- Excluded because there is no historical timeline layer to give them context.
                  AND (k."bedrijfstype" IS NULL OR k."bedrijfstype" != 'voormalig bedrijf')
                LIMIT 20000
            ) features;
        """)
        result = db.session.execute(sql_query, {'w': w, 's': s, 'e': e, 'n': n, 'animal_type': animal_type}).scalar()
        return jsonify(json.loads(result) if isinstance(result, str) else result)
    except Exception as e:
        logger.error(f"KRD Query Error: {e}")
        return jsonify({'error': 'Failed to fetch KRD data'}), 500

# ---------------------------------------------------------
# 5b. API Route: KRD Stallen (individual housing units, krd_stallen table)
#
# krd_stallen = one row per animal housing unit (stal) within a farm.
# A single farm can have multiple stallen, each with its own NH3/odour/dust figures.
# This is more granular than krd_farms — useful for per-unit emission analysis.
# Note: stallen exports do NOT include an animal type field (bedrijfstype).
#   Animal type is only available at the farm level in krd_farms.
# Loaded via etl/load_stallen.py from the KRD "Stallen" tab exports.
# Source: https://krd.igoview.nl/ → Stallen tab → Totaaloverzicht stallen
# ---------------------------------------------------------
@main_bp.route('/api/krd_stallen', methods=['GET'])
def get_krd_stallen():
    bbox = request.args.get('bbox')
    if not bbox:
        return jsonify({'error': 'Missing bbox parameter'}), 400

    try:
        w, s, e, n = map(float, bbox.split(','))
        sql_query = text("""
            SELECT jsonb_build_object(
                'type', 'FeatureCollection',
                'features', COALESCE(jsonb_agg(features.feature), '[]'::jsonb)
            ) AS geojson
            FROM (
                SELECT jsonb_build_object(
                    'type', 'Feature',
                    'properties', row_to_json(s)::jsonb - 'geometry' - 'id',
                    'geometry', ST_AsGeoJSON(geometry)::jsonb
                ) AS feature
                FROM krd_stallen s
                WHERE ST_Intersects(geometry, ST_MakeEnvelope(:w, :s, :e, :n, 4326))
                LIMIT 10000
            ) features;
        """)
        result = db.session.execute(sql_query, {
            'w': w, 's': s, 'e': e, 'n': n
        }).scalar()
        return jsonify(json.loads(result) if isinstance(result, str) else result)
    except Exception as e:
        logger.error(f"KRD Stallen Query Error: {e}")
        return jsonify({'error': 'Failed to fetch KRD stallen data'}), 500

# ---------------------------------------------------------
# 6. API Route: Serve Pesticides Atlas Measurements (Point Layer)
# ---------------------------------------------------------
@main_bp.route('/api/pesticides', methods=['GET'])
def get_pesticides():
    bbox = request.args.get('bbox')
    year = request.args.get('year', type=int)
    if not bbox:
        return jsonify({'error': 'Missing bbox parameter'}), 400

    try:
        w, s, e, n = map(float, bbox.split(','))
        year_filter = "AND jaar = :year" if year else ""
        params = {'w': w, 's': s, 'e': e, 'n': n}
        if year:
            params['year'] = year
        sql_query = text(f"""
            SELECT jsonb_build_object(
                'type', 'FeatureCollection',
                'features', COALESCE(jsonb_agg(features.feature), '[]'::jsonb)
            ) AS geojson
            FROM (
                SELECT jsonb_build_object(
                    'type', 'Feature',
                    'properties', jsonb_build_object(
                        'station_code',           meetpunt_code,
                        'water_board',            wbhcode_omschrijving,
                        'year',                   jaar,
                        'substances_tested',      substances_tested,
                        'worst_substance',        worst_substance,
                        'norm_type',              worst_norm_omschrijving,
                        'exceedance_ratio',       worst_exceedance,
                        'exceedances_above_norm', exceedances_above_norm
                    ),
                    'geometry', ST_AsGeoJSON(geometry)::jsonb
                ) AS feature
                FROM (
                    SELECT
                        meetpunt_code,
                        wbhcode_omschrijving,
                        jaar,
                        geometry,
                        COUNT(*)                                          AS substances_tested,
                        SUM(CASE WHEN mate_normov > 1 THEN 1 ELSE 0 END) AS exceedances_above_norm,
                        MAX(mate_normov)                                  AS worst_exceedance,
                        (ARRAY_AGG(stof_naam_sam ORDER BY mate_normov DESC NULLS LAST))[1] AS worst_substance,
                        (ARRAY_AGG(norm_omschrijving ORDER BY mate_normov DESC NULLS LAST))[1] AS worst_norm_omschrijving
                    FROM pesticides_measurements
                    WHERE ST_Intersects(geometry, ST_MakeEnvelope(:w, :s, :e, :n, 4326))
                      {year_filter}
                    GROUP BY meetpunt_code, wbhcode_omschrijving, jaar, geometry
                    LIMIT 5000
                ) agg
            ) features;
        """)
        result = db.session.execute(sql_query, params).scalar()
        return jsonify(json.loads(result) if isinstance(result, str) else result)
    except Exception as e:
        logger.error(f"Pesticides Query Error: {e}")
        return jsonify({'error': 'Failed to fetch pesticides data'}), 500

# ---------------------------------------------------------
# 7. API Route: Serve Health Facilities (HOTOSM Points)
# ---------------------------------------------------------
@main_bp.route('/api/health_facilities', methods=['GET'])
def get_health_facilities():
    bbox = request.args.get('bbox')
    facility_type = request.args.get('type')  # optional filter e.g. hospital, pharmacy

    if not bbox:
        return jsonify({'error': 'Missing bbox parameter'}), 400

    try:
        w, s, e, n = map(float, bbox.split(','))

        filters = "ST_Intersects(geometry, ST_MakeEnvelope(:w, :s, :e, :n, 4326))"
        params = {'w': w, 's': s, 'e': e, 'n': n}

        if facility_type:
            filters += " AND facility_type = :facility_type"
            params['facility_type'] = facility_type

        sql_query = text(f"""
            SELECT jsonb_build_object(
                'type', 'FeatureCollection',
                'features', COALESCE(jsonb_agg(features.feature), '[]'::jsonb)
            ) AS geojson
            FROM (
                SELECT jsonb_build_object(
                    'type', 'Feature',
                    'properties', jsonb_build_object(
                        'name', name,
                        'facility_type', facility_type,
                        'healthcare', healthcare,
                        'amenity', amenity,
                        'operator_type', operator_type,
                        'addr_city', addr_city,
                        'addr_full', addr_full
                    ),
                    'geometry', ST_AsGeoJSON(geometry)::jsonb
                ) AS feature
                FROM health_facilities
                WHERE {filters}
                LIMIT 5000
            ) features;
        """)
        result = db.session.execute(sql_query, params).scalar()
        return jsonify(json.loads(result) if isinstance(result, str) else result)
    except Exception as e:
        logger.error(f"Health Facilities Query Error: {e}")
        return jsonify({'error': 'Failed to fetch health facilities data'}), 500
# ---------------------------------------------------------
# 8. API Route: Serve Schools (Education Points)
# ---------------------------------------------------------
@main_bp.route('/api/schools', methods=['GET'])
def get_schools():
    bbox = request.args.get('bbox')
    onderwijstype = request.args.get('type')

    if not bbox:
        return jsonify({'error': 'Missing bbox parameter'}), 400

    try:
        w, s, e, n = map(float, bbox.split(','))

        filters = "ST_Intersects(geometry, ST_MakeEnvelope(:w, :s, :e, :n, 4326))"
        params = {'w': w, 's': s, 'e': e, 'n': n}

        if onderwijstype:
            filters += " AND onderwijstype = :onderwijstype"
            params['onderwijstype'] = onderwijstype

        sql_query = text(f"""
            SELECT jsonb_build_object(
                'type', 'FeatureCollection',
                'features', COALESCE(jsonb_agg(features.feature), '[]'::jsonb)
            ) AS geojson
            FROM (
                SELECT jsonb_build_object(
                    'type', 'Feature',
                    'properties', jsonb_build_object(
                        'instellingsnaam', instellingsnaam,
                        'onderwijstype', onderwijstype,
                        'straatnaam', straatnaam,
                        'huisnummer_toevoeging', "huisnummer-toevoeging",
                        'postcode', postcode,
                        'plaatsnaam', plaatsnaam,
                        'provincie', provincie,
                        'gemeentenummer', gemeentenummer,
                        'gemeentenaam', gemeentenaam,
                        'telefoonnummer', telefoonnummer
                    ),
                    'geometry', ST_AsGeoJSON(geometry)::jsonb
                ) AS feature
                FROM schools
                WHERE {filters}
                LIMIT 10000
            ) features;
        """)
        result = db.session.execute(sql_query, params).scalar()
        return jsonify(json.loads(result) if isinstance(result, str) else result)
    except Exception as e:
        logger.error(f"Schools Query Error: {e}")
        return jsonify({'error': 'Failed to fetch schools data'}), 500
    
# ---------------------------------------------------------
# API Route: Serve Waterschappen (Water Authority Borders)
# ---------------------------------------------------------
@main_bp.route('/api/waterschappen', methods=['GET'])
def get_waterschappen():
    bbox = request.args.get('bbox')
    if not bbox:
        return jsonify({'error': 'Missing bbox parameter'}), 400

    try:
        w, s, e, n = map(float, bbox.split(','))

        sql_query = text("""
            SELECT jsonb_build_object(
                'type', 'FeatureCollection',
                'features', COALESCE(jsonb_agg(features.feature), '[]'::jsonb)
            ) AS geojson
            FROM (
                SELECT jsonb_build_object(
                    'type', 'Feature',
                    'properties', jsonb_build_object(
                        'code', code,
                        'naam', naam
                    ),
                    'geometry', ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom, 0.0005))::jsonb
                ) AS feature
                FROM waterschappen
                WHERE ST_Intersects(geom, ST_MakeEnvelope(:w, :s, :e, :n, 4326))
            ) features;
        """)
        result = db.session.execute(sql_query, {'w': w, 's': s, 'e': e, 'n': n}).scalar()

        return jsonify(json.loads(result) if isinstance(result, str) else result)

    except Exception as e:
        logger.error(f"Waterschappen Query Error: {e}")
        return jsonify({'error': 'Failed to fetch Waterschappen data', 'details': str(e)}), 500

# ---------------------------------------------------------
# 9. API Route: Dynamic Year Availability Scanner
# ---------------------------------------------------------
@main_bp.route('/api/available_years', methods=['GET'])
def get_available_years():
    """
    Dynamically interrogates the PostGIS database to find which exact years 
    are available for each temporal dataset. Static datasets return empty lists.
    """
    # Mapping frontend layer IDs to their respective table and temporal column
    layer_configs = {
        'brp':            {'table': 'brp_parcels',              'column': 'year'},
        'bag':            {'table': 'bag_buildings',             'column': 'oorspronkelijkbouwjaar'},
        'pesticides':     {'table': 'pesticides_measurements',   'column': 'jaar'},
        'kadastralekaart':{'table': 'kadastralekaart_perceel',   'column': None},  # Static
        'natura2000':     {'table': 'natura2000_areas',          'column': None},  # Static
    }
    
    available_years = {}
    
    for layer_id, config in layer_configs.items():
        if config['column'] is None:
            # Static layer: no year selection required
            available_years[layer_id] = []
            continue
            
        try:
            sql_query = text(f"""
                SELECT DISTINCT {config['column']}
                FROM {config['table']}
                WHERE {config['column']} IS NOT NULL
                ORDER BY {config['column']} DESC;
            """)
            result = db.session.execute(sql_query).fetchall()
            
            # Extract the years into a clean list
            years = [row[0] for row in result]
            available_years[layer_id] = years
            
        except Exception as e:
            # Table might not exist yet, or column is missing.
            # Roll back so a failed query doesn't poison the shared session
            # and cause all subsequent layers to fail with InFailedSqlTransaction.
            db.session.rollback()
            logger.warning(f"Could not fetch years for {layer_id}: {e}")
            available_years[layer_id] = []
            
    return jsonify(available_years)

# ---------------------------------------------------------
# 9. API Route: Multi-layer Excel Export
# BRP: raw rows + pivot summary sheet.
# Pesticides: full table (not bbox-filtered).
# All other layers: filtered by current map bbox.
# ---------------------------------------------------------
@main_bp.route('/api/export_excel', methods=['POST'])
def export_excel():
    body = request.get_json()
    bbox_str = body.get('bbox', '3.3,50.75,7.22,53.7')
    active_layers = body.get('layers', [])
    requested_merges = body.get('merges', [])
    buffer_geom_json = body.get('buffer_geom')

    try:
        w, s, e, n = map(float, bbox_str.split(','))
    except Exception:
        return jsonify({'error': 'Invalid bbox'}), 400

    if buffer_geom_json:
        geom_expr = "ST_SetSRID(ST_GeomFromGeoJSON(:buffer_geom), 4326)"
        geo_params = {'buffer_geom': buffer_geom_json}
    else:
        geom_expr = "ST_MakeEnvelope(:w,:s,:e,:n,4326)"
        geo_params = {'w': w, 's': s, 'e': e, 'n': n}

    layer_queries = {
        'BRP Parcels': f"""
            SELECT
                year                                                        AS "Year",
                gewas                                                       AS "Crop Type",
                gewascode                                                   AS "Crop Code",
                ROUND((ST_Area(geometry::geography) / 10000)::numeric, 4)  AS "Area (ha)"
            FROM brp_parcels
            WHERE ST_Intersects(geometry, {geom_expr})
            LIMIT 10000
        """,
        'BAG Buildings': f"""
            SELECT
                identificatie           AS "Building ID",
                oorspronkelijkbouwjaar  AS "Construction Year",
                status                  AS "Status"
            FROM bag_buildings
            WHERE ST_Intersects(geometry, {geom_expr})
            LIMIT 10000
        """,
        'Natura 2000': f"""
            SELECT naam_n2k AS "Area Name"
            FROM natura2000_areas
            WHERE ST_Intersects(ST_Transform(geometry, 4326), {geom_expr})
        """,
        'Bestuurlijke Grenzen': f"""
            SELECT
                code          AS "Code",
                gemeentenaam  AS "Name",
                layer_type    AS "Boundary Type"
            FROM grenzen
            WHERE ST_Intersects(geom, {geom_expr})
        """,
        # "beëndigd" uses the exact column name as stored in the DB.
        # The KRD CSV export encodes ë as \xeb (Latin-1), and the 'i' in 'beëindigd' is
        # missing — the actual column is 'beëndigd' (8 chars), not 'beëindigd' (9 chars).
        'KRD Veehouderijen': f"""
            SELECT
                adres                           AS "Adres",
                gemeente                        AS "Gemeente",
                provincie                       AS "Provincie",
                bedrijfstype                    AS "Diersoort / Bedrijfstype",
                "aantal stallen"                AS "Aantal stallen",
                "nh3 emissie (kg/j)"            AS "NH3 Emissie (kg/j)",
                "geur emissie (oue/s)"          AS "Geur Emissie (ouE/s)",
                "fijnstof emissie (g/j)"        AS "Fijnstof Emissie (g/j)",
                "beëndigd"                      AS "Beëindigd (Ja = vergunning beëindigd)",
                besluitdatum                    AS "Datum besluit",
                ippc                            AS "IPPC-installatie",
                zaaktype                        AS "Zaaktype",
                bronhouder                      AS "Bronhouder (omgevingsdienst)"
            FROM krd_farms
            WHERE ST_Intersects(geometry, {geom_expr})
              AND (bedrijfstype IS NULL OR bedrijfstype != 'voormalig bedrijf')
            LIMIT 10000
        """,
        'Health Facilities': f"""
            SELECT
                name            AS "Name",
                facility_type   AS "Type",
                addr_city       AS "City",
                operator_type   AS "Operator"
            FROM health_facilities
            WHERE ST_Intersects(geometry, {geom_expr})
            LIMIT 10000
        """,
        'Schools': f"""
            SELECT
                instellingsnaam AS "School Name",
                onderwijstype   AS "Type",
                straatnaam      AS "Street",
                plaatsnaam      AS "City",
                provincie       AS "Province"
            FROM schools
            WHERE ST_Intersects(geometry, {geom_expr})
            LIMIT 10000
        """,
        'Water Hydrography': f"""
            SELECT *
            FROM hydrography_watercourse
            WHERE ST_Intersects(geometry, {geom_expr})
            LIMIT 5000
        """,
        'Nature Network NL': f"""
            SELECT *
            FROM nnn_areas
            WHERE ST_Intersects(geometry, {geom_expr})
            LIMIT 5000
        """,
        'WFD Surface Water': f"""
            SELECT *
            FROM wfd_surface_water
            WHERE ST_Intersects(geometry, {geom_expr})
            LIMIT 2000
        """,
        'Kadastrale Kaart': f"""
            SELECT
                identificatie           AS "Parcel ID",
                gemeente_code           AS "Municipality Code",
                gemeente                AS "Municipality",
                sectie                  AS "Section",
                perceelnummer           AS "Parcel Number",
                kadastralegrootte       AS "Area (m2)",
                soortgrootte            AS "Area Type",
                status                  AS "Status"
            FROM kadastralekaart_perceel
            WHERE ST_Intersects(geometry, {geom_expr})
            LIMIT 5000
        """,
        'Waterschappen': f"""
            SELECT
                code AS "Code",
                naam AS "Naam"
            FROM waterschappen
            WHERE ST_Intersects(geom, {geom_expr})
        """,
    }

    brp_pivot_query = f"""
        SELECT
            gewas                                                               AS "Crop Type",
            gewascode                                                           AS "Crop Code",
            COUNT(*)                                                            AS "Parcel Count",
            ROUND(SUM(ST_Area(geometry::geography) / 10000)::numeric, 2)       AS "Total Area (ha)"
        FROM brp_parcels
        WHERE ST_Intersects(geometry, {geom_expr})
        GROUP BY gewas, gewascode
        ORDER BY "Total Area (ha)" DESC
    """

    pesticides_query = text("""
        SELECT
            stof_naam_sam           AS "Substance",
            jaar                    AS "Year",
            norm_omschrijving       AS "Norm Type",
            normklas                AS "Norm Class",
            klasse_omschrijving     AS "Result",
            mate_normov             AS "Exceedance Ratio",
            meetpunt_code           AS "Station Code",
            wbhcode_omschrijving    AS "Water Board"
        FROM pesticides_measurements
        ORDER BY jaar DESC, stof_naam_sam
    """)

    # Columns that contain PostGIS geometry and must never appear in Excel
    GEOM_COLS = {'geom', 'geometry', 'wkb_geometry', 'the_geom', 'shape'}

    SOURCE_URLS = {
        'BRP Parcels':          'https://www.pdok.nl/introductie/-/article/basisregistratie-gewaspercelen-brp-',
        'BRP Summary':          'https://www.pdok.nl/introductie/-/article/basisregistratie-gewaspercelen-brp-',
        'BAG Buildings':        'https://www.pdok.nl/introductie/-/article/basisregistratie-adressen-en-gebouwen-ba-1',
        'Natura 2000':          'https://www.pdok.nl/introductie/-/article/natura-2000',
        'Nature Network NL':    'https://www.nationaalgeoregister.nl/geonetwork/srv/dut/catalog.search#/metadata/c7d8d77b-8c47-4309-8c58-9b12b086407f',
        'Kadastrale Kaart':     'https://www.nationaalgeoregister.nl/geonetwork/srv/dut/catalog.search#/metadata/a29917b9-3426-4041-a11b-69bcb2256904',
        'KRD Veehouderijen':    'https://krd.igoview.nl/',
        'Pesticides Atlas':     'https://www.bestrijdingsmiddelenatlas.nl/atlas/1/1',
        'Health Facilities':    'https://data.humdata.org/dataset/hotosm_nld_health_facilities',
        'Schools':              'https://duo.nl/open_onderwijsdata/',
        'Bestuurlijke Grenzen': 'https://www.pdok.nl/introductie/-/article/bestuurlijke-grenzen',
        'Water Hydrography':    'https://www.pdok.nl/introductie/-/article/waterschappen-hydrografie-inspire-geharmoniseerd-',
        'WFD Surface Water':    'https://www.pdok.nl/introductie/-/article/krw-oppervlaktewaterlichamen-inspire-geharmoniseerd-',
        'Waterschappen':        'https://www.pdok.nl/introductie/-/article/waterschappen-waterschapsgrenzen-imso',
        'Kadastral-Natura2000': 'https://www.nationaalgeoregister.nl/geonetwork/srv/dut/catalog.search#/metadata/a29917b9-3426-4041-a11b-69bcb2256904',
        'KRD-Natura2000':       'https://krd.igoview.nl/ × https://www.pdok.nl/introductie/-/article/natura-2000',
        'BRP-Natura2000':       'https://www.pdok.nl/introductie/-/article/basisregistratie-gewaspercelen-brp- × https://www.pdok.nl/introductie/-/article/natura-2000',
        'KRD-NNN':              'https://krd.igoview.nl/ × https://service.pdok.nl/provincies/natuurnetwerk-nederland/atom/index.xml',
        'BRP-Pesticides':       'https://www.pdok.nl/introductie/-/article/basisregistratie-gewaspercelen-brp- × https://www.bestrijdingsmiddelenatlas.nl/atlas/1/1',
    }

    DATASET_DATES = {
        'BRP Parcels':          'Annual update — RVO / PDOK (2009–2025 available)',
        'BAG Buildings':        'Continuously updated — Kadaster / PDOK BAG',
        'Natura 2000':          'Periodically updated — Ministerie van LNV / PDOK',
        'Nature Network NL':    'Periodically updated per province — PDOK INSPIRE',
        'Kadastrale Kaart':     'Continuously updated — Kadaster / PDOK BRK',
        'KRD Veehouderijen':    'As published on krd.igoview.nl (Gelderland/Twente, Limburg, Noord-Brabant)',
        'Pesticides Atlas':     '2022 annual figures — Bestrijdingsmiddelenatlas',
        'Health Facilities':    'Continuously updated — HOTOSM / OpenStreetMap Netherlands',
        'Schools':              '2024 — DUO (Dienst Uitvoering Onderwijs)',
        'Bestuurlijke Grenzen': 'Periodically updated — PDOK Bestuurlijke Grenzen',
        'Water Hydrography':    'Periodically updated — Waterschappen / PDOK INSPIRE',
        'WFD Surface Water':    'Per WFD reporting cycle (6 years) — Rijkswaterstaat / PDOK',
        'Waterschappen':        'Periodically updated — Unie van Waterschappen / PDOK',
        'Kadastral-Natura2000': 'Derived join — Kadaster BRK × Natura 2000 (LNV)',
        'KRD-Natura2000':       'Derived join — KRD × Natura 2000, farms within 10 km',
        'BRP-Natura2000':       'Derived join — BRP × Natura 2000, parcels within 5 km',
        'KRD-NNN':              'Derived join — KRD × NNN, farms within 5 km',
        'BRP-Pesticides':       'Derived join — BRP × Pesticides, parcels within 2 km of stations',
    }

    export_date = pd.Timestamp.now().strftime("%Y-%m-%d")
    export_ts   = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S UTC")

    def write_sheet(writer, df, sheet_name, source_url, data_date=''):
        from openpyxl.styles import Font, PatternFill, Alignment
        df.to_excel(writer, index=False, sheet_name=sheet_name, startrow=5)
        ws = writer.sheets[sheet_name]
        # Row 1: dataset label
        ws['A1'] = sheet_name
        ws['A1'].font = Font(bold=True, size=11)
        # Row 2: source URL
        ws['A2'] = f'Source:      {source_url}'
        ws['A2'].font = Font(size=9, color='1155CC')
        # Row 3: data publication date
        ws['A3'] = f'Data date:   {data_date}'
        ws['A3'].font = Font(italic=True, size=9, color='555555')
        # Row 4: export timestamp
        ws['A4'] = f'Exported on: {export_ts}'
        ws['A4'].font = Font(italic=True, size=9, color='555555')
        # Row 5: blank separator (data header lands on row 6)
        ws.row_dimensions[5].height = 6
        # Widen column A so URLs don't truncate
        ws.column_dimensions['A'].width = max(
            72,
            ws.column_dimensions['A'].width if ws.column_dimensions['A'].width else 0
        )

    def _run(conn, stmt):
        """Execute a SQLAlchemy statement and return a DataFrame.

        Uses result.mappings() so pandas receives plain dicts — avoids the
        ResourceClosedError that occurs when result.keys() is called after
        fetchall() exhausts the cursor in SQLAlchemy 2.x.
        """
        result = conn.execute(stmt)
        rows = result.mappings().all()
        return pd.DataFrame(rows)

    buf = io.BytesIO()
    try:
        with pd.ExcelWriter(buf, engine='openpyxl') as writer:
            with db.engine.connect() as conn:
                for layer_name in active_layers:
                    if layer_name == 'Pesticides Atlas':
                        df = _run(conn, pesticides_query)
                    elif layer_name in layer_queries:
                        df = _run(conn,
                                  text(layer_queries[layer_name]).bindparams(**geo_params))
                    else:
                        continue

                    # Drop any geometry columns that slipped through
                    df = df.drop(columns=[c for c in df.columns if c.lower() in GEOM_COLS],
                                 errors='ignore')

                    if not df.empty:
                        write_sheet(writer, df, layer_name[:31],
                                    SOURCE_URLS.get(layer_name, ''),
                                    DATASET_DATES.get(layer_name, ''))

                    # BRP: add a pivot/summary sheet right after the raw data sheet
                    if layer_name == 'BRP Parcels':
                        pivot_df = _run(conn,
                                        text(brp_pivot_query).bindparams(**geo_params))
                        if not pivot_df.empty:
                            write_sheet(writer, pivot_df, 'BRP Summary',
                                        SOURCE_URLS['BRP Summary'],
                                        DATASET_DATES.get('BRP Parcels', ''))

                # Cross-dataset merge sheets — only run the ones the user selected
                MERGE_SQL = {
                    'Kadastral-Natura2000': f"""
                        SELECT
                            k.identificatie       AS "Parcel ID",
                            k.gemeente            AS "Municipality",
                            k.sectie              AS "Section",
                            k.perceelnummer       AS "Parcel Number",
                            k.kadastralegrootte   AS "Cadastral Area (m2)",
                            k.status              AS "Status",
                            n.naam_n2k            AS "Natura 2000 Area",
                            ROUND((ST_Distance(k.geometry::geography,
                                ST_Transform(n.geometry, 4326)::geography) / 1000)::numeric, 3)
                                                  AS "Distance to N2000 (km)",
                            CASE WHEN ST_Intersects(k.geometry, ST_Transform(n.geometry, 4326))
                                 THEN 'Yes' ELSE 'No' END AS "Within N2000"
                        FROM kadastralekaart_perceel k
                        JOIN natura2000_areas n
                            ON ST_DWithin(k.geometry::geography,
                               ST_Transform(n.geometry, 4326)::geography, 1000)
                        WHERE ST_Intersects(k.geometry, {geom_expr})
                        ORDER BY "Distance to N2000 (km)"
                        LIMIT 5000
                    """,
                    'KRD-Natura2000': f"""
                        SELECT
                            k.adres                    AS "Farm Address",
                            k.gemeente                 AS "Gemeente",
                            k.provincie                AS "Provincie",
                            k.bedrijfstype             AS "Farm Type",
                            k."nh3 emissie (kg/j)"     AS "NH3 Emission (kg/j)",
                            k."geur emissie (oue/s)"   AS "Odour Emission (ouE/s)",
                            n.naam_n2k                 AS "Natura 2000 Area",
                            ROUND((ST_Distance(k.geometry::geography,
                                ST_Transform(n.geometry, 4326)::geography) / 1000)::numeric, 3)
                                                       AS "Distance to N2000 (km)",
                            CASE WHEN ST_Intersects(k.geometry, ST_Transform(n.geometry, 4326))
                                 THEN 'Yes' ELSE 'No' END AS "Farm Within N2000"
                        FROM krd_farms k
                        JOIN natura2000_areas n
                            ON ST_DWithin(k.geometry::geography, ST_Transform(n.geometry, 4326)::geography, 10000)
                        WHERE ST_Intersects(k.geometry, {geom_expr})
                          AND (k.bedrijfstype IS NULL OR k.bedrijfstype != 'voormalig bedrijf')
                        ORDER BY "Distance to N2000 (km)", k.adres
                        LIMIT 5000
                    """,
                    'BRP-Natura2000': f"""
                        SELECT
                            b.year                     AS "Year",
                            b.gewas                    AS "Crop",
                            b.gewascode                AS "Crop Code",
                            ROUND((ST_Area(b.geometry::geography) / 10000)::numeric, 2)
                                                       AS "Area (ha)",
                            n.naam_n2k                 AS "Natura 2000 Area",
                            ROUND((ST_Distance(b.geometry::geography,
                                ST_Transform(n.geometry, 4326)::geography) / 1000)::numeric, 3)
                                                       AS "Distance to N2000 (km)",
                            CASE WHEN ST_Intersects(b.geometry, ST_Transform(n.geometry, 4326))
                                 THEN 'Yes' ELSE 'No' END AS "Parcel Within N2000"
                        FROM brp_parcels b
                        JOIN natura2000_areas n
                            ON ST_DWithin(b.geometry::geography, ST_Transform(n.geometry, 4326)::geography, 5000)
                        WHERE ST_Intersects(b.geometry, {geom_expr})
                        ORDER BY "Distance to N2000 (km)", b.gewas
                        LIMIT 5000
                    """,
                    'KRD-NNN': f"""
                        SELECT
                            k.adres                    AS "Farm Address",
                            k.gemeente                 AS "Gemeente",
                            k.bedrijfstype             AS "Farm Type",
                            k."nh3 emissie (kg/j)"     AS "NH3 Emission (kg/j)",
                            COALESCE(a.name, a.naam, a.inspireid, '—') AS "NNN Area",
                            ROUND((ST_Distance(k.geometry::geography,
                                a.geometry::geography) / 1000)::numeric, 3)
                                                       AS "Distance to NNN (km)",
                            CASE WHEN ST_Intersects(k.geometry, a.geometry)
                                 THEN 'Yes' ELSE 'No' END AS "Farm Within NNN"
                        FROM krd_farms k
                        JOIN nnn_areas a
                            ON ST_DWithin(k.geometry::geography, a.geometry::geography, 5000)
                        WHERE ST_Intersects(k.geometry, {geom_expr})
                          AND (k.bedrijfstype IS NULL OR k.bedrijfstype != 'voormalig bedrijf')
                        ORDER BY "Distance to NNN (km)", k.adres
                        LIMIT 5000
                    """,
                    'BRP-Pesticides': f"""
                        SELECT
                            p.meetpunt_code            AS "Station Code",
                            p.wbhcode_omschrijving     AS "Water Board",
                            p.jaar                     AS "Measurement Year",
                            p.worst_substance          AS "Worst Substance",
                            ROUND(p.worst_exceedance::numeric, 2) AS "Exceedance Ratio",
                            b.year                     AS "BRP Year",
                            b.gewas                    AS "Nearby Crop",
                            b.gewascode                AS "Crop Code",
                            ROUND((ST_Area(b.geometry::geography) / 10000)::numeric, 2)
                                                       AS "Parcel Area (ha)",
                            ROUND((ST_Distance(p.geometry::geography,
                                b.geometry::geography) / 1000)::numeric, 3)
                                                       AS "Distance (km)"
                        FROM (
                            SELECT meetpunt_code, wbhcode_omschrijving, jaar, geometry,
                                MAX(mate_normov) AS worst_exceedance,
                                (ARRAY_AGG(stof_naam_sam ORDER BY mate_normov DESC NULLS LAST))[1]
                                    AS worst_substance
                            FROM pesticides_measurements
                            WHERE ST_Intersects(geometry, {geom_expr})
                            GROUP BY meetpunt_code, wbhcode_omschrijving, jaar, geometry
                        ) p
                        JOIN brp_parcels b
                            ON ST_DWithin(p.geometry::geography, b.geometry::geography, 2000)
                           AND ST_Intersects(b.geometry, {geom_expr})
                        ORDER BY p.worst_exceedance DESC NULLS LAST, "Distance (km)"
                        LIMIT 5000
                    """,
                }

                for merge_id in requested_merges:
                    if merge_id not in MERGE_SQL:
                        continue
                    mdf = _run(conn, text(MERGE_SQL[merge_id]).bindparams(**geo_params))
                    mdf = mdf.drop(columns=[c for c in mdf.columns if c.lower() in GEOM_COLS],
                                   errors='ignore')
                    if not mdf.empty:
                        write_sheet(writer, mdf, merge_id,
                                    SOURCE_URLS.get(merge_id, ''),
                                    DATASET_DATES.get(merge_id, ''))

            # Always append a Data Sources sheet listing provenance for every active layer
            all_sheet_names = (
                list(active_layers)
                + (['BRP Summary'] if 'BRP Parcels' in active_layers else [])
                + [m for m in requested_merges if m in MERGE_SQL]
            )
            sources_rows = [
                {
                    'Dataset':            ln,
                    'Source URL':         SOURCE_URLS.get(ln, ''),
                    'Data publication':   DATASET_DATES.get(ln, ''),
                    'Export timestamp':   export_ts,
                }
                for ln in all_sheet_names
                if SOURCE_URLS.get(ln)
            ]
            if sources_rows:
                from openpyxl.styles import Font, PatternFill
                src_df = pd.DataFrame(sources_rows)
                src_df.to_excel(writer, index=False, sheet_name='Data Sources', startrow=2)
                ws_src = writer.sheets['Data Sources']
                ws_src['A1'] = f'Data Sources — exported {export_ts}'
                ws_src['A1'].font = Font(bold=True, size=11)
                ws_src.column_dimensions['A'].width = 26
                ws_src.column_dimensions['B'].width = 80
                ws_src.column_dimensions['C'].width = 52
                ws_src.column_dimensions['D'].width = 22
                # Style URL cells blue so they read as links
                for row in ws_src.iter_rows(min_row=4, max_col=2):
                    cell = row[1]
                    if cell.value and str(cell.value).startswith('http'):
                        cell.font = Font(color='1155CC', size=9)

        buf.seek(0)
        return send_file(
            buf,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=f'Environmental_Evidence_{pd.Timestamp.now().strftime("%Y-%m-%d_%H%M")}.xlsx'
        )
    except Exception as e:
        logger.error(f"Excel Export Error: {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500


# ---------------------------------------------------------
# 10. API Route: Serve Nature Network Netherlands — Areas, Buffers, and Centers
# ---------------------------------------------------------
@main_bp.route('/api/nnn', methods=['GET'])
def get_nnn():
    """
    Returns NNN area polygons as plain GeoJSON features.
    Buffer zones and center pins are generated client-side via turf.js
    (same pipeline as Natura 2000) so the visual output is identical.
    Geometry simplification is applied based on bbox width for performance.
    """
    bbox = request.args.get('bbox')
    if not bbox:
        return jsonify({'error': 'Missing bbox parameter'}), 400

    try:
        w, s, e, n = map(float, bbox.split(','))

        bbox_width = e - w
        if bbox_width > 2:
            tolerance = 0.001   # nationwide — coarse simplification
        elif bbox_width > 0.5:
            tolerance = 0.0002  # regional
        else:
            tolerance = 0       # local — full detail

        sql_query = text("""
            SELECT jsonb_build_object(
                'type', 'FeatureCollection',
                'features', COALESCE(jsonb_agg(features.feature), '[]'::jsonb)
            ) AS geojson
            FROM (
                SELECT jsonb_build_object(
                    'type', 'Feature',
                    'properties', row_to_json(a)::jsonb - 'geometry' - 'id',
                    'geometry', ST_AsGeoJSON(
                        CASE WHEN :tolerance > 0
                            THEN ST_SimplifyPreserveTopology(geometry, :tolerance)
                            ELSE geometry
                        END
                    )::jsonb
                ) AS feature
                FROM nnn_areas a
                WHERE ST_Intersects(geometry, ST_MakeEnvelope(:w, :s, :e, :n, 4326))
                LIMIT 1000
            ) features;
        """)
        result = db.session.execute(sql_query, {
            'w': w, 's': s, 'e': e, 'n': n,
            'tolerance': tolerance
        }).scalar()

        return jsonify(json.loads(result) if isinstance(result, str) else result)
    except Exception as e:
        logger.error(f"NNN Query Error: {e}")
        return jsonify({'error': 'Failed to fetch NNN data'}), 500


# ---------------------------------------------------------
# 11. API Route: Serve Water Hydrography (INSPIRE harmonized)
# ---------------------------------------------------------
@main_bp.route('/api/hydrography', methods=['GET'])
def get_hydrography():
    """Combined fallback — all types, limit 8000. Used when split endpoints fail."""
    bbox = request.args.get('bbox')
    if not bbox:
        return jsonify({'error': 'Missing bbox parameter'}), 400

    try:
        w, s, e, n = map(float, bbox.split(','))
        sql_query = text("""
            SELECT jsonb_build_object(
                'type', 'FeatureCollection',
                'features', COALESCE(jsonb_agg(features.feature), '[]'::jsonb)
            ) AS geojson
            FROM (
                SELECT jsonb_build_object(
                    'type', 'Feature',
                    'properties', row_to_json(h)::jsonb - 'geometry' - 'id',
                    'geometry', ST_AsGeoJSON(geometry)::jsonb
                ) AS feature
                FROM hydrography_watercourse h
                WHERE ST_Intersects(geometry, ST_MakeEnvelope(:w, :s, :e, :n, 4326))
                LIMIT 8000
            ) features;
        """)
        result = db.session.execute(sql_query, {'w': w, 's': s, 'e': e, 'n': n}).scalar()
        return jsonify(json.loads(result) if isinstance(result, str) else result)
    except Exception as e:
        logger.error(f"Hydrography Query Error: {e}")
        return jsonify({'error': 'Failed to fetch hydrography data'}), 500


@main_bp.route('/api/hydrography_main', methods=['GET'])
def get_hydrography_main():
    """Main channels only — no row limit (~15k features nationwide)."""
    bbox = request.args.get('bbox')
    if not bbox:
        return jsonify({'error': 'Missing bbox parameter'}), 400

    try:
        w, s, e, n = map(float, bbox.split(','))
        sql_query = text("""
            SELECT jsonb_build_object(
                'type', 'FeatureCollection',
                'features', COALESCE(jsonb_agg(features.feature), '[]'::jsonb)
            ) AS geojson
            FROM (
                SELECT jsonb_build_object(
                    'type', 'Feature',
                    'properties', row_to_json(h)::jsonb - 'geometry' - 'id',
                    'geometry', ST_AsGeoJSON(geometry)::jsonb
                ) AS feature
                FROM hydrography_watercourse h
                WHERE ST_Intersects(geometry, ST_MakeEnvelope(:w, :s, :e, :n, 4326))
                  AND localtype IN (
                      'rivier', 'kanaal', 'gracht',
                      'primair boezemwater', 'secundair boezemwater'
                  )
            ) features;
        """)
        result = db.session.execute(sql_query, {'w': w, 's': s, 'e': e, 'n': n}).scalar()
        return jsonify(json.loads(result) if isinstance(result, str) else result)
    except Exception as e:
        logger.error(f"Hydrography Main Query Error: {e}")
        return jsonify({'error': 'Failed to fetch main channel data'}), 500


@main_bp.route('/api/hydrography_other', methods=['GET'])
def get_hydrography_other():
    """All types except main channels — limit 8000."""
    bbox = request.args.get('bbox')
    if not bbox:
        return jsonify({'error': 'Missing bbox parameter'}), 400

    try:
        w, s, e, n = map(float, bbox.split(','))
        sql_query = text("""
            SELECT jsonb_build_object(
                'type', 'FeatureCollection',
                'features', COALESCE(jsonb_agg(features.feature), '[]'::jsonb)
            ) AS geojson
            FROM (
                SELECT jsonb_build_object(
                    'type', 'Feature',
                    'properties', row_to_json(h)::jsonb - 'geometry' - 'id',
                    'geometry', ST_AsGeoJSON(geometry)::jsonb
                ) AS feature
                FROM hydrography_watercourse h
                WHERE ST_Intersects(geometry, ST_MakeEnvelope(:w, :s, :e, :n, 4326))
                  AND (localtype IS NULL OR localtype NOT IN (
                      'rivier', 'kanaal', 'gracht',
                      'primair boezemwater', 'secundair boezemwater'
                  ))
                LIMIT 8000
            ) features;
        """)
        result = db.session.execute(sql_query, {'w': w, 's': s, 'e': e, 'n': n}).scalar()
        return jsonify(json.loads(result) if isinstance(result, str) else result)
    except Exception as e:
        logger.error(f"Hydrography Other Query Error: {e}")
        return jsonify({'error': 'Failed to fetch hydrography data'}), 500


# ---------------------------------------------------------
# 11. API Route: Serve WFD Surface Water Bodies (INSPIRE harmonised)
# ---------------------------------------------------------
@main_bp.route('/api/wfd_surface_water', methods=['GET'])
def get_wfd_surface_water():
    bbox = request.args.get('bbox')
    if not bbox:
        return jsonify({'error': 'Missing bbox parameter'}), 400

    try:
        w, s, e, n = map(float, bbox.split(','))
        sql_query = text("""
            SELECT jsonb_build_object(
                'type', 'FeatureCollection',
                'features', COALESCE(jsonb_agg(features.feature), '[]'::jsonb)
            ) AS geojson
            FROM (
                SELECT jsonb_build_object(
                    'type', 'Feature',
                    'properties', row_to_json(w)::jsonb - 'geometry' - 'id',
                    'geometry', ST_AsGeoJSON(geometry)::jsonb
                ) AS feature
                FROM wfd_surface_water w
                WHERE ST_Intersects(geometry, ST_MakeEnvelope(:w, :s, :e, :n, 4326))
                LIMIT 5000
            ) features;
        """)
        result = db.session.execute(sql_query, {'w': w, 's': s, 'e': e, 'n': n}).scalar()
        return jsonify(json.loads(result) if isinstance(result, str) else result)
    except Exception as e:
        logger.error(f"WFD Surface Water Query Error: {e}")
        return jsonify({'type': 'FeatureCollection', 'features': []})


# ---------------------------------------------------------
# Kadastrale Kaart (Cadastral Parcels)
# Source: Kadaster / PDOK — BRK Kadastrale Kaart
# OGC API: https://api.pdok.nl/kadaster/brk-kadastrale-kaart/ogc/v1
# ---------------------------------------------------------
@main_bp.route('/api/kadastralekaart', methods=['GET'])
def get_kadastralekaart():
    bbox = request.args.get('bbox')
    if not bbox:
        return jsonify({'error': 'Missing bbox parameter'}), 400

    try:
        w, s, e, n = map(float, bbox.split(','))
        sql_query = text("""
            SELECT jsonb_build_object(
                'type', 'FeatureCollection',
                'features', COALESCE(jsonb_agg(features.feature), '[]'::jsonb)
            ) AS geojson
            FROM (
                SELECT jsonb_build_object(
                    'type', 'Feature',
                    'properties', jsonb_build_object(
                        'identificatie',    identificatie,
                        'gemeente',         gemeente,
                        'gemeente_code',    gemeente_code,
                        'sectie',           sectie,
                        'perceelnummer',    perceelnummer,
                        'kadastralegrootte', kadastralegrootte,
                        'soortgrootte',     soortgrootte,
                        'status',           status
                    ),
                    'geometry', ST_AsGeoJSON(geometry)::jsonb
                ) AS feature
                FROM kadastralekaart_perceel
                WHERE ST_Intersects(geometry, ST_MakeEnvelope(:w, :s, :e, :n, 4326))
                LIMIT 2000
            ) features;
        """)
        result = db.session.execute(sql_query, {'w': w, 's': s, 'e': e, 'n': n}).scalar()
        return jsonify(json.loads(result) if isinstance(result, str) else result)
    except Exception as e:
        logger.error(f"Kadastralekaart Query Error: {e}")
        return jsonify({'error': 'Failed to fetch Kadastralekaart data'}), 500
