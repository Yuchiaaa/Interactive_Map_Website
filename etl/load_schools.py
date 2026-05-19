import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv

# =========================================================
# DATABASE CONFIGURATION
# =========================================================
# Same pattern as your working pesticides script
DB_URI = 'postgresql://postgres:123456@100.74.81.23:5432/legal_mapping'

engine = create_engine(DB_URI)

TABLE_NAME = 'schools'

# =========================================================
# COORDINATE SYSTEM
# =========================================================
SOURCE_CRS = 'EPSG:4326'
TARGET_CRS = 'EPSG:4326'




def load_schools(file_paths):
    """
    Load cleaned school dataset into PostGIS.
    """

    if isinstance(file_paths, str):
        file_paths = [file_paths]

    engine = create_engine(DB_URI)
    first_file = True

    for file_path in file_paths:

        if not os.path.exists(file_path):
            print(f"❌ File not found: {file_path}")
            continue

        file_name = os.path.basename(file_path)
        print(f"\n⏳ Processing: {file_name}")

        try:
            # ----------------------------------------------------------
            # STEP 1: Load CSV
            # ----------------------------------------------------------
            df = pd.read_csv(file_path)
            df.columns = [c.strip().lower() for c in df.columns]

            print(f"📄 Loaded {len(df)} rows")

            # ----------------------------------------------------------
            # STEP 2: Validate required columns
            # ----------------------------------------------------------
            required_cols = ['latitude', 'longitude', 'instellingsnaam']
            missing = [c for c in required_cols if c not in df.columns]

            if missing:
                raise ValueError(f"Missing required columns: {missing}")

            # ----------------------------------------------------------
            # STEP 3: Convert coordinates
            # ----------------------------------------------------------
            df['latitude'] = pd.to_numeric(df['latitude'], errors='coerce')
            df['longitude'] = pd.to_numeric(df['longitude'], errors='coerce')

            before = len(df)
            df = df.dropna(subset=['latitude', 'longitude'])
            print(f"⚠️ Dropped {before - len(df)} rows with missing coordinates")

            # ----------------------------------------------------------
            # STEP 4: Build geometry (lon, lat order!)
            # ----------------------------------------------------------
            geometry = [
                Point(xy) for xy in zip(df['longitude'], df['latitude'])
            ]

            gdf = gpd.GeoDataFrame(df, geometry=geometry, crs=SOURCE_CRS)

            print(f"🌍 Created {len(gdf)} spatial points")

            # ----------------------------------------------------------
            # STEP 5: Load into PostGIS
            # ----------------------------------------------------------
            mode = 'replace' if first_file else 'append'

            gdf.to_postgis(
                TABLE_NAME,
                engine,
                if_exists=mode,
                index=True,
                index_label='id'
            )

            first_file = False
            print(f"✅ Inserted into '{TABLE_NAME}'")

        except Exception as e:
            print(f"❌ Error in {file_name}: {e}")

    # ----------------------------------------------------------
    # STEP 6: Ensure primary key
    # ----------------------------------------------------------
    print("\n⏳ Finalizing schema...")
    try:
        with engine.begin() as conn:
            conn.execute(text(f"""
                ALTER TABLE {TABLE_NAME}
                ADD COLUMN IF NOT EXISTS id SERIAL PRIMARY KEY;
            """))
        print("✅ Schema ready")
    except Exception:
        pass

    print("\n🎉 Done loading schools!")


# =========================================================
# ENTRY POINT
# =========================================================
if __name__ == "__main__":

    school_file = "static/csv files/final_schools_with_coordinates.csv"

    if not os.path.exists(school_file):
        print("❌ File not found. Check path:")
        print(school_file)
    else:
        load_schools(school_file)
