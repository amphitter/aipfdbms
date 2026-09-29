"""Identity, configuration, numbering, audit, and shared reads."""

from __future__ import annotations

from aipf.repo import audit as audit_sql
from aipf.repo import masters as masters_sql
from aipf.repo import sessions as sessions_sql
from aipf.repo import users as users_sql

import hashlib
import json
from datetime import timedelta

from .db import one, rows
from .events import publish
from .util import (
    ApiError,
    clean_text,
    hash_password,
    mask_secret,
    new_id,
    now,
    now_iso,
    phone_key,
    require,
    token as new_token,
    verify_password,
    year_now,
)

SESSION_HOURS = 16

PERMISSIONS = [
    ("patient.view", "patients", "View patients in scope"),
    ("patient.view_all", "patients", "View every patient record"),
    ("patient.create", "patients", "Register patients"),
    ("patient.edit", "patients", "Edit patients"),
    ("opd.view", "opd", "View OPD"),
    ("opd.create", "opd", "Create OPD encounters"),
    ("opd.assign", "opd", "Assign doctors and queue"),
    ("queue.view", "opd", "View own queue"),
    ("queue.view_all", "opd", "View every doctor queue"),
    ("queue.manage", "opd", "Change queue status"),
    ("consultation.view", "clinical", "View consultations"),
    ("consultation.create", "clinical", "Write consultations"),
    ("consultation.manage_all", "clinical", "Write a consultation on another doctor's encounter"),
    ("prescription.view", "clinical", "View prescriptions"),
    ("prescription.create", "clinical", "Write prescriptions"),
    ("pharmacy.view", "pharmacy", "View pharmacy queue"),
    ("pharmacy.dispense", "pharmacy", "Dispense medicines"),
    ("inventory.view", "pharmacy", "View stock"),
    ("inventory.adjust", "pharmacy", "Adjust stock"),
    ("inventory.edit", "pharmacy", "Edit products and batches"),
    ("lab.view", "lab", "View lab orders"),
    ("lab.order", "lab", "Order tests"),
    ("lab.result", "lab", "Enter results"),
    ("lab.test.view", "lab", "View the laboratory test catalogue"),
    ("lab.test.manage", "lab", "Create and deactivate laboratory tests"),
    ("lab.order.create", "lab", "Create a laboratory order"),
    ("lab.order.view", "lab", "View laboratory orders in scope"),
    ("lab.order.cancel", "lab", "Cancel a laboratory order without deleting it"),
    ("lab.sample.collect", "lab", "Collect a laboratory sample"),
    ("lab.sample.reject", "lab", "Reject a laboratory sample"),
    ("lab.sample.process", "lab", "Receive and process a laboratory sample"),
    ("lab.result.enter", "lab", "Enter a laboratory result"),
    ("lab.result.verify", "lab", "Verify a laboratory result"),
    ("lab.result.correct", "lab", "Correct a verified laboratory result"),
    ("lab.report.view", "lab", "View a laboratory report in scope"),
    ("lab.report.generate", "lab", "Generate a laboratory report from stored results"),
    ("billing.view", "billing", "View bills"),
    ("billing.create", "billing", "Create and edit draft bills"),
    ("billing.medicine_issue", "billing", "Issue a medicine onto a draft bill and deduct stock"),
    ("billing.edit", "billing", "Edit a draft bill"),
    ("billing.finalize", "billing", "Finalize bills"),
    ("billing.void", "billing", "Void a bill"),
    ("billing.refund", "billing", "Refund and void"),
    ("billing.print", "billing", "Print bills"),
    ("billing.report", "billing", "View billing reports"),
    ("payment.create", "billing", "Record a payment"),
    ("payment.view", "billing", "View payments"),
    ("payment.refund", "billing", "Refund a payment"),
    ("deposit.create", "billing", "Receive a deposit"),
    ("deposit.allocate", "billing", "Allocate a deposit to a bill"),
    ("financial_adjustment.create", "billing", "Propose a financial adjustment"),
    ("financial_adjustment.approve", "billing", "Approve a financial adjustment"),
    ("admission.view", "ipd", "View admissions"),
    ("admission.manage", "ipd", "Admit, transfer, discharge"),
    ("ipd.admission.create", "ipd", "Create an admission"),
    ("ipd.admission.view", "ipd", "View an admission in scope"),
    ("ipd.admission.manage", "ipd", "Post an inpatient charge"),
    ("ipd.bed.view", "ipd", "View bed availability"),
    ("ipd.bed.assign", "ipd", "Assign a bed"),
    ("ipd.bed.move", "ipd", "Move a patient to another bed"),
    ("ipd.bed.release", "ipd", "Release a bed"),
    ("ipd.discharge.finalize", "ipd", "Finalize a discharge"),
    ("ipd.discharge.document", "ipd", "Generate a discharge summary"),
    ("bed.view", "ipd", "View beds"),
    ("bed.manage", "ipd", "Change bed status"),
    ("ot.view", "ot", "View OT cases"),
    ("ot.manage", "ot", "Manage OT cases and notes"),
    ("ot.theatre.manage", "ot", "Manage theatres"),
    ("ot.procedure.manage", "ot", "Manage operative procedures"),
    ("ot.request", "ot", "Request surgery"),
    ("ot.approve", "ot", "Approve an OT request"),
    ("ot.schedule", "ot", "Schedule and reschedule OT"),
    ("ot.team.manage", "ot", "Assign the operative team"),
    ("ot.preop.record", "ot", "Record pre-operative assessment"),
    ("ot.start", "ot", "Start a procedure"),
    ("ot.intraop.record", "ot", "Record intra-operative notes"),
    ("ot.complete", "ot", "Complete an OT case"),
    ("ot.postop.record", "ot", "Record post-operative notes"),
    ("ot.cancel", "ot", "Cancel or postpone OT"),
    ("ot.report.generate", "ot", "Generate an operation report"),
    ("ot.charge.post", "ot", "Post an OT charge"),
    ("document.view", "documents", "View documents in scope"),
    ("document.view_all", "documents", "Open any patient document"),
    ("document.upload", "documents", "Upload documents"),
    ("document.deactivate", "documents", "Deactivate documents"),
    ("report.view", "reports", "View reports"),
    ("report.export", "reports", "Export reports"),
    ("user.manage", "admin", "Manage staff"),
    ("role.manage", "admin", "Manage roles"),
    ("master.manage", "admin", "Manage master data"),
    ("backup.view", "admin", "View backups"),
    ("backup.create", "admin", "Create backups"),
    ("backup.restore", "admin", "Restore backups"),
    ("health.view", "admin", "View system health"),
    ("whatsapp.configure", "admin", "Configure WhatsApp"),
    ("whatsapp.send", "admin", "Send WhatsApp"),
    ("leads.view", "admin", "View website leads"),
    ("leads.manage", "admin", "Manage website leads"),
    ("audit.view", "admin", "View audit log"),
    ("config.manage", "admin", "Manage hospital configuration"),
]

ROLE_MATRIX = {
    "admin": [code for code, _, _ in PERMISSIONS],
    "doctor": [
        "patient.view", "opd.view", "queue.view", "queue.manage",
        "consultation.view", "consultation.create", "prescription.view", "prescription.create",
        "lab.view", "lab.order", "lab.order.create", "lab.order.view", "lab.order.cancel",
        "lab.test.view", "lab.report.view",
        "ot.view", "ot.manage", "ot.request", "ot.approve", "ot.schedule", "ot.team.manage",
        "ot.preop.record", "ot.start", "ot.intraop.record", "ot.complete", "ot.postop.record",
        "ot.cancel", "ot.report.generate", "ot.charge.post",
        "admission.view", "admission.manage",
        "ipd.admission.create", "ipd.admission.view", "ipd.bed.view", "ipd.discharge.finalize", "ipd.discharge.document",
        "document.view", "document.upload", "billing.view",
    ],
    "reception": [
        "patient.view", "patient.view_all", "patient.create", "patient.edit", "opd.view", "opd.create", "opd.assign",
        "queue.view", "queue.view_all", "queue.manage", "billing.view", "billing.create", "billing.medicine_issue", "billing.finalize", "billing.print",
        "whatsapp.send",
        "payment.create", "payment.view", "deposit.create",
        "document.view", "document.view_all", "document.upload", "leads.view", "leads.manage", "admission.view", "bed.view",
        "ipd.admission.view", "ipd.bed.view",
    ],
    "pharmacist": [
        "patient.view", "patient.view_all", "prescription.view", "pharmacy.view", "pharmacy.dispense",
        "inventory.view", "inventory.edit", "billing.view", "document.view",
    ],
    "billing": [
        "patient.view", "patient.view_all", "billing.view", "billing.create", "billing.medicine_issue", "billing.edit", "billing.finalize",
        "billing.void", "billing.refund", "billing.print", "billing.report", "report.view", "document.view", "admission.view",
        "ipd.admission.view",
        "payment.create", "payment.view", "payment.refund", "deposit.create", "deposit.allocate",
        "financial_adjustment.create", "financial_adjustment.approve", "whatsapp.send",
    ],
    "nurse": [
        "patient.view", "patient.view_all", "admission.view", "admission.manage", "bed.view", "bed.manage",
        "ipd.admission.view", "ipd.admission.manage", "ipd.bed.view", "ipd.bed.assign", "ipd.bed.move", "ipd.bed.release",
        "ipd.discharge.document",
        "document.view", "document.upload", "ot.view", "ot.preop.record", "ot.postop.record", "queue.view",
    ],
    "lab": [
        "patient.view", "patient.view_all", "lab.view", "lab.result", "lab.result.enter",
        "lab.test.view", "lab.order.view", "lab.order.cancel",
        "lab.sample.collect", "lab.sample.reject", "lab.sample.process",
        "lab.report.view", "lab.report.generate",
        "document.view", "document.upload", "billing.view",
    ],
}


def audit(conn, user, action, module, entity=None, entity_id=None, old=None, new=None, reason=None):
    audit_sql.q_core_4644(conn, now_iso(), (user or {}).get("id"), (user or {}).get("username"), action, module, entity, entity_id, json.dumps(old, default=str) if old is not None else None, json.dumps(new, default=str) if new is not None else None, reason, (user or {}).get("workstation"), (user or {}).get("ip"))


def log(conn, level, module, message, user=None, entity=None, entity_id=None, extra=None):
    audit_sql.q_core_5402(conn, now_iso(), level, module, message[:1000], (user or {}).get("id") if user else None, entity, entity_id, json.dumps(extra, default=str) if extra else None)


def token_digest(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def permit(user, permission: str | None, conn=None, action: str | None = None):
    if not permission:
        return
    if not user:
        raise ApiError("Sign in required.", 401, "unauthorized")
    if permission not in (user.get("permissions") or []):
        if conn is not None:
            audit(conn, user, "authz_denied", "auth", "permission", permission, reason=action or permission)
        raise ApiError("You do not have permission for this action.", 403, "forbidden")


def permit_any(user, permissions: list[str], conn=None, action: str | None = None):
    if not user:
        raise ApiError("Sign in required.", 401, "unauthorized")
    held = set(user.get("permissions") or [])
    if any(code in held for code in permissions):
        return
    if conn is not None:
        audit(conn, user, "authz_denied", "auth", "permission", ",".join(permissions), reason=action or "forbidden")
    raise ApiError("You do not have permission for this action.", 403, "forbidden")


def next_number(conn, name: str, prefix: str, width: int = 6, yearly: bool = True) -> str:
    year = year_now() if yearly else 0
    n = masters_sql.allocate_sequence(conn, name, year)
    if yearly:
        return f"{prefix}-{year}-{n:0{width}d}"
    return f"{prefix}-{n:0{width}d}"


def config_get(conn, key: str, default: str = "") -> str:
    row = masters_sql.q_core_6946(conn, key)
    return row["value"] if row else default


def config_set(conn, key: str, value: str, user=None, secret: bool = False):
    masters_sql.q_core_7135(conn, key, value, 1 if secret else 0, now_iso(), (user or {}).get("id"))


def config_map(conn, include_secrets: bool = False) -> dict:
    data = {}
    for row in masters_sql.q_core_7609(conn):
        if row["is_secret"] and not include_secrets:
            data[row["key"]] = mask_secret(row["value"])
            data[row["key"] + "__set"] = bool(row["value"])
        else:
            data[row["key"]] = row["value"]
    return data


def hospital(conn) -> dict:
    row = masters_sql.q_core_7966(conn)
    return row or {}


def public_branding(conn) -> dict:
    h = hospital(conn)
    return {
        "name": h.get("name"),
        "legal_name": h.get("legal_name"),
        "tagline": h.get("tagline"),
        "address_line1": h.get("address_line1"),
        "address_line2": h.get("address_line2"),
        "city": h.get("city"),
        "state": h.get("state"),
        "pin": h.get("pin"),
        "phone": h.get("phone"),
        "email": h.get("email"),
        "website": h.get("website"),
        "registration_no": h.get("registration_no"),
        "has_logo": bool(h.get("logo_path")),
    }


def load_user(conn, user_id: str) -> dict | None:
    user = users_sql.q_core_8688(conn, user_id)
    if not user or not user["active"]:
        return None
    roles = [r["role"] for r in users_sql.q_core_8835(conn, user_id)]
    perms = {
        r["permission"]
        for r in users_sql.q_core_8961(conn, user_id)
    }
    user.pop("password_hash", None)
    user["roles"] = roles
    user["permissions"] = sorted(perms)
    return user


def user_by_username(conn, username: str) -> dict | None:
    return users_sql.q_core_9377(conn, username.strip())


def login(conn, username: str, password: str, workstation: str = "", ip: str = "", user_agent: str = "") -> dict:
    require(username and password, "Username and password are required.")
    row = user_by_username(conn, username)
    if not row or not row["active"] or not verify_password(password, row["password_hash"]):
        audit(conn, {"username": username, "ip": ip, "workstation": workstation}, "login_failed", "auth", "user", username)
        raise ApiError("Those credentials were not accepted.", 401, "unauthorized")
    session = new_token()
    expires = (now() + timedelta(hours=SESSION_HOURS)).isoformat(timespec="seconds")
    sessions_sql.q_core_10110(conn, token_digest(session), row["id"], clean_text(workstation, 80), ip, clean_text(user_agent, 200), now_iso(), expires)
    users_sql.touch_login(conn, now_iso(), row["id"])
    user = load_user(conn, row["id"])
    user["workstation"] = workstation
    user["ip"] = ip
    audit(conn, user, "login", "auth", "session", token_digest(session)[:12])
    log(conn, "info", "auth", f"{user['username']} signed in", user)
    return {"token": session, "expires_at": expires, "user": user}


def stream_ticket(conn, user) -> dict:
    raw = new_token()
    expires = (now() + timedelta(seconds=90)).isoformat(timespec="seconds")
    sessions_sql.q_core_10110(
        conn,
        token_digest(raw),
        user["id"],
        "event-stream",
        user.get("ip") or "",
        "",
        now_iso(),
        expires,
    )
    return {"token": raw, "expires_at": expires}


def staff_directory(conn, user) -> list[dict]:
    permit_any(user, ["ot.team.manage", "ot.manage", "ot.view", "user.manage"], conn, "staff_directory")
    return users_sql.list_directory(conn)


def logout(conn, user, token_value: str):
    if token_value:
        digest = token_digest(token_value)
        sessions_sql.q_core_10748(conn, now_iso(), digest)
        sessions_sql.revoke_stream_tickets(conn, now_iso(), user["id"])
        audit(conn, user, "logout", "auth", "session", digest[:12])


def session_user(conn, token_value: str, workstation: str = "", ip: str = "") -> dict | None:
    if not token_value:
        return None
    digest = token_digest(token_value)
    row = users_sql.q_core_11063(conn, digest)
    if not row or not row["active"]:
        return None
    if row["expires_at"] < now_iso():
        return None
    # Slide the session while the desk is in use.
    expires = (now() + timedelta(hours=SESSION_HOURS)).isoformat(timespec="seconds")
    sessions_sql.q_core_11503(conn, expires, digest)
    user = load_user(conn, row["user_id"])
    if not user:
        return None
    user["workstation"] = workstation or row.get("workstation") or ""
    user["ip"] = ip or row.get("ip") or ""
    user["token"] = token_value
    return user


def change_password(conn, user, current: str, new_password: str):
    row = users_sql.q_core_11909(conn, user["id"])
    require(row and verify_password(current, row["password_hash"]), "Current password is not correct.", 400, "unauthorized")
    require(len(new_password or "") >= 8, "Use at least 8 characters.")
    users_sql.q_core_12181(conn, hash_password(new_password), now_iso(), user["id"])
    audit(conn, user, "password_change", "auth", "user", user["id"])


def list_users(conn) -> list[dict]:
    people = users_sql.q_core_12476(conn)
    for person in people:
        person["roles"] = [r["role"] for r in users_sql.q_core_12700(conn, person["id"])]
    return people


def save_user(conn, actor, payload: dict, user_id: str | None = None) -> dict:
    permit(actor, "user.manage")
    username = clean_text(payload.get("username"), 40).lower()
    full_name = clean_text(payload.get("full_name"), 120)
    require(username and full_name, "Username and full name are required.")
    roles = payload.get("roles") or []
    require(roles, "Choose at least one role.")
    known = {r["code"] for r in users_sql.q_core_13224(conn)}
    for role in roles:
        require(role in known, f"Unknown role {role}.")
    if user_id:
        existing = users_sql.q_core_13391(conn, user_id)
        require(existing, "Staff member not found.", 404, "not_found")
        clash = users_sql.q_core_13534(conn, username, user_id)
        require(not clash, "That username is already in use.")
        active = 1 if payload.get("active", existing.get("active")) else 0
        title = clean_text(payload.get("title"), 40) if "title" in payload else existing.get("title")
        specialty = clean_text(payload.get("specialty"), 80) if "specialty" in payload else existing.get("specialty")
        department_id = payload.get("department_id") if "department_id" in payload else existing.get("department_id")
        phone = phone_key(payload.get("phone")) if "phone" in payload else existing.get("phone")
        admin_doctor = 1 if payload.get("is_admin_doctor") else 0 if "is_admin_doctor" in payload else existing.get("is_admin_doctor") or 0
        users_sql.q_core_13694(conn, username, full_name, title, specialty, department_id or None, phone or None, active, admin_doctor, now_iso(), user_id)
        if payload.get("password"):
            require(len(payload["password"]) >= 8, "Use at least 8 characters.")
            users_sql.q_core_14418(conn, hash_password(payload["password"]), user_id)
            audit(conn, actor, "password_reset", "auth", "user", user_id)
        if existing.get("active") and not active:
            sessions_sql.revoke_user_sessions(conn, now_iso(), user_id)
            audit(conn, actor, "user_disable", "admin", "user", user_id, old={"active": 1}, new={"active": 0})
        users_sql.q_core_14533(conn, user_id)
        for role in roles:
            users_sql.q_core_14639(conn, user_id, role)
        audit(conn, actor, "user_update", "admin", "user", user_id, new={"username": username, "roles": roles, "active": active})
        publish("staff.updated", {"id": user_id})
        return load_user(conn, user_id)
    require(payload.get("password") and len(payload["password"]) >= 8, "Set an initial password of at least 8 characters.")
    require(not user_by_username(conn, username), "That username is already in use.")
    uid = new_id("U")
    users_sql.q_core_15161(conn, uid, username, full_name, hash_password(payload["password"]), clean_text(payload.get("title"), 40), clean_text(payload.get("specialty"), 80), payload.get("department_id") or None, phone_key(payload.get("phone")) or None, 1, 1 if payload.get("is_admin_doctor") else 0, now_iso())
    for role in roles:
        users_sql.q_core_15752(conn, uid, role)
    audit(conn, actor, "user_create", "admin", "user", uid, new={"username": username, "roles": roles})
    return load_user(conn, uid)


def list_roles(conn) -> list[dict]:
    result = users_sql.q_core_16019(conn)
    for role in result:
        role["permissions"] = [r["permission"] for r in users_sql.q_core_16159(conn, role["code"])]
    return result


def set_role_permissions(conn, actor, code: str, permissions: list[str]):
    permit(actor, "role.manage")
    role = users_sql.q_core_16402(conn, code)
    require(role, "Role not found.", 404, "not_found")
    known = {p[0] for p in PERMISSIONS}
    clean = [p for p in permissions if p in known]
    old = [r["permission"] for r in users_sql.q_core_16639(conn, code)]
    users_sql.q_core_16720(conn, code)
    for perm in clean:
        users_sql.q_core_16818(conn, code, perm)
    audit(conn, actor, "role_permissions", "admin", "role", code, old={"permissions": old}, new={"permissions": clean})
    return list_roles(conn)


def master_list(conn, list_type: str, include_inactive: bool = False) -> list[dict]:
    if include_inactive:
        return masters_sql.q_core_17183(conn, list_type)
    return masters_sql.q_core_17293(conn, list_type)


def save_master(conn, actor, list_type: str, payload: dict, item_id: str | None = None) -> dict:
    permit(actor, "master.manage")
    name = clean_text(payload.get("name"), 120)
    require(name, "Name is required.")
    if item_id:
        existing = masters_sql.q_core_17661(conn, item_id, list_type)
        require(existing, "Master item not found.", 404, "not_found")
        masters_sql.q_core_17828(conn, name, clean_text(payload.get("code"), 40), clean_text(payload.get("description"), 400), payload.get("meta") if isinstance(payload.get("meta"), str) else json.dumps(payload.get("meta") or {}), int(payload.get("sort_order") or 0), 1 if payload.get("active", True) else 0, now_iso(), item_id)
        audit(conn, actor, "master_update", "admin", list_type, item_id, old=existing, new=payload)
        publish("master.updated", {"type": list_type, "id": item_id})
        return masters_sql.q_core_18549(conn, item_id)
    item_id = new_id("M")
    masters_sql.q_core_18642(conn, item_id, list_type, name, clean_text(payload.get("code"), 40), clean_text(payload.get("description"), 400), payload.get("meta") if isinstance(payload.get("meta"), str) else json.dumps(payload.get("meta") or {}), int(payload.get("sort_order") or 0), 1 if payload.get("active", True) else 0, now_iso())
    audit(conn, actor, "master_create", "admin", list_type, item_id, new={"name": name})
    publish("master.updated", {"type": list_type, "id": item_id})
    return masters_sql.q_core_19342(conn, item_id)


def delete_user(conn, actor, user_id: str) -> dict:
    permit(actor, "user.manage")
    require(actor.get("id") != user_id, "You cannot delete the account you are signed in with.", 409, "conflict")
    existing = users_sql.q_core_13391(conn, user_id)
    require(existing, "Staff member not found.", 404, "not_found")
    if users_sql.has_role(conn, user_id, "admin") and users_sql.other_admins(conn, user_id) == 0:
        require(False, "The last admin account cannot be deleted.", 409, "conflict")
    blocked = users_sql.blocking_user_links(conn, user_id)
    require(not blocked, "This person is still named on " + ", ".join(blocked) + ". Those records stay. Disable the account instead of erasing it.", 409, "conflict")
    audit(conn, actor, "user_delete", "admin", "user", user_id, old={"username": existing.get("username"), "full_name": existing.get("full_name")})
    users_sql.detach_user(conn, user_id)
    sessions_sql.revoke_user_sessions(conn, now_iso(), user_id)
    publish("staff.updated", {"id": user_id, "action": "deleted"})
    return {"ok": True, "id": user_id}


def delete_master_item(conn, actor, list_type: str, item_id: str) -> dict:
    permit(actor, "master.manage")
    existing = masters_sql.q_core_19531(conn, item_id, list_type)
    require(existing, "Master item not found.", 404, "not_found")
    audit(conn, actor, "master_delete", "admin", list_type, item_id, old={"name": existing.get("name")})
    masters_sql.detach_master_item(conn, item_id)
    masters_sql.delete_master_item(conn, list_type, item_id)
    publish("master.updated", {"type": list_type, "id": item_id, "action": "deleted"})
    return {"ok": True, "id": item_id}


def deactivate_master(conn, actor, list_type: str, item_id: str) -> dict:
    permit(actor, "master.manage")
    existing = masters_sql.q_core_19531(conn, item_id, list_type)
    require(existing, "Master item not found.", 404, "not_found")
    masters_sql.q_core_19690(conn, now_iso(), item_id)
    audit(conn, actor, "master_deactivate", "admin", list_type, item_id, old={"active": existing["active"]}, new={"active": 0})
    return masters_sql.q_core_19925(conn, item_id)


def name_of(conn, table: str, item_id: str | None, field: str = "name") -> str:
    if not item_id:
        return ""
    if table == "users":
        row = users_sql.q_core_20147(conn, item_id)
        if not row:
            return ""
        return " ".join(x for x in [row.get("title"), row.get("full_name")] if x)
    row = masters_sql.lookup_name(conn, table, item_id, field)
    return row["name"] if row else ""


def doctor_label(conn, user_id: str | None) -> str:
    return name_of(conn, "users", user_id)
