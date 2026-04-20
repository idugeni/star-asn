import asyncio
import os
import sys
from telegram import Bot, MenuButtonWebApp, WebAppInfo
from dotenv import load_dotenv

# Ensure we can import from project root
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

async def activate():
    print("[INFO] Memulai aktivasi Telegram Mini App...")
    
    # Load environment variables
    load_dotenv()
    
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    url = os.getenv("MINI_APP_URL")
    
    if not token:
        print("[ERROR] TELEGRAM_BOT_TOKEN tidak ditemukan di .env!")
        return
    
    if not url or "your-mini-app" in url:
        print(f"[ERROR] MINI_APP_URL belum diatur dengan benar: {url}")
        return

    bot = Bot(token=token)
    
    try:
        print(f"[INFO] Menghubungkan tombol 'Buka' ke: {url}")
        
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="Buka",
                web_app=WebAppInfo(url=url)
            )
        )
        
        # Verify
        current_button = await bot.get_chat_menu_button()
        btn_text = current_button.text if current_button else 'None'
        print(f"[SUCCESS] Berhasil! Tombol menu saat ini: {btn_text}")
        print("\nKonfigurasi SELESAI. Silakan buka Bot Telegram Anda.")
        
    except Exception as e:
        print(f"[ERROR] Terjadi kesalahan: {e}")

if __name__ == "__main__":
    asyncio.run(activate())
