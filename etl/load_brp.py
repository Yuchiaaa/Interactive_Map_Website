import subprocess
import zipfile
import tempfile
import shutil
import pyogrio
from sqlalchemy import create_engine, text
import os
import re
from urllib.parse import urlparse
from dotenv import load_dotenv

load_dotenv()

DB_URI = os.environ.get('DATABASE_URL')
if not DB_URI:
    raise ValueError("DATABASE_URL is not set. Please check your .env file.")

parsed_url = urlparse(DB_URI)
db_user = parsed_url.username
db_pass = parsed_url.password
db_host = parsed_url.hostname
db_port = parsed_url.port or 5432
db_name = parsed_url.path.lstrip('/')

OGR_PG_CONN_STRING = f"PG:dbname={db_name} user={db_user} password={db_pass} host={db_host} port={db_port}"


def load_brp_gdal(file_path, manual_year=None):
    """
    Load a BRP gewaspercelen file into the brp_parcels PostGIS table.

    Handles both GPKG (2020-2025) and ZIP archives containing shapefiles (2009-2019).

    Year detection is cascading:
      1. Internal column 'jaar' or 'year' in the source data
      2. manual_year argument
      3. Year extracted from the filename via regex (e.g. 'brp_2021.gpkg')
    """
    if not os.path.exists(file_path):
        print(f"Error: File not found at {file_path}")
        return

    file_name = os.path.basename(file_path)
    ext = os.path.splitext(file_name)[1].lower()

    # For ZIP archives (2009-2019): extract to a temp dir and find the .shp
    temp_dir = None
    try:
        if ext == '.zip':
            temp_dir = tempfile.mkdtemp(prefix='brp_')
            print(f"Extracting ZIP archive to {temp_dir}...")
            with zipfile.ZipFile(file_path) as zf:
                zf.extractall(temp_dir)

            shp_files = [
                os.path.join(temp_dir, f)
                for f in os.listdir(temp_dir)
                if f.lower().endswith('.shp')
            ]
            if not shp_files:
                print("Error: No .shp file found inside the ZIP archive.")
                return
            actual_path = shp_files[0]
            print(f"Found shapefile: {os.path.basename(actual_path)}")
        else:
            actual_path = file_path

        _load_file(actual_path, original_filename=file_name, manual_year=manual_year)

    finally:
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)


def _load_file(file_path, original_filename, manual_year=None):
    """Internal: runs the GDAL pipeline on a resolved file path (GPKG or SHP)."""
    print(f"Initializing GDAL pipeline for {os.path.basename(file_path)}...")

    try:
        layers = pyogrio.list_layers(file_path)
        layer_name = layers[0][0]

        info = pyogrio.read_info(file_path, layer=layer_name)
        fields = [f.lower() for f in info.get('fields', [])]

        # Dutch BRP files use 'gewasnaam' in some years and 'gewas' in others
        gewas_col = 'gewasnaam' if 'gewasnaam' in fields else 'gewas'

        # ---------------------------------------------------------
        # Cascading year detection
        # ---------------------------------------------------------
        year_sql = ""
        detected_source = "Unknown"

        if 'jaar' in fields:
            year_sql = "jaar AS year"
            detected_source = "Internal 'jaar' column"
        elif 'year' in fields:
            year_sql = "year AS year"
            detected_source = "Internal 'year' column"
        elif manual_year is not None:
            year_sql = f"CAST({manual_year} AS integer) AS year"
            detected_source = f"Manual override ({manual_year})"
        else:
            match = re.search(r'(19|20)\d{2}', original_filename)
            if match:
                auto_year = match.group(0)
                year_sql = f"CAST({auto_year} AS integer) AS year"
                detected_source = f"Filename regex ({auto_year})"
            else:
                print("Fatal: No year found — pass manual_year or put the year in the filename.")
                return

        print(f"Layer: '{layer_name}' | Crop column: '{gewas_col}'")
        print(f"Year strategy: {detected_source} | Features: {info['features']}")

        # Column names must match what routes.py queries: gewas, gewascode, year
        sql_query = f'SELECT {gewas_col} AS gewas, gewascode, {year_sql} FROM "{layer_name}"'

        # Repair / migrate schema so ogr2ogr can append cleanly.
        # The table may have been created by an older version of the model with
        # English column names (crop_name, crop_code, area_ha). This migration
        # renames them to the Dutch names the routes actually query.
        print("Verifying / migrating database schema...")
        engine = create_engine(DB_URI)
        with engine.begin() as conn:
            try:
                conn.execute(text(
                    "ALTER TABLE brp_parcels ALTER COLUMN geometry "
                    "TYPE geometry(MultiPolygon, 4326) USING ST_Multi(geometry);"
                ))
                conn.execute(text("ALTER TABLE brp_parcels ADD COLUMN IF NOT EXISTS year INTEGER;"))
                conn.execute(text("CREATE SEQUENCE IF NOT EXISTS brp_parcels_id_seq;"))
                conn.execute(text(
                    "ALTER TABLE brp_parcels ALTER COLUMN id SET DEFAULT nextval('brp_parcels_id_seq');"
                ))
            except Exception:
                pass  # Table doesn't exist yet — ogr2ogr creates it on first run

            # Rename legacy English columns to Dutch names expected by routes.py.
            # Safe to run repeatedly: the DO block checks before renaming.
            try:
                conn.execute(text("""
                    DO $$
                    BEGIN
                        IF EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'brp_parcels' AND column_name = 'crop_name'
                        ) THEN
                            ALTER TABLE brp_parcels RENAME COLUMN crop_name TO gewas;
                        END IF;
                        IF EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'brp_parcels' AND column_name = 'crop_code'
                        ) THEN
                            ALTER TABLE brp_parcels RENAME COLUMN crop_code TO gewascode;
                        END IF;
                        IF EXISTS (
                            SELECT 1 FROM information_schema.columns
                            WHERE table_name = 'brp_parcels' AND column_name = 'area_ha'
                        ) THEN
                            ALTER TABLE brp_parcels DROP COLUMN area_ha;
                        END IF;
                    END $$;
                """))
                print("Column migration done (crop_name→gewas, crop_code→gewascode).")
            except Exception as mig_err:
                print(f"Column migration skipped: {mig_err}")
        print("Schema check done.")

        cmd = [
            "ogr2ogr",
            "-f", "PostgreSQL",
            OGR_PG_CONN_STRING,
            file_path,
            "-nln", "brp_parcels",
            "-append",
            "-nlt", "PROMOTE_TO_MULTI",
            "-dim", "XY",
            "-t_srs", "EPSG:4326",
            "-dialect", "OGRSQL",
            "-sql", sql_query,
        ]

        print("Running ogr2ogr...")
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            print(f"GDAL error:\n{result.stderr}")
            return

        print(f"Done. Loaded {info['features']:,} features into brp_parcels.")

    except Exception as e:
        print(f"Pipeline failed: {e}")


if __name__ == "__main__":
    # Change these two lines and run the script.
    # Use the full path to your downloaded file.
    # For ZIP files (2009-2019) the year is auto-detected from the filename.
    #
    # Example GPKG (2020-2025):
    #   brp_file = r"C:\Downloads\brpgewaspercelen_definitief_2024.gpkg"
    #   load_brp_gdal(brp_file)
    #
    # Example ZIP (2009-2019):
    #   brp_file = r"C:\Downloads\brpgewaspercelen_definitief_2019.zip"
    #   load_brp_gdal(brp_file)
    print("BRP loader ready. Edit the __main__ block with your file path and run the script.")
