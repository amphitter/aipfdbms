"""SQL owned by the repository. Domain modules call these functions."""
from __future__ import annotations

from aipf.repo.sqlio import count_where, execute, has_column, one, rows

def q_clinical_9364(conn, p0):
    return one(conn, "SELECT id FROM users WHERE id=? AND active=1", (p0,))

def list_directory(conn) -> list[dict]:
    people = rows(conn, "SELECT id, full_name, title, specialty FROM users WHERE active=1 ORDER BY full_name")
    roles = rows(conn, "SELECT user_id, role FROM user_roles")
    held: dict[str, list[str]] = {}
    for row in roles:
        held.setdefault(row["user_id"], []).append(row["role"])
    for person in people:
        person["roles"] = held.get(person["id"], [])
    return people


def q_clinical_35973(conn):
    return rows(conn, """SELECT u.id, u.full_name, u.title, u.specialty, u.department_id, u.active
           FROM users u JOIN user_roles r ON r.user_id=u.id
           WHERE r.role IN ('doctor','admin') AND u.active=1
           GROUP BY u.id ORDER BY u.full_name""", ())

def q_system_43595(conn):
    return one(conn, "SELECT COUNT(*) AS n FROM users WHERE active=1", ())

def q_core_8688(conn, p0):
    return one(conn, "SELECT * FROM users WHERE id=?", (p0,))

def q_core_8835(conn, p0):
    return rows(conn, "SELECT role FROM user_roles WHERE user_id=?", (p0,))

def q_core_8961(conn, p0):
    return rows(conn, """SELECT DISTINCT rp.permission
               FROM user_roles ur JOIN role_permissions rp ON rp.role = ur.role
               WHERE ur.user_id=?""", (p0,))

def q_core_9377(conn, p0):
    return one(conn, "SELECT * FROM users WHERE lower(username)=lower(?)", (p0,))

def q_core_11063(conn, p0):
    return one(conn, """SELECT s.*, u.active FROM sessions s JOIN users u ON u.id = s.user_id
           WHERE s.token=? AND s.revoked_at IS NULL""", (p0,))

def q_core_11909(conn, p0):
    return one(conn, "SELECT password_hash FROM users WHERE id=?", (p0,))

def touch_login(conn, at, user_id):
    return execute(conn, "UPDATE users SET last_login_at=? WHERE id=?", (at, user_id))


def q_core_12181(conn, p0, p1, p2):
    return execute(conn, "UPDATE users SET password_hash=?, must_change_password=0, updated_at=? WHERE id=?", (p0, p1, p2))

def q_core_12476(conn):
    return rows(conn, "SELECT id, username, full_name, title, specialty, department_id, phone, active, is_admin_doctor, created_at, last_login_at FROM users ORDER BY full_name", ())

def q_core_12700(conn, p0):
    return rows(conn, "SELECT role FROM user_roles WHERE user_id=?", (p0,))

def q_core_13224(conn):
    return rows(conn, "SELECT code FROM roles WHERE active=1", ())

def q_core_13391(conn, p0):
    return one(conn, "SELECT * FROM users WHERE id=?", (p0,))

def q_core_13534(conn, p0, p1):
    return one(conn, "SELECT id FROM users WHERE lower(username)=? AND id<>?", (p0, p1))

def q_core_13694(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8, p9):
    return execute(conn, """UPDATE users SET username=?, full_name=?, title=?, specialty=?, department_id=?, phone=?,
               active=?, is_admin_doctor=?, updated_at=? WHERE id=?""", (p0, p1, p2, p3, p4, p5, p6, p7, p8, p9))

def q_core_14418(conn, p0, p1):
    return execute(conn, "UPDATE users SET password_hash=? WHERE id=?", (p0, p1))

def q_core_14533(conn, p0):
    return execute(conn, "DELETE FROM user_roles WHERE user_id=?", (p0,))

def q_core_14639(conn, p0, p1):
    return execute(conn, "INSERT INTO user_roles(user_id, role) VALUES (?,?)", (p0, p1))

def q_core_15161(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10):
    return execute(conn, """INSERT INTO users(id, username, full_name, password_hash, title, specialty, department_id, phone, active, is_admin_doctor, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10))

def q_core_15752(conn, p0, p1):
    return execute(conn, "INSERT INTO user_roles(user_id, role) VALUES (?,?)", (p0, p1))

def q_core_16019(conn):
    return rows(conn, "SELECT * FROM roles ORDER BY sort_order, name", ())

def q_core_16159(conn, p0):
    return rows(conn, "SELECT permission FROM role_permissions WHERE role=? ORDER BY permission", (p0,))

def q_core_16402(conn, p0):
    return one(conn, "SELECT * FROM roles WHERE code=?", (p0,))

def q_core_16639(conn, p0):
    return rows(conn, "SELECT permission FROM role_permissions WHERE role=?", (p0,))

def q_core_16720(conn, p0):
    return execute(conn, "DELETE FROM role_permissions WHERE role=?", (p0,))

def q_core_16818(conn, p0, p1):
    return execute(conn, "INSERT INTO role_permissions(role, permission) VALUES (?,?)", (p0, p1))

def q_core_20147(conn, p0):
    return one(conn, "SELECT full_name, title FROM users WHERE id=?", (p0,))

def q_seed_349(conn):
    return one(conn, "SELECT id FROM users LIMIT 1", ())

def q_seed_1017(conn, p0, p1, p2):
    if conn.dialect == "postgres":
        sql = "INSERT INTO permissions(code, module, description) VALUES (?,?,?) ON CONFLICT (code) DO NOTHING"
    else:
        sql = "INSERT OR IGNORE INTO permissions(code, module, description) VALUES (?,?,?)"
    return execute(conn, sql, (p0, p1, p2))

def q_seed_1746(conn, p0, p1, p2, p3):
    return execute(conn, "INSERT INTO roles(code, name, description, active, is_system, sort_order) VALUES (?,?,?,1,1,?)", (p0, p1, p2, p3))

def q_seed_1977(conn, p0, p1):
    if conn.dialect == "postgres":
        sql = "INSERT INTO role_permissions(role, permission) VALUES (?,?) ON CONFLICT (role, permission) DO NOTHING"
    else:
        sql = "INSERT OR IGNORE INTO role_permissions(role, permission) VALUES (?,?)"
    return execute(conn, sql, (p0, p1))

def q_seed_16116(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8):
    return execute(conn, """INSERT INTO users(id, username, full_name, password_hash, title, specialty, department_id, active, is_admin_doctor, created_at)
           VALUES (?,?,?,?,?,?,?,1,?,?)""", (p0, p1, p2, p3, p4, p5, p6, p7, p8))

def q_seed_16427(conn, p0, p1):
    return execute(conn, "INSERT INTO user_roles(user_id, role) VALUES (?,?)", (p0, p1))

def q_seed_16536(conn, p0):
    return execute(conn, "INSERT INTO user_roles(user_id, role) VALUES (?, 'doctor')", (p0,))


def other_admins(conn, user_id: str) -> int:
    row = one(conn, "SELECT COUNT(*) AS n FROM user_roles WHERE role='admin' AND user_id<>?", (user_id,))
    return int((row or {}).get("n") or 0)


def has_role(conn, user_id: str, role: str) -> bool:
    return bool(one(conn, "SELECT 1 AS ok FROM user_roles WHERE user_id=? AND role=?", (user_id, role)))


def blocking_user_links(conn, user_id: str) -> list[str]:
    checks = (
        ("consultations", "doctor_id", "consultations"),
        ("prescriptions", "doctor_id", "prescriptions"),
        ("consultation_revisions", "doctor_id", "consultation history"),
        ("financial_adjustments", "created_by", "financial adjustments"),
        ("ot_team_members", "user_id", "OT team assignments"),
    )
    blocked = []
    for table, column, label in checks:
        if count_where(conn, table, column, user_id):
            blocked.append(label)
    return blocked


def detach_user(conn, user_id: str) -> None:
    nullable = (
        ("patients", "created_by"),
        ("encounters", "doctor_id"),
        ("encounters", "created_by"),
        ("queue_entries", "doctor_id"),
        ("stock_movements", "user_id"),
        ("dispense_lines", "dispensed_by"),
        ("invoices", "finalized_by"),
        ("invoices", "created_by"),
        ("payments", "received_by"),
        ("deposits", "received_by"),
        ("invoice_revisions", "user_id"),
        ("admissions", "doctor_id"),
        ("admissions", "requested_by"),
        ("bed_movements", "user_id"),
        ("admission_charges", "posted_by"),
        ("ot_cases", "surgeon_id"),
        ("ot_cases", "notes_by"),
        ("ot_cases", "requested_by"),
        ("ot_cases", "approved_by"),
        ("ot_cases", "started_by"),
        ("ot_cases", "completed_by"),
        ("ot_cases", "cancelled_by"),
        ("lab_orders", "doctor_id"),
        ("lab_orders", "created_by"),
        ("lab_order_items", "resulted_by"),
        ("lab_results", "entered_by"),
        ("lab_results", "finalized_by"),
        ("lab_samples", "collected_by"),
        ("lab_samples", "received_by"),
        ("lab_samples", "rejected_by"),
        ("documents", "uploaded_by"),
        ("notifications", "user_id"),
        ("backups", "created_by"),
        ("ot_bookings", "surgeon_id"),
        ("ot_bookings", "created_by"),
    )
    for table, column in nullable:
        if has_column(conn, table, column):
            execute(conn, f"UPDATE {table} SET {column}=NULL WHERE {column}=?", (user_id,))
    execute(conn, "DELETE FROM sessions WHERE user_id=?", (user_id,))
    execute(conn, "DELETE FROM user_roles WHERE user_id=?", (user_id,))
    execute(conn, "DELETE FROM users WHERE id=?", (user_id,))

