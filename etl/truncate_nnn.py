from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os

load_dotenv()

# =========================================================
# DATABASE CONFIGURATION
# =========================================================
DB_URI = os.environ.get('DATABASE_URL')
if not DB_URI:
    raise ValueError("DATABASE_URL is not set. Please check your .env file.")

engine = create_engine(DB_URI)


def truncate_nnn():
    """
    Empties all rows from the 'nnn_areas' table without destroying the schema.

    Use this before re-loading NNN data (e.g. when an updated INSPIRE export is
    available from https://www.nationaalgeoregister.nl/geonetwork/srv/dut/catalog.search#/metadata/c7d8d77b-8c47-4309-8c58-9b12b086407f)
    to ensure no duplicate records accumulate.

    TRUNCATE vs DELETE:
    - TRUNCATE is faster than DELETE for large tables (no row-by-row logging).
    - RESTART IDENTITY resets the auto-increment 'id' counter back to 1,
      so IDs are clean and sequential after each reload.
    - CASCADE propagates the truncation to any dependent tables (foreign keys),
      preventing constraint violations.
    """
    table_name = 'nnn_areas'
    print(f"🧹 Emptying data from '{table_name}'...")

    try:
        with engine.begin() as conn:

            # Check if the table exists before attempting to truncate.
            # Avoids a crash on first run when the table hasn't been created yet.
            check_query = text(
                "SELECT EXISTS ("
                "  SELECT FROM information_schema.tables"
                "  WHERE table_name = :table_name"
                ")"
            )
            exists = conn.execute(check_query, {'table_name': table_name}).scalar()

            if exists:
                conn.execute(text(f"TRUNCATE TABLE {table_name} RESTART IDENTITY CASCADE;"))
                print(f"✅ Successfully emptied all data from '{table_name}'.")
            else:
                print(f"⚠️  Table '{table_name}' does not exist yet. Run load_nnn.py first.")

    except Exception as e:
        print(f"❌ Error truncating '{table_name}': {e}")


# =========================================================
# ENTRY POINT
# =========================================================
if __name__ == "__main__":
    truncate_nnn()
