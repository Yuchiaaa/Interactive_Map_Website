# app/routes.py
import io
import json
import pandas as pd
from flask import Blueprint, render_template, request, jsonify, send_file
from sqlalchemy import text
from app import db

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
    """Renders the ML analysis page."""
    return render_template('ml.html')

# ---------------------------------------------------------
# 1. API Route: Serve BRP Crop Parcels (Time Machine)
# ---------------------------------------------------------
@main_bp.route('/api/brp_parcels', methods=['GET'])
def get_brp_parcels():
    bbox = request.args.get('bbox')
    year = request.args.get('year', 2020, type=int)

    if not bbox:
        return jsonify({'error': 'Missing bounding box (bbox) parameter'}), 400

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
                        'jaar', year,
                        'gewascode', gewascode,
                        'gewas', gewas
                    ),
                    'geometry', ST_AsGeoJSON(geometry)::jsonb
                ) AS feature
                FROM brp_parcels
                WHERE year = :year
                  AND ST_Intersects(geometry, ST_MakeEnvelope(:w, :s, :e, :n, 4326))
                LIMIT 2000
            ) features;
        """)
        result = db.session.execute(sql_query, {'year': year, 'w': w, 's': s, 'e': e, 'n': n}).scalar()
        return jsonify(json.loads(result) if isinstance(result, str) else result)
    except Exception as e:
        print(f"❌ BRP Query Error: {e}")
        return jsonify({'error': 'Failed to fetch BRP data'}), 500

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
        print(f"❌ BAG Query Error: {e}")
        return jsonify({'error': 'Failed to fetch BAG data'}), 500

# ---------------------------------------------------------
# 3. API Route: Serve Natura 2000 Areas, Buffers, and Centers
# ---------------------------------------------------------
@main_bp.route('/api/natura2000_areas', methods=['GET'])
def get_natura2000_areas():
    bbox = request.args.get('bbox')
    buffer_km = request.args.get('buffer_km', 0.5, type=float)

    if not bbox:
        return jsonify({'error': 'Missing bbox parameter'}), 400

    try:
        w, s, e, n = map(float, bbox.split(','))
        buffer_m = max(buffer_km, 0) * 1000

        sql_query = text("""
            WITH source AS (
                SELECT
                    n.*,
                    CASE
                        WHEN ST_SRID(n.geometry) = 4326 THEN n.geometry
                        ELSE ST_Transform(n.geometry, 4326)
                    END AS geom_4326
                FROM natura2000_areas n
                WHERE n.geometry IS NOT NULL
            ),
            prepared AS (
                SELECT
                    *,
                    ST_Buffer(geom_4326::geography, :buffer_m)::geometry AS buffer_geom,
                    ST_PointOnSurface(geom_4326) AS center_geom
                FROM source
            ),
            visible AS (
                SELECT *
                FROM prepared
                WHERE ST_Intersects(
                    buffer_geom,
                    ST_MakeEnvelope(:w, :s, :e, :n, 4326)
                )
                LIMIT 750
            ),
            feature_parts AS (
                SELECT
                    COALESCE(id::text, row_number() OVER ()::text) AS area_id,
                    1 AS sort_order,
                    jsonb_build_object(
                        'type', 'Feature',
                        'properties',
                            (row_to_json(visible)::jsonb
                                - 'geometry'
                                - 'geom_4326'
                                - 'buffer_geom'
                                - 'center_geom')
                            || jsonb_build_object(
                                'layer_type', 'area',
                                'buffer_km', :buffer_km
                            ),
                        'geometry', ST_AsGeoJSON(geom_4326)::jsonb
                    ) AS feature
                FROM visible

                UNION ALL

                SELECT
                    COALESCE(id::text, row_number() OVER ()::text) AS area_id,
                    0 AS sort_order,
                    jsonb_build_object(
                        'type', 'Feature',
                        'properties',
                            (row_to_json(visible)::jsonb
                                - 'geometry'
                                - 'geom_4326'
                                - 'buffer_geom'
                                - 'center_geom')
                            || jsonb_build_object(
                                'layer_type', 'buffer',
                                'buffer_km', :buffer_km
                            ),
                        'geometry', ST_AsGeoJSON(buffer_geom)::jsonb
                    ) AS feature
                FROM visible

                UNION ALL

                SELECT
                    COALESCE(id::text, row_number() OVER ()::text) AS area_id,
                    2 AS sort_order,
                    jsonb_build_object(
                        'type', 'Feature',
                        'properties',
                            (row_to_json(visible)::jsonb
                                - 'geometry'
                                - 'geom_4326'
                                - 'buffer_geom'
                                - 'center_geom')
                            || jsonb_build_object(
                                'layer_type', 'center',
                                'buffer_km', :buffer_km
                            ),
                        'geometry', ST_AsGeoJSON(center_geom)::jsonb
                    ) AS feature
                FROM visible
            )
            SELECT jsonb_build_object(
                'type', 'FeatureCollection',
                'features', COALESCE(jsonb_agg(feature ORDER BY area_id, sort_order), '[]'::jsonb)
            ) AS geojson
            FROM feature_parts;
        """)

        result = db.session.execute(sql_query, {
            'w': w,
            's': s,
            'e': e,
            'n': n,
            'buffer_km': buffer_km,
            'buffer_m': buffer_m
        }).scalar()
        return jsonify(json.loads(result) if isinstance(result, str) else result)
    except Exception as e:
        print(f"❌ Natura 2000 Query Error: {e}")
        return jsonify({'error': 'Failed to fetch Natura 2000 data', 'details': str(e)}), 500


# ---------------------------------------------------------
# 3B. API Route: Natura 2000 Table Diagnostics
# ---------------------------------------------------------
@main_bp.route('/api/test_natura', methods=['GET'])
def test_natura():
    try:
        # 1. Check total number of rows in the table
        count_query = text("SELECT count(*) FROM natura2000_areas;")
        total_rows = db.session.execute(count_query).scalar()
        
        if total_rows == 0:
            return jsonify({"status": "❌ FATAL: THE TABLE IS COMPLETELY EMPTY!"})
            
        # 2. Check the SRID (Coordinate System) and look at the first polygon
        geom_query = text("SELECT ST_SRID(geometry), ST_AsText(geometry) FROM natura2000_areas WHERE geometry IS NOT NULL LIMIT 1;")
        geom_row = db.session.execute(geom_query).fetchone()
        
        return jsonify({
            "status": "✅ DATA EXISTS!",
            "total_rows": total_rows,
            "srid": geom_row[0] if geom_row else "UNKNOWN",
            "sample_coordinate": geom_row[1][:100] + "..." if geom_row else "NO GEOMETRY"
        })
        
    except Exception as e:
        return jsonify({"status": "❌ DATABASE ERROR", "details": str(e)})
    

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
        print(f"❌ Grenzen Query Error: {e}")
        return jsonify({'error': 'Failed to fetch Grenzen data', 'details': str(e)}), 500


@main_bp.route('/api/test_grenzen', methods=['GET'])
def test_grenzen():
    try:
        count = db.session.execute(text("SELECT count(*) FROM grenzen")).scalar()
        if count == 0:
            return jsonify({"status": "❌ grenzen table is empty"})
        row = db.session.execute(text(
            "SELECT ST_SRID(geom), layer_type, ST_AsText(ST_Centroid(geom)) FROM grenzen WHERE geom IS NOT NULL LIMIT 1"
        )).fetchone()
        return jsonify({
            "status": "✅ data exists",
            "total_rows": count,
            "srid": row[0] if row else None,
            "layer_type": row[1] if row else None,
            "sample_centroid": row[2] if row else None,
        })
    except Exception as e:
        return jsonify({"status": "❌ error", "details": str(e)})

# ---------------------------------------------------------
# 5. API Route: Serve KRD Livestock Farms (Point Layer)
# ---------------------------------------------------------
@main_bp.route('/api/krd_farms', methods=['GET'])
def get_krd_farms():
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
                    'properties', row_to_json(k)::jsonb - 'geometry' - 'id',
                    'geometry', ST_AsGeoJSON(geometry)::jsonb
                ) AS feature
                FROM krd_farms k
                WHERE ST_Intersects(geometry, ST_MakeEnvelope(:w, :s, :e, :n, 4326))
                LIMIT 5000
            ) features;
        """)
        result = db.session.execute(sql_query, {'w': w, 's': s, 'e': e, 'n': n}).scalar()
        return jsonify(json.loads(result) if isinstance(result, str) else result)
    except Exception as e:
        print(f"❌ KRD Query Error: {e}")
        return jsonify({'error': 'Failed to fetch KRD data'}), 500

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
        print(f"❌ Pesticides Query Error: {e}")
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
        print(f"❌ Health Facilities Query Error: {e}")
        return jsonify({'error': 'Failed to fetch health facilities data'}), 500
# ---------------------------------------------------------
# 8. API Route: Serve Schools (Education Points)
# ---------------------------------------------------------
@main_bp.route('/api/schools', methods=['GET'])
def get_schools():
    bbox = request.args.get('bbox')
    school_type = request.args.get('type')  # optional filter e.g. primary, secondary, vocational, university

    if not bbox:
        return jsonify({'error': 'Missing bbox parameter'}), 400

    try:
        w, s, e, n = map(float, bbox.split(','))

        filters = "ST_Intersects(geometry, ST_MakeEnvelope(:w, :s, :e, :n, 4326))"
        params = {'w': w, 's': s, 'e': e, 'n': n}

        if school_type:
            filters += " AND school_type = :school_type"
            params['school_type'] = school_type

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
                        'school_type', school_type,
                        'straatnaam', straatnaam,
                        'plaatsnaam', plaatsnaam,
                        'provincie', provincie
                    ),
                    'geometry', ST_AsGeoJSON(geometry)::jsonb
                ) AS feature
                FROM schools
                WHERE {filters}
                LIMIT 5000
            ) features;
        """)
        result = db.session.execute(sql_query, params).scalar()
        return jsonify(json.loads(result) if isinstance(result, str) else result)
    except Exception as e:
        print(f"❌ Schools Query Error: {e}")
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
                    'geometry', ST_AsGeoJSON(geom)::jsonb
                ) AS feature
                FROM waterschappen
                WHERE ST_Intersects(geom, ST_MakeEnvelope(:w, :s, :e, :n, 4326))
            ) features;
        """)
        result = db.session.execute(sql_query, {'w': w, 's': s, 'e': e, 'n': n}).scalar()

        return jsonify(json.loads(result) if isinstance(result, str) else result)

    except Exception as e:
        print(f"❌ Waterschappen Query Error: {e}")
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
        'kadaster': {'table': 'kadaster_parcels', 'column': None},  # Static
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
            print(f"⚠️ Could not fetch years for {layer_id}: {e}")
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

    try:
        w, s, e, n = map(float, bbox_str.split(','))
    except Exception:
        return jsonify({'error': 'Invalid bbox'}), 400

    layer_queries = {
        'BRP Parcels': text("""
            SELECT
                year                                                        AS "Year",
                gewas                                                       AS "Crop Type",
                gewascode                                                   AS "Crop Code",
                ROUND((ST_Area(geometry::geography) / 10000)::numeric, 4)  AS "Area (ha)"
            FROM brp_parcels
            WHERE ST_Intersects(geometry, ST_MakeEnvelope(:w,:s,:e,:n,4326))
            LIMIT 10000
        """),
        'BAG Buildings': text("""
            SELECT
                identificatie           AS "Building ID",
                oorspronkelijkbouwjaar  AS "Construction Year",
                status                  AS "Status"
            FROM bag_buildings
            WHERE ST_Intersects(geometry, ST_MakeEnvelope(:w,:s,:e,:n,4326))
            LIMIT 10000
        """),
        'Natura 2000': text("""
            SELECT naam AS "Area Name"
            FROM natura2000_areas
            WHERE ST_Intersects(geometry, ST_MakeEnvelope(:w,:s,:e,:n,4326))
        """),
        'KRD Veehouderijen': text("""
            SELECT
                adres                       AS "Adres",
                gemeente                    AS "Gemeente",
                provincie                   AS "Provincie",
                "nh3 emissie (kg/j)"        AS "NH3 Emissie (kg/j)",
                "geur emissie (oue/s)"      AS "Geur Emissie (ouE/s)",
                "fijnstof emissie (g/j)"    AS "Fijnstof Emissie (g/j)"
            FROM krd_farms
            WHERE ST_Intersects(geometry, ST_MakeEnvelope(:w,:s,:e,:n,4326))
            LIMIT 10000
        """),
        'Health Facilities': text("""
            SELECT
                name            AS "Name",
                facility_type   AS "Type",
                addr_city       AS "City",
                operator_type   AS "Operator"
            FROM health_facilities
            WHERE ST_Intersects(geometry, ST_MakeEnvelope(:w,:s,:e,:n,4326))
            LIMIT 10000
        """),
        'Schools': text("""
            SELECT
                instellingsnaam AS "School Name",
                school_type     AS "Type",
                straatnaam      AS "Street",
                plaatsnaam      AS "City",
                provincie       AS "Province"
            FROM schools
            WHERE ST_Intersects(geometry, ST_MakeEnvelope(:w,:s,:e,:n,4326))
            LIMIT 10000
        """),
        'Water Hydrography': text("""
            SELECT *
            FROM hydrography_watercourse
            WHERE ST_Intersects(geometry, ST_MakeEnvelope(:w,:s,:e,:n,4326))
            LIMIT 5000
        """),
        'Nature Network NL': text("""
            SELECT *
            FROM nnn_areas
            WHERE ST_Intersects(geometry, ST_MakeEnvelope(:w,:s,:e,:n,4326))
            LIMIT 5000
        """),
        'WFD Surface Water': text("""
            SELECT *
            FROM wfd_surface_water
            WHERE ST_Intersects(geometry, ST_MakeEnvelope(:w,:s,:e,:n,4326))
            LIMIT 2000
        """),
    }

    brp_pivot_query = text("""
        SELECT
            gewas                                                               AS "Crop Type",
            gewascode                                                           AS "Crop Code",
            COUNT(*)                                                            AS "Parcel Count",
            ROUND(SUM(ST_Area(geometry::geography) / 10000)::numeric, 2)       AS "Total Area (ha)"
        FROM brp_parcels
        WHERE ST_Intersects(geometry, ST_MakeEnvelope(:w,:s,:e,:n,4326))
        GROUP BY gewas, gewascode
        ORDER BY "Total Area (ha)" DESC
    """)

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
        'KRD Veehouderijen': 'https://krd.igoview.nl/',
        'Health Facilities': 'https://data.humdata.org/dataset/hotosm-nld-health-facilities',
        'Schools':             'https://www.duo.nl/open_onderwijsdata/',
        'Pesticides Atlas':    'https://www.bestrijdingsmiddelenatlas.nl/downloads',
        'Water Hydrography':   'https://api.pdok.nl/hwh/waterschappen-hydrografie/ogc/v1',
        'Nature Network NL':   'https://service.pdok.nl/provincies/natuurnetwerk-nederland/atom/index.xml',
        'WFD Surface Water':   'https://service.pdok.nl/ihw/krw-oppervlaktewaterlichaams-geharmoniseerd/wms/v1_0',
    }

    def write_sheet(writer, df, sheet_name, source_url):
        df.to_excel(writer, index=False, sheet_name=sheet_name, startrow=2)
        ws = writer.sheets[sheet_name]
        ws['A1'] = f'Source: {source_url}'

    buf = io.BytesIO()
    try:
        with pd.ExcelWriter(buf, engine='openpyxl') as writer:
            for layer_name in active_layers:
                if layer_name == 'Pesticides Atlas':
                    df = pd.read_sql(pesticides_query, db.engine)
                elif layer_name in layer_queries:
                    df = pd.read_sql(layer_queries[layer_name], db.engine,
                                     params={'w': w, 's': s, 'e': e, 'n': n})
                else:
                    continue

                # Drop any geometry columns that slipped through (e.g. Woondeals SELECT *)
                df = df.drop(columns=[c for c in df.columns if c.lower() in GEOM_COLS],
                             errors='ignore')

                if not df.empty:
                    write_sheet(writer, df, layer_name[:31], SOURCE_URLS.get(layer_name, ''))

                # BRP: add a pivot/summary sheet right after the raw data sheet
                if layer_name == 'BRP Parcels':
                    pivot_df = pd.read_sql(brp_pivot_query, db.engine,
                                           params={'w': w, 's': s, 'e': e, 'n': n})
                    if not pivot_df.empty:
                        write_sheet(writer, pivot_df, 'BRP Summary', SOURCE_URLS['BRP Summary'])

        buf.seek(0)
        return send_file(
            buf,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=f'Environmental_Evidence_{pd.Timestamp.now().strftime("%Y-%m-%d")}.xlsx'
        )
    except Exception as e:
        print(f"❌ Excel Export Error: {e}")
        return jsonify({'error': 'Export failed'}), 500


# ---------------------------------------------------------
# 10. API Route: Serve Nature Network Netherlands (INSPIRE harmonized)
# ---------------------------------------------------------
@main_bp.route('/api/nnn', methods=['GET'])
def get_nnn():
    bbox = request.args.get('bbox')
    if not bbox:
        return jsonify({'error': 'Missing bbox parameter'}), 400

    try:
        w, s, e, n = map(float, bbox.split(','))

        # Simplify geometries based on bbox size for performance:
        # nationwide view (~4° wide) → heavy simplification
        # regional/local view (<1° wide) → no simplification
        bbox_width = e - w
        if bbox_width > 2:
            tolerance = 0.001   # nationwide zoom — reduce coordinate density
        elif bbox_width > 0.5:
            tolerance = 0.0002  # regional zoom
        else:
            tolerance = 0       # local zoom — full detail

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
            ) features;
        """)
        result = db.session.execute(sql_query, {'w': w, 's': s, 'e': e, 'n': n, 'tolerance': tolerance}).scalar()
        return jsonify(json.loads(result) if isinstance(result, str) else result)
    except Exception as e:
        print(f"❌ NNN Query Error: {e}")
        return jsonify({'error': 'Failed to fetch NNN data'}), 500


# ---------------------------------------------------------
# 11. API Route: Serve Water Hydrography (INSPIRE harmonized)
# ---------------------------------------------------------
@main_bp.route('/api/hydrography', methods=['GET'])
def get_hydrography():
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
                LIMIT 5000
            ) features;
        """)
        result = db.session.execute(sql_query, {'w': w, 's': s, 'e': e, 'n': n}).scalar()
        return jsonify(json.loads(result) if isinstance(result, str) else result)
    except Exception as e:
        print(f"❌ Hydrography Query Error: {e}")
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
                LIMIT 2000
            ) features;
        """)
        result = db.session.execute(sql_query, {'w': w, 's': s, 'e': e, 'n': n}).scalar()
        return jsonify(json.loads(result) if isinstance(result, str) else result)
    except Exception as e:
        print(f"❌ WFD Surface Water Query Error: {e}")
        return jsonify({'error': 'Failed to fetch WFD Surface Water data'}), 500


# ---------------------------------------------------------
# ML Routes
# ---------------------------------------------------------

@main_bp.route('/api/ml/status')
def ml_status():
    """Returns computed_at timestamp and row count for each ML analysis."""
    tables = {
        'risk_scores':       'ml_risk_scores',
        'pesticide_trends':  'ml_pesticide_trends',
        'farm_anomalies':    'ml_farm_anomalies',
    }
    status = {}
    for key, table in tables.items():
        try:
            row = db.session.execute(
                text(f"SELECT MAX(computed_at), COUNT(*) FROM {table}")
            ).fetchone()
            status[key] = {
                'computed_at': row[0].isoformat() if row[0] else None,
                'count': int(row[1]),
            }
        except Exception:
            status[key] = {'computed_at': None, 'count': 0}
    return jsonify(status)


@main_bp.route('/api/ml/risk_scores')
def ml_risk_scores():
    try:
        sql = text("""
            SELECT jsonb_build_object(
                'type', 'FeatureCollection',
                'features', COALESCE(jsonb_agg(f.feature), '[]'::jsonb)
            ) AS geojson
            FROM (
                SELECT jsonb_build_object(
                    'type', 'Feature',
                    'properties', jsonb_build_object(
                        'farm_id',            farm_id,
                        'adres',              adres,
                        'gemeente',           gemeente,
                        'provincie',          provincie,
                        'risk_score',         ROUND(risk_score::numeric, 1),
                        'nh3_value',          ROUND(nh3_value::numeric, 1),
                        'dist_natura_km',     ROUND(dist_natura_km::numeric, 2),
                        'nearest_exceedance', ROUND(nearest_exceedance::numeric, 2),
                        'schools_within_5km', schools_within_5km
                    ),
                    'geometry', ST_AsGeoJSON(geometry)::jsonb
                ) AS feature
                FROM ml_risk_scores
                WHERE geometry IS NOT NULL
            ) f
        """)
        result = db.session.execute(sql).scalar()
        return jsonify(json.loads(result) if isinstance(result, str) else result)
    except Exception as e:
        print(f"❌ ML Risk Scores Error: {e}")
        return jsonify({'type': 'FeatureCollection', 'features': []})


@main_bp.route('/api/ml/pesticide_trends')
def ml_pesticide_trends():
    try:
        sql = text("""
            SELECT jsonb_build_object(
                'type', 'FeatureCollection',
                'features', COALESCE(jsonb_agg(f.feature), '[]'::jsonb)
            ) AS geojson
            FROM (
                SELECT jsonb_build_object(
                    'type', 'Feature',
                    'properties', jsonb_build_object(
                        'station_code',    station_code,
                        'station_name',    station_name,
                        'trend',           trend,
                        'p_value',         ROUND(p_value::numeric, 4),
                        'tau',             ROUND(tau::numeric, 3),
                        'slope',           ROUND(slope::numeric, 4),
                        'year_start',      year_start,
                        'year_end',        year_end,
                        'n_years',         n_years,
                        'mean_exceedance', ROUND(mean_exceedance::numeric, 2)
                    ),
                    'geometry', ST_AsGeoJSON(geometry)::jsonb
                ) AS feature
                FROM ml_pesticide_trends
                WHERE geometry IS NOT NULL
            ) f
        """)
        result = db.session.execute(sql).scalar()
        return jsonify(json.loads(result) if isinstance(result, str) else result)
    except Exception as e:
        print(f"❌ ML Pesticide Trends Error: {e}")
        return jsonify({'type': 'FeatureCollection', 'features': []})


@main_bp.route('/api/ml/farm_anomalies')
def ml_farm_anomalies():
    try:
        sql = text("""
            SELECT jsonb_build_object(
                'type', 'FeatureCollection',
                'features', COALESCE(jsonb_agg(f.feature), '[]'::jsonb)
            ) AS geojson
            FROM (
                SELECT jsonb_build_object(
                    'type', 'Feature',
                    'properties', jsonb_build_object(
                        'farm_id',       farm_id,
                        'adres',         adres,
                        'gemeente',      gemeente,
                        'provincie',     provincie,
                        'anomaly_score', ROUND(anomaly_score::numeric, 4),
                        'is_anomaly',    is_anomaly,
                        'nh3',           ROUND(nh3::numeric, 1),
                        'geur',          ROUND(geur::numeric, 1),
                        'fijnstof',      ROUND(fijnstof::numeric, 2)
                    ),
                    'geometry', ST_AsGeoJSON(geometry)::jsonb
                ) AS feature
                FROM ml_farm_anomalies
                WHERE geometry IS NOT NULL
            ) f
        """)
        result = db.session.execute(sql).scalar()
        return jsonify(json.loads(result) if isinstance(result, str) else result)
    except Exception as e:
        print(f"❌ ML Farm Anomalies Error: {e}")
        return jsonify({'type': 'FeatureCollection', 'features': []})
