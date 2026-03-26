from sqlalchemy import create_engine, text

# Database Configuration
DB_URI = 'postgresql://postgres:admin@localhost:5432/legal_mapping'
engine = create_engine(DB_URI)

def truncate_brp():
    """Empties all rows from the BRP parcels table without destroying the schema."""
    table_name = 'brp_parcels'
    print(f"🧹 Empting data from '{table_name}'...")
    
    try:
        with engine.begin() as conn:
            # Check if table exists before truncating
            check_query = text("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = :table_name)")
            exists = conn.execute(check_query, {'table_name': table_name}).scalar()
            
            if exists:
                conn.execute(text(f"TRUNCATE TABLE {table_name} RESTART IDENTITY CASCADE;"))
                print(f"✅ Successfully emptied all data from {table_name}.")
            else:
                print(f"⚠️ Table {table_name} does not exist yet.")
    except Exception as e:
        print(f"❌ Error truncating {table_name}: {e}")

if __name__ == "__main__":
    truncate_brp()