"""Aggregate reads for the Today desk. Domain code does not write SQL."""
from __future__ import annotations

from aipf.repo.sqlio import one, rows

_HOSPITAL_BED = "id NOT LIKE 'BD-%'"


def count_on(conn, table: str, column: str, day: str, extra: str = ""):
    return one(conn, f"SELECT COUNT(*) AS n FROM {table} WHERE substr({column},1,10)=? {extra}", (day,))


def patients_on(conn, day: str):
    return one(conn, "SELECT COUNT(*) AS n FROM patients WHERE substr(created_at,1,10)=?", (day,))


def opd_on(conn, day: str):
    return one(conn, "SELECT COUNT(*) AS n FROM encounters WHERE substr(arrived_at,1,10)=?", (day,))


def queue_status(conn, status: str):
    return one(conn, "SELECT COUNT(*) AS n FROM queue_entries WHERE status=?", (status,))


def admissions_active(conn):
    return one(conn, "SELECT COUNT(*) AS n FROM admissions WHERE status NOT IN ('DISCHARGED','CANCELLED')", ())


def admissions_on(conn, day: str):
    return one(conn, "SELECT COUNT(*) AS n FROM admissions WHERE substr(admitted_at,1,10)=? OR substr(created_at,1,10)=?", (day, day))


def discharges_on(conn, day: str):
    return one(conn, "SELECT COUNT(*) AS n FROM admissions WHERE status='DISCHARGED' AND substr(COALESCE(discharged_at, updated_at, created_at),1,10)=?", (day,))


def prescriptions_on(conn, day: str):
    return one(conn, "SELECT COUNT(*) AS n FROM prescriptions WHERE substr(COALESCE(finalized_at, created_at),1,10)=?", (day,))


def documents_on(conn, day: str):
    return one(conn, "SELECT COUNT(*) AS n FROM documents WHERE active=1 AND substr(uploaded_at,1,10)=?", (day,))


def bills_on(conn, day: str):
    return one(conn, "SELECT COUNT(*) AS n FROM invoices WHERE substr(created_at,1,10)=?", (day,))


def bills_paid_on(conn, day: str):
    return one(conn, "SELECT COUNT(*) AS n FROM invoices WHERE status='FINALIZED' AND payment_status='PAID' AND substr(COALESCE(finalized_at, updated_at),1,10)=?", (day,))


def bills_partial(conn):
    return one(conn, "SELECT COUNT(*) AS n FROM invoices WHERE status='FINALIZED' AND payment_status='PARTIAL'", ())


def bills_due(conn):
    return one(conn, "SELECT COUNT(*) AS n FROM invoices WHERE status='FINALIZED' AND due_paise>0", ())


def refunds_on(conn, day: str):
    return one(conn, "SELECT COALESCE(SUM(amount_paise),0) AS n FROM payments WHERE kind='REFUND' AND substr(received_at,1,10)=?", (day,))


def movements_on(conn, day: str, kinds: tuple[str, ...]):
    marks = ",".join("?" for _ in kinds)
    return one(conn, f"SELECT COUNT(*) AS n FROM stock_movements WHERE substr(at,1,10)=? AND movement_type IN ({marks})", (day, *kinds))


def whatsapp_on(conn, day: str, statuses: tuple[str, ...]):
    marks = ",".join("?" for _ in statuses)
    return one(
        conn,
        f"SELECT COUNT(*) AS n FROM notifications WHERE channel='WHATSAPP' AND status IN ({marks}) AND substr(COALESCE(sent_at, created_at),1,10)=?",
        (*statuses, day),
    )


def hospital_beds(conn):
    return one(
        conn,
        f"""SELECT COUNT(*) AS total,
                   SUM(CASE WHEN status='AVAILABLE' THEN 1 ELSE 0 END) AS available,
                   SUM(CASE WHEN status='OCCUPIED' THEN 1 ELSE 0 END) AS occupied,
                   SUM(CASE WHEN status IN ('BLOCKED','MAINTENANCE') THEN 1 ELSE 0 END) AS blocked
            FROM beds WHERE active=1 AND {_HOSPITAL_BED}""",
        (),
    )


def sample_beds(conn):
    return one(conn, "SELECT COUNT(*) AS n FROM beds WHERE active=1 AND id LIKE 'BD-%'", ())


def ward_summary(conn):
    return rows(
        conn,
        f"""SELECT w.name AS ward,
                   COUNT(*) AS total,
                   SUM(CASE WHEN b.status='OCCUPIED' THEN 1 ELSE 0 END) AS occupied,
                   SUM(CASE WHEN b.status='AVAILABLE' THEN 1 ELSE 0 END) AS available
            FROM beds b JOIN wards w ON w.id=b.ward_id
            WHERE b.active=1 AND b.id NOT LIKE 'BD-%'
            GROUP BY w.id, w.name
            ORDER BY w.name""",
        (),
    )


def live_queue(conn):
    return rows(
        conn,
        """SELECT q.id, q.token_no, q.status, q.arrived_at, q.encounter_id, q.department_id,
                  p.name AS patient_name, p.id AS patient_id,
                  TRIM(COALESCE(u.title,'') || ' ' || COALESCE(u.full_name,'')) AS doctor_name
           FROM queue_entries q
           JOIN patients p ON p.id=q.patient_id
           LEFT JOIN users u ON u.id=q.doctor_id
           WHERE q.status NOT IN ('COMPLETED','CANCELLED')
           ORDER BY q.priority DESC, q.token_no
           LIMIT 12""",
        (),
    )


def doctor_activity(conn):
    return rows(
        conn,
        """SELECT u.id,
                  MAX(TRIM(COALESCE(u.title,'') || ' ' || COALESCE(u.full_name,''))) AS name,
                  SUM(CASE WHEN q.status NOT IN ('COMPLETED','CANCELLED') THEN 1 ELSE 0 END) AS open_n,
                  SUM(CASE WHEN q.status='IN_CONSULTATION' THEN 1 ELSE 0 END) AS consulting
           FROM queue_entries q
           JOIN users u ON u.id=q.doctor_id
           WHERE q.status NOT IN ('COMPLETED','CANCELLED')
           GROUP BY u.id
           ORDER BY consulting DESC, open_n DESC
           LIMIT 8""",
        (),
    )


def ot_open(conn):
    return one(conn, "SELECT COUNT(*) AS n FROM ot_cases WHERE status NOT IN ('CANCELLED','COMPLETED','CLOSED')", ())


def ot_today(conn, day: str):
    return rows(
        conn,
        """SELECT o.id, o.procedure_name, o.status, o.scheduled_at, o.started_at,
                  p.name AS patient_name,
                  TRIM(COALESCE(u.title,'') || ' ' || COALESCE(u.full_name,'')) AS surgeon_name
           FROM ot_cases o
           JOIN patients p ON p.id=o.patient_id
           LEFT JOIN users u ON u.id=o.surgeon_id
           WHERE o.status!='CANCELLED'
             AND substr(COALESCE(o.scheduled_at, o.created_at),1,10)=?
           ORDER BY COALESCE(o.scheduled_at, o.created_at)
           LIMIT 6""",
        (day,),
    )


def lab_pending(conn):
    return rows(
        conn,
        """SELECT o.id, o.status, o.ordered_at, p.name AS patient_name,
                  COALESCE((SELECT custom_name FROM lab_order_items i WHERE i.order_id=o.id LIMIT 1), 'Lab order') AS test_name
           FROM lab_orders o
           JOIN patients p ON p.id=o.patient_id
           WHERE o.status NOT IN ('RESULTED','VERIFIED','CANCELLED','REPORTED')
           ORDER BY o.ordered_at DESC
           LIMIT 6""",
        (),
    )


def recent_bills(conn):
    return rows(
        conn,
        """SELECT i.id, i.number, i.status, i.payment_status, i.net_paise, i.due_paise, i.created_at,
                  p.name AS patient_name
           FROM invoices i JOIN patients p ON p.id=i.patient_id
           ORDER BY i.created_at DESC
           LIMIT 6""",
        (),
    )


def draft_bills(conn):
    return rows(
        conn,
        """SELECT i.id, i.number, i.net_paise, i.created_at, p.name AS patient_name
           FROM invoices i JOIN patients p ON p.id=i.patient_id
           WHERE i.status='DRAFT'
           ORDER BY i.created_at DESC
           LIMIT 5""",
        (),
    )


def recent_patients(conn):
    return rows(
        conn,
        """SELECT p.id, p.name, e.id AS encounter_id, e.status, e.arrived_at,
                  TRIM(COALESCE(u.title,'') || ' ' || COALESCE(u.full_name,'')) AS doctor_name
           FROM encounters e
           JOIN patients p ON p.id=e.patient_id
           LEFT JOIN users u ON u.id=e.doctor_id
           ORDER BY e.arrived_at DESC
           LIMIT 8""",
        (),
    )


def recent_documents(conn):
    return rows(
        conn,
        """SELECT d.id, d.document_type, d.title, d.uploaded_at, d.patient_id, p.name AS patient_name
           FROM documents d LEFT JOIN patients p ON p.id=d.patient_id
           WHERE d.active=1
           ORDER BY d.uploaded_at DESC
           LIMIT 6""",
        (),
    )


def recent_activity(conn):
    return rows(
        conn,
        """SELECT at, action, entity, entity_id, username
           FROM audit_logs
           ORDER BY at DESC
           LIMIT 8""",
        (),
    )
