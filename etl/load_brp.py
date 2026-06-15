import zipfile
import tempfile
import shutil
import os
import re
import pyogrio
import geopandas as gpd
from shapely.geometry import MultiPolygon
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
# Stores crop parcel boundaries with crop name, crop code, and reference year,
# sourced from https://www.pdok.nl/introductie/-/article/basisregistratie-gewaspercelen-brp-
TABLE_NAME = 'brp_parcels'


# =========================================================
# LOAD
# =========================================================

def load_brp(file_paths, manual_year: int = None):
    """
    Load one or more BRP spatial files into the 'brp_parcels' PostGIS table.

    Source: https://www.pdok.nl/introductie/-/article/basisregistratie-gewaspercelen-brp-
    Download path: PDOK > BRP Gewaspercelen > Definitief > [year]

    Accepted formats: GeoPackage (.gpkg), Shapefile (.shp), GeoJSON, GML,
    FlatGeobuf (.fgb), KML, MapInfo TAB, or a ZIP archive containing any of the above.

    Parameters
    ----------
    file_paths : str or list of str
        Path(s) to the downloaded spatial file(s) on disk.
        Multiple years can be passed as a list — each file is appended to the table.
    manual_year : int, optional
        Override the year for all records. Only needed if the filename does not
        contain a recognisable year (e.g. brpgewaspercelen_definitief_2024.gpkg).
    """

    # Normalize input: always work with a list of paths
    if isinstance(file_paths, str):
        file_paths = [file_paths]

    for file_path in file_paths:

        # ----------------------------------------------------------
        # STEP 1: Validate the file exists
        # ----------------------------------------------------------
        if not os.path.exists(file_path):
            print(f"❌ Error: file not found: {file_path}")
            continue

        file_name = os.path.basename(file_path)
        ext       = os.path.splitext(file_name)[1].lower()
        print(f"\n⏳ Processing BRP file: {file_name}")

        temp_dir = None
        try:
            # ----------------------------------------------------------
            # STEP 2: Extract ZIP archives to a temp directory
            # Older BRP exports (2009–2019) ship as a ZIP containing a shapefile.
            # ----------------------------------------------------------
            if ext == ".zip":
                temp_dir = tempfile.mkdtemp(prefix="brp_")
                print(f"   📦 Extracting ZIP...")
                with zipfile.ZipFile(file_path) as zf:
                    zf.extractall(temp_dir)
                actual_path = _find_spatial_file(temp_dir)
                if not actual_path:
                    print("   ❌ Error: no readable spatial file found inside the ZIP.")
                    continue
                print(f"   📄 Found: {os.path.basename(actual_path)}")
            else:
                actual_path = file_path

            _ingest(actual_path, file_name, manual_year)

        except Exception as e:
            print(f"   ❌ Pipeline failed for {file_name}: {e}")
        finally:
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)

    print(f"\n🎉 BRP loading complete!")


def _find_spatial_file(directory: str) -> str | None:
    """Return the first readable spatial file in a directory tree, preferring GPKG over SHP."""
    priority = (".gpkg", ".shp", ".geojson", ".json", ".gml", ".fgb", ".kml", ".tab")
    found = {}
    for root, dirs, files in os.walk(directory):
        # .gdb is a directory-based format — detect it by directory name
        for d in dirs:
            if d.lower().endswith(".gdb") and ".gdb" not in found:
                found[".gdb"] = os.path.join(root, d)
        for f in files:
            f_ext = os.path.splitext(f)[1].lower()
            if f_ext in priority and f_ext not in found:
                found[f_ext] = os.path.join(root, f)
    for f_ext in priority:
        if f_ext in found:
            return found[f_ext]
    # Fall back to .gdb if no file-based format found
    if ".gdb" in found:
        return found[".gdb"]
    return None


def _ingest(file_path: str, original_name: str, manual_year: int = None):
    """Read, normalise, and write one spatial file to brp_parcels."""

    # ----------------------------------------------------------
    # STEP 3: Inspect layers and available fields
    # ----------------------------------------------------------
    layers     = pyogrio.list_layers(file_path)
    layer_name = layers[0][0]
    info       = pyogrio.read_info(file_path, layer=layer_name)
    fields     = [f.lower() for f in info.get("fields", [])]

    # ----------------------------------------------------------
    # STEP 4: Resolve column name variants across BRP years
    # Column names differ between older shapefile exports and newer GPKG exports.
    # ----------------------------------------------------------
    gewas_col = next(
        (c for c in ("gewasnaam", "gewas", "crop_name", "cropname", "naam") if c in fields),
        None,
    )
    gewascode_col = next(
        (c for c in ("gewascode", "gewas_code", "crop_code", "cropcode") if c in fields),
        None,
    )

    # ----------------------------------------------------------
    # STEP 5: Resolve the year from the filename
    # BRP files never contain a year column — the year is always encoded
    # in the filename (e.g. brpgewaspercelen_definitief_2024.gpkg).
    # manual_year can be passed as an override for non-standard filenames.
    # ----------------------------------------------------------
    if manual_year is not None:
        year = int(manual_year)
    else:
        m = re.search(r"(19|20)\d{2}", original_name)
        if m:
            year = int(m.group())
        else:
            print("   ❌ Error: cannot determine year — include the year in the filename or pass manual_year.")
            return

    # ----------------------------------------------------------
    # STEP 6: Reject duplicate years — check the DB before reading the full file
    # ----------------------------------------------------------
    engine_check = create_engine(DB_URI, pool_pre_ping=True)
    with engine_check.connect() as conn:
        table_exists = conn.execute(text(
            "SELECT EXISTS ("
            "  SELECT FROM information_schema.tables"
            "  WHERE table_name = 'brp_parcels'"
            ")"
        )).scalar()

        if table_exists:
            already_loaded = conn.execute(
                text("SELECT EXISTS (SELECT 1 FROM brp_parcels WHERE year = :year LIMIT 1)"),
                {"year": year},
            ).scalar()
            if already_loaded:
                print(f"   ⚠️  Year {year} already exists in '{TABLE_NAME}'. Skipping to avoid duplicates.")
                print(f"       Run truncate_brp(year={year}) first if you want to reload this year.")
                engine_check.dispose()
                return
    engine_check.dispose()

    print(f"   🗂️  Layer: '{layer_name}' | Features: {info['features']:,}")
    print(f"   🏷️  gewas='{gewas_col}' | gewascode='{gewascode_col}' | year={year}")

    # ----------------------------------------------------------
    # STEP 7: Read only the columns we need (speeds up large GPKG files)
    # ----------------------------------------------------------
    read_cols = [c for c in (gewas_col, gewascode_col) if c]
    print(f"   📖 Reading {info['features']:,} features...")
    gdf = gpd.read_file(file_path, layer=layer_name, columns=read_cols or None, engine="pyogrio")

    # ----------------------------------------------------------
    # STEP 8: Reproject to WGS84 (EPSG:4326) if needed
    # BRP datasets are typically in RD New (EPSG:28992).
    # All layers in this pipeline use EPSG:4326 for the web frontend.
    # ----------------------------------------------------------
    if gdf.crs is None or gdf.crs.to_epsg() != 4326:
        print(f"   🌍 Reprojecting {gdf.crs} → EPSG:4326...")
        gdf = gdf.to_crs(epsg=4326)

    # ----------------------------------------------------------
    # STEP 9: Normalise columns to a consistent schema
    # ----------------------------------------------------------
    gdf["year"] = year

    if gewas_col and gewas_col != "gewas":
        gdf = gdf.rename(columns={gewas_col: "gewas"})
    elif not gewas_col:
        gdf["gewas"] = None

    if gewascode_col and gewascode_col != "gewascode":
        gdf = gdf.rename(columns={gewascode_col: "gewascode"})
    elif not gewascode_col:
        gdf["gewascode"] = None

    # ----------------------------------------------------------
    # STEP 10: Ensure consistent MultiPolygon geometry type
    # Older shapefiles may contain Polygon geometries — cast to MultiPolygon
    # so the PostGIS column type stays uniform across all years.
    # ----------------------------------------------------------
    poly_mask = gdf.geometry.geom_type == "Polygon"
    if poly_mask.any():
        gdf.loc[poly_mask, "geometry"] = gdf.loc[poly_mask, "geometry"].apply(
            lambda g: MultiPolygon([g])
        )

    gdf = gdf[["gewas", "gewascode", "year", "geometry"]]

    # ----------------------------------------------------------
    # STEP 11: Write to PostGIS (append to existing table)
    # ----------------------------------------------------------
    engine = create_engine(
        DB_URI,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 300, "options": "-c statement_timeout=0"},
    )
    print(f"   📥 Inserting {len(gdf):,} records into '{TABLE_NAME}' (chunksize=50 000)...")
    gdf.to_postgis(TABLE_NAME, engine, if_exists="append", index=False, chunksize=50000)
    engine.dispose()
    print(f"   ✅ Success: {len(gdf):,} features loaded into '{TABLE_NAME}'.")


# =========================================================
# ENTRY POINT
# =========================================================
# INSTRUCTIONS:
#   1. Go to https://www.pdok.nl/introductie/-/article/basisregistratie-gewaspercelen-brp-
#   2. Download the desired year(s) — GPKG for 2020–2025, ZIP for 2009–2019
#   3. Update the path(s) below and run: python load_brp.py
#
# To load multiple years, pass a list of file paths.
# All files are appended to the brp_parcels table.
# =========================================================
if __name__ == "__main__":

    brp_files = [
        {"path": "/Users/khushi/Downloads/brpgewaspercelen_definitief_2025.gpkg"},
        {"path": "/Users/khushi/Downloads/brpgewaspercelen_definitief_2024.gpkg"},
        {"path": "/Users/khushi/Downloads/brpgewaspercelen_definitief_2023.gpkg"},
        {"path": "/Users/khushi/Downloads/brpgewaspercelen_definitief_2022.gpkg"},
        {"path": "/Users/khushi/Downloads/brpgewaspercelen_definitief_2021.gpkg"},
        {"path": "/Users/khushi/Downloads/brpgewaspercelen_definitief_2020.gpkg"},
    ]

    if not brp_files or brp_files[0]["path"].startswith("/path/to/"):
        print("BRP loader ready.")
        print("Update the file path(s) in brp_files, then run again.")
    else:
        paths = [entry["path"] for entry in brp_files]
        load_brp(paths)
