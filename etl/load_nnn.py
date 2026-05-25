import os
import tempfile
import requests
import geopandas as gpd
from sqlalchemy import create_engine
from dotenv import load_dotenv

load_dotenv()

DB_URI = os.environ.get('DATABASE_URL')
if not DB_URI:
    raise ValueError("DATABASE_URL is not set. Please check your .env file.")

# ATOM download service:
# https://service.pdok.nl/provincies/natuurnetwerk-nederland/atom/index.xml
DOWNLOAD_URL = "https://service.pdok.nl/provincies/natuurnetwerk-nederland/atom/downloads/inspire-pv-ps.nlps-nnn.gml"

# WMS (visualization only, use as tile layer in the frontend):
# https://service.pdok.nl/provincies/natuurnetwerk-nederland/wms/v1_0
# Layers: PS.ProtectedSite | PS.ProtectedSitesSpecialAreaOfConservation

TABLE_NAME = "nnn_areas"

# Columns to keep from the raw INSPIRE GML and their English translations.
# All other columns are either 100% NULL or contain the same value on every row
# (namespace='nlps-nnn', language='nld') and are dropped.
COLUMN_MAP = {
    'gml_id':                    'gml_id',
    'localid':                   'site_id',
    'legalfoundationdate':       'legal_foundation_date',
    'text':                      'name',
    'percentageunderdesignation':'percentage_under_designation',
    'geometry':                  'geometry',
}


def download_gml(dest_path):
    """Streams the GML download to disk with a progress indicator (~194 MB)."""
    print("Downloading NNN GML from PDOK ATOM feed...")
    response = requests.get(DOWNLOAD_URL, stream=True, timeout=120)
    response.raise_for_status()

    total = int(response.headers.get('content-length', 0))
    downloaded = 0
    chunk_size = 1024 * 1024  # 1 MB chunks

    with open(dest_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=chunk_size):
            f.write(chunk)
            downloaded += len(chunk)
            if total:
                pct = downloaded / total * 100
                print(f"  {downloaded // (1024*1024)} / {total // (1024*1024)} MB  ({pct:.1f}%)", end='\r', flush=True)

    print(f"\nDownload complete: {dest_path}")


def clean(gdf):
    """
    Drops empty/redundant columns and renames remaining columns to clean English.

    Dropped columns (confirmed 100% NULL or constant across all 46,792 rows):
      sitedesignation, legalfoundationdocument, nativeness, namestatus,
      sourceofname, pronunciation, script, siteprotectionclassification,
      legalfoundationdate_, namespace (always 'nlps-nnn'), language (always 'nld')

    Kept and renamed:
      gml_id                    → gml_id
      localid                   → site_id
      legalfoundationdate       → legal_foundation_date
      text                      → name  (Dutch area name, e.g. 'Nationaal Park Zuid-Kennemerland')
      percentageunderdesignation→ percentage_under_designation
      geometry                  → geometry
    """
    # Lowercase all column names first
    gdf.columns = [col.lower() for col in gdf.columns]

    # Keep only meaningful columns
    cols_to_keep = [c for c in COLUMN_MAP.keys() if c in gdf.columns]
    gdf = gdf[cols_to_keep].copy()

    # Rename to clean English
    gdf = gdf.rename(columns=COLUMN_MAP)

    return gdf


def load_nnn():
    """
    Downloads the Nature Network Netherlands (Natuurnetwerk Nederland) INSPIRE
    GML from the PDOK ATOM download service, cleans and reprojects to WGS84,
    and writes to PostGIS table 'nnn_areas'.

    Source: PDOK / BIJ12 — Nature Network Netherlands Provinces (INSPIRE harmonized)
    ATOM feed: https://service.pdok.nl/provincies/natuurnetwerk-nederland/atom/index.xml
    """
    with tempfile.NamedTemporaryFile(suffix='.gml', delete=False) as tmp:
        tmp_path = tmp.name

    try:
        download_gml(tmp_path)

        print("Reading GML with geopandas...")
        gdf = gpd.read_file(tmp_path)
        print(f"  CRS: {gdf.crs}")
        print(f"  Features: {len(gdf)}  |  Raw columns: {len(gdf.columns)}")

        # Reproject from EPSG:3035 (ETRS89 LAEA) to WGS84 for web mapping
        if gdf.crs is None or gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(epsg=4326)

        # Clean: drop empty/redundant columns and rename to English
        gdf = clean(gdf)
        print(f"  Columns after cleaning: {list(gdf.columns)}")

        # Repair invalid geometries and drop null geometries
        gdf['geometry'] = gdf['geometry'].make_valid()
        gdf = gdf.dropna(subset=['geometry'])

        print(f"Inserting {len(gdf)} records into '{TABLE_NAME}'...")
        engine = create_engine(DB_URI, pool_pre_ping=True)
        gdf.to_postgis(TABLE_NAME, engine, if_exists='replace', index=True, index_label='id')
        engine.dispose()

        print(f"Success: NNN areas imported into '{TABLE_NAME}'.")

    except Exception as e:
        print(f"Failed to load NNN data: {e}")

    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


if __name__ == "__main__":
    load_nnn()
