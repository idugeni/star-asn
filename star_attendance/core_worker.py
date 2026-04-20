import argparse
import asyncio
import os
import sys

from colorama import Fore, Style, init
from dotenv import load_dotenv

# Add root directory to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Load environment as early as possible
env_path = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))
load_dotenv(env_path)

from star_attendance.core.processor import mass_attendance, process_single_user
from star_attendance.core.utils import print_sync
from star_attendance.runtime import get_store

# Setup
init(autoreset=True)


async def main():
    parser = argparse.ArgumentParser(description="Star ASN Attendance Worker")
    parser.add_argument("--action", choices=["in", "out"], required=True, help="Action type: in or out")
    parser.add_argument("--mass", "-m", action="store_true", help="Run in mass mode")
    parser.add_argument("--limit", type=int, help="Limit number of users for mass mode")
    parser.add_argument("--nip", help="Target NIP (single mode)")
    parser.add_argument("--password", help="Target Password (single mode)")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without executing")
    parser.add_argument("--explain", action="store_true", help="Explain rule decisions")

    # Rules options
    parser.add_argument("--rule-in-before", default="07:30", help="Time cutoff for Check In (default: 07:30)")
    parser.add_argument("--rule-out-after", default="17:00", help="Time cutoff for Check Out (default: 17:00)")
    parser.add_argument(
        "--rule-mode",
        default="smart",
        choices=["smart", "time", "work", "combined", "none"],
        help="Rule mode for Check Out",
    )
    parser.add_argument("--rule-work-hours", type=float, default=8.0, help="Work hours duration for Check Out rules")

    # Positional args (legacy support)
    parser.add_argument("pos_nip", nargs="?", help="Legacy positional NIP")
    parser.add_argument("pos_password", nargs="?", help="Legacy positional Password")

    args = parser.parse_args()

    # Resolve legacy positional args if --nip/--password not set
    if not args.nip and args.pos_nip:
        args.nip = args.pos_nip
    if not args.password and args.pos_password:
        args.password = args.pos_password

    if args.mass:
        await mass_attendance(limit=args.limit, options=args)
    else:
        # Single User Mode
        target_nip = args.nip
        if not target_nip:
            print_sync(f"{Fore.RED}Error: NIP is required for single mode.{Style.RESET_ALL}")
            sys.exit(1)

        store = get_store()
        args.store = store
        user = {"nip": target_nip, "password": args.password}
        await process_single_user(user, args, 1, 1, is_mass=False)


if __name__ == "__main__":
    asyncio.run(main())
