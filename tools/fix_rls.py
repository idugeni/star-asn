import os
import psycopg2
from dotenv import load_dotenv

def fix_rls():
    print("[INFO] Memulai perbaikan RLS untuk Mini App...")
    load_dotenv()
    
    db_url = os.getenv("POSTGRES_URL")
    if not db_url:
        print("[ERROR] POSTGRES_URL tidak ditemukan di .env!")
        return

    try:
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        
        print("[INFO] Menambahkan kebijakan SELECT untuk role 'anon'...")
        
        sql = """
        -- 1. Berikan hak akses select ke role anon agar frontend bisa mencari user
        GRANT SELECT ON public.users TO anon;
        GRANT SELECT ON public.upts TO anon;
        
        -- 2. Buat policy agar anon bisa melihat data user (untuk identifikasi Mini App)
        DROP POLICY IF EXISTS "Allow Mini App identification" ON users;
        CREATE POLICY "Allow Mini App identification" ON users 
            FOR SELECT TO anon 
            USING (true);

        -- 3. Pastikan upts juga bisa dibaca oleh anon untuk label lokasi
        DROP POLICY IF EXISTS "Allow Mini App to view UPTs" ON upts;
        CREATE POLICY "Allow Mini App to view UPTs" ON upts 
            FOR SELECT TO anon 
            USING (true);
        """
        
        cur.execute(sql)
        conn.commit()
        
        print("[SUCCESS] Kebijakan RLS telah diperbarui!")
        print("Silakan muat ulang (Reload) Mini App di Telegram Anda.")
        
        cur.close()
        conn.close()
        
    except Exception as e:
        print(f"[ERROR] Gagal memperbarui database: {e}")

if __name__ == "__main__":
    fix_rls()
