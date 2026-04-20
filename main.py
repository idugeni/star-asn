import os
import subprocess
import sys

from colorama import Fore, Style, init
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize colorama
init(autoreset=True)

IS_INTERACTIVE = sys.stdin.isatty() and sys.stdout.isatty()


def clear_screen():
    if not IS_INTERACTIVE:
        return
    if os.name != "nt" and not os.getenv("TERM"):
        return
    os.system("cls" if os.name == "nt" else "clear")


def show_banner():
    banner = f"""
{Fore.CYAN}    ███████╗████████╗ █████╗ ██████╗      █████╗ ███████╗███╗   ██╗
{Fore.CYAN}    ██╔════╝╚══██╔══╝██╔══██╗██╔══██╗    ██╔══██╗██╔════╝████╗  ██║
{Fore.WHITE}    ███████╗   ██║   ███████║██████╔╝    ███████║███████╗██╔██╗ ██║
{Fore.WHITE}    ╚════██║   ██║   ██╔══██║██╔══██╗    ██╔══██║╚════██║██║╚██╗██║
{Fore.CYAN}    ███████║   ██║   ██╔══██║██║  ██║    ██╔══██║███████║██║ ╚████║
{Fore.CYAN}    ╚══════╝   ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝    ╚═╝  ╚═╝╚══════╝╚═╝  ╚═══╝
    {Fore.YELLOW}════════════════════ MASTER CONTROL CONSOLE ════════════════════
    """
    print(banner)


def show_menu():
    while True:
        clear_screen()
        show_banner()
        print(f"{Fore.CYAN}    [1] {Fore.GREEN}ABSEN MASUK (Check In)")
        print(f"{Fore.CYAN}    [2] {Fore.RED}ABSEN PULANG (Check Out)")
        print(f"{Fore.CYAN}    [3] {Fore.MAGENTA}TOOLS & UTILITIES")
        print(f"{Fore.CYAN}    [4] {Fore.YELLOW}RESTART SCHEDULER")
        print(f"{Fore.CYAN}    [5] {Fore.WHITE}EXIT SYSTEM")
        print(f"\n    {Fore.CYAN}────────────────────────────────────────────────────────────────")

        choice = input(f"    {Fore.WHITE}Select Action > {Style.RESET_ALL}").strip()

        if choice == "1":
            show_attendance_menu("in")
        elif choice == "2":
            show_attendance_menu("out")
        elif choice == "3":
            show_tools_menu()
        elif choice == "4":
            print(f"    {Fore.YELLOW}Restarting internal scheduler engine...")
            import requests  # type: ignore

            try:
                api_url = os.getenv("INTERNAL_API_URL", "http://127.0.0.1:8000")
                api_token = os.getenv("INTERNAL_API_TOKEN") or os.getenv("MASTER_SECURITY_KEY", "")
                requests.post(
                    f"{api_url}/internal/scheduler/restart",
                    headers={"X-Internal-Token": api_token},
                    timeout=10,
                )
                print(f"    {Fore.GREEN}SUCCESS: Scheduler resynced.")
            except Exception:
                print(f"    {Fore.RED}ERROR: Could not reach API.")
            input("\n    Press Enter to continue...")
        elif choice == "5":
            print(f"    {Fore.YELLOW}Star ASN Console safe shutdown. Goodbye.")
            break


def show_attendance_menu(type="in"):
    title = "CHECK-IN OPERATIONS" if type == "in" else "CHECK-OUT OPERATIONS"
    script = "star_attendance/core_worker.py"
    color = Fore.GREEN if type == "in" else Fore.RED

    while True:
        clear_screen()
        show_banner()
        print(f"    {color}--- {title} ---")
        print(f"    {Fore.CYAN}[1] {Fore.WHITE}Single User (Auto Password)")
        print(f"    {Fore.CYAN}[2] {Fore.WHITE}Single User (Manual Credentials)")
        print(f"    {Fore.CYAN}[3] {Fore.WHITE}Mass Attendance (Batch Process)")
        print(f"    {Fore.CYAN}[4] {Fore.YELLOW}Back to Master Control")
        print(f"\n    {Fore.CYAN}────────────────────────────────────────────────────────────────")

        choice = input(f"    {Fore.WHITE}Action > {Style.RESET_ALL}").strip()

        if choice == "1":
            nip = input(f"    {Fore.WHITE}Enter NIP: {Style.RESET_ALL}").strip()
            if nip:
                subprocess.run([sys.executable, script, "--action", type, "--nip", nip])
                input("\n    Press Enter to continue...")
        elif choice == "2":
            nip = input(f"    {Fore.WHITE}Enter NIP: {Style.RESET_ALL}").strip()
            password = input(f"    {Fore.WHITE}Enter Password: {Style.RESET_ALL}").strip()
            if nip and password:
                subprocess.run([sys.executable, script, "--action", type, "--nip", nip, "--password", password])
                input("\n    Press Enter to continue...")
        elif choice == "3":
            confirm = input(f"    {Fore.YELLOW}Launch mass attendance cluster? (y/n): {Style.RESET_ALL}").lower()
            if confirm == "y":
                subprocess.run([sys.executable, script, "--action", type, "--mass"])
                input("\n    Press Enter to continue...")
        elif choice == "4":
            return
        else:
            print(f"    {Fore.RED}Invalid choice.")


def show_tools_menu():
    while True:
        clear_screen()
        show_banner()
        print(f"    {Fore.MAGENTA}--- UTILITY & MAINTENANCE ---")
        print(f"    {Fore.CYAN}[1] {Fore.WHITE}System Health Check (Ping Status)")
        print(f"    {Fore.CYAN}[2] {Fore.WHITE}Database Export (Backup to CSV)")
        print(f"    {Fore.CYAN}[3] {Fore.WHITE}Sync Database (Scrape Personnel)")
        print(f"    {Fore.CYAN}[4] {Fore.YELLOW}Return")
        print(f"\n    {Fore.CYAN}────────────────────────────────────────────────────────────────")

        choice = input(f"    {Fore.WHITE}Tool > {Style.RESET_ALL}").strip()

        if choice == "1":
            subprocess.run([sys.executable, "tools/sys_tools.py", "--health"])
            input("\n    Press Enter to continue...")
        elif choice == "2":
            subprocess.run([sys.executable, "tools/sys_tools.py", "--backup"])
            input("\n    Press Enter to continue...")
        elif choice == "3":
            subprocess.run([sys.executable, "tools/sync_db.py"])
            input("\n    Press Enter to continue...")
        elif choice == "4":
            break


if __name__ == "__main__":
    try:
        if not IS_INTERACTIVE:
            print(
                "Star ASN console requires an interactive terminal. "
                "For Docker production, run the API service instead: "
                "`uvicorn api.main:app --host 0.0.0.0 --port 8000`."
            )
            sys.exit(1)
        show_menu()
    except KeyboardInterrupt:
        print(f"\n    {Fore.YELLOW}Console process killed.")
        sys.exit(0)
    except EOFError:
        print(f"\n    {Fore.YELLOW}Console closed because no interactive input is available.")
        sys.exit(1)
