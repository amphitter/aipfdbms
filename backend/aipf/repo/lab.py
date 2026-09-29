"""SQL owned by the repository. Domain modules call these functions."""
from __future__ import annotations

from aipf.repo.sqlio import execute, one, rows

def q_clinical_19140(conn, p0):
    return rows(conn, "SELECT * FROM lab_orders WHERE encounter_id=? ORDER BY ordered_at DESC", (p0,))

def q_clinical_27447(conn, p0):
    return rows(conn, "SELECT * FROM lab_orders WHERE patient_id=? ORDER BY ordered_at", (p0,))

def q_clinical_29322(conn, p0):
    return rows(conn, "SELECT * FROM lab_orders WHERE patient_id=? ORDER BY ordered_at DESC", (p0,))

def q_clinical_34107(conn):
    return rows(conn, "SELECT * FROM lab_tests ORDER BY category, sort_order, name", ())

def q_clinical_34192(conn):
    return rows(conn, "SELECT * FROM lab_tests WHERE active=1 ORDER BY category, sort_order, name", ())

def q_clinical_34523(conn, p0):
    return one(conn, "SELECT id FROM lab_tests WHERE id=?", (p0,))

def q_clinical_34630(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8, p9):
    return execute(conn, """UPDATE lab_tests SET code=?, name=?, category=?, price_paise=?, sample_type=?, preparation=?, tat_hours=?, active=?, sort_order=? WHERE id=?""", (p0, p1, p2, p3, p4, p5, p6, p7, p8, p9))

def q_clinical_35219(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10):
    return execute(conn, """INSERT INTO lab_tests(id, code, name, category, price_paise, sample_type, preparation, tat_hours, active, sort_order, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10))

def q_clinical_35867(conn, p0):
    return one(conn, "SELECT * FROM lab_tests WHERE id=?", (p0,))

def q_wards_21525(conn, p0, p1, p2, p3, p4, p5, p6, p7):
    return execute(conn, """INSERT INTO lab_orders(id, encounter_id, admission_id, patient_id, doctor_id, status, notes, ordered_at, created_by, priority)
           VALUES (?,?,?,?,?,'SAMPLE_PENDING',?,?,?,'ROUTINE')""", (p0, p1, p2, p3, p4, p5, p6, p7))

def q_wards_22104(conn, p0):
    return one(conn, "SELECT * FROM lab_tests WHERE id=? AND active=1", (p0,))

def q_wards_22590(conn, p0, p1, p2, p3, p4, p5, p6):
    return execute(conn, """INSERT INTO lab_order_items(id, order_id, test_id, custom_name, price_paise, price_pending, sample_type, status)
               VALUES (?,?,?,?,?,?,?,'SAMPLE_PENDING')""", (p0, p1, p2, p3, p4, p5, p6))

def q_wards_23472(conn, p0, p1):
    return execute(conn, "UPDATE lab_order_items SET invoice_item_id=? WHERE id=?", (p0, p1))

def q_wards_24156(conn, p0):
    return one(conn, "SELECT * FROM lab_orders WHERE id=?", (p0,))

def q_wards_24300(conn, p0):
    return rows(conn, "SELECT * FROM lab_order_items WHERE order_id=?", (p0,))

def q_wards_24616(conn, p0):
    return rows(conn, "SELECT * FROM lab_orders WHERE status=? ORDER BY ordered_at DESC", (p0,))

def q_wards_24732(conn):
    return rows(conn, "SELECT * FROM lab_orders ORDER BY ordered_at DESC LIMIT 100", ())

def q_wards_24930(conn, p0):
    return rows(conn, "SELECT * FROM lab_order_items WHERE order_id=?", (p0,))

def q_wards_25295(conn, p0):
    return one(conn, "SELECT id FROM lab_orders WHERE id=?", (p0,))

def q_wards_25405(conn, p0, p1):
    return execute(conn, "UPDATE lab_orders SET status=? WHERE id=?", (p0, p1))

def q_wards_25521(conn, p0, p1):
    return execute(conn, "UPDATE lab_order_items SET status=? WHERE order_id=? AND status!='RESULTED'", (p0, p1))

def q_wards_25976(conn, p0):
    return one(conn, "SELECT * FROM lab_order_items WHERE id=?", (p0,))

def q_wards_26201(conn, p0, p1, p2, p3, p4):
    return execute(conn, "UPDATE lab_order_items SET result_text=?, result_at=?, resulted_by=?, document_id=COALESCE(?, document_id), status='RESULTED' WHERE id=?", (p0, p1, p2, p3, p4))

def q_wards_26471(conn, p0):
    return one(conn, "SELECT COUNT(*) AS n FROM lab_order_items WHERE order_id=? AND status!='RESULTED'", (p0,))

def q_wards_26637(conn, p0):
    return execute(conn, "UPDATE lab_orders SET status='RESULTED' WHERE id=?", (p0,))

def q_system_37470(conn):
    return one(conn, "SELECT COUNT(*) AS n FROM lab_orders WHERE status NOT IN ('RESULTED','VERIFIED','CANCELLED')", ())

def q_seed_9134(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8, p9):
    return execute(conn, """INSERT INTO lab_tests(id, code, name, category, price_paise, sample_type, preparation, tat_hours, active, sort_order, created_at)
               VALUES (?,?,?,?,?,?,?,?,1,?,?)""", (p0, p1, p2, p3, p4, p5, p6, p7, p8, p9))

def insert_result(conn, result_id, item_id, value_text, units, reference_range, status, entered_by, entered_at, document_id, finalized_by=None, finalized_at=None):
    return execute(
        conn,
        """INSERT INTO lab_results(
             id, lab_order_item_id, value_text, units, reference_range, status,
             entered_by, entered_at, finalized_by, finalized_at, document_id
           ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (result_id, item_id, value_text, units, reference_range, status, entered_by, entered_at, finalized_by, finalized_at, document_id),
    )


def _lock(conn, sql: str, params):
    if getattr(conn, "dialect", "") == "postgres":
        sql += " FOR UPDATE"
    return one(conn, sql, params)


def test_by_code(conn, code: str):
    return one(conn, "SELECT id, code FROM lab_tests WHERE code IS NOT NULL AND code <> '' AND upper(code)=upper(?)", (code,))


def test_row(conn, test_id: str):
    return one(conn, "SELECT * FROM lab_tests WHERE id=?", (test_id,))


def update_test_config(conn, item_id, container, unit, reference_range, low, high, crit_low, crit_high, methodology, result_type, updated_at):
    return execute(
        conn,
        """UPDATE lab_tests
              SET container_type=?, unit=?, reference_range=?, reference_low=?, reference_high=?,
                  critical_low=?, critical_high=?, methodology=?, result_type=?, updated_at=?
            WHERE id=?""",
        (container, unit, reference_range, low, high, crit_low, crit_high, methodology, result_type, updated_at, item_id),
    )


def patient_row(conn, patient_id: str):
    return one(conn, "SELECT id, name, gender, dob, age_at_registration, hospital_no FROM patients WHERE id=?", (patient_id,))


def encounter_owner(conn, encounter_id: str):
    return one(conn, "SELECT id, patient_id FROM encounters WHERE id=?", (encounter_id,))


def admission_owner(conn, admission_id: str):
    return one(conn, "SELECT id, patient_id, encounter_id FROM admissions WHERE id=?", (admission_id,))


def insert_order(conn, oid, encounter_id, admission_id, patient_id, doctor_id, notes, ordered_at, created_by, priority):
    return execute(
        conn,
        """INSERT INTO lab_orders(id, encounter_id, admission_id, patient_id, doctor_id, status, notes, ordered_at, created_by, priority)
           VALUES (?,?,?,?,?,'SAMPLE_PENDING',?,?,?,?)""",
        (oid, encounter_id, admission_id, patient_id, doctor_id, notes, ordered_at, created_by, priority),
    )


def insert_item(conn, iid, order_id, test_id, custom_name, price, pending, sample_type):
    return execute(
        conn,
        """INSERT INTO lab_order_items(id, order_id, test_id, custom_name, price_paise, price_pending, sample_type, status)
           VALUES (?,?,?,?,?,?,?,'SAMPLE_PENDING')""",
        (iid, order_id, test_id, custom_name, price, pending, sample_type),
    )


def lock_order(conn, order_id: str):
    return _lock(conn, "SELECT * FROM lab_orders WHERE id=?", (order_id,))


def lock_item(conn, item_id: str):
    return _lock(conn, "SELECT * FROM lab_order_items WHERE id=?", (item_id,))


def sample_row(conn, sample_id: str):
    return one(conn, "SELECT * FROM lab_samples WHERE id=?", (sample_id,))


def lock_sample(conn, sample_id: str):
    return _lock(conn, "SELECT * FROM lab_samples WHERE id=?", (sample_id,))


def lock_result(conn, result_id: str):
    return _lock(conn, "SELECT * FROM lab_results WHERE id=?", (result_id,))


def items_for_order(conn, order_id: str):
    return rows(conn, "SELECT * FROM lab_order_items WHERE order_id=? ORDER BY id", (order_id,))


def item_row(conn, item_id: str):
    return one(conn, "SELECT * FROM lab_order_items WHERE id=?", (item_id,))


def set_item_status(conn, item_id: str, status: str):
    return execute(conn, "UPDATE lab_order_items SET status=? WHERE id=?", (status, item_id))


def attach_item_document(conn, item_id: str, document_id: str):
    return execute(conn, "UPDATE lab_order_items SET document_id=? WHERE id=?", (document_id, item_id))


def set_order_status(conn, order_id: str, status: str):
    return execute(conn, "UPDATE lab_orders SET status=? WHERE id=?", (status, order_id))


def cancel_order(conn, order_id: str, user_id: str, reason: str, at: str):
    return execute(
        conn,
        "UPDATE lab_orders SET status='CANCELLED', cancelled_at=?, cancelled_by=?, cancel_reason=? WHERE id=?",
        (at, user_id, reason, order_id),
    )


def active_sample_for_item(conn, item_id: str):
    return one(
        conn,
        """SELECT s.* FROM lab_samples s
           JOIN lab_sample_items si ON si.sample_id = s.id
           WHERE si.order_item_id=? AND si.active_item=1 AND s.status <> 'REJECTED'""",
        (item_id,),
    )


def _unique_violation(exc: Exception) -> bool:
    text = str(exc).lower()
    return "unique" in text or "duplicate" in text


def _insert_once(conn, sql: str, params) -> bool:
    """Insert under a savepoint so a unique race rolls back only this statement."""
    conn.execute("SAVEPOINT lab_write")
    try:
        execute(conn, sql, params)
        conn.execute("RELEASE SAVEPOINT lab_write")
        return True
    except Exception as exc:
        conn.execute("ROLLBACK TO SAVEPOINT lab_write")
        if _unique_violation(exc):
            return False
        raise


def insert_sample(conn, sample_id, accession, patient_id, encounter_id, order_id, specimen, container, collected_at, collected_by, location, notes, replaces, created_at):
    return _insert_once(
        conn,
        """INSERT INTO lab_samples(
             id, accession_no, patient_id, encounter_id, order_id, specimen_type, container_type, status,
             collected_at, collected_by, collection_location, collection_notes, replaces_sample_id, created_at
           ) VALUES (?,?,?,?,?,?,?,'COLLECTED',?,?,?,?,?,?)""",
        (sample_id, accession, patient_id, encounter_id, order_id, specimen, container, collected_at, collected_by, location, notes, replaces, created_at),
    )


def link_sample_item(conn, sample_id: str, item_id: str) -> bool:
    return _insert_once(
        conn,
        "INSERT INTO lab_sample_items(sample_id, order_item_id, active_item) VALUES (?,?,1)",
        (sample_id, item_id),
    )


def release_active_links(conn, sample_id: str):
    return execute(conn, "UPDATE lab_sample_items SET active_item=NULL WHERE sample_id=?", (sample_id,))


def reject_sample(conn, sample_id: str, user_id: str, reason: str, at: str):
    cur = execute(
        conn,
        """UPDATE lab_samples
              SET status='REJECTED', rejected_at=?, rejected_by=?, rejection_reason=?
            WHERE id=? AND status IN ('COLLECTED', 'RECEIVED', 'PROCESSING')""",
        (at, user_id, reason, sample_id),
    )
    if cur.rowcount:
        release_active_links(conn, sample_id)
    return cur.rowcount


def receive_sample(conn, sample_id: str, user_id: str, at: str):
    cur = execute(
        conn,
        """UPDATE lab_samples SET status='RECEIVED', received_at=?, received_by=?
            WHERE id=? AND status='COLLECTED'""",
        (at, user_id, sample_id),
    )
    return cur.rowcount


def process_sample(conn, sample_id: str, user_id: str, at: str):
    cur = execute(
        conn,
        """UPDATE lab_samples
              SET status='PROCESSING',
                  received_at=COALESCE(received_at, ?),
                  received_by=COALESCE(received_by, ?)
            WHERE id=? AND status IN ('COLLECTED', 'RECEIVED')""",
        (at, user_id, sample_id),
    )
    return cur.rowcount


def sample_items(conn, sample_id: str):
    return rows(conn, "SELECT order_item_id FROM lab_sample_items WHERE sample_id=?", (sample_id,))


def samples_for_order(conn, order_id: str):
    return rows(conn, "SELECT * FROM lab_samples WHERE order_id=? ORDER BY created_at", (order_id,))


def sample_links_for_item(conn, item_id: str):
    return rows(conn, "SELECT sample_id, order_item_id FROM lab_sample_items WHERE order_item_id=? ORDER BY sample_id", (item_id,))


def delete_document_row(conn, doc_id: str):
    return execute(conn, "DELETE FROM documents WHERE id=? AND entity_type='lab_order'", (doc_id,))


def sample_links(conn, order_id: str):
    return rows(
        conn,
        """SELECT si.sample_id, si.order_item_id
             FROM lab_sample_items si
             JOIN lab_samples s ON s.id = si.sample_id
            WHERE s.order_id=?""",
        (order_id,),
    )


def rejection_reason(conn, code: str):
    return one(
        conn,
        """SELECT id, code, name FROM master_items
            WHERE list_type='lab_rejection_reason' AND active=1 AND upper(code)=upper(?)""",
        (code,),
    )


def current_result(conn, item_id: str):
    return one(
        conn,
        """SELECT * FROM lab_results
            WHERE lab_order_item_id=? AND status IN ('ENTERED', 'VERIFIED', 'FINALIZED')
            ORDER BY revision_no DESC LIMIT 1""",
        (item_id,),
    )


def results_for_item(conn, item_id: str):
    return rows(conn, "SELECT * FROM lab_results WHERE lab_order_item_id=? ORDER BY revision_no", (item_id,))


def results_for_order(conn, order_id: str):
    return rows(
        conn,
        """SELECT r.* FROM lab_results r
             JOIN lab_order_items i ON i.id = r.lab_order_item_id
            WHERE i.order_id=?
            ORDER BY r.revision_no""",
        (order_id,),
    )


def supersede_result(conn, result_id: str):
    cur = execute(conn, "UPDATE lab_results SET status='SUPERSEDED' WHERE id=? AND status IN ('ENTERED', 'VERIFIED')", (result_id,))
    return cur.rowcount


def insert_workflow_result(conn, values: dict):
    conn.execute("SAVEPOINT lab_result")
    try:
        execute(
            conn,
            """INSERT INTO lab_results(
                 id, lab_order_item_id, value_text, units, reference_range, status,
                 entered_by, entered_at, result_type, reference_low, reference_high,
                 critical_low, critical_high, methodology, abnormal_flag, critical_flag,
                 remarks, revision_no, supersedes_id, correction_reason
               ) VALUES (?,?,?,?,?,'ENTERED',?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                values["id"], values["item_id"], values["value"], values["units"], values["reference_range"],
                values["entered_by"], values["entered_at"], values["result_type"], values["reference_low"],
                values["reference_high"], values["critical_low"], values["critical_high"], values["methodology"],
                values["abnormal_flag"], values["critical_flag"], values["remarks"], values["revision_no"],
                values["supersedes_id"], values["correction_reason"],
            ),
        )
        conn.execute("RELEASE SAVEPOINT lab_result")
    except Exception as exc:
        conn.execute("ROLLBACK TO SAVEPOINT lab_result")
        text = str(exc).lower()
        if "unique" in text or "duplicate" in text:
            return None
        raise
    return values["id"]


def verify_result(conn, result_id: str, user_id: str, at: str):
    cur = execute(
        conn,
        """UPDATE lab_results
              SET status='VERIFIED', verified_by=?, verified_at=?, finalized_by=?, finalized_at=?
            WHERE id=? AND status='ENTERED'""",
        (user_id, at, user_id, at, result_id),
    )
    return cur.rowcount


def result_row(conn, result_id: str):
    return one(conn, "SELECT * FROM lab_results WHERE id=?", (result_id,))


def invoice_line(conn, item_id: str):
    return one(
        conn,
        """SELECT ii.id, ii.rate_paise, ii.amount_paise, ii.tax_paise, ii.description, ii.invoice_id
             FROM invoice_items ii
             JOIN lab_order_items li ON li.invoice_item_id = ii.id
            WHERE li.id=?""",
        (item_id,),
    )


def processing_queue(conn):
    return rows(
        conn,
        """SELECT s.*, o.priority, o.patient_id AS order_patient_id
             FROM lab_samples s
             JOIN lab_orders o ON o.id = s.order_id
            WHERE s.status IN ('COLLECTED', 'RECEIVED')
            ORDER BY CASE o.priority WHEN 'STAT' THEN 0 WHEN 'URGENT' THEN 1 ELSE 2 END, s.collected_at""",
    )


def reports_for_order(conn, order_id: str):
    return rows(conn, "SELECT * FROM lab_reports WHERE order_id=? ORDER BY generated_at", (order_id,))


def report_by_fingerprint(conn, order_id: str, fingerprint: str):
    return one(conn, "SELECT * FROM lab_reports WHERE order_id=? AND fingerprint=?", (order_id, fingerprint))


def report_row(conn, report_id: str):
    return one(conn, "SELECT * FROM lab_reports WHERE id=?", (report_id,))


def latest_report(conn, order_id: str):
    return one(conn, "SELECT * FROM lab_reports WHERE order_id=? ORDER BY generated_at DESC LIMIT 1", (order_id,))


def insert_report(conn, report_id, order_id, patient_id, encounter_id, document_id, fingerprint, user_id, at):
    conn.execute("SAVEPOINT lab_report")
    try:
        execute(
            conn,
            """INSERT INTO lab_reports(id, order_id, patient_id, encounter_id, document_id, fingerprint, generated_by, generated_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (report_id, order_id, patient_id, encounter_id, document_id, fingerprint, user_id, at),
        )
        conn.execute("RELEASE SAVEPOINT lab_report")
    except Exception as exc:
        conn.execute("ROLLBACK TO SAVEPOINT lab_report")
        text = str(exc).lower()
        if "unique" in text or "duplicate" in text:
            return None
        raise
    return report_id


def count_reports(conn, order_id: str):
    return one(conn, "SELECT COUNT(*) AS n FROM lab_reports WHERE order_id=?", (order_id,))


def count_documents_for_order(conn, order_id: str):
    return one(conn, "SELECT COUNT(*) AS n FROM documents WHERE entity_type='lab_order' AND entity_id=?", (order_id,))


def count_samples(conn, order_id: str):
    return one(conn, "SELECT COUNT(*) AS n FROM lab_samples WHERE order_id=?", (order_id,))


def count_payments(conn, patient_id: str):
    return one(conn, "SELECT COUNT(*) AS n FROM payments WHERE patient_id=?", (patient_id,))


def samples_for_patient(conn, patient_id: str):
    return rows(
        conn,
        "SELECT id, accession_no, status, collected_at, rejected_at, order_id FROM lab_samples WHERE patient_id=? ORDER BY created_at",
        (patient_id,),
    )


def verified_for_patient(conn, patient_id: str):
    return rows(
        conn,
        """SELECT r.id, r.verified_at, r.abnormal_flag, r.critical_flag, r.value_text, r.lab_order_item_id,
                  i.custom_name, t.name AS test_name, o.id AS order_id
             FROM lab_results r
             JOIN lab_order_items i ON i.id = r.lab_order_item_id
             JOIN lab_orders o ON o.id = i.order_id
             LEFT JOIN lab_tests t ON t.id = i.test_id
            WHERE o.patient_id=? AND r.status='VERIFIED'
            ORDER BY r.verified_at""",
        (patient_id,),
    )


def reports_for_patient(conn, patient_id: str):
    return rows(
        conn,
        "SELECT id, order_id, document_id, generated_at FROM lab_reports WHERE patient_id=? ORDER BY generated_at",
        (patient_id,),
    )


def delete_for_patients(conn, ids: list[str]):
    if not ids:
        return
    marks = ",".join("?" for _ in ids)
    execute(conn, f"UPDATE lab_samples SET replaces_sample_id=NULL WHERE patient_id IN ({marks})", ids)
    execute(conn, f"DELETE FROM lab_reports WHERE patient_id IN ({marks})", ids)
    execute(
        conn,
        f"""DELETE FROM lab_results WHERE lab_order_item_id IN (
              SELECT id FROM lab_order_items WHERE order_id IN (SELECT id FROM lab_orders WHERE patient_id IN ({marks}))
            )""",
        ids,
    )
    execute(conn, f"DELETE FROM lab_sample_items WHERE sample_id IN (SELECT id FROM lab_samples WHERE patient_id IN ({marks}))", ids)
    execute(conn, f"DELETE FROM lab_samples WHERE patient_id IN ({marks})", ids)


def get_idempotency(conn, key: str):
    return one(conn, "SELECT * FROM idempotency_keys WHERE idempotency_key=?", (key,))


def claim_key(conn, key: str, scope: str, request_hash: str, at: str) -> dict:
    existing = get_idempotency(conn, key)
    if existing:
        if existing["request_hash"] != request_hash or existing["scope"] != scope:
            return {"status": "conflict"}
        if existing.get("entity_id"):
            return {"status": "replay", "entity_id": existing["entity_id"]}
        return {"status": "in_progress"}
    conn.execute("SAVEPOINT lab_idem")
    try:
        execute(
            conn,
            """INSERT INTO idempotency_keys(idempotency_key, scope, request_hash, entity_id, created_at)
               VALUES (?,?,?,?,?)""",
            (key, scope, request_hash, None, at),
        )
        conn.execute("RELEASE SAVEPOINT lab_idem")
    except Exception as exc:
        conn.execute("ROLLBACK TO SAVEPOINT lab_idem")
        text = str(exc).lower()
        if "unique" in text or "duplicate" in text:
            existing = get_idempotency(conn, key)
            if existing and existing["request_hash"] == request_hash and existing["scope"] == scope and existing.get("entity_id"):
                return {"status": "replay", "entity_id": existing["entity_id"]}
            if existing and (existing["request_hash"] != request_hash or existing["scope"] != scope):
                return {"status": "conflict"}
            return {"status": "in_progress"}
        raise
    return {"status": "claimed"}


def finish_key(conn, key: str, entity_id: str):
    return execute(conn, "UPDATE idempotency_keys SET entity_id=? WHERE idempotency_key=?", (entity_id, key))
