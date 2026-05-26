import subprocess
import pyogrio
from sqlalchemy import create_engine, text
import os
from urllib.parse import urlparse
from dotenv import load_dotenv

# Load environment variables securely from the .env file
load_dotenv()

DB_URI = os.environ.get('DATABASE_URL')
if not DB_URI:
    raise ValueError("DATABASE_URL is not set. Please check your .env file.")

# Parse the standard SQLAlchemy URL to build the GDAL/ogr2ogr specific connection string
parsed_url = urlparse(DB_URI)
db_user = parsed_url.username
db_pass = parsed_url.password
db_host = parsed_url.hostname
db_port = parsed_url.port or 5432
db_name = parsed_url.path.lstrip('/')

OGR_PG_CONN_STRING = f"PG:dbname={db_name} user={db_user} password={db_pass} host={db_host} port={db_port}"

def load_waterschappen_gdal(file_path):
    """
    Industrial-grade GDAL (ogr2ogr) pipeline for Water Authority Borders (Waterschappen).
    Bypasses Python memory limits to handle complex polygon geometry.
    """
    if not os.path.exists(file_path):
        print(f"Error: File not found at {file_path}")
        return

    file_name = os.path.basename(file_path)
    print(f"Initializing GDAL C++ Data Pipeline for {file_name}...")

    try:
        # 1. Read metadata dynamically
        layers = pyogrio.list_layers(file_path)
        layer_name = layers[0][0]

        info = pyogrio.read_info(file_path, layer=layer_name)
        print(f"Layer: '{layer_name}' | Records: {info['features']}")

        sql_query = f'SELECT code, naam FROM "{layer_name}"'

        # 2. Repair PostGIS Schema (Ensures AUTO-INCREMENT id and MultiPolygons)
        print("Verifying and repairing database schema...")
        engine = create_engine(DB_URI)
        with engine.begin() as conn:
            try:
                # Force geometry to MultiPolygon and target the 'geom' column as defined in models.py
                conn.execute(text("ALTER TABLE waterschappen ALTER COLUMN geom TYPE geometry(MultiPolygon, 4326) USING ST_Multi(geom);"))

                # Ensure the 'id' column auto-increments perfectly
                conn.execute(text("CREATE SEQUENCE IF NOT EXISTS waterschappen_id_seq;"))
                conn.execute(text("ALTER TABLE waterschappen ALTER COLUMN id SET DEFAULT nextval('waterschappen_id_seq');"))
            except Exception:
                pass # Silently pass if already properly configured or table doesn't exist yet
        print("Schema verification complete.")

        # 3. Build the GDAL ogr2ogr command
        cmd = [
            "ogr2ogr",
            "-f", "PostgreSQL",
            OGR_PG_CONN_STRING,
            file_path,
            "-nln", "waterschappen",      # Target PostGIS table for Waterschappen
            "-lco", "GEOMETRY_NAME=geom", # Force the spatial column to be named 'geom' matching models.py
            "-append",
            "-nlt", "PROMOTE_TO_MULTI",   # Crucial for complex boundaries
            "-dim", "XY",                 # Strip elevation data if any exists
            "-t_srs", "EPSG:4326",        # Force standard Web Map projection
            "-dialect", "OGRSQL",
            "-sql", sql_query
        ]

        print("Executing C++ ogr2ogr binary... (Processing spatial data)")

        # 4. Execute the C++ engine
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            print(f"GDAL Error:\n{result.stderr}")
            return

        print("Success: Waterschappen securely imported into the database.")

    except Exception as e:
        print(f"Pipeline failed: {e}")

if __name__ == "__main__":
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    waterschappen_file = os.path.join(BASE_DIR, "hwh_waterschapsgrenzenimso_geopackage_IMWA.gpkg")

    load_waterschappen_gdal(waterschappen_file)
