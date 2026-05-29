from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv
load_dotenv()

DB_URI = os.environ.get('DATABASE_URL')
if not DB_URI:
    raise ValueError("DATABASE_URL is not set. Please check your .env file.")

engine = create_engine(DB_URI)


def truncate_stallen():
    """
    Empties all rows from 'krd_stallen' without destroying the schema.

    Run this before re-loading stallen data when a new KRD export is available.
    Get the export from: https://krd.igoview.nl/ → Stallen tab → Totaaloverzicht stallen.
    """
    table_name = 'krd_stallen'
    print(f"Emptying data from '{table_name}'...")

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
                print(f"Done: emptied all data from '{table_name}'.")
            else:
                print(f"Table '{table_name}' does not exist yet. Run load_stallen.py first.")

    except Exception as e:
        print(f"Error truncating '{table_name}': {e}")


if __name__ == "__main__":
    truncate_stallen()
