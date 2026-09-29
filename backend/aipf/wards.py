"""Admissions, beds, OT, laboratory, and patient documents."""

from __future__ import annotations

from aipf.repo import billing as billing_sql
from aipf.repo import documents as documents_sql
from aipf.repo import encounters as encounters_sql
from aipf.repo import ipd as ipd_sql
from aipf.repo import lab as lab_sql
from aipf.repo import ot as ot_sql
from aipf.repo import patients as patients_sql
from aipf.repo import wards as wards_sql

import base64
import hashlib
import json
from pathlib import Path

from . import access
from .billing import add_item, open_draft
from .core import audit, doctor_label, hospital, name_of, next_number, permit, permit_any
from .db import DOCUMENTS, one, rows
from .events import publish
from .util import (
    ApiError,
    clean_text,
    money_mul,
    new_id,
    now_iso,
    require,
    safe_filename,
    sha256_bytes,
    today_str,
)

BED_STATUSES = ["AVAILABLE", "OCCUPIED", "RESERVED", "MAINTENANCE", "BLOCKED", "CLEANING"]
OPEN_ADMISSION = ("REQUESTED", "ADMITTED", "DISCHARGE_PENDING")
NOT_FOUND = "That record was not found."
OT_OUTCOMES = ["SUCCESSFUL", "UNSUCCESSFUL", "ABORTED"]
ALLOWED_MIME = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "text/plain": ".txt",
}


def bed_board(conn, user=None) -> dict:
    wards = wards_sql.q_wards_830(conn)
    for ward in wards:
        ward["rooms"] = wards_sql.q_wards_952(conn, ward["id"])
        beds = patients_sql.q_wards_1067(conn, ward["id"])
        for bed in beds:
            if user and bed.get("patient_id") and not access.can_view_patient(conn, user, bed.get("patient_id")):
                bed["patient_name"] = None
                bed["patient_id"] = None
                bed["admission_id"] = None
                bed["current_admission_id"] = None
                bed.pop("primary_phone", None)
        ward["beds"] = beds
    return {"wards": wards}


def set_bed_status(conn, user, bed_id: str, status: str, notes: str = "") -> dict:
    permit(user, "bed.manage")
    require(status in BED_STATUSES, "Unknown bed status.")
    bed = wards_sql.q_wards_1734(conn, bed_id)
    require(bed, "Bed not found.", 404, "not_found")
    if bed.get("current_admission_id") and status != bed["status"]:
        raise ApiError("Discharge or transfer the patient before changing this bed.", 409, "conflict")
    if status == "OCCUPIED" and not bed.get("current_admission_id"):
        raise ApiError("Occupy a bed by admitting a patient, not by changing the status alone.", 409, "conflict")
    wards_sql.q_wards_2172(conn, status, clean_text(notes, 200), bed_id)
    audit(conn, user, "bed_status", "ipd", "bed", bed_id, old={"status": bed["status"]}, new={"status": status})
    publish("beds.updated", {"id": bed_id, "status": status})
    return wards_sql.q_wards_2461(conn, bed_id)


def admit(conn, user, payload: dict, sample: int = 0) -> dict:
    permit_any(user, ["admission.manage", "ipd.admission.create"], conn, "ipd_admit")
    patient_id = payload.get("patient_id")
    if not patient_id or not patients_sql.q_wards_2672(conn, patient_id):
        raise ApiError(NOT_FOUND, 404, "not_found")
    encounter_id = payload.get("encounter_id") or None
    if encounter_id:
        owned = ipd_sql.encounter_owner(conn, encounter_id)
        if not owned or owned["patient_id"] != patient_id:
            raise ApiError(NOT_FOUND, 404, "not_found")
    doctor_id = payload.get("doctor_id") or user.get("id")
    if doctor_id and not ipd_sql.user_row(conn, doctor_id):
        raise ApiError(NOT_FOUND, 404, "not_found")
    key = clean_text(payload.get("idempotency_key"), 80)
    digest = _hash({
        "patient_id": patient_id,
        "encounter_id": encounter_id,
        "bed_id": payload.get("bed_id"),
        "doctor_id": doctor_id,
        "reason": payload.get("reason"),
    })
    replay = _replay(conn, user, "admit", key, digest, lambda entity: _admission_result(conn, entity))
    if replay is not None:
        return replay
    require(not ipd_sql.q_wards_2791(conn, patient_id), "This patient already has an open admission.", 409, "conflict")
    bed = ipd_sql.lock_bed(conn, payload["bed_id"]) if payload.get("bed_id") else None
    if payload.get("bed_id"):
        if not bed or not int(bed.get("active") or 0):
            raise ApiError(NOT_FOUND, 404, "not_found")
        room_open = wards_sql.q_wards_3362(conn, bed["room_id"])
        ward_open = wards_sql.q_wards_13816(conn, bed["ward_id"])
        if not room_open or not int(room_open.get("active") or 0) or not ward_open or not int(ward_open.get("active") or 0):
            raise ApiError(NOT_FOUND, 404, "not_found")
        require(bed["status"] not in ("BLOCKED", "MAINTENANCE", "CLEANING"), "That bed is not available.", 409, "conflict")
        require(bed["status"] == "AVAILABLE" and not bed.get("current_admission_id"), "That bed is not available.", 409, "conflict")
    status = "ADMITTED" if bed else "REQUESTED"
    aid = next_number(conn, "admission", "ADM", 6, True)
    room = wards_sql.q_wards_3362(conn, bed["room_id"]) if bed else None
    rate = int(room["daily_rate_paise"] or 0) if room else 0
    inserted = ipd_sql.insert_admission(conn, (
        aid, patient_id, encounter_id, clean_text(payload.get("admission_type") or "INPATIENT", 30), status,
        bed["ward_id"] if bed else payload.get("ward_id"), bed["room_id"] if bed else None, bed["id"] if bed else None,
        doctor_id, payload.get("department_id") or None, clean_text(payload.get("diagnosis"), 400),
        clean_text(payload.get("reason"), 400), now_iso() if status == "ADMITTED" else None,
        clean_text(payload.get("expected_discharge"), 10) or None, rate, user["id"], now_iso(), now_iso(), sample,
    ))
    if not inserted:
        raise ApiError("This patient already has an open admission.", 409, "conflict")
    if bed:
        require(ipd_sql.occupy_bed(conn, bed["id"], aid) == 1, "That bed is not available.", 409, "conflict")
        ipd_sql.q_wards_4737(conn, aid, patient_id, bed["id"], "Admission", user["id"], now_iso())
    invoice = open_draft(conn, user, patient_id, encounter_id, aid, "IPD", sample)
    if rate and status == "ADMITTED":
        post_charge(conn, user, aid, "Bed / room charge — admission day", "IPD", rate, 1, "day", "admission", aid)
    if key:
        ipd_sql.finish_key(conn, _stored_key("admit", key), aid)
    audit(conn, user, "admission", "ipd", "admission", aid, new={"patient_id": patient_id, "bed_id": bed["id"] if bed else None, "status": status})
    publish("admission.updated", {"id": aid, "patient_id": patient_id, "status": status})
    publish("ipd.admission.created", {"id": aid, "patient_id": patient_id, "status": status})
    if bed:
        publish("ipd.bed.assigned", {"id": bed["id"], "patient_id": patient_id, "admission_id": aid})
    return _admission_result(conn, aid)


def get_admission(conn, admission_id: str) -> dict:
    adm = ipd_sql.q_wards_5554(conn, admission_id)
    require(adm, NOT_FOUND, 404, "not_found")
    adm["patient_name"] = name_of(conn, "patients", adm["patient_id"])
    adm["doctor_name"] = doctor_label(conn, adm.get("doctor_id"))
    adm["ward_name"] = name_of(conn, "wards", adm.get("ward_id"))
    adm["room_name"] = name_of(conn, "rooms", adm.get("room_id"))
    bed = wards_sql.q_wards_5958(conn, adm.get("bed_id")) if adm.get("bed_id") else None
    adm["bed_name"] = bed["name"] if bed else ""
    adm["charges"] = ipd_sql.q_wards_6127(conn, admission_id)
    adm["movements"] = ipd_sql.q_wards_6266(conn, admission_id)
    adm["invoices"] = billing_sql.q_wards_6380(conn, admission_id)
    return adm


def list_admissions(conn, status: str = "ADMITTED") -> dict:
    if status == "ALL":
        items = ipd_sql.q_wards_6628(conn)
    elif status == "CURRENT":
        items = ipd_sql.list_current(conn)
    else:
        items = ipd_sql.q_wards_6728(conn, status)
    for item in items:
        item["patient_name"] = name_of(conn, "patients", item["patient_id"])
        item["ward_name"] = name_of(conn, "wards", item.get("ward_id"))
        bed = wards_sql.q_wards_7005(conn, item.get("bed_id")) if item.get("bed_id") else None
        item["bed_name"] = bed["name"] if bed else ""
        item["doctor_name"] = doctor_label(conn, item.get("doctor_id"))
    return {"items": items, "total": len(items)}


def transfer(conn, user, admission_id: str, bed_id: str, reason: str, idempotency_key: str = "") -> dict:
    permit_any(user, ["admission.manage", "ipd.bed.move", "ipd.bed.assign"], conn, "ipd_move")
    require(reason, "Record why the patient is moving.")
    key = clean_text(idempotency_key, 80)
    digest = _hash({"admission_id": admission_id, "bed_id": bed_id, "reason": reason})
    replay = _replay(conn, user, "move", key, digest, lambda entity: get_admission(conn, entity))
    if replay is not None:
        return replay
    adm = ipd_sql.lock_admission(conn, admission_id)
    if not adm or not access.can_view_patient(conn, user, adm.get("patient_id")):
        access.hide_record(conn, user, "admission", admission_id)
    require(adm["status"] in ("ADMITTED", "DISCHARGE_PENDING"), "Only an admitted patient can be transferred.", 409, "invalid_transition")
    for locked_id in sorted({item for item in (adm.get("bed_id"), bed_id) if item}):
        ipd_sql.lock_bed(conn, locked_id)
    adm = ipd_sql.lock_admission(conn, admission_id)
    bed = ipd_sql.lock_bed(conn, bed_id)
    if not bed or not int(bed.get("active") or 0):
        raise ApiError(NOT_FOUND, 404, "not_found")
    dest_room = wards_sql.q_wards_7949(conn, bed["room_id"])
    dest_ward = wards_sql.q_wards_13816(conn, bed["ward_id"])
    if not dest_room or not int(dest_room.get("active") or 0) or not dest_ward or not int(dest_ward.get("active") or 0):
        raise ApiError(NOT_FOUND, 404, "not_found")
    require(bed["status"] not in ("BLOCKED", "MAINTENANCE", "CLEANING"), "Destination bed is not available.", 409, "conflict")
    old = adm.get("bed_id")
    require(old != bed_id, "The patient is already in that bed.", 409, "conflict")
    room = wards_sql.q_wards_7949(conn, bed["room_id"])
    rate = int(room["daily_rate_paise"] or 0) if room else int(adm["daily_rate_paise"] or 0)
    if old:
        require(ipd_sql.release_bed(conn, old, admission_id) == 1, "The current bed changed. Try the move again.", 409, "conflict")
    require(ipd_sql.occupy_bed(conn, bed_id, admission_id) == 1, "Destination bed is not available.", 409, "conflict")
    require(ipd_sql.move_admission(conn, admission_id, bed["ward_id"], bed["room_id"], bed["id"], rate, now_iso(), old) == 1, "The admission changed. Try the move again.", 409, "conflict")
    ipd_sql.q_wards_8406(conn, admission_id, adm["patient_id"], old, bed["id"], clean_text(reason, 240), user["id"], now_iso())
    if key:
        ipd_sql.finish_key(conn, _stored_key("move", key), admission_id)
    audit(conn, user, "bed_transfer", "ipd", "admission", admission_id, old={"bed_id": old}, new={"bed_id": bed["id"], "rate_paise": rate}, reason=reason)
    publish("beds.updated", {"admission_id": admission_id, "patient_id": adm["patient_id"]})
    publish("ipd.bed.moved", {"id": bed["id"], "patient_id": adm["patient_id"], "admission_id": admission_id, "from_bed_id": old})
    return get_admission(conn, admission_id)


def post_charge(conn, user, admission_id: str, description: str, category: str, rate_paise: int, qty: float = 1, unit: str = "", source_module: str = "ipd", source_id: str = "", master_item_id: str = "") -> dict:
    adm = ipd_sql.q_wards_9103(conn, admission_id)
    if not adm or not access.can_view_patient(conn, user, adm.get("patient_id")):
        access.hide_record(conn, user, "admission", admission_id)
    cid = new_id("AC")
    invoice = open_draft(conn, user, adm["patient_id"], adm.get("encounter_id"), admission_id, "IPD", adm.get("is_sample") or 0)
    updated = add_item(
        conn,
        user,
        invoice["id"],
        {
            "description": description,
            "category": category,
            "rate_paise": rate_paise,
            "qty": qty,
            "unit": unit,
            "source_module": source_module,
            "source_id": cid,
            "master_item_id": master_item_id or None,
        },
    )
    stored = billing_sql.q_billing_7233(conn, updated["added_item_id"])
    amount = int(stored["amount_paise"])
    rate = int(stored["rate_paise"])
    ipd_sql.q_wards_9762(conn, cid, admission_id, today_str(), stored.get("description") or description, category, rate, qty, amount, source_module, source_id or cid, updated["added_item_id"], user["id"], now_iso())
    audit(conn, user, "admission_charge", "ipd", "admission", admission_id, new={"description": description, "amount_paise": amount, "rate_paise": rate})
    publish("admission.updated", {"id": admission_id, "patient_id": adm["patient_id"]})
    return get_admission(conn, admission_id)


def post_bed_day(conn, user, admission_id: str, idempotency_key: str = "", charge_date: str = "") -> dict:
    permit_any(user, ["admission.manage", "ipd.admission.manage"], conn, "ipd_bed_charge")
    day = clean_text(charge_date, 10) or today_str()
    key = clean_text(idempotency_key, 80)
    digest = _hash({"admission_id": admission_id, "charge_date": day})
    replay = _replay(conn, user, "bed_day", key, digest, lambda entity: get_admission(conn, entity))
    if replay is not None:
        return replay
    adm = ipd_sql.lock_admission(conn, admission_id)
    if not adm or not access.can_view_patient(conn, user, adm.get("patient_id")):
        access.hide_record(conn, user, "admission", admission_id)
    require(adm["status"] in ("ADMITTED", "DISCHARGE_PENDING"), "Patient is not currently admitted.", 409, "invalid_transition")
    if ipd_sql.q_wards_10667(conn, admission_id, day):
        if key:
            ipd_sql.finish_key(conn, _stored_key("bed_day", key), admission_id)
        return get_admission(conn, admission_id)
    rate = int(adm["daily_rate_paise"] or 0)
    require(rate > 0, "This bed has no daily rate. Set it on the room, or post a manual charge.")
    label = " / ".join(x for x in [name_of(conn, "wards", adm.get("ward_id")), name_of(conn, "rooms", adm.get("room_id")), (wards_sql.q_wards_5958(conn, adm.get("bed_id")) or {}).get("name")] if x)
    cid = new_id("AC")
    inserted = ipd_sql.insert_bed_day(conn, (
        cid, admission_id, day, f"Bed charge {day} — {label}", "IPD", rate, 1, rate,
        "bed_day", admission_id, None, user["id"], now_iso(),
    ))
    if not inserted:
        return get_admission(conn, admission_id)
    invoice = open_draft(conn, user, adm["patient_id"], adm.get("encounter_id"), admission_id, "IPD", adm.get("is_sample") or 0)
    updated = add_item(conn, user, invoice["id"], {
        "description": f"Bed charge {day} — {label}",
        "category": "IPD",
        "rate_paise": rate,
        "qty": 1,
        "unit": "day",
        "source_module": "bed_day",
        "source_id": cid,
    })
    ipd_sql.set_charge_invoice(conn, cid, updated["added_item_id"])
    if key:
        ipd_sql.finish_key(conn, _stored_key("bed_day", key), admission_id)
    audit(conn, user, "bed_charge", "ipd", "admission", admission_id, new={"charge_date": day, "rate_paise": rate, "kept": True})
    publish("admission.updated", {"id": admission_id, "patient_id": adm["patient_id"]})
    return get_admission(conn, admission_id)


def discharge(conn, user, admission_id: str, payload: dict, idempotency_key: str = "") -> dict:
    permit_any(user, ["admission.manage", "ipd.discharge.finalize"], conn, "ipd_discharge")
    summary = clean_text(payload.get("discharge_summary"), 4000)
    require(summary, "Write a discharge summary before discharge.")
    key = clean_text(idempotency_key or payload.get("idempotency_key"), 80)
    digest = _hash({"admission_id": admission_id, "summary": summary, "condition": payload.get("discharge_condition")})
    replay = _replay(conn, user, "discharge", key, digest, lambda entity: get_admission(conn, entity))
    if replay is not None:
        return replay
    adm = ipd_sql.lock_admission(conn, admission_id)
    if not adm or not access.can_view_patient(conn, user, adm.get("patient_id")):
        access.hide_record(conn, user, "admission", admission_id)
    doctor_id = payload.get("discharge_doctor_id") or user.get("id")
    at = now_iso()
    require(
        ipd_sql.mark_discharged(conn, admission_id, at, summary, clean_text(payload.get("discharge_condition"), 240), doctor_id) == 1,
        "Only an admitted patient can be discharged.",
        409,
        "invalid_transition",
    )
    if adm.get("bed_id"):
        require(ipd_sql.release_bed(conn, adm["bed_id"], admission_id) == 1, "The bed was already released.", 409, "conflict")
        ipd_sql.q_wards_12128(conn, admission_id, adm["patient_id"], adm["bed_id"], "Discharge", user["id"], at)
        publish("ipd.bed.released", {"id": adm["bed_id"], "patient_id": adm["patient_id"], "admission_id": admission_id})
    if key:
        ipd_sql.finish_key(conn, _stored_key("discharge", key), admission_id)
    audit(conn, user, "discharge", "ipd", "admission", admission_id, new={"condition": payload.get("discharge_condition"), "bed_released": bool(adm.get("bed_id"))})
    publish("admission.updated", {"id": admission_id, "patient_id": adm["patient_id"], "status": "DISCHARGED"})
    publish("ipd.discharge.completed", {"id": admission_id, "patient_id": adm["patient_id"]})
    publish("beds.updated", {"id": adm.get("bed_id"), "patient_id": adm["patient_id"]})
    return get_admission(conn, admission_id)


def save_ward(conn, user, payload: dict, ward_id: str | None = None) -> dict:
    permit(user, "master.manage")
    name = clean_text(payload.get("name"), 80)
    require(name, "Ward name is required.")
    code = clean_text(payload.get("code"), 20).upper() or None
    kind = clean_text(payload.get("ward_type"), 40)
    active = 1 if payload.get("active", True) else 0
    if ward_id:
        if not wards_sql.q_wards_13816(conn, ward_id):
            raise ApiError(NOT_FOUND, 404, "not_found")
        saved = wards_sql.update_ward(conn, (name, code, kind, 1 if payload.get("ac") else 0, clean_text(payload.get("description"), 240), active, int(payload.get("sort_order") or 0), ward_id))
        if not saved:
            raise ApiError("That ward code is already in use.", 409, "conflict")
    else:
        ward_id = new_id("W")
        saved = wards_sql.insert_ward(conn, (ward_id, name, code, kind, 1 if payload.get("ac") else 0, clean_text(payload.get("description"), 240), 1, int(payload.get("sort_order") or 0)))
        if not saved:
            raise ApiError("That ward code is already in use.", 409, "conflict")
    audit(conn, user, "ward_save", "admin", "ward", ward_id, new={"name": name, "active": active, "ward_type": kind})
    return wards_sql.q_wards_13816(conn, ward_id)


def facility_catalog(conn, include_inactive: bool = False) -> dict:
    return wards_sql.facilities(conn, include_inactive)


def update_room(conn, user, room_id: str, payload: dict) -> dict:
    permit(user, "master.manage", conn, "room")
    row = wards_sql.q_wards_14464(conn, room_id)
    require(row, "Room not found.", 404, "not_found")
    active = 1 if payload.get("active", True) else 0
    if not active:
        occupied = wards_sql.occupied_beds_in_room(conn, room_id)
        require(not occupied or int(occupied.get("n") or 0) == 0, "Discharge or transfer patients before deactivating this room.")
    wards_sql.update_room(
        conn, room_id,
        clean_text(payload.get("name") or row["name"], 80),
        clean_text(payload.get("room_type") or row.get("room_type") or "GENERAL", 30),
        int(payload.get("daily_rate_paise") if payload.get("daily_rate_paise") is not None else (row.get("daily_rate_paise") or 0)),
        active,
    )
    audit(conn, user, "room_update", "admin", "room", room_id, new={"active": bool(active)})
    return wards_sql.q_wards_14464(conn, room_id)


def update_bed_record(conn, user, bed_id: str, payload: dict) -> dict:
    permit(user, "master.manage", conn, "bed")
    row = wards_sql.q_wards_15057(conn, bed_id)
    require(row, "Bed not found.", 404, "not_found")
    active = 1 if payload.get("active", True) else 0
    if not active and row.get("current_admission_id"):
        require(False, "Discharge or transfer the patient before deactivating this bed.")
    status = row["status"]
    if not active and status == "AVAILABLE":
        status = "BLOCKED"
    if active and not row.get("current_admission_id") and status in ("BLOCKED", "MAINTENANCE"):
        status = "AVAILABLE"
    wards_sql.update_bed_record(conn, bed_id, clean_text(payload.get("name") or row["name"], 40), active, status)
    audit(conn, user, "bed_update", "admin", "bed", bed_id, new={"active": bool(active), "status": status})
    return wards_sql.q_wards_15057(conn, bed_id)


def delete_bed(conn, user, bed_id: str) -> dict:
    permit(user, "master.manage")
    row = wards_sql.q_wards_15057(conn, bed_id)
    require(row, "Bed not found.", 404, "not_found")
    require(not row.get("current_admission_id"), "Discharge or transfer the patient before deleting this bed.", 409, "conflict")
    require(wards_sql.bed_history_count(conn, bed_id) == 0, "This bed is on an admission record. Deactivate it instead of erasing it.", 409, "conflict")
    audit(conn, user, "bed_delete", "admin", "bed", bed_id, old={"name": row.get("name")})
    wards_sql.delete_bed(conn, bed_id)
    return {"ok": True, "id": bed_id}


def delete_room(conn, user, room_id: str) -> dict:
    permit(user, "master.manage")
    row = wards_sql.q_wards_14464(conn, room_id)
    require(row, "Room not found.", 404, "not_found")
    require(wards_sql.room_history_count(conn, room_id) == 0, "This room is on an admission record. Deactivate it instead of erasing it.", 409, "conflict")
    for bed in wards_sql.beds_in_room(conn, room_id):
        require(not bed.get("current_admission_id"), "A bed in this room is occupied.", 409, "conflict")
        require(wards_sql.bed_history_count(conn, bed["id"]) == 0, "A bed in this room is on an admission record.", 409, "conflict")
    audit(conn, user, "room_delete", "admin", "room", room_id, old={"name": row.get("name")})
    for bed in wards_sql.beds_in_room(conn, room_id):
        wards_sql.delete_bed(conn, bed["id"])
    wards_sql.delete_room(conn, room_id)
    return {"ok": True, "id": room_id}


def delete_ward(conn, user, ward_id: str) -> dict:
    permit(user, "master.manage")
    row = wards_sql.q_wards_13816(conn, ward_id)
    require(row, "Ward not found.", 404, "not_found")
    require(wards_sql.ward_history_count(conn, ward_id) == 0, "This ward is on an admission record. Deactivate it instead of erasing it.", 409, "conflict")
    for room in wards_sql.rooms_in_ward(conn, ward_id):
        require(wards_sql.room_history_count(conn, room["id"]) == 0, "A room in this ward is on an admission record.", 409, "conflict")
        for bed in wards_sql.beds_in_room(conn, room["id"]):
            require(wards_sql.bed_history_count(conn, bed["id"]) == 0, "A bed in this ward is on an admission record.", 409, "conflict")
    audit(conn, user, "ward_delete", "admin", "ward", ward_id, old={"name": row.get("name")})
    for room in wards_sql.rooms_in_ward(conn, ward_id):
        for bed in wards_sql.beds_in_room(conn, room["id"]):
            wards_sql.delete_bed(conn, bed["id"])
        wards_sql.delete_room(conn, room["id"])
    wards_sql.delete_ward(conn, ward_id)
    return {"ok": True, "id": ward_id}


def save_room(conn, user, payload: dict) -> dict:
    permit(user, "master.manage")
    require(payload.get("ward_id") and payload.get("name"), "Ward and room name are required.")
    if not ipd_sql.ward_row(conn, payload["ward_id"]):
        raise ApiError(NOT_FOUND, 404, "not_found")
    rid = new_id("R")
    saved = wards_sql.insert_room(conn, (rid, payload["ward_id"], clean_text(payload["name"], 80), clean_text(payload.get("room_type"), 40), 1 if payload.get("ac") else 0, int(payload.get("daily_rate_paise") or 0)))
    if not saved:
        raise ApiError("That room already exists in this ward.", 409, "conflict")
    audit(conn, user, "room_save", "admin", "room", rid, new={"name": payload.get("name"), "rate_paise": int(payload.get("daily_rate_paise") or 0)})
    return wards_sql.q_wards_14464(conn, rid)


def save_bed(conn, user, payload: dict) -> dict:
    permit(user, "master.manage")
    room = wards_sql.q_wards_14612(conn, payload.get("room_id"))
    require(room and payload.get("name"), "Room and bed name are required.")
    bid = new_id("BD")
    saved = wards_sql.insert_bed(conn, (bid, room["id"], room["ward_id"], clean_text(payload["name"], 40)))
    if not saved:
        raise ApiError("That bed already exists in this room.", 409, "conflict")
    audit(conn, user, "bed_create", "admin", "bed", bid, new={"name": payload.get("name"), "room_id": room["id"]})
    return wards_sql.q_wards_15057(conn, bid)


def create_ot(conn, user, payload: dict) -> dict:
    permit_any(user, ["ot.manage", "ot.request"], conn, "ot_request")
    patient_id = payload.get("patient_id") or ""
    require(patient_id, "Patient is required.")
    require(payload.get("procedure_name"), "Patient and procedure are required.")
    if not patients_sql.q_wards_2672(conn, patient_id) or not access.can_view_patient(conn, user, patient_id):
        access.hide_record(conn, user, "patient", patient_id)
    encounter_id = payload.get("encounter_id") or None
    admission_id = payload.get("admission_id") or None
    if encounter_id:
        owned = ot_sql.encounter_owner(conn, encounter_id)
        if not owned or owned["patient_id"] != patient_id:
            raise ApiError(NOT_FOUND, 404, "not_found")
    if admission_id:
        owned = ot_sql.admission_owner(conn, admission_id)
        if not owned or owned["patient_id"] != patient_id:
            raise ApiError(NOT_FOUND, 404, "not_found")
    oid = next_number(conn, "ot", "OT", 6, True)
    ot_sql.q_wards_15355(conn, oid, patient_id, encounter_id, admission_id, clean_text(payload["procedure_name"], 200), payload.get("procedure_id"), payload.get("surgeon_id") or user.get("id"), clean_text(payload.get("assistants"), 240), clean_text(payload.get("anesthesia"), 120), clean_text(payload.get("scheduled_at"), 30) or None, user["id"], now_iso(), now_iso())
    audit(conn, user, "ot_request", "ot", "ot", oid, new={"procedure": payload["procedure_name"]})
    publish("ot.updated", {"id": oid, "status": "REQUESTED", "patient_id": patient_id, "permission": "ot.view"})
    return get_ot(conn, oid)


def get_ot(conn, ot_id: str) -> dict:
    case = ot_sql.q_wards_16351(conn, ot_id)
    require(case, NOT_FOUND, 404, "not_found")
    case["patient_name"] = name_of(conn, "patients", case["patient_id"])
    case["surgeon_name"] = doctor_label(conn, case.get("surgeon_id"))
    return case


def list_ot(conn, status: str = "") -> dict:
    if status:
        items = ot_sql.q_wards_16703(conn, status)
    else:
        items = ot_sql.q_wards_16841(conn)
    for item in items:
        item["patient_name"] = name_of(conn, "patients", item["patient_id"])
        item["surgeon_name"] = doctor_label(conn, item.get("surgeon_id"))
    return {"items": items, "total": len(items)}


_LEGACY_NEXT = {
    "REQUESTED": {"REQUESTED", "SCHEDULED", "IN_PROGRESS", "PERFORMED", "CANCELLED"},
    "APPROVED": {"APPROVED", "SCHEDULED", "IN_PROGRESS", "PERFORMED", "CANCELLED"},
    "SCHEDULED": {"SCHEDULED", "IN_PROGRESS", "PERFORMED", "CANCELLED"},
    "PRE_OP": {"PRE_OP", "IN_PROGRESS", "PERFORMED", "CANCELLED"},
    "IN_PROGRESS": {"IN_PROGRESS", "PERFORMED", "CANCELLED"},
    "PERFORMED": {"PERFORMED", "NOTES_PENDING"},
    "NOTES_PENDING": {"NOTES_PENDING"},
    "RECOVERY": {"RECOVERY", "PERFORMED"},
    "POSTPONED": {"POSTPONED", "SCHEDULED", "CANCELLED"},
    "COMPLETED": {"COMPLETED"},
    "CANCELLED": {"CANCELLED"},
}


def update_ot(conn, user, ot_id: str, payload: dict) -> dict:
    permit(user, "ot.manage")
    case = get_ot(conn, ot_id)
    if not access.can_view_patient(conn, user, case.get("patient_id")):
        access.hide_record(conn, user, "ot", ot_id)
    status = payload.get("status") or case["status"]
    if payload.get("status") == "COMPLETED" and case["status"] != "COMPLETED":
        raise ApiError("Completion is recorded by the operative record, not a status flag.", 409, "invalid_transition")
    known = set(_LEGACY_NEXT)
    require(status in known, "Unknown OT status.")
    require(status in _LEGACY_NEXT.get(case["status"], set()), "That status change is not allowed.", 409, "invalid_transition")
    ot_sql.q_wards_17483(conn, status, payload.get("scheduled_at") or case.get("scheduled_at"), payload.get("started_at") or case.get("started_at") or (now_iso() if status == "IN_PROGRESS" else None), payload.get("ended_at") or case.get("ended_at") or (now_iso() if status in ("PERFORMED", "NOTES_PENDING", "COMPLETED") else None), clean_text(payload.get("assistants") if "assistants" in payload else case.get("assistants"), 240), clean_text(payload.get("ot_staff") if "ot_staff" in payload else case.get("ot_staff"), 240), clean_text(payload.get("anesthesia") if "anesthesia" in payload else case.get("anesthesia"), 120), payload.get("surgeon_id") or case.get("surgeon_id"), now_iso(), ot_id)
    if status == "PERFORMED":
        ot_sql.q_wards_18509(conn, ot_id)
        surgeon = payload.get("surgeon_id") or case.get("surgeon_id")
        if surgeon:
            from .notify import notify_in_app
            notify_in_app(
                conn,
                surgeon,
                "OT notes required",
                f"Add OT notes for {case['patient_name']} — {case['procedure_name']}.",
                "ot",
                ot_id,
            )
    audit(conn, user, "ot_update", "ot", "ot", ot_id, old={"status": case["status"]}, new={"status": status})
    publish("ot.updated", {"id": ot_id, "status": status, "patient_id": case["patient_id"], "permission": "ot.view"})
    return get_ot(conn, ot_id)


def ot_notes(conn, user, ot_id: str, payload: dict) -> dict:
    permit_any(user, ["ot.manage", "ot.intraop.record"], conn, "ot_notes")
    case = get_ot(conn, ot_id)
    if not access.can_view_patient(conn, user, case.get("patient_id")):
        access.hide_record(conn, user, "ot", ot_id)
    outcome = payload.get("outcome")
    require(outcome in OT_OUTCOMES, "Outcome must be SUCCESSFUL, UNSUCCESSFUL, or ABORTED.")
    require(clean_text(payload.get("procedure_notes"), 4000), "Procedure notes are required, whatever the outcome.")
    ot_sql.q_wards_19594(conn, clean_text(payload.get("pre_op_notes"), 2000), clean_text(payload.get("procedure_notes"), 4000), clean_text(payload.get("findings"), 2000), clean_text(payload.get("complications"), 2000), clean_text(payload.get("post_op_instructions"), 2000), outcome, user["id"], now_iso(), clean_text(payload.get("anesthesia"), 120) or None, clean_text(payload.get("assistants"), 240) or None, now_iso(), ot_id)
    from .billing import configured_procedure_fee
    configured = configured_procedure_fee(conn, case.get("procedure_id"))
    fee = configured if configured is not None else int(payload.get("fee_paise") or 0)
    if fee:
        invoice = open_draft(conn, user, case["patient_id"], case.get("encounter_id"), case.get("admission_id"), "IPD" if case.get("admission_id") else "OPD")
        add_item(
            conn, user, invoice["id"],
            {
                "description": f"OT — {case['procedure_name']} ({outcome.title()})",
                "category": "OT",
                "rate_paise": fee,
                "qty": 1,
                "unit": "procedure",
                "source_module": "ot",
                "source_id": ot_id,
                "master_item_id": case.get("procedure_id"),
            },
        )
    audit(conn, user, "ot_notes", "ot", "ot", ot_id, new={"outcome": outcome})
    publish("ot.updated", {"id": ot_id, "outcome": outcome, "patient_id": case["patient_id"], "permission": "ot.view"})
    return get_ot(conn, ot_id)


def order_labs(conn, user, payload: dict) -> dict:
    from .laboratory import place_order
    return place_order(conn, user, payload)


def get_lab_order(conn, order_id: str) -> dict:
    from .laboratory import present
    return present(conn, order_id)


def list_labs(conn, status: str = "") -> dict:
    if status:
        items = lab_sql.q_wards_24616(conn, status)
    else:
        items = lab_sql.q_wards_24732(conn)
    from .laboratory import enrich
    for item in items:
        item["patient_name"] = name_of(conn, "patients", item["patient_id"])
        enrich(conn, item)
    return {"items": items, "total": len(items)}


def set_lab_status(conn, user, order_id: str, status: str) -> dict:
    from .laboratory import reject_direct_status
    return reject_direct_status(conn, user, order_id, status)


def save_lab_result(conn, user, item_id: str, result_text: str, document_id: str | None = None, units: str | None = None, reference_range: str | None = None, status: str = "ENTERED") -> dict:
    from .laboratory import enter_result
    return enter_result(conn, user, item_id, {
        "value": result_text,
        "units": units,
        "reference_range": reference_range,
        "status": status,
        "document_id": document_id,
    })


def store_document(conn, user, payload: dict) -> dict:
    permit(user, "document.upload")
    mime = (payload.get("mime_type") or "application/octet-stream").lower()
    require(mime in ALLOWED_MIME, "This file type is not accepted. Use PDF or an image.")
    raw_b64 = payload.get("content_base64") or ""
    try:
        data = base64.b64decode(raw_b64, validate=True)
    except Exception as exc:
        raise ApiError("The file could not be read.") from exc
    require(0 < len(data) <= 8 * 1024 * 1024, "File must be between 1 byte and 8 MB.")
    patient_id = payload.get("patient_id")
    if patient_id:
        require(patients_sql.q_wards_27528(conn, patient_id), "Patient not found.", 404, "not_found")
    from .storage import get_storage

    doc_id = new_id("DOC")
    ext = ALLOWED_MIME[mime]
    stored = f"{doc_id}{ext}"
    key = f"{patient_id or '_unlinked'}/{stored}"
    storage = get_storage()
    saved = storage.save(key, data, mime)
    checksum = saved["checksum"]
    try:
        documents_sql.q_wards_28079(conn, doc_id, patient_id, clean_text(payload.get("entity_type"), 40), clean_text(payload.get("entity_id"), 40), clean_text(payload.get("document_type") or "Other", 80), clean_text(payload.get("title"), 160), safe_filename(payload.get("filename") or "document"), key, mime, len(data), checksum, user["id"], now_iso(), clean_text(payload.get("notes"), 400))
    except Exception:
        if storage.exists(key):
            storage.delete(key)
        raise
    audit(conn, user, "document_upload", "documents", "document", doc_id, new={"type": payload.get("document_type"), "patient_id": patient_id, "checksum": checksum})
    publish("document.updated", {"id": doc_id, "patient_id": patient_id})
    return documents_sql.q_wards_29086(conn, doc_id)


def document_file(conn, doc_id: str) -> tuple[dict, bytes]:
    from .storage import get_storage

    doc = documents_sql.q_wards_29339(conn, doc_id)
    require(doc, "That record was not found.", 404, "not_found")
    storage = get_storage()
    key = doc["stored_name"]
    require(storage.exists(key), "File is missing from local storage.", 404, "not_found")
    meta = storage.metadata(key)
    require(meta["size"] == doc["size_bytes"], "Stored file does not match the document record.", 409, "storage_mismatch")
    return doc, storage.read(key)


def deactivate_document(conn, user, doc_id: str, reason: str) -> dict:
    permit(user, "document.deactivate")
    doc = documents_sql.q_wards_29802(conn, doc_id)
    require(doc, "Document not found.", 404, "not_found")
    require(reason, "Say why this document is being withdrawn.")
    documents_sql.q_wards_29988(conn, clean_text(reason, 400), doc_id)
    audit(conn, user, "document_deactivate", "documents", "document", doc_id, reason=reason)
    return {"id": doc_id, "active": 0}


def list_documents(conn, patient_id: str = "", entity_type: str = "", entity_id: str = "", q: str = "") -> dict:
    return {"items": documents_sql.list_documents(conn, patient_id, entity_type, entity_id, q)}


def _hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _stored_key(scope: str, key: str) -> str:
    return f"ipd:{scope}:{key}"


def _admission_result(conn, admission_id: str) -> dict:
    row = get_admission(conn, admission_id)
    invoices = row.get("invoices") or []
    if invoices:
        row["invoice_id"] = invoices[0]["id"]
    return row


def _replay(conn, user, scope: str, key: str, digest: str, loader):
    if not key:
        return None
    claim = ipd_sql.claim_key(conn, _stored_key(scope, key), f"ipd.{scope}", digest, now_iso())
    if claim["status"] == "conflict":
        raise ApiError("This idempotency key was already used for a different request.", 409, "conflict")
    if claim["status"] == "in_progress":
        raise ApiError("This request is already being processed.", 409, "conflict")
    if claim["status"] == "replay":
        row = loader(claim["entity_id"])
        patient_id = row.get("patient_id")
        if not access.can_view_patient(conn, user, patient_id):
            access.hide_record(conn, user, "admission", claim["entity_id"])
        return row
    return None


def assign_bed(conn, user, admission_id: str, bed_id: str, reason: str = "", idempotency_key: str = "") -> dict:
    permit_any(user, ["admission.manage", "ipd.bed.assign"], conn, "ipd_assign")
    key = clean_text(idempotency_key, 80)
    digest = _hash({"admission_id": admission_id, "bed_id": bed_id})
    replay = _replay(conn, user, "assign", key, digest, lambda entity: get_admission(conn, entity))
    if replay is not None:
        return replay
    adm = ipd_sql.lock_admission(conn, admission_id)
    if not adm or not access.can_view_patient(conn, user, adm.get("patient_id")):
        access.hide_record(conn, user, "admission", admission_id)
    require(adm["status"] == "REQUESTED", "Only a requested admission can be assigned a first bed.", 409, "invalid_transition")
    bed = ipd_sql.lock_bed(conn, bed_id)
    if not bed or not int(bed.get("active") or 0):
        raise ApiError(NOT_FOUND, 404, "not_found")
    assigned_room = wards_sql.q_wards_3362(conn, bed["room_id"])
    assigned_ward = wards_sql.q_wards_13816(conn, bed["ward_id"])
    if not assigned_room or not int(assigned_room.get("active") or 0) or not assigned_ward or not int(assigned_ward.get("active") or 0):
        raise ApiError(NOT_FOUND, 404, "not_found")
    require(bed["status"] == "AVAILABLE" and not bed.get("current_admission_id"), "That bed is not available.", 409, "conflict")
    room = wards_sql.q_wards_3362(conn, bed["room_id"])
    rate = int(room["daily_rate_paise"] or 0) if room else 0
    at = now_iso()
    require(ipd_sql.occupy_bed(conn, bed_id, admission_id) == 1, "That bed is not available.", 409, "conflict")
    require(ipd_sql.place_on_bed(conn, admission_id, bed["ward_id"], bed["room_id"], bed["id"], rate, at) == 1, "The admission changed. Assign it again.", 409, "conflict")
    ipd_sql.q_wards_4737(conn, admission_id, adm["patient_id"], bed["id"], clean_text(reason, 240) or "Assignment", user["id"], at)
    if rate:
        post_charge(conn, user, admission_id, "Bed / room charge — admission day", "IPD", rate, 1, "day", "admission", admission_id)
    if key:
        ipd_sql.finish_key(conn, _stored_key("assign", key), admission_id)
    audit(conn, user, "bed_assign", "ipd", "admission", admission_id, new={"bed_id": bed_id, "rate_paise": rate})
    publish("ipd.bed.assigned", {"id": bed_id, "patient_id": adm["patient_id"], "admission_id": admission_id})
    publish("admission.updated", {"id": admission_id, "patient_id": adm["patient_id"], "status": "ADMITTED"})
    return get_admission(conn, admission_id)


def mark_discharge_pending(conn, user, admission_id: str) -> dict:
    permit_any(user, ["admission.manage", "ipd.discharge.finalize"], conn, "ipd_pending")
    adm = ipd_sql.lock_admission(conn, admission_id)
    if not adm or not access.can_view_patient(conn, user, adm.get("patient_id")):
        access.hide_record(conn, user, "admission", admission_id)
    require(ipd_sql.mark_discharge_pending(conn, admission_id, now_iso()) == 1, "Only an admitted patient can be marked ready for discharge.", 409, "invalid_transition")
    audit(conn, user, "discharge_pending", "ipd", "admission", admission_id, new={"status": "DISCHARGE_PENDING", "bed_id": adm.get("bed_id")})
    publish("admission.updated", {"id": admission_id, "patient_id": adm["patient_id"], "status": "DISCHARGE_PENDING"})
    return get_admission(conn, admission_id)


def cancel_admission(conn, user, admission_id: str, reason: str) -> dict:
    permit_any(user, ["admission.manage", "ipd.admission.create"], conn, "ipd_cancel")
    require(clean_text(reason, 400), "Say why this admission is being cancelled.")
    adm = ipd_sql.lock_admission(conn, admission_id)
    if not adm or not access.can_view_patient(conn, user, adm.get("patient_id")):
        access.hide_record(conn, user, "admission", admission_id)
    at = now_iso()
    if adm.get("bed_id"):
        require(ipd_sql.release_bed(conn, adm["bed_id"], admission_id) == 1, "The bed changed. Cancel it again.", 409, "conflict")
        ipd_sql.q_wards_12128(conn, admission_id, adm["patient_id"], adm["bed_id"], "Cancelled", user["id"], at)
        publish("ipd.bed.released", {"id": adm["bed_id"], "patient_id": adm["patient_id"], "admission_id": admission_id})
    require(ipd_sql.mark_cancelled(conn, admission_id, at, clean_text(reason, 400)) == 1, "This admission can no longer be cancelled.", 409, "invalid_transition")
    audit(conn, user, "admission_cancel", "ipd", "admission", admission_id, reason=reason, new={"status": "CANCELLED"})
    publish("admission.updated", {"id": admission_id, "patient_id": adm["patient_id"], "status": "CANCELLED"})
    return get_admission(conn, admission_id)


def _discharge_fingerprint(conn, adm: dict) -> str:
    charges = ipd_sql.q_wards_6127(conn, adm["id"])
    profile = hospital(conn)
    payload = {
        "admission_id": adm["id"],
        "patient_id": adm["patient_id"],
        "summary": adm.get("discharge_summary") or "",
        "condition": adm.get("discharge_condition") or "",
        "hospital": profile.get("name") or "",
        "charges": [(row["id"], row["amount_paise"], row["description"]) for row in charges],
    }
    return _hash(payload)


def generate_discharge_document(conn, user, admission_id: str) -> dict:
    permit_any(user, ["admission.manage", "ipd.discharge.document", "document.upload"], conn, "ipd_document")
    adm = ipd_sql.lock_admission(conn, admission_id)
    if not adm or not access.can_view_patient(conn, user, adm.get("patient_id")):
        access.hide_record(conn, user, "admission", admission_id)
    require(adm["status"] == "DISCHARGED", "Discharge the patient before preparing the summary.", 409, "invalid_transition")
    fingerprint = _discharge_fingerprint(conn, adm)
    existing_id = adm.get("discharge_document_id")
    if existing_id and adm.get("discharge_fingerprint") == fingerprint:
        doc = documents_sql.q_wards_29086(conn, existing_id)
        if doc:
            return doc
    from .pdf import render_discharge_summary
    from .storage import get_storage

    profile = hospital(conn)
    charges = ipd_sql.q_wards_6127(conn, admission_id)
    patient = patients_sql.q_wards_2672(conn, adm["patient_id"]) or {}
    data = render_discharge_summary({
        "hospital_name": profile.get("name") or "Hospital",
        "hospital_address": ", ".join(x for x in [profile.get("address_line1"), profile.get("city")] if x),
        "patient_id": adm["patient_id"],
        "patient_name": patient.get("name") or name_of(conn, "patients", adm["patient_id"]),
        "admission_id": admission_id,
        "admitted_at": adm.get("admitted_at") or "",
        "discharged_at": adm.get("discharged_at") or "",
        "condition": adm.get("discharge_condition") or "",
        "summary": adm.get("discharge_summary") or "",
        "doctor": doctor_label(conn, adm.get("discharge_doctor_id") or adm.get("doctor_id")),
        "charges": charges,
    })
    doc_id = new_id("DOC")
    key = f"{adm['patient_id']}/{doc_id}.pdf"
    storage = get_storage()
    saved = storage.save(key, data, "application/pdf")
    try:
        documents_sql.q_wards_28079(
            conn, doc_id, adm["patient_id"], "admission", admission_id, "Discharge summary",
            f"Discharge summary {admission_id}", f"{doc_id}.pdf", key, "application/pdf",
            len(data), saved["checksum"], user["id"], now_iso(), "Generated from the stored discharge summary",
        )
    except Exception:
        if storage.exists(key):
            storage.delete(key)
        raise
    ipd_sql.set_discharge_document(conn, admission_id, doc_id, fingerprint)
    action = "discharge_document_correction" if existing_id else "discharge_document"
    audit(conn, user, action, "ipd", "admission", admission_id, new={"document_id": doc_id, "checksum": saved["checksum"]})
    publish("document.updated", {"id": doc_id, "patient_id": adm["patient_id"]})
    return documents_sql.q_wards_29086(conn, doc_id)


def discharge_document_file(conn, user, admission_id: str) -> tuple[dict, bytes]:
    permit_any(user, ["admission.view", "ipd.admission.view", "ipd.discharge.document", "document.view"], conn, "ipd_document_read")
    adm = ipd_sql.q_wards_5554(conn, admission_id)
    if not adm or not access.can_view_patient(conn, user, adm.get("patient_id")):
        access.hide_record(conn, user, "admission", admission_id)
    doc_id = adm.get("discharge_document_id")
    if not doc_id:
        raise ApiError(NOT_FOUND, 404, "not_found")
    doc, data = document_file(conn, doc_id)
    if doc.get("patient_id") != adm["patient_id"]:
        access.hide_record(conn, user, "document", doc_id)
    return doc, data
