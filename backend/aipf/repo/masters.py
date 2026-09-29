"""SQL owned by the repository. Domain modules call these functions."""
from __future__ import annotations

from aipf.repo.sqlio import count_where, exec_if, execute, one, rows

def q_clinical_9137(conn, p0):
    return one(conn, "SELECT * FROM opd_types WHERE id=? AND active=1", (p0,))

def q_clinical_30314(conn):
    return rows(conn, "SELECT * FROM opd_types ORDER BY sort_order, name", ())

def q_clinical_30389(conn):
    return rows(conn, "SELECT * FROM opd_types WHERE active=1 ORDER BY sort_order, name", ())

def q_clinical_30855(conn, p0):
    return one(conn, "SELECT id FROM opd_types WHERE id=?", (p0,))

def q_clinical_30966(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10):
    return execute(conn, """UPDATE opd_types SET name=?, code=?, fee_paise=?, validity_days=?, description=?, services_included=?, departments=?, active=?, sort_order=?, updated_at=?
               WHERE id=?""", (p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10))

def q_clinical_31536(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11):
    return execute(conn, """INSERT INTO opd_types(id, name, code, fee_paise, validity_days, description, services_included, departments, active, sort_order, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11))

def q_clinical_32167(conn, p0):
    return one(conn, "SELECT * FROM opd_types WHERE id=?", (p0,))

def q_clinical_32327(conn):
    return rows(conn, "SELECT * FROM services ORDER BY category, sort_order, name", ())

def q_clinical_32411(conn):
    return rows(conn, "SELECT * FROM services WHERE active=1 ORDER BY category, sort_order, name", ())

def q_clinical_32813(conn, p0):
    return one(conn, "SELECT id FROM services WHERE id=?", (p0,))

def q_clinical_32922(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8):
    return execute(conn, """UPDATE services SET name=?, code=?, category=?, rate_paise=?, unit=?, description=?, active=?, sort_order=? WHERE id=?""", (p0, p1, p2, p3, p4, p5, p6, p7, p8))

def q_clinical_33406(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8, p9):
    return execute(conn, """INSERT INTO services(id, name, code, category, rate_paise, unit, description, active, sort_order, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""", (p0, p1, p2, p3, p4, p5, p6, p7, p8, p9))

def q_clinical_33947(conn, p0):
    return one(conn, "SELECT * FROM services WHERE id=?", (p0,))

def q_system_43300(conn):
    return one(conn, "SELECT COUNT(*) AS n FROM master_items WHERE list_type='department' AND active=1", ())

def q_system_43864(conn):
    return one(conn, "SELECT COUNT(*) AS n FROM opd_types WHERE active=1", ())

def q_system_44107(conn):
    return one(conn, "SELECT COUNT(*) AS n FROM master_items WHERE list_type='payment_mode' AND active=1", ())

def q_system_44910(conn):
    return one(conn, "SELECT COUNT(*) AS n FROM master_items WHERE list_type='document_type'", ())

def q_system_46868(conn, params):
    return execute(conn, """UPDATE hospital_profile SET name=:name, legal_name=:legal_name, tagline=:tagline, address_line1=:address_line1,
           address_line2=:address_line2, city=:city, state=:state, pin=:pin, phone=:phone, email=:email, website=:website,
           registration_no=:registration_no, updated_at=:updated_at WHERE id=1""", params)

def allocate_sequence(conn, name: str, year: int) -> int:
    row = one(
        conn,
        """INSERT INTO sequences(name, year, next_value) VALUES (?, ?, 2)
           ON CONFLICT(name, year) DO UPDATE SET next_value = sequences.next_value + 1
           RETURNING next_value""",
        (name, year),
    )
    return int(row["next_value"]) - 1


def q_core_6342(conn, p0, p1):
    return one(conn, "SELECT next_value FROM sequences WHERE name=? AND year=?", (p0, p1))

def q_core_6450(conn, p0, p1, p2):
    return execute(conn, "INSERT INTO sequences(name, year, next_value) VALUES (?,?,?)", (p0, p1, p2))

def q_core_6646(conn, p0, p1, p2):
    return execute(conn, "UPDATE sequences SET next_value=? WHERE name=? AND year=?", (p0, p1, p2))

def q_core_6946(conn, p0):
    return one(conn, "SELECT value FROM app_config WHERE key=?", (p0,))

def q_core_7135(conn, p0, p1, p2, p3, p4):
    return execute(conn, """INSERT INTO app_config(key, value, is_secret, updated_at, updated_by)
           VALUES (?,?,?,?,?)
           ON CONFLICT(key) DO UPDATE SET value=excluded.value, is_secret=excluded.is_secret,
             updated_at=excluded.updated_at, updated_by=excluded.updated_by""", (p0, p1, p2, p3, p4))

def q_core_7609(conn):
    return rows(conn, "SELECT key, value, is_secret FROM app_config ORDER BY key", ())

def q_core_7966(conn):
    return one(conn, "SELECT * FROM hospital_profile WHERE id=1", ())

def q_core_17183(conn, p0):
    return rows(conn, "SELECT * FROM master_items WHERE list_type=? ORDER BY sort_order, name", (p0,))

def q_core_17293(conn, p0):
    return rows(conn, "SELECT * FROM master_items WHERE list_type=? AND active=1 ORDER BY sort_order, name", (p0,))

def q_core_17661(conn, p0, p1):
    return one(conn, "SELECT * FROM master_items WHERE id=? AND list_type=?", (p0, p1))

def q_core_17828(conn, p0, p1, p2, p3, p4, p5, p6, p7):
    return execute(conn, """UPDATE master_items SET name=?, code=?, description=?, meta=?, sort_order=?, active=?, updated_at=?
               WHERE id=?""", (p0, p1, p2, p3, p4, p5, p6, p7))

def q_core_18549(conn, p0):
    return one(conn, "SELECT * FROM master_items WHERE id=?", (p0,))

def q_core_18642(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8):
    return execute(conn, """INSERT INTO master_items(id, list_type, name, code, description, meta, sort_order, active, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""", (p0, p1, p2, p3, p4, p5, p6, p7, p8))

def q_core_19342(conn, p0):
    return one(conn, "SELECT * FROM master_items WHERE id=?", (p0,))

def q_core_19531(conn, p0, p1):
    return one(conn, "SELECT * FROM master_items WHERE id=? AND list_type=?", (p0, p1))

def q_core_19690(conn, p0, p1):
    return execute(conn, "UPDATE master_items SET active=0, updated_at=? WHERE id=?", (p0, p1))

def q_core_19925(conn, p0):
    return one(conn, "SELECT * FROM master_items WHERE id=?", (p0,))

def q_seed_2127(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11, p12, p13):
    return execute(conn, """INSERT INTO hospital_profile(id, name, legal_name, tagline, address_line1, address_line2, city, state, pin, phone, email, website, registration_no, logo_path, updated_at)
           VALUES (1,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11, p12, p13))

def q_seed_3573(conn, p0, p1, p2, p3):
    return execute(conn, "INSERT INTO app_config(key, value, is_secret, updated_at) VALUES (?,?,?,?)", (p0, p1, p2, p3))

def q_seed_3886(conn, p0, p1, p2, p3, p4, p5, p6, p7):
    return execute(conn, """INSERT INTO master_items(id, list_type, name, code, description, meta, sort_order, active, created_at)
           VALUES (?,?,?,?,?,?,?,1,?)""", (p0, p1, p2, p3, p4, p5, p6, p7))

def q_seed_6840(conn, *params):
    return execute(conn, """INSERT INTO opd_types(id, name, code, fee_paise, validity_days, description, services_included, departments, active, sort_order, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,'',1,?,?,?)""", params)

def q_seed_7841(conn, p0, p1, p2, p3, p4, p5, p6, p7):
    return execute(conn, "INSERT INTO services(id, name, code, category, rate_paise, unit, active, sort_order, created_at) VALUES (?,?,?,?,?,?,1,?,?)", (p0, p1, p2, p3, p4, p5, p6, p7))

def q_seed_26126(conn, p0):
    return execute(conn, """INSERT INTO invoice_items(id, invoice_id, source_module, source_id, master_item_id, description, category, rate_paise, qty, unit, amount_paise, created_at)
           VALUES ('II-5B','INV-S5','service','SV-ECG','SV-ECG','ECG','HOSPITAL SERVICES',25000,1,'test',25000,?)""", (p0,))

def q_seed_30437(conn, p0, p1, p2):
    return execute(conn, "INSERT INTO sequences(name, year, next_value) VALUES (?,?,?)", (p0, p1, p2))

_LOOKUP = {
    "patients": {"name"},
    "opd_types": {"name"},
    "wards": {"name"},
    "rooms": {"name"},
    "master_items": {"name"},
    "users": {"full_name", "name"},
    "products": {"name"},
    "services": {"name"},
    "lab_tests": {"name"},
    "beds": {"bed_no", "name"},
}


def lookup_name(conn, table: str, item_id: str, field: str = "name"):
    allowed = _LOOKUP.get(table)
    if not allowed or field not in allowed:
        return None
    return one(conn, f"SELECT {field} AS name FROM {table} WHERE id=?", (item_id,))


def detach_master_item(conn, item_id: str) -> None:
    links = (
        ("patients", "category_id"),
        ("patients", "department_id"),
        ("users", "department_id"),
        ("services", "department_id"),
        ("lab_tests", "department_id"),
        ("encounters", "department_id"),
        ("queue_entries", "department_id"),
        ("admissions", "department_id"),
        ("ot_procedures", "department_id"),
    )
    for table, column in links:
        exec_if(conn, table, f"UPDATE {table} SET {column}=NULL WHERE {column}=?", (item_id,))


def delete_master_item(conn, list_type: str, item_id: str):
    return execute(conn, "DELETE FROM master_items WHERE id=? AND list_type=?", (item_id, list_type))


def delete_opd_type(conn, item_id: str):
    exec_if(conn, "encounters", "UPDATE encounters SET opd_type_id=NULL WHERE opd_type_id=?", (item_id,))
    return execute(conn, "DELETE FROM opd_types WHERE id=?", (item_id,))


def delete_service(conn, item_id: str):
    return execute(conn, "DELETE FROM services WHERE id=?", (item_id,))


def lab_test_in_use(conn, item_id: str) -> int:
    return count_where(conn, "lab_order_items", "test_id", item_id)


def delete_lab_test(conn, item_id: str):
    return execute(conn, "DELETE FROM lab_tests WHERE id=?", (item_id,))


def set_logo_path(conn, column: str, path: str, updated_at: str):
    if column not in {"logo_path", "logo_mono_path"}:
        raise ValueError("Unknown logo column")
    return execute(
        conn,
        f"UPDATE hospital_profile SET {column}=?, updated_at=? WHERE id=1",
        (path, updated_at),
    )
