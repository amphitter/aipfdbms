"""Local hospital API. Browsers talk only to this process."""

from __future__ import annotations

import errno
import json
import mimetypes
import os
import re
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import access, billing, clinical, core, laboratory, notify, pairing, pharmacy, system, theatre, wards
from .db import DB_PATH, ROOT, Tx, connect, init_db
from .events import publish, subscribe, unsubscribe
from .system import mark_worker
from .util import ApiError, now_iso, redact

FRONTEND = ROOT / "frontend" / "dist"
HOST = "0.0.0.0"
PORT = int(os.environ.get("AIPF_PORT", "8787"))


class FileResponse:
    def __init__(self, data: bytes, content_type: str, filename: str | None = None, disposition: str = "inline"):
        self.data = data
        self.content_type = content_type
        self.filename = filename
        self.disposition = disposition


class Ctx:
    def __init__(self, conn, user, params, query, body, ip, workstation, idempotency_key=""):
        self.conn = conn
        self.user = user
        self.params = params
        self.query = query
        self.body = body or {}
        self.ip = ip
        self.workstation = workstation
        self.idempotency_key = idempotency_key or ""

    def q(self, name, default=""):
        values = self.query.get(name)
        if not values:
            return default
        return values[0]


def _public_accounts():
    # Usernames may be listed. Passwords are never returned and are not stored in source.
    return []


def _compile(pattern: str) -> re.Pattern:
    regex = re.sub(r":([A-Za-z_][A-Za-z0-9_]*)", r"(?P<\1>[^/]+)", pattern)
    return re.compile("^" + regex + "$")


def _guard_patient(c, patient_id):
    access.guard_patient(c.conn, c.user, patient_id)


def _guard_invoice(c, invoice_id):
    row = billing.get_invoice(c.conn, invoice_id)
    _guard_patient(c, (row or {}).get("patient_id"))
    return row


def _items(payload):
    if isinstance(payload, dict) and isinstance(payload.get("items"), list):
        return payload, payload["items"]
    return None, payload if isinstance(payload, list) else []


def _filter_patients(c, payload, key="patient_id"):
    wrapper, items = _items(payload)
    filtered = access.filter_by_patient(c.conn, c.user, items, key)
    if wrapper is None:
        return filtered
    wrapper["items"] = filtered
    if "total" in wrapper:
        wrapper["total"] = len(filtered)
    return wrapper


def _filter_documents(c, payload):
    wrapper, items = _items(payload)
    filtered = access.filter_documents(c.conn, c.user, items)
    if wrapper is None:
        return filtered
    wrapper["items"] = filtered
    if "total" in wrapper:
        wrapper["total"] = len(filtered)
    return wrapper


def _take_payment(c):
    _guard_invoice(c, c.params["id"])
    body = c.body
    return billing.record_payment(
        c.conn,
        c.user,
        c.params["id"],
        body.get("mode") or "",
        int(body.get("amount_paise") or 0),
        body.get("reference") or "",
        body.get("notes") or "",
        "PAYMENT",
        body.get("idempotency_key") or c.idempotency_key,
        require_key=True,
    )


def _allocate_deposit(c):
    _guard_invoice(c, c.params["id"])
    body = c.body
    return billing.apply_deposit(
        c.conn,
        c.user,
        c.params["id"],
        body.get("deposit_id") or "",
        body.get("amount_paise"),
        body.get("idempotency_key") or c.idempotency_key,
        require_key=True,
    )


def _refund_payment(c):
    _guard_invoice(c, c.params["id"])
    body = c.body
    return billing.refund(
        c.conn,
        c.user,
        c.params["id"],
        int(body.get("amount_paise") or 0),
        body.get("mode") or "",
        body.get("reason") or "",
        body.get("payment_id"),
        body.get("idempotency_key") or c.idempotency_key,
        require_key=True,
    )


def _receive_deposit(c):
    _guard_patient(c, c.body.get("patient_id"))
    body = c.body
    return billing.create_deposit(
        c.conn,
        c.user,
        body.get("patient_id") or "",
        int(body.get("amount_paise") or 0),
        body.get("mode") or "",
        body.get("admission_id"),
        body.get("reference") or "",
        body.get("notes") or "",
        body.get("deposit_type") or "",
        body.get("encounter_id"),
        body.get("idempotency_key") or c.idempotency_key,
        require_key=True,
    )


def _refund_deposit(c):
    return billing.refund_deposit(
        c.conn,
        c.user,
        c.params["id"],
        c.body.get("reason") or "",
        c.body.get("idempotency_key") or c.idempotency_key,
        require_key=True,
    )


def _add_invoice_item(c):
    core.permit_any(c.user, ["billing.create", "billing.edit"], c.conn, "invoice_item")
    _guard_invoice(c, c.params["id"])
    return billing.add_item(c.conn, c.user, c.params["id"], c.body, from_client=True)


def build_routes():
    R = []

    def add(method, pattern, fn, permission=None, auth=True, tx=None):
        CATALOG.append({"method": method, "path": pattern, "permission": permission, "auth": auth})
        R.append((method, _compile(pattern), fn, permission, auth, tx))

    add("GET", "/api/public/branding", lambda c: core.public_branding(c.conn), auth=False, tx=False)
    add("GET", "/api/public/accounts", lambda c: {"items": _public_accounts()} if core.config_get(c.conn, "show_install_hints", "1") == "1" else {"items": []}, auth=False, tx=False)
    add("POST", "/api/auth/login", lambda c: core.login(c.conn, c.body.get("username", ""), c.body.get("password", ""), c.body.get("workstation") or c.workstation, c.ip, ""), auth=False, tx=False)
    add("POST", "/api/auth/logout", lambda c: (core.logout(c.conn, c.user, c.user.get("token")), {"ok": True})[1], tx=False)
    add("POST", "/api/auth/stream-ticket", lambda c: core.stream_ticket(c.conn, c.user), tx=False)
    add("GET", "/api/auth/stream-ticket", lambda c: core.stream_ticket(c.conn, c.user), tx=False)
    add("GET", "/api/auth/me", lambda c: {k: v for k, v in c.user.items() if k not in {"token", "password_hash"}})
    add("POST", "/api/auth/password", lambda c: (core.change_password(c.conn, c.user, c.body.get("current", ""), c.body.get("password", "")), {"ok": True})[1])

    add("GET", "/api/dashboard", lambda c: system.dashboard(c.conn, c.user), tx=False)
    add("GET", "/api/search", lambda c: system.global_search(c.conn, c.q("q"), c.user), tx=False)
    add("GET", "/api/onboarding", lambda c: system.onboarding(c.conn), tx=False)

    add("GET", "/api/patients", lambda c: clinical.search_patients(c.conn, c.q("q"), int(c.q("limit", "40") or 40), c.user, page=int(c.q("page", "0") or 0), page_size=int(c.q("page_size", "0") or 0), sort=c.q("sort") or "registered", direction=c.q("direction") or "desc", department_id=c.q("department_id"), gender=c.q("gender"), age=c.q("age"), registered=c.q("registered"), status=c.q("status")), "patient.view", tx=False)
    add("GET", "/api/patients/export", lambda c: FileResponse(clinical.patients_csv(c.conn, c.user, c.q("q"), c.q("sort") or "registered", c.q("direction") or "desc", c.q("department_id"), c.q("gender"), c.q("age"), c.q("registered"), c.q("status")).encode(), "text/csv", "patients.csv", "attachment"), "patient.view", tx=False)
    add("GET", "/api/patients/by-phone", lambda c: _filter_patients(c, {"items": clinical.matches_by_phone(c.conn, c.q("phone"))}, "id"), "patient.view", tx=False)
    add("POST", "/api/patients", lambda c: clinical.save_patient(c.conn, c.user, c.body), "patient.create")
    add("POST", "/api/patients/import", lambda c: clinical.import_patients(c.conn, c.user, c.body), "patient.create")
    add("POST", "/api/patients/status", lambda c: clinical.set_patients_status(c.conn, c.user, c.body), "patient.edit")
    add("GET", "/api/patients/:id", lambda c: (clinical.get_patient(c.conn, c.params["id"]), _guard_patient(c, c.params["id"]))[0], "patient.view", tx=False)
    add("PATCH", "/api/patients/:id", lambda c: clinical.save_patient(c.conn, c.user, c.body, c.params["id"]), "patient.edit")
    add("DELETE", "/api/patients/:id", lambda c: clinical.delete_patient(c.conn, c.user, c.params["id"]), "patient.edit")
    add("GET", "/api/patients/:id/timeline", lambda c: (_guard_patient(c, c.params["id"]), clinical.patient_timeline(c.conn, c.params["id"], c.user))[1], "patient.view", tx=False)

    add("GET", "/api/opd/types", lambda c: {"items": clinical.opd_types(c.conn, c.q("all") == "1")}, "opd.view", tx=False)
    add("POST", "/api/opd/types", lambda c: clinical.save_opd_type(c.conn, c.user, c.body), "master.manage")
    add("PATCH", "/api/opd/types/:id", lambda c: clinical.save_opd_type(c.conn, c.user, c.body, c.params["id"]), "master.manage")
    add("DELETE", "/api/opd/types/:id", lambda c: clinical.delete_opd_type(c.conn, c.user, c.params["id"]), "master.manage")
    add("GET", "/api/opd/valid", lambda c: {"items": clinical.valid_opd_cards(c.conn, c.q("patient_id"))}, "opd.view", tx=False)
    add("POST", "/api/opd", lambda c: clinical.create_encounter(c.conn, c.user, c.body), "opd.create")
    add("POST", "/api/visits", lambda c: clinical.register_visit(c.conn, c.user, c.body), "opd.create")
    add("GET", "/api/opd/:id", lambda c: (lambda row: (_guard_patient(c, row.get("patient_id")), row)[1])(clinical.get_encounter(c.conn, c.params["id"])), "opd.view", tx=False)
    add("POST", "/api/opd/:id/assign", lambda c: clinical.enqueue(c.conn, c.user, c.params["id"], c.body.get("doctor_id"), int(c.body.get("priority") or 0), c.body.get("priority_label")), "opd.assign")

    add("GET", "/api/queue", lambda c: clinical.list_queue(c.conn, c.user, c.q("doctor_id"), c.q("status"), c.q("mine") == "1"), "queue.view", tx=False)
    add("POST", "/api/queue/:id/status", lambda c: clinical.set_queue_status(c.conn, c.user, c.params["id"], c.body.get("status")), "queue.manage")

    add("POST", "/api/consultations", lambda c: clinical.save_consultation(c.conn, c.user, c.body), "consultation.create")
    add("POST", "/api/prescriptions", lambda c: clinical.save_prescription(c.conn, c.user, c.body), "prescription.create")
    add("PUT", "/api/prescriptions/:id", lambda c: clinical.save_prescription(c.conn, c.user, c.body, c.params["id"]), "prescription.create")
    add("POST", "/api/prescriptions/:id/finalize", lambda c: clinical.finalize_prescription(c.conn, c.user, c.params["id"]), "prescription.create")
    add("GET", "/api/prescriptions/:id", lambda c: (lambda row: (_guard_patient(c, row.get("patient_id")), row)[1])(clinical.get_prescription(c.conn, c.params["id"])), "prescription.view", tx=False)
    add("GET", "/api/prescriptions/:id/pdf", lambda c: (lambda row: (_guard_patient(c, row.get("patient_id")), (lambda data, name: FileResponse(data, "application/pdf", name))(*clinical.prescription_download(c.conn, c.user, c.params["id"])))[1])(clinical.get_prescription(c.conn, c.params["id"])), ["prescription.view", "billing.print"], tx=True)

    add("GET", "/api/doctors", lambda c: {"items": clinical.doctors(c.conn)}, auth=True, tx=False)
    add("GET", "/api/staff", lambda c: {"items": core.staff_directory(c.conn, c.user)}, tx=False)
    add("GET", "/api/services", lambda c: {"items": clinical.services(c.conn, c.q("all") == "1")}, tx=False)
    add("POST", "/api/services", lambda c: clinical.save_service(c.conn, c.user, c.body), "master.manage")
    add("PATCH", "/api/services/:id", lambda c: clinical.save_service(c.conn, c.user, c.body, c.params["id"]), "master.manage")
    add("DELETE", "/api/services/:id", lambda c: clinical.delete_service(c.conn, c.user, c.params["id"]), "master.manage")
    add("GET", "/api/lab/tests", lambda c: {"items": clinical.lab_tests(c.conn, c.q("all") == "1")}, tx=False)
    add("POST", "/api/lab/tests", lambda c: clinical.save_lab_test(c.conn, c.user, c.body), "master.manage")
    add("PATCH", "/api/lab/tests/:id", lambda c: clinical.save_lab_test(c.conn, c.user, c.body, c.params["id"]), "master.manage")
    add("DELETE", "/api/lab/tests/:id", lambda c: clinical.delete_lab_test(c.conn, c.user, c.params["id"]), "master.manage")

    add("GET", "/api/formulary", lambda c: pharmacy.list_products(c.conn, c.q("q")), "prescription.create", tx=False)
    add("GET", "/api/pharmacy/queue", lambda c: pharmacy.pharmacy_queue(c.conn, c.user), "pharmacy.view", tx=False)
    add("GET", "/api/pharmacy/lookup", lambda c: pharmacy.lookup_barcode(c.conn, c.q("code") or c.q("q")), "pharmacy.view", tx=False)
    add("POST", "/api/pharmacy/dispense", lambda c: pharmacy.dispense(c.conn, c.user, c.body, c.idempotency_key, require_key=True), "pharmacy.dispense")
    add("GET", "/api/inventory/products", lambda c: pharmacy.list_products(c.conn, c.q("q"), c.q("alerts") == "1", c.q("all") == "1"), "inventory.view", tx=False)
    add("POST", "/api/inventory/products", lambda c: pharmacy.save_product(c.conn, c.user, c.body), "inventory.edit")
    add("PATCH", "/api/inventory/products/:id", lambda c: pharmacy.save_product(c.conn, c.user, c.body, c.params["id"]), "inventory.edit")
    add("GET", "/api/inventory/products/:id", lambda c: pharmacy.get_product(c.conn, c.params["id"]), "inventory.view", tx=False)
    add("POST", "/api/inventory/batches", lambda c: pharmacy.add_batch(c.conn, c.user, c.body), "inventory.edit")
    add("POST", "/api/inventory/movements", lambda c: pharmacy.post_movement(c.conn, c.user, c.body), "inventory.adjust")
    add("GET", "/api/inventory/barcode-types", lambda c: pharmacy.barcode_types(c.conn), "inventory.view", tx=False)
    add("POST", "/api/inventory/barcode-types", lambda c: pharmacy.save_barcode_type(c.conn, c.user, c.body), "master.manage")
    add("POST", "/api/inventory/skus", lambda c: pharmacy.save_sku(c.conn, c.user, c.body), "inventory.edit")
    add("POST", "/api/inventory/barcodes", lambda c: pharmacy.save_barcode(c.conn, c.user, c.body), "inventory.edit")
    add("PATCH", "/api/inventory/skus/:id", lambda c: pharmacy.set_sku_active(c.conn, c.user, c.params["id"], c.body), "inventory.edit")
    add("PATCH", "/api/inventory/barcodes/:id", lambda c: pharmacy.set_barcode_active(c.conn, c.user, c.params["id"], c.body), "inventory.edit")
    add("POST", "/api/inventory/barcodes/resolve", lambda c: pharmacy.resolve_for_user(c.conn, c.user, c.body.get("code") or c.body.get("barcode") or ""), tx=False)
    add("POST", "/api/scan-pairs", lambda c: pairing.create_pair(c.user, c.body.get("origin") or ""), tx=False)
    add("GET", "/api/scan-pairs/:token", lambda c: pairing.read_pair(c.user, c.params["token"]), tx=False)
    add("POST", "/api/scan-pairs/:token", lambda c: pairing.submit_pair(c.params["token"], c.body.get("code") or ""), tx=False)
    add("POST", "/api/inventory/receive", lambda c: pharmacy.receive_stock(c.conn, c.user, c.body), "inventory.edit")
    add("GET", "/api/inventory/ledger", lambda c: pharmacy.ledger(c.conn, c.q("product_id"), c.q("batch_id")), "inventory.view", tx=False)
    add("GET", "/api/inventory/alerts", lambda c: pharmacy.alerts(c.conn), "inventory.view", tx=False)
    add("GET", "/api/inventory/reconcile/:id", lambda c: pharmacy.reconciliation(c.conn, c.params["id"]), "inventory.view", tx=False)

    add("POST", "/api/lab/orders", lambda c: laboratory.place_order(c.conn, c.user, c.body), "lab.order")
    add("GET", "/api/lab/orders", lambda c: _filter_patients(c, wards.list_labs(c.conn, c.q("status"))), "lab.view", tx=False)
    add("GET", "/api/lab/orders/:id", lambda c: (lambda row: (_guard_patient(c, row.get("patient_id")), row)[1])(wards.get_lab_order(c.conn, c.params["id"])), "lab.view", tx=False)
    add("POST", "/api/lab/orders/:id/cancel", lambda c: laboratory.cancel_order(c.conn, c.user, c.params["id"], c.body, c.idempotency_key), "lab.order.cancel")
    add("POST", "/api/lab/orders/:id/samples", lambda c: laboratory.collect_sample(c.conn, c.user, c.params["id"], c.body, c.idempotency_key), "lab.sample.collect")
    add("POST", "/api/lab/samples/:id/reject", lambda c: laboratory.reject_sample(c.conn, c.user, c.params["id"], c.body, c.idempotency_key), "lab.sample.reject")
    add("POST", "/api/lab/samples/:id/receive", lambda c: laboratory.receive_sample(c.conn, c.user, c.params["id"], c.body, c.idempotency_key), "lab.sample.process")
    add("POST", "/api/lab/samples/:id/process", lambda c: laboratory.process_sample(c.conn, c.user, c.params["id"], c.body, c.idempotency_key), "lab.sample.process")
    add("GET", "/api/lab/queue", lambda c: laboratory.processing_queue(c.conn, c.user), "lab.view", tx=False)
    add("POST", "/api/lab/orders/:id/status", lambda c: laboratory.reject_direct_status(c.conn, c.user, c.params["id"], c.body.get("status")), "lab.result")
    add("POST", "/api/lab/items/:id/result", lambda c: laboratory.enter_result(c.conn, c.user, c.params["id"], c.body, c.idempotency_key), "lab.result")
    add("POST", "/api/lab/results/:id/verify", lambda c: laboratory.verify_result(c.conn, c.user, c.params["id"], c.body, c.idempotency_key), "lab.result.verify")
    add("POST", "/api/lab/results/:id/correct", lambda c: laboratory.correct_result(c.conn, c.user, c.params["id"], c.body, c.idempotency_key), "lab.result.correct")
    add("POST", "/api/lab/orders/:id/report-upload", lambda c: laboratory.upload_report(c.conn, c.user, c.params["id"], c.body), "document.upload")
    add("POST", "/api/lab/orders/:id/report", lambda c: laboratory.generate_report(c.conn, c.user, c.params["id"], c.body, c.idempotency_key), "lab.report.generate")
    add("GET", "/api/lab/orders/:id/report", lambda c: FileResponse(laboratory.report_pdf(c.conn, c.user, c.params["id"]), "application/pdf", "lab-report.pdf"), "lab.report.view", tx=False)

    add("GET", "/api/invoices", lambda c: _filter_patients(c, billing.list_invoices(c.conn, c.q("q"), c.q("status"), c.q("payment_status"), c.q("patient_id"))), "billing.view", tx=False)
    add("POST", "/api/invoices", lambda c: billing.open_draft(c.conn, c.user, c.body["patient_id"], c.body.get("encounter_id"), c.body.get("admission_id"), c.body.get("bill_type") or "OPD"), "billing.create")
    add("GET", "/api/invoices/:id", lambda c: (lambda row: (_guard_patient(c, (row or {}).get("patient_id")), row)[1])(billing.get_invoice(c.conn, c.params["id"])), "billing.view", tx=False)
    add("GET", "/api/invoices/:id/document", lambda c: (_guard_invoice(c, c.params["id"]), {k: v for k, v in billing.invoice_document(c.conn, c.params["id"]).items() if k != "logo_bytes"})[1], "billing.view", tx=False)
    add("GET", "/api/invoices/:id/pdf", lambda c: (_guard_invoice(c, c.params["id"]), FileResponse(billing.invoice_pdf(c.conn, c.params["id"], c.q("format") == "slip"), "application/pdf", billing.invoice_filename(c.conn, c.params["id"])))[1], "billing.print", tx=False)
    add("POST", "/api/invoices/:id/prescription-charges", lambda c: billing.add_prescription_charges(c.conn, c.user, c.params["id"], c.body.get("prescription_id") or "", c.body.get("item_ids") or []), "billing.medicine_issue")
    add("POST", "/api/invoices/:id/issue", lambda c: (_guard_invoice(c, c.params["id"]), billing.issue_medicines(c.conn, c.user, c.params["id"], c.body))[1], "billing.medicine_issue")
    add("POST", "/api/invoices/:id/notes", lambda c: (_guard_invoice(c, c.params["id"]), billing.save_notes(c.conn, c.user, c.params["id"], c.body.get("notes") or ""))[1], "billing.create")
    add("GET", "/api/billing/desk", lambda c: billing.billing_desk(c.conn, c.user, c.q("patient_id"), c.q("encounter_id")), "billing.view", tx=False)
    add("GET", "/api/billing/medicines", lambda c: billing.search_counter_medicines(c.conn, c.user, c.q("q")), "billing.medicine_issue", tx=False)
    add("POST", "/api/invoices/:id/items", _add_invoice_item, "billing.create")
    add("DELETE", "/api/invoice-items/:id", lambda c: billing.remove_draft_item(c.conn, c.user, c.params["id"]), "billing.create")
    add("POST", "/api/invoice-items/:id/revise", lambda c: billing.revise_issued_line(c.conn, c.user, c.params["id"], c.body), "billing.medicine_issue")
    add("POST", "/api/invoices/:id/discount", lambda c: billing.set_discount(c.conn, c.user, c.params["id"], int(c.body.get("discount_paise") or 0), c.body.get("reason", "")), "billing.create")
    add("POST", "/api/invoices/:id/finalize", lambda c: (_guard_invoice(c, c.params["id"]), billing.finalize(c.conn, c.user, c.params["id"]))[1], "billing.finalize")
    add("POST", "/api/invoices/:id/payments", _take_payment, "payment.create")
    add("POST", "/api/invoices/:id/deposit", _allocate_deposit, "deposit.allocate")
    add("POST", "/api/invoices/:id/refund", _refund_payment, "payment.refund")
    add("POST", "/api/invoices/:id/void", lambda c: (_guard_invoice(c, c.params["id"]), billing.void_invoice(c.conn, c.user, c.params["id"], c.body.get("reason", "")))[1], "billing.void")
    add("POST", "/api/invoices/:id/adjust", lambda c: (_guard_invoice(c, c.params["id"]), billing.adjust(c.conn, c.user, c.params["id"], int(c.body.get("amount_paise") or 0), c.body.get("description", ""), c.body.get("reason", "")))[1], "financial_adjustment.create")
    add("POST", "/api/deposits", _receive_deposit, "deposit.create")
    add("POST", "/api/deposits/:id/refund", _refund_deposit, "payment.refund")
    add("GET", "/api/deposits", lambda c: (_guard_patient(c, c.q("patient_id")), billing.list_deposits(c.conn, c.q("patient_id")))[1], "billing.view", tx=False)
    add("GET", "/api/reports/billing", lambda c: billing.outstanding_report(c.conn), "billing.report", tx=False)

    add("GET", "/api/beds", lambda c: wards.bed_board(c.conn, c.user), ["bed.view", "ipd.bed.view"], tx=False)
    add("POST", "/api/beds/:id/status", lambda c: wards.set_bed_status(c.conn, c.user, c.params["id"], c.body.get("status"), c.body.get("notes", "")), "bed.manage")
    add("GET", "/api/admissions", lambda c: _filter_patients(c, wards.list_admissions(c.conn, c.q("status") or "ADMITTED")), ["admission.view", "ipd.admission.view"], tx=False)
    add("POST", "/api/admissions", lambda c: wards.admit(c.conn, c.user, {**c.body, "idempotency_key": c.body.get("idempotency_key") or c.idempotency_key}), ["admission.manage", "ipd.admission.create"])
    add("GET", "/api/admissions/:id", lambda c: (lambda row: (_guard_patient(c, row.get("patient_id")), row)[1])(wards.get_admission(c.conn, c.params["id"])), ["admission.view", "ipd.admission.view"], tx=False)
    add("POST", "/api/admissions/:id/assign", lambda c: wards.assign_bed(c.conn, c.user, c.params["id"], c.body.get("bed_id") or "", c.body.get("reason") or "", c.body.get("idempotency_key") or c.idempotency_key), ["admission.manage", "ipd.bed.assign"])
    add("POST", "/api/admissions/:id/transfer", lambda c: wards.transfer(c.conn, c.user, c.params["id"], c.body["bed_id"], c.body.get("reason", ""), c.body.get("idempotency_key") or c.idempotency_key), ["admission.manage", "ipd.bed.move", "ipd.bed.assign"])
    add("POST", "/api/admissions/:id/charges", lambda c: wards.post_charge(c.conn, c.user, c.params["id"], c.body.get("description", "Charge"), c.body.get("category") or "IPD", int(c.body.get("rate_paise") or 0), float(c.body.get("qty") or 1), c.body.get("unit") or "", c.body.get("source_module") or "ipd", c.body.get("source_id") or "", c.body.get("master_item_id") or ""), ["admission.manage", "ipd.admission.manage"])
    add("POST", "/api/admissions/:id/bed-day", lambda c: wards.post_bed_day(c.conn, c.user, c.params["id"], c.body.get("idempotency_key") or c.idempotency_key, c.body.get("charge_date") or ""), ["admission.manage", "ipd.admission.manage"])
    add("POST", "/api/admissions/:id/discharge-pending", lambda c: wards.mark_discharge_pending(c.conn, c.user, c.params["id"]), ["admission.manage", "ipd.discharge.finalize"])
    add("POST", "/api/admissions/:id/cancel", lambda c: wards.cancel_admission(c.conn, c.user, c.params["id"], c.body.get("reason") or ""), ["admission.manage", "ipd.admission.create"])
    add("POST", "/api/admissions/:id/discharge", lambda c: wards.discharge(c.conn, c.user, c.params["id"], c.body, c.body.get("idempotency_key") or c.idempotency_key), ["admission.manage", "ipd.discharge.finalize"])
    add("POST", "/api/admissions/:id/discharge-document", lambda c: wards.generate_discharge_document(c.conn, c.user, c.params["id"]), ["admission.manage", "ipd.discharge.document", "document.upload"])
    add("GET", "/api/admissions/:id/discharge-document", lambda c: (lambda doc, data: FileResponse(data, doc.get("mime_type") or "application/pdf", doc.get("filename") or "discharge.pdf"))(*wards.discharge_document_file(c.conn, c.user, c.params["id"])), ["admission.view", "ipd.admission.view", "document.view"], tx=False)
    add("POST", "/api/wards", lambda c: wards.save_ward(c.conn, c.user, c.body), "master.manage")
    add("GET", "/api/facilities", lambda c: wards.facility_catalog(c.conn, c.q("all") == "1"), "master.manage", tx=False)
    add("PATCH", "/api/wards/:id", lambda c: wards.save_ward(c.conn, c.user, c.body, c.params["id"]), "master.manage")
    add("DELETE", "/api/wards/:id", lambda c: wards.delete_ward(c.conn, c.user, c.params["id"]), "master.manage")
    add("POST", "/api/rooms", lambda c: wards.save_room(c.conn, c.user, c.body), "master.manage")
    add("PATCH", "/api/rooms/:id", lambda c: wards.update_room(c.conn, c.user, c.params["id"], c.body), "master.manage")
    add("DELETE", "/api/rooms/:id", lambda c: wards.delete_room(c.conn, c.user, c.params["id"]), "master.manage")
    add("POST", "/api/beds", lambda c: wards.save_bed(c.conn, c.user, c.body), "master.manage")
    add("PATCH", "/api/beds/:id", lambda c: wards.update_bed_record(c.conn, c.user, c.params["id"], c.body), "master.manage")
    add("DELETE", "/api/beds/:id", lambda c: wards.delete_bed(c.conn, c.user, c.params["id"]), "master.manage")

    add("GET", "/api/ot", lambda c: _filter_patients(c, wards.list_ot(c.conn, c.q("status"))), "ot.view", tx=False)
    add("POST", "/api/ot", lambda c: wards.create_ot(c.conn, c.user, c.body), "ot.manage")
    add("GET", "/api/ot/theatres", lambda c: theatre.list_theatres(c.conn, c.q("all") == "1"), "ot.view", tx=False)
    add("POST", "/api/ot/theatres", lambda c: theatre.save_theatre(c.conn, c.user, c.body), ["ot.theatre.manage", "master.manage"])
    add("PUT", "/api/ot/theatres/:id", lambda c: theatre.save_theatre(c.conn, c.user, c.body, c.params["id"]), ["ot.theatre.manage", "master.manage"])
    add("DELETE", "/api/ot/theatres/:id", lambda c: theatre.delete_theatre(c.conn, c.user, c.params["id"]), ["ot.theatre.manage", "master.manage"])
    add("GET", "/api/ot/procedures", lambda c: theatre.list_procedures(c.conn, c.q("all") == "1"), "ot.view", tx=False)
    add("POST", "/api/ot/procedures", lambda c: theatre.save_procedure(c.conn, c.user, c.body), ["ot.procedure.manage", "master.manage"])
    add("PUT", "/api/ot/procedures/:id", lambda c: theatre.save_procedure(c.conn, c.user, c.body, c.params["id"]), ["ot.procedure.manage", "master.manage"])
    add("DELETE", "/api/ot/procedures/:id", lambda c: theatre.delete_procedure(c.conn, c.user, c.params["id"]), ["ot.procedure.manage", "master.manage"])
    add("GET", "/api/ot/checklist", lambda c: theatre.list_checklist(c.conn, c.q("all") == "1"), "ot.view", tx=False)
    add("POST", "/api/ot/checklist", lambda c: theatre.save_checklist(c.conn, c.user, c.body), ["ot.theatre.manage", "master.manage"])
    add("PUT", "/api/ot/checklist/:id", lambda c: theatre.save_checklist(c.conn, c.user, c.body, c.params["id"]), ["ot.theatre.manage", "master.manage"])
    add("DELETE", "/api/ot/checklist/:id", lambda c: theatre.delete_checklist(c.conn, c.user, c.params["id"]), ["ot.theatre.manage", "master.manage"])
    add("POST", "/api/ot/requests", lambda c: theatre.request_case(c.conn, c.user, c.body, c.idempotency_key), ["ot.request", "ot.manage"])
    add("GET", "/api/ot/:id", lambda c: theatre.present(c.conn, c.user, c.params["id"]), "ot.view", tx=False)
    add("POST", "/api/ot/:id", lambda c: wards.update_ot(c.conn, c.user, c.params["id"], c.body), "ot.manage")
    add("POST", "/api/ot/:id/notes", lambda c: wards.ot_notes(c.conn, c.user, c.params["id"], c.body), "ot.manage")
    add("POST", "/api/ot/:id/approve", lambda c: theatre.approve(c.conn, c.user, c.params["id"], c.body, c.idempotency_key), ["ot.approve", "ot.manage"])
    add("POST", "/api/ot/:id/schedule", lambda c: theatre.schedule(c.conn, c.user, c.params["id"], c.body, c.idempotency_key), ["ot.schedule", "ot.manage"])
    add("POST", "/api/ot/:id/reschedule", lambda c: theatre.reschedule(c.conn, c.user, c.params["id"], c.body, c.idempotency_key), ["ot.schedule", "ot.manage"])
    add("POST", "/api/ot/:id/cancel", lambda c: theatre.cancel(c.conn, c.user, c.params["id"], c.body, c.idempotency_key), ["ot.cancel", "ot.manage"])
    add("POST", "/api/ot/:id/postpone", lambda c: theatre.postpone(c.conn, c.user, c.params["id"], c.body, c.idempotency_key), ["ot.cancel", "ot.schedule", "ot.manage"])
    add("POST", "/api/ot/:id/team", lambda c: theatre.assign_team(c.conn, c.user, c.params["id"], c.body, c.idempotency_key), ["ot.team.manage", "ot.manage"])
    add("POST", "/api/ot/:id/preop", lambda c: theatre.record_preop(c.conn, c.user, c.params["id"], c.body, c.idempotency_key), ["ot.preop.record", "ot.manage"])
    add("POST", "/api/ot/:id/start", lambda c: theatre.start(c.conn, c.user, c.params["id"], c.body, c.idempotency_key), ["ot.start", "ot.manage"])
    add("POST", "/api/ot/:id/intraop", lambda c: theatre.record_intraop(c.conn, c.user, c.params["id"], c.body, c.idempotency_key), ["ot.intraop.record", "ot.manage"])
    add("POST", "/api/ot/:id/recovery", lambda c: theatre.recover(c.conn, c.user, c.params["id"], c.body, c.idempotency_key), ["ot.complete", "ot.manage"])
    add("POST", "/api/ot/:id/complete", lambda c: theatre.complete(c.conn, c.user, c.params["id"], c.body, c.idempotency_key), ["ot.complete", "ot.manage"])
    add("POST", "/api/ot/:id/postop", lambda c: theatre.record_postop(c.conn, c.user, c.params["id"], c.body, c.idempotency_key), ["ot.postop.record", "ot.manage"])
    add("POST", "/api/ot/:id/charge", lambda c: theatre.post_charge(c.conn, c.user, c.params["id"], c.body, c.idempotency_key), ["ot.charge.post", "ot.manage"])
    add("POST", "/api/ot/:id/report", lambda c: theatre.generate_report(c.conn, c.user, c.params["id"], c.body, c.idempotency_key), ["ot.report.generate", "ot.manage", "document.upload"])
    add("GET", "/api/ot/:id/report", lambda c: (lambda doc, data: FileResponse(data, doc.get("mime_type") or "application/pdf", doc.get("filename") or "ot-report.pdf"))(*theatre.report_file(c.conn, c.user, c.params["id"])), ["ot.view", "document.view"], tx=False)
    add("POST", "/api/ot/:id/links", lambda c: theatre.link_record(c.conn, c.user, c.params["id"], c.body, c.idempotency_key), ["ot.request", "ot.manage", "ot.intraop.record"])

    add("GET", "/api/documents", lambda c: _filter_documents(c, wards.list_documents(c.conn, c.q("patient_id"), c.q("entity_type"), c.q("entity_id"), c.q("q"))), "document.view", tx=False)
    add("POST", "/api/documents", lambda c: wards.store_document(c.conn, c.user, c.body), "document.upload")
    add("POST", "/api/documents/:id/deactivate", lambda c: wards.deactivate_document(c.conn, c.user, c.params["id"], c.body.get("reason", "")), "document.deactivate")

    add("GET", "/api/master/:type", lambda c: {"items": core.master_list(c.conn, c.params["type"], c.q("all") == "1")}, tx=False)
    add("POST", "/api/master/:type", lambda c: core.save_master(c.conn, c.user, c.params["type"], c.body), "master.manage")
    add("PATCH", "/api/master/:type/:id", lambda c: core.save_master(c.conn, c.user, c.params["type"], c.body, c.params["id"]), "master.manage")
    add("POST", "/api/master/:type/:id/deactivate", lambda c: core.deactivate_master(c.conn, c.user, c.params["type"], c.params["id"]), "master.manage")
    add("DELETE", "/api/master/:type/:id", lambda c: core.delete_master_item(c.conn, c.user, c.params["type"], c.params["id"]), "master.manage")

    add("GET", "/api/users", lambda c: {"items": core.list_users(c.conn)}, "user.manage", tx=False)
    add("POST", "/api/users", lambda c: core.save_user(c.conn, c.user, c.body), "user.manage")
    add("PATCH", "/api/users/:id", lambda c: core.save_user(c.conn, c.user, c.body, c.params["id"]), "user.manage")
    add("DELETE", "/api/users/:id", lambda c: core.delete_user(c.conn, c.user, c.params["id"]), "user.manage")
    add("GET", "/api/roles", lambda c: {"items": core.list_roles(c.conn), "catalog": [{"code": a, "module": b, "description": c_} for a, b, c_ in core.PERMISSIONS]}, "role.manage", tx=False)
    add("PUT", "/api/roles/:code/permissions", lambda c: {"items": core.set_role_permissions(c.conn, c.user, c.params["code"], c.body.get("permissions") or [])}, "role.manage")

    add("GET", "/api/hospital", lambda c: {**core.hospital(c.conn), "bill_prefix": core.config_get(c.conn, "bill_prefix", "AIPF-BILL")}, tx=False)
    add("PUT", "/api/hospital", lambda c: system.update_hospital(c.conn, c.user, c.body), "config.manage")
    add("GET", "/api/config", lambda c: core.config_map(c.conn), "config.manage", tx=False)
    add("POST", "/api/admin/load-demo", lambda c: system.load_demo(c.conn, c.user), "config.manage")
    add("POST", "/api/admin/clear-sample", lambda c: system.clear_sample(c.conn, c.user), "config.manage")

    add("GET", "/api/integrations", lambda c: system.integration_view(c.conn), "config.manage", tx=False)
    add("PUT", "/api/integrations/whatsapp", lambda c: system.save_whatsapp(c.conn, c.user, c.body), "whatsapp.configure")
    add("POST", "/api/integrations/whatsapp/test", lambda c: notify.connection_status(c.conn), "whatsapp.configure", tx=False)
    add("POST", "/api/integrations/whatsapp/qr", lambda c: notify.qr_status(c.conn), "whatsapp.configure", tx=False)
    add("POST", "/api/whatsapp/messages", lambda c: notify.send_patient_message(c.conn, c.user, c.body), "whatsapp.send", tx=False)
    add("POST", "/api/whatsapp/documents", lambda c: notify.send_patient_document(c.conn, c.user, c.body), "whatsapp.send", tx=False)
    add("POST", "/api/integrations/whatsapp/reconnect", lambda c: notify.provider_from_config(c.conn).reconnect(), "whatsapp.configure", tx=False)
    add("POST", "/api/integrations/whatsapp/disconnect", lambda c: notify.provider_from_config(c.conn).disconnect(), "whatsapp.configure", tx=False)
    add("POST", "/api/integrations/whatsapp/send-test", lambda c: _send_test(c), "whatsapp.send", tx=False)
    add("PUT", "/api/integrations/leads", lambda c: system.save_leads_config(c.conn, c.user, c.body), "leads.manage")
    add("POST", "/api/integrations/leads/test", lambda c: system.test_leads(c.conn), "leads.view", tx=False)
    add("POST", "/api/leads/sync", lambda c: system.sync_leads(c.conn, c.user), "leads.manage")
    add("GET", "/api/leads", lambda c: system.list_leads(c.conn, c.q("status")), "leads.view", tx=False)
    add("POST", "/api/leads", lambda c: system.create_lead(c.conn, c.user, c.body), "leads.manage")
    add("POST", "/api/leads/:id/archive", lambda c: system.archive_lead(c.conn, c.user, c.params["id"]), "leads.manage")

    add("GET", "/api/notifications/mine", lambda c: notify.list_notifications(c.conn, "IN_APP", "", c.user["id"]), tx=False)
    add("GET", "/api/notifications", lambda c: notify.list_notifications(c.conn, c.q("channel"), c.q("status"), c.q("user_id") if c.user and "audit.view" in c.user.get("permissions", []) else c.user["id"]), tx=False)
    add("POST", "/api/notifications/:id/read", lambda c: notify.mark_read(c.conn, c.user, c.params["id"]))
    add("POST", "/api/notifications/:id/retry", lambda c: notify.retry_notification(c.conn, c.user, c.params["id"]), "whatsapp.send")
    add("POST", "/api/notifications/:id/cancel", lambda c: notify.cancel_notification(c.conn, c.user, c.params["id"]), "whatsapp.send")
    add("GET", "/api/templates", lambda c: {"items": notify.list_templates(c.conn), "variables": notify.TEMPLATE_VARS}, tx=False)
    add("POST", "/api/templates", lambda c: notify.save_template(c.conn, c.user, c.body), "whatsapp.configure")
    add("PUT", "/api/templates/:id", lambda c: notify.save_template(c.conn, c.user, c.body, c.params["id"]), "whatsapp.configure")

    add("GET", "/api/system/health", lambda c: system.health_report(c.conn), "health.view", tx=False)
    add("GET", "/api/system/health/:name", lambda c: system.component_health(c.conn, c.params["name"]), "health.view", tx=False)
    add("GET", "/api/backups", lambda c: system.list_backups(c.conn), "backup.view", tx=False)
    add("GET", "/api/backups/settings", lambda c: system.backup_settings(c.conn), "backup.view", tx=False)
    add("PUT", "/api/backups/settings", lambda c: system.save_backup_settings(c.conn, c.user, c.body), "config.manage")
    add("POST", "/api/backups", lambda c: system.create_backup(c.conn, c.user, "MANUAL"), "backup.create", tx=False)
    add("POST", "/api/backups/:id/verify", lambda c: system.verify_backup(c.conn, c.user, c.params["id"]), "backup.view", tx=False)
    add("POST", "/api/backups/:id/restore", lambda c: system.restore_backup(c.conn, c.user, c.params["id"], c.body.get("confirm", "")), "backup.restore", tx=False)
    add("DELETE", "/api/backups/:id", lambda c: system.delete_backup(c.conn, c.user, c.params["id"]), "backup.restore", tx=False)

    add("GET", "/api/reports/daily", lambda c: system.daily_report(c.conn, c.q("date") or None), "report.view", tx=False)
    add("GET", "/api/reports/pharmacy", lambda c: pharmacy.alerts(c.conn), "report.view", tx=False)
    add("GET", "/api/reports/export", lambda c: FileResponse(system.report_csv(c.conn, c.q("type") or "daily", c.q("date") or None).encode(), "text/csv", f"{c.q('type') or 'daily'}.csv", "attachment"), "report.export", tx=False)
    add("GET", "/api/audit", lambda c: system.audit_query(c.conn, c.q("module"), c.q("user_id"), c.q("action"), c.q("entity"), c.q("date")), "audit.view", tx=False)
    add("GET", "/api/logs", lambda c: system.logs_query(c.conn, c.q("module"), c.q("level")), "audit.view", tx=False)
    return R


def _send_test(ctx: Ctx):
    phone = str(ctx.body.get("phone") or "").strip()
    if not phone:
        raise ApiError("Enter a phone number for the test.")
    provider = notify.provider_from_config(ctx.conn)
    result = provider.send_text(phone, ctx.body.get("text") or "AIPF Mission Hospital test message. No patient data is included.")
    confirmed = notify.confirmed_message_id(result)
    core.audit(ctx.conn, ctx.user, "whatsapp_test", "whatsapp", "integration", "openwa", new={"ok": bool(confirmed), "phone_last4": phone[-4:]})
    if not confirmed:
        raise ApiError(notify.safe_failure_reason(result), 400, "provider")
    return notify._safe_provider(result)


CATALOG: list[dict] = []
ROUTES = build_routes()


def match(method: str, path: str):
    for route_method, pattern, fn, permission, auth, tx in ROUTES:
        if route_method != method:
            continue
        found = pattern.match(path)
        if found:
            return fn, found.groupdict(), permission, auth, tx
    return None, {}, None, True, None


_DISCONNECT_ERRNOS = {errno.EPIPE, errno.ECONNRESET, errno.ESHUTDOWN}
if hasattr(errno, "ECONNABORTED"):
    _DISCONNECT_ERRNOS.add(errno.ECONNABORTED)
_DISCONNECT_WINERRORS = {10053, 10054}


def client_disconnected(exc: BaseException) -> bool:
    """A browser closed the socket. This is not an application failure."""
    if isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
        return True
    if not isinstance(exc, OSError) or isinstance(exc, (TimeoutError, ConnectionRefusedError)):
        return False
    win = getattr(exc, "winerror", None)
    if win in _DISCONNECT_WINERRORS:
        return True
    return exc.errno in _DISCONNECT_ERRNOS


def api_module(path: str) -> str:
    parts = [part for part in (path or "").split("/") if part]
    if len(parts) >= 2 and parts[0] == "api":
        return parts[1]
    return parts[0] if parts else "-"


def log_api_failure(method: str, path: str, user_id: str, exc: BaseException, *, with_traceback: bool) -> None:
    message = " ".join(redact(str(exc), 300).split())
    print(
        f"AIPF api error method={method or '-'} path={path or '-'} user={user_id or '-'} module={api_module(path)} type={type(exc).__name__} message={message}",
        file=sys.stderr,
        flush=True,
    )
    if not with_traceback:
        return
    stack = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    print(redact(stack, 4000), file=sys.stderr, flush=True)


class HospitalServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        exc = sys.exception()
        if exc is not None and client_disconnected(exc):
            print("AIPF client disconnect during request handling", file=sys.stderr, flush=True)
            return
        super().handle_error(request, client_address)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        return

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except Exception as exc:
            if client_disconnected(exc):
                self._note_disconnect()
                self.close_connection = True
                return
            raise

    def _request_path(self) -> str:
        recorded = getattr(self, "_req_path", "")
        if recorded:
            return recorded
        try:
            return urlparse(getattr(self, "path", "") or "").path or "-"
        except Exception:
            return "-"

    def _note_disconnect(self):
        self.close_connection = True
        if getattr(self, "_disconnect_noted", False):
            return
        self._disconnect_noted = True
        method = getattr(self, "command", "") or "-"
        user = getattr(self, "_req_user", "") or "-"
        print(
            f"AIPF client disconnect method={method} path={self._request_path()} user={user}",
            file=sys.stderr,
            flush=True,
        )

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def do_PATCH(self):
        self._handle()

    def do_PUT(self):
        self._handle()

    def do_DELETE(self):
        self._handle()

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin") or "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Workstation")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, PUT, DELETE, OPTIONS")
        self.send_header("X-Content-Type-Options", "nosniff")

    def _handle(self):
        parsed = urlparse(self.path)
        path = parsed.path
        self._req_path = path
        self._req_user = ""
        if path.startswith("/api/events"):
            return self._events(parse_qs(parsed.query))
        if path == "/api/branding/logo" or path == "/api/public/logo":
            return self._logo()
        if path.startswith("/api/documents/") and path.endswith("/file") and self.command == "GET":
            return self._document(path.split("/")[3])
        if path == "/api/branding/logo" and self.command == "POST":
            pass
        if self.command == "POST" and path == "/api/branding/logo":
            return self._upload_logo()
        fn, params, permission, auth, tx = match(self.command, path)
        if not fn:
            if not path.startswith("/api/"):
                return self._static(path)
            return self._json({"ok": False, "error": {"code": "not_found", "message": "That address is not part of the hospital API."}}, 404)
        length = int(self.headers.get("Content-Length") or 0)
        if length > 12_000_000:
            return self._json({"ok": False, "error": {"code": "too_large", "message": "Upload is too large."}}, 413)
        raw = self.rfile.read(length) if length else b""
        body = {}
        if raw:
            try:
                body = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                return self._json({"ok": False, "error": {"code": "invalid", "message": "Request body must be JSON."}}, 400)
        conn = connect()
        use_tx = tx if tx is not None else self.command in ("POST", "PUT", "PATCH", "DELETE")
        try:
            token = ""
            header = self.headers.get("Authorization") or ""
            if header.startswith("Bearer "):
                token = header[7:].strip()
            if not token:
                token = (parse_qs(parsed.query).get("token") or [""])[0]
            workstation = self.headers.get("X-Workstation") or ""
            user = core.session_user(conn, token, workstation, self.client_address[0]) if token else None
            if user:
                self._req_user = str(user.get("id") or "")
            if auth and not user:
                return self._json({"ok": False, "error": {"code": "unauthorized", "message": "Sign in required."}}, 401)
            if isinstance(permission, (list, tuple)):
                core.permit_any(user, list(permission), conn, f"{self.command} {path}")
            elif permission:
                core.permit(user, permission, conn, f"{self.command} {path}")
            idempotency_key = self.headers.get("Idempotency-Key") or body.get("idempotency_key") or ""
            ctx = Ctx(conn, user, params, parse_qs(parsed.query), body, self.client_address[0], workstation, idempotency_key)
            if use_tx:
                with Tx(conn):
                    result = fn(ctx)
            else:
                result = fn(ctx)
            if isinstance(result, FileResponse):
                return self._file(result)
            return self._json({"ok": True, "data": result})
        except ApiError as exc:
            log_api_failure(self.command, path, self._req_user, exc, with_traceback=False)
            error = {"code": exc.code, "message": exc.message}
            if getattr(exc, "details", None):
                error["details"] = exc.details
            return self._json({"ok": False, "error": error}, exc.status)
        except Exception as exc:
            if client_disconnected(exc):
                self._note_disconnect()
                return
            log_api_failure(self.command, path, self._req_user, exc, with_traceback=True)
            try:
                core.log(conn, "error", api_module(path), f"{type(exc).__name__}: {redact(str(exc), 400)}")
            except Exception:
                pass
            return self._json({"ok": False, "error": {"code": "server", "message": "The hospital server hit an unexpected error. The action was not half-applied if it was inside a transaction."}}, 500)
        finally:
            conn.close()

    def _events(self, query):
        token = (query.get("token") or [""])[0]
        header = self.headers.get("Authorization") or ""
        if header.startswith("Bearer "):
            token = header[7:].strip()
        conn = connect()
        user = core.session_user(conn, token, "", self.client_address[0]) if token else None
        conn.close()
        if not user:
            return self._json({"ok": False, "error": {"code": "unauthorized", "message": "Sign in required."}}, 401)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self._cors()
        self.end_headers()
        q = subscribe()
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                try:
                    item = q.get(timeout=15)
                    data = item.get("data") or {}
                    patient_id = data.get("patient_id")
                    needed = data.get("permission")
                    if patient_id or needed:
                        check = connect()
                        try:
                            visible = access.can_view_patient(check, user, patient_id) if patient_id else True
                            allowed = not needed or needed in (user.get("permissions") or [])
                        finally:
                            check.close()
                        if not visible or not allowed:
                            continue
                    payload = json.dumps(item, default=str)
                    self.wfile.write(f"data: {payload}\n\n".encode())
                except Exception as exc:
                    if client_disconnected(exc):
                        self._note_disconnect()
                        break
                    try:
                        self.wfile.write(b": ping\n\n")
                    except Exception as ping_exc:
                        if client_disconnected(ping_exc):
                            self._note_disconnect()
                        break
                try:
                    self.wfile.flush()
                except Exception as exc:
                    if client_disconnected(exc):
                        self._note_disconnect()
                    break
        except Exception as exc:
            if client_disconnected(exc):
                self._note_disconnect()
        finally:
            unsubscribe(q)

    def _logo(self):
        conn = connect()
        profile = core.hospital(conn)
        conn.close()
        path = Path(profile.get("logo_path") or "")
        if not path.exists():
            return self._json({"ok": False, "error": {"code": "not_found", "message": "No logo uploaded."}}, 404)
        data = path.read_bytes()
        kind = "image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    def _upload_logo(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode())
        except Exception:
            return self._json({"ok": False, "error": {"code": "invalid", "message": "JSON body required."}}, 400)
        import base64
        conn = connect()
        try:
            token = (self.headers.get("Authorization") or "").replace("Bearer ", "")
            user = core.session_user(conn, token, self.headers.get("X-Workstation") or "", self.client_address[0])
            core.permit(user, "config.manage", conn, "POST /api/hospital/logo")
            data = base64.b64decode(body.get("content_base64") or "")
            with Tx(conn):
                result = system.save_logo(conn, user, data, body.get("kind") or "primary")
            return self._json({"ok": True, "data": result})
        except ApiError as exc:
            return self._json({"ok": False, "error": {"code": exc.code, "message": exc.message}}, exc.status)
        finally:
            conn.close()

    def _document(self, doc_id: str):
        conn = connect()
        try:
            token = (self.headers.get("Authorization") or "").replace("Bearer ", "")
            if not token:
                token = (parse_qs(urlparse(self.path).query).get("token") or [""])[0]
            user = core.session_user(conn, token, "", self.client_address[0])
            core.permit(user, "document.view", conn, "GET /api/documents/file")
            doc, data = wards.document_file(conn, doc_id)
            if not access.can_read_document(conn, user, doc):
                access.hide_record(conn, user, "document", doc_id)
            self.send_response(200)
            self.send_header("Content-Type", doc.get("mime_type") or "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Content-Disposition", f"inline; filename=\"{doc.get('filename') or 'document'}\"")
            self._cors()
            self.end_headers()
            self.wfile.write(data)
        except ApiError as exc:
            self._json({"ok": False, "error": {"code": exc.code, "message": exc.message}}, exc.status)
        finally:
            conn.close()

    def _static(self, path: str):
        if not FRONTEND.exists():
            body = b"AIPF hospital API is running. Open the desk application."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        rel = path.lstrip("/") or "index.html"
        file = (FRONTEND / rel).resolve()
        if not str(file).startswith(str(FRONTEND.resolve())) or not file.exists() or file.is_dir():
            file = FRONTEND / "index.html"
        data = file.read_bytes()
        kind = mimetypes.guess_type(str(file))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _write_response(self, status: int, headers: list[tuple[str, str]], body: bytes) -> bool:
        try:
            self.send_response(status)
            for name, value in headers:
                self.send_header(name, value)
            self._cors()
            self.end_headers()
            self.wfile.write(body)
            return True
        except Exception as exc:
            if client_disconnected(exc):
                self._note_disconnect()
                return False
            raise

    def _json(self, payload, status=200):
        raw = json.dumps(payload, default=str).encode()
        self._write_response(
            status,
            [
                ("Content-Type", "application/json; charset=utf-8"),
                ("Content-Length", str(len(raw))),
                ("Cache-Control", "no-store"),
            ],
            raw,
        )

    def _file(self, result: FileResponse):
        headers = [
            ("Content-Type", result.content_type),
            ("Content-Length", str(len(result.data))),
        ]
        if result.filename:
            headers.append(("Content-Disposition", f"{result.disposition}; filename=\"{result.filename}\""))
        self._write_response(200, headers, result.data)


def worker():
    mark_worker(True)
    while True:
        try:
            conn = connect()
            notify.process_queue(conn)
            system.maybe_scheduled_backup(conn)
            conn.close()
            mark_worker(True)
        except Exception:
            traceback.print_exc()
            mark_worker(False)
        time.sleep(8)


def main():
    conn = init_db()
    dialect = conn.dialect
    conn.close()
    thread = threading.Thread(target=worker, name="aipf-worker", daemon=True)
    thread.start()
    server = HospitalServer((HOST, PORT), Handler)
    print(f"AIPF hospital server on http://{HOST}:{PORT}", flush=True)
    print(f"Database {dialect}. Client PCs do not connect to it.", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
