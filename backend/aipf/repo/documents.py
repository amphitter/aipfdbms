"""SQL owned by the repository. Domain modules call these functions."""
from __future__ import annotations

from aipf.repo.sqlio import execute, one, rows

def q_clinical_28670(conn, p0):
    return rows(conn, "SELECT * FROM documents WHERE patient_id=? AND active=1 ORDER BY uploaded_at", (p0,))

def q_clinical_29881(conn, p0):
    return rows(conn, "SELECT id, document_type, title, filename, mime_type, size_bytes, uploaded_at, entity_type, entity_id, active FROM documents WHERE patient_id=? ORDER BY uploaded_at DESC", (p0,))

def q_wards_28079(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11, p12, p13):
    return execute(conn, """INSERT INTO documents(id, patient_id, entity_type, entity_id, document_type, title, filename, stored_name, mime_type,
           size_bytes, checksum, uploaded_by, uploaded_at, active, notes)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)""", (p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11, p12, p13))

def q_wards_29086(conn, p0):
    return one(conn, "SELECT id, patient_id, entity_type, entity_id, document_type, title, filename, mime_type, size_bytes, checksum, uploaded_at, active FROM documents WHERE id=?", (p0,))

def q_wards_29339(conn, p0):
    return one(conn, "SELECT * FROM documents WHERE id=? AND active=1", (p0,))

def q_wards_29802(conn, p0):
    return one(conn, "SELECT * FROM documents WHERE id=?", (p0,))

def q_wards_29988(conn, p0, p1):
    return execute(conn, "UPDATE documents SET active=0, notes=? WHERE id=?", (p0, p1))

def q_system_34436(conn, like, ident):
    return rows(conn, """SELECT id, patient_id, title, filename, document_type, entity_type, entity_id
        FROM documents WHERE active=1 AND (
          lower(title) LIKE ? OR lower(filename) LIKE ? OR upper(id) LIKE ? OR upper(patient_id) LIKE ? OR upper(entity_id) LIKE ?
        ) LIMIT 8""", (like, like, ident, ident, ident))


def document_for_entity(conn, entity_type: str, entity_id: str):
    return one(conn, """SELECT * FROM documents
        WHERE entity_type=? AND entity_id=? AND active=1
        ORDER BY uploaded_at DESC LIMIT 1""", (entity_type, entity_id))

def list_documents(conn, patient_id: str = "", entity_type: str = "", entity_id: str = "", q: str = ""):
    sql = """SELECT d.id, d.patient_id, d.entity_type, d.entity_id, d.document_type, d.title, d.filename,
                    d.mime_type, d.size_bytes, d.checksum, d.uploaded_by, d.uploaded_at, d.active, d.notes,
                    p.name AS patient_name, u.full_name AS uploaded_by_name
             FROM documents d
             LEFT JOIN patients p ON p.id = d.patient_id
             LEFT JOIN users u ON u.id = d.uploaded_by
             WHERE d.active=1"""
    params: list = []
    if patient_id:
        sql += " AND d.patient_id=?"
        params.append(patient_id)
    if entity_type:
        sql += " AND d.entity_type=?"
        params.append(entity_type)
    if entity_id:
        sql += " AND d.entity_id=?"
        params.append(entity_id)
    if q:
        like = f"%{q.lower()}%"
        ident = f"%{q.upper()}%"
        sql += """ AND (
            upper(d.patient_id) LIKE ? OR upper(d.id) LIKE ? OR upper(d.entity_id) LIKE ?
            OR lower(d.title) LIKE ? OR lower(d.filename) LIKE ? OR lower(d.document_type) LIKE ?
            OR lower(p.name) LIKE ?
        )"""
        params.extend([ident, ident, ident, like, like, like, like])
    sql += " ORDER BY d.uploaded_at DESC LIMIT 200"
    return rows(conn, sql, params)
