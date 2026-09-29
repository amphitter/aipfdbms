"""Acceptance checks for the hospital rules that must not be wrong."""

import os
import secrets
import shutil
import sys
import tempfile
import threading
from pathlib import Path

os.environ.setdefault("AIPF_SEED_PASSWORD", secrets.token_urlsafe(18))

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aipf import billing, clinical, core, pharmacy, wards
from aipf.db import apply_migrations, connect  # connect(path) opens an isolated test database
from aipf.seed import seed
from aipf.util import amount_in_words


def setup():
    folder = Path(tempfile.mkdtemp(prefix="aipf-test-"))
    db = folder / "hospital.db"
    conn = connect(db)
    apply_migrations(conn)
    seed(conn)
    user = core.session_user  # noqa: keep import used
    director = core.user_by_username(conn, "director")
    actor = core.load_user(conn, director["id"])
    actor["workstation"] = "test"
    actor["ip"] = "127.0.0.1"
    return conn, actor, folder


def test_words():
    assert amount_in_words(10998700) == "Rupees One Lakh Nine Thousand Nine Hundred Eighty-Seven Only"
    assert amount_in_words(0) == "Rupees Zero Only"


def test_phone_does_not_overwrite():
    conn, actor, folder = setup()
    matches = clinical.matches_by_phone(conn, "9811122334")
    names = {p["name"] for p in matches}
    assert {"Rajesh Sharma", "Aarav Sharma", "Neha Sharma"} <= names
    created = clinical.save_patient(conn, actor, {
        "name": "New Sharma Child",
        "primary_phone": "9811122334",
        "gender": "Female",
        "age_at_registration": 2,
        "confirm_new": True,
    })
    assert created["id"] != "P-000001"
    still = clinical.get_patient(conn, "P-000001")
    assert still["name"] == "Rajesh Sharma"
    shutil.rmtree(folder)


def test_opd_validity_and_queue():
    conn, actor, folder = setup()
    first = clinical.create_encounter(conn, actor, {
        "patient_id": "P-000003",
        "opd_type_id": "OTY-CARD5",
        "doctor_id": "U-ANITA",
        "chief_complaint": "Review",
        "queue": True,
    })
    assert first["fee_paise"] == 50000
    cards = clinical.valid_opd_cards(conn, "P-000003")
    assert cards
    second = clinical.create_encounter(conn, actor, {
        "patient_id": "P-000003",
        "opd_type_id": "OTY-CARD5",
        "doctor_id": "U-ANITA",
        "use_opd_id": first["id"],
        "chief_complaint": "Return within card",
    })
    assert second["fee_paise"] == 0
    assert second["parent_opd_id"] == first["id"]
    assert second["id"] != first["id"]
    queue = clinical.list_queue(conn, actor, doctor_id="U-ANITA")
    assert any(item["encounter_id"] == second["id"] for item in queue["items"])
    shutil.rmtree(folder)


def test_dispense_stock_and_bill_rates():
    conn, actor, folder = setup()
    before = pharmacy.get_product(conn, "PR-PARA")
    batch = next(b for b in before["batches"] if b["id"] == "BAT-PR-PARA")
    opening = batch["qty_on_hand"]
    result = pharmacy.dispense(conn, actor, {
        "prescription_id": "RX-2026-000001",
        "lines": [
            {"item_id": "RI-1", "product_id": "PR-PARA", "batch_id": "BAT-PR-PARA", "qty": 10},
            {"item_id": "RI-2", "product_id": "PR-PAN", "batch_id": "BAT-PR-PAN", "qty": 5},
        ],
    })
    after = pharmacy.get_product(conn, "PR-PARA")
    batch = next(b for b in after["batches"] if b["id"] == "BAT-PR-PARA")
    assert batch["qty_on_hand"] == opening - 10
    recon = pharmacy.reconciliation(conn, "BAT-PR-PARA")
    assert recon["dispensed"] == 10
    assert abs(recon["remaining"] - (recon["purchased"] - recon["dispensed"])) < 0.01
    invoice = billing.get_invoice(conn, result["invoice_id"])
    pharmacy_lines = [i for i in invoice["items"] if i["category"] == "PHARMACY"]
    assert pharmacy_lines
    assert pharmacy_lines[0]["rate_paise"] == 150
    # Changing the master rate must not rewrite the billed line.
    conn.execute("UPDATE products SET sale_rate_paise=99999 WHERE id='PR-PARA'")
    again = billing.get_invoice(conn, result["invoice_id"])
    assert [i for i in again["items"] if i["category"] == "PHARMACY"][0]["rate_paise"] == 150
    from aipf.util import ApiError
    try:
        pharmacy.dispense(conn, actor, {
            "prescription_id": "RX-2026-000001",
            "lines": [{"item_id": "RI-1", "product_id": "PR-PARA", "batch_id": "BAT-PR-PARA", "qty": 1}],
        })
        raise AssertionError("second full dispense should fail")
    except ApiError as exc:
        assert exc.status == 400
    shutil.rmtree(folder)


def test_negative_stock_and_concurrency():
    conn, actor, folder = setup()
    conn.execute("UPDATE batches SET qty_on_hand=1 WHERE id='BAT-PR-ORS'")
    conn.execute("DELETE FROM stock_movements WHERE batch_id='BAT-PR-ORS'")
    conn.execute(
        """INSERT INTO stock_movements(product_id, batch_id, qty, unit, movement_type, reason, at)
           VALUES ('PR-ORS','BAT-PR-ORS',1,'Sachet','OPENING','test', datetime('now'))"""
    )
    errors = []

    def worker():
        local = connect(folder / "hospital.db")
        try:
            pharmacy.move(local, actor, "BAT-PR-ORS", 1, "DISPENSED", "test", "x", "race")
        except Exception as exc:
            errors.append(str(exc))
        finally:
            local.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    left = connect(folder / "hospital.db")
    qty = left.execute("SELECT qty_on_hand FROM batches WHERE id='BAT-PR-ORS'").fetchone()["qty_on_hand"]
    left.close()
    assert qty == 0
    assert len(errors) == 1
    shutil.rmtree(folder)


def test_bill_payments_reprint_and_adjustment():
    conn, actor, folder = setup()
    invoice = billing.get_invoice(conn, "INV-S5")
    number = invoice["number"]
    billing.record_payment(conn, actor, invoice["id"], "UPI", 25000, reference="UPI123")
    paid = billing.get_invoice(conn, invoice["id"])
    assert paid["payment_status"] == "PAID"
    assert paid["due_paise"] == 0
    assert paid["number"] == number
    pdf = billing.invoice_pdf(conn, invoice["id"])
    pdf2 = billing.invoice_pdf(conn, invoice["id"])
    assert pdf.startswith(b"%PDF")
    assert pdf2.startswith(b"%PDF")
    assert billing.get_invoice(conn, invoice["id"])["number"] == number
    # Adjustment keeps the number and records a revision.
    billing.adjust(conn, actor, invoice["id"], -5000, "Courtesy reduction", "Director approved")
    adjusted = billing.get_invoice(conn, invoice["id"])
    assert adjusted["number"] == number
    assert adjusted["revision"] >= 1
    assert any(i["category"] == "ADJUSTMENT" for i in adjusted["items"])
    shutil.rmtree(folder)


def test_bed_conflict_and_ot_outcome():
    conn, actor, folder = setup()
    try:
        wards.admit(conn, actor, {"patient_id": "P-000008", "bed_id": "BD-R-W-GEN-Common-1", "doctor_id": "U-IMRAN"})
        raise AssertionError("occupied bed should be refused")
    except Exception as exc:
        assert "not available" in str(exc).lower()
    case = wards.update_ot(conn, actor, "OT-2026-000001", {"status": "PERFORMED"})
    assert case["status"] == "NOTES_PENDING"
    done = wards.ot_notes(conn, actor, "OT-2026-000001", {
        "outcome": "UNSUCCESSFUL",
        "procedure_notes": "Attempted reduction. Swelling too tense. Plan review tomorrow.",
        "findings": "Displaced distal radius.",
    })
    assert done["outcome"] == "UNSUCCESSFUL"
    assert done["status"] == "COMPLETED"
    assert done["procedure_notes"]
    shutil.rmtree(folder)


def test_doctor_cannot_open_another_queue():
    conn, _actor, folder = setup()
    anita = core.load_user(conn, core.user_by_username(conn, "dr.anita")["id"])
    anita["workstation"] = "test"
    anita["ip"] = "127.0.0.1"
    try:
        clinical.list_queue(conn, anita, doctor_id="U-IMRAN")
        raise AssertionError("doctor queue bypass")
    except Exception as exc:
        assert getattr(exc, "status", None) == 403
    own = clinical.list_queue(conn, anita)
    assert all(item["doctor_id"] == "U-ANITA" for item in own["items"])
    denied = conn.execute(
        "SELECT action FROM audit_logs WHERE action='queue_denied' AND entity_id='U-IMRAN'"
    ).fetchone()
    assert denied
    shutil.rmtree(folder)


def test_install_passwords_are_not_public():
    import os
    from aipf.server import _public_accounts

    os.environ.pop("AIPF_DEV_HINTS", None)
    assert _public_accounts() == []


def test_permission():
    conn, actor, folder = setup()
    reception = core.load_user(conn, core.user_by_username(conn, "reception")["id"])
    try:
        core.permit(reception, "backup.restore")
        raise AssertionError("reception must not restore")
    except Exception as exc:
        assert getattr(exc, "status", None) == 403
    shutil.rmtree(folder)


if __name__ == "__main__":
    test_words()
    test_phone_does_not_overwrite()
    test_opd_validity_and_queue()
    test_dispense_stock_and_bill_rates()
    test_negative_stock_and_concurrency()
    test_bill_payments_reprint_and_adjustment()
    test_bed_conflict_and_ot_outcome()
    test_doctor_cannot_open_another_queue()
    test_install_passwords_are_not_public()
    test_permission()
    print("all hospital flow checks passed")
