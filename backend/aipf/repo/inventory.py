"""SQL owned by the repository. Domain modules call these functions."""
from __future__ import annotations

from aipf.repo.sqlio import execute, one, rows

def q_pharmacy_704(conn, p0):
    return one(conn, "SELECT COALESCE(SUM(qty_on_hand),0) AS q FROM batches WHERE product_id=? AND active=1", (p0,))

def q_pharmacy_993(conn, p0):
    return rows(conn, "SELECT * FROM batches WHERE product_id=? AND active=1 ORDER BY expiry_date IS NULL, expiry_date, batch_no", (p0,))

def q_pharmacy_1314(conn, p0, p1, p2, p3, p4):
    return rows(conn, """SELECT * FROM products WHERE active=1 AND (
                 lower(name) LIKE ? OR lower(brand) LIKE ? OR lower(composition) LIKE ? OR barcode LIKE ? OR id LIKE ?
               ) ORDER BY name LIMIT 80""", (p0, p1, p2, p3, p4))

def q_pharmacy_1664(conn):
    return rows(conn, "SELECT * FROM products WHERE active=1 ORDER BY name", ())

def products_all(conn):
    return rows(conn, "SELECT * FROM products ORDER BY name", ())

def set_sku_active(conn, sku_id: str, active: int, stamp: str):
    return execute(conn, "UPDATE packaging_skus SET active=?, updated_at=? WHERE id=?", (active, stamp, sku_id))

def sku_row(conn, sku_id: str):
    return one(conn, "SELECT * FROM packaging_skus WHERE id=?", (sku_id,))

def set_barcode_active(conn, barcode_id: str, active: int, stamp: str):
    return execute(conn, "UPDATE barcodes SET active=?, updated_at=? WHERE id=?", (active, stamp, barcode_id))

def product_by_id(conn, product_id: str):
    return one(conn, "SELECT * FROM products WHERE id=?", (product_id,))


def barcode_row(conn, barcode_id: str):
    return one(conn, "SELECT * FROM barcodes WHERE id=?", (barcode_id,))

def q_pharmacy_2217(conn, p0):
    return one(conn, "SELECT * FROM products WHERE id=?", (p0,))

def q_pharmacy_3529(conn, p0):
    return one(conn, "SELECT id FROM products WHERE id=?", (p0,))

def q_pharmacy_3641(conn, *params):
    return execute(conn, """UPDATE products SET brand=?, name=?, composition=?, strength=?, dosage_form=?, manufacturer=?, unit=?, packaging=?,
               packaging_json=?, barcode=?, purchase_rate_paise=?, sale_rate_paise=?, mrp_paise=?, min_stock=?, reorder_level=?, active=?, updated_at=?
               WHERE id=?""", params)

def q_pharmacy_4076(conn, *params):
    return execute(conn, """INSERT INTO products(id, brand, name, composition, strength, dosage_form, manufacturer, unit, packaging, packaging_json,
               barcode, purchase_rate_paise, sale_rate_paise, mrp_paise, min_stock, reorder_level, active, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", params)

def q_pharmacy_4725(conn, p0):
    return one(conn, "SELECT * FROM products WHERE id=?", (p0,))

def q_pharmacy_5170(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10):
    return execute(conn, """INSERT INTO batches(id, product_id, batch_no, mfg_date, expiry_date, purchase_rate_paise, sale_rate_paise,
           qty_on_hand, unit, barcode, manufacturer, active, created_at)
           VALUES (?,?,?,?,?,?,?,0,?,?,?,1,?)""", (p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10))

def q_pharmacy_6164(conn, p0):
    return one(conn, "SELECT * FROM batches WHERE id=?", (p0,))

def q_pharmacy_6968(conn, p0):
    return one(conn, "SELECT * FROM batches WHERE id=?", (p0,))

def q_pharmacy_7744(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10):
    return execute(conn, """INSERT INTO stock_movements(product_id, batch_id, qty, unit, movement_type, reference_type, reference_id, reason, user_id, workstation, at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10))

def q_pharmacy_8270(conn, p0):
    return one(conn, "SELECT * FROM batches WHERE id=?", (p0,))

def q_pharmacy_9435(conn, p0):
    return one(conn, "SELECT * FROM batches WHERE id=?", (p0,))

def q_pharmacy_9509(conn, p0):
    return rows(conn, "SELECT movement_type, SUM(qty) AS qty FROM stock_movements WHERE batch_id=? GROUP BY movement_type", (p0,))

def q_pharmacy_10005(conn, p0):
    return one(conn, "SELECT * FROM batches WHERE barcode=? AND active=1", (p0,))

def q_pharmacy_10129(conn, p0):
    return one(conn, "SELECT * FROM products WHERE id=?", (p0,))

def q_pharmacy_10228(conn, p0):
    return one(conn, "SELECT * FROM products WHERE barcode=? AND active=1", (p0,))

def q_pharmacy_10348(conn, p0, p1):
    return one(conn, "SELECT * FROM products WHERE id=? OR name LIKE ? LIMIT 1", (p0, p1))

def q_pharmacy_11394(conn, p0, p1):
    return one(conn, """SELECT * FROM batches WHERE product_id=? AND active=1 AND qty_on_hand>0
           AND (expiry_date IS NULL OR expiry_date>=?)
           ORDER BY expiry_date IS NULL, expiry_date, created_at LIMIT 1""", (p0, p1))

def q_pharmacy_13670(conn, p0):
    return one(conn, "SELECT * FROM batches WHERE id=?", (p0,))

def q_pharmacy_14272(conn, p0):
    return one(conn, "SELECT * FROM products WHERE id=?", (p0,))

def q_pharmacy_17641(conn, p0):
    return rows(conn, """SELECT b.*, p.name AS product_name FROM batches b JOIN products p ON p.id=b.product_id
           WHERE b.qty_on_hand>0 AND b.expiry_date IS NOT NULL AND b.expiry_date < ? ORDER BY b.expiry_date""", (p0,))

def q_pharmacy_17910(conn, p0, p1):
    return rows(conn, """SELECT b.*, p.name AS product_name FROM batches b JOIN products p ON p.id=b.product_id
           WHERE b.qty_on_hand>0 AND b.expiry_date IS NOT NULL AND b.expiry_date >= ? AND b.expiry_date <= ?
           ORDER BY b.expiry_date""", (p0, p1))

def q_pharmacy_18253(conn):
    return rows(conn, "SELECT * FROM products WHERE active=1", ())

def q_pharmacy_18403(conn):
    # PostgreSQL does not allow a SELECT alias in HAVING. Compare the aggregate itself.
    return rows(conn, """SELECT b.id, b.batch_no, b.qty_on_hand, totals.ledger_qty, p.name AS product_name
           FROM batches b
           JOIN products p ON p.id=b.product_id
           JOIN (
             SELECT b2.id AS batch_id, COALESCE(SUM(m.qty), 0) AS ledger_qty
             FROM batches b2
             LEFT JOIN stock_movements m ON m.batch_id=b2.id
             GROUP BY b2.id
           ) totals ON totals.batch_id=b.id
           WHERE ABS(b.qty_on_hand - totals.ledger_qty) > 0.001""", ())

def q_system_34288(conn, p0, p1):
    return rows(conn, "SELECT id, name, strength, barcode FROM products WHERE lower(name) LIKE ? OR barcode LIKE ? LIMIT 8", (p0, p1))

def q_system_39315(conn, p0):
    return one(conn, "SELECT COUNT(*) AS n FROM stock_movements WHERE substr(at,1,10)=?", (p0,))

def q_system_40120(conn):
    return rows(conn, "SELECT p.name, b.batch_no, b.expiry_date, b.qty_on_hand, b.unit FROM batches b JOIN products p ON p.id=b.product_id ORDER BY p.name", ())

def q_system_44392(conn):
    return one(conn, "SELECT COUNT(*) AS n FROM products WHERE active=1", ())

def q_system_44661(conn):
    return one(conn, "SELECT COUNT(*) AS n FROM stock_movements", ())

def q_seed_14060(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11, p12, p13, p14, p15, p16, p17):
    return execute(conn, """INSERT INTO products(
                 id, brand, name, composition, strength, dosage_form, manufacturer, unit, packaging, packaging_json,
                 barcode, purchase_rate_paise, sale_rate_paise, mrp_paise, min_stock, reorder_level, active, created_at, updated_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)""", (p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11, p12, p13, p14, p15, p16, p17))

def q_seed_14706(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10):
    return execute(conn, """INSERT INTO batches(id, product_id, batch_no, mfg_date, expiry_date, purchase_rate_paise, sale_rate_paise, qty_on_hand, unit, barcode, active, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,1,?)""", (p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10))

def q_seed_15042(conn, p0, p1, p2, p3, p4, p5):
    return execute(conn, """INSERT INTO stock_movements(product_id, batch_id, qty, unit, movement_type, reference_type, reference_id, reason, at)
               VALUES (?,?,?,?, 'OPENING', 'seed', ?, 'Opening stock', ?)""", (p0, p1, p2, p3, p4, p5))

def q_seed_15409(conn, p0):
    return execute(conn, """INSERT INTO batches(id, product_id, batch_no, mfg_date, expiry_date, purchase_rate_paise, sale_rate_paise, qty_on_hand, unit, barcode, active, created_at)
           VALUES ('BAT-PR-CET2','PR-CET','B-CET-NEW','2026-06-01','2028-06-01',40,100,120,'Tablet','AIPFCET10B',1,?)""", (p0,))

def q_seed_15737(conn, p0):
    return execute(conn, """INSERT INTO stock_movements(product_id, batch_id, qty, unit, movement_type, reference_type, reference_id, reason, at)
           VALUES ('PR-CET','BAT-PR-CET2',120,'Tablet','OPENING','seed','BAT-PR-CET2','Opening stock',?)""", (p0,))

def search_for_billing(conn, needle: str):
    text = (needle or "").strip()
    if not text:
        return rows(conn, "SELECT * FROM products WHERE active=1 ORDER BY name LIMIT 20", ())
    like = f"%{text.lower()}%"
    raw = f"%{text}%"
    return rows(
        conn,
        """SELECT DISTINCT p.* FROM products p
           LEFT JOIN packaging_skus s ON s.product_id=p.id
           LEFT JOIN barcodes bc ON bc.sku_id=s.id AND bc.active=1
           LEFT JOIN batches b ON b.product_id=p.id
           WHERE p.active=1 AND (
             lower(p.name) LIKE ? OR lower(COALESCE(p.brand, '')) LIKE ? OR lower(COALESCE(p.composition, '')) LIKE ?
             OR lower(COALESCE(p.strength, '')) LIKE ? OR lower(COALESCE(s.name, '')) LIKE ?
             OR bc.value LIKE ? OR p.barcode LIKE ? OR b.barcode LIKE ? OR p.id LIKE ?
           )
           ORDER BY p.name LIMIT 20""",
        (like, like, like, like, like, raw, raw, raw, raw),
    )

def list_ledger(conn, product_id: str = "", batch_id: str = "", limit: int = 200):
    sql = """SELECT m.*, p.name AS product_name, b.batch_no, u.full_name AS user_name, inv.number AS bill_number
             FROM stock_movements m
             JOIN products p ON p.id=m.product_id
             JOIN batches b ON b.id=m.batch_id
             LEFT JOIN users u ON u.id=m.user_id
             LEFT JOIN invoices inv ON m.reference_type='invoice' AND inv.id=m.reference_id
             WHERE 1=1"""
    params: list = []
    if product_id:
        sql += " AND m.product_id=?"
        params.append(product_id)
    if batch_id:
        sql += " AND m.batch_id=?"
        params.append(batch_id)
    sql += " ORDER BY m.id DESC LIMIT ?"
    params.append(limit)
    return rows(conn, sql, params)
