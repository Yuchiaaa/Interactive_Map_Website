import geopandas as gpd
from sqlalchemy import create_engine
import os

# Database Configuration
DB_URI = 'postgresql://postgres:admin@localhost:5432/legal_mapping'
engine = create_engine(DB_URI)

def load_brp(file_path, target_year, load_mode='append'):
    """
    Loads local BRP spatial files into the database.
    Use mode='replace' for the very first year you upload, 
    and mode='append' for all subsequent historical years.
    """
    if not os.path.exists(file_path):
        print(f"❌ Error: File not found at {file_path}")
        return

    print(f"⏳ Processing BRP data for year {target_year}...")
    try:
        gdf = gpd.read_file(file_path)
        
        if gdf.crs is None or gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(epsg=4326)

        # Standardize columns and inject year
        gdf.columns = [col.lower() for col in gdf.columns]
        gdf['year'] = target_year
        gdf['geometry'] = gdf['geometry'].make_valid()
        gdf = gdf.dropna(subset=['geometry'])

        print(f"📥 Inserting {len(gdf)} records into 'brp_parcels'...")
        gdf.to_postgis('brp_parcels', engine, if_exists=load_mode, index=True, index_label='id')
        print(f"✅ Success: BRP {target_year} secured in database.")

    except Exception as e:
        print(f"❌ Failed to load BRP: {e}")

if __name__ == "__main__":
    # INSTRUCTIONS: Change the path and year, then run the script.
    
    # brp_file = "/Users/yuchia/Desktop/your_local_data/brp_2022.geojson"
    # load_brp(brp_file, target_year=2022, load_mode='append')
    print("BRP Script ready. Uncomment the execution lines to run.")