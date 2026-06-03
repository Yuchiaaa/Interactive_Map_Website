import os
import pyogrio
import geopandas as gpd
from sqlalchemy import create_engine, text, Integer, Float
from dotenv import load_dotenv

load_dotenv()

# =========================================================
# DATABASE CONFIGURATION
# =========================================================
DB_URI = os.environ.get('DATABASE_URL')
if not DB_URI:
    raise ValueError("DATABASE_URL is not set. Please check your .env file.")

# Target table name in the PostGIS database.
# Stores cadastral parcel boundaries with municipality, section, and area attributes,
# sourced from https://www.nationaalgeoregister.nl/geonetwork/srv/dut/catalog.search#/metadata/a29917b9-3426-4041-a11b-69bcb2256904
TABLE_NAME = 'kadastralekaart_perceel'

# =========================================================
# SCHEMA CONFIGURATION
# =========================================================

# Explicit column types — prevents SQLAlchemy from guessing int vs float per batch
DTYPE = {
    'gemeente_code':     Integer(),
    'perceelnummer':     Integer(),
    'kadastralegrootte': Float(),
}

# Mapping of raw file column names → clean DB column names.
# Confirmed against the BRK GeoPackage export from PDOK.
COLUMN_MAP = {
    'identificatie_lokaal_id':    'identificatie',
    'kadastrale_gemeente_code':   'gemeente_code',
    'kadastrale_gemeente_waarde': 'gemeente',
    'sectie':                     'sectie',
    'perceelnummer':              'perceelnummer',
    'kadastrale_grootte_waarde':  'kadastralegrootte',
    'soort_grootte_waarde':       'soortgrootte',
    'status_historie_waarde':     'status',
}


# =========================================================
# LOAD
# =========================================================

def load_kadastralekaart(file_paths):
    """
    Load one or more Kadastrale Kaart (BRK) spatial files into the
    'kadastralekaart_perceel' PostGIS table.

    Source: https://www.nationaalgeoregister.nl/geonetwork/srv/dut/catalog.search#/metadata/a29917b9-3426-4041-a11b-69bcb2256904
    Download path: Nationaal Georegister > BRK Kadastrale Kaart > Perceel > GeoPackage

    Parameters
    ----------
    file_paths : str or list of str
        Path(s) to the downloaded BRK spatial file(s) on disk.
        Multiple province files can be passed as a list — each is appended to the table.
        Accepted formats: GeoPackage (.gpkg), Shapefile (.shp), GeoJSON.
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
        print(f"\n⏳ Processing Kadastrale Kaart file: {file_name}")

        try:
            # ----------------------------------------------------------
            # STEP 2: Reject duplicate loads — check the DB before reading the file
            # ----------------------------------------------------------
            engine_check = create_engine(DB_URI, pool_pre_ping=True)
            with engine_check.connect() as conn:
                table_exists = conn.execute(text(
                    "SELECT EXISTS ("
                    "  SELECT FROM information_schema.tables"
                    "  WHERE table_name = 'kadastralekaart_perceel'"
                    ")"
                )).scalar()

                if table_exists and first_file:
                    already_loaded = conn.execute(
                        text("SELECT EXISTS (SELECT 1 FROM kadastralekaart_perceel LIMIT 1)")
                    ).scalar()
                    if already_loaded:
                        print(f"   ⚠️  '{TABLE_NAME}' already contains data. Skipping to avoid duplicates.")
                        print(f"       Run truncate_kadastralekaart() first if you want to reload.")
                        engine_check.dispose()
                        continue
            engine_check.dispose()

            # ----------------------------------------------------------
            # STEP 3: Inspect layers and available fields
            # ----------------------------------------------------------
            layers     = pyogrio.list_layers(file_path)
            layer_name = layers[0][0]
            info       = pyogrio.read_info(file_path, layer=layer_name)

            print(f"   🗂️  Layer: '{layer_name}' | Features: {info['features']:,}")

            # ----------------------------------------------------------
            # STEP 4: Read the spatial file using pyogrio (fast reader)
            # ----------------------------------------------------------
            print(f"   📖 Reading {info['features']:,} features...")
            gdf = gpd.read_file(file_path, layer=layer_name, engine="pyogrio")

            # ----------------------------------------------------------
            # STEP 5: Standardize column names to lowercase
            # ----------------------------------------------------------
            gdf.columns = [col.lower() for col in gdf.columns]

            # ----------------------------------------------------------
            # STEP 6: Rename columns to clean DB names via COLUMN_MAP
            # Raw file exports use verbose Dutch names; we map them to
            # shorter, consistent names that match the rest of the pipeline.
            # ----------------------------------------------------------
            rename = {raw: clean for raw, clean in COLUMN_MAP.items() if raw in gdf.columns}
            if rename:
                gdf = gdf.rename(columns=rename)

            # ----------------------------------------------------------
            # STEP 7: Reproject to WGS84 (EPSG:4326) if needed
            # BRK datasets are typically in RD New (EPSG:28992).
            # All layers in this pipeline use EPSG:4326 for the web frontend.
            # ----------------------------------------------------------
            if gdf.crs is None or gdf.crs.to_epsg() != 4326:
                print(f"   🌍 Reprojecting {gdf.crs} → EPSG:4326...")
                gdf = gdf.to_crs(epsg=4326)

            # ----------------------------------------------------------
            # STEP 8: Repair and drop invalid geometries
            # Cadastral exports occasionally contain self-intersecting rings.
            # ----------------------------------------------------------
            before = len(gdf)
            gdf['geometry'] = gdf['geometry'].make_valid()
            gdf = gdf.dropna(subset=['geometry'])
            dropped = before - len(gdf)
            if dropped > 0:
                print(f"   ⚠️  Dropped {dropped} rows with invalid/null geometry.")

            # ----------------------------------------------------------
            # STEP 9: Write to PostGIS
            # First file: 'replace' — clean slate with correct schema.
            # Subsequent files: 'append' — add rows for additional provinces.
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
                dtype=DTYPE,
                chunksize=50000,
            )

            # ----------------------------------------------------------
            # STEP 10: Ensure spatial index exists after each file
            # ----------------------------------------------------------
            with engine.begin() as conn:
                conn.execute(text(
                    f"CREATE INDEX IF NOT EXISTS idx_{TABLE_NAME}_geom "
                    f"ON {TABLE_NAME} USING GIST (geometry);"
                ))
            engine.dispose()

            first_file = False
            print(f"   ✅ Success: {file_name} loaded into '{TABLE_NAME}'.")

        except Exception as e:
            print(f"   ❌ Pipeline failed for {file_name}: {e}")

    print(f"\n🎉 Kadastrale Kaart loading complete!")


# =========================================================
# ENTRY POINT
# =========================================================
# INSTRUCTIONS:
#   1. Go to https://www.nationaalgeoregister.nl/geonetwork/srv/dut/catalog.search#/metadata/a29917b9-3426-4041-a11b-69bcb2256904
#   2. Download the BRK Kadastrale Kaart Perceel dataset as GeoPackage
#   3. Update the path(s) below and run: python load_kadastralekaart.py
#
# To load multiple province files, pass a list of file paths.
# The table will be replaced on the first file and appended for the rest.
# =========================================================
if __name__ == "__main__":

    kadastralekaart_files = [
        {"path": "/Users/khushi/Downloads/kadastralekaart_perceel.gpkg"},
        # {"path": "/Users/khushi/Downloads/kadastralekaart_perceel_noord-brabant.gpkg"},
        # {"path": "/Users/khushi/Downloads/kadastralekaart_perceel_gelderland.gpkg"},
    ]

    if not kadastralekaart_files or kadastralekaart_files[0]["path"].startswith("/path/to/"):
        print("Kadastrale Kaart loader ready.")
        print("Update the file path(s) in kadastralekaart_files, then run again.")
    else:
        paths = [entry["path"] for entry in kadastralekaart_files]
        load_kadastralekaart(paths)
