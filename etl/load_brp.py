import subprocess
import pyogrio
from sqlalchemy import create_engine, text
import os
import re

# ---------------------------------------------------------
# DATABASE CONFIGURATION
# ---------------------------------------------------------
DB_URI = 'postgresql://postgres:admin@localhost:5432/legal_mapping'

def load_brp_gdal(file_path, manual_year=None):
    """
    Industrial-grade GDAL (ogr2ogr) pipeline with Cascading Year Detection:
    1. Internal DB column ('jaar' or 'year')
    2. Manual user input (manual_year)
    3. Filename regex extraction (e.g., 'brp_2020.gpkg')
    """
    if not os.path.exists(file_path):
        print(f"❌ Error: File not found at {file_path}")
        return

    file_name = os.path.basename(file_path)
    print(f"🚀 Initializing GDAL C++ Data Pipeline for {file_name}...")
    
    try:
        # 1. Read GPKG metadata
        layers = pyogrio.list_layers(file_path)
        layer_name = layers[0][0]
        
        info = pyogrio.read_info(file_path, layer=layer_name)
        fields = [f.lower() for f in info.get('fields', [])]
        
        gewas_col = 'gewasnaam' if 'gewasnaam' in fields else 'gewas'
        
        # ---------------------------------------------------------
        # THE FIX: 3-Tier Cascading Fallback Logic for Year
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
                print("❌ Fatal Error: No internal year column, no manual year provided, and no year found in filename.")
                return

        print(f"📊 Layer: '{layer_name}' | Crop: '{gewas_col}'")
        print(f"🎯 Year Strategy: {detected_source} | Records: {info['features']}")

        # Build the dynamic SQL query
        sql_query = f'SELECT {gewas_col} AS gewas, gewascode, {year_sql} FROM "{layer_name}"'

        # 2. Repair PostGIS Schema (Ensures AUTO-INCREMENT id and MultiPolygons)
        print("⏳ Repairing database schema...")
        engine = create_engine(DB_URI)
        with engine.begin() as conn:
            try:
                conn.execute(text("ALTER TABLE brp_parcels ALTER COLUMN geometry TYPE geometry(MultiPolygon, 4326) USING ST_Multi(geometry);"))
                conn.execute(text("ALTER TABLE brp_parcels ADD COLUMN IF NOT EXISTS year INTEGER;"))
                conn.execute(text("CREATE SEQUENCE IF NOT EXISTS brp_parcels_id_seq;"))
                conn.execute(text("ALTER TABLE brp_parcels ALTER COLUMN id SET DEFAULT nextval('brp_parcels_id_seq');"))
            except Exception as db_err:
                pass 
        print("✅ Schema repair complete.")

        # 3. Build the GDAL ogr2ogr command
        cmd = [
            "ogr2ogr",
            "-f", "PostgreSQL",
            "PG:dbname=legal_mapping user=postgres password=admin host=localhost port=5432",
            file_path,
            "-nln", "brp_parcels",       
            "-append",                   
            "-nlt", "PROMOTE_TO_MULTI",  
            "-dim", "XY",                
            "-t_srs", "EPSG:4326",       
            "-dialect", "OGRSQL",
            "-sql", sql_query
        ]

        print(f"⏳ Executing C++ ogr2ogr binary... (Hold tight!)")
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            print(f"❌ GDAL Error:\n{result.stderr}")
            return
            
        print(f"🎉 Epic Success! Data cleanly imported.")

    except Exception as e:
        print(f"❌ Pipeline failed: {e}")

if __name__ == "__main__":
    brp_file = "/Users/yuchia/Downloads/brpgewaspercelen_definitief_2020.gpkg" 
    
    # Example 1: Rely entirely on internal columns or filename regex
    # load_brp_gdal(brp_file)
    
    # Example 2: Force a manual year (Fallback Priority 2)
    load_brp_gdal(brp_file, manual_year=2020)