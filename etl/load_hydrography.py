import os
import time
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
# OGC API CONFIGURATION
# =========================================================
# Source: https://www.pdok.nl/introductie/-/article/waterschappen-hydrografie-inspire-geharmoniseerd-
# Endpoint: PDOK OGC API Features > Waterschappen Hydrografie
BASE_URL    = "https://api.pdok.nl/hwh/waterschappen-hydrografie/ogc/v1"
COLLECTION  = "watercourse"
TABLE_NAME  = "hydrography_watercourse"
PAGE_SIZE   = 1000   # features per API request
BATCH_PAGES = 10     # flush to DB every 10 pages (10 000 features)


# =========================================================
# LOAD
# =========================================================

def load_hydrography(collection=COLLECTION):
    """
    Stream the PDOK Waterschappen Hydrografie OGC API into the
    'hydrography_watercourse' PostGIS table.

    Source: https://www.pdok.nl/introductie/-/article/waterschappen-hydrografie-inspire-geharmoniseerd-
    Endpoint: GET /collections/watercourse/items

    Features are fetched page by page and flushed to PostGIS in batches to
    keep memory usage low and survive VPN/Tailscale connection drops.
    A fresh DB engine is created per batch write for the same reason.
    """

    # ----------------------------------------------------------
    # STEP 1: Reject duplicate loads — check the DB before hitting the API
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

    print(f"⏳ Starting hydrography load: collection='{collection}' → '{TABLE_NAME}'")

    # ----------------------------------------------------------
    # STEP 2: Stream OGC API pages and flush batches to PostGIS
    # ----------------------------------------------------------
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

    # ----------------------------------------------------------
    # STEP 3: Flush the final partial batch
    # ----------------------------------------------------------
    if batch:
        print(f"   📥 Writing final batch to DB (total: {total:,})...")
        _write_batch(batch, first_write)

    print(f"\n✅ Done — {total:,} features loaded into '{TABLE_NAME}'.")
    print(f"\n🎉 Hydrography loading complete!")


def _fetch_page(url, retries=5, backoff=15):
    """Fetch one OGC API page with exponential retry on timeout or connection error."""
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
    """
    Write a list of GeoJSON features to PostGIS.
    Creates a fresh DB engine per call to survive VPN/Tailscale connection drops
    between batch writes on long-running loads.
    """
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
# INSTRUCTIONS:
#   No file download needed — data is streamed directly from the PDOK OGC API.
#   Run: python load_hydrography.py
#
#   Source: https://www.pdok.nl/introductie/-/article/waterschappen-hydrografie-inspire-geharmoniseerd-
#   Available collections: watercourse, drainagebasin, embankment, damorweir,
#                          lock, sluice, crossing, crossingline, crossingpoint
# =========================================================
if __name__ == "__main__":
    load_hydrography()
