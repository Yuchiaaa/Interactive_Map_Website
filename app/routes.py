# app/routes.py
import io
import pandas as pd
import json
from flask import current_app as app, render_template, send_file, jsonify, request
from sqlalchemy import text
from .models import db

# ---------------------------------------------------------
# 1. Main Route: Serve the interactive map interface
# ---------------------------------------------------------
@app.route('/')
def index():
    """Renders the main HTML template for the web application."""
    return render_template('index.html')

# ---------------------------------------------------------
# 2. API Route: Export database to Excel
# ---------------------------------------------------------
@app.route('/api/export_excel', methods=['POST'])
def export_database_to_excel():
    """
    Exports all seeded PostGIS datasets directly to a multi-sheet Excel file.
    Uses ST_AsText to convert binary geometries into readable Well-Known Text (WKT).
    """
    try:
        # Create an in-memory bytes buffer for the Excel file
        output = io.BytesIO()
        
        # Initialize the Pandas Excel writer using openpyxl engine
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            
            # Export BRP Crop Parcels
            brp_query = text("""
                SELECT id, year, crop_code, crop_name, area_ha, ST_AsText(geom) AS geometry_wkt 
                FROM brp_parcels
            """)
            brp_df = pd.read_sql(brp_query, db.engine)
            if not brp_df.empty:
                brp_df.to_excel(writer, sheet_name='BRP_Crop_Parcels', index=False)

            # Export Kadaster Parcels
            kadaster_query = text("""
                SELECT id, municipality_code, section, parcel_number, registered_area, ST_AsText(geom) AS geometry_wkt 
                FROM kadaster_parcels
            """)
            kadaster_df = pd.read_sql(kadaster_query, db.engine)
            if not kadaster_df.empty:
                kadaster_df.to_excel(writer, sheet_name='Kadaster_Parcels', index=False)

            # Export Natura 2000 Areas
            natura_query = text("""
                SELECT id, site_name, protection_type, ST_AsText(geom) AS geometry_wkt 
                FROM natura2000_areas
            """)
            natura_df = pd.read_sql(natura_query, db.engine)
            if not natura_df.empty:
                natura_df.to_excel(writer, sheet_name='Natura2000', index=False)

            # Export BAG Buildings
            bag_query = text("""
                SELECT id, building_id, construction_year, status, ST_AsText(geom) AS geometry_wkt 
                FROM bag_buildings
            """)
            bag_df = pd.read_sql(bag_query, db.engine)
            if not bag_df.empty:
                bag_df.to_excel(writer, sheet_name='BAG_Buildings', index=False)

        # Reset the pointer of the buffer to the beginning
        output.seek(0)
        
        # Send the generated Excel file back to the client
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name='Environmental_Evidence_Full_Database.xlsx'
        )

    except Exception as e:
        print(f"Database Export Error: {e}")
        return jsonify({'error': 'Failed to generate full database export'}), 500
    
    

# ---------------------------------------------------------
# 3. API Route: Serve dynamic BRP data from local PostGIS
# ---------------------------------------------------------
@app.route('/api/brp_parcels', methods=['GET'])
def get_brp_parcels():
    """
    Fetches BRP crop parcels from the local PostGIS database based on 
    the current map viewport (Bounding Box) and selected year.
    Converts the spatial data directly into a GeoJSON FeatureCollection.
    """
    bbox = request.args.get('bbox')
    year = request.args.get('year', 2023, type=int)

    if not bbox:
        return jsonify({'error': 'Missing bounding box (bbox) parameter'}), 400

    try:
        # Parse the bounding box (West, South, East, North)
        w, s, e, n = map(float, bbox.split(','))
        
        # Highly optimized PostGIS SQL to generate GeoJSON directly in the database
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
                        'gewascode', crop_code,
                        'gewas', crop_name,
                        'area_ha', area_ha
                    ),
                    'geometry', ST_AsGeoJSON(geom)::jsonb
                ) AS feature
                FROM brp_parcels
                WHERE year = :year
                  AND ST_Intersects(geom, ST_MakeEnvelope(:w, :s, :e, :n, 4326))
                LIMIT 1000
            ) features;
        """)
        
        # Execute the query using SQLAlchemy
        result = db.session.execute(sql_query, {'year': year, 'w': w, 's': s, 'e': e, 'n': n}).scalar()
        
        # SQLAlchemy with psycopg2 usually returns jsonb as a Python dict
        if isinstance(result, str):
            return jsonify(json.loads(result))
        return jsonify(result)

    except Exception as e:
        print(f"PostGIS Query Error: {e}")
        return jsonify({'error': 'Failed to fetch spatial data from local database'}), 500