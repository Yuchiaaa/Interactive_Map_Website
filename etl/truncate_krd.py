from sqlalchemy import create_engine, text

# =========================================================
# DATABASE CONFIGURATION
# =========================================================
# Connection string to the local PostGIS database.
# Must match the credentials used across all ETL scripts in this project.
DB_URI = 'postgresql://postgres:admin@localhost:5432/legal_mapping'

engine = create_engine(DB_URI)


def truncate_krd():
    """
    Empties all rows from the 'krd_farms' table without destroying the schema.

    Use this script before re-loading KRD data (e.g. when a new export is available
    from https://krd.igoview.nl/) to ensure no duplicate records accumulate.

    TRUNCATE vs DELETE:
    - TRUNCATE is faster than DELETE for large tables (no row-by-row logging).
    - RESTART IDENTITY resets the auto-increment 'id' counter back to 1,
      so IDs are clean and sequential after each reload.
    - CASCADE propagates the truncation to any dependent tables (foreign keys),
      preventing constraint violations.

    This pattern is identical to truncate_brp, truncate_bag, etc.
    """
    table_name = 'krd_farms'
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
                # TRUNCATE: removes all rows, resets ID sequence, cascades to dependents
                conn.execute(text(f"TRUNCATE TABLE {table_name} RESTART IDENTITY CASCADE;"))
                print(f"✅ Successfully emptied all data from '{table_name}'.")
            else:
                # Table doesn't exist yet — nothing to truncate
                print(f"⚠️  Table '{table_name}' does not exist yet. Run load_krd.py first.")

    except Exception as e:
        print(f"❌ Error truncating '{table_name}': {e}")


# =========================================================
# ENTRY POINT
# =========================================================
if __name__ == "__main__":
    truncate_krd()
