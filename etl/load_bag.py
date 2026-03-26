import geopandas as gpd
import pandas as pd
from sqlalchemy import create_engine
import os

# Database Configuration
DB_URI = 'postgresql://postgres:admin@localhost:5432/legal_mapping'
engine = create_engine(DB_URI)

def load_bag(file_path):
    """
    Loads local BAG building files into the database.
    Always uses 'replace' since BAG contains all historical construction years intrinsically.
    """
    if not os.path.exists(file_path):
        print(f"❌ Error: File not found at {file_path}")
        return

    print("⏳ Processing BAG Buildings data...")
    try:
        gdf = gpd.read_file(file_path)
        
        if gdf.crs is None or gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(epsg=4326)

        gdf.columns = [col.lower() for col in gdf.columns]
        
        # Crucial step: Ensure construction year is numeric for temporal filtering
        if 'oorspronkelijkbouwjaar' in gdf.columns:
            gdf['oorspronkelijkbouwjaar'] = pd.to_numeric(gdf['oorspronkelijkbouwjaar'], errors='coerce')

        gdf['geometry'] = gdf['geometry'].make_valid()
        gdf = gdf.dropna(subset=['geometry'])

        print(f"📥 Inserting {len(gdf)} records into 'bag_buildings'...")
        gdf.to_postgis('bag_buildings', engine, if_exists='replace', index=True, index_label='id')
        print("✅ Success: BAG buildings secured in database.")

    except Exception as e:
        print(f"❌ Failed to load BAG: {e}")

if __name__ == "__main__":
    # INSTRUCTIONS: Change the path, then run the script.
    
    # bag_file = "/Users/yuchia/Desktop/your_local_data/bag_latest.geojson"
    # load_bag(bag_file)
    print("BAG Script ready. Uncomment the execution lines to run.")