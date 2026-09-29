"""Copy a SQLite hospital file into an already-migrated empty PostgreSQL database.

Does not delete the SQLite file. Refuses to write into a PostgreSQL database that already has patients.
"""

from __future__ import annotations

from .constraints import COPY_ORDER, FOREIGN_KEYS, IDENTITY_TABLES


def orphan_report(conn) -> list[str]:
    problems = []
    for table, column, ref_table, ref_col in FOREIGN_KEYS:
        if not _has_table(conn, table) or not _has_table(conn, ref_table):
            continue
        rows = conn.execute(
            f"""SELECT {column} AS v FROM {table}
                WHERE {column} IS NOT NULL AND CAST({column} AS TEXT) != ''
                  AND {column} NOT IN (SELECT {ref_col} FROM {ref_table})
                LIMIT 5"""
        ).fetchall()
        if rows:
            sample = ", ".join(str(r["v"]) for r in rows)
            problems.append(f"{table}.{column} -> {ref_table}.{ref_col}: {sample}")
    return problems


def copy_database(source, target) -> dict:
    if target.dialect != "postgres":
        raise RuntimeError("copy_database target must be PostgreSQL")
    if source.dialect != "sqlite":
        raise RuntimeError("copy_database source must be SQLite")
    existing = target.execute("SELECT COUNT(*) AS n FROM patients").fetchone()
    if existing and int(existing["n"]) > 0:
        raise RuntimeError("Target PostgreSQL database already has patients. Refusing to merge or wipe it.")
    problems = orphan_report(source)
    if problems:
        raise RuntimeError("SQLite data violates foreign keys and was not copied:\n" + "\n".join(problems))
    fk_cols = {(table, column) for table, column, _ref_table, _ref_col in FOREIGN_KEYS}
    held_beds = source.execute("SELECT id, current_admission_id FROM beds WHERE current_admission_id IS NOT NULL").fetchall()
    copied = 0
    target.execute("BEGIN")
    try:
        for table in COPY_ORDER:
            if not _has_table(source, table):
                continue
            cols = [r["name"] for r in source.execute(f"PRAGMA table_info({table})").fetchall()]
            if table == "beds":
                cols_write = cols
            else:
                cols_write = cols
            rows = source.execute(f"SELECT {', '.join(cols)} FROM {table}").fetchall()
            if table == "master_items":
                # 0012 seeds rejection reasons on every database. The source copy is authoritative.
                target.execute("DELETE FROM master_items")
            if not rows:
                continue
            placeholders = ", ".join("?" for _ in cols_write)
            sql = f"INSERT INTO {table} ({', '.join(cols_write)}) VALUES ({placeholders})"
            for row in rows:
                values = []
                for name in cols_write:
                    value = row[name]
                    if table == "beds" and name == "current_admission_id":
                        value = None
                    if (table, name) in fk_cols and value == "":
                        value = None
                    values.append(value)
                target.execute(sql, values)
                copied += 1
        for bed in held_beds:
            target.execute(
                "UPDATE beds SET current_admission_id=? WHERE id=?",
                (bed["current_admission_id"], bed["id"]),
            )
        for table in IDENTITY_TABLES:
            target.execute(
                f"""SELECT setval(
                        pg_get_serial_sequence('{table}', 'id'),
                        GREATEST((SELECT COALESCE(MAX(id), 0) FROM {table}), 1),
                        (SELECT COUNT(*) FROM {table}) > 0
                    )"""
            )
        target.execute("COMMIT")
    except Exception:
        try:
            target.execute("ROLLBACK")
        except Exception:
            pass
        raise
    return {"rows": copied, "beds_relinked": len(held_beds)}


def main() -> None:
    import sys
    from pathlib import Path

    from .db import DB_PATH, apply_migrations, connect
    from .engine import database_url

    url = database_url()
    if not url:
        print("Set AIPF_DATABASE_URL to an empty PostgreSQL database first.", file=sys.stderr)
        sys.exit(2)
    source_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DB_PATH
    source = connect(source_path)
    target = connect()
    apply_migrations(target)
    try:
        result = copy_database(source, target)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    print(f"Copied {result['rows']} rows from {source_path}. SQLite file was not deleted.")


def _has_table(conn, table: str) -> bool:
    if conn.dialect == "sqlite":
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        return row is not None
    row = conn.execute(
        "SELECT 1 AS ok FROM information_schema.tables WHERE table_schema='public' AND table_name=?",
        (table,),
    ).fetchone()
    return row is not None


if __name__ == "__main__":
    main()
