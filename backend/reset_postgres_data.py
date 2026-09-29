"""Irreversibly remove all AIPF data from PostgreSQL while preserving the schema.

Run from backend with an explicit confirmation:

    python reset_postgres_data.py --confirm-reset DELETE-ALL-DATA

The database URL is read from AIPF_DATABASE_URL unless --database-url is supplied.
This script refuses SQLite, requires an explicit confirmation token, and refuses a
production environment unless --allow-production is supplied.
"""

from __future__ import annotations

import argparse
import os
import sys
from urllib.parse import parse_qs, urlparse


CONFIRMATION = "DELETE-ALL-DATA"
PRESERVED_TABLES = {"schema_migrations"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Delete all rows from every public PostgreSQL table except schema_migrations."
    )
    parser.add_argument(
        "--confirm-reset",
        required=True,
        help=f"Required exact confirmation token: {CONFIRMATION}",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("AIPF_DATABASE_URL", "").strip(),
        help="PostgreSQL URL. Defaults to AIPF_DATABASE_URL.",
    )
    parser.add_argument(
        "--allow-production",
        action="store_true",
        help="Allow the reset when AIPF_ENV=production. Without this flag it is refused.",
    )
    return parser.parse_args()


def connection_details(url: str) -> tuple[str, str, str]:
    parsed = urlparse(url)
    database = parsed.path.lstrip("/") or "unknown"
    host = parsed.hostname or "unknown"
    user = parsed.username or "unknown"
    return host, database, user


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def main() -> int:
    args = parse_args()
    if args.confirm_reset != CONFIRMATION:
        print(f"Refusing reset: --confirm-reset must be exactly {CONFIRMATION}", file=sys.stderr)
        return 2

    url = args.database_url
    if not url.startswith(("postgresql://", "postgres://")):
        print("Refusing reset: --database-url/AIPF_DATABASE_URL must be a PostgreSQL URL.", file=sys.stderr)
        print("SQLite is never reset by this script.", file=sys.stderr)
        return 2

    environment = os.environ.get("AIPF_ENV", "development").strip().lower()
    if environment == "production" and not args.allow_production:
        print("Refusing reset: AIPF_ENV=production. Add --allow-production only after verifying the target.", file=sys.stderr)
        return 2

    host, database, user = connection_details(url)
    if database in {"postgres", "template0", "template1"}:
        print(f"Refusing reset: database name {database!r} is a PostgreSQL system database.", file=sys.stderr)
        return 2

    print("DESTRUCTIVE PostgreSQL DATA RESET")
    print(f"Host:     {host}")
    print(f"Database: {database}")
    print(f"User:     {user}")
    print("Scope:    every public table except schema_migrations")
    print("Keeps:    tables, constraints, indexes, migrations, and schema")
    print("Removes:  patients, users, roles, visits, bills, inventory, lab data, documents metadata, audit data, and all other rows")
    print("Does not remove files from the separate data/documents storage directory.")

    try:
        answer = input(f"Type {CONFIRMATION} again to continue: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nReset cancelled.")
        return 130
    if answer != CONFIRMATION:
        print("Reset cancelled: confirmation did not match.")
        return 1

    try:
        import psycopg
    except ImportError:
        print("PostgreSQL driver missing. Run: python -m pip install -r requirements.txt", file=sys.stderr)
        return 1

    try:
        with psycopg.connect(url, autocommit=False) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT tablename
                    FROM pg_catalog.pg_tables
                    WHERE schemaname = 'public'
                    ORDER BY tablename
                    """
                )
                tables = [row[0] for row in cur.fetchall() if row[0] not in PRESERVED_TABLES]
                if not tables:
                    print("No application tables found. Nothing was changed.")
                    return 0

                joined = ", ".join(quote_identifier(table) for table in tables)
                cur.execute(f"TRUNCATE TABLE {joined} RESTART IDENTITY CASCADE")

                cur.execute(
                    """
                    SELECT tablename
                    FROM pg_catalog.pg_tables
                    WHERE schemaname = 'public'
                    ORDER BY tablename
                    """
                )
                verify_tables = [row[0] for row in cur.fetchall() if row[0] not in PRESERVED_TABLES]
                remaining: list[tuple[str, int]] = []
                for table in verify_tables:
                    cur.execute(f"SELECT COUNT(*) FROM public.{quote_identifier(table)}")
                    count = int(cur.fetchone()[0])
                    if count:
                        remaining.append((table, count))
                if remaining:
                    conn.rollback()
                    print(f"Reset rolled back: rows remain in {remaining}", file=sys.stderr)
                    return 1
            conn.commit()
    except Exception as exc:
        print(f"Reset failed and was rolled back where possible: {exc}", file=sys.stderr)
        return 1

    print(f"Reset complete. Cleared {len(tables)} public tables; schema_migrations was preserved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
