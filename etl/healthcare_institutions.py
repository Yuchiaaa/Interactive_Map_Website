import geopandas as gpd
import pandas as pd
from sqlalchemy import create_engine, text
import os

# =========================================================
# DATABASE CONFIGURATION
# =========================================================
DB_URI = 'postgresql://postgres:admin@100.74.81.23:5432/legal_mapping'

# Target table name in PostGIS.
TABLE_NAME = 'health_facilities'

# Web mapping standard used by the rest of the project pipeline.
TARGET_CRS = 'EPSG:4326'


def clean_column_names(gdf):
    """
    Standardizes HOTOSM/OSM column names for PostGIS.
    Convert them to safer names:
        name:en -> name_en
        addr:city -> addr_city
        operator:type -> operator_type
    """
    rename_map = {
        'name:en': 'name_en',
        'name:nl': 'name_nl',
        'healthcare:speciality': 'healthcare_speciality',
        'operator:type': 'operator_type',
        'capacity:persons': 'capacity_persons',
        'addr:full': 'addr_full',
        'addr:city': 'addr_city'
    }

    gdf = gdf.rename(columns=rename_map)
    gdf.columns = [
        col.strip().lower().replace(':', '_').replace('-', '_').replace(' ', '_')
        for col in gdf.columns
    ]
    return gdf


def add_facility_type(gdf):
    """
    Create a simplified 'facility_type' column for easier filtering in the map.

    Priority:
    1. healthcare tag, e.g. doctor, pharmacy, hospital
    2. amenity tag, e.g. doctors, dentist, clinic
    3. unknown
    """
    healthcare = gdf['healthcare'] if 'healthcare' in gdf.columns else pd.Series([None] * len(gdf))
    amenity = gdf['amenity'] if 'amenity' in gdf.columns else pd.Series([None] * len(gdf))

    gdf['facility_type'] = healthcare.fillna(amenity).fillna('unknown')

    # Cleanup for slightly more consistent naming
    gdf['facility_type'] = (
        gdf['facility_type']
        .astype(str)
        .str.lower()
        .str.strip()
        .replace({
            'doctors': 'doctor',
            'dentist': 'dentist',
            'clinic': 'clinic',
            'hospital': 'hospital',
            'pharmacy': 'pharmacy'
        })
    )

    return gdf


def load_health_facilities(file_path):
    """
    Load HOTOSM Netherlands health facilities point data into PostGIS.

    Source:
    HOTOSM Netherlands health facilities points GPKG.

    Included OSM tags:
    - healthcare IS NOT NULL
    - OR amenity IN ('doctors', 'dentist', 'clinic', 'hospital', 'pharmacy')

    Main processing steps:
    1. Read local GeoPackage file
    2. Convert CRS to EPSG:4326 for Leaflet/web mapping compatibility
    3. Clean OSM-style column names
    4. Make geometries valid and remove empty geometries
    5. Create a simplified facility_type column
    6. Load to PostGIS table: health_facilities
    """

    engine = create_engine(DB_URI)

    if not os.path.exists(file_path):
        print(f"❌ Error: File not found at {file_path}")
        return

    print(f"⏳ Processing HOTOSM health facilities: {os.path.basename(file_path)}")

    try:
        # ---------------------------------------------------------
        # STEP 1: Read GeoPackage
        # ---------------------------------------------------------
        gdf = gpd.read_file(file_path)
        print(f"📄 Loaded {len(gdf)} records.")
        print(f"🌍 Source CRS: {gdf.crs}")

        # ---------------------------------------------------------
        # STEP 2: Keep only point geometries
        # This file should already be points, but this protects the pipeline.
        # ---------------------------------------------------------
        gdf = gdf[gdf.geometry.notna()]
        gdf = gdf[gdf.geometry.geom_type.isin(['Point', 'MultiPoint'])]

        # ---------------------------------------------------------
        # STEP 3: Convert to EPSG:4326 if needed
        # Leaflet expects WGS84 longitude/latitude.
        # ---------------------------------------------------------
        if gdf.crs is None:
            print("⚠️ CRS is missing. Assuming EPSG:4326 because HOTOSM exports usually use WGS84.")
            gdf = gdf.set_crs(TARGET_CRS)
        elif gdf.crs.to_epsg() != 4326:
            gdf = gdf.to_crs(TARGET_CRS)
            print("🌍 Reprojected to EPSG:4326.")
        else:
            print("✅ CRS already EPSG:4326.")

        # ---------------------------------------------------------
        # STEP 4: Standardize column names
        # ---------------------------------------------------------
        gdf = clean_column_names(gdf)

        # ---------------------------------------------------------
        # STEP 5: Convert capacity to numeric where available
        # ---------------------------------------------------------
        if 'capacity_persons' in gdf.columns:
            gdf['capacity_persons'] = pd.to_numeric(gdf['capacity_persons'], errors='coerce')

        # ---------------------------------------------------------
        # STEP 6: Add simplified type column for frontend filtering
        # ---------------------------------------------------------
        gdf = add_facility_type(gdf)

        # ---------------------------------------------------------
        # STEP 7: Clean geometries
        # Points usually do not need make_valid, but this keeps the loader
        # consistent with the BAG/Natura loaders.
        # ---------------------------------------------------------
        gdf['geometry'] = gdf['geometry'].make_valid()
        gdf = gdf.dropna(subset=['geometry'])

        # ---------------------------------------------------------
        # STEP 8: Load into PostGIS
        # 'replace' gives a clean refresh each time the HOTOSM file updates.
        # ---------------------------------------------------------
        print(f"📥 Inserting {len(gdf)} records into '{TABLE_NAME}'...")
        gdf.to_postgis(
            TABLE_NAME,
            engine,
            if_exists='replace',
            index=True,
            index_label='id'
        )

        # ---------------------------------------------------------
        # STEP 9: Add useful indexes for map queries
        # ---------------------------------------------------------
        with engine.begin() as conn:
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS {TABLE_NAME}_geom_idx ON {TABLE_NAME} USING GIST (geometry);"))
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS {TABLE_NAME}_facility_type_idx ON {TABLE_NAME} (facility_type);"))
            conn.execute(text(f"CREATE INDEX IF NOT EXISTS {TABLE_NAME}_osm_id_idx ON {TABLE_NAME} (osm_id);"))

        print(f"✅ Success: HOTOSM health facilities loaded into '{TABLE_NAME}'.")
        print("🗺️ Ready for PostGIS queries and Leaflet frontend display.")

    except Exception as e:
        print(f"❌ Failed to load HOTOSM health facilities: {e}")


if __name__ == "__main__":
    health_file = "/Users/erikamelodyscales/Desktop/hotosm_nld_health_facilities_points_gpkg/hotosm_nld_health_facilities_points_gpkg.gpkg"

    load_health_facilities(health_file)
