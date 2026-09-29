"""Laboratory workflow. Billing stays in the invoice engine. Role names are not consulted."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation

from aipf.repo import documents as documents_sql
from aipf.repo import encounters as encounters_sql
from aipf.repo import lab as lab_sql

from . import access
from .billing import add_item, open_draft
from .core import audit, doctor_label, hospital, name_of, next_number, permit, permit_any
from .events import publish
from .pdf import render_lab_report
from .util import ApiError, clean_text, new_id, now_iso, require, safe_filename

RESULT_TYPES = ("numeric", "text", "qualitative", "positive_negative", "normal_abnormal")
PRIORITIES = ("ROUTINE", "URGENT", "STAT")
COLLECTABLE = ("SAMPLE_PENDING", "RECOLLECTION_REQUIRED")
CANCELLABLE = ("SAMPLE_PENDING", "SAMPLE_COLLECTED", "PROCESSING", "RESULT_PENDING", "RECOLLECTION_REQUIRED", "ORDERED")
NOT_FOUND = "That record was not found."


def apply_test_config(conn, item_id: str, payload: dict) -> None:
    current = lab_sql.test_row(conn, item_id) or {}
    result_type = _pick(payload, "result_type", current.get("result_type"))
    result_type = clean_text(result_type, 40).lower() or None
    if result_type:
        require(result_type in RESULT_TYPES, "Result type is not one of the configured types.")
    low = _range(payload, "reference_low", current.get("reference_low"))
    high = _range(payload, "reference_high", current.get("reference_high"))
    crit_low = _range(payload, "critical_low", current.get("critical_low"))
    crit_high = _range(payload, "critical_high", current.get("critical_high"))
    lab_sql.update_test_config(
        conn,
        item_id,
        _text_pick(payload, "container_type", current.get("container_type"), 60),
        _text_pick(payload, "unit", current.get("unit"), 40),
        _text_pick(payload, "reference_range", current.get("reference_range"), 160),
        low,
        high,
        crit_low,
        crit_high,
        _text_pick(payload, "methodology", current.get("methodology"), 160),
        result_type,
        now_iso(),
    )


def place_order(conn, user, payload: dict) -> dict:
    permit_any(user, ["lab.order", "lab.order.create"], conn, "lab_order")
    patient_id = payload.get("patient_id") or ""
    require(patient_id, "Patient is required.")
    require(not payload.get("phone") or patient_id, "Patient is required.")
    _own_patient(conn, user, patient_id)
    encounter_id = payload.get("encounter_id") or None
    admission_id = payload.get("admission_id") or None
    if encounter_id:
        owned = lab_sql.encounter_owner(conn, encounter_id)
        if not owned or owned["patient_id"] != patient_id:
            raise ApiError(NOT_FOUND, 404, "not_found")
    if admission_id:
        owned = lab_sql.admission_owner(conn, admission_id)
        if not owned or owned["patient_id"] != patient_id:
            raise ApiError(NOT_FOUND, 404, "not_found")
        if encounter_id and owned.get("encounter_id") and owned["encounter_id"] != encounter_id:
            raise ApiError(NOT_FOUND, 404, "not_found")
    priority = (clean_text(payload.get("priority") or "ROUTINE", 20) or "ROUTINE").upper()
    require(priority in PRIORITIES, "Priority must be routine, urgent, or stat.")
    tests = payload.get("tests") or []
    require(tests, "Select at least one test.")
    key = clean_text(payload.get("idempotency_key"), 80)
    digest = _hash({"patient_id": patient_id, "encounter_id": encounter_id, "admission_id": admission_id, "priority": priority, "tests": tests})
    if key:
        claim = lab_sql.claim_key(conn, _stored_key("order", key), "lab.order", digest, now_iso())
        if claim["status"] == "conflict":
            raise ApiError("This idempotency key was already used for a different order.", 409, "idempotency_conflict")
        if claim["status"] == "replay":
            found = present(conn, claim["entity_id"])
            found["idempotent_replay"] = True
            return found
        if claim["status"] == "in_progress":
            raise ApiError("That request is still being saved.", 409, "idempotency_conflict")
    oid = next_number(conn, "lab", "LAB", 6, True)
    lab_sql.insert_order(
        conn, oid, encounter_id, admission_id, patient_id, user["id"],
        clean_text(payload.get("notes"), 400), now_iso(), user["id"], priority,
    )
    bill_type = "IPD" if admission_id else "OPD"
    invoice = open_draft(conn, user, patient_id, encounter_id, admission_id, bill_type)
    for test in tests:
        master = None
        test_id = test.get("test_id") or None
        custom = clean_text(test.get("custom_name"), 160)
        if test_id:
            master = lab_sql.q_wards_22104(conn, test_id)
            if not master:
                raw = lab_sql.test_row(conn, test_id)
                if raw and not int(raw.get("active") or 0):
                    raise ApiError("This test is inactive.", 409, "inactive_test")
                raise ApiError(NOT_FOUND, 404, "not_found")
            price = int(master["price_paise"] or 0)
            pending = 0
            name = master["name"]
            sample = master.get("sample_type") or ""
        else:
            require(custom, "Each test needs a master test or a custom name.")
            price = 0
            pending = 1
            name = custom
            sample = clean_text(test.get("sample_type"), 60)
        iid = new_id("LI")
        lab_sql.insert_item(conn, iid, oid, master["id"] if master else None, custom or None, price, pending, sample)
        description = name if not pending else f"[PRICE PENDING] {name}"
        updated = add_item(
            conn, user, invoice["id"],
            {
                "description": description,
                "category": "LABORATORY",
                "rate_paise": price,
                "qty": 1,
                "unit": "test",
                "source_module": "lab",
                "source_id": iid,
                "master_item_id": master["id"] if master else None,
            },
        )
        lab_sql.q_wards_23472(conn, updated["added_item_id"], iid)
    queue = encounters_sql.q_wards_23589(conn, encounter_id) if encounter_id else None
    if queue and queue["status"] in ("WAITING", "CALLED", "IN_CONSULTATION"):
        from .clinical import set_queue_status
        set_queue_status(conn, user, queue["id"], "WAITING_FOR_TEST")
    audit(conn, user, "lab_order", "lab", "lab_order", oid, new={"tests": len(tests), "priority": priority, "patient_id": patient_id})
    publish("lab.updated", {"id": oid, "patient_id": patient_id, "kind": "ordered"})
    if key:
        lab_sql.finish_key(conn, _stored_key("order", key), oid)
    return present(conn, oid)


def collect_sample(conn, user, order_id: str, payload: dict, idempotency_key: str = "") -> dict:
    permit(user, "lab.sample.collect", conn, "lab_sample_collect")
    key = _require_key(idempotency_key or payload.get("idempotency_key"))
    item_ids = list(payload.get("item_ids") or [])
    require(item_ids, "Choose the tests to collect.")
    digest = _hash({"order_id": order_id, "item_ids": item_ids, "location": payload.get("location"), "notes": payload.get("notes")})
    claim = lab_sql.claim_key(conn, _stored_key("collect", key), "lab.sample.collect", digest, now_iso())
    if claim["status"] == "conflict":
        raise ApiError("This idempotency key was already used for a different collection.", 409, "idempotency_conflict")
    if claim["status"] == "replay":
        sample = lab_sql.sample_row(conn, claim["entity_id"])
        require(sample, NOT_FOUND, 404, "not_found")
        sample["idempotent_replay"] = True
        return sample
    if claim["status"] == "in_progress":
        raise ApiError("That request is still being saved.", 409, "idempotency_conflict")
    order = _locked_order(conn, user, order_id)
    require(order["status"] != "CANCELLED", "This order is cancelled.", 409, "invalid_transition")
    require(len(item_ids) == len(set(item_ids)), "Each ordered test can be collected once in this sample.")
    locked = {}
    for item_id in sorted(item_ids, key=str):
        item = lab_sql.lock_item(conn, item_id)
        if not item or item["order_id"] != order_id:
            raise ApiError(NOT_FOUND, 404, "not_found")
        locked[item_id] = item
    items = []
    replaces = None
    for item_id in item_ids:
        item = locked[item_id]
        require(item["status"] in COLLECTABLE, "This test is not waiting for collection.", 409, "invalid_transition")
        if lab_sql.active_sample_for_item(conn, item_id):
            raise ApiError("This test already has an active sample.", 409, "duplicate_collection")
        items.append(item)
        if item["status"] == "RECOLLECTION_REQUIRED":
            previous = _latest_sample(conn, item_id)
            if previous:
                replaces = previous["id"]
    specimen = items[0].get("sample_type") or ""
    require(all((item.get("sample_type") or "") == specimen for item in items), "Collect one specimen type at a time.")
    container = _container(conn, items)
    sample_id = new_id("SMP")
    at = now_iso()
    inserted = False
    accession = ""
    for _attempt in range(3):
        accession = next_number(conn, "accession", "ACC", 6, True)
        inserted = lab_sql.insert_sample(
            conn, sample_id, accession, order["patient_id"], order.get("encounter_id"), order_id,
            specimen, container, at, user["id"],
            clean_text(payload.get("location"), 80) or None,
            clean_text(payload.get("notes"), 400) or None,
            replaces, at,
        )
        if inserted:
            break
    require(inserted, "Accession allocation conflicted. Collect again.", 409, "conflict")
    for item in items:
        if not lab_sql.link_sample_item(conn, sample_id, item["id"]):
            raise ApiError("This test already has an active sample.", 409, "duplicate_collection")
        lab_sql.set_item_status(conn, item["id"], "SAMPLE_COLLECTED")
    _rollup(conn, order_id)
    audit(conn, user, "lab_sample_collect", "lab", "lab_sample", sample_id, new={"accession_no": accession, "order_id": order_id, "items": item_ids})
    publish("lab.updated", {"id": order_id, "patient_id": order["patient_id"], "kind": "collected", "sample_id": sample_id})
    lab_sql.finish_key(conn, _stored_key("collect", key), sample_id)
    sample = lab_sql.sample_row(conn, sample_id)
    sample["idempotent_replay"] = False
    return sample


def reject_sample(conn, user, sample_id: str, payload: dict, idempotency_key: str = "") -> dict:
    permit(user, "lab.sample.reject", conn, "lab_sample_reject")
    key = _require_key(idempotency_key or payload.get("idempotency_key"))
    code = clean_text(payload.get("reason_code"), 40).upper()
    notes = clean_text(payload.get("notes"), 400)
    preview = lab_sql.sample_row(conn, sample_id)
    if not preview:
        raise ApiError(NOT_FOUND, 404, "not_found")
    reason = lab_sql.rejection_reason(conn, code)
    require(reason, "Choose a configured rejection reason.")
    if code == "OTHER":
        require(notes, "Other needs a note.")
    digest = _hash({"sample_id": sample_id, "reason_code": code, "notes": notes})
    claim = _claim_or_replay(conn, "reject", key, "lab.sample.reject", digest, loader=lambda entity: _sample_payload(conn, entity))
    if claim is not None:
        return claim
    order = _locked_order(conn, user, preview["order_id"])
    sample = lab_sql.lock_sample(conn, sample_id)
    require(sample and sample["status"] in ("COLLECTED", "RECEIVED", "PROCESSING"), "This sample cannot be rejected.", 409, "invalid_transition")
    text = reason["name"] if not notes else f"{reason['name']}: {notes}"
    at = now_iso()
    require(lab_sql.reject_sample(conn, sample_id, user["id"], text, at) == 1, "This sample cannot be rejected.", 409, "invalid_transition")
    for link in lab_sql.sample_items(conn, sample_id):
        item = lab_sql.lock_item(conn, link["order_item_id"])
        require(item and item["status"] not in ("VERIFIED", "RESULT_ENTERED", "CANCELLED"), "A resulted test cannot be rejected.", 409, "invalid_transition")
        lab_sql.set_item_status(conn, item["id"], "RECOLLECTION_REQUIRED")
    _rollup(conn, order["id"])
    audit(conn, user, "lab_sample_reject", "lab", "lab_sample", sample_id, reason=text, new={"kept": True})
    publish("lab.updated", {"id": order["id"], "patient_id": order["patient_id"], "kind": "rejected", "sample_id": sample_id})
    lab_sql.finish_key(conn, _stored_key("reject", key), sample_id)
    saved = lab_sql.sample_row(conn, sample_id)
    saved["idempotent_replay"] = False
    return saved


def receive_sample(conn, user, sample_id: str, payload: dict, idempotency_key: str = "") -> dict:
    permit(user, "lab.sample.process", conn, "lab_sample_receive")
    return _move_sample(conn, user, sample_id, payload, idempotency_key, "receive", "lab.sample.receive", lab_sql.receive_sample, "received")


def process_sample(conn, user, sample_id: str, payload: dict, idempotency_key: str = "") -> dict:
    permit(user, "lab.sample.process", conn, "lab_sample_process")
    saved = _move_sample(conn, user, sample_id, payload, idempotency_key, "process", "lab.sample.process", lab_sql.process_sample, "processing")
    if saved.get("idempotent_replay"):
        return saved
    for link in lab_sql.sample_items(conn, sample_id):
        item = lab_sql.lock_item(conn, link["order_item_id"])
        if item and item["status"] == "SAMPLE_COLLECTED":
            lab_sql.set_item_status(conn, item["id"], "PROCESSING")
    preview = lab_sql.sample_row(conn, sample_id)
    _rollup(conn, preview["order_id"])
    return saved


def enter_result(conn, user, item_id: str, payload: dict, idempotency_key: str = "") -> dict:
    permit_any(user, ["lab.result", "lab.result.enter"], conn, "lab_result_enter")
    key = _require_key(idempotency_key or payload.get("idempotency_key"))
    digest = _hash({"item_id": item_id, "value": payload.get("value") or payload.get("result_text"), "remarks": payload.get("remarks")})
    claim = _claim_or_replay(conn, "enter", key, "lab.result.enter", digest, loader=lambda entity: _result_payload(conn, entity))
    if claim is not None:
        return claim
    item = lab_sql.item_row(conn, item_id)
    if not item:
        raise ApiError(NOT_FOUND, 404, "not_found")
    order = _locked_order(conn, user, item["order_id"])
    item = lab_sql.lock_item(conn, item_id)
    require(item["status"] in ("PROCESSING", "RESULT_ENTERED", "RESULT_PENDING"), "Collect and process the sample before entering a result.", 409, "invalid_transition")
    current = lab_sql.current_result(conn, item_id)
    if current and current["status"] in ("VERIFIED", "FINALIZED"):
        raise ApiError("A verified result cannot be edited. Correct it with a reason.", 409, "invalid_transition")
    master = lab_sql.test_row(conn, item["test_id"]) if item.get("test_id") else None
    result_type = ((master or {}).get("result_type") or "text").lower()
    if not master:
        requested = clean_text(payload.get("result_type"), 40).lower()
        result_type = requested if requested in RESULT_TYPES else "text"
    value = _normalize_value(result_type, payload.get("value") if payload.get("value") is not None else payload.get("result_text"))
    low = (master or {}).get("reference_low")
    high = (master or {}).get("reference_high")
    crit_low = (master or {}).get("critical_low")
    crit_high = (master or {}).get("critical_high")
    flag, critical = _classify(result_type, value, low, high, crit_low, crit_high)
    revision = 1
    supersedes = None
    if current and current["status"] == "ENTERED":
        require(lab_sql.supersede_result(conn, current["id"]) == 1, "The open result changed. Enter it again.", 409, "conflict")
        revision = int(current["revision_no"] or 1) + 1
        supersedes = current["id"]
    result_id = new_id("LR")
    at = now_iso()
    saved = lab_sql.insert_workflow_result(conn, {
        "id": result_id,
        "item_id": item_id,
        "value": value,
        "units": (master or {}).get("unit"),
        "reference_range": _range_text(master),
        "entered_by": user["id"],
        "entered_at": at,
        "result_type": result_type,
        "reference_low": low,
        "reference_high": high,
        "critical_low": crit_low,
        "critical_high": crit_high,
        "methodology": (master or {}).get("methodology"),
        "abnormal_flag": flag,
        "critical_flag": critical,
        "remarks": clean_text(payload.get("remarks"), 4000) or None,
        "revision_no": revision,
        "supersedes_id": supersedes,
        "correction_reason": clean_text(payload.get("reason"), 400) or None,
    })
    require(saved, "A result is already entered for this test.", 409, "conflict")
    lab_sql.set_item_status(conn, item_id, "RESULT_ENTERED")
    _rollup(conn, order["id"])
    audit(conn, user, "lab_result_enter", "lab", "lab_result", result_id, new={"item_id": item_id, "revision_no": revision, "abnormal_flag": flag})
    if critical:
        audit(conn, user, "lab_result_critical", "lab", "lab_result", result_id, new={"flag": flag, "item_id": item_id})
    publish("lab.updated", {"id": order["id"], "patient_id": order["patient_id"], "kind": "result_entered", "item_id": item_id})
    lab_sql.finish_key(conn, _stored_key("enter", key), result_id)
    return _result_payload(conn, result_id)


def verify_result(conn, user, result_id: str, payload: dict, idempotency_key: str = "") -> dict:
    permit(user, "lab.result.verify", conn, "lab_result_verify")
    key = _require_key(idempotency_key or payload.get("idempotency_key"))
    digest = _hash({"result_id": result_id})
    claim = _claim_or_replay(conn, "verify", key, "lab.result.verify", digest, loader=lambda entity: _result_payload(conn, entity))
    if claim is not None:
        return claim
    preview = lab_sql.result_row(conn, result_id)
    if not preview:
        raise ApiError(NOT_FOUND, 404, "not_found")
    item = lab_sql.item_row(conn, preview["lab_order_item_id"])
    order = _locked_order(conn, user, item["order_id"])
    require(lab_sql.verify_result(conn, result_id, user["id"], now_iso()) == 1, "Only an entered result can be verified.", 409, "invalid_transition")
    lab_sql.set_item_status(conn, item["id"], "VERIFIED")
    _rollup(conn, order["id"])
    audit(conn, user, "lab_result_verify", "lab", "lab_result", result_id, new={"item_id": item["id"]})
    publish("lab.updated", {"id": order["id"], "patient_id": order["patient_id"], "kind": "verified", "result_id": result_id})
    lab_sql.finish_key(conn, _stored_key("verify", key), result_id)
    return _result_payload(conn, result_id)


def correct_result(conn, user, result_id: str, payload: dict, idempotency_key: str = "") -> dict:
    permit(user, "lab.result.correct", conn, "lab_result_correct")
    key = _require_key(idempotency_key or payload.get("idempotency_key"))
    reason = clean_text(payload.get("reason"), 400)
    require(reason, "A correction needs a reason.")
    digest = _hash({"result_id": result_id, "value": payload.get("value"), "reason": reason})
    claim = _claim_or_replay(conn, "correct", key, "lab.result.correct", digest, loader=lambda entity: _result_payload(conn, entity))
    if claim is not None:
        return claim
    preview = lab_sql.result_row(conn, result_id)
    if not preview:
        raise ApiError(NOT_FOUND, 404, "not_found")
    item = lab_sql.item_row(conn, preview["lab_order_item_id"])
    order = _locked_order(conn, user, item["order_id"])
    current = lab_sql.lock_result(conn, result_id)
    require(current and current["status"] == "VERIFIED", "Only the verified result can be corrected.", 409, "invalid_transition")
    require(lab_sql.supersede_result(conn, result_id) == 1, "That result was already corrected.", 409, "conflict")
    master = lab_sql.test_row(conn, item["test_id"]) if item.get("test_id") else None
    result_type = current.get("result_type") or "text"
    value = _normalize_value(result_type, payload.get("value"))
    low = (master or {}).get("reference_low")
    high = (master or {}).get("reference_high")
    crit_low = (master or {}).get("critical_low")
    crit_high = (master or {}).get("critical_high")
    flag, critical = _classify(result_type, value, low, high, crit_low, crit_high)
    new_id_ = new_id("LR")
    at = now_iso()
    saved = lab_sql.insert_workflow_result(conn, {
        "id": new_id_,
        "item_id": item["id"],
        "value": value,
        "units": (master or {}).get("unit") or current.get("units"),
        "reference_range": _range_text(master) or current.get("reference_range"),
        "entered_by": user["id"],
        "entered_at": at,
        "result_type": result_type,
        "reference_low": low,
        "reference_high": high,
        "critical_low": crit_low,
        "critical_high": crit_high,
        "methodology": (master or {}).get("methodology"),
        "abnormal_flag": flag,
        "critical_flag": critical,
        "remarks": clean_text(payload.get("remarks"), 4000) or current.get("remarks"),
        "revision_no": int(current["revision_no"] or 1) + 1,
        "supersedes_id": result_id,
        "correction_reason": reason,
    })
    require(saved, "A result is already open for this test.", 409, "conflict")
    lab_sql.set_item_status(conn, item["id"], "RESULT_ENTERED")
    _rollup(conn, order["id"])
    audit(
        conn, user, "lab_result_correct", "lab", "lab_result", new_id_,
        reason=reason,
        old={"id": result_id, "value": current.get("value_text"), "revision_no": current.get("revision_no")},
        new={"value": value, "revision_no": int(current["revision_no"] or 1) + 1},
    )
    if critical:
        audit(conn, user, "lab_result_critical", "lab", "lab_result", new_id_, new={"flag": flag})
    publish("lab.updated", {"id": order["id"], "patient_id": order["patient_id"], "kind": "corrected", "result_id": new_id_})
    lab_sql.finish_key(conn, _stored_key("correct", key), new_id_)
    return _result_payload(conn, new_id_)


def cancel_order(conn, user, order_id: str, payload: dict, idempotency_key: str = "") -> dict:
    permit(user, "lab.order.cancel", conn, "lab_order_cancel")
    key = _require_key(idempotency_key or payload.get("idempotency_key"))
    reason = clean_text(payload.get("reason"), 400)
    require(reason, "Say why this order is being cancelled.")
    digest = _hash({"order_id": order_id, "reason": reason})
    claim = _claim_or_replay(conn, "cancel", key, "lab.order.cancel", digest, loader=lambda entity: present(conn, entity))
    if claim is not None:
        return claim
    order = _locked_order(conn, user, order_id)
    items = lab_sql.items_for_order(conn, order_id)
    require(items, NOT_FOUND, 404, "not_found")
    require(all(item["status"] in CANCELLABLE for item in items), "A resulted order cannot be cancelled. Billing can adjust the invoice.", 409, "invalid_transition")
    line_ids = [item.get("invoice_item_id") for item in items if item.get("invoice_item_id")]
    at = now_iso()
    for item in items:
        lab_sql.set_item_status(conn, item["id"], "CANCELLED")
    lab_sql.cancel_order(conn, order_id, user["id"], reason, at)
    audit(conn, user, "lab_order_cancel", "lab", "lab_order", order_id, reason=reason, new={"invoice_lines_kept": line_ids})
    publish("lab.updated", {"id": order_id, "patient_id": order["patient_id"], "kind": "cancelled"})
    lab_sql.finish_key(conn, _stored_key("cancel", key), order_id)
    saved = present(conn, order_id)
    saved["invoice_lines_kept"] = line_ids
    saved["idempotent_replay"] = False
    return saved


def upload_report(conn, user, order_id: str, payload: dict) -> dict:
    """Store the laboratory's real PDF; AIPF never generates the report."""
    permit(user, "document.upload")
    order = _locked_order(conn, user, order_id)
    existing = documents_sql.list_documents(conn, order["patient_id"], "lab_order", order_id, "")
    if existing:
        return {"order": present(conn, order_id), "document": existing[0], "idempotent_replay": True}
    mime = (payload.get("mime_type") or "").lower()
    require(mime == "application/pdf", "Upload the laboratory report as a PDF.")
    filename = clean_text(payload.get("filename"), 180)
    require(filename.lower().endswith(".pdf"), "The laboratory report filename must end in .pdf.")
    from .wards import store_document
    document = store_document(conn, user, {
        **payload,
        "patient_id": order["patient_id"],
        "entity_type": "lab_order",
        "entity_id": order_id,
        "document_type": "LAB REPORT",
        "title": clean_text(payload.get("title"), 160) or filename,
        "filename": filename,
        "mime_type": "application/pdf",
    })
    active_items = [item for item in lab_sql.items_for_order(conn, order_id) if item["status"] != "CANCELLED"]
    require(active_items, "This laboratory order has no active tests.", 409, "invalid_transition")
    require(all(item["status"] in ("SAMPLE_COLLECTED", "PROCESSING", "RESULT_PENDING", "RESULT_ENTERED", "VERIFIED") for item in active_items), "Collect the sample before uploading the report.", 409, "invalid_transition")
    for item in active_items:
        lab_sql.attach_item_document(conn, item["id"], document["id"])
        lab_sql.set_item_status(conn, item["id"], "REPORT_UPLOADED")
    lab_sql.set_order_status(conn, order_id, "REPORT_UPLOADED")
    audit(conn, user, "lab_report_upload", "lab", "lab_order", order_id, new={"document_id": document["id"], "filename": filename})
    publish("lab.updated", {"id": order_id, "patient_id": order["patient_id"], "kind": "report_uploaded", "document_id": document["id"]})
    return {"order": present(conn, order_id), "document": document, "idempotent_replay": False}


def generate_report(conn, user, order_id: str, payload: dict, idempotency_key: str = "") -> dict:
    permit(user, "lab.report.generate", conn, "lab_report_generate")
    key = _require_key(idempotency_key or payload.get("idempotency_key"))
    digest = _hash({"order_id": order_id})
    claim = _claim_or_replay(conn, "report", key, "lab.report.generate", digest, loader=lambda entity: _report_meta(conn, entity))
    if claim is not None:
        return claim
    order = _locked_order(conn, user, order_id)
    payload_pdf, fingerprint, verified = _report_source(conn, order)
    existing = lab_sql.report_by_fingerprint(conn, order_id, fingerprint)
    if existing:
        lab_sql.finish_key(conn, _stored_key("report", key), existing["id"])
        meta = _report_meta(conn, existing["id"])
        meta["idempotent_replay"] = True
        return meta
    generated_at = payload_pdf.get("reported_at") or now_iso()
    payload_pdf["reported_at"] = generated_at
    data = render_lab_report(payload_pdf)
    doc_id = new_id("DOC")
    storage_key = f"{order['patient_id']}/{doc_id}.pdf"
    from .storage import get_storage
    storage = get_storage()
    saved = storage.save(storage_key, data, "application/pdf")
    try:
        documents_sql.q_wards_28079(
            conn, doc_id, order["patient_id"], "lab_order", order_id, "Laboratory report",
            f"Laboratory report {order_id}", safe_filename(f"{order_id}.pdf"), storage_key,
            "application/pdf", len(data), saved["checksum"], user["id"], generated_at,
            "Generated from stored verified results",
        )
        report_id = new_id("RPT")
        inserted = lab_sql.insert_report(
            conn, report_id, order_id, order["patient_id"], order.get("encounter_id"),
            doc_id, fingerprint, user["id"], generated_at,
        )
        if not inserted:
            existing = lab_sql.report_by_fingerprint(conn, order_id, fingerprint)
            lab_sql.delete_document_row(conn, doc_id)
            storage.delete(storage_key)
            require(existing, "The report was already generated.", 409, "conflict")
            lab_sql.finish_key(conn, _stored_key("report", key), existing["id"])
            meta = _report_meta(conn, existing["id"])
            meta["idempotent_replay"] = True
            return meta
    except Exception:
        if storage.exists(storage_key):
            storage.delete(storage_key)
        raise
    audit(conn, user, "lab_report_generate", "lab", "lab_report", report_id, new={"document_id": doc_id, "results": len(verified), "checksum": saved["checksum"]})
    publish("lab.updated", {"id": order_id, "patient_id": order["patient_id"], "kind": "reported", "document_id": doc_id})
    lab_sql.finish_key(conn, _stored_key("report", key), report_id)
    meta = _report_meta(conn, report_id)
    meta["idempotent_replay"] = False
    return meta


def report_pdf(conn, user, order_id: str) -> bytes:
    permit(user, "lab.report.view", conn, "lab_report_view")
    order = visible_order(conn, user, order_id)
    report = lab_sql.latest_report(conn, order["id"])
    if not report:
        raise ApiError(NOT_FOUND, 404, "not_found")
    from .storage import get_storage

    doc = documents_sql.q_wards_29339(conn, report["document_id"])
    if not doc or doc.get("patient_id") != order["patient_id"] or doc.get("entity_id") != order["id"]:
        raise ApiError(NOT_FOUND, 404, "not_found")
    storage = get_storage()
    key = doc["stored_name"]
    if not key or not storage.exists(key):
        raise ApiError(NOT_FOUND, 404, "not_found")
    meta = storage.metadata(key)
    require(meta["size"] == doc["size_bytes"], "Stored file does not match the document record.", 409, "storage_mismatch")
    return storage.read(key)


def processing_queue(conn, user) -> dict:
    permit(user, "lab.view", conn, "lab_queue")
    items = []
    for sample in lab_sql.processing_queue(conn):
        if access.can_view_patient(conn, user, sample.get("patient_id")):
            sample.pop("order_patient_id", None)
            items.append(sample)
    return {"items": items, "total": len(items)}


def reject_direct_status(conn, user, order_id: str, _status: str) -> dict:
    permit(user, "lab.result", conn, "lab_status")
    visible_order(conn, user, order_id)
    raise ApiError(
        "Laboratory status cannot be set directly. Use collection, processing, result entry, verification, or cancellation.",
        409,
        "invalid_transition",
    )


def present(conn, order_id: str) -> dict:
    order = lab_sql.q_wards_24156(conn, order_id)
    require(order, NOT_FOUND, 404, "not_found")
    order["patient_name"] = name_of(conn, "patients", order["patient_id"])
    order["doctor_name"] = doctor_label(conn, order.get("doctor_id"))
    return enrich(conn, order)


def enrich(conn, order: dict) -> dict:
    order["items"] = lab_sql.items_for_order(conn, order["id"])
    samples = lab_sql.samples_for_order(conn, order["id"])
    links = lab_sql.sample_links(conn, order["id"])
    linked = {}
    for link in links:
        linked.setdefault(link["order_item_id"], []).append(link["sample_id"])
    grouped = {}
    for result in lab_sql.results_for_order(conn, order["id"]):
        grouped.setdefault(result["lab_order_item_id"], []).append(result)
    for item in order["items"]:
        item["samples"] = [sample for sample in samples if sample["id"] in linked.get(item["id"], [])]
        item["results"] = grouped.get(item["id"], [])
        item["current_result"] = next((row for row in reversed(item["results"]) if row["status"] in ("ENTERED", "VERIFIED", "FINALIZED")), None)
    order["samples"] = samples
    reports = lab_sql.reports_for_order(conn, order["id"])
    order["reports"] = [
        {"id": row["id"], "document_id": row["document_id"], "generated_at": row["generated_at"], "fingerprint": row["fingerprint"]}
        for row in reports
    ]
    return order


def visible_order(conn, user, order_id: str, lock: bool = False) -> dict:
    order = lab_sql.lock_order(conn, order_id) if lock else lab_sql.q_wards_24156(conn, order_id)
    if not order or not access.can_view_patient(conn, user, order.get("patient_id")):
        access.hide_record(conn, user, "lab_order", order_id)
    return order


def _locked_order(conn, user, order_id: str) -> dict:
    return visible_order(conn, user, order_id, lock=True)


def _own_patient(conn, user, patient_id: str) -> None:
    if not patient_id or not lab_sql.patient_row(conn, patient_id) or not access.can_view_patient(conn, user, patient_id):
        access.hide_record(conn, user, "patient", patient_id)


def _rollup(conn, order_id: str) -> None:
    items = lab_sql.items_for_order(conn, order_id)
    active = [item for item in items if item["status"] != "CANCELLED"]
    if not active:
        lab_sql.set_order_status(conn, order_id, "CANCELLED")
        return
    statuses = {item["status"] for item in active}
    for name in ("SAMPLE_PENDING", "RECOLLECTION_REQUIRED", "SAMPLE_COLLECTED", "PROCESSING", "RESULT_PENDING", "RESULT_ENTERED", "VERIFIED"):
        if name in statuses:
            lab_sql.set_order_status(conn, order_id, name)
            return
    lab_sql.set_order_status(conn, order_id, "SAMPLE_PENDING")


def _move_sample(conn, user, sample_id: str, payload: dict, idempotency_key: str, scope: str, claim_scope: str, updater, kind: str) -> dict:
    key = _require_key(idempotency_key or payload.get("idempotency_key"))
    digest = _hash({"sample_id": sample_id, "kind": kind})
    claim = _claim_or_replay(conn, scope, key, claim_scope, digest, loader=lambda entity: _sample_payload(conn, entity))
    if claim is not None:
        return claim
    preview = lab_sql.sample_row(conn, sample_id)
    if not preview:
        raise ApiError(NOT_FOUND, 404, "not_found")
    order = _locked_order(conn, user, preview["order_id"])
    lab_sql.lock_sample(conn, sample_id)
    at = now_iso()
    require(updater(conn, sample_id, user["id"], at) == 1, "This sample is not waiting for that step.", 409, "invalid_transition")
    audit(conn, user, f"lab_sample_{kind}", "lab", "lab_sample", sample_id, new={"order_id": order["id"]})
    publish("lab.updated", {"id": order["id"], "patient_id": order["patient_id"], "kind": kind, "sample_id": sample_id})
    lab_sql.finish_key(conn, _stored_key(scope, key), sample_id)
    saved = _sample_payload(conn, sample_id)
    saved["idempotent_replay"] = False
    return saved


def _report_source(conn, order: dict) -> tuple[dict, str, list]:
    items = lab_sql.items_for_order(conn, order["id"])
    active = [item for item in items if item["status"] != "CANCELLED"]
    require(active, "There is no result to report.", 409, "invalid_transition")
    require(all(item["status"] == "VERIFIED" for item in active), "Verify every active test before reporting.", 409, "invalid_transition")
    samples = lab_sql.samples_for_order(conn, order["id"])
    links = lab_sql.sample_links(conn, order["id"])
    by_item = {}
    for link in links:
        by_item.setdefault(link["order_item_id"], []).append(link["sample_id"])
    sample_by_id = {sample["id"]: sample for sample in samples}
    patient = lab_sql.patient_row(conn, order["patient_id"]) or {}
    profile = hospital(conn)
    address = ", ".join(part for part in (profile.get("address_line1"), profile.get("city")) if part)
    results = []
    verified = []
    for item in active:
        current = lab_sql.current_result(conn, item["id"])
        require(current and current["status"] == "VERIFIED", "Verify every active test before reporting.", 409, "invalid_transition")
        verified.append(current)
        line = lab_sql.invoice_line(conn, item["id"])
        accession = ""
        for sample_id in by_item.get(item["id"], []):
            sample = sample_by_id.get(sample_id)
            if sample and sample["status"] != "REJECTED":
                accession = sample["accession_no"]
        name = (line or {}).get("description") or item.get("custom_name") or "Test"
        if name.startswith("[PRICE PENDING] "):
            name = name[len("[PRICE PENDING] "):]
        results.append({
            "test_name": name,
            "value": current.get("value_text"),
            "unit": current.get("units"),
            "reference_range": current.get("reference_range"),
            "abnormal_flag": current.get("abnormal_flag"),
            "critical_flag": int(current.get("critical_flag") or 0),
            "methodology": current.get("methodology"),
            "remarks": current.get("remarks"),
            "accession_no": accession,
            "rate_paise": None if not line or item.get("price_pending") else int(line["rate_paise"] or 0),
            "price_pending": bool(item.get("price_pending")),
        })
    fingerprint = hashlib.sha256(
        "|".join(
            f"{row['id']}:{row['revision_no']}:{row.get('value_text')}:{row.get('reference_range')}:{row.get('abnormal_flag')}"
            for row in sorted(verified, key=lambda row: row["id"])
        ).encode()
    ).hexdigest()
    payload = {
        "hospital_name": profile.get("name") or "Hospital",
        "hospital_address": address,
        "patient_id": order["patient_id"],
        "patient_name": patient.get("name") or "",
        "encounter_id": order.get("encounter_id"),
        "admission_id": order.get("admission_id"),
        "order_id": order["id"],
        "priority": order.get("priority"),
        "reported_at": now_iso(),
        "results": results,
    }
    return payload, fingerprint, verified


def _report_meta(conn, report_id: str) -> dict:
    report = lab_sql.report_row(conn, report_id)
    require(report, NOT_FOUND, 404, "not_found")
    document = documents_sql.q_wards_29086(conn, report["document_id"]) or {}
    return {
        "id": report["id"],
        "order_id": report["order_id"],
        "document_id": report["document_id"],
        "checksum": document.get("checksum"),
        "generated_at": report["generated_at"],
        "idempotent_replay": False,
    }


def _result_payload(conn, result_id: str) -> dict:
    row = lab_sql.result_row(conn, result_id)
    require(row, NOT_FOUND, 404, "not_found")
    row["idempotent_replay"] = False
    return row


def _sample_payload(conn, sample_id: str) -> dict:
    row = lab_sql.sample_row(conn, sample_id)
    require(row, NOT_FOUND, 404, "not_found")
    row["idempotent_replay"] = True
    return row


def _claim_or_replay(conn, scope: str, key: str, claim_scope: str, digest: str, loader=None):
    claim = lab_sql.claim_key(conn, _stored_key(scope, key), claim_scope, digest, now_iso())
    if claim["status"] == "conflict":
        raise ApiError("This idempotency key was already used for a different request.", 409, "idempotency_conflict")
    if claim["status"] == "in_progress":
        raise ApiError("That request is still being saved.", 409, "idempotency_conflict")
    if claim["status"] == "replay":
        if loader is None:
            return {"id": claim["entity_id"], "idempotent_replay": True}
        found = loader(claim["entity_id"])
        found["idempotent_replay"] = True
        return found
    return None


def _latest_sample(conn, item_id: str):
    links = [row for row in lab_sql.sample_links_for_item(conn, item_id)]
    if not links:
        return None
    return lab_sql.sample_row(conn, links[-1]["sample_id"])


def _container(conn, items: list[dict]) -> str | None:
    found = []
    for item in items:
        if not item.get("test_id"):
            continue
        master = lab_sql.test_row(conn, item["test_id"])
        if master and master.get("container_type"):
            found.append(master["container_type"])
    if not found:
        return None
    require(len(set(found)) == 1, "These tests do not share a container.")
    return found[0]


def _range_text(master: dict | None) -> str | None:
    if not master:
        return None
    if master.get("reference_range"):
        return master["reference_range"]
    low, high = master.get("reference_low"), master.get("reference_high")
    if low or high:
        return f"{low or ''} - {high or ''}".strip()
    return None


def _classify(result_type: str, value: str, low, high, crit_low, crit_high) -> tuple[str | None, int]:
    if result_type != "numeric":
        return None, 0
    try:
        number = Decimal(value)
    except (InvalidOperation, TypeError) as exc:
        raise ApiError("A numeric result must be a number.") from exc
    def dec(raw):
        if raw in (None, ""):
            return None
        return Decimal(str(raw))
    try:
        clo, chi, lo, hi = dec(crit_low), dec(crit_high), dec(low), dec(high)
    except (InvalidOperation, TypeError) as exc:
        raise ApiError("The configured range is not numeric.") from exc
    if clo is not None and number < clo:
        return "critical_low", 1
    if chi is not None and number > chi:
        return "critical_high", 1
    if lo is not None and number < lo:
        return "low", 0
    if hi is not None and number > hi:
        return "high", 0
    if lo is not None or hi is not None:
        return "normal", 0
    return None, 0


def _normalize_value(result_type: str, raw) -> str:
    text = clean_text(raw, 4000)
    require(text, "Enter the result.")
    if result_type == "numeric":
        try:
            Decimal(text)
        except InvalidOperation as exc:
            raise ApiError("A numeric result must be a number.") from exc
        return text
    if result_type == "positive_negative":
        upper = text.upper()
        require(upper in ("POSITIVE", "NEGATIVE"), "Result must be positive or negative.")
        return upper
    if result_type == "normal_abnormal":
        upper = text.upper()
        require(upper in ("NORMAL", "ABNORMAL"), "Result must be normal or abnormal.")
        return upper
    return text


def _pick(payload, key, fallback):
    if key in payload:
        return payload.get(key)
    return fallback


def _text_pick(payload, key, fallback, limit: int):
    if key in payload:
        return clean_text(payload.get(key), limit) or None
    return fallback


def _range(payload, key, fallback):
    if key not in payload:
        return fallback
    text = clean_text(payload.get(key), 40)
    if not text:
        return None
    try:
        Decimal(text)
    except InvalidOperation as exc:
        raise ApiError("A reference range must be numeric.") from exc
    return text


def _hash(payload) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _stored_key(scope: str, key: str) -> str:
    return f"lab:{scope}:{key}"


def _require_key(raw) -> str:
    key = clean_text(raw, 80)
    require(key, "Idempotency key is required.", 400, "idempotency_required")
    return key
