"""First-boot hospital workspace. Master data is configuration, not code."""

from __future__ import annotations

import json

from aipf.repo import billing as billing_sql
from aipf.repo import encounters as encounters_sql
from aipf.repo import inventory as inventory_sql
from aipf.repo import ipd as ipd_sql
from aipf.repo import lab as lab_sql
from aipf.repo import masters as masters_sql
from aipf.repo import notifications as notifications_sql
from aipf.repo import operations as operations_sql
from aipf.repo import ot as ot_sql
from aipf.repo import patients as patients_sql
from aipf.repo import payments as payments_sql
from aipf.repo import users as users_sql
from aipf.repo import wards as wards_sql

from .core import PERMISSIONS, ROLE_MATRIX
from .db import BRANDING, one, rows
from .util import hash_password, now_iso, today_str

NOW = None  # set at seed time
IDS = {"dept": {}, "cat": {}}


def ensure_default_grants(conn) -> None:
    """Add permissions introduced after an existing database was seeded.

    A freshly migrated empty database has no roles yet, so this does not
    insert permission rows there. Copying a database into that empty target
    must not collide with rows this function created.
    """
    from .core import PERMISSIONS, ROLE_MATRIX

    roles = {row["code"] for row in users_sql.q_core_16019(conn)}
    if not roles:
        return
    for code, module, description in PERMISSIONS:
        users_sql.q_seed_1017(conn, code, module, description)
    for role, permissions in ROLE_MATRIX.items():
        if role not in roles:
            continue
        for permission in permissions:
            users_sql.q_seed_1977(conn, role, permission)


def seed_if_empty(conn) -> bool:
    if users_sql.q_seed_349(conn):
        return False
    seed(conn)
    return True


def seed(conn) -> None:
    global NOW
    NOW = now_iso()
    day = today_str()
    from .db import begin, commit, rollback

    begin(conn)
    try:
        _permissions(conn)
        _roles(conn)
        _hospital(conn)
        _config(conn)
        _masters(conn)
        _clinical_masters(conn)
        _wards(conn)
        _pharmacy(conn)
        _users(conn)
        _sample_day(conn, day)
        _templates(conn)
        commit(conn)
    except Exception:
        rollback(conn)
        raise


def _permissions(conn):
    for code, module, description in PERMISSIONS:
        users_sql.q_seed_1017(conn, code, module, description)


def _roles(conn):
    labels = {
        "admin": ("Admin doctor", "Director. Full hospital control.", 1),
        "doctor": ("Doctor", "Assigned queue, consultation, prescription, orders.", 2),
        "reception": ("Reception", "Registration, queue, documents, leads.", 3),
        "pharmacist": ("Pharmacist", "Dispensing and stock ledger.", 4),
        "billing": ("Billing", "Invoices, payments, refunds.", 5),
        "nurse": ("Nursing", "Wards, beds, admission support.", 6),
        "lab": ("Laboratory", "Samples and results.", 7),
    }
    for code, (name, description, order) in labels.items():
        users_sql.q_seed_1746(conn, code, name, description, order)
        for perm in ROLE_MATRIX[code]:
            users_sql.q_seed_1977(conn, code, perm)


def _hospital(conn):
    logo = BRANDING / "logo.jpg"
    masters_sql.q_seed_2127(conn, "AIPF Mission Hospital", "All India Prayer Fellowship Mission Hospital", "Multispeciality mission hospital", "Shahpurpur, Fatehpur Beri", "New Delhi", "New Delhi", "Delhi", "110074", "", "", "", "", str(logo) if logo.exists() else None, NOW)


def _config(conn):
    values = {
        "bill_prefix": "AIPF-BILL",
        "timezone": "Asia/Kolkata",
        "whatsapp_delay_minutes": "5",
        "wa_provider": "openwa",
        "wa_enabled": "0",
        "wa_base_url": "",
        "wa_session_id": "",
        "leads_enabled": "0",
        "leads_collection": "leads",
        "allow_negative_stock": "0",
        "allow_expired_dispense": "0",
        "backup_enabled": "1",
        "backup_time": "02:00",
        "backup_retention_days": "30",
        "backup_max_count": "30",
        "cloud_prefix": "aipf",
        "show_install_hints": "1",
    }
    for key, value in values.items():
        secret = key in ("wa_api_key", "leads_mongo_uri", "cloud_access_key", "cloud_secret_key")
        masters_sql.q_seed_3573(conn, key, value, 1 if secret else 0, NOW)


def _add_master(conn, list_type, name, code="", description="", sort=0, meta="{}"):
    import uuid
    item_id = "M" + uuid.uuid4().hex[:10]
    masters_sql.q_seed_3886(conn, item_id, list_type, name, code, description, meta, sort, NOW)
    return item_id


def _masters(conn):
    departments = [
        ("General Medicine", "GM"),
        ("Surgery", "SUR"),
        ("Orthopedics", "ORTH"),
        ("Gynecology", "GYN"),
        ("Pediatrics", "PED"),
        ("Physiotherapy", "PHY"),
        ("Neurology", "NEU"),
        ("Emergency", "EMR"),
        ("ENT", "ENT"),
        ("Ophthalmology", "OPH"),
    ]
    IDS["dept"] = {}
    IDS["cat"] = {}
    for i, (name, code) in enumerate(departments):
        IDS["dept"][code] = _add_master(conn, "department", name, code, sort=i)
    categories = ["General medical", "Surgical", "Orthopedic", "Gynecology", "Pediatric", "Physiotherapy", "Neurological", "Emergency", "Other"]
    for i, name in enumerate(categories):
        IDS["cat"][name] = _add_master(conn, "patient_category", name, sort=i)
    for i, name in enumerate(["Cash", "UPI", "Card", "Bank transfer", "Cheque", "Other"]):
        _add_master(conn, "payment_mode", name, sort=i)
    for i, name in enumerate(["Advance", "IPD deposit", "OT deposit", "Other"]):
        _add_master(conn, "deposit_type", name, sort=i)
    for i, (name, code, bps) in enumerate([
        ("GST 5%", "GST5", 500),
        ("GST 12%", "GST12", 1200),
        ("GST 18%", "GST18", 1800),
        ("Exempt", "EXEMPT", 0),
    ]):
        _add_master(conn, "tax_rate", name, code=code, meta=json.dumps({"bps": bps}), sort=i)
    for i, name in enumerate(["Aadhaar", "PAN", "Address proof", "Insurance document", "Previous medical report", "Lab report", "Prescription", "Discharge summary", "OT notes", "Invoice", "Payment receipt", "Scan / image", "Other"]):
        _add_master(conn, "document_type", name, sort=i)
    for i, name in enumerate(["Fever", "Pain", "Injury", "Antenatal", "Child illness", "Diabetes review", "Hypertension", "Post-operative", "Other"]):
        _add_master(conn, "condition", name, sort=i)
    for i, (name, desc) in enumerate([
        ("Appendicectomy", "Open or laparoscopic"),
        ("Wound debridement", "Minor OT"),
        ("Closed reduction", "Orthopedic"),
        ("Normal delivery support", "Labour room"),
        ("Incision and drainage", "Abscess"),
    ]):
        _add_master(conn, "procedure", name, description=desc, sort=i)
    for i, name in enumerate(["Box", "Strip", "Sachet", "Pouch", "Bottle", "Vial", "Tablet", "Capsule", "Piece", "Pack", "Ampoule", "Tube"]):
        _add_master(conn, "unit", name, sort=i)


def _clinical_masters(conn):
    opd = [
        ("OTY-GEN", "General OPD", "GEN", 20000, 1, "Single-day general consultation.", "Doctor consultation", 1),
        ("OTY-CARD5", "5-day OPD card", "CARD5", 50000, 5, "Return visits within 5 days are not charged the card fee again.", "Consultations during validity", 2),
        ("OTY-SPL", "Specialist OPD", "SPL", 40000, 1, "Gynecology, orthopedics, surgery, pediatrics.", "Specialist consultation", 3),
        ("OTY-EMR", "Emergency OPD", "EMR", 50000, 1, "Emergency desk.", "Emergency consultation", 4),
        ("OTY-PHY", "Physiotherapy session", "PHY", 30000, 1, "One supervised session.", "Physiotherapy", 5),
    ]
    for row in opd:
        masters_sql.q_seed_6840(conn, *row, NOW, NOW)
    services = [
        ("SV-DRESS", "Dressing", "DRS", "HOSPITAL SERVICES", 15000, "procedure"),
        ("SV-INJ", "Injection administration", "INJ", "HOSPITAL SERVICES", 5000, "procedure"),
        ("SV-NEB", "Nebulization", "NEB", "HOSPITAL SERVICES", 12000, "sitting"),
        ("SV-ECG", "ECG", "ECG", "HOSPITAL SERVICES", 25000, "test"),
        ("SV-IV", "IV set and fluids", "IV", "HOSPITAL SERVICES", 18000, "set"),
        ("SV-NUR", "Nursing charge", "NUR", "IPD", 30000, "day"),
        ("SV-SUT", "Minor suturing", "SUT", "PROCEDURE", 40000, "procedure"),
        ("SV-O2", "Oxygen", "O2", "HOSPITAL SERVICES", 20000, "hour"),
    ]
    for i, (sid, name, code, cat, rate, unit) in enumerate(services):
        masters_sql.q_seed_7841(conn, sid, name, code, cat, rate, unit, i, NOW)
    tests = [
        ("LT-CBC", "CBC", "CBC", "Haematology", 25000, "Blood", "None", 6),
        ("LT-FBS", "Blood sugar fasting", "FBS", "Biochemistry", 8000, "Blood", "Overnight fast", 4),
        ("LT-PPBS", "Blood sugar PP", "PPBS", "Biochemistry", 8000, "Blood", "2 hours after food", 4),
        ("LT-LFT", "Liver function test", "LFT", "Biochemistry", 45000, "Blood", "Fasting preferred", 12),
        ("LT-KFT", "Kidney function test", "KFT", "Biochemistry", 45000, "Blood", "None", 12),
        ("LT-URE", "Urine routine", "URE", "Clinical pathology", 10000, "Urine", "Midstream", 6),
        ("LT-WID", "Widal", "WID", "Serology", 15000, "Blood", "None", 8),
        ("LT-MAL", "Malaria antigen", "MAL", "Serology", 25000, "Blood", "None", 2),
        ("LT-DEN", "Dengue NS1", "DEN", "Serology", 60000, "Blood", "None", 6),
        ("LT-CXR", "X-ray chest", "CXR", "Radiology", 35000, "None", "Remove metal", 4),
        ("LT-USG", "USG abdomen", "USG", "Radiology", 70000, "None", "Full bladder if pelvic", 24),
    ]
    for i, row in enumerate(tests):
        lab_sql.q_seed_9134(conn, row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], i, NOW)


def _wards(conn):
    plan = [
        ("W-GEN", "General ward", "GEN", "GENERAL", 0, [("Common", "COMMON", 0, 80000, 8)]),
        ("W-FEM", "Female ward", "FEM", "FEMALE", 0, [("Common", "COMMON", 0, 80000, 6)]),
        ("W-PED", "Pediatric ward", "PED", "PEDIATRIC", 0, [("Common", "COMMON", 0, 90000, 4)]),
        ("W-PVT", "Private non-AC", "PVT", "PRIVATE", 0, [("Room 1", "PRIVATE", 0, 150000, 1), ("Room 2", "PRIVATE", 0, 150000, 1), ("Room 3", "PRIVATE", 0, 150000, 1)]),
        ("W-AC", "AC cabin", "AC", "CABIN", 1, [("Cabin A", "CABIN", 1, 250000, 1), ("Cabin B", "CABIN", 1, 250000, 1)]),
        ("W-EM", "Emergency observation", "EMO", "EMERGENCY", 0, [("Observation", "COMMON", 0, 100000, 4)]),
        ("W-DC", "Day care", "DC", "DAYCARE", 0, [("Day care", "COMMON", 0, 60000, 3)]),
    ]
    for order, (wid, name, code, wtype, ac, rooms) in enumerate(plan):
        wards_sql.q_seed_10329(conn, wid, name, code, wtype, ac, order)
        for rname, rtype, rac, rate, beds in rooms:
            rid = f"R-{wid}-{rname.replace(' ', '')[:8]}"
            wards_sql.q_seed_10631(conn, rid, wid, rname, rtype, rac, rate)
            for n in range(1, beds + 1):
                bid = f"BD-{rid}-{n}"
                wards_sql.q_seed_10927(conn, bid, rid, wid, f"Bed {n}" if beds > 1 else "Bed")


def _pharmacy(conn):
    products = [
        ("PR-PARA", "House stock", "Paracetamol", "Paracetamol", "500 mg", "Tablet", "Tablet", "1 box = 10 strips = 10 tablets", '{"levels":[{"unit":"Box","contains":10,"of":"Strip"},{"unit":"Strip","contains":10,"of":"Tablet"}]}', "AIPFPARA500", 80, 150, 200, 200, "B-PARA-26", "2026-01-01", "2027-12-31", 500),
        ("PR-AMOX", "House stock", "Amoxicillin", "Amoxicillin", "500 mg", "Capsule", "Capsule", "1 strip = 10 capsules", '{"levels":[{"unit":"Strip","contains":10,"of":"Capsule"}]}', "AIPFAMOX500", 400, 800, 40, 80, "B-AMOX-11", "2026-02-01", "2027-06-30", 200),
        ("PR-AZI", "House stock", "Azithromycin", "Azithromycin", "500 mg", "Tablet", "Tablet", "1 strip = 3 tablets", '{"levels":[{"unit":"Strip","contains":3,"of":"Tablet"}]}', "AIPFAZI500", 1200, 2200, 30, 40, "B-AZI-09", "2025-12-01", "2026-11-15", 60),
        ("PR-PAN", "House stock", "Pantoprazole", "Pantoprazole", "40 mg", "Tablet", "Tablet", "1 strip = 10 tablets", "{}", "AIPFPAN40", 150, 400, 50, 80, "B-PAN-04", "2026-03-01", "2028-03-01", 300),
        ("PR-CET", "House stock", "Cetirizine", "Cetirizine", "10 mg", "Tablet", "Tablet", "1 strip = 10 tablets", "{}", "AIPFCET10", 40, 100, 40, 60, "B-CET-OLD", "2025-01-01", "2026-08-01", 30),
        ("PR-ORS", "House stock", "ORS", "Oral rehydration salts", "21.8 g", "Sachet", "Sachet", "1 box = 20 sachets", '{"levels":[{"unit":"Box","contains":20,"of":"Sachet"}]}', "AIPFORS", 500, 1200, 20, 40, "B-ORS-02", "2026-04-01", "2027-04-01", 8),
        ("PR-DIC", "House stock", "Diclofenac gel", "Diclofenac", "1% w/w", "Tube", "Tube", "1 tube", "{}", "AIPFDICGEL", 2500, 4500, 10, 15, "B-DIC-3", "2026-01-15", "2027-08-01", 24),
        ("PR-MET", "House stock", "Metformin", "Metformin", "500 mg", "Tablet", "Tablet", "1 strip = 10 tablets", "{}", "AIPFMET500", 60, 150, 100, 150, "B-MET-7", "2026-05-01", "2028-01-01", 400),
        ("PR-AML", "House stock", "Amlodipine", "Amlodipine", "5 mg", "Tablet", "Tablet", "1 strip = 10 tablets", "{}", "AIPFAML5", 50, 120, 80, 100, "B-AML-2", "2026-02-01", "2028-02-01", 250),
        ("PR-NS", "House stock", "Normal saline", "Sodium chloride 0.9%", "500 ml", "Bottle", "Bottle", "1 bottle", "{}", "AIPFNS500", 1800, 3500, 20, 30, "B-NS-19", "2026-06-01", "2027-12-01", 40),
        ("PR-INJ", "House stock", "Diclofenac injection", "Diclofenac", "75 mg/ml", "Ampoule", "Ampoule", "1 box = 10 ampoules", "{}", "AIPFDICINJ", 600, 1400, 20, 30, "B-INJ-5", "2026-01-01", "2027-01-01", 50),
        ("PR-BET", "House stock", "Povidone iodine", "Povidone iodine", "5%", "Bottle", "Bottle", "100 ml bottle", "{}", "AIPFBET", 3000, 5500, 8, 12, "B-BET-1", "2026-03-01", "2028-03-01", 18),
    ]
    for row in products:
        (pid, brand, name, composition, strength, form, unit, packaging, packaging_json, barcode, purchase, sale, min_stock, reorder, batch, mfg, exp, qty) = row
        inventory_sql.q_seed_14060(conn, pid, brand, name, composition, strength, form, "To be confirmed on purchase", unit, packaging, packaging_json, barcode, purchase, sale, sale, min_stock, reorder, NOW, NOW)
        bid = "BAT-" + pid
        inventory_sql.q_seed_14706(conn, bid, pid, batch, mfg, exp, purchase, sale, qty, unit, barcode, NOW)
        inventory_sql.q_seed_15042(conn, pid, bid, qty, unit, bid, NOW)
    # A second, in-date cetirizine batch so the expired one is not the only stock.
    inventory_sql.q_seed_15409(conn, NOW)
    inventory_sql.q_seed_15737(conn, NOW)
    from .pharmacy import seed_registered_barcodes
    seed_registered_barcodes(conn)


def _install_password() -> str:
    import os

    value = os.environ.get("AIPF_SEED_PASSWORD", "").strip()
    if len(value) < 12:
        raise RuntimeError(
            "Set AIPF_SEED_PASSWORD in the environment before seeding. "
            "It is not stored in the repository."
        )
    return value


def _user(conn, uid, username, full_name, title, specialty, dept, role, admin_doctor=0):
    users_sql.q_seed_16116(conn, uid, username, full_name, hash_password(_install_password()), title, specialty, dept, admin_doctor, NOW)
    users_sql.q_seed_16427(conn, uid, role)
    if admin_doctor:
        users_sql.q_seed_16536(conn, uid)


def _users(conn):
    d = IDS["dept"]
    _user(conn, "U-DIRECTOR", "director", "Samuel Thomas", "Dr", "General Medicine", d["GM"], "admin", 1)
    _user(conn, "U-RECEPTION", "reception", "Lata Minj", "", "Front desk", d["GM"], "reception")
    _user(conn, "U-ANITA", "dr.anita", "Anita Rao", "Dr", "Gynecology", d["GYN"], "doctor")
    _user(conn, "U-IMRAN", "dr.imran", "Imran Qureshi", "Dr", "Orthopedics", d["ORTH"], "doctor")
    _user(conn, "U-PRIYA", "dr.priya", "Priya Nair", "Dr", "Pediatrics", d["PED"], "doctor")
    _user(conn, "U-JOSEPH", "dr.joseph", "Joseph Mathew", "Dr", "Surgery", d["SUR"], "doctor")
    _user(conn, "U-PHARM", "pharmacy", "Ramesh Yadav", "", "Pharmacy", None, "pharmacist")
    _user(conn, "U-BILL", "billing", "Sunita Paul", "", "Accounts", None, "billing")
    _user(conn, "U-NURSE", "nurse", "Anjali Kerketta", "", "Ward", d["GM"], "nurse")
    _user(conn, "U-LAB", "lab", "Deepak Oraon", "", "Laboratory", None, "lab")


def _patient(conn, pid, name, phone, gender, age, guardian, category, dept, address, allergies="", dob=None):
    search = " ".join(x.lower() for x in [pid, name, phone, guardian, address] if x)
    patients_sql.q_seed_17935(conn, pid, pid, name, guardian, phone, gender, age, address, category, dept, allergies, search, NOW, NOW, dob)


def _sample_day(conn, day):
    d = IDS["dept"]
    c = IDS["cat"]
    _patient(conn, "P-000001", "Rajesh Sharma", "9811122334", "Male", 48, "Ram Prasad Sharma", c["General medical"], d["GM"], "Fatehpur Beri, New Delhi", "None known")
    _patient(conn, "P-000002", "Aarav Sharma", "9811122334", "Male", 7, "Rajesh Sharma", c["Pediatric"], d["PED"], "Fatehpur Beri, New Delhi", "")
    _patient(conn, "P-000003", "Neha Sharma", "9811122334", "Female", 42, "Ram Prasad Sharma", c["Gynecology"], d["GYN"], "Fatehpur Beri, New Delhi", "Sulfa drugs")
    _patient(conn, "P-000004", "Fatima Begum", "9899001122", "Female", 34, "Yusuf Begum", c["Gynecology"], d["GYN"], "Shahpurpur, New Delhi", "")
    _patient(conn, "P-000005", "Harpreet Singh", "9810099887", "Male", 62, "Gurmeet Singh", c["Orthopedic"], d["ORTH"], "Chhatarpur, New Delhi", "Ibuprofen — rash")
    _patient(conn, "P-000006", "Meera Devi", "9876543210", "Female", 29, "Sohan Lal", c["General medical"], d["GM"], "Fatehpur Beri, New Delhi", "")
    _patient(conn, "P-000007", "Joseph Kujur", "9810011223", "Male", 55, "Marcus Kujur", c["General medical"], d["GM"], "Asola, New Delhi", "")
    _patient(conn, "P-000008", "Kamla Devi", "9812340008", "Female", 70, "Ramesh Devi", c["Emergency"], d["EMR"], "Bhatti Mines, New Delhi", "Penicillin")

    def encounter(eid, patient, opd, fee, doctor, dept, complaint, status="OPEN"):
        encounters_sql.q_seed_19829(conn, eid, patient, opd, fee, NOW[:10] + "T23:59:00+05:30", doctor, dept, status, complaint, NOW, "U-RECEPTION", NOW)

    encounter("OPD-2026-000001", "P-000001", "OTY-GEN", 20000, "U-DIRECTOR", d["GM"], "Fever and body ache for 2 days")
    encounter("OPD-2026-000002", "P-000002", "OTY-SPL", 40000, "U-PRIYA", d["PED"], "Cough, on same family phone")
    encounter("OPD-2026-000003", "P-000004", "OTY-SPL", 40000, "U-ANITA", d["GYN"], "Antenatal visit")
    encounter("OPD-2026-000004", "P-000006", "OTY-CARD5", 50000, "U-DIRECTOR", d["GM"], "Acidity and headache")
    encounter("OPD-2026-000005", "P-000007", "OTY-GEN", 20000, "U-DIRECTOR", d["GM"], "Blood pressure review")
    encounter("OPD-2026-000006", "P-000008", "OTY-EMR", 50000, "U-JOSEPH", d["EMR"], "Giddiness since morning")
    encounter("OPD-2026-000007", "P-000005", "OTY-SPL", 40000, "U-IMRAN", d["ORTH"], "Fall, left wrist swelling", status="COMPLETED")

    def queue(qid, token, enc, patient, doctor, dept, status):
        called = NOW if status in ("CALLED", "IN_CONSULTATION") else None
        started = NOW if status == "IN_CONSULTATION" else None
        encounters_sql.q_seed_21260(conn, qid, token, enc, patient, doctor, dept, status, NOW, called, started, NOW)

    queue("Q-1", 1, "OPD-2026-000001", "P-000001", "U-DIRECTOR", d["GM"], "WAITING")
    queue("Q-2", 2, "OPD-2026-000002", "P-000002", "U-PRIYA", d["PED"], "WAITING")
    queue("Q-3", 3, "OPD-2026-000003", "P-000004", "U-ANITA", d["GYN"], "IN_CONSULTATION")
    queue("Q-4", 4, "OPD-2026-000004", "P-000006", "U-DIRECTOR", d["GM"], "WAITING_FOR_PHARMACY")
    queue("Q-5", 5, "OPD-2026-000006", "P-000008", "U-JOSEPH", d["EMR"], "WAITING")

    encounters_sql.q_seed_22044(conn, NOW, NOW)
    encounters_sql.q_seed_22488(conn, NOW, NOW, NOW)
    encounters_sql.q_seed_22772(conn)
    encounters_sql.q_seed_23156(conn)

    # Draft bills for open visits, one finalized partial bill.
    bills = [
        ("INV-S1", "AIPF-BILL-2026-000001", "P-000001", "OPD-2026-000001", None, "OPD", "DRAFT", 20000, "II-1", "General OPD", "CONSULTATION", "opd"),
        ("INV-S2", "AIPF-BILL-2026-000002", "P-000002", "OPD-2026-000002", None, "OPD", "DRAFT", 40000, "II-2", "Specialist OPD", "CONSULTATION", "opd"),
        ("INV-S3", "AIPF-BILL-2026-000003", "P-000004", "OPD-2026-000003", None, "OPD", "DRAFT", 40000, "II-3", "Specialist OPD", "CONSULTATION", "opd"),
        ("INV-S4", "AIPF-BILL-2026-000004", "P-000006", "OPD-2026-000004", None, "OPD", "DRAFT", 50000, "II-4", "5-day OPD card", "CONSULTATION", "opd"),
        ("INV-S6", "AIPF-BILL-2026-000006", "P-000008", "OPD-2026-000006", None, "OPD", "DRAFT", 50000, "II-6", "Emergency OPD", "CONSULTATION", "opd"),
    ]
    for iid, number, patient, enc, adm, btype, status, amount, line, desc, cat, source in bills:
        billing_sql.q_seed_24489(conn, iid, number, patient, enc, adm, btype, status, amount, amount, amount, NOW, NOW)
        billing_sql.q_seed_24947(conn, line, iid, source, enc, desc, cat, amount, amount, NOW)

    # Joseph's finalized bill with partial cash payment.
    billing_sql.q_seed_25345(conn, NOW, NOW, NOW)
    billing_sql.q_seed_25817(conn, NOW)
    masters_sql.q_seed_26126(conn, NOW)
    payments_sql.q_seed_26451(conn, NOW)

    # Harpreet admitted on general ward bed 1. The admission row must exist before the bed points at it.
    ipd_sql.q_seed_26796(conn, d["ORTH"], NOW, NOW, NOW)
    wards_sql.q_seed_27321(conn)
    ipd_sql.q_seed_27446(conn, NOW)
    billing_sql.q_seed_27680(conn, NOW, NOW)
    billing_sql.q_seed_28089(conn, NOW)
    billing_sql.q_seed_28401(conn, NOW)
    ipd_sql.q_seed_28727(conn, day, NOW)
    ot_sql.q_seed_29119(conn, NOW, NOW)
    operations_sql.q_seed_29469(conn, NOW, NOW)
    notifications_sql.q_seed_29768(conn, NOW, NOW)

    # Sequences so the next live record does not collide with the opening day.
    sequences = [
        ("patient", 0, 9),
        ("opd", 2026, 8),
        ("invoice", 2026, 8),
        ("rx", 2026, 2),
        ("admission", 2026, 2),
        ("ot", 2026, 2),
        ("lab", 2026, 1),
    ]
    for name, year, nxt in sequences:
        masters_sql.q_seed_30437(conn, name, year, nxt)


def _templates(conn):
    notifications_sql.q_seed_30561(conn, NOW)
