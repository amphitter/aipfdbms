"""Record-level authorization.

Permissions decide which action is allowed. These rules decide which record
that action may touch. Role names are not consulted.

Patient read (`patient.view`):
- `patient.view_all` may read every patient. Reception, pharmacy, billing,
  nursing, laboratory, and the administrator role receive this permission.
- Otherwise the patient must be clinically linked to the caller: encounter
  doctor, queue doctor, admission doctor, operating surgeon, or prescribing
  doctor. A missing or out-of-scope patient is reported as not found.

Document read (`document.view`):
- `document.view_all` may open any document. Reception and the administrator
  role receive it, because registration files identity documents.
- Otherwise the caller may open a document they uploaded, or a document whose
  patient is clinically linked to them. `patient.view_all` does not open files.
  Out-of-scope documents are reported as not found.

Queue:
- Without `queue.view_all`, a caller may only read or change queue entries
  assigned to their own user id. A cross-doctor request is forbidden.

Clinical write:
- Without `consultation.manage_all`, a consultation or prescription can be
  written only on an encounter assigned to the caller.

Lists and search apply the same patient rule. Financial dashboard figures are
omitted unless the caller has `billing.view` or `report.view`.
"""

from __future__ import annotations

from aipf.repo import access as access_sql

from .core import audit
from .util import ApiError


def can_view_patient(conn, user, patient_id: str | None) -> bool:
    if not user or not patient_id:
        return False
    if "patient.view_all" in (user.get("permissions") or []):
        return True
    return bool(access_sql.clinical_link(conn, user["id"], patient_id))


def can_read_document(conn, user, doc: dict | None) -> bool:
    if not user or not doc:
        return False
    permissions = user.get("permissions") or []
    if "document.view" not in permissions and "document.view_all" not in permissions:
        return False
    if "document.view_all" in permissions:
        return True
    if doc.get("uploaded_by") == user.get("id"):
        return True
    return bool(access_sql.clinical_link(conn, user["id"], doc.get("patient_id")))


def hide_record(conn, user, entity: str, entity_id: str | None) -> None:
    audit(conn, user, "record_denied", "auth", entity, entity_id, reason="Outside the caller's record scope")
    raise ApiError("That record was not found.", 404, "not_found")


def guard_patient(conn, user, patient_id: str | None) -> None:
    if not can_view_patient(conn, user, patient_id):
        hide_record(conn, user, "patient", patient_id)


def filter_by_patient(conn, user, items: list[dict], key: str = "patient_id") -> list[dict]:
    if not user or "patient.view_all" in (user.get("permissions") or []):
        return items
    return [item for item in items if can_view_patient(conn, user, item.get(key))]


def filter_documents(conn, user, items: list[dict]) -> list[dict]:
    return [item for item in items if can_read_document(conn, user, item)]
