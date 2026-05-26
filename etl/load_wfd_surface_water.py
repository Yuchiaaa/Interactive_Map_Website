import geopandas as gpd
from sqlalchemy import create_engine
import os
from dotenv import load_dotenv

load_dotenv()

DB_URI = os.environ.get('DATABASE_URL')
if not DB_URI:
    raise ValueError("DATABASE_URL is not set. Please check your .env file.")

TABLE_NAME = "wfd_surface_water"


def load_wfd_surface_water(file_path):
    if not os.path.exists(file_path):
        print(f"Error: File not found at {file_path}")
        return

    print("Processing WFD Surface Water Bodies data...")
    try:
        gdf = gpd.read_file(file_path)
        print(f"  Read {len(gdf)} features. Columns: {list(gdf.columns)}")

        if gdf.crs is None or gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(epsg=4326)

        gdf.columns = [col.lower() for col in gdf.columns]
        gdf['geometry'] = gdf['geometry'].make_valid()
        gdf = gdf.dropna(subset=['geometry'])

        print(f"  Inserting {len(gdf)} records into '{TABLE_NAME}'...")
        engine = create_engine(DB_URI, pool_pre_ping=True)
        gdf.to_postgis(TABLE_NAME, engine, if_exists='replace', index=True, index_label='id')
        engine.dispose()
        print(f"Success: {len(gdf)} WFD Surface Water Bodies loaded into '{TABLE_NAME}'.")

    except Exception as e:
        print(f"Failed to load WFD Surface Water Bodies: {e}")


if __name__ == "__main__":
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    load_wfd_surface_water(os.path.join(BASE_DIR, "INSPIRESurfaceWaterBody.gml"))
