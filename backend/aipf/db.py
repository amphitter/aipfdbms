"""Local database access. Clients never connect here — only the application server does."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .util import now_iso

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
DB_PATH = DATA / "hospital.db"
DOCUMENTS = DATA / "documents"
BACKUPS = DATA / "backups"
LOGS = DATA / "logs"
BRANDING = DATA / "branding"
SCHEMA = Path(__file__).with_name("schema.sql")


def ensure_dirs() -> None:
    for path in (DATA, DOCUMENTS, BACKUPS, LOGS, BRANDING):
        path.mkdir(parents=True, exist_ok=True)


def connect(path: Path | None = None):
    """Open the configured database. SQLite is never a silent fallback."""
    import os

    from .engine import connect_postgres, connect_sqlite, database_url

    env = os.environ.get("AIPF_ENV", "development").strip().lower()
    url = database_url()
    if env == "production":
        if path is not None or not url or not url.startswith("postgres"):
            raise RuntimeError(
                "AIPF_ENV=production requires AIPF_DATABASE_URL to be a PostgreSQL URL. "
                "Startup refused. SQLite was not used."
            )
        return connect_postgres(url)
    if path is not None:
        return connect_sqlite(path)
    if not url:
        raise RuntimeError(
            "No database configured. Set AIPF_DATABASE_URL to a PostgreSQL URL, "
            "or an explicit sqlite:/// URL for development. Refusing to guess."
        )
    if url.startswith("postgres"):
        return connect_postgres(url)
    if url.startswith("sqlite:"):
        return connect_sqlite(_sqlite_path(url))
    raise RuntimeError("AIPF_DATABASE_URL must start with postgresql://, postgres://, or sqlite://")


def _sqlite_path(url: str) -> Path:
    raw = url.split("://", 1)[1]
    if not raw:
        raise RuntimeError("sqlite URL is missing a path")
    return Path(raw)


def begin(conn) -> None:
    conn.execute("BEGIN IMMEDIATE" if conn.dialect == "sqlite" else "BEGIN")


def commit(conn) -> None:
    conn.execute("COMMIT")


def rollback(conn) -> None:
    conn.execute("ROLLBACK")


class Tx:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self) -> sqlite3.Connection:
        self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        if exc_type:
            self.conn.execute("ROLLBACK")
            return False
        self.conn.execute("COMMIT")
        return False


def rows(conn, sql: str, params: tuple | list = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def one(conn, sql: str, params: tuple | list = ()) -> dict | None:
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def execute(conn, sql: str, params: tuple | list = ()) -> int:
    cur = conn.execute(sql, params)
    return cur.rowcount


def current_version(conn) -> int:
    from .migrate import current_version as version_of

    return version_of(conn)


def apply_migrations(conn) -> int:
    from .migrate import apply_migrations as run

    return run(conn)


def init_db(path: Path | None = None) -> sqlite3.Connection:
    conn = connect(path)
    apply_migrations(conn)
    from .seed import ensure_default_grants, seed_if_empty
    from .pharmacy import ensure_barcode_types
    ensure_default_grants(conn)
    ensure_barcode_types(conn)
    seed_if_empty(conn)
    return conn


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)
