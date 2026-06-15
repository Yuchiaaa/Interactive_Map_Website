import pandas as pd
import geopandas as gpd
import requests
import time
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
# Stores school locations with name, type, address, and geocoded coordinates,
# sourced from DUO (https://www.duo.nl/open_onderwijsdata/databestanden/)
TABLE_NAME = 'schools'

COLUMNS_TO_KEEP = [
    "PROVINCIE",
    "INSTELLINGSNAAM",
    "STRAATNAAM",
    "HUISNUMMER-TOEVOEGING",
    "POSTCODE",
    "PLAATSNAAM",
    "GEMEENTENUMMER",
    "GEMEENTENAAM",
    "TELEFOONNUMMER",
]


# =========================================================
# LOAD
# =========================================================

def load_schools(file_groups: list[tuple[str, str]]):
    """
    Clean, geocode, and load school CSV files into the 'schools' PostGIS table.

    Source: https://www.duo.nl/open_onderwijsdata/databestanden/
    Download path: DUO Open Data > [education level] > Adressen hoofdvestigingen

    Accepted format: semicolon-separated CSV with cp1252 encoding (as exported by DUO).

    Parameters
    ----------
    file_groups : list of (file_path, school_type) tuples
        Each tuple provides the path to a raw DUO CSV and a label for the school type
        (e.g. "primary", "secondary", "vocational", "university").
        All files are merged and loaded as a single table.
    """

    # ----------------------------------------------------------
    # STEP 1: Clean and merge all input CSVs
    # ----------------------------------------------------------
    df = _clean_and_merge(file_groups)

    if df.empty:
        print("❌ No data to load after cleaning. Aborting.")
        return

    # ----------------------------------------------------------
    # STEP 2: Geocode addresses via PDOK Locatieserver
    # ----------------------------------------------------------
    df = _geocode(df)

    if df.empty:
        print("❌ No rows with valid coordinates. Aborting.")
        return

    # ----------------------------------------------------------
    # STEP 3: Load into PostGIS
    # ----------------------------------------------------------
    _ingest(df)

    print(f"\n🎉 Schools loading complete!")


def _clean_and_merge(file_groups: list[tuple[str, str]]) -> pd.DataFrame:
    """Read, filter columns, and merge all raw DUO CSVs into one DataFrame."""
    frames = []

    for file_path, school_type in file_groups:

        # ----------------------------------------------------------
        # STEP 1a: Validate the file exists
        # ----------------------------------------------------------
        if not os.path.exists(file_path):
            print(f"❌ File not found, skipping: {file_path}")
            continue

        file_name = os.path.basename(file_path)
        print(f"\n⏳ Processing: {file_name}")

        try:
            # ----------------------------------------------------------
            # STEP 1b: Read CSV (DUO files use semicolon + cp1252 encoding)
            # ----------------------------------------------------------
            df = pd.read_csv(file_path, sep=";", encoding="cp1252", dtype=str)
            df.columns = df.columns.str.strip()

            # ----------------------------------------------------------
            # STEP 1c: Keep only relevant columns
            # ----------------------------------------------------------
            available = [c for c in COLUMNS_TO_KEEP if c in df.columns]
            missing   = [c for c in COLUMNS_TO_KEEP if c not in df.columns]
            if missing:
                print(f"   ⚠️  Columns not found and skipped: {missing}")

            filtered = df[available].copy()
            filtered["onderwijstype"] = school_type
            frames.append(filtered)
            print(f"   📄 Loaded {len(filtered)} rows")

        except Exception as e:
            print(f"   ❌ Failed to read {file_name}: {e}")

    if not frames:
        return pd.DataFrame()

    merged = pd.concat(frames, ignore_index=True)
    merged.columns = merged.columns.str.lower()
    merged = merged.fillna("")
    print(f"\n📋 Merged total: {len(merged)} rows")
    return merged


def _get_coordinates(row) -> pd.Series:
    """Query PDOK Locatieserver for lat/lon of a single address row."""
    address = (
        f"{row.get('straatnaam', '')} "
        f"{row.get('huisnummer-toevoeging', '')} "
        f"{row.get('postcode', '')} "
        f"{row.get('plaatsnaam', '')}"
    ).strip()

    try:
        resp = requests.get(
            "https://api.pdok.nl/bzk/locatieserver/search/v3_1/free",
            params={"q": address},
            timeout=10,
        )
        resp.raise_for_status()
        docs = resp.json()["response"]["docs"]

        if not docs:
            return pd.Series([None, None])

        point = docs[0]["centroide_ll"]
        lon, lat = point.replace("POINT(", "").replace(")", "").split()
        time.sleep(0.1)
        return pd.Series([float(lat), float(lon)])

    except Exception:
        return pd.Series([None, None])


def _geocode(df: pd.DataFrame) -> pd.DataFrame:
    """Apply PDOK geocoding to every row and drop unresolved addresses."""
    print("🌍 Geocoding addresses via PDOK (this takes a while)...")
    df[["latitude", "longitude"]] = df.apply(_get_coordinates, axis=1)

    before = len(df)
    df = df.dropna(subset=["latitude", "longitude"])
    print(f"   ✅ Geocoded {len(df)} rows ({before - len(df)} addresses not found)")
    return df


def _ingest(df: pd.DataFrame):
    """Build geometry and write the geocoded DataFrame to PostGIS."""
    engine = create_engine(DB_URI, pool_pre_ping=True)

    # ----------------------------------------------------------
    # STEP 3a: Build Point geometry (lon, lat order)
    # ----------------------------------------------------------
    geometry = [Point(xy) for xy in zip(df["longitude"], df["latitude"])]
    gdf = gpd.GeoDataFrame(df, geometry=geometry, crs="EPSG:4326")

    print(f"   📥 Inserting {len(gdf):,} records into '{TABLE_NAME}'...")

    # ----------------------------------------------------------
    # STEP 3b: Write to PostGIS (replace on first load)
    # ----------------------------------------------------------
    gdf.to_postgis(TABLE_NAME, engine, if_exists="replace", index=True, index_label="id")

    # ----------------------------------------------------------
    # STEP 3c: Ensure primary key exists
    # ----------------------------------------------------------
    with engine.begin() as conn:
        conn.execute(text(f"""
            ALTER TABLE {TABLE_NAME}
            ADD COLUMN IF NOT EXISTS id SERIAL PRIMARY KEY;
        """))

    engine.dispose()
    print(f"   ✅ Success: {len(gdf):,} records loaded into '{TABLE_NAME}'.")


# =========================================================
# ENTRY POINT
# =========================================================
# INSTRUCTIONS:
#   1. Go to https://www.duo.nl/open_onderwijsdata/databestanden/
#   2. Download the CSV files for each education level
#   3. Place them in ~/Downloads (or update the paths below)
#   4. Run: python etl/load_schools.py
# =========================================================
if __name__ == "__main__":

    DOWNLOADS = os.path.expanduser("~/Downloads")

    school_files = [
        {"path": os.path.join(DOWNLOADS, "01.-hoofdvestigingen-basisonderwijs (1).csv"), "type": "primary"},
        {"path": os.path.join(DOWNLOADS, "01.-hoofdvestigingen-vo.csv"),                 "type": "secondary"},
        {"path": os.path.join(DOWNLOADS, "01.-adressen-mbo-instellingen.csv"),           "type": "vocational"},
        {"path": os.path.join(DOWNLOADS, "01.-instellingen-hbo-en-wo.csv"),              "type": "university"},
    ]

    load_schools([(e["path"], e["type"]) for e in school_files])
