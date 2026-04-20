import asyncio
import argparse
import os
import sys
from datetime import datetime
from playwright.async_api import async_playwright  # type: ignore
from dotenv import load_dotenv

# Add root directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from star_attendance.database_manager import SupabaseManager
    from colorama import init, Fore
except ImportError:
    print("Pastikan Anda menjalankan script ini dari root directory atau sudah menginstal dependensi yang diperlukan.")
    sys.exit(1)

# Initialize colorama
init(autoreset=True)

async def run_manual_login():
    parser = argparse.ArgumentParser(description="Star ASN Manual Login Bridge")
    parser.add_argument("--nip", required=True, help="Target NIP for session capture")
    parser.add_argument("--url", default="https://star-asn.kemenimipas.go.id/authentication/login", help="Login URL")
    parser.add_argument("--timeout", type=int, default=300, help="Wait timeout in seconds (default: 300)")
    
    args = parser.parse_args()
    nip = args.nip
    
    # Load .env for Redis config
    env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '.env'))
    load_dotenv(env_path)
    
    try:
        store = SupabaseManager()
    except Exception as e:
        print(f"{Fore.RED}[ERROR] Gagal terhubung ke Database: {e}")
        return

    print(f"\n{Fore.CYAN}{'='*60}")
    print(f"{Fore.YELLOW}{' '*15}STAR ASN MANUAL LOGIN BRIDGE")
    print(f"{Fore.CYAN}{'='*60}\n")
    
    print(f"{Fore.WHITE}[1] Membuka browser Chromium...")
    
    async with async_playwright() as p:
        # Launch browser - headed is required for manual login
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        print(f"{Fore.WHITE}[2] Navigasi ke {args.url}")
        await page.goto(args.url)

        print(f"\n{Fore.MAGENTA}{'!'*60}")
        print(f"{Fore.MAGENTA} SILAKAN LOGIN SECARA MANUAL PADA JENDELA BROWSER YANG TERBUKA")
        print(f"{Fore.MAGENTA} JGN TUTUP BROWSER SEBELUM DASHBOARD TERMUAT")
        print(f"{Fore.MAGENTA}{'!'*60}\n")
        
        print(f"{Fore.YELLOW}[WAIT] Menunggu deteksi login sukses (Dashboard)...")
        
        success = False
        start_time = datetime.now()
        
        try:
            while (datetime.now() - start_time).seconds < args.timeout:
                current_url = page.url.lower()
                
                # Detection criteria: URL contains dashboard or we see specific dashboard element
                if "/home/dashboard" in current_url or "/attendance/presence" in current_url:
                    print(f"\n{Fore.GREEN}[SUCCESS] Login terdeteksi! Mengambil data sesi...")
                    
                    # Optional: wait for it to stabilize
                    await asyncio.sleep(2)
                    
                    # Extract Data
                    playwright_cookies = await context.cookies()
                    # Convert to simple key-value dict for curl_cffi consumption
                    cookies_dict = {c['name']: c['value'] for c in playwright_cookies}
                    
                    user_agent = await page.evaluate("navigator.userAgent")
                    
                    session_data = {
                        "nip": nip,
                        "cookies": cookies_dict,
                        "user_agent": user_agent,
                        "captured_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
                    
                    store.save_user_session(nip, session_data)
                    
                    print(f"{Fore.GREEN}[FINISH] Sesi disimpan ke Database untuk NIP: {Fore.WHITE}{nip}")
                    print(f"{Fore.WHITE}User-Agent: {user_agent[:50]}...")
                    print(f"{Fore.WHITE}Total Cookies: {len(cookies_dict)}")
                    
                    success = True
                    break
                
                # Check if page is closed
                if page.is_closed():
                    print(f"{Fore.RED}[ERROR] Browser ditutup sebelum login selesai.")
                    break
                    
                await asyncio.sleep(1)
                
            if not success and (datetime.now() - start_time).seconds >= args.timeout:
                print(f"{Fore.RED}[TIMEOUT] Waktu tunggu habis. Silakan coba lagi.")
                
        except Exception as e:
            print(f"{Fore.RED}[ERROR] Terjadi kegagalan flow: {e}")
        finally:
            await browser.close()
            print(f"\n{Fore.CYAN}{'='*60}")

if __name__ == "__main__":
    try:
        asyncio.run(run_manual_login())
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}[CANCEL] Proses dibatalkan oleh pengguna.")
