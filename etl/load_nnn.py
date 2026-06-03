import os
import time
import tempfile
import requests
import geopandas as gpd
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
# ATOM DOWNLOAD CONFIGURATION
# =========================================================
# Source: https://www.nationaalgeoregister.nl/geonetwork/srv/dut/catalog.search#/metadata/c7d8d77b-8c47-4309-8c58-9b12b086407f
# ATOM feed: https://service.pdok.nl/provincies/natuurnetwerk-nederland/atom/index.xml
DOWNLOAD_URL = (
    "https://service.pdok.nl/provincies/natuurnetwerk-nederland"
    "/atom/downloads/inspire-pv-ps.nlps-nnn.gml"
)

TABLE_NAME = 'nnn_areas'

# Columns to keep from the raw INSPIRE GML and their English translations.
# All other columns are either 100% NULL or constant across all rows
# (namespace='nlps-nnn', language='nld') and are dropped.
COLUMN_MAP = {
    'gml_id':                     'gml_id',
    'localid':                    'site_id',
    'legalfoundationdate':        'legal_foundation_date',
    'text':                       'name',
    'percentageunderdesignation': 'percentage_under_designation',
    'geometry':                   'geometry',
}


# =========================================================
# LOAD
# =========================================================

def load_nnn():
    """
    Download the Natuurnetwerk Nederland (NNN) INSPIRE GML from the PDOK ATOM
    feed, clean and reproject to WGS84, and write to the 'nnn_areas' PostGIS table.

    Source: https://www.nationaalgeoregister.nl/geonetwork/srv/dut/catalog.search#/metadata/c7d8d77b-8c47-4309-8c58-9b12b086407f
    ATOM feed: https://service.pdok.nl/provincies/natuurnetwerk-nederland/atom/index.xml

    The GML (~194 MB) is streamed to a temporary file, processed, then deleted.
    No local file is left behind after the load completes.
    """

    # ----------------------------------------------------------
    # STEP 1: Reject duplicate loads — check the DB before downloading
    # ----------------------------------------------------------
    engine_check = create_engine(DB_URI, pool_pre_ping=True)
    with engine_check.connect() as conn:
        table_exists = conn.execute(text(
            "SELECT EXISTS ("
            "  SELECT FROM information_schema.tables"
            "  WHERE table_name = 'nnn_areas'"
            ")"
        )).scalar()

        if table_exists:
            already_loaded = conn.execute(
                text("SELECT EXISTS (SELECT 1 FROM nnn_areas LIMIT 1)")
            ).scalar()
            if already_loaded:
                print(f"⚠️  '{TABLE_NAME}' already contains data. Skipping to avoid duplicates.")
                print(f"    Run truncate_nnn() first if you want to reload.")
                engine_check.dispose()
                return
    engine_check.dispose()

    print(f"⏳ Starting NNN load → '{TABLE_NAME}'")

    tmp_path = None
    try:
        # ----------------------------------------------------------
        # STEP 2: Stream GML download to a temporary file
        # ----------------------------------------------------------
        with tempfile.NamedTemporaryFile(suffix='.gml', delete=False) as tmp:
            tmp_path = tmp.name

        _download_gml(tmp_path)

        # ----------------------------------------------------------
        # STEP 3: Read GML with pyogrio (fast reader)
        # ----------------------------------------------------------
        print(f"   📖 Reading GML...")
        gdf = gpd.read_file(tmp_path, engine="pyogrio")
        print(f"   🗂️  Features: {len(gdf):,} | Raw columns: {len(gdf.columns)}")

        # ----------------------------------------------------------
        # STEP 4: Reproject to WGS84 (EPSG:4326)
        # NNN INSPIRE GML uses ETRS89 LAEA (EPSG:3035).
        # All layers in this pipeline use EPSG:4326 for the web frontend.
        # ----------------------------------------------------------
        if gdf.crs is None or gdf.crs.to_epsg() != 4326:
            print(f"   🌍 Reprojecting {gdf.crs} → EPSG:4326...")
            gdf = gdf.to_crs(epsg=4326)

        # ----------------------------------------------------------
        # STEP 5: Drop empty/redundant columns and rename to clean English
        # Dropped columns are confirmed 100% NULL or constant across all rows:
        # sitedesignation, legalfoundationdocument, nativeness, namestatus,
        # sourceofname, pronunciation, script, siteprotectionclassification,
        # legalfoundationdate_, namespace (always 'nlps-nnn'), language (always 'nld')
        # ----------------------------------------------------------
        gdf = _clean(gdf)
        print(f"   🏷️  Columns after cleaning: {list(gdf.columns)}")

        # ----------------------------------------------------------
        # STEP 6: Repair and drop invalid geometries
        # ----------------------------------------------------------
        before = len(gdf)
        gdf['geometry'] = gdf['geometry'].make_valid()
        gdf = gdf.dropna(subset=['geometry'])
        dropped = before - len(gdf)
        if dropped > 0:
            print(f"   ⚠️  Dropped {dropped} rows with invalid/null geometry.")

        # ----------------------------------------------------------
        # STEP 7: Write to PostGIS
        # ----------------------------------------------------------
        engine = create_engine(
            DB_URI,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 300, "options": "-c statement_timeout=0"},
        )
        print(f"   📥 Inserting {len(gdf):,} records into '{TABLE_NAME}'...")
        gdf.to_postgis(
            TABLE_NAME, engine,
            if_exists='replace',
            index=True,
            index_label='id',
            chunksize=50000,
        )
        engine.dispose()
        print(f"   ✅ Success: {len(gdf):,} NNN areas loaded into '{TABLE_NAME}'.")

    except Exception as e:
        print(f"   ❌ Pipeline failed: {e}")

    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)

    print(f"\n🎉 NNN loading complete!")


def _download_gml(dest_path, retries=5, backoff=15):
    """Stream the NNN GML (~194 MB) to disk with progress and retry on failure."""
    print(f"   🌐 Downloading NNN GML from PDOK ATOM feed...")

    for attempt in range(retries):
        try:
            with requests.get(DOWNLOAD_URL, stream=True, timeout=120) as r:
                r.raise_for_status()
                total      = int(r.headers.get('content-length', 0))
                downloaded = 0
                with open(dest_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            print(
                                f"   {downloaded // (1024*1024)} / {total // (1024*1024)} MB"
                                f"  ({downloaded / total * 100:.1f}%)",
                                end='\r', flush=True,
                            )
            print(f"\n   ✅ Download complete.")
            return
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError):
            if attempt < retries - 1:
                wait = backoff * (attempt + 1)
                print(f"\n   ⚠️  Timeout (attempt {attempt + 1}/{retries}). Retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise
        except requests.HTTPError as e:
            print(f"\n   ❌ HTTP error: {e.response.status_code} — {DOWNLOAD_URL}")
            raise


def _clean(gdf):
    """
    Lowercase all column names, keep only meaningful columns, and rename to
    clean English names via COLUMN_MAP.
    """
    gdf.columns = [col.lower() for col in gdf.columns]
    cols_to_keep = [c for c in COLUMN_MAP if c in gdf.columns]
    return gdf[cols_to_keep].copy().rename(columns=COLUMN_MAP)


# =========================================================
# ENTRY POINT
# =========================================================
# INSTRUCTIONS:
#   No file download needed — data is streamed directly from the PDOK ATOM feed.
#   Run: python load_nnn.py
#
#   Source: https://www.nationaalgeoregister.nl/geonetwork/srv/dut/catalog.search#/metadata/c7d8d77b-8c47-4309-8c58-9b12b086407f
#   ATOM feed: https://service.pdok.nl/provincies/natuurnetwerk-nederland/atom/index.xml
# =========================================================
if __name__ == "__main__":
    load_nnn()
