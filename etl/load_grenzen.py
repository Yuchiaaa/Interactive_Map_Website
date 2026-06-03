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
# Stores administrative boundary polygons (gemeenten, provincies, landsgrens)
# merged into a single table with a layer_type discriminator column,
# sourced from https://www.pdok.nl/introductie/-/article/bestuurlijke-grenzen
TABLE_NAME = 'grenzen'

# =========================================================
# GDAL CONNECTION
# =========================================================
# ogr2ogr requires its own PG connection string format — parsed from DATABASE_URL.
# This is used instead of geopandas because ogr2ogr handles PROMOTE_TO_MULTI
# and multi-layer append into a single table more reliably for complex boundaries.
_parsed   = urlparse(DB_URI)
OGR_PG    = (
    f"PG:dbname={_parsed.path.lstrip('/')} "
    f"user={_parsed.username} "
    f"password={_parsed.password} "
    f"host={_parsed.hostname} "
    f"port={_parsed.port or 5432}"
)


# =========================================================
# LOAD
# =========================================================

def load_grenzen(file_paths):
    """
    Load one or more Bestuurlijke Grenzen (administrative boundaries) files into
    the 'grenzen' PostGIS table using ogr2ogr.

    Source: https://www.pdok.nl/introductie/-/article/bestuurlijke-grenzen
    Download path: PDOK > Bestuurlijke Grenzen > GeoPackage

    All layers in the GeoPackage (gemeenten, provincies, landsgrens) are merged
    into the single 'grenzen' table and tagged with a 'layer_type' column.
    ogr2ogr is used instead of geopandas because it handles PROMOTE_TO_MULTI
    and multi-layer appending into one table more reliably for complex boundaries.

    Parameters
    ----------
    file_paths : str or list of str
        Path(s) to the downloaded Bestuurlijke Grenzen GeoPackage file(s) on disk.
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
        print(f"\n⏳ Processing Bestuurlijke Grenzen file: {file_name}")

        try:
            # ----------------------------------------------------------
            # STEP 2: Reject duplicate loads — check the DB before reading the file
            # ----------------------------------------------------------
            engine_check = create_engine(DB_URI, pool_pre_ping=True)
            with engine_check.connect() as conn:
                table_exists = conn.execute(text(
                    "SELECT EXISTS ("
                    "  SELECT FROM information_schema.tables"
                    "  WHERE table_name = 'grenzen'"
                    ")"
                )).scalar()

                if table_exists:
                    already_loaded = conn.execute(
                        text("SELECT EXISTS (SELECT 1 FROM grenzen LIMIT 1)")
                    ).scalar()
                    if already_loaded:
                        print(f"   ⚠️  '{TABLE_NAME}' already contains data. Skipping to avoid duplicates.")
                        print(f"       Run truncate_grenzen() first if you want to reload.")
                        engine_check.dispose()
                        continue
            engine_check.dispose()

            # ----------------------------------------------------------
            # STEP 3: Inspect all layers in the GeoPackage
            # ----------------------------------------------------------
            layers = pyogrio.list_layers(file_path)
            print(f"   🗂️  Found {len(layers)} layer(s): {[l[0] for l in layers]}")

            # ----------------------------------------------------------
            # STEP 4: Ensure the grenzen table schema is ready
            # Adds layer_type column if the table already exists from a prior run.
            # Schema repairs are silently ignored if already correct.
            # ----------------------------------------------------------
            engine = create_engine(DB_URI, pool_pre_ping=True)
            with engine.begin() as conn:
                try:
                    conn.execute(text(
                        "ALTER TABLE grenzen "
                        "ALTER COLUMN geom TYPE geometry(MultiPolygon, 4326) "
                        "USING ST_Multi(geom);"
                    ))
                    conn.execute(text(
                        "CREATE SEQUENCE IF NOT EXISTS grenzen_ogc_fid_seq;"
                    ))
                    conn.execute(text(
                        "ALTER TABLE grenzen "
                        "ALTER COLUMN ogc_fid SET DEFAULT nextval('grenzen_ogc_fid_seq');"
                    ))
                    conn.execute(text(
                        "ALTER TABLE grenzen ADD COLUMN IF NOT EXISTS layer_type VARCHAR;"
                    ))
                except Exception:
                    pass

            # ----------------------------------------------------------
            # STEP 5: Load each layer into grenzen via ogr2ogr
            # -nlt PROMOTE_TO_MULTI ensures Polygon → MultiPolygon uniformity.
            # -append merges all layers into the same table.
            # A SQL select injects the layer name as layer_type per row.
            # ----------------------------------------------------------
            for layer_name, _ in layers:
                info = pyogrio.read_info(file_path, layer=layer_name)
                print(f"   📖 Loading '{layer_name}' ({info['features']:,} features)...")

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
                    "-sql", f"SELECT *, '{layer_name}' AS layer_type FROM \"{layer_name}\"",
                ]

                result = subprocess.run(cmd, capture_output=True, text=True)

                if result.returncode != 0:
                    print(f"   ❌ GDAL error for layer '{layer_name}':\n{result.stderr}")
                else:
                    print(f"   ✅ '{layer_name}' imported into '{TABLE_NAME}'.")

            engine.dispose()

        except Exception as e:
            print(f"   ❌ Pipeline failed for {file_name}: {e}")

    print(f"\n🎉 Bestuurlijke Grenzen loading complete!")


# =========================================================
# ENTRY POINT
# =========================================================
# INSTRUCTIONS:
#   1. Go to https://www.pdok.nl/introductie/-/article/bestuurlijke-grenzen
#   2. Download the Bestuurlijke Grenzen dataset as GeoPackage
#   3. Update the path below and run: python load_grenzen.py
#
# All layers (gemeenten, provincies, landsgrens) are automatically
# detected and merged into the single 'grenzen' table.
# =========================================================
if __name__ == "__main__":

    grenzen_files = [
        {"path": "/Users/khushi/Downloads/bestuurlijkegrenzen.gpkg"},
    ]

    if not grenzen_files or grenzen_files[0]["path"].startswith("/path/to/"):
        print("Grenzen loader ready.")
        print("Update the file path(s) in grenzen_files, then run again.")
    else:
        paths = [entry["path"] for entry in grenzen_files]
        load_grenzen(paths)
