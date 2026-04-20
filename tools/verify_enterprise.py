import os
import sys
import asyncio
from dotenv import load_dotenv

load_dotenv()

# Add parent directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from star_attendance.bootstrap_db import bootstrap_database
from star_attendance.db.manager import db_manager
from star_attendance.db.models import User
from star_attendance.runtime import get_store

def verify_enterprise_upgrade():
    print("Starting Enterprise Upgrade Verification...")
    
    # 1. Initialize DB
    asyncio.run(bootstrap_database())
    store = get_store()
    
    # 2. Test Admin Check
    admin_id = os.getenv("TELEGRAM_ADMIN_ID")
    print(f"Checking Admin ID from .env: {admin_id}")
    
    # 3. Simulate User Registration with new fields
    test_user = {
        "nip": "123456789",
        "nama": "Test Enterprise User",
        "password": "testpassword",
        "upt_id": "KANWIL_TEST",
        "telegram_id": 999999999,
        "cron_in": "08:00",
        "cron_out": "16:30"
    }
    
    print(f"Registering test user: {test_user['nip']}")
    if store.add_user(test_user):
        print("OK: User registration successful.")
    else:
        print("FAIL: User registration failed.")
        return

    # 4. Verify Retrieval by Telegram ID
    print(f"Looking up user by Telegram ID: {test_user['telegram_id']}")
    retrieved = store.get_user_by_telegram_id(test_user['telegram_id'])
    if retrieved and retrieved['nip'] == test_user['nip']:
        print(f"OK: Lookup successful: Found {retrieved['nama']}")
    else:
        print("FAIL: Lookup failed.")
        
    # 5. Verify Settings Update
    print("Updating personal schedule...")
    if store.update_user_settings(test_user['nip'], {"cron_in": "07:00"}):
        updated = store.get_user_data(test_user['nip'])
        # We need to check cron_in from raw db since get_user_data is limited
        with db_manager.get_session() as session:
            u = session.query(User).filter(User.nip == test_user['nip']).first()
            if u.cron_in == "07:00":
                print("OK: Setting update successful (IN: 07:00).")
            else:
                print(f"FAIL: Setting update failed: {u.cron_in}")
    
    # 6. Cleanup
    print("Cleaning up test user...")
    store.delete_user(test_user['nip'])
    print("Verification Complete.")

if __name__ == "__main__":
    verify_enterprise_upgrade()
