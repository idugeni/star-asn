import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get("POSTGRES_URL", "")

SQL = """
-- Membuka akses baca untuk Admin agar tab Log tampil
DROP POLICY IF EXISTS "Anyone can read logs" ON audit_logs;
CREATE POLICY "Anyone can read logs" ON audit_logs 
FOR SELECT USING (true);

ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY;
"""

def direct_pg_migration():
    if not DATABASE_URL:
        print("Error: POSTGRES_URL tidak ditemukan di .env!")
        return

    print("Menghubungkan ke PostgreSQL Cluster...")
    try:
        # Connect to your postgres DB
        conn = psycopg2.connect(DATABASE_URL)
        # Open a cursor to perform database operations
        cur = conn.cursor()
        
        print("Mengeksekusi Patch Keamanan (RLS Audit Logs)...")
        cur.execute(SQL)
        
        # Commit the changes
        conn.commit()
        
        print("MIGRASI BERHASIL! RLS Audit Logs telah diperbarui.")
        
        # Close communication with the database
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Gagal Migrasi PostgreSQL: {e}")

if __name__ == "__main__":
    direct_pg_migration()
