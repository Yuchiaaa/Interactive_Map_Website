import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os

load_dotenv()

# =========================================================
# DATABASE CONFIGURATION
# =========================================================
DB_URI = os.environ.get('DATABASE_URL')
if not DB_URI:
    raise ValueError("DATABASE_URL is not set. Please check your .env file.")

# Target table name in the PostGIS database.
# Stores pesticide measurement points with norm exceedance data,
# sourced from www.bestrijdingsmiddelenatlas.nl
TABLE_NAME = 'pesticides_measurements'

# =========================================================
# COORDINATE SYSTEM CONFIGURATION
# =========================================================
# Pesticides Atlas exports coordinates in the Dutch national grid system (RD New).
# We reproject to WGS84 (EPSG:4326) to stay consistent with all other
# layers in this pipeline (BRP, Kadaster, Natura2000, BAG, KRD).
SOURCE_CRS = 'EPSG:28992'   # RD New — standard for Dutch government datasets
TARGET_CRS = 'EPSG:4326'    # WGS84 — used by the web mapping frontend


def load_pesticides(file_paths, year=None):
    """
    Loads Pesticides Atlas (Bestrijdingsmiddelenatlas) norm exceedance data
    from one or more CSV exports into the PostGIS database.

    Source: www.bestrijdingsmiddelenatlas.nl
    Download path: Kaart > Overschrijdingen > Lijst stoffen > Per jaar > Nationaal

    Each row represents a single measurement at a monitoring station (meetpunt)
    for a specific substance (stof), including the norm class and exceedance ratio.

    Parameters
    ----------
    file_paths : str or list of str
        Path(s) to the downloaded CSV file(s).
        Multiple years can be passed as a list — the first file replaces the
        table, subsequent files are appended (same pattern as load_krd.py).

    year : int, optional
        Override the year for all records. Only needed if the CSV does not
        contain a 'JAAR' column (which it normally does).
    """

    # Normalize input: always work with a list of paths
    if isinstance(file_paths, str):
        file_paths = [file_paths]

    engine = create_engine(DB_URI)
    first_file = True  # Controls whether we REPLACE or APPEND the PostGIS table

    for file_path in file_paths:

        # ----------------------------------------------------------
        # STEP 1: Validate file exists
        # ----------------------------------------------------------
        if not os.path.exists(file_path):
            print(f"❌ Error: File not found at {file_path}")
            continue

        file_name = os.path.basename(file_path)
        print(f"\n⏳ Processing Pesticides Atlas file: {file_name}")

        try:
            # ----------------------------------------------------------
            # STEP 2: Reject duplicate years — check the DB before reading the file
            # ----------------------------------------------------------
            if year is not None:
                engine_check = create_engine(DB_URI, pool_pre_ping=True)
                with engine_check.connect() as conn:
                    table_exists = conn.execute(text(
                        "SELECT EXISTS ("
                        "  SELECT FROM information_schema.tables"
                        "  WHERE table_name = 'pesticides_measurements'"
                        ")"
                    )).scalar()

                    if table_exists and first_file:
                        already_loaded = conn.execute(
                            text("SELECT EXISTS (SELECT 1 FROM pesticides_measurements WHERE jaar = :year LIMIT 1)"),
                            {"year": int(year)},
                        ).scalar()
                        if already_loaded:
                            print(f"   ⚠️  Year {year} already exists in '{TABLE_NAME}'. Skipping to avoid duplicates.")
                            print(f"       Run truncate_pesticides() first if you want to reload.")
                            engine_check.dispose()
                            continue
                engine_check.dispose()

            # ----------------------------------------------------------
            # STEP 3: Read CSV
            # Pesticides Atlas exports use comma delimiter with dot decimals.
            # Some string fields contain quoted commas (e.g. CAS_NR "NVT, GROEP"),
            # which pandas handles automatically with quotechar='"'.
            # ----------------------------------------------------------
            df = pd.read_csv(file_path, sep=',', decimal='.', dtype=str)
            print(f"   📄 Loaded {len(df)} rows from CSV.")

            # ----------------------------------------------------------
            # STEP 4: Standardize column names to lowercase
            # ----------------------------------------------------------
            df.columns = [col.strip().lower() for col in df.columns]

            # ----------------------------------------------------------
            # STEP 5: Validate required columns are present
            # ----------------------------------------------------------
            required = ['xcoord_m', 'ycoord_m']
            missing = [c for c in required if c not in df.columns]
            if missing:
                print(f"   ❌ Missing required columns: {missing}")
                print(f"   Available columns: {list(df.columns)}")
                continue

            # ----------------------------------------------------------
            # STEP 6: Year handling
            # Priority 1: Internal 'jaar' column (standard in BMA exports)
            # Priority 2: Manual override via 'year' parameter
            # ----------------------------------------------------------
            if 'jaar' not in df.columns:
                if year is not None:
                    df['jaar'] = year
                    print(f"   📅 Year column not found — injected manually: {year}")
                else:
                    print("   ⚠️  No 'jaar' column found and no year override provided. 'jaar' will be NULL.")

            # ----------------------------------------------------------
            # STEP 7: Cast numeric columns to correct types
            # ----------------------------------------------------------
            int_cols = ['wbhcode', 'meetpunt_code', 'jaar', 'stof_nr_sam',
                        'normklas', 'klasse']
            float_cols = ['xcoord_m', 'ycoord_m', 'mate_normov']

            for col in int_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')

            for col in float_cols:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')

            # ----------------------------------------------------------
            # STEP 8: Drop rows with missing coordinates
            # ----------------------------------------------------------
            before = len(df)
            df = df.dropna(subset=['xcoord_m', 'ycoord_m'])
            dropped = before - len(df)
            if dropped > 0:
                print(f"   ⚠️  Dropped {dropped} rows with missing coordinates.")

            # ----------------------------------------------------------
            # STEP 9: Build Point geometry and reproject RD New → WGS84
            # ----------------------------------------------------------
            geometry = [Point(xy) for xy in zip(df['xcoord_m'], df['ycoord_m'])]
            gdf = gpd.GeoDataFrame(df, geometry=geometry, crs=SOURCE_CRS)
            gdf = gdf.to_crs(TARGET_CRS)
            print(f"   🌍 Reprojected {len(gdf)} measurement points from RD New → WGS84.")

            # ----------------------------------------------------------
            # STEP 10: Load into PostGIS
            # First file: 'replace' — clean slate with correct schema.
            # Subsequent files: 'append' — add rows for additional years.
            # ----------------------------------------------------------
            if_exists_strategy = 'replace' if first_file else 'append'
            print(f"   📥 Inserting {len(gdf)} records into '{TABLE_NAME}' (mode: {if_exists_strategy})...")

            gdf.to_postgis(
                TABLE_NAME,
                engine,
                if_exists=if_exists_strategy,
                index=True,
                index_label='id',
                chunksize=50000,
            )

            first_file = False
            print(f"   ✅ Success: {file_name} loaded into '{TABLE_NAME}'.")

        except Exception as e:
            print(f"   ❌ Pipeline failed for {file_name}: {e}")

    # ----------------------------------------------------------
    # STEP 11: Post-load schema repair
    # Ensure 'id' is a proper primary key with auto-increment.
    # Same pattern as load_krd.py and master_sync.py.
    # ----------------------------------------------------------
    print(f"\n⏳ Verifying schema for '{TABLE_NAME}'...")
    try:
        with engine.begin() as conn:
            conn.execute(text(
                f"ALTER TABLE {TABLE_NAME} ADD COLUMN IF NOT EXISTS id SERIAL PRIMARY KEY;"
            ))
        print(f"✅ Schema verified. '{TABLE_NAME}' is ready for spatial queries.")
    except Exception:
        # Primary key already exists — silently ignore
        pass

    print(f"\n🎉 Pesticides Atlas data loading complete!")


# =========================================================
# ENTRY POINT
# =========================================================
# INSTRUCTIONS:
#   1. Go to https://www.bestrijdingsmiddelenatlas.nl/atlas/1/1
#   2. Navigate to: Kaart > Overschrijdingen > Lijst stoffen > Per jaar > Nationaal
#   3. Select the desired year and download the CSV
#   4. Update the path(s) below and run: python load_pesticides.py
#
# To load multiple years, pass a list of file paths.
# The table will be replaced on the first file and appended for the rest.
# =========================================================
if __name__ == "__main__":

    pesticides_files = [
        {"path": '/Users/khushi/Desktop/Pesticides/P8_7_20260603_082113/P8_7_download overschrijdingen, lijst stoffen, per jaar  - nationaal.csv'},
        # {"path": "/path/to/P8_7_download_overschrijdingen_2023.csv"},
    ]

    if not pesticides_files or pesticides_files[0]["path"].startswith("/path/to/"):
        print("Pesticides Script ready.")
        print("Update the file path(s) in pesticides_files, then run again.")
    else:
        paths = [entry["path"] for entry in pesticides_files]
        load_pesticides(paths)
