"""SQL owned by the repository. Domain modules call these functions."""
from __future__ import annotations

from aipf.repo.sqlio import execute, one, rows

def q_system_2010(conn):
    return one(conn, "SELECT 1 AS ok", ())

def q_system_5208(conn):
    return one(conn, "SELECT * FROM backups WHERE status IN ('LOCAL_OK','VERIFIED','PARTIAL') ORDER BY started_at DESC LIMIT 1", ())

def q_system_6364(conn):
    return one(conn, "SELECT * FROM backups WHERE cloud_status IS NOT NULL ORDER BY started_at DESC LIMIT 1", ())

def q_system_8788(conn, p0, p1, p2):
    return execute(conn, "INSERT INTO health_snapshots(at, overall, payload) VALUES (?,?,?)", (p0, p1, p2))

def q_system_11775(conn):
    return execute(conn, "PRAGMA wal_checkpoint(TRUNCATE)", ())

def q_system_13363(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11, p12, p13):
    return execute(conn, """INSERT INTO backups(id, kind, status, local_path, size_bytes, checksum, cloud_status, cloud_error, cloud_key, started_at, finished_at, created_by, notes, verified_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11, p12, p13))

def q_system_14129(conn, p0):
    return one(conn, "SELECT * FROM backups WHERE id=?", (p0,))

def q_system_14379(conn, p0, p1, p2, p3, p4, p5, p6, p7):
    return execute(conn, """INSERT INTO backups(id, kind, status, local_path, cloud_status, cloud_error, started_at, finished_at, created_by, notes)
               VALUES (?,?, 'FAILED', ?, 'FAILED', ?, ?, ?, ?, ?)""", (p0, p1, p2, p3, p4, p5, p6, p7))

def q_system_20264(conn, p0):
    return one(conn, "SELECT * FROM backups WHERE id=?", (p0,))

def q_system_20805(conn, p0, p1, p2):
    return execute(conn, "UPDATE backups SET verified_at=?, notes=? WHERE id=?", (p0, p1, p2))

def q_system_21054(conn, p0):
    return one(conn, "SELECT * FROM backups WHERE id=?", (p0,))

def q_system_21169(conn):
    return rows(conn, "SELECT id, kind, status, size_bytes, checksum, cloud_status, cloud_error, started_at, finished_at, created_by, notes, verified_at FROM backups ORDER BY started_at DESC", ())

def q_system_23158(conn, p0):
    return one(conn, "SELECT * FROM backups WHERE id=?", (p0,))

def q_system_23446(conn, p0):
    return execute(conn, "DELETE FROM backups WHERE id=?", (p0,))

def q_system_23793(conn):
    return rows(conn, "SELECT * FROM backups ORDER BY started_at DESC", ())

def q_system_24137(conn, p0):
    return execute(conn, "DELETE FROM backups WHERE id=?", (p0,))

def q_system_30786(conn, p0):
    return one(conn, "SELECT id FROM leads WHERE external_id=?", (p0,))

def q_system_30922(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10):
    return execute(conn, """INSERT INTO leads(id, external_id, name, phone, email, message, source, status, raw_json, received_at, synced_at, created_at)
                   VALUES (?,?,?,?,?,?,?,'NEW',?,?,?,?)""", (p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10))

def q_system_32017(conn, p0):
    return rows(conn, "SELECT id, external_id, name, phone, email, message, source, status, patient_id, received_at, created_at FROM leads WHERE status=? ORDER BY created_at DESC", (p0,))

def q_system_32224(conn):
    return rows(conn, "SELECT id, external_id, name, phone, email, message, source, status, patient_id, received_at, created_at FROM leads ORDER BY created_at DESC LIMIT 200", ())

def q_system_32552(conn, p0, p1, p2, p3, p4, p5, p6, p7):
    return execute(conn, """INSERT INTO leads(id, name, phone, email, message, source, status, created_at, received_at)
           VALUES (?,?,?,?,?,?, 'NEW', ?, ?)""", (p0, p1, p2, p3, p4, p5, p6, p7))

def q_system_33037(conn, p0):
    return one(conn, "SELECT * FROM leads WHERE id=?", (p0,))

def q_system_33180(conn, p0):
    return execute(conn, "UPDATE leads SET status='ARCHIVED' WHERE id=?", (p0,))

def q_system_33329(conn, p0):
    return one(conn, "SELECT * FROM leads WHERE id=?", (p0,))

def q_system_35460(conn):
    return one(conn, "SELECT overall, at FROM health_snapshots ORDER BY id DESC LIMIT 1", ())

def q_system_35557(conn):
    return one(conn, "SELECT id, status, started_at, cloud_status FROM backups ORDER BY started_at DESC LIMIT 1", ())

def q_system_37369(conn):
    return one(conn, "SELECT COUNT(*) AS n FROM leads WHERE status='NEW'", ())

def q_system_45189(conn):
    return one(conn, "SELECT COUNT(*) AS n FROM backups WHERE status!='FAILED'", ())

def q_seed_29469(conn, p0, p1):
    return execute(conn, """INSERT INTO leads(id, name, phone, email, message, source, status, created_at, received_at)
           VALUES ('LD-1','Ritu Malhotra','9811100099','ritu.example@email.com','Asked about orthopedic OPD tomorrow morning.','website','NEW',?,?)""", (p0, p1))

def purge_sample_patients(conn, ids: list[str]) -> list[str]:
    if not ids:
        return []
    marks = ",".join("?" for _ in ids)
    stored = [row["stored_name"] for row in rows(conn, f"SELECT stored_name FROM documents WHERE patient_id IN ({marks})", ids)]
    rx_ids = [row["id"] for row in rows(conn, f"SELECT id FROM prescriptions WHERE patient_id IN ({marks})", ids)]
    if rx_ids:
        q = ",".join("?" for _ in rx_ids)
        execute(conn, f"DELETE FROM dispense_idempotency WHERE prescription_id IN ({q})", rx_ids)
        execute(conn, f"DELETE FROM prescription_items WHERE prescription_id IN ({q})", rx_ids)
        execute(conn, f"DELETE FROM dispense_lines WHERE prescription_id IN ({q})", rx_ids)
    execute(conn, f"DELETE FROM prescriptions WHERE patient_id IN ({marks})", ids)
    execute(conn, f"DELETE FROM consultations WHERE patient_id IN ({marks})", ids)
    execute(conn, f"DELETE FROM queue_entries WHERE patient_id IN ({marks})", ids)
    inv_ids = [row["id"] for row in rows(conn, f"SELECT id FROM invoices WHERE patient_id IN ({marks})", ids)]
    if inv_ids:
        q = ",".join("?" for _ in inv_ids)
        item_scope = f"SELECT id FROM invoice_items WHERE invoice_id IN ({q})"
        execute(conn, f"DELETE FROM admission_charges WHERE invoice_item_id IN ({item_scope})", inv_ids)
        execute(conn, f"DELETE FROM ot_charge_links WHERE invoice_item_id IN ({item_scope})", inv_ids)
        execute(conn, f"UPDATE dispense_lines SET invoice_item_id=NULL WHERE invoice_item_id IN ({item_scope})", inv_ids)
        execute(conn, f"UPDATE lab_order_items SET invoice_item_id=NULL WHERE invoice_item_id IN ({item_scope})", inv_ids)
        execute(conn, f"DELETE FROM financial_adjustments WHERE invoice_id IN ({q})", inv_ids)
        execute(conn, f"DELETE FROM invoice_items WHERE invoice_id IN ({q})", inv_ids)
        execute(conn, f"DELETE FROM invoice_revisions WHERE invoice_id IN ({q})", inv_ids)
        execute(conn, f"DELETE FROM payments WHERE invoice_id IN ({q})", inv_ids)
    execute(conn, f"DELETE FROM payments WHERE patient_id IN ({marks})", ids)
    execute(conn, f"DELETE FROM invoices WHERE patient_id IN ({marks})", ids)
    execute(conn, f"DELETE FROM deposits WHERE patient_id IN ({marks})", ids)
    ot_ids = [row["id"] for row in rows(conn, f"SELECT id FROM ot_cases WHERE patient_id IN ({marks})", ids)]
    if ot_ids:
        q = ",".join("?" for _ in ot_ids)
        for table in ("ot_booking_history", "ot_bookings", "ot_charge_links", "ot_intraop_records", "ot_links", "ot_postop_records", "ot_preop_records", "ot_team_members"):
            execute(conn, f"DELETE FROM {table} WHERE ot_id IN ({q})", ot_ids)
    execute(conn, f"DELETE FROM ot_cases WHERE patient_id IN ({marks})", ids)
    from aipf.repo import lab as lab_sql
    lab_sql.delete_for_patients(conn, ids)
    lab_ids = [row["id"] for row in rows(conn, f"SELECT id FROM lab_orders WHERE patient_id IN ({marks})", ids)]
    if lab_ids:
        q = ",".join("?" for _ in lab_ids)
        execute(conn, f"DELETE FROM lab_results WHERE lab_order_item_id IN (SELECT id FROM lab_order_items WHERE order_id IN ({q}))", lab_ids)
        execute(conn, f"DELETE FROM lab_order_items WHERE order_id IN ({q})", lab_ids)
    execute(conn, f"DELETE FROM lab_orders WHERE patient_id IN ({marks})", ids)
    adm_ids = [row["id"] for row in rows(conn, f"SELECT id FROM admissions WHERE patient_id IN ({marks})", ids)]
    if adm_ids:
        q = ",".join("?" for _ in adm_ids)
        execute(conn, f"UPDATE beds SET status='AVAILABLE', current_admission_id=NULL WHERE current_admission_id IN ({q})", adm_ids)
        execute(conn, f"DELETE FROM admission_charges WHERE admission_id IN ({q})", adm_ids)
        execute(conn, f"DELETE FROM bed_movements WHERE admission_id IN ({q})", adm_ids)
    execute(conn, f"DELETE FROM admissions WHERE patient_id IN ({marks})", ids)
    execute(conn, f"UPDATE lab_order_items SET document_id=NULL WHERE document_id IN (SELECT id FROM documents WHERE patient_id IN ({marks}))", ids)
    execute(conn, f"UPDATE lab_results SET document_id=NULL WHERE document_id IN (SELECT id FROM documents WHERE patient_id IN ({marks}))", ids)
    execute(conn, f"UPDATE notifications SET document_id=NULL WHERE document_id IN (SELECT id FROM documents WHERE patient_id IN ({marks}))", ids)
    execute(conn, f"DELETE FROM documents WHERE patient_id IN ({marks})", ids)
    execute(conn, f"DELETE FROM consultation_revisions WHERE encounter_id IN (SELECT id FROM encounters WHERE patient_id IN ({marks}))", ids)
    execute(conn, f"DELETE FROM encounters WHERE patient_id IN ({marks})", ids)
    execute(conn, f"UPDATE leads SET patient_id=NULL WHERE patient_id IN ({marks})", ids)
    execute(conn, f"DELETE FROM notifications WHERE patient_id IN ({marks})", ids)
    execute(conn, f"DELETE FROM patients WHERE id IN ({marks})", ids)
    return stored
