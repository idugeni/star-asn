import os
import sys
import asyncio
from dotenv import load_dotenv

load_dotenv()

# Add root directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from star_attendance.bootstrap_db import bootstrap_database
from star_attendance.runtime import get_store

def init_supabase():
    print("--- STAR-ASN SUPABASE INITIALIZATION START ---")
    
    # 1. Verify URL
    db_url = os.getenv("POSTGRES_URL")
    if not db_url or "supabase" not in db_url.lower():
        print("WARNING: POSTGRES_URL doesn't look like a Supabase URL.")
    
    print("Running deterministic SQL migrations and queue bootstrap...")
    asyncio.run(bootstrap_database())
    print("SUCCESS: SQL migrations and pgqueuer bootstrap applied.")

    # 3. Verify Store logic
    print("Verifying database manager connectivity...")
    store = get_store()
    settings = store.get_settings()
    print(f"Connection OK. Default timezone: {settings.get('timezone', 'Not Set')}")
    
    print("\n--- INITIALIZATION SUCCESSFUL ---")
    print("System is now ready for 'Maximal' operation.")
    print("Start workers using: python star_attendance/worker_pg.py")

if __name__ == "__main__":
    init_supabase()
