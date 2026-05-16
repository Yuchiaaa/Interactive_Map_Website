import subprocess
import pyogrio
from sqlalchemy import create_engine, text
import os
import re
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

def load_brp_gdal(file_path, manual_year=None):
    """
    Industrial-grade GDAL (ogr2ogr) pipeline with Cascading Year Detection:
    1. Internal DB column ('jaar' or 'year')
    2. Manual user input (manual_year)
    3. Filename regex extraction (e.g., 'brp_2020.gpkg')
    """
    if not os.path.exists(file_path):
        print(f"Error: File not found at {file_path}")
        return

    file_name = os.path.basename(file_path)
    print(f"Initializing GDAL data pipeline for {file_name}...")
    
    try:
        # 1. Read GPKG metadata
        layers = pyogrio.list_layers(file_path)
        layer_name = layers[0][0]
        
        info = pyogrio.read_info(file_path, layer=layer_name)
        fields = [f.lower() for f in info.get('fields', [])]
        
        gewas_col = 'gewasnaam' if 'gewasnaam' in fields else 'gewas'
        
        # ---------------------------------------------------------
        # Cascading Fallback Logic for Year
        # ---------------------------------------------------------
        year_sql = ""
        detected_source = "Unknown"
        
        # Priority 1: Check internal data columns
        if 'jaar' in fields:
            year_sql = "jaar AS year"
            detected_source = "Internal 'jaar' column"
        elif 'year' in fields:
            year_sql = "year AS year"
            detected_source = "Internal 'year' column"
            
        # Priority 2: Use manual input if provided
        elif manual_year is not None:
            year_sql = f"CAST({manual_year} AS integer) AS year"
            detected_source = f"Manual override ({manual_year})"
            
        # Priority 3: Extract from filename using Regex
        else:
            match = re.search(r'(19|20)\d{2}', file_name)
            if match:
                auto_year = match.group(0)
                year_sql = f"CAST({auto_year} AS integer) AS year"
                detected_source = f"Filename regex extraction ({auto_year})"
            else:
                print("Fatal Error: No internal year column, no manual year provided, and no year found in filename.")
                return

        print(f"Layer: '{layer_name}' | Crop Column: '{gewas_col}'")
        print(f"Year Strategy: {detected_source} | Records: {info['features']}")

        # Build the dynamic SQL query. 
        # Note: Aliasing to 'crop_name' and 'crop_code' to strictly match models.py
        sql_query = f'SELECT {gewas_col} AS crop_name, gewascode AS crop_code, {year_sql} FROM "{layer_name}"'

        # 2. Repair PostGIS Schema (Ensures AUTO-INCREMENT id and MultiPolygons)
        print("Verifying and repairing database schema...")
        engine = create_engine(DB_URI)
        with engine.begin() as conn:
            try:
                # Forces geometries to MultiPolygon and creates the sequence ID generator
                conn.execute(text("ALTER TABLE brp_parcels ALTER COLUMN geometry TYPE geometry(MultiPolygon, 4326) USING ST_Multi(geometry);"))
                conn.execute(text("ALTER TABLE brp_parcels ADD COLUMN IF NOT EXISTS year INTEGER;"))
                conn.execute(text("CREATE SEQUENCE IF NOT EXISTS brp_parcels_id_seq;"))
                conn.execute(text("ALTER TABLE brp_parcels ALTER COLUMN id SET DEFAULT nextval('brp_parcels_id_seq');"))
            except Exception:
                pass # Table might not exist yet, which ogr2ogr will handle
        print("Schema verification complete.")

        # 3. Build the GDAL ogr2ogr command
        cmd = [
            "ogr2ogr",
            "-f", "PostgreSQL",
            OGR_PG_CONN_STRING,          # Uses the dynamically parsed connection string
            file_path,
            "-nln", "brp_parcels",       
            "-append",                   
            "-nlt", "PROMOTE_TO_MULTI",  
            "-dim", "XY",                
            "-t_srs", "EPSG:4326",       
            "-dialect", "OGRSQL",
            "-sql", sql_query
        ]

        print("Executing C++ ogr2ogr binary...")
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"GDAL Error:\n{result.stderr}")
            return
            
        print("Success: Data cleanly imported into PostgreSQL via GDAL.")

    except Exception as e:
        print(f"Pipeline failed: {e}")

if __name__ == "__main__":
    # INSTRUCTIONS: Change the path to your local data, then run the script.
    
    # brp_file = "/Users/yuchia/Downloads/brpgewaspercelen_definitief_2020.gpkg" 
    # load_brp_gdal(brp_file, manual_year=2020)
    print("BRP Script ready. Uncomment the execution lines to run.")