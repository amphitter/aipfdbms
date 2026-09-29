"""Small SQL dialect helpers. Domain SQL uses `?` placeholders."""

from __future__ import annotations


def split_sql(sql: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    in_str = False
    i = 0
    while i < len(sql):
        ch = sql[i]
        if ch == "'":
            buf.append(ch)
            if in_str and i + 1 < len(sql) and sql[i + 1] == "'":
                buf.append("'")
                i += 2
                continue
            in_str = not in_str
            i += 1
            continue
        if ch == ";" and not in_str:
            stmt = "".join(buf).strip()
            if stmt and not _comment_only(stmt):
                parts.append(stmt)
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail and not _comment_only(tail):
        parts.append(tail)
    return parts


def _comment_only(stmt: str) -> bool:
    for line in stmt.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("--"):
            return False
    return True


def translate(sql: str, dialect: str) -> str:
    if dialect != "postgres":
        return sql
    sql = sql.replace("BEGIN IMMEDIATE", "BEGIN")
    sql = sql.replace("IFNULL(", "COALESCE(")
    sql = sql.replace("datetime('now')", "CURRENT_TIMESTAMP")
    return _placeholders(sql)


def _placeholders(sql: str) -> str:
    out: list[str] = []
    in_str = False
    i = 0
    while i < len(sql):
        ch = sql[i]
        if ch == "'":
            out.append(ch)
            if in_str and i + 1 < len(sql) and sql[i + 1] == "'":
                out.append("'")
                i += 2
                continue
            in_str = not in_str
            i += 1
            continue
        if not in_str and ch == "?":
            out.append("%s")
        elif not in_str and ch == "%":
            out.append("%%")
        else:
            out.append(ch)
        i += 1
    return "".join(out)
