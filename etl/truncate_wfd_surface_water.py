from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv

load_dotenv()

DB_URI = os.environ.get('DATABASE_URL')
if not DB_URI:
    raise ValueError("DATABASE_URL is not set. Please check your .env file.")

engine = create_engine(DB_URI)


def truncate_wfd_surface_water():
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE wfd_surface_water RESTART IDENTITY;"))
    print("Success: wfd_surface_water table truncated.")


if __name__ == "__main__":
    truncate_wfd_surface_water()
