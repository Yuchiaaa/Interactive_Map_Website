'''
This program imports spatial data in the year of 2026 from various Dutch geospatial APIs (BRP, BAG, Natura 2000, Kadaster) and loads it into a PostgreSQL/PostGIS database. It uses a streamlined approach with a single function to handle fetching, processing, and loading for all datasets, while ensuring proper error handling and logging throughout the process.
'''

import geopandas as gpd
import pandas as pd
from sqlalchemy import create_engine
import requests

# ---------------------------------------------------------
# Database Configuration
# ---------------------------------------------------------
DB_URI = 'postgresql://postgres:123456@localhost:5432/legal_mapping'
engine = create_engine(DB_URI)

# Bounding boxes
BBOX_WFS1 = "4.50,52.30,4.75,52.40" # Lon, Lat (West, South, East, North) for WFS 1.0.0 / OGC API
BBOX_WFS2 = "52.30,4.50,52.40,4.75" # Lat, Lon (South, West, North, East) strictly for WFS 2.0.0

def fetch_and_load(url, table_name, desired_columns, load_mode='replace', explicit_year=None):
    try:
        response = requests.get(url)
        if response.status_code != 200 or response.text.strip().startswith('<'):
            print(f"❌ API Error for {table_name}.")
            return False

        data = response.json()
        if not data.get('features'):
            print(f"⚠️ No features found for {table_name}.")
            return False

        gdf = gpd.GeoDataFrame.from_features(data['features'])
        gdf.set_crs(epsg=4326, inplace=True)

        # Smart column matching and cleaning
        actual_cols = gdf.columns.tolist()
        cols_to_keep = [c for c in actual_cols if any(d.lower() == c.lower() for d in desired_columns)]
        if 'geometry' in actual_cols:
            cols_to_keep.append('geometry')

        gdf = gdf[cols_to_keep]
        gdf.rename(columns={c: c.lower() for c in cols_to_keep}, inplace=True)

        if explicit_year:
            gdf['year'] = explicit_year

        if table_name == 'bag_buildings' and 'oorspronkelijkbouwjaar' in gdf.columns:
            gdf['oorspronkelijkbouwjaar'] = pd.to_numeric(gdf['oorspronkelijkbouwjaar'], errors='coerce')

        gdf.to_postgis(table_name, engine, if_exists=load_mode, index=True, index_label='id')
        print(f"✅ Successfully loaded {len(gdf)} records into {table_name}.")
        return True
    except Exception as e:
        print(f"❌ Error processing {table_name}: {e}")
        return False

if __name__ == "__main__":
    print("🚀 Starting Streamlined 2026 Spatial Data ETL Pipeline...\n" + "="*50)
    
    # 1. BRP Crop Parcels (2026 OGC API)
    print("\n--- Processing BRP Parcels ---")
    brp_url = f"https://api.pdok.nl/rvo/gewaspercelen/ogc/v1/collections/brpgewas/items?bbox={BBOX_WFS1}&limit=2000"
    fetch_and_load(brp_url, 'brp_parcels', ['gewascode', 'gewas'], load_mode='replace', explicit_year=2026)

    # 2. BAG Buildings (WFS 2.0.0 - Using flipped BBOX_WFS2)
    print("\n--- Processing BAG Buildings ---")
    bag_url = f"https://service.pdok.nl/lv/bag/wfs/v2_0?service=WFS&version=2.0.0&request=GetFeature&typeName=bag:pand&outputFormat=application/json&srsName=EPSG:4326&bbox={BBOX_WFS2},urn:ogc:def:crs:EPSG::4326&count=2000"
    fetch_and_load(bag_url, 'bag_buildings', ['identificatie', 'oorspronkelijkbouwjaar', 'status'], load_mode='replace')
    
    # 3. Natura 2000 (WFS 1.0.0)
    print("\n--- Processing Natura 2000 ---")
    natura_url = f"https://service.pdok.nl/rvo/natura2000/wfs/v1_0?service=WFS&version=1.0.0&request=GetFeature&typeName=natura2000:natura2000&outputFormat=application/json&srsName=EPSG:4326&bbox={BBOX_WFS1},EPSG:4326&maxFeatures=2000"
    fetch_and_load(natura_url, 'natura2000_areas', ['naam', 'gebiedstype'], load_mode='replace')
    
    # 4. Kadaster (WFS 1.0.0)
    print("\n--- Processing Kadaster Parcels ---")
    kadaster_url = f"https://service.pdok.nl/kadaster/kadastralekaart/wfs/v5_0?service=WFS&version=1.0.0&request=GetFeature&typeName=kadastralekaartv5:perceel&outputFormat=application/json&srsName=EPSG:4326&bbox={BBOX_WFS1},EPSG:4326&maxFeatures=2000"
    fetch_and_load(kadaster_url, 'kadaster_parcels', ['kadastralegemeentecode', 'sectie', 'perceelnummer', 'kadastralegrootte'], load_mode='replace')
    
    print("\n" + "="*50 + "\n✅ ETL Pipeline Execution Finished.")