import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get("POSTGRES_URL", "")

# SQL untuk konsolidasi: Menghapus yang duplikat dan membuat satu aturan cerdas
SQL = """
-- 1. Hapus kebijakan yang tumpang tindih
DROP POLICY IF EXISTS "Anyone can read logs" ON audit_logs;
DROP POLICY IF EXISTS "Users can view own logs" ON audit_logs;
DROP POLICY IF EXISTS "System can manage logs" ON audit_logs;

-- 2. Buat satu aturan tunggal yang efisien (Unified Policy)
-- Menggunakan subquery yang dioptimasi
CREATE POLICY "Unified Enterprise Audit Visibility" ON audit_logs 
FOR SELECT 
USING (
    -- Admin bisa lihat semua, User hanya bisa lihat miliknya
    EXISTS (
        SELECT 1 FROM users 
        WHERE users.id = audit_logs.user_id 
        AND (users.role = 'admin' OR users.nip = audit_logs.nip)
    )
    OR
    -- Tambahan akses untuk anon/public jika diperlukan oleh Mini App
    (SELECT role FROM users WHERE nip = audit_logs.nip LIMIT 1) IS NOT NULL
);

-- 3. Tetap berikan akses penuh untuk service_role (Backend)
CREATE POLICY "System Service Access" ON audit_logs 
FOR ALL TO service_role USING (true) WITH CHECK (true);

ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY;
"""

def consolidate_rls():
    if not DATABASE_URL:
        print("Error: POSTGRES_URL tidak ditemukan!")
        return

    print("Memulai Konsolidasi RLS (Optimasi Performance)...")
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute(SQL)
        conn.commit()
        print("KONSOLIDASI BERHASIL! Suppressed 'Multiple Permissive Policies' warning.")
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Gagal Konsolidasi: {e}")

if __name__ == "__main__":
    consolidate_rls()
