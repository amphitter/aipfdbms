"""Database connections. Clients never receive one of these.

Production: AIPF_ENV=production and AIPF_DATABASE_URL=postgresql://...
If PostgreSQL is configured but down, startup fails. It does not open SQLite.
Development SQLite requires an explicit sqlite:/// URL or a path passed to connect().
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from .sqlutil import translate


class Row(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class Cursor:
    def __init__(self, rows: list, rowcount: int = -1):
        self._rows = rows
        self._i = 0
        self.rowcount = rowcount

    def fetchone(self):
        if self._i >= len(self._rows):
            return None
        row = self._rows[self._i]
        self._i += 1
        return row

    def fetchall(self):
        rows = self._rows[self._i :]
        self._i = len(self._rows)
        return rows


class SqliteConn:
    dialect = "sqlite"

    def __init__(self, raw: sqlite3.Connection):
        self.raw = raw

    def execute(self, sql: str, params: tuple | list = ()):
        return self.raw.execute(sql, params)

    def executescript(self, sql: str):
        return self.raw.executescript(sql)

    def close(self) -> None:
        self.raw.close()

    @property
    def in_transaction(self) -> bool:
        return self.raw.in_transaction


class PgConn:
    dialect = "postgres"

    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql: str, params: tuple | list = ()):
        stripped = sql.strip()
        if stripped.upper().startswith("PRAGMA"):
            return Cursor([])
        sql = translate(sql, "postgres")
        if params:
            cur = self.raw.execute(sql, tuple(params))
        else:
            cur = self.raw.execute(sql)
        if cur.description is None:
            return Cursor([], cur.rowcount)
        cols = [d.name for d in cur.description]
        rows = [Row(zip(cols, _adapt(rec))) for rec in cur.fetchall()]
        return Cursor(rows, cur.rowcount)

    def executescript(self, sql: str):
        from .sqlutil import split_sql

        for stmt in split_sql(sql):
            self.execute(stmt)
        return Cursor([])

    def close(self) -> None:
        self.raw.close()

    @property
    def in_transaction(self) -> bool:
        from psycopg.pq import TransactionStatus

        return self.raw.info.transaction_status != TransactionStatus.IDLE


def _adapt(record) -> list:
    out = []
    for value in record:
        if isinstance(value, memoryview):
            value = bytes(value)
        out.append(value)
    return out


def database_url() -> str:
    return os.environ.get("AIPF_DATABASE_URL", "").strip()


def connect_sqlite(path: Path) -> SqliteConn:
    from .db import ensure_dirs

    ensure_dirs()
    raw = sqlite3.connect(str(path), timeout=15, isolation_level=None, check_same_thread=False)
    raw.row_factory = sqlite3.Row
    raw.execute("PRAGMA foreign_keys=ON")
    raw.execute("PRAGMA journal_mode=WAL")
    raw.execute("PRAGMA busy_timeout=8000")
    raw.execute("PRAGMA synchronous=NORMAL")
    return SqliteConn(raw)


def connect_postgres(url: str) -> PgConn:
    if not url.startswith("postgres"):
        raise RuntimeError("AIPF_DATABASE_URL must start with postgresql:// or postgres://")
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("PostgreSQL support requires psycopg. Install backend/requirements.txt.") from exc
    try:
        raw = psycopg.connect(url, autocommit=True)
    except Exception as exc:
        raise RuntimeError(
            f"PostgreSQL is configured but unavailable ({exc}). Startup refused. SQLite was not used."
        ) from exc
    raw.execute("SET TIME ZONE 'UTC'")
    return PgConn(raw)
