"""SQL owned by the repository. Domain modules call these functions."""
from __future__ import annotations

from aipf.repo.sqlio import execute, one, rows

def q_clinical_19399(conn, p0):
    return one(conn, "SELECT * FROM admissions WHERE encounter_id=? AND status!='CANCELLED' ORDER BY created_at DESC LIMIT 1", (p0,))

def q_clinical_27716(conn, p0):
    return rows(conn, "SELECT * FROM admissions WHERE patient_id=? ORDER BY created_at", (p0,))

def q_clinical_29443(conn, p0):
    return rows(conn, "SELECT * FROM admissions WHERE patient_id=? ORDER BY created_at DESC", (p0,))

def q_billing_19155(conn, p0):
    return one(conn, "SELECT * FROM admissions WHERE id=?", (p0,))

def q_wards_2791(conn, p0):
    return one(conn, "SELECT id FROM admissions WHERE patient_id=? AND status IN ('REQUESTED','ADMITTED','DISCHARGE_PENDING')", (p0,))

def q_wards_3544(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11, p12, p13, p14, p15, p16, p17, p18):
    return execute(conn, """INSERT INTO admissions(id, patient_id, encounter_id, admission_type, status, ward_id, room_id, bed_id, doctor_id,
           department_id, diagnosis, reason, admitted_at, expected_discharge, daily_rate_paise, requested_by, created_at, updated_at, is_sample)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11, p12, p13, p14, p15, p16, p17, p18))

def q_wards_4737(conn, p0, p1, p2, p3, p4, p5):
    return execute(conn, "INSERT INTO bed_movements(admission_id, patient_id, to_bed_id, reason, user_id, at) VALUES (?,?,?,?,?,?)", (p0, p1, p2, p3, p4, p5))

def q_wards_5554(conn, p0):
    return one(conn, "SELECT * FROM admissions WHERE id=?", (p0,))

def q_wards_6127(conn, p0):
    return rows(conn, "SELECT * FROM admission_charges WHERE admission_id=? ORDER BY charge_date, posted_at", (p0,))

def q_wards_6266(conn, p0):
    return rows(conn, "SELECT * FROM bed_movements WHERE admission_id=? ORDER BY id", (p0,))

def q_wards_6628(conn):
    return rows(conn, "SELECT * FROM admissions ORDER BY created_at DESC LIMIT 100", ())

def q_wards_6728(conn, p0):
    return rows(conn, "SELECT * FROM admissions WHERE status=? ORDER BY admitted_at DESC", (p0,))


def list_current(conn):
    return rows(conn, "SELECT * FROM admissions WHERE status IN ('ADMITTED','DISCHARGE_PENDING') ORDER BY admitted_at DESC", ())

def q_wards_7409(conn, p0):
    return one(conn, "SELECT * FROM admissions WHERE id=?", (p0,))

def q_wards_8016(conn, p0, p1, p2, p3, p4, p5):
    return execute(conn, "UPDATE admissions SET ward_id=?, room_id=?, bed_id=?, daily_rate_paise=?, updated_at=? WHERE id=?", (p0, p1, p2, p3, p4, p5))

def q_wards_8406(conn, p0, p1, p2, p3, p4, p5, p6):
    return execute(conn, "INSERT INTO bed_movements(admission_id, patient_id, from_bed_id, to_bed_id, reason, user_id, at) VALUES (?,?,?,?,?,?,?)", (p0, p1, p2, p3, p4, p5, p6))

def q_wards_9103(conn, p0):
    return one(conn, "SELECT * FROM admissions WHERE id=?", (p0,))

def q_wards_9762(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11, p12):
    return execute(conn, """INSERT INTO admission_charges(id, admission_id, charge_date, description, category, rate_paise, qty, amount_paise, source_module, source_id, invoice_item_id, posted_by, posted_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", (p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11, p12))

def q_wards_10667(conn, p0, p1):
    return one(conn, "SELECT id FROM admission_charges WHERE admission_id=? AND charge_date=? AND source_module IN ('bed_day','admission')", (p0, p1))

def q_wards_11409(conn, p0):
    return one(conn, "SELECT * FROM admissions WHERE id=?", (p0,))

def q_wards_11708(conn, p0, p1, p2, p3, p4):
    return execute(conn, """UPDATE admissions SET status='DISCHARGED', discharged_at=?, discharge_summary=?, discharge_condition=?, updated_at=? WHERE id=?""", (p0, p1, p2, p3, p4))

def q_wards_12128(conn, p0, p1, p2, p3, p4, p5):
    return execute(conn, "INSERT INTO bed_movements(admission_id, patient_id, from_bed_id, reason, user_id, at) VALUES (?,?,?,?,?,?)", (p0, p1, p2, p3, p4, p5))

def q_system_34179(conn, p0):
    return rows(conn, "SELECT id, patient_id, status FROM admissions WHERE id LIKE ? LIMIT 8", (p0,))

def q_system_36579(conn):
    return one(conn, "SELECT COUNT(*) AS n FROM admissions WHERE status='ADMITTED'", ())

def q_system_38775(conn, p0):
    return one(conn, "SELECT COUNT(*) AS n FROM admissions WHERE substr(COALESCE(admitted_at, created_at),1,10)=?", (p0,))

def q_system_38916(conn, p0):
    return one(conn, "SELECT COUNT(*) AS n FROM admissions WHERE substr(discharged_at,1,10)=?", (p0,))

def q_seed_26796(conn, p0, p1, p2, p3):
    return execute(conn, """INSERT INTO admissions(id, patient_id, encounter_id, admission_type, status, ward_id, room_id, bed_id, doctor_id, department_id, diagnosis, reason, admitted_at, daily_rate_paise, requested_by, created_at, updated_at, is_sample)
           VALUES ('ADM-2026-000001','P-000005','OPD-2026-000007','INPATIENT','ADMITTED','W-GEN','R-W-GEN-Common','BD-R-W-GEN-Common-1','U-IMRAN',?,'Left wrist injury — observation','Fall at home',?,80000,'U-IMRAN',?,?,1)""", (p0, p1, p2, p3))

def q_seed_27446(conn, p0):
    return execute(conn, """INSERT INTO bed_movements(admission_id, patient_id, to_bed_id, reason, user_id, at)
           VALUES ('ADM-2026-000001','P-000005','BD-R-W-GEN-Common-1','Admission','U-NURSE',?)""", (p0,))

def q_seed_28727(conn, p0, p1):
    return execute(conn, """INSERT INTO admission_charges(id, admission_id, charge_date, description, category, rate_paise, qty, amount_paise, source_module, source_id, invoice_item_id, posted_by, posted_at)
           VALUES ('AC-1','ADM-2026-000001',?,'Bed / room charge — admission day','IPD',80000,1,80000,'admission','ADM-2026-000001','II-7B','U-NURSE',?)""", (p0, p1))


def _lock(conn, sql: str, params):
    if getattr(conn, "dialect", "") == "postgres":
        sql += " FOR UPDATE"
    return one(conn, sql, params)


def lock_admission(conn, admission_id: str):
    return _lock(conn, "SELECT * FROM admissions WHERE id=?", (admission_id,))


def lock_bed(conn, bed_id: str):
    return _lock(conn, "SELECT * FROM beds WHERE id=?", (bed_id,))


def encounter_owner(conn, encounter_id: str):
    return one(conn, "SELECT id, patient_id FROM encounters WHERE id=?", (encounter_id,))


def user_row(conn, user_id: str):
    return one(conn, "SELECT id FROM users WHERE id=? AND active=1", (user_id,))


def ward_row(conn, ward_id: str):
    return one(conn, "SELECT * FROM wards WHERE id=?", (ward_id,))


def _unique(exc: Exception) -> bool:
    text = str(exc).lower()
    return "unique" in text or "duplicate" in text


def insert_admission(conn, params: tuple) -> bool:
    conn.execute("SAVEPOINT ipd_write")
    try:
        q_wards_3544(conn, *params)
        conn.execute("RELEASE SAVEPOINT ipd_write")
        return True
    except Exception as exc:
        conn.execute("ROLLBACK TO SAVEPOINT ipd_write")
        if _unique(exc):
            return False
        raise


def occupy_bed(conn, bed_id: str, admission_id: str) -> int:
    cur = execute(
        conn,
        """UPDATE beds
              SET status='OCCUPIED', current_admission_id=?
            WHERE id=? AND active=1 AND status='AVAILABLE' AND current_admission_id IS NULL""",
        (admission_id, bed_id),
    )
    return cur.rowcount


def release_bed(conn, bed_id: str, admission_id: str) -> int:
    cur = execute(
        conn,
        """UPDATE beds
              SET status='AVAILABLE', current_admission_id=NULL
            WHERE id=? AND current_admission_id=?""",
        (bed_id, admission_id),
    )
    return cur.rowcount


def mark_discharge_pending(conn, admission_id: str, at: str) -> int:
    cur = execute(
        conn,
        "UPDATE admissions SET status='DISCHARGE_PENDING', updated_at=? WHERE id=? AND status='ADMITTED'",
        (at, admission_id),
    )
    return cur.rowcount


def mark_discharged(conn, admission_id: str, at: str, summary: str, condition: str, doctor_id: str | None) -> int:
    cur = execute(
        conn,
        """UPDATE admissions
              SET status='DISCHARGED', discharged_at=?, discharge_summary=?, discharge_condition=?,
                  discharge_doctor_id=?, bed_id=NULL, updated_at=?
            WHERE id=? AND status IN ('ADMITTED', 'DISCHARGE_PENDING')""",
        (at, summary, condition, doctor_id, at, admission_id),
    )
    return cur.rowcount


def mark_cancelled(conn, admission_id: str, at: str, reason: str) -> int:
    cur = execute(
        conn,
        """UPDATE admissions
              SET status='CANCELLED', cancelled_at=?, cancel_reason=?, updated_at=?, bed_id=NULL
            WHERE id=? AND status IN ('REQUESTED', 'ADMITTED', 'DISCHARGE_PENDING')""",
        (at, reason, at, admission_id),
    )
    return cur.rowcount


def place_on_bed(conn, admission_id: str, ward_id, room_id, bed_id, rate: int, at: str) -> int:
    cur = execute(
        conn,
        """UPDATE admissions
              SET status='ADMITTED', ward_id=?, room_id=?, bed_id=?, daily_rate_paise=?,
                  admitted_at=COALESCE(admitted_at, ?), updated_at=?
            WHERE id=? AND status='REQUESTED'""",
        (ward_id, room_id, bed_id, rate, at, at, admission_id),
    )
    return cur.rowcount


def move_admission(conn, admission_id: str, ward_id, room_id, bed_id, rate: int, at: str, previous_bed: str | None) -> int:
    if previous_bed is None:
        cur = execute(
            conn,
            """UPDATE admissions
                  SET ward_id=?, room_id=?, bed_id=?, daily_rate_paise=?, updated_at=?
                WHERE id=? AND status IN ('ADMITTED', 'DISCHARGE_PENDING') AND bed_id IS NULL""",
            (ward_id, room_id, bed_id, rate, at, admission_id),
        )
    else:
        cur = execute(
            conn,
            """UPDATE admissions
                  SET ward_id=?, room_id=?, bed_id=?, daily_rate_paise=?, updated_at=?
                WHERE id=? AND status IN ('ADMITTED', 'DISCHARGE_PENDING') AND bed_id=?""",
            (ward_id, room_id, bed_id, rate, at, admission_id, previous_bed),
        )
    return cur.rowcount


def insert_bed_day(conn, params: tuple) -> bool:
    conn.execute("SAVEPOINT ipd_charge")
    try:
        q_wards_9762(conn, *params)
        conn.execute("RELEASE SAVEPOINT ipd_charge")
        return True
    except Exception as exc:
        conn.execute("ROLLBACK TO SAVEPOINT ipd_charge")
        if _unique(exc):
            return False
        raise


def set_charge_invoice(conn, charge_id: str, invoice_item_id: str):
    return execute(conn, "UPDATE admission_charges SET invoice_item_id=? WHERE id=?", (invoice_item_id, charge_id))


def set_discharge_document(conn, admission_id: str, document_id: str, fingerprint: str):
    return execute(
        conn,
        "UPDATE admissions SET discharge_document_id=?, discharge_fingerprint=? WHERE id=?",
        (document_id, fingerprint, admission_id),
    )


def movements_for_patient(conn, patient_id: str):
    return rows(conn, "SELECT * FROM bed_movements WHERE patient_id=? ORDER BY id", (patient_id,))


def claim_key(conn, key: str, scope: str, request_hash: str, at: str) -> dict:
    existing = one(conn, "SELECT * FROM idempotency_keys WHERE idempotency_key=?", (key,))
    if existing:
        if existing["request_hash"] != request_hash or existing["scope"] != scope:
            return {"status": "conflict"}
        if existing.get("entity_id"):
            return {"status": "replay", "entity_id": existing["entity_id"]}
        return {"status": "in_progress"}
    conn.execute("SAVEPOINT ipd_idem")
    try:
        execute(
            conn,
            """INSERT INTO idempotency_keys(idempotency_key, scope, request_hash, entity_id, created_at)
               VALUES (?,?,?,?,?)""",
            (key, scope, request_hash, None, at),
        )
        conn.execute("RELEASE SAVEPOINT ipd_idem")
    except Exception as exc:
        conn.execute("ROLLBACK TO SAVEPOINT ipd_idem")
        if _unique(exc):
            existing = one(conn, "SELECT * FROM idempotency_keys WHERE idempotency_key=?", (key,))
            if existing and existing.get("entity_id") and existing["request_hash"] == request_hash and existing["scope"] == scope:
                return {"status": "replay", "entity_id": existing["entity_id"]}
            return {"status": "in_progress"}
        raise
    return {"status": "claimed"}


def finish_key(conn, key: str, entity_id: str):
    return execute(conn, "UPDATE idempotency_keys SET entity_id=? WHERE idempotency_key=?", (entity_id, key))

