import os
import zipfile
import tempfile
import shutil
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
# Stores health facility point locations with OSM tags (type, name, operator),
# sourced from https://data.humdata.org/dataset/hotosm_nld_health_facilities
TABLE_NAME = 'health_facilities'

TARGET_CRS = 'EPSG:4326'


def _clean_column_names(gdf):
    """
    Standardize HOTOSM/OSM column names for PostGIS.
    OSM colon-separated keys (name:en, addr:city) are not valid SQL identifiers.
    """
    rename_map = {
        'name:en':               'name_en',
        'name:nl':               'name_nl',
        'healthcare:speciality': 'healthcare_speciality',
        'operator:type':         'operator_type',
        'capacity:persons':      'capacity_persons',
        'addr:full':             'addr_full',
        'addr:city':             'addr_city',
    }
    gdf = gdf.rename(columns=rename_map)
    gdf.columns = [
        col.strip().lower().replace(':', '_').replace('-', '_').replace(' ', '_')
        for col in gdf.columns
    ]
    return gdf


def _add_facility_type(gdf):
    """
    Derive a simplified 'facility_type' column for frontend filtering.
    Priority: healthcare tag → amenity tag → 'unknown'.
    """
    healthcare = gdf['healthcare'] if 'healthcare' in gdf.columns else pd.Series([None] * len(gdf))
    amenity    = gdf['amenity']    if 'amenity'    in gdf.columns else pd.Series([None] * len(gdf))

    gdf['facility_type'] = (
        healthcare.fillna(amenity).fillna('unknown')
        .astype(str).str.lower().str.strip()
        .replace({'doctors': 'doctor'})
    )
    return gdf


# =========================================================
# LOAD
# =========================================================

def load_healthcare(file_paths):
    """
    Load one or more HOTOSM Netherlands health facility files into the
    'health_facilities' PostGIS table.

    Source: https://data.humdata.org/dataset/hotosm_nld_health_facilities
    Download path: HOTOSM > Netherlands > Health Facilities > Points GeoPackage

    Parameters
    ----------
    file_paths : str or list of str
        Path(s) to the downloaded HOTOSM GeoPackage file(s) on disk.
        Accepted formats: GeoPackage (.gpkg), GeoJSON, Shapefile (.shp).
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
        ext       = os.path.splitext(file_name)[1].lower()
        print(f"\n⏳ Processing HOTOSM health facilities file: {file_name}")

        temp_dir = None
        try:
            # ----------------------------------------------------------
            # STEP 1b: Extract ZIP archives to a temp directory
            # ----------------------------------------------------------
            if ext == ".zip":
                temp_dir = tempfile.mkdtemp(prefix="healthcare_")
                print(f"   📦 Extracting ZIP...")
                with zipfile.ZipFile(file_path) as zf:
                    zf.extractall(temp_dir)
                priority = (".gpkg", ".shp", ".geojson", ".gml", ".fgb")
                found_by_ext = {}
                for root, _, files in os.walk(temp_dir):
                    for f in files:
                        f_ext = os.path.splitext(f)[1].lower()
                        if f_ext in priority and f_ext not in found_by_ext:
                            found_by_ext[f_ext] = os.path.join(root, f)
                found = next((found_by_ext[e] for e in priority if e in found_by_ext), None)
                if not found:
                    print("   ❌ Error: no readable spatial file found inside the ZIP.")
                    continue
                file_path = found
                print(f"   📄 Found: {os.path.basename(file_path)}")

            # ----------------------------------------------------------
            # STEP 2: Reject duplicate loads — check the DB before reading the file
            # ----------------------------------------------------------
            engine_check = create_engine(DB_URI, pool_pre_ping=True)
            with engine_check.connect() as conn:
                table_exists = conn.execute(text(
                    "SELECT EXISTS ("
                    "  SELECT FROM information_schema.tables"
                    "  WHERE table_name = 'health_facilities'"
                    ")"
                )).scalar()

                if table_exists and first_file:
                    already_loaded = conn.execute(
                        text("SELECT EXISTS (SELECT 1 FROM health_facilities LIMIT 1)")
                    ).scalar()
                    if already_loaded:
                        print(f"   ⚠️  '{TABLE_NAME}' already contains data. Skipping to avoid duplicates.")
                        print(f"       Run truncate_healthcare() first if you want to reload.")
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
            # STEP 4: Keep only point geometries
            # HOTOSM exports may include relation boundaries — we only want points.
            # ----------------------------------------------------------
            before = len(gdf)
            gdf = gdf[gdf.geometry.notna()]
            gdf = gdf[gdf.geometry.geom_type.isin(['Point', 'MultiPoint'])]
            dropped = before - len(gdf)
            if dropped > 0:
                print(f"   ⚠️  Dropped {dropped} non-point geometries.")

            # ----------------------------------------------------------
            # STEP 5: Reproject to WGS84 (EPSG:4326) if needed
            # HOTOSM exports are usually already in WGS84.
            # ----------------------------------------------------------
            if gdf.crs is None:
                print(f"   ⚠️  CRS missing — assuming EPSG:4326 (standard for HOTOSM exports).")
                gdf = gdf.set_crs(TARGET_CRS)
            elif gdf.crs.to_epsg() != 4326:
                print(f"   🌍 Reprojecting {gdf.crs} → EPSG:4326...")
                gdf = gdf.to_crs(TARGET_CRS)

            # ----------------------------------------------------------
            # STEP 6: Standardize column names
            # OSM colon-separated keys (name:en, addr:city) are not valid SQL
            # identifiers — rename them before writing to PostGIS.
            # ----------------------------------------------------------
            gdf = _clean_column_names(gdf)

            # ----------------------------------------------------------
            # STEP 7: Cast capacity to numeric where available
            # ----------------------------------------------------------
            if 'capacity_persons' in gdf.columns:
                gdf['capacity_persons'] = pd.to_numeric(gdf['capacity_persons'], errors='coerce')

            # ----------------------------------------------------------
            # STEP 8: Derive simplified facility_type for frontend filtering
            # ----------------------------------------------------------
            gdf = _add_facility_type(gdf)

            # ----------------------------------------------------------
            # STEP 9: Repair and drop invalid geometries
            # ----------------------------------------------------------
            gdf['geometry'] = gdf['geometry'].make_valid()
            gdf = gdf.dropna(subset=['geometry'])

            # ----------------------------------------------------------
            # STEP 10: Write to PostGIS
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
                index=False,
                chunksize=50000,
            )

            # ----------------------------------------------------------
            # STEP 11: Ensure indexes exist for map queries
            # ----------------------------------------------------------
            with engine.begin() as conn:
                conn.execute(text(
                    f"CREATE INDEX IF NOT EXISTS {TABLE_NAME}_geom_idx "
                    f"ON {TABLE_NAME} USING GIST (geometry);"
                ))
                conn.execute(text(
                    f"CREATE INDEX IF NOT EXISTS {TABLE_NAME}_facility_type_idx "
                    f"ON {TABLE_NAME} (facility_type);"
                ))
                osm_id_exists = conn.execute(text(
                    "SELECT EXISTS ("
                    "  SELECT FROM information_schema.columns"
                    "  WHERE table_name = :t AND column_name = 'osm_id'"
                    ")"
                ), {"t": TABLE_NAME}).scalar()
                if osm_id_exists:
                    conn.execute(text(
                        f"CREATE INDEX IF NOT EXISTS {TABLE_NAME}_osm_id_idx "
                        f"ON {TABLE_NAME} (osm_id);"
                    ))
            engine.dispose()

            first_file = False
            print(f"   ✅ Success: {file_name} loaded into '{TABLE_NAME}'.")

        except Exception as e:
            print(f"   ❌ Pipeline failed for {file_name}: {e}")
        finally:
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)

    print(f"\n🎉 Healthcare data loading complete!")


# =========================================================
# ENTRY POINT
# =========================================================
# INSTRUCTIONS:
#   1. Go to https://data.humdata.org/dataset/hotosm_nld_health_facilities
#   2. Download "hotosm_nld_health_facilities_points_gpkg.gpkg"
#   3. Update the path below and run: python load_healthcare.py
# =========================================================
if __name__ == "__main__":

    healthcare_files = [
        {"path": "/Users/khushi/Downloads/hotosm_nld_health_facilities_points_gpkg.gpkg"},
    ]

    if not healthcare_files or healthcare_files[0]["path"].startswith("/path/to/"):
        print("Healthcare loader ready.")
        print("Update the file path(s) in healthcare_files, then run again.")
    else:
        paths = [entry["path"] for entry in healthcare_files]
        load_healthcare(paths)
