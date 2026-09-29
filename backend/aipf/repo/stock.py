"""Batch quantity changes. The UPDATE is the lock. A movement is written only after it succeeds."""

from __future__ import annotations


def apply_stock_delta(conn, batch_id: str, signed_qty: float, allow_negative: bool) -> bool:
    if signed_qty < 0 and not allow_negative:
        cur = conn.execute(
            """UPDATE batches
               SET qty_on_hand = qty_on_hand + ?
               WHERE id = ? AND qty_on_hand + ? >= 0""",
            (signed_qty, batch_id, signed_qty),
        )
    else:
        cur = conn.execute(
            "UPDATE batches SET qty_on_hand = qty_on_hand + ? WHERE id = ?",
            (signed_qty, batch_id),
        )
    return cur.rowcount == 1
