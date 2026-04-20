from __future__ import annotations

import hashlib
from collections.abc import Iterable
from pathlib import Path

from sqlalchemy import text

from star_attendance.db.manager import db_manager

REQUIRED_TABLES = (
    "users",
    "upts",
    "user_sessions",
    "audit_logs",
    "settings",
    "attendance_job_locks",
    "attendance_dead_letters",
    "pgqueuer",
)


def migrations_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "supabase" / "migrations"


def discover_migration_files() -> list[Path]:
    return sorted(migrations_dir().glob("*.sql"))


def checksum_for_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ensure_schema_migrations_table() -> None:
    with db_manager.engine.begin() as conn:
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS public.schema_migrations (
                filename TEXT PRIMARY KEY,
                checksum TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
            )
            """
        )


def applied_migrations() -> dict[str, str]:
    ensure_schema_migrations_table()
    with db_manager.engine.begin() as conn:
        rows = conn.execute(text("SELECT filename, checksum FROM public.schema_migrations")).fetchall()
    return {str(row.filename): str(row.checksum) for row in rows}


def _execute_sql_script(script: str) -> None:
    raw_connection = db_manager.engine.raw_connection()
    try:
        cursor = raw_connection.cursor()
        cursor.execute(script)
        raw_connection.commit()
    except Exception:
        raw_connection.rollback()
        raise
    finally:
        raw_connection.close()


def apply_pending_migrations(files: Iterable[Path] | None = None) -> list[str]:
    files = list(files or discover_migration_files())
    applied = applied_migrations()
    executed: list[str] = []

    for path in files:
        filename = path.name
        checksum = checksum_for_file(path)
        existing_checksum = applied.get(filename)
        if existing_checksum:
            if existing_checksum != checksum:
                print(f"Migration checksum mismatch for {filename}. Updating checksum to match current file.")
                with db_manager.engine.begin() as conn:
                    conn.execute(
                        text(
                            """
                            UPDATE public.schema_migrations 
                            SET checksum = :checksum, applied_at = now()
                            WHERE filename = :filename
                            """
                        ),
                        {"filename": filename, "checksum": checksum},
                    )
            continue

        _execute_sql_script(path.read_text(encoding="utf-8"))
        with db_manager.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO public.schema_migrations (filename, checksum)
                    VALUES (:filename, :checksum)
                    """
                ),
                {"filename": filename, "checksum": checksum},
            )
        executed.append(filename)

    return executed


def verify_runtime_schema(require_pgqueuer: bool = True) -> None:
    missing: list[str] = []
    required = REQUIRED_TABLES if require_pgqueuer else tuple(t for t in REQUIRED_TABLES if t != "pgqueuer")

    with db_manager.engine.begin() as conn:
        for table_name in required:
            present = conn.execute(
                text("SELECT to_regclass(:table_name) IS NOT NULL"),
                {"table_name": f"public.{table_name}"},
            ).scalar_one()
            if not present:
                missing.append(table_name)

        telegram_type = conn.execute(
            text(
                """
                SELECT data_type
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'users'
                  AND column_name = 'telegram_id'
                """
            )
        ).scalar_one_or_none()

    if missing:
        raise RuntimeError(f"Database schema is not ready. Missing tables: {', '.join(missing)}")
    if telegram_type != "bigint":
        raise RuntimeError("Database schema is not ready. users.telegram_id must be BIGINT.")
