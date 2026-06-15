import os
import time
import zipfile
import tempfile
import requests
import geopandas as gpd
from sqlalchemy import create_engine, text, Integer, Float
from dotenv import load_dotenv

load_dotenv()

# =========================================================
# DATABASE CONFIGURATION
# =========================================================
DB_URI = os.environ.get('DATABASE_URL')
if not DB_URI:
    raise ValueError("DATABASE_URL is not set. Please check your .env file.")

TABLE_NAME = 'kadastralekaart_perceel'

# =========================================================
# API CONFIGURATION
# =========================================================
# PDOK Download API v5_0 — async job-based, delivers a ZIP containing GML.
# Workflow: POST /full/custom → poll status → download ZIP → extract GML → load.
API_BASE    = 'https://api.pdok.nl/kadaster/kadastralekaart/download/v5_0'
API_PAYLOAD = {'format': 'gml', 'featuretypes': ['perceel']}

# =========================================================
# SCHEMA CONFIGURATION
# =========================================================
DTYPE = {
    'gemeente_code':     Integer(),
    'perceelnummer':     Integer(),
    'kadastralegrootte': Float(),
}

# GML delivers nested pipe-delimited column names — map them to clean DB names.
# Only the columns listed here are kept; everything else is dropped before writing.
COLUMN_MAP = {
    'kadastraleAanduiding|TypeKadastraleAanduiding|kadastraleGemeente|KadastraleGemeente|code':   'gemeente_code',
    'kadastraleAanduiding|TypeKadastraleAanduiding|kadastraleGemeente|KadastraleGemeente|waarde': 'gemeente',
    'kadastraleGrootte|TypeOppervlak|waarde':                                                      'kadastralegrootte',
    'kadastraleGrootte|TypeOppervlak|soortGrootte|SoortGrootte|waarde':                            'soortgrootte',
}

# Columns to keep in the final table (everything else is dropped).
KEEP_COLUMNS = ['identificatie', 'sectie', 'perceelnummer',
                'gemeente_code', 'gemeente', 'kadastralegrootte', 'soortgrootte', 'geometry']


# =========================================================
# LOAD
# =========================================================

def load_kadastralekaart():
    """
    Download the Kadastrale Kaart (BRK perceel) dataset from the PDOK Download
    API and write it to the 'kadastralekaart_perceel' PostGIS table.

    Source: https://api.pdok.nl/kadaster/kadastralekaart/download/v5_0/ui/
    Feature type: perceel (cadastral parcel boundaries)

    Flow:
      1. POST /full/custom  → PDOK queues an async export job (~2-3 min)
      2. Poll /status       → wait for COMPLETED
      3. Download ZIP       → extract GML
      4. Reproject + clean  → write to PostGIS

    Fallback:
      If the API is unreachable or the job fails, existing data in the DB is
      preserved and a clear error message is printed. No data is ever wiped
      before a successful download.
    """

    print(f"⏳ Starting Kadastrale Kaart load → '{TABLE_NAME}'")

    # ----------------------------------------------------------
    # STEP 1: Reject duplicate loads — check the DB first
    # ----------------------------------------------------------
    engine_check = create_engine(DB_URI, pool_pre_ping=True)
    with engine_check.connect() as conn:
        table_exists = conn.execute(text(
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = :t)"
        ), {'t': TABLE_NAME}).scalar()

        if table_exists:
            already_loaded = conn.execute(
                text(f"SELECT EXISTS (SELECT 1 FROM {TABLE_NAME} LIMIT 1)")
            ).scalar()
            if already_loaded:
                print(f"⚠️  '{TABLE_NAME}' already contains data. Skipping to avoid duplicates.")
                print(f"    Run truncate_kadastralekaart() first if you want to reload.")
                engine_check.dispose()
                return
    engine_check.dispose()

    tmp_dir = None
    try:
        # ----------------------------------------------------------
        # STEP 2: Submit async download job to PDOK API
        # ----------------------------------------------------------
        print(f"   🌐 Submitting download job to PDOK API...")
        try:
            resp = requests.post(
                f'{API_BASE}/full/custom',
                json=API_PAYLOAD,
                headers={'Accept': 'application/json', 'Content-Type': 'application/json'},
                timeout=30,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"   ❌ API unreachable: {e}")
            print(f"   ℹ️  Existing data in '{TABLE_NAME}' has been preserved.")
            return

        job_id = resp.json().get('downloadRequestId')
        status_url = f'{API_BASE}/full/custom/{job_id}/status'
        print(f"   🔄 Job ID: {job_id}")

        # ----------------------------------------------------------
        # STEP 3: Poll until COMPLETED (PDOK typically takes 2-5 min)
        # ----------------------------------------------------------
        print(f"   ⏳ Waiting for PDOK to compile the export (this takes 2–5 minutes)...")
        download_href = None
        for attempt in range(60):
            time.sleep(10)
            try:
                s = requests.get(status_url, headers={'Accept': 'application/json'}, timeout=30)
                s.raise_for_status()
                data = s.json()
            except requests.RequestException as e:
                print(f"   ⚠️  Status poll failed (attempt {attempt+1}): {e}")
                continue

            status   = data.get('status')
            progress = data.get('progress', 0)
            print(f"   {status} ({progress}%)", end='\r', flush=True)

            if status == 'COMPLETED':
                download_href = data['_links']['download']['href']
                print(f"\n   ✅ Export ready.")
                break
            elif status == 'FAILED':
                print(f"\n   ❌ PDOK job failed. Existing DB data preserved.")
                return
        else:
            print(f"\n   ❌ Timed out waiting for PDOK job. Existing DB data preserved.")
            return

        # ----------------------------------------------------------
        # STEP 4: Download the ZIP to a temp directory
        # ----------------------------------------------------------
        download_url = f'https://api.pdok.nl{download_href}'
        print(f"   📥 Downloading ZIP...")
        tmp_dir = tempfile.mkdtemp(prefix='kadastralekaart_')
        zip_path = os.path.join(tmp_dir, 'extract.zip')

        try:
            with requests.get(download_url, stream=True, timeout=300) as r:
                r.raise_for_status()
                total      = int(r.headers.get('content-length', 0))
                downloaded = 0
                with open(zip_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            print(f"   {downloaded // (1024*1024)} / {total // (1024*1024)} MB"
                                  f"  ({downloaded / total * 100:.1f}%)", end='\r', flush=True)
            print(f"\n   ✅ Download complete.")
        except requests.RequestException as e:
            print(f"\n   ❌ Download failed: {e}. Existing DB data preserved.")
            return

        # ----------------------------------------------------------
        # STEP 5: Extract ZIP and find the GML file
        # ----------------------------------------------------------
        print(f"   📦 Extracting ZIP...")
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp_dir)

        gml_path = None
        for root, _, files in os.walk(tmp_dir):
            for f in files:
                if f.lower().endswith('.gml'):
                    gml_path = os.path.join(root, f)
                    break
            if gml_path:
                break

        if not gml_path:
            print(f"   ❌ No GML file found in the ZIP. Existing DB data preserved.")
            return
        print(f"   📄 Found: {os.path.basename(gml_path)}")

        # ----------------------------------------------------------
        # STEP 6: Read GML
        # ----------------------------------------------------------
        print(f"   📖 Reading GML (this may take a few minutes for the full NL dataset)...")
        gdf = gpd.read_file(gml_path, engine='pyogrio')
        print(f"   🗂️  Features: {len(gdf):,} | Columns: {list(gdf.columns)}")

        # ----------------------------------------------------------
        # STEP 7: Standardize column names and drop unneeded columns
        # GML uses pipe-delimited nested names that exceed PostgreSQL's 63-char
        # limit and cause DuplicateColumn errors — rename first, then keep only
        # the columns we actually need.
        # ----------------------------------------------------------
        rename = {raw: clean for raw, clean in COLUMN_MAP.items() if raw in gdf.columns}
        if rename:
            gdf = gdf.rename(columns=rename)
        keep = [c for c in KEEP_COLUMNS if c in gdf.columns]
        gdf = gdf[keep]

        # ----------------------------------------------------------
        # STEP 8: Reproject to WGS84 (EPSG:4326)
        # GML from PDOK BRK uses RD New (EPSG:28992).
        # ----------------------------------------------------------
        if gdf.crs is None or gdf.crs.to_epsg() != 4326:
            print(f"   🌍 Reprojecting {gdf.crs} → EPSG:4326...")
            gdf = gdf.to_crs(epsg=4326)

        # ----------------------------------------------------------
        # STEP 9: Repair and drop invalid geometries
        # ----------------------------------------------------------
        before = len(gdf)
        gdf['geometry'] = gdf['geometry'].make_valid()
        gdf = gdf.dropna(subset=['geometry'])
        dropped = before - len(gdf)
        if dropped > 0:
            print(f"   ⚠️  Dropped {dropped} rows with invalid/null geometry.")

        # ----------------------------------------------------------
        # STEP 10: Write to PostGIS
        # Only replace after a successful download — never wipe first.
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
            index=False,
            dtype=DTYPE,
            chunksize=50000,
        )

        # ----------------------------------------------------------
        # STEP 11: Spatial index
        # ----------------------------------------------------------
        with engine.begin() as conn:
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS idx_{TABLE_NAME}_geom "
                f"ON {TABLE_NAME} USING GIST (geometry);"
            ))
        engine.dispose()
        print(f"   ✅ Success: {len(gdf):,} cadastral parcels loaded into '{TABLE_NAME}'.")

    except Exception as e:
        print(f"   ❌ Pipeline failed: {e}")
        print(f"   ℹ️  Existing data in '{TABLE_NAME}' has been preserved.")

    finally:
        if tmp_dir and os.path.exists(tmp_dir):
            import shutil
            shutil.rmtree(tmp_dir, ignore_errors=True)

    print(f"\n🎉 Kadastrale Kaart loading complete!")


# =========================================================
# ENTRY POINT
# =========================================================
# INSTRUCTIONS:
#   No file download needed — data is fetched directly from the PDOK Download API.
#   Run: python load_kadastralekaart.py
#
#   Source: https://api.pdok.nl/kadaster/kadastralekaart/download/v5_0/ui/
#   Feature type: perceel (cadastral parcel boundaries)
#
#   The API takes 2–5 minutes to compile the full Netherlands export.
#   If the API is unreachable, existing DB data is preserved as fallback.
# =========================================================
if __name__ == "__main__":
    load_kadastralekaart()
