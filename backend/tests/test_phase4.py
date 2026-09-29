"""Phase 4 financial gate. Real HTTP against throwaway PostgreSQL.

A critical failure means PHASE 4 NOT ACCEPTED. Checks are not weakened to pass.
"""

from __future__ import annotations

import json
import os
import secrets
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
REPORT = ROOT / "PHASE-4-ACCEPTANCE-REPORT.md"


def test_phase4_http_gate():
    url = (os.environ.get("AIPF_TEST_POSTGRES") or "").strip()
    if not url.startswith("postgres"):
        raise AssertionError("AIPF_TEST_POSTGRES must be a PostgreSQL URL for the Phase 4 gate")
    failures = _run(url)
    assert failures == [], failures


def _run(admin_url: str) -> list[str]:
    import psycopg

    password = secrets.token_urlsafe(18)
    os.environ["AIPF_SEED_PASSWORD"] = password
    db_name = "aipf_phase4"
    admin = psycopg.connect(admin_url, autocommit=True)
    admin.execute(f"DROP DATABASE IF EXISTS {db_name} WITH (FORCE)")
    admin.execute(f"CREATE DATABASE {db_name}")
    admin.close()
    target = admin_url.rsplit("/", 1)[0] + "/" + db_name
    previous = os.environ.get("AIPF_DATABASE_URL")
    os.environ["AIPF_DATABASE_URL"] = target
    port = 8797
    proc = None
    failures: list[str] = []
    evidence: list[dict] = []
    try:
        from aipf.db import apply_migrations, connect
        from aipf.seed import seed
        from aipf import core

        conn = connect()
        assert conn.dialect == "postgres"
        version = apply_migrations(conn)
        assert version >= 11, version
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
            failures.append("server did not start: " + _drain(proc)[-800:])
            _write_report(failures, evidence, version)
            return failures
        base = f"http://127.0.0.1:{port}"

        def check(name: str, cond: bool, detail: str = ""):
            evidence.append({"name": name, "ok": bool(cond)})
            if not cond:
                failures.append(name + (": " + detail if detail else ""))

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
                    payload = {"raw": blob[:200]}
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

        status, admin_token, admin_user = login("director")
        check("director login", status == 200 and bool(admin_token), str(status))
        status, doctor, _ = login("dr.anita")
        check("doctor login", status == 200 and bool(doctor))
        status, billing, billing_user = login("billing")
        check("billing login", status == 200 and bool(billing))
        status, pharmacy, _ = login("pharmacy")
        check("pharmacist login", status == 200 and bool(pharmacy))
        if not all([admin_token, doctor, billing, pharmacy]):
            _write_report(failures, evidence, version)
            return failures

        perms = billing_user.get("permissions") or []
        for code in (
            "payment.create", "payment.view", "payment.refund", "deposit.create", "deposit.allocate",
            "billing.edit", "billing.void", "billing.report", "financial_adjustment.create", "financial_adjustment.approve",
        ):
            check(f"billing role has {code}", code in perms)
        check("doctor has no payment.refund", "payment.refund" not in (login("dr.anita")[2].get("permissions") or []))
        check("authorization is not a role-name bypass", "role ==" not in (ROOT / "backend/aipf/billing.py").read_text())

        status, hidden = call("GET", "/api/invoices/INV-S1", doctor)
        check("doctor cannot open another patient's bill", status == 404, str(status) + " " + err(hidden))
        check("hidden bill does not leak the name", "Rajesh" not in json.dumps(hidden))
        status, seen = call("GET", "/api/invoices/INV-S1", billing)
        check("billing can open the same bill", status == 200 and data_of(seen).get("id") == "INV-S1", str(status))
        status, _ = call("POST", "/api/invoices/INV-S1/refund", doctor, {"amount_paise": 1, "reason": "no", "payment_id": "PAY-S1"})
        check("doctor refund is forbidden before business rules", status == 403, str(status))
        status, _ = call("POST", "/api/invoices/INV-S1/payments", doctor, {"mode": "Cash", "amount_paise": 1, "idempotency_key": "nope"})
        check("doctor cannot take payment", status == 403, str(status))
        status, dep_hidden = call("GET", "/api/deposits?patient_id=P-000001", doctor)
        check("doctor cannot list another patient's deposits", status == 404, str(status) + " " + err(dep_hidden))
        status, _ = call("GET", "/api/reports/billing", doctor)
        check("doctor cannot open the billing report", status == 403, str(status))
        status, report = call("GET", "/api/reports/billing", billing)
        check("billing report is permission gated", status == 200 and "items" in data_of(report), str(status))

        status, modes = call("GET", "/api/master/payment_mode", billing)
        mode_names = [item.get("name") for item in data_of(modes).get("items") or []]
        check("payment modes come from master data", status == 200 and "UPI" in mode_names and "Cash" in mode_names, str(mode_names))
        status, types = call("GET", "/api/master/deposit_type", billing)
        type_names = [item.get("name") for item in data_of(types).get("items") or []]
        check("deposit types come from master data", status == 200 and "Advance" in type_names, str(type_names))

        def patient(name, phone):
            status, payload = call("POST", "/api/patients", admin_token, {
                "name": name, "primary_phone": phone, "gender": "Female", "age_at_registration": 34, "confirm_new": True,
            })
            return status, data_of(payload).get("id"), payload

        status, pid, payload = patient("Phase Four Patient", "9811100001")
        check("register financial patient", status == 200 and bool(pid), err(payload))
        status, service = call("POST", "/api/services", admin_token, {
            "name": "Phase 4 dressing", "category": "HOSPITAL SERVICES", "rate_paise": 50000, "unit": "procedure",
        })
        service_id = data_of(service).get("id")
        check("create configured service", status == 200 and bool(service_id), err(service))
        status, invoice = call("POST", "/api/invoices", admin_token, {"patient_id": pid, "bill_type": "OPD"})
        inv_id = data_of(invoice).get("id")
        inv_no = data_of(invoice).get("number")
        check("open draft", status == 200 and bool(inv_id) and bool(inv_no), err(invoice))
        status, bad_tax = call("POST", f"/api/invoices/{inv_id}/items", admin_token, {
            "description": "Client tax", "category": "OTHER", "rate_paise": 1000, "qty": 1, "tax_paise": 180,
        })
        check("client tax amount is rejected", status == 400, str(status) + " " + err(bad_tax))
        status, added = call("POST", f"/api/invoices/{inv_id}/items", admin_token, {
            "description": "Phase 4 dressing", "category": "HOSPITAL SERVICES", "rate_paise": 1, "qty": 1,
            "source_module": "service", "master_item_id": service_id, "tax_code": "GST18",
        })
        line = next((item for item in data_of(added).get("items") or [] if item.get("master_item_id") == service_id), {})
        check("service rate is server snapshot not client rate", line.get("rate_paise") == 50000, str(line.get("rate_paise")))
        check("tax is integer bps from configured GST18", line.get("tax_paise") == 9000, str(line.get("tax_paise")))
        check("line amount is rate minus discount plus tax", line.get("amount_paise") == 59000, str(line.get("amount_paise")))
        status, no_reason = call("POST", f"/api/invoices/{inv_id}/discount", admin_token, {"discount_paise": 1000, "reason": ""})
        check("discount needs a reason", status == 400, str(status))
        status, too_big = call("POST", f"/api/invoices/{inv_id}/discount", admin_token, {"discount_paise": 999999, "reason": "too much"})
        check("discount cannot exceed the bill", status == 400, str(status) + " " + err(too_big))
        status, discounted = call("POST", f"/api/invoices/{inv_id}/discount", admin_token, {"discount_paise": 1000, "reason": "Staff concession"})
        check("configured discount applies", status == 200 and data_of(discounted).get("net_paise") == 58000, str(data_of(discounted).get("net_paise")))
        status, finalized = call("POST", f"/api/invoices/{inv_id}/finalize", admin_token, {})
        check("finalize", status == 200 and data_of(finalized).get("status") == "FINALIZED", err(finalized))
        status, edited = call("POST", f"/api/invoices/{inv_id}/items", admin_token, {
            "description": "Late line", "category": "OTHER", "rate_paise": 100, "qty": 1,
        })
        check("finalized bill rejects a new line", status == 400, str(status) + " " + err(edited))
        status, patched = call("PATCH", f"/api/services/{service_id}", admin_token, {
            "name": "Phase 4 dressing", "category": "HOSPITAL SERVICES", "rate_paise": 100, "unit": "procedure",
        })
        check("master service price can change", status == 200, str(status))
        status, after_price = call("GET", f"/api/invoices/{inv_id}", billing)
        frozen = next((item for item in data_of(after_price).get("items") or [] if item.get("master_item_id") == service_id), {})
        check("finalized line ignores a later master price", frozen.get("rate_paise") == 50000 and frozen.get("tax_paise") == 9000, str(frozen))
        check("invoice number is stable", data_of(after_price).get("number") == inv_no)

        status, missing_key = call("POST", f"/api/invoices/{inv_id}/payments", billing, {"mode": "UPI", "amount_paise": 10000})
        check("http payment requires an idempotency key", status == 400, str(status) + " " + err(missing_key))
        status, bad_mode = call("POST", f"/api/invoices/{inv_id}/payments", billing, {
            "mode": "Wallet-X", "amount_paise": 10000, "idempotency_key": "bad-mode",
        })
        check("unknown payment mode is rejected", status == 400, str(status) + " " + err(bad_mode))
        status, new_mode = call("POST", "/api/master/payment_mode", admin_token, {"name": "NEFT", "code": "NEFT"})
        check("new payment mode is configuration", status == 200, err(new_mode))
        status, zero = call("POST", f"/api/invoices/{inv_id}/payments", billing, {"mode": "NEFT", "amount_paise": 0, "idempotency_key": "zero"})
        check("zero payment rejected", status == 400, str(status))
        status, negative = call("POST", f"/api/invoices/{inv_id}/payments", billing, {"mode": "NEFT", "amount_paise": -1, "idempotency_key": "neg"})
        check("negative payment rejected", status == 400, str(status))
        status, first_pay = call("POST", f"/api/invoices/{inv_id}/payments", billing, {
            "mode": "upi", "amount_paise": 10000, "reference": "UPI-1", "idempotency_key": "pay-1",
        })
        first = data_of(first_pay)
        check("partial payment", status == 200 and first.get("paid_paise") == 10000 and first.get("due_paise") == 48000 and first.get("payment_status") == "PARTIAL", str(status) + " " + err(first_pay) + " " + str(first.get("due_paise")))
        check("mode is stored as configured name", any(p.get("mode") == "UPI" for p in first.get("payments") or []), str([p.get("mode") for p in first.get("payments") or []]))
        status, replay = call("POST", f"/api/invoices/{inv_id}/payments", billing, {
            "mode": "UPI", "amount_paise": 10000, "reference": "UPI-1", "idempotency_key": "pay-1",
        })
        check("payment retry is one row", status == 200 and data_of(replay).get("idempotent_replay") is True and data_of(replay).get("payment_id") == first.get("payment_id") and data_of(replay).get("paid_paise") == 10000, err(replay))
        status, over = call("POST", f"/api/invoices/{inv_id}/payments", billing, {
            "mode": "NEFT", "amount_paise": 48001, "idempotency_key": "over-1",
        })
        check("overpayment rejected", status == 409, str(status) + " " + err(over))
        status, rest = call("POST", f"/api/invoices/{inv_id}/payments", billing, {
            "mode": "NEFT", "amount_paise": 48000, "idempotency_key": "pay-2",
        })
        check("exact remaining payment marks paid", status == 200 and data_of(rest).get("payment_status") == "PAID" and data_of(rest).get("due_paise") == 0, err(rest))
        status, extra = call("POST", f"/api/invoices/{inv_id}/payments", billing, {
            "mode": "Cash", "amount_paise": 1, "idempotency_key": "extra",
        })
        check("payment on a settled bill is rejected", status == 409, str(status))

        pay_id = data_of(rest).get("payment_id")
        status, no_ref = call("POST", f"/api/invoices/{inv_id}/refund", billing, {
            "amount_paise": 1000, "mode": "NEFT", "reason": "missing link", "idempotency_key": "ref-missing",
        })
        check("refund must name the original payment", status == 400, str(status) + " " + err(no_ref))
        before_rows = len(data_of(rest).get("payments") or [])
        status, refunded = call("POST", f"/api/invoices/{inv_id}/refund", billing, {
            "payment_id": pay_id, "amount_paise": 5000, "mode": "NEFT", "reason": "Service not given", "idempotency_key": "ref-1",
        })
        ref = data_of(refunded)
        check("refund reduces paid and keeps the original", status == 200 and ref.get("paid_paise") == 53000 and ref.get("due_paise") == 5000 and any(p.get("id") == pay_id for p in ref.get("payments") or []), str(ref.get("paid_paise")) + " " + err(refunded))
        check("refund row references the payment", any(p.get("kind") == "REFUND" and p.get("reverses") == pay_id for p in ref.get("payments") or []))
        status, ref_replay = call("POST", f"/api/invoices/{inv_id}/refund", billing, {
            "payment_id": pay_id, "amount_paise": 5000, "mode": "NEFT", "reason": "Service not given", "idempotency_key": "ref-1",
        })
        check("refund retry does not double", status == 200 and data_of(ref_replay).get("idempotent_replay") is True and data_of(ref_replay).get("paid_paise") == 53000, err(ref_replay))
        status, too_much = call("POST", f"/api/invoices/{inv_id}/refund", billing, {
            "payment_id": pay_id, "amount_paise": 43001, "mode": "NEFT", "reason": "too much", "idempotency_key": "ref-too",
        })
        check("refund cannot exceed refundable remainder", status == 409, str(status) + " " + err(too_much))
        check("original payment was not deleted", any(p.get("id") == pay_id for p in data_of(ref_replay).get("payments") or []) and len(data_of(ref_replay).get("payments") or []) == before_rows + 1)

        status, seed_pay = call("POST", "/api/invoices/INV-S5/payments", billing, {
            "mode": "UPI", "amount_paise": 25000, "reference": "UPI-S5", "idempotency_key": "s5-exact",
        })
        check("seeded due can be paid exactly", status == 200 and data_of(seed_pay).get("payment_status") == "PAID" and data_of(seed_pay).get("due_paise") == 0, err(seed_pay))
        status, seed_over = call("POST", "/api/invoices/INV-S5/payments", billing, {
            "mode": "Cash", "amount_paise": 1, "idempotency_key": "s5-over",
        })
        check("seeded bill rejects a further rupee", status == 409, str(status))

        status, missing = call("POST", "/api/invoices/INV-DOES-NOT-EXIST/payments", billing, {
            "mode": "Cash", "amount_paise": 1, "idempotency_key": "missing",
        })
        check("missing invoice payment is not found", status == 404, str(status) + " " + err(missing))

        status, dep = call("POST", "/api/deposits", billing, {
            "patient_id": pid, "amount_paise": 20000, "mode": "Cash", "deposit_type": "Advance", "idempotency_key": "dep-1",
        })
        deposit = data_of(dep)
        check("deposit is not an invoice payment", status == 200 and deposit.get("invoice_id") in (None, "") and deposit.get("balance_paise") == 20000 and deposit.get("deposit_type") == "Advance", err(dep))
        status, dep_replay = call("POST", "/api/deposits", billing, {
            "patient_id": pid, "amount_paise": 20000, "mode": "Cash", "deposit_type": "Advance", "idempotency_key": "dep-1",
        })
        check("deposit create is idempotent", status == 200 and data_of(dep_replay).get("id") == deposit.get("id") and data_of(dep_replay).get("idempotent_replay") is True, err(dep_replay))
        status, untouched = call("GET", f"/api/invoices/{inv_id}", billing)
        check("deposit does not auto-apply", data_of(untouched).get("due_paise") == 5000, str(data_of(untouched).get("due_paise")))
        status, allocated = call("POST", f"/api/invoices/{inv_id}/deposit", billing, {
            "deposit_id": deposit.get("id"), "amount_paise": 3000, "idempotency_key": "alloc-1",
        })
        check("explicit allocation reduces due", status == 200 and data_of(allocated).get("due_paise") == 2000 and data_of(allocated).get("deposit_applied_paise") == 3000, err(allocated))
        status, listed = call("GET", f"/api/deposits?patient_id={pid}", billing)
        left = next((item for item in data_of(listed).get("items") or [] if item.get("id") == deposit.get("id")), {})
        check("deposit row remains with reduced balance", left.get("balance_paise") == 17000 and left.get("utilized_paise") == 3000, str(left))
        status, alloc_over = call("POST", f"/api/invoices/{inv_id}/deposit", billing, {
            "deposit_id": deposit.get("id"), "amount_paise": 2001, "idempotency_key": "alloc-over",
        })
        check("allocation cannot exceed due", status == 409, str(status) + " " + err(alloc_over))
        status, refund_dep = call("POST", f"/api/deposits/{deposit.get('id')}/refund", billing, {
            "reason": "Unused advance", "idempotency_key": "dep-ref-1",
        })
        check("unused deposit refund keeps the row", status == 200 and data_of(refund_dep).get("status") == "REFUNDED" and data_of(refund_dep).get("balance_paise") == 0 and data_of(refund_dep).get("id") == deposit.get("id"), err(refund_dep))

        status, void_blocked = call("POST", f"/api/invoices/{inv_id}/void", billing, {"reason": "mistake"})
        check("void blocked while money remains", status == 400, str(status) + " " + err(void_blocked))
        status, cleared = call("POST", f"/api/invoices/{inv_id}/refund", billing, {
            "payment_id": data_of(allocated).get("payment_id"), "amount_paise": 3000, "mode": "Cash", "reason": "Reverse allocation", "idempotency_key": "ref-alloc",
        })
        check("allocated deposit can be refunded on the bill", status == 200, err(cleared) or str(data_of(cleared).get("paid_paise")))

        numbers = _concurrent_numbers(base, admin_token)
        check("concurrent invoices get distinct numbers", len(numbers) == 6 and len(set(numbers)) == 6, str(numbers))
        raced = _race_payments(base, admin_token, pid)
        check("concurrent same key is one payment", raced.get("same_key_rows") == 1 and raced.get("same_key_ok") == 6, str(raced))
        check("concurrent overpay cannot exceed due", raced.get("over_ok") == 1 and raced.get("over_conflict") == 1 and raced.get("over_paid") == raced.get("over_net"), str(raced))

        heard = _hear(base, doctor, billing, pid)
        check("payment event carries patient_id to billing", heard.get("billing"), str(heard))
        check("payment event does not leak to the other doctor", not heard.get("doctor"), str(heard))

        status, pdf1 = call("GET", f"/api/invoices/{inv_id}/pdf", billing, raw=True)
        status2, pdf2 = call("GET", f"/api/invoices/{inv_id}/pdf", billing, raw=True)
        text = pdf1.decode("latin1", errors="ignore") if isinstance(pdf1, (bytes, bytearray)) else ""
        check("pdf is a real document", status == 200 and isinstance(pdf1, (bytes, bytearray)) and pdf1.startswith(b"%PDF"), str(status))
        check("pdf reprints do not change bytes while the bill is unchanged", pdf1 == pdf2, f"{len(pdf1) if isinstance(pdf1, bytes) else 0}/{len(pdf2) if isinstance(pdf2, bytes) else 0}")
        snap = data_of(call("GET", f"/api/invoices/{inv_id}", billing)[1])
        from aipf.util import format_inr_plain
        check("pdf amount matches the invoice api", format_inr_plain(snap.get("net_paise") or 0) in text and snap.get("number") in text, snap.get("number"))
        check("pdf draws the rupee glyph", b"/Filter /DCTDecode" in pdf1 and "Indian Rupees" in text)
        status, again = call("GET", f"/api/invoices/{inv_id}", billing)
        check("reprint does not change invoice rows", data_of(again).get("updated_at") == snap.get("updated_at") and data_of(again).get("net_paise") == snap.get("net_paise"))

        long_tail = "PHASE4-LONG-TAIL-XYZ"
        status, long_inv = call("POST", "/api/invoices", admin_token, {"patient_id": pid, "bill_type": "OPD"})
        long_id = data_of(long_inv).get("id")
        if data_of(long_inv).get("id") == inv_id:
            status, long_patient = patient("Phase Four Long", "9811100002")
            status, long_inv = call("POST", "/api/invoices", admin_token, {"patient_id": long_patient, "bill_type": "OPD"})
            long_id = data_of(long_inv).get("id")
        call("POST", f"/api/invoices/{long_id}/items", admin_token, {
            "description": ("Dressing note " * 12) + long_tail, "category": "OTHER", "rate_paise": 100, "qty": 1,
        })
        for n in range(42):
            call("POST", f"/api/invoices/{long_id}/items", admin_token, {
                "description": f"Paging line {n}", "category": "OTHER", "rate_paise": 100, "qty": 1,
            })
        call("POST", f"/api/invoices/{long_id}/finalize", admin_token, {})
        status, long_pdf = call("GET", f"/api/invoices/{long_id}/pdf", billing, raw=True)
        long_text = long_pdf.decode("latin1", errors="ignore") if isinstance(long_pdf, (bytes, bytearray)) else ""
        check("long description is wrapped into the pdf", isinstance(long_pdf, (bytes, bytearray)) and long_tail in long_text)
        check("long bill paginates", isinstance(long_pdf, (bytes, bytearray)) and long_pdf.count(b"/Type /Page") > 1, str(long_pdf.count(b"/Type /Page") if isinstance(long_pdf, (bytes, bytearray)) else 0))

        _module_snapshots(call, check, admin_token, billing, pharmacy, patient)
        _adjustment_and_audit(call, check, admin_token, billing, inv_id)

        direct = psycopg.connect(target)
        names = {row[0] for row in direct.execute("SELECT conname FROM pg_constraint").fetchall()}
        for name in (
            "invoices_status_check", "invoices_money_nonneg", "payments_amount_positive",
            "payments_kind_check", "deposits_balance_check", "financial_adjustments_status_check",
        ):
            check(f"postgres constraint {name}", name in names)
        index = direct.execute("SELECT indexname FROM pg_indexes WHERE indexname='uq_payments_idempotency'").fetchone()
        check("payment idempotency unique index", index is not None)
        direct.close()
    except Exception as exc:
        failures.append(f"gate crashed: {type(exc).__name__}: {exc}")
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
        _write_report(failures, evidence, locals().get("version"))
    return failures


def _module_snapshots(call, check, admin, billing, pharmacy, patient):
    status, person, _ = patient("Phase Four Modules", "9811100003")
    check("module patient", status == 200 and bool(person))
    status, opd_type = call("POST", "/api/opd/types", admin, {"name": "Phase 4 card", "fee_paise": 22000, "validity_days": 1})
    opd_id = (opd_type.get("data") or {}).get("id")
    status, visit = call("POST", "/api/visits", admin, {"patient_id": person, "opd_type_id": opd_id, "doctor_id": "U-ANITA", "queue": False})
    check("opd visit", status == 200, str(status) + " " + str((visit.get("error") or {}).get("message")))
    status, bills = call("GET", f"/api/invoices?patient_id={person}", billing)
    opd_bill = next((item for item in (bills.get("data") or {}).get("items") or [] if item.get("bill_type") == "OPD"), {})
    status, opd_full = call("GET", f"/api/invoices/{opd_bill.get('id')}", billing)
    opd_line = next((item for item in (opd_full.get("data") or {}).get("items") or [] if item.get("category") == "CONSULTATION"), {})
    check("opd fee snapshotted from the card", opd_line.get("rate_paise") == 22000, str(opd_line.get("rate_paise")))
    call("PATCH", f"/api/opd/types/{opd_id}", admin, {"name": "Phase 4 card", "fee_paise": 100, "validity_days": 1})
    status, opd_again = call("GET", f"/api/invoices/{opd_bill.get('id')}", billing)
    opd_line = next((item for item in (opd_again.get("data") or {}).get("items") or [] if item.get("category") == "CONSULTATION"), {})
    check("later opd fee does not rewrite the bill", opd_line.get("rate_paise") == 22000, str(opd_line.get("rate_paise")))

    status, lab = call("POST", "/api/lab/tests", admin, {"name": "Phase 4 CBC", "price_paise": 33000, "sample_type": "Blood"})
    lab_id = (lab.get("data") or {}).get("id")
    status, ordered = call("POST", "/api/lab/orders", admin, {"patient_id": person, "tests": [{"test_id": lab_id}]})
    check("lab order bills through the invoice", status == 200, str(status) + " " + str((ordered.get("error") or {}).get("message")))
    status, bills = call("GET", f"/api/invoices?patient_id={person}", billing)
    lab_bill_id = (bills.get("data") or {}).get("items", [{}])[0].get("id")
    status, lab_full = call("GET", f"/api/invoices/{lab_bill_id}", billing)
    lab_line = next((item for item in (lab_full.get("data") or {}).get("items") or [] if item.get("category") == "LABORATORY"), {})
    check("lab price snapshotted", lab_line.get("rate_paise") == 33000, str(lab_line.get("rate_paise")))
    call("PATCH", f"/api/lab/tests/{lab_id}", admin, {"name": "Phase 4 CBC", "price_paise": 100})
    status, lab_again = call("GET", f"/api/invoices/{lab_bill_id}", billing)
    lab_line = next((item for item in (lab_again.get("data") or {}).get("items") or [] if item.get("category") == "LABORATORY"), {})
    check("later lab price does not rewrite the bill", lab_line.get("rate_paise") == 33000, str(lab_line.get("rate_paise")))

    status, ward = call("POST", "/api/wards", admin, {"name": "Phase 4 ward", "code": "P4"})
    ward_id = (ward.get("data") or {}).get("id")
    status, room = call("POST", "/api/rooms", admin, {"ward_id": ward_id, "name": "P4 room", "daily_rate_paise": 75000})
    room_id = (room.get("data") or {}).get("id")
    status, bed = call("POST", "/api/beds", admin, {"room_id": room_id, "name": "P4 bed"})
    bed_id = (bed.get("data") or {}).get("id")
    status, ipd_person, _ = patient("Phase Four IPD", "9811100004")
    status, admitted = call("POST", "/api/admissions", admin, {
        "patient_id": ipd_person, "bed_id": bed_id, "doctor_id": "U-ANITA", "daily_rate_paise": 1,
    })
    ipd_invoice = (admitted.get("data") or {}).get("invoice_id")
    check("admission opens the central bill", status == 200 and bool(ipd_invoice), str(status) + " " + str((admitted.get("error") or {}).get("message")))
    status, ipd = call("GET", f"/api/invoices/{ipd_invoice}", billing)
    ipd_line = next((item for item in (ipd.get("data") or {}).get("items") or [] if item.get("category") == "IPD"), {})
    check("bed charge uses the room rate not the client rate", ipd_line.get("rate_paise") == 75000, str(ipd_line.get("rate_paise")))
    import psycopg
    pg = psycopg.connect(os.environ["AIPF_DATABASE_URL"])
    pg.execute("UPDATE rooms SET daily_rate_paise=100 WHERE id=%s", (room_id,))
    pg.commit()
    pg.close()
    status, ipd = call("GET", f"/api/invoices/{ipd_invoice}", billing)
    ipd_line = next((item for item in (ipd.get("data") or {}).get("items") or [] if item.get("category") == "IPD"), {})
    check("later room rate does not rewrite the bed line", ipd_line.get("rate_paise") == 75000, str(ipd_line.get("rate_paise")))

    status, proc = call("POST", "/api/master/procedure", admin, {"name": "Phase 4 procedure", "meta": {"fee_paise": 80000}})
    proc_id = (proc.get("data") or {}).get("id")
    status, case = call("POST", "/api/ot", admin, {"patient_id": person, "procedure_name": "Phase 4 procedure", "procedure_id": proc_id})
    ot_id = (case.get("data") or {}).get("id")
    status, notes = call("POST", f"/api/ot/{ot_id}/notes", admin, {
        "outcome": "SUCCESSFUL", "procedure_notes": "Completed without complication.", "fee_paise": 1,
    })
    check("ot notes accepted", status == 200, str(status) + " " + str((notes.get("error") or {}).get("message")))
    status, bills = call("GET", f"/api/invoices?patient_id={person}", billing)
    ot_rate = None
    for item in (bills.get("data") or {}).get("items") or []:
        status, full = call("GET", f"/api/invoices/{item.get('id')}", billing)
        for line in (full.get("data") or {}).get("items") or []:
            if line.get("category") == "OT":
                ot_rate = line.get("rate_paise")
    check("ot charge uses configured procedure fee", ot_rate == 80000, str(ot_rate))

    status, dispensed = call("POST", "/api/pharmacy/dispense", pharmacy, {
        "prescription_id": "RX-2026-000001",
        "lines": [{"item_id": "RI-1", "product_id": "PR-PARA", "batch_id": "BAT-PR-PARA", "qty": 1}],
        "idempotency_key": "phase4-dispense",
    })
    pharm_invoice = (dispensed.get("data") or {}).get("invoice_id")
    check("pharmacy bills the existing invoice", status == 200 and bool(pharm_invoice), str(status) + " " + str((dispensed.get("error") or {}).get("message")))
    status, pharm = call("GET", f"/api/invoices/{pharm_invoice}", billing)
    pharm_line = next((item for item in (pharm.get("data") or {}).get("items") or [] if item.get("category") == "PHARMACY"), {})
    check("pharmacy rate snapshotted from the batch", pharm_line.get("rate_paise") == 150, str(pharm_line.get("rate_paise")))
    pg = psycopg.connect(os.environ["AIPF_DATABASE_URL"])
    pg.execute("UPDATE batches SET sale_rate_paise=99999 WHERE id='BAT-PR-PARA'")
    pg.commit()
    pg.close()
    status, pharm = call("GET", f"/api/invoices/{pharm_invoice}", billing)
    pharm_line = next((item for item in (pharm.get("data") or {}).get("items") or [] if item.get("category") == "PHARMACY"), {})
    check("later batch price does not rewrite the pharmacy line", pharm_line.get("rate_paise") == 150, str(pharm_line.get("rate_paise")))


def _adjustment_and_audit(call, check, admin, billing, inv_id):
    status, person = call("POST", "/api/patients", admin, {
        "name": "Phase Four Void", "primary_phone": "9811100009", "gender": "Male", "age_at_registration": 50, "confirm_new": True,
    })
    void_patient = (person.get("data") or {}).get("id")
    status, draft = call("POST", "/api/invoices", admin, {"patient_id": void_patient, "bill_type": "OPD"})
    void_id = (draft.get("data") or {}).get("id")
    call("POST", f"/api/invoices/{void_id}/items", admin, {"description": "Void me", "category": "OTHER", "rate_paise": 500, "qty": 1})
    call("POST", f"/api/invoices/{void_id}/finalize", admin, {})
    status, voided = call("POST", f"/api/invoices/{void_id}/void", billing, {"reason": "Raised in error"})
    check("void preserves the bill", status == 200 and (voided.get("data") or {}).get("status") == "VOID", str(status) + " " + str((voided.get("error") or {}).get("message")))
    status, void_pay = call("POST", f"/api/invoices/{void_id}/payments", billing, {"mode": "Cash", "amount_paise": 500, "idempotency_key": "void-pay"})
    check("payment on a void bill is rejected", status == 400, str(status) + " " + str((void_pay.get("error") or {}).get("message")))
    status, still_void = call("GET", f"/api/invoices/{void_id}", billing)
    check("void bill is still stored", status == 200 and (still_void.get("data") or {}).get("status") == "VOID")
    status, roles = call("GET", "/api/roles", admin)
    billing_role = next(item for item in (roles.get("data") or {}).get("items") or [] if item.get("code") == "billing")
    original = billing_role.get("permissions") or []
    status, _ = call("PUT", "/api/roles/billing/permissions", admin, {"permissions": [p for p in original if p != "financial_adjustment.approve"]})
    before = call("GET", f"/api/invoices/{inv_id}", admin)[1]
    status, denied = call("POST", f"/api/invoices/{inv_id}/adjust", billing, {
        "amount_paise": -1000, "description": "Should not post", "reason": "No approval",
    })
    after = call("GET", f"/api/invoices/{inv_id}", admin)[1]
    check("adjustment without approval does not change the bill", status == 403 and (before.get("data") or {}).get("net_paise") == (after.get("data") or {}).get("net_paise"), str(status))
    call("PUT", "/api/roles/billing/permissions", admin, {"permissions": original})
    status, adjusted = call("POST", f"/api/invoices/{inv_id}/adjust", billing, {
        "amount_paise": -1000, "description": "Courtesy", "reason": "Approved concession",
    })
    check("approved adjustment posts on the same bill", status == 200 and any(i.get("category") == "ADJUSTMENT" for i in (adjusted.get("data") or {}).get("items") or []), str(status) + " " + str((adjusted.get("error") or {}).get("message")))
    status, missing = call("DELETE", f"/api/invoices/{inv_id}", admin)
    check("invoice cannot be physically deleted", status == 404, str(status))
    status, still = call("GET", f"/api/invoices/{inv_id}", billing)
    check("voided or adjusted bill remains readable", status == 200 and (still.get("data") or {}).get("id") == inv_id)
    status, audit_delete = call("DELETE", "/api/audit", admin)
    check("audit has no delete route", status == 404, str(status))
    import psycopg
    pg = psycopg.connect(os.environ["AIPF_DATABASE_URL"])
    actions = {row[0] for row in pg.execute("SELECT action FROM audit_logs").fetchall()}
    pg.close()
    for action in ("payment", "refund", "deposit", "invoice_finalize", "invoice_adjust"):
        check(f"audit {action}", action in actions, str(sorted(actions)[:12]))


def _concurrent_numbers(base, token) -> list[str]:
    numbers: list[str] = []
    lock = threading.Lock()

    def make(i):
        body = json.dumps({
            "name": f"Number Patient {i}", "primary_phone": f"98112000{i:02d}", "gender": "Male",
            "age_at_registration": 40, "confirm_new": True,
        }).encode()
        req = urllib.request.Request(base + "/api/patients", data=body, method="POST", headers={
            "Content-Type": "application/json", "Authorization": "Bearer " + token,
        })
        with urllib.request.urlopen(req, timeout=30) as res:
            pid = json.loads(res.read().decode())["data"]["id"]
        body = json.dumps({"patient_id": pid, "bill_type": "OPD"}).encode()
        req = urllib.request.Request(base + "/api/invoices", data=body, method="POST", headers={
            "Content-Type": "application/json", "Authorization": "Bearer " + token,
        })
        with urllib.request.urlopen(req, timeout=30) as res:
            number = json.loads(res.read().decode())["data"]["number"]
        with lock:
            numbers.append(number)

    threads = [threading.Thread(target=make, args=(i,)) for i in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return numbers


def _race_payments(base, token, patient_id) -> dict:
    def post(path, body):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode(), method="POST", headers={
            "Content-Type": "application/json", "Authorization": "Bearer " + token,
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                return res.status, json.loads(res.read().decode())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode())

    status, service = post("/api/services", {"name": "Race service", "category": "HOSPITAL SERVICES", "rate_paise": 20000, "unit": "unit"})
    service_id = service["data"]["id"]
    status, invoice = post("/api/invoices", {"patient_id": patient_id, "bill_type": "OPD"})
    same_id = invoice["data"]["id"]
    post(f"/api/invoices/{same_id}/items", {
        "description": "Race", "category": "HOSPITAL SERVICES", "source_module": "service", "master_item_id": service_id, "qty": 1,
    })
    post(f"/api/invoices/{same_id}/finalize", {})
    codes = []

    def pay_same():
        status, _ = post(f"/api/invoices/{same_id}/payments", {"mode": "Cash", "amount_paise": 20000, "idempotency_key": "race-same"})
        codes.append(status)

    threads = [threading.Thread(target=pay_same) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    status, same = post_get(base, token, f"/api/invoices/{same_id}")
    same_rows = len([p for p in same.get("payments") or [] if p.get("kind") == "PAYMENT"])

    status, other = post("/api/invoices", {"patient_id": patient_id, "bill_type": "OPD"})
    over_id = other["data"]["id"]
    post(f"/api/invoices/{over_id}/items", {
        "description": "Race over", "category": "HOSPITAL SERVICES", "source_module": "service", "master_item_id": service_id, "qty": 1,
    })
    post(f"/api/invoices/{over_id}/finalize", {})
    over_codes = []

    def pay_over(key):
        status, _ = post(f"/api/invoices/{over_id}/payments", {"mode": "UPI", "amount_paise": 20000, "idempotency_key": key})
        over_codes.append(status)

    pair = [threading.Thread(target=pay_over, args=(key,)) for key in ("over-a", "over-b")]
    for thread in pair:
        thread.start()
    for thread in pair:
        thread.join()
    status, over = post_get(base, token, f"/api/invoices/{over_id}")
    return {
        "same_key_ok": codes.count(200),
        "same_key_rows": same_rows,
        "over_ok": over_codes.count(200),
        "over_conflict": over_codes.count(409),
        "over_paid": over.get("paid_paise"),
        "over_net": over.get("net_paise"),
    }


def post_get(base, token, path):
    req = urllib.request.Request(base + path, headers={"Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=30) as res:
        return res.status, json.loads(res.read().decode())["data"]


def _hear(base, doctor, billing, patient_id) -> dict[str, bool]:
    found = {"billing": False, "doctor": False}

    def listen(name, token):
        ticket = urllib.request.Request(
            base + "/api/auth/stream-ticket", data=b"{}", method="POST",
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + token},
        )
        with urllib.request.urlopen(ticket, timeout=10) as res:
            raw = json.loads(res.read().decode())["data"]["token"]
        req = urllib.request.Request(base + "/api/events?" + urllib.parse.urlencode({"token": raw}))
        try:
            with urllib.request.urlopen(req, timeout=6) as res:
                deadline = time.time() + 5
                while time.time() < deadline:
                    line = res.readline()
                    if not line:
                        break
                    if patient_id.encode() in line and b"invoice.updated" in line:
                        found[name] = True
                        return
        except Exception:
            return

    threads = [
        threading.Thread(target=listen, args=("billing", billing)),
        threading.Thread(target=listen, args=("doctor", doctor)),
    ]
    for thread in threads:
        thread.start()
    time.sleep(0.8)
    body = json.dumps({
        "mode": "Cash", "amount_paise": 100, "idempotency_key": "sse-pay",
    }).encode()
    # The hidden patient already has a finalized bill with due from the main flow only if pid matches.
    # Open a fresh finalized bill for this patient inside the listener window.
    req = urllib.request.Request(
        base + "/api/invoices", data=json.dumps({"patient_id": patient_id, "bill_type": "OPD"}).encode(),
        method="POST", headers={"Content-Type": "application/json", "Authorization": "Bearer " + billing},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            invoice_id = json.loads(res.read().decode())["data"]["id"]
        item = json.dumps({"description": "SSE line", "category": "OTHER", "rate_paise": 100, "qty": 1}).encode()
        urllib.request.urlopen(urllib.request.Request(
            base + f"/api/invoices/{invoice_id}/items", data=item, method="POST",
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + billing},
        ), timeout=20).read()
        urllib.request.urlopen(urllib.request.Request(
            base + f"/api/invoices/{invoice_id}/finalize", data=b"{}", method="POST",
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + billing},
        ), timeout=20).read()
        urllib.request.urlopen(urllib.request.Request(
            base + f"/api/invoices/{invoice_id}/payments", data=body, method="POST",
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + billing},
        ), timeout=20).read()
    except Exception:
        pass
    for thread in threads:
        thread.join(timeout=8)
    return found


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
            time.sleep(0.4)
    return False


def _drain(proc) -> str:
    try:
        out, _ = proc.communicate(timeout=3)
    except Exception:
        out = ""
    return out or ""


def _write_report(failures: list[str], evidence: list[dict], version) -> None:
    passed = sum(1 for item in evidence if item.get("ok"))
    failed = [item["name"] for item in evidence if not item.get("ok")]
    decision = "PHASE 4 ACCEPTED" if not failures else "PHASE 4 NOT ACCEPTED"
    lines = [
        f"# {decision}",
        "",
        "Gate: real HTTP against a throwaway PostgreSQL database, plus the checks below.",
        "The database URL is not recorded here.",
        "",
        f"Schema version observed: {version}.",
        f"Checks passed: {passed}. Checks failed: {len(failed)}.",
        "",
    ]
    if failed:
        lines.append("Failed checks:")
        lines.extend(f"- {name}" for name in failed)
        lines.append("")
    if failures:
        lines.append("Failure detail:")
        lines.extend(f"- {item}" for item in failures)
        lines.append("")
    lines.append("Critical invariants covered: server totals, integer paise, snapshotted rates, draft/finalize/void, no overpay, idempotent payments and refunds, deposits separate from invoice payments, configured modes and tax, invoice numbers, permissions, record scope, audit retention, one PDF document, PostgreSQL checks.")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
