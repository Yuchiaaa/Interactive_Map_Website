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

TABLE_NAME = 'krd_stallen'
SOURCE_CRS = 'EPSG:28992'   # RD New - Dutch national grid
TARGET_CRS = 'EPSG:4326'    # WGS84

# =========================================================
# COLUMN MAPPING
# Maps lowercase KRD stallen CSV names -> DB column names.
# Columns not listed here are dropped before insertion.
# =========================================================
COLUMN_MAP = {
    'bronhouder':             'bronhouder',
    'vthobject id':           'vthobject_id',
    'stal id':                'stal_id',
    'omschrijving':           'omschrijving',
    'adres':                  'adres',
    'gemeente':               'gemeente',
    'nh3 emissie (kg/j)':     'nh3_emissie',
    'geur emissie (oue/s)':   'geur_emissie',
    'fijnstof emissie (g/j)': 'fijnstof_emissie',
    'zaaknummer':             'zaaknummer',
    'besluitdatum':           'besluitdatum',
    'zaaktype':               'zaaktype',
}


def load_stallen(file_path, province=None, append=False):
    """
    Loads one KRD stallen export file into PostGIS table 'krd_stallen'.

    Parameters
    ----------
    file_path : str
        Path to the KRD stallen CSV export.
        Download from: https://krd.igoview.nl/ -> Stallen tab -> Totaaloverzicht stallen.

    province : str, optional
        Province label for all records (e.g. 'Limburg', 'Noord-Brabant').
        Use 'GelderlandTwente' to auto-split on the Bronhouder column (ODT = Twente).

    append : bool
        If True, appends to existing table.
        Set True for every province after the first to avoid overwriting loaded data.
    """
    if not os.path.exists(file_path):
        print(f"ERROR: Error: File not found at {file_path}")
        return

    file_name = os.path.basename(file_path)
    print(f"\n Processing: {file_name}")

    engine = create_engine(DB_URI)

    try:
        # ----------------------------------------------------------
        # STEP 1: Read file - KRD stallen exports are tab-delimited latin-1
        # ----------------------------------------------------------
        ext = os.path.splitext(file_path)[1].lower()
        if ext in ['.xlsx', '.xls']:
            df = pd.read_excel(file_path, dtype=str)
        else:
            df = pd.read_csv(file_path, sep='\t', encoding='latin-1', dtype=str)
        print(f"    {len(df)} rows loaded.")

        # Normalise column names
        df.columns = [col.strip().lower() for col in df.columns]

        # ----------------------------------------------------------
        # STEP 2: Province tagging
        # ----------------------------------------------------------
        if province == 'GelderlandTwente':
            if 'bronhouder' in df.columns:
                df['provincie'] = df['bronhouder'].apply(
                    lambda b: 'Twente' if str(b).strip().upper() == 'ODT' else 'Gelderland'
                )
                t = (df['provincie'] == 'Twente').sum()
                g = (df['provincie'] == 'Gelderland').sum()
                print(f"    Split by Bronhouder: {g} Gelderland, {t} Twente.")
            else:
                df['provincie'] = 'GelderlandTwente'
        elif province:
            df['provincie'] = province

        # ----------------------------------------------------------
        # STEP 3: Find and normalise the beendigd column.
        # Its name has an encoding quirk (e stored as a non-ASCII byte).
        # We detect it by looking for any column containing 'ndigd'.
        # ----------------------------------------------------------
        beendigd_src = next((c for c in df.columns if 'ndigd' in c), None)
        if beendigd_src:
            df = df.rename(columns={beendigd_src: 'beendigd'})

        # ----------------------------------------------------------
        # STEP 4: Parse coordinates - KRD stallen uses EmissieX/EmissieY
        # (stored as RD New, EPSG:28992). Rows with zero or null coords
        # have no location data in the KRD system and are dropped.
        # ----------------------------------------------------------
        x_col, y_col = 'emissiex', 'emissiey'
        if x_col not in df.columns or y_col not in df.columns:
            raise ValueError(
                f"Expected coordinate columns 'emissiex' and 'emissiey'. "
                f"Found: {list(df.columns)}"
            )

        df[x_col] = pd.to_numeric(df[x_col], errors='coerce')
        df[y_col] = pd.to_numeric(df[y_col], errors='coerce')
        before = len(df)
        df = df[df[x_col].notna() & df[y_col].notna() & (df[x_col] != 0) & (df[y_col] != 0)]
        dropped = before - len(df)
        if dropped:
            print(f"   WARNING:  Dropped {dropped} rows with missing/zero coordinates.")

        # ----------------------------------------------------------
        # STEP 5: Keep only mapped columns (+ provincie, beendigd, coords)
        # ----------------------------------------------------------
        rename = {k: v for k, v in COLUMN_MAP.items() if k in df.columns}
        df = df.rename(columns=rename)

        keep = [v for v in COLUMN_MAP.values() if v in df.columns]
        for extra in ('provincie', 'beendigd', x_col, y_col):
            if extra in df.columns and extra not in keep:
                keep.append(extra)
        df = df[keep]

        # Ensure beendigd column is always present (some provincial exports omit it)
        if 'beendigd' not in df.columns:
            df = df.copy()
            df['beendigd'] = None

        # ----------------------------------------------------------
        # STEP 6: Build GeoDataFrame and reproject RD New -> WGS84
        # ----------------------------------------------------------
        geometry = [Point(x, y) for x, y in zip(df[x_col], df[y_col])]
        gdf = gpd.GeoDataFrame(df.drop(columns=[x_col, y_col]), geometry=geometry, crs=SOURCE_CRS)
        gdf = gdf.to_crs(TARGET_CRS)
        print(f"    Reprojected {len(gdf)} points RD New -> WGS84.")

        # ----------------------------------------------------------
        # STEP 7: Write to PostGIS
        # ----------------------------------------------------------
        if_exists = 'replace' if not append else 'append'
        print(f"    Inserting {len(gdf)} rows into '{TABLE_NAME}' (mode: {if_exists})...")
        gdf.to_postgis(TABLE_NAME, engine, if_exists=if_exists, index=True, index_label='id')
        print(f"   Done: Done: {file_name}")

    except Exception as e:
        print(f"   ERROR: Failed for {file_name}: {e}")
        import traceback; traceback.print_exc()

    # Ensure id is a proper primary key
    try:
        with engine.begin() as conn:
            conn.execute(text(
                f"ALTER TABLE {TABLE_NAME} ADD COLUMN IF NOT EXISTS id SERIAL PRIMARY KEY;"
            ))
    except Exception:
        pass


# =========================================================
# ENTRY POINT
# =========================================================
# HOW TO GET THE STALLEN FILES:
#   1. Go to https://krd.igoview.nl/
#   2. For each province: Stallen tab -> select all -> Export -> Totaaloverzicht stallen -> CSV
#   3. Run: python etl/truncate_stallen.py
#   4. Run: python etl/load_stallen.py
#
# Relevant fields for environmental assessment:
#   - omschrijving: housing unit description (animal type + system where available)
#   - nh3_emissie: NH3 per housing unit (kg/j) - key for Natura 2000 deposit calculation
#   - geur_emissie: odour load (ouE/s)
#   - fijnstof_emissie: fine particulate (g/j)
#   - besluitdatum: date of the relevant permit decision
#   - beendigd: Ja = housing unit / permit terminated
# =========================================================
if __name__ == "__main__":
    BASE = r"C:\Users\hanna\Desktop\CAPSTONE\Interactive_Map_Website\csv files"

    stallen_files = [
        {"path": os.path.join(BASE, "GelderlandTwente_stalen.csv"), "province": "GelderlandTwente"},
        {"path": os.path.join(BASE, "Limburg_stalen.csv"),          "province": "Limburg"},
        {"path": os.path.join(BASE, "NoordBrabant_stalen.csv"),     "province": "Noord-Brabant"},
    ]

    for i, entry in enumerate(stallen_files):
        load_stallen(entry["path"], province=entry.get("province"), append=(i > 0))

    print("\n All stallen files loaded.")
