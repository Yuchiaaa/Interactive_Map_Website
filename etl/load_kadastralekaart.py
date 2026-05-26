import os
import time
import requests
import geopandas as gpd
from shapely.geometry import shape
from sqlalchemy import create_engine, text, Integer, Float, String
from dotenv import load_dotenv

# Load environment variables securely from the .env file
load_dotenv()

# Database Configuration securely loaded from the environment
DB_URI = os.environ.get('DATABASE_URL')
if not DB_URI:
    raise ValueError("DATABASE_URL is not set. Please check your .env file.")

# OGC API Features endpoint (from PDOK nationaalgeoregister.nl)
# Source: https://www.nationaalgeoregister.nl/geonetwork/srv/dut/catalog.search#/metadata/a29917b9-3426-4041-a11b-69bcb2256904
OGC_API_BASE = "https://api.pdok.nl/kadaster/brk-kadastrale-kaart/ogc/v1"

TABLE_NAME = "kadastralekaart_perceel"
COLLECTION = "perceel"
PAGE_SIZE  = 1000  # features per API request
BATCH_SIZE = 5000  # rows written to DB at once

# Explicit column types — prevents pandas from guessing int vs float per batch
DTYPE = {
    'gemeente_code':     Integer(),
    'perceelnummer':     Integer(),
    'kadastralegrootte': Float(),
}

# Mapping of API property names → clean DB column names
# Confirmed from: GET /collections/perceel/items?limit=1
COLUMN_MAP = {
    'identificatie_lokaal_id':   'identificatie',
    'kadastrale_gemeente_code':  'gemeente_code',
    'kadastrale_gemeente_waarde':'gemeente',
    'sectie':                    'sectie',
    'perceelnummer':             'perceelnummer',
    'kadastrale_grootte_waarde': 'kadastralegrootte',
    'soort_grootte_waarde':      'soortgrootte',
    'status_historie_waarde':    'status',
}

# Dutch provinces with their bounding boxes (west, south, east, north — WGS84)
# Load one at a time using: python load_kadastralekaart.py <province_name>
PROVINCES = {
    'groningen':     (6.50, 52.80, 7.30, 53.55),
    'friesland':     (4.70, 52.70, 6.40, 53.55),
    'drenthe':       (6.10, 52.40, 7.10, 53.15),
    'overijssel':    (5.80, 51.90, 7.10, 52.80),
    'flevoland':     (5.10, 52.20, 5.95, 52.80),
    'gelderland':    (4.95, 51.70, 6.90, 52.50),
    'utrecht':       (4.70, 51.90, 5.60, 52.30),
    'noord-holland': (4.50, 52.15, 5.35, 52.95),
    'zuid-holland':  (3.80, 51.70, 4.95, 52.35),
    'zeeland':       (3.30, 51.20, 4.30, 51.80),
    'noord-brabant': (3.95, 51.25, 5.75, 51.90),
    'limburg':       (5.55, 50.70, 6.30, 51.80),
}


def fetch_page(url, params=None, retries=5, backoff=15):
    for attempt in range(retries):
        try:
            response = requests.get(url, params=params, timeout=90)
            response.raise_for_status()
            return response.json()
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as e:
            if attempt < retries - 1:
                wait = backoff * (attempt + 1)
                print(f"  Timeout (attempt {attempt + 1}/{retries}). Retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise


def load_province(province_name, first_province=False):
    """
    Loads cadastral parcels for a single province into PostGIS.
    Uses the OGC API bbox filter to only fetch parcels in that province.

    Args:
        province_name:  Key from PROVINCES dict (e.g. 'noord-brabant')
        first_province: If True, replaces the table. If False, appends.
    """
    if province_name not in PROVINCES:
        print(f"Unknown province '{province_name}'. Available: {list(PROVINCES.keys())}")
        return 0

    bbox = PROVINCES[province_name]
    bbox_str = ','.join(str(c) for c in bbox)

    engine = create_engine(DB_URI, pool_pre_ping=True)

    url    = f"{OGC_API_BASE}/collections/{COLLECTION}/items"
    params = {'f': 'json', 'limit': PAGE_SIZE, 'bbox': bbox_str}

    # Only replace (recreate) the table if explicitly told to AND the table is empty
    engine_check = create_engine(DB_URI, pool_pre_ping=True)
    with engine_check.connect() as conn:
        try:
            existing = conn.execute(text(f"SELECT COUNT(*) FROM {TABLE_NAME}")).scalar()
        except Exception:
            existing = 0
    engine_check.dispose()

    total_loaded = 0
    batch        = []
    first_write  = first_province and (existing == 0)  # only replace if table is empty

    print(f"\n[{province_name.upper()}] Fetching bbox={bbox_str}...")

    while url:
        data     = fetch_page(url, params)
        features = data.get('features', [])
        batch.extend(features)

        url    = None
        params = None
        for link in data.get('links', []):
            if link.get('rel') == 'next':
                url = link['href']
                break

        if len(batch) >= BATCH_SIZE or (not url and batch):
            gdf = _build_gdf(batch)
            if not gdf.empty:
                gdf.to_postgis(
                    TABLE_NAME, engine,
                    if_exists='replace' if first_write else 'append',
                    index=False,
                    dtype=DTYPE
                )
                total_loaded += len(gdf)
                first_write   = False
                print(f"  {province_name}: {total_loaded:,} parcels written...", flush=True)
            batch = []

    # Ensure spatial index exists after each province
    with engine.begin() as conn:
        conn.execute(text(
            f"CREATE INDEX IF NOT EXISTS idx_{TABLE_NAME}_geom "
            f"ON {TABLE_NAME} USING GIST (geometry);"
        ))

    engine.dispose()
    print(f"[{province_name.upper()}] Done — {total_loaded:,} parcels loaded.")
    return total_loaded


def load_kadastralekaart(provinces=None):
    """
    Loads cadastral parcels province by province into the shared PostGIS database.

    Args:
        provinces: List of province names to load. Defaults to all 12.
                   Example: ['noord-brabant', 'gelderland']
    """
    targets = provinces or list(PROVINCES.keys())
    grand_total = 0

    print(f"Loading {len(targets)} province(s): {targets}")
    print(f"Target database: {DB_URI.split('@')[-1]}")  # print host/db only, not credentials

    for i, province in enumerate(targets):
        count = load_province(province, first_province=(i == 0))
        grand_total += count

    print(f"\nAll done — {grand_total:,} total parcels in '{TABLE_NAME}'.")


def _build_gdf(features):
    """Converts a list of GeoJSON features into a clean GeoDataFrame,
    renaming API property names to clean DB column names via COLUMN_MAP."""
    rows = []
    for f in features:
        props = f.get('properties') or {}
        geom  = f.get('geometry')
        if not geom:
            continue
        row = {db_col: props.get(api_col) for api_col, db_col in COLUMN_MAP.items()}
        row['geometry'] = shape(geom)
        rows.append(row)

    if not rows:
        return gpd.GeoDataFrame()

    # OGC API Features returns GeoJSON which is always WGS84 (EPSG:4326)
    gdf = gpd.GeoDataFrame(rows, geometry='geometry', crs='EPSG:4326')

    gdf['geometry'] = gdf['geometry'].make_valid()
    gdf = gdf.dropna(subset=['geometry'])
    return gdf


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        # Load specific provinces passed as arguments
        # Example: python load_kadastralekaart.py noord-brabant gelderland
        requested = [p.lower() for p in sys.argv[1:]]
        load_kadastralekaart(provinces=requested)
    else:
        # Load all provinces
        load_kadastralekaart()
