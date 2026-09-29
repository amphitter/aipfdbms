"""Record-scope queries. Domain code does not assemble this SQL."""

from __future__ import annotations

from aipf.repo.sqlio import one, rows


def clinical_link(conn, user_id: str, patient_id: str):
    return one(
        conn,
        """SELECT 1 AS ok FROM encounters WHERE patient_id=? AND doctor_id=?
           UNION SELECT 1 FROM queue_entries WHERE patient_id=? AND doctor_id=?
           UNION SELECT 1 FROM admissions WHERE patient_id=? AND doctor_id=?
           UNION SELECT 1 FROM ot_cases WHERE patient_id=? AND surgeon_id=?
           UNION SELECT 1 FROM prescriptions WHERE patient_id=? AND doctor_id=?
           LIMIT 1""",
        (patient_id, user_id, patient_id, user_id, patient_id, user_id, patient_id, user_id, patient_id, user_id),
    )


def search_linked(conn, user_id: str, q: str, like: str, upper: str, phone: str, limit: int):
    sql = """SELECT DISTINCT p.* FROM patients p
             WHERE p.id IN (
               SELECT patient_id FROM encounters WHERE doctor_id=?
               UNION SELECT patient_id FROM queue_entries WHERE doctor_id=?
               UNION SELECT patient_id FROM admissions WHERE doctor_id=?
               UNION SELECT patient_id FROM ot_cases WHERE surgeon_id=?
               UNION SELECT patient_id FROM prescriptions WHERE doctor_id=?
             )"""
    params: list = [user_id, user_id, user_id, user_id, user_id]
    if q:
        sql += " AND (lower(COALESCE(p.search_text, p.name, '')) LIKE ? OR p.id LIKE ? OR COALESCE(p.hospital_no, '') LIKE ? OR COALESCE(p.primary_phone, '') LIKE ?)"
        params.extend([like, upper, upper, phone])
    sql += " ORDER BY p.created_at DESC LIMIT ?"
    params.append(limit)
    return rows(conn, sql, params)
