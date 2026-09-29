"""Phase 3: prescription, pharmacy, barcode, and inventory over real HTTP."""

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
MARKER = "PHASE3-NOTE-ALPHA"


def test_phase3_http_workflow():
    url = (os.environ.get("AIPF_TEST_POSTGRES") or os.environ.get("AIPF_DATABASE_URL") or "").strip()
    if not url.startswith("postgres"):
        if os.environ.get("PHASE3_REQUIRE_POSTGRES") == "1":
            raise AssertionError("PostgreSQL URL is required for the Phase 3 workflow")
        print("skip phase3 http: PostgreSQL URL is not set")
        return
    failures = _run(url)
    assert failures == [], failures


def _run(admin_url: str) -> list[str]:
    import psycopg

    password = secrets.token_urlsafe(18)
    os.environ["AIPF_SEED_PASSWORD"] = password
    db_name = "aipf_phase3"
    admin = psycopg.connect(admin_url, autocommit=True)
    admin.execute(f"DROP DATABASE IF EXISTS {db_name} WITH (FORCE)")
    admin.execute(f"CREATE DATABASE {db_name}")
    admin.close()
    target = admin_url.rsplit("/", 1)[0] + "/" + db_name
    previous = os.environ.get("AIPF_DATABASE_URL")
    os.environ["AIPF_DATABASE_URL"] = target
    port = 8796
    proc = None
    failures: list[str] = []
    try:
        from aipf.db import apply_migrations, connect
        from aipf.seed import seed
        from aipf import core

        conn = connect()
        assert conn.dialect == "postgres"
        assert apply_migrations(conn) >= 9
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
            detail = ""
            if proc.poll() is not None and proc.stdout is not None:
                detail = _redact(proc.stdout.read() or "")[-800:]
            failures.append("server did not start " + detail)
            return failures
        base = f"http://127.0.0.1:{port}"

        def check(name: str, cond: bool, detail: str = ""):
            if not cond:
                failures.append(name + (": " + detail if detail else ""))

        def call(method, path, token=None, body=None, headers=None):
            data = None if body is None else json.dumps(body).encode()
            req = urllib.request.Request(base + path, data=data, method=method)
            if body is not None:
                req.add_header("Content-Type", "application/json")
            if token:
                req.add_header("Authorization", "Bearer " + token)
            for key, value in (headers or {}).items():
                req.add_header(key, value)
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
            data = (payload or {}).get("data") or {}
            return status, data.get("token"), data.get("user") or {}

        def data_of(payload):
            return (payload or {}).get("data") or {}

        def err_of(payload):
            return (payload or {}).get("error") or {}

        status, pharmacy, pharm_user = login("pharmacy")
        check("pharmacist login", status == 200 and bool(pharmacy), str(status))
        status, doctor, _ = login("dr.anita")
        check("doctor login", status == 200 and bool(doctor), str(status))
        status, other, _ = login("dr.imran")
        check("other doctor login", status == 200 and bool(other), str(status))
        status, director, _ = login("director")
        check("director login", status == 200 and bool(director), str(status))
        status, reception, _ = login("reception")
        check("reception login", status == 200 and bool(reception), str(status))
        if failures:
            return failures

        check("pharmacist has no inventory.adjust", "inventory.adjust" not in (pharm_user.get("permissions") or []))
        check("pharmacist can dispense", "pharmacy.dispense" in (pharm_user.get("permissions") or []))
        check("pharmacist can edit inventory", "inventory.edit" in (pharm_user.get("permissions") or []))

        status, types = call("GET", "/api/inventory/barcode-types", pharmacy)
        codes = {item.get("code") for item in data_of(types).get("items", [])}
        check("barcode types come from configuration", status == 200 and {"EAN-13", "CODE-128", "QR", "INTERNAL"} <= codes, str(codes))
        status, added = call("POST", "/api/inventory/barcode-types", director, {"code": "hospital-shelf", "name": "Shelf label"})
        check("a new barcode type can be configured", status == 200 and any(item.get("code") == "HOSPITAL-SHELF" for item in data_of(added).get("items", [])), str(status))

        before_products = _count(target, "SELECT COUNT(*) FROM products")
        before_moves = _count(target, "SELECT COUNT(*) FROM stock_movements")
        status, unknown = call("POST", "/api/inventory/barcodes/resolve", pharmacy, {"code": "NO-SUCH-SCAN"})
        check("unknown barcode is rejected", status == 404 and err_of(unknown).get("code") == "not_found", str(status))
        check("unknown barcode creates no product", _count(target, "SELECT COUNT(*) FROM products") == before_products)
        check("unknown barcode creates no movement", _count(target, "SELECT COUNT(*) FROM stock_movements") == before_moves)
        status, received_unknown = call("POST", "/api/inventory/receive", pharmacy, {"barcode": "NO-SUCH-SCAN", "qty": 5, "batch_no": "X", "mfg_date": "2026-01-01", "expiry_date": "2028-01-01"})
        check("unknown scan cannot receive stock", status == 404, str(status) + " " + err_of(received_unknown).get("message", ""))
        check("failed receive created no product", _count(target, "SELECT COUNT(*) FROM products") == before_products)

        nonbase = _count(target, "SELECT COUNT(*) FROM packaging_skus WHERE units_per_pack <> 1")
        check("seed pack text did not become a conversion", nonbase == 0, str(nonbase))
        status, resolved = call("POST", "/api/inventory/barcodes/resolve", pharmacy, {"code": "AIPFPARA500"})
        hit = data_of(resolved)
        check("manufacturer barcode resolves the package", status == 200 and (hit.get("product") or {}).get("id") == "PR-PARA", str(status))
        check("barcode is not treated as the batch", hit.get("matched_batch") is None and (hit.get("barcode") or {}).get("scope") == "SKU")
        check("base package size is the stored 1", (hit.get("sku") or {}).get("units_per_pack") == 1)
        check("resolve does not dispense", hit.get("dispensed") is False and _count(target, "SELECT COUNT(*) FROM stock_movements") == before_moves)
        suggestions = hit.get("suggestions") or []
        check("resolve suggests usable batches only", suggestions and all(item.get("qty_on_hand", 0) > 0 for item in suggestions))
        status, cet = call("POST", "/api/inventory/barcodes/resolve", pharmacy, {"code": "AIPFCET10"})
        cet_batches = [item.get("batch_no") for item in data_of(cet).get("suggestions") or []]
        check("expired batch is not the scan selection", status == 200 and "B-CET-OLD" not in cet_batches, str(cet_batches))

        status, sku = call("POST", "/api/inventory/skus", pharmacy, {
            "product_id": "PR-PARA",
            "name": "Strip",
            "unit": "Strip",
            "units_per_pack": 10,
        })
        sku_id = data_of(sku).get("id")
        check("package conversion is stored only when entered", status == 200 and data_of(sku).get("units_per_pack") == 10, str(status))
        status, missing_size = call("POST", "/api/inventory/skus", pharmacy, {"product_id": "PR-PARA", "name": "Box", "unit": "Box"})
        check("package size is not assumed", status == 400, str(status))
        status, code = call("POST", "/api/inventory/barcodes", pharmacy, {
            "sku_id": sku_id,
            "value": "STRIP-PARA-3",
            "barcode_type": "CODE-128",
            "scope": "SKU",
        })
        check("barcode is registered against the package", status == 200 and data_of(code).get("scope") == "SKU", str(status) + " " + err_of(code).get("message", ""))
        status, bad_type = call("POST", "/api/inventory/barcodes", pharmacy, {
            "sku_id": sku_id,
            "value": "STRIP-PARA-OTHER",
            "barcode_type": "NOT-A-TYPE",
            "scope": "SKU",
        })
        check("unconfigured barcode type is rejected", status == 400 and err_of(bad_type).get("code") == "barcode_type", str(status))
        other_sku = _one(target, "SELECT id FROM packaging_skus WHERE product_id=%s AND units_per_pack=1", ("PR-PAN",))
        status, dup = call("POST", "/api/inventory/barcodes", pharmacy, {
            "sku_id": other_sku,
            "value": "STRIP-PARA-3",
            "barcode_type": "CODE-128",
            "scope": "SKU",
        })
        check("one active barcode cannot point at two packages", status == 409 and err_of(dup).get("code") == "ambiguous_barcode", str(status) + " " + err_of(dup).get("message", ""))
        moves_before_scan = _count(target, "SELECT COUNT(*) FROM stock_movements")
        status, strip = call("POST", "/api/inventory/barcodes/resolve", pharmacy, {"code": "STRIP-PARA-3"})
        check("strip barcode resolves that package", status == 200 and (data_of(strip).get("sku") or {}).get("units_per_pack") == 10, str(status))
        check("strip scan does not multiply or move stock", _count(target, "SELECT COUNT(*) FROM stock_movements") == moves_before_scan)

        para_before = _qty(target, "BAT-PR-PARA")
        status, receipt = call("POST", "/api/inventory/receive", pharmacy, {
            "barcode": "STRIP-PARA-3",
            "batch_no": "B-PARA-RECV",
            "mfg_date": "2026-02-01",
            "expiry_date": "2028-02-01",
            "qty": 3,
        })
        check("receive uses the resolved product and an explicit quantity", status == 200 and data_of(receipt).get("received_qty") == 3 and data_of(receipt).get("created_product") is False, str(status) + " " + err_of(receipt).get("message", ""))
        recv_batch = (data_of(receipt).get("batch") or {}).get("id")
        check("receive wrote a purchase movement, not a silent overwrite", _count(target, "SELECT COUNT(*) FROM stock_movements WHERE batch_id=%s AND movement_type='PURCHASE'", (recv_batch,)) == 1)
        check("receive did not apply the strip size silently", _qty(target, recv_batch) == 3, str(_qty(target, recv_batch)))
        check("opening batch was not overwritten", _qty(target, "BAT-PR-PARA") == para_before)

        status, batch_code = call("POST", "/api/inventory/barcodes", pharmacy, {
            "sku_id": sku_id,
            "value": "BATCH-PARA-RECV",
            "barcode_type": "INTERNAL",
            "scope": "BATCH",
            "batch_id": recv_batch,
        })
        check("explicit batch barcode can be registered", status == 200 and data_of(batch_code).get("scope") == "BATCH", err_of(batch_code).get("message", ""))
        moves_before_batch_scan = _count(target, "SELECT COUNT(*) FROM stock_movements")
        status, batch_hit = call("POST", "/api/inventory/barcodes/resolve", pharmacy, {"code": "BATCH-PARA-RECV"})
        check("batch barcode identifies the batch and still does not dispense", status == 200 and (data_of(batch_hit).get("matched_batch") or {}).get("id") == recv_batch and _count(target, "SELECT COUNT(*) FROM stock_movements") == moves_before_batch_scan)

        phone = "93" + secrets.token_hex(3)
        status, visit = call("POST", "/api/visits", reception, {
            "name": "Phase Three Patient",
            "primary_phone": phone,
            "gender": "Female",
            "age_at_registration": 36,
            "confirm_new": True,
            "opd_type_id": "OTY-GEN",
            "doctor_id": "U-ANITA",
            "chief_complaint": "Needs medicine",
            "queue": True,
        })
        encounter = data_of(visit).get("encounter") or {}
        patient = data_of(visit).get("patient") or {}
        check("visit opens the consultation", status == 200 and encounter.get("id") and patient.get("id"), err_of(visit).get("message", ""))
        if not encounter.get("id"):
            return failures
        status, note = call("POST", "/api/consultations", doctor, {
            "encounter_id": encounter["id"],
            "symptoms": MARKER + " headache",
            "diagnosis": "Tension headache",
        })
        check("doctor writes the consultation", status == 200, err_of(note).get("message", ""))
        status, draft = call("POST", "/api/prescriptions", doctor, {
            "encounter_id": encounter["id"],
            "patient_id": "P-000001",
            "doctor_id": "U-IMRAN",
            "items": [{"product_id": "PR-PARA", "medicine_name": "Paracetamol", "strength": "500 mg", "dose": "1-0-1", "quantity": 10, "unit": "Tablet"}],
        })
        check("prescription ignores a mismatched patient and doctor", status == 403, str(status))
        status, draft = call("POST", "/api/prescriptions", doctor, {
            "encounter_id": encounter["id"],
            "items": [{"product_id": "PR-PARA", "medicine_name": "Paracetamol", "strength": "500 mg", "dose": "1-0-1", "quantity": 10, "unit": "Tablet"}],
        })
        rx = data_of(draft)
        item_id = ((rx.get("items") or [{}])[0]).get("id")
        check("doctor saves a draft prescription", status == 200 and rx.get("status") == "DRAFT" and item_id, err_of(draft).get("message", ""))
        status, stolen = call("PUT", f"/api/prescriptions/{rx.get('id')}", doctor, {
            "patient_id": "P-000001",
            "encounter_id": encounter["id"],
            "doctor_id": "U-ANITA",
            "items": [{"product_id": "PR-PARA", "medicine_name": "Paracetamol", "quantity": 10, "unit": "Tablet"}],
        })
        check("owner cannot reassign the prescription patient", status == 403, str(status))
        status, hidden = call("GET", f"/api/prescriptions/{rx.get('id')}", other)
        check("other doctor cannot open the prescription", status == 404, str(status))
        status, foreign_final = call("POST", f"/api/prescriptions/{rx.get('id')}/finalize", other, {})
        check("other doctor cannot finalize it", status == 403, str(status))
        stock_before = _qty(target, "BAT-PR-PARA")
        status, final = call("POST", f"/api/prescriptions/{rx.get('id')}/finalize", doctor, {})
        check("doctor finalizes the prescription", status == 200 and data_of(final).get("status") == "FINALIZED", err_of(final).get("message", ""))
        check("finalizing does not reduce stock", _qty(target, "BAT-PR-PARA") == stock_before, str(_qty(target, "BAT-PR-PARA")))
        status, queue = call("GET", "/api/pharmacy/queue", pharmacy)
        queued = data_of(queue)
        check("pharmacy queue shows the finalized prescription", status == 200 and any(item.get("id") == rx.get("id") for item in queued.get("items", [])))
        blob = json.dumps(queued)
        check("pharmacy queue has no phone and no consultation note", phone not in blob and "primary_phone" not in blob and MARKER not in blob)
        status, denied_queue = call("GET", "/api/pharmacy/queue", doctor)
        check("doctor cannot open the pharmacy queue", status == 403, str(status))
        status, early = call("POST", "/api/pharmacy/dispense", pharmacy, {"prescription_id": "RX-MISSING", "lines": [{"item_id": "x", "qty": 1}]}, {"Idempotency-Key": "missing-rx"})
        check("dispense without a key is rejected", call("POST", "/api/pharmacy/dispense", pharmacy, {"prescription_id": rx.get("id"), "lines": [{"item_id": item_id, "qty": 1, "product_id": "PR-PARA", "batch_id": "BAT-PR-PARA"}]})[0] == 400)
        check("doctor cannot dispense", call("POST", "/api/pharmacy/dispense", doctor, {"prescription_id": rx.get("id"), "lines": [{"item_id": item_id, "qty": 1}]}, {"Idempotency-Key": "doctor-try"})[0] == 403)

        heard = _hear(base, pharmacy, other, rx.get("id"), item_id, patient.get("id"))
        check("pharmacist hears the dispense event", heard["pharmacy"] and heard["patient"] and not heard["leaked"])
        check("other doctor does not hear the patient event", not heard["other"])
        check("partial dispense leaves the remainder", heard["status"] == 200 and data_of(heard["payload"]).get("prescription", {}).get("status") == "PARTIAL", str(heard["status"]) + " " + err_of(heard["payload"]).get("message", ""))
        check("partial dispense reduced stock by the confirmed quantity", _qty(target, "BAT-PR-PARA") == stock_before - 4, str(_qty(target, "BAT-PR-PARA")))
        dispense_rows = _count(target, "SELECT COUNT(*) FROM dispense_lines WHERE prescription_id=%s", (rx.get("id"),))
        invoice_id = data_of(heard["payload"]).get("invoice_id")
        status, again = call("POST", "/api/pharmacy/dispense", pharmacy, {
            "prescription_id": rx.get("id"),
            "lines": [{"item_id": item_id, "qty": 4, "product_id": "PR-PARA", "batch_id": "BAT-PR-PARA"}],
        }, {"Idempotency-Key": heard["key"]})
        check("same dispense key returns the same result", status == 200 and data_of(again).get("idempotent_replay") is True, str(status))
        check("retry does not dispense again", _count(target, "SELECT COUNT(*) FROM dispense_lines WHERE prescription_id=%s", (rx.get("id"),)) == dispense_rows)
        check("retry does not reduce stock again", _qty(target, "BAT-PR-PARA") == stock_before - 4)
        status, clash = call("POST", "/api/pharmacy/dispense", pharmacy, {
            "prescription_id": rx.get("id"),
            "lines": [{"item_id": item_id, "qty": 1, "product_id": "PR-PARA", "batch_id": "BAT-PR-PARA"}],
        }, {"Idempotency-Key": heard["key"]})
        check("same key with a different payload is rejected", status == 409 and err_of(clash).get("code") == "idempotency_conflict", str(status))
        status, too_much = call("POST", "/api/pharmacy/dispense", pharmacy, {
            "prescription_id": rx.get("id"),
            "lines": [{"item_id": item_id, "qty": 7, "product_id": "PR-PARA", "batch_id": "BAT-PR-PARA"}],
        }, {"Idempotency-Key": "phase3-too-much"})
        check("dispense cannot exceed the prescribed remainder", status == 400, str(status) + " " + err_of(too_much).get("message", ""))
        status, rest = call("POST", "/api/pharmacy/dispense", pharmacy, {
            "prescription_id": rx.get("id"),
            "lines": [{"item_id": item_id, "qty": 6, "product_id": "PR-PARA", "batch_id": "BAT-PR-PARA"}],
        }, {"Idempotency-Key": "phase3-rest"})
        check("remainder can be dispensed later", status == 200 and data_of(rest).get("prescription", {}).get("status") == "DISPENSED", err_of(rest).get("message", ""))
        check("full quantity was not exceeded", _qty(target, "BAT-PR-PARA") == stock_before - 10)
        status, gone = call("GET", "/api/pharmacy/queue", pharmacy)
        check("completed prescription leaves the queue", all(item.get("id") != rx.get("id") for item in data_of(gone).get("items", [])))

        status, bill = call("GET", f"/api/invoices/{invoice_id}", pharmacy)
        invoice = data_of(bill)
        pharmacy_lines = [item for item in invoice.get("items", []) if item.get("category") == "PHARMACY"]
        check("dispense adds a draft charge, not a second billing system", status == 200 and invoice.get("status") == "DRAFT" and invoice.get("patient_id") == patient.get("id") and invoice.get("encounter_id") == encounter.get("id"), str(invoice.get("status")))
        check("charge snapshots rate, product, and quantity", pharmacy_lines and pharmacy_lines[0].get("rate_paise") == 150 and pharmacy_lines[0].get("qty") == 4 and pharmacy_lines[0].get("master_item_id") == "PR-PARA")
        _exec(target, "UPDATE products SET sale_rate_paise=99999 WHERE id='PR-PARA'")
        _exec(target, "UPDATE batches SET sale_rate_paise=88888 WHERE id='BAT-PR-PARA'")
        status, bill_again = call("GET", f"/api/invoices/{invoice_id}", pharmacy)
        still = [item for item in data_of(bill_again).get("items", []) if item.get("category") == "PHARMACY"]
        check("later price changes do not rewrite the charge", still and still[0].get("rate_paise") == 150)

        sub = _prescribe(call, doctor, reception, "Substitution Patient", [{"product_id": "PR-PARA", "medicine_name": "Paracetamol", "quantity": 2, "unit": "Tablet"}])
        check("substitution visit", bool(sub.get("item_id")), sub.get("error", ""))
        pan_before = _qty(target, "BAT-PR-PAN")
        para_now = _qty(target, "BAT-PR-PARA")
        status, mismatch = call("POST", "/api/pharmacy/dispense", pharmacy, {
            "prescription_id": sub.get("rx_id"),
            "lines": [{"item_id": sub.get("item_id"), "qty": 2, "product_id": "PR-PAN", "batch_id": "BAT-PR-PAN"}],
        }, {"Idempotency-Key": "phase3-mismatch"})
        check("wrong product is not a silent substitution", status == 409 and err_of(mismatch).get("code") == "product_mismatch", str(status))
        check("rejected substitution did not move stock", _qty(target, "BAT-PR-PAN") == pan_before and _qty(target, "BAT-PR-PARA") == para_now)
        status, no_reason = call("POST", "/api/pharmacy/dispense", pharmacy, {
            "prescription_id": sub.get("rx_id"),
            "lines": [{"item_id": sub.get("item_id"), "qty": 2, "product_id": "PR-PAN", "batch_id": "BAT-PR-PAN", "substituted": True}],
        }, {"Idempotency-Key": "phase3-no-reason"})
        check("substitution without a reason is rejected", status == 400, str(status))
        status, swapped = call("POST", "/api/pharmacy/dispense", pharmacy, {
            "prescription_id": sub.get("rx_id"),
            "lines": [{"item_id": sub.get("item_id"), "qty": 2, "product_id": "PR-PAN", "batch_id": "BAT-PR-PAN", "substituted": True, "substitution_reason": "Prescribed pack out of stock"}],
        }, {"Idempotency-Key": "phase3-sub"})
        swapped_rx = data_of(swapped).get("prescription") or {}
        swapped_item = (swapped_rx.get("items") or [{}])[0]
        check("explicit substitution dispenses the chosen product", status == 200 and _qty(target, "BAT-PR-PAN") == pan_before - 2, err_of(swapped).get("message", ""))
        check("substitution does not rewrite the prescribed name", swapped_item.get("medicine_name") == "Paracetamol" and swapped_item.get("product_id") == "PR-PARA", str(swapped_item.get("medicine_name")))

        loose = _product_with_stock(call, pharmacy, "Loose tablets", 8)
        loose_codes = _count(target, "SELECT COUNT(*) FROM barcodes b JOIN packaging_skus s ON s.id=b.sku_id WHERE s.product_id=%s", (loose.get("product_id"),))
        check("product can exist with no barcode", loose.get("batch_id") and loose_codes == 0, str(loose) + " codes " + str(loose_codes))
        loose_rx = _prescribe(call, doctor, reception, "No Barcode Patient", [{"product_id": loose.get("product_id"), "medicine_name": "Loose tablets", "quantity": 2, "unit": "Tablet"}])
        status, loose_disp = call("POST", "/api/pharmacy/dispense", pharmacy, {
            "prescription_id": loose_rx.get("rx_id"),
            "lines": [{"item_id": loose_rx.get("item_id"), "qty": 2, "product_id": loose.get("product_id"), "batch_id": loose.get("batch_id")}],
        }, {"Idempotency-Key": "phase3-loose"})
        check("dispense does not require a barcode", status == 200 and _qty(target, loose.get("batch_id")) == 6, err_of(loose_disp).get("message", ""))

        dated = _product_with_stock(call, pharmacy, "Dated tablets", 4, expiry="2027-01-15", batch_no="SOON")
        later = call("POST", "/api/inventory/receive", pharmacy, {
            "product_id": dated.get("product_id"),
            "batch_no": "LATER",
            "mfg_date": "2026-03-01",
            "expiry_date": "2028-06-01",
            "qty": 4,
        })
        later_id = (data_of(later[1]).get("batch") or {}).get("id")
        _exec(target, "INSERT INTO packaging_skus(id, product_id, name, unit, units_per_pack, active, created_at, updated_at) VALUES (%s, %s, 'Base', 'Tablet', 1, 1, '2026-09-01', '2026-09-01')", ("SKU-DATED", dated.get("product_id")))
        _exec(target, "INSERT INTO barcodes(id, sku_id, value, barcode_type, scope, active, created_at, updated_at) VALUES ('BC-DATED', 'SKU-DATED', 'DATED-SCAN', 'INTERNAL', 'SKU', 1, '2026-09-01', '2026-09-01')")
        status, ordered = call("POST", "/api/inventory/barcodes/resolve", pharmacy, {"code": "DATED-SCAN"})
        first = ((data_of(ordered).get("suggestions") or [{}])[0]).get("batch_no")
        check("FEFO suggestion is the earlier usable batch", status == 200 and first == "SOON", str(first))
        dated_rx = _prescribe(call, doctor, reception, "FEFO Patient", [{"product_id": dated.get("product_id"), "medicine_name": "Dated tablets", "quantity": 1, "unit": "Tablet"}])
        status, chose_later = call("POST", "/api/pharmacy/dispense", pharmacy, {
            "prescription_id": dated_rx.get("rx_id"),
            "lines": [{"item_id": dated_rx.get("item_id"), "qty": 1, "product_id": dated.get("product_id"), "batch_id": later_id}],
        }, {"Idempotency-Key": "phase3-later"})
        check("pharmacist may confirm a later valid batch", status == 200 and _qty(target, later_id) == 3, err_of(chose_later).get("message", ""))
        _exec(target, "UPDATE batches SET expiry_date='2020-01-01' WHERE id=%s", (dated.get("batch_id"),))
        expired_rx = _prescribe(call, doctor, reception, "Expired Patient", [{"product_id": dated.get("product_id"), "medicine_name": "Dated tablets", "quantity": 1, "unit": "Tablet"}])
        status, expired = call("POST", "/api/pharmacy/dispense", pharmacy, {
            "prescription_id": expired_rx.get("rx_id"),
            "lines": [{"item_id": expired_rx.get("item_id"), "qty": 1, "product_id": dated.get("product_id"), "batch_id": dated.get("batch_id")}],
        }, {"Idempotency-Key": "phase3-expired"})
        check("expired batch is rejected", status == 400 and "expired" in err_of(expired).get("message", "").lower(), err_of(expired).get("message", ""))
        _exec(target, "UPDATE batches SET active=0 WHERE id=%s", (later_id,))
        inactive_rx = _prescribe(call, doctor, reception, "Inactive Patient", [{"product_id": dated.get("product_id"), "medicine_name": "Dated tablets", "quantity": 1, "unit": "Tablet"}])
        status, inactive = call("POST", "/api/pharmacy/dispense", pharmacy, {
            "prescription_id": inactive_rx.get("rx_id"),
            "lines": [{"item_id": inactive_rx.get("item_id"), "qty": 1, "product_id": dated.get("product_id"), "batch_id": later_id}],
        }, {"Idempotency-Key": "phase3-inactive"})
        check("inactive batch is rejected", status == 400 and "inactive" in err_of(inactive).get("message", "").lower(), err_of(inactive).get("message", ""))
        status, wrong_batch = call("POST", "/api/pharmacy/dispense", pharmacy, {
            "prescription_id": inactive_rx.get("rx_id"),
            "lines": [{"item_id": inactive_rx.get("item_id"), "qty": 1, "product_id": dated.get("product_id"), "batch_id": "BAT-PR-PAN"}],
        }, {"Idempotency-Key": "phase3-wrong-batch"})
        check("batch from another product is rejected", status == 409, str(status) + " " + err_of(wrong_batch).get("message", ""))

        short = _product_with_stock(call, pharmacy, "Short tablets", 1)
        short_rx = _prescribe(call, doctor, reception, "Short Patient", [{"product_id": short.get("product_id"), "medicine_name": "Short tablets", "quantity": 2, "unit": "Tablet"}])
        status, short_disp = call("POST", "/api/pharmacy/dispense", pharmacy, {
            "prescription_id": short_rx.get("rx_id"),
            "lines": [{"item_id": short_rx.get("item_id"), "qty": 2, "product_id": short.get("product_id"), "batch_id": short.get("batch_id")}],
        }, {"Idempotency-Key": "phase3-short"})
        check("insufficient stock is rejected", status == 400 and _qty(target, short.get("batch_id")) == 1, err_of(short_disp).get("message", ""))

        race = _product_with_stock(call, pharmacy, "Race tablets", 1)
        race_rx = _prescribe(call, doctor, reception, "Race Patient", [{"product_id": race.get("product_id"), "medicine_name": "Race tablets", "quantity": 1, "unit": "Tablet"}])
        race_result = _concurrent_dispense(base, pharmacy, race_rx, race.get("product_id"), race.get("batch_id"), same_key=False)
        check("concurrent dispense cannot go negative", race_result["ok"] == 1 and race_result["fail"] == 1 and _qty(target, race.get("batch_id")) == 0 and _count(target, "SELECT COUNT(*) FROM stock_movements WHERE batch_id=%s AND movement_type='DISPENSED'", (race.get("batch_id"),)) == 1, str(race_result))

        same = _product_with_stock(call, pharmacy, "Retry tablets", 1)
        same_rx = _prescribe(call, doctor, reception, "Retry Patient", [{"product_id": same.get("product_id"), "medicine_name": "Retry tablets", "quantity": 1, "unit": "Tablet"}])
        same_result = _concurrent_dispense(base, pharmacy, same_rx, same.get("product_id"), same.get("batch_id"), same_key=True)
        check("concurrent retry of one key dispenses once", same_result["ok"] == 2 and _qty(target, same.get("batch_id")) == 0 and _count(target, "SELECT COUNT(*) FROM dispense_lines WHERE prescription_id=%s", (same_rx.get("rx_id"),)) == 1, str(same_result))

        status, adjust = call("POST", "/api/inventory/movements", pharmacy, {"batch_id": short.get("batch_id"), "qty": 1, "movement_type": "ADJUSTMENT", "reason": "count"})
        check("pharmacist cannot adjust stock", status == 403, str(status))
        status, no_reason_adj = call("POST", "/api/inventory/movements", director, {"batch_id": short.get("batch_id"), "qty": 1, "movement_type": "ADJUSTMENT"})
        check("adjustment without a reason is rejected", status == 400, str(status) + " " + err_of(no_reason_adj).get("message", ""))
        status, adjusted = call("POST", "/api/inventory/movements", director, {"batch_id": short.get("batch_id"), "qty": 1, "movement_type": "LOST", "reason": "broken strip"})
        check("adjustment with permission and reason writes the ledger", status == 200 and _count(target, "SELECT COUNT(*) FROM stock_movements WHERE batch_id=%s AND movement_type='LOST'", (short.get("batch_id"),)) == 1, err_of(adjusted).get("message", ""))
        check("adjustment did not overwrite the quantity without a movement", _qty(target, short.get("batch_id")) == 0)

        rejected, detail = _rejects(target, "UPDATE batches SET qty_on_hand=-1 WHERE id=%s", ("BAT-PR-ORS",))
        check("database rejects negative stock", rejected, detail)
        rejected, detail = _rejects(target, "UPDATE prescriptions SET status='LEAKED' WHERE id=%s", (rx.get("id"),))
        check("database rejects an unknown prescription status", rejected, detail)
        rejected, detail = _rejects(
            target,
            "INSERT INTO barcodes(id, sku_id, value, barcode_type, scope, active, created_at, updated_at) VALUES ('BC-DUP', %s, 'STRIP-PARA-3', 'INTERNAL', 'SKU', 1, '2026-09-01', '2026-09-01')",
            (sku_id,),
        )
        check("database rejects a second active copy of a barcode", rejected, detail)
        check("no supplier or GRN module was added", _count(target, "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public' AND table_name IN ('suppliers','goods_receipts','grn')") == 0)

        audit = _audit_blob(target)
        check("audit does not copy the consultation note", MARKER not in audit)
        check("dispense was audited", "dispense" in audit)
        front = (ROOT / "frontend" / "src" / "pages" / "clinical.tsx").read_text()
        check("frontend scan resolves and does not dispense on scan", "/api/inventory/barcodes/resolve" in front and "Idempotency-Key" in front)
        check("frontend does not hardcode the barcode type list", "EAN-13" not in front and "barcode-types" in front)
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
            failures.append("cleanup failed: " + type(exc).__name__)
        if previous is None:
            os.environ.pop("AIPF_DATABASE_URL", None)
        else:
            os.environ["AIPF_DATABASE_URL"] = previous
    return failures


def _prescribe(call, doctor, reception, name, items) -> dict:
    phone = "94" + secrets.token_hex(3)
    status, visit = call("POST", "/api/visits", reception, {
        "name": name,
        "primary_phone": phone,
        "gender": "Male",
        "age_at_registration": 40,
        "confirm_new": True,
        "opd_type_id": "OTY-GEN",
        "doctor_id": "U-ANITA",
        "queue": True,
    })
    if status != 200:
        return {"error": str(status) + " " + str(((visit or {}).get("error") or {}).get("message"))}
    encounter = ((visit or {}).get("data") or {}).get("encounter") or {}
    status, rx = call("POST", "/api/prescriptions", doctor, {"encounter_id": encounter.get("id"), "items": items})
    if status != 200:
        return {"error": "rx " + str(status) + " " + str(((rx or {}).get("error") or {}).get("message"))}
    body = (rx or {}).get("data") or {}
    status, final = call("POST", f"/api/prescriptions/{body.get('id')}/finalize", doctor, {})
    if status != 200:
        return {"error": "final " + str(status)}
    return {"rx_id": body.get("id"), "item_id": ((body.get("items") or [{}])[0]).get("id"), "patient_id": encounter.get("patient_id"), "error": ""}


def _product_with_stock(call, pharmacy, name, qty, expiry="2028-01-01", batch_no="B1") -> dict:
    status, product = call("POST", "/api/inventory/products", pharmacy, {"name": name, "unit": "Tablet", "sale_rate_paise": 100, "purchase_rate_paise": 50})
    if status != 200:
        return {"error": str(status)}
    product_id = ((product or {}).get("data") or {}).get("id")
    status, receipt = call("POST", "/api/inventory/receive", pharmacy, {
        "product_id": product_id,
        "batch_no": batch_no,
        "mfg_date": "2026-01-01",
        "expiry_date": expiry,
        "qty": qty,
    })
    if status != 200:
        return {"error": "receive " + str(status) + " " + str(((receipt or {}).get("error") or {}).get("message")), "product_id": product_id}
    batch_id = (((receipt or {}).get("data") or {}).get("batch") or {}).get("id")
    return {"product_id": product_id, "batch_id": batch_id, "barcodes": 0}


def _concurrent_dispense(base, token, rx, product_id, batch_id, same_key: bool) -> dict:
    outcomes = []
    lock = threading.Lock()
    shared = "phase3-shared-" + secrets.token_hex(4)

    def one(index: int):
        key = shared if same_key else "phase3-race-" + str(index) + "-" + secrets.token_hex(3)
        body = {
            "prescription_id": rx.get("rx_id"),
            "lines": [{"item_id": rx.get("item_id"), "qty": 1, "product_id": product_id, "batch_id": batch_id}],
        }
        req = urllib.request.Request(
            base + "/api/pharmacy/dispense",
            data=json.dumps(body).encode(),
            method="POST",
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + token, "Idempotency-Key": key},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                code = res.status
        except urllib.error.HTTPError as exc:
            code = exc.code
        except Exception:
            code = 0
        with lock:
            outcomes.append(code)

    threads = [threading.Thread(target=one, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=40)
    return {"ok": outcomes.count(200), "fail": sum(1 for code in outcomes if code not in (200, 0)), "codes": outcomes}


def _hear(base, pharmacy, other, rx_id, item_id, patient_id) -> dict:
    found = {"pharmacy": False, "other": False, "patient": False, "leaked": False, "status": 0, "payload": {}, "key": "phase3-partial"}

    def listen(name: str, token: str):
        try:
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
            with urllib.request.urlopen(req, timeout=8) as res:
                deadline = time.time() + 6
                while time.time() < deadline:
                    line = res.readline()
                    if not line:
                        break
                    if MARKER.encode() in line:
                        found["leaked"] = True
                    if b"pharmacy.dispensed" in line:
                        found[name] = True
                        if patient_id and patient_id.encode() in line:
                            found["patient"] = True
                        return
        except Exception:
            return

    threads = [
        threading.Thread(target=listen, args=("pharmacy", pharmacy)),
        threading.Thread(target=listen, args=("other", other)),
    ]
    for thread in threads:
        thread.start()
    time.sleep(0.6)
    body = {
        "prescription_id": rx_id,
        "lines": [{"item_id": item_id, "qty": 4, "product_id": "PR-PARA", "batch_id": "BAT-PR-PARA"}],
    }
    req = urllib.request.Request(
        base + "/api/pharmacy/dispense",
        data=json.dumps(body).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + pharmacy, "Idempotency-Key": found["key"]},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            found["status"] = res.status
            found["payload"] = json.loads(res.read().decode())
    except urllib.error.HTTPError as exc:
        found["status"] = exc.code
        try:
            found["payload"] = json.loads(exc.read().decode())
        except Exception:
            found["payload"] = {}
    for thread in threads:
        thread.join(timeout=8)
    return found


def _count(url: str, sql: str, params: tuple = ()) -> int:
    return int(_one(url, sql, params) or 0)


def _one(url: str, sql: str, params: tuple = ()):
    import psycopg
    conn = psycopg.connect(url, autocommit=True)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def _qty(url: str, batch_id: str):
    value = _one(url, "SELECT qty_on_hand FROM batches WHERE id=%s", (batch_id,))
    return float(value or 0)


def _exec(url: str, sql: str, params: tuple = ()) -> None:
    import psycopg
    conn = psycopg.connect(url, autocommit=True)
    with conn.cursor() as cur:
        cur.execute(sql, params)
    conn.close()


def _rejects(url: str, sql: str, params: tuple) -> tuple[bool, str]:
    import psycopg
    conn = psycopg.connect(url)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()
        return False, "committed"
    except Exception as exc:
        conn.rollback()
        return True, type(exc).__name__
    finally:
        conn.close()


def _audit_blob(url: str) -> str:
    import psycopg
    conn = psycopg.connect(url, autocommit=True)
    with conn.cursor() as cur:
        cur.execute("SELECT action, COALESCE(old_value,''), COALESCE(new_value,''), COALESCE(reason,'') FROM audit_logs")
        rows = cur.fetchall()
    conn.close()
    return "\n".join(" ".join(str(part) for part in row) for row in rows)


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


def _redact(text: str) -> str:
    url = os.environ.get("AIPF_DATABASE_URL") or ""
    if url:
        text = text.replace(url, "[redacted]")
    return text
