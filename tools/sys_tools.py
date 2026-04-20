import os
import sys
import json
import csv
import argparse
import requests
from datetime import datetime
from colorama import init, Fore
from dotenv import load_dotenv

# Add root directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Load environment
load_dotenv()

from star_attendance.database_manager import SupabaseManager
from star_attendance.db.manager import db_manager

init(autoreset=True)

def check_health():
    print(f"\n{Fore.CYAN}--- STAR-ASN SYSTEM HEALTH AUDIT ---")
    
    # 1. Database Check (Supabase/Postgres)
    print(f"{Fore.WHITE}Testing Database Connectivity... ", end="")
    try:
        store = SupabaseManager()
        # Test basic query
        with db_manager.get_session() as session:
            session.execute(text("SELECT 1"))
        print(f"{Fore.GREEN}ONLINE (Supabase/Postgres)")
    except Exception as e:
        print(f"{Fore.RED}OFFLINE ({e})")

    # 2. API Check
    print(f"{Fore.WHITE}Testing API Responsiveness... ", end="")
    try:
        api_url = os.getenv("INTERNAL_API_URL", "http://127.0.0.1:8000")
        api_token = os.getenv("INTERNAL_API_TOKEN") or os.getenv("MASTER_SECURITY_KEY", "")
        res = requests.get(
            f"{api_url}/healthz",
            headers={"X-Internal-Token": api_token},
            timeout=3,
        )
        if res.status_code == 200:
            print(f"{Fore.GREEN}READY ({api_url})")
        else:
            print(f"{Fore.YELLOW}STALLING (HTTP {res.status_code})")
    except Exception:
        print(f"{Fore.RED}UNREACHABLE")

    # 3. Environment Check
    print(f"{Fore.WHITE}Checking Environment Config... ", end="")
    if os.path.exists(".env"):
        print(f"{Fore.GREEN}FOUND")
    else:
        print(f"{Fore.RED}MISSING (.env)")

def export_backup():
    print(f"\n{Fore.MAGENTA}--- DATABASE EXPORT (AUDIT LOGS) ---")
    try:
        store = SupabaseManager()
    except Exception as e:
        print(f"{Fore.RED}FAILED to initialize Database Store: {e}")
        return
    
    # Create backups directory
    os.makedirs("backups", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"backups/audit_export_{timestamp}.csv"
    
    print(f"{Fore.WHITE}Fetching audit history from Supabase...")
    
    all_data = []
    try:
        from star_attendance.db.models import AuditLog, User
        with db_manager.get_session() as session:
            logs = session.query(AuditLog).order_by(AuditLog.timestamp.desc()).limit(1000).all()
            for log_entry in logs:
                name = log_entry.user.nama if log_entry.user else "Unknown"
                all_data.append({
                    "nip": log_entry.nip,
                    "nama": name,
                    "timestamp": log_entry.timestamp.isoformat() if log_entry.timestamp else None,
                    "action": log_entry.action,
                    "status": log_entry.status,
                    "message": log_entry.message
                })
    except Exception as e:
        print(f"{Fore.RED}Critical error during database fetch: {e}")

    if not all_data:
        print(f"{Fore.YELLOW}Warning: No audit logs found to export.")
        return

    keys = all_data[0].keys()
    with open(filename, 'w', newline='', encoding='utf-8') as f:
        dict_writer = csv.DictWriter(f, fieldnames=keys)
        dict_writer.writeheader()
        dict_writer.writerows(all_data)

    print(f"{Fore.GREEN}SUCCESS: {len(all_data)} records exported to {filename}")

if __name__ == "__main__":
    from sqlalchemy import text # type: ignore
    parser = argparse.ArgumentParser()
    parser.add_argument("--health", action="store_true")
    parser.add_argument("--backup", action="store_true")
    args = parser.parse_args()

    if args.health:
        check_health()
    elif args.backup:
        export_backup()
    else:
        check_health()
        export_backup()
