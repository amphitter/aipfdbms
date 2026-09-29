"""Stabilization checks. PostgreSQL is required for the ledger-alias defect."""

import os
import secrets
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("AIPF_SEED_PASSWORD", secrets.token_urlsafe(18))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aipf import pharmacy, theatre
from aipf.db import apply_migrations, connect
from aipf.server import ROUTES
from aipf.util import ApiError


def test_stream_ticket_accepts_get_and_post():
    methods = {method for method, pattern, *_ in ROUTES if pattern.match("/api/auth/stream-ticket")}
    assert "POST" in methods
    assert "GET" in methods


def test_alerts_query_runs_on_sqlite():
    folder = Path(tempfile.mkdtemp(prefix="aipf-stab-"))
    conn = connect(folder / "hospital.db")
    apply_migrations(conn)
    result = pharmacy.alerts(conn)
    assert "mismatches" in result
    conn.close()


def test_health_report_survives_hosts_without_load_average(monkeypatch):
    folder = Path(tempfile.mkdtemp(prefix="aipf-stab-health-"))
    conn = connect(folder / "hospital.db")
    apply_migrations(conn)
    import aipf.system as system
    monkeypatch.delattr(system.os, "getloadavg", raising=False)
    report = system.health_report(conn, deep=False)
    cpu = next(row for row in report["checks"] if row["name"] == "CPU")
    assert cpu["status"] == "HEALTHY"
    assert "not exposed" in cpu["detail"]
    conn.close()


def test_patient_delete_preserves_history_instead_of_purging():
    folder = Path(tempfile.mkdtemp(prefix="aipf-stab-patient-delete-"))
    conn = connect(folder / "hospital.db")
    apply_migrations(conn)
    conn.execute("INSERT INTO patients(id, name, status, created_at) VALUES (?,?,?,?)", ("P-DELETE", "Protected Patient", "ACTIVE", "2026-09-28T00:00:00+05:30"))
    from aipf import clinical
    try:
        clinical.delete_patient(conn, {"id": "U", "permissions": ["patient.edit"]}, "P-DELETE")
    except ApiError as exc:
        assert exc.status == 409
        assert exc.code == "history_preserved"
    else:
        raise AssertionError("patient deletion was not blocked")
    assert conn.execute("SELECT id FROM patients WHERE id='P-DELETE'").fetchone()[0] == "P-DELETE"
    conn.close()


def test_unknown_barcode_does_not_create_a_product():
    folder = Path(tempfile.mkdtemp(prefix="aipf-stab-"))
    conn = connect(folder / "hospital.db")
    apply_migrations(conn)
    before = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    try:
        pharmacy.receive_stock(conn, {"id": "U", "permissions": ["inventory.edit"]}, {"barcode": "UNKNOWN-STAB", "qty": 1, "batch_no": "B1"})
    except ApiError as exc:
        assert "No product was created" in exc.message or "Choose a product" in exc.message
    else:
        raise AssertionError("unknown barcode was accepted")
    after = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    assert after == before
    conn.close()


def test_empty_team_assignment_is_rejected():
    try:
        theatre.assign_team(None, {"id": "U", "permissions": ["ot.team.manage"]}, "OT-NONE", {"user_id": "", "function": "surgeon"})
    except ApiError as exc:
        assert "person" in exc.message.lower()
    else:
        raise AssertionError("empty team member was accepted")


def test_alerts_query_runs_on_postgres():
    url = os.environ.get("AIPF_TEST_POSTGRES", "").strip()
    if not url:
        print("skip postgres alerts: AIPF_TEST_POSTGRES is not set")
        return
    os.environ["AIPF_DATABASE_URL"] = url
    conn = connect()
    apply_migrations(conn)
    result = pharmacy.alerts(conn)
    assert isinstance(result["mismatches"], list)
    conn.close()
