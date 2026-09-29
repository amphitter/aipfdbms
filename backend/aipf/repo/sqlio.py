"""The only query executor. Repository modules call this. Domain modules do not."""

from __future__ import annotations

import re

from aipf.db import one as db_one
from aipf.db import rows as db_rows

_NAMED = re.compile(r":([A-Za-z_][A-Za-z0-9_]*)")


def _positional(sql: str, params):
    """Named :fields are a SQLite habit. Both engines receive positional placeholders."""
    if not isinstance(params, dict):
        return sql, params
    names: list[str] = []

    def repl(match):
        names.append(match.group(1))
        return "?"

    sql = _NAMED.sub(repl, sql)
    return sql, tuple(params[name] for name in names)


def one(conn, sql: str, params=()):
    sql, params = _positional(sql, params)
    return db_one(conn, sql, params)


def rows(conn, sql: str, params=()):
    sql, params = _positional(sql, params)
    return db_rows(conn, sql, params)


def execute(conn, sql: str, params=()):
    sql, params = _positional(sql, params)
    return conn.execute(sql, params)


def has_column(conn, table: str, column: str) -> bool:
    if not has_table(conn, table):
        return False
    if getattr(conn, "dialect", "sqlite") == "postgres":
        found = one(conn, "SELECT 1 AS ok FROM information_schema.columns WHERE table_name=? AND column_name=? AND table_schema=current_schema()", (table, column))
    else:
        found = one(conn, f"SELECT 1 AS ok FROM pragma_table_info('{table}') WHERE name=?", (column,))
    return bool(found)


def has_table(conn, name: str) -> bool:
    if getattr(conn, "dialect", "sqlite") == "postgres":
        found = one(conn, "SELECT 1 AS ok FROM information_schema.tables WHERE table_name=? AND table_schema=current_schema()", (name,))
    else:
        found = one(conn, "SELECT 1 AS ok FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return bool(found)


def exec_if(conn, table: str, sql: str, params=()):
    if has_table(conn, table):
        return execute(conn, sql, params)
    return None


def count_where(conn, table: str, column: str, value) -> int:
    if not has_table(conn, table):
        return 0
    row = one(conn, f"SELECT COUNT(*) AS n FROM {table} WHERE {column}=?", (value,))
    return int((row or {}).get("n") or 0)
