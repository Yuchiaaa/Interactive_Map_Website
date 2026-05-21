"""
Pesticide Exceedance Trend Detection — per Monitoring Station
=============================================================
For each station in pesticides_measurements with ≥ 3 years of data,
applies the Mann-Kendall monotonic trend test on annual peak exceedance.

  - tau > 0, p < 0.05  →  'increasing'  (statistically significant worsening)
  - tau < 0, p < 0.05  →  'decreasing'  (statistically significant improvement)
  - p ≥ 0.05           →  'stable'      (no significant monotonic trend)

The Theil-Sen slope gives the estimated change in exceedance ratio per year.
Results are written to the ml_pesticide_trends table.

Run standalone:  python -m ml.trend_detection
"""

import os
import numpy as np
import pandas as pd
import geopandas as gpd
from datetime import datetime
from scipy import stats
from shapely.geometry import Point
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DB_URI = os.environ.get('DATABASE_URL')
if not DB_URI:
    raise ValueError("DATABASE_URL is not set.")

TABLE = 'ml_pesticide_trends'
MIN_YEARS = 3    # minimum data points required for trend analysis
ALPHA = 0.05     # significance threshold


def _create_table(conn):
    conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            id               SERIAL PRIMARY KEY,
            station_code     INTEGER,
            station_name     TEXT,
            trend            TEXT,
            p_value          FLOAT,
            tau              FLOAT,
            slope            FLOAT,
            year_start       INTEGER,
            year_end         INTEGER,
            n_years          INTEGER,
            mean_exceedance  FLOAT,
            computed_at      TIMESTAMP,
            geometry         GEOMETRY(POINT, 4326)
        )
    """))


def run(engine=None):
    if engine is None:
        engine = create_engine(DB_URI)

    print("⏳ [Trend Detection] Loading pesticide measurements...")

    try:
        df = pd.read_sql(text("""
            SELECT
                meetpunt_code,
                COALESCE(meetpunt_naam, meetpunt_code::text) AS station_name,
                jaar,
                MAX(mate_normov)  AS peak_exceedance,
                AVG(mate_normov)  AS avg_exceedance,
                ST_X(geometry)    AS lon,
                ST_Y(geometry)    AS lat
            FROM pesticides_measurements
            WHERE mate_normov IS NOT NULL
              AND jaar IS NOT NULL
              AND geometry IS NOT NULL
            GROUP BY meetpunt_code, meetpunt_naam, jaar, geometry
            ORDER BY meetpunt_code, jaar
        """), engine)
    except Exception as e:
        print(f"❌ [Trend Detection] Could not load pesticides_measurements: {e}")
        return

    if df.empty:
        print("❌ [Trend Detection] No pesticide data found.")
        return

    print(f"   Loaded {len(df)} station-year rows across {df['meetpunt_code'].nunique()} stations.")

    results = []
    skipped = 0

    for station_code, group in df.groupby('meetpunt_code'):
        group = group.sort_values('jaar').dropna(subset=['peak_exceedance'])

        if len(group) < MIN_YEARS:
            skipped += 1
            continue

        years = group['jaar'].values.astype(float)
        exceedance = group['peak_exceedance'].values.astype(float)

        # Mann-Kendall via scipy kendalltau (equivalent test)
        tau, p_value = stats.kendalltau(years, exceedance)

        # Theil-Sen slope: estimated change in exceedance per year
        slope_result = stats.theilslopes(exceedance, years)
        slope = float(slope_result.slope)

        if p_value < ALPHA:
            trend = 'increasing' if tau > 0 else 'decreasing'
        else:
            trend = 'stable'

        results.append({
            'station_code':   int(station_code),
            'station_name':   str(group['station_name'].iloc[0]),
            'trend':          trend,
            'p_value':        float(p_value),
            'tau':            float(tau),
            'slope':          slope,
            'year_start':     int(years[0]),
            'year_end':       int(years[-1]),
            'n_years':        int(len(years)),
            'mean_exceedance': float(exceedance.mean()),
            'lon':            float(group['lon'].iloc[0]),
            'lat':            float(group['lat'].iloc[0]),
        })

    if not results:
        print(f"❌ [Trend Detection] No stations met the minimum {MIN_YEARS}-year threshold.")
        return

    print(f"   Analysed {len(results)} stations ({skipped} skipped — insufficient years).")

    result_df = pd.DataFrame(results)
    now = datetime.utcnow()
    result_df['computed_at'] = now

    result_gdf = gpd.GeoDataFrame(
        result_df,
        geometry=[Point(r['lon'], r['lat']) for _, r in result_df.iterrows()],
        crs='EPSG:4326'
    ).drop(columns=['lon', 'lat'])

    with engine.begin() as conn:
        _create_table(conn)

    result_gdf.to_postgis(TABLE, engine, if_exists='replace', index=False)

    inc = sum(1 for r in results if r['trend'] == 'increasing')
    dec = sum(1 for r in results if r['trend'] == 'decreasing')
    sta = sum(1 for r in results if r['trend'] == 'stable')
    print(f"✅ [Trend Detection] Done. Increasing: {inc} | Stable: {sta} | Decreasing: {dec}")
    return result_gdf


if __name__ == '__main__':
    run()
