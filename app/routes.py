# app/routes.py
import json
from flask import Blueprint, render_template, request, jsonify
from sqlalchemy import text
from app import db

main_bp = Blueprint('main', __name__)

# ---------------------------------------------------------
# 0. Main Page Route
# ---------------------------------------------------------
@main_bp.route('/')
def index():
    """Renders the main map interface."""
    return render_template('index.html')

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
# 3. API Route: Serve Natura 2000 Areas (Static)
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
# 4. API Route: Serve Woondeals (Regional Housing Agreements)
# ---------------------------------------------------------
@main_bp.route('/api/woondeals', methods=['GET'])
def get_woondeals():
    bbox = request.args.get('bbox')
    if not bbox:
        return jsonify({'error': 'Missing bbox parameter'}), 400

    try:
        w, s, e, n = map(float, bbox.split(','))
        
        # FIX: Changed 'geometry' to 'geom' to match the actual PostGIS database schema
        sql_query = text("""
            SELECT jsonb_build_object(
                'type', 'FeatureCollection', 
                'features', COALESCE(jsonb_agg(features.feature), '[]'::jsonb)
            ) AS geojson
            FROM (
                SELECT jsonb_build_object(
                    'type', 'Feature',
                    'properties', row_to_json(w)::jsonb - 'geometry' - 'geom' - 'wkb_geometry' - 'fid' - 'id',
                    'geometry', ST_AsGeoJSON(geom)::jsonb
                ) AS feature
                FROM woondeals w
                WHERE ST_Intersects(geom, ST_MakeEnvelope(:w, :s, :e, :n, 4326)) 
            ) features;
        """)
        result = db.session.execute(sql_query, {'w': w, 's': s, 'e': e, 'n': n}).scalar()
        
        return jsonify(json.loads(result) if isinstance(result, str) else result)
        
    except Exception as e:
        print(f"❌ Woondeals Query Error: {e}")
        return jsonify({'error': 'Failed to fetch Woondeals data', 'details': str(e)}), 500

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
                        'stof_naam', stof_naam_sam,
                        'jaar', jaar,
                        'normklas', normklas,
                        'norm_omschrijving', norm_omschrijving,
                        'klasse', klasse,
                        'klasse_omschrijving', klasse_omschrijving,
                        'mate_normov', mate_normov,
                        'meetpunt_code', meetpunt_code
                    ),
                    'geometry', ST_AsGeoJSON(geometry)::jsonb
                ) AS feature
                FROM pesticides_measurements
                WHERE ST_Intersects(geometry, ST_MakeEnvelope(:w, :s, :e, :n, 4326))
                LIMIT 5000
            ) features;
        """)
        result = db.session.execute(sql_query, {'w': w, 's': s, 'e': e, 'n': n}).scalar()
        return jsonify(json.loads(result) if isinstance(result, str) else result)
    except Exception as e:
        print(f"❌ Pesticides Query Error: {e}")
        return jsonify({'error': 'Failed to fetch pesticides data'}), 500

# ---------------------------------------------------------
# 7. API Route: Dynamic Year Availability Scanner
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
        'natura2000': {'table': 'natura2000_areas', 'column': None}, # Static
        'woondeals': {'table': 'woondeals', 'column': None}         # Static (or update if temporal)
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