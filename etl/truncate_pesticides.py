from sqlalchemy import create_engine, text

# =========================================================
# DATABASE CONFIGURATION
# =========================================================
# Connection string to the local PostGIS database.
# Must match the credentials used across all ETL scripts in this project.
DB_URI = 'postgresql://postgres:admin@localhost:5432/legal_mapping'

engine = create_engine(DB_URI)


def truncate_pesticides():
    """
    Empties all rows from the 'pesticides_measurements' table without destroying the schema.

    Use this before re-loading Pesticides Atlas data (e.g. when a new annual
    export is available from www.bestrijdingsmiddelenatlas.nl) to ensure no
    duplicate records accumulate.

    TRUNCATE vs DELETE:
    - TRUNCATE is faster than DELETE for large tables (no row-by-row logging).
    - RESTART IDENTITY resets the auto-increment 'id' counter back to 1,
      so IDs are clean and sequential after each reload.
    - CASCADE propagates the truncation to any dependent tables (foreign keys),
      preventing constraint violations.

    This pattern is identical to truncate_brp, truncate_krd, truncate_bag, etc.
    """
    table_name = 'pesticides_measurements'
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
                print(f"⚠️  Table '{table_name}' does not exist yet. Run load_pesticides.py first.")

    except Exception as e:
        print(f"❌ Error truncating '{table_name}': {e}")


# =========================================================
# ENTRY POINT
# =========================================================
if __name__ == "__main__":
    truncate_pesticides()
