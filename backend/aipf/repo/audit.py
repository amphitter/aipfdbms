"""SQL owned by the repository. Domain modules call these functions."""
from __future__ import annotations

from aipf.repo.sqlio import execute, one, rows

def q_core_4644(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11):
    return execute(conn, """INSERT INTO audit_logs
        (at, user_id, username, action, module, entity, entity_id, old_value, new_value, reason, workstation, ip)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11))

def q_core_5402(conn, p0, p1, p2, p3, p4, p5, p6, p7):
    return execute(conn, """INSERT INTO app_logs (at, level, module, message, user_id, entity, entity_id, extra)
           VALUES (?,?,?,?,?,?,?,?)""", (p0, p1, p2, p3, p4, p5, p6, p7))

def query_audit(conn, module: str = "", user_id: str = "", action: str = "", entity: str = "", day: str = "", limit: int = 200):
    sql = "SELECT * FROM audit_logs WHERE 1=1"
    params: list = []
    if module:
        sql += " AND module=?"
        params.append(module)
    if user_id:
        sql += " AND user_id=?"
        params.append(user_id)
    if action:
        sql += " AND action LIKE ?"
        params.append(f"%{action}%")
    if entity:
        sql += " AND (entity=? OR entity_id LIKE ?)"
        params.extend([entity, f"%{entity}%"])
    if day:
        sql += " AND substr(at,1,10)=?"
        params.append(day)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(min(limit, 500))
    return rows(conn, sql, params)


def query_logs(conn, module: str = "", level: str = "", limit: int = 200):
    sql = "SELECT * FROM app_logs WHERE 1=1"
    params: list = []
    if module:
        sql += " AND module=?"
        params.append(module)
    if level:
        sql += " AND level=?"
        params.append(level)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(min(limit, 500))
    return rows(conn, sql, params)
