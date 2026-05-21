"""
Environmental Risk Score — per KRD Livestock Farm
==================================================
Computes a composite 0-100 risk score for each farm by combining four
independently normalised components:

  1. NH3 emission intensity      (30%)  — percentile rank of raw NH3 kg/yr
  2. Natura 2000 proximity       (30%)  — 1 / (1 + dist_km / 5)
  3. Pesticide exceedance nearby (25%)  — normalised ratio at nearest station
  4. Sensitive receptor density  (15%)  — percentile rank of (schools + clinics) within 5 km

Results are written to the ml_risk_scores table.

Run standalone:  python -m ml.risk_score
"""

import os
import sys
import numpy as np
import pandas as pd
import geopandas as gpd
from datetime import datetime
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DB_URI = os.environ.get('DATABASE_URL')
if not DB_URI:
    raise ValueError("DATABASE_URL is not set.")

WEIGHTS = {'nh3': 0.30, 'natura': 0.30, 'pesticide': 0.25, 'sensitivity': 0.15}
TABLE = 'ml_risk_scores'


def _create_table(conn):
    conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            id                   SERIAL PRIMARY KEY,
            farm_id              INTEGER,
            adres                TEXT,
            gemeente             TEXT,
            provincie            TEXT,
            risk_score           FLOAT,
            nh3_component        FLOAT,
            natura_component     FLOAT,
            pesticide_component  FLOAT,
            sensitivity_component FLOAT,
            nh3_value            FLOAT,
            dist_natura_km       FLOAT,
            nearest_exceedance   FLOAT,
            schools_within_5km   INTEGER,
            computed_at          TIMESTAMP,
            geometry             GEOMETRY(POINT, 4326)
        )
    """))


def run(engine=None):
    if engine is None:
        engine = create_engine(DB_URI)

    print("⏳ [Risk Score] Loading farm data...")

    # 1. Load KRD farms
    try:
        farms_gdf = gpd.read_postgis(
            """SELECT id, adres, gemeente, provincie,
                      NULLIF("nh3 emissie (kg/j)", '')::float AS nh3,
                      geometry
               FROM krd_farms
               WHERE geometry IS NOT NULL""",
            engine, geom_col='geometry'
        )
    except Exception as e:
        print(f"❌ [Risk Score] Could not load krd_farms: {e}")
        return

    if farms_gdf.empty:
        print("❌ [Risk Score] krd_farms table is empty.")
        return

    farms_gdf['nh3'] = pd.to_numeric(farms_gdf['nh3'], errors='coerce').fillna(0.0)
    print(f"   Loaded {len(farms_gdf)} farms.")

    # 2. Distance to nearest Natura 2000 boundary (projected, accurate)
    print("⏳ [Risk Score] Computing Natura 2000 proximity...")
    try:
        natura_gdf = gpd.read_postgis(
            "SELECT geometry FROM natura2000_areas WHERE geometry IS NOT NULL",
            engine, geom_col='geometry', crs='EPSG:28992'
        ).to_crs('EPSG:4326')

        farms_proj = farms_gdf[['id', 'geometry']].to_crs('EPSG:28992')
        natura_proj = natura_gdf.to_crs('EPSG:28992')

        nearest = gpd.sjoin_nearest(
            farms_proj.reset_index(drop=True),
            natura_proj[['geometry']].reset_index(drop=True),
            how='left',
            distance_col='dist_natura_m'
        ).drop_duplicates(subset='id')[['id', 'dist_natura_m']]

        farms_gdf = farms_gdf.merge(nearest, on='id', how='left')
        farms_gdf['dist_natura_km'] = (farms_gdf['dist_natura_m'].fillna(25_000) / 1000.0)
    except Exception as e:
        print(f"   ⚠️  Natura distance failed ({e}). Defaulting to 25 km.")
        farms_gdf['dist_natura_km'] = 25.0

    # 3. Nearest pesticide monitoring station exceedance (PostGIS KNN)
    print("⏳ [Risk Score] Fetching nearest pesticide exceedance...")
    try:
        pesticide_df = pd.read_sql(text("""
            WITH station_avg AS (
                SELECT meetpunt_code, geometry,
                       AVG(mate_normov) AS avg_exceedance
                FROM pesticides_measurements
                WHERE mate_normov IS NOT NULL
                GROUP BY meetpunt_code, geometry
            )
            SELECT DISTINCT ON (k.id)
                k.id,
                s.avg_exceedance AS nearest_exceedance
            FROM krd_farms k
            CROSS JOIN LATERAL (
                SELECT avg_exceedance
                FROM station_avg
                ORDER BY k.geometry <-> geometry
                LIMIT 1
            ) s
            WHERE k.geometry IS NOT NULL
        """), engine)
        farms_gdf = farms_gdf.merge(pesticide_df, on='id', how='left')
        farms_gdf['nearest_exceedance'] = farms_gdf['nearest_exceedance'].fillna(0.0)
    except Exception as e:
        print(f"   ⚠️  Pesticide join failed ({e}). Setting exceedance to 0.")
        farms_gdf['nearest_exceedance'] = 0.0

    # 4. Sensitive receptors within 5 km (PostGIS DWithin)
    print("⏳ [Risk Score] Counting schools and health facilities within 5 km...")
    try:
        sensitivity_df = pd.read_sql(text("""
            SELECT k.id,
                   COUNT(DISTINCT s.id) AS schools_count,
                   COUNT(DISTINCT h.id) AS health_count
            FROM krd_farms k
            LEFT JOIN schools s
                   ON ST_DWithin(k.geometry::geography, s.geometry::geography, 5000)
            LEFT JOIN health_facilities h
                   ON ST_DWithin(k.geometry::geography, h.geometry::geography, 5000)
            WHERE k.geometry IS NOT NULL
            GROUP BY k.id
        """), engine)
        farms_gdf = farms_gdf.merge(sensitivity_df, on='id', how='left')
        farms_gdf['schools_count'] = farms_gdf['schools_count'].fillna(0).astype(int)
        farms_gdf['health_count'] = farms_gdf['health_count'].fillna(0).astype(int)
    except Exception as e:
        print(f"   ⚠️  Sensitivity join failed ({e}). Setting counts to 0.")
        farms_gdf['schools_count'] = 0
        farms_gdf['health_count'] = 0

    # 5. Normalise components
    def pct_rank(s):
        return s.rank(pct=True, na_option='bottom')

    farms_gdf['nh3_norm'] = pct_rank(farms_gdf['nh3'])
    # Proximity: dist=0 → 1.0, dist=5km → 0.5, dist=25km → 0.17
    farms_gdf['natura_norm'] = 1.0 / (1.0 + farms_gdf['dist_natura_km'] / 5.0)
    farms_gdf['pesticide_norm'] = np.clip(farms_gdf['nearest_exceedance'], 0, 100) / 100.0
    farms_gdf['sensitivity_raw'] = farms_gdf['schools_count'] + farms_gdf['health_count']
    farms_gdf['sensitivity_norm'] = pct_rank(farms_gdf['sensitivity_raw'])

    # 6. Composite score 0–100
    farms_gdf['risk_score'] = (
        WEIGHTS['nh3']         * farms_gdf['nh3_norm'] +
        WEIGHTS['natura']      * farms_gdf['natura_norm'] +
        WEIGHTS['pesticide']   * farms_gdf['pesticide_norm'] +
        WEIGHTS['sensitivity'] * farms_gdf['sensitivity_norm']
    ) * 100
    farms_gdf['risk_score'] = farms_gdf['risk_score'].clip(0, 100).round(1)

    # 7. Write to DB
    print(f"⏳ [Risk Score] Writing {len(farms_gdf)} results to {TABLE}...")
    now = datetime.utcnow()

    result_gdf = gpd.GeoDataFrame({
        'farm_id':               farms_gdf['id'].astype(int),
        'adres':                 farms_gdf['adres'].fillna(''),
        'gemeente':              farms_gdf['gemeente'].fillna(''),
        'provincie':             farms_gdf['provincie'].fillna(''),
        'risk_score':            farms_gdf['risk_score'],
        'nh3_component':         farms_gdf['nh3_norm'].round(4),
        'natura_component':      farms_gdf['natura_norm'].round(4),
        'pesticide_component':   farms_gdf['pesticide_norm'].round(4),
        'sensitivity_component': farms_gdf['sensitivity_norm'].round(4),
        'nh3_value':             farms_gdf['nh3'].round(2),
        'dist_natura_km':        farms_gdf['dist_natura_km'].round(3),
        'nearest_exceedance':    farms_gdf['nearest_exceedance'].round(4),
        'schools_within_5km':    farms_gdf['schools_count'].astype(int),
        'computed_at':           now,
        'geometry':              farms_gdf['geometry'],
    }, geometry='geometry', crs='EPSG:4326')

    with engine.begin() as conn:
        _create_table(conn)

    result_gdf.to_postgis(TABLE, engine, if_exists='replace', index=False)
    print(f"✅ [Risk Score] Done. {len(result_gdf)} farms scored.")
    return result_gdf


if __name__ == '__main__':
    run()
