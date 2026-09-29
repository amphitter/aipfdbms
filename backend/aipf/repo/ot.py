"""SQL owned by the repository. Domain modules call these functions."""
from __future__ import annotations

from aipf.repo.sqlio import count_where, exec_if, execute, has_column, has_table, one, rows

_ACTIVE = "('SCHEDULED', 'PRE_OP', 'IN_PROGRESS')"


def q_clinical_19270(conn, p0):
    return rows(conn, "SELECT * FROM ot_cases WHERE encounter_id=? ORDER BY created_at DESC", (p0,))


def q_clinical_28022(conn, p0):
    return rows(conn, "SELECT * FROM ot_cases WHERE patient_id=? ORDER BY created_at", (p0,))


def q_clinical_29556(conn, p0):
    return rows(conn, "SELECT * FROM ot_cases WHERE patient_id=? ORDER BY created_at DESC", (p0,))


def q_wards_15355(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11, p12):
    return execute(conn, """INSERT INTO ot_cases(id, patient_id, encounter_id, admission_id, procedure_name, procedure_id, surgeon_id, assistants,
           anesthesia, status, scheduled_at, requested_by, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,'REQUESTED',?,?,?,?)""", (p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11, p12))


def q_wards_16351(conn, p0):
    return one(conn, "SELECT * FROM ot_cases WHERE id=?", (p0,))


def q_wards_16703(conn, p0):
    return rows(conn, "SELECT * FROM ot_cases WHERE status=? ORDER BY COALESCE(scheduled_at, created_at) DESC", (p0,))


def q_wards_16841(conn):
    return rows(conn, "SELECT * FROM ot_cases ORDER BY created_at DESC LIMIT 100", ())


def q_wards_17483(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8, p9):
    return execute(conn, """UPDATE ot_cases SET status=?, scheduled_at=?, started_at=?, ended_at=?, assistants=?, ot_staff=?, anesthesia=?,
           surgeon_id=?, updated_at=? WHERE id=?""", (p0, p1, p2, p3, p4, p5, p6, p7, p8, p9))


def q_wards_18509(conn, p0):
    return execute(conn, "UPDATE ot_cases SET status='NOTES_PENDING' WHERE id=? AND (outcome IS NULL OR outcome='')", (p0,))


def q_wards_19594(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11):
    return execute(conn, """UPDATE ot_cases SET pre_op_notes=?, procedure_notes=?, findings=?, complications=?, post_op_instructions=?,
           outcome=?, notes_by=?, notes_at=?, status='COMPLETED', anesthesia=COALESCE(?, anesthesia), assistants=COALESCE(?, assistants),
           updated_at=? WHERE id=?""", (p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11))


def q_system_36789(conn, p0):
    return one(conn, "SELECT COUNT(*) AS n FROM ot_cases WHERE substr(COALESCE(scheduled_at, created_at),1,10)=? AND status!='CANCELLED'", (p0,))


def q_seed_29119(conn, p0, p1):
    return execute(conn, """INSERT INTO ot_cases(id, patient_id, encounter_id, admission_id, procedure_name, surgeon_id, status, requested_by, created_at, updated_at)
           VALUES ('OT-2026-000001','P-000005','OPD-2026-000007','ADM-2026-000001','Closed reduction — left wrist','U-IMRAN','REQUESTED','U-IMRAN',?,?)""", (p0, p1))


def _lock(sql: str, conn) -> str:
    if getattr(conn, "dialect", "") == "postgres":
        return sql + " FOR UPDATE"
    return sql


def _unique(exc: Exception) -> bool:
    text = str(exc).lower()
    return "unique" in text or "duplicate" in text


def patient_owner(conn, patient_id: str):
    return one(conn, "SELECT id FROM patients WHERE id=?", (patient_id,))


def encounter_owner(conn, encounter_id: str):
    return one(conn, "SELECT id, patient_id FROM encounters WHERE id=?", (encounter_id,))


def admission_owner(conn, admission_id: str):
    return one(conn, "SELECT id, patient_id, encounter_id, status FROM admissions WHERE id=?", (admission_id,))


def lab_owner(conn, order_id: str):
    return one(conn, "SELECT id, patient_id FROM lab_orders WHERE id=?", (order_id,))


def prescription_owner(conn, prescription_id: str):
    return one(conn, "SELECT id, patient_id FROM prescriptions WHERE id=?", (prescription_id,))


def lock_case(conn, ot_id: str):
    return one(conn, _lock("SELECT * FROM ot_cases WHERE id=?", conn), (ot_id,))


def lock_theatre(conn, theatre_id: str):
    return one(conn, _lock("SELECT * FROM ot_theatres WHERE id=?", conn), (theatre_id,))


def lock_user(conn, user_id: str):
    return one(conn, _lock("SELECT id, active FROM users WHERE id=?", conn), (user_id,))


def theatre_by_code(conn, code: str):
    return one(conn, "SELECT id FROM ot_theatres WHERE lower(code)=lower(?)", (code,))


def insert_theatre(conn, params: tuple) -> bool:
    conn.execute("SAVEPOINT ot_master")
    try:
        execute(
            conn,
            """INSERT INTO ot_theatres(id, code, name, location, active, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?)""",
            params,
        )
        conn.execute("RELEASE SAVEPOINT ot_master")
        return True
    except Exception as exc:
        conn.execute("ROLLBACK TO SAVEPOINT ot_master")
        if _unique(exc):
            return False
        raise


def update_theatre(conn, theatre_id: str, code: str, name: str, location: str, active: int, updated_at: str):
    return execute(
        conn,
        "UPDATE ot_theatres SET code=?, name=?, location=?, active=?, updated_at=? WHERE id=?",
        (code, name, location, active, updated_at, theatre_id),
    )


def list_theatres(conn, include_inactive: bool = False):
    if include_inactive:
        return rows(conn, "SELECT * FROM ot_theatres ORDER BY name", ())
    return rows(conn, "SELECT * FROM ot_theatres WHERE active=1 ORDER BY name", ())


def get_theatre(conn, theatre_id: str):
    return one(conn, "SELECT * FROM ot_theatres WHERE id=?", (theatre_id,))


def procedure_by_code(conn, code: str):
    return one(conn, "SELECT id FROM ot_procedures WHERE lower(code)=lower(?)", (code,))


def get_procedure(conn, procedure_id: str):
    return one(conn, "SELECT * FROM ot_procedures WHERE id=?", (procedure_id,))


def insert_procedure(conn, params: tuple) -> bool:
    conn.execute("SAVEPOINT ot_master")
    try:
        execute(
            conn,
            """INSERT INTO ot_procedures(id, code, name, department_id, category, price_paise, duration_minutes,
                   require_admission, active, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            params,
        )
        conn.execute("RELEASE SAVEPOINT ot_master")
        return True
    except Exception as exc:
        conn.execute("ROLLBACK TO SAVEPOINT ot_master")
        if _unique(exc):
            return False
        raise


def update_procedure(conn, params: tuple):
    return execute(
        conn,
        """UPDATE ot_procedures SET code=?, name=?, department_id=?, category=?, price_paise=?, duration_minutes=?,
               require_admission=?, active=?, updated_at=? WHERE id=?""",
        params,
    )


def list_procedures(conn, include_inactive: bool = False):
    if include_inactive:
        return rows(conn, "SELECT * FROM ot_procedures ORDER BY name", ())
    return rows(conn, "SELECT * FROM ot_procedures WHERE active=1 ORDER BY name", ())


def checklist_by_code(conn, code: str):
    return one(conn, "SELECT id FROM ot_checklist_items WHERE lower(code)=lower(?)", (code,))


def insert_checklist(conn, params: tuple) -> bool:
    conn.execute("SAVEPOINT ot_master")
    try:
        execute(
            conn,
            """INSERT INTO ot_checklist_items(id, code, label, required, active, sort_order)
               VALUES (?,?,?,?,?,?)""",
            params,
        )
        conn.execute("RELEASE SAVEPOINT ot_master")
        return True
    except Exception as exc:
        conn.execute("ROLLBACK TO SAVEPOINT ot_master")
        if _unique(exc):
            return False
        raise


def update_checklist(conn, label: str, required: int, active: int, sort_order: int, item_id: str):
    return execute(
        conn,
        "UPDATE ot_checklist_items SET label=?, required=?, active=?, sort_order=? WHERE id=?",
        (label, required, active, sort_order, item_id),
    )


def list_checklist(conn, include_inactive: bool = False):
    if include_inactive:
        return rows(conn, "SELECT * FROM ot_checklist_items ORDER BY sort_order, label", ())
    return rows(conn, "SELECT * FROM ot_checklist_items WHERE active=1 ORDER BY sort_order, label", ())


def get_checklist(conn, item_id: str):
    return one(conn, "SELECT * FROM ot_checklist_items WHERE id=?", (item_id,))


def insert_request(conn, params: tuple):
    return execute(
        conn,
        """INSERT INTO ot_cases(id, patient_id, encounter_id, admission_id, procedure_name, procedure_id, procedure_code,
               surgeon_id, priority, indication, status, consent_status, readiness, requested_by, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,'REQUESTED','PENDING','PENDING',?,?,?)""",
        params,
    )


def mark_approved(conn, ot_id: str, at: str, by: str) -> bool:
    cur = execute(
        conn,
        """UPDATE ot_cases SET status='APPROVED', approved_at=?, approved_by=?, updated_at=?
           WHERE id=? AND status='REQUESTED'""",
        (at, by, at, ot_id),
    )
    return cur.rowcount == 1


def move_schedule(conn, ot_id: str, theatre_id: str, surgeon_id: str, start_at: str, at: str) -> bool:
    cur = execute(
        conn,
        """UPDATE ot_cases SET theatre_id=?, surgeon_id=?, scheduled_at=?, updated_at=?,
               status=CASE WHEN status='POSTPONED' THEN 'SCHEDULED' ELSE status END
           WHERE id=? AND status IN ('SCHEDULED', 'PRE_OP', 'POSTPONED')""",
        (theatre_id, surgeon_id, start_at, at, ot_id),
    )
    return cur.rowcount == 1


def set_booking_surgeon(conn, booking_id: str, surgeon_id: str, at: str):
    return execute(conn, "UPDATE ot_bookings SET surgeon_id=?, updated_at=? WHERE id=?", (surgeon_id, at, booking_id))


def set_scheduled(conn, ot_id: str, theatre_id: str, surgeon_id: str, start_at: str, at: str) -> bool:
    cur = execute(
        conn,
        """UPDATE ot_cases SET status='SCHEDULED', theatre_id=?, surgeon_id=?, scheduled_at=?, updated_at=?
           WHERE id=? AND status IN ('APPROVED', 'POSTPONED', 'SCHEDULED')""",
        (theatre_id, surgeon_id, start_at, at, ot_id),
    )
    return cur.rowcount == 1


def set_preop_status(conn, ot_id: str, consent: str, readiness: str, at: str) -> bool:
    cur = execute(
        conn,
        """UPDATE ot_cases SET status='PRE_OP', consent_status=?, readiness=?, updated_at=?
           WHERE id=? AND status IN ('SCHEDULED', 'PRE_OP')""",
        (consent, readiness, at, ot_id),
    )
    return cur.rowcount == 1


def mark_started(conn, ot_id: str, at: str, by: str) -> bool:
    cur = execute(
        conn,
        """UPDATE ot_cases SET status='IN_PROGRESS', started_at=?, started_by=?, updated_at=?
           WHERE id=? AND status='PRE_OP'""",
        (at, by, at, ot_id),
    )
    return cur.rowcount == 1


def mark_recovery(conn, ot_id: str, at: str) -> bool:
    cur = execute(
        conn,
        "UPDATE ot_cases SET status='RECOVERY', updated_at=? WHERE id=? AND status='IN_PROGRESS'",
        (at, ot_id),
    )
    return cur.rowcount == 1


def mark_completed(conn, ot_id: str, at: str, by: str) -> bool:
    cur = execute(
        conn,
        """UPDATE ot_cases SET status='COMPLETED', completed_at=?, completed_by=?, ended_at=?, updated_at=?
           WHERE id=? AND status='RECOVERY'""",
        (at, by, at, at, ot_id),
    )
    return cur.rowcount == 1


def mark_cancelled(conn, ot_id: str, at: str, by: str, reason: str) -> bool:
    cur = execute(
        conn,
        """UPDATE ot_cases SET status='CANCELLED', cancelled_at=?, cancelled_by=?, cancel_reason=?, updated_at=?
           WHERE id=? AND status NOT IN ('COMPLETED', 'CANCELLED')""",
        (at, by, reason, at, ot_id),
    )
    return cur.rowcount == 1


def mark_postponed(conn, ot_id: str, at: str, reason: str) -> bool:
    cur = execute(
        conn,
        """UPDATE ot_cases SET status='POSTPONED', postponed_at=?, postpone_reason=?, updated_at=?
           WHERE id=? AND status IN ('APPROVED', 'SCHEDULED', 'PRE_OP')""",
        (at, reason, at, ot_id),
    )
    return cur.rowcount == 1


def set_snapshot(conn, ot_id: str, price: int, at: str):
    return execute(
        conn,
        "UPDATE ot_cases SET price_snapshot_paise=?, updated_at=? WHERE id=? AND price_snapshot_paise IS NULL",
        (price, at, ot_id),
    )


def set_report(conn, ot_id: str, document_id: str, fingerprint: str):
    return execute(
        conn,
        "UPDATE ot_cases SET report_document_id=?, report_fingerprint=? WHERE id=?",
        (document_id, fingerprint, ot_id),
    )


def set_surgeon(conn, ot_id: str, surgeon_id: str, at: str):
    return execute(conn, "UPDATE ot_cases SET surgeon_id=?, updated_at=? WHERE id=?", (surgeon_id, at, ot_id))


def active_booking(conn, ot_id: str):
    return one(
        conn,
        f"SELECT * FROM ot_bookings WHERE ot_id=? AND status IN {_ACTIVE} ORDER BY created_at DESC LIMIT 1",
        (ot_id,),
    )


def bookings_for(conn, ot_id: str):
    return rows(conn, "SELECT * FROM ot_bookings WHERE ot_id=? ORDER BY created_at", (ot_id,))


def theatre_overlap(conn, theatre_id: str, start_at: str, end_at: str, ignore_id: str):
    return one(
        conn,
        f"""SELECT id FROM ot_bookings
            WHERE theatre_id=? AND status IN {_ACTIVE} AND id<>?
              AND start_at < ? AND end_at > ?
            LIMIT 1""",
        (theatre_id, ignore_id or "", end_at, start_at),
    )


def surgeon_overlap(conn, surgeon_id: str, start_at: str, end_at: str, ignore_id: str):
    return one(
        conn,
        f"""SELECT id FROM ot_bookings
            WHERE surgeon_id=? AND status IN {_ACTIVE} AND id<>?
              AND start_at < ? AND end_at > ?
            LIMIT 1""",
        (surgeon_id, ignore_id or "", end_at, start_at),
    )


def team_overlap(conn, user_id: str, function_code: str, start_at: str, end_at: str, ignore_booking: str):
    return one(
        conn,
        f"""SELECT b.id FROM ot_bookings b
            JOIN ot_team_members t ON t.ot_id=b.ot_id AND t.removed_at IS NULL
            WHERE t.user_id=? AND t.function_code=? AND b.status IN {_ACTIVE} AND b.id<>?
              AND b.start_at < ? AND b.end_at > ?
            LIMIT 1""",
        (user_id, function_code, ignore_booking or "", end_at, start_at),
    )


def insert_booking(conn, params: tuple) -> bool:
    conn.execute("SAVEPOINT ot_book")
    try:
        execute(
            conn,
            """INSERT INTO ot_bookings(id, ot_id, theatre_id, surgeon_id, start_at, end_at, status, created_by, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            params,
        )
        conn.execute("RELEASE SAVEPOINT ot_book")
        return True
    except Exception as exc:
        conn.execute("ROLLBACK TO SAVEPOINT ot_book")
        if _unique(exc):
            return False
        raise


def update_booking(conn, booking_id: str, theatre_id: str, surgeon_id: str, start_at: str, end_at: str, at: str) -> bool:
    cur = execute(
        conn,
        """UPDATE ot_bookings SET theatre_id=?, surgeon_id=?, start_at=?, end_at=?, status='SCHEDULED', updated_at=?
           WHERE id=? AND status IN ('SCHEDULED', 'PRE_OP', 'POSTPONED')""",
        (theatre_id, surgeon_id, start_at, end_at, at, booking_id),
    )
    return cur.rowcount == 1


def set_booking_status(conn, ot_id: str, status: str, at: str, only: tuple[str, ...] | None = None) -> int:
    if only:
        marks = ",".join("?" for _ in only)
        cur = execute(
            conn,
            f"UPDATE ot_bookings SET status=?, updated_at=? WHERE ot_id=? AND status IN ({marks})",
            (status, at, ot_id, *only),
        )
    else:
        cur = execute(
            conn,
            "UPDATE ot_bookings SET status=?, updated_at=? WHERE ot_id=? AND status NOT IN ('CANCELLED', 'COMPLETED')",
            (status, at, ot_id),
        )
    return cur.rowcount


def insert_history(conn, params: tuple):
    return execute(
        conn,
        """INSERT INTO ot_booking_history(id, booking_id, ot_id, action, theatre_id, surgeon_id, start_at, end_at, reason, actor_id, at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        params,
    )


def history_for(conn, ot_id: str):
    return rows(conn, "SELECT * FROM ot_booking_history WHERE ot_id=? ORDER BY at, id", (ot_id,))


def insert_team(conn, params: tuple) -> bool:
    conn.execute("SAVEPOINT ot_team")
    try:
        execute(
            conn,
            """INSERT INTO ot_team_members(id, ot_id, user_id, function_code, assigned_by, assigned_at)
               VALUES (?,?,?,?,?,?)""",
            params,
        )
        conn.execute("RELEASE SAVEPOINT ot_team")
        return True
    except Exception as exc:
        conn.execute("ROLLBACK TO SAVEPOINT ot_team")
        if _unique(exc):
            return False
        raise


def team_for(conn, ot_id: str):
    return rows(conn, "SELECT * FROM ot_team_members WHERE ot_id=? ORDER BY assigned_at, id", (ot_id,))


def active_team(conn, ot_id: str, function_code: str):
    return one(
        conn,
        "SELECT * FROM ot_team_members WHERE ot_id=? AND function_code=? AND removed_at IS NULL",
        (ot_id, function_code),
    )


def retire_team(conn, member_id: str, at: str):
    return execute(conn, "UPDATE ot_team_members SET removed_at=? WHERE id=? AND removed_at IS NULL", (at, member_id))


def insert_preop(conn, params: tuple):
    return execute(
        conn,
        """INSERT INTO ot_preop_records(id, ot_id, consent_status, readiness, assessment, allergies, recorded_by, recorded_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        params,
    )


def preop_for(conn, ot_id: str):
    return rows(conn, "SELECT * FROM ot_preop_records WHERE ot_id=? ORDER BY recorded_at, id", (ot_id,))


def latest_preop(conn, ot_id: str):
    return one(conn, "SELECT * FROM ot_preop_records WHERE ot_id=? ORDER BY recorded_at DESC, id DESC LIMIT 1", (ot_id,))


def insert_check(conn, params: tuple):
    return execute(
        conn,
        "INSERT INTO ot_preop_checks(id, preop_id, item_id, satisfied, note) VALUES (?,?,?,?,?)",
        params,
    )


def checks_for(conn, preop_id: str):
    return rows(conn, "SELECT * FROM ot_preop_checks WHERE preop_id=? ORDER BY id", (preop_id,))


def missing_required(conn, preop_id: str):
    return rows(
        conn,
        """SELECT id, label FROM ot_checklist_items
           WHERE active=1 AND required=1
             AND id NOT IN (SELECT item_id FROM ot_preop_checks WHERE preop_id=? AND satisfied=1)""",
        (preop_id,),
    )


def insert_intraop(conn, params: tuple):
    return execute(
        conn,
        """INSERT INTO ot_intraop_records(id, ot_id, notes, findings, complications, anesthesia, recorded_by, recorded_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        params,
    )


def intraop_for(conn, ot_id: str):
    return rows(conn, "SELECT * FROM ot_intraop_records WHERE ot_id=? ORDER BY recorded_at, id", (ot_id,))


def insert_postop(conn, params: tuple):
    return execute(
        conn,
        """INSERT INTO ot_postop_records(id, ot_id, notes, instructions, condition, recorded_by, recorded_at)
           VALUES (?,?,?,?,?,?,?)""",
        params,
    )


def postop_for(conn, ot_id: str):
    return rows(conn, "SELECT * FROM ot_postop_records WHERE ot_id=? ORDER BY recorded_at, id", (ot_id,))


def insert_link(conn, params: tuple) -> bool:
    conn.execute("SAVEPOINT ot_link")
    try:
        execute(
            conn,
            "INSERT INTO ot_links(id, ot_id, module, entity_id, linked_by, linked_at) VALUES (?,?,?,?,?,?)",
            params,
        )
        conn.execute("RELEASE SAVEPOINT ot_link")
        return True
    except Exception as exc:
        conn.execute("ROLLBACK TO SAVEPOINT ot_link")
        if _unique(exc):
            return False
        raise


def links_for(conn, ot_id: str):
    return rows(conn, "SELECT id, ot_id, module, entity_id, linked_by, linked_at FROM ot_links WHERE ot_id=? ORDER BY linked_at", (ot_id,))


def charge_link(conn, ot_id: str, procedure_id: str, purpose: str):
    return one(
        conn,
        "SELECT * FROM ot_charge_links WHERE ot_id=? AND procedure_id=? AND purpose=?",
        (ot_id, procedure_id, purpose),
    )


def insert_charge_link(conn, params: tuple) -> bool:
    conn.execute("SAVEPOINT ot_charge")
    try:
        execute(
            conn,
            """INSERT INTO ot_charge_links(id, ot_id, procedure_id, purpose, invoice_item_id, price_paise, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            params,
        )
        conn.execute("RELEASE SAVEPOINT ot_charge")
        return True
    except Exception as exc:
        conn.execute("ROLLBACK TO SAVEPOINT ot_charge")
        if _unique(exc):
            return False
        raise


def charges_for(conn, ot_id: str):
    return rows(conn, "SELECT * FROM ot_charge_links WHERE ot_id=? ORDER BY created_at", (ot_id,))


def claim_key(conn, key: str, scope: str, request_hash: str, at: str) -> dict:
    existing = one(conn, "SELECT * FROM idempotency_keys WHERE idempotency_key=?", (key,))
    if existing:
        if existing["request_hash"] != request_hash or existing["scope"] != scope:
            return {"status": "conflict"}
        if existing.get("entity_id"):
            return {"status": "replay", "entity_id": existing["entity_id"]}
        return {"status": "in_progress"}
    conn.execute("SAVEPOINT ot_idem")
    try:
        execute(
            conn,
            """INSERT INTO idempotency_keys(idempotency_key, scope, request_hash, entity_id, created_at)
               VALUES (?,?,?,?,?)""",
            (key, scope, request_hash, None, at),
        )
        conn.execute("RELEASE SAVEPOINT ot_idem")
    except Exception as exc:
        conn.execute("ROLLBACK TO SAVEPOINT ot_idem")
        if _unique(exc):
            existing = one(conn, "SELECT * FROM idempotency_keys WHERE idempotency_key=?", (key,))
            if existing and existing.get("entity_id") and existing["request_hash"] == request_hash and existing["scope"] == scope:
                return {"status": "replay", "entity_id": existing["entity_id"]}
            return {"status": "in_progress"}
        raise
    return {"status": "claimed"}


def finish_key(conn, key: str, entity_id: str):
    return execute(conn, "UPDATE idempotency_keys SET entity_id=? WHERE idempotency_key=?", (entity_id, key))


def theatre_open_use(conn, theatre_id: str) -> int:
    used = 0
    if has_column(conn, "ot_cases", "theatre_id"):
        row = one(conn, "SELECT COUNT(*) AS n FROM ot_cases WHERE theatre_id=? AND status IN ('REQUESTED','APPROVED','SCHEDULED','PRE_OP','IN_PROGRESS')", (theatre_id,))
        used += int((row or {}).get("n") or 0)
    if has_table(conn, "ot_bookings"):
        row = one(conn, "SELECT COUNT(*) AS n FROM ot_bookings WHERE theatre_id=? AND status IN ('SCHEDULED','PRE_OP','IN_PROGRESS')", (theatre_id,))
        used += int((row or {}).get("n") or 0)
    return used


def theatre_in_use(conn, theatre_id: str) -> int:
    used = 0
    if has_column(conn, "ot_cases", "theatre_id"):
        used += count_where(conn, "ot_cases", "theatre_id", theatre_id)
    used += count_where(conn, "ot_bookings", "theatre_id", theatre_id)
    return used


def procedure_in_use(conn, procedure_id: str) -> int:
    used = count_where(conn, "ot_cases", "procedure_id", procedure_id)
    used += count_where(conn, "ot_charge_links", "procedure_id", procedure_id)
    return used


def checklist_in_use(conn, item_id: str) -> int:
    return count_where(conn, "ot_preop_checks", "item_id", item_id)


def delete_theatre(conn, theatre_id: str):
    if has_column(conn, "ot_cases", "theatre_id"):
        execute(conn, "UPDATE ot_cases SET theatre_id=NULL WHERE theatre_id=?", (theatre_id,))
    if has_table(conn, "ot_bookings"):
        exec_if(conn, "ot_booking_history", "DELETE FROM ot_booking_history WHERE theatre_id=?", (theatre_id,))
        execute(conn, "DELETE FROM ot_bookings WHERE theatre_id=?", (theatre_id,))
    return execute(conn, "DELETE FROM ot_theatres WHERE id=?", (theatre_id,))


def delete_procedure(conn, procedure_id: str):
    if has_column(conn, "ot_cases", "procedure_id"):
        execute(conn, "UPDATE ot_cases SET procedure_id=NULL WHERE procedure_id=?", (procedure_id,))
    exec_if(conn, "ot_charge_links", "DELETE FROM ot_charge_links WHERE procedure_id=?", (procedure_id,))
    return execute(conn, "DELETE FROM ot_procedures WHERE id=?", (procedure_id,))


def delete_checklist(conn, item_id: str):
    return execute(conn, "DELETE FROM ot_checklist_items WHERE id=?", (item_id,))
