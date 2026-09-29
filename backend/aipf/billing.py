"""One invoice model. Historical rates stay on the line. Payments are separate records."""

from __future__ import annotations

import re

from aipf.repo import billing as billing_sql
from aipf.repo import encounters as encounters_sql
from aipf.repo import inventory as inventory_sql
from aipf.repo import pharmacy as pharmacy_sql
from aipf.repo import ipd as ipd_sql
from aipf.repo import patients as patients_sql
from aipf.repo import payments as payments_sql
from aipf.repo import wards as wards_sql

import hashlib
import json

from .core import audit, config_get, doctor_label, hospital, master_list, name_of, next_number, permit, permit_any
from .db import one, rows
from .events import publish
from .pdf import load_logo, render_invoice_pdf, render_prescription_pdf
from .util import (
    ApiError,
    amount_in_words,
    clean_text,
    display_age,
    format_inr_plain,
    money_mul,
    new_id,
    now_iso,
    require,
    tax_from_bps,
    today_str,
)

CATEGORIES = [
    "CONSULTATION",
    "HOSPITAL SERVICES",
    "PHARMACY",
    "LABORATORY",
    "IPD",
    "OT",
    "PROCEDURE",
    "OTHER",
    "ADJUSTMENT",
]


def _meta(item: dict) -> dict:
    meta = item.get("meta") or "{}"
    if isinstance(meta, dict):
        return meta
    try:
        parsed = json.loads(meta or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def configured_mode(conn, mode: str) -> str:
    wanted = clean_text(mode, 40).lower()
    require(wanted, "Payment mode is required.")
    for item in master_list(conn, "payment_mode"):
        if (item.get("name") or "").strip().lower() == wanted:
            return item["name"]
    raise ApiError("Unknown payment mode. Choose a configured mode.", 400, "validation")


def configured_deposit_type(conn, deposit_type: str) -> str:
    wanted = clean_text(deposit_type, 80).lower()
    require(wanted, "Deposit type is required.")
    for item in master_list(conn, "deposit_type"):
        if (item.get("name") or "").strip().lower() == wanted:
            return item["name"]
    raise ApiError("Unknown deposit type. Choose a configured type.", 400, "validation")


def configured_tax_bps(conn, code: str) -> int:
    wanted = clean_text(code, 40).lower()
    require(wanted, "Choose a configured tax rate.")
    for item in master_list(conn, "tax_rate"):
        tokens = {(item.get("code") or "").strip().lower(), (item.get("name") or "").strip().lower()}
        if wanted not in tokens:
            continue
        meta = _meta(item)
        require("bps" in meta, "Configured tax rate has no basis points.")
        return int(meta["bps"])
    raise ApiError("Unknown tax rate. Choose a configured tax code.", 400, "validation")


def configured_procedure_fee(conn, procedure_id: str | None) -> int | None:
    if not procedure_id:
        return None
    row = billing_sql.procedure_master(conn, procedure_id)
    if not row or int(row.get("active") or 0) != 1:
        return None
    meta = _meta(row)
    if "fee_paise" not in meta:
        return None
    return int(meta["fee_paise"])


def _line_rate(conn, item: dict, from_client: bool) -> int:
    source = item.get("source_module") or "manual"
    master_id = item.get("master_item_id")
    if source == "service":
        require(master_id, "Choose a configured service.")
        row = billing_sql.service_rate(conn, master_id)
        require(row and int(row.get("active") or 0) == 1, "Service not found.", 404, "not_found")
        return int(row["rate_paise"] or 0)
    if source == "lab" and master_id:
        row = billing_sql.lab_price(conn, master_id)
        require(row and int(row.get("active") or 0) == 1, "Lab test not found.", 404, "not_found")
        return int(row["price_paise"] or 0)
    if source == "pharmacy":
        batch_id = item.get("batch_id")
        require(batch_id, "Pharmacy lines must name the dispensed batch.")
        row = billing_sql.batch_rate(conn, batch_id)
        require(row and int(row.get("active") or 0) == 1, "Batch not found.", 404, "not_found")
        return int(row["sale_rate_paise"] or 0)
    if source == "prescription":
        require(master_id, "Link the medicine to a product before billing it.")
        row = inventory_sql.product_by_id(conn, master_id)
        require(row and int(row.get("active") or 0) == 1, "Product not found.", 404, "not_found")
        rate = int(row.get("sale_rate_paise") or 0)
        require(rate > 0, "Set the sale price in Inventory before billing this medicine.")
        return rate
    if from_client and source == "opd" and master_id:
        row = billing_sql.opd_fee(conn, master_id)
        require(row and int(row.get("active") or 0) == 1, "OPD type not found.", 404, "not_found")
        return int(row["fee_paise"] or 0)
    if source == "ot" and master_id:
        fee = configured_procedure_fee(conn, master_id)
        if fee is not None:
            return fee
    return int(item.get("rate_paise") or 0)


def _qty(item: dict):
    from decimal import Decimal

    raw = item.get("qty")
    try:
        qty = Decimal(str(1 if raw in (None, "") else raw))
    except Exception as exc:
        raise ApiError("Quantity must be a number.") from exc
    require(qty > 0, "Quantity must be greater than zero.")
    return qty


def _stored_qty(qty) -> str:
    text = format(qty, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _rowcount(cur) -> int:
    return int(getattr(cur, "rowcount", 0) or 0)


def _scoped_key(scope: str, key: str) -> str:
    return f"{scope}:{key}" if key else ""


def recalc(conn, invoice_id: str) -> dict:
    invoice = billing_sql.q_billing_747(conn, invoice_id)
    require(invoice, "Invoice not found.", 404, "not_found")
    items = billing_sql.q_billing_882(conn, invoice_id)
    gross = 0
    line_discount = 0
    tax = 0
    for item in items:
        gross += money_mul(item["rate_paise"], item["qty"])
        line_discount += int(item["discount_paise"] or 0)
        tax += int(item["tax_paise"] or 0)
    bill_discount = int(invoice["discount_paise"] or 0)
    net = gross - line_discount - bill_discount + tax
    pays = payments_sql.q_billing_1343(conn, invoice_id)
    paid = 0
    deposit_applied = 0
    for pay in pays:
        amt = int(pay["amount_paise"])
        if pay["kind"] in ("PAYMENT", "DEPOSIT_APPLY"):
            paid += amt
        elif pay["kind"] == "REFUND":
            paid -= amt
        if pay["kind"] == "DEPOSIT_APPLY":
            deposit_applied += amt
    due = net - paid
    if invoice["status"] == "VOID":
        payment_status = "VOID"
        due = 0
    elif due <= 0 and (paid > 0 or net <= 0):
        payment_status = "PAID"
        due = 0
    elif paid > 0:
        payment_status = "PARTIAL"
    else:
        payment_status = "UNPAID"
    billing_sql.q_billing_2077(conn, gross, tax, net, paid, max(due, 0), deposit_applied, payment_status, now_iso(), invoice_id)
    return get_invoice(conn, invoice_id)


def list_deposits(conn, patient_id: str) -> dict:
    return {"items": payments_sql.q_billing_2494(conn, patient_id)}


def get_invoice(conn, invoice_id: str) -> dict | None:
    invoice = billing_sql.q_billing_2663(conn, invoice_id, invoice_id)
    if not invoice:
        return None
    invoice["items"] = billing_sql.q_billing_2811(conn, invoice["id"])
    invoice["payments"] = payments_sql.q_billing_2948(conn, invoice["id"])
    invoice["revisions"] = billing_sql.q_billing_3070(conn, invoice["id"])
    invoice["amount_in_words"] = amount_in_words(invoice["net_paise"])
    invoice["patient_name"] = name_of(conn, "patients", invoice["patient_id"])
    return invoice


def list_invoices(conn, q: str = "", status: str = "", payment_status: str = "", patient_id: str = "", limit: int = 80) -> dict:
    items = billing_sql.list_invoices(conn, q, status, payment_status, patient_id, limit)
    for item in items:
        item["patient_name"] = name_of(conn, "patients", item["patient_id"])
    return {"items": items, "total": len(items)}


def open_draft(conn, user, patient_id: str, encounter_id: str | None = None, admission_id: str | None = None, bill_type: str = "OPD", sample: int = 0) -> dict:
    existing = billing_sql.q_billing_4421(conn, patient_id, encounter_id, admission_id)
    if existing:
        return existing
    prefix = config_get(conn, "bill_prefix", "AIPF-BILL")
    number = next_number(conn, "invoice", prefix, 6, True)
    iid = new_id("INV")
    billing_sql.q_billing_4897(conn, iid, number, patient_id, encounter_id, admission_id, bill_type, (user or {}).get("id"), now_iso(), now_iso(), sample)
    audit(conn, user, "invoice_create", "billing", "invoice", iid, new={"number": number})
    publish("invoice.updated", {"id": iid, "number": number, "patient_id": patient_id})
    return billing_sql.q_billing_5452(conn, iid)


def add_item(conn, user, invoice_id: str, item: dict, allow_finalized: bool = False, from_client: bool = False) -> dict:
    invoice = billing_sql.q_billing_5617(conn, invoice_id)
    require(invoice, "Invoice not found.", 404, "not_found")
    if invoice["status"] == "VOID":
        raise ApiError("This bill is void.")
    if invoice["status"] == "FINALIZED" and not allow_finalized:
        raise ApiError("This bill is finalized. Add an adjustment with a reason instead of editing it.")
    category = item.get("category") or "OTHER"
    require(category in CATEGORIES, "Unknown bill category.")
    rate = _line_rate(conn, item, from_client)
    qty = _qty(item)
    discount = int(item.get("discount_paise") or 0)
    require(discount >= 0, "Discount cannot be negative.")
    line_gross = money_mul(rate, qty)
    if line_gross >= 0:
        require(discount <= line_gross, "Discount cannot exceed the line amount.")
    else:
        require(discount == 0, "A credit line cannot also carry a discount.")
    client_tax = item.get("tax_paise")
    tax_code = clean_text(item.get("tax_code"), 40)
    if client_tax not in (None, "", 0, "0") and not tax_code:
        raise ApiError("Tax is calculated from a configured rate, not a client amount.", 400, "validation")
    tax = tax_from_bps(line_gross - discount, configured_tax_bps(conn, tax_code)) if tax_code else 0
    amount = line_gross - discount + tax
    iid = new_id("II")
    billing_sql.q_billing_6414(conn, iid, invoice_id, item.get("source_module"), item.get("source_id"), item.get("master_item_id"), clean_text(item.get("description"), 240) or "Service", category, rate, _stored_qty(qty), clean_text(item.get("unit"), 40), discount, tax, amount, int(item.get("sort_order") or 0), now_iso())
    updated = recalc(conn, invoice_id)
    updated["added_item_id"] = iid
    return updated


def remove_draft_item(conn, user, item_id: str) -> dict:
    permit(user, "billing.create")
    item = billing_sql.q_billing_7233(conn, item_id)
    require(item, "Line not found.", 404, "not_found")
    invoice = billing_sql.lock_invoice(conn, item["invoice_id"])
    require(invoice, "Invoice not found.", 404, "not_found")
    from .access import guard_patient
    guard_patient(conn, user, invoice["patient_id"])
    require(invoice["status"] == "DRAFT", "Only draft lines can be removed. Finalized bills need an adjustment.")
    if _stock_line(conn, item):
        permit(user, "billing.medicine_issue")
        _reverse_issued(conn, user, invoice, item)
    billing_sql.q_billing_7554(conn, item_id)
    audit(conn, user, "invoice_item_remove", "billing", "invoice", invoice["id"], old=item)
    return recalc(conn, invoice["id"])


def _stock_line(conn, item: dict) -> bool:
    if item.get("source_module") == "billing_issue":
        return True
    if pharmacy_sql.dispense_by_invoice_item(conn, item["id"]):
        return True
    return item.get("source_module") == "pharmacy" and bool(pharmacy_sql.dispense_by_id(conn, item.get("source_id") or ""))


def _selling_rate(product: dict, batch: dict, manual) -> tuple[int, str]:
    master = int(product.get("sale_rate_paise") or 0)
    if master > 0:
        return master, "master"
    batch_rate = int((batch or {}).get("sale_rate_paise") or 0)
    if batch_rate > 0:
        return batch_rate, "batch"
    try:
        entered = int(manual or 0)
    except (TypeError, ValueError) as exc:
        raise ApiError("Enter the selling rate in paise.") from exc
    if entered > 0:
        return entered, "manual"
    raise ApiError("Set a selling rate before billing this medicine, or enter one. Nothing was billed.")


def _issue_record(conn, item: dict):
    row = pharmacy_sql.dispense_by_invoice_item(conn, item["id"])
    if row:
        return row
    if item.get("source_module") == "pharmacy" and item.get("source_id"):
        return pharmacy_sql.dispense_by_id(conn, item["source_id"])
    return None


def _refresh_prescription(conn, prescription_id: str) -> None:
    if not prescription_id:
        return
    lines = encounters_sql.q_pharmacy_16748(conn, prescription_id)
    issued = any(float(line.get("dispensed_qty") or 0) > 0 for line in lines)
    open_qty = any(
        (line.get("quantity") or 0) and float(line.get("dispensed_qty") or 0) + 0.0001 < float(line["quantity"])
        for line in lines
    )
    if not issued:
        status = "FINALIZED"
    elif open_qty:
        status = "PARTIAL"
    else:
        status = "DISPENSED"
    encounters_sql.q_pharmacy_17035(conn, status, now_iso(), prescription_id)


def _set_dispensed(conn, item_id: str, prescription_id: str, dispensed: float, product_id: str | None) -> None:
    item = encounters_sql.prescription_item(conn, item_id)
    if not item:
        return
    dispensed = max(0.0, dispensed)
    prescribed = float(item.get("quantity") or 0)
    if prescribed and dispensed + 0.0001 >= prescribed:
        status = "DISPENSED"
    elif dispensed > 0:
        status = "PARTIAL"
    else:
        status = "PRESCRIBED"
    encounters_sql.q_pharmacy_16054(conn, dispensed, status, product_id or item.get("product_id"), item_id)
    _refresh_prescription(conn, prescription_id)


def _reverse_issued(conn, user, invoice: dict, item: dict) -> None:
    from .pharmacy import move

    record = _issue_record(conn, item)
    if record:
        batch_id = record["batch_id"]
        qty = float(record["qty"])
        prescription_item_id = record.get("prescription_item_id")
        prescription_id = record.get("prescription_id")
        product_id = record.get("product_id")
    elif item.get("source_module") == "billing_issue":
        batch_id = item.get("source_id")
        qty = float(item.get("qty") or 0)
        prescription_item_id = None
        prescription_id = None
        product_id = item.get("master_item_id")
    else:
        return
    require(batch_id and qty > 0, "This medicine line has no batch to return.")
    move(
        conn, user, batch_id, qty, "BILLING_RETURN", "invoice", invoice["id"],
        f"Removed from draft bill {invoice.get('number')}",
    )
    if record:
        pharmacy_sql.delete_dispense(conn, record["id"])
    if prescription_item_id:
        current = encounters_sql.prescription_item(conn, prescription_item_id)
        already = float((current or {}).get("dispensed_qty") or 0)
        _set_dispensed(conn, prescription_item_id, prescription_id, already - qty, product_id)


def issue_medicines(conn, user, invoice_id: str, payload: dict) -> dict:
    """Add medicines to a draft bill and deduct stock in the same transaction."""
    from .db import begin, commit, rollback
    from .pharmacy import move

    permit(user, "billing.medicine_issue")
    own = not conn.in_transaction
    if own:
        begin(conn)
    try:
        result = _issue_medicines(conn, user, invoice_id, payload, move)
        if own:
            commit(conn)
        return result
    except Exception:
        if own:
            rollback(conn)
        raise


def _issue_medicines(conn, user, invoice_id: str, payload: dict, move) -> dict:
    raw_items = payload.get("items") if isinstance(payload.get("items"), list) else [payload]
    require(raw_items, "Choose a medicine.")
    key = clean_text(payload.get("idempotency_key"), 80)
    digest = ""
    if key:
        digest = hashlib.sha256(json.dumps({"invoice_id": invoice_id, "items": raw_items, "confirm": bool(payload.get("confirm"))}, default=str, sort_keys=True).encode()).hexdigest()
        claim = billing_sql.claim_issue_key(conn, key, digest, now_iso())
        if claim["status"] == "conflict":
            raise ApiError("This request was already used for a different bill.", 409, "idempotency_conflict")
        if claim["status"] == "in_progress":
            raise ApiError("That request is still being saved.", 409, "idempotency_conflict")
        if claim["status"] == "replay":
            return get_invoice(conn, claim["entity_id"])
    invoice = billing_sql.lock_invoice(conn, invoice_id)
    require(invoice, "Invoice not found.", 404, "not_found")
    from .access import guard_patient
    guard_patient(conn, user, invoice["patient_id"])
    require(invoice["status"] == "DRAFT", "This bill is finalized. Add an adjustment with a reason instead of editing it.")
    warnings = []
    for raw in raw_items:
        warning = _issue_one(conn, user, invoice, raw if isinstance(raw, dict) else {}, bool(payload.get("confirm")), move)
        if warning:
            warnings.append(warning)
    if key:
        billing_sql.finish_issue_key(conn, key, invoice_id)
    result = get_invoice(conn, invoice_id)
    result["warnings"] = warnings
    audit(conn, user, "billing_medicine_issue", "billing", "invoice", invoice_id, new={"count": len(raw_items), "warnings": warnings})
    return result


def _issue_one(conn, user, invoice: dict, raw: dict, confirm: bool, move) -> str:
    prescription_item = None
    prescription = None
    product_id = clean_text(raw.get("product_id"), 40)
    if raw.get("prescription_item_id"):
        prescription_item = encounters_sql.prescription_item(conn, raw["prescription_item_id"])
        require(prescription_item, "Prescription line not found.", 404, "not_found")
        prescription = encounters_sql.q_pharmacy_11761(conn, prescription_item["prescription_id"])
        require(prescription, "Prescription not found.", 404, "not_found")
        require(prescription.get("status") != "CANCELLED" and prescription_item.get("status") != "CANCELLED", "That prescription line is cancelled.")
        require(prescription.get("status") in ("FINALIZED", "PARTIAL", "DISPENSED"), "Finalize the prescription before billing it.", 409, "invalid_transition")
        require(prescription["patient_id"] == invoice["patient_id"], "That prescription belongs to a different patient.")
        if invoice.get("encounter_id") and prescription.get("encounter_id") and invoice["encounter_id"] != prescription["encounter_id"]:
            raise ApiError("That prescription is for a different visit.")
        linked = prescription_item.get("product_id")
        if linked and product_id and linked != product_id:
            raise ApiError("This is not the prescribed product. The prescription was not changed.", 409, "product_mismatch")
        product_id = product_id or linked
        require(product_id, f"Link {prescription_item.get('medicine_name') or 'this medicine'} to a stock product before billing it. The prescription was not changed.")
    require(product_id, "Choose a medicine. An unknown barcode cannot create one.")
    product = inventory_sql.product_by_id(conn, product_id)
    require(product and int(product.get("active") or 0) == 1, "Medicine not found.", 404, "not_found")
    batch_id = clean_text(raw.get("batch_id"), 40)
    if not batch_id:
        suggested = inventory_sql.q_pharmacy_11394(conn, product_id, today_str())
        require(suggested, f"No usable batch is in stock for {product.get('name')}.")
        batch_id = suggested["id"]
    batch = inventory_sql.q_pharmacy_13670(conn, batch_id)
    require(batch and batch["product_id"] == product_id, "Batch does not belong to this medicine.", 409, "batch_conflict")
    require(int(batch.get("active") or 0) == 1, "Batch is inactive.")
    if batch.get("expiry_date") and batch["expiry_date"] < today_str() and config_get(conn, "allow_expired_dispense", "0") != "1":
        raise ApiError(f"Batch {batch['batch_no']} expired on {batch['expiry_date']}. It was not billed.")
    qty = _qty({"qty": raw.get("qty") if raw.get("qty") not in (None, "") else (prescription_item.get("quantity") if prescription_item else 1)})
    warning = ""
    if prescription_item and prescription_item.get("quantity"):
        prescribed = float(prescription_item["quantity"])
        already = float(prescription_item.get("dispensed_qty") or 0)
        if abs((already + float(qty)) - prescribed) > 0.001 and not confirm:
            raise ApiError(
                f"Billed quantity {float(qty):g} differs from prescribed {prescribed:g}. Confirm to bill this quantity. The prescription was not changed.",
                409,
                "qty_mismatch",
            )
        if abs((already + float(qty)) - prescribed) > 0.001:
            warning = f"{product.get('name')} billed {float(qty):g}, prescribed {prescribed:g}."
    rate, _source = _selling_rate(product, batch, raw.get("rate_paise"))
    amount = money_mul(rate, qty)
    description = " ".join(part for part in [product.get("name"), product.get("strength")] if part)
    description = f"{description} · batch {batch['batch_no']}"
    updated = add_item(
        conn,
        user,
        invoice["id"],
        {
            "description": description,
            "category": "PHARMACY",
            "rate_paise": rate,
            "qty": qty,
            "unit": batch.get("unit") or product.get("unit"),
            "source_module": "billing_issue",
            "source_id": batch_id,
            "master_item_id": product_id,
        },
    )
    move(
        conn, user, batch_id, float(qty), "BILLING_ISSUE", "invoice", invoice["id"],
        f"Issued on bill {invoice.get('number')}",
    )
    if prescription_item:
        line_id = new_id("DL")
        pharmacy_sql.q_pharmacy_15133(
            conn, line_id, prescription["id"], prescription_item["id"], invoice["patient_id"],
            invoice.get("encounter_id"), product_id, batch_id, float(qty), batch.get("unit") or product.get("unit"),
            rate, amount, 0, "", updated["added_item_id"], user["id"], now_iso(),
        )
        billing_sql.update_draft_line(
            conn, _stored_qty(qty), rate, amount, description, line_id,
            batch.get("unit") or product.get("unit"), updated["added_item_id"],
        )
        already = float(prescription_item.get("dispensed_qty") or 0)
        _set_dispensed(conn, prescription_item["id"], prescription["id"], already + float(qty), product_id)
    return warning


def revise_issued_line(conn, user, item_id: str, payload: dict) -> dict:
    from .db import begin, commit, rollback
    from .pharmacy import move

    permit(user, "billing.medicine_issue")
    own = not conn.in_transaction
    if own:
        begin(conn)
    try:
        result = _revise_issued_line(conn, user, item_id, payload, move)
        if own:
            commit(conn)
        return result
    except Exception:
        if own:
            rollback(conn)
        raise


def _revise_issued_line(conn, user, item_id: str, payload: dict, move) -> dict:
    item = billing_sql.q_billing_7233(conn, item_id)
    require(item, "Line not found.", 404, "not_found")
    invoice = billing_sql.lock_invoice(conn, item["invoice_id"])
    require(invoice and invoice["status"] == "DRAFT", "Only a draft medicine line can be changed. A finalized bill needs an adjustment.")
    from .access import guard_patient
    guard_patient(conn, user, invoice["patient_id"])
    require(_stock_line(conn, item), "Only an issued medicine line can be changed here.")
    record = _issue_record(conn, item)
    old_batch = record["batch_id"] if record else item.get("source_id")
    old_qty = float(item.get("qty") or 0)
    new_batch = clean_text(payload.get("batch_id"), 40) or old_batch
    new_qty = _qty({"qty": payload.get("qty") if payload.get("qty") not in (None, "") else old_qty})
    product_id = (record or {}).get("product_id") or item.get("master_item_id")
    product = inventory_sql.product_by_id(conn, product_id)
    require(product and int(product.get("active") or 0) == 1, "Medicine not found.", 404, "not_found")
    batch = inventory_sql.q_pharmacy_13670(conn, new_batch)
    require(batch and batch["product_id"] == product_id, "Batch does not belong to this medicine.", 409, "batch_conflict")
    require(int(batch.get("active") or 0) == 1, "Batch is inactive.")
    if batch.get("expiry_date") and batch["expiry_date"] < today_str() and config_get(conn, "allow_expired_dispense", "0") != "1":
        raise ApiError(f"Batch {batch['batch_no']} expired on {batch['expiry_date']}. It was not billed.")
    prescription_item = encounters_sql.prescription_item(conn, record["prescription_item_id"]) if record and record.get("prescription_item_id") else None
    if prescription_item and prescription_item.get("quantity"):
        prescribed = float(prescription_item["quantity"])
        already = float(prescription_item.get("dispensed_qty") or 0) - old_qty + float(new_qty)
        if abs(already - prescribed) > 0.001 and not payload.get("confirm"):
            raise ApiError(
                f"Billed quantity {float(new_qty):g} differs from prescribed {prescribed:g}. Confirm to keep this quantity. The prescription was not changed.",
                409,
                "qty_mismatch",
            )
    if new_batch == old_batch and abs(float(new_qty) - old_qty) < 0.0001:
        return get_invoice(conn, invoice["id"])
    move(conn, user, old_batch, old_qty, "BILLING_RETURN", "invoice", invoice["id"], f"Reversed before change on bill {invoice.get('number')}")
    move(conn, user, new_batch, float(new_qty), "BILLING_ISSUE", "invoice", invoice["id"], f"Issued on bill {invoice.get('number')}")
    rate, _source = _selling_rate(product, batch, payload.get("rate_paise") or item.get("rate_paise"))
    amount = money_mul(rate, new_qty)
    description = " ".join(part for part in [product.get("name"), product.get("strength")] if part)
    description = f"{description} · batch {batch['batch_no']}"
    source_id = record["id"] if record else new_batch
    billing_sql.update_draft_line(conn, _stored_qty(new_qty), rate, amount, description, source_id, batch.get("unit") or product.get("unit"), item["id"])
    if record:
        pharmacy_sql.update_dispense(conn, float(new_qty), new_batch, rate, amount, record["id"])
        if prescription_item:
            already = float(prescription_item.get("dispensed_qty") or 0) - old_qty + float(new_qty)
            _set_dispensed(conn, prescription_item["id"], record.get("prescription_id"), already, product_id)
    audit(conn, user, "billing_medicine_revise", "billing", "invoice", invoice["id"], old={"qty": old_qty, "batch_id": old_batch}, new={"qty": float(new_qty), "batch_id": new_batch})
    return recalc(conn, invoice["id"])


def save_notes(conn, user, invoice_id: str, notes: str) -> dict:
    permit(user, "billing.create")
    invoice = billing_sql.lock_invoice(conn, invoice_id)
    require(invoice, "Invoice not found.", 404, "not_found")
    from .access import guard_patient
    guard_patient(conn, user, invoice["patient_id"])
    require(invoice["status"] == "DRAFT", "Notes on a finalized bill are not edited here.")
    billing_sql.set_notes(conn, clean_text(notes, 1000), now_iso(), invoice_id)
    audit(conn, user, "invoice_notes", "billing", "invoice", invoice_id)
    return get_invoice(conn, invoice_id)


def search_counter_medicines(conn, user, q: str) -> dict:
    permit(user, "billing.medicine_issue")
    items = []
    for product in inventory_sql.search_for_billing(conn, q or ""):
        product = dict(product)
        batches = []
        for batch in inventory_sql.q_pharmacy_993(conn, product["id"]):
            if int(batch.get("active") or 0) != 1:
                continue
            rate, source = _selling_rate(product, batch, 0) if int(product.get("sale_rate_paise") or 0) or int(batch.get("sale_rate_paise") or 0) else (0, "manual")
            batches.append({
                "id": batch["id"],
                "batch_no": batch.get("batch_no"),
                "expiry_date": batch.get("expiry_date"),
                "qty_on_hand": batch.get("qty_on_hand"),
                "unit": batch.get("unit"),
                "sale_rate_paise": int(batch.get("sale_rate_paise") or 0),
                "rate_paise": rate,
                "rate_source": source,
            })
        product["batches"] = batches
        product["stock"] = sum(float(batch.get("qty_on_hand") or 0) for batch in batches)
        items.append(product)
    return {"items": items, "total": len(items)}


def billing_desk(conn, user, patient_id: str, encounter_id: str = "") -> dict:
    from .access import guard_patient
    from .clinical import get_encounter

    permit(user, "billing.view")
    patient_id = clean_text(patient_id, 40)
    require(patient_id, "Choose a patient.")
    guard_patient(conn, user, patient_id)
    patient = patients_sql.q_billing_18932(conn, patient_id)
    require(patient, "Patient not found.", 404, "not_found")
    encounters = encounters_sql.q_clinical_29080(conn, patient_id)
    chosen_id = clean_text(encounter_id, 40) or (encounters[0]["id"] if encounters else "")
    encounter = None
    if chosen_id:
        full = get_encounter(conn, chosen_id)
        require(full.get("patient_id") == patient_id, "That visit is for a different patient.")
        encounter = {
            "id": full["id"],
            "status": full.get("status"),
            "arrived_at": full.get("arrived_at"),
            "doctor_name": full.get("doctor_name") or "",
            "department_name": full.get("department_name") or "",
            "prescriptions": [],
        }
        for rx in full.get("prescriptions") or []:
            encounter["prescriptions"].append({
                "id": rx["id"],
                "status": rx.get("status"),
                "doctor_id": rx.get("doctor_id"),
                "items": [
                    {
                        "id": item["id"],
                        "medicine_name": item.get("medicine_name"),
                        "strength": item.get("strength"),
                        "dose": item.get("dose"),
                        "frequency": item.get("frequency"),
                        "duration": item.get("duration"),
                        "quantity": item.get("quantity"),
                        "unit": item.get("unit"),
                        "dispensed_qty": item.get("dispensed_qty"),
                        "status": item.get("status"),
                        "product_id": item.get("product_id"),
                    }
                    for item in rx.get("items") or []
                ],
            })
    draft = billing_sql.q_billing_4421(conn, patient_id, chosen_id or None, None)
    invoice = get_invoice(conn, draft["id"]) if draft else None
    return {
        "patient": {
            "id": patient["id"],
            "name": patient.get("name"),
            "gender": patient.get("gender"),
            "age": display_age(patient),
            "phone": patient.get("primary_phone") or "",
            "guardian_name": patient.get("guardian_name") or "",
        },
        "encounters": [{"id": row["id"], "arrived_at": row.get("arrived_at"), "status": row.get("status")} for row in encounters],
        "encounter": encounter,
        "invoice": invoice,
    }


def set_discount(conn, user, invoice_id: str, discount_paise: int, reason: str) -> dict:
    permit(user, "billing.create")
    invoice = billing_sql.q_billing_7890(conn, invoice_id)
    require(invoice, "Invoice not found.", 404, "not_found")
    require(invoice["status"] == "DRAFT", "Discount on a finalized bill must be posted as an adjustment.")
    require(discount_paise >= 0, "Discount cannot be negative.")
    if int(discount_paise) > 0:
        require(clean_text(reason, 240), "A discount needs a reason.")
    items = billing_sql.q_billing_882(conn, invoice_id)
    line_discount = sum(int(row["discount_paise"] or 0) for row in items)
    gross = sum(money_mul(row["rate_paise"], row["qty"]) for row in items)
    require(int(discount_paise) <= max(0, gross - line_discount), "Discount cannot exceed the bill.")
    billing_sql.q_billing_8189(conn, int(discount_paise), clean_text(reason, 240), now_iso(), invoice_id)
    audit(conn, user, "invoice_discount", "billing", "invoice", invoice_id, old={"discount_paise": invoice["discount_paise"]}, new={"discount_paise": discount_paise, "reason": reason})
    return recalc(conn, invoice_id)


def snapshot(conn, invoice_id: str) -> dict:
    invoice = get_invoice(conn, invoice_id)
    return {
        "number": invoice["number"],
        "status": invoice["status"],
        "gross_paise": invoice["gross_paise"],
        "discount_paise": invoice["discount_paise"],
        "net_paise": invoice["net_paise"],
        "paid_paise": invoice["paid_paise"],
        "due_paise": invoice["due_paise"],
        "items": invoice["items"],
    }


def finalize(conn, user, invoice_id: str) -> dict:
    permit(user, "billing.finalize")
    invoice = get_invoice(conn, invoice_id)
    require(invoice, "Invoice not found.", 404, "not_found")
    require(invoice["status"] == "DRAFT", "Only a draft bill can be finalized.")
    require(invoice["items"], "Add at least one line before finalizing.")
    pending = [i for i in invoice["items"] if i["description"].startswith("[PRICE PENDING]")]
    require(not pending, "Assign a price to every custom test before finalizing.")
    before = snapshot(conn, invoice_id)
    changed = billing_sql.q_billing_9622(conn, now_iso(), user["id"], now_iso(), invoice_id)
    require(_rowcount(changed) == 1, "Only a draft bill can be finalized.", 409, "conflict")
    after = recalc(conn, invoice_id)
    billing_sql.q_billing_9882(conn, invoice_id, after["revision"], "Finalized", user["id"], user.get("workstation"), now_iso(), json.dumps(before, default=str), json.dumps(snapshot(conn, invoice_id), default=str))
    audit(conn, user, "invoice_finalize", "billing", "invoice", invoice_id, new={"number": after["number"], "net_paise": after["net_paise"]})
    publish("invoice.updated", {"id": invoice_id, "status": "FINALIZED", "patient_id": after["patient_id"]})
    from .notify import maybe_queue_bill_message
    maybe_queue_bill_message(conn, user, invoice_id)
    return after


def _payment_hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _replay(conn, invoice_id: str, payment_id: str, own: bool, commit) -> dict:
    updated = get_invoice(conn, invoice_id)
    updated["payment_id"] = payment_id
    updated["refund_id"] = payment_id
    updated["idempotent_replay"] = True
    updated["payment"] = payments_sql.get_payment(conn, payment_id)
    if own:
        commit(conn)
    return updated


def record_payment(
    conn,
    user,
    invoice_id: str,
    mode: str,
    amount_paise: int,
    reference: str = "",
    notes: str = "",
    kind: str = "PAYMENT",
    idempotency_key: str | None = None,
    require_key: bool = False,
) -> dict:
    from .db import begin, commit, rollback

    permit_any(user, ["payment.create", "billing.create"], conn, "payment")
    amount = int(amount_paise)
    require(amount > 0, "Amount must be greater than zero.")
    mode = configured_mode(conn, mode)
    reference = clean_text(reference, 80)
    notes = clean_text(notes, 240)
    key = clean_text(idempotency_key, 120) if idempotency_key else ""
    if require_key:
        require(key, "An idempotency key is required for this payment.")
    stored_key = _scoped_key("pay", key)
    digest = _payment_hash({
        "amount_paise": amount,
        "invoice_id": invoice_id,
        "kind": kind,
        "mode": mode,
        "notes": notes,
        "reference": reference,
    })
    own = not conn.in_transaction
    if own:
        begin(conn)
    try:
        locked = billing_sql.lock_invoice(conn, invoice_id)
        require(locked, "Invoice not found.", 404, "not_found")
        if stored_key:
            existing = payments_sql.get_idempotency(conn, stored_key)
            if existing:
                if existing["request_hash"] != digest:
                    raise ApiError("This idempotency key was already used for a different payment.", 409, "idempotency_conflict")
                return _replay(conn, invoice_id, existing["entity_id"], own, commit)
        require(locked["status"] == "FINALIZED", "Finalize the bill before taking payment.")
        if kind in ("PAYMENT", "DEPOSIT_APPLY"):
            require(amount <= int(locked["due_paise"] or 0), "Payment exceeds the amount due.", 409, "conflict")
        pid = new_id("PAY")
        if stored_key:
            try:
                outcome = payments_sql.claim_payment(
                    conn,
                    stored_key,
                    digest,
                    {
                        "id": pid,
                        "invoice_id": invoice_id,
                        "patient_id": locked["patient_id"],
                        "admission_id": locked.get("admission_id"),
                        "kind": kind,
                        "mode": mode,
                        "amount_paise": amount,
                        "reference": reference,
                        "notes": notes,
                        "received_by": user["id"],
                        "workstation": user.get("workstation"),
                        "received_at": now_iso(),
                    },
                )
            except payments_sql.IdempotencyConflict as exc:
                raise ApiError("This idempotency key was already used for a different payment.", 409, "idempotency_conflict") from exc
            if outcome["status"] == "replay":
                return _replay(conn, invoice_id, outcome["payment_id"], own, commit)
            pid = outcome["payment_id"]
        else:
            payments_sql.q_billing_11129(
                conn, pid, invoice_id, locked["patient_id"], locked.get("admission_id"),
                kind, mode, amount, reference, notes, user["id"], user.get("workstation"), now_iso(),
            )
        updated = recalc(conn, invoice_id)
        audit(conn, user, "payment", "billing", "payment", pid, new={"invoice": locked["number"], "mode": mode, "amount_paise": amount, "kind": kind})
        publish("invoice.updated", {"id": invoice_id, "payment_id": pid, "patient_id": locked["patient_id"]})
        updated["payment_id"] = pid
        updated["idempotent_replay"] = False
        if own:
            commit(conn)
        return updated
    except Exception:
        if own:
            rollback(conn)
        raise


def apply_deposit(
    conn,
    user,
    invoice_id: str,
    deposit_id: str,
    amount_paise: int | None = None,
    idempotency_key: str | None = None,
    require_key: bool = False,
) -> dict:
    from .db import begin, commit, rollback

    permit_any(user, ["deposit.allocate", "billing.create"], conn, "deposit_allocate")
    require(amount_paise is not None, "Enter the amount to allocate. A deposit is not applied automatically.")
    use = int(amount_paise)
    require(use > 0, "Amount must be greater than zero.")
    key = clean_text(idempotency_key, 120) if idempotency_key else ""
    if require_key:
        require(key, "An idempotency key is required to allocate a deposit.")
    own = not conn.in_transaction
    if own:
        begin(conn)
    try:
        deposit = payments_sql.lock_deposit(conn, deposit_id)
        require(deposit and deposit.get("status") == "OPEN", "Deposit not found.", 404, "not_found")
        if key:
            existing = payments_sql.get_idempotency(conn, _scoped_key("pay", key))
            if existing:
                updated = _replay(conn, invoice_id, existing["entity_id"], own, commit)
                return updated
        require(use <= int(deposit["balance_paise"] or 0), "Amount exceeds the deposit balance.", 409, "conflict")
        invoice = billing_sql.lock_invoice(conn, invoice_id)
        require(invoice, "Invoice not found.", 404, "not_found")
        require(deposit["patient_id"] == invoice["patient_id"], "Deposit belongs to another patient.")
        result = record_payment(
            conn, user, invoice_id, deposit.get("mode") or "", use,
            reference=deposit_id, notes="Deposit allocated", kind="DEPOSIT_APPLY",
            idempotency_key=key or None,
        )
        if result.get("idempotent_replay"):
            if own:
                commit(conn)
            return result
        changed = payments_sql.allocate_balance(conn, deposit_id, use)
        require(changed == 1, "Deposit balance changed. Allocate the remaining balance again.", 409, "conflict")
        audit(conn, user, "deposit_apply", "billing", "deposit", deposit_id, new={"invoice_id": invoice_id, "amount_paise": use, "patient_id": invoice["patient_id"]})
        publish("invoice.updated", {"id": invoice_id, "deposit_id": deposit_id, "patient_id": invoice["patient_id"]})
        updated = get_invoice(conn, invoice_id)
        updated["payment_id"] = result.get("payment_id")
        updated["idempotent_replay"] = False
        if own:
            commit(conn)
        return updated
    except Exception:
        if own:
            rollback(conn)
        raise


def create_deposit(
    conn,
    user,
    patient_id: str,
    amount_paise: int,
    mode: str,
    admission_id: str | None = None,
    reference: str = "",
    notes: str = "",
    deposit_type: str = "",
    encounter_id: str | None = None,
    idempotency_key: str | None = None,
    require_key: bool = False,
) -> dict:
    from .db import begin, commit, rollback

    permit_any(user, ["deposit.create", "billing.create"], conn, "deposit")
    require(patients_sql.q_billing_13318(conn, patient_id), "Patient not found.", 404, "not_found")
    amount = int(amount_paise)
    require(amount > 0, "Amount must be greater than zero.")
    mode = configured_mode(conn, mode)
    dtype = configured_deposit_type(conn, deposit_type)
    reference = clean_text(reference, 80)
    notes = clean_text(notes, 240)
    if encounter_id:
        encounter = encounters_sql.q_billing_19021(conn, encounter_id)
        require(encounter and encounter["patient_id"] == patient_id, "Encounter does not belong to this patient.", 404, "not_found")
    key = clean_text(idempotency_key, 120) if idempotency_key else ""
    if require_key:
        require(key, "An idempotency key is required to receive a deposit.")
    digest = _payment_hash({
        "admission_id": admission_id or "",
        "amount_paise": amount,
        "deposit_type": dtype,
        "encounter_id": encounter_id or "",
        "mode": mode,
        "patient_id": patient_id,
    })
    stored_key = _scoped_key("deposit", key)
    own = not conn.in_transaction
    if own:
        begin(conn)
    try:
        did = new_id("DEP")
        if stored_key:
            try:
                outcome = payments_sql.claim_scope(conn, stored_key, "deposit", digest, did, now_iso())
            except payments_sql.IdempotencyConflict as exc:
                raise ApiError("This idempotency key was already used for a different deposit.", 409, "idempotency_conflict") from exc
            if outcome["status"] == "replay":
                row = payments_sql.q_billing_14535(conn, outcome["entity_id"])
                row["idempotent_replay"] = True
                if own:
                    commit(conn)
                return row
            did = outcome["entity_id"]
        payments_sql.insert_deposit(
            conn, did, patient_id, admission_id, encounter_id, dtype, amount, amount,
            mode, reference, user["id"], now_iso(), notes,
        )
        payments_sql.q_billing_13927(
            conn, new_id("PAY"), None, patient_id, admission_id, mode, amount, did,
            "Deposit received", user["id"], user.get("workstation"), now_iso(),
        )
        audit(conn, user, "deposit", "billing", "deposit", did, new={"amount_paise": amount, "patient_id": patient_id, "deposit_type": dtype})
        publish("invoice.updated", {"deposit_id": did, "patient_id": patient_id})
        row = payments_sql.q_billing_14535(conn, did)
        row["idempotent_replay"] = False
        if own:
            commit(conn)
        return row
    except Exception:
        if own:
            rollback(conn)
        raise


def refund_deposit(conn, user, deposit_id: str, reason: str, idempotency_key: str | None = None, require_key: bool = False) -> dict:
    from .access import guard_patient
    from .db import begin, commit, rollback

    permit_any(user, ["payment.refund", "billing.refund"], conn, "deposit_refund")
    require(clean_text(reason, 240), "A deposit refund needs a reason.")
    key = clean_text(idempotency_key, 120) if idempotency_key else ""
    if require_key:
        require(key, "An idempotency key is required for this refund.")
    own = not conn.in_transaction
    if own:
        begin(conn)
    try:
        deposit = payments_sql.lock_deposit(conn, deposit_id)
        require(deposit, "Deposit not found.", 404, "not_found")
        guard_patient(conn, user, deposit["patient_id"])
        stored_key = _scoped_key("deposit-refund", key)
        digest = _payment_hash({"deposit_id": deposit_id, "reason": clean_text(reason, 240)})
        if stored_key:
            try:
                outcome = payments_sql.claim_scope(conn, stored_key, "deposit-refund", digest, deposit_id, now_iso())
            except payments_sql.IdempotencyConflict as exc:
                raise ApiError("This idempotency key was already used for a different refund.", 409, "idempotency_conflict") from exc
            if outcome["status"] == "replay":
                row = payments_sql.q_billing_14535(conn, deposit_id)
                row["idempotent_replay"] = True
                if own:
                    commit(conn)
                return row
        require(deposit.get("status") == "OPEN", "This deposit is not open.")
        balance = int(deposit["balance_paise"] or 0)
        require(balance > 0, "There is no unused deposit balance to refund.")
        receipt = payments_sql.deposit_receipt(conn, deposit_id)
        changed = payments_sql.refund_unused(conn, deposit_id, balance)
        require(changed == 1, "Deposit balance changed. Refresh and try again.", 409, "conflict")
        require(deposit.get("mode"), "Deposit has no payment mode.")
        payments_sql.insert_keyed_refund(
            conn, new_id("PAY"), None, deposit["patient_id"], deposit.get("admission_id"),
            deposit.get("mode"), balance, deposit_id, clean_text(reason, 240),
            user["id"], user.get("workstation"), now_iso(), receipt["id"] if receipt else None, stored_key or None,
        )
        audit(conn, user, "deposit_refund", "billing", "deposit", deposit_id, reason=reason, new={"amount_paise": balance, "patient_id": deposit["patient_id"]})
        publish("invoice.updated", {"deposit_id": deposit_id, "patient_id": deposit["patient_id"]})
        row = payments_sql.q_billing_14535(conn, deposit_id)
        row["idempotent_replay"] = False
        if own:
            commit(conn)
        return row
    except Exception:
        if own:
            rollback(conn)
        raise


def refund(
    conn,
    user,
    invoice_id: str,
    amount_paise: int,
    mode: str,
    reason: str,
    payment_id: str | None = None,
    idempotency_key: str | None = None,
    require_key: bool = False,
) -> dict:
    from .db import begin, commit, rollback

    permit_any(user, ["payment.refund", "billing.refund"], conn, "refund")
    amount = int(amount_paise)
    require(amount > 0, "Amount must be greater than zero.")
    require(clean_text(reason, 240), "A refund needs a reason.")
    require(payment_id, "Refund must name the payment being reversed.")
    mode = configured_mode(conn, mode)
    reason = clean_text(reason, 240)
    key = clean_text(idempotency_key, 120) if idempotency_key else ""
    if require_key:
        require(key, "An idempotency key is required for this refund.")
    stored_key = _scoped_key("refund", key)
    digest = _payment_hash({
        "amount_paise": amount,
        "invoice_id": invoice_id,
        "mode": mode,
        "payment_id": payment_id,
        "reason": reason,
    })
    own = not conn.in_transaction
    if own:
        begin(conn)
    try:
        locked = billing_sql.lock_invoice(conn, invoice_id)
        require(locked, "Invoice not found.", 404, "not_found")
        if stored_key:
            existing = payments_sql.get_idempotency(conn, stored_key)
            if existing:
                if existing["request_hash"] != digest:
                    raise ApiError("This idempotency key was already used for a different refund.", 409, "idempotency_conflict")
                updated = _replay(conn, invoice_id, existing["entity_id"], own, commit)
                updated["refund_id"] = existing["entity_id"]
                updated["reverses"] = payment_id
                return updated
        original = payments_sql.latest_payment(conn, invoice_id, payment_id)
        require(original and original.get("kind") != "REFUND", "Refund must reference the payment being reversed.", 404, "not_found")
        remaining = int(original["amount_paise"]) - payments_sql.refunded_against(conn, original["id"])
        require(amount <= remaining, "Refund exceeds the refundable balance of that payment.", 409, "conflict")
        pid = new_id("PAY")
        if stored_key:
            try:
                outcome = payments_sql.claim_scope(conn, stored_key, "refund", digest, pid, now_iso())
            except payments_sql.IdempotencyConflict as exc:
                raise ApiError("This idempotency key was already used for a different refund.", 409, "idempotency_conflict") from exc
            if outcome["status"] == "replay":
                updated = _replay(conn, invoice_id, outcome["entity_id"], own, commit)
                updated["reverses"] = payment_id
                return updated
            pid = outcome["entity_id"]
        payments_sql.insert_keyed_refund(
            conn, pid, invoice_id, locked["patient_id"], locked.get("admission_id"), mode, amount,
            original["id"], reason, user["id"], user.get("workstation"), now_iso(), original["id"], stored_key or None,
        )
        updated = recalc(conn, invoice_id)
        audit(conn, user, "refund", "billing", "payment", pid, reason=reason, new={"amount_paise": amount, "invoice": locked["number"], "reverses": original["id"]})
        publish("invoice.updated", {"id": invoice_id, "refund_id": pid, "patient_id": locked["patient_id"]})
        updated["refund_id"] = pid
        updated["reverses"] = original["id"]
        updated["idempotent_replay"] = False
        if own:
            commit(conn)
        return updated
    except Exception:
        if own:
            rollback(conn)
        raise


def void_invoice(conn, user, invoice_id: str, reason: str) -> dict:
    permit_any(user, ["billing.void", "billing.refund"], conn, "void")
    invoice = get_invoice(conn, invoice_id)
    require(invoice, "Invoice not found.", 404, "not_found")
    require(invoice["status"] != "VOID", "Already void.")
    require(clean_text(reason, 240), "Voiding a bill needs a reason.")
    require(int(invoice["paid_paise"] or 0) == 0, "Refund payments before voiding a bill that has money against it.")
    before = snapshot(conn, invoice_id)
    changed = billing_sql.q_billing_16229(conn, now_iso(), clean_text(reason, 240), now_iso(), invoice_id)
    require(_rowcount(changed) == 1, "Already void.", 409, "conflict")
    billing_sql.q_billing_16477(conn, invoice_id, invoice["revision"] + 1, reason, user["id"], user.get("workstation"), now_iso(), json.dumps(before, default=str), json.dumps(snapshot(conn, invoice_id), default=str))
    audit(conn, user, "invoice_void", "billing", "invoice", invoice_id, reason=reason)
    publish("invoice.updated", {"id": invoice_id, "status": "VOID", "patient_id": invoice["patient_id"]})
    return get_invoice(conn, invoice_id)


def adjust(conn, user, invoice_id: str, amount_paise: int, description: str, reason: str) -> dict:
    permit(user, "financial_adjustment.create", conn, "adjust")
    require(
        "financial_adjustment.approve" in (user.get("permissions") or []),
        "A financial adjustment must be approved before it changes the bill.",
        403,
        "forbidden",
    )
    invoice = billing_sql.lock_invoice(conn, invoice_id)
    require(invoice, "Invoice not found.", 404, "not_found")
    require(invoice["status"] == "FINALIZED", "Draft bills can be edited directly.")
    require(clean_text(reason, 240), "An adjustment needs a reason.")
    require(clean_text(description, 240), "Describe the adjustment.")
    amount = int(amount_paise)
    require(amount != 0, "Adjustment amount cannot be zero.")
    require(int(invoice["net_paise"] or 0) + amount >= 0, "Adjustment cannot make the bill negative.")
    before = snapshot(conn, invoice_id)
    aid = new_id("ADJ")
    at = now_iso()
    billing_sql.insert_adjustment(conn, aid, invoice_id, amount, clean_text(description, 240), clean_text(reason, 240), "APPROVED", user["id"], at, user["id"], at)
    add_item(
        conn,
        user,
        invoice_id,
        {
            "description": description,
            "category": "ADJUSTMENT",
            "rate_paise": amount,
            "qty": 1,
            "source_module": "adjustment",
            "unit": "adjustment",
        },
        allow_finalized=True,
    )
    billing_sql.q_billing_18004(conn, now_iso(), invoice_id)
    updated = recalc(conn, invoice_id)
    billing_sql.q_billing_18153(conn, invoice_id, updated["revision"], reason, user["id"], user.get("workstation"), now_iso(), json.dumps(before, default=str), json.dumps(snapshot(conn, invoice_id), default=str))
    audit(conn, user, "invoice_adjust", "billing", "invoice", invoice_id, reason=reason, old=before, new={"amount_paise": amount, "description": description, "adjustment_id": aid})
    publish("invoice.updated", {"id": invoice_id, "patient_id": invoice["patient_id"]})
    updated["adjustment_id"] = aid
    return updated


def outstanding_report(conn) -> dict:
    items = billing_sql.q_system_40532(conn)
    for item in items:
        item["patient_name"] = name_of(conn, "patients", item["patient_id"])
    return {"items": items, "total": len(items)}


def invoice_document(conn, invoice_id: str) -> dict:
    invoice = get_invoice(conn, invoice_id)
    require(invoice, "Invoice not found.", 404, "not_found")
    patient = patients_sql.q_billing_18932(conn, invoice["patient_id"])
    encounter = encounters_sql.q_billing_19021(conn, invoice["encounter_id"]) if invoice.get("encounter_id") else None
    admission = ipd_sql.q_billing_19155(conn, invoice["admission_id"]) if invoice.get("admission_id") else None
    h = hospital(conn)
    doctor = ""
    department = ""
    if encounter:
        doctor = doctor_label(conn, encounter.get("doctor_id"))
        department = name_of(conn, "master_items", encounter.get("department_id"))
        if not doctor:
            latest = encounters_sql.q_clinical_18647(conn, encounter["id"])
            if latest:
                doctor = doctor_label(conn, latest[0].get("doctor_id"))
    if admission and not doctor:
        doctor = doctor_label(conn, admission.get("doctor_id"))
    ward = room = bed = ""
    if admission:
        ward = name_of(conn, "wards", admission.get("ward_id"))
        room = name_of(conn, "rooms", admission.get("room_id"))
        bed_row = wards_sql.q_billing_19785(conn, admission.get("bed_id")) if admission.get("bed_id") else None
        bed = bed_row["name"] if bed_row else ""
    paid_on = ""
    if invoice["payment_status"] == "PAID":
        pays = [p for p in invoice["payments"] if p["kind"] in ("PAYMENT", "DEPOSIT_APPLY")]
        if pays:
            paid_on = pays[-1]["received_at"][:10]
    fields = [
        {"label": "Bill number", "value": invoice["number"]},
        {"label": "Patient ID", "value": patient["id"]},
        {"label": "Patient name", "value": patient["name"]},
        {"label": "Guardian", "value": patient.get("guardian_name") or "—"},
        {"label": "Age", "value": display_age(patient)},
        {"label": "Gender", "value": patient.get("gender") or "—"},
        {"label": "Phone", "value": patient.get("primary_phone") or "-"},
    ]
    if encounter:
        fields.append({"label": "OPD / encounter", "value": encounter["id"]})
    if admission:
        fields.append({"label": "Admission", "value": admission["id"]})
    fields.extend(
        [
            {"label": "Doctor", "value": doctor or "—"},
            {"label": "Department", "value": department or "—"},
            {"label": "Date", "value": (invoice.get("finalized_at") or invoice["created_at"])[:10]},
            {"label": "Time", "value": (invoice.get("finalized_at") or invoice["created_at"])[11:16]},
            {"label": "Bill type", "value": invoice["bill_type"]},
            {"label": "Payment status", "value": invoice["payment_status"]},
        ]
    )
    if admission:
        fields.append({"label": "Admitted", "value": (admission.get("admitted_at") or "")[:10]})
        if admission.get("discharged_at"):
            fields.append({"label": "Discharged", "value": admission["discharged_at"][:10]})
        fields.append({"label": "Ward / room / bed", "value": " / ".join(x for x in [ward, room, bed] if x) or "—"})
        fields.append({"label": "Patient type", "value": admission.get("admission_type") or "IPD"})
    subtotals = {}
    for item in invoice["items"]:
        subtotals[item["category"]] = subtotals.get(item["category"], 0) + int(item["amount_paise"])
    invoice["paid_on"] = paid_on
    return {
        "hospital": h,
        "patient": patient,
        "invoice": invoice,
        "items": invoice["items"],
        "payments": invoice["payments"],
        "fields": fields,
        "subtotals": subtotals,
        "generated_at": invoice.get("updated_at") or invoice.get("finalized_at") or invoice.get("created_at"),
        "logo_bytes": load_logo(h.get("logo_path")),
        "amount_in_words": amount_in_words(invoice["net_paise"]),
        "formatted": {
            "gross": format_inr_plain(invoice["gross_paise"]),
            "net": format_inr_plain(invoice["net_paise"]),
            "paid": format_inr_plain(invoice["paid_paise"]),
            "due": format_inr_plain(invoice["due_paise"]),
        },
    }


def file_stamp(name: str, when: str, number: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9]+", "", name or "") or "Patient"
    day = str(when or "")[:10] or "undated"
    ident = re.sub(r"[^A-Za-z0-9.-]+", "", number or "") or "document"
    return f"{stem}_{day}_{ident}.pdf"


def invoice_filename(conn, invoice_id: str) -> str:
    invoice = get_invoice(conn, invoice_id)
    patient = patients_sql.q_billing_18932(conn, invoice["patient_id"]) or {}
    when = invoice.get("finalized_at") or invoice.get("created_at") or ""
    return file_stamp(patient.get("name") or "", when, invoice.get("number") or invoice_id)


def invoice_pdf(conn, invoice_id: str, slip: bool = False) -> bytes:
    doc = invoice_document(conn, invoice_id)
    doc["cashier"] = doctor_label(conn, (doc.get("invoice") or {}).get("created_by"))
    return render_invoice_pdf(doc, slip=slip)


def prescription_document(conn, prescription_id: str) -> dict:
    rx = encounters_sql.q_billing_22969(conn, prescription_id)
    require(rx, "Prescription not found.", 404, "not_found")
    patient = patients_sql.q_billing_23116(conn, rx["patient_id"]) or {}
    items = encounters_sql.q_billing_23196(conn, prescription_id)
    encounter = encounters_sql.q_billing_19021(conn, rx.get("encounter_id")) if rx.get("encounter_id") else None
    department = name_of(conn, "master_items", encounter.get("department_id")) if encounter else ""
    profile = hospital(conn)
    when = rx.get("finalized_at") or rx.get("created_at") or ""
    return {
        "hospital": profile,
        "patient": patient,
        "prescription": rx,
        "items": items,
        "doctor": doctor_label(conn, rx.get("doctor_id")),
        "department": department,
        "age": display_age(patient) if patient else "",
        "generated_at": when,
        "logo_bytes": load_logo(profile.get("logo_path")),
        "filename": file_stamp(patient.get("name") or "", when, rx.get("id") or prescription_id),
        "patient_id": rx["patient_id"],
    }


def prescription_pdf(conn, prescription_id: str) -> bytes:
    return render_prescription_pdf(prescription_document(conn, prescription_id))


def add_prescription_charges(conn, user, invoice_id: str, prescription_id: str, item_ids: list) -> dict:
    """Issue selected prescription lines. Stock is deducted with the bill line."""
    require(prescription_id, "Choose a prescription.")
    require(item_ids, "Select at least one medicine.")
    return issue_medicines(conn, user, invoice_id, {
        "items": [{"prescription_item_id": item_id} for item_id in item_ids],
        "confirm": False,
    })
