"""Patients, OPD encounters, queues, consultations, and prescriptions."""

from __future__ import annotations

from aipf.repo import billing as billing_sql
from aipf.repo import documents as documents_sql
from aipf.repo import encounters as encounters_sql
from aipf.repo import ipd as ipd_sql
from aipf.repo import lab as lab_sql
from aipf.repo import masters as masters_sql
from aipf.repo import ot as ot_sql
from aipf.repo import patients as patients_sql
from aipf.repo import payments as payments_sql
from aipf.repo import users as users_sql

from datetime import timedelta

from .billing import add_item, open_draft
from .core import audit, doctor_label, master_list, name_of, next_number, permit, permit_any
from .db import one, rows
from .events import publish
from .util import (
    ApiError,
    clean_text,
    display_age,
    new_id,
    now,
    now_iso,
    phone_key,
    require,
    today_str,
)


QUEUE_STATUSES = [
    "WAITING",
    "CALLED",
    "IN_CONSULTATION",
    "WAITING_FOR_TEST",
    "WAITING_FOR_PHARMACY",
    "WAITING_FOR_BILL",
    "COMPLETED",
    "CANCELLED",
]

QUEUE_TRANSITIONS = {
    "WAITING": {"CALLED", "IN_CONSULTATION", "WAITING_FOR_PHARMACY", "CANCELLED"},
    "CALLED": {"WAITING", "IN_CONSULTATION", "WAITING_FOR_PHARMACY", "CANCELLED"},
    "IN_CONSULTATION": {"CALLED", "WAITING_FOR_TEST", "WAITING_FOR_PHARMACY", "WAITING_FOR_BILL", "COMPLETED", "CANCELLED"},
    "WAITING_FOR_TEST": {"IN_CONSULTATION", "COMPLETED", "CANCELLED"},
    "WAITING_FOR_PHARMACY": {"IN_CONSULTATION", "WAITING_FOR_BILL", "COMPLETED", "CANCELLED"},
    "WAITING_FOR_BILL": {"IN_CONSULTATION", "COMPLETED", "CANCELLED"},
    "COMPLETED": set(),
    "CANCELLED": set(),
}


def patient_search_text(p: dict) -> str:
    parts = [
        p.get("id"), p.get("hospital_no"), p.get("name"), p.get("guardian_name"),
        p.get("primary_phone"), p.get("alternate_phone"), p.get("guardian_phone"),
        p.get("address"), p.get("email"),
    ]
    return " ".join(str(x).lower() for x in parts if x)


def enrich_patient(conn, patient: dict) -> dict:
    if not patient:
        return patient
    patient["age_display"] = display_age(patient)
    patient["category_name"] = name_of(conn, "master_items", patient.get("category_id"))
    patient["department_name"] = name_of(conn, "master_items", patient.get("department_id"))
    return patient


def matches_by_phone(conn, phone: str) -> list[dict]:
    key = phone_key(phone)
    if len(key) < 6:
        return []
    found = patients_sql.q_clinical_1456(conn, key, key, key)
    return [enrich_patient(conn, p) for p in found]


def _confirmed_new(payload: dict) -> bool:
    return payload.get("confirm_new") is True or payload.get("confirm_new") == 1


def identity_matches(conn, payload: dict) -> list[dict]:
    found: dict[str, dict] = {}
    for key in ("primary_phone", "alternate_phone", "guardian_phone", "emergency_phone"):
        for patient in matches_by_phone(conn, payload.get(key) or ""):
            found[patient["id"]] = patient
    name = clean_text(payload.get("name"), 160).lower()
    dob = clean_text(payload.get("dob"), 10)
    if name and dob:
        for patient in patients_sql.match_name_dob(conn, name, dob):
            enriched = enrich_patient(conn, patient)
            found[enriched["id"]] = enriched
    return list(found.values())


def _match_summary(patient: dict) -> dict:
    return {
        "id": patient.get("id"),
        "name": patient.get("name"),
        "age_display": patient.get("age_display"),
        "gender": patient.get("gender"),
        "guardian_name": patient.get("guardian_name"),
        "primary_phone": patient.get("primary_phone"),
    }


def _registry_item(conn, row: dict) -> dict:
    item = enrich_patient(conn, dict(row))
    code = row.get("care_code") or "ACTIVE"
    item["care_code"] = code
    item["care_label"] = patients_sql.CARE_LABELS.get(code, code.replace("_", " ").title())
    return item


def search_patients(conn, q: str = "", limit: int = 40, user=None, page: int = 0, page_size: int = 0, sort: str = "registered", direction: str = "desc", department_id: str = "", gender: str = "", age: str = "", registered: str = "", status: str = "") -> dict:
    from .util import today_str
    q = (q or "").strip()
    permissions = set((user or {}).get("permissions") or [])
    scope = user["id"] if user is not None and "patient.view_all" not in permissions else None
    patient_status = status if status in ("ACTIVE", "INACTIVE") else ""
    care = status if status in ("WAITING", "IN_CONSULTATION", "ADMITTED", "EMERGENCY", "OPD", "DISCHARGED") else ""
    sort = sort if sort in ("registered", "name", "id", "encounter") else "registered"
    direction = "asc" if str(direction).lower() == "asc" else "desc"
    year = today_str()[:4]
    where, params = patients_sql.registry_where(q, phone_key(q), department_id, gender, age, registered, patient_status, care, scope, year)
    total = int((patients_sql.registry_count(conn, where, params) or {}).get("n") or 0)
    if page:
        size = min(max(int(page_size or 50), 1), 100)
        page_n = max(int(page), 1)
    else:
        size = min(max(int(limit or 40), 1), 100)
        page_n = 1
    offset = (page_n - 1) * size
    items = [_registry_item(conn, row) for row in patients_sql.registry_page(conn, where, params, sort, direction, size, offset)]
    summary = patients_sql.registry_summary(conn, today_str(), scope)
    if user is not None and "admission.view" not in permissions and "ipd.admission.view" not in permissions:
        summary.pop("inpatients", None)
        summary.pop("emergency", None)
    if user is not None and "opd.view" not in permissions and "queue.view" not in permissions:
        summary.pop("opd_today", None)
        summary.pop("waiting", None)
    beds = None
    if user is None or "bed.view" in permissions or "ipd.bed.view" in permissions:
        from aipf.repo.dashboard import hospital_beds
        hospital = hospital_beds(conn) or {}
        total_beds = int(hospital.get("total") or 0)
        occupied = int(hospital.get("occupied") or 0)
        beds = {
            "configured": total_beds > 0,
            "total": total_beds,
            "occupied": occupied,
            "available": int(hospital.get("available") or 0),
            "occupancy_pct": round(occupied * 100 / total_beds) if total_beds else None,
        }
    return {
        "items": items,
        "total": total,
        "page": page_n,
        "page_size": size,
        "sort": sort,
        "direction": direction,
        "summary": summary,
        "beds": beds,
    }


def patients_csv(conn, user, q: str = "", sort: str = "registered", direction: str = "desc", department_id: str = "", gender: str = "", age: str = "", registered: str = "", status: str = "") -> str:
    import csv
    import io
    found = search_patients(conn, q, 2000, user, page=1, page_size=100, sort=sort, direction=direction, department_id=department_id, gender=gender, age=age, registered=registered, status=status)
    pages = [found]
    while len(pages[-1]["items"]) == pages[-1]["page_size"] and sum(len(page["items"]) for page in pages) < found["total"] and sum(len(page["items"]) for page in pages) < 2000:
        pages.append(search_patients(conn, q, 100, user, page=len(pages) + 1, page_size=100, sort=sort, direction=direction, department_id=department_id, gender=gender, age=age, registered=registered, status=status))
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Patient ID", "Name", "Phone", "Guardian", "Age", "Gender", "Department", "Status", "Last encounter", "Last encounter at"])
    for page in pages:
        for item in page["items"]:
            writer.writerow([
                item.get("id"),
                item.get("name"),
                item.get("primary_phone") or "",
                item.get("guardian_name") or "",
                item.get("age_display") or "",
                item.get("gender") or "",
                item.get("department_name") or "",
                item.get("care_label") or "",
                item.get("last_encounter_id") or "",
                item.get("last_encounter_at") or "",
            ])
    return buffer.getvalue()


def import_patients(conn, user, payload: dict) -> dict:
    permit(user, "patient.create")
    incoming = payload.get("rows") if isinstance(payload.get("rows"), list) else []
    require(incoming, "No patient rows were provided.")
    require(len(incoming) <= 200, "Import at most 200 rows at a time.")
    created, skipped, errors = [], [], []
    for index, raw in enumerate(incoming, start=1):
        if not isinstance(raw, dict):
            errors.append({"row": index, "message": "That row was not a record."})
            continue
        body = {
            "name": raw.get("name"),
            "gender": raw.get("gender") or "",
            "primary_phone": raw.get("primary_phone") or raw.get("phone") or "",
            "alternate_phone": raw.get("alternate_phone") or "",
            "guardian_name": raw.get("guardian_name") or "",
            "guardian_phone": raw.get("guardian_phone") or "",
            "dob": raw.get("dob") or "",
            "age_at_registration": raw.get("age_at_registration") if raw.get("age_at_registration") not in ("", None) else raw.get("age"),
            "address": raw.get("address") or "",
            "department_id": raw.get("department_id") or None,
            "confirm_new": False,
        }
        try:
            saved = save_patient(conn, user, body)
            created.append({"row": index, "id": saved["id"], "name": saved["name"]})
        except ApiError as exc:
            if exc.code == "possible_match":
                skipped.append({"row": index, "name": clean_text(body.get("name"), 160), "message": exc.message, "matches": (exc.details or {}).get("matches") or []})
            else:
                errors.append({"row": index, "name": clean_text(body.get("name"), 160), "message": exc.message})
    return {"created": created, "skipped": skipped, "errors": errors}


def set_patients_status(conn, user, payload: dict) -> dict:
    permit(user, "patient.edit")
    status = clean_text(payload.get("status"), 20).upper()
    require(status in ("ACTIVE", "INACTIVE"), "Choose active or inactive. This does not delete the record.")
    ids = payload.get("ids") if isinstance(payload.get("ids"), list) else []
    require(ids, "Choose at least one patient.")
    require(len(ids) <= 100, "Update at most 100 patients at a time.")
    from .access import guard_patient
    updated = []
    for raw in ids:
        patient_id = clean_text(raw, 40)
        guard_patient(conn, user, patient_id)
        existing = patients_sql.q_clinical_15659(conn, patient_id)
        require(existing, "Patient not found.", 404, "not_found")
        if existing.get("status") != status:
            patients_sql.set_patient_status(conn, patient_id, status, now_iso())
            audit(conn, user, "patient_status", "patients", "patient", patient_id, old={"status": existing.get("status")}, new={"status": status})
            publish("patient.updated", {"id": patient_id, "patient_id": patient_id, "action": "status", "status": status})
        updated.append(patient_id)
    return {"updated": updated, "status": status}


def get_patient(conn, patient_id: str) -> dict:
    patient = patients_sql.q_clinical_2465(conn, patient_id, patient_id)
    require(patient, "Patient not found.", 404, "not_found")
    return enrich_patient(conn, patient)


def save_patient(conn, user, payload: dict, patient_id: str | None = None, sample: int = 0) -> dict:
    if patient_id:
        permit(user, "patient.edit")
    else:
        permit(user, "patient.create")
    name = clean_text(payload.get("name"), 160)
    require(name, "Patient name is required.")
    phone = phone_key(payload.get("primary_phone"))
    alt = phone_key(payload.get("alternate_phone"))
    gphone = phone_key(payload.get("guardian_phone"))
    gender = clean_text(payload.get("gender"), 20)
    dob = clean_text(payload.get("dob"), 10) or None
    age = payload.get("age_at_registration")
    if age in ("", None):
        age = None
    else:
        age = int(age)
        require(0 <= age <= 130, "Age looks wrong.")
    if not patient_id:
        # A shared phone is not an identity. A second person is allowed only
        # when the desk explicitly confirms this is not one of the matches.
        matches = identity_matches(conn, payload)
        if matches and not _confirmed_new(payload):
            raise ApiError(
                "This may be an existing patient. Choose that record, or confirm a new person.",
                409,
                "possible_match",
                {"matches": [_match_summary(item) for item in matches]},
            )
        patient_id = next_number(conn, "patient", "P", 6, yearly=False)
        row = {
            "id": patient_id,
            "hospital_no": clean_text(payload.get("hospital_no"), 40) or patient_id,
            "name": name,
            "guardian_name": clean_text(payload.get("guardian_name"), 160),
            "guardian_phone": gphone,
            "primary_phone": phone,
            "alternate_phone": alt,
            "gender": gender,
            "dob": dob,
            "age_at_registration": age,
            "age_unit": clean_text(payload.get("age_unit") or "Y", 4) or "Y",
            "age_is_estimated": 1 if payload.get("age_is_estimated") else 0,
            "address": clean_text(payload.get("address"), 400),
            "email": clean_text(payload.get("email"), 120),
            "category_id": payload.get("category_id") or None,
            "department_id": payload.get("department_id") or None,
            "emergency_name": clean_text(payload.get("emergency_name"), 160),
            "emergency_phone": phone_key(payload.get("emergency_phone")),
            "notes": clean_text(payload.get("notes"), 1000),
            "allergies": clean_text(payload.get("allergies"), 400),
            "is_sample": sample,
            "status": "ACTIVE",
            "created_by": (user or {}).get("id"),
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        row["search_text"] = patient_search_text(row)
        patients_sql.q_clinical_5090(conn, row)
        audit(conn, user, "patient_create", "patients", "patient", patient_id, new={"name": name, "phone": phone})
        publish("patient.updated", {"id": patient_id, "patient_id": patient_id, "action": "created"})
        return get_patient(conn, patient_id)
    existing = get_patient(conn, patient_id)
    updated = {
        "name": name,
        "hospital_no": clean_text(payload.get("hospital_no"), 40) or existing.get("hospital_no") or patient_id,
        "guardian_name": clean_text(payload.get("guardian_name"), 160),
        "guardian_phone": gphone,
        "primary_phone": phone,
        "alternate_phone": alt,
        "gender": gender,
        "dob": dob,
        "age_at_registration": age if age is not None else existing.get("age_at_registration"),
        "age_unit": clean_text(payload.get("age_unit") or existing.get("age_unit") or "Y", 4),
        "age_is_estimated": 1 if payload.get("age_is_estimated") else 0,
        "address": clean_text(payload.get("address"), 400),
        "email": clean_text(payload.get("email"), 120),
        "category_id": payload.get("category_id") or None,
        "department_id": payload.get("department_id") or None,
        "emergency_name": clean_text(payload.get("emergency_name"), 160),
        "emergency_phone": phone_key(payload.get("emergency_phone")),
        "notes": clean_text(payload.get("notes"), 1000),
        "allergies": clean_text(payload.get("allergies"), 400),
        "status": clean_text(payload.get("status") or existing.get("status") or "ACTIVE", 20),
        "updated_at": now_iso(),
        "id": patient_id,
    }
    updated["search_text"] = patient_search_text({**existing, **updated})
    patients_sql.q_clinical_7531(conn, updated)
    audit(conn, user, "patient_edit", "patients", "patient", patient_id, old={"name": existing["name"], "phone": existing.get("primary_phone")}, new={"name": name, "phone": phone})
    publish("patient.updated", {"id": patient_id, "patient_id": patient_id, "action": "edited"})
    return get_patient(conn, patient_id)


def delete_patient(conn, user, patient_id: str) -> dict:
    """Permanent patient deletion is intentionally unavailable once a record exists.

    Patient history is longitudinal and referenced by dispensing, billing, admissions,
    documents, and audit-related records. Deactivation is the safe lifecycle action.
    """
    permit(user, "patient.edit")
    patient = patients_sql.q_clinical_2465(conn, patient_id, patient_id)
    require(patient, "Patient not found.", 404, "not_found")
    raise ApiError(
        "Patients cannot be permanently deleted. Mark the patient inactive; clinical, dispensing, billing, admission, and document history stays linked to the Patient ID.",
        409,
        "history_preserved",
    )


def valid_opd_cards(conn, patient_id: str) -> list[dict]:
    found = encounters_sql.q_clinical_8579(conn, patient_id, now_iso())
    return found


def create_encounter(conn, user, payload: dict, sample: int = 0) -> dict:
    permit(user, "opd.create")
    patient = get_patient(conn, payload["patient_id"])
    opd_type = masters_sql.q_clinical_9137(conn, payload.get("opd_type_id"))
    require(opd_type, "Choose an active OPD type.")
    doctor_id = payload.get("doctor_id") or None
    if doctor_id:
        require(users_sql.q_clinical_9364(conn, doctor_id), "Doctor not found.")
    use_card = payload.get("use_opd_id")
    parent = None
    fee = int(opd_type["fee_paise"])
    waived = ""
    if use_card:
        parent = encounters_sql.q_clinical_9604(conn, use_card, patient["id"])
        require(parent, "The OPD card to reuse was not found.")
        require(parent.get("validity_until") and parent["validity_until"] >= now_iso(), "That OPD card has expired.")
        fee = 0
        waived = f"Covered by {parent['id']} until {parent['validity_until'][:16].replace('T', ' ')}"
    validity = (now() + timedelta(days=int(opd_type["validity_days"] or 1))).isoformat(timespec="seconds")
    # A waived follow-up keeps the original card's validity; it is not a new paid card.
    if parent:
        validity = parent["validity_until"]
    eid = next_number(conn, "opd", "OPD", 6, True)
    encounters_sql.q_clinical_10306(conn, eid, patient["id"], opd_type["id"], parent["id"] if parent else None, fee, waived, validity, doctor_id, payload.get("department_id") or patient.get("department_id"), clean_text(payload.get("chief_complaint"), 400), clean_text(payload.get("visit_kind") or "OPD", 20), now_iso(), user["id"], now_iso(), sample)
    invoice = open_draft(conn, user, patient["id"], eid, None, "OPD", sample)
    description = opd_type["name"]
    if parent:
        description = f"{opd_type['name']} — covered by {parent['id']}"
    add_item(
        conn,
        user,
        invoice["id"],
        {
            "description": description,
            "category": "CONSULTATION",
            "rate_paise": fee,
            "qty": 1,
            "unit": "visit",
            "source_module": "opd",
            "source_id": eid,
            "master_item_id": opd_type["id"],
        },
    )
    queue = None
    if payload.get("queue", True):
        queue = enqueue(conn, user, eid, doctor_id, payload.get("priority") or 0, payload.get("priority_label"))
    audit(conn, user, "opd_create", "opd", "encounter", eid, new={"patient_id": patient["id"], "doctor_id": doctor_id, "opd_type_id": opd_type["id"], "fee_paise": fee, "parent": parent["id"] if parent else None})
    publish("queue.updated", {"encounter_id": eid, "patient_id": patient["id"], "doctor_id": doctor_id})
    return get_encounter(conn, eid) | {"queue": queue, "invoice_id": invoice["id"]}


def register_visit(conn, user, payload: dict) -> dict:
    """Create the visit, and the patient when needed, in the caller's transaction."""
    permit(user, "opd.create")
    patient_id = payload.get("patient_id")
    if patient_id:
        patient = get_patient(conn, patient_id)
    else:
        permit(user, "patient.create")
        patient = save_patient(conn, user, payload.get("patient") or payload)
        patient_id = patient["id"]
    encounter = create_encounter(conn, user, {
        "patient_id": patient_id,
        "opd_type_id": payload.get("opd_type_id"),
        "doctor_id": payload.get("doctor_id"),
        "department_id": payload.get("department_id"),
        "chief_complaint": payload.get("chief_complaint"),
        "visit_kind": payload.get("visit_kind") or "OPD",
        "queue": payload.get("queue", True),
        "priority": payload.get("priority") or 0,
        "priority_label": payload.get("priority_label"),
        "use_opd_id": payload.get("use_opd_id"),
    })
    return {"patient": get_patient(conn, patient_id), "encounter": encounter}


def enqueue(conn, user, encounter_id: str, doctor_id: str | None, priority: int = 0, priority_label: str | None = None) -> dict:
    encounter = encounters_sql.q_clinical_12223(conn, encounter_id)
    require(encounter, "Encounter not found.", 404, "not_found")
    existing = encounters_sql.q_clinical_12369(conn, encounter_id)
    if existing:
        if doctor_id and doctor_id != existing.get("doctor_id"):
            encounters_sql.q_clinical_12586(conn, doctor_id, encounter.get("department_id"), existing["id"])
            encounters_sql.q_clinical_12740(conn, doctor_id, encounter_id)
            audit(conn, user, "queue_reassign", "opd", "queue", existing["id"], new={"doctor_id": doctor_id})
            publish("queue.updated", {"id": existing["id"], "patient_id": encounter["patient_id"], "doctor_id": doctor_id})
        return encounters_sql.q_clinical_13014(conn, existing["id"])
    day = today_str()
    token = encounters_sql.allocate_token(conn, day)
    qid = new_id("Q")
    encounters_sql.insert_queue_entry(conn, qid, token, day, encounter_id, encounter["patient_id"], doctor_id, encounter.get("department_id"), int(priority or 0), clean_text(priority_label, 40), encounter["arrived_at"], now_iso())
    if doctor_id:
        encounters_sql.q_clinical_13781(conn, doctor_id, encounter_id)
    audit(conn, user, "queue_create", "opd", "queue", qid, new={"token": token, "doctor_id": doctor_id})
    publish("queue.updated", {"id": qid, "encounter_id": encounter_id, "patient_id": encounter["patient_id"], "doctor_id": doctor_id})
    return encounters_sql.q_clinical_14057(conn, qid)


def set_queue_status(conn, user, queue_id: str, status: str) -> dict:
    permit(user, "queue.manage")
    require(status in QUEUE_STATUSES, "Unknown queue status.")
    entry = encounters_sql.q_clinical_14297(conn, queue_id)
    require(entry, "Queue entry not found.", 404, "not_found")
    if entry.get("doctor_id") and entry["doctor_id"] != user.get("id") and "queue.view_all" not in (user.get("permissions") or []):
        audit(conn, user, "queue_denied", "opd", "queue", queue_id, reason="Cannot change another doctor's queue")
        raise ApiError("You can only change your own queue.", 403, "forbidden")
    if status != entry["status"] and status not in QUEUE_TRANSITIONS.get(entry["status"], set()):
        raise ApiError("That queue status is not a valid next step.", 409, "invalid_transition")
    stamp = now_iso()
    called = entry.get("called_at")
    started = entry.get("started_at")
    completed = entry.get("completed_at")
    if status == "CALLED":
        called = stamp
    if status == "IN_CONSULTATION":
        started = started or stamp
        called = called or stamp
    if status in ("COMPLETED", "CANCELLED"):
        completed = stamp
    encounters_sql.q_clinical_14792(conn, status, called, started, completed, queue_id)
    if status == "COMPLETED":
        encounters_sql.q_clinical_15005(conn, stamp, entry["encounter_id"])
    if status == "CANCELLED":
        encounters_sql.q_clinical_15183(conn, entry["encounter_id"])
    audit(conn, user, "queue_status", "opd", "queue", queue_id, old={"status": entry["status"]}, new={"status": status})
    publish("queue.updated", {"id": queue_id, "status": status, "patient_id": entry.get("patient_id"), "doctor_id": entry.get("doctor_id")})
    return enrich_queue(conn, encounters_sql.q_clinical_15493(conn, queue_id))


def enrich_queue(conn, entry: dict) -> dict:
    if not entry:
        return entry
    patient = patients_sql.q_clinical_15659(conn, entry["patient_id"])
    entry["patient_name"] = patient["name"] if patient else ""
    entry["age_display"] = display_age(patient) if patient else ""
    entry["gender"] = patient.get("gender") if patient else ""
    entry["phone"] = patient.get("primary_phone") if patient else ""
    entry["category_name"] = name_of(conn, "master_items", patient.get("category_id")) if patient else ""
    entry["doctor_name"] = doctor_label(conn, entry.get("doctor_id"))
    entry["department_name"] = name_of(conn, "master_items", entry.get("department_id"))
    encounter = encounters_sql.q_clinical_16273(conn, entry["encounter_id"])
    entry["encounter"] = encounter
    if encounter and encounter.get("opd_type_id"):
        entry["opd_type_name"] = name_of(conn, "opd_types", encounter["opd_type_id"])
    entry["allowed_next"] = sorted(QUEUE_TRANSITIONS.get(entry.get("status"), set()))
    entry.pop("phone", None)
    return entry


def list_queue(conn, user, doctor_id: str = "", status: str = "", mine: bool = False) -> dict:
    permit(user, "queue.view")
    can_all = "queue.view_all" in user.get("permissions", [])
    target = doctor_id
    if mine or doctor_id == "me":
        target = user["id"]
    elif doctor_id and doctor_id != user.get("id") and not can_all:
        audit(conn, user, "queue_denied", "opd", "queue", doctor_id, reason="Attempted to open another doctor's queue")
        raise ApiError("You can only open your own queue.", 403, "forbidden")
    elif not can_all:
        target = user["id"]
    items = [enrich_queue(conn, e) for e in encounters_sql.list_queue(conn, status, target)]
    return {"items": items, "total": len(items)}


def get_encounter(conn, encounter_id: str) -> dict:
    encounter = encounters_sql.q_clinical_17771(conn, encounter_id)
    require(encounter, "Encounter not found.", 404, "not_found")
    patient = enrich_patient(conn, patients_sql.q_clinical_17937(conn, encounter["patient_id"]))
    encounter["patient"] = patient
    encounter["doctor_name"] = doctor_label(conn, encounter.get("doctor_id"))
    encounter["department_name"] = name_of(conn, "master_items", encounter.get("department_id"))
    encounter["opd_type_name"] = name_of(conn, "opd_types", encounter.get("opd_type_id"))
    encounter["queue"] = enrich_queue(conn, encounters_sql.q_clinical_18357(conn, encounter_id))
    encounter["consultation"] = encounters_sql.q_clinical_18502(conn, encounter_id)
    encounter["prescriptions"] = encounters_sql.q_clinical_18647(conn, encounter_id)
    for rx in encounter["prescriptions"]:
        rx["items"] = encounters_sql.q_clinical_18816(conn, rx["id"])
    encounter["invoices"] = billing_sql.q_clinical_18948(conn, encounter_id)
    encounter["lab_orders"] = lab_sql.q_clinical_19140(conn, encounter_id)
    encounter["ot_cases"] = ot_sql.q_clinical_19270(conn, encounter_id)
    encounter["admission"] = ipd_sql.q_clinical_19399(conn, encounter_id)
    return encounter


def save_consultation(conn, user, payload: dict) -> dict:
    permit(user, "consultation.create")
    encounter = encounters_sql.q_clinical_19669(conn, payload.get("encounter_id"))
    require(encounter, "Encounter not found.", 404, "not_found")
    owns = encounter.get("doctor_id") and encounter["doctor_id"] == user.get("id")
    if not owns and "consultation.manage_all" not in (user.get("permissions") or []):
        audit(conn, user, "record_denied", "clinical", "encounter", encounter["id"], reason="Consultation is outside the caller's scope")
        raise ApiError("You can only write a consultation on your own encounter.", 403, "forbidden")
    existing = encounters_sql.q_clinical_19830(conn, encounter["id"])
    fields = {
        "symptoms": clean_text(payload.get("symptoms"), 2000),
        "findings": clean_text(payload.get("findings"), 2000),
        "diagnosis": clean_text(payload.get("diagnosis"), 500),
        "notes": clean_text(payload.get("notes"), 4000),
        "instructions": clean_text(payload.get("instructions"), 2000),
        "follow_up": clean_text(payload.get("follow_up"), 400),
        "updated_at": now_iso(),
    }
    if existing:
        if (existing.get("diagnosis") or "") != (fields["diagnosis"] or ""):
            encounters_sql.insert_consultation_revision(conn, new_id("CR"), existing["id"], encounter["id"], existing.get("doctor_id") or user["id"], existing.get("diagnosis"), now_iso())
        encounters_sql.q_clinical_20373(conn, {**fields, "id": existing["id"]})
        cid = existing["id"]
        audit(conn, user, "consultation_update", "clinical", "consultation", cid, old={"diagnosis": existing.get("diagnosis")}, new={"diagnosis": fields["diagnosis"]})
    else:
        cid = new_id("CN")
        encounters_sql.q_clinical_20906(conn, cid, encounter["id"], encounter["patient_id"], user["id"], fields["symptoms"], fields["findings"], fields["diagnosis"], fields["notes"], fields["instructions"], fields["follow_up"], now_iso(), now_iso())
        audit(conn, user, "consultation_create", "clinical", "consultation", cid, new={"diagnosis": fields["diagnosis"]})
    queue = encounters_sql.q_clinical_21503(conn, encounter["id"])
    if queue and queue["status"] in ("WAITING", "CALLED"):
        set_queue_status(conn, user, queue["id"], "IN_CONSULTATION")
        queue = encounters_sql.q_clinical_21503(conn, encounter["id"])
    if payload.get("complete") and queue and queue["status"] != "COMPLETED":
        set_queue_status(conn, user, queue["id"], "COMPLETED")
        audit(conn, user, "consultation_complete", "clinical", "encounter", encounter["id"], new={"queue_id": queue["id"]})
    publish("clinical.updated", {"encounter_id": encounter["id"], "patient_id": encounter["patient_id"]})
    return encounters_sql.q_clinical_21835(conn, cid)


def save_prescription(conn, user, payload: dict, prescription_id: str | None = None) -> dict:
    permit(user, "prescription.create")
    if prescription_id:
        rx = encounters_sql.q_clinical_22068(conn, prescription_id)
        require(rx, "Prescription not found.", 404, "not_found")
        require(rx["status"] == "DRAFT", "A finalized prescription cannot be rewritten. Create a new one.")
        for field in ("patient_id", "encounter_id", "doctor_id"):
            sent = payload.get(field)
            if sent and str(sent) != str(rx.get(field) or ""):
                audit(conn, user, "record_denied", "clinical", "prescription", prescription_id, reason="Prescription ownership cannot be reassigned")
                raise ApiError("Prescription ownership cannot be reassigned.", 403, "forbidden")
        encounter_id = rx["encounter_id"]
    else:
        encounter_id = payload.get("encounter_id")
        rx = None
    encounter = encounters_sql.q_clinical_22450(conn, encounter_id)
    require(encounter, "Encounter not found.", 404, "not_found")
    if not rx:
        if payload.get("patient_id") and str(payload.get("patient_id")) != str(encounter["patient_id"]):
            audit(conn, user, "record_denied", "clinical", "encounter", encounter_id, reason="Prescription patient does not match the encounter")
            raise ApiError("Prescription ownership cannot be reassigned.", 403, "forbidden")
        if payload.get("doctor_id") and str(payload.get("doctor_id")) != str(user.get("id")) and "consultation.manage_all" not in (user.get("permissions") or []):
            audit(conn, user, "record_denied", "clinical", "encounter", encounter_id, reason="Prescription doctor does not match the caller")
            raise ApiError("Prescription ownership cannot be reassigned.", 403, "forbidden")
    if encounter.get("doctor_id") and encounter["doctor_id"] != user.get("id") and "consultation.manage_all" not in (user.get("permissions") or []):
        audit(conn, user, "record_denied", "clinical", "encounter", encounter_id, reason="Prescription is outside the caller's scope")
        raise ApiError("You can only prescribe on your own encounter.", 403, "forbidden")
    items = payload.get("items") or []
    require(items, "Add at least one medicine.")
    if not rx:
        prescription_id = next_number(conn, "rx", "RX", 6, True)
        consult = encounters_sql.q_clinical_22767(conn, encounter_id)
        encounters_sql.q_clinical_22888(conn, prescription_id, encounter_id, consult["id"] if consult else None, encounter["patient_id"], user["id"], clean_text(payload.get("notes"), 1000), now_iso(), now_iso())
    else:
        encounters_sql.q_clinical_23300(conn, clean_text(payload.get("notes"), 1000), now_iso(), prescription_id)
        encounters_sql.q_clinical_23452(conn, prescription_id)
    for index, item in enumerate(items):
        name = clean_text(item.get("medicine_name"), 160)
        require(name, "Each medicine needs a name.")
        encounters_sql.q_clinical_23703(conn, new_id("RI"), prescription_id, item.get("product_id") or None, name, clean_text(item.get("strength"), 60), clean_text(item.get("dose"), 40), clean_text(item.get("frequency"), 40), clean_text(item.get("route") or "Oral", 40), clean_text(item.get("duration"), 40), int(item.get("duration_days") or 0) or None, clean_text(item.get("timing"), 60), clean_text(item.get("food_instruction"), 80), float(item.get("quantity") or 0), clean_text(item.get("unit"), 40), clean_text(item.get("notes"), 240), index)
    audit(conn, user, "prescription_save", "clinical", "prescription", prescription_id, new={"items": len(items)})
    publish("clinical.updated", {"encounter_id": encounter_id, "patient_id": encounter["patient_id"], "prescription_id": prescription_id})
    return get_prescription(conn, prescription_id)


def get_prescription(conn, prescription_id: str) -> dict:
    rx = encounters_sql.q_clinical_24993(conn, prescription_id)
    require(rx, "Prescription not found.", 404, "not_found")
    rx["items"] = encounters_sql.q_clinical_25144(conn, prescription_id)
    rx["patient_name"] = name_of(conn, "patients", rx["patient_id"])
    rx["doctor_name"] = doctor_label(conn, rx.get("doctor_id"))
    patient = patients_sql.q_clinical_25402(conn, rx["patient_id"])
    rx["age_display"] = display_age(patient) if patient else ""
    rx["gender"] = patient.get("gender") if patient else ""
    return rx


def finalize_prescription(conn, user, prescription_id: str) -> dict:
    permit(user, "prescription.create")
    rx = get_prescription(conn, prescription_id)
    if rx.get("doctor_id") and rx["doctor_id"] != user.get("id") and "consultation.manage_all" not in (user.get("permissions") or []):
        audit(conn, user, "record_denied", "clinical", "prescription", prescription_id, reason="Finalize is outside the caller's scope")
        raise ApiError("You can only finalize your own prescription.", 403, "forbidden")
    require(rx["status"] == "DRAFT", "Prescription is already finalized.")
    require(rx["items"], "Nothing to finalize.")
    encounters_sql.q_clinical_25896(conn, now_iso(), now_iso(), prescription_id)
    queue = encounters_sql.q_clinical_26073(conn, rx["encounter_id"])
    if queue:
        set_queue_status(conn, user, queue["id"], "WAITING_FOR_PHARMACY")
    audit(conn, user, "prescription_finalize", "clinical", "prescription", prescription_id)
    publish("prescription.finalized", {"id": prescription_id, "encounter_id": rx["encounter_id"], "patient_id": rx["patient_id"]})
    stored = store_prescription_slip(conn, user, prescription_id)
    result = get_prescription(conn, prescription_id)
    result["document_id"] = stored.get("id")
    return result


def store_prescription_slip(conn, user, prescription_id: str) -> dict:
    """Save one prescription PDF. A reprint returns the stored document and does not write another."""
    existing = documents_sql.document_for_entity(conn, "prescription", prescription_id)
    if existing:
        return existing
    from .billing import prescription_document
    from .pdf import render_prescription_pdf
    from .storage import get_storage

    payload = prescription_document(conn, prescription_id)
    rx = payload["prescription"]
    require(rx.get("status") == "FINALIZED", "Finalize the prescription before saving the slip.", 409, "invalid_transition")
    data = render_prescription_pdf(payload)
    doc_id = new_id("DOC")
    key = f"{payload['patient_id']}/{doc_id}.pdf"
    storage = get_storage()
    saved = storage.save(key, data, "application/pdf")
    try:
        documents_sql.q_wards_28079(
            conn,
            doc_id,
            payload["patient_id"],
            "prescription",
            prescription_id,
            "PRESCRIPTION",
            f"Prescription {prescription_id}",
            payload["filename"],
            key,
            "application/pdf",
            len(data),
            saved["checksum"],
            (user or {}).get("id"),
            now_iso(),
            rx.get("encounter_id") or "",
        )
    except Exception:
        if storage.exists(key):
            storage.delete(key)
        raise
    audit(conn, user, "prescription_document", "documents", "document", doc_id, new={"prescription_id": prescription_id, "checksum": saved["checksum"]})
    publish("document.updated", {"id": doc_id, "patient_id": payload["patient_id"]})
    return documents_sql.q_wards_29086(conn, doc_id)


def prescription_download(conn, user, prescription_id: str) -> tuple[bytes, str]:
    rx = get_prescription(conn, prescription_id)
    existing = documents_sql.document_for_entity(conn, "prescription", prescription_id)
    if not existing and rx.get("status") == "FINALIZED":
        existing = store_prescription_slip(conn, user, prescription_id)
    if existing:
        from .wards import document_file

        doc, data = document_file(conn, existing["id"])
        return data, doc.get("filename") or existing.get("filename") or f"{prescription_id}.pdf"
    from .billing import prescription_document
    from .pdf import render_prescription_pdf

    payload = prescription_document(conn, prescription_id)
    return render_prescription_pdf(payload), payload["filename"]


def patient_timeline(conn, patient_id: str, user=None) -> dict:
    patient = get_patient(conn, patient_id)
    permissions = set((user or {}).get("permissions") or [])
    see_all = user is None
    def allowed(code: str) -> bool:
        return see_all or code in permissions
    events = []
    events.append({"at": patient["created_at"], "kind": "registration", "title": "Registered", "detail": patient["name"], "id": patient["id"]})
    encounters = encounters_sql.q_clinical_26838(conn, patient_id)
    consultations = []
    if allowed("opd.view") or allowed("consultation.view") or allowed("consultation.create") or see_all:
        for enc in encounters:
            doctor = doctor_label(conn, enc.get("doctor_id"))
            detail = enc.get("chief_complaint") or enc["status"]
            if doctor:
                detail = f"{doctor} · {detail}"
            events.append({"at": enc["arrived_at"], "kind": "opd", "title": f"OPD {enc['id']}", "detail": detail, "id": enc["id"], "status": enc["status"], "doctor": doctor})
    if allowed("consultation.view") or allowed("consultation.create"):
        for enc in encounters:
            note = encounters_sql.q_clinical_18502(conn, enc["id"])
            if not note:
                continue
            consultations.append({"id": note["id"], "encounter_id": enc["id"], "doctor_id": note.get("doctor_id"), "diagnosis": note.get("diagnosis"), "updated_at": note.get("updated_at")})
            events.append({"at": note.get("updated_at") or note.get("created_at"), "kind": "consultation", "title": "Consultation", "detail": note.get("diagnosis") or "Notes recorded", "id": note["id"], "encounter_id": enc["id"]})
    if allowed("prescription.view"):
        for rx in encounters_sql.q_clinical_27136(conn, patient_id):
            events.append({"at": rx.get("finalized_at") or rx["created_at"], "kind": "prescription", "title": f"Prescription {rx['id']}", "detail": rx["status"], "id": rx["id"], "status": rx["status"]})
    if allowed("lab.view") or allowed("lab.order.view") or allowed("lab.report.view"):
        for lab in lab_sql.q_clinical_27447(conn, patient_id):
            events.append({"at": lab["ordered_at"], "kind": "lab", "title": f"Lab {lab['id']}", "detail": lab["status"], "id": lab["id"], "status": lab["status"]})
        for sample in lab_sql.samples_for_patient(conn, patient_id):
            events.append({"at": sample.get("collected_at") or sample.get("rejected_at"), "kind": "lab_sample", "title": f"Sample {sample['accession_no']}", "detail": sample["status"], "id": sample["id"], "status": sample["status"]})
        for result in lab_sql.verified_for_patient(conn, patient_id):
            events.append({"at": result.get("verified_at"), "kind": "lab_result", "title": f"Result verified · {result.get('test_name') or result.get('custom_name') or 'Test'}", "detail": "Range flag is not a diagnosis", "id": result["id"], "status": "VERIFIED"})
        for report in lab_sql.reports_for_patient(conn, patient_id):
            events.append({"at": report.get("generated_at"), "kind": "lab_report", "title": f"Report {report['order_id']}", "detail": "Stored report", "id": report["id"]})
    if allowed("admission.view") or allowed("ipd.admission.view"):
        for adm in ipd_sql.q_clinical_27716(conn, patient_id):
            events.append({"at": adm.get("admitted_at") or adm["created_at"], "kind": "admission", "title": f"Admission {adm['id']}", "detail": adm["status"], "id": adm["id"], "status": adm["status"]})
            if adm.get("discharged_at"):
                events.append({"at": adm.get("discharged_at"), "kind": "discharge", "title": f"Discharged {adm['id']}", "detail": adm.get("discharge_condition") or "Discharged", "id": adm["id"], "status": "DISCHARGED"})
        for move in ipd_sql.movements_for_patient(conn, patient_id):
            events.append({"at": move.get("at"), "kind": "bed_movement", "title": "Bed movement", "detail": move.get("reason") or "Moved", "id": str(move.get("id")), "status": "RECORDED"})
    if allowed("ot.view"):
        for ot in ot_sql.q_clinical_28022(conn, patient_id):
            events.append({"at": ot.get("scheduled_at") or ot["created_at"], "kind": "ot", "title": f"OT {ot['procedure_name']}", "detail": ot.get("outcome") or ot["status"], "id": ot["id"], "status": ot["status"]})
            if ot.get("started_at"):
                events.append({"at": ot.get("started_at"), "kind": "ot_start", "title": f"Procedure started {ot['procedure_name']}", "detail": ot["status"], "id": ot["id"], "status": "IN_PROGRESS"})
            if ot.get("completed_at"):
                events.append({"at": ot.get("completed_at"), "kind": "ot_complete", "title": f"Procedure completed {ot['procedure_name']}", "detail": ot.get("outcome") or "COMPLETED", "id": ot["id"], "status": "COMPLETED"})
    if allowed("billing.view"):
        for inv in billing_sql.q_clinical_28341(conn, patient_id):
            events.append({"at": inv.get("finalized_at") or inv["created_at"], "kind": "bill", "title": inv["number"], "detail": f"{inv['status']} · {inv['payment_status']}", "id": inv["id"], "status": inv["payment_status"]})
    documents = documents_sql.q_clinical_28670(conn, patient_id) if allowed("document.view") or allowed("document.view_all") else []
    if user is not None and documents:
        from .access import can_read_document
        documents = [doc for doc in documents if can_read_document(conn, user, doc)]
    for doc in documents:
        events.append({"at": doc["uploaded_at"], "kind": "document", "title": doc.get("title") or doc["filename"], "detail": doc["document_type"], "id": doc["id"]})
    events.sort(key=lambda e: e.get("at") or "", reverse=True)
    from .util import today_str
    where, params = patients_sql.registry_where("", "", "", "", "", "", "", "", None, today_str()[:4], patient_id)
    current_rows = patients_sql.registry_page(conn, where, params, "registered", "desc", 1, 0)
    current = _registry_item(conn, current_rows[0]) if current_rows else None
    return {
        "patient": patient,
        "current": current,
        "events": events,
        "encounters": encounters if allowed("opd.view") or allowed("consultation.view") or allowed("consultation.create") or see_all else [],
        "consultations": consultations,
        "prescriptions": encounters_sql.q_clinical_29204(conn, patient_id) if allowed("prescription.view") else [],
        "labs": lab_sql.q_clinical_29322(conn, patient_id) if allowed("lab.view") else [],
        "admissions": ipd_sql.q_clinical_29443(conn, patient_id) if allowed("admission.view") or allowed("ipd.admission.view") else [],
        "ot": ot_sql.q_clinical_29556(conn, patient_id) if allowed("ot.view") else [],
        "invoices": billing_sql.q_clinical_29673(conn, patient_id) if allowed("billing.view") else [],
        "documents": documents,
        "deposits": payments_sql.q_clinical_30101(conn, patient_id) if allowed("billing.view") else [],
    }


def opd_types(conn, include_inactive: bool = False) -> list[dict]:
    if include_inactive:
        return masters_sql.q_clinical_30314(conn)
    return masters_sql.q_clinical_30389(conn)


def save_opd_type(conn, user, payload: dict, item_id: str | None = None) -> dict:
    permit(user, "master.manage")
    name = clean_text(payload.get("name"), 120)
    require(name, "Name is required.")
    fee = int(payload.get("fee_paise") or 0)
    days = int(payload.get("validity_days") or 1)
    require(days >= 0, "Validity cannot be negative.")
    if item_id:
        require(masters_sql.q_clinical_30855(conn, item_id), "OPD type not found.", 404, "not_found")
        masters_sql.q_clinical_30966(conn, name, clean_text(payload.get("code"), 20), fee, days, clean_text(payload.get("description"), 400), clean_text(payload.get("services_included"), 400), payload.get("departments") or "", 1 if payload.get("active", True) else 0, int(payload.get("sort_order") or 0), now_iso(), item_id)
    else:
        item_id = new_id("OTY")
        masters_sql.q_clinical_31536(conn, item_id, name, clean_text(payload.get("code"), 20), fee, days, clean_text(payload.get("description"), 400), clean_text(payload.get("services_included"), 400), payload.get("departments") or "", 1, int(payload.get("sort_order") or 0), now_iso(), now_iso())
    audit(conn, user, "opd_type_save", "admin", "opd_type", item_id, new={"name": name, "fee_paise": fee})
    return masters_sql.q_clinical_32167(conn, item_id)


def services(conn, include_inactive=False) -> list[dict]:
    if include_inactive:
        return masters_sql.q_clinical_32327(conn)
    return masters_sql.q_clinical_32411(conn)


def save_service(conn, user, payload: dict, item_id: str | None = None) -> dict:
    permit(user, "master.manage")
    name = clean_text(payload.get("name"), 160)
    require(name, "Name is required.")
    category = clean_text(payload.get("category") or "HOSPITAL SERVICES", 40)
    if item_id:
        require(masters_sql.q_clinical_32813(conn, item_id), "Service not found.", 404, "not_found")
        masters_sql.q_clinical_32922(conn, name, clean_text(payload.get("code"), 20), category, int(payload.get("rate_paise") or 0), clean_text(payload.get("unit"), 40), clean_text(payload.get("description"), 400), 1 if payload.get("active", True) else 0, int(payload.get("sort_order") or 0), item_id)
    else:
        item_id = new_id("SV")
        masters_sql.q_clinical_33406(conn, item_id, name, clean_text(payload.get("code"), 20), category, int(payload.get("rate_paise") or 0), clean_text(payload.get("unit"), 40), clean_text(payload.get("description"), 400), 1, int(payload.get("sort_order") or 0), now_iso())
    audit(conn, user, "service_save", "admin", "service", item_id, new={"name": name})
    return masters_sql.q_clinical_33947(conn, item_id)


def lab_tests(conn, include_inactive=False) -> list[dict]:
    if include_inactive:
        return lab_sql.q_clinical_34107(conn)
    return lab_sql.q_clinical_34192(conn)


def save_lab_test(conn, user, payload: dict, item_id: str | None = None) -> dict:
    permit_any(user, ["master.manage", "lab.test.manage"], conn, "lab_test_save")
    name = clean_text(payload.get("name"), 160)
    require(name, "Test name is required.")
    current = lab_sql.test_row(conn, item_id) if item_id else {}
    code = clean_text(payload.get("code"), 20).upper() if "code" in payload or not item_id else (current.get("code") or "")
    if code:
        taken = lab_sql.test_by_code(conn, code)
        if taken and taken["id"] != (item_id or ""):
            raise ApiError("That test code is already used.", 409, "duplicate_code")
    if item_id:
        require(current, "Test not found.", 404, "not_found")
        sample_type = clean_text(payload.get("sample_type"), 60) if "sample_type" in payload else (current.get("sample_type") or "")
        category = clean_text(payload.get("category"), 60) if "category" in payload else (current.get("category") or "")
        preparation = clean_text(payload.get("preparation"), 240) if "preparation" in payload else (current.get("preparation") or "")
        price = int(payload.get("price_paise") if "price_paise" in payload else current.get("price_paise") or 0)
        active = 1 if payload.get("active", True) else 0
        sort_order = int(payload.get("sort_order") if "sort_order" in payload else current.get("sort_order") or 0)
        tat = payload.get("tat_hours") if "tat_hours" in payload else current.get("tat_hours")
        lab_sql.q_clinical_34630(conn, code, name, category, price, sample_type, preparation, int(tat or 0) or None, active, sort_order, item_id)
    else:
        item_id = new_id("LT")
        try:
            lab_sql.q_clinical_35219(conn, item_id, code, name, clean_text(payload.get("category"), 60), int(payload.get("price_paise") or 0), clean_text(payload.get("sample_type"), 60), clean_text(payload.get("preparation"), 240), int(payload.get("tat_hours") or 0) or None, 1, int(payload.get("sort_order") or 0), now_iso())
        except Exception as exc:
            if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                raise ApiError("That test code is already used.", 409, "duplicate_code") from exc
            raise
    from .laboratory import apply_test_config
    apply_test_config(conn, item_id, payload)
    audit(conn, user, "lab_test_save", "admin", "lab_test", item_id, new={"name": name, "code": code})
    return lab_sql.q_clinical_35867(conn, item_id)


def delete_opd_type(conn, user, item_id: str) -> dict:
    permit(user, "master.manage")
    current = masters_sql.q_clinical_32167(conn, item_id)
    require(current, "OPD type not found.", 404, "not_found")
    audit(conn, user, "opd_type_delete", "admin", "opd_type", item_id, old={"name": current.get("name")})
    masters_sql.delete_opd_type(conn, item_id)
    return {"ok": True, "id": item_id}


def delete_service(conn, user, item_id: str) -> dict:
    permit(user, "master.manage")
    current = masters_sql.q_clinical_33947(conn, item_id)
    require(current, "Service not found.", 404, "not_found")
    audit(conn, user, "service_delete", "admin", "service", item_id, old={"name": current.get("name")})
    masters_sql.delete_service(conn, item_id)
    return {"ok": True, "id": item_id}


def delete_lab_test(conn, user, item_id: str) -> dict:
    permit_any(user, ["master.manage", "lab.test.manage"], conn, "lab_test_delete")
    current = lab_sql.test_row(conn, item_id)
    require(current, "Test not found.", 404, "not_found")
    require(masters_sql.lab_test_in_use(conn, item_id) == 0, "This test is on a laboratory order. Deactivate it instead of erasing it.", 409, "conflict")
    audit(conn, user, "lab_test_delete", "admin", "lab_test", item_id, old={"name": current.get("name")})
    masters_sql.delete_lab_test(conn, item_id)
    return {"ok": True, "id": item_id}


def doctors(conn) -> list[dict]:
    return users_sql.q_clinical_35973(conn)
