"""Versioned migrations discovered from files on disk.

Startup hashes every applied file. A stored checksum that does not match the
file refuses to start. The stored checksum is not rewritten, and the migration
is not run again. A migration that fails is rolled back and not marked applied.
A missing checksum on a legacy row is left untouched.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from .sqlutil import split_sql
from .util import now_iso

MIGRATIONS = Path(__file__).with_name("migrations")


def apply_migrations(conn) -> int:
    _ensure_migration_table(conn)
    files = files_for(conn.dialect)
    applied = _applied(conn)
    _refuse_missing_files(applied, files)
    _refuse_checksum_mismatch(applied, files)
    for path in files:
        version = _version(path)
        if version in applied:
            continue
        _apply_file(conn, path)
    return current_version(conn)


def current_version(conn) -> int:
    row = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
    if not row or row["v"] is None:
        return 0
    return int(row["v"])


def files_for(dialect: str) -> list[Path]:
    if not MIGRATIONS.is_dir():
        raise RuntimeError(f"Migration directory is missing: {MIGRATIONS}")
    chosen: dict[int, Path] = {}
    for path in sorted(MIGRATIONS.glob("*.sql")):
        version = _version(path)
        specific = f".{dialect}.sql"
        if path.name.endswith(specific):
            chosen[version] = path
        elif ".sqlite." not in path.name and ".postgres." not in path.name:
            chosen.setdefault(version, path)
    if not chosen:
        raise RuntimeError(f"No migration files for {dialect} in {MIGRATIONS}")
    return [chosen[version] for version in sorted(chosen)]


def file_checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def apply_statements(conn, version: int, name: str, statements: tuple[str, ...], checksum: str) -> None:
    """Transactional apply used by the file runner. Failure leaves no version row."""
    _apply_in_transaction(conn, version, name, statements, checksum)


def _version(path: Path) -> int:
    head = path.name.split("_", 1)[0]
    if not head.isdigit():
        raise RuntimeError(f"Migration file name must start with a version: {path.name}")
    return int(head)


def _applied(conn) -> dict[int, dict]:
    found = {}
    for row in conn.execute("SELECT version, name, checksum, applied_at FROM schema_migrations").fetchall():
        found[int(row["version"])] = dict(row)
    return found


def _refuse_missing_files(applied: dict[int, dict], files: list[Path]) -> None:
    present = {_version(path) for path in files}
    missing = sorted(set(applied) - present)
    if missing:
        raise RuntimeError(
            f"Applied migration versions {missing} have no file on disk. Startup refused."
        )


def _refuse_checksum_mismatch(applied: dict[int, dict], files: list[Path]) -> None:
    by_version = {_version(path): path for path in files}
    for version, row in applied.items():
        stored = row.get("checksum")
        if not stored:
            continue
        digest = file_checksum(by_version[version])
        if stored != digest:
            raise RuntimeError(
                f"Migration version {version} checksum mismatch "
                f"(stored {stored}, file {digest}). "
                "Startup refused. The stored checksum was not changed and the migration was not re-run."
            )


def _apply_file(conn, path: Path) -> None:
    statements = tuple(split_sql(path.read_text(encoding="utf-8")))
    if not statements:
        raise RuntimeError(f"Migration {path.name} has no statements")
    _apply_in_transaction(conn, _version(path), path.stem, statements, file_checksum(path))


def _apply_in_transaction(conn, version: int, name: str, statements: tuple[str, ...], checksum: str) -> None:
    begin = "BEGIN IMMEDIATE" if conn.dialect == "sqlite" else "BEGIN"
    try:
        conn.execute(begin)
        for stmt in statements:
            conn.execute(stmt)
        conn.execute(
            "INSERT INTO schema_migrations(version, name, checksum, applied_at) VALUES (?,?,?,?)",
            (version, name, checksum, now_iso()),
        )
        conn.execute("COMMIT")
    except Exception as exc:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise RuntimeError(f"Migration {name} version {version} failed and was not recorded: {exc}") from exc


def _ensure_migration_table(conn) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )"""
    )
    if conn.dialect == "sqlite":
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(schema_migrations)").fetchall()}
        if "checksum" not in cols:
            conn.execute("ALTER TABLE schema_migrations ADD COLUMN checksum TEXT")
    else:
        conn.execute("ALTER TABLE schema_migrations ADD COLUMN IF NOT EXISTS checksum TEXT")
