# etl/auto_pipeline.py
import json
import requests
from sqlalchemy import create_engine, text
from apscheduler.schedulers.blocking import BlockingScheduler
from datetime import datetime

# Database connection configuration
DB_URI = 'postgresql://postgres:admin@localhost:5432/legal_mapping'
engine = create_engine(DB_URI)

# Haarlem bounding box for spatial extraction
BBOX = "4.60,52.30,4.70,52.40"

def fetch_and_load_brp():
    print(f"\n[{datetime.now()}] --- Starting ETL: BRP Crop Parcels (2026) ---")
    url = f"https://api.pdok.nl/rvo/gewaspercelen/ogc/v1/collections/brpgewas/items?bbox={BBOX}&limit=2000"
    
    try:
        response = requests.get(url, headers={'Accept': 'application/geo+json'}, timeout=60)
        response.raise_for_status()
        features = response.json().get('features', [])
        
        if not features:
            print("No BRP data found.")
            return

        delete_query = text("DELETE FROM brp_parcels WHERE year = 2026")
        insert_query = text("""
            INSERT INTO brp_parcels (year, crop_code, crop_name, area_ha, geom)
            VALUES (
                2026, :crop_code, :crop_name, 
                ST_Area(ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(:geom_json), 4326), 28992)) / 10000.0,
                ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(:geom_json), 4326))
            )
        """)

        with engine.begin() as conn:
            conn.execute(delete_query)
            inserted_count = 0
            for feat in features:
                props = feat.get('properties', {})
                geom_dict = feat.get('geometry')
                if not geom_dict: continue
                
                conn.execute(insert_query, {
                    'crop_code': str(props.get('gewascode', 'Unknown')),
                    'crop_name': str(props.get('gewas', 'Unknown')),
                    'geom_json': json.dumps(geom_dict)
                })
                inserted_count += 1
        print(f"✅ BRP updated: {inserted_count} parcels.")
    except Exception as e:
        print(f"❌ BRP ETL Error: {e}")

def fetch_and_load_kadaster():
    print(f"\n[{datetime.now()}] --- Starting ETL: Kadaster Parcels ---")
    # Using WFS 1.0.0 with maxFeatures
    url = f"https://service.pdok.nl/kadaster/kadastralekaart/wfs/v5_0?service=WFS&version=1.0.0&request=GetFeature&typeName=kadastralekaartv5:perceel&outputFormat=application/json&srsName=EPSG:4326&bbox={BBOX},EPSG:4326&maxFeatures=2000"
    
    try:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        features = response.json().get('features', [])
        
        if not features: return

        # TRUNCATE completely clears the table before reloading the fresh bounding box data
        truncate_query = text("TRUNCATE TABLE kadaster_parcels")
        insert_query = text("""
            INSERT INTO kadaster_parcels (municipality_code, section, parcel_number, registered_area, geom)
            VALUES (
                :muni, :section, :parcel, :area,
                ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(:geom_json), 4326))
            )
        """)

        with engine.begin() as conn:
            conn.execute(truncate_query)
            inserted_count = 0
            for feat in features:
                props = feat.get('properties', {})
                geom_dict = feat.get('geometry')
                if not geom_dict: continue
                
                conn.execute(insert_query, {
                    'muni': str(props.get('kadastraleGemeentecode', 'N/A')),
                    'section': str(props.get('sectie', 'N/A')),
                    'parcel': str(props.get('perceelnummer', 'N/A')),
                    'area': float(props.get('kadastraleGrootte') or 0.0),
                    'geom_json': json.dumps(geom_dict)
                })
                inserted_count += 1
        print(f"✅ Kadaster updated: {inserted_count} parcels.")
    except Exception as e:
        print(f"❌ Kadaster ETL Error: {e}")

def fetch_and_load_natura2000():
    print(f"\n[{datetime.now()}] --- Starting ETL: Natura 2000 ---")
    url = f"https://service.pdok.nl/rvo/natura2000/wfs/v1_0?service=WFS&version=1.0.0&request=GetFeature&typeName=natura2000&outputFormat=application/json&srsName=EPSG:4326&bbox={BBOX},EPSG:4326&maxFeatures=2000"
    
    try:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        features = response.json().get('features', [])
        
        if not features: return

        truncate_query = text("TRUNCATE TABLE natura2000_areas")
        insert_query = text("""
            INSERT INTO natura2000_areas (site_name, protection_type, geom)
            VALUES (
                :name, :type,
                ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(:geom_json), 4326))
            )
        """)

        with engine.begin() as conn:
            conn.execute(truncate_query)
            inserted_count = 0
            for feat in features:
                props = feat.get('properties', {})
                geom_dict = feat.get('geometry')
                if not geom_dict: continue
                
                conn.execute(insert_query, {
                    'name': str(props.get('naam', 'N/A')),
                    'type': str(props.get('gebiedstype', 'N/A')),
                    'geom_json': json.dumps(geom_dict)
                })
                inserted_count += 1
        print(f"✅ Natura 2000 updated: {inserted_count} areas.")
    except Exception as e:
        print(f"❌ Natura 2000 ETL Error: {e}")

def fetch_and_load_bag():
    print(f"\n[{datetime.now()}] --- Starting ETL: BAG Buildings ---")
    # Using WFS 2.0.0 with count parameter
    url = f"https://service.pdok.nl/lv/bag/wfs/v2_0?service=WFS&version=2.0.0&request=GetFeature&typeName=bag:pand&outputFormat=application/json&srsName=EPSG:4326&bbox={BBOX},EPSG:4326&count=2000"
    
    try:
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        features = response.json().get('features', [])
        
        if not features: return

        truncate_query = text("TRUNCATE TABLE bag_buildings")
        # BAG geometries can be plain POLYGON, so we rely on the GEOMETRY column type dynamically
        insert_query = text("""
            INSERT INTO bag_buildings (building_id, construction_year, status, geom)
            VALUES (
                :bid, :year, :status,
                ST_SetSRID(ST_GeomFromGeoJSON(:geom_json), 4326)
            )
        """)

        with engine.begin() as conn:
            conn.execute(truncate_query)
            inserted_count = 0
            for feat in features:
                props = feat.get('properties', {})
                geom_dict = feat.get('geometry')
                if not geom_dict: continue
                
                # Extract year safely, fallback to 0 if parsing fails
                try:
                    year = int(props.get('oorspronkelijkbouwjaar', 0))
                except ValueError:
                    year = 0

                conn.execute(insert_query, {
                    'bid': str(props.get('identificatie', 'N/A')),
                    'year': year,
                    'status': str(props.get('status', 'N/A')),
                    'geom_json': json.dumps(geom_dict)
                })
                inserted_count += 1
        print(f"✅ BAG Buildings updated: {inserted_count} structures.")
    except Exception as e:
        print(f"❌ BAG ETL Error: {e}")

def run_full_pipeline():
    print(f"\n=======================================================")
    print(f"🚀 Triggering Master Data Pipeline at {datetime.now()}")
    print(f"=======================================================")
    fetch_and_load_brp()
    fetch_and_load_kadaster()
    fetch_and_load_natura2000()
    fetch_and_load_bag()
    print(f"=======================================================\n")

if __name__ == "__main__":
    # Execute immediately upon startup
    run_full_pipeline()
    
    # Initialize scheduler for continuous integration
    scheduler = BlockingScheduler()
    # Execute every Sunday at 02:00 AM
    scheduler.add_job(run_full_pipeline, 'cron', day_of_week='sun', hour=2, minute=0)
    
    print("⏱️ Background scheduler active. Press Ctrl+C to terminate.")
    scheduler.start()