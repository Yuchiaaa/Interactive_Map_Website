import subprocess
import pyogrio
import os
import re
import datetime
from urllib.parse import urlparse
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from load_pesticides import load_pesticides
from load_healthcare import load_healthcare
from load_hydrography import load_hydrography
from load_wfd_surface_water import load_wfd_surface_water
from load_nnn import load_nnn

# Load environment variables securely from the .env file
load_dotenv()

# Database Configuration securely loaded from the environment
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

# Dynamically resolve the absolute path to the etl directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Define the master registry for all data streams
# Format: "target_table": {"filename": "...", "needs_year": True/False, "geom_col": "..."}
DATA_STREAMS = {
    "brp_parcels": {
        "filename": "brp_2020.gpkg",
        "needs_year": True,
        "geom_col": "geometry"
    },
    "natura2000_areas": {
        "filename": "natura2000.gpkg",
        "needs_year": False,
        "geom_col": "geometry"
    },
    
    "pesticides_measurements": {
        "filename": "P8_7_download_overschrijdingen_2024.csv",
        "needs_year": False,
        "loader": "csv"
    },
    "health_facilities": {
        "filename": "hotosm_nld_health_facilities_points_gpkg/hotosm_nld_health_facilities_points_gpkg.gpkg",
        "needs_year": False,
        "loader": "gpkg_python"
    },
    "wfd_surface_water": {
        "filename": "INSPIRESurfaceWaterBody.gml",
        "needs_year": False,
        "loader": "gml_python"
    },
    "hydrography_watercourse": {
        "loader": "api_python"  # Streams from OGC API — no local file
    },
    "nnn_areas": {
        "loader": "api_python"  # Downloads from PDOK ATOM feed — no local file
    }
}

def sync_data_stream(table_name, config):
    """
    Executes the GDAL overwrite pipeline for a single data stream.
    Automatically handles smart year injection if required by the configuration.
    """
    print(f"\n[{datetime.datetime.now().strftime('%H:%M:%S')}] Processing Stream: {table_name}")

    # ----------------------------------------------------------
    # API streams: no local file needed — delegate directly
    # ----------------------------------------------------------
    if config.get("loader") == "api_python":
        if table_name == "hydrography_watercourse":
            load_hydrography()
        elif table_name == "nnn_areas":
            load_nnn()
        return

    file_path = os.path.join(BASE_DIR, config["filename"])

    if not os.path.exists(file_path):
        print(f"   Skipped: File not found ({file_path})")
        return

    # ----------------------------------------------------------
    # CSV streams: delegate to dedicated Python loaders
    # ----------------------------------------------------------
    if config.get("loader") == "csv":
        if table_name == "pesticides_measurements":
            load_pesticides(file_path)
        return

    if config.get("loader") == "gpkg_python":
        if table_name == "health_facilities":
            load_healthcare(file_path)
        return

    if config.get("loader") == "gml_python":
        if table_name == "wfd_surface_water":
            load_wfd_surface_water(file_path)
        return

    try:
        # 1. Read metadata from GPKG
        layers = pyogrio.list_layers(file_path)
        layer_name = layers[0][0]
        info = pyogrio.read_info(file_path, layer=layer_name)
        fields = [f.lower() for f in info.get('fields', [])]
        
        print(f"   Found layer '{layer_name}' with {info['features']} records.")

        # 2. Build dynamic SQL for GDAL
        sql_query = f'SELECT * FROM "{layer_name}"'
        
        # Smart Year Injection and Schema Mapping for BRP
        if config.get("needs_year"):
            year_sql = ""
            if 'jaar' in fields:
                year_sql = "jaar AS year"
            elif 'year' in fields:
                year_sql = "year AS year"
            else:
                # Extract year from filename using regex
                match = re.search(r'(19|20)\d{2}', config["filename"])
                if match:
                    auto_year = match.group(0)
                    year_sql = f"CAST({auto_year} AS integer) AS year"
                else:
                    print("   Error: Needs year but couldn't detect from columns or filename.")
                    return
            
            # Reconstruct SQL to strictly match models.py (crop_name, crop_code)
            gewas_col = 'gewasnaam' if 'gewasnaam' in fields else ('gewas' if 'gewas' in fields else 'NULL')
            if gewas_col != 'NULL':
                sql_query = f'SELECT {gewas_col} AS crop_name, gewascode AS crop_code, {year_sql} FROM "{layer_name}"'

        # 3. Build the GDAL ogr2ogr command
        cmd = [
            "ogr2ogr",
            "-f", "PostgreSQL",
            OGR_PG_CONN_STRING,          # Securely inject the parsed connection string
            file_path,
            "-nln", table_name,          # Target PostGIS table
            "-overwrite",                # DROP and RECREATE table automatically
            "-nlt", "PROMOTE_TO_MULTI",  # Force MultiPolygon for complex natural bounds
            "-dim", "XY",                # Strip Z elevation
            "-t_srs", "EPSG:4326",       # Project to Web Mercator
            "-dialect", "OGRSQL",
            "-sql", sql_query
        ]

        # Explicitly set the geometry column name if specified in config
        if config.get("geom_col"):
            cmd.extend(["-lco", f"GEOMETRY_NAME={config['geom_col']}"])

        # 4. Execute C++ Engine
        print("   Running GDAL C++ Engine...")
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"   GDAL Error: {result.stderr.strip()}")
            return
            
        # 5. Schema Repair: Ensure primary key exists post-overwrite
        engine = create_engine(DB_URI)
        with engine.begin() as conn:
            try:
                # Add standard 'id' column if missing and make it the primary key
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS id SERIAL PRIMARY KEY;"))
            except Exception:
                pass
                
        print(f"   Success: {table_name} synced successfully.")

    except Exception as e:
        print(f"   Stream failed: {e}")

def run_master_sync():
    """
    Main loop to execute all configured data streams.
    """
    print("===================================================")
    print(f"MASTER DATA SYNC INITIATED AT {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("===================================================")
    
    for table_name, config in DATA_STREAMS.items():
        sync_data_stream(table_name, config)
        
    print("\n===================================================")
    print("ALL DATA STREAMS PROCESSED SUCCESSFULLY.")
    print("===================================================")

if __name__ == "__main__":
    run_master_sync()