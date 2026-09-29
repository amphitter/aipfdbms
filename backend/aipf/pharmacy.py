"""Products, batches, the stock ledger, and dispensing. Quantity is never edited in silence."""

from __future__ import annotations

from aipf.repo import encounters as encounters_sql
from aipf.repo import inventory as inventory_sql
from aipf.repo import patients as patients_sql
from aipf.repo import pharmacy as pharmacy_sql

import hashlib
import json
from datetime import timedelta

from .access import can_view_patient
from .billing import add_item, open_draft
from .core import audit, config_get, permit
from .db import begin, commit, execute, one, rollback, rows
from .repo.stock import apply_stock_delta
from .events import publish
from .util import (
    ApiError,
    clean_text,
    display_age,
    money_mul,
    new_id,
    now,
    now_iso,
    require,
    today_str,
)

MOVEMENT_TYPES = ["OPENING", "PURCHASE", "RETURN", "ADJUSTMENT", "DISPENSED", "DAMAGED", "EXPIRED", "LOST", "BILLING_ISSUE", "BILLING_RETURN"]
INBOUND = {"OPENING", "PURCHASE", "RETURN", "BILLING_RETURN"}


def product_stock(conn, product_id: str) -> float:
    row = inventory_sql.q_pharmacy_704(conn, product_id)
    return float(row["q"] if row else 0)


def enrich_product(conn, product: dict) -> dict:
    product["stock"] = product_stock(conn, product["id"])
    product["batches"] = inventory_sql.q_pharmacy_993(conn, product["id"])
    product["skus"] = rows(
        conn,
        """SELECT id, product_id, name, unit, units_per_pack, active
           FROM packaging_skus WHERE product_id=? ORDER BY created_at, id""",
        (product["id"],),
    )
    product["barcodes"] = rows(
        conn,
        """SELECT b.id, b.sku_id, b.batch_id, b.value, b.barcode_type, b.scope, b.active,
                  s.name AS sku_name, s.units_per_pack
           FROM barcodes b JOIN packaging_skus s ON s.id=b.sku_id
           WHERE s.product_id=? ORDER BY b.created_at, b.id""",
        (product["id"],),
    )
    return product


def list_products(conn, q: str = "", alerts_only: bool = False, include_inactive: bool = False) -> dict:
    if include_inactive:
        items = inventory_sql.products_all(conn)
        needle = (q or "").strip().lower()
        if needle:
            items = [item for item in items if needle in " ".join(str(item.get(key) or "") for key in ("name", "brand", "composition", "barcode", "id")).lower()]
    elif q:
        like = f"%{q.lower()}%"
        items = inventory_sql.q_pharmacy_1314(conn, like, like, like, f"%{q.strip()}%", f"%{q.strip()}%")
    else:
        items = inventory_sql.q_pharmacy_1664(conn)
    enriched = [enrich_product(conn, p) for p in items]
    if alerts_only:
        today = today_str()
        soon = (now() + timedelta(days=90)).date().isoformat()
        enriched = [
            p for p in enriched
            if p["stock"] <= (p["reorder_level"] or 0)
            or any((b.get("expiry_date") or "9999") <= soon for b in p["batches"])
        ]
    return {"items": enriched, "total": len(enriched)}


def get_product(conn, product_id: str) -> dict:
    product = inventory_sql.q_pharmacy_2217(conn, product_id)
    require(product, "Product not found.", 404, "not_found")
    return enrich_product(conn, product)


def save_product(conn, user, payload: dict, product_id: str | None = None) -> dict:
    permit(user, "inventory.edit")
    name = clean_text(payload.get("name"), 160)
    require(name, "Product name is required.")
    fields = (
        clean_text(payload.get("brand"), 120),
        name,
        clean_text(payload.get("composition"), 240),
        clean_text(payload.get("strength"), 60),
        clean_text(payload.get("dosage_form"), 40),
        clean_text(payload.get("manufacturer"), 120),
        clean_text(payload.get("unit") or "Tablet", 40),
        clean_text(payload.get("packaging"), 160),
        payload.get("packaging_json") if isinstance(payload.get("packaging_json"), str) else json.dumps(payload.get("packaging_json") or {}),
        clean_text(payload.get("barcode"), 80) or None,
        int(payload.get("purchase_rate_paise") or 0),
        int(payload.get("sale_rate_paise") or 0),
        int(payload.get("mrp_paise") or 0) or None,
        float(payload.get("min_stock") or 0),
        float(payload.get("reorder_level") or 0),
        1 if payload.get("active", True) else 0,
    )
    if product_id:
        require(inventory_sql.q_pharmacy_3529(conn, product_id), "Product not found.", 404, "not_found")
        inventory_sql.q_pharmacy_3641(conn, *fields, now_iso(), product_id)
    else:
        product_id = new_id("PR")
        inventory_sql.q_pharmacy_4076(conn, product_id, *fields, now_iso(), now_iso())
    audit(conn, user, "product_save", "pharmacy", "product", product_id, new={"name": name})
    return get_product(conn, product_id)


def add_batch(conn, user, payload: dict) -> dict:
    permit(user, "inventory.edit")
    product = inventory_sql.q_pharmacy_4725(conn, payload.get("product_id"))
    require(product, "Product not found.", 404, "not_found")
    batch_no = clean_text(payload.get("batch_no"), 60)
    require(batch_no, "Batch number is required.")
    qty = float(payload.get("qty") or 0)
    require(qty > 0, "Opening quantity must be greater than zero.")
    bid = new_id("B")
    unit = clean_text(payload.get("unit") or product["unit"], 40)
    try:
        inventory_sql.q_pharmacy_5170(conn, bid, product["id"], batch_no, clean_text(payload.get("mfg_date"), 10) or None, clean_text(payload.get("expiry_date"), 10) or None, int(payload.get("purchase_rate_paise") or product["purchase_rate_paise"]), int(payload.get("sale_rate_paise") or product["sale_rate_paise"]), unit, clean_text(payload.get("barcode"), 80) or None, clean_text(payload.get("manufacturer") or product.get("manufacturer"), 120), now_iso())
    except Exception as exc:
        if _is_unique(exc):
            raise ApiError("That batch number already exists for this product.", 409, "batch_conflict") from exc
        raise
    move(conn, user, bid, qty, "OPENING", "batch", bid, payload.get("reason") or "Opening stock")
    audit(conn, user, "batch_create", "pharmacy", "batch", bid, new={"batch_no": batch_no, "qty": qty})
    return inventory_sql.q_pharmacy_6164(conn, bid)


def move(conn, user, batch_id: str, qty: float, movement_type: str, reference_type: str = "", reference_id: str = "", reason: str = "") -> dict:
    from .db import begin, commit, rollback

    own_tx = not conn.in_transaction
    if own_tx:
        begin(conn)
    try:
        result = _move(conn, user, batch_id, qty, movement_type, reference_type, reference_id, reason)
        if own_tx:
            commit(conn)
        return result
    except Exception:
        if own_tx:
            rollback(conn)
        raise


def _move(conn, user, batch_id: str, qty: float, movement_type: str, reference_type: str = "", reference_id: str = "", reason: str = "") -> dict:
    require(movement_type in MOVEMENT_TYPES, "Unknown movement type.")
    batch = inventory_sql.q_pharmacy_6968(conn, batch_id)
    require(batch, "Batch not found.", 404, "not_found")
    signed = float(qty)
    if movement_type not in INBOUND and signed > 0:
        signed = -signed
    if movement_type in INBOUND and signed < 0:
        signed = abs(signed)
    allow_negative = config_get(conn, "allow_negative_stock", "0") == "1"
    if movement_type == "BILLING_ISSUE":
        allow_negative = False
    if movement_type in ("ADJUSTMENT", "DAMAGED", "EXPIRED", "LOST") and not clean_text(reason, 240):
        raise ApiError("A reason is required for this stock movement.")
    if not apply_stock_delta(conn, batch_id, signed, allow_negative):
        raise ApiError(
            f"Batch {batch['batch_no']} does not have enough stock. On hand {batch['qty_on_hand']}, requested {abs(signed)}."
        )
    inventory_sql.q_pharmacy_7744(conn, batch["product_id"], batch_id, signed, batch.get("unit"), movement_type, reference_type, reference_id, clean_text(reason, 240), (user or {}).get("id"), (user or {}).get("workstation"), now_iso())
    publish("inventory.updated", {"batch_id": batch_id, "product_id": batch["product_id"]})
    return inventory_sql.q_pharmacy_8270(conn, batch_id)


def post_movement(conn, user, payload: dict) -> dict:
    permit(user, "inventory.adjust")
    if (payload.get("movement_type") or "") in ("BILLING_ISSUE", "BILLING_RETURN"):
        raise ApiError("A bill records this stock movement. It cannot be posted as a manual adjustment.")
    return move(
        conn, user, payload["batch_id"], float(payload.get("qty") or 0),
        payload.get("movement_type") or "ADJUSTMENT",
        payload.get("reference_type") or "manual",
        payload.get("reference_id") or "",
        payload.get("reason") or "",
    )


def ledger(conn, product_id: str = "", batch_id: str = "", limit: int = 200) -> dict:
    items = inventory_sql.list_ledger(conn, product_id, batch_id, limit)
    for item in items:
        if item.get("bill_number"):
            item["explained_by"] = f"Billing → Bill {item['bill_number']}"
    summary = None
    if batch_id:
        batch = inventory_sql.q_pharmacy_9435(conn, batch_id)
        sums = inventory_sql.q_pharmacy_9509(conn, batch_id)
        summary = {"batch": batch, "by_type": {s["movement_type"]: s["qty"] for s in sums}, "on_hand": batch["qty_on_hand"] if batch else 0}
    return {"items": items, "summary": summary}


def _is_unique(exc: Exception) -> bool:
    text = str(exc).lower()
    return "unique" in text or "duplicate" in text


def _date_text(value, label: str) -> str:
    text = clean_text(value, 10)
    require(len(text) == 10 and text[4] == "-" and text[7] == "-", f"{label} must be YYYY-MM-DD.")
    return text


BARCODE_TYPES = (
    ("EAN-13", "EAN-13"),
    ("EAN-8", "EAN-8"),
    ("UPC-A", "UPC-A"),
    ("CODE-128", "Code 128"),
    ("CODE-39", "Code 39"),
    ("QR", "QR"),
    ("DATAMATRIX", "Data Matrix"),
    ("INTERNAL", "Internal"),
)


def ensure_barcode_types(conn) -> None:
    for code, name in BARCODE_TYPES:
        execute(
            conn,
            """INSERT INTO barcode_types(code, name, active)
               SELECT ?, ?, 1 WHERE NOT EXISTS (SELECT 1 FROM barcode_types WHERE code=?)""",
            (code, name, code),
        )


def seed_registered_barcodes(conn) -> None:
    """Register each seeded product barcode as a base-unit SKU. Pack text is not a conversion."""
    ensure_barcode_types(conn)
    products = rows(conn, "SELECT id, unit, barcode FROM products WHERE barcode IS NOT NULL AND barcode != ''")
    stamp = now_iso()
    for product in products:
        sku_id = "SKU-" + product["id"]
        if not one(conn, "SELECT id FROM packaging_skus WHERE id=?", (sku_id,)):
            execute(
                conn,
                """INSERT INTO packaging_skus(id, product_id, name, unit, units_per_pack, active, created_at, updated_at)
                   VALUES (?,?,?,?,1,1,?,?)""",
                (sku_id, product["id"], "Base unit", product.get("unit") or "Unit", stamp, stamp),
            )
        barcode_id = "BC-" + product["id"]
        if not one(conn, "SELECT id FROM barcodes WHERE id=?", (barcode_id,)):
            execute(
                conn,
                """INSERT INTO barcodes(id, sku_id, batch_id, value, barcode_type, scope, active, created_at, updated_at)
                   VALUES (?,?,NULL,?,?, 'SKU', 1, ?, ?)""",
                (barcode_id, sku_id, product["barcode"], "INTERNAL", stamp, stamp),
            )


def barcode_types(conn) -> dict:
    items = rows(conn, "SELECT code, name, active FROM barcode_types WHERE active=1 ORDER BY code")
    return {"items": items}


def save_barcode_type(conn, user, payload: dict) -> dict:
    permit(user, "master.manage")
    code = clean_text(payload.get("code"), 40).upper()
    name = clean_text(payload.get("name"), 80) or code
    require(code, "Barcode type needs a code.")
    execute(
        conn,
        """INSERT INTO barcode_types(code, name, active)
           SELECT ?, ?, 1 WHERE NOT EXISTS (SELECT 1 FROM barcode_types WHERE code=?)""",
        (code, name, code),
    )
    audit(conn, user, "barcode_type_save", "pharmacy", "barcode_type", code, new={"name": name})
    return barcode_types(conn)


def save_sku(conn, user, payload: dict) -> dict:
    permit(user, "inventory.edit")
    product = inventory_sql.q_pharmacy_4725(conn, payload.get("product_id"))
    require(product, "Product not found.", 404, "not_found")
    name = clean_text(payload.get("name"), 80)
    unit = clean_text(payload.get("unit"), 40)
    require(name and unit, "A package needs a name and a unit.")
    raw_size = payload.get("units_per_pack")
    require(raw_size not in (None, ""), "Enter how many base units this package contains. It is not assumed.")
    try:
        units = int(raw_size)
    except (TypeError, ValueError) as exc:
        raise ApiError("Package size must be a whole number.") from exc
    require(units > 0, "Package size must be greater than zero.")
    sku_id = new_id("SKU")
    stamp = now_iso()
    execute(
        conn,
        """INSERT INTO packaging_skus(id, product_id, name, unit, units_per_pack, active, created_at, updated_at)
           VALUES (?,?,?,?,?,1,?,?)""",
        (sku_id, product["id"], name, unit, units, stamp, stamp),
    )
    audit(conn, user, "sku_save", "pharmacy", "packaging_sku", sku_id, new={"product_id": product["id"], "units_per_pack": units})
    return one(conn, "SELECT * FROM packaging_skus WHERE id=?", (sku_id,))


def set_sku_active(conn, user, sku_id: str, payload: dict) -> dict:
    permit(user, "inventory.edit")
    row = inventory_sql.sku_row(conn, sku_id)
    require(row, "Packaging not found.", 404, "not_found")
    active = 1 if payload.get("active") else 0
    inventory_sql.set_sku_active(conn, sku_id, active, now_iso())
    audit(conn, user, "sku_active", "pharmacy", "packaging_sku", sku_id, new={"active": bool(active)})
    return inventory_sql.sku_row(conn, sku_id)


def set_barcode_active(conn, user, barcode_id: str, payload: dict) -> dict:
    permit(user, "inventory.edit")
    row = inventory_sql.barcode_row(conn, barcode_id)
    require(row, "Barcode not found.", 404, "not_found")
    active = 1 if payload.get("active") else 0
    inventory_sql.set_barcode_active(conn, barcode_id, active, now_iso())
    audit(conn, user, "barcode_active", "pharmacy", "barcode", barcode_id, new={"active": bool(active)})
    return inventory_sql.barcode_row(conn, barcode_id)


def save_barcode(conn, user, payload: dict) -> dict:
    permit(user, "inventory.edit")
    sku = one(conn, "SELECT * FROM packaging_skus WHERE id=?", (payload.get("sku_id"),))
    require(sku, "Package not found.", 404, "not_found")
    value = clean_text(payload.get("value") or payload.get("barcode"), 80)
    require(value, "Barcode value is required.")
    code = clean_text(payload.get("barcode_type"), 40).upper()
    kind = one(conn, "SELECT code FROM barcode_types WHERE code=? AND active=1", (code,))
    require(kind, "That barcode type is not configured.", 400, "barcode_type")
    scope = clean_text(payload.get("scope") or "SKU", 10).upper()
    require(scope in ("SKU", "BATCH"), "Barcode scope must be SKU or BATCH.")
    batch_id = payload.get("batch_id") or None
    if scope == "BATCH":
        batch = inventory_sql.q_pharmacy_9435(conn, batch_id)
        require(batch and batch["product_id"] == sku["product_id"], "A batch barcode must belong to the same product.")
    else:
        require(not batch_id, "A package barcode cannot identify a batch.")
        batch_id = None
    barcode_id = new_id("BC")
    stamp = now_iso()
    try:
        execute(
            conn,
            """INSERT INTO barcodes(id, sku_id, batch_id, value, barcode_type, scope, active, created_at, updated_at)
               VALUES (?,?,?,?,?,?,1,?,?)""",
            (barcode_id, sku["id"], batch_id, value, code, scope, stamp, stamp),
        )
    except Exception as exc:
        if _is_unique(exc):
            raise ApiError("That barcode is already active on another package.", 409, "ambiguous_barcode") from exc
        raise
    audit(conn, user, "barcode_save", "pharmacy", "barcode", barcode_id, new={"sku_id": sku["id"], "scope": scope, "barcode_type": code})
    return one(conn, "SELECT * FROM barcodes WHERE id=?", (barcode_id,))


def _suggestions(conn, product_id: str) -> list[dict]:
    today = today_str()
    return rows(
        conn,
        """SELECT id, batch_no, expiry_date, qty_on_hand, sale_rate_paise, unit
           FROM batches
           WHERE product_id=? AND active=1 AND qty_on_hand>0
             AND (expiry_date IS NULL OR expiry_date>=?)
           ORDER BY CASE WHEN expiry_date IS NULL THEN 1 ELSE 0 END, expiry_date, created_at""",
        (product_id, today),
    )


def resolve_barcode(conn, raw: str) -> dict:
    """Identify a package. This does not dispense, receive, or create a product."""
    code = clean_text(raw, 80)
    require(code, "Scan a barcode.")
    matches = rows(
        conn,
        """SELECT b.*, s.product_id, s.name AS sku_name, s.unit AS sku_unit, s.units_per_pack
           FROM barcodes b JOIN packaging_skus s ON s.id=b.sku_id
           WHERE b.value=? AND b.active=1 AND s.active=1""",
        (code,),
    )
    if len(matches) > 1:
        raise ApiError("This barcode matches more than one package. It was not used.", 409, "ambiguous_barcode")
    if len(matches) == 1:
        match = matches[0]
        product = inventory_sql.q_pharmacy_10129(conn, match["product_id"])
        require(product and int(product.get("active") or 0) == 1, "Unknown barcode. No product was created.", 404, "not_found")
        matched_batch = None
        if match["scope"] == "BATCH" and match.get("batch_id"):
            matched_batch = one(
                conn,
                "SELECT id, product_id, batch_no, expiry_date, qty_on_hand, active FROM batches WHERE id=?",
                (match["batch_id"],),
            )
        return _resolution(code, product, match, matched_batch, _suggestions(conn, product["id"]))
    retired = one(conn, "SELECT id FROM barcodes WHERE value=?", (code,))
    if retired:
        raise ApiError("Unknown barcode. No product was created.", 404, "not_found")
    legacy = rows(conn, "SELECT * FROM products WHERE barcode=? AND active=1", (code,))
    if len(legacy) > 1:
        raise ApiError("This barcode matches more than one package. It was not used.", 409, "ambiguous_barcode")
    if len(legacy) == 1:
        return _resolution(code, legacy[0], None, None, _suggestions(conn, legacy[0]["id"]))
    raise ApiError("Unknown barcode. No product was created.", 404, "not_found")


def _resolution(code: str, product: dict, barcode: dict | None, matched_batch: dict | None, suggestions: list[dict]) -> dict:
    sku = None
    barcode_out = None
    if barcode:
        sku = {
            "id": barcode["sku_id"],
            "name": barcode.get("sku_name"),
            "unit": barcode.get("sku_unit"),
            "units_per_pack": barcode.get("units_per_pack"),
        }
        barcode_out = {
            "id": barcode["id"],
            "value": barcode["value"],
            "barcode_type": barcode["barcode_type"],
            "scope": barcode["scope"],
        }
    return {
        "code": code,
        "resolved_only": True,
        "dispensed": False,
        "stock_changed": False,
        "product": {
            "id": product["id"],
            "name": product["name"],
            "brand": product.get("brand"),
            "composition": product.get("composition"),
            "strength": product.get("strength"),
            "manufacturer": product.get("manufacturer"),
            "dosage_form": product.get("dosage_form"),
            "unit": product.get("unit"),
            "stock": None,
        },
        "sku": sku,
        "barcode": barcode_out,
        "matched_batch": matched_batch if barcode and barcode.get("scope") == "BATCH" else None,
        "suggestions": suggestions,
    }


def resolve_for_user(conn, user, code: str) -> dict:
    perms = set((user or {}).get("permissions") or [])
    if "pharmacy.view" not in perms and "inventory.view" not in perms and "billing.medicine_issue" not in perms:
        raise ApiError("You do not have permission for this action.", 403, "forbidden")
    found = resolve_barcode(conn, code)
    found["product"]["stock"] = product_stock(conn, found["product"]["id"])
    return found


def lookup_barcode(conn, raw: str) -> dict:
    found = resolve_barcode(conn, raw)
    found["product"]["stock"] = product_stock(conn, found["product"]["id"])
    found["raw"] = found["code"]
    found["batch"] = found.get("matched_batch")
    return found


def receive_stock(conn, user, payload: dict) -> dict:
    """Receive into a selected or new batch. A barcode scan alone does not create stock or a product.

    This is not a supplier or GRN purchase. There is no purchase order and no supplier invoice.
    Quantity is base units. The stored package size is shown to the operator and is not applied silently.
    """
    permit(user, "inventory.edit")
    code = clean_text(payload.get("barcode"), 80)
    product_id = payload.get("product_id")
    sku = None
    if code:
        resolved = resolve_barcode(conn, code)
        if product_id and product_id != resolved["product"]["id"]:
            raise ApiError("The barcode does not belong to that product.", 409, "product_mismatch")
        product_id = resolved["product"]["id"]
        sku = resolved.get("sku")
        if resolved.get("matched_batch") and not payload.get("batch_id") and not payload.get("batch_no"):
            payload = {**payload, "batch_id": resolved["matched_batch"]["id"]}
    require(product_id, "Choose a product. An unknown scan cannot create one.")
    product = inventory_sql.q_pharmacy_4725(conn, product_id)
    require(product and int(product.get("active") or 0) == 1, "Product not found.", 404, "not_found")
    try:
        qty = float(payload.get("qty") or 0)
    except (TypeError, ValueError) as exc:
        raise ApiError("Enter the quantity to receive.") from exc
    require(qty > 0, "Enter the quantity to receive. A scan does not create stock.")
    batch_id = payload.get("batch_id")
    if batch_id:
        batch = inventory_sql.q_pharmacy_9435(conn, batch_id)
        require(batch and batch["product_id"] == product["id"], "Batch does not belong to this product.", 409, "batch_conflict")
        require(int(batch.get("active") or 0) == 1, "Batch is inactive.")
    else:
        batch_no = clean_text(payload.get("batch_no"), 60)
        require(batch_no, "Select a batch or enter a batch number.")
        existing = one(conn, "SELECT * FROM batches WHERE product_id=? AND batch_no=?", (product["id"], batch_no))
        expiry = clean_text(payload.get("expiry_date"), 10)
        mfg = clean_text(payload.get("mfg_date"), 10)
        if existing:
            if expiry and existing.get("expiry_date") and expiry != existing["expiry_date"]:
                raise ApiError("That batch already exists with a different expiry.", 409, "batch_conflict")
            require(int(existing.get("active") or 0) == 1, "Batch is inactive.")
            batch_id = existing["id"]
        else:
            mfg = _date_text(mfg, "Manufacturing date")
            expiry = _date_text(expiry, "Expiry date")
            require(mfg <= expiry, "Manufacturing date cannot be after expiry.")
            require(expiry >= today_str(), "Refusing to receive an already expired batch.")
            batch_id = new_id("BAT")
            unit = clean_text(payload.get("unit") or product["unit"], 40)
            inventory_sql.q_pharmacy_5170(
                conn, batch_id, product["id"], batch_no, mfg, expiry,
                int(payload.get("purchase_rate_paise") or product["purchase_rate_paise"]),
                int(payload.get("sale_rate_paise") or product["sale_rate_paise"]),
                unit, None, clean_text(product.get("manufacturer"), 120), now_iso(),
            )
    move(conn, user, batch_id, qty, "PURCHASE", "receive", batch_id, "Received into stock")
    audit(conn, user, "stock_receive", "pharmacy", "batch", batch_id, new={"product_id": product["id"], "qty": qty})
    batch = inventory_sql.q_pharmacy_9435(conn, batch_id)
    return {"product_id": product["id"], "batch": batch, "sku": sku, "received_qty": qty, "created_product": False}


def pharmacy_queue(conn, user) -> dict:
    items = patients_sql.q_pharmacy_10684(conn)
    visible = []
    for rx in items:
        if not can_view_patient(conn, user, rx.get("patient_id")):
            continue
        rx["items"] = encounters_sql.q_pharmacy_11164(conn, rx["id"])
        rx["age_display"] = display_age(rx)
        for field in ("primary_phone", "dob"):
            rx.pop(field, None)
        visible.append(rx)
    return {"items": visible, "total": len(visible)}


def _fefo_batch(conn, product_id: str):
    today = today_str()
    return inventory_sql.q_pharmacy_11394(conn, product_id, today)


def _dispense_hash(prescription_id: str, lines: list[dict]) -> str:
    normalized = []
    for line in lines:
        normalized.append({
            "item_id": line.get("item_id"),
            "product_id": line.get("product_id"),
            "batch_id": line.get("batch_id"),
            "qty": round(float(line.get("qty") or 0), 4),
            "substituted": bool(line.get("substituted")),
            "substitution_reason": clean_text(line.get("substitution_reason"), 240),
        })
    normalized.sort(key=lambda row: str(row["item_id"]))
    body = {"prescription_id": prescription_id, "lines": normalized}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def _claim_dispense(conn, key: str, digest: str, prescription_id: str):
    existing = one(conn, "SELECT * FROM dispense_idempotency WHERE idempotency_key=?", (key,))
    if existing:
        return _replay_or_conflict(existing, digest)
    try:
        conn.execute("SAVEPOINT disp_idem")
        execute(
            conn,
            """INSERT INTO dispense_idempotency(idempotency_key, request_hash, prescription_id, result_json, created_at)
               VALUES (?,?,?,?,?)""",
            (key, digest, prescription_id, None, now_iso()),
        )
        conn.execute("RELEASE SAVEPOINT disp_idem")
    except Exception as exc:
        try:
            conn.execute("ROLLBACK TO SAVEPOINT disp_idem")
        except Exception:
            pass
        if not _is_unique(exc):
            raise
        existing = one(conn, "SELECT * FROM dispense_idempotency WHERE idempotency_key=?", (key,))
        if not existing:
            raise
        return _replay_or_conflict(existing, digest)
    return None


def _replay_or_conflict(existing: dict, digest: str):
    if existing["request_hash"] != digest:
        raise ApiError("This idempotency key was already used for a different dispense.", 409, "idempotency_conflict")
    if not existing.get("result_json"):
        raise ApiError("This dispense is already in progress.", 409, "idempotency_conflict")
    result = json.loads(existing["result_json"])
    result["idempotent_replay"] = True
    return result


def dispense(conn, user, payload: dict, idempotency_key: str | None = None, *, require_key: bool = False) -> dict:
    permit(user, "pharmacy.dispense")
    key = clean_text(idempotency_key, 120) if idempotency_key else ""
    if require_key and not key:
        raise ApiError("Dispense needs an idempotency key.", 400, "idempotency_required")
    rx = encounters_sql.q_pharmacy_11761(conn, payload.get("prescription_id"))
    require(rx, "Prescription not found.", 404, "not_found")
    require(rx["status"] in ("FINALIZED", "PARTIAL"), "Finalize the prescription before dispensing.")
    lines = payload.get("lines") or []
    require(lines, "Select at least one line to dispense.")
    digest = _dispense_hash(rx["id"], lines) if key else ""
    own = not conn.in_transaction
    if own:
        begin(conn)
    try:
        if key:
            replay = _claim_dispense(conn, key, digest, rx["id"])
            if replay:
                if own:
                    rollback(conn)
                return replay
        result = _dispense_lines(conn, user, rx, lines)
        if key:
            execute(
                conn,
                "UPDATE dispense_idempotency SET result_json=? WHERE idempotency_key=?",
                (json.dumps(result, default=str), key),
            )
        if own:
            commit(conn)
        return result
    except Exception:
        if own:
            rollback(conn)
        raise


def _dispense_lines(conn, user, rx: dict, lines: list[dict]) -> dict:
    invoice = open_draft(conn, user, rx["patient_id"], rx["encounter_id"], None, "OPD", 0)
    created = []
    allow_expired = config_get(conn, "allow_expired_dispense", "0") == "1"
    for line in lines:
        item = encounters_sql.q_pharmacy_12331(conn, line.get("item_id"), rx["id"])
        require(item, "Prescription line not found.")
        qty = float(line.get("qty") or 0)
        require(qty > 0, "Dispense quantity must be greater than zero.")
        remaining = float(item.get("quantity") or 0) - float(item.get("dispensed_qty") or 0)
        if item.get("quantity"):
            require(qty <= remaining + 0.0001, f"{item['medicine_name']} only has {remaining:g} left to dispense.")
        batch_id = line.get("batch_id")
        product_id = line.get("product_id") or item.get("product_id")
        substituted = 0
        sub_reason = ""
        if line.get("substituted"):
            require(clean_text(line.get("substitution_reason"), 240), "A substitution needs an explicit reason.")
            require(product_id, "Choose the substitute product.")
            substituted = 1
            sub_reason = clean_text(line.get("substitution_reason"), 240)
        if not product_id:
            raise ApiError(f"Link {item['medicine_name']} to a stock product before dispensing.")
        prescribed = item.get("product_id")
        if prescribed and prescribed != product_id and not substituted:
            raise ApiError(
                "This product is not what was prescribed. Substitution needs an explicit reason.",
                409,
                "product_mismatch",
            )
        if not batch_id:
            suggested = _fefo_batch(conn, product_id)
            require(suggested, "No usable batch is in stock for this medicine.")
            batch_id = suggested["id"]
        batch = inventory_sql.q_pharmacy_13670(conn, batch_id)
        require(batch and batch["product_id"] == product_id, "Batch does not belong to the selected product.", 409, "batch_conflict")
        require(int(batch.get("active") or 0) == 1, "Batch is inactive.")
        if batch.get("expiry_date") and batch["expiry_date"] < today_str() and not allow_expired:
            raise ApiError(f"Batch {batch['batch_no']} expired on {batch['expiry_date']}. It cannot be dispensed.")
        move(conn, user, batch_id, qty, "DISPENSED", "prescription", rx["id"], f"Dispensed against {rx['id']}")
        rate = int(batch["sale_rate_paise"] or 0)
        amount = money_mul(rate, qty)
        product = inventory_sql.q_pharmacy_14272(conn, product_id)
        line_id = new_id("DL")
        description = f"{product['name']} {product.get('strength') or ''} · batch {batch['batch_no']}".strip()
        if substituted:
            description = f"Substitute: {description} (for {item['medicine_name']})"
        updated_invoice = add_item(
            conn,
            user,
            invoice["id"],
            {
                "description": description,
                "category": "PHARMACY",
                "rate_paise": rate,
                "qty": qty,
                "unit": batch.get("unit") or product.get("unit"),
                "source_module": "pharmacy",
                "source_id": line_id,
                "master_item_id": product_id,
                "batch_id": batch_id,
            },
        )
        invoice_item_id = updated_invoice["added_item_id"]
        pharmacy_sql.q_pharmacy_15133(conn, line_id, rx["id"], item["id"], rx["patient_id"], rx["encounter_id"], product_id, batch_id, qty, batch.get("unit"), rate, amount, substituted, sub_reason, invoice_item_id, user["id"], now_iso())
        dispensed_qty = float(item.get("dispensed_qty") or 0) + qty
        status = "DISPENSED"
        if item.get("quantity") and dispensed_qty + 0.0001 < float(item["quantity"]):
            status = "PARTIAL"
        if substituted:
            status = "SUBSTITUTED" if status == "DISPENSED" else status
        link_product = None if substituted else product_id
        encounters_sql.q_pharmacy_16054(conn, dispensed_qty, status, link_product, item["id"])
        created.append(line_id)
    pending = encounters_sql.q_pharmacy_16303(conn, rx["id"])
    new_status = "PARTIAL" if pending and pending["n"] else "DISPENSED"
    # If every line with a quantity is fully dispensed, mark dispensed.
    open_lines = encounters_sql.q_pharmacy_16748(conn, rx["id"])
    if any((i.get("quantity") or 0) and float(i["dispensed_qty"] or 0) + 0.0001 < float(i["quantity"]) for i in open_lines):
        new_status = "PARTIAL"
    else:
        new_status = "DISPENSED"
    encounters_sql.q_pharmacy_17035(conn, new_status, now_iso(), rx["id"])
    audit(conn, user, "dispense", "pharmacy", "prescription", rx["id"], new={"lines": created, "status": new_status})
    publish("pharmacy.dispensed", {
        "prescription_id": rx["id"],
        "invoice_id": invoice["id"],
        "patient_id": rx["patient_id"],
        "status": new_status,
    })
    from .clinical import get_prescription
    return {"prescription": get_prescription(conn, rx["id"]), "invoice_id": invoice["id"], "dispense_ids": created}


def alerts(conn) -> dict:
    today = today_str()
    soon = (now() + timedelta(days=90)).date().isoformat()
    expired = inventory_sql.q_pharmacy_17641(conn, today)
    expiring = inventory_sql.q_pharmacy_17910(conn, today, soon)
    products = [enrich_product(conn, p) for p in inventory_sql.q_pharmacy_18253(conn)]
    low = [p for p in products if p["stock"] <= float(p["reorder_level"] or 0)]
    mismatches = inventory_sql.q_pharmacy_18403(conn)
    return {"low_stock": low, "expiring": expiring, "expired": expired, "mismatches": mismatches}


def reconciliation(conn, batch_id: str) -> dict:
    data = ledger(conn, batch_id=batch_id, limit=500)
    summary = data["summary"] or {}
    by_type = summary.get("by_type") or {}
    purchased = float(by_type.get("OPENING") or 0) + float(by_type.get("PURCHASE") or 0) + float(by_type.get("RETURN") or 0)
    dispensed = abs(float(by_type.get("DISPENSED") or 0))
    damaged = abs(float(by_type.get("DAMAGED") or 0))
    expired = abs(float(by_type.get("EXPIRED") or 0))
    lost = abs(float(by_type.get("LOST") or 0))
    adjusted = float(by_type.get("ADJUSTMENT") or 0)
    return {
        "batch": summary.get("batch"),
        "purchased": purchased,
        "dispensed": dispensed,
        "damaged": damaged,
        "expired": expired,
        "lost": lost,
        "adjusted": adjusted,
        "remaining": summary.get("on_hand"),
        "movements": data["items"],
    }
