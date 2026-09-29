"""SQL owned by the repository. Domain modules call these functions."""
from __future__ import annotations

from aipf.repo.sqlio import execute, one, rows

def q_core_10110(conn, p0, p1, p2, p3, p4, p5, p6):
    return execute(conn, """INSERT INTO sessions(token, user_id, workstation, ip, user_agent, created_at, expires_at)
           VALUES (?,?,?,?,?,?,?)""", (p0, p1, p2, p3, p4, p5, p6))

def q_core_10748(conn, p0, p1):
    return execute(conn, "UPDATE sessions SET revoked_at=? WHERE token=?", (p0, p1))

def revoke_stream_tickets(conn, revoked_at, user_id):
    return execute(conn, "UPDATE sessions SET revoked_at=? WHERE user_id=? AND workstation='event-stream' AND revoked_at IS NULL", (revoked_at, user_id))


def revoke_user_sessions(conn, revoked_at, user_id):
    return execute(conn, "UPDATE sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", (revoked_at, user_id))


def q_core_11503(conn, p0, p1):
    return execute(conn, "UPDATE sessions SET expires_at=? WHERE token=?", (p0, p1))

