"""Phase 0: migrations, atomic stock, and PostgreSQL constraints."""

import os
import secrets
import shutil
import sys
import tempfile
import threading
from pathlib import Path

os.environ.setdefault("AIPF_SEED_PASSWORD", secrets.token_urlsafe(18))

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aipf.db import apply_migrations, connect
from aipf.migrate import current_version
from aipf.pgcopy import copy_database, orphan_report
from aipf.seed import seed
from aipf import pharmacy
from aipf.util import ApiError


def test_sqlite_migration_is_repeatable():
    folder = Path(tempfile.mkdtemp(prefix="aipf-mig-"))
    conn = connect(folder / "hospital.db")
    assert apply_migrations(conn) == 17
    assert apply_migrations(conn) == 17
    assert current_version(conn) == 17
    row = conn.execute(
        "SELECT checksum FROM schema_migrations WHERE version=2"
    ).fetchone()
    assert row["checksum"]
    index = conn.execute(
        "SELECT name FROM sqlite_master WHERE name='uq_admission_one_open'"
    ).fetchone()
    assert index
    conn.close()
    shutil.rmtree(folder)


def test_atomic_stock_does_not_write_a_failed_movement():
    folder = Path(tempfile.mkdtemp(prefix="aipf-stock-"))
    conn = connect(folder / "hospital.db")
    apply_migrations(conn)
    seed(conn)
    from aipf import core

    actor = core.load_user(conn, core.user_by_username(conn, "director")["id"])
    conn.execute("UPDATE batches SET qty_on_hand=1 WHERE id='BAT-PR-ORS'")
    conn.execute("DELETE FROM stock_movements WHERE batch_id='BAT-PR-ORS'")
    errors = []

    def worker():
        local = connect(folder / "hospital.db")
        try:
            pharmacy.move(local, actor, "BAT-PR-ORS", 1, "DISPENSED", "test", "x", "race")
        except ApiError as exc:
            errors.append(exc.message)
        finally:
            local.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    left = connect(folder / "hospital.db")
    qty = left.execute("SELECT qty_on_hand FROM batches WHERE id='BAT-PR-ORS'").fetchone()["qty_on_hand"]
    moves = left.execute("SELECT COUNT(*) AS n FROM stock_movements WHERE batch_id='BAT-PR-ORS'").fetchone()["n"]
    left.close()
    assert qty == 0
    assert moves == 1
    assert len(errors) == 1
    shutil.rmtree(folder)


def test_postgres_constraints_and_copy():
    url = os.environ.get("AIPF_TEST_POSTGRES", "").strip()
    if not url:
        print("skip postgres: AIPF_TEST_POSTGRES is not set")
        return
    try:
        import psycopg
    except ImportError:
        print("skip postgres: psycopg missing")
        return
    admin = psycopg.connect(url, autocommit=True)
    admin.execute("DROP DATABASE IF EXISTS aipf_phase0")
    admin.execute("CREATE DATABASE aipf_phase0")
    admin.close()
    target_url = url.rsplit("/", 1)[0] + "/aipf_phase0"
    os.environ["AIPF_DATABASE_URL"] = target_url
    folder = Path(tempfile.mkdtemp(prefix="aipf-pg-"))
    pg = None
    empty = None
    src = None
    try:
        pg = connect()
        assert pg.dialect == "postgres"
        assert apply_migrations(pg) >= 3
        assert apply_migrations(pg) >= 3
        seed(pg)
        orphans = orphan_report(pg)
        assert orphans == [], orphans
        try:
            pg.execute("INSERT INTO encounters(id, patient_id, arrived_at, created_at) VALUES ('E-BAD', 'NO-SUCH', '2026-01-01', '2026-01-01')")
            raise AssertionError("foreign key did not reject a missing patient")
        except AssertionError:
            raise
        except Exception as exc:
            assert "foreign key" in str(exc).lower() or "violates" in str(exc).lower()
        src = connect(folder / "hospital.db")
        apply_migrations(src)
        seed(src)
        assert orphan_report(src) == []
        pg.execute("DELETE FROM audit_logs")
        pg.execute("DELETE FROM app_logs")
        pg.execute("DELETE FROM health_snapshots")
        # Seeded target already has patients, so copy must refuse rather than merge.
        try:
            copy_database(src, pg)
            raise AssertionError("copy should refuse a non-empty target")
        except RuntimeError as exc:
            assert "already has patients" in str(exc)
        src.close()
        pg.close()

        admin = psycopg.connect(url, autocommit=True)
        admin.execute("DROP DATABASE IF EXISTS aipf_phase0")
        admin.execute("CREATE DATABASE aipf_phase0")
        admin.close()
        empty = connect()
        apply_migrations(empty)
        src = connect(folder / "hospital.db")
        result = copy_database(src, empty)
        assert result["rows"] > 0
        n = empty.execute("SELECT COUNT(*) AS n FROM patients").fetchone()["n"]
        assert n == src.execute("SELECT COUNT(*) AS n FROM patients").fetchone()["n"]
        src.close()
        empty.close()
        src = None
        empty = None
    finally:
        os.environ.pop("AIPF_DATABASE_URL", None)
        for conn in (pg, empty, src):
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
        shutil.rmtree(folder, ignore_errors=True)
        admin = psycopg.connect(url, autocommit=True)
        admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='aipf_phase0' AND pid <> pg_backend_pid()"
        )
        admin.execute("DROP DATABASE IF EXISTS aipf_phase0")
        admin.close()


def test_postgres_stock_race():
    url = os.environ.get("AIPF_TEST_POSTGRES", "").strip()
    if not url:
        print("skip postgres stock: AIPF_TEST_POSTGRES is not set")
        return
    import psycopg
    from aipf import core

    admin = psycopg.connect(url, autocommit=True)
    admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='aipf_stock' AND pid <> pg_backend_pid()")
    admin.execute("DROP DATABASE IF EXISTS aipf_stock")
    admin.execute("CREATE DATABASE aipf_stock")
    admin.close()
    os.environ["AIPF_DATABASE_URL"] = url.rsplit("/", 1)[0] + "/aipf_stock"
    try:
        conn = connect()
        apply_migrations(conn)
        seed(conn)
        actor = core.load_user(conn, core.user_by_username(conn, "director")["id"])
        conn.execute("UPDATE batches SET qty_on_hand=1 WHERE id='BAT-PR-ORS'")
        conn.execute("DELETE FROM stock_movements WHERE batch_id='BAT-PR-ORS'")
        conn.close()
        errors = []

        def worker():
            local = connect()
            try:
                pharmacy.move(local, actor, "BAT-PR-ORS", 1, "DISPENSED", "test", "x", "race")
            except ApiError:
                errors.append("short")
            finally:
                local.close()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        left = connect()
        qty = left.execute("SELECT qty_on_hand FROM batches WHERE id='BAT-PR-ORS'").fetchone()["qty_on_hand"]
        moves = left.execute("SELECT COUNT(*) AS n FROM stock_movements WHERE batch_id='BAT-PR-ORS' AND movement_type='DISPENSED'").fetchone()["n"]
        left.close()
        assert float(qty) == 0
        assert moves == 1
        assert len(errors) == 1
    finally:
        os.environ.pop("AIPF_DATABASE_URL", None)
        admin = psycopg.connect(url, autocommit=True)
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='aipf_stock' AND pid <> pg_backend_pid()")
        admin.execute("DROP DATABASE IF EXISTS aipf_stock")
        admin.close()


if __name__ == "__main__":
    test_sqlite_migration_is_repeatable()
    test_atomic_stock_does_not_write_a_failed_movement()
    test_postgres_constraints_and_copy()
    test_postgres_stock_race()
    print("phase 0 checks passed")
