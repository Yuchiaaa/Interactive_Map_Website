from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv

# Load environment variables securely from the .env file
load_dotenv()

# Database Configuration securely loaded from the environment
DB_URI = os.environ.get('DATABASE_URL')

if not DB_URI:
    raise ValueError("DATABASE_URL is not set. Please check your .env file.")

engine = create_engine(DB_URI)

def truncate_grenzen():
    """Empties all rows from the Grenzen table without destroying the schema."""
    table_name = 'grenzen'
    print(f"Emptying data from '{table_name}'...")

    try:
        with engine.begin() as conn:
            # Check if table exists before truncating
            check_query = text("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = :table_name)")
            exists = conn.execute(check_query, {'table_name': table_name}).scalar()

            if exists:
                conn.execute(text(f"TRUNCATE TABLE {table_name} RESTART IDENTITY CASCADE;"))
                print(f"Successfully emptied all data from {table_name}.")
            else:
                print(f"Table {table_name} does not exist yet.")
    except Exception as e:
        print(f"Error truncating {table_name}: {e}")

if __name__ == "__main__":
    # INSTRUCTIONS: Run this script to clear the table data safely.
    truncate_grenzen()
