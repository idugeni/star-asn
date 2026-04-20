import os
import requests
from dotenv import load_dotenv

load_dotenv()

URL = os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "")
KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

SQL = """
-- Membuka akses baca untuk Admin agar tab Log tampil
DROP POLICY IF EXISTS "Anyone can read logs" ON audit_logs;
CREATE POLICY "Anyone can read logs" ON audit_logs 
FOR SELECT USING (true);

ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY;
"""

def direct_migration():
    if not URL or not KEY:
        print("Error: Kredensial Supabase tidak ditemukan!")
        return

    # Mencoba menjalankan via RPC exec_sql (Jika fungsi ini dibuat sebelumnya)
    headers = {
        "apikey": KEY,
        "Authorization": f"Bearer {KEY}",
        "Content-Type": "application/json"
    }
    
    rpc_url = f"{URL}/rest/v1/rpc/exec_sql"
    
    print(f"Mencoba migrasi langsung ke: {URL}")
    
    try:
        response = requests.post(rpc_url, headers=headers, json={"query": SQL})
        if response.status_code == 200 or response.status_code == 204:
            print("MIGRASI BERHASIL! RLS Audit Logs telah diperbarui.")
        else:
            print(f"Gagal via REST: {response.status_code}")
            print(response.text)
            print("\nDatabase Anda belum memiliki fungsi RPC 'exec_sql'.")
            print("Misi dialihkan: Silakan tempel SQL secara manual di dashboard Supabase.")
    except Exception as e:
        print(f"Error Koneksi: {e}")

if __name__ == "__main__":
    direct_migration()
