from __future__ import annotations

import argparse
import importlib
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable

SERVICE_TARGETS: dict[str, str] = {
    "bootstrap": "star_attendance.bootstrap_db:main",
    "api": "api.main:start_api",
    "worker": "star_attendance.worker_pg:run",
    "bot": "star_attendance.telegram_bot:main",
}

REQUIRED_ENV: dict[str, tuple[str, ...]] = {
    "bootstrap": ("POSTGRES_URL", "MASTER_SECURITY_KEY"),
    "api": ("POSTGRES_URL", "MASTER_SECURITY_KEY"),
    "worker": ("POSTGRES_URL", "MASTER_SECURITY_KEY"),
    "bot": ("TELEGRAM_BOT_TOKEN", "POSTGRES_URL", "MASTER_SECURITY_KEY"),
}

EXIT_PRECONDITION_FAILED = 78


class PreflightError(RuntimeError):
    pass


def configure_logging() -> logging.Logger:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    return logging.getLogger("service_runner")


logger = configure_logging()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Unified Star ASN container entrypoint")
    parser.add_argument(
        "command",
        choices=sorted([*SERVICE_TARGETS.keys(), "check-api"]),
        help="Service role or healthcheck command to execute.",
    )
    return parser.parse_args(argv)


def load_callable(import_path: str) -> Callable[[], int | None]:
    module_name, callable_name = import_path.split(":", maxsplit=1)
    module = importlib.import_module(module_name)
    target = getattr(module, callable_name, None)
    if target is None or not callable(target):
        raise PreflightError(f"Entrypoint '{import_path}' is not callable.")
    return target


def require_env(command: str) -> None:
    missing = [name for name in REQUIRED_ENV.get(command, ()) if not os.getenv(name)]
    if missing:
        raise PreflightError(f"Missing required environment variables for '{command}': {', '.join(missing)}")


def resolve_retry_settings() -> tuple[int, float]:
    attempts = max(1, int(os.getenv("STARTUP_MAX_ATTEMPTS", "1")))
    delay_seconds = max(0.0, float(os.getenv("STARTUP_RETRY_DELAY_SECONDS", "5")))
    return attempts, delay_seconds


def run_service(command: str) -> int:
    require_env(command)
    target = load_callable(SERVICE_TARGETS[command])
    result = target()
    return int(result) if isinstance(result, int) else 0


def build_healthcheck_url() -> str:
    base_url = (
        os.getenv("INTERNAL_API_HEALTHCHECK_URL") or os.getenv("INTERNAL_API_URL") or "http://127.0.0.1:11800"
    ).rstrip("/")
    return f"{base_url}/healthz"


def check_api() -> int:
    token = os.getenv("INTERNAL_API_TOKEN") or os.getenv("MASTER_SECURITY_KEY")
    if not token:
        raise PreflightError("Healthcheck requires INTERNAL_API_TOKEN or MASTER_SECURITY_KEY to be set.")

    request = urllib.request.Request(
        build_healthcheck_url(),
        headers={"X-Internal-Token": token},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        response.read()
        if response.status >= 400:
            raise RuntimeError(f"Healthcheck failed with status code {response.status}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "check-api":
        try:
            return check_api()
        except PreflightError as exc:
            logger.error(str(exc))
            return EXIT_PRECONDITION_FAILED
        except urllib.error.URLError as exc:
            logger.error("API healthcheck failed: %s", exc)
            return 1

    attempts, delay_seconds = resolve_retry_settings()
    for attempt in range(1, attempts + 1):
        try:
            logger.info("Starting service '%s' (attempt %s/%s)", args.command, attempt, attempts)
            return run_service(args.command)
        except PreflightError as exc:
            logger.error(str(exc))
            return EXIT_PRECONDITION_FAILED
        except KeyboardInterrupt:
            logger.info("Service '%s' interrupted by operator.", args.command)
            return 130
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
            if code == 0:
                return 0
            logger.error("Service '%s' exited with code %s", args.command, code)
            return code
        except Exception as exc:
            if attempt >= attempts:
                logger.exception(
                    "Service '%s' failed after %s startup attempt(s).",
                    args.command,
                    attempt,
                )
                return 1
            logger.warning(
                "Service '%s' startup attempt %s/%s failed: %s. Retrying in %.1f seconds.",
                args.command,
                attempt,
                attempts,
                exc,
                delay_seconds,
            )
            time.sleep(delay_seconds)
    return 1


if __name__ == "__main__":
    sys.exit(main())
