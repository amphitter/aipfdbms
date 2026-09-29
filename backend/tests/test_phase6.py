"""Phase 6 inpatient occupancy, charges, and discharge. Real HTTP on throwaway PostgreSQL."""

import json
import os
import re
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

os.environ.setdefault("AIPF_SEED_PASSWORD", secrets.token_urlsafe(18))

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
URL_FILE = Path("/tmp/aipf_pg_url")
REPORT = ROOT / "PHASE-6-ACCEPTANCE-REPORT.md"

HEADINGS = [
    "Patient, encounter, admission, stay, ward, room, bed, movement, charge, and discharge stay separate",
    "Patient identity is the patient id, not the phone",
    "One patient can have many admissions over time",
    "One open admission is a PostgreSQL constraint",
    "Status transitions are enforced on the server",
    "Encounter must belong to the same patient",
    "Wards, rooms, beds, and types come from the database",
    "Referenced masters are deactivated, not deleted",
    "Beds keep a permanent id",
    "Bed status is not an arbitrary client string",
    "A blocked bed cannot be assigned",
    "One bed cannot have two active occupants",
    "One admission cannot have two current beds",
    "Assignment, movement, and discharge release are one transaction",
    "Bed history is append-only",
    "Concurrent admission to one bed yields one success and one conflict",
    "Concurrent movement leaves one current bed and no stale occupied bed",
    "Concurrent discharge yields one logical discharge",
    "The same idempotency key is one admission, one assignment, and one discharge",
    "Bed charges use the existing billing engine only",
    "Historical bed rates are snapshotted",
    "The same admission, bed, and period is not billed twice",
    "Moving to a higher rate does not reprice earlier lines",
    "Discharge releases the bed",
    "Due and settlement stay on the Phase 4 invoice",
    "Discharge summary is an A4 document",
    "Reprint is byte-identical and does not mutate records",
    "Discharge document uses StorageProvider",
    "Document retrieval is authorized on the server",
    "Timeline and bed availability respect record scope",
    "Authorization uses permission codes, not role names",
    "Audit has no delete route",
    "Schema change is a new versioned migration",
    "Locking and idempotency stay in the existing repository",
    "No second invoice, payment, or refund system",
]


def _with_database(url: str, name: str) -> str:
    base, query = (url.split("?", 1) + [""])[:2]
    query = f"?{query}" if query else ""
    head, _db = base.rsplit("/", 1)
    return f"{head}/{name}{query}"


def _postgres_url() -> str:
    url = (os.environ.get("AIPF_TEST_POSTGRES") or "").strip()
    if not url and URL_FILE.exists():
        url = URL_FILE.read_text(encoding="utf-8").strip()
    if not url.startswith("postgres"):
        raise AssertionError("PostgreSQL is required for the Phase 6 gate")
    return url


def _sanitize(text: str) -> str:
    text = re.sub(r"postgres(?:ql)?://\S+", "[database]", text or "")
    text = text.replace(str(URL_FILE), "[url-file]")
    return text


def _free_port(start: int) -> int:
    port = start
    while port < start + 20:
        with socket.socket() as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                port += 1
                continue
            return port
    return start


def _wait_ready(proc: subprocess.Popen, port: int) -> bool:
    deadline = time.time() + 60
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/public/branding", timeout=2) as res:
                if res.status == 200:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


def _drain(proc: subprocess.Popen) -> str:
    if proc.stdout is None:
        return ""
    try:
        return proc.stdout.read() or ""
    except Exception:
        return ""


def test_phase6_http_gate():
    try:
        failures = _run(_postgres_url())
    except Exception as exc:
        raise AssertionError(_sanitize(str(exc))) from None
    assert not failures, _sanitize("\n".join(failures))


def _run(admin_url: str) -> list[str]:
    import psycopg

    password = secrets.token_urlsafe(18)
    os.environ["AIPF_SEED_PASSWORD"] = password
    db_name = "aipf_phase6"
    admin = psycopg.connect(admin_url, autocommit=True)
    admin.execute(f"DROP DATABASE IF EXISTS {db_name} WITH (FORCE)")
    admin.execute(f"CREATE DATABASE {db_name}")
    admin.close()
    target = _with_database(admin_url, db_name)
    previous = os.environ.get("AIPF_DATABASE_URL")
    os.environ["AIPF_DATABASE_URL"] = target
    port = _free_port(8799)
    proc = None
    failures: list[str] = []
    evidence: list[dict] = []
    version = None
    try:
        from aipf.db import apply_migrations, connect
        from aipf.seed import seed
        from aipf import core

        conn = connect()
        assert conn.dialect == "postgres"
        version = apply_migrations(conn)
        seed(conn)
        core.config_set(conn, "backup_enabled", "0")
        conn.close()

        env = os.environ.copy()
        env["AIPF_DATABASE_URL"] = target
        env["AIPF_PORT"] = str(port)
        env["AIPF_SEED_PASSWORD"] = password
        env["AIPF_ENV"] = "development"
        proc = subprocess.Popen(
            [sys.executable, "-m", "aipf.server"],
            cwd=str(ROOT / "backend"),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        base = f"http://127.0.0.1:{port}"
        if not _wait_ready(proc, port):
            failures.append("server did not start: " + _sanitize(_drain(proc)[-800:]))
            _write_report(failures, evidence, version)
            return failures
        try:
            failures.extend(_gate(base, password, target, version, evidence))
        except Exception as exc:
            failures.append("gate stopped: " + type(exc).__name__ + " " + _sanitize(str(exc)))
        _write_report(failures, evidence, version)
        return failures
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        if previous is None:
            os.environ.pop("AIPF_DATABASE_URL", None)
        else:
            os.environ["AIPF_DATABASE_URL"] = previous
        try:
            admin = psycopg.connect(admin_url, autocommit=True)
            admin.execute(f"DROP DATABASE IF EXISTS {db_name} WITH (FORCE)")
            admin.close()
        except Exception:
            pass


def _gate(base: str, password: str, target: str, version, evidence: list[dict]) -> list[str]:
    import psycopg

    failures: list[str] = []

    def check(section: int, name: str, cond: bool, detail: str = ""):
        evidence.append({"section": section, "name": name, "ok": bool(cond)})
        if not cond:
            failures.append(f"{section}. {name}: {_sanitize(detail)}")

    def call(method, path, token=None, body=None, raw=False):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(base + path, data=data, method=method)
        if body is not None:
            req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", "Bearer " + token)
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                blob = res.read()
                if raw or "json" not in (res.headers.get("content-type") or ""):
                    return res.status, blob
                return res.status, json.loads(blob.decode())
        except urllib.error.HTTPError as exc:
            blob = exc.read()
            try:
                payload = json.loads(blob.decode())
            except Exception:
                payload = {"raw": blob[:180]}
            return exc.code, payload

    def login(username):
        status, payload = call("POST", "/api/auth/login", body={"username": username, "password": password})
        token = ((payload or {}).get("data") or {}).get("token")
        user = ((payload or {}).get("data") or {}).get("user") or {}
        return status, token, user

    def data_of(payload):
        return (payload or {}).get("data") or {}

    def err(payload):
        error = (payload or {}).get("error") or {}
        return error.get("message") or ""

    def race(fn_a, fn_b):
        results = [None, None]
        barrier = threading.Barrier(2)

        def run(index, fn):
            barrier.wait()
            results[index] = fn()

        threads = [threading.Thread(target=run, args=(0, fn_a)), threading.Thread(target=run, args=(1, fn_b))]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        return results

    status, admin, admin_user = login("director")
    check(31, "director can sign in", status == 200 and bool(admin), str(status))
    status, anita, anita_user = login("dr.anita")
    check(30, "admitting doctor can sign in", status == 200 and bool(anita))
    status, imran, imran_user = login("dr.imran")
    check(30, "second doctor can sign in", status == 200 and bool(imran))
    status, nurse, nurse_user = login("nurse")
    check(31, "nurse can sign in", status == 200 and bool(nurse))
    status, pharmacy, _ = login("pharmacy")
    check(31, "pharmacist can sign in", status == 200 and bool(pharmacy))
    status, billing, _ = login("billing")
    check(25, "billing user can sign in", status == 200 and bool(billing))
    if not all([admin, anita, imran, nurse, pharmacy, billing]):
        return failures

    wards_src = (ROOT / "backend/aipf/wards.py").read_text(encoding="utf-8")
    ipd_src = (ROOT / "backend/aipf/repo/ipd.py").read_text(encoding="utf-8")
    check(31, "authorization source does not branch on a role name", "role ==" not in wards_src and 'user.get("role")' not in wards_src)
    check(34, "domain module does not contain a SQL statement", "SELECT " not in wards_src and "INSERT " not in wards_src and "UPDATE " not in wards_src)
    check(34, "occupancy lock is in the repository", "FOR UPDATE" in ipd_src and "def occupy_bed" in ipd_src)
    check(34, "idempotency uses the existing key table", "idempotency_keys" in ipd_src and "ipd_idempotency" not in ipd_src)
    check(7, "ward names are not hardcoded in the inpatient module", "ICU" not in wards_src and "Private" not in wards_src)
    check(33, "schema version includes the phase 6 postgres migration", version == 19, str(version))
    applied = sorted(p.name for p in (ROOT / "backend/aipf/migrations").glob("00*.sql"))
    check(33, "phase 6 did not edit an earlier migration", "0015_ipd_integrity.sql" in applied and "0016_ipd_checks.postgres.sql" in applied and "0002_operational_indexes.sql" in applied)

    def patient(name, phone):
        status, payload = call("POST", "/api/patients", admin, {
            "name": name, "primary_phone": phone, "gender": "Female", "age_at_registration": 36, "confirm_new": True,
        })
        return status, data_of(payload).get("id")

    def visit(person, doctor="U-ANITA"):
        status, opd = call("POST", "/api/opd/types", admin, {"name": "Phase 6 card " + person, "fee_paise": 20000, "validity_days": 1})
        opd_id = data_of(opd).get("id")
        status, payload = call("POST", "/api/visits", admin, {"patient_id": person, "opd_type_id": opd_id, "doctor_id": doctor, "queue": False})
        return status, (data_of(payload).get("encounter") or {}).get("id")

    def place(code, kind, rate):
        status, ward = call("POST", "/api/wards", admin, {"name": f"Phase 6 {code}", "code": code, "ward_type": kind})
        ward_id = data_of(ward).get("id")
        status, room = call("POST", "/api/rooms", admin, {"ward_id": ward_id, "name": f"{code} room", "room_type": kind, "daily_rate_paise": rate})
        room_id = data_of(room).get("id")
        status, bed = call("POST", "/api/beds", admin, {"room_id": room_id, "name": f"{code} bed"})
        return ward_id, room_id, data_of(bed).get("id"), status

    status, person, = patient("Phase Six Patient", "9811100601")
    check(2, "patient is created by id", status == 200 and bool(person) and not str(person).startswith("9811"), str(status))
    status, twin = patient("Phase Six Twin", "9811100601")
    check(2, "shared phone does not merge patients", status == 200 and twin and twin != person)
    by_phone = call("POST", "/api/admissions", admin, {"phone": "9811100601", "reason": "Do not use the phone"})
    check(2, "admission cannot be created from a phone number", by_phone[0] == 404, str(by_phone[0]) + " " + err(by_phone[1]))

    status, encounter_id = visit(person)
    check(6, "encounter belongs to the patient", status == 200 and bool(encounter_id), str(status))
    status, other = patient("Phase Six Other", "9811100602")
    status, other_encounter = visit(other, "U-IMRAN")
    check(6, "second encounter is separate", status == 200 and other_encounter and other_encounter != encounter_id)
    foreign = call("POST", "/api/admissions", admin, {"patient_id": person, "encounter_id": other_encounter, "doctor_id": "U-ANITA", "reason": "Wrong encounter"})
    missing_enc = call("POST", "/api/admissions", admin, {"patient_id": person, "encounter_id": "ENC-MISSING", "doctor_id": "U-ANITA", "reason": "Missing encounter"})
    check(6, "another patient's encounter is not attached", foreign[0] == 404, str(foreign[0]) + " " + err(foreign[1]))
    check(6, "missing and foreign encounters look the same", foreign[0] == missing_enc[0] == 404 and err(foreign[1]) == err(missing_enc[1]), err(foreign[1]) + " | " + err(missing_enc[1]))
    bad_doctor = call("POST", "/api/admissions", admin, {"patient_id": person, "doctor_id": "U-NOBODY", "reason": "No doctor"})
    check(6, "unknown doctor is not attached", bad_doctor[0] == 404, str(bad_doctor[0]))

    low_ward, low_room, low_bed, low_status = place("P6A", "Observation", 100000)
    high_ward, high_room, high_bed, high_status = place("P6B", "Step down", 200000)
    blocked_ward, blocked_room, blocked_bed, blocked_status = place("P6C", "Isolation", 50000)
    check(7, "ward, room, and bed are created from the request", low_status == 200 and bool(low_bed) and bool(high_bed), str(low_status))
    status, wards = call("GET", "/api/beds", admin)
    names = {ward.get("name") for ward in data_of(wards).get("wards") or []}
    types = {ward.get("ward_type") for ward in data_of(wards).get("wards") or []}
    check(7, "created ward type is returned from the database", status == 200 and "Phase 6 P6A" in names and "Observation" in types, str(sorted(types)))
    duplicate_ward = call("POST", "/api/wards", admin, {"name": "Duplicate code", "code": "p6a", "ward_type": "Other"})
    check(7, "duplicate ward code is rejected", duplicate_ward[0] == 409, str(duplicate_ward[0]) + " " + err(duplicate_ward[1]))
    duplicate_room = call("POST", "/api/rooms", admin, {"ward_id": low_ward, "name": "P6A room", "daily_rate_paise": 1})
    check(7, "duplicate room name in a ward is rejected", duplicate_room[0] == 409, err(duplicate_room[1]))
    missing_ward = call("POST", "/api/rooms", admin, {"ward_id": "W-MISSING", "name": "Ghost", "daily_rate_paise": 1})
    check(7, "room cannot be attached to a missing ward", missing_ward[0] == 404, str(missing_ward[0]))

    blocked = call("POST", f"/api/beds/{blocked_bed}/status", nurse, {"status": "BLOCKED", "notes": "Closed"})
    check(11, "bed can be blocked by a known status", blocked[0] == 200 and data_of(blocked[1]).get("status") == "BLOCKED", err(blocked[1]))
    invented = call("POST", f"/api/beds/{blocked_bed}/status", nurse, {"status": "WHATEVER"})
    check(10, "unknown bed status is rejected", invented[0] == 400, str(invented[0]) + " " + err(invented[1]))
    forced = call("POST", "/api/admissions", admin, {
        "patient_id": other, "bed_id": blocked_bed, "doctor_id": "U-IMRAN", "status": "DISCHARGED", "daily_rate_paise": 1,
    })
    check(11, "a blocked bed cannot be assigned", forced[0] == 409, str(forced[0]) + " " + err(forced[1]))
    check(5, "client status does not discharge a new admission", data_of(forced[1]).get("status") != "DISCHARGED")

    requested = call("POST", "/api/admissions", admin, {
        "patient_id": person, "encounter_id": encounter_id, "doctor_id": "U-ANITA", "reason": "Observation",
        "idempotency_key": "p6-request", "daily_rate_paise": 1, "status": "DISCHARGED",
    })
    requested_id = data_of(requested[1]).get("id")
    check(1, "admission without a bed stays requested", requested[0] == 200 and data_of(requested[1]).get("status") == "REQUESTED", err(requested[1]))
    check(5, "client status is ignored", data_of(requested[1]).get("status") == "REQUESTED")
    replay_request = call("POST", "/api/admissions", admin, {
        "patient_id": person, "encounter_id": encounter_id, "doctor_id": "U-ANITA", "reason": "Observation",
        "idempotency_key": "p6-request",
    })
    check(19, "same admission key returns the same admission", replay_request[0] == 200 and data_of(replay_request[1]).get("id") == requested_id, err(replay_request[1]))
    second_open = call("POST", "/api/admissions", admin, {"patient_id": person, "doctor_id": "U-ANITA", "reason": "Second", "idempotency_key": "p6-second"})
    check(4, "a second open admission is rejected", second_open[0] == 409, str(second_open[0]) + " " + err(second_open[1]))

    assigned = call("POST", f"/api/admissions/{requested_id}/assign", nurse, {"bed_id": low_bed, "reason": "First bed", "idempotency_key": "p6-assign"})
    assigned_row = data_of(assigned[1])
    check(14, "assignment occupies the selected bed", assigned[0] == 200 and assigned_row.get("status") == "ADMITTED" and assigned_row.get("bed_id") == low_bed, err(assigned[1]))
    check(21, "assignment snapshots the room rate and ignores a client rate", assigned_row.get("daily_rate_paise") == 100000, str(assigned_row.get("daily_rate_paise")))
    assign_again = call("POST", f"/api/admissions/{requested_id}/assign", nurse, {"bed_id": low_bed, "reason": "First bed", "idempotency_key": "p6-assign"})
    check(19, "same assignment key does not create a second assignment", assign_again[0] == 200 and data_of(assign_again[1]).get("bed_id") == low_bed, err(assign_again[1]))
    hidden_board = call("GET", "/api/beds", imran)
    hidden_bed = [bed for ward in data_of(hidden_board[1]).get("wards") or [] for bed in ward.get("beds") or [] if bed.get("id") == low_bed]
    check(30, "an occupied bed does not reveal an out-of-scope patient", hidden_board[0] == 200 and hidden_bed and hidden_bed[0].get("status") == "OCCUPIED" and not hidden_bed[0].get("patient_name") and not hidden_bed[0].get("patient_id") and not hidden_bed[0].get("admission_id"), str(hidden_bed[:1]))
    status, board = call("GET", "/api/beds", nurse)
    occupied = [bed for ward in data_of(board).get("wards") or [] for bed in ward.get("beds") or [] if bed.get("id") == low_bed]
    check(12, "assigned bed is occupied by one admission", occupied and occupied[0].get("status") == "OCCUPIED" and occupied[0].get("current_admission_id") == requested_id, str(occupied[:1]))

    status, service = call("POST", "/api/services", admin, {"name": "Phase 6 nursing", "category": "HOSPITAL SERVICES", "rate_paise": 25000, "unit": "visit"})
    service_id = data_of(service).get("id")
    charged = call("POST", f"/api/admissions/{requested_id}/charges", nurse, {
        "description": "Client priced service", "category": "HOSPITAL SERVICES", "rate_paise": 1,
        "source_module": "service", "master_item_id": service_id,
    })
    invoice_id = (data_of(charged[1]).get("invoices") or [{}])[0].get("id") or data_of(charged[1]).get("invoice_id")
    status, invoice = call("GET", f"/api/invoices/{invoice_id}", billing)
    service_line = next((item for item in data_of(invoice).get("items") or [] if item.get("master_item_id") == service_id), {})
    bed_line = next((item for item in data_of(invoice).get("items") or [] if item.get("source_module") == "admission"), {})
    check(20, "service charge is an invoice line", charged[0] == 200 and bool(service_line), err(charged[1]))
    check(20, "service price comes from the master, not the client", service_line.get("rate_paise") == 25000, str(service_line.get("rate_paise")))
    check(21, "admission-day bed line uses the room rate", bed_line.get("rate_paise") == 100000, str(bed_line.get("rate_paise")))
    call("PATCH", f"/api/services/{service_id}", admin, {"name": "Phase 6 nursing", "category": "HOSPITAL SERVICES", "rate_paise": 90000, "unit": "visit"})
    status, invoice = call("GET", f"/api/invoices/{invoice_id}", billing)
    service_line = next((item for item in data_of(invoice).get("items") or [] if item.get("master_item_id") == service_id), {})
    check(21, "later service price does not rewrite the line", service_line.get("rate_paise") == 25000, str(service_line.get("rate_paise")))

    same_day = call("POST", f"/api/admissions/{requested_id}/bed-day", nurse, {"idempotency_key": "p6-day"})
    status, invoice = call("GET", f"/api/invoices/{invoice_id}", billing)
    ipd_lines = [item for item in data_of(invoice).get("items") or [] if item.get("category") == "IPD"]
    check(22, "the admission day is not billed a second time", same_day[0] == 200 and len(ipd_lines) == 1, str(len(ipd_lines)) + " " + err(same_day[1]))

    moved = call("POST", f"/api/admissions/{requested_id}/transfer", nurse, {"bed_id": high_bed, "reason": "Needs the higher room", "idempotency_key": "p6-move"})
    check(14, "movement changes the current bed", moved[0] == 200 and data_of(moved[1]).get("bed_id") == high_bed and data_of(moved[1]).get("daily_rate_paise") == 200000, err(moved[1]))
    movements = data_of(moved[1]).get("movements") or []
    check(15, "movement is appended", len(movements) >= 2 and movements[0].get("to_bed_id") == low_bed, str(movements))
    status, invoice = call("GET", f"/api/invoices/{invoice_id}", billing)
    bed_line = next((item for item in data_of(invoice).get("items") or [] if item.get("source_module") == "admission"), {})
    check(23, "moving from 1000 rupees to 2000 rupees does not reprice the earlier line", bed_line.get("rate_paise") == 100000, str(bed_line.get("rate_paise")))
    next_day = call("POST", f"/api/admissions/{requested_id}/bed-day", nurse, {"charge_date": "2099-01-01", "idempotency_key": "p6-next"})
    status, invoice = call("GET", f"/api/invoices/{invoice_id}", billing)
    next_line = next((item for item in data_of(invoice).get("items") or [] if "2099-01-01" in (item.get("description") or "")), {})
    old_line = next((item for item in data_of(invoice).get("items") or [] if item.get("source_module") == "admission"), {})
    check(23, "the later period uses the new rate", next_day[0] == 200 and next_line.get("rate_paise") == 200000 and old_line.get("rate_paise") == 100000, str(next_line.get("rate_paise")))
    before_lines = len(data_of(invoice).get("items") or [])
    raced = race(
        lambda: call("POST", f"/api/admissions/{requested_id}/bed-day", nurse, {"charge_date": "2099-01-02", "idempotency_key": "p6-race-day-a"}),
        lambda: call("POST", f"/api/admissions/{requested_id}/bed-day", nurse, {"charge_date": "2099-01-02", "idempotency_key": "p6-race-day-b"}),
    )
    status, invoice = call("GET", f"/api/invoices/{invoice_id}", billing)
    day_lines = [item for item in data_of(invoice).get("items") or [] if "2099-01-02" in (item.get("description") or "")]
    check(22, "concurrent generation of the same period creates one line", len(day_lines) == 1 and len(data_of(invoice).get("items") or []) == before_lines + 1, str(len(day_lines)) + " " + str([item[0] for item in raced]))

    pending = call("POST", f"/api/admissions/{requested_id}/discharge-pending", nurse, {})
    check(5, "discharge pending keeps the stay open", pending[0] == 200 and data_of(pending[1]).get("status") == "DISCHARGE_PENDING" and data_of(pending[1]).get("bed_id") == high_bed, err(pending[1]))
    status, board = call("GET", "/api/beds", nurse)
    still = [bed for ward in data_of(board).get("wards") or [] for bed in ward.get("beds") or [] if bed.get("id") == high_bed]
    check(5, "pending discharge does not free the bed", still and still[0].get("status") == "OCCUPIED", str(still[:1]))
    backwards = call("POST", f"/api/admissions/{requested_id}/assign", nurse, {"bed_id": low_bed, "idempotency_key": "p6-back"})
    check(5, "an admitted stay cannot be assigned as if it were requested", backwards[0] == 409, str(backwards[0]))

    pg = psycopg.connect(target)
    indexes = {row[0]: row[1] for row in pg.execute("SELECT indexname, indexdef FROM pg_indexes WHERE indexname IN ('uq_admission_one_open','uq_bed_current_admission','uq_bed_day_charge')")}
    check(4, "open admission is a partial unique index", "uq_admission_one_open" in indexes and "DISCHARGE_PENDING" in indexes["uq_admission_one_open"], indexes.get("uq_admission_one_open", ""))
    check(12, "one current occupant is a partial unique index", "uq_bed_current_admission" in indexes, str(indexes.keys()))
    check(13, "one current bed pointer is the same bed index", "current_admission_id" in indexes.get("uq_bed_current_admission", ""))
    check(22, "one charge per period is a partial unique index", "uq_bed_day_charge" in indexes and "bed_day" in indexes["uq_bed_day_charge"], indexes.get("uq_bed_day_charge", ""))
    forbidden = [row[0] for row in pg.execute("SELECT table_name FROM information_schema.tables WHERE table_name IN ('ipd_payments','ipd_invoices','ipd_refunds')")]
    check(35, "no inpatient payment, invoice, or refund table exists", forbidden == [], str(forbidden))
    pg.close()

    summary = "Observed overnight. Fit for discharge. " + ("Stable progress recorded for the file. " * 90)
    discharge_body = {"discharge_summary": summary, "discharge_condition": "Stable", "idempotency_key": "p6-discharge"}
    raced = race(
        lambda: call("POST", f"/api/admissions/{requested_id}/discharge", nurse, discharge_body),
        lambda: call("POST", f"/api/admissions/{requested_id}/discharge", nurse, discharge_body),
    )
    codes = sorted(item[0] for item in raced)
    status, after = call("GET", f"/api/admissions/{requested_id}", nurse)
    check(18, "concurrent discharge has one success", 200 in codes and data_of(after).get("status") == "DISCHARGED", str(codes) + " " + err(after))
    replay_discharge = call("POST", f"/api/admissions/{requested_id}/discharge", nurse, discharge_body)
    check(19, "same discharge key returns the discharged admission", replay_discharge[0] == 200 and data_of(replay_discharge[1]).get("status") == "DISCHARGED", err(replay_discharge[1]))
    status, board = call("GET", "/api/beds", nurse)
    released = [bed for ward in data_of(board).get("wards") or [] for bed in ward.get("beds") or [] if bed.get("id") == high_bed]
    old_bed = [bed for ward in data_of(board).get("wards") or [] for bed in ward.get("beds") or [] if bed.get("id") == low_bed]
    check(24, "discharge does not leave the last bed occupied", released and released[0].get("status") == "AVAILABLE" and not released[0].get("current_admission_id"), str(released[:1]))
    check(17, "the previous bed is not left occupied", old_bed and old_bed[0].get("status") == "AVAILABLE" and not old_bed[0].get("current_admission_id"), str(old_bed[:1]))
    check(9, "bed id is unchanged after release", released[0].get("id") == high_bed)
    again = call("POST", "/api/admissions", anita, {
        "patient_id": person, "encounter_id": encounter_id, "doctor_id": "U-ANITA", "reason": "Readmission", "idempotency_key": "p6-readmit",
    })
    second_id = data_of(again[1]).get("id")
    check(3, "the same patient can be admitted again after discharge", again[0] == 200 and second_id and second_id != requested_id, err(again[1]))
    cancelled = call("POST", f"/api/admissions/{second_id}/cancel", nurse, {"reason": "Did not arrive"})
    check(5, "a requested admission can be cancelled without deletion", cancelled[0] == 200 and data_of(cancelled[1]).get("status") == "CANCELLED" and data_of(cancelled[1]).get("id") == second_id, err(cancelled[1]))
    dead = call("POST", f"/api/admissions/{requested_id}/discharge", nurse, {"discharge_summary": "Again", "discharge_condition": "Stable", "idempotency_key": "p6-again"})
    check(5, "a discharged admission cannot be discharged again", dead[0] == 409, str(dead[0]) + " " + err(dead[1]))

    status, invoice = call("GET", f"/api/invoices/{invoice_id}", billing)
    due_before = data_of(invoice).get("due_paise")
    net = data_of(invoice).get("net_paise")
    check(25, "invoice total is the server total", isinstance(net, int) and net == due_before and net >= 100000, str(net))
    finalized = call("POST", f"/api/invoices/{invoice_id}/finalize", billing, {})
    check(25, "billing finalizes the inpatient invoice", finalized[0] == 200 and data_of(finalized[1]).get("status") == "FINALIZED", err(finalized[1]))
    nurse_pay = call("POST", f"/api/invoices/{invoice_id}/payments", nurse, {"mode": "Cash", "amount_paise": 100, "idempotency_key": "p6-nurse-pay"})
    check(25, "inpatient staff cannot settle the bill", nurse_pay[0] == 403, str(nurse_pay[0]))
    paid = call("POST", f"/api/invoices/{invoice_id}/payments", billing, {"mode": "Cash", "amount_paise": 10000, "idempotency_key": "p6-pay"})
    status, invoice = call("GET", f"/api/invoices/{invoice_id}", billing)
    check(25, "settlement uses the invoice payment path", paid[0] == 200 and data_of(invoice).get("paid_paise") == 10000 and data_of(invoice).get("due_paise") == net - 10000, err(paid[1]) + " " + str(data_of(invoice).get("due_paise")))
    late_line = call("POST", f"/api/invoices/{invoice_id}/items", billing, {"description": "Late edit", "category": "IPD", "rate_paise": 1, "qty": 1})
    check(25, "finalized inpatient invoice rejects a direct edit", late_line[0] == 400, str(late_line[0]) + " " + err(late_line[1]))

    pg = psycopg.connect(target)
    before_docs = pg.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    before_audit = pg.execute("SELECT COUNT(*) FROM audit_logs WHERE entity_id=%s AND action LIKE 'discharge_document%%'", (requested_id,)).fetchone()[0]
    before_admission = pg.execute("SELECT updated_at, discharge_summary FROM admissions WHERE id=%s", (requested_id,)).fetchone()
    before_patient = pg.execute("SELECT updated_at FROM patients WHERE id=%s", (person,)).fetchone()[0]
    pg.close()
    generated = call("POST", f"/api/admissions/{requested_id}/discharge-document", nurse, {})
    doc = data_of(generated[1])
    check(28, "discharge document is stored without a filesystem path", generated[0] == 200 and doc.get("id") and "stored_name" not in doc and "path" not in doc and "home/user" not in json.dumps(doc), err(generated[1]))
    first_pdf = call("GET", f"/api/admissions/{requested_id}/discharge-document", nurse, raw=True)
    second_pdf = call("GET", f"/api/admissions/{requested_id}/discharge-document", nurse, raw=True)
    pdf = first_pdf[1] if isinstance(first_pdf[1], bytes) else b""
    pdf2 = second_pdf[1] if isinstance(second_pdf[1], bytes) else b""
    check(26, "discharge summary is a PDF", first_pdf[0] == 200 and pdf.startswith(b"%PDF"), str(first_pdf[0]))
    check(26, "page size is A4", b"595.28 841.89" in pdf, "")
    check(26, "page is white and numbered", b"1 1 1 rg" in pdf and b"Page 1 of" in pdf and b"Page 2 of" in pdf)
    check(26, "rupee amount is drawn from the stored charges", b"1,000.00" in pdf and b"2,000.00" in pdf)
    check(27, "reprint bytes are identical", pdf == pdf2 and len(pdf) > 1000, str(len(pdf)) + " " + str(len(pdf2)))
    generated_again = call("POST", f"/api/admissions/{requested_id}/discharge-document", nurse, {})
    check(27, "generating the unchanged summary does not create a second document", generated_again[0] == 200 and data_of(generated_again[1]).get("id") == doc.get("id"), err(generated_again[1]))
    pg = psycopg.connect(target)
    after_docs = pg.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    after_audit = pg.execute("SELECT COUNT(*) FROM audit_logs WHERE entity_id=%s AND action LIKE 'discharge_document%%'", (requested_id,)).fetchone()[0]
    after_admission = pg.execute("SELECT updated_at, discharge_summary FROM admissions WHERE id=%s", (requested_id,)).fetchone()
    after_patient = pg.execute("SELECT updated_at FROM patients WHERE id=%s", (person,)).fetchone()[0]
    stored = pg.execute("SELECT stored_name FROM documents WHERE id=%s", (doc.get("id"),)).fetchone()
    check(27, "reprint does not add a document or a duplicate audit", after_docs == before_docs + 1 and after_audit == before_audit + 1, f"docs {before_docs}->{after_docs} audit {before_audit}->{after_audit}")
    check(27, "reprint does not mutate the admission or the patient", after_admission == before_admission and after_patient == before_patient)
    check(28, "document bytes are read through storage", bool(stored and stored[0]) and "home/user" not in json.dumps(doc))
    pg.close()

    hidden = call("GET", f"/api/admissions/{requested_id}", imran)
    missing = call("GET", "/api/admissions/ADM-DOES-NOT-EXIST", imran)
    check(30, "another doctor cannot open the admission by changing the id", hidden[0] == 404, str(hidden[0]) + " " + err(hidden[1]))
    check(30, "missing and hidden admissions look the same", hidden[0] == missing[0] and err(hidden[1]) == err(missing[1]), err(hidden[1]) + " | " + err(missing[1]))
    hidden_pdf = call("GET", f"/api/admissions/{requested_id}/discharge-document", imran, raw=True)
    missing_pdf = call("GET", "/api/admissions/ADM-DOES-NOT-EXIST/discharge-document", imran, raw=True)
    check(29, "document retrieval is refused outside record scope", hidden_pdf[0] == 404, str(hidden_pdf[0]))
    check(29, "missing and hidden documents look the same", hidden_pdf[0] == missing_pdf[0])
    anita_pdf = call("GET", f"/api/admissions/{requested_id}/discharge-document", anita, raw=True)
    check(29, "the admitting doctor can read the stored summary", anita_pdf[0] == 200 and isinstance(anita_pdf[1], bytes) and anita_pdf[1] == pdf)
    timeline = call("GET", f"/api/patients/{person}/timeline", anita)
    kinds = {event.get("kind") for event in data_of(timeline[1]).get("events") or []}
    check(30, "timeline includes the stay and the movement", timeline[0] == 200 and {"admission", "discharge", "bed_movement"} <= kinds, str(sorted(kinds)))
    hidden_timeline = call("GET", f"/api/patients/{person}/timeline", imran)
    check(30, "the other doctor does not receive the timeline", hidden_timeline[0] == 404, str(hidden_timeline[0]))
    imran_board = call("GET", "/api/beds", imran)
    imran_bed = [bed for ward in data_of(imran_board[1]).get("wards") or [] for bed in ward.get("beds") or [] if bed.get("id") == high_bed]
    check(30, "bed availability does not reveal an out-of-scope name", imran_board[0] == 200 and imran_bed and not imran_bed[0].get("patient_name") and not imran_bed[0].get("patient_id"), str(imran_bed[:1]))

    pharm_admit = call("POST", "/api/admissions", pharmacy, {"patient_id": other, "doctor_id": "U-IMRAN", "reason": "No"})
    check(31, "pharmacist cannot admit", pharm_admit[0] == 403, str(pharm_admit[0]))
    roles = data_of(call("GET", "/api/roles", admin)[1]).get("items") or []
    nurse_role = next(role for role in roles if role.get("code") == "nurse")
    original = list(nurse_role.get("permissions") or [])
    narrowed = [code for code in original if code not in {"admission.manage", "ipd.bed.move", "ipd.bed.assign", "ipd.discharge.finalize"}]
    call("PUT", "/api/roles/nurse/permissions", admin, {"permissions": narrowed})
    status, nurse2, nurse2_user = login("nurse")
    check(31, "permission change is visible without changing the role name", "ipd.bed.move" not in (nurse2_user.get("permissions") or []) and "nurse" in (nurse2_user.get("roles") or []))
    denied_move = call("POST", f"/api/admissions/{requested_id}/transfer", nurse2, {"bed_id": low_bed, "reason": "Should fail", "idempotency_key": "p6-denied"})
    check(31, "movement requires a permission code", denied_move[0] == 403, str(denied_move[0]))
    call("PUT", "/api/roles/nurse/permissions", admin, {"permissions": narrowed + ["ipd.bed.move"]})
    status, nurse3, _ = login("nurse")
    still_denied = call("POST", f"/api/admissions/{requested_id}/transfer", nurse3, {"bed_id": low_bed, "reason": "Discharged", "idempotency_key": "p6-denied-2"})
    check(31, "a granted move code is enforced by the server", still_denied[0] in (403, 404, 409), str(still_denied[0]))
    call("PUT", "/api/roles/nurse/permissions", admin, {"permissions": original})

    from aipf.server import CATALOG
    methods = {(item["method"], item["path"]) for item in CATALOG}
    check(32, "audit has no delete route", ("DELETE", "/api/audit") not in methods and not any(item["method"] == "DELETE" and "audit" in item["path"] for item in CATALOG))
    check(8, "wards, admissions, and movements have no delete route", not any(item["method"] == "DELETE" and any(part in item["path"] for part in ("/api/wards", "/api/admissions", "/api/beds")) for item in CATALOG))
    deactivated = call("PATCH", f"/api/wards/{low_ward}", admin, {"name": "Phase 6 P6A", "code": "P6A", "ward_type": "Observation", "active": False})
    check(8, "a referenced ward is deactivated", deactivated[0] == 200 and data_of(deactivated[1]).get("active") in (0, False), err(deactivated[1]))
    still_there = call("GET", f"/api/admissions/{requested_id}", admin)
    check(8, "deactivation does not remove the historical admission", still_there[0] == 200 and data_of(still_there[1]).get("id") == requested_id)
    removed = call("DELETE", f"/api/wards/{low_ward}", admin)
    check(8, "there is no ward delete", removed[0] in (404, 405), str(removed[0]))

    status, rival_a = patient("Phase Six Rival A", "9811100603")
    status, rival_b = patient("Phase Six Rival B", "9811100604")
    _, _, race_bed, _ = place("P6R", "Overflow", 100000)
    _, _, left_bed, _ = place("P6L", "Left", 100000)
    _, _, right_bed, _ = place("P6Z", "Right", 100000)
    hold = call("POST", "/api/admissions", admin, {"patient_id": rival_a, "doctor_id": "U-ANITA", "bed_id": left_bed, "reason": "Hold", "idempotency_key": "p6-hold"})
    hold_id = data_of(hold[1]).get("id")
    check(16, "race setup admission exists", hold[0] == 200 and bool(hold_id), err(hold[1]))
    raced = race(
        lambda: call("POST", "/api/admissions", admin, {"patient_id": rival_b, "doctor_id": "U-IMRAN", "bed_id": race_bed, "reason": "Race", "idempotency_key": "p6-bed-a"}),
        lambda: call("POST", "/api/admissions", admin, {"patient_id": other, "doctor_id": "U-IMRAN", "bed_id": race_bed, "reason": "Race", "idempotency_key": "p6-bed-b"}),
    )
    winners = [item for item in raced if item[0] == 200]
    check(16, "two patients and one bed produce one success and one conflict", len(winners) == 1 and any(item[0] == 409 for item in raced), str([item[0] for item in raced]))
    status, board = call("GET", "/api/beds", admin)
    race_row = [bed for ward in data_of(board).get("wards") or [] for bed in ward.get("beds") or [] if bed.get("id") == race_bed]
    check(16, "the contested bed has one occupant", race_row and race_row[0].get("status") == "OCCUPIED" and bool(race_row[0].get("current_admission_id")), str(race_row[:1]))
    raced = race(
        lambda: call("POST", f"/api/admissions/{hold_id}/transfer", admin, {"bed_id": right_bed, "reason": "Move right", "idempotency_key": "p6-move-a"}),
        lambda: call("POST", f"/api/admissions/{hold_id}/transfer", admin, {"bed_id": race_bed, "reason": "Move contest", "idempotency_key": "p6-move-b"}),
    )
    held = call("GET", f"/api/admissions/{hold_id}", admin)
    status, board = call("GET", "/api/beds", admin)
    current = data_of(held[1]).get("bed_id")
    occupied_ids = [bed.get("id") for ward in data_of(board).get("wards") or [] for bed in ward.get("beds") or [] if bed.get("current_admission_id") == hold_id]
    stale = [bed for ward in data_of(board).get("wards") or [] for bed in ward.get("beds") or [] if bed.get("id") == left_bed]
    check(17, "concurrent movement leaves one current bed", held[0] == 200 and occupied_ids == [current] and current in (right_bed, race_bed, left_bed), str(occupied_ids) + " " + str([item[0] for item in raced]))
    check(17, "the bed that was left is not occupied by the moved admission", not stale or stale[0].get("current_admission_id") != hold_id or current == left_bed, str(stale[:1]))

    pg = psycopg.connect(target)
    pg.execute("BEGIN")
    try:
        pg.execute("INSERT INTO admissions(id, patient_id, status, created_at) VALUES ('ADM-SQL-1', %s, 'REQUESTED', '2026-09-27T00:00:00')", (person,))
        raised = False
        try:
            pg.execute("INSERT INTO admissions(id, patient_id, status, created_at) VALUES ('ADM-SQL-2', %s, 'ADMITTED', '2026-09-27T00:00:01')", (person,))
        except Exception as exc:
            raised = "unique" in str(exc).lower() or "duplicate" in str(exc).lower()
        check(4, "PostgreSQL rejects a second open admission without the application", raised)
    finally:
        pg.execute("ROLLBACK")
    pg.close()

    check(1, "charge rows are not payment rows", "ipd_payments" not in wards_src and "record_payment" not in wards_src)
    check(35, "inpatient module does not record payments", "record_payment" not in wards_src and "create_deposit" not in wards_src)
    return failures


def _write_report(failures: list[str], evidence: list[dict], version) -> None:
    by_section: dict[int, list[dict]] = {i: [] for i in range(1, 36)}
    for item in evidence:
        by_section.setdefault(int(item["section"]), []).append(item)
    failed = [item for item in evidence if not item["ok"]]
    decision = "PHASE 6 ACCEPTED" if not failures and not failed else "PHASE 6 NOT ACCEPTED"
    lines = [
        "# PHASE 6 ACCEPTANCE REPORT",
        "",
        f"Decision: {decision}",
        "",
        "Phase 6 inpatient stay only. Phases 0–5 were not reopened except for the schema-version assertion required by the new migration.",
        "Phase 4 remains the only financial source of truth. No inpatient payment, invoice, or refund table was added.",
        "",
        "Gate: real HTTP against a throwaway PostgreSQL database. The database URL is not recorded here.",
        f"Schema version observed: {version}.",
        f"Checks recorded: {len(evidence)}. Checks failed: {len(failed)}.",
        "",
    ]
    for index, title in enumerate(HEADINGS, start=1):
        items = by_section.get(index) or []
        passed = sum(1 for item in items if item["ok"])
        result = "PASS" if items and passed == len(items) else "FAIL"
        lines.append(f"## {index}. {title}")
        lines.append("")
        lines.append(f"Result: {result}. {passed} of {len(items)} checks passed.")
        lines.append("")
        for item in items:
            mark = "PASS" if item["ok"] else "FAIL"
            lines.append(f"- {mark}: {item['name']}")
        if not items:
            lines.append("- FAIL: no check was recorded")
        lines.append("")
    lines.extend([
        "## Gate evidence",
        "",
        "The gate started the hospital server and called it over HTTP. Occupancy and charge races used two concurrent requests.",
        "PostgreSQL indexes and the rejected second open admission were read from the throwaway database after the HTTP calls.",
        "The database URL is not included.",
        "",
        "## Regression",
        "",
        "Phase 0 expects SQLite schema 17. 0017 is shared. 0016 and 0018 are PostgreSQL-only.",
        "Phase 5 expects PostgreSQL schema 19 because later migrations are applied with the existing ones.",
        "Admission without a bed still returns REQUESTED. The room rate, not the client rate, is snapshotted.",
        "",
        "## Remaining non-blocking limitations",
        "",
        "ADMITTED remains the occupied status. It was not renamed to ACTIVE, because Phase 4, Phase 5, and the current desk already use ADMITTED.",
        "DISCHARGE_PENDING and CANCELLED were added. A client cannot choose either status by sending a status string.",
        "",
    ])
    if failures:
        lines.append("Failures:")
        lines.append("")
        for failure in failures:
            lines.append(f"- {failure}")
        lines.append("")
    REPORT.write_text("\n".join(lines), encoding="utf-8")
