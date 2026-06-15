import os
import time
import subprocess
import requests
import geopandas as gpd
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

# =========================================================
# OGC API CONFIGURATION (fallback when no local file given)
# =========================================================
BASE_URL    = "https://api.pdok.nl/hwh/waterschappen-hydrografie/ogc/v1"
COLLECTION  = "watercourse"
TABLE_NAME  = "hydrography_watercourse"
PAGE_SIZE   = 1000
BATCH_PAGES = 10

# =========================================================
# GDAL CONNECTION (used for GML file loading via ogr2ogr)
# =========================================================
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

def load_hydrography(file_path=None, collection=COLLECTION):
    """
    Load the PDOK Waterschappen Hydrografie (Watercourse) dataset.

    Primary:  local GML file via ogr2ogr (faster, no network dependency)
    Fallback: PDOK OGC API Features stream (if no file_path given)

    Source: https://www.pdok.nl/introductie/-/article/waterschappen-hydrografie-inspire-geharmoniseerd-
    API:    https://api.pdok.nl/hwh/waterschappen-hydrografie/ogc/v1

    Parameters
    ----------
    file_path : str, optional
        Path to a local Hydrography GML file. If provided, loads the
        Watercourse layer from the file using ogr2ogr. If omitted, streams
        from the PDOK OGC API.
    """

    # ----------------------------------------------------------
    # STEP 1: Reject duplicate loads
    # ----------------------------------------------------------
    engine_check = create_engine(DB_URI, pool_pre_ping=True)
    with engine_check.connect() as conn:
        table_exists = conn.execute(text(
            "SELECT EXISTS ("
            "  SELECT FROM information_schema.tables"
            "  WHERE table_name = 'hydrography_watercourse'"
            ")"
        )).scalar()

        if table_exists:
            already_loaded = conn.execute(
                text("SELECT EXISTS (SELECT 1 FROM hydrography_watercourse LIMIT 1)")
            ).scalar()
            if already_loaded:
                print(f"⚠️  '{TABLE_NAME}' already contains data. Skipping to avoid duplicates.")
                print(f"    Run truncate_hydrography() first if you want to reload.")
                engine_check.dispose()
                return
    engine_check.dispose()

    if file_path:
        _load_from_file(file_path)
    else:
        _load_from_api(collection)


def _load_from_file(file_path):
    """
    Load Watercourse layer from a local GML file using ogr2ogr.

    Uses a temp-table swap so existing DB data is preserved if the load fails:
      1. ogr2ogr → hydrography_watercourse_tmp
      2. Success → DROP old table, rename tmp → final
      3. Failure → DROP tmp, old data untouched
    """

    if not os.path.exists(file_path):
        print(f"❌ File not found: {file_path}")
        return

    print(f"⏳ Loading hydrography from file: {os.path.basename(file_path)}")
    print(f"   Layer: Watercourse → '{TABLE_NAME}'")

    tmp_table = f"{TABLE_NAME}_tmp"

    # Clean up any leftover temp table from a previous failed run
    engine = create_engine(DB_URI, pool_pre_ping=True)
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {tmp_table};"))
    engine.dispose()

    cmd = [
        "ogr2ogr",
        "-f", "PostgreSQL",
        OGR_PG,
        file_path,
        "Watercourse",
        "-nln", tmp_table,
        "-lco", "GEOMETRY_NAME=geometry",
        "-overwrite",
        "-nlt", "PROMOTE_TO_MULTI",
        "-dim", "XY",
        "-t_srs", "EPSG:4326",
    ]

    print(f"   📥 Running ogr2ogr (1,233,670 features — this takes a few minutes)...")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"   ❌ ogr2ogr failed. Existing DB data preserved.")
        print(f"   {result.stderr[:500]}")
        engine = create_engine(DB_URI, pool_pre_ping=True)
        with engine.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {tmp_table};"))
        engine.dispose()
        return

    # Swap: drop old, rename tmp → final
    engine = create_engine(DB_URI, pool_pre_ping=True)
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {TABLE_NAME};"))
        conn.execute(text(f"ALTER TABLE {tmp_table} RENAME TO {TABLE_NAME};"))
        conn.execute(text(
            f"CREATE INDEX IF NOT EXISTS idx_{TABLE_NAME}_geom "
            f"ON {TABLE_NAME} USING GIST (geometry);"
        ))
        count = conn.execute(text(f"SELECT COUNT(*) FROM {TABLE_NAME}")).scalar()
    engine.dispose()

    print(f"   ✅ Success: {count:,} watercourse features loaded into '{TABLE_NAME}'.")
    print(f"\n🎉 Hydrography loading complete!")


def _load_from_api(collection):
    """Stream the PDOK OGC API and write to PostGIS in batches."""

    print(f"⏳ Starting hydrography load: collection='{collection}' → '{TABLE_NAME}'")

    next_url    = f"{BASE_URL}/collections/{collection}/items?f=json&limit={PAGE_SIZE}"
    page        = 1
    total       = 0
    batch       = []
    first_write = True

    while next_url:
        print(f"   🌐 Fetching page {page}...", flush=True)
        data     = _fetch_page(next_url)
        features = data.get('features', [])
        batch.extend(features)
        total += len(features)

        next_url = next(
            (l['href'] for l in data.get('links', []) if l.get('rel') == 'next'),
            None,
        )
        page += 1

        if len(batch) >= PAGE_SIZE * BATCH_PAGES:
            print(f"   📥 Writing batch to DB (total so far: {total:,})...")
            _write_batch(batch, first_write)
            first_write = False
            batch = []

    if batch:
        print(f"   📥 Writing final batch to DB (total: {total:,})...")
        _write_batch(batch, first_write)

    print(f"\n✅ Done — {total:,} features loaded into '{TABLE_NAME}'.")
    print(f"\n🎉 Hydrography loading complete!")


def _fetch_page(url, retries=5, backoff=15):
    for attempt in range(retries):
        try:
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            return response.json()
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as e:
            if attempt < retries - 1:
                wait = backoff * (attempt + 1)
                print(f"   ⚠️  Timeout (attempt {attempt + 1}/{retries}). Retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise
        except requests.HTTPError as e:
            print(f"   ❌ HTTP error: {e.response.status_code} — {url}")
            raise


def _write_batch(features, first_batch):
    gdf = gpd.GeoDataFrame.from_features(features, crs='EPSG:4326')
    gdf.columns = [col.lower() for col in gdf.columns]
    gdf = gdf.dropna(subset=['geometry'])
    if gdf.empty:
        return

    engine = create_engine(DB_URI, pool_pre_ping=True)
    gdf.to_postgis(
        TABLE_NAME, engine,
        if_exists='replace' if first_batch else 'append',
        index=True,
        index_label='id',
        chunksize=50000,
    )
    engine.dispose()


# =========================================================
# ENTRY POINT
# =========================================================
# File mode (recommended):
#   python load_hydrography.py
#   → uses the local GML file defined below
#
# API mode (fallback — no file needed):
#   Call load_hydrography() with no arguments
#
# Source: https://www.pdok.nl/introductie/-/article/waterschappen-hydrografie-inspire-geharmoniseerd-
# API:    https://api.pdok.nl/hwh/waterschappen-hydrografie/ogc/v1
# =========================================================
if __name__ == "__main__":
    load_hydrography(file_path='/Users/khushi/Downloads/Hydrography.gml')
