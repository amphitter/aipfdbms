"""Phase 2: patient, visit, queue, and consultation over real HTTP."""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[2]


def test_phase2_http_workflow():
    url = (os.environ.get("AIPF_TEST_POSTGRES") or os.environ.get("AIPF_DATABASE_URL") or "").strip()
    if not url.startswith("postgres"):
        if os.environ.get("PHASE2_REQUIRE_POSTGRES") == "1":
            raise AssertionError("PostgreSQL URL is required for the Phase 2 workflow")
        print("skip phase2 http: PostgreSQL URL is not set")
        return
    failures = _run(url)
    assert failures == [], failures


def _run(admin_url: str) -> list[str]:
    import psycopg

    password = secrets.token_urlsafe(18)
    os.environ["AIPF_SEED_PASSWORD"] = password
    db_name = "aipf_phase2"
    admin = psycopg.connect(admin_url, autocommit=True)
    admin.execute(f"DROP DATABASE IF EXISTS {db_name}")
    admin.execute(f"CREATE DATABASE {db_name}")
    admin.close()
    target = admin_url.rsplit("/", 1)[0] + "/" + db_name
    previous = os.environ.get("AIPF_DATABASE_URL")
    os.environ["AIPF_DATABASE_URL"] = target
    port = 8795
    proc = None
    failures: list[str] = []
    try:
        from aipf import core
        from aipf.db import apply_migrations, connect
        from aipf.seed import seed

        conn = connect()
        assert conn.dialect == "postgres"
        assert apply_migrations(conn) >= 7
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
        if not _wait_ready(proc, port):
            failures.append("server did not start")
            return failures
        base = f"http://127.0.0.1:{port}"

        def check(name: str, cond: bool, detail: str = ""):
            if not cond:
                failures.append(name + (": " + detail if detail else ""))

        def call(method, path, token=None, body=None):
            data = None if body is None else json.dumps(body).encode()
            req = urllib.request.Request(base + path, data=data, method=method)
            if body is not None:
                req.add_header("Content-Type", "application/json")
            if token:
                req.add_header("Authorization", "Bearer " + token)
            try:
                with urllib.request.urlopen(req, timeout=30) as res:
                    raw = res.read()
                    ctype = res.headers.get("content-type") or ""
                    if "json" in ctype:
                        return res.status, json.loads(raw.decode())
                    return res.status, {"length": len(raw)}
            except urllib.error.HTTPError as exc:
                raw = exc.read()
                try:
                    payload = json.loads(raw.decode())
                except Exception:
                    payload = {"length": len(raw)}
                return exc.code, payload

        def login(username):
            status, payload = call("POST", "/api/auth/login", body={"username": username, "password": password})
            token = ((payload or {}).get("data") or {}).get("token")
            return status, token

        status, reception = login("reception")
        check("reception login", status == 200 and bool(reception), str(status))
        status, doctor = login("dr.anita")
        check("doctor login", status == 200 and bool(doctor), str(status))
        status, other = login("dr.imran")
        check("other doctor login", status == 200 and bool(other), str(status))
        status, admin = login("director")
        check("admin login", status == 200 and bool(admin), str(status))

        status, found = call("GET", "/api/patients?q=9811122334", reception)
        names = {item.get("name") for item in (found.get("data") or {}).get("items", [])}
        check("shared phone search lists the family", status == 200 and {"Rajesh Sharma", "Aarav Sharma"} <= names, str(names))

        status, blocked = call("POST", "/api/patients", reception, {
            "name": "Unconfirmed Sharma",
            "primary_phone": "9811122334",
            "gender": "Female",
            "age_at_registration": 3,
        })
        check("shared phone without confirmation is refused", status == 409 and (blocked.get("error") or {}).get("code") == "possible_match", str(status))
        check("match payload has no clinical note", "allergies" not in json.dumps((blocked.get("error") or {}).get("details") or {}))

        status, created = call("POST", "/api/patients", reception, {
            "name": "Meera Lal",
            "primary_phone": "9811122334",
            "gender": "Female",
            "age_at_registration": 31,
            "dob": "1995-04-02",
            "confirm_new": True,
        })
        meera = (created.get("data") or {})
        check("explicit new person on a shared phone", status == 200 and meera.get("id") and meera.get("id") != "P-000001", str(status))
        status, rajesh = call("GET", "/api/patients/P-000001", reception)
        check("existing patient was not overwritten", status == 200 and (rajesh.get("data") or {}).get("name") == "Rajesh Sharma")

        status, updated = call("PATCH", f"/api/patients/{meera.get('id')}", reception, {
            "name": "Meera Lal",
            "primary_phone": "9811122334",
            "gender": "Female",
            "address": "Shahpurpur",
        })
        check("patient id is stable on edit", status == 200 and (updated.get("data") or {}).get("id") == meera.get("id"), str(status))

        before = _count(target, "SELECT COUNT(*) FROM patients")
        before_enc = _count(target, "SELECT COUNT(*) FROM encounters")
        status, rolled = call("POST", "/api/visits", reception, {
            "name": "Rollback Person",
            "primary_phone": "9000001111",
            "gender": "Male",
            "age_at_registration": 40,
            "confirm_new": True,
            "opd_type_id": "NO-SUCH-TYPE",
            "doctor_id": "U-ANITA",
        })
        check("bad visit is rejected", status == 400, str(status) + " " + str((rolled.get("error") or {}).get("message")))
        check("failed visit created no patient", _count(target, "SELECT COUNT(*) FROM patients") == before)
        check("failed visit created no encounter", _count(target, "SELECT COUNT(*) FROM encounters") == before_enc)

        status, missing = call("POST", "/api/opd", reception, {"patient_id": "P-MISSING", "opd_type_id": "OTY-GEN", "doctor_id": "U-ANITA"})
        check("unknown patient is rejected", status == 404, str(status))

        status, types = call("POST", "/api/opd/types", admin, {"name": "Phase 2 desk", "fee_paise": 15000, "validity_days": 1})
        new_type = (types.get("data") or {}).get("id")
        check("opd type comes from master data", status == 200 and bool(new_type), str(status))
        status, listed = call("GET", "/api/opd/types", reception)
        check("new opd type is available to reception", any(item.get("id") == new_type for item in (listed.get("data") or {}).get("items", [])))

        phone = "900000" + secrets.token_hex(2)
        status, visit = call("POST", "/api/visits", reception, {
            "name": "Phase Two Patient",
            "primary_phone": phone,
            "gender": "Male",
            "age_at_registration": 44,
            "confirm_new": True,
            "opd_type_id": new_type,
            "doctor_id": "U-ANITA",
            "chief_complaint": "Sore throat",
            "queue": True,
        })
        encounter = (visit.get("data") or {}).get("encounter") or {}
        patient = (visit.get("data") or {}).get("patient") or {}
        check("visit creates patient and encounter", status == 200 and patient.get("id") and encounter.get("id"), str(status) + " " + str((visit.get("error") or {}).get("message")))
        check("encounter is not the patient id", encounter.get("id") != patient.get("id"))
        check("doctor assigned", encounter.get("doctor_id") == "U-ANITA")
        queue = encounter.get("queue") or {}
        check("queue entry created", bool(queue.get("id")) and queue.get("token_no"))
        first_id = patient.get("id")
        first_encounter = encounter.get("id")

        status, second = call("POST", "/api/visits", reception, {
            "patient_id": first_id,
            "opd_type_id": new_type,
            "doctor_id": "U-ANITA",
            "chief_complaint": "Return visit",
            "queue": False,
        })
        second_enc = ((second.get("data") or {}).get("encounter") or {}).get("id")
        check("return visit creates a new encounter", status == 200 and second_enc and second_enc != first_encounter, str(status))
        check("return visit keeps the same patient", ((second.get("data") or {}).get("patient") or {}).get("id") == first_id)
        check("no second patient for the return visit", _count(target, "SELECT COUNT(*) FROM patients WHERE id=%s", (first_id,)) == 1)

        status, own_queue = call("GET", "/api/queue", doctor)
        own_ids = {item.get("patient_id") for item in (own_queue.get("data") or {}).get("items", [])}
        check("doctor sees own queue", status == 200 and first_id in own_ids, str(own_ids))
        check("queue payload has no phone", "primary_phone" not in json.dumps(own_queue.get("data") or {}))
        status, foreign = call("GET", "/api/queue?doctor_id=U-IMRAN", doctor)
        check("doctor cannot open another queue", status == 403, str(status))
        status, foreign_status = call("POST", "/api/queue/Q-1/status", doctor, {"status": "CALLED"})
        check("doctor cannot change another queue id", status == 403, str(status))
        status, assign = call("POST", f"/api/opd/{first_encounter}/assign", doctor, {"doctor_id": "U-IMRAN"})
        check("doctor cannot reassign by encounter id", status == 403, str(status))

        status, note = call("POST", "/api/consultations", doctor, {
            "encounter_id": first_encounter,
            "symptoms": "SECRET-NOTE-PHASE2 sore throat",
            "findings": "Throat congested",
            "diagnosis": "Pharyngitis",
            "instructions": "Fluids",
        })
        check("doctor saves own consultation", status == 200 and (note.get("data") or {}).get("diagnosis") == "Pharyngitis", str(status) + " " + str((note.get("error") or {}).get("message")))
        status, revised = call("POST", "/api/consultations", doctor, {
            "encounter_id": first_encounter,
            "symptoms": "SECRET-NOTE-PHASE2 still sore",
            "findings": "Improving",
            "diagnosis": "Resolving pharyngitis",
            "instructions": "Finish fluids",
        })
        check("consultation update keeps the encounter", status == 200 and (revised.get("data") or {}).get("encounter_id") == first_encounter)
        check("prior diagnosis was retained", _count(target, "SELECT COUNT(*) FROM consultation_revisions WHERE diagnosis=%s", ("Pharyngitis",)) == 1)
        status, stolen = call("POST", "/api/consultations", other, {
            "encounter_id": first_encounter,
            "diagnosis": "Not my patient",
        })
        check("other doctor cannot write the consultation", status == 403, str(status))
        status, hidden = call("GET", f"/api/patients/{first_id}", other)
        check("other doctor cannot open the patient", status == 404, str(status))
        status, hidden_timeline = call("GET", f"/api/patients/{first_id}/timeline", other)
        check("other doctor timeline is blocked", status == 404, str(status))
        status, timeline = call("GET", f"/api/patients/{first_id}/timeline", doctor)
        events = (timeline.get("data") or {}).get("events") or []
        check("timeline shows both encounters", status == 200 and sum(1 for ev in events if ev.get("kind") == "opd") >= 2, str(status))
        check("timeline shows the consultation", any(ev.get("kind") == "consultation" for ev in events))
        status, done = call("POST", "/api/consultations", doctor, {
            "encounter_id": first_encounter,
            "diagnosis": "Resolving pharyngitis",
            "complete": True,
        })
        check("doctor completes the visit", status == 200, str(status) + " " + str((done.get("error") or {}).get("message")))
        status, after = call("GET", f"/api/opd/{first_encounter}", doctor)
        check("queue completed", ((after.get("data") or {}).get("queue") or {}).get("status") == "COMPLETED", str(((after.get("data") or {}).get("queue") or {}).get("status")))
        check("encounter completed", (after.get("data") or {}).get("status") == "COMPLETED")

        status, jump = call("POST", "/api/visits", reception, {
            "patient_id": "P-000004",
            "opd_type_id": "OTY-GEN",
            "doctor_id": "U-ANITA",
            "queue": True,
        })
        waiting = (((jump.get("data") or {}).get("encounter") or {}).get("queue") or {})
        status, illegal = call("POST", f"/api/queue/{waiting.get('id')}/status", doctor, {"status": "COMPLETED"})
        check("illegal queue jump is rejected", status == 409, str(status))

        heard = _hear(base, doctor, reception, new_type)
        check("realtime queue event reaches reception", heard["reception"])
        check("realtime does not leak the patient to the other doctor", not heard["other"])
        tokens = _concurrent_visits(base, reception, new_type)
        check("concurrent visits get distinct tokens", len(tokens) == 6 and len(set(tokens)) == 6, str(tokens))

        blob = _audit_blob(target)
        check("audit patient create", "patient_create" in blob)
        check("audit visit", "opd_create" in blob and "queue_create" in blob)
        check("audit consultation", "consultation_create" in blob or "consultation_update" in blob)
        check("audit has no clinical note", "SECRET-NOTE-PHASE2" not in blob)
        check("queue status constraint", _count(target, "SELECT COUNT(*) FROM pg_constraint WHERE conname='queue_status_check'") == 1)
        check("phone is not unique", _count(target, """
            SELECT COUNT(*) FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(c.conkey)
            WHERE t.relname='patients' AND a.attname='primary_phone' AND c.contype='u'
        """) == 0)
    except Exception as exc:
        failures.append(f"workflow crashed: {type(exc).__name__}: {exc}")
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
        try:
            import psycopg
            admin = psycopg.connect(admin_url, autocommit=True)
            admin.execute(f"DROP DATABASE IF EXISTS {db_name} WITH (FORCE)")
            admin.close()
        except Exception as exc:
            failures.append(f"cleanup failed: {exc}")
        if previous is None:
            os.environ.pop("AIPF_DATABASE_URL", None)
        else:
            os.environ["AIPF_DATABASE_URL"] = previous
    return failures


def _hear(base: str, doctor: str, reception: str, opd_type: str) -> dict[str, bool]:
    found = {"reception": False, "other": False}

    def listen(name: str, token: str):
        ticket = urllib.request.Request(
            base + "/api/auth/stream-ticket",
            data=b"{}",
            method="POST",
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + token},
        )
        with urllib.request.urlopen(ticket, timeout=10) as res:
            raw = json.loads(res.read().decode())["data"]["token"]
        query = urllib.parse.urlencode({"token": raw})
        req = urllib.request.Request(base + "/api/events?" + query)
        try:
            with urllib.request.urlopen(req, timeout=5) as res:
                deadline = time.time() + 4
                while time.time() < deadline:
                    line = res.readline()
                    if not line:
                        break
                    if b"queue.updated" in line and b"patient_id" in line:
                        found[name] = True
                        return
        except Exception:
            return

    import urllib.parse
    threads = [
        threading.Thread(target=listen, args=("reception", reception)),
        threading.Thread(target=listen, args=("other", doctor)),
    ]
    for thread in threads:
        thread.start()
    time.sleep(0.6)
    body = {
        "name": "Realtime Person",
        "primary_phone": "9001112233",
        "gender": "Female",
        "age_at_registration": 28,
        "confirm_new": True,
        "opd_type_id": opd_type,
        "doctor_id": "U-IMRAN",
        "chief_complaint": "Realtime",
        "queue": True,
    }
    req = urllib.request.Request(
        base + "/api/visits",
        data=json.dumps(body).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + reception},
    )
    urllib.request.urlopen(req, timeout=20).read()
    for thread in threads:
        thread.join(timeout=8)
    return found


def _concurrent_visits(base: str, token: str, opd_type: str) -> list[int]:
    tokens: list[int] = []
    errors: list[str] = []
    lock = threading.Lock()

    def one(index: int):
        body = {
            "name": f"Concurrent {index}",
            "primary_phone": f"91000000{index:02d}",
            "gender": "Female",
            "age_at_registration": 20 + index,
            "confirm_new": True,
            "opd_type_id": opd_type,
            "doctor_id": "U-ANITA",
            "chief_complaint": "Concurrent",
            "queue": True,
        }
        req = urllib.request.Request(
            base + "/api/visits",
            data=json.dumps(body).encode(),
            method="POST",
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + token},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                payload = json.loads(res.read().decode())
            number = (((payload.get("data") or {}).get("encounter") or {}).get("queue") or {}).get("token_no")
            with lock:
                tokens.append(number)
        except urllib.error.HTTPError as exc:
            with lock:
                errors.append(exc.read().decode()[:300])
        except Exception as exc:
            with lock:
                errors.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=one, args=(i,)) for i in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    if errors:
        tokens.append(-1)
        tokens.append(errors[0])
    return tokens


def _count(url: str, sql: str, params: tuple = ()) -> int:
    import psycopg
    conn = psycopg.connect(url, autocommit=True)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        value = cur.fetchone()[0]
    conn.close()
    return int(value)


def _audit_blob(url: str) -> str:
    import psycopg
    conn = psycopg.connect(url, autocommit=True)
    with conn.cursor() as cur:
        cur.execute("SELECT action, COALESCE(old_value,''), COALESCE(new_value,''), COALESCE(reason,'') FROM audit_logs")
        rows = cur.fetchall()
    conn.close()
    return "\n".join(" ".join(row) for row in rows)


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
