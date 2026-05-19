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


def truncate_healthcare():
    """
    Empties all rows from the 'health_facilities' table without destroying the schema.

    Use this before re-loading HOTOSM health facilities data to ensure no
    duplicate records accumulate.
    """
    table_name = 'health_facilities'
    print(f"🧹 Emptying data from '{table_name}'...")

    try:
        with engine.begin() as conn:
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
                print(f"⚠️  Table '{table_name}' does not exist yet. Run load_healthcare.py first.")

    except Exception as e:
        print(f"❌ Error truncating '{table_name}': {e}")


# =========================================================
# ENTRY POINT
# =========================================================
if __name__ == "__main__":
    truncate_healthcare()
