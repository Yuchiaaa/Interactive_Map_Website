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

def load_grenzen_gdal(file_path):
    """
    Industrial-grade GDAL (ogr2ogr) pipeline for Bestuurlijke Grenzen (Administrative Boundaries).
    Loads all layers (gemeenten, provincies, landsgrens) into a single grenzen table.
    """
    if not os.path.exists(file_path):
        print(f"Error: File not found at {file_path}")
        return

    file_name = os.path.basename(file_path)
    print(f"Initializing GDAL C++ Data Pipeline for {file_name}...")

    try:
        # 1. Read metadata dynamically
        layers = pyogrio.list_layers(file_path)
        print(f"Found {len(layers)} layers: {[l[0] for l in layers]}")

        # 2. Repair PostGIS Schema
        print("Verifying and repairing database schema...")
        engine = create_engine(DB_URI)
        with engine.begin() as conn:
            try:
                conn.execute(text("ALTER TABLE grenzen ALTER COLUMN geom TYPE geometry(MultiPolygon, 4326) USING ST_Multi(geom);"))
                conn.execute(text("CREATE SEQUENCE IF NOT EXISTS grenzen_ogc_fid_seq;"))
                conn.execute(text("ALTER TABLE grenzen ALTER COLUMN ogc_fid SET DEFAULT nextval('grenzen_ogc_fid_seq');"))
                conn.execute(text("ALTER TABLE grenzen ADD COLUMN IF NOT EXISTS layer_type VARCHAR;"))
            except Exception:
                pass
        print("Schema verification complete.")

        # 3. Load each layer into the same grenzen table
        for layer_name, _ in layers:
            info = pyogrio.read_info(file_path, layer=layer_name)
            print(f"\nLoading layer: '{layer_name}' | Records: {info['features']}")

            sql_query = f"SELECT *, '{layer_name}' AS layer_type FROM \"{layer_name}\""

            cmd = [
                "ogr2ogr",
                "-f", "PostgreSQL",
                OGR_PG_CONN_STRING,
                file_path,
                "-nln", "grenzen",           # Target PostGIS table
                "-lco", "GEOMETRY_NAME=geom", # Force spatial column name to match models.py
                "-append",
                "-nlt", "PROMOTE_TO_MULTI",  # Crucial for complex boundaries
                "-dim", "XY",                # Strip elevation data if any exists
                "-t_srs", "EPSG:4326",       # Force standard Web Map projection
                "-dialect", "OGRSQL",
                "-sql", sql_query
            ]

            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode != 0:
                print(f"GDAL Error for layer '{layer_name}':\n{result.stderr}")
            else:
                print(f"Success: '{layer_name}' imported into grenzen.")

        print("\nAll layers imported into the grenzen table.")

    except Exception as e:
        print(f"Pipeline failed: {e}")

if __name__ == "__main__":
    # INSTRUCTIONS: Change the path to match your downloaded file.
    grenzen_file = "/Users/aya/Downloads/bestuurlijkegrenzen.gpkg"

    load_grenzen_gdal(grenzen_file)
