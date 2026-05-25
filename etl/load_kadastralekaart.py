import os
import subprocess
from sqlalchemy import create_engine, text
from urllib.parse import urlparse
from dotenv import load_dotenv

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

# OGC API Features endpoint (from PDOK nationaalgeoregister.nl)
# Source: https://www.nationaalgeoregister.nl/geonetwork/srv/dut/catalog.search#/metadata/a29917b9-3426-4041-a11b-69bcb2256904
OGC_API_BASE = "https://api.pdok.nl/kadaster/brk-kadastrale-kaart/ogc/v1"

TABLE_NAME = "kadastralekaart_perceel"

# Collection to load — 'perceel' contains cadastral parcel polygons
COLLECTION = "perceel"

# Only keep these columns — drop all others after load to keep the table lean
RELEVANT_COLUMNS = {
    'identificatie',          # Unique parcel ID
    'kadastralegemeentecode', # Cadastral municipality code
    'sectie',                 # Section letter (A, B, C …)
    'perceelnummer',          # Parcel number within section
    'kadastralegrootte',      # Cadastral area in m²
    'soortgrootte',           # Type of area measurement
    'geometry',               # Spatial column — never drop
}


def load_kadastralekaart():
    """
    Loads cadastral parcels from the PDOK OGC API Features endpoint into PostGIS
    using ogr2ogr's OAPIF driver. Pagination is handled automatically by GDAL.
    After loading, irrelevant columns are dropped so only the cadastral
    identifier fields and geometry are kept.

    Source: Kadaster / PDOK — BRK Kadastrale Kaart
    OGC API: https://api.pdok.nl/kadaster/brk-kadastrale-kaart/ogc/v1
    """
    print(f"Loading Kadastrale Kaart ('{COLLECTION}') from PDOK OGC API...")

    cmd = [
        "ogr2ogr",
        "-f", "PostgreSQL",
        OGR_PG_CONN_STRING,
        f"OAPIF:{OGC_API_BASE}",
        COLLECTION,
        "-nln", TABLE_NAME,
        "-lco", "GEOMETRY_NAME=geometry",
        "-overwrite",
        "-nlt", "PROMOTE_TO_MULTI",
        "-dim", "XY",
        "-t_srs", "EPSG:4326",
        "--config", "GDAL_HTTP_TIMEOUT", "120",
    ]

    print("Running GDAL C++ Engine (OAPIF driver — pagination handled automatically)...")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"GDAL Error:\n{result.stderr}")
        return

    engine = create_engine(DB_URI, pool_pre_ping=True)
    with engine.begin() as conn:

        # Discover all columns that were loaded
        rows = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = :t ORDER BY ordinal_position;"
        ), {'t': TABLE_NAME}).fetchall()
        all_columns = {r[0] for r in rows}

        # Drop any column not in our relevant set
        cols_to_drop = all_columns - RELEVANT_COLUMNS - {'id', 'ogc_fid'}
        for col in cols_to_drop:
            try:
                conn.execute(text(f'ALTER TABLE {TABLE_NAME} DROP COLUMN IF EXISTS "{col}";'))
                print(f"  Dropped column: {col}")
            except Exception as e:
                print(f"  Could not drop column {col}: {e}")

        # Repair geometry invalids and ensure spatial index
        print("Repairing invalid geometries...")
        conn.execute(text(
            f"UPDATE {TABLE_NAME} SET geometry = ST_MakeValid(geometry) "
            f"WHERE NOT ST_IsValid(geometry);"
        ))
        conn.execute(text(
            f"DELETE FROM {TABLE_NAME} WHERE geometry IS NULL;"
        ))
        conn.execute(text(
            f"CREATE INDEX IF NOT EXISTS idx_{TABLE_NAME}_geom "
            f"ON {TABLE_NAME} USING GIST (geometry);"
        ))

        count = conn.execute(text(f"SELECT COUNT(*) FROM {TABLE_NAME}")).scalar()

    engine.dispose()
    print(f"Success: {count:,} cadastral parcels imported into '{TABLE_NAME}'.")


if __name__ == "__main__":
    load_kadastralekaart()
