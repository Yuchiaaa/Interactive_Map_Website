"""
Farm Emission Anomaly Detection — KRD Livestock Farms
======================================================
Uses scikit-learn's Isolation Forest on three emission features:
  - NH3 (kg/yr)        — ammonia
  - Geur (ouE/s)       — odour
  - Fijnstof (g/yr)    — fine particulate matter

All three are log1p-transformed before training to reduce the effect of
extreme outliers and right-skewed distributions.

Farms whose anomaly_score is below the Isolation Forest decision threshold
are flagged as anomalies (is_anomaly = True, approximately 5% of farms).
These are the facilities with emission profiles statistically unusual
compared to the broader population — worth further investigation.

Results are written to the ml_farm_anomalies table.

Run standalone:  python -m ml.anomaly_detection
"""

import os
import numpy as np
import pandas as pd
import geopandas as gpd
from datetime import datetime
from shapely.geometry import Point
from sklearn.ensemble import IsolationForest
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DB_URI = os.environ.get('DATABASE_URL')
if not DB_URI:
    raise ValueError("DATABASE_URL is not set.")

TABLE = 'ml_farm_anomalies'
CONTAMINATION = 0.05    # expected fraction of anomalies


def _create_table(conn):
    conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
            id             SERIAL PRIMARY KEY,
            farm_id        INTEGER,
            adres          TEXT,
            gemeente       TEXT,
            provincie      TEXT,
            anomaly_score  FLOAT,
            is_anomaly     BOOLEAN,
            nh3            FLOAT,
            geur           FLOAT,
            fijnstof       FLOAT,
            computed_at    TIMESTAMP,
            geometry       GEOMETRY(POINT, 4326)
        )
    """))


def run(engine=None):
    if engine is None:
        engine = create_engine(DB_URI)

    print("⏳ [Anomaly Detection] Loading farm emission data...")

    try:
        df = pd.read_sql(text("""
            SELECT
                id,
                adres,
                gemeente,
                provincie,
                NULLIF("nh3 emissie (kg/j)", '')::float      AS nh3,
                NULLIF("geur emissie (oue/s)", '')::float    AS geur,
                NULLIF("fijnstof emissie (g/j)", '')::float  AS fijnstof,
                ST_X(geometry) AS lon,
                ST_Y(geometry) AS lat
            FROM krd_farms
            WHERE geometry IS NOT NULL
        """), engine)
    except Exception as e:
        print(f"❌ [Anomaly Detection] Could not load krd_farms: {e}")
        return

    if df.empty:
        print("❌ [Anomaly Detection] krd_farms table is empty.")
        return

    for col in ['nh3', 'geur', 'fijnstof']:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0).clip(lower=0)

    # Keep only farms with at least one non-zero emission value
    df = df[(df['nh3'] > 0) | (df['geur'] > 0) | (df['fijnstof'] > 0)].copy()

    if len(df) < 10:
        print("❌ [Anomaly Detection] Not enough farms with emission data.")
        return

    print(f"   Training on {len(df)} farms with emission data.")

    # Log-transform to handle heavy right skew
    X = np.log1p(df[['nh3', 'geur', 'fijnstof']].values)

    clf = IsolationForest(
        n_estimators=200,
        contamination=CONTAMINATION,
        random_state=42,
        n_jobs=-1,
    )
    clf.fit(X)

    # decision_function: higher = more normal, lower = more anomalous
    df['anomaly_score'] = clf.decision_function(X)
    df['is_anomaly'] = clf.predict(X) == -1    # -1 means anomaly

    n_anomalies = df['is_anomaly'].sum()
    print(f"   Flagged {n_anomalies} farms as anomalies ({n_anomalies/len(df)*100:.1f}%).")

    now = datetime.utcnow()
    df['computed_at'] = now

    result_gdf = gpd.GeoDataFrame(
        df[['id', 'adres', 'gemeente', 'provincie',
            'anomaly_score', 'is_anomaly',
            'nh3', 'geur', 'fijnstof', 'computed_at', 'lon', 'lat']].rename(columns={'id': 'farm_id'}),
        geometry=[Point(r['lon'], r['lat']) for _, r in df.iterrows()],
        crs='EPSG:4326'
    ).drop(columns=['lon', 'lat'])

    with engine.begin() as conn:
        _create_table(conn)

    result_gdf.to_postgis(TABLE, engine, if_exists='replace', index=False)
    print(f"✅ [Anomaly Detection] Done. {len(result_gdf)} farms written to {TABLE}.")
    return result_gdf


if __name__ == '__main__':
    run()
