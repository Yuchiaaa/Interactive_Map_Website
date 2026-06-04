# app/routes.py
import io
import json
import logging
import pandas as pd
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

@main_bp.route('/map')
def index():
    """Renders the main map interface."""
    return render_template('index.html')

@main_bp.route('/ml')
def ml():
    """Renders the ML analysis placeholder page."""
    return render_template('ml.html')

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
            spatial_filter = "(SELECT geom FROM grenzen WHERE gemeentenaam = :gemeente AND layer_type = 'gemeenten' LIMIT 1)"
            params = {'year': year, 'gemeente': gemeente}
            row_limit = 5000
        else:
            spatial_filter = "ST_MakeEnvelope(:w, :s, :e, :n, 4326)"
            params = {'year': year, 'w': w, 's': s, 'e': e, 'n': n}
            row_limit = 5000

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
                  AND ST_Intersects(geometry, {spatial_filter})
                LIMIT {row_limit}
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


# ---------------------------------------------------------
# 1C. API Route: BRP Trend — year-over-year crop category totals
# Used by the Trend Analysis tab in the pivot popup to answer:
# "Is grassland increasing? Is maize expanding?"
# ---------------------------------------------------------
@main_bp.route('/api/brp_trend', methods=['GET'])
def get_brp_trend():
    try:
        years_result = db.session.execute(
            text("SELECT DISTINCT year FROM brp_parcels ORDER BY year")
        ).fetchall()
        years = [r[0] for r in years_result]

        per_year_sql = text("""
            SELECT
                ROUND(SUM(CASE
                    WHEN gewas ILIKE '%gras%' OR gewas ILIKE '%weide%'
                    THEN ST_Area(geometry::geography) / 10000 ELSE 0 END)::numeric, 1) AS grassland_ha,
                ROUND(SUM(CASE
                    WHEN gewas ILIKE '%mais%' OR gewas ILIKE '%maïs%'
                    THEN ST_Area(geometry::geography) / 10000 ELSE 0 END)::numeric, 1) AS maize_ha,
                ROUND(SUM(CASE
                    WHEN gewas ILIKE '%aardappel%'
                    THEN ST_Area(geometry::geography) / 10000 ELSE 0 END)::numeric, 1) AS potato_ha,
                ROUND(SUM(CASE
                    WHEN gewas ILIKE '%tarwe%' OR gewas ILIKE '%graan%' OR gewas ILIKE '%gerst%'
                      OR gewas ILIKE '%haver%' OR gewas ILIKE '%rogge%' OR gewas ILIKE '%triticale%'
                      OR gewas ILIKE '%spelt%' OR gewas ILIKE '%raaigras%' OR gewas ILIKE '%zwenkgras%'
                      OR gewas ILIKE '%boekweit%' OR gewas ILIKE '%soedangras%' OR gewas ILIKE '%sorghum%'
                    THEN ST_Area(geometry::geography) / 10000 ELSE 0 END)::numeric, 1) AS wheat_ha,
                ROUND(SUM(CASE
                    WHEN gewas ILIKE '%bieten%'
                    THEN ST_Area(geometry::geography) / 10000 ELSE 0 END)::numeric, 1) AS beets_ha,
                ROUND(SUM(CASE
                    WHEN gewas ILIKE '%koolzaad%' OR gewas ILIKE '%raapzaad%' OR gewas ILIKE '%vlas%'
                      OR gewas ILIKE '%hennep%' OR gewas ILIKE '%zonnebloem%' OR gewas ILIKE '%miscanthus%'
                      OR gewas ILIKE '%luzerne%' OR gewas ILIKE '%cichorei%' OR gewas ILIKE '%mosterd%'
                      OR gewas ILIKE '%groenbemester%' OR gewas ILIKE '%facelia%' OR gewas ILIKE '%tagetes%'
                      OR gewas ILIKE '%bladrammenas%' OR gewas ILIKE '%drachtplant%' OR gewas ILIKE '%soja%'
                      OR gewas ILIKE '%quinoa%' OR gewas ILIKE '%teunisbloem%' OR gewas ILIKE '%lisdodde%'
                      OR gewas ILIKE '%hop%'
                    THEN ST_Area(geometry::geography) / 10000 ELSE 0 END)::numeric, 1) AS industrial_ha,
                ROUND(SUM(CASE
                    WHEN (gewas ILIKE '%bollen%'
                      OR (gewas ILIKE '%bloem%' AND gewas NOT ILIKE '%bloemkool%'))
                      AND gewas NOT ILIKE '%zonnebloem%'
                    THEN ST_Area(geometry::geography) / 10000 ELSE 0 END)::numeric, 1) AS flowers_ha,
                ROUND(SUM(CASE
                    WHEN gewas ILIKE '%erwten%' OR gewas ILIKE '%bonen%' OR gewas ILIKE '%lupinen%'
                      OR gewas ILIKE '%klaver%' OR gewas ILIKE '%wikke%' OR gewas ILIKE '%kapucijner%'
                      OR gewas ILIKE '%esparcette%' OR gewas ILIKE '%rolklaver%'
                    THEN ST_Area(geometry::geography) / 10000 ELSE 0 END)::numeric, 1) AS legumes_ha,
                ROUND(SUM(CASE
                    WHEN gewas ILIKE '%kool%' OR gewas ILIKE '%prei%' OR gewas ILIKE '%wortel%'
                      OR gewas ILIKE '%peen%' OR gewas ILIKE '%spinazie%' OR gewas ILIKE '%selderij%'
                      OR gewas ILIKE '%schorseneer%' OR gewas ILIKE '%witlof%' OR gewas ILIKE '%broc%'
                      OR gewas ILIKE '%asperge%' OR gewas ILIKE '%pompoen%' OR gewas ILIKE '%courgette%'
                      OR gewas ILIKE '%komkommer%' OR gewas ILIKE '%andijvie%' OR gewas ILIKE '%rabarber%'
                      OR gewas ILIKE '%knoflook%' OR gewas ILIKE '%sjalot%' OR gewas ILIKE '%radijs%'
                      OR gewas ILIKE '%ui%' OR gewas ILIKE '%venkel%' OR gewas ILIKE '%kruiden%'
                      OR gewas ILIKE '%snijgroen%' OR gewas ILIKE '%valeriaan%' OR gewas ILIKE '%pastinaak%'
                      OR gewas ILIKE '%aardpeer%'
                    THEN ST_Area(geometry::geography) / 10000 ELSE 0 END)::numeric, 1) AS vegetables_ha,
                ROUND(SUM(CASE
                    WHEN gewas ILIKE '%appel%' OR gewas ILIKE '%peer%' OR gewas ILIKE '%kers%'
                      OR gewas ILIKE '%pruim%' OR gewas ILIKE '%bessen%' OR gewas ILIKE '%aardbei%'
                      OR gewas ILIKE '%framboos%' OR gewas ILIKE '%bramen%' OR gewas ILIKE '%druif%'
                      OR gewas ILIKE '%noten%' OR gewas ILIKE '%cranberry%' OR gewas ILIKE '%vruchtboom%'
                    THEN ST_Area(geometry::geography) / 10000 ELSE 0 END)::numeric, 1) AS fruit_ha,
                ROUND(SUM(CASE
                    WHEN gewas ILIKE '%laanboom%' OR gewas ILIKE '%laanbomen%' OR gewas ILIKE '%sierheesters%'
                      OR gewas ILIKE '%sierconiferen%' OR gewas ILIKE '%vaste planten%' OR gewas ILIKE '%buxus%'
                      OR gewas ILIKE '%rozenstruik%' OR gewas ILIKE '%bosplant%' OR gewas ILIKE '%haagplant%'
                      OR gewas ILIKE '%ericac%' OR gewas ILIKE '%onderstam%' OR gewas ILIKE '%kerstboom%'
                      OR gewas ILIKE '%moerboom%'
                    THEN ST_Area(geometry::geography) / 10000 ELSE 0 END)::numeric, 1) AS nursery_ha,
                ROUND(SUM(CASE
                    WHEN gewas ILIKE 'bos%' OR gewas ILIKE '%natuur%' OR gewas ILIKE '%riet%'
                      OR gewas ILIKE '%wilgenhak%' OR gewas ILIKE '%voedselbos%' OR gewas ILIKE '%woudboom%'
                      OR gewas ILIKE 'rand,%' OR gewas ILIKE 'rand %' OR gewas ILIKE '%bufferstrook%'
                      OR gewas ILIKE '%onbeteeld%' OR gewas ILIKE '%sloot%'
                    THEN ST_Area(geometry::geography) / 10000 ELSE 0 END)::numeric, 1) AS nature_ha,
                ROUND(SUM(ST_Area(geometry::geography) / 10000)::numeric, 1) AS total_ha
            FROM brp_parcels
            WHERE year = :year
        """)

        data = []
        for year in years:
            r = db.session.execute(per_year_sql, {'year': year}).fetchone()
            data.append({
                'year':          year,
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
                'other_ha':      round(float(r.total_ha) - sum([
                    float(r.grassland_ha), float(r.maize_ha), float(r.potato_ha),
                    float(r.wheat_ha), float(r.beets_ha), float(r.industrial_ha),
                    float(r.flowers_ha), float(r.legumes_ha), float(r.vegetables_ha),
                    float(r.fruit_ha), float(r.nursery_ha), float(r.nature_ha),
                ]), 1),
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
                        COUNT(*)                                        AS substances_tested,
                        SUM(CASE WHEN mate_normov > 1 THEN 1 ELSE 0 END) AS exceedances_above_norm,
                        MAX(mate_normov)                                AS worst_exceedance,
                        (ARRAY_AGG(stof_naam_sam ORDER BY mate_normov DESC NULLS LAST))[1] AS worst_substance,
                        (ARRAY_AGG(norm_omschrijving ORDER BY mate_normov DESC NULLS LAST))[1] AS worst_norm_omschrijving
                    FROM pesticides_measurements
                    WHERE ST_Intersects(geometry, ST_MakeEnvelope(:w, :s, :e, :n, 4326))
                    GROUP BY meetpunt_code, wbhcode_omschrijving, jaar, geometry
                    LIMIT 5000
                ) agg
            ) features;
        """)
        result = db.session.execute(sql_query, {'w': w, 's': s, 'e': e, 'n': n}).scalar()
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
        'brp': {'table': 'brp_parcels', 'column': 'year'},
        'bag': {'table': 'bag_buildings', 'column': 'oorspronkelijkbouwjaar'},
        'kadastralekaart': {'table': 'kadastralekaart_perceel', 'column': None},  # Static
        'natura2000': {'table': 'natura2000_areas', 'column': None} # Static
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
            # Table might not exist yet, or column is missing
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
            WHERE ST_Intersects(geometry, {geom_expr})
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
        'BRP Parcels':       'https://www.nationaalgeoregister.nl/geonetwork/srv/dut/catalog.search#/metadata/44e6d4d3-8fc5-47d6-8712-33dd6d244eef',
        'BRP Summary':       'https://www.nationaalgeoregister.nl/geonetwork/srv/dut/catalog.search#/metadata/44e6d4d3-8fc5-47d6-8712-33dd6d244eef',
        'BAG Buildings':     'https://www.pdok.nl/introductie/-/article/basisregistraties-adressen-en-gebouwen-bag-',
        'Natura 2000':       'https://www.pdok.nl/introductie/-/article/natura2000',
        'KRD Veehouderijen': 'https://krd.igoview.nl/ — Totaaloverzicht veehouderijen (Gelderland/Twente, Limburg, Noord-Brabant)',
        'Health Facilities': 'https://data.humdata.org/dataset/hotosm-nld-health-facilities',
        'Schools':             'https://www.duo.nl/open_onderwijsdata/',
        'Pesticides Atlas':    'https://www.bestrijdingsmiddelenatlas.nl/downloads',
        'Water Hydrography':   'https://api.pdok.nl/hwh/waterschappen-hydrografie/ogc/v1',
        'Nature Network NL':   'https://service.pdok.nl/provincies/natuurnetwerk-nederland/atom/index.xml',
        'WFD Surface Water':   'https://service.pdok.nl/ihw/krw-oppervlaktewaterlichaams-geharmoniseerd/wms/v1_0',
        'Kadastrale Kaart':    'https://www.nationaalgeoregister.nl/geonetwork/srv/dut/catalog.search#/metadata/a29917b9-3426-4041-a11b-69bcb2256904',
        'Waterschappen':       'https://api.pdok.nl/hwh/waterschappen/ogc/v1',
    }

    # Publication / data-date of each dataset (for audit trail in exports)
    DATASET_DATES = {
        'BRP Parcels':       '2024 (annual update — RVO)',
        'BAG Buildings':     'Continuously updated — Kadaster',
        'Natura 2000':       'Periodically updated — Ministerie van LNV',
        'KRD Veehouderijen': 'As published on krd.igoview.nl at time of export',
        'Health Facilities': 'Continuously updated — HOTOSM/OpenStreetMap',
        'Schools':           '2024 — DUO (Dienst Uitvoering Onderwijs)',
        'Pesticides Atlas':  '2022 — Bestrijdingsmiddelenatlas',
        'Water Hydrography': 'Periodically updated — Waterschappen/PDOK',
        'Nature Network NL': 'Periodically updated per province — PDOK INSPIRE',
        'WFD Surface Water': 'Per WFD reporting cycle (6 years) — Rijkswaterstaat',
        'Kadastrale Kaart':  'Continuously updated — Kadaster',
        'Waterschappen':     'Periodically updated — Unie van Waterschappen',
    }

    export_date = pd.Timestamp.now().strftime("%Y-%m-%d")

    def write_sheet(writer, df, sheet_name, source_url, data_date=''):
        df.to_excel(writer, index=False, sheet_name=sheet_name, startrow=3)
        ws = writer.sheets[sheet_name]
        ws['A1'] = f'Source: {source_url}'
        ws['A2'] = f'Data date: {data_date}  |  Exported: {export_date}'

    buf = io.BytesIO()
    try:
        with pd.ExcelWriter(buf, engine='openpyxl') as writer:
            for layer_name in active_layers:
                if layer_name == 'Pesticides Atlas':
                    df = pd.read_sql(pesticides_query, db.engine)
                elif layer_name in layer_queries:
                    df = pd.read_sql(text(layer_queries[layer_name]), db.engine,
                                     params=geo_params)
                else:
                    continue

                # Drop any geometry columns that slipped through (e.g. Woondeals SELECT *)
                df = df.drop(columns=[c for c in df.columns if c.lower() in GEOM_COLS],
                             errors='ignore')

                if not df.empty:
                    write_sheet(writer, df, layer_name[:31],
                                SOURCE_URLS.get(layer_name, ''),
                                DATASET_DATES.get(layer_name, ''))

                # BRP: add a pivot/summary sheet right after the raw data sheet
                if layer_name == 'BRP Parcels':
                    pivot_df = pd.read_sql(text(brp_pivot_query), db.engine,
                                           params=geo_params)
                    if not pivot_df.empty:
                        write_sheet(writer, pivot_df, 'BRP Summary',
                                    SOURCE_URLS['BRP Summary'],
                                    DATASET_DATES.get('BRP Parcels', ''))

            # Auto-join: Kadastrale Kaart × Natura 2000 (added when both layers are active)
            if 'Kadastrale Kaart' in active_layers and 'Natura 2000' in active_layers:
                natura_cadastral_q = f"""
                    SELECT
                        k.identificatie       AS "Parcel ID",
                        k.gemeente            AS "Municipality",
                        k.sectie              AS "Section",
                        k.perceelnummer       AS "Parcel Number",
                        k.kadastralegrootte   AS "Cadastral Area (m2)",
                        k.status              AS "Status",
                        n.naam_n2k            AS "Natura 2000 Area",
                        ROUND((ST_Distance(
                            k.geometry::geography,
                            ST_Transform(n.geometry, 4326)::geography
                        ) / 1000)::numeric, 3) AS "Distance to Natura2000 (km)",
                        CASE WHEN ST_Intersects(
                            k.geometry,
                            ST_Transform(n.geometry, 4326)
                        ) THEN 'Yes' ELSE 'No' END AS "Within Natura2000"
                    FROM kadastralekaart_perceel k
                    JOIN natura2000_areas n ON ST_DWithin(
                        k.geometry::geography,
                        ST_Transform(n.geometry, 4326)::geography,
                        1000
                    )
                    WHERE ST_Intersects(k.geometry, {geom_expr})
                    ORDER BY "Distance to Natura2000 (km)"
                    LIMIT 5000
                """
                n2k_df = pd.read_sql(text(natura_cadastral_q), db.engine,
                                     params=geo_params)
                n2k_df = n2k_df.drop(columns=[c for c in n2k_df.columns if c.lower() in GEOM_COLS],
                                     errors='ignore')
                if not n2k_df.empty:
                    write_sheet(writer, n2k_df, 'Kadastral-Natura2000',
                                SOURCE_URLS['Kadastrale Kaart'],
                                DATASET_DATES.get('Kadastrale Kaart', ''))

            # Always append a Data Sources sheet listing provenance for every active layer
            sources_rows = [
                {
                    'Dataset':      ln,
                    'Source / URL': SOURCE_URLS.get(ln, ''),
                    'Data date':    DATASET_DATES.get(ln, ''),
                    'Export date':  export_date,
                }
                for ln in active_layers
                if ln in SOURCE_URLS
            ]
            if sources_rows:
                src_df = pd.DataFrame(sources_rows)
                src_df.to_excel(writer, index=False, sheet_name='Data Sources', startrow=0)

        buf.seek(0)
        return send_file(
            buf,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=f'Environmental_Evidence_{pd.Timestamp.now().strftime("%Y-%m-%d")}.xlsx'
        )
    except Exception as e:
        logger.error(f"Excel Export Error: {e}")
        return jsonify({'error': 'Export failed'}), 500


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
