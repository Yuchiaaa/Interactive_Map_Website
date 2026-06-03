import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv

load_dotenv()

# =========================================================
# DATABASE CONFIGURATION
# =========================================================
DB_URI = os.environ.get('DATABASE_URL')
if not DB_URI:
    raise ValueError("DATABASE_URL is not set. Please check your .env file.")

# Target table name in the PostGIS database.
# Stores livestock farm locations with emission figures (NH3, fijnstof, geur),
# sourced from https://krd.igoview.nl/
TABLE_NAME = 'krd_farms'

# =========================================================
# COORDINATE SYSTEM CONFIGURATION
# =========================================================
# KRD exports coordinates in the Dutch national grid system (RD New).
# We reproject to WGS84 (EPSG:4326) to stay consistent with all other
# layers in this pipeline (BRP, Kadaster, Natura2000, BAG).
SOURCE_CRS = 'EPSG:28992'   # RD New — standard for Dutch government datasets
TARGET_CRS = 'EPSG:4326'    # WGS84 — used by the web mapping frontend


def _detect_coordinate_columns(columns):
    """
    Detects which columns contain x and y coordinates.
    Handles KRD export column names like 'BAG VBO X', 'Gem. emissie X', 'x', etc.
    Returns a tuple (x_col, y_col) or raises ValueError if not found.
    """
    columns_lower = [c.lower() for c in columns]

    x_candidates = ['x', 'x_coord', 'coordinaat_x', 'rd_x', 'xcoord', 'bag vbo x', 'gem. emissie x']
    y_candidates = ['y', 'y_coord', 'coordinaat_y', 'rd_y', 'ycoord', 'bag vbo y', 'gem. emissie y']

    x_col = y_col = None
    for i, col in enumerate(columns_lower):
        if col in x_candidates and x_col is None:
            x_col = columns[i]
        if col in y_candidates and y_col is None:
            y_col = columns[i]

    if x_col is None or y_col is None:
        raise ValueError(
            f"Could not detect coordinate columns.\n"
            f"Available columns: {list(columns)}\n"
            f"Expected one of {x_candidates} for X and {y_candidates} for Y."
        )

    return x_col, y_col


# =========================================================
# LOAD
# =========================================================

def load_krd(file_path, province=None):
    """
    Load one KRD livestock farm export into the 'krd_farms' PostGIS table.

    Source: https://krd.igoview.nl/
    Download path: KRD > Veehouderijen > Totaaloverzicht veehouderijen > Export CSV/Excel

    Call this function once per province file. Each province is appended to the
    shared table — the table is created on the first load and reused thereafter.

    Parameters
    ----------
    file_path : str
        Path to the exported KRD file on disk. Accepts CSV or Excel (.xlsx/.xls).
    province : str, optional
        Province label to tag all records in this file (e.g. 'Limburg', 'Noord-Brabant').
        Use 'GelderlandTwente' to auto-split by Bronhouder column into Gelderland / Twente.
        If omitted, the script tries to detect the province from the filename.
    """

    # ----------------------------------------------------------
    # STEP 1: Validate the file exists
    # ----------------------------------------------------------
    if not os.path.exists(file_path):
        print(f"❌ Error: file not found: {file_path}")
        return

    file_name = os.path.basename(file_path)
    print(f"\n⏳ Processing KRD file: {file_name}")

    try:
        # ----------------------------------------------------------
        # STEP 2: Reject duplicate loads — check the DB before reading the file
        # For KRD the duplicate guard is per province (not per year).
        # ----------------------------------------------------------
        engine_check = create_engine(DB_URI, pool_pre_ping=True)
        with engine_check.connect() as conn:
            table_exists = conn.execute(text(
                "SELECT EXISTS ("
                "  SELECT FROM information_schema.tables"
                "  WHERE table_name = 'krd_farms'"
                ")"
            )).scalar()

            if table_exists:
                check_province = province if (province and province != 'GelderlandTwente') else None

                if check_province:
                    already_loaded = conn.execute(
                        text("SELECT EXISTS (SELECT 1 FROM krd_farms WHERE provincie = :p LIMIT 1)"),
                        {"p": check_province},
                    ).scalar()
                    if already_loaded:
                        print(f"   ⚠️  Province '{check_province}' already exists in '{TABLE_NAME}'. Skipping to avoid duplicates.")
                        print(f"       Run truncate_krd() first if you want to reload.")
                        engine_check.dispose()
                        return
                elif province == 'GelderlandTwente':
                    already_gelderland = conn.execute(
                        text("SELECT EXISTS (SELECT 1 FROM krd_farms WHERE provincie = 'Gelderland' LIMIT 1)")
                    ).scalar()
                    already_twente = conn.execute(
                        text("SELECT EXISTS (SELECT 1 FROM krd_farms WHERE provincie = 'Twente' LIMIT 1)")
                    ).scalar()
                    if already_gelderland or already_twente:
                        print(f"   ⚠️  Gelderland/Twente data already exists in '{TABLE_NAME}'. Skipping to avoid duplicates.")
                        print(f"       Run truncate_krd() first if you want to reload.")
                        engine_check.dispose()
                        return

        # Determine if_exists based on whether the table currently holds any rows
        if_exists_strategy = 'append' if table_exists else 'replace'
        engine_check.dispose()

        # ----------------------------------------------------------
        # STEP 3: Read the file — CSV (tab or semicolon) or Excel
        # KRD exports are tab-delimited with latin-1 encoding (Dutch characters).
        # dtype=str prevents pandas from guessing int/float per batch, which
        # causes type conflicts when appending multiple province files.
        # ----------------------------------------------------------
        ext = os.path.splitext(file_path)[1].lower()

        if ext in ('.xlsx', '.xls'):
            df = pd.read_excel(file_path, dtype=str)
            print(f"   📄 Loaded Excel file with {len(df):,} rows.")
        elif ext == '.csv':
            df = pd.read_csv(file_path, sep='\t', encoding='latin-1', dtype=str)
            if df.shape[1] == 1:
                df = pd.read_csv(file_path, sep=';', encoding='latin-1', decimal=',', dtype=str)
            if df.shape[1] == 1:
                df = pd.read_csv(file_path, sep=',', encoding='latin-1', dtype=str)
            print(f"   📄 Loaded CSV file with {len(df):,} rows.")
        else:
            print(f"   ❌ Unsupported file format: {ext}. Expected .csv, .xlsx, or .xls.")
            return

        # ----------------------------------------------------------
        # STEP 4: Standardize column names to lowercase
        # ----------------------------------------------------------
        df.columns = [col.strip().lower() for col in df.columns]

        # ----------------------------------------------------------
        # STEP 5: Add province tag
        # KRD is split across 4 separate provincial databases — tagging lets
        # us filter by province in the frontend and detect duplicates above.
        # ----------------------------------------------------------
        if province == 'GelderlandTwente':
            # ODT = Omgevingsdienst Twente; all other agencies are Gelderland.
            if 'bronhouder' in df.columns:
                df['provincie'] = df['bronhouder'].apply(
                    lambda b: 'Twente' if str(b).strip().upper() == 'ODT' else 'Gelderland'
                )
                twente_count    = (df['provincie'] == 'Twente').sum()
                gelderland_count = (df['provincie'] == 'Gelderland').sum()
                print(f"   🔍 Split by Bronhouder: {gelderland_count:,} Gelderland, {twente_count:,} Twente.")
            else:
                df['provincie'] = 'GelderlandTwente'
        elif province:
            df['provincie'] = province
        else:
            for p in ['gelderlandtwente', 'limburg', 'noordbrabant', 'noord-brabant']:
                if p in file_name.lower():
                    df['provincie'] = p
                    print(f"   🔍 Auto-detected province from filename: {p}")
                    break

        # ----------------------------------------------------------
        # STEP 6: Detect and validate coordinate columns
        # KRD stores farm locations as x/y in RD New (EPSG:28992).
        # ----------------------------------------------------------
        x_col, y_col = _detect_coordinate_columns(df.columns)
        print(f"   📍 Coordinate columns: x='{x_col}', y='{y_col}'")

        before = len(df)
        df = df.dropna(subset=[x_col, y_col])
        df[x_col] = pd.to_numeric(df[x_col], errors='coerce')
        df[y_col] = pd.to_numeric(df[y_col], errors='coerce')
        df = df.dropna(subset=[x_col, y_col])
        dropped = before - len(df)
        if dropped > 0:
            print(f"   ⚠️  Dropped {dropped} rows with missing/invalid coordinates.")

        # ----------------------------------------------------------
        # STEP 7: Build Point geometry and reproject RD New → WGS84
        # Each livestock farm is a single point on the map, consistent
        # with how the KRD web viewer displays farms.
        # ----------------------------------------------------------
        geometry = [Point(xy) for xy in zip(df[x_col], df[y_col])]
        gdf = gpd.GeoDataFrame(df, geometry=geometry, crs=SOURCE_CRS)
        gdf = gdf.to_crs(TARGET_CRS)
        print(f"   🌍 Reprojected {len(gdf):,} farm points from RD New → WGS84.")

        # ----------------------------------------------------------
        # STEP 8: Write to PostGIS
        # ----------------------------------------------------------
        engine = create_engine(
            DB_URI,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 300, "options": "-c statement_timeout=0"},
        )
        print(f"   📥 Inserting {len(gdf):,} records into '{TABLE_NAME}' (mode: {if_exists_strategy})...")
        gdf.to_postgis(
            TABLE_NAME, engine,
            if_exists=if_exists_strategy,
            index=True,
            index_label='id',
            chunksize=50000,
        )
        engine.dispose()
        print(f"   ✅ Success: {file_name} loaded into '{TABLE_NAME}'.")

    except ValueError as ve:
        print(f"   ❌ Column detection error: {ve}")
    except Exception as e:
        print(f"   ❌ Pipeline failed for {file_name}: {e}")
        return

    # ----------------------------------------------------------
    # STEP 9: Post-load schema repair
    # Ensure 'id' is a proper primary key with auto-increment.
    # geopandas.to_postgis does not always create a primary key automatically.
    # ----------------------------------------------------------
    print(f"\n⏳ Verifying schema for '{TABLE_NAME}'...")
    try:
        engine = create_engine(DB_URI, pool_pre_ping=True)
        with engine.begin() as conn:
            conn.execute(text(
                f"ALTER TABLE {TABLE_NAME} ADD COLUMN IF NOT EXISTS id SERIAL PRIMARY KEY;"
            ))
        engine.dispose()
        print(f"✅ Schema verified. '{TABLE_NAME}' is ready for spatial queries.")
    except Exception:
        pass

    print(f"\n🎉 KRD data loading complete!")


# =========================================================
# ENTRY POINT
# =========================================================
# INSTRUCTIONS:
#   1. Go to https://krd.igoview.nl/
#   2. For each province (Gelderland/Twente, Limburg, Noord-Brabant):
#      - Open the "Veehouderijen" tab
#      - Export "Totaaloverzicht veehouderijen" as CSV or Excel
#      - Save locally and update the paths below
#   3. Run: python load_krd.py
#
# Each province file is loaded separately and appended into the shared
# 'krd_farms' table, tagged by province for easy filtering.
# =========================================================
if __name__ == "__main__":

    BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "csv files")

    krd_files = [
        {"path": os.path.join(BASE, "KRD_GelderlandTwente.csv"), "province": "GelderlandTwente"},
        {"path": os.path.join(BASE, "KRD_limburg.csv"),          "province": "Limburg"},
        {"path": os.path.join(BASE, "KRD_noordbrabant.csv"),     "province": "Noord-Brabant"},
    ]

    if not krd_files:
        print("KRD loader ready.")
        print("Update the file path(s) in krd_files, then run again.")
    else:
        for entry in krd_files:
            load_krd(entry["path"], province=entry.get("province"))
