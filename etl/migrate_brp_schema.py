"""
One-time schema migration for brp_parcels.

The table was originally created with English column names (crop_name, crop_code, area_ha)
from an older version of models.py. The routes and ETL now use the Dutch PDOK names
(gewas, gewascode). Run this script once to fix the DB without touching any data.

Usage:
    python etl/migrate_brp_schema.py
"""

from sqlalchemy import create_engine, text
import os
from dotenv import load_dotenv

load_dotenv()

DB_URI = os.environ.get('DATABASE_URL')
if not DB_URI:
    raise ValueError("DATABASE_URL not set.")

engine = create_engine(DB_URI)

def migrate():
    with engine.begin() as conn:
        # Check table exists at all
        exists = conn.execute(text(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='brp_parcels')"
        )).scalar()

        if not exists:
            print("Table brp_parcels does not exist yet — nothing to migrate.")
            print("It will be created with the correct schema when you first load a BRP file.")
            return

        conn.execute(text("""
            DO $$
            BEGIN
                -- crop_name → gewas
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'brp_parcels' AND column_name = 'crop_name'
                ) THEN
                    ALTER TABLE brp_parcels RENAME COLUMN crop_name TO gewas;
                    RAISE NOTICE 'Renamed crop_name to gewas';
                END IF;

                -- crop_code → gewascode
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'brp_parcels' AND column_name = 'crop_code'
                ) THEN
                    ALTER TABLE brp_parcels RENAME COLUMN crop_code TO gewascode;
                    RAISE NOTICE 'Renamed crop_code to gewascode';
                END IF;

                -- area_ha is now computed on the fly from geometry; drop the stored column
                IF EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'brp_parcels' AND column_name = 'area_ha'
                ) THEN
                    ALTER TABLE brp_parcels DROP COLUMN area_ha;
                    RAISE NOTICE 'Dropped stored area_ha column';
                END IF;
            END $$;
        """))

        # Show final state
        cols = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='brp_parcels' ORDER BY ordinal_position"
        )).fetchall()
        row_count = conn.execute(text("SELECT COUNT(*) FROM brp_parcels")).scalar()

        print(f"Migration complete.")
        print(f"  Columns: {[c[0] for c in cols]}")
        print(f"  Rows:    {row_count}")


if __name__ == "__main__":
    migrate()
