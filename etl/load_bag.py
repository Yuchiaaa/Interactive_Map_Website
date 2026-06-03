import os
import pyogrio
import geopandas as gpd
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

# =========================================================
# DATABASE CONFIGURATION
# =========================================================
DB_URI = os.environ.get('DATABASE_URL')
if not DB_URI:
    raise ValueError("DATABASE_URL is not set. Please check your .env file.")

# Target table name in the PostGIS database.
# Stores building footprints with construction year and status attributes,
# sourced from https://www.pdok.nl/introductie/-/article/basisregistratie-adressen-en-gebouwen-ba-1
TABLE_NAME = 'bag_buildings'


# =========================================================
# LOAD
# =========================================================

def load_bag(file_paths):
    """
    Load one or more BAG building files into the 'bag_buildings' PostGIS table.

    Source: https://www.pdok.nl/introductie/-/article/basisregistratie-adressen-en-gebouwen-ba-1
    Download path: PDOK > BAG > Panden > GeoPackage

    BAG contains all historical construction years as an attribute per building
    (oorspronkelijkbouwjaar), so the table is replaced on the first file and
    subsequent files are appended.

    Parameters
    ----------
    file_paths : str or list of str
        Path(s) to the downloaded BAG spatial file(s) on disk.
        Accepted formats: GeoPackage (.gpkg), GeoJSON, Shapefile (.shp), or ZIP.
    """

    # Normalize input: always work with a list of paths
    if isinstance(file_paths, str):
        file_paths = [file_paths]

    first_file = True  # First file replaces the table; subsequent files append

    for file_path in file_paths:

        # ----------------------------------------------------------
        # STEP 1: Validate the file exists
        # ----------------------------------------------------------
        if not os.path.exists(file_path):
            print(f"❌ Error: file not found: {file_path}")
            continue

        file_name = os.path.basename(file_path)
        print(f"\n⏳ Processing BAG file: {file_name}")

        try:
            # ----------------------------------------------------------
            # STEP 2: Reject duplicate loads — check the DB before reading the file
            # ----------------------------------------------------------
            engine_check = create_engine(DB_URI, pool_pre_ping=True)
            with engine_check.connect() as conn:
                table_exists = conn.execute(text(
                    "SELECT EXISTS ("
                    "  SELECT FROM information_schema.tables"
                    "  WHERE table_name = 'bag_buildings'"
                    ")"
                )).scalar()

                if table_exists and first_file:
                    already_loaded = conn.execute(
                        text("SELECT EXISTS (SELECT 1 FROM bag_buildings LIMIT 1)")
                    ).scalar()
                    if already_loaded:
                        print(f"   ⚠️  '{TABLE_NAME}' already contains data. Skipping to avoid duplicates.")
                        print(f"       Run truncate_bag() first if you want to reload.")
                        engine_check.dispose()
                        continue
            engine_check.dispose()

            # ----------------------------------------------------------
            # STEP 3: Read the spatial file using pyogrio (fast reader)
            # ----------------------------------------------------------
            layer_info = pyogrio.list_layers(file_path)
            layer_name = layer_info[0][0]
            info       = pyogrio.read_info(file_path, layer=layer_name)

            print(f"   🗂️  Layer: '{layer_name}' | Features: {info['features']:,}")
            print(f"   📖 Reading {info['features']:,} features...")
            gdf = gpd.read_file(file_path, layer=layer_name, engine="pyogrio")

            # ----------------------------------------------------------
            # STEP 4: Standardize column names to lowercase
            # ----------------------------------------------------------
            gdf.columns = [col.lower() for col in gdf.columns]

            # ----------------------------------------------------------
            # STEP 5: Reproject to WGS84 (EPSG:4326) if needed
            # BAG datasets are typically in RD New (EPSG:28992).
            # All layers in this pipeline use EPSG:4326 for the web frontend.
            # ----------------------------------------------------------
            if gdf.crs is None or gdf.crs.to_epsg() != 4326:
                print(f"   🌍 Reprojecting {gdf.crs} → EPSG:4326...")
                gdf = gdf.to_crs(epsg=4326)

            # ----------------------------------------------------------
            # STEP 6: Cast construction year to numeric
            # oorspronkelijkbouwjaar can arrive as string in some exports.
            # ----------------------------------------------------------
            if 'oorspronkelijkbouwjaar' in gdf.columns:
                gdf['oorspronkelijkbouwjaar'] = pd.to_numeric(
                    gdf['oorspronkelijkbouwjaar'], errors='coerce'
                )

            # ----------------------------------------------------------
            # STEP 7: Repair and drop invalid geometries
            # Some BAG exports contain self-intersecting or otherwise broken
            # polygon rings — make_valid() fixes them in-place.
            # ----------------------------------------------------------
            before = len(gdf)
            gdf['geometry'] = gdf['geometry'].make_valid()
            gdf = gdf.dropna(subset=['geometry'])
            dropped = before - len(gdf)
            if dropped > 0:
                print(f"   ⚠️  Dropped {dropped} rows with invalid/null geometry.")

            # ----------------------------------------------------------
            # STEP 8: Write to PostGIS
            # First file: 'replace' — clean slate with correct schema.
            # Subsequent files: 'append' — add rows for any additional tiles.
            # ----------------------------------------------------------
            if_exists_strategy = 'replace' if first_file else 'append'
            engine = create_engine(
                DB_URI,
                pool_pre_ping=True,
                connect_args={"connect_timeout": 300, "options": "-c statement_timeout=0"},
            )
            print(f"   📥 Inserting {len(gdf):,} records into '{TABLE_NAME}' (mode: {if_exists_strategy})...")
            gdf.to_postgis(TABLE_NAME, engine, if_exists=if_exists_strategy, index=True, index_label='id', chunksize=50000)
            engine.dispose()

            first_file = False
            print(f"   ✅ Success: {file_name} loaded into '{TABLE_NAME}'.")

        except Exception as e:
            print(f"   ❌ Pipeline failed for {file_name}: {e}")

    print(f"\n🎉 BAG loading complete!")


# =========================================================
# ENTRY POINT
# =========================================================
# INSTRUCTIONS:
#   1. Go to https://www.pdok.nl/introductie/-/article/basisregistratie-adressen-en-gebouwen-ba-1
#   2. Download the BAG Panden dataset as GeoPackage
#   3. Update the path(s) below and run: python load_bag.py
#
# To load multiple tiles, pass a list of file paths.
# The table will be replaced on the first file and appended for the rest.
# =========================================================
if __name__ == "__main__":

    bag_files = [
        {"path": "/Users/khushi/Downloads/bag-light.gpkg"},
        # {"path": "/Users/khushi/Downloads/bag_panden_tile2.gpkg"},
    ]

    if not bag_files or bag_files[0]["path"].startswith("/path/to/"):
        print("BAG loader ready.")
        print("Update the file path(s) in bag_files, then run again.")
    else:
        paths = [entry["path"] for entry in bag_files]
        load_bag(paths)
