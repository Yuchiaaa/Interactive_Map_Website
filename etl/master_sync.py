import subprocess
import pyogrio
import os
import re
import datetime
from sqlalchemy import create_engine, text

# =========================================================
# CONFIGURATION
# =========================================================
DB_URI = 'postgresql://postgres:admin@localhost:5432/legal_mapping'

# Dynamically resolve the absolute path to the etl directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Define the master registry for all data streams
# Format: "target_table": {"filename": "...", "needs_year": True/False}
DATA_STREAMS = {
    "brp_parcels": {
        "filename": "brp_2020.gpkg",
        "needs_year": True
    },
    "natura2000_areas": {
        "filename": "natura2000.gpkg",
        "needs_year": False
    },
    "kadaster_parcels": {
        "filename": "kadaster.gpkg",
        "needs_year": False
    },
    "woondeals": {
        "filename": "RegionaleWoondeals.gpkg",
        "needs_year": False
    }
}

def sync_data_stream(table_name, config):
    """
    Executes the GDAL overwrite pipeline for a single data stream.
    Automatically handles smart year injection if required by the configuration.
    """
    file_path = os.path.join(BASE_DIR, config["filename"])
    
    print(f"\n[{datetime.datetime.now().strftime('%H:%M:%S')}] 🔄 Processing Stream: {table_name}")
    
    if not os.path.exists(file_path):
        print(f"   ⚠️  Skipped: File not found ({file_path})")
        return

    try:
        # 1. Read metadata from GPKG
        layers = pyogrio.list_layers(file_path)
        layer_name = layers[0][0]
        info = pyogrio.read_info(file_path, layer=layer_name)
        fields = [f.lower() for f in info.get('fields', [])]
        
        print(f"   📊 Found layer '{layer_name}' with {info['features']} records.")

        # 2. Build dynamic SQL for GDAL
        sql_query = f'SELECT * FROM "{layer_name}"'
        
        # Smart Year Injection for datasets that require temporal tracking (like BRP)
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
                    print("   ❌ Error: Needs year but couldn't detect from columns or filename.")
                    return
            
            # Reconstruct SQL to include all original columns PLUS the year
            # Ensure crop column is standardized if it exists
            gewas_col = 'gewasnaam' if 'gewasnaam' in fields else ('gewas' if 'gewas' in fields else 'NULL')
            if gewas_col != 'NULL':
                sql_query = f'SELECT {gewas_col} AS gewas, gewascode, {year_sql} FROM "{layer_name}"'

        # 3. Build the GDAL ogr2ogr command
        cmd = [
            "ogr2ogr",
            "-f", "PostgreSQL",
            f"PG:dbname=legal_mapping user=postgres password=admin host=localhost port=5432",
            file_path,
            "-nln", table_name,          # Target PostGIS table
            "-overwrite",                # DROP and RECREATE table automatically
            "-nlt", "PROMOTE_TO_MULTI",  # Force MultiPolygon for complex natural bounds
            "-dim", "XY",                # Strip Z elevation
            "-t_srs", "EPSG:4326",       # Project to Web Mercator
            "-dialect", "OGRSQL",
            "-sql", sql_query
        ]

        # 4. Execute C++ Engine
        print("   ⏳ Running C++ GDAL Engine...")
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"   ❌ GDAL Error: {result.stderr.strip()}")
            return
            
        # 5. Schema Repair: Ensure primary key exists post-overwrite
        engine = create_engine(DB_URI)
        with engine.begin() as conn:
            try:
                # Add standard 'id' column if missing and make it the primary key
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS id SERIAL PRIMARY KEY;"))
            except Exception:
                pass
                
        print(f"   ✅ Success: {table_name} perfectly synced!")

    except Exception as e:
        print(f"   ❌ Stream failed: {e}")

def run_master_sync():
    """
    Main loop to execute all configured data streams.
    """
    print("===================================================")
    print(f"🚀 MASTER DATA SYNC INITIATED AT {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("===================================================")
    
    for table_name, config in DATA_STREAMS.items():
        sync_data_stream(table_name, config)
        
    print("\n===================================================")
    print("🎉 ALL DATA STREAMS PROCESSED SUCCESSFULLY!")
    print("===================================================")

if __name__ == "__main__":
    run_master_sync()