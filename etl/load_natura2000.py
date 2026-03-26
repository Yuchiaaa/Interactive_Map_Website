import geopandas as gpd
from sqlalchemy import create_engine
import os

# Database Configuration
DB_URI = 'postgresql://postgres:admin@localhost:5432/legal_mapping'
engine = create_engine(DB_URI)

def load_natura2000(file_path):
    """Loads local Natura 2000 protected areas into the database."""
    if not os.path.exists(file_path):
        print(f"❌ Error: File not found at {file_path}")
        return

    print("⏳ Processing Natura 2000 data...")
    try:
        gdf = gpd.read_file(file_path)
        
        if gdf.crs is None or gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(epsg=4326)

        gdf.columns = [col.lower() for col in gdf.columns]
        gdf['geometry'] = gdf['geometry'].make_valid()
        gdf = gdf.dropna(subset=['geometry'])

        print(f"📥 Inserting {len(gdf)} records into 'natura2000_areas'...")
        gdf.to_postgis('natura2000_areas', engine, if_exists='replace', index=True, index_label='id')
        print("✅ Success: Natura 2000 secured in database.")

    except Exception as e:
        print(f"❌ Failed to load Natura 2000: {e}")

if __name__ == "__main__":
    # INSTRUCTIONS: Change the path, then run the script.
    
    # natura_file = "/Users/yuchia/Desktop/your_local_data/natura2000_latest.geojson"
    # load_natura2000(natura_file)
    print("Natura 2000 Script ready. Uncomment the execution lines to run.")