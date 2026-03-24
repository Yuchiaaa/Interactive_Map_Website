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
    year = request.args.get('year', 2026, type=int)

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
# 3. API Route: Serve Natura 2000 Areas (Nationwide/Static)
# ---------------------------------------------------------
@main_bp.route('/api/natura2000_areas', methods=['GET'])
def get_natura2000_areas():
    bbox = request.args.get('bbox')
    if not bbox:
        return jsonify({'error': 'Missing bbox parameter'}), 400

    try:
        w, s, e, n = map(float, bbox.split(','))
        sql_query = text("""
            SELECT jsonb_build_object('type', 'FeatureCollection', 'features', COALESCE(jsonb_agg(features.feature), '[]'::jsonb)) AS geojson
            FROM (
                SELECT jsonb_build_object(
                    'type', 'Feature',
                    'properties', jsonb_build_object('naam', naam, 'type', gebiedstype),
                    'geometry', ST_AsGeoJSON(geometry)::jsonb
                ) AS feature
                FROM natura2000_areas
                WHERE ST_Intersects(geometry, ST_MakeEnvelope(:w, :s, :e, :n, 4326))
            ) features;
        """)
        result = db.session.execute(sql_query, {'w': w, 's': s, 'e': e, 'n': n}).scalar()
        return jsonify(json.loads(result) if isinstance(result, str) else result)
    except Exception as e:
        print(f"❌ Natura 2000 Query Error: {e}")
        return jsonify({'error': 'Failed to fetch Natura 2000 data'}), 500

# ---------------------------------------------------------
# 4. API Route: Serve Kadaster Parcels
# ---------------------------------------------------------
@main_bp.route('/api/kadaster_parcels', methods=['GET'])
def get_kadaster_parcels():
    bbox = request.args.get('bbox')
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
                        'gemeente', kadastralegemeentecode, 
                        'sectie', sectie, 
                        'perceelnummer', perceelnummer, 
                        'area', kadastralegrootte
                    ),
                    'geometry', ST_AsGeoJSON(geometry)::jsonb
                ) AS feature
                FROM kadaster_parcels
                WHERE ST_Intersects(geometry, ST_MakeEnvelope(:w, :s, :e, :n, 4326)) 
                LIMIT 2000
            ) features;
        """)
        result = db.session.execute(sql_query, {'w': w, 's': s, 'e': e, 'n': n}).scalar()
        return jsonify(json.loads(result) if isinstance(result, str) else result)
    except Exception as e:
        print(f"❌ Kadaster Query Error: {e}")
        return jsonify({'error': 'Failed to fetch Kadaster data'}), 500