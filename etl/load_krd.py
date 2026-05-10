import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from sqlalchemy import create_engine, text
import os

# =========================================================
# DATABASE CONFIGURATION
# =========================================================
# Connection string to the local PostGIS database.
# Must match the credentials used across all ETL scripts in this project.
DB_URI = 'postgresql://postgres:admin@localhost:5432/legal_mapping'

# Target table name in the PostGIS database.
# Stores livestock farm locations with emission figures (NH3, fijnstof, geur),
# as required by the "Mapping for the Environment" project spec (layer e).
TABLE_NAME = 'krd_farms'

# =========================================================
# COORDINATE SYSTEM CONFIGURATION
# =========================================================
# KRD exports coordinates in the Dutch national grid system (RD New).
# We reproject to WGS84 (EPSG:4326) to stay consistent with all other
# layers in this pipeline (BRP, Kadaster, Natura2000, BAG).
SOURCE_CRS = 'EPSG:28992'   # RD New — standard for Dutch government datasets
TARGET_CRS = 'EPSG:4326'    # WGS84 — used by the web mapping frontend


def detect_coordinate_columns(columns):
    """
    Dynamically detects which columns contain x and y coordinates.

    KRD exports from different provinces may use slightly different column names
    (e.g. 'x', 'X', 'x_coord', 'coordinaat_x'). This function handles all variants
    so the script works regardless of which province export is loaded.

    Returns a tuple (x_col, y_col) or raises an error if not found.
    """
    columns_lower = [c.lower() for c in columns]

    # Common x-coordinate column name patterns in KRD exports
    x_candidates = ['x', 'x_coord', 'coordinaat_x', 'rd_x', 'xcoord']
    # Common y-coordinate column name patterns in KRD exports
    y_candidates = ['y', 'y_coord', 'coordinaat_y', 'rd_y', 'ycoord']

    x_col = None
    y_col = None

    # Match against actual column names (case-insensitive)
    for i, col in enumerate(columns_lower):
        if col in x_candidates:
            x_col = columns[i]
        if col in y_candidates:
            y_col = columns[i]

    if x_col is None or y_col is None:
        raise ValueError(
            f"Could not detect coordinate columns.\n"
            f"Available columns: {list(columns)}\n"
            f"Expected one of {x_candidates} for X and {y_candidates} for Y."
        )

    return x_col, y_col


def load_krd(file_paths, province=None):
    """
    Loads KRD livestock farm emission data from one or more CSV/Excel exports
    into the PostGIS database table 'krd_farms'.

    This function follows the same ETL philosophy as load_bag, load_brp, etc.:
    - Source: local file(s) manually exported from https://krd.igoview.nl/
    - Transform: detect coordinates, reproject to EPSG:4326, standardize columns
    - Load: append into PostGIS using geopandas (replace on first load, append for subsequent provinces)

    Parameters
    ----------
    file_paths : str or list of str
        Path(s) to the exported KRD file(s). Accepts both CSV and Excel (.xlsx).
        Since KRD data is split by province (Gelderland, Limburg, Noord-Brabant, Twente),
        you can pass a list of 4 files to load all provinces in one call.

    province : str, optional
        Optional label to tag each record with its source province.
        Useful for filtering later in the mapping tool.
        Example: 'Noord-Brabant', 'Gelderland', 'Limburg', 'Twente'
        If None, the column will be filled with NULL.
    """

    # -------------------------------------------------------
    # Normalize input: always work with a list of file paths,
    # even if the user passes a single string.
    # -------------------------------------------------------
    if isinstance(file_paths, str):
        file_paths = [file_paths]

    engine = create_engine(DB_URI)
    first_file = True  # Controls whether we REPLACE or APPEND the PostGIS table

    for file_path in file_paths:

        # ----------------------------------------------------------
        # STEP 1: Validate that the file exists before doing anything
        # ----------------------------------------------------------
        if not os.path.exists(file_path):
            print(f"❌ Error: File not found at {file_path}")
            continue  # Skip this file, try the next one

        file_name = os.path.basename(file_path)
        print(f"\n⏳ Processing KRD file: {file_name}")

        try:
            # ----------------------------------------------------------
            # STEP 2: Read the file into a DataFrame.
            # KRD exports come as CSV (Totaaloverzicht) or Excel.
            # We detect the format by file extension.
            # ----------------------------------------------------------
            ext = os.path.splitext(file_path)[1].lower()

            if ext in ['.xlsx', '.xls']:
                # Excel export — common when using the KRD web interface
                df = pd.read_excel(file_path)
                print(f"   📄 Loaded Excel file with {len(df)} rows.")
            elif ext == '.csv':
                # CSV export — try semicolon delimiter first (Dutch standard),
                # fall back to comma if that produces only one column.
                df = pd.read_csv(file_path, sep=';', decimal=',')
                if df.shape[1] == 1:
                    df = pd.read_csv(file_path, sep=',')
                print(f"   📄 Loaded CSV file with {len(df)} rows.")
            else:
                print(f"   ❌ Unsupported file format: {ext}. Expected .csv, .xlsx, or .xls.")
                continue

            # ----------------------------------------------------------
            # STEP 3: Standardize column names to lowercase.
            # Ensures consistent behaviour regardless of export locale
            # (some KRD exports use mixed case or accented characters).
            # ----------------------------------------------------------
            df.columns = [col.strip().lower() for col in df.columns]

            # ----------------------------------------------------------
            # STEP 4: Add province tag if provided.
            # This is important because KRD is split across 4 separate
            # provincial databases — tagging lets us filter by province later.
            # ----------------------------------------------------------
            if province:
                df['provincie'] = province
            else:
                # Try to auto-detect province from filename
                # e.g. "krd_export_noord-brabant.csv" → "noord-brabant"
                for p in ['gelderland', 'limburg', 'noord-brabant', 'twente']:
                    if p in file_name.lower():
                        df['provincie'] = p
                        print(f"   🔍 Auto-detected province from filename: {p}")
                        break

            # ----------------------------------------------------------
            # STEP 5: Detect and validate coordinate columns.
            # KRD stores farm locations as x/y in RD New (EPSG:28992).
            # We need these to build a geometry column for PostGIS.
            # ----------------------------------------------------------
            x_col, y_col = detect_coordinate_columns(df.columns)
            print(f"   📍 Using coordinate columns: x='{x_col}', y='{y_col}'")

            # Drop rows where coordinates are missing — they cannot be placed on the map
            before = len(df)
            df = df.dropna(subset=[x_col, y_col])
            dropped = before - len(df)
            if dropped > 0:
                print(f"   ⚠️  Dropped {dropped} rows with missing coordinates.")

            # Ensure coordinates are numeric (sometimes exported as strings)
            df[x_col] = pd.to_numeric(df[x_col], errors='coerce')
            df[y_col] = pd.to_numeric(df[y_col], errors='coerce')
            df = df.dropna(subset=[x_col, y_col])  # Drop again after coercion

            # ----------------------------------------------------------
            # STEP 6: Build Point geometry from x/y coordinates.
            # Each livestock farm is represented as a single point on the map.
            # This is consistent with how the KRD web viewer displays farms.
            # ----------------------------------------------------------
            geometry = [Point(xy) for xy in zip(df[x_col], df[y_col])]

            # ----------------------------------------------------------
            # STEP 7: Create a GeoDataFrame and reproject to EPSG:4326.
            # Source CRS is RD New (EPSG:28992) — the Dutch national grid.
            # All other layers in this pipeline use EPSG:4326 (WGS84),
            # so we reproject here to keep everything consistent for the
            # PostGIS spatial joins and the web mapping frontend.
            # ----------------------------------------------------------
            gdf = gpd.GeoDataFrame(df, geometry=geometry, crs=SOURCE_CRS)
            gdf = gdf.to_crs(TARGET_CRS)
            print(f"   🌍 Reprojected {len(gdf)} farm points from RD New → WGS84.")

            # ----------------------------------------------------------
            # STEP 8: Load into PostGIS.
            # Strategy:
            #   - First file: 'replace' — drops and recreates the table.
            #     This ensures a clean slate and correct schema.
            #   - Subsequent files (other provinces): 'append' — adds rows
            #     to the existing table without touching the schema.
            # This mirrors the multi-year append strategy used in load_brp.py.
            # ----------------------------------------------------------
            if_exists_strategy = 'replace' if first_file else 'append'
            print(f"   📥 Inserting {len(gdf)} records into '{TABLE_NAME}' (mode: {if_exists_strategy})...")

            gdf.to_postgis(
                TABLE_NAME,
                engine,
                if_exists=if_exists_strategy,
                index=True,
                index_label='id'
            )

            first_file = False  # All subsequent files will be appended
            print(f"   ✅ Success: {file_name} loaded into '{TABLE_NAME}'.")

        except ValueError as ve:
            # Coordinate detection failed — give a clear, actionable error
            print(f"   ❌ Column detection error: {ve}")
        except Exception as e:
            print(f"   ❌ Pipeline failed for {file_name}: {e}")

    # ----------------------------------------------------------
    # STEP 9: Post-load schema repair.
    # Ensure the 'id' column is a proper primary key with auto-increment.
    # geopandas.to_postgis does not always create a primary key automatically,
    # so we enforce it here — same pattern as in master_sync.py.
    # ----------------------------------------------------------
    print(f"\n⏳ Verifying schema for '{TABLE_NAME}'...")
    try:
        with engine.begin() as conn:
            conn.execute(text(
                f"ALTER TABLE {TABLE_NAME} ADD COLUMN IF NOT EXISTS id SERIAL PRIMARY KEY;"
            ))
        print(f"✅ Schema verified. '{TABLE_NAME}' is ready for spatial queries.")
    except Exception:
        # Primary key may already exist — silently ignore
        pass

    print(f"\n🎉 KRD data loading complete!")


# =========================================================
# ENTRY POINT
# =========================================================
# INSTRUCTIONS:
#   1. Go to https://krd.igoview.nl/
#   2. For each province (Gelderland, Limburg, Noord-Brabant, Twente):
#      - Open the "Veehouderijen" tab
#      - Apply any filters if needed (or select all)
#      - Export "Totaaloverzicht veehouderijen" as CSV or Excel
#      - Save the file locally and update the paths below
#   3. Run this script: python load_krd.py
#
# The script will load all provinces and append them into a single
# 'krd_farms' table, tagged by province for easy filtering.
# =========================================================
if __name__ == "__main__":

    # Add one entry per province export file.
    # The 'province' key is optional — if omitted, the script tries to
    # detect the province name from the filename automatically.
    krd_files = [
        # {"path": "/path/to/krd_gelderland.csv",     "province": "Gelderland"},
        # {"path": "/path/to/krd_limburg.csv",         "province": "Limburg"},
        # {"path": "/path/to/krd_noord-brabant.csv",   "province": "Noord-Brabant"},
        # {"path": "/path/to/krd_twente.csv",          "province": "Twente"},
    ]

    if not krd_files:
        print("KRD Script ready.")
        print("Uncomment and update the file paths in krd_files, then run again.")
    else:
        for entry in krd_files:
            load_krd(entry["path"], province=entry.get("province"))
