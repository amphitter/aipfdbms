"""SQL owned by the repository. Domain modules call these functions."""
from __future__ import annotations

from aipf.repo.sqlio import execute, one, rows

def q_clinical_30101(conn, p0):
    return rows(conn, "SELECT * FROM deposits WHERE patient_id=? ORDER BY received_at DESC", (p0,))

def q_billing_1343(conn, p0):
    # Refund rows are included. recalc subtracts kind REFUND. Filtering them out left paid_paise unchanged.
    return rows(conn, "SELECT * FROM payments WHERE invoice_id=?", (p0,))

def q_billing_2494(conn, p0):
    return rows(conn, "SELECT * FROM deposits WHERE patient_id=? ORDER BY received_at DESC", (p0,))

def q_billing_2948(conn, p0):
    return rows(conn, "SELECT * FROM payments WHERE invoice_id=? ORDER BY received_at", (p0,))

def q_billing_11129(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11):
    return execute(conn, """INSERT INTO payments(id, invoice_id, patient_id, admission_id, kind, mode, amount_paise, reference, notes, received_by, workstation, received_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11))

def q_billing_12037(conn, p0):
    return one(conn, "SELECT * FROM deposits WHERE id=?", (p0,))

def q_billing_12784(conn, p0, p1, p2):
    return execute(conn, "UPDATE deposits SET balance_paise=?, status=? WHERE id=?", (p0, p1, p2))

def insert_deposit(conn, deposit_id, patient_id, admission_id, encounter_id, deposit_type, amount, balance, mode, reference, user_id, received_at, notes):
    return execute(
        conn,
        """INSERT INTO deposits(
             id, patient_id, admission_id, encounter_id, deposit_type,
             amount_paise, balance_paise, utilized_paise, mode, reference, received_by, received_at, notes, status
           ) VALUES (?,?,?,?,?,?,?,0,?,?,?,?,?, 'OPEN')""",
        (deposit_id, patient_id, admission_id, encounter_id, deposit_type, amount, balance, mode, reference, user_id, received_at, notes),
    )

def q_billing_13927(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10):
    return execute(conn, """INSERT INTO payments(id, invoice_id, patient_id, admission_id, kind, mode, amount_paise, reference, notes, received_by, workstation, received_at)
           VALUES (?,?,?,?, 'DEPOSIT', ?, ?, ?, ?, ?, ?, ?)""", (p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10))

def q_billing_14535(conn, p0):
    return one(conn, "SELECT * FROM deposits WHERE id=?", (p0,))

def q_billing_15059(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10):
    return execute(conn, """INSERT INTO payments(id, invoice_id, patient_id, admission_id, kind, mode, amount_paise, reference, notes, received_by, workstation, received_at)
           VALUES (?,?,?,?, 'REFUND', ?, ?, ?, ?, ?, ?, ?)""", (p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10))

def q_system_34858(conn, p0):
    return one(conn, "SELECT COALESCE(SUM(CASE WHEN kind='REFUND' THEN -amount_paise ELSE amount_paise END),0) AS n FROM payments WHERE substr(received_at,1,10)=? AND kind IN ('PAYMENT','DEPOSIT','DEPOSIT_APPLY','REFUND')", (p0,))

def q_system_38291(conn, p0):
    return rows(conn, """SELECT mode, kind, SUM(amount_paise) AS amount_paise, COUNT(*) AS n
           FROM payments WHERE substr(received_at,1,10)=? GROUP BY mode, kind""", (p0,))

def q_seed_26451(conn, p0):
    return execute(conn, """INSERT INTO payments(id, invoice_id, patient_id, kind, mode, amount_paise, received_by, received_at)
           VALUES ('PAY-S1','INV-S5','P-000007','PAYMENT','Cash',20000,'U-BILL',?)""", (p0,))

class IdempotencyConflict(Exception):
    """Same key, different payment payload. The stored checksum is left as-is."""


def _unique(exc: Exception) -> bool:
    text = str(exc).lower()
    return "unique" in text or "duplicate" in text


def get_idempotency(conn, key: str):
    return one(conn, "SELECT * FROM idempotency_keys WHERE idempotency_key=?", (key,))


def get_payment(conn, payment_id: str):
    return one(conn, "SELECT * FROM payments WHERE id=?", (payment_id,))


def latest_payment(conn, invoice_id: str, payment_id: str | None = None):
    if payment_id:
        return one(
            conn,
            "SELECT * FROM payments WHERE id=? AND invoice_id=? AND kind!='REFUND'",
            (payment_id, invoice_id),
        )
    return one(
        conn,
        "SELECT * FROM payments WHERE invoice_id=? AND kind!='REFUND' ORDER BY received_at DESC LIMIT 1",
        (invoice_id,),
    )


def insert_refund(conn, pid, invoice_id, patient_id, admission_id, mode, amount, reference, notes, user_id, workstation, received_at, reverses):
    return execute(
        conn,
        """INSERT INTO payments(id, invoice_id, patient_id, admission_id, kind, mode, amount_paise, reference, notes, received_by, workstation, received_at, reverses)
           VALUES (?,?,?,?, 'REFUND', ?, ?, ?, ?, ?, ?, ?, ?)""",
        (pid, invoice_id, patient_id, admission_id, mode, amount, reference, notes, user_id, workstation, received_at, reverses),
    )


def claim_payment(conn, key: str, request_hash: str, values: dict) -> dict:
    existing = get_idempotency(conn, key)
    if existing:
        if existing["request_hash"] != request_hash:
            raise IdempotencyConflict()
        return {"status": "replay", "payment_id": existing["entity_id"]}
    conn.execute("SAVEPOINT pay_idem")
    try:
        execute(
            conn,
            """INSERT INTO idempotency_keys(idempotency_key, scope, request_hash, entity_id, created_at)
               VALUES (?,?,?,?,?)""",
            (key, "payment", request_hash, values["id"], values["received_at"]),
        )
        execute(
            conn,
            """INSERT INTO payments(
                 id, invoice_id, patient_id, admission_id, kind, mode, amount_paise,
                 reference, notes, received_by, workstation, received_at, idempotency_key
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                values["id"], values["invoice_id"], values["patient_id"], values["admission_id"],
                values["kind"], values["mode"], values["amount_paise"], values["reference"],
                values["notes"], values["received_by"], values["workstation"], values["received_at"],
                key,
            ),
        )
        conn.execute("RELEASE SAVEPOINT pay_idem")
        return {"status": "created", "payment_id": values["id"]}
    except IdempotencyConflict:
        raise
    except Exception as exc:
        conn.execute("ROLLBACK TO SAVEPOINT pay_idem")
        try:
            conn.execute("RELEASE SAVEPOINT pay_idem")
        except Exception:
            pass
        if not _unique(exc):
            raise
        existing = get_idempotency(conn, key)
        if not existing or existing["request_hash"] != request_hash:
            raise IdempotencyConflict()
        return {"status": "replay", "payment_id": existing["entity_id"]}


def deposit_receipt(conn, deposit_id: str):
    return one(
        conn,
        "SELECT * FROM payments WHERE reference=? AND kind='DEPOSIT' AND reverses IS NULL ORDER BY received_at LIMIT 1",
        (deposit_id,),
    )


def lock_deposit(conn, deposit_id: str):
    if getattr(conn, "dialect", "") == "postgres":
        return one(conn, "SELECT * FROM deposits WHERE id=? FOR UPDATE", (deposit_id,))
    return one(conn, "SELECT * FROM deposits WHERE id=?", (deposit_id,))


def refunded_against(conn, payment_id: str) -> int:
    row = one(
        conn,
        "SELECT COALESCE(SUM(amount_paise),0) AS n FROM payments WHERE reverses=? AND kind='REFUND'",
        (payment_id,),
    )
    return int(row["n"] or 0)


def allocate_balance(conn, deposit_id: str, use: int) -> int:
    cur = execute(
        conn,
        """UPDATE deposits
           SET balance_paise = balance_paise - ?,
               utilized_paise = utilized_paise + ?,
               status = CASE WHEN balance_paise - ? = 0 THEN 'APPLIED' ELSE 'OPEN' END
           WHERE id=? AND status='OPEN' AND balance_paise >= ?""",
        (use, use, use, deposit_id, use),
    )
    return int(cur.rowcount)


def refund_unused(conn, deposit_id: str, balance: int) -> int:
    cur = execute(
        conn,
        """UPDATE deposits
           SET balance_paise=0, status='REFUNDED'
           WHERE id=? AND status='OPEN' AND balance_paise=?""",
        (deposit_id, balance),
    )
    return int(cur.rowcount)


def insert_keyed_refund(conn, pid, invoice_id, patient_id, admission_id, mode, amount, reference, notes, user_id, workstation, received_at, reverses, key):
    return execute(
        conn,
        """INSERT INTO payments(
             id, invoice_id, patient_id, admission_id, kind, mode, amount_paise, reference, notes,
             received_by, workstation, received_at, reverses, idempotency_key
           ) VALUES (?,?,?,?, 'REFUND', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (pid, invoice_id, patient_id, admission_id, mode, amount, reference, notes, user_id, workstation, received_at, reverses, key or None),
    )


def claim_scope(conn, key: str, scope: str, request_hash: str, entity_id: str, created_at: str) -> dict:
    existing = get_idempotency(conn, key)
    if existing:
        if existing["request_hash"] != request_hash:
            raise IdempotencyConflict()
        return {"status": "replay", "entity_id": existing["entity_id"]}
    conn.execute("SAVEPOINT scope_idem")
    try:
        execute(
            conn,
            """INSERT INTO idempotency_keys(idempotency_key, scope, request_hash, entity_id, created_at)
               VALUES (?,?,?,?,?)""",
            (key, scope, request_hash, entity_id, created_at),
        )
        conn.execute("RELEASE SAVEPOINT scope_idem")
        return {"status": "created", "entity_id": entity_id}
    except IdempotencyConflict:
        raise
    except Exception as exc:
        conn.execute("ROLLBACK TO SAVEPOINT scope_idem")
        try:
            conn.execute("RELEASE SAVEPOINT scope_idem")
        except Exception:
            pass
        if not _unique(exc):
            raise
        existing = get_idempotency(conn, key)
        if not existing or existing["request_hash"] != request_hash:
            raise IdempotencyConflict()
        return {"status": "replay", "entity_id": existing["entity_id"]}
