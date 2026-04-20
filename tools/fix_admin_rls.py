import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

url: str = os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "")
key: str = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "") # Use Service Role to bypass RLS for setup
supabase: Client = create_client(url, key)

SQL_PATCH = """
-- 1. Ensure anonymous users can select logs (needed for Mini App identification)
DROP POLICY IF EXISTS "Anyone can read logs" ON audit_logs;
CREATE POLICY "Anyone can read logs" ON audit_logs 
FOR SELECT USING (true);

-- 2. Ensure total count is reachable
ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY;
"""

def apply_patch():
    try:
        # Using RPC if available or we just explain the need to run in SQL Editor
        # But commonly we run via a direct SQL execution if we have the permissions.
        # Since I am an agent, I'll recommend the user runs this in SQL Editor for absolute certainty
        print("Menerapkan Patch RLS Audit Logs...")
        res = supabase.rpc('exec_sql', {'sql_query': SQL_PATCH}).execute()
        print("Patch berhasil diterapkan!")
    except Exception as e:
        print(f"Gagal via RPC: {e}")
        print("\nSilakan SALIN & TEMPEL kode SQL berikut ke SQL Editor di Dashboard Supabase Anda:")
        print("-" * 50)
        print(SQL_PATCH)
        print("-" * 50)

if __name__ == "__main__":
    apply_patch()
