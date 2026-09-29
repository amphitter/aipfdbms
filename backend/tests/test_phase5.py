"""Phase 5 laboratory gate. Real HTTP against throwaway PostgreSQL.

A critical failure means PHASE 5 NOT ACCEPTED. Checks are not weakened to pass.
"""

from __future__ import annotations

import hashlib
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
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "PHASE-5-ACCEPTANCE-REPORT.md"
URL_FILE = Path("/tmp/aipf_pg_url")

SECTIONS = [
    "Test master is database-managed",
    "Referenced tests are deactivated, not deleted",
    "Price is snapshotted through the billing engine",
    "No second billing or lab payment system",
    "Client price and tax are ignored",
    "Order is bound to patient and encounter",
    "Admission is bound when supplied",
    "Phone is not an identity",
    "Another patient's encounter is rejected",
    "Many tests keep separate lifecycles",
    "Status transitions are explicit",
    "Accession numbers are unique and concurrency-safe",
    "Collection is a real sample record",
    "Rejection keeps the sample and allows recollection",
    "Processing queue is event-scoped, not polled",
    "Result types are structured",
    "Reference range is snapshotted at result time",
    "Abnormal and critical come only from configured ranges",
    "Entry and verification are different permissions",
    "Correction preserves the previous result",
    "PDF is rendered from stored results",
    "Report can span pages and shows the rupee sign",
    "Reprint does not mutate the database",
    "Documents go through StorageProvider",
    "Document fetch is authorized",
    "Timeline and doctor access follow permission and scope",
    "Authorization uses permission codes",
    "Cancellation keeps the order and the invoice line",
    "Repeat tests are distinct instances",
]


def test_phase5_http_gate():
    try:
        failures = _run(_postgres_url())
    except Exception as exc:
        raise AssertionError(_sanitize(str(exc))) from None
    assert not failures, _sanitize("\n".join(failures))


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
        raise AssertionError("PostgreSQL is required for the Phase 5 gate")
    return url


def _sanitize(text: str) -> str:
    text = re.sub(r"postgres(?:ql)?://\S+", "[database]", text or "")
    text = text.replace(str(URL_FILE), "[url-file]")
    return text


def _run(admin_url: str) -> list[str]:
    import psycopg

    password = secrets.token_urlsafe(18)
    os.environ["AIPF_SEED_PASSWORD"] = password
    db_name = "aipf_phase5"
    admin = psycopg.connect(admin_url, autocommit=True)
    admin.execute(f"DROP DATABASE IF EXISTS {db_name} WITH (FORCE)")
    admin.execute(f"CREATE DATABASE {db_name}")
    admin.close()
    target = _with_database(admin_url, db_name)
    previous = os.environ.get("AIPF_DATABASE_URL")
    os.environ["AIPF_DATABASE_URL"] = target
    port = _free_port(8798)
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

    def code(payload):
        return ((payload or {}).get("error") or {}).get("code") or ""

    status, admin, admin_user = login("director")
    check(27, "director can sign in", status == 200 and bool(admin), str(status))
    status, anita, anita_user = login("dr.anita")
    check(27, "doctor can sign in", status == 200 and bool(anita))
    status, imran, _ = login("dr.imran")
    check(26, "second doctor can sign in", status == 200 and bool(imran))
    status, lab, lab_user = login("lab")
    check(19, "laboratory user can sign in", status == 200 and bool(lab))
    status, billing, _ = login("billing")
    check(4, "billing user can sign in", status == 200 and bool(billing))
    status, pharmacy, _ = login("pharmacy")
    check(27, "pharmacist can sign in", status == 200 and bool(pharmacy))
    if not all([admin, anita, imran, lab, billing]):
        return failures

    lab_perms = set(lab_user.get("permissions") or [])
    check(19, "technician can enter but is not granted verification", "lab.result.enter" in lab_perms and "lab.result.verify" not in lab_perms, str(sorted(lab_perms)))
    check(27, "doctor permissions do not include verify or view-all", "lab.result.verify" not in (anita_user.get("permissions") or []) and "patient.view_all" not in (anita_user.get("permissions") or []))
    check(27, "authorization source does not branch on a role name", "role ==" not in (ROOT / "backend/aipf/laboratory.py").read_text(encoding="utf-8") and 'user.get("role")' not in (ROOT / "backend/aipf/laboratory.py").read_text(encoding="utf-8"))
    check(4, "laboratory domain does not record payments", "record_payment" not in (ROOT / "backend/aipf/laboratory.py").read_text(encoding="utf-8") and "remove_draft_item" not in (ROOT / "backend/aipf/laboratory.py").read_text(encoding="utf-8"))
    page = (ROOT / "frontend/src/pages/clinical.tsx").read_text(encoding="utf-8")
    check(11, "laboratory page does not post an arbitrary status", "SAMPLE_COLLECTED" not in page and "setInterval" not in page)
    check(1, "schema version is the current postgres migration", version == 19, str(version))

    def patient(name, phone):
        status, payload = call("POST", "/api/patients", admin, {
            "name": name, "primary_phone": phone, "gender": "Female", "age_at_registration": 41, "confirm_new": True,
        })
        return status, data_of(payload).get("id"), payload

    status, person, _ = patient("Phase Five Patient", "9811100501")
    check(8, "patient is created by id", status == 200 and bool(person) and not str(person).startswith("9811"), str(status))
    status, twin, _ = patient("Phase Five Twin", "9811100501")
    check(8, "shared phone does not merge patients", status == 200 and twin and twin != person, str(status))
    status, opd = call("POST", "/api/opd/types", admin, {"name": "Phase 5 card", "fee_paise": 20000, "validity_days": 1})
    opd_id = data_of(opd).get("id")
    status, visit = call("POST", "/api/visits", admin, {"patient_id": person, "opd_type_id": opd_id, "doctor_id": "U-ANITA", "queue": False})
    encounter_id = (data_of(visit).get("encounter") or {}).get("id")
    invoice_id = (data_of(visit).get("encounter") or {}).get("invoice_id")
    check(6, "encounter belongs to the patient", status == 200 and bool(encounter_id), err(visit))

    status, glucose = call("POST", "/api/lab/tests", admin, {
        "name": "Phase Five Glucose", "code": "P5GLU", "price_paise": 50000, "sample_type": "Blood",
        "container_type": "Fluoride", "unit": "mg/dL", "result_type": "numeric",
        "reference_low": "70", "reference_high": "110", "critical_low": "40", "critical_high": "400",
        "methodology": "GOD-POD", "reference_range": "70 - 110",
    })
    glucose_id = data_of(glucose).get("id")
    status, note = call("POST", "/api/lab/tests", admin, {
        "name": "Phase Five Note", "code": "P5NOTE", "price_paise": 10000, "sample_type": "Blood", "result_type": "text", "unit": "",
    })
    note_id = data_of(note).get("id")
    status, widal = call("POST", "/api/lab/tests", admin, {
        "name": "Phase Five Screen", "code": "P5SCR", "price_paise": 15000, "sample_type": "Blood", "result_type": "positive_negative",
    })
    widal_id = data_of(widal).get("id")
    status, catalogue = call("GET", "/api/lab/tests?all=1", admin)
    listed = {item.get("id"): item for item in data_of(catalogue).get("items") or []}
    check(1, "configured test is returned by the catalogue API", status == 200 and listed.get(glucose_id, {}).get("reference_low") == "70" and listed.get(glucose_id, {}).get("methodology") == "GOD-POD", str(status))
    status, duplicate = call("POST", "/api/lab/tests", admin, {"name": "Duplicate glucose", "code": "p5glu", "price_paise": 1, "sample_type": "Blood"})
    check(1, "duplicate test code is rejected", status == 409, str(status) + " " + err(duplicate))

    status, phone_order = call("POST", "/api/lab/orders", anita, {"phone": "9811100501", "tests": [{"test_id": glucose_id}]})
    check(8, "order cannot be created from a phone number", status == 400, str(status) + " " + err(phone_order))
    status, other_enc = call("POST", "/api/visits", admin, {"patient_id": twin, "opd_type_id": opd_id, "doctor_id": "U-IMRAN", "queue": False})
    twin_encounter = (data_of(other_enc).get("encounter") or {}).get("id")
    status, crossed = call("POST", "/api/lab/orders", anita, {
        "patient_id": person, "encounter_id": twin_encounter, "tests": [{"test_id": glucose_id}],
    })
    check(9, "another patient's encounter is not attached", status == 404 and "Phase Five" not in json.dumps(crossed), str(status) + " " + err(crossed))
    status, missing_enc = call("POST", "/api/lab/orders", anita, {
        "patient_id": person, "encounter_id": "OPD-NO-SUCH", "tests": [{"test_id": glucose_id}],
    })
    check(9, "missing and foreign encounters look the same", status == 404 and err(crossed) == err(missing_enc), err(crossed) + " / " + err(missing_enc))
    status, pharmacist_order = call("POST", "/api/lab/orders", pharmacy, {"patient_id": person, "encounter_id": encounter_id, "tests": [{"test_id": glucose_id}]})
    check(27, "order permission is required before the record is touched", status == 403, str(status))

    order_body = {
        "patient_id": person, "encounter_id": encounter_id, "priority": "STAT", "idempotency_key": "p5-order",
        "tests": [
            {"test_id": glucose_id, "price_paise": 100, "tax_paise": 999},
            {"test_id": note_id, "price_paise": 1},
            {"test_id": widal_id},
        ],
    }
    status, ordered = call("POST", "/api/lab/orders", anita, order_body)
    order = data_of(ordered)
    order_id = order.get("id")
    check(6, "doctor orders on the linked encounter", status == 200 and order.get("encounter_id") == encounter_id and order.get("patient_id") == person, err(ordered))
    check(10, "one order holds three distinct tests", status == 200 and len(order.get("items") or []) == 3, str(len(order.get("items") or [])))
    status, replay = call("POST", "/api/lab/orders", anita, order_body)
    check(12, "repeating the order key does not create a second order", status == 200 and data_of(replay).get("id") == order_id and data_of(replay).get("idempotent_replay") is True, err(replay))
    items = {item.get("test_id"): item for item in order.get("items") or []}
    glucose_item = items.get(glucose_id) or {}
    note_item = items.get(note_id) or {}
    widal_item = items.get(widal_id) or {}
    status, bill = call("GET", f"/api/invoices/{invoice_id}", billing)
    lines = [item for item in data_of(bill).get("items") or [] if item.get("category") == "LABORATORY"]
    glucose_line = next((item for item in lines if item.get("description") == "Phase Five Glucose"), {})
    check(3, "master price of 500 rupees is snapshotted in integer paise", glucose_line.get("rate_paise") == 50000, str(glucose_line.get("rate_paise")))
    check(5, "client price and tax are not stored", glucose_line.get("rate_paise") == 50000 and int(glucose_line.get("tax_paise") or 0) == 0, str(glucose_line))
    check(4, "ordering does not create a payment", data_of(bill).get("payments") == [] or data_of(bill).get("paid_paise") in (0, None), str(data_of(bill).get("paid_paise")))
    payments_before = len(data_of(bill).get("payments") or [])
    status, custom = call("POST", "/api/lab/orders", anita, {
        "patient_id": person, "encounter_id": encounter_id, "idempotency_key": "p5-custom",
        "tests": [{"custom_name": "Unlisted smear", "price_paise": 99999, "sample_type": "Blood"}],
    })
    custom_item = (data_of(custom).get("items") or [{}])[0]
    check(5, "custom test is price pending rather than a client price", status == 200 and custom_item.get("price_pending") in (1, True) and int(custom_item.get("price_paise") or 0) == 0, err(custom))
    call("PATCH", f"/api/lab/tests/{glucose_id}", admin, {"name": "Phase Five Glucose", "price_paise": 70000})
    status, bill_again = call("GET", f"/api/invoices/{invoice_id}", billing)
    glucose_line = next((item for item in data_of(bill_again).get("items") or [] if item.get("description") == "Phase Five Glucose"), {})
    check(3, "later master price of 700 rupees does not rewrite the line", glucose_line.get("rate_paise") == 50000, str(glucose_line.get("rate_paise")))

    status, hidden = call("GET", f"/api/lab/orders/{order_id}", imran)
    status, absent = call("GET", "/api/lab/orders/LAB-NO-SUCH", imran)
    check(26, "another doctor cannot open the order", status == 404 and err(hidden) == err(absent) and "Phase Five" not in json.dumps(hidden), err(hidden))
    status, seen = call("GET", f"/api/lab/orders/{order_id}", anita)
    check(26, "the linked doctor can open the same order", status == 200 and data_of(seen).get("id") == order_id, str(status))
    jump = call("POST", f"/api/lab/orders/{order_id}/status", lab, {"status": "RESULTED"})
    status, after_jump = call("GET", f"/api/lab/orders/{order_id}", lab)
    still_pending = {item.get("test_id"): item.get("status") for item in data_of(after_jump).get("items") or []}
    check(11, "arbitrary status jump is rejected", jump[0] == 409 and still_pending.get(glucose_id) == "SAMPLE_PENDING", str(jump[0]) + " " + err(jump[1]) + " " + str(still_pending))
    status, early = call("POST", f"/api/lab/items/{note_item.get('id')}/result", lab, {"value": "too soon", "idempotency_key": "p5-early"})
    check(11, "result entry cannot skip collection", status == 409, str(status) + " " + err(early))

    heard, listeners = _hear(base, lab, imran, person)
    status, sample = call("POST", f"/api/lab/orders/{order_id}/samples", lab, {"item_ids": [glucose_item.get("id")], "location": "OPD desk", "idempotency_key": "p5-collect-g"})
    for thread in listeners:
        thread.join(timeout=8)
    accession = data_of(sample).get("accession_no")
    check(13, "collection creates one accessioned sample", status == 200 and str(accession).startswith("ACC-"), err(sample))
    check(15, "collection event reaches the laboratory user only", heard.get("lab") is True and heard.get("imran") is False, str(heard))
    status, queued = call("GET", "/api/lab/queue", lab)
    check(15, "processing queue lists the collected sample", any(item.get("accession_no") == accession for item in data_of(queued).get("items") or []), str(status))
    status, imran_queue = call("GET", "/api/lab/queue", imran)
    check(15, "the other doctor's queue does not list it", all(item.get("accession_no") != accession for item in data_of(imran_queue).get("items") or []))
    status, detail = call("GET", f"/api/lab/orders/{order_id}", lab)
    by_test = {item.get("test_id"): item for item in data_of(detail).get("items") or []}
    check(10, "unordered tests stay pending while one is collected", by_test.get(note_id, {}).get("status") == "SAMPLE_PENDING" and by_test.get(glucose_id, {}).get("status") == "SAMPLE_COLLECTED", str({k: v.get("status") for k, v in by_test.items()}))
    sample_id = data_of(sample).get("id")
    bad_reason = call("POST", f"/api/lab/samples/{sample_id}/reject", lab, {"reason_code": "BROKEN", "idempotency_key": "p5-bad-reason"})
    check(14, "unknown rejection reason is rejected", bad_reason[0] == 400, err(bad_reason[1]))
    status, rejected = call("POST", f"/api/lab/samples/{sample_id}/reject", lab, {"reason_code": "HAEMOLYSED", "idempotency_key": "p5-reject"})
    check(14, "configured rejection reason is accepted", status == 200 and data_of(rejected).get("status") == "REJECTED", err(rejected))
    audits_at_reject = _count(target, "audit_logs")
    kept_accession = data_of(rejected).get("accession_no")
    kept_reason = data_of(rejected).get("rejection_reason")
    late_bad = call("POST", f"/api/lab/samples/{sample_id}/reject", lab, {"reason_code": "random_invalid_reason", "idempotency_key": "p5-bad-after"})
    status, after_bad = call("GET", f"/api/lab/orders/{order_id}", lab)
    still_rejected = next((item for item in data_of(after_bad).get("samples") or [] if item.get("id") == sample_id), {})
    check(14, "unknown reason after rejection does not mutate the sample", late_bad[0] == 400 and still_rejected.get("status") == "REJECTED" and still_rejected.get("accession_no") == kept_accession and still_rejected.get("rejection_reason") == kept_reason and _count(target, "audit_logs") == audits_at_reject, err(late_bad[1]) + " " + str(still_rejected.get("status")))
    status, recollected = call("POST", f"/api/lab/orders/{order_id}/samples", lab, {"item_ids": [glucose_item.get("id")], "idempotency_key": "p5-recollect"})
    new_accession = data_of(recollected).get("accession_no")
    status, history = call("GET", f"/api/lab/orders/{order_id}", lab)
    glucose_now = next(item for item in data_of(history).get("items") or [] if item.get("test_id") == glucose_id)
    sample_states = {item.get("accession_no"): item.get("status") for item in glucose_now.get("samples") or []}
    check(14, "rejected sample is kept and recollection has a new accession", sample_states.get(accession) == "REJECTED" and new_accession and new_accession != accession and sample_states.get(new_accession) == "COLLECTED", str(sample_states))
    status, both = call("POST", f"/api/lab/orders/{order_id}/samples", lab, {"item_ids": [note_item.get("id"), widal_item.get("id")], "idempotency_key": "p5-collect-rest"})
    rest_id = data_of(both).get("id")
    check(13, "two tests of one specimen can share a collection", status == 200 and bool(rest_id), err(both))
    status, received = call("POST", f"/api/lab/samples/{rest_id}/receive", lab, {"idempotency_key": "p5-receive"})
    check(15, "receipt is an explicit step", status == 200 and data_of(received).get("status") == "RECEIVED", err(received))
    status, processed_rest = call("POST", f"/api/lab/samples/{rest_id}/process", lab, {"idempotency_key": "p5-process-rest"})
    processed_g = call("POST", f"/api/lab/samples/{data_of(recollected).get('id')}/process", lab, {"idempotency_key": "p5-process-g"})
    status, queue_after = call("GET", "/api/lab/queue", lab)
    check(15, "processed samples leave the queue", status == 200 and processed_g[0] == 200 and all(item.get("id") not in {rest_id, data_of(recollected).get("id")} for item in data_of(queue_after).get("items") or []), err(processed_g[1]) if isinstance(processed_g[1], dict) else "")

    doctor_enter = call("POST", f"/api/lab/items/{glucose_item.get('id')}/result", anita, {"value": "90", "idempotency_key": "p5-doc-enter"})
    check(19, "doctor cannot enter a result", doctor_enter[0] == 403, str(doctor_enter[0]))
    status, entered = call("POST", f"/api/lab/items/{glucose_item.get('id')}/result", lab, {"value": "50", "idempotency_key": "p5-enter-g"})
    glucose_result = data_of(entered)
    check(16, "numeric result is stored", status == 200 and glucose_result.get("value_text") == "50" and glucose_result.get("result_type") == "numeric", err(entered))
    check(18, "low flag comes from the configured range", glucose_result.get("abnormal_flag") == "low" and int(glucose_result.get("critical_flag") or 0) == 0, str(glucose_result.get("abnormal_flag")))
    check(17, "range is snapshotted onto the result", glucose_result.get("reference_range") == "70 - 110" and glucose_result.get("methodology") == "GOD-POD", str(glucose_result.get("reference_range")))
    status, note_entered = call("POST", f"/api/lab/items/{note_item.get('id')}/result", lab, {"value": "abnormal", "remarks": "N" * 3600, "idempotency_key": "p5-enter-note"})
    check(18, "a text value is not turned into a diagnosis flag", status == 200 and data_of(note_entered).get("abnormal_flag") in (None, "") and int(data_of(note_entered).get("critical_flag") or 0) == 0, str(data_of(note_entered).get("abnormal_flag")))
    status, screen_entered = call("POST", f"/api/lab/items/{widal_item.get('id')}/result", lab, {"value": "positive", "idempotency_key": "p5-enter-screen"})
    check(16, "positive or negative is a result value, not a flag", status == 200 and data_of(screen_entered).get("value_text") == "POSITIVE" and int(data_of(screen_entered).get("critical_flag") or 0) == 0, err(screen_entered))
    lab_verify = call("POST", f"/api/lab/results/{glucose_result.get('id')}/verify", lab, {"idempotency_key": "p5-lab-verify"})
    check(19, "technician verification is forbidden", lab_verify[0] == 403, str(lab_verify[0]))
    doctor_verify = call("POST", f"/api/lab/results/{glucose_result.get('id')}/verify", anita, {"idempotency_key": "p5-doc-verify"})
    check(19, "doctor verification is forbidden", doctor_verify[0] == 403, str(doctor_verify[0]))

    status, roles = call("GET", "/api/roles", admin)
    lab_role = next(item for item in data_of(roles).get("items") or [] if item.get("code") == "lab")
    original = list(lab_role.get("permissions") or [])
    granted = call("PUT", "/api/roles/lab/permissions", admin, {"permissions": original + ["lab.result.verify"]})
    granted_lab = next((item for item in data_of(granted[1]).get("items") or [] if item.get("code") == "lab"), {})
    check(27, "verification can be granted by permission code", granted[0] == 200 and "lab.result.verify" in (granted_lab.get("permissions") or []), err(granted[1]))
    now_verified = call("POST", f"/api/lab/results/{glucose_result.get('id')}/verify", lab, {"idempotency_key": "p5-verify-g"})
    verify_note = call("POST", f"/api/lab/results/{data_of(note_entered).get('id')}/verify", lab, {"idempotency_key": "p5-verify-note"})
    verify_screen = call("POST", f"/api/lab/results/{data_of(screen_entered).get('id')}/verify", lab, {"idempotency_key": "p5-verify-screen"})
    check(19, "the same user verifies only after the permission is granted", now_verified[0] == 200 and data_of(now_verified[1]).get("status") == "VERIFIED" and verify_note[0] == 200 and verify_screen[0] == 200, err(now_verified[1]) if isinstance(now_verified[1], dict) else "")
    call("PUT", "/api/roles/lab/permissions", admin, {"permissions": original})
    lab_correct = call("POST", f"/api/lab/results/{glucose_result.get('id')}/correct", lab, {"value": "39", "reason": "no", "idempotency_key": "p5-lab-correct"})
    check(20, "technician cannot correct a verified result", lab_correct[0] == 403, str(lab_correct[0]))
    call("PATCH", f"/api/lab/tests/{glucose_id}", admin, {
        "name": "Phase Five Glucose", "price_paise": 70000, "reference_low": "80", "reference_high": "120",
        "critical_low": "40", "critical_high": "400", "reference_range": "80 - 120", "methodology": "HEXOKINASE",
    })
    status, corrected = call("POST", f"/api/lab/results/{glucose_result.get('id')}/correct", admin, {
        "value": "39", "reason": "Repeat run was lower", "remarks": "C" * 3500, "idempotency_key": "p5-correct",
    })
    correction = data_of(corrected)
    check(20, "correction is a new revision with a reason", status == 200 and correction.get("supersedes_id") == glucose_result.get("id") and correction.get("correction_reason") == "Repeat run was lower" and int(correction.get("revision_no") or 0) == 2, err(corrected))
    check(18, "critical flag is calculated from the snapshotted critical range", correction.get("abnormal_flag") == "critical_low" and int(correction.get("critical_flag") or 0) == 1, str(correction.get("abnormal_flag")))
    history = call("GET", f"/api/lab/orders/{order_id}", anita)
    glucose_hist = next((item for item in data_of(history[1]).get("items") or [] if item.get("test_id") == glucose_id), {})
    old = next((item for item in glucose_hist.get("results") or [] if item.get("id") == glucose_result.get("id")), {})
    if not old:
        check(20, "previous result is present in history", False, "enter=" + str(glucose_result.get("id")) + " correct=" + str(correction.get("id")) + " statuses=" + str([item.get("status") for item in glucose_hist.get("results") or []]) + " err=" + err(corrected[1] if isinstance(corrected, tuple) else corrected))
    check(20, "previous value, actor, and time remain", old.get("status") == "SUPERSEDED" and old.get("value_text") == "50" and old.get("reference_range") == "70 - 110" and old.get("entered_by"), str(old.get("status")))
    check(17, "historical range is not rewritten from today's master", old.get("methodology") == "GOD-POD" and correction.get("reference_range") == "80 - 120", str(old.get("methodology")) + " / " + str(correction.get("reference_range")))
    status, audit_rows = call("GET", "/api/audit?module=lab&action=lab_result_critical", admin)
    check(18, "critical result is audited", any(item.get("action") == "lab_result_critical" for item in data_of(audit_rows).get("items") or []), str(status))
    lab_reverify = call("POST", f"/api/lab/results/{correction.get('id')}/verify", lab, {"idempotency_key": "p5-reverify-denied"})
    check(19, "revoked verification permission is enforced", lab_reverify[0] == 403, str(lab_reverify[0]))
    verified_correction = call("POST", f"/api/lab/results/{correction.get('id')}/verify", admin, {"idempotency_key": "p5-reverify"})
    check(19, "holder of the verify permission can verify the correction", verified_correction[0] == 200 and data_of(verified_correction[1]).get("status") == "VERIFIED", err(verified_correction[1]) if isinstance(verified_correction[1], dict) else "")
    call("PATCH", f"/api/lab/tests/{glucose_id}", admin, {
        "name": "Phase Five Glucose", "price_paise": 70000, "reference_range": "90 - 130", "methodology": "LATER",
        "reference_low": "90", "reference_high": "130",
    })

    status, report = call("POST", f"/api/lab/orders/{order_id}/report", lab, {"idempotency_key": "p5-report"})
    meta = data_of(report)
    check(21, "report is generated from verified results", status == 200 and meta.get("document_id") and meta.get("checksum"), err(report))
    check(24, "report response has no filesystem path", status == 200 and "/home" not in json.dumps(meta) and "stored_name" not in json.dumps(meta), json.dumps(meta)[:240])
    status, pdf = call("GET", f"/api/lab/orders/{order_id}/report", anita, raw=True)
    check(21, "linked doctor can fetch the stored PDF", isinstance(pdf, bytes) and pdf.startswith(b"%PDF") and b"Phase Five Patient" in pdf and person.encode() in pdf, str(status))
    check(22, "long report has a second page", isinstance(pdf, bytes) and b"Page 2" in pdf)
    check(22, "rupee sign is embedded and the snapshotted amount is shown", isinstance(pdf, bytes) and b"DCTDecode" in pdf and b"500.00" in pdf and b"700.00" not in pdf)
    check(18, "PDF says a flag is not a diagnosis", isinstance(pdf, bytes) and b"not a diagnosis" in pdf)
    check(21, "PDF uses the result-time method, not the later master", isinstance(pdf, bytes) and b"HEXOKINASE" in pdf and b"LATER" not in pdf)
    check(24, "stored checksum matches the PDF bytes", isinstance(pdf, bytes) and hashlib.sha256(pdf).hexdigest() == meta.get("checksum"))
    before = _snapshot(target, order_id)
    status, again = call("GET", f"/api/lab/orders/{order_id}/report", anita, raw=True)
    after = _snapshot(target, order_id)
    check(
        23,
        "reprint is byte-identical and writes nothing",
        again == pdf
        and before["documents"] == after["documents"]
        and before["results"] == after["results"]
        and before["audits"] == after["audits"]
        and before["generated_at"] == after["generated_at"]
        and before["checksums"] == after["checksums"]
        and before["reports"] == after["reports"],
        "bytes=" + str(again == pdf)
        + " docs=" + str(before["documents"]) + "/" + str(after["documents"])
        + " audits=" + str(before["audits"]) + "/" + str(after["audits"])
        + " generated=" + str(before["generated_at"]) + "/" + str(after["generated_at"]),
    )
    status, second = call("POST", f"/api/lab/orders/{order_id}/report", lab, {"idempotency_key": "p5-report-again"})
    check(23, "generating an unchanged report does not create a document", data_of(second).get("document_id") == meta.get("document_id") and _snapshot(target, order_id)["documents"] == after["documents"], err(second))
    imran_pdf = call("GET", f"/api/lab/orders/{order_id}/report", imran, raw=True)
    missing_pdf = call("GET", "/api/lab/orders/LAB-NO-SUCH/report", imran, raw=True)
    check(25, "report fetch outside scope matches a missing report", imran_pdf[0] == 404 and missing_pdf[0] == 404 and err(imran_pdf[1]) == err(missing_pdf[1]) and b"Phase Five" not in (imran_pdf[1] if isinstance(imran_pdf[1], bytes) else json.dumps(imran_pdf[1]).encode()))
    doc_id = meta.get("document_id")
    hidden_file = call("GET", f"/api/documents/{doc_id}/file", imran, raw=True)
    missing_file = call("GET", "/api/documents/DOC-NO-SUCH/file", imran, raw=True)
    check(25, "document file outside scope matches a missing file", hidden_file[0] == 404 and missing_file[0] == 404 and err(hidden_file[1]) == err(missing_file[1]))
    own_file = call("GET", f"/api/documents/{doc_id}/file", anita, raw=True)
    check(25, "linked doctor with document permission can open the file", own_file[0] == 200 and isinstance(own_file[1], bytes) and own_file[1].startswith(b"%PDF"), str(own_file[0]))
    bogus = call("GET", "/api/documents/..%2F..%2Fetc%2Fpasswd/file", anita, raw=True)
    check(25, "a path is not accepted as a document id", bogus[0] in (404, 400) and b"root:" not in (bogus[1] if isinstance(bogus[1], bytes) else b""))

    status, timeline = call("GET", f"/api/patients/{person}/timeline", anita)
    kinds = {item.get("kind") for item in data_of(timeline).get("events") or []}
    check(26, "timeline shows sample, verified result, and report", {"lab_sample", "lab_result", "lab_report"} <= kinds, str(kinds))
    check(18, "timeline does not call the flag a diagnosis", all(item.get("detail") != "Diagnosis" for item in data_of(timeline).get("events") or []))
    status, billing_timeline = call("GET", f"/api/patients/{person}/timeline", billing)
    billing_kinds = {item.get("kind") for item in data_of(billing_timeline).get("events") or []}
    check(26, "billing timeline does not receive laboratory detail", "lab_result" not in billing_kinds and accession not in json.dumps(data_of(billing_timeline)))
    imran_timeline = call("GET", f"/api/patients/{person}/timeline", imran)
    check(26, "unlinked doctor timeline is not found", imran_timeline[0] == 404 and "Phase Five" not in json.dumps(imran_timeline[1]))

    status, repeat = call("POST", "/api/lab/orders", anita, {
        "patient_id": person, "encounter_id": encounter_id, "idempotency_key": "p5-repeat",
        "tests": [{"test_id": glucose_id}, {"test_id": glucose_id}],
    })
    repeat_items = data_of(repeat).get("items") or []
    check(29, "repeat test creates two item ids", status == 200 and len(repeat_items) == 2 and repeat_items[0].get("id") != repeat_items[1].get("id"), err(repeat))
    first_rep = call("POST", f"/api/lab/orders/{data_of(repeat).get('id')}/samples", lab, {"item_ids": [repeat_items[0].get("id")], "idempotency_key": "p5-repeat-a"})
    second_rep = call("POST", f"/api/lab/orders/{data_of(repeat).get('id')}/samples", lab, {"item_ids": [repeat_items[1].get("id")], "idempotency_key": "p5-repeat-b"})
    check(29, "repeat collections get distinct accessions", first_rep[0] == 200 and second_rep[0] == 200 and data_of(first_rep[1]).get("accession_no") != data_of(second_rep[1]).get("accession_no"), err(second_rep[1]) if isinstance(second_rep[1], dict) else "")

    status, cancel_order = call("POST", "/api/lab/orders", anita, {
        "patient_id": person, "encounter_id": encounter_id, "idempotency_key": "p5-cancel-order",
        "tests": [{"test_id": note_id}],
    })
    cancel_id = data_of(cancel_order).get("id")
    line_ids = [item.get("invoice_item_id") for item in data_of(cancel_order).get("items") or []]
    status, bill_before = call("GET", f"/api/invoices/{invoice_id}", billing)
    net_before = data_of(bill_before).get("net_paise")
    count_before = len(data_of(bill_before).get("items") or [])
    cancelled = call("POST", f"/api/lab/orders/{cancel_id}/cancel", anita, {"reason": "Patient declined", "idempotency_key": "p5-cancel"})
    status, bill_after = call("GET", f"/api/invoices/{invoice_id}", billing)
    remaining = [item.get("id") for item in data_of(bill_after).get("items") or []]
    check(28, "cancellation keeps the order and the invoice line", cancelled[0] == 200 and data_of(cancelled[1]).get("status") == "CANCELLED" and line_ids and line_ids[0] in remaining and data_of(bill_after).get("net_paise") == net_before and len(remaining) == count_before, err(cancelled[1]) if isinstance(cancelled[1], dict) else "")
    check(4, "cancellation adds no payment", len(data_of(bill_after).get("payments") or []) == payments_before)
    still = call("GET", f"/api/lab/orders/{cancel_id}", lab)
    check(28, "cancelled order is still readable", still[0] == 200 and data_of(still[1]).get("id") == cancel_id)

    status, other_person, _ = patient("Phase Five Adjust", "9811100509")
    status, other_visit = call("POST", "/api/visits", admin, {"patient_id": other_person, "opd_type_id": opd_id, "doctor_id": "U-ANITA", "queue": False})
    other_enc = (data_of(other_visit).get("encounter") or {}).get("id")
    other_invoice = (data_of(other_visit).get("encounter") or {}).get("invoice_id")
    status, admitted = call("POST", "/api/admissions", admin, {"patient_id": other_person, "encounter_id": other_enc, "doctor_id": "U-ANITA", "reason": "Observation"})
    admission_id = data_of(admitted).get("id")
    ipd_order = call("POST", "/api/lab/orders", anita, {
        "patient_id": other_person, "encounter_id": other_enc, "admission_id": admission_id, "idempotency_key": "p5-ipd",
        "tests": [{"test_id": note_id}],
    })
    check(7, "admission is stored when it belongs to the patient", ipd_order[0] == 200 and data_of(ipd_order[1]).get("admission_id") == admission_id, err(ipd_order[1]) if isinstance(ipd_order[1], dict) else "")
    wrong_adm = call("POST", "/api/lab/orders", anita, {
        "patient_id": person, "encounter_id": encounter_id, "admission_id": admission_id, "idempotency_key": "p5-wrong-adm",
        "tests": [{"test_id": note_id}],
    })
    check(7, "another patient's admission is not attached", wrong_adm[0] == 404, str(wrong_adm[0]) + " " + err(wrong_adm[1]))
    ipd_cancel = call("POST", f"/api/lab/orders/{data_of(ipd_order[1]).get('id')}/cancel", anita, {"reason": "Not required", "idempotency_key": "p5-ipd-cancel"})
    check(28, "inpatient cancellation still keeps the row", ipd_cancel[0] == 200, err(ipd_cancel[1]) if isinstance(ipd_cancel[1], dict) else "")
    line_id = ((data_of(ipd_order[1]).get("items") or [{}])[0]).get("invoice_item_id")
    listed = call("GET", f"/api/invoices?patient_id={other_person}", billing)
    lab_invoice = ""
    for invoice in data_of(listed[1]).get("items") or []:
        full = call("GET", f"/api/invoices/{invoice.get('id')}", billing)
        if line_id and any(item.get("id") == line_id for item in data_of(full[1]).get("items") or []):
            lab_invoice = invoice.get("id")
            break
    finalized = call("POST", f"/api/invoices/{lab_invoice}/finalize", billing, {})
    check(4, "billing finalizes the invoice the lab line sits on", finalized[0] == 200 and lab_invoice, err(finalized[1]) if isinstance(finalized[1], dict) else "")
    lab_adjust = call("POST", f"/api/invoices/{lab_invoice}/adjust", lab, {"amount_paise": -10000, "description": "Lab reversal", "reason": "Cancelled"})
    check(4, "laboratory user cannot post a financial adjustment", lab_adjust[0] == 403, str(lab_adjust[0]))
    adjusted = call("POST", f"/api/invoices/{lab_invoice}/adjust", billing, {"amount_paise": -10000, "description": "Lab reversal", "reason": "Order cancelled before processing"})
    status, adjusted_bill = call("GET", f"/api/invoices/{lab_invoice}", billing)
    descriptions = [item.get("description") for item in data_of(adjusted_bill).get("items") or []]
    check(28, "phase 4 adjustment reverses the charge without deleting the lab line", adjusted[0] == 200 and "Phase Five Note" in descriptions and "Lab reversal" in descriptions, err(adjusted[1]) if isinstance(adjusted[1], dict) else "")

    call("PATCH", f"/api/lab/tests/{glucose_id}", admin, {"name": "Phase Five Glucose", "code": "P5GLU", "price_paise": 70000, "active": False})
    inactive = call("POST", "/api/lab/orders", anita, {"patient_id": person, "encounter_id": encounter_id, "tests": [{"test_id": glucose_id}], "idempotency_key": "p5-inactive"})
    check(2, "inactive test cannot be ordered", inactive[0] == 409, str(inactive[0]) + " " + err(inactive[1]))
    old_order = call("GET", f"/api/lab/orders/{order_id}", anita)
    check(2, "historical order remains after deactivation", old_order[0] == 200 and any(item.get("test_id") == glucose_id for item in data_of(old_order[1]).get("items") or []))
    deleted = call("DELETE", f"/api/lab/tests/{glucose_id}", admin)
    still_listed = call("GET", "/api/lab/tests?all=1", admin)
    check(2, "there is no delete of a referenced test", deleted[0] == 404 and any(item.get("id") == glucose_id for item in data_of(still_listed[1]).get("items") or []), str(deleted[0]))
    audits_before = _count(target, "audit_logs")
    audit_delete = call("DELETE", "/api/audit", admin)
    check(27, "audit rows cannot be deleted through the API", audit_delete[0] == 404 and _count(target, "audit_logs") == audits_before, str(audit_delete[0]))
    constraints = _constraints(target)
    indexes = _indexes(target)
    check(13, "postgres prevents two active collections of one ordered test", "uq_lab_active_collection" in indexes)
    check(12, "postgres enforces accession uniqueness and laboratory checks", "lab_samples_accession_no_key" in constraints or any("accession" in name for name in constraints))
    for name in ("lab_orders_status_check", "lab_orders_priority_check", "lab_order_items_status_check", "lab_samples_status_check", "lab_results_status_check", "lab_results_revision_positive"):
        check(11, f"postgres check {name}", name in constraints, ", ".join(sorted(constraints)[:12]))

    race = _race(base, anita, lab, person, encounter_id, note_id)
    check(12, "concurrent collections receive distinct accessions", race["distinct"] is True and race["count"] == 2, str(race))
    clash = _clash(base, anita, lab, person, encounter_id, note_id)
    check(13, "concurrent collection of one test creates one sample", clash["ok"] == 1 and clash["conflict"] >= 1 and clash["samples"] == 1, str(clash))
    same = _same_key(base, anita, lab, person, encounter_id, note_id)
    check(12, "concurrent retry of one collection key creates one sample", same["samples"] == 1 and same["accession_count"] == 1, str(same))
    many = _many(base, anita, lab, person, encounter_id, note_id, 10)
    check(12, "ten concurrent collections receive ten distinct accessions", many["distinct"] is True and many["count"] == 10, str(many))
    verified_race = _verify_race(base, admin, lab, person, encounter_id, note_id)
    check(19, "concurrent verification commits one verified result", verified_race["ok"] == 1 and verified_race["conflict"] == 1 and verified_race["verified"] == 1, str(verified_race))
    return failures


def _snapshot(url: str, order_id: str) -> dict:
    import psycopg

    conn = psycopg.connect(url)
    try:
        documents = conn.execute("SELECT count(*) FROM documents WHERE entity_type='lab_order' AND entity_id=%s", (order_id,)).fetchone()[0]
        reports = conn.execute("SELECT count(*) FROM lab_reports WHERE order_id=%s", (order_id,)).fetchone()[0]
        results = conn.execute(
            """SELECT r.id, r.value_text, r.status, r.reference_range, r.methodology
                 FROM lab_results r JOIN lab_order_items i ON i.id=r.lab_order_item_id
                WHERE i.order_id=%s ORDER BY r.id""",
            (order_id,),
        ).fetchall()
        audits = conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0]
        reports_meta = conn.execute(
            "SELECT generated_at, document_id FROM lab_reports WHERE order_id=%s ORDER BY generated_at, id",
            (order_id,),
        ).fetchall()
        checksums = []
        if reports_meta:
            checksums = conn.execute(
                "SELECT id, checksum FROM documents WHERE id = ANY(%s) ORDER BY id",
                ([row[1] for row in reports_meta],),
            ).fetchall()
        return {
            "documents": documents,
            "reports": reports,
            "results": results,
            "audits": audits,
            "generated_at": [row[0] for row in reports_meta],
            "checksums": [(row[0], row[1]) for row in checksums],
        }
    finally:
        conn.close()


def _count(url: str, table: str) -> int:
    import psycopg

    conn = psycopg.connect(url)
    try:
        return int(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
    finally:
        conn.close()


def _constraints(url: str) -> set[str]:
    import psycopg

    conn = psycopg.connect(url)
    try:
        rows = conn.execute("SELECT conname FROM pg_constraint").fetchall()
        return {row[0] for row in rows}
    finally:
        conn.close()


def _indexes(url: str) -> set[str]:
    import psycopg

    conn = psycopg.connect(url)
    try:
        rows = conn.execute("SELECT indexname FROM pg_indexes").fetchall()
        return {row[0] for row in rows}
    finally:
        conn.close()


def _post(base, token, path, body):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), method="POST", headers={
        "Content-Type": "application/json", "Authorization": "Bearer " + token,
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return res.status, json.loads(res.read().decode())
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode())
        except Exception:
            payload = {}
        return exc.code, payload


def _order_one(base, token, person, encounter_id, test_id, key):
    status, payload = _post(base, token, "/api/lab/orders", {
        "patient_id": person, "encounter_id": encounter_id, "idempotency_key": key,
        "tests": [{"test_id": test_id}],
    })
    item = ((payload.get("data") or {}).get("items") or [{}])[0]
    return (payload.get("data") or {}).get("id"), item.get("id"), status


def _race(base, order_token, collect_token, person, encounter_id, test_id) -> dict:
    made = []
    for key in ("race-a", "race-b"):
        order_id, item_id, status = _order_one(base, order_token, person, encounter_id, test_id, key)
        made.append((order_id, item_id, status))
    accessions = []

    def collect(order_id, item_id, key):
        status, payload = _post(base, collect_token, f"/api/lab/orders/{order_id}/samples", {"item_ids": [item_id], "idempotency_key": key})
        accessions.append((status, (payload.get("data") or {}).get("accession_no")))

    threads = [threading.Thread(target=collect, args=(order_id, item_id, f"race-collect-{n}")) for n, (order_id, item_id, _) in enumerate(made)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    values = [item[1] for item in accessions if item[0] == 200 and item[1]]
    return {"distinct": len(set(values)) == 2, "count": len(values), "orders": [item[2] for item in made], "collect": [item[0] for item in accessions]}


def _many(base, order_token, collect_token, person, encounter_id, test_id, count: int) -> dict:
    made = []
    for n in range(count):
        order_id, item_id, status = _order_one(base, order_token, person, encounter_id, test_id, f"many-{n}")
        made.append((order_id, item_id, status))
    accessions = []

    def collect(order_id, item_id, key):
        status, payload = _post(base, collect_token, f"/api/lab/orders/{order_id}/samples", {"item_ids": [item_id], "idempotency_key": key})
        accessions.append((status, (payload.get("data") or {}).get("accession_no")))

    threads = [threading.Thread(target=collect, args=(order_id, item_id, f"many-collect-{n}")) for n, (order_id, item_id, _) in enumerate(made)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    values = [item[1] for item in accessions if item[0] == 200 and item[1]]
    return {"distinct": len(set(values)) == count, "count": len(values), "orders": [item[2] for item in made], "collect": [item[0] for item in accessions]}


def _clash(base, order_token, collect_token, person, encounter_id, test_id) -> dict:
    order_id, item_id, _ = _order_one(base, order_token, person, encounter_id, test_id, "clash-order")
    codes = []

    def collect(key):
        status, _ = _post(base, collect_token, f"/api/lab/orders/{order_id}/samples", {"item_ids": [item_id], "idempotency_key": key})
        codes.append(status)

    threads = [threading.Thread(target=collect, args=(f"clash-{n}",)) for n in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    status, payload = _post(base, collect_token, f"/api/lab/orders/{order_id}/samples", {"item_ids": [item_id], "idempotency_key": "clash-3"})
    codes.append(status)
    try:
        with urllib.request.urlopen(urllib.request.Request(base + f"/api/lab/orders/{order_id}", headers={"Authorization": "Bearer " + collect_token}), timeout=20) as order:
            body = json.loads(order.read().decode())["data"]
    except urllib.error.HTTPError:
        return {"ok": codes.count(200), "conflict": codes.count(409), "samples": -1}
    samples = body.get("samples") or []
    return {"ok": codes.count(200), "conflict": codes.count(409), "samples": len([item for item in samples if item.get("status") != "REJECTED"])}


def _same_key(base, order_token, collect_token, person, encounter_id, test_id) -> dict:
    order_id, item_id, _ = _order_one(base, order_token, person, encounter_id, test_id, "same-order")
    accessions = []

    def collect():
        status, payload = _post(base, collect_token, f"/api/lab/orders/{order_id}/samples", {"item_ids": [item_id], "idempotency_key": "same-collect"})
        accessions.append((status, (payload.get("data") or {}).get("accession_no")))

    threads = [threading.Thread(target=collect) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    req = urllib.request.Request(base + f"/api/lab/orders/{order_id}", headers={"Authorization": "Bearer " + collect_token})
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            samples = json.loads(res.read().decode())["data"].get("samples") or []
    except urllib.error.HTTPError:
        return {"samples": -1, "accession_count": len({item[1] for item in accessions if item[1]})}
    return {"samples": len(samples), "accession_count": len({item[1] for item in accessions if item[1]})}


def _verify_race(base, admin, lab, person, encounter_id, test_id) -> dict:
    order_id, item_id, _ = _order_one(base, admin, person, encounter_id, test_id, "verify-order")
    status, payload = _post(base, lab, f"/api/lab/orders/{order_id}/samples", {"item_ids": [item_id], "idempotency_key": "verify-collect"})
    sample_id = (payload.get("data") or {}).get("id")
    _post(base, lab, f"/api/lab/samples/{sample_id}/process", {"idempotency_key": "verify-process"})
    status, entered = _post(base, lab, f"/api/lab/items/{item_id}/result", {"value": "text result", "idempotency_key": "verify-enter"})
    result_id = (entered.get("data") or {}).get("id")
    codes = []

    def verify(key):
        status, _ = _post(base, admin, f"/api/lab/results/{result_id}/verify", {"idempotency_key": key})
        codes.append(status)

    threads = [threading.Thread(target=verify, args=(key,)) for key in ("verify-a", "verify-b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    req = urllib.request.Request(base + f"/api/lab/orders/{order_id}", headers={"Authorization": "Bearer " + admin})
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            item = json.loads(res.read().decode())["data"]["items"][0]
    except urllib.error.HTTPError:
        return {"ok": codes.count(200), "conflict": codes.count(409), "verified": -1}
    verified = len([row for row in item.get("results") or [] if row.get("status") == "VERIFIED"])
    return {"ok": codes.count(200), "conflict": codes.count(409), "verified": verified}


def _hear(base, lab, imran, patient_id) -> dict:
    found = {"lab": False, "imran": False}

    def listen(name, token):
        ticket = urllib.request.Request(
            base + "/api/auth/stream-ticket", data=b"{}", method="POST",
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + token},
        )
        try:
            with urllib.request.urlopen(ticket, timeout=10) as res:
                raw = json.loads(res.read().decode())["data"]["token"]
        except Exception:
            return
        req = urllib.request.Request(base + "/api/events?" + urllib.parse.urlencode({"token": raw}))
        try:
            with urllib.request.urlopen(req, timeout=8) as res:
                deadline = time.time() + 6
                while time.time() < deadline:
                    line = res.readline()
                    if not line:
                        break
                    if patient_id.encode() in line and b"lab.updated" in line:
                        found[name] = True
                        return
        except Exception:
            return

    threads = [threading.Thread(target=listen, args=("lab", lab)), threading.Thread(target=listen, args=("imran", imran))]
    for thread in threads:
        thread.start()
    time.sleep(0.6)
    return found, threads


def _wait_ready(proc, port) -> bool:
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


def _drain(proc) -> str:
    try:
        out, _ = proc.communicate(timeout=3)
    except Exception:
        out = ""
    return out or ""


def _free_port(preferred: int) -> int:
    for port in (preferred, preferred + 1, preferred + 11):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
        return port
    return preferred


def _write_report(failures: list[str], evidence: list[dict], version) -> None:
    by_section = {index: [] for index in range(1, 30)}
    for item in evidence:
        by_section.setdefault(item["section"], []).append(item)
    failed = [item for item in evidence if not item.get("ok")]
    decision = "PHASE 5 ACCEPTED" if not failures and evidence and not failed else "PHASE 5 NOT ACCEPTED"
    lines = [
        f"# {decision}",
        "",
        "Phase 5 laboratory workflow only. Phase 4 was not reopened. Phase 6 was not started.",
        "The billing engine remains the only financial source of truth. No laboratory payment table was added.",
        "",
        "Gate: real HTTP against a throwaway PostgreSQL database. The database URL is not recorded here.",
        f"Schema version observed: {version}.",
        f"Checks recorded: {len(evidence)}. Checks failed: {len(failed)}.",
        "",
    ]
    for index, title in enumerate(SECTIONS, start=1):
        rows = by_section.get(index) or []
        passed = sum(1 for row in rows if row.get("ok"))
        state = "PASS" if rows and passed == len(rows) else "FAIL"
        lines.append(f"## {index}. {title}")
        lines.append("")
        lines.append(f"Result: {state}. {passed} of {len(rows)} checks passed.")
        lines.append("")
        for row in rows:
            mark = "PASS" if row.get("ok") else "FAIL"
            detail = "" if row.get("ok") or not row.get("detail") else f" — {_sanitize(str(row.get('detail')))[:240]}"
            lines.append(f"- {mark}: {row['name']}{detail}")
        if not rows:
            lines.append("- FAIL: no check was recorded for this section")
        lines.append("")
    if failures:
        lines.append("## Failure detail")
        lines.append("")
        lines.extend(f"- {_sanitize(item)}" for item in failures)
        lines.append("")
    lines.append("Critical laboratory or financial failures were not skipped. A failed critical check is PHASE 5 NOT ACCEPTED.")
    lines.append("")
    REPORT.write_text("\n".join(lines), encoding="utf-8")
