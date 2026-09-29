"""SQL owned by the repository. Domain modules call these functions."""
from __future__ import annotations

from aipf.repo.sqlio import execute, one, rows

def q_clinical_18948(conn, p0):
    return rows(conn, "SELECT id, number, status, payment_status, net_paise, due_paise, paid_paise FROM invoices WHERE encounter_id=? ORDER BY created_at", (p0,))

def q_clinical_28341(conn, p0):
    return rows(conn, "SELECT * FROM invoices WHERE patient_id=? ORDER BY created_at", (p0,))

def q_clinical_29673(conn, p0):
    return rows(conn, "SELECT id, number, status, payment_status, net_paise, due_paise, paid_paise, created_at, bill_type FROM invoices WHERE patient_id=? ORDER BY created_at DESC", (p0,))

def q_billing_747(conn, p0):
    return one(conn, "SELECT * FROM invoices WHERE id=?", (p0,))

def q_billing_882(conn, p0):
    return rows(conn, "SELECT * FROM invoice_items WHERE invoice_id=? ORDER BY sort_order, created_at", (p0,))

def q_billing_2077(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8):
    return execute(conn, """UPDATE invoices SET gross_paise=?, tax_paise=?, net_paise=?, paid_paise=?, due_paise=?,
           deposit_applied_paise=?, payment_status=?, updated_at=? WHERE id=?""", (p0, p1, p2, p3, p4, p5, p6, p7, p8))

def q_billing_2663(conn, p0, p1):
    return one(conn, "SELECT * FROM invoices WHERE id=? OR number=?", (p0, p1))

def q_billing_2811(conn, p0):
    return rows(conn, "SELECT * FROM invoice_items WHERE invoice_id=? ORDER BY sort_order, created_at", (p0,))

def q_billing_3070(conn, p0):
    return rows(conn, "SELECT id, revision_no, reason, user_id, at FROM invoice_revisions WHERE invoice_id=? ORDER BY id", (p0,))

def q_billing_4421(conn, p0, p1, p2):
    return one(conn, """SELECT * FROM invoices WHERE patient_id=? AND status='DRAFT'
           AND IFNULL(encounter_id,'')=IFNULL(?, '') AND IFNULL(admission_id,'')=IFNULL(?, '')
           ORDER BY created_at DESC LIMIT 1""", (p0, p1, p2))

def q_billing_4897(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8, p9):
    return execute(conn, """INSERT INTO invoices(id, number, patient_id, encounter_id, admission_id, bill_type, status, payment_status,
           created_by, created_at, updated_at, is_sample)
           VALUES (?,?,?,?,?,?, 'DRAFT','UNPAID', ?, ?, ?, ?)""", (p0, p1, p2, p3, p4, p5, p6, p7, p8, p9))

def q_billing_5452(conn, p0):
    return one(conn, "SELECT * FROM invoices WHERE id=?", (p0,))

def q_billing_5617(conn, p0):
    return one(conn, "SELECT * FROM invoices WHERE id=?", (p0,))

def q_billing_6414(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11, p12, p13, p14):
    return execute(conn, """INSERT INTO invoice_items(id, invoice_id, source_module, source_id, master_item_id, description, category,
           rate_paise, qty, unit, discount_paise, tax_paise, amount_paise, sort_order, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11, p12, p13, p14))

def q_billing_7233(conn, p0):
    return one(conn, "SELECT * FROM invoice_items WHERE id=?", (p0,))

def q_billing_7366(conn, p0):
    return one(conn, "SELECT * FROM invoices WHERE id=?", (p0,))

def q_billing_7554(conn, p0):
    return execute(conn, "DELETE FROM invoice_items WHERE id=?", (p0,))

def lock_invoice(conn, invoice_id: str):
    sql = "SELECT * FROM invoices WHERE id=?"
    if getattr(conn, "dialect", "") == "postgres":
        sql += " FOR UPDATE"
    return one(conn, sql, (invoice_id,))

def update_draft_line(conn, qty, rate, amount, description, source_id, unit, item_id):
    return execute(
        conn,
        """UPDATE invoice_items
           SET qty=?, rate_paise=?, amount_paise=?, description=?, source_id=?, unit=?
           WHERE id=?""",
        (qty, rate, amount, description, source_id, unit, item_id),
    )

def set_notes(conn, notes: str, stamp: str, invoice_id: str):
    return execute(conn, "UPDATE invoices SET notes=?, updated_at=? WHERE id=?", (notes, stamp, invoice_id))

def claim_issue_key(conn, key: str, request_hash: str, at: str) -> dict:
    existing = one(conn, "SELECT * FROM idempotency_keys WHERE idempotency_key=?", (key,))
    if existing:
        if existing["request_hash"] != request_hash or existing["scope"] != "billing_issue":
            return {"status": "conflict"}
        if existing.get("entity_id"):
            return {"status": "replay", "entity_id": existing["entity_id"]}
        return {"status": "in_progress"}
    conn.execute("SAVEPOINT bill_issue_key")
    try:
        execute(
            conn,
            """INSERT INTO idempotency_keys(idempotency_key, scope, request_hash, entity_id, created_at)
               VALUES (?,?,?,?,?)""",
            (key, "billing_issue", request_hash, None, at),
        )
        conn.execute("RELEASE SAVEPOINT bill_issue_key")
        return {"status": "claimed"}
    except Exception as exc:
        conn.execute("ROLLBACK TO SAVEPOINT bill_issue_key")
        text = str(exc).lower()
        if "unique" in text or "duplicate" in text:
            return {"status": "in_progress"}
        raise

def finish_issue_key(conn, key: str, entity_id: str):
    return execute(conn, "UPDATE idempotency_keys SET entity_id=? WHERE idempotency_key=?", (entity_id, key))

def q_billing_7890(conn, p0):
    return one(conn, "SELECT * FROM invoices WHERE id=?", (p0,))

def q_billing_8189(conn, p0, p1, p2, p3):
    return execute(conn, "UPDATE invoices SET discount_paise=?, discount_reason=?, updated_at=? WHERE id=?", (p0, p1, p2, p3))

def q_billing_9622(conn, p0, p1, p2, p3):
    return execute(conn, """UPDATE invoices SET status='FINALIZED', finalized_at=?, finalized_by=?, revision=revision+1, updated_at=?
           WHERE id=? AND status='DRAFT'""", (p0, p1, p2, p3))

def q_billing_9882(conn, p0, p1, p2, p3, p4, p5, p6, p7):
    return execute(conn, """INSERT INTO invoice_revisions(invoice_id, revision_no, reason, user_id, workstation, at, before_json, after_json)
           VALUES (?,?,?,?,?,?,?,?)""", (p0, p1, p2, p3, p4, p5, p6, p7))

def q_billing_10789(conn, p0):
    return one(conn, "SELECT * FROM invoices WHERE id=?", (p0,))

def q_billing_12210(conn, p0):
    return one(conn, "SELECT * FROM invoices WHERE id=?", (p0,))

def q_billing_16229(conn, p0, p1, p2, p3):
    return execute(conn, "UPDATE invoices SET status='VOID', voided_at=?, void_reason=?, payment_status='VOID', due_paise=0, updated_at=?, revision=revision+1 WHERE id=? AND status!='VOID'", (p0, p1, p2, p3))

def q_billing_16477(conn, p0, p1, p2, p3, p4, p5, p6, p7):
    return execute(conn, """INSERT INTO invoice_revisions(invoice_id, revision_no, reason, user_id, workstation, at, before_json, after_json)
           VALUES (?,?,?,?,?,?,?,?)""", (p0, p1, p2, p3, p4, p5, p6, p7))

def q_billing_17200(conn, p0):
    return one(conn, "SELECT * FROM invoices WHERE id=?", (p0,))

def q_billing_18004(conn, p0, p1):
    return execute(conn, "UPDATE invoices SET revision=revision+1, updated_at=? WHERE id=?", (p0, p1))

def q_billing_18153(conn, p0, p1, p2, p3, p4, p5, p6, p7):
    return execute(conn, """INSERT INTO invoice_revisions(invoice_id, revision_no, reason, user_id, workstation, at, before_json, after_json)
           VALUES (?,?,?,?,?,?,?,?)""", (p0, p1, p2, p3, p4, p5, p6, p7))

def q_wards_6380(conn, p0):
    return rows(conn, "SELECT id, number, status, payment_status, net_paise, due_paise FROM invoices WHERE admission_id=?", (p0,))

def q_system_33833(conn, p0, p1):
    return rows(conn, "SELECT id, number, patient_id, status, payment_status, net_paise FROM invoices WHERE number LIKE ? OR id LIKE ? ORDER BY created_at DESC LIMIT 8", (p0, p1))

def q_system_35097(conn):
    return one(conn, "SELECT COALESCE(SUM(due_paise),0) AS n FROM invoices WHERE status='FINALIZED' AND due_paise>0", ())

def q_system_36398(conn):
    return one(conn, "SELECT COUNT(*) AS n FROM invoices WHERE status='DRAFT'", ())

def q_system_39074(conn):
    return one(conn, "SELECT COALESCE(SUM(due_paise),0) AS n FROM invoices WHERE status='FINALIZED'", ())

def q_system_40532(conn):
    return rows(conn, "SELECT number, patient_id, payment_status, net_paise, paid_paise, due_paise FROM invoices WHERE status='FINALIZED' AND due_paise>0", ())

def q_notify_8207(conn, p0):
    return one(conn, "SELECT * FROM invoices WHERE id=?", (p0,))

def q_seed_24489(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11):
    return execute(conn, """INSERT INTO invoices(id, number, patient_id, encounter_id, admission_id, bill_type, status, payment_status, gross_paise, discount_paise, tax_paise, net_paise, paid_paise, due_paise, created_by, created_at, updated_at, is_sample)
               VALUES (?,?,?,?,?,?,?,'UNPAID',?,0,0,?,0,?, 'U-RECEPTION', ?, ?, 1)""", (p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11))

def q_seed_24947(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8):
    return execute(conn, """INSERT INTO invoice_items(id, invoice_id, source_module, source_id, description, category, rate_paise, qty, unit, discount_paise, tax_paise, amount_paise, created_at)
               VALUES (?,?,?,?,?,?,?,1,'visit',0,0,?,?)""", (p0, p1, p2, p3, p4, p5, p6, p7, p8))

def q_seed_25345(conn, p0, p1, p2):
    return execute(conn, """INSERT INTO invoices(id, number, patient_id, encounter_id, bill_type, status, payment_status, gross_paise, discount_paise, tax_paise, net_paise, paid_paise, due_paise, finalized_at, finalized_by, created_by, created_at, updated_at, is_sample)
           VALUES ('INV-S5','AIPF-BILL-2026-000005','P-000007','OPD-2026-000005','OPD','FINALIZED','PARTIAL',45000,0,0,45000,20000,25000,?, 'U-BILL','U-BILL',?,?,1)""", (p0, p1, p2))

def q_seed_25817(conn, p0):
    return execute(conn, """INSERT INTO invoice_items(id, invoice_id, source_module, source_id, description, category, rate_paise, qty, unit, amount_paise, created_at)
           VALUES ('II-5A','INV-S5','opd','OPD-2026-000005','General OPD','CONSULTATION',20000,1,'visit',20000,?)""", (p0,))

def q_seed_27680(conn, p0, p1):
    return execute(conn, """INSERT INTO invoices(id, number, patient_id, encounter_id, admission_id, bill_type, status, payment_status, gross_paise, net_paise, due_paise, created_by, created_at, updated_at, is_sample)
           VALUES ('INV-S7','AIPF-BILL-2026-000007','P-000005','OPD-2026-000007','ADM-2026-000001','IPD','DRAFT','UNPAID',120000,120000,120000,'U-NURSE',?,?,1)""", (p0, p1))

def q_seed_28089(conn, p0):
    return execute(conn, """INSERT INTO invoice_items(id, invoice_id, source_module, source_id, description, category, rate_paise, qty, unit, amount_paise, created_at)
           VALUES ('II-7A','INV-S7','opd','OPD-2026-000007','Specialist OPD','CONSULTATION',40000,1,'visit',40000,?)""", (p0,))

def q_seed_28401(conn, p0):
    return execute(conn, """INSERT INTO invoice_items(id, invoice_id, source_module, source_id, description, category, rate_paise, qty, unit, amount_paise, created_at)
           VALUES ('II-7B','INV-S7','admission','ADM-2026-000001','Bed / room charge — admission day','IPD',80000,1,'day',80000,?)""", (p0,))

def list_invoices(conn, q: str = "", status: str = "", payment_status: str = "", patient_id: str = "", limit: int = 80):
    sql = "SELECT * FROM invoices WHERE 1=1"
    params: list = []
    if patient_id:
        sql += " AND patient_id=?"
        params.append(patient_id)
    if status:
        sql += " AND status=?"
        params.append(status)
    if payment_status:
        sql += " AND payment_status=?"
        params.append(payment_status)
    if q:
        sql += " AND (number LIKE ? OR patient_id LIKE ? OR id LIKE ?)"
        like = f"%{q.strip()}%"
        params.extend([like, like, like])
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    return rows(conn, sql, params)


def lock_invoice(conn, invoice_id: str):
    if getattr(conn, "dialect", "") == "postgres":
        return one(conn, "SELECT * FROM invoices WHERE id=? FOR UPDATE", (invoice_id,))
    return one(conn, "SELECT * FROM invoices WHERE id=?", (invoice_id,))


def service_rate(conn, service_id: str):
    return one(conn, "SELECT id, name, category, rate_paise, unit, active FROM services WHERE id=?", (service_id,))


def lab_price(conn, test_id: str):
    return one(conn, "SELECT id, name, price_paise, active FROM lab_tests WHERE id=?", (test_id,))


def opd_fee(conn, opd_type_id: str):
    return one(conn, "SELECT id, name, fee_paise, active FROM opd_types WHERE id=?", (opd_type_id,))


def batch_rate(conn, batch_id: str):
    return one(conn, "SELECT id, product_id, sale_rate_paise, active FROM batches WHERE id=?", (batch_id,))


def procedure_master(conn, procedure_id: str):
    return one(conn, "SELECT id, name, meta, active FROM master_items WHERE id=? AND list_type='procedure'", (procedure_id,))


def insert_adjustment(conn, adjustment_id, invoice_id, amount, description, reason, status, user_id, at, approved_by, approved_at):
    return execute(
        conn,
        """INSERT INTO financial_adjustments(
             id, invoice_id, amount_paise, description, reason, status, created_by, created_at, approved_by, approved_at
           ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (adjustment_id, invoice_id, amount, description, reason, status, user_id, at, approved_by, approved_at),
    )
