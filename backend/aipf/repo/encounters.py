"""SQL owned by the repository. Domain modules call these functions."""
from __future__ import annotations

from aipf.repo.sqlio import execute, one, rows

def q_clinical_8579(conn, p0, p1):
    return rows(conn, """SELECT e.*, t.name AS opd_type_name, t.validity_days, t.fee_paise AS type_fee
           FROM encounters e JOIN opd_types t ON t.id = e.opd_type_id
           WHERE e.patient_id=? AND e.status!='CANCELLED' AND e.fee_paise>0 AND e.validity_until>=?
           ORDER BY e.validity_until DESC""", (p0, p1))

def q_clinical_9604(conn, p0, p1):
    return one(conn, "SELECT * FROM encounters WHERE id=? AND patient_id=?", (p0, p1))

def q_clinical_10306(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11, p12, p13, p14):
    return execute(conn, """INSERT INTO encounters(id, patient_id, opd_type_id, parent_opd_id, fee_paise, fee_waived_reason, validity_until,
           doctor_id, department_id, status, chief_complaint, visit_kind, arrived_at, created_by, created_at, is_sample)
           VALUES (?,?,?,?,?,?,?,?,?,'OPEN',?,?,?,?,?,?)""", (p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11, p12, p13, p14))

def q_clinical_12223(conn, p0):
    return one(conn, "SELECT * FROM encounters WHERE id=?", (p0,))

def q_clinical_12369(conn, p0):
    return one(conn, "SELECT * FROM queue_entries WHERE encounter_id=? AND status NOT IN ('COMPLETED','CANCELLED')", (p0,))

def q_clinical_12586(conn, p0, p1, p2):
    return execute(conn, "UPDATE queue_entries SET doctor_id=?, department_id=? WHERE id=?", (p0, p1, p2))

def q_clinical_12740(conn, p0, p1):
    return execute(conn, "UPDATE encounters SET doctor_id=? WHERE id=?", (p0, p1))

def q_clinical_13014(conn, p0):
    return one(conn, "SELECT * FROM queue_entries WHERE id=?", (p0,))

def q_clinical_13101(conn, p0):
    return one(conn, "SELECT COALESCE(MAX(token_no),0) AS n FROM queue_entries WHERE substr(created_at,1,10)=?", (p0,))

def allocate_token(conn, day: str) -> int:
    execute(
        conn,
        """INSERT INTO queue_days(day, next_token)
           SELECT ?, COALESCE(MAX(token_no), 0) FROM queue_entries WHERE service_day=?
           ON CONFLICT(day) DO NOTHING""",
        (day, day),
    )
    row = one(conn, "UPDATE queue_days SET next_token = next_token + 1 WHERE day=? RETURNING next_token", (day,))
    return int(row["next_token"])


def insert_queue_entry(conn, qid, token, day, encounter_id, patient_id, doctor_id, department_id, priority, label, arrived_at, created_at):
    return execute(
        conn,
        """INSERT INTO queue_entries(id, token_no, encounter_id, patient_id, doctor_id, department_id, status, priority,
           priority_label, arrived_at, created_at, service_day)
           VALUES (?,?,?,?,?,?, 'WAITING', ?, ?, ?, ?, ?)""",
        (qid, token, encounter_id, patient_id, doctor_id, department_id, priority, label, arrived_at, created_at, day),
    )


def insert_consultation_revision(conn, revision_id, consultation_id, encounter_id, doctor_id, diagnosis, created_at):
    return execute(
        conn,
        """INSERT INTO consultation_revisions(id, consultation_id, encounter_id, doctor_id, diagnosis, created_at)
           VALUES (?,?,?,?,?,?)""",
        (revision_id, consultation_id, encounter_id, doctor_id, diagnosis, created_at),
    )


def q_clinical_13312(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8, p9):
    return execute(conn, """INSERT INTO queue_entries(id, token_no, encounter_id, patient_id, doctor_id, department_id, status, priority,
           priority_label, arrived_at, created_at)
           VALUES (?,?,?,?,?,?, 'WAITING', ?, ?, ?, ?)""", (p0, p1, p2, p3, p4, p5, p6, p7, p8, p9))

def q_clinical_13781(conn, p0, p1):
    return execute(conn, "UPDATE encounters SET doctor_id=? WHERE id=?", (p0, p1))

def q_clinical_14057(conn, p0):
    return one(conn, "SELECT * FROM queue_entries WHERE id=?", (p0,))

def q_clinical_14297(conn, p0):
    return one(conn, "SELECT * FROM queue_entries WHERE id=?", (p0,))

def q_clinical_14792(conn, p0, p1, p2, p3, p4):
    return execute(conn, "UPDATE queue_entries SET status=?, called_at=?, started_at=?, completed_at=? WHERE id=?", (p0, p1, p2, p3, p4))

def q_clinical_15005(conn, p0, p1):
    return execute(conn, "UPDATE encounters SET status='COMPLETED', completed_at=? WHERE id=? AND status!='CANCELLED'", (p0, p1))

def q_clinical_15183(conn, p0):
    return execute(conn, "UPDATE encounters SET status='CANCELLED' WHERE id=?", (p0,))

def q_clinical_15493(conn, p0):
    return one(conn, "SELECT * FROM queue_entries WHERE id=?", (p0,))

def q_clinical_16273(conn, p0):
    return one(conn, "SELECT id, opd_type_id, validity_until, fee_paise, parent_opd_id, chief_complaint, status FROM encounters WHERE id=?", (p0,))

def q_clinical_17771(conn, p0):
    return one(conn, "SELECT * FROM encounters WHERE id=?", (p0,))

def q_clinical_18357(conn, p0):
    return one(conn, "SELECT * FROM queue_entries WHERE encounter_id=? ORDER BY created_at DESC LIMIT 1", (p0,))

def q_clinical_18502(conn, p0):
    return one(conn, "SELECT * FROM consultations WHERE encounter_id=? ORDER BY updated_at DESC LIMIT 1", (p0,))

def q_clinical_18647(conn, p0):
    return rows(conn, "SELECT * FROM prescriptions WHERE encounter_id=? ORDER BY created_at DESC", (p0,))

def q_clinical_18816(conn, p0):
    return rows(conn, "SELECT * FROM prescription_items WHERE prescription_id=? ORDER BY sort_order", (p0,))

def q_clinical_19669(conn, p0):
    return one(conn, "SELECT * FROM encounters WHERE id=?", (p0,))

def q_clinical_19830(conn, p0):
    return one(conn, "SELECT * FROM consultations WHERE encounter_id=?", (p0,))

def q_clinical_20373(conn, params):
    return execute(conn, """UPDATE consultations SET symptoms=:symptoms, findings=:findings, diagnosis=:diagnosis, notes=:notes,
               instructions=:instructions, follow_up=:follow_up, updated_at=:updated_at WHERE id=:id""", params)

def q_clinical_20906(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11):
    return execute(conn, """INSERT INTO consultations(id, encounter_id, patient_id, doctor_id, symptoms, findings, diagnosis, notes, instructions, follow_up, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11))

def q_clinical_21503(conn, p0):
    return one(conn, "SELECT * FROM queue_entries WHERE encounter_id=? AND status NOT IN ('COMPLETED','CANCELLED')", (p0,))

def q_clinical_21835(conn, p0):
    return one(conn, "SELECT * FROM consultations WHERE id=?", (p0,))

def q_clinical_22068(conn, p0):
    return one(conn, "SELECT * FROM prescriptions WHERE id=?", (p0,))

def q_clinical_22450(conn, p0):
    return one(conn, "SELECT * FROM encounters WHERE id=?", (p0,))

def q_clinical_22767(conn, p0):
    return one(conn, "SELECT id FROM consultations WHERE encounter_id=? ORDER BY updated_at DESC LIMIT 1", (p0,))

def q_clinical_22888(conn, p0, p1, p2, p3, p4, p5, p6, p7):
    return execute(conn, """INSERT INTO prescriptions(id, encounter_id, consultation_id, patient_id, doctor_id, status, notes, created_at, updated_at)
               VALUES (?,?,?,?,?,'DRAFT',?,?,?)""", (p0, p1, p2, p3, p4, p5, p6, p7))

def q_clinical_23300(conn, p0, p1, p2):
    return execute(conn, "UPDATE prescriptions SET notes=?, updated_at=? WHERE id=?", (p0, p1, p2))

def q_clinical_23452(conn, p0):
    return execute(conn, "DELETE FROM prescription_items WHERE prescription_id=?", (p0,))

def q_clinical_23703(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11, p12, p13, p14, p15):
    return execute(conn, """INSERT INTO prescription_items(id, prescription_id, product_id, medicine_name, strength, dose, frequency, route,
               duration, duration_days, timing, food_instruction, quantity, unit, notes, sort_order)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11, p12, p13, p14, p15))

def q_clinical_24993(conn, p0):
    return one(conn, "SELECT * FROM prescriptions WHERE id=?", (p0,))

def q_clinical_25144(conn, p0):
    return rows(conn, "SELECT * FROM prescription_items WHERE prescription_id=? ORDER BY sort_order", (p0,))

def q_clinical_25896(conn, p0, p1, p2):
    return execute(conn, "UPDATE prescriptions SET status='FINALIZED', finalized_at=?, updated_at=? WHERE id=?", (p0, p1, p2))

def q_clinical_26073(conn, p0):
    return one(conn, "SELECT * FROM queue_entries WHERE encounter_id=? AND status NOT IN ('COMPLETED','CANCELLED')", (p0,))

def q_clinical_26838(conn, p0):
    return rows(conn, "SELECT * FROM encounters WHERE patient_id=? ORDER BY arrived_at", (p0,))

def q_clinical_27136(conn, p0):
    return rows(conn, "SELECT * FROM prescriptions WHERE patient_id=? ORDER BY created_at", (p0,))

def q_clinical_29080(conn, p0):
    return rows(conn, "SELECT * FROM encounters WHERE patient_id=? ORDER BY arrived_at DESC", (p0,))

def q_clinical_29204(conn, p0):
    return rows(conn, "SELECT * FROM prescriptions WHERE patient_id=? ORDER BY created_at DESC", (p0,))

def q_pharmacy_11164(conn, p0):
    return rows(conn, "SELECT * FROM prescription_items WHERE prescription_id=? ORDER BY sort_order", (p0,))

def q_pharmacy_11761(conn, p0):
    return one(conn, "SELECT * FROM prescriptions WHERE id=?", (p0,))

def q_pharmacy_12331(conn, p0, p1):
    return one(conn, "SELECT * FROM prescription_items WHERE id=? AND prescription_id=?", (p0, p1))

def prescription_item(conn, item_id: str):
    return one(conn, "SELECT * FROM prescription_items WHERE id=?", (item_id,))

def q_pharmacy_16054(conn, p0, p1, p2, p3):
    return execute(conn, "UPDATE prescription_items SET dispensed_qty=?, status=?, product_id=COALESCE(product_id, ?) WHERE id=?", (p0, p1, p2, p3))

def q_pharmacy_16303(conn, p0):
    return one(conn, """SELECT COUNT(*) AS n FROM prescription_items
           WHERE prescription_id=? AND status NOT IN ('DISPENSED','SUBSTITUTED','CANCELLED')
             AND (quantity IS NULL OR quantity=0 OR dispensed_qty+0.0001 < quantity)""", (p0,))

def q_pharmacy_16748(conn, p0):
    return rows(conn, "SELECT * FROM prescription_items WHERE prescription_id=?", (p0,))

def q_pharmacy_17035(conn, p0, p1, p2):
    return execute(conn, "UPDATE prescriptions SET status=?, updated_at=? WHERE id=?", (p0, p1, p2))

def q_billing_19021(conn, p0):
    return one(conn, "SELECT * FROM encounters WHERE id=?", (p0,))

def q_billing_22969(conn, p0):
    return one(conn, "SELECT * FROM prescriptions WHERE id=?", (p0,))

def q_billing_23196(conn, p0):
    return rows(conn, "SELECT * FROM prescription_items WHERE prescription_id=? ORDER BY sort_order", (p0,))

def q_wards_23589(conn, p0):
    return one(conn, "SELECT id, status FROM queue_entries WHERE encounter_id=? AND status NOT IN ('COMPLETED','CANCELLED')", (p0,))

def prescriptions_matching(conn, ident: str):
    return rows(conn, "SELECT id, patient_id, encounter_id, status FROM prescriptions WHERE upper(id) LIKE ? ORDER BY created_at DESC LIMIT 8", (ident,))


def q_system_34031(conn, p0):
    return rows(conn, "SELECT id, patient_id, status, arrived_at FROM encounters WHERE id LIKE ? ORDER BY arrived_at DESC LIMIT 8", (p0,))

def q_system_36212(conn, p0):
    return one(conn, "SELECT COUNT(*) AS n FROM encounters WHERE substr(arrived_at,1,10)=?", (p0,))

def q_system_36961(conn):
    return one(conn, "SELECT COUNT(*) AS n FROM prescriptions WHERE status IN ('FINALIZED','PARTIAL')", ())

def q_system_37600(conn):
    return one(conn, "SELECT COUNT(*) AS n FROM queue_entries WHERE status NOT IN ('COMPLETED','CANCELLED')", ())

def q_system_38657(conn, p0):
    return one(conn, "SELECT COUNT(*) AS n FROM encounters WHERE substr(arrived_at,1,10)=?", (p0,))

def q_seed_19829(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11):
    return execute(conn, """INSERT INTO encounters(id, patient_id, opd_type_id, fee_paise, validity_until, doctor_id, department_id, status, chief_complaint, visit_kind, arrived_at, created_by, created_at, is_sample)
               VALUES (?,?,?,?,?,?,?,?,?,'OPD',?,?,?,1)""", (p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11))

def q_seed_21260(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10):
    return execute(conn, """INSERT INTO queue_entries(id, token_no, encounter_id, patient_id, doctor_id, department_id, status, priority, arrived_at, called_at, started_at, created_at, service_day)
               VALUES (?,?,?,?,?,?,?,0,?,?,?,?, substr(?,1,10))""", (p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p7))

def q_seed_22044(conn, created_at, updated_at):
    return execute(conn, """INSERT INTO consultations(id, encounter_id, patient_id, doctor_id, symptoms, findings, diagnosis, notes, instructions, follow_up, created_at, updated_at)
           VALUES ('CN-FATIMA','OPD-2026-000003','P-000004','U-ANITA','Amenorrhoea, mild nausea','Uterus corresponding to dates','Antenatal — routine','Continue iron and calcium.','Rest, warning signs explained.','4 weeks',?,?)""", (created_at, updated_at))

def q_seed_22488(conn, p0, p1, p2):
    return execute(conn, """INSERT INTO prescriptions(id, encounter_id, patient_id, doctor_id, status, notes, finalized_at, created_at, updated_at)
           VALUES ('RX-2026-000001','OPD-2026-000004','P-000006','U-DIRECTOR','FINALIZED','',?,?,?)""", (p0, p1, p2))

def q_seed_22772(conn):
    return execute(conn, """INSERT INTO prescription_items(id, prescription_id, product_id, medicine_name, strength, dose, frequency, route, duration, duration_days, food_instruction, quantity, unit, status, sort_order)
           VALUES ('RI-1','RX-2026-000001','PR-PARA','Paracetamol','500 mg','1-0-1','Twice daily','Oral','5 Days',5,'After food',10,'Tablet','PENDING',0)""", ())

def q_seed_23156(conn):
    return execute(conn, """INSERT INTO prescription_items(id, prescription_id, product_id, medicine_name, strength, dose, frequency, route, duration, duration_days, food_instruction, quantity, unit, status, sort_order)
           VALUES ('RI-2','RX-2026-000001','PR-PAN','Pantoprazole','40 mg','1-0-0','Once daily','Oral','5 Days',5,'Before food',5,'Tablet','PENDING',1)""", ())

def list_queue(conn, status: str = "", doctor_id: str = ""):
    sql = "SELECT * FROM queue_entries WHERE status NOT IN ('COMPLETED','CANCELLED')"
    params: list = []
    if status:
        sql = "SELECT * FROM queue_entries WHERE status=?"
        params = [status]
    if doctor_id:
        sql += " AND doctor_id=?"
        params.append(doctor_id)
    sql += " ORDER BY priority DESC, token_no ASC"
    return rows(conn, sql, params)
