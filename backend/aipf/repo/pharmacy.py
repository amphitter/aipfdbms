"""SQL owned by the repository. Domain modules call these functions."""
from __future__ import annotations

from aipf.repo.sqlio import execute, one, rows

def q_pharmacy_15133(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11, p12, p13, p14, p15):
    return execute(conn, """INSERT INTO dispense_lines(id, prescription_id, prescription_item_id, patient_id, encounter_id, product_id, batch_id,
               qty, unit, rate_paise, amount_paise, substituted, substitution_reason, invoice_item_id, dispensed_by, dispensed_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11, p12, p13, p14, p15))

def q_system_39192(conn, p0):
    return one(conn, "SELECT COUNT(*) AS n FROM dispense_lines WHERE substr(dispensed_at,1,10)=?", (p0,))

def dispense_by_invoice_item(conn, item_id: str):
    return one(conn, "SELECT * FROM dispense_lines WHERE invoice_item_id=?", (item_id,))

def dispense_by_id(conn, line_id: str):
    return one(conn, "SELECT * FROM dispense_lines WHERE id=?", (line_id,))

def delete_dispense(conn, line_id: str):
    return execute(conn, "DELETE FROM dispense_lines WHERE id=?", (line_id,))

def update_dispense(conn, qty, batch_id: str, rate: int, amount: int, line_id: str):
    return execute(
        conn,
        "UPDATE dispense_lines SET qty=?, batch_id=?, rate_paise=?, amount_paise=? WHERE id=?",
        (qty, batch_id, rate, amount, line_id),
    )

