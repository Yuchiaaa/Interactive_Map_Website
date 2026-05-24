import requests
import geopandas as gpd
from sqlalchemy import create_engine
import os
from dotenv import load_dotenv

load_dotenv()

DB_URI = os.environ.get('DATABASE_URL')
if not DB_URI:
    raise ValueError("DATABASE_URL is not set. Please check your .env file.")

BASE_URL = "https://api.pdok.nl/hwh/waterschappen-hydrografie/ogc/v1"

# Available INSPIRE collections:
# watercourse, drainagebasin, embankment, damorweir, lock, sluice,
# crossing, crossingline, crossingpoint
COLLECTION  = "watercourse"
TABLE_NAME  = "hydrography_watercourse"
PAGE_SIZE   = 1000
BATCH_PAGES = 10   # Write to DB every 10 pages (10,000 features)


def fetch_page(url):
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    return response.json()


def write_batch(features, first_batch):
    """Create a fresh DB connection per batch to avoid Tailscale timeout drops."""
    gdf = gpd.GeoDataFrame.from_features(features, crs='EPSG:4326')
    gdf.columns = [col.lower() for col in gdf.columns]
    gdf = gdf.dropna(subset=['geometry'])
    if gdf.empty:
        return
    # Fresh engine per write — avoids stale pooled connections over VPN
    engine = create_engine(DB_URI, pool_pre_ping=True)
    mode = 'replace' if first_batch else 'append'
    gdf.to_postgis(TABLE_NAME, engine, if_exists=mode, index=True, index_label='id')
    engine.dispose()


def load_hydrography(collection=COLLECTION):
    """
    Streams the OGC API Features cursor-based pagination in batches and writes
    each batch to PostGIS as it arrives. Creates a fresh DB connection per batch
    to survive VPN/Tailscale connection drops between writes.
    """
    print(f"Starting hydrography load: collection='{collection}' → table='{TABLE_NAME}'")

    first_url  = f"{BASE_URL}/collections/{collection}/items?f=json&limit={PAGE_SIZE}"
    next_url   = first_url
    page       = 1
    total      = 0
    batch      = []
    first_write = True

    while next_url:
        print(f"  Fetching page {page} ...", flush=True)
        data = fetch_page(next_url)
        features = data.get('features', [])
        batch.extend(features)
        total += len(features)

        # Follow cursor to next page
        next_url = next((l['href'] for l in data.get('links', []) if l.get('rel') == 'next'), None)
        page += 1

        # Flush batch to DB every BATCH_PAGES pages
        if len(batch) >= PAGE_SIZE * BATCH_PAGES:
            print(f"  Writing batch to DB (total so far: {total}) ...")
            write_batch(batch, first_write)
            first_write = False
            batch = []

    # Write remaining features
    if batch:
        print(f"  Writing final batch to DB (total: {total}) ...")
        write_batch(batch, first_write)

    print(f"Success: {total} features loaded into '{TABLE_NAME}'.")


if __name__ == "__main__":
    load_hydrography()
