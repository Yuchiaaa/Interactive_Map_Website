"""
Run all ML analyses in sequence.

Usage:
    python -m ml.run_all

What it does:
    1. Environmental Risk Score   →  ml_risk_scores table
    2. Pesticide Trend Detection  →  ml_pesticide_trends table
    3. Farm Anomaly Detection     →  ml_farm_anomalies table

Results are stored in the PostgreSQL database and immediately served
by the Flask app at /api/ml/risk_scores, /api/ml/pesticide_trends,
and /api/ml/farm_anomalies.

Make sure the Flask app has been started at least once first so that
db.create_all() creates the result tables.
"""

import os
import time
from sqlalchemy import create_engine
from dotenv import load_dotenv

load_dotenv()

DB_URI = os.environ.get('DATABASE_URL')
if not DB_URI:
    raise ValueError("DATABASE_URL is not set. Check your .env file.")


def main():
    engine = create_engine(DB_URI)

    print("=" * 60)
    print("  Environmental Intelligence — ML Analysis Suite")
    print("=" * 60)

    analyses = [
        ('Environmental Risk Score',  'ml.risk_score'),
        ('Pesticide Trend Detection', 'ml.trend_detection'),
        ('Farm Anomaly Detection',    'ml.anomaly_detection'),
    ]

    for name, module_path in analyses:
        print(f"\n{'─' * 60}")
        print(f"  Running: {name}")
        print(f"{'─' * 60}")
        t0 = time.time()
        try:
            # Dynamic import so each module can be run independently too
            parts = module_path.split('.')
            mod = __import__(module_path, fromlist=[parts[-1]])
            mod.run(engine=engine)
            elapsed = time.time() - t0
            print(f"  Completed in {elapsed:.1f}s")
        except Exception as e:
            print(f"  ❌ {name} failed: {e}")

    print(f"\n{'=' * 60}")
    print("  All analyses complete. Refresh the ML page to see results.")
    print("=" * 60)


if __name__ == '__main__':
    main()
