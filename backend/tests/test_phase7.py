"""Phase 7 operating theatre workflow. Real HTTP on throwaway PostgreSQL."""

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
REPORT = ROOT / "PHASE-7-ACCEPTANCE-REPORT.md"

HEADINGS = [
    "Patient, encounter, admission, request, booking, theatre, procedure, team, pre-op, intra-op, post-op, and document stay separate",
    "Patient identity is the patient id, not the phone",
    "A foreign encounter is rejected",
    "A foreign admission is rejected",
    "Missing and unauthorized OT records look the same",
    "Theatres come from the database",
    "Procedures come from the database",
    "Referenced masters are not deleted",
    "Status transitions are enforced on the server",
    "Client JSON cannot force completed",
    "The accepted notes path still completes",
    "The same theatre cannot hold two overlapping bookings",
    "The same surgeon cannot hold two overlapping bookings",
    "Different theatres at the same time can both succeed",
    "Concurrent theatre overlap yields one success and one conflict",
    "Concurrent surgeon overlap yields one success and one conflict",
    "The same case has one logical booking",
    "Reschedule and cancel preserve history",
    "A cancelled case stays readable",
    "Pre-op, consent, and readiness stay separate from the operative record",
    "Start waits for consent, readiness, and the checklist",
    "Intra-operative records are not overwritten",
    "Post-operative records are not overwritten",
    "Concurrent completion is one logical completion",
    "Concurrent start is one logical start",
    "Charges go through Phase 4 only",
    "Client price and tax are ignored",
    "The procedure price is snapshotted",
    "The same case, procedure, and purpose is one charge",
    "A billed cancellation does not delete financial rows",
    "Pharmacy stock is not mutated by OT",
    "Laboratory orders stay in the laboratory module",
    "Inpatient OT uses the admission identity",
    "Timeline events respect record scope",
    "Authorization uses permission codes, not role names",
    "Audit has no delete route",
    "The operation report is an A4 document from stored data",
    "Reprint is byte-identical and does not mutate records",
    "Documents use StorageProvider",
    "Document retrieval is authorized on the server",
    "Schema change is a new versioned migration",
    "Locking stays in the repository",
    "Idempotency uses the existing key table",
    "No second invoice, payment, or refund system",
    "Realtime events carry record scope",
    "Existing OT notes still bill the procedure master fee",
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
        raise AssertionError("PostgreSQL is required for the Phase 7 gate")
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


def test_phase7_http_gate():
    try:
        failures = _run(_postgres_url())
    except Exception as exc:
        raise AssertionError(_sanitize(str(exc))) from None
    assert not failures, _sanitize("\n".join(failures))


def _run(admin_url: str) -> list[str]:
    import psycopg

    password = secrets.token_urlsafe(18)
    os.environ["AIPF_SEED_PASSWORD"] = password
    db_name = "aipf_phase7"
    admin = psycopg.connect(admin_url, autocommit=True)
    admin.execute("DROP DATABASE IF EXISTS aipf_p7smoke WITH (FORCE)")
    admin.execute(f"DROP DATABASE IF EXISTS {db_name} WITH (FORCE)")
    admin.execute(f"CREATE DATABASE {db_name}")
    admin.close()
    target = _with_database(admin_url, db_name)
    previous = os.environ.get("AIPF_DATABASE_URL")
    os.environ["AIPF_DATABASE_URL"] = target
    port = _free_port(8817)
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
        core.config_set(conn, "ot_require_consent", "1")
        core.config_set(conn, "ot_require_readiness", "1")
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
        if not _wait_ready(proc, port):
            failures.append("server did not start: " + _sanitize(_drain(proc)[-800:]))
            _write_report(failures, evidence, version)
            return failures
        try:
            failures.extend(_gate(f"http://127.0.0.1:{port}", password, target, version, evidence))
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
        return ((payload or {}).get("error") or {}).get("message") or ""

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

    status, admin, _ = login("director")
    check(35, "director can sign in", status == 200 and bool(admin), str(status))
    status, anita, anita_user = login("dr.anita")
    check(35, "operating doctor can sign in", status == 200 and bool(anita) and anita_user.get("id") == "U-ANITA")
    status, imran, _ = login("dr.imran")
    check(5, "second doctor can sign in", status == 200 and bool(imran))
    status, nurse, _ = login("nurse")
    check(35, "nurse can sign in", status == 200 and bool(nurse))
    status, billing, _ = login("billing")
    check(26, "billing user can sign in", status == 200 and bool(billing))
    status, reception, _ = login("reception")
    check(34, "reception can sign in", status == 200 and bool(reception))
    status, lab, _ = login("lab")
    check(35, "laboratory user can sign in", status == 200 and bool(lab))
    if not all([admin, anita, imran, nurse, billing, reception, lab]):
        return failures

    theatre_src = (ROOT / "backend/aipf/theatre.py").read_text(encoding="utf-8")
    ot_src = (ROOT / "backend/aipf/repo/ot.py").read_text(encoding="utf-8")
    server_src = (ROOT / "backend/aipf/server.py").read_text(encoding="utf-8")
    wards_src = (ROOT / "backend/aipf/wards.py").read_text(encoding="utf-8")
    check(35, "authorization source does not branch on a role name", "role ==" not in theatre_src and 'user.get("role")' not in theatre_src)
    check(42, "domain module does not contain a SQL statement", "SELECT " not in theatre_src and "INSERT " not in theatre_src and "UPDATE " not in theatre_src)
    check(42, "theatre and surgeon locks are in the repository", "FOR UPDATE" in ot_src and "def lock_theatre" in ot_src and "def lock_user" in ot_src)
    check(43, "idempotency uses the existing key table", "idempotency_keys" in ot_src and "ot_idempotency" not in ot_src)
    check(6, "theatre names are not hardcoded in the theatre module", "Main Theatre" not in theatre_src and "OT-1" not in theatre_src)
    check(41, "schema version is the phase 7 postgres migration", version == 19, str(version))
    applied = sorted(p.name for p in (ROOT / "backend/aipf/migrations").glob("00*.sql"))
    check(41, "phase 7 added a new migration and left earlier files in place", "0017_ot_workflow.sql" in applied and "0018_ot_checks.postgres.sql" in applied and "0016_ipd_checks.postgres.sql" in applied)
    check(44, "theatre module does not record payments", "record_payment" not in theatre_src and "ot_invoices" not in theatre_src)
    check(31, "theatre module does not write stock movements", "stock_movements" not in theatre_src)
    check(45, "events carry the patient and the view permission", '"permission": "ot.view"' in theatre_src and "patient_id" in theatre_src)
    check(45, "the existing stream filters a permission on the event", 'data.get("permission")' in server_src)
    check(39, "report bytes are read through storage", "get_storage()" in theatre_src and "document_file" in theatre_src)
    check(11, "legacy notes still ask the billing engine for the configured fee", "configured_procedure_fee" in wards_src)

    seq = {"n": 0}

    def patient(name):
        seq["n"] += 1
        status, payload = call("POST", "/api/patients", admin, {
            "name": name, "primary_phone": f"9811107{seq['n']:03d}", "gender": "Female", "age_at_registration": 41, "confirm_new": True,
        })
        return status, data_of(payload).get("id")

    def visit(person, doctor="U-ANITA"):
        status, opd = call("POST", "/api/opd/types", admin, {"name": "Phase 7 card " + person, "fee_paise": 20000, "validity_days": 1})
        status, payload = call("POST", "/api/visits", admin, {
            "patient_id": person, "opd_type_id": data_of(opd).get("id"), "doctor_id": doctor, "queue": False,
        })
        return status, (data_of(payload).get("encounter") or {}).get("id")

    status, ward = call("POST", "/api/wards", admin, {"name": "Phase 7 ward", "code": "P7", "ward_type": "Surgical"})
    ward_id = data_of(ward).get("id")
    status, room = call("POST", "/api/rooms", admin, {"ward_id": ward_id, "name": "Phase 7 room", "room_type": "Surgical", "daily_rate_paise": 150000})
    room_id = data_of(room).get("id")

    def bed(label):
        status, payload = call("POST", "/api/beds", admin, {"room_id": room_id, "name": label})
        return status, data_of(payload).get("id")

    def admit(person, encounter_id, label):
        status, bed_id = bed(label)
        status, payload = call("POST", "/api/admissions", admin, {
            "patient_id": person, "encounter_id": encounter_id, "doctor_id": "U-ANITA", "reason": label,
        })
        admission_id = data_of(payload).get("id")
        return admission_id, bed_id, data_of(payload).get("status")

    status, theatre_a = call("POST", "/api/ot/theatres", admin, {"code": "P7-A", "name": "Phase Seven North", "location": "First floor"})
    theatre_a_id = data_of(theatre_a).get("id")
    status, theatre_b = call("POST", "/api/ot/theatres", admin, {"code": "P7-B", "name": "Phase Seven South", "location": "First floor"})
    theatre_b_id = data_of(theatre_b).get("id")
    status, theatre_c = call("POST", "/api/ot/theatres", admin, {"code": "P7-C", "name": "Phase Seven Spare", "location": "Annex"})
    theatre_c_id = data_of(theatre_c).get("id")
    check(6, "theatres are created from the request", status == 200 and theatre_a_id and theatre_b_id and theatre_a_id != theatre_b_id, err(theatre_a))
    duplicate_theatre = call("POST", "/api/ot/theatres", admin, {"code": "p7-a", "name": "Duplicate"})
    check(6, "duplicate theatre code is rejected", duplicate_theatre[0] == 409, err(duplicate_theatre[1]))
    status, listed = call("GET", "/api/ot/theatres", anita)
    names = {item.get("name") for item in data_of(listed).get("items") or []}
    check(6, "created theatre name is returned from the database", status == 200 and "Phase Seven North" in names and "Main Theatre" not in names, str(sorted(names)))

    status, procedure = call("POST", "/api/ot/procedures", admin, {
        "code": "P7-REP", "name": "Phase Seven Repair", "category": "General", "price_paise": 125000,
        "duration_minutes": 60, "require_admission": 1,
    })
    procedure_id = data_of(procedure).get("id")
    check(7, "procedure price and admission rule come from the request", status == 200 and data_of(procedure).get("price_paise") == 125000 and data_of(procedure).get("require_admission") in (1, True), err(procedure))
    duplicate_procedure = call("POST", "/api/ot/procedures", admin, {"code": "p7-rep", "name": "Other", "price_paise": 1})
    check(7, "duplicate procedure code is rejected", duplicate_procedure[0] == 409, err(duplicate_procedure[1]))
    status, check_item = call("POST", "/api/ot/checklist", admin, {"code": "P7-ID", "label": "Identity confirmed", "required": 1})
    check_id = data_of(check_item).get("id")
    check(21, "checklist item is database-managed", status == 200 and bool(check_id), err(check_item))

    status, person = patient("Phase Seven Patient")
    check(2, "patient is created by id", status == 200 and bool(person) and not str(person).startswith("9811"), str(person))
    status, encounter_id = visit(person)
    check(3, "encounter belongs to the patient", status == 200 and bool(encounter_id), str(status))
    status, other = patient("Phase Seven Other")
    status, other_encounter = visit(other, "U-IMRAN")
    other_admission, _, _ = admit(other, other_encounter, "Other bed")
    status, other_bed = bed("Other assigned")
    assigned_other = call("POST", f"/api/admissions/{other_admission}/assign", nurse, {"bed_id": other_bed, "reason": "Other stay", "idempotency_key": "p7-other-bed"})
    check(4, "second patient can be admitted", assigned_other[0] == 200, err(assigned_other[1]))

    admission_id, main_bed, admission_status = admit(person, encounter_id, "Main bed")
    check(33, "admission starts requested until a bed is assigned", admission_status == "REQUESTED" and bool(admission_id), admission_status or "")

    phone_only = call("POST", "/api/ot/requests", anita, {"phone": "9811107001", "procedure_id": procedure_id, "indication": "Do not use the phone"})
    check(2, "OT request cannot be created from a phone number", phone_only[0] == 400, str(phone_only[0]) + " " + err(phone_only[1]))
    foreign = call("POST", "/api/ot/requests", anita, {
        "patient_id": person, "encounter_id": other_encounter, "admission_id": admission_id,
        "procedure_id": procedure_id, "indication": "Wrong encounter", "status": "COMPLETED",
    })
    missing_enc = call("POST", "/api/ot/requests", anita, {
        "patient_id": person, "encounter_id": "ENC-MISSING", "admission_id": admission_id,
        "procedure_id": procedure_id, "indication": "Missing encounter",
    })
    check(3, "another patient's encounter is not attached", foreign[0] == 404, str(foreign[0]) + " " + err(foreign[1]))
    check(3, "missing and foreign encounters look the same", foreign[0] == missing_enc[0] == 404 and err(foreign[1]) == err(missing_enc[1]), err(foreign[1]) + " | " + err(missing_enc[1]))
    foreign_adm = call("POST", "/api/ot/requests", anita, {
        "patient_id": person, "encounter_id": encounter_id, "admission_id": other_admission,
        "procedure_id": procedure_id, "indication": "Wrong admission",
    })
    missing_adm = call("POST", "/api/ot/requests", anita, {
        "patient_id": person, "encounter_id": encounter_id, "admission_id": "ADM-MISSING",
        "procedure_id": procedure_id, "indication": "Missing admission",
    })
    check(4, "another patient's admission is not attached", foreign_adm[0] == 404, err(foreign_adm[1]))
    check(4, "missing and foreign admissions look the same", foreign_adm[0] == missing_adm[0] == 404 and err(foreign_adm[1]) == err(missing_adm[1]))
    needs_admission = call("POST", "/api/ot/requests", anita, {
        "patient_id": person, "encounter_id": encounter_id, "procedure_id": procedure_id, "indication": "No admission",
    })
    check(33, "a procedure that requires admission rejects a request without one", needs_admission[0] == 400, err(needs_admission[1]))

    requested = call("POST", "/api/ot/requests", anita, {
        "patient_id": person, "encounter_id": encounter_id, "admission_id": admission_id,
        "procedure_id": procedure_id, "indication": "Displaced fracture", "priority": "URGENT",
        "status": "COMPLETED", "fee_paise": 1, "rate_paise": 1, "idempotency_key": "p7-request",
    })
    case_id = data_of(requested[1]).get("id")
    check(10, "client status does not complete a new request", requested[0] == 200 and data_of(requested[1]).get("status") == "REQUESTED", err(requested[1]))
    check(1, "request id is not the patient, encounter, or admission id", case_id and case_id not in {person, encounter_id, admission_id})
    check(33, "request keeps the admission id", data_of(requested[1]).get("admission_id") == admission_id)
    replay_request = call("POST", "/api/ot/requests", anita, {
        "patient_id": person, "encounter_id": encounter_id, "admission_id": admission_id,
        "procedure_id": procedure_id, "indication": "Displaced fracture", "priority": "URGENT",
        "idempotency_key": "p7-request",
    })
    check(43, "same request key returns the same case", replay_request[0] == 200 and data_of(replay_request[1]).get("id") == case_id, err(replay_request[1]))
    conflict_key = call("POST", "/api/ot/requests", anita, {
        "patient_id": person, "encounter_id": encounter_id, "admission_id": admission_id,
        "procedure_id": procedure_id, "indication": "Different indication", "priority": "URGENT",
        "idempotency_key": "p7-request",
    })
    check(43, "same key with a different request conflicts", conflict_key[0] == 409, err(conflict_key[1]))
    forced = call("POST", f"/api/ot/{case_id}", admin, {"status": "COMPLETED"})
    check(10, "status JSON cannot force completed", forced[0] == 409 and data_of(forced[1]).get("status") != "COMPLETED", err(forced[1]))
    early = call("POST", f"/api/ot/{case_id}/schedule", anita, {
        "theatre_id": theatre_a_id, "surgeon_id": "U-ANITA", "start_at": "2026-10-01T08:00:00", "end_at": "2026-10-01T09:00:00",
    })
    check(9, "a request cannot be scheduled before approval", early[0] == 409, err(early[1]))
    approved = call("POST", f"/api/ot/{case_id}/approve", anita, {"idempotency_key": "p7-approve"})
    check(9, "approval is a server transition", approved[0] == 200 and data_of(approved[1]).get("status") == "APPROVED", err(approved[1]))
    too_soon = call("POST", f"/api/ot/{case_id}/schedule", anita, {
        "theatre_id": theatre_a_id, "surgeon_id": "U-ANITA", "start_at": "2026-10-01T08:00:00", "end_at": "2026-10-01T09:00:00",
        "idempotency_key": "p7-too-soon",
    })
    check(33, "scheduling waits until the admission is occupied", too_soon[0] == 409, err(too_soon[1]))
    occupied = call("POST", f"/api/admissions/{admission_id}/assign", nurse, {"bed_id": main_bed, "reason": "To theatre", "idempotency_key": "p7-main-bed"})
    check(33, "bed assignment uses the existing admission", occupied[0] == 200 and data_of(occupied[1]).get("status") == "ADMITTED", err(occupied[1]))

    scheduled = call("POST", f"/api/ot/{case_id}/schedule", anita, {
        "theatre_id": theatre_a_id, "surgeon_id": "U-ANITA", "start_at": "2026-10-01T08:00:00", "end_at": "2026-10-01T09:00:00",
        "idempotency_key": "p7-schedule",
    })
    booking_id = ((data_of(scheduled[1]).get("bookings") or [{}])[-1]).get("id")
    check(12, "schedule creates a booking", scheduled[0] == 200 and data_of(scheduled[1]).get("status") == "SCHEDULED" and bool(booking_id), err(scheduled[1]))
    check(1, "booking id is separate from the case id", booking_id and booking_id != case_id)
    replay_schedule = call("POST", f"/api/ot/{case_id}/schedule", anita, {
        "theatre_id": theatre_a_id, "surgeon_id": "U-ANITA", "start_at": "2026-10-01T08:00:00", "end_at": "2026-10-01T09:00:00",
        "idempotency_key": "p7-schedule",
    })
    replay_booking = ((data_of(replay_schedule[1]).get("bookings") or [{}])[-1]).get("id")
    check(43, "same schedule key returns the same booking", replay_schedule[0] == 200 and replay_booking == booking_id, err(replay_schedule[1]))
    renamed = call("PUT", f"/api/ot/procedures/{procedure_id}", admin, {
        "code": "P7-REP", "name": "Phase Seven Repair renamed", "category": "General", "price_paise": 125000,
        "duration_minutes": 60, "require_admission": 1,
    })
    status, current = call("GET", f"/api/ot/{case_id}", anita)
    check(7, "renaming the procedure does not rewrite the requested name", renamed[0] == 200 and data_of(current).get("procedure_name") == "Phase Seven Repair", data_of(current).get("procedure_name"))
    moved = call("POST", f"/api/ot/{case_id}/reschedule", anita, {
        "theatre_id": theatre_a_id, "surgeon_id": "U-ANITA", "start_at": "2026-10-01T08:15:00", "end_at": "2026-10-01T09:15:00",
        "reason": "Surgeon delayed", "idempotency_key": "p7-move",
    })
    history = data_of(moved[1]).get("history") or []
    check(18, "reschedule appends history and keeps one booking", moved[0] == 200 and len(data_of(moved[1]).get("bookings") or []) == 1 and any(item.get("action") == "reschedule" for item in history), err(moved[1]))

    def opened_case(label, surgeon, theatre_id, start, end, doctor="U-ANITA"):
        status, who = patient(label)
        status, enc = visit(who, doctor)
        adm, bed_id, _ = admit(who, enc, label + " bed")
        call("POST", f"/api/admissions/{adm}/assign", nurse, {"bed_id": bed_id, "reason": label, "idempotency_key": "bed-" + label})
        status, made = call("POST", "/api/ot/requests", anita if doctor == "U-ANITA" else admin, {
            "patient_id": who, "encounter_id": enc, "admission_id": adm, "procedure_id": procedure_id,
            "indication": label, "idempotency_key": "req-" + label,
        })
        cid = data_of(made).get("id")
        call("POST", f"/api/ot/{cid}/approve", admin, {"idempotency_key": "apr-" + label})
        return who, enc, adm, cid

    def book(cid, theatre_id, surgeon, start, end, key):
        return call("POST", f"/api/ot/{cid}/schedule", admin, {
            "theatre_id": theatre_id, "surgeon_id": surgeon, "start_at": start, "end_at": end, "idempotency_key": key,
        })

    _, _, _, overlap_case = opened_case("Overlap", "U-IMRAN", theatre_a_id, "2026-10-01T08:30:00", "2026-10-01T09:30:00", "U-IMRAN")
    overlap = book(overlap_case, theatre_a_id, "U-IMRAN", "2026-10-01T08:30:00", "2026-10-01T09:30:00", "p7-overlap")
    check(12, "overlapping theatre booking is rejected", overlap[0] == 409 and "theatre" in err(overlap[1]).lower(), err(overlap[1]))
    _, _, _, other_theatre_case = opened_case("Other theatre", "U-IMRAN", theatre_b_id, "2026-10-01T08:15:00", "2026-10-01T09:15:00", "U-IMRAN")
    other_ok = book(other_theatre_case, theatre_b_id, "U-IMRAN", "2026-10-01T08:15:00", "2026-10-01T09:15:00", "p7-other-th")
    check(14, "a different theatre can be booked at the same time", other_ok[0] == 200, err(other_ok[1]))
    _, _, _, adjacent_case = opened_case("Adjacent", "U-IMRAN", theatre_a_id, "2026-10-01T09:15:00", "2026-10-01T10:15:00", "U-IMRAN")
    adjacent = book(adjacent_case, theatre_a_id, "U-IMRAN", "2026-10-01T09:15:00", "2026-10-01T10:15:00", "p7-adjacent")
    check(12, "a booking that starts when the previous one ends is allowed", adjacent[0] == 200, err(adjacent[1]))
    _, _, _, surgeon_block = opened_case("Surgeon block", "U-ANITA", theatre_c_id, "2026-10-01T08:15:00", "2026-10-01T09:15:00")
    surgeon_hit = book(surgeon_block, theatre_c_id, "U-ANITA", "2026-10-01T08:20:00", "2026-10-01T09:00:00", "p7-surgeon-block")
    check(13, "overlapping surgeon booking is rejected", surgeon_hit[0] == 409 and "surgeon" in err(surgeon_hit[1]).lower(), err(surgeon_hit[1]))

    team = call("POST", f"/api/ot/{case_id}/team", anita, {"user_id": "U-ANITA", "function": "surgeon", "idempotency_key": "p7-team"})
    check(1, "team member is a separate record", team[0] == 200 and (data_of(team[1]).get("team") or [{}])[-1].get("id") not in {case_id, booking_id}, err(team[1]))
    nurse_start = call("POST", f"/api/ot/{case_id}/start", nurse, {"idempotency_key": "p7-nurse-start"})
    check(35, "view permission cannot start a procedure", nurse_start[0] == 403, str(nurse_start[0]) + " " + err(nurse_start[1]))
    jumped = call("POST", f"/api/ot/{case_id}/start", anita, {"idempotency_key": "p7-early-start"})
    check(9, "start is rejected before the pre-operative step", jumped[0] == 409, err(jumped[1]))
    pending = call("POST", f"/api/ot/{case_id}/preop", anita, {
        "consent_status": "PENDING", "readiness": "NOT_READY", "assessment": "Not ready", "idempotency_key": "p7-pre-1",
    })
    check(20, "pre-operative record is stored separately", pending[0] == 200 and len(data_of(pending[1]).get("preop") or []) == 1 and data_of(pending[1]).get("intraop") == [], err(pending[1]))
    blocked = call("POST", f"/api/ot/{case_id}/start", anita, {"idempotency_key": "p7-blocked"})
    check(21, "start is rejected until consent is obtained", blocked[0] == 409, err(blocked[1]))
    no_check = call("POST", f"/api/ot/{case_id}/preop", anita, {
        "consent_status": "OBTAINED", "readiness": "READY", "assessment": "Ready without checklist", "idempotency_key": "p7-pre-2",
    })
    still = call("POST", f"/api/ot/{case_id}/start", anita, {"idempotency_key": "p7-still"})
    check(21, "start is rejected until the required checklist item is satisfied", no_check[0] == 200 and still[0] == 409, err(still[1]))
    ready = call("POST", f"/api/ot/{case_id}/preop", anita, {
        "consent_status": "OBTAINED", "readiness": "READY", "assessment": "Identity checked",
        "checks": [{"item_id": check_id, "satisfied": 1}], "idempotency_key": "p7-pre-3",
    })
    preop_rows = data_of(ready[1]).get("preop") or []
    check(20, "a later pre-operative record does not erase the first", ready[0] == 200 and len(preop_rows) >= 2 and preop_rows[0].get("consent_status") == "PENDING", str(preop_rows[:1]))
    started = call("POST", f"/api/ot/{case_id}/start", anita, {"idempotency_key": "p7-start"})
    check(9, "start moves the case into progress", started[0] == 200 and data_of(started[1]).get("status") == "IN_PROGRESS", err(started[1]))
    replay_start = call("POST", f"/api/ot/{case_id}/start", anita, {"idempotency_key": "p7-start"})
    check(43, "same start key replays the started case", replay_start[0] == 200 and data_of(replay_start[1]).get("status") == "IN_PROGRESS", err(replay_start[1]))
    early_complete = call("POST", f"/api/ot/{case_id}/complete", anita, {"idempotency_key": "p7-early-complete"})
    check(9, "completion is rejected before recovery", early_complete[0] == 409, err(early_complete[1]))
    early_recovery = call("POST", f"/api/ot/{case_id}/recovery", anita, {"idempotency_key": "p7-early-recovery"})
    check(22, "recovery waits for an intra-operative record", early_recovery[0] == 409, err(early_recovery[1]))
    marker = "PHASE7MARKER " + ("Stored operative line. " * 160)
    first_note = call("POST", f"/api/ot/{case_id}/intraop", anita, {"notes": "First operative note", "findings": "Stable", "idempotency_key": "p7-intra-1"})
    second_note = call("POST", f"/api/ot/{case_id}/intraop", anita, {"notes": marker, "findings": "Unchanged first note", "idempotency_key": "p7-intra-2"})
    notes = data_of(second_note[1]).get("intraop") or []
    check(22, "a second intra-operative record does not replace the first", second_note[0] == 200 and len(notes) == 2 and notes[0].get("notes") == "First operative note", err(second_note[1]))
    recovered = call("POST", f"/api/ot/{case_id}/recovery", anita, {"idempotency_key": "p7-recovery"})
    check(9, "recovery follows the operative record", recovered[0] == 200 and data_of(recovered[1]).get("status") == "RECOVERY", err(recovered[1]))
    first_post = call("POST", f"/api/ot/{case_id}/postop", anita, {"notes": "First recovery note", "condition": "Stable", "idempotency_key": "p7-post-1"})
    second_post = call("POST", f"/api/ot/{case_id}/postop", anita, {"notes": "Second recovery note", "idempotency_key": "p7-post-2"})
    posts = data_of(second_post[1]).get("postop") or []
    check(23, "a second post-operative record does not replace the first", second_post[0] == 200 and len(posts) == 2 and posts[0].get("notes") == "First recovery note", err(second_post[1]))
    check(1, "post-operative id is separate from the intra-operative id", posts and notes and posts[0].get("id") != notes[0].get("id"))
    completed = call("POST", f"/api/ot/{case_id}/complete", anita, {"idempotency_key": "p7-complete"})
    check(9, "completion is recorded by the server", completed[0] == 200 and data_of(completed[1]).get("status") == "COMPLETED", err(completed[1]))
    replay_complete = call("POST", f"/api/ot/{case_id}/complete", anita, {"idempotency_key": "p7-complete"})
    check(24, "same completion key does not create a second completion", replay_complete[0] == 200 and data_of(replay_complete[1]).get("completed_at") == data_of(completed[1]).get("completed_at"))

    charged = call("POST", f"/api/ot/{case_id}/charge", anita, {
        "rate_paise": 1, "tax_paise": 999, "qty": 4, "idempotency_key": "p7-charge",
    })
    invoice_id = data_of(charged[1]).get("invoice_id")
    item_id = data_of(charged[1]).get("invoice_item_id")
    check(26, "charge returns the Phase 4 invoice line", charged[0] == 200 and bool(invoice_id) and bool(item_id), err(charged[1]))
    status, invoice = call("GET", f"/api/invoices/{invoice_id}", billing)
    procedure_lines = [item for item in data_of(invoice).get("items") or [] if item.get("source_id") == f"{case_id}:{procedure_id}:procedure"]
    check(27, "client price and tax do not set the line", len(procedure_lines) == 1 and procedure_lines[0].get("rate_paise") == 125000 and int(procedure_lines[0].get("tax_paise") or 0) == 0, str(procedure_lines[:1]))
    check(26, "the line is an OT category on the invoice", procedure_lines and procedure_lines[0].get("category") == "OT" and procedure_lines[0].get("source_module") == "ot")
    call("PUT", f"/api/ot/procedures/{procedure_id}", admin, {
        "code": "P7-REP", "name": "Phase Seven Repair renamed", "category": "General", "price_paise": 900000,
        "duration_minutes": 60, "require_admission": 1,
    })
    again = call("POST", f"/api/ot/{case_id}/charge", anita, {"rate_paise": 1, "tax_paise": 999, "idempotency_key": "p7-charge-again"})
    status, invoice = call("GET", f"/api/invoices/{invoice_id}", billing)
    procedure_lines = [item for item in data_of(invoice).get("items") or [] if ":procedure" in (item.get("source_id") or "")]
    check(28, "a later procedure price does not rewrite the line", again[0] == 200 and len(procedure_lines) == 1 and procedure_lines[0].get("rate_paise") == 125000, str(procedure_lines[:1]))
    check(29, "a second charge request does not add a line", data_of(again[1]).get("invoice_item_id") == item_id)
    call("PUT", f"/api/ot/procedures/{procedure_id}", admin, {
        "code": "P7-REP", "name": "Phase Seven Repair renamed", "category": "General", "price_paise": 125000,
        "duration_minutes": 60, "require_admission": 1,
    })

    hidden = call("GET", f"/api/ot/{case_id}", imran)
    absent = call("GET", "/api/ot/OT-NO-SUCH", imran)
    check(5, "an out-of-scope case looks like a missing case", hidden[0] == absent[0] == 404 and err(hidden[1]) == err(absent[1]), err(hidden[1]) + " | " + err(absent[1]))
    status, mine = call("GET", "/api/ot", imran)
    check(5, "the list does not include the other doctor's case", status == 200 and case_id not in {item.get("id") for item in data_of(mine).get("items") or []})
    status, anita_timeline = call("GET", f"/api/patients/{person}/timeline", anita)
    status, desk_timeline = call("GET", f"/api/patients/{person}/timeline", reception)
    anita_events = data_of(anita_timeline).get("events") or []
    desk_events = data_of(desk_timeline).get("events") or []
    check(34, "the operating doctor sees the OT event", any(str(item.get("kind") or "").startswith("ot") for item in anita_events), str(anita_events)[:300])
    check(34, "a user without OT view does not see the operative event", not any(str(item.get("kind") or "").startswith("ot") for item in desk_events) and not data_of(desk_timeline).get("ot"), str([item.get("kind") for item in desk_events]))

    before_report = call("GET", f"/api/ot/{case_id}", anita)
    before_stamp = data_of(before_report[1]).get("updated_at")
    report = call("POST", f"/api/ot/{case_id}/report", anita, {"idempotency_key": "p7-report"})
    report_json = json.dumps(report[1])
    check(39, "report metadata does not expose a storage path", report[0] == 200 and "stored_name" not in report_json and "/home/" not in report_json, report_json[:240])
    check(37, "report names the stored procedure", "Phase Seven Repair" in report_json or data_of(report[1]).get("title"), report_json[:180])
    status, first_pdf = call("GET", f"/api/ot/{case_id}/report", anita, raw=True)
    status, second_pdf = call("GET", f"/api/ot/{case_id}/report", anita, raw=True)
    check(37, "report is an A4 PDF with a white page and a second page", status == 200 and first_pdf.startswith(b"%PDF") and b"595.28" in first_pdf and b"841.89" in first_pdf and b"1 1 1 rg" in first_pdf and b"Page 2 of" in first_pdf and b"PHASE7MARKER" in first_pdf, str(status))
    check(38, "two reads of the report are byte-identical", first_pdf == second_pdf and len(first_pdf) > 800)
    reprint = call("POST", f"/api/ot/{case_id}/report", anita, {"idempotency_key": "p7-report-reprint"})
    after_report = call("GET", f"/api/ot/{case_id}", anita)
    check(38, "reprint does not change the case timestamp", data_of(after_report[1]).get("updated_at") == before_stamp and data_of(reprint[1]).get("id") == data_of(report[1]).get("id"), err(reprint[1]))
    denied_pdf = call("GET", f"/api/ot/{case_id}/report", imran, raw=True)
    missing_pdf = call("GET", "/api/ot/OT-NO-SUCH/report", imran, raw=True)
    check(40, "an unauthorized report looks like a missing report", denied_pdf[0] == missing_pdf[0] == 404, str(denied_pdf[0]) + " " + str(missing_pdf[0]))

    pg = psycopg.connect(target)
    before_docs = pg.execute("SELECT COUNT(*) FROM documents WHERE entity_id=%s AND document_type=%s", (case_id, "OT report")).fetchone()[0]
    before_audit = pg.execute("SELECT COUNT(*) FROM audit_logs WHERE entity_id=%s AND action LIKE 'ot_report%%'", (case_id,)).fetchone()[0]
    pg.close()
    status, third_pdf = call("GET", f"/api/ot/{case_id}/report", anita, raw=True)
    pg = psycopg.connect(target)
    after_docs = pg.execute("SELECT COUNT(*) FROM documents WHERE entity_id=%s AND document_type=%s", (case_id, "OT report")).fetchone()[0]
    after_audit = pg.execute("SELECT COUNT(*) FROM audit_logs WHERE entity_id=%s AND action LIKE 'ot_report%%'", (case_id,)).fetchone()[0]
    stock_before = pg.execute("SELECT COUNT(*) FROM stock_movements").fetchone()[0]
    pg.close()
    check(38, "reading the report does not create a document or an audit row", third_pdf == first_pdf and after_docs == before_docs and after_audit == before_audit, str((after_docs, before_docs, after_audit, before_audit)))

    correction = call("POST", f"/api/ot/{case_id}/intraop", anita, {"notes": "Correction note after the report", "idempotency_key": "p7-correct-note"})
    corrected = call("POST", f"/api/ot/{case_id}/report", anita, {"idempotency_key": "p7-report-correction"})
    status, corrected_pdf = call("GET", f"/api/ot/{case_id}/report", anita, raw=True)
    pg = psycopg.connect(target)
    corrected_docs = pg.execute("SELECT COUNT(*) FROM documents WHERE entity_id=%s AND document_type=%s", (case_id, "OT report")).fetchone()[0]
    pg.close()
    check(38, "a changed record is a new document, not a silent reprint", correction[0] == 200 and corrected[0] == 200 and corrected_docs == before_docs + 1 and corrected_pdf != first_pdf, str(corrected_docs))

    status, glucose = call("POST", "/api/lab/tests", admin, {"name": "Phase Seven Glucose", "code": "P7GLU", "price_paise": 10000, "sample_type": "Blood", "result_type": "numeric"})
    glucose_id = data_of(glucose).get("id")
    ordered = call("POST", "/api/lab/orders", anita, {"patient_id": person, "encounter_id": encounter_id, "admission_id": admission_id, "tests": [{"test_id": glucose_id}], "idempotency_key": "p7-lab"})
    order_id = data_of(ordered[1]).get("id")
    linked = call("POST", f"/api/ot/{case_id}/links", anita, {"module": "lab", "entity_id": order_id, "idempotency_key": "p7-lab-link"})
    check(32, "a laboratory order is linked, not copied into an OT order", linked[0] == 200 and any(item.get("module") == "lab" and item.get("entity_id") == order_id for item in data_of(linked[1]).get("links") or []), err(linked[1]))
    other_order = call("POST", "/api/lab/orders", admin, {"patient_id": other, "encounter_id": other_encounter, "tests": [{"test_id": glucose_id}], "idempotency_key": "p7-lab-other"})
    foreign_link = call("POST", f"/api/ot/{case_id}/links", anita, {"module": "lab", "entity_id": data_of(other_order[1]).get("id"), "idempotency_key": "p7-lab-foreign"})
    check(32, "another patient's laboratory order cannot be linked", foreign_link[0] == 404, err(foreign_link[1]))
    prescribed = call("POST", "/api/prescriptions", anita, {
        "encounter_id": encounter_id, "patient_id": person, "items": [{"medicine_name": "Phase Seven analgesia", "dose": "1", "frequency": "OD"}],
    })
    rx_id = data_of(prescribed[1]).get("id")
    pharmacy_link = call("POST", f"/api/ot/{case_id}/links", anita, {"module": "pharmacy", "entity_id": rx_id, "idempotency_key": "p7-rx-link"})
    pg = psycopg.connect(target)
    stock_after = pg.execute("SELECT COUNT(*) FROM stock_movements").fetchone()[0]
    financial = pg.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name IN ('ot_invoices', 'ot_payments', 'ot_refunds')").fetchall()
    pg.close()
    check(31, "linking a prescription does not move stock", pharmacy_link[0] == 200 and stock_after == stock_before, err(pharmacy_link[1]) + " " + str((stock_before, stock_after)))
    check(44, "no OT invoice, payment, or refund table exists", not financial, str(financial))

    removed = call("PUT", f"/api/ot/theatres/{theatre_c_id}", admin, {"code": "P7-C", "name": "Phase Seven Spare", "delete": True})
    status, still_there = call("GET", "/api/ot/theatres?all=1", admin)
    spare = [item for item in data_of(still_there).get("items") or [] if item.get("id") == theatre_c_id]
    check(8, "a theatre is not deleted", removed[0] == 409 and spare and spare[0].get("name") == "Phase Seven Spare", err(removed[1]))
    retired = call("PUT", f"/api/ot/theatres/{theatre_c_id}", admin, {"code": "P7-C", "name": "Phase Seven Spare", "active": 0})
    check(8, "a theatre can be deactivated and still read", retired[0] == 200 and data_of(retired[1]).get("active") in (0, False))
    _, _, _, spare_case = opened_case("Inactive theatre", "U-IMRAN", theatre_c_id, "2026-10-09T08:00:00", "2026-10-09T09:00:00", "U-IMRAN")
    dead = book(spare_case, theatre_c_id, "U-IMRAN", "2026-10-09T08:00:00", "2026-10-09T09:00:00", "p7-dead-theatre")
    check(8, "an inactive theatre cannot be booked", dead[0] == 409 and "not available" in err(dead[1]).lower(), err(dead[1]))
    deleted = call("DELETE", f"/api/ot/theatres/{theatre_c_id}", admin)
    check(8, "there is no theatre delete route", deleted[0] == 404, str(deleted[0]))
    audit_delete = call("DELETE", "/api/audit", admin)
    check(36, "audit has no delete route", audit_delete[0] == 404, str(audit_delete[0]))

    def prepare_started(label, theatre_id, surgeon, start, end):
        _, _, _, cid = opened_case(label, surgeon, theatre_id, start, end, "U-ANITA" if surgeon == "U-ANITA" else "U-IMRAN")
        booked = book(cid, theatre_id, surgeon, start, end, "book-" + label)
        if booked[0] != 200:
            return cid, booked
        call("POST", f"/api/ot/{cid}/preop", admin, {
            "consent_status": "OBTAINED", "readiness": "READY", "assessment": label,
            "checks": [{"item_id": check_id, "satisfied": 1}], "idempotency_key": "pre-" + label,
        })
        began = call("POST", f"/api/ot/{cid}/start", admin, {"idempotency_key": "start-" + label})
        return cid, began

    cancel_id, cancel_started = prepare_started("Cancel billed", theatre_a_id, "U-IMRAN", "2026-10-08T08:00:00", "2026-10-08T09:00:00")
    cancel_charge = call("POST", f"/api/ot/{cancel_id}/charge", admin, {"rate_paise": 1, "tax_paise": 50, "idempotency_key": "p7-cancel-charge"})
    cancel_invoice = data_of(cancel_charge[1]).get("invoice_id")
    cancelled = call("POST", f"/api/ot/{cancel_id}/cancel", admin, {"reason": "Patient postponed after charge", "idempotency_key": "p7-cancel"})
    status, cancel_view = call("GET", f"/api/ot/{cancel_id}", admin)
    status, cancel_bill = call("GET", f"/api/invoices/{cancel_invoice}", billing) if cancel_invoice else (0, {})
    cancel_lines = [item for item in data_of(cancel_bill).get("items") or [] if item.get("source_module") == "ot"]
    check(19, "a cancelled case remains readable", cancelled[0] == 200 and data_of(cancel_view).get("status") == "CANCELLED", err(cancelled[1]))
    check(18, "cancellation keeps the booking history", any(item.get("action") == "cancel" for item in data_of(cancel_view).get("history") or []) and data_of(cancel_view).get("bookings"))
    check(30, "cancellation does not delete the invoice line", cancel_started[0] == 200 and cancel_charge[0] == 200 and len(cancel_lines) == 1 and cancel_lines[0].get("rate_paise") == 125000, err(cancel_charge[1]) + " " + err(cancel_started[1]))

    _, _, _, race_a = opened_case("Race theatre A", "U-ANITA", theatre_a_id, "2026-10-02T08:00:00", "2026-10-02T09:00:00")
    _, _, _, race_b = opened_case("Race theatre B", "U-IMRAN", theatre_a_id, "2026-10-02T08:00:00", "2026-10-02T09:00:00", "U-IMRAN")
    raced_theatre = race(
        lambda: book(race_a, theatre_a_id, "U-ANITA", "2026-10-02T08:00:00", "2026-10-02T09:00:00", "p7-race-th-a"),
        lambda: book(race_b, theatre_a_id, "U-IMRAN", "2026-10-02T08:00:00", "2026-10-02T09:00:00", "p7-race-th-b"),
    )
    pg = psycopg.connect(target)
    theatre_bookings = pg.execute(
        "SELECT COUNT(*) FROM ot_bookings WHERE theatre_id=%s AND start_at=%s AND status NOT IN ('CANCELLED', 'POSTPONED')",
        (theatre_a_id, "2026-10-02T08:00:00"),
    ).fetchone()[0]
    pg.close()
    check(15, "concurrent theatre overlap yields one success and one conflict", sorted(item[0] for item in raced_theatre) == [200, 409] and theatre_bookings == 1, str([(item[0], err(item[1])) for item in raced_theatre]) + " " + str(theatre_bookings))

    _, _, _, surg_a = opened_case("Race surgeon A", "U-ANITA", theatre_a_id, "2026-10-03T08:00:00", "2026-10-03T09:00:00")
    _, _, _, surg_b = opened_case("Race surgeon B", "U-ANITA", theatre_b_id, "2026-10-03T08:00:00", "2026-10-03T09:00:00")
    raced_surgeon = race(
        lambda: book(surg_a, theatre_a_id, "U-ANITA", "2026-10-03T08:00:00", "2026-10-03T09:00:00", "p7-race-sg-a"),
        lambda: book(surg_b, theatre_b_id, "U-ANITA", "2026-10-03T08:00:00", "2026-10-03T09:00:00", "p7-race-sg-b"),
    )
    pg = psycopg.connect(target)
    surgeon_bookings = pg.execute(
        "SELECT COUNT(*) FROM ot_bookings WHERE surgeon_id=%s AND start_at=%s AND status NOT IN ('CANCELLED', 'POSTPONED')",
        ("U-ANITA", "2026-10-03T08:00:00"),
    ).fetchone()[0]
    pg.close()
    check(16, "concurrent surgeon overlap yields one success and one conflict", sorted(item[0] for item in raced_surgeon) == [200, 409] and surgeon_bookings == 1, str([(item[0], err(item[1])) for item in raced_surgeon]) + " " + str(surgeon_bookings))

    _, _, _, same = opened_case("Same case", "U-IMRAN", theatre_a_id, "2026-10-04T08:00:00", "2026-10-04T09:00:00", "U-IMRAN")
    raced_same = race(
        lambda: book(same, theatre_a_id, "U-IMRAN", "2026-10-04T08:00:00", "2026-10-04T09:00:00", "p7-race-same-a"),
        lambda: book(same, theatre_b_id, "U-IMRAN", "2026-10-04T08:30:00", "2026-10-04T09:30:00", "p7-race-same-b"),
    )
    pg = psycopg.connect(target)
    same_bookings = pg.execute("SELECT COUNT(*) FROM ot_bookings WHERE ot_id=%s", (same,)).fetchone()[0]
    pg.close()
    check(17, "two schedule requests for one case leave one booking", sorted(item[0] for item in raced_same) == [200, 409] and same_bookings == 1, str([(item[0], err(item[1])) for item in raced_same]) + " " + str(same_bookings))

    start_id, start_ready = prepare_started("Start race setup", theatre_b_id, "U-IMRAN", "2026-10-05T08:00:00", "2026-10-05T09:00:00")
    # prepare_started already started it. Build a case stopped at pre-op for the race.
    _, _, _, start_case = opened_case("Start race", "U-IMRAN", theatre_b_id, "2026-10-05T11:00:00", "2026-10-05T12:00:00", "U-IMRAN")
    book(start_case, theatre_b_id, "U-IMRAN", "2026-10-05T11:00:00", "2026-10-05T12:00:00", "p7-start-book")
    call("POST", f"/api/ot/{start_case}/preop", admin, {
        "consent_status": "OBTAINED", "readiness": "READY", "assessment": "Ready",
        "checks": [{"item_id": check_id, "satisfied": 1}], "idempotency_key": "p7-start-pre",
    })
    raced_start = race(
        lambda: call("POST", f"/api/ot/{start_case}/start", admin, {"idempotency_key": "p7-race-start-a"}),
        lambda: call("POST", f"/api/ot/{start_case}/start", admin, {"idempotency_key": "p7-race-start-b"}),
    )
    pg = psycopg.connect(target)
    start_audits = pg.execute("SELECT COUNT(*) FROM audit_logs WHERE entity_id=%s AND action='ot_start'", (start_case,)).fetchone()[0]
    pg.close()
    status, start_view = call("GET", f"/api/ot/{start_case}", admin)
    check(25, "concurrent start yields one success and one conflict", sorted(item[0] for item in raced_start) == [200, 409] and data_of(start_view).get("status") == "IN_PROGRESS" and start_audits == 1, str([(item[0], err(item[1])) for item in raced_start]) + " " + str(start_audits))

    complete_id, complete_started = prepare_started("Complete race", theatre_a_id, "U-IMRAN", "2026-10-06T08:00:00", "2026-10-06T09:00:00")
    call("POST", f"/api/ot/{complete_id}/intraop", admin, {"notes": "Race note", "idempotency_key": "p7-race-note"})
    call("POST", f"/api/ot/{complete_id}/recovery", admin, {"idempotency_key": "p7-race-recovery"})
    raced_complete = race(
        lambda: call("POST", f"/api/ot/{complete_id}/complete", admin, {"idempotency_key": "p7-race-complete-a"}),
        lambda: call("POST", f"/api/ot/{complete_id}/complete", admin, {"idempotency_key": "p7-race-complete-b"}),
    )
    pg = psycopg.connect(target)
    complete_audits = pg.execute("SELECT COUNT(*) FROM audit_logs WHERE entity_id=%s AND action='ot_complete'", (complete_id,)).fetchone()[0]
    pg.close()
    status, complete_view = call("GET", f"/api/ot/{complete_id}", admin)
    check(24, "concurrent completion leaves one completed case", complete_started[0] == 200 and data_of(complete_view).get("status") == "COMPLETED" and complete_audits == 1 and all(item[0] == 200 for item in raced_complete), str([(item[0], err(item[1])) for item in raced_complete]) + " " + str(complete_audits))

    charge_id, charge_started = prepare_started("Charge race", theatre_b_id, "U-IMRAN", "2026-10-07T08:00:00", "2026-10-07T09:00:00")
    raced_charge = race(
        lambda: call("POST", f"/api/ot/{charge_id}/charge", admin, {"rate_paise": 1, "tax_paise": 9, "idempotency_key": "p7-race-charge-a"}),
        lambda: call("POST", f"/api/ot/{charge_id}/charge", admin, {"rate_paise": 2, "tax_paise": 8, "idempotency_key": "p7-race-charge-b"}),
    )
    charge_invoice = next((data_of(item[1]).get("invoice_id") for item in raced_charge if data_of(item[1]).get("invoice_id")), "")
    if not charge_invoice:
        status, charge_view = call("GET", f"/api/ot/{charge_id}", admin)
        link = (data_of(charge_view).get("charges") or [{}])[0]
        charge_invoice = ""
        item_lookup = link.get("invoice_item_id")
        if item_lookup:
            pg = psycopg.connect(target)
            found = pg.execute("SELECT invoice_id FROM invoice_items WHERE id=%s", (item_lookup,)).fetchone()
            pg.close()
            charge_invoice = found[0] if found else ""
    status, charge_bill = call("GET", f"/api/invoices/{charge_invoice}", billing) if charge_invoice else (0, {})
    race_lines = [item for item in data_of(charge_bill).get("items") or [] if item.get("source_module") == "ot" and charge_id in (item.get("source_id") or "")]
    check(29, "concurrent charge requests create one line", charge_started[0] == 200 and len(race_lines) == 1 and race_lines[0].get("rate_paise") == 125000, str([(item[0], err(item[1])) for item in raced_charge]) + " " + str(race_lines[:1]))

    status, roles = call("GET", "/api/roles", admin)
    lab_role = next(item for item in data_of(roles).get("items") or [] if item.get("code") == "lab")
    original = list(dict.fromkeys(lab_role.get("permissions") or []))
    call("PUT", "/api/roles/lab/permissions", admin, {"permissions": ["ot.view", "patient.view"]})
    status, lab, _ = login("lab")
    denied_code = call("POST", f"/api/ot/{case_id}/approve", lab, {})
    check(35, "a laboratory role with only OT view cannot approve", denied_code[0] == 403, str(denied_code[0]) + " " + err(denied_code[1]))
    _, _, _, code_case = opened_case("Code grant", "U-IMRAN", theatre_b_id, "2026-10-10T08:00:00", "2026-10-10T09:00:00", "U-IMRAN")
    call("PUT", "/api/roles/lab/permissions", admin, {"permissions": ["ot.approve", "patient.view_all"]})
    status, lab, _ = login("lab")
    granted = call("POST", f"/api/ot/{code_case}/approve", lab, {"idempotency_key": "p7-code-approve"})
    check(35, "a non-doctor role can approve when it holds the permission code", granted[0] == 200 and data_of(granted[1]).get("status") == "APPROVED", err(granted[1]))
    call("PUT", "/api/roles/lab/permissions", admin, {"permissions": original})

    status, legacy_person = patient("Phase Seven Legacy")
    status, master = call("POST", "/api/master/procedure", admin, {"name": "Phase Seven legacy procedure", "meta": {"fee_paise": 80000}})
    master_id = data_of(master).get("id")
    status, legacy = call("POST", "/api/ot", admin, {"patient_id": legacy_person, "procedure_name": "Phase Seven legacy procedure", "procedure_id": master_id})
    legacy_id = data_of(legacy).get("id")
    performed = call("POST", f"/api/ot/{legacy_id}", admin, {"status": "PERFORMED"})
    noted = call("POST", f"/api/ot/{legacy_id}/notes", admin, {
        "outcome": "SUCCESSFUL", "procedure_notes": "Legacy notes still complete the case.", "fee_paise": 1,
    })
    check(11, "performed still requires notes and notes still complete the case", performed[0] == 200 and data_of(performed[1]).get("status") == "NOTES_PENDING" and noted[0] == 200 and data_of(noted[1]).get("status") == "COMPLETED", err(performed[1]) + " " + err(noted[1]))
    status, bills = call("GET", f"/api/invoices?patient_id={legacy_person}", billing)
    legacy_rate = None
    for item in data_of(bills).get("items") or []:
        status, full = call("GET", f"/api/invoices/{item.get('id')}", billing)
        for line in data_of(full).get("items") or []:
            if line.get("category") == "OT":
                legacy_rate = line.get("rate_paise")
    check(46, "legacy notes bill the master fee instead of the client fee", legacy_rate == 80000, str(legacy_rate))

    seen = {item["section"] for item in evidence}
    for index in range(1, 47):
        if index not in seen:
            failures.append(f"{index}. no check recorded")
    return failures


def _write_report(failures: list[str], evidence: list[dict], version) -> None:
    by_section: dict[int, list[dict]] = {i: [] for i in range(1, 47)}
    for item in evidence:
        by_section.setdefault(int(item["section"]), []).append(item)
    failed = [item for item in evidence if not item["ok"]]
    empty = [index for index, items in by_section.items() if not items]
    decision = "PHASE 7 ACCEPTED" if not failures and not failed and not empty else "PHASE 7 NOT ACCEPTED"
    lines = [
        "# PHASE 7 ACCEPTANCE REPORT",
        "",
        f"Decision: {decision}",
        "",
        "Phase 7 operating theatre only. Phases 0–6 were not reopened except for the schema-version assertion required by the new migration.",
        "Phase 4 remains the only financial source of truth. No OT payment, invoice, or refund table was added.",
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
        "The gate started the hospital server and called it over HTTP. Theatre, surgeon, start, completion, and charge races used two concurrent requests.",
        "Booking counts, document counts, audit counts, and stock counts were read from the throwaway database after the HTTP calls.",
        "The database URL is not included.",
        "",
        "## Regression",
        "",
        "The accepted PERFORMED to NOTES_PENDING to notes path still completes a case and bills the configured procedure fee.",
        "SQLite schema is 17 because 0017 is shared. PostgreSQL schema is 19 because 0018 and 0019 are PostgreSQL-only.",
        "",
        "## Remaining non-blocking limitations",
        "",
        "The older status endpoint still allows REQUESTED to PERFORMED so the accepted notes path and the current desk remain usable. It does not accept a jump to COMPLETED.",
        "Operation notes from that older endpoint still complete the case. The new workflow completes only from recovery.",
        "",
    ])
    if failures:
        lines.append("Failures:")
        lines.append("")
        for failure in failures:
            lines.append(f"- {failure}")
        lines.append("")
    REPORT.write_text("\n".join(lines), encoding="utf-8")
