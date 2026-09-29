"""Operating theatre workflow. Money stays in Phase 4. Stock stays in pharmacy."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta

from aipf.repo import documents as documents_sql
from aipf.repo import ot as ot_sql

from . import access
from .billing import add_item, configured_procedure_fee, open_draft
from .core import audit, config_get, doctor_label, hospital, name_of, next_number, permit_any
from .events import publish
from .util import ApiError, clean_text, new_id, now, require
from .wards import NOT_FOUND, document_file, get_ot

PRIORITIES = ("ROUTINE", "URGENT", "EMERGENCY")
FUNCTIONS = ("surgeon", "assistant", "anesthetist", "nurse", "technician")
CONSENT = ("PENDING", "OBTAINED", "REFUSED")
READINESS = ("PENDING", "READY", "NOT_READY")
OPEN_ADMISSION = ("REQUESTED", "ADMITTED", "DISCHARGE_PENDING")


def _stamp() -> str:
    return now().isoformat(timespec="milliseconds")


def _hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _stored_key(scope: str, key: str) -> str:
    return f"ot:{scope}:{key}"


def _flag(conn, key: str) -> bool:
    return config_get(conn, key, "1") == "1"


def _exclusive(conn) -> set[str]:
    raw = config_get(conn, "ot_exclusive_functions", "surgeon")
    return {part.strip() for part in raw.split(",") if part.strip()}


def _moment(value) -> str:
    text = clean_text(value, 19)
    require(len(text) >= 16 and text[4] == "-" and text[7] == "-" and text[10] == "T", "Use a date and time, such as 2026-10-01T08:00:00.")
    if len(text) == 16:
        text += ":00"
    require(len(text) == 19 and text[13] == ":" and text[16] == ":", "Use a date and time, such as 2026-10-01T08:00:00.")
    try:
        datetime.strptime(text, "%Y-%m-%dT%H:%M:%S")
    except ValueError as exc:
        raise ApiError("Use a date and time, such as 2026-10-01T08:00:00.") from exc
    return text


def _add_minutes(start: str, minutes: int) -> str:
    return (datetime.strptime(start, "%Y-%m-%dT%H:%M:%S") + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S")


def _own(conn, user, case: dict | None, ot_id: str) -> dict:
    if not case or not access.can_view_patient(conn, user, case.get("patient_id")):
        access.hide_record(conn, user, "ot", ot_id)
    return case


def _replay(conn, user, scope: str, key: str, digest: str):
    if not key:
        return None
    claim = ot_sql.claim_key(conn, _stored_key(scope, key), f"ot.{scope}", digest, _stamp())
    if claim["status"] == "conflict":
        raise ApiError("This idempotency key was already used for a different request.", 409, "conflict")
    if claim["status"] == "in_progress":
        raise ApiError("This request is already being processed.", 409, "conflict")
    if claim["status"] == "replay":
        row = present(conn, user, claim["entity_id"])
        row["idempotent_replay"] = True
        return row
    return None


def _finish(conn, scope: str, key: str, ot_id: str) -> None:
    if key:
        ot_sql.finish_key(conn, _stored_key(scope, key), ot_id)


def _emit(event: str, case: dict, **extra) -> None:
    publish(event, {"id": case["id"], "patient_id": case.get("patient_id"), "status": case.get("status"), "permission": "ot.view", **extra})


def _safe_doc(doc: dict | None) -> dict | None:
    if not doc:
        return None
    return {key: value for key, value in doc.items() if key not in {"stored_name", "path", "logo_path"}}


def present(conn, user, ot_id: str) -> dict:
    try:
        case = get_ot(conn, ot_id)
    except ApiError:
        access.hide_record(conn, user, "ot", ot_id)
        raise
    _own(conn, user, case, ot_id)
    case["bookings"] = ot_sql.bookings_for(conn, ot_id)
    case["history"] = ot_sql.history_for(conn, ot_id)
    case["team"] = ot_sql.team_for(conn, ot_id)
    case["preop"] = ot_sql.preop_for(conn, ot_id)
    case["intraop"] = ot_sql.intraop_for(conn, ot_id)
    case["postop"] = ot_sql.postop_for(conn, ot_id)
    case["links"] = ot_sql.links_for(conn, ot_id)
    case["charges"] = ot_sql.charges_for(conn, ot_id)
    latest = case["preop"][-1]["id"] if case["preop"] else ""
    case["checks"] = ot_sql.checks_for(conn, latest) if latest else []
    theatre = ot_sql.get_theatre(conn, case.get("theatre_id")) if case.get("theatre_id") else None
    case["theatre_name"] = (theatre or {}).get("name") or ""
    case["theatre_code"] = (theatre or {}).get("code") or ""
    if case.get("report_document_id"):
        case["report"] = _safe_doc(documents_sql.q_wards_29086(conn, case["report_document_id"]))
    return case


def _bound(conn, patient_id: str, encounter_id: str | None, admission_id: str | None) -> None:
    if encounter_id:
        owned = ot_sql.encounter_owner(conn, encounter_id)
        if not owned or owned["patient_id"] != patient_id:
            raise ApiError(NOT_FOUND, 404, "not_found")
    if admission_id:
        owned = ot_sql.admission_owner(conn, admission_id)
        if not owned or owned["patient_id"] != patient_id:
            raise ApiError(NOT_FOUND, 404, "not_found")
        if encounter_id and owned.get("encounter_id") and owned["encounter_id"] != encounter_id:
            raise ApiError(NOT_FOUND, 404, "not_found")
        require(owned["status"] in OPEN_ADMISSION, "That admission is not open.", 409, "invalid_transition")


def list_theatres(conn, include_inactive: bool = False) -> dict:
    items = ot_sql.list_theatres(conn, include_inactive)
    return {"items": items, "total": len(items)}


def save_theatre(conn, user, payload: dict, theatre_id: str | None = None) -> dict:
    permit_any(user, ["ot.theatre.manage", "master.manage"], conn, "ot_theatre")
    require(not payload.get("delete"), "A theatre is deactivated, not deleted.", 409, "conflict")
    name = clean_text(payload.get("name"), 120)
    code = clean_text(payload.get("code"), 40)
    require(name and code, "Theatre code and name are required.")
    location = clean_text(payload.get("location"), 160)
    active = 0 if payload.get("active") in (0, "0", False) else 1
    at = _stamp()
    if theatre_id:
        current = ot_sql.get_theatre(conn, theatre_id)
        require(current, NOT_FOUND, 404, "not_found")
        clash = ot_sql.theatre_by_code(conn, code)
        require(not clash or clash["id"] == theatre_id, "That theatre code is already in use.", 409, "conflict")
        ot_sql.update_theatre(conn, theatre_id, code, name, location, active, at)
        audit(conn, user, "theatre_save", "ot", "theatre", theatre_id, new={"code": code, "active": active})
        return ot_sql.get_theatre(conn, theatre_id)
    require(not ot_sql.theatre_by_code(conn, code), "That theatre code is already in use.", 409, "conflict")
    tid = new_id("THR")
    if not ot_sql.insert_theatre(conn, (tid, code, name, location, active, at, at)):
        raise ApiError("That theatre code is already in use.", 409, "conflict")
    audit(conn, user, "theatre_save", "ot", "theatre", tid, new={"code": code, "name": name})
    return ot_sql.get_theatre(conn, tid)


def list_procedures(conn, include_inactive: bool = False) -> dict:
    items = ot_sql.list_procedures(conn, include_inactive)
    return {"items": items, "total": len(items)}


def save_procedure(conn, user, payload: dict, procedure_id: str | None = None) -> dict:
    permit_any(user, ["ot.procedure.manage", "master.manage"], conn, "ot_procedure")
    require(not payload.get("delete"), "A procedure is deactivated, not deleted.", 409, "conflict")
    name = clean_text(payload.get("name"), 160)
    code = clean_text(payload.get("code"), 40)
    require(name and code, "Procedure code and name are required.")
    try:
        price = int(payload.get("price_paise"))
    except (TypeError, ValueError) as exc:
        raise ApiError("Enter the procedure price in paise.") from exc
    require(price >= 0, "Procedure price cannot be negative.")
    try:
        duration = int(payload.get("duration_minutes") or 60)
    except (TypeError, ValueError) as exc:
        raise ApiError("Duration must be a number of minutes.") from exc
    require(duration > 0, "Duration must be at least one minute.")
    department_id = payload.get("department_id") or None
    category = clean_text(payload.get("category"), 80)
    require_admission = 1 if payload.get("require_admission") in (1, "1", True) else 0
    active = 0 if payload.get("active") in (0, "0", False) else 1
    at = _stamp()
    if procedure_id:
        current = ot_sql.get_procedure(conn, procedure_id)
        require(current, NOT_FOUND, 404, "not_found")
        clash = ot_sql.procedure_by_code(conn, code)
        require(not clash or clash["id"] == procedure_id, "That procedure code is already in use.", 409, "conflict")
        ot_sql.update_procedure(conn, (code, name, department_id, category, price, duration, require_admission, active, at, procedure_id))
        audit(conn, user, "procedure_save", "ot", "procedure", procedure_id, new={"price_paise": price, "active": active})
        return ot_sql.get_procedure(conn, procedure_id)
    require(not ot_sql.procedure_by_code(conn, code), "That procedure code is already in use.", 409, "conflict")
    pid = new_id("OTP")
    if not ot_sql.insert_procedure(conn, (pid, code, name, department_id, category, price, duration, require_admission, active, at, at)):
        raise ApiError("That procedure code is already in use.", 409, "conflict")
    audit(conn, user, "procedure_save", "ot", "procedure", pid, new={"code": code, "price_paise": price})
    return ot_sql.get_procedure(conn, pid)


def list_checklist(conn, include_inactive: bool = False) -> dict:
    items = ot_sql.list_checklist(conn, include_inactive)
    return {"items": items, "total": len(items)}


def save_checklist(conn, user, payload: dict, item_id: str | None = None) -> dict:
    permit_any(user, ["ot.theatre.manage", "master.manage"], conn, "ot_checklist")
    require(not payload.get("delete"), "A checklist item is deactivated, not deleted.", 409, "conflict")
    label = clean_text(payload.get("label"), 160)
    code = clean_text(payload.get("code"), 40)
    require(label and code, "Checklist code and label are required.")
    required = 1 if payload.get("required") in (1, "1", True) else 0
    active = 0 if payload.get("active") in (0, "0", False) else 1
    sort_order = int(payload.get("sort_order") or 0)
    if item_id:
        require(ot_sql.get_checklist(conn, item_id), NOT_FOUND, 404, "not_found")
        ot_sql.update_checklist(conn, label, required, active, sort_order, item_id)
        return ot_sql.get_checklist(conn, item_id)
    require(not ot_sql.checklist_by_code(conn, code), "That checklist code is already in use.", 409, "conflict")
    cid = new_id("CHK")
    if not ot_sql.insert_checklist(conn, (cid, code, label, required, active, sort_order)):
        raise ApiError("That checklist code is already in use.", 409, "conflict")
    audit(conn, user, "checklist_save", "ot", "checklist", cid, new={"code": code, "required": required})
    return ot_sql.get_checklist(conn, cid)


def delete_theatre(conn, user, theatre_id: str) -> dict:
    permit_any(user, ["ot.theatre.manage", "master.manage"], conn, "ot_theatre_delete")
    current = ot_sql.get_theatre(conn, theatre_id)
    require(current, NOT_FOUND, 404, "not_found")
    require(ot_sql.theatre_open_use(conn, theatre_id) == 0, "This theatre has an open case or booking. Finish or cancel that work first.", 409, "conflict")
    audit(conn, user, "theatre_delete", "ot", "theatre", theatre_id, old={"name": current.get("name"), "code": current.get("code")})
    ot_sql.delete_theatre(conn, theatre_id)
    return {"ok": True, "id": theatre_id}


def delete_procedure(conn, user, procedure_id: str) -> dict:
    permit_any(user, ["ot.procedure.manage", "master.manage"], conn, "ot_procedure_delete")
    current = ot_sql.get_procedure(conn, procedure_id)
    require(current, NOT_FOUND, 404, "not_found")
    require(ot_sql.procedure_in_use(conn, procedure_id) == 0, "This procedure is on a case or a bill. Deactivate it instead of erasing it.", 409, "conflict")
    audit(conn, user, "procedure_delete", "ot", "procedure", procedure_id, old={"name": current.get("name"), "code": current.get("code")})
    ot_sql.delete_procedure(conn, procedure_id)
    return {"ok": True, "id": procedure_id}


def delete_checklist(conn, user, item_id: str) -> dict:
    permit_any(user, ["ot.theatre.manage", "master.manage"], conn, "ot_checklist_delete")
    current = ot_sql.get_checklist(conn, item_id)
    require(current, NOT_FOUND, 404, "not_found")
    require(ot_sql.checklist_in_use(conn, item_id) == 0, "This checklist item is on a recorded case. Deactivate it instead of erasing it.", 409, "conflict")
    audit(conn, user, "checklist_delete", "ot", "checklist", item_id, old={"label": current.get("label"), "code": current.get("code")})
    ot_sql.delete_checklist(conn, item_id)
    return {"ok": True, "id": item_id}


def request_case(conn, user, payload: dict, fallback: str = "") -> dict:
    permit_any(user, ["ot.request", "ot.manage"], conn, "ot_request")
    patient_id = payload.get("patient_id") or ""
    require(patient_id, "Patient is required.")
    require(not payload.get("phone") or patient_id, "Patient is required.")
    if not ot_sql.patient_owner(conn, patient_id) or not access.can_view_patient(conn, user, patient_id):
        access.hide_record(conn, user, "patient", patient_id)
    procedure_id = clean_text(payload.get("procedure_id"), 40)
    require(procedure_id, "Choose a procedure.")
    procedure = ot_sql.get_procedure(conn, procedure_id)
    if not procedure or int(procedure.get("active") or 0) != 1:
        raise ApiError(NOT_FOUND, 404, "not_found")
    encounter_id = payload.get("encounter_id") or None
    admission_id = payload.get("admission_id") or None
    require(encounter_id, "Encounter is required.")
    _bound(conn, patient_id, encounter_id, admission_id)
    if int(procedure.get("require_admission") or 0) == 1:
        require(admission_id, "This procedure needs an admission.")
    priority = (clean_text(payload.get("priority") or "ROUTINE", 20) or "ROUTINE").upper()
    require(priority in PRIORITIES, "Priority must be routine, urgent, or emergency.")
    indication = clean_text(payload.get("indication"), 500)
    require(indication, "Indication is required.")
    key = clean_text(payload.get("idempotency_key") or fallback, 80)
    digest = _hash({"patient_id": patient_id, "encounter_id": encounter_id, "admission_id": admission_id, "procedure_id": procedure_id, "indication": indication, "priority": priority})
    replay = _replay(conn, user, "request", key, digest)
    if replay is not None:
        return replay
    oid = next_number(conn, "ot", "OT", 6, True)
    at = _stamp()
    surgeon_id = payload.get("surgeon_id") or None
    if surgeon_id and not ot_sql.lock_user(conn, surgeon_id):
        raise ApiError(NOT_FOUND, 404, "not_found")
    ot_sql.insert_request(conn, (
        oid, patient_id, encounter_id, admission_id, procedure["name"], procedure_id, procedure.get("code"),
        surgeon_id, priority, indication, user["id"], at, at,
    ))
    _finish(conn, "request", key, oid)
    audit(conn, user, "ot_request", "ot", "ot", oid, new={"procedure_id": procedure_id, "patient_id": patient_id})
    row = present(conn, user, oid)
    _emit("ot.request.created", row)
    return row


def approve(conn, user, ot_id: str, payload: dict, fallback: str = "") -> dict:
    permit_any(user, ["ot.approve", "ot.manage"], conn, "ot_approve")
    key = clean_text((payload or {}).get("idempotency_key") or fallback, 80)
    digest = _hash({"ot_id": ot_id, "action": "approve"})
    replay = _replay(conn, user, "approve", key, digest)
    if replay is not None:
        return replay
    case = _own(conn, user, ot_sql.lock_case(conn, ot_id), ot_id)
    if case["status"] == "APPROVED":
        _finish(conn, "approve", key, ot_id)
        return present(conn, user, ot_id)
    require(case["status"] == "REQUESTED", "Only a requested case can be approved.", 409, "invalid_transition")
    require(ot_sql.mark_approved(conn, ot_id, _stamp(), user["id"]), "Only a requested case can be approved.", 409, "invalid_transition")
    _finish(conn, "approve", key, ot_id)
    audit(conn, user, "ot_approve", "ot", "ot", ot_id, old={"status": "REQUESTED"}, new={"status": "APPROVED"})
    row = present(conn, user, ot_id)
    _emit("ot.updated", row)
    return row


def _window(conn, case: dict, payload: dict) -> tuple[str, str]:
    start_at = _moment(payload.get("start_at") or payload.get("scheduled_at"))
    procedure = ot_sql.get_procedure(conn, case.get("procedure_id")) if case.get("procedure_id") else None
    duration = int((procedure or {}).get("duration_minutes") or 60)
    end_at = _moment(payload.get("end_at")) if payload.get("end_at") else _add_minutes(start_at, duration)
    require(end_at > start_at, "End time must be after the start.")
    return start_at, end_at


def _occupy(conn, theatre_id: str, surgeon_id: str, start_at: str, end_at: str, ignore_booking: str) -> None:
    theatre = ot_sql.lock_theatre(conn, theatre_id)
    if not theatre:
        raise ApiError(NOT_FOUND, 404, "not_found")
    require(int(theatre.get("active") or 0) == 1, "That theatre is not available.", 409, "conflict")
    surgeon = ot_sql.lock_user(conn, surgeon_id)
    if not surgeon or int(surgeon.get("active") or 0) != 1:
        raise ApiError(NOT_FOUND, 404, "not_found")
    if ot_sql.theatre_overlap(conn, theatre_id, start_at, end_at, ignore_booking):
        raise ApiError("That theatre is already booked for this time.", 409, "conflict")
    if ot_sql.surgeon_overlap(conn, surgeon_id, start_at, end_at, ignore_booking):
        raise ApiError("That surgeon is already booked for this time.", 409, "conflict")
    for function_code in _exclusive(conn):
        if function_code == "surgeon":
            continue
        if ot_sql.team_overlap(conn, surgeon_id, function_code, start_at, end_at, ignore_booking):
            raise ApiError("That person is already booked for this time.", 409, "conflict")


def schedule(conn, user, ot_id: str, payload: dict, fallback: str = "") -> dict:
    permit_any(user, ["ot.schedule", "ot.manage"], conn, "ot_schedule")
    theatre_id = clean_text(payload.get("theatre_id"), 40)
    surgeon_id = clean_text(payload.get("surgeon_id"), 40)
    require(theatre_id and surgeon_id, "Theatre and surgeon are required.")
    start_at = _moment(payload.get("start_at") or payload.get("scheduled_at"))
    key = clean_text(payload.get("idempotency_key") or fallback, 80)
    digest = _hash({"ot_id": ot_id, "theatre_id": theatre_id, "surgeon_id": surgeon_id, "start_at": start_at, "end_at": payload.get("end_at") or ""})
    replay = _replay(conn, user, "schedule", key, digest)
    if replay is not None:
        return replay
    case = _own(conn, user, ot_sql.lock_case(conn, ot_id), ot_id)
    require(case["status"] in ("APPROVED", "POSTPONED"), "Approve the request before scheduling.", 409, "invalid_transition")
    if int((ot_sql.get_procedure(conn, case.get("procedure_id")) or {}).get("require_admission") or 0) == 1:
        owned = ot_sql.admission_owner(conn, case.get("admission_id") or "")
        if not owned or owned["patient_id"] != case["patient_id"] or owned["status"] not in ("ADMITTED", "DISCHARGE_PENDING"):
            raise ApiError("The patient must be admitted before this procedure is scheduled.", 409, "invalid_transition")
    start_at, end_at = _window(conn, case, payload)
    _occupy(conn, theatre_id, surgeon_id, start_at, end_at, "")
    if ot_sql.active_booking(conn, ot_id):
        raise ApiError("This case already has a booking.", 409, "conflict")
    at = _stamp()
    booking_id = new_id("OTB")
    if not ot_sql.insert_booking(conn, (booking_id, ot_id, theatre_id, surgeon_id, start_at, end_at, "SCHEDULED", user["id"], at, at)):
        raise ApiError("This case already has a booking.", 409, "conflict")
    ot_sql.insert_history(conn, (new_id("OTH"), booking_id, ot_id, "schedule", theatre_id, surgeon_id, start_at, end_at, clean_text(payload.get("reason"), 240), user["id"], at))
    require(ot_sql.set_scheduled(conn, ot_id, theatre_id, surgeon_id, start_at, at), "Approve the request before scheduling.", 409, "invalid_transition")
    _finish(conn, "schedule", key, ot_id)
    audit(conn, user, "ot_schedule", "ot", "ot", ot_id, new={"theatre_id": theatre_id, "start_at": start_at, "end_at": end_at})
    row = present(conn, user, ot_id)
    _emit("ot.scheduled", row)
    return row


def reschedule(conn, user, ot_id: str, payload: dict, fallback: str = "") -> dict:
    permit_any(user, ["ot.schedule", "ot.manage"], conn, "ot_reschedule")
    reason = clean_text(payload.get("reason"), 240)
    require(reason, "A reschedule needs a reason.")
    theatre_id = clean_text(payload.get("theatre_id"), 40)
    surgeon_id = clean_text(payload.get("surgeon_id"), 40)
    require(theatre_id and surgeon_id, "Theatre and surgeon are required.")
    key = clean_text(payload.get("idempotency_key") or fallback, 80)
    digest = _hash({"ot_id": ot_id, "theatre_id": theatre_id, "surgeon_id": surgeon_id, "start_at": payload.get("start_at"), "end_at": payload.get("end_at"), "reason": reason})
    replay = _replay(conn, user, "reschedule", key, digest)
    if replay is not None:
        return replay
    case = _own(conn, user, ot_sql.lock_case(conn, ot_id), ot_id)
    require(case["status"] in ("SCHEDULED", "PRE_OP", "POSTPONED"), "This case cannot be rescheduled.", 409, "invalid_transition")
    booking = ot_sql.active_booking(conn, ot_id) or (ot_sql.bookings_for(conn, ot_id) or [None])[-1]
    require(booking, "This case has no booking to move.", 409, "invalid_transition")
    start_at, end_at = _window(conn, case, payload)
    _occupy(conn, theatre_id, surgeon_id, start_at, end_at, booking["id"])
    at = _stamp()
    require(ot_sql.update_booking(conn, booking["id"], theatre_id, surgeon_id, start_at, end_at, at), "This booking can no longer be moved.", 409, "conflict")
    ot_sql.insert_history(conn, (new_id("OTH"), booking["id"], ot_id, "reschedule", booking.get("theatre_id"), booking.get("surgeon_id"), booking.get("start_at"), booking.get("end_at"), reason, user["id"], at))
    require(ot_sql.move_schedule(conn, ot_id, theatre_id, surgeon_id, start_at, at), "This case cannot be rescheduled.", 409, "invalid_transition")
    _finish(conn, "reschedule", key, ot_id)
    audit(conn, user, "ot_reschedule", "ot", "ot", ot_id, old={"start_at": booking.get("start_at")}, new={"start_at": start_at, "end_at": end_at}, reason=reason)
    row = present(conn, user, ot_id)
    _emit("ot.scheduled", row)
    return row


def cancel(conn, user, ot_id: str, payload: dict, fallback: str = "") -> dict:
    permit_any(user, ["ot.cancel", "ot.manage"], conn, "ot_cancel")
    reason = clean_text(payload.get("reason"), 240)
    require(reason, "A cancellation needs a reason.")
    key = clean_text(payload.get("idempotency_key") or fallback, 80)
    digest = _hash({"ot_id": ot_id, "action": "cancel", "reason": reason})
    replay = _replay(conn, user, "cancel", key, digest)
    if replay is not None:
        return replay
    case = _own(conn, user, ot_sql.lock_case(conn, ot_id), ot_id)
    if case["status"] == "CANCELLED":
        _finish(conn, "cancel", key, ot_id)
        return present(conn, user, ot_id)
    booking = ot_sql.active_booking(conn, ot_id)
    at = _stamp()
    require(ot_sql.mark_cancelled(conn, ot_id, at, user["id"], reason), "A completed case is not cancelled here. Use a billing adjustment.", 409, "invalid_transition")
    if booking:
        ot_sql.set_booking_status(conn, ot_id, "CANCELLED", at)
        ot_sql.insert_history(conn, (new_id("OTH"), booking["id"], ot_id, "cancel", booking.get("theatre_id"), booking.get("surgeon_id"), booking.get("start_at"), booking.get("end_at"), reason, user["id"], at))
    else:
        ot_sql.insert_history(conn, (new_id("OTH"), None, ot_id, "cancel", case.get("theatre_id"), case.get("surgeon_id"), case.get("scheduled_at"), None, reason, user["id"], at))
    _finish(conn, "cancel", key, ot_id)
    audit(conn, user, "ot_cancel", "ot", "ot", ot_id, old={"status": case["status"]}, new={"status": "CANCELLED"}, reason=reason)
    row = present(conn, user, ot_id)
    _emit("ot.cancelled", row)
    return row


def postpone(conn, user, ot_id: str, payload: dict, fallback: str = "") -> dict:
    permit_any(user, ["ot.cancel", "ot.schedule", "ot.manage"], conn, "ot_postpone")
    reason = clean_text(payload.get("reason"), 240)
    require(reason, "A postponement needs a reason.")
    key = clean_text(payload.get("idempotency_key") or fallback, 80)
    digest = _hash({"ot_id": ot_id, "action": "postpone", "reason": reason})
    replay = _replay(conn, user, "postpone", key, digest)
    if replay is not None:
        return replay
    case = _own(conn, user, ot_sql.lock_case(conn, ot_id), ot_id)
    booking = ot_sql.active_booking(conn, ot_id)
    at = _stamp()
    require(ot_sql.mark_postponed(conn, ot_id, at, reason), "This case cannot be postponed.", 409, "invalid_transition")
    if booking:
        ot_sql.set_booking_status(conn, ot_id, "POSTPONED", at)
        ot_sql.insert_history(conn, (new_id("OTH"), booking["id"], ot_id, "postpone", booking.get("theatre_id"), booking.get("surgeon_id"), booking.get("start_at"), booking.get("end_at"), reason, user["id"], at))
    _finish(conn, "postpone", key, ot_id)
    audit(conn, user, "ot_postpone", "ot", "ot", ot_id, old={"status": case["status"]}, new={"status": "POSTPONED"}, reason=reason)
    row = present(conn, user, ot_id)
    _emit("ot.updated", row)
    return row


def assign_team(conn, user, ot_id: str, payload: dict, fallback: str = "") -> dict:
    permit_any(user, ["ot.team.manage", "ot.manage"], conn, "ot_team")
    member_id = clean_text(payload.get("user_id"), 40)
    function_code = (clean_text(payload.get("function") or payload.get("function_code"), 40) or "").lower()
    require(member_id and function_code, "Choose a person and a function.")
    require(function_code in FUNCTIONS, "Unknown team function.")
    key = clean_text(payload.get("idempotency_key") or fallback, 80)
    digest = _hash({"ot_id": ot_id, "user_id": member_id, "function": function_code})
    replay = _replay(conn, user, "team", key, digest)
    if replay is not None:
        return replay
    case = _own(conn, user, ot_sql.lock_case(conn, ot_id), ot_id)
    require(case["status"] not in ("COMPLETED", "CANCELLED"), "This case is closed.", 409, "invalid_transition")
    person = ot_sql.lock_user(conn, member_id)
    if not person or int(person.get("active") or 0) != 1:
        raise ApiError(NOT_FOUND, 404, "not_found")
    booking = ot_sql.active_booking(conn, ot_id)
    if function_code in _exclusive(conn) and booking:
        if function_code == "surgeon" and ot_sql.surgeon_overlap(conn, member_id, booking["start_at"], booking["end_at"], booking["id"]):
            raise ApiError("That surgeon is already booked for this time.", 409, "conflict")
        if function_code != "surgeon" and ot_sql.team_overlap(conn, member_id, function_code, booking["start_at"], booking["end_at"], booking["id"]):
            raise ApiError("That person is already booked for this time.", 409, "conflict")
    at = _stamp()
    current = ot_sql.active_team(conn, ot_id, function_code) if function_code == "surgeon" else None
    if current and current["user_id"] == member_id:
        _finish(conn, "team", key, ot_id)
        return present(conn, user, ot_id)
    if current:
        ot_sql.retire_team(conn, current["id"], at)
    if not ot_sql.insert_team(conn, (new_id("OTM"), ot_id, member_id, function_code, user["id"], at)):
        raise ApiError("That function is already filled.", 409, "conflict")
    if function_code == "surgeon":
        ot_sql.set_surgeon(conn, ot_id, member_id, at)
        if booking:
            ot_sql.set_booking_surgeon(conn, booking["id"], member_id, at)
    _finish(conn, "team", key, ot_id)
    audit(conn, user, "ot_team", "ot", "ot", ot_id, new={"user_id": member_id, "function": function_code})
    row = present(conn, user, ot_id)
    _emit("ot.updated", row)
    return row


def record_preop(conn, user, ot_id: str, payload: dict, fallback: str = "") -> dict:
    permit_any(user, ["ot.preop.record", "ot.manage"], conn, "ot_preop")
    consent = (clean_text(payload.get("consent_status") or "PENDING", 20) or "PENDING").upper()
    readiness = (clean_text(payload.get("readiness") or "PENDING", 20) or "PENDING").upper()
    require(consent in CONSENT, "Consent must be pending, obtained, or refused.")
    require(readiness in READINESS, "Readiness must be pending, ready, or not ready.")
    checks = payload.get("checks") or []
    require(isinstance(checks, list), "Checklist answers must be a list.")
    key = clean_text(payload.get("idempotency_key") or fallback, 80)
    digest = _hash({"ot_id": ot_id, "consent": consent, "readiness": readiness, "assessment": payload.get("assessment") or "", "checks": checks})
    replay = _replay(conn, user, "preop", key, digest)
    if replay is not None:
        return replay
    case = _own(conn, user, ot_sql.lock_case(conn, ot_id), ot_id)
    require(case["status"] in ("SCHEDULED", "PRE_OP"), "Record pre-operative details after the case is scheduled.", 409, "invalid_transition")
    at = _stamp()
    preop_id = new_id("OPR")
    ot_sql.insert_preop(conn, (
        preop_id, ot_id, consent, readiness, clean_text(payload.get("assessment"), 4000),
        clean_text(payload.get("allergies"), 500), user["id"], at,
    ))
    for item in checks:
        item_id = (item or {}).get("item_id")
        row = ot_sql.get_checklist(conn, item_id) if item_id else None
        if not row or int(row.get("active") or 0) != 1:
            raise ApiError(NOT_FOUND, 404, "not_found")
        satisfied = 1 if (item or {}).get("satisfied") in (1, "1", True) else 0
        ot_sql.insert_check(conn, (new_id("OPC"), preop_id, item_id, satisfied, clean_text((item or {}).get("note"), 240)))
    require(ot_sql.set_preop_status(conn, ot_id, consent, readiness, at), "Record pre-operative details after the case is scheduled.", 409, "invalid_transition")
    _finish(conn, "preop", key, ot_id)
    audit(conn, user, "ot_preop", "ot", "ot", ot_id, new={"consent_status": consent, "readiness": readiness, "preop_id": preop_id})
    row = present(conn, user, ot_id)
    _emit("ot.updated", row)
    return row


def _ready(conn, case: dict) -> None:
    preop = ot_sql.latest_preop(conn, case["id"])
    if _flag(conn, "ot_require_consent"):
        require(preop and preop.get("consent_status") == "OBTAINED", "Consent is not recorded as obtained.", 409, "invalid_transition")
    if _flag(conn, "ot_require_readiness"):
        require(preop and preop.get("readiness") == "READY", "The patient is not marked ready.", 409, "invalid_transition")
    if not preop:
        missing = ot_sql.missing_required(conn, "")
    else:
        missing = ot_sql.missing_required(conn, preop["id"])
    require(not missing, "The pre-operative checklist is not complete.", 409, "invalid_transition")
    require(case.get("surgeon_id") or ot_sql.active_team(conn, case["id"], "surgeon"), "Assign a surgeon before starting.", 409, "invalid_transition")
    require(ot_sql.active_booking(conn, case["id"]), "This case has no active theatre booking.", 409, "invalid_transition")
    procedure = ot_sql.get_procedure(conn, case.get("procedure_id")) if case.get("procedure_id") else None
    if procedure and int(procedure.get("require_admission") or 0) == 1:
        owned = ot_sql.admission_owner(conn, case.get("admission_id") or "")
        require(owned and owned["patient_id"] == case["patient_id"] and owned["status"] in ("ADMITTED", "DISCHARGE_PENDING"), "The patient must be admitted before the procedure starts.", 409, "invalid_transition")


def start(conn, user, ot_id: str, payload: dict, fallback: str = "") -> dict:
    permit_any(user, ["ot.start", "ot.manage"], conn, "ot_start")
    key = clean_text((payload or {}).get("idempotency_key") or fallback, 80)
    digest = _hash({"ot_id": ot_id, "action": "start"})
    replay = _replay(conn, user, "start", key, digest)
    if replay is not None:
        return replay
    case = _own(conn, user, ot_sql.lock_case(conn, ot_id), ot_id)
    require(case["status"] == "PRE_OP", "Start is only allowed from the pre-operative step.", 409, "invalid_transition")
    _ready(conn, case)
    at = _stamp()
    require(ot_sql.mark_started(conn, ot_id, at, user["id"]), "Start is only allowed from the pre-operative step.", 409, "invalid_transition")
    ot_sql.set_booking_status(conn, ot_id, "IN_PROGRESS", at, ("SCHEDULED", "PRE_OP"))
    _finish(conn, "start", key, ot_id)
    audit(conn, user, "ot_start", "ot", "ot", ot_id, old={"status": "PRE_OP"}, new={"status": "IN_PROGRESS"})
    row = present(conn, user, ot_id)
    _emit("ot.started", row)
    return row


def record_intraop(conn, user, ot_id: str, payload: dict, fallback: str = "") -> dict:
    permit_any(user, ["ot.intraop.record", "ot.manage"], conn, "ot_intraop")
    notes = clean_text(payload.get("notes") or payload.get("procedure_notes"), 4000)
    require(notes, "Intra-operative notes are required.")
    key = clean_text(payload.get("idempotency_key") or fallback, 80)
    digest = _hash({"ot_id": ot_id, "notes": notes, "findings": payload.get("findings") or "", "at": payload.get("recorded_at") or ""})
    replay = _replay(conn, user, "intraop", key, digest)
    if replay is not None:
        return replay
    case = _own(conn, user, ot_sql.lock_case(conn, ot_id), ot_id)
    require(case["status"] in ("IN_PROGRESS", "RECOVERY", "COMPLETED"), "Intra-operative notes are recorded after the procedure starts.", 409, "invalid_transition")
    at = _stamp()
    record_id = new_id("OIR")
    ot_sql.insert_intraop(conn, (
        record_id, ot_id, notes, clean_text(payload.get("findings"), 4000),
        clean_text(payload.get("complications"), 2000), clean_text(payload.get("anesthesia"), 120), user["id"], at,
    ))
    _finish(conn, "intraop", key, ot_id)
    audit(conn, user, "ot_intraop", "ot", "ot", ot_id, new={"record_id": record_id})
    row = present(conn, user, ot_id)
    _emit("ot.updated", row)
    return row


def recover(conn, user, ot_id: str, payload: dict, fallback: str = "") -> dict:
    permit_any(user, ["ot.complete", "ot.manage"], conn, "ot_recovery")
    key = clean_text((payload or {}).get("idempotency_key") or fallback, 80)
    digest = _hash({"ot_id": ot_id, "action": "recovery"})
    replay = _replay(conn, user, "recovery", key, digest)
    if replay is not None:
        return replay
    case = _own(conn, user, ot_sql.lock_case(conn, ot_id), ot_id)
    if case["status"] == "RECOVERY":
        _finish(conn, "recovery", key, ot_id)
        return present(conn, user, ot_id)
    require(ot_sql.intraop_for(conn, ot_id), "Record the intra-operative note before recovery.", 409, "invalid_transition")
    require(ot_sql.mark_recovery(conn, ot_id, _stamp()), "Recovery follows the procedure, not an earlier step.", 409, "invalid_transition")
    _finish(conn, "recovery", key, ot_id)
    audit(conn, user, "ot_recovery", "ot", "ot", ot_id, old={"status": case["status"]}, new={"status": "RECOVERY"})
    row = present(conn, user, ot_id)
    _emit("ot.updated", row)
    return row


def complete(conn, user, ot_id: str, payload: dict, fallback: str = "") -> dict:
    permit_any(user, ["ot.complete", "ot.manage"], conn, "ot_complete")
    key = clean_text((payload or {}).get("idempotency_key") or fallback, 80)
    digest = _hash({"ot_id": ot_id, "action": "complete"})
    replay = _replay(conn, user, "complete", key, digest)
    if replay is not None:
        return replay
    case = _own(conn, user, ot_sql.lock_case(conn, ot_id), ot_id)
    if case["status"] == "COMPLETED" and case.get("completed_at"):
        _finish(conn, "complete", key, ot_id)
        row = present(conn, user, ot_id)
        row["idempotent_replay"] = True
        return row
    require(case["status"] == "RECOVERY", "Complete the case from recovery, not from an earlier step.", 409, "invalid_transition")
    require(ot_sql.intraop_for(conn, ot_id), "The operative record is missing.", 409, "invalid_transition")
    at = _stamp()
    require(ot_sql.mark_completed(conn, ot_id, at, user["id"]), "Complete the case from recovery, not from an earlier step.", 409, "invalid_transition")
    ot_sql.set_booking_status(conn, ot_id, "COMPLETED", at, ("IN_PROGRESS", "PRE_OP", "SCHEDULED"))
    _finish(conn, "complete", key, ot_id)
    audit(conn, user, "ot_complete", "ot", "ot", ot_id, old={"status": "RECOVERY"}, new={"status": "COMPLETED"})
    row = present(conn, user, ot_id)
    _emit("ot.completed", row)
    return row


def record_postop(conn, user, ot_id: str, payload: dict, fallback: str = "") -> dict:
    permit_any(user, ["ot.postop.record", "ot.manage"], conn, "ot_postop")
    notes = clean_text(payload.get("notes") or payload.get("post_op_instructions"), 4000)
    require(notes, "Post-operative notes are required.")
    key = clean_text(payload.get("idempotency_key") or fallback, 80)
    digest = _hash({"ot_id": ot_id, "notes": notes, "condition": payload.get("condition") or ""})
    replay = _replay(conn, user, "postop", key, digest)
    if replay is not None:
        return replay
    case = _own(conn, user, ot_sql.lock_case(conn, ot_id), ot_id)
    require(case["status"] in ("RECOVERY", "COMPLETED"), "Post-operative notes follow the procedure.", 409, "invalid_transition")
    at = _stamp()
    record_id = new_id("OOR")
    ot_sql.insert_postop(conn, (
        record_id, ot_id, notes, clean_text(payload.get("instructions"), 2000),
        clean_text(payload.get("condition"), 120), user["id"], at,
    ))
    _finish(conn, "postop", key, ot_id)
    audit(conn, user, "ot_postop", "ot", "ot", ot_id, new={"record_id": record_id})
    row = present(conn, user, ot_id)
    _emit("ot.updated", row)
    return row


def _procedure_price(conn, case: dict) -> int:
    if case.get("price_snapshot_paise") is not None:
        return int(case["price_snapshot_paise"])
    procedure = ot_sql.get_procedure(conn, case.get("procedure_id")) if case.get("procedure_id") else None
    if procedure and int(procedure.get("active") or 0) == 1:
        return int(procedure["price_paise"])
    configured = configured_procedure_fee(conn, case.get("procedure_id"))
    require(configured is not None, "This procedure has no configured price.", 409, "conflict")
    return int(configured)


def post_charge(conn, user, ot_id: str, payload: dict, fallback: str = "") -> dict:
    permit_any(user, ["ot.charge.post", "ot.manage"], conn, "ot_charge")
    purpose = "procedure"
    key = clean_text((payload or {}).get("idempotency_key") or fallback, 80)
    case = _own(conn, user, ot_sql.lock_case(conn, ot_id), ot_id)
    procedure_id = case.get("procedure_id") or ""
    require(procedure_id, "This case has no procedure to charge.")
    digest = _hash({"ot_id": ot_id, "procedure_id": procedure_id, "purpose": purpose})
    replay = _replay(conn, user, "charge", key, digest)
    if replay is not None:
        return replay
    require(case["status"] in ("IN_PROGRESS", "RECOVERY", "COMPLETED"), "Charge the procedure after it has started.", 409, "invalid_transition")
    existing = ot_sql.charge_link(conn, ot_id, procedure_id, purpose)
    if existing:
        _finish(conn, "charge", key, ot_id)
        row = present(conn, user, ot_id)
        row["invoice_item_id"] = existing["invoice_item_id"]
        row["price_paise"] = int(existing["price_paise"])
        row["idempotent_replay"] = True
        return row
    price = _procedure_price(conn, case)
    at = _stamp()
    ot_sql.set_snapshot(conn, ot_id, price, at)
    invoice = open_draft(
        conn, user, case["patient_id"], case.get("encounter_id"), case.get("admission_id"),
        "IPD" if case.get("admission_id") else "OT",
    )
    updated = add_item(conn, user, invoice["id"], {
        "description": case["procedure_name"],
        "category": "OT",
        "rate_paise": price,
        "qty": 1,
        "unit": "procedure",
        "source_module": "ot",
        "source_id": f"{ot_id}:{procedure_id}:{purpose}",
    })
    item_id = updated["added_item_id"]
    link_id = new_id("OCL")
    if not ot_sql.insert_charge_link(conn, (link_id, ot_id, procedure_id, purpose, item_id, price, at)):
        raise ApiError("This procedure has already been charged.", 409, "conflict")
    _finish(conn, "charge", key, ot_id)
    audit(conn, user, "ot_charge", "ot", "ot", ot_id, new={"invoice_item_id": item_id, "price_paise": price, "purpose": purpose})
    row = present(conn, user, ot_id)
    row["invoice_id"] = invoice["id"]
    row["invoice_item_id"] = item_id
    row["price_paise"] = price
    _emit("ot.updated", row)
    return row


def _fingerprint(conn, case: dict) -> str:
    payload = {
        "id": case["id"],
        "patient_id": case["patient_id"],
        "procedure_name": case.get("procedure_name"),
        "procedure_code": case.get("procedure_code"),
        "indication": case.get("indication"),
        "status": case.get("status"),
        "theatre_id": case.get("theatre_id"),
        "surgeon_id": case.get("surgeon_id"),
        "preop": ot_sql.preop_for(conn, case["id"]),
        "intraop": ot_sql.intraop_for(conn, case["id"]),
        "postop": ot_sql.postop_for(conn, case["id"]),
        "team": [(row["user_id"], row["function_code"], row.get("removed_at")) for row in ot_sql.team_for(conn, case["id"])],
        "booking": [(row["id"], row["theatre_id"], row["start_at"], row["end_at"], row["status"]) for row in ot_sql.bookings_for(conn, case["id"])],
    }
    return _hash(payload)


def generate_report(conn, user, ot_id: str, payload: dict | None = None, fallback: str = "") -> dict:
    permit_any(user, ["ot.report.generate", "ot.manage", "document.upload"], conn, "ot_report")
    key = clean_text((payload or {}).get("idempotency_key") or fallback, 80)
    digest = _hash({"ot_id": ot_id, "action": "report"})
    replay = _replay(conn, user, "report", key, digest)
    if replay is not None:
        return replay["report"] or replay
    case = _own(conn, user, ot_sql.lock_case(conn, ot_id), ot_id)
    require(case["status"] == "COMPLETED", "Complete the case before preparing the operation report.", 409, "invalid_transition")
    fingerprint = _fingerprint(conn, case)
    existing_id = case.get("report_document_id")
    if existing_id and case.get("report_fingerprint") == fingerprint:
        doc = documents_sql.q_wards_29086(conn, existing_id)
        if doc:
            _finish(conn, "report", key, ot_id)
            return doc
    from .pdf import render_ot_report
    from .storage import get_storage

    profile = hospital(conn)
    patient_name = name_of(conn, "patients", case["patient_id"])
    theatre = ot_sql.get_theatre(conn, case.get("theatre_id")) if case.get("theatre_id") else {}
    data = render_ot_report({
        "hospital_name": profile.get("name") or "Hospital",
        "hospital_address": ", ".join(x for x in [profile.get("address_line1"), profile.get("city")] if x),
        "case_id": ot_id,
        "patient_id": case["patient_id"],
        "patient_name": patient_name,
        "procedure_name": case.get("procedure_name") or "",
        "indication": case.get("indication") or "",
        "theatre": (theatre or {}).get("name") or "",
        "surgeon": doctor_label(conn, case.get("surgeon_id")),
        "scheduled_at": case.get("scheduled_at") or "",
        "started_at": case.get("started_at") or "",
        "completed_at": case.get("completed_at") or "",
        "preop": ot_sql.preop_for(conn, ot_id),
        "intraop": ot_sql.intraop_for(conn, ot_id),
        "postop": ot_sql.postop_for(conn, ot_id),
        "team": ot_sql.team_for(conn, ot_id),
    })
    doc_id = new_id("DOC")
    storage_key = f"{case['patient_id']}/{doc_id}.pdf"
    storage = get_storage()
    saved = storage.save(storage_key, data, "application/pdf")
    try:
        documents_sql.q_wards_28079(
            conn, doc_id, case["patient_id"], "ot", ot_id, "OT report",
            f"Operation report {ot_id}", f"{doc_id}.pdf", storage_key, "application/pdf",
            len(data), saved["checksum"], user["id"], _stamp(), "Generated from the stored operation record",
        )
    except Exception:
        if storage.exists(storage_key):
            storage.delete(storage_key)
        raise
    ot_sql.set_report(conn, ot_id, doc_id, fingerprint)
    action = "ot_report_correction" if existing_id else "ot_report"
    audit(conn, user, action, "ot", "ot", ot_id, new={"document_id": doc_id, "checksum": saved["checksum"]})
    _finish(conn, "report", key, ot_id)
    publish("document.updated", {"id": doc_id, "patient_id": case["patient_id"], "permission": "ot.view"})
    return documents_sql.q_wards_29086(conn, doc_id)


def report_file(conn, user, ot_id: str) -> tuple[dict, bytes]:
    permit_any(user, ["ot.view", "ot.report.generate", "document.view"], conn, "ot_report_read")
    case = ot_sql.q_wards_16351(conn, ot_id)
    if not case or not access.can_view_patient(conn, user, case.get("patient_id")):
        access.hide_record(conn, user, "ot", ot_id)
    doc_id = case.get("report_document_id")
    if not doc_id:
        raise ApiError(NOT_FOUND, 404, "not_found")
    doc, data = document_file(conn, doc_id)
    if doc.get("patient_id") != case["patient_id"]:
        access.hide_record(conn, user, "document", doc_id)
    safe = _safe_doc(doc) or {}
    return safe, data


def link_record(conn, user, ot_id: str, payload: dict, fallback: str = "") -> dict:
    permit_any(user, ["ot.request", "ot.manage", "ot.intraop.record"], conn, "ot_link")
    module = (clean_text(payload.get("module"), 20) or "").lower()
    entity_id = clean_text(payload.get("entity_id"), 40)
    require(module in ("lab", "pharmacy") and entity_id, "Name the laboratory order or prescription.")
    key = clean_text(payload.get("idempotency_key") or fallback, 80)
    digest = _hash({"ot_id": ot_id, "module": module, "entity_id": entity_id})
    replay = _replay(conn, user, "link", key, digest)
    if replay is not None:
        return replay
    case = _own(conn, user, ot_sql.lock_case(conn, ot_id), ot_id)
    if module == "lab":
        owned = ot_sql.lab_owner(conn, entity_id)
    else:
        owned = ot_sql.prescription_owner(conn, entity_id)
    if not owned or owned["patient_id"] != case["patient_id"]:
        raise ApiError(NOT_FOUND, 404, "not_found")
    at = _stamp()
    ot_sql.insert_link(conn, (new_id("OLK"), ot_id, module, entity_id, user["id"], at))
    _finish(conn, "link", key, ot_id)
    audit(conn, user, "ot_link", "ot", "ot", ot_id, new={"module": module, "entity_id": entity_id})
    row = present(conn, user, ot_id)
    _emit("ot.updated", row)
    return row
