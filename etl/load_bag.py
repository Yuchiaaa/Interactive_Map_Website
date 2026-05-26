import os
import subprocess
from sqlalchemy import create_engine, text
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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TABLE_NAME = "bag_buildings"

RELEVANT_COLUMNS = {
    'identificatie',
    'oorspronkelijkbouwjaar',
    'status',
    'geometry',
}


def load_bag():
    """
    Loads BAG Panden (buildings) from the local bag-light.gpkg file into PostGIS.
    File source: https://service.pdok.nl/kadaster/bag/atom/downloads/bag-light.gpkg (~7.7 GB)
    Place the file at etl/bag-light.gpkg before running.
    """
    file_path = os.path.join(BASE_DIR, "bag-light.gpkg")

    if not os.path.exists(file_path):
        print(f"Skipped: file not found ({file_path})")
        print("Download from: https://service.pdok.nl/kadaster/bag/atom/downloads/bag-light.gpkg")
        return

    print(f"Loading BAG Panden from {file_path} ...")

    cmd = [
        "ogr2ogr",
        "-f", "PostgreSQL",
        OGR_PG_CONN_STRING,
        file_path,
        "pand",
        "-nln", TABLE_NAME,
        "-lco", "GEOMETRY_NAME=geometry",
        "-overwrite",
        "-nlt", "PROMOTE_TO_MULTI",
        "-dim", "XY",
        "-t_srs", "EPSG:4326",
    ]

    print("Running GDAL ogr2ogr pipeline...")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"GDAL Error:\n{result.stderr}")
        return

    engine = create_engine(DB_URI, pool_pre_ping=True)
    with engine.begin() as conn:

        rows = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = :t ORDER BY ordinal_position;"
        ), {'t': TABLE_NAME}).fetchall()
        all_columns = {r[0] for r in rows}

        cols_to_drop = all_columns - RELEVANT_COLUMNS - {'id', 'ogc_fid'}
        for col in cols_to_drop:
            try:
                conn.execute(text(f'ALTER TABLE {TABLE_NAME} DROP COLUMN IF EXISTS "{col}";'))
            except Exception:
                pass

        print("Repairing invalid geometries and building spatial index...")
        conn.execute(text(
            f"UPDATE {TABLE_NAME} SET geometry = ST_MakeValid(geometry) "
            f"WHERE NOT ST_IsValid(geometry);"
        ))
        conn.execute(text(f"DELETE FROM {TABLE_NAME} WHERE geometry IS NULL;"))
        conn.execute(text(
            f"CREATE INDEX IF NOT EXISTS idx_{TABLE_NAME}_geom "
            f"ON {TABLE_NAME} USING GIST (geometry);"
        ))

        count = conn.execute(text(f"SELECT COUNT(*) FROM {TABLE_NAME}")).scalar()

    engine.dispose()
    print(f"Success: {count:,} buildings imported into '{TABLE_NAME}'.")


if __name__ == "__main__":
    load_bag()
