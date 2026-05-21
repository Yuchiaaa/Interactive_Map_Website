from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv
load_dotenv()

# =========================================================
# DATABASE CONFIGURATION
# =========================================================
DB_URI = os.environ.get('DATABASE_URL')
if not DB_URI:
    raise ValueError("DATABASE_URL is not set. Please check your .env file.")
engine = create_engine(DB_URI)

def truncate_schools():
    """
    Empties all rows from the 'schools' table without destroying the schema.

    Use this before re-loading final_schools_with_coordinates.csv
    to prevent duplicate entries.

    - TRUNCATE is faster than DELETE
    - RESTART IDENTITY resets the primary key counter
    - CASCADE ensures foreign key safety
    """

    table_name = 'schools'
    print(f"🧹 Emptying data from '{table_name}'...")

    try:
        with engine.begin() as conn:

            # ----------------------------------------------------------
            # STEP 1: Check if table exists
            # ----------------------------------------------------------
            check_query = text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = :table_name
                );
            """)

            exists = conn.execute(
                check_query,
                {"table_name": table_name}
            ).scalar()

            # ----------------------------------------------------------
            # STEP 2: Truncate safely
            # ----------------------------------------------------------
            if exists:
                conn.execute(text(f"""
                    TRUNCATE TABLE {table_name}
                    RESTART IDENTITY CASCADE;
                """))
                print(f"✅ Successfully emptied '{table_name}'.")
            else:
                print(f"⚠️ Table '{table_name}' does not exist yet. Run your schools loader first.")

    except Exception as e:
        print(f"❌ Error truncating '{table_name}': {e}")


# =========================================================
# ENTRY POINT
# =========================================================
if __name__ == "__main__":
    truncate_schools()
