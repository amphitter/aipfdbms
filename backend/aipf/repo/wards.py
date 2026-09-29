"""SQL owned by the repository. Domain modules call these functions."""
from __future__ import annotations

from aipf.repo.sqlio import count_where, execute, one, rows

def q_billing_19785(conn, p0):
    return one(conn, "SELECT name FROM beds WHERE id=?", (p0,))

def q_wards_830(conn):
    return rows(conn, "SELECT * FROM wards WHERE active=1 ORDER BY sort_order, name", ())

def q_wards_952(conn, p0):
    return rows(conn, "SELECT * FROM rooms WHERE ward_id=? AND active=1 ORDER BY name", (p0,))

def q_wards_1734(conn, p0):
    return one(conn, "SELECT * FROM beds WHERE id=?", (p0,))

def q_wards_2172(conn, p0, p1, p2):
    return execute(conn, "UPDATE beds SET status=?, notes=? WHERE id=?", (p0, p1, p2))

def q_wards_2461(conn, p0):
    return one(conn, "SELECT * FROM beds WHERE id=?", (p0,))

def q_wards_3035(conn, p0):
    return one(conn, "SELECT * FROM beds WHERE id=? AND active=1", (p0,))

def q_wards_3362(conn, p0):
    return one(conn, "SELECT * FROM rooms WHERE id=?", (p0,))

def q_wards_4626(conn, p0, p1):
    return execute(conn, "UPDATE beds SET status='OCCUPIED', current_admission_id=? WHERE id=?", (p0, p1))

def q_wards_5958(conn, p0):
    return one(conn, "SELECT name FROM beds WHERE id=?", (p0,))

def q_wards_7005(conn, p0):
    return one(conn, "SELECT name FROM beds WHERE id=?", (p0,))

def q_wards_7582(conn, p0):
    return one(conn, "SELECT * FROM beds WHERE id=? AND active=1", (p0,))

def q_wards_7841(conn, p0):
    return execute(conn, "UPDATE beds SET status='AVAILABLE', current_admission_id=NULL WHERE id=?", (p0,))

def q_wards_7949(conn, p0):
    return one(conn, "SELECT * FROM rooms WHERE id=?", (p0,))

def q_wards_8290(conn, p0, p1):
    return execute(conn, "UPDATE beds SET status='OCCUPIED', current_admission_id=? WHERE id=?", (p0, p1))

def q_wards_12013(conn, p0):
    return execute(conn, "UPDATE beds SET status='AVAILABLE', current_admission_id=NULL WHERE id=?", (p0,))

def q_wards_12904(conn, p0, p1, p2, p3, p4, p5, p6, p7):
    return execute(conn, "UPDATE wards SET name=?, code=?, ward_type=?, ac=?, description=?, active=?, sort_order=? WHERE id=?", (p0, p1, p2, p3, p4, p5, p6, p7))

def q_wards_13354(conn, p0, p1, p2, p3, p4, p5, p6, p7):
    return execute(conn, "INSERT INTO wards(id, name, code, ward_type, ac, description, active, sort_order) VALUES (?,?,?,?,?,?,?,?)", (p0, p1, p2, p3, p4, p5, p6, p7))

def q_wards_13816(conn, p0):
    return one(conn, "SELECT * FROM wards WHERE id=?", (p0,))

def q_wards_14080(conn, p0, p1, p2, p3, p4, p5):
    return execute(conn, "INSERT INTO rooms(id, ward_id, name, room_type, ac, daily_rate_paise, active) VALUES (?,?,?,?,?,?,1)", (p0, p1, p2, p3, p4, p5))

def q_wards_14464(conn, p0):
    return one(conn, "SELECT * FROM rooms WHERE id=?", (p0,))

def q_wards_14612(conn, p0):
    return one(conn, "SELECT * FROM rooms WHERE id=?", (p0,))

def q_wards_14787(conn, p0, p1, p2, p3):
    return execute(conn, "INSERT INTO beds(id, room_id, ward_id, name, status, active) VALUES (?,?,?,?, 'AVAILABLE', 1)", (p0, p1, p2, p3))

def q_wards_15057(conn, p0):
    return one(conn, "SELECT * FROM beds WHERE id=?", (p0,))

def facilities(conn, include_inactive: bool = False):
    ward_sql = "SELECT * FROM wards" + ("" if include_inactive else " WHERE active=1") + " ORDER BY sort_order, name"
    room_sql = """SELECT r.*, w.name AS ward_name FROM rooms r JOIN wards w ON w.id=r.ward_id"""
    bed_sql = """SELECT b.*, r.name AS room_name, w.name AS ward_name
                 FROM beds b JOIN rooms r ON r.id=b.room_id JOIN wards w ON w.id=b.ward_id"""
    if not include_inactive:
        room_sql += " WHERE r.active=1"
        bed_sql += " WHERE b.active=1"
    room_sql += " ORDER BY w.name, r.name"
    bed_sql += " ORDER BY w.name, r.name, b.name"
    return {
        "wards": rows(conn, ward_sql, ()),
        "rooms": rows(conn, room_sql, ()),
        "beds": rows(conn, bed_sql, ()),
    }

def update_room(conn, room_id: str, name: str, room_type: str, rate: int, active: int):
    return execute(conn, "UPDATE rooms SET name=?, room_type=?, daily_rate_paise=?, active=? WHERE id=?", (name, room_type, rate, active, room_id))

def occupied_beds_in_room(conn, room_id: str):
    return one(conn, "SELECT COUNT(*) AS n FROM beds WHERE room_id=? AND current_admission_id IS NOT NULL", (room_id,))

def update_bed_record(conn, bed_id: str, name: str, active: int, status: str):
    return execute(conn, "UPDATE beds SET name=?, active=?, status=? WHERE id=?", (name, active, status, bed_id))

def q_system_35215(conn):
    return one(conn, "SELECT SUM(CASE WHEN status='OCCUPIED' THEN 1 ELSE 0 END) AS occupied, SUM(CASE WHEN status='AVAILABLE' THEN 1 ELSE 0 END) AS available FROM beds WHERE active=1", ())


def _unique(exc: Exception) -> bool:
    text = str(exc).lower()
    return "unique" in text or "duplicate" in text


def insert_ward(conn, params: tuple) -> bool:
    conn.execute("SAVEPOINT ward_write")
    try:
        q_wards_13354(conn, *params)
        conn.execute("RELEASE SAVEPOINT ward_write")
        return True
    except Exception as exc:
        conn.execute("ROLLBACK TO SAVEPOINT ward_write")
        if _unique(exc):
            return False
        raise


def update_ward(conn, params: tuple) -> bool:
    conn.execute("SAVEPOINT ward_write")
    try:
        q_wards_12904(conn, *params)
        conn.execute("RELEASE SAVEPOINT ward_write")
        return True
    except Exception as exc:
        conn.execute("ROLLBACK TO SAVEPOINT ward_write")
        if _unique(exc):
            return False
        raise


def insert_room(conn, params: tuple) -> bool:
    conn.execute("SAVEPOINT room_write")
    try:
        q_wards_14080(conn, *params)
        conn.execute("RELEASE SAVEPOINT room_write")
        return True
    except Exception as exc:
        conn.execute("ROLLBACK TO SAVEPOINT room_write")
        if _unique(exc):
            return False
        raise


def insert_bed(conn, params: tuple) -> bool:
    conn.execute("SAVEPOINT bed_write")
    try:
        q_wards_14787(conn, *params)
        conn.execute("RELEASE SAVEPOINT bed_write")
        return True
    except Exception as exc:
        conn.execute("ROLLBACK TO SAVEPOINT bed_write")
        if _unique(exc):
            return False
        raise

def q_seed_10329(conn, p0, p1, p2, p3, p4, p5):
    return execute(conn, "INSERT INTO wards(id, name, code, ward_type, ac, active, sort_order) VALUES (?,?,?,?,?,1,?)", (p0, p1, p2, p3, p4, p5))

def q_seed_10631(conn, p0, p1, p2, p3, p4, p5):
    return execute(conn, "INSERT INTO rooms(id, ward_id, name, room_type, ac, daily_rate_paise, active) VALUES (?,?,?,?,?,?,1)", (p0, p1, p2, p3, p4, p5))

def q_seed_10927(conn, p0, p1, p2, p3):
    return execute(conn, "INSERT INTO beds(id, room_id, ward_id, name, status, active) VALUES (?,?,?,?, 'AVAILABLE', 1)", (p0, p1, p2, p3))

def bed_history_count(conn, bed_id: str) -> int:
    return (
        count_where(conn, "admissions", "bed_id", bed_id)
        + count_where(conn, "bed_movements", "from_bed_id", bed_id)
        + count_where(conn, "bed_movements", "to_bed_id", bed_id)
    )


def room_history_count(conn, room_id: str) -> int:
    return count_where(conn, "admissions", "room_id", room_id)


def ward_history_count(conn, ward_id: str) -> int:
    return count_where(conn, "admissions", "ward_id", ward_id)


def beds_in_room(conn, room_id: str):
    return rows(conn, "SELECT id, current_admission_id FROM beds WHERE room_id=?", (room_id,))


def rooms_in_ward(conn, ward_id: str):
    return rows(conn, "SELECT id FROM rooms WHERE ward_id=?", (ward_id,))


def delete_bed(conn, bed_id: str):
    return execute(conn, "DELETE FROM beds WHERE id=?", (bed_id,))


def delete_room(conn, room_id: str):
    return execute(conn, "DELETE FROM rooms WHERE id=?", (room_id,))


def delete_ward(conn, ward_id: str):
    return execute(conn, "DELETE FROM wards WHERE id=?", (ward_id,))


def q_seed_27321(conn):
    return execute(conn, "UPDATE beds SET status='OCCUPIED', current_admission_id='ADM-2026-000001' WHERE id='BD-R-W-GEN-Common-1'", ())

