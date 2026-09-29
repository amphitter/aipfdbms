"""SQL owned by the repository. Domain modules call these functions."""
from __future__ import annotations

from aipf.repo.sqlio import execute, one, rows

def q_system_37213(conn):
    return one(conn, "SELECT COUNT(*) AS n FROM notifications WHERE channel='WHATSAPP' AND status IN ('QUEUED','PROCESSING','FAILED')", ())

def q_notify_6419(conn):
    return rows(conn, "SELECT * FROM notification_templates ORDER BY name", ())

def q_notify_6764(conn, p0, p1, p2, p3, p4, p5):
    return execute(conn, "UPDATE notification_templates SET name=?, body=?, message_type=?, active=?, updated_at=? WHERE id=?", (p0, p1, p2, p3, p4, p5))

def q_notify_7093(conn, p0, p1, p2, p3, p4):
    return execute(conn, """INSERT INTO notification_templates(id, name, channel, message_type, body, active, updated_at)
               VALUES (?,?,'WHATSAPP',?,?,1,?)""", (p0, p1, p2, p3, p4))

def q_notify_7479(conn, p0):
    return one(conn, "SELECT * FROM notification_templates WHERE id=?", (p0,))

def q_notify_7681(conn, p0, p1, p2, p3, p4, p5, p6, p7):
    return execute(conn, """INSERT INTO notifications(id, channel, user_id, message_type, body, status, entity_type, entity_id, created_at, updated_at)
           VALUES (?,'IN_APP',?,?,?,'UNREAD',?,?,?,?)""", (p0, p1, p2, p3, p4, p5, p6, p7))

def q_notify_8360(conn, p0):
    return one(conn, "SELECT id FROM notifications WHERE channel='WHATSAPP' AND entity_type='invoice' AND entity_id=? AND status!='CANCELLED'", (p0,))

def q_notify_8775(conn):
    return one(conn, "SELECT * FROM notification_templates WHERE message_type='visit_complete' AND active=1 ORDER BY updated_at DESC LIMIT 1", ())

def q_notify_9591(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8):
    return execute(conn, """INSERT INTO notifications(id, channel, patient_id, phone, message_type, template_id, body, status, scheduled_at,
           provider, retry_count, max_retries, entity_type, entity_id, created_at, updated_at)
           VALUES (?,'WHATSAPP',?,?, 'visit_complete', ?, ?, 'QUEUED', ?, 'openwa', 0, 3, 'invoice', ?, ?, ?)""", (p0, p1, p2, p3, p4, p5, p6, p7, p8))

def q_notify_10846(conn, p0):
    return one(conn, "SELECT * FROM notifications WHERE id=?", (p0,))

def q_notify_11155(conn, p0, p1):
    return execute(conn, "UPDATE notifications SET status='READ', updated_at=? WHERE id=?", (p0, p1))

def q_notify_11276(conn, p0):
    return one(conn, "SELECT * FROM notifications WHERE id=?", (p0,))

def q_notify_11408(conn, p0, p1):
    return rows(conn, """SELECT * FROM notifications WHERE channel='WHATSAPP' AND status='QUEUED' AND (scheduled_at IS NULL OR scheduled_at<=?)
           ORDER BY scheduled_at LIMIT ?""", (p0, p1))

def q_notify_11724(conn, p0, p1):
    return execute(conn, "UPDATE notifications SET status='PROCESSING', updated_at=? WHERE id=? AND status='QUEUED'", (p0, p1))

def q_notify_12356(conn, p0, p1, p2, p3):
    return execute(conn, """UPDATE notifications SET status='SENT', sent_at=?, provider='openwa', provider_message_id=?, failure_reason=NULL, updated_at=?
                   WHERE id=?""", (p0, p1, p2, p3))

def q_notify_13150(conn, p0, p1, p2, p3, p4, p5):
    return execute(conn, """UPDATE notifications SET status=?, retry_count=?, failure_reason=?, scheduled_at=?, updated_at=? WHERE id=?""", (p0, p1, p2, p3, p4, p5))

def q_notify_13458(conn, p0):
    return one(conn, "SELECT * FROM notifications WHERE id=?", (p0,))

def q_notify_13597(conn, p0, p1, p2):
    return execute(conn, "UPDATE notifications SET status='QUEUED', scheduled_at=?, failure_reason=NULL, updated_at=? WHERE id=?", (p0, p1, p2))

def q_notify_13876(conn, p0):
    return one(conn, "SELECT * FROM notifications WHERE id=?", (p0,))

def q_notify_14021(conn, p0, p1):
    return execute(conn, "UPDATE notifications SET status='CANCELLED', updated_at=? WHERE id=? AND status IN ('QUEUED','FAILED')", (p0, p1))

def q_notify_14267(conn, p0):
    return one(conn, "SELECT * FROM notifications WHERE id=?", (p0,))

def q_seed_29768(conn, p0, p1):
    return execute(conn, """INSERT INTO notifications(id, channel, user_id, message_type, body, status, entity_type, entity_id, created_at, updated_at)
           VALUES ('NT-1','IN_APP','U-IMRAN','OT notes','OT request waiting: Harpreet Singh — closed reduction.','UNREAD','ot','OT-2026-000001',?,?)""", (p0, p1))

def q_seed_30561(conn, p0):
    return execute(conn, """INSERT INTO notification_templates(id, name, channel, message_type, body, active, updated_at)
           VALUES ('TPL-VISIT','Visit thank-you','WHATSAPP','visit_complete',
           'Thank you for visiting {hospital_name}, {patient_name}. Your bill {bill_number} for {visit_date} is ready. — {hospital_name}',
           1, ?)""", (p0,))

def record_outbound(conn, nid, patient_id, phone, message_type, body, status, sent_at, failure, entity_type, entity_id, document_id, at, provider_message_id=None):
    return execute(conn, """INSERT INTO notifications(id, channel, patient_id, phone, message_type, body, status, sent_at,
           provider, provider_message_id, failure_reason, retry_count, max_retries, entity_type, entity_id, document_id, created_at, updated_at)
           VALUES (?,'WHATSAPP',?,?,?,?,?,?, 'openwa', ?, ?, 0, 0, ?, ?, ?, ?, ?)""",
           (nid, patient_id, phone, message_type, body, status, sent_at, provider_message_id, failure, entity_type, entity_id, document_id, at, at))


def list_notifications(conn, channel: str = "", status: str = "", user_id: str = ""):
    sql = "SELECT * FROM notifications WHERE 1=1"
    params: list = []
    if channel:
        sql += " AND channel=?"
        params.append(channel)
    if status:
        sql += " AND status=?"
        params.append(status)
    if user_id:
        sql += " AND user_id=?"
        params.append(user_id)
    sql += " ORDER BY created_at DESC LIMIT 150"
    return rows(conn, sql, params)
