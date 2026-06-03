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


def truncate_brp(year: int = None):
    """
    Clear data from the 'brp_parcels' table.

    Use this before re-loading BRP data (e.g. when a corrected or new annual
    export is available from https://www.pdok.nl/introductie/-/article/basisregistratie-gewaspercelen-brp-)
    to ensure no duplicate records accumulate.

    Parameters
    ----------
    year : int, optional
        When provided, only rows matching that reference year are deleted.
        When omitted, the entire table is truncated (faster, resets ID counter).

    TRUNCATE vs DELETE:
    - TRUNCATE is faster than DELETE for large tables (no row-by-row logging).
    - RESTART IDENTITY resets the auto-increment 'id' counter back to 1,
      so IDs are clean and sequential after each full reload.
    - CASCADE propagates the truncation to any dependent tables (foreign keys),
      preventing constraint violations.
    """
    table_name = 'brp_parcels'

    try:
        with engine.begin() as conn:

            # Check if the table exists before attempting any operation.
            # Avoids a crash on first run when the table hasn't been created yet.
            check_query = text(
                "SELECT EXISTS ("
                "  SELECT FROM information_schema.tables"
                "  WHERE table_name = :table_name"
                ")"
            )
            exists = conn.execute(check_query, {'table_name': table_name}).scalar()

            if not exists:
                print(f"⚠️  Table '{table_name}' does not exist yet. Run load_brp.py first.")
                return

            if year is not None:
                # ----------------------------------------------------------
                # Year-scoped delete — remove only one reference year's rows.
                # Useful when reloading a single year without disturbing others.
                # ----------------------------------------------------------
                print(f"🧹 Deleting '{table_name}' rows for year {year}...")
                conn.execute(
                    text(f"DELETE FROM {table_name} WHERE year = :year"),
                    {"year": int(year)},
                )
                print(f"✅ Deleted all rows for year {year} from '{table_name}'.")
            else:
                # ----------------------------------------------------------
                # Full truncate — fastest way to wipe the entire table.
                # ----------------------------------------------------------
                print(f"🧹 Emptying all data from '{table_name}'...")
                conn.execute(text(f"TRUNCATE TABLE {table_name} RESTART IDENTITY CASCADE;"))
                print(f"✅ Successfully emptied all data from '{table_name}'.")

    except Exception as e:
        print(f"❌ Error truncating '{table_name}': {e}")


# =========================================================
# ENTRY POINT
# =========================================================
if __name__ == "__main__":
    # Truncate all rows:
    truncate_brp()

    # Delete a specific year only:
    # truncate_brp(year=2021)
