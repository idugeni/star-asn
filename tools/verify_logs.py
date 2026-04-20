import os
import sys
from dotenv import load_dotenv

load_dotenv()

# Add parent directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from star_attendance.database_manager import SupabaseManager

def verify_log_forwarding():
    print("Testing Log Forwarding to Group...")
    store = SupabaseManager()
    
    # Trigger a manual audit log entry
    # This should internally call the notifier
    print("Sending test audit log...")
    store.add_audit_log(
        nip="TEST_LOGGER",
        action="sys_test",
        status="ok",
        message="Verification of centralized log group forwarding.",
        response_time=0.42
    )
    print("Check your Telegram Log Group (-1003829211138) for 'STAR-ASN TELEMETRY ALERT'.")

if __name__ == "__main__":
    verify_log_forwarding()
