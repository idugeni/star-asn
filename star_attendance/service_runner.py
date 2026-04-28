from __future__ import annotations

import argparse
import importlib
import logging
import os
import sys
import time
import asyncio
import httpx
from collections.abc import Callable
from typing import TypeVar

from star_attendance.core.exceptions import ConfigurationError, MissingEnvironmentVariableError
from star_attendance.core.logging_config import configure_structlog, get_logger

T = TypeVar("T")

SERVICE_TARGETS: dict[str, str] = {
    "bootstrap": "star_attendance.bootstrap_db:main",
    "api": "api.main:start_api",
    "api-full": "api.main:start_api", # Special handling in run_service
    "worker": "star_attendance.worker_pg:run",
    "bot": "star_attendance.telegram_bot:main",
}

REQUIRED_ENV: dict[str, tuple[str, ...]] = {
    "bootstrap": ("POSTGRES_URL", "MASTER_SECURITY_KEY"),
    "api": ("POSTGRES_URL", "MASTER_SECURITY_KEY"),
    "api-full": ("POSTGRES_URL", "MASTER_SECURITY_KEY"),
    "worker": ("POSTGRES_URL", "MASTER_SECURITY_KEY"),
    "bot": ("TELEGRAM_BOT_TOKEN", "POSTGRES_URL", "MASTER_SECURITY_KEY"),
}

EXIT_PRECONDITION_FAILED = 78


class PreflightError(ConfigurationError):
    """Legacy compatibility - maps to ConfigurationError."""

    pass


def configure_logging() -> logging.Logger:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    configure_structlog(level_name)
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
    """Load a callable from a module path string.

    Args:
        import_path: String in format 'module.submodule:function_name'

    Returns:
        Callable that returns int or None

    Raises:
        PreflightError: If the import fails or target is not callable
    """
    try:
        module_name, callable_name = import_path.split(":", maxsplit=1)
        module = importlib.import_module(module_name)
        target = getattr(module, callable_name, None)
        if target is None:
            raise PreflightError(f"Entrypoint '{import_path}' not found in module.")
        if not callable(target):
            raise PreflightError(f"Entrypoint '{import_path}' is not callable (type: {type(target).__name__}).")
        return target  # type: ignore[return-value]
    except ImportError as exc:
        raise PreflightError(f"Failed to import module for '{import_path}': {exc}") from exc
    except ValueError as exc:
        raise PreflightError(f"Invalid import path format '{import_path}'. Expected 'module:function'.") from exc


def require_env(command: str) -> None:
    """Verify required environment variables are set for a command.

    Raises:
        MissingEnvironmentVariableError: If any required variable is missing
    """
    required = REQUIRED_ENV.get(command, ())
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        for var_name in missing:
            raise MissingEnvironmentVariableError(
                var_name,
                details={"command": command, "all_missing": missing}
            )


def resolve_retry_settings() -> tuple[int, float]:
    attempts = max(1, int(os.getenv("STARTUP_MAX_ATTEMPTS", "1")))
    delay_seconds = max(0.0, float(os.getenv("STARTUP_RETRY_DELAY_SECONDS", "5")))
    return attempts, delay_seconds


def run_service(command: str) -> int:
    require_env(command)

    if command == "api-full":
        logger.info("Service 'api-full' detected. Running database bootstrap first...")
        bootstrap_target = load_callable(SERVICE_TARGETS["bootstrap"])
        bootstrap_result = bootstrap_target()
        if isinstance(bootstrap_result, int) and bootstrap_result != 0:
            logger.error("Bootstrap failed with code %s. Aborting API startup.", bootstrap_result)
            return bootstrap_result
        logger.info("Bootstrap successful. Starting API...")

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

    with httpx.Client(timeout=5.0) as client:
        response = client.get(
            build_healthcheck_url(),
            headers={"X-Internal-Token": token},
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Healthcheck failed with status code {response.status_code}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "check-api":
        try:
            return check_api()
        except MissingEnvironmentVariableError as exc:
            logger.error("Missing environment variable '%s' for healthcheck: %s", exc.var_name, exc)
            return EXIT_PRECONDITION_FAILED
        except PreflightError as exc:
            logger.error("Preflight check failed for healthcheck: %s", exc)
            return EXIT_PRECONDITION_FAILED
        except httpx.ConnectError as exc:
            logger.error("API healthcheck failed (connection): %s", exc)
            return 1
        except httpx.TimeoutException as exc:
            logger.error("API healthcheck failed (timeout): %s", exc)
            return 1

    attempts, delay_seconds = resolve_retry_settings()
    for attempt in range(1, attempts + 1):
        try:
            logger.info("Starting service '%s' (attempt %s/%s)", args.command, attempt, attempts)
            return run_service(args.command)
        except MissingEnvironmentVariableError as exc:
            logger.error("Missing environment variable '%s' for command '%s': %s", exc.var_name, args.command, exc)
            return EXIT_PRECONDITION_FAILED
        except PreflightError as exc:
            logger.error("Preflight check failed for command '%s': %s", args.command, exc)
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
