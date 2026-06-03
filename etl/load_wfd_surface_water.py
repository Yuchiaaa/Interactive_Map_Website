import os
import pyogrio
import geopandas as gpd
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
# Stores WFD (Water Framework Directive) surface water body polygons,
# sourced from https://www.pdok.nl/introductie/-/article/krw-oppervlaktewaterlichamen-inspire-geharmoniseerd-
TABLE_NAME = 'wfd_surface_water'


# =========================================================
# LOAD
# =========================================================

def load_wfd_surface_water(file_paths):
    """
    Load one or more WFD surface water body files into the 'wfd_surface_water' PostGIS table.

    Source: https://www.pdok.nl/introductie/-/article/krw-oppervlaktewaterlichamen-inspire-geharmoniseerd-
    Download path: PDOK > KRW Oppervlaktewaterlichamen > INSPIRE geharmoniseerd > GML / GeoPackage

    Parameters
    ----------
    file_paths : str or list of str
        Path(s) to the downloaded WFD spatial file(s) on disk.
        Accepted formats: GML (.gml), GeoPackage (.gpkg), GeoJSON, Shapefile (.shp).
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
        print(f"\n⏳ Processing WFD Surface Water file: {file_name}")

        try:
            # ----------------------------------------------------------
            # STEP 2: Reject duplicate loads — check the DB before reading the file
            # ----------------------------------------------------------
            engine_check = create_engine(DB_URI, pool_pre_ping=True)
            with engine_check.connect() as conn:
                table_exists = conn.execute(text(
                    "SELECT EXISTS ("
                    "  SELECT FROM information_schema.tables"
                    "  WHERE table_name = 'wfd_surface_water'"
                    ")"
                )).scalar()

                if table_exists and first_file:
                    already_loaded = conn.execute(
                        text("SELECT EXISTS (SELECT 1 FROM wfd_surface_water LIMIT 1)")
                    ).scalar()
                    if already_loaded:
                        print(f"   ⚠️  '{TABLE_NAME}' already contains data. Skipping to avoid duplicates.")
                        print(f"       Run truncate_wfd_surface_water() first if you want to reload.")
                        engine_check.dispose()
                        continue
            engine_check.dispose()

            # ----------------------------------------------------------
            # STEP 3: Inspect layer and read with pyogrio (fast reader)
            # ----------------------------------------------------------
            layers     = pyogrio.list_layers(file_path)
            layer_name = layers[0][0]
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
            # WFD INSPIRE exports from PDOK are typically in RD New (EPSG:28992).
            # All layers in this pipeline use EPSG:4326 for the web frontend.
            # ----------------------------------------------------------
            if gdf.crs is None or gdf.crs.to_epsg() != 4326:
                print(f"   🌍 Reprojecting {gdf.crs} → EPSG:4326...")
                gdf = gdf.to_crs(epsg=4326)

            # ----------------------------------------------------------
            # STEP 6: Repair and drop invalid geometries
            # WFD surface water bodies can contain complex polygon rings
            # with self-intersections from the INSPIRE harmonisation process.
            # ----------------------------------------------------------
            before = len(gdf)
            gdf['geometry'] = gdf['geometry'].make_valid()
            gdf = gdf.dropna(subset=['geometry'])
            dropped = before - len(gdf)
            if dropped > 0:
                print(f"   ⚠️  Dropped {dropped} rows with invalid/null geometry.")

            # ----------------------------------------------------------
            # STEP 7: Write to PostGIS
            # First file: 'replace' — clean slate with correct schema.
            # Subsequent files: 'append' — add rows for any additional exports.
            # ----------------------------------------------------------
            if_exists_strategy = 'replace' if first_file else 'append'
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

            first_file = False
            print(f"   ✅ Success: {file_name} loaded into '{TABLE_NAME}'.")

        except Exception as e:
            print(f"   ❌ Pipeline failed for {file_name}: {e}")

    print(f"\n🎉 WFD Surface Water loading complete!")


# =========================================================
# ENTRY POINT
# =========================================================
# INSTRUCTIONS:
#   1. Go to https://www.pdok.nl/introductie/-/article/krw-oppervlaktewaterlichamen-inspire-geharmoniseerd-
#   2. Download the KRW Oppervlaktewaterlichamen dataset as GML or GeoPackage
#   3. Update the path below and run: python load_wfd_surface_water.py
# =========================================================
if __name__ == "__main__":

    wfd_files = [
        {"path": "/Users/khushi/Downloads/INSPIRESurfaceWaterBody.gml"},
    ]

    if not wfd_files or wfd_files[0]["path"].startswith("/path/to/"):
        print("WFD Surface Water loader ready.")
        print("Update the file path(s) in wfd_files, then run again.")
    else:
        paths = [entry["path"] for entry in wfd_files]
        load_wfd_surface_water(paths)
