import os
import subprocess
import pyogrio
from urllib.parse import urlparse
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

# =========================================================
# DATABASE CONFIGURATION
# =========================================================
DB_URI = os.environ.get('DATABASE_URL')
if not DB_URI:
    raise ValueError("DATABASE_URL is not set. Please check your .env file.")

# Target table name in the PostGIS database.
# Stores water authority (waterschap) boundary polygons,
# sourced from https://www.pdok.nl/introductie/-/article/waterschappen-waterschapsgrenzen-imso
TABLE_NAME = 'waterschappen'

# =========================================================
# GDAL CONNECTION
# =========================================================
# ogr2ogr requires its own PG connection string format — parsed from DATABASE_URL.
# Used instead of geopandas because ogr2ogr handles PROMOTE_TO_MULTI for
# complex boundary polygons more reliably.
_parsed = urlparse(DB_URI)
OGR_PG  = (
    f"PG:dbname={_parsed.path.lstrip('/')} "
    f"user={_parsed.username} "
    f"password={_parsed.password} "
    f"host={_parsed.hostname} "
    f"port={_parsed.port or 5432}"
)


# =========================================================
# LOAD
# =========================================================

def load_waterschappen(file_paths):
    """
    Load one or more Waterschappen boundary files into the 'waterschappen'
    PostGIS table using ogr2ogr.

    Source: https://www.pdok.nl/introductie/-/article/waterschappen-waterschapsgrenzen-imso
    Download path: PDOK > Waterschappen Waterschapsgrenzen IMSO > GeoPackage

    ogr2ogr is used instead of geopandas because it handles PROMOTE_TO_MULTI
    and complex boundary polygons more reliably.

    Parameters
    ----------
    file_paths : str or list of str
        Path(s) to the downloaded Waterschappen GeoPackage file(s) on disk.
    """

    # Normalize input: always work with a list of paths
    if isinstance(file_paths, str):
        file_paths = [file_paths]

    for file_path in file_paths:

        # ----------------------------------------------------------
        # STEP 1: Validate the file exists
        # ----------------------------------------------------------
        if not os.path.exists(file_path):
            print(f"❌ Error: file not found: {file_path}")
            continue

        file_name = os.path.basename(file_path)
        print(f"\n⏳ Processing Waterschappen file: {file_name}")

        try:
            # ----------------------------------------------------------
            # STEP 2: Reject duplicate loads — check the DB before reading the file
            # ----------------------------------------------------------
            engine_check = create_engine(DB_URI, pool_pre_ping=True)
            with engine_check.connect() as conn:
                table_exists = conn.execute(text(
                    "SELECT EXISTS ("
                    "  SELECT FROM information_schema.tables"
                    "  WHERE table_name = 'waterschappen'"
                    ")"
                )).scalar()

                if table_exists:
                    already_loaded = conn.execute(
                        text("SELECT EXISTS (SELECT 1 FROM waterschappen LIMIT 1)")
                    ).scalar()
                    if already_loaded:
                        print(f"   ⚠️  '{TABLE_NAME}' already contains data. Skipping to avoid duplicates.")
                        print(f"       Run truncate_waterschappen() first if you want to reload.")
                        engine_check.dispose()
                        continue
            engine_check.dispose()

            # ----------------------------------------------------------
            # STEP 3: Inspect the layer
            # ----------------------------------------------------------
            layers     = pyogrio.list_layers(file_path)
            layer_name = layers[0][0]
            info       = pyogrio.read_info(file_path, layer=layer_name)

            print(f"   🗂️  Layer: '{layer_name}' | Features: {info['features']:,}")

            # ----------------------------------------------------------
            # STEP 4: Ensure the waterschappen table schema is ready
            # Adds MultiPolygon constraint and sequence if the table already
            # exists from a prior run. Repairs are silently ignored if correct.
            # ----------------------------------------------------------
            engine = create_engine(DB_URI, pool_pre_ping=True)
            with engine.begin() as conn:
                try:
                    conn.execute(text(
                        "ALTER TABLE waterschappen "
                        "ALTER COLUMN geom TYPE geometry(MultiPolygon, 4326) "
                        "USING ST_Multi(geom);"
                    ))
                    conn.execute(text(
                        "CREATE SEQUENCE IF NOT EXISTS waterschappen_id_seq;"
                    ))
                    conn.execute(text(
                        "ALTER TABLE waterschappen "
                        "ALTER COLUMN id SET DEFAULT nextval('waterschappen_id_seq');"
                    ))
                except Exception:
                    pass

            # ----------------------------------------------------------
            # STEP 5: Load via ogr2ogr
            # Only select code and naam — avoids importing redundant IMSO columns.
            # -nlt PROMOTE_TO_MULTI ensures Polygon → MultiPolygon uniformity.
            # ----------------------------------------------------------
            sql_query = f'SELECT code, naam FROM "{layer_name}"'

            cmd = [
                "ogr2ogr",
                "-f", "PostgreSQL",
                OGR_PG,
                file_path,
                "-nln", TABLE_NAME,
                "-lco", "GEOMETRY_NAME=geom",
                "-append",
                "-nlt", "PROMOTE_TO_MULTI",
                "-dim", "XY",
                "-t_srs", "EPSG:4326",
                "-dialect", "OGRSQL",
                "-sql", sql_query,
            ]

            print(f"   📖 Running ogr2ogr for '{layer_name}'...")
            result = subprocess.run(cmd, capture_output=True, text=True)
            engine.dispose()

            if result.returncode != 0:
                print(f"   ❌ GDAL error:\n{result.stderr}")
                continue

            print(f"   ✅ Success: {file_name} loaded into '{TABLE_NAME}'.")

        except Exception as e:
            print(f"   ❌ Pipeline failed for {file_name}: {e}")

    print(f"\n🎉 Waterschappen loading complete!")


# =========================================================
# ENTRY POINT
# =========================================================
# INSTRUCTIONS:
#   1. Go to https://www.pdok.nl/introductie/-/article/waterschappen-waterschapsgrenzen-imso
#   2. Download the Waterschappen Waterschapsgrenzen IMSO dataset as GeoPackage
#   3. Update the path below and run: python load_waterschappen.py
# =========================================================
if __name__ == "__main__":

    waterschappen_files = [
        {"path": "/Users/khushi/Downloads/hwh_waterschapsgrenzenimso_geopackage_IMWA.gpkg"},
    ]

    if not waterschappen_files or waterschappen_files[0]["path"].startswith("/path/to/"):
        print("Waterschappen loader ready.")
        print("Update the file path(s) in waterschappen_files, then run again.")
    else:
        paths = [entry["path"] for entry in waterschappen_files]
        load_waterschappen(paths)
