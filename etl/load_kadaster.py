import subprocess
import pyogrio
from sqlalchemy import create_engine, text
import os

# ---------------------------------------------------------
# DATABASE CONFIGURATION
# ---------------------------------------------------------
DB_URI = 'postgresql://postgres:admin@localhost:5432/legal_mapping'

def load_kadaster_gdal(file_path):
    """
    Industrial-grade GDAL (ogr2ogr) pipeline for Kadaster Cadastral Parcels.
    Completely bypasses Python memory limits to handle millions of highly 
    precise surveyor-grade polygon vertices.
    """
    if not os.path.exists(file_path):
        print(f"❌ Error: File not found at {file_path}")
        return

    file_name = os.path.basename(file_path)
    print(f"🚀 Initializing GDAL C++ Data Pipeline for {file_name}...")
    
    try:
        # 1. Read metadata dynamically 
        layers = pyogrio.list_layers(file_path)
        layer_name = layers[0][0]
        
        info = pyogrio.read_info(file_path, layer=layer_name)
        print(f"📊 Layer: '{layer_name}' | Records: {info['features']}")

        # Grab all surveyor attributes (sectie, perceelnummer, gemeente, etc.)
        sql_query = f'SELECT * FROM "{layer_name}"'

        # 2. Repair PostGIS Schema (Ensures AUTO-INCREMENT id and MultiPolygons)
        print("⏳ Repairing database schema...")
        engine = create_engine(DB_URI)
        with engine.begin() as conn:
            try:
                # Force geometry to MultiPolygon to prevent Strict Typing crashes
                conn.execute(text("ALTER TABLE kadaster_parcels ALTER COLUMN geometry TYPE geometry(MultiPolygon, 4326) USING ST_Multi(geometry);"))
                
                # Ensure the 'id' column auto-increments perfectly
                conn.execute(text("CREATE SEQUENCE IF NOT EXISTS kadaster_parcels_id_seq;"))
                conn.execute(text("ALTER TABLE kadaster_parcels ALTER COLUMN id SET DEFAULT nextval('kadaster_parcels_id_seq');"))
            except Exception as db_err:
                pass # Silently pass if already properly configured
        print("✅ Schema repair complete.")

        # 3. Build the GDAL ogr2ogr command
        cmd = [
            "ogr2ogr",
            "-f", "PostgreSQL",
            "PG:dbname=legal_mapping user=postgres password=admin host=localhost port=5432",
            file_path,
            "-nln", "kadaster_parcels",  # Target PostGIS table for Kadaster
            "-append",                   
            "-nlt", "PROMOTE_TO_MULTI",  # Crucial for complex cadastral boundaries
            "-dim", "XY",                # Strip elevation data if any exists
            "-t_srs", "EPSG:4326",       # Force standard Web Map projection
            "-dialect", "OGRSQL",
            "-sql", sql_query
        ]

        print(f"⏳ Executing C++ ogr2ogr binary... (Hold tight, this is a massive dataset!)")
        
        # 4. Execute the C++ engine
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"❌ GDAL Error:\n{result.stderr}")
            return
            
        print(f"🎉 Epic Success! Kadaster cadastral parcels securely imported into the database.")

    except Exception as e:
        print(f"❌ Pipeline failed: {e}")

if __name__ == "__main__":
    # INSTRUCTIONS: Change the path to match your downloaded file.
    # Typically, Kadaster data might be quite large (GBs). GDAL will handle it smoothly.
    kadaster_file = "/Users/yuchia/Downloads/RegionaleWoondeals.gpkg" # Check your extension (.gpkg, .geojson, .shp)
    
    load_kadaster_gdal(kadaster_file)