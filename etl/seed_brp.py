# etl/seed_brp.py
import requests
import json
from sqlalchemy import create_engine, text

# Database connection
DB_URI = 'postgresql://postgres:admin@localhost:5432/legal_mapping'
engine = create_engine(DB_URI)

# Bounding box around Haarlem
BBOX = "4.60,52.30,4.70,52.40"

def seed_brp_data_via_postgis():
    print("Fetching real BRP data around Haarlem from PDOK API...")
    url = f"https://api.pdok.nl/rvo/gewaspercelen/ogc/v1/collections/brpgewas/items?bbox={BBOX}&limit=1000"
    
    try:
        response = requests.get(url, headers={'Accept': 'application/geo+json'}, timeout=30)
        response.raise_for_status()
        
        # Parse standard JSON natively (this will never segfault)
        data = response.json()
        features = data.get('features', [])
        
        if not features:
            print("No BRP data found in this area.")
            return
            
        print(f"Downloaded {len(features)} raw features. Handing over to PostGIS for spatial processing...")

        # Craft the raw PostGIS SQL query
        # ST_GeomFromGeoJSON: Parses the raw JSON string into a PostGIS geometry
        # ST_SetSRID: Assigns the WGS84 coordinate system
        # ST_Transform & ST_Area: Projects to Dutch EPSG:28992 and calculates precise area
        # ST_Multi: Ensures even single Polygons are cast to MultiPolygons to match our table schema
        insert_query = text("""
            INSERT INTO brp_parcels (year, crop_code, crop_name, area_ha, geom)
            VALUES (
                :year, 
                :crop_code, 
                :crop_name, 
                ST_Area(ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(:geom_json), 4326), 28992)) / 10000.0,
                ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(:geom_json), 4326))
            )
        """)

        # Open a database connection and execute inserts
        # Using engine.begin() ensures everything is committed as a single transaction
        with engine.begin() as conn:
            for feat in features:
                props = feat.get('properties', {})
                geom_dict = feat.get('geometry')
                
                # Skip features with missing geometry
                if not geom_dict:
                    continue
                
                # Convert the geometry dict back to a plain string to pass to PostGIS
                geom_json_str = json.dumps(geom_dict)
                
                conn.execute(insert_query, {
                    'year': 2026,
                    'crop_code': props.get('gewascode', 'Unknown'),
                    'crop_name': props.get('gewas', 'Unknown'),
                    'geom_json': geom_json_str
                })

        print("✅ Data successfully parsed and inserted by PostGIS!")
        
    except Exception as e:
        print(f"Error seeding data: {e}")

if __name__ == "__main__":
    seed_brp_data_via_postgis()