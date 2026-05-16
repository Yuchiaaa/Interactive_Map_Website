import geopandas as gpd
from sqlalchemy import create_engine
import os
from dotenv import load_dotenv

# Load environment variables securely from the .env file
load_dotenv()

# Database Configuration securely loaded from the environment
DB_URI = os.environ.get('DATABASE_URL')

if not DB_URI:
    raise ValueError("DATABASE_URL is not set. Please check your .env file.")

engine = create_engine(DB_URI)

def load_natura2000(file_path):
    """
    Loads local Natura 2000 protected areas into the database.
    Uses 'replace' to ensure the database always has the latest boundaries.
    """
    if not os.path.exists(file_path):
        print(f"Error: File not found at {file_path}")
        return

    print("Processing Natura 2000 data...")
    try:
        # Load the spatial file
        gdf = gpd.read_file(file_path)
        
        # Ensure the coordinate reference system is EPSG:4326 for web mapping
        if gdf.crs is None or gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(epsg=4326)

        # Standardize column names to lowercase to prevent PostgreSQL quoting issues
        gdf.columns = [col.lower() for col in gdf.columns]
        
        # Repair invalid geometries (self-intersections) and drop nulls
        gdf['geometry'] = gdf['geometry'].make_valid()
        gdf = gdf.dropna(subset=['geometry'])

        print(f"Inserting {len(gdf)} records into 'natura2000_areas'...")
        
        # Push the geodataframe to PostGIS
        gdf.to_postgis('natura2000_areas', engine, if_exists='replace', index=True, index_label='id')
        print("Success: Natura 2000 areas securely imported into the database.")

    except Exception as e:
        print(f"Failed to load Natura 2000 data: {e}")

if __name__ == "__main__":
    # INSTRUCTIONS: Change the path to your local data, then run the script.
    
    # natura_file = "/Users/yuchia/Desktop/your_local_data/natura2000_latest.geojson"
    # load_natura2000(natura_file)
    print("Natura 2000 Script ready. Uncomment the execution lines to run.")