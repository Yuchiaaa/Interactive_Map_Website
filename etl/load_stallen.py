import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv

load_dotenv()

DB_URI = os.environ.get('DATABASE_URL')
if not DB_URI:
    raise ValueError("DATABASE_URL is not set. Please check your .env file.")

TABLE_NAME  = 'krd_stallen'
SOURCE_CRS  = 'EPSG:28992'
TARGET_CRS  = 'EPSG:4326'


def load_stallen(file_path, province=None):
    """
    Load one KRD Stallen export into the 'krd_stallen' PostGIS table.

    Source: https://krd.igoview.nl/
    Download path: KRD > Stallen > Totaaloverzicht stallen > Export CSV/Excel

    One row per animal housing unit (stal) within a farm. Multiple stallen
    can belong to the same farm (linked via VTHobject ID). Each stal has
    its own NH3/odour/dust emission figures.

    Call once per province file — appended into the shared table.

    Parameters
    ----------
    file_path : str
        Path to exported KRD Stallen CSV or Excel file.
    province : str, optional
        Province label. Use 'GelderlandTwente' to auto-split by Bronhouder
        (ODT = Twente, rest = Gelderland). Auto-detected from filename if omitted.
    """

    if not os.path.exists(file_path):
        print(f"❌ File not found: {file_path}")
        return

    file_name = os.path.basename(file_path)
    print(f"\n⏳ Processing Stallen file: {file_name}")

    try:
        # ----------------------------------------------------------
        # STEP 1: Duplicate guard — check by province before reading file
        # ----------------------------------------------------------
        engine_check = create_engine(DB_URI, pool_pre_ping=True)
        with engine_check.connect() as conn:
            table_exists = conn.execute(text(
                "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'krd_stallen')"
            )).scalar()

            if table_exists:
                check_province = province if (province and province != 'GelderlandTwente') else None

                if check_province:
                    already = conn.execute(
                        text("SELECT EXISTS (SELECT 1 FROM krd_stallen WHERE provincie = :p LIMIT 1)"),
                        {"p": check_province},
                    ).scalar()
                    if already:
                        print(f"   ⚠️  Province '{check_province}' already in '{TABLE_NAME}'. Skipping.")
                        print(f"       Run truncate_stallen() first to reload.")
                        engine_check.dispose()
                        return

                elif province == 'GelderlandTwente':
                    already_g = conn.execute(text(
                        "SELECT EXISTS (SELECT 1 FROM krd_stallen WHERE provincie = 'Gelderland' LIMIT 1)"
                    )).scalar()
                    already_t = conn.execute(text(
                        "SELECT EXISTS (SELECT 1 FROM krd_stallen WHERE provincie = 'Twente' LIMIT 1)"
                    )).scalar()
                    if already_g or already_t:
                        print(f"   ⚠️  Gelderland/Twente already in '{TABLE_NAME}'. Skipping.")
                        engine_check.dispose()
                        return

        if_exists_strategy = 'append' if table_exists else 'replace'
        engine_check.dispose()

        # ----------------------------------------------------------
        # STEP 2: Read file
        # ----------------------------------------------------------
        ext = os.path.splitext(file_path)[1].lower()
        if ext in ('.xlsx', '.xls'):
            df = pd.read_excel(file_path, dtype=str)
            print(f"   📄 Loaded Excel with {len(df):,} rows.")
        elif ext == '.csv':
            df = pd.read_csv(file_path, sep='\t', encoding='latin-1', dtype=str)
            if df.shape[1] == 1:
                df = pd.read_csv(file_path, sep=';', encoding='latin-1', dtype=str)
            if df.shape[1] == 1:
                df = pd.read_csv(file_path, sep=',', encoding='latin-1', dtype=str)
            print(f"   📄 Loaded CSV with {len(df):,} rows.")
        else:
            print(f"   ❌ Unsupported format: {ext}")
            return

        # ----------------------------------------------------------
        # STEP 3: Standardize column names
        # Keep original names (with spaces) like krd_farms — the frontend
        # popup expects 'nh3 emissie (kg/j)' etc. with spaces.
        # Only strip Dutch accent chars to ensure cross-file consistency
        # (e.g. 'Beëndigd' missing from GelderlandTwente file).
        # ----------------------------------------------------------
        df.columns = [
            col.strip().lower()
               .replace('ë', 'e').replace('é', 'e')
               .replace('ü', 'u').replace('ö', 'o')
            for col in df.columns
        ]

        # Pad missing columns so all province files share the same schema
        STANDARD_COLS = [
            'bronhouder', 'vthobject id', 'stal id', 'omschrijving',
            'beendigd', 'adres', 'gemeente',
            'emissiex', 'emissiey',
            'nh3 emissie (kg/j)', 'geur emissie (oue/s)', 'fijnstof emissie (g/j)',
            'zaaknummer', 'besluitdatum', 'zaaktype',
        ]
        for col in STANDARD_COLS:
            if col not in df.columns:
                df[col] = None
        df = df[STANDARD_COLS]

        # ----------------------------------------------------------
        # STEP 4: Province tag
        # ----------------------------------------------------------
        if province == 'GelderlandTwente':
            if 'bronhouder' in df.columns:
                df['provincie'] = df['bronhouder'].apply(
                    lambda b: 'Twente' if str(b).strip().upper() == 'ODT' else 'Gelderland'
                )
                t = (df['provincie'] == 'Twente').sum()
                g = (df['provincie'] == 'Gelderland').sum()
                print(f"   🔍 Split: {g:,} Gelderland, {t:,} Twente.")
            else:
                df['provincie'] = 'GelderlandTwente'
        elif province:
            df['provincie'] = province
        else:
            for p in ['gelderlandtwente', 'limburg', 'noordbrabant', 'noord-brabant']:
                if p in file_name.lower():
                    df['provincie'] = p
                    break

        # ----------------------------------------------------------
        # STEP 5: Coordinates — EmissieX / EmissieY in RD New
        # ----------------------------------------------------------
        x_col, y_col = 'emissiex', 'emissiey'
        if x_col not in df.columns or y_col not in df.columns:
            raise ValueError(f"Expected coordinate columns 'EmissieX'/'EmissieY'. Got: {list(df.columns)}")

        before = len(df)
        df[x_col] = pd.to_numeric(df[x_col], errors='coerce')
        df[y_col] = pd.to_numeric(df[y_col], errors='coerce')
        df = df.dropna(subset=[x_col, y_col])
        dropped = before - len(df)
        if dropped:
            print(f"   ⚠️  Dropped {dropped} rows with missing coordinates.")

        # ----------------------------------------------------------
        # STEP 6: Build geometry and reproject RD New → WGS84
        # ----------------------------------------------------------
        geometry = [Point(xy) for xy in zip(df[x_col], df[y_col])]
        gdf = gpd.GeoDataFrame(df, geometry=geometry, crs=SOURCE_CRS)
        gdf = gdf.to_crs(TARGET_CRS)
        print(f"   🌍 Reprojected {len(gdf):,} stallen points RD New → WGS84.")

        # ----------------------------------------------------------
        # STEP 7: Write to PostGIS
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
        print(f"   ❌ Column error: {ve}")
    except Exception as e:
        print(f"   ❌ Pipeline failed for {file_name}: {e}")
        return

    # ----------------------------------------------------------
    # STEP 8: Ensure primary key
    # ----------------------------------------------------------
    try:
        engine = create_engine(DB_URI, pool_pre_ping=True)
        with engine.begin() as conn:
            conn.execute(text(
                f"ALTER TABLE {TABLE_NAME} ADD COLUMN IF NOT EXISTS id SERIAL PRIMARY KEY;"
            ))
        engine.dispose()
    except Exception:
        pass

    print(f"\n🎉 Stallen loading complete!")


# =========================================================
# ENTRY POINT
# =========================================================
# Instructions:
#   1. Go to https://krd.igoview.nl/
#   2. Open the "Stallen" tab
#   3. Export "Totaaloverzicht stallen" as CSV for each province
#   4. Update paths below and run: python load_stallen.py
# =========================================================
if __name__ == "__main__":
    stallen_files = [
        {"path": "/Users/khushi/Downloads/stalen (2).csv", "province": "GelderlandTwente"},
        {"path": "/Users/khushi/Downloads/stalen (3).csv", "province": "Limburg"},
        {"path": "/Users/khushi/Downloads/stalen (4).csv", "province": "Noord-Brabant"},
    ]
    for entry in stallen_files:
        load_stallen(entry["path"], province=entry.get("province"))
