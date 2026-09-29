"""SQL owned by the repository. Domain modules call these functions."""
from __future__ import annotations

from aipf.repo.sqlio import exec_if, execute, one, rows

def match_name_dob(conn, name: str, dob: str):
    return rows(conn, "SELECT * FROM patients WHERE lower(name)=? AND dob=?", (name, dob))


def q_clinical_1456(conn, p0, p1, p2):
    return rows(conn, """SELECT * FROM patients WHERE status!='INACTIVE' AND (
             primary_phone=? OR alternate_phone=? OR guardian_phone=?
           ) ORDER BY name LIMIT 20""", (p0, p1, p2))

def q_clinical_1857(conn, p0):
    return rows(conn, "SELECT * FROM patients ORDER BY created_at DESC LIMIT ?", (p0,))

def q_clinical_2022(conn, p0, p1, p2, p3, p4):
    return rows(conn, """SELECT * FROM patients
               WHERE search_text LIKE ? OR id LIKE ? OR hospital_no LIKE ? OR primary_phone LIKE ?
               ORDER BY created_at DESC LIMIT ?""", (p0, p1, p2, p3, p4))


_LINKED = """p.id IN (
  SELECT patient_id FROM encounters WHERE doctor_id=?
  UNION SELECT patient_id FROM queue_entries WHERE doctor_id=?
  UNION SELECT patient_id FROM admissions WHERE doctor_id=?
  UNION SELECT patient_id FROM ot_cases WHERE surgeon_id=?
  UNION SELECT patient_id FROM prescriptions WHERE doctor_id=?
)"""

CARE_LABELS = {
    "INACTIVE": "Inactive",
    "EMERGENCY": "Emergency",
    "ADMITTED": "Admitted",
    "IN_CONSULTATION": "In Consultation",
    "WAITING": "Waiting",
    "OPD": "Active OPD",
    "DISCHARGED": "Discharged",
    "ACTIVE": "Active",
}

CARE_SQL = """CASE
  WHEN p.status='INACTIVE' THEN 'INACTIVE'
  WHEN EXISTS (
    SELECT 1 FROM admissions a
    WHERE a.patient_id=p.id AND a.status NOT IN ('DISCHARGED','CANCELLED')
      AND (a.admission_type='EMERGENCY' OR a.department_id IN (
        SELECT id FROM master_items WHERE list_type='department' AND lower(name)='emergency'
      ))
  ) THEN 'EMERGENCY'
  WHEN EXISTS (
    SELECT 1 FROM admissions a
    WHERE a.patient_id=p.id AND a.status NOT IN ('DISCHARGED','CANCELLED')
  ) THEN 'ADMITTED'
  WHEN EXISTS (
    SELECT 1 FROM queue_entries q
    WHERE q.patient_id=p.id AND q.status='IN_CONSULTATION'
  ) THEN 'IN_CONSULTATION'
  WHEN EXISTS (
    SELECT 1 FROM queue_entries q
    WHERE q.patient_id=p.id AND q.status NOT IN ('COMPLETED','CANCELLED')
  ) THEN 'WAITING'
  WHEN EXISTS (
    SELECT 1 FROM encounters e
    WHERE e.patient_id=p.id AND e.status='OPEN'
  ) THEN 'OPD'
  WHEN (
    SELECT a.status FROM admissions a
    WHERE a.patient_id=p.id
    ORDER BY COALESCE(a.discharged_at, a.admitted_at, a.created_at) DESC
    LIMIT 1
  )='DISCHARGED' THEN 'DISCHARGED'
  ELSE 'ACTIVE'
END"""

_AGE = """(CASE
  WHEN p.dob IS NOT NULL AND length(p.dob)>=4
  THEN (CAST(substr(?,1,4) AS INTEGER) - CAST(substr(p.dob,1,4) AS INTEGER))
  ELSE p.age_at_registration
END)"""

_SORTS = {
    "registered": "p.created_at",
    "name": "lower(p.name)",
    "id": "p.id",
    "encounter": "last_encounter_at",
}


def registry_where(q: str, phone: str, department_id: str, gender: str, age: str, registered: str, patient_status: str, care: str, scope_user_id: str | None, year: str, patient_id: str = ""):
    clauses = ["1=1"]
    params: list = []
    if scope_user_id:
        clauses.append(_LINKED)
        params.extend([scope_user_id, scope_user_id, scope_user_id, scope_user_id, scope_user_id])
    if patient_id:
        clauses.append("p.id=?")
        params.append(patient_id)
    if q:
        like = f"%{q.lower()}%"
        upper = f"%{q.upper()}%"
        needle = f"%{phone or q}%"
        clauses.append("""(
          lower(COALESCE(p.search_text, p.name, '')) LIKE ?
          OR p.id LIKE ?
          OR COALESCE(p.hospital_no,'') LIKE ?
          OR COALESCE(p.primary_phone,'') LIKE ?
          OR COALESCE(p.alternate_phone,'') LIKE ?
          OR COALESCE(p.guardian_phone,'') LIKE ?
          OR lower(COALESCE(p.guardian_name,'')) LIKE ?
          OR p.id IN (SELECT patient_id FROM encounters WHERE id LIKE ?)
        )""")
        params.extend([like, upper, upper, needle, needle, needle, like, upper])
    if department_id:
        clauses.append("""(
          p.department_id=?
          OR (SELECT e.department_id FROM encounters e WHERE e.patient_id=p.id ORDER BY e.arrived_at DESC, e.id DESC LIMIT 1)=?
        )""")
        params.extend([department_id, department_id])
    if gender:
        clauses.append("lower(COALESCE(p.gender,''))=lower(?)")
        params.append(gender)
    if registered:
        clauses.append("substr(p.created_at,1,10)=?")
        params.append(registered)
    if age in ("0-17", "18-39", "40-59", "60+", "unknown"):
        if age == "0-17":
            clauses.append(f"{_AGE} BETWEEN 0 AND 17")
        elif age == "18-39":
            clauses.append(f"{_AGE} BETWEEN 18 AND 39")
        elif age == "40-59":
            clauses.append(f"{_AGE} BETWEEN 40 AND 59")
        elif age == "60+":
            clauses.append(f"{_AGE} >= 60")
        else:
            clauses.append(f"{_AGE} IS NULL")
        params.append(year)
    if patient_status in ("ACTIVE", "INACTIVE"):
        clauses.append("p.status=?")
        params.append(patient_status)
    if care:
        clauses.append(f"({CARE_SQL})=?" )
        params.append(care)
    return " AND ".join(clauses), tuple(params)


def registry_count(conn, where: str, params):
    return one(conn, f"SELECT COUNT(*) AS n FROM patients p WHERE {where}", params)


def registry_page(conn, where: str, params, sort: str, direction: str, limit: int, offset: int):
    column = _SORTS.get(sort, "p.created_at")
    way = "ASC" if direction == "asc" else "DESC"
    if column == "last_encounter_at":
        order = f"CASE WHEN last_encounter_at IS NULL THEN 1 ELSE 0 END, last_encounter_at {way}, p.id"
    else:
        order = f"{column} {way}, p.id"
    return rows(
        conn,
        f"""SELECT p.*,
                   (SELECT e.id FROM encounters e WHERE e.patient_id=p.id ORDER BY e.arrived_at DESC, e.id DESC LIMIT 1) AS last_encounter_id,
                   (SELECT e.arrived_at FROM encounters e WHERE e.patient_id=p.id ORDER BY e.arrived_at DESC, e.id DESC LIMIT 1) AS last_encounter_at,
                   (SELECT e.status FROM encounters e WHERE e.patient_id=p.id ORDER BY e.arrived_at DESC, e.id DESC LIMIT 1) AS last_encounter_status,
                   (SELECT TRIM(COALESCE(u.title,'') || ' ' || COALESCE(u.full_name,''))
                      FROM encounters e LEFT JOIN users u ON u.id=e.doctor_id
                      WHERE e.patient_id=p.id ORDER BY e.arrived_at DESC, e.id DESC LIMIT 1) AS last_doctor_name,
                   (SELECT q.status FROM queue_entries q
                      WHERE q.patient_id=p.id AND q.status NOT IN ('COMPLETED','CANCELLED')
                      ORDER BY q.arrived_at DESC LIMIT 1) AS queue_status,
                   (SELECT a.status FROM admissions a
                      WHERE a.patient_id=p.id AND a.status NOT IN ('DISCHARGED','CANCELLED')
                      ORDER BY COALESCE(a.admitted_at, a.created_at) DESC LIMIT 1) AS admission_status,
                   (SELECT a.admission_type FROM admissions a
                      WHERE a.patient_id=p.id AND a.status NOT IN ('DISCHARGED','CANCELLED')
                      ORDER BY COALESCE(a.admitted_at, a.created_at) DESC LIMIT 1) AS admission_type,
                   (SELECT a.bed_id FROM admissions a
                      WHERE a.patient_id=p.id AND a.status NOT IN ('DISCHARGED','CANCELLED')
                      ORDER BY COALESCE(a.admitted_at, a.created_at) DESC LIMIT 1) AS bed_id,
                   (SELECT b.name FROM admissions a LEFT JOIN beds b ON b.id=a.bed_id
                      WHERE a.patient_id=p.id AND a.status NOT IN ('DISCHARGED','CANCELLED')
                      ORDER BY COALESCE(a.admitted_at, a.created_at) DESC LIMIT 1) AS bed_name,
                   (SELECT d.name FROM master_items d WHERE d.id=p.department_id) AS department_name,
                   ({CARE_SQL}) AS care_code
            FROM patients p
            WHERE {where}
            ORDER BY {order}
            LIMIT ? OFFSET ?""",
        (*params, limit, offset),
    )


def registry_summary(conn, day: str, scope_user_id: str | None):
    scope = ""
    scope_params: tuple = ()
    if scope_user_id:
        scope = f" AND {_LINKED}"
        scope_params = (scope_user_id, scope_user_id, scope_user_id, scope_user_id, scope_user_id)
    active = one(conn, f"SELECT COUNT(*) AS n FROM patients p WHERE p.status='ACTIVE'{scope}", scope_params)
    registered = one(conn, f"SELECT COUNT(*) AS n FROM patients p WHERE substr(p.created_at,1,10)=?{scope}", (day, *scope_params))
    enc_scope = ""
    enc_params: tuple = (day,)
    if scope_user_id:
        enc_scope = f" AND e.patient_id IN (SELECT p.id FROM patients p WHERE {_LINKED})"
        enc_params = (day, *scope_params)
    opd = one(conn, f"SELECT COUNT(*) AS n FROM encounters e WHERE substr(e.arrived_at,1,10)=?{enc_scope}", enc_params)
    wait_scope = ""
    wait_params: tuple = ()
    if scope_user_id:
        wait_scope = f" AND q.patient_id IN (SELECT p.id FROM patients p WHERE {_LINKED})"
        wait_params = scope_params
    waiting = one(conn, f"SELECT COUNT(*) AS n FROM queue_entries q WHERE q.status='WAITING'{wait_scope}", wait_params)
    adm_scope = ""
    adm_params: tuple = ()
    if scope_user_id:
        adm_scope = f" AND a.patient_id IN (SELECT p.id FROM patients p WHERE {_LINKED})"
        adm_params = scope_params
    inpatient = one(
        conn,
        f"""SELECT COUNT(*) AS n FROM admissions a
            WHERE a.status NOT IN ('DISCHARGED','CANCELLED')
              AND COALESCE(a.admission_type,'')!='EMERGENCY'
              AND a.department_id NOT IN (SELECT id FROM master_items WHERE list_type='department' AND lower(name)='emergency')
              {adm_scope}""",
        adm_params,
    )
    emergency = one(
        conn,
        f"""SELECT COUNT(*) AS n FROM admissions a
            WHERE a.status NOT IN ('DISCHARGED','CANCELLED')
              AND (a.admission_type='EMERGENCY' OR a.department_id IN (
                SELECT id FROM master_items WHERE list_type='department' AND lower(name)='emergency'
              ))
              {adm_scope}""",
        adm_params,
    )
    return {
        "active": int((active or {}).get("n") or 0),
        "registered_today": int((registered or {}).get("n") or 0),
        "opd_today": int((opd or {}).get("n") or 0),
        "waiting": int((waiting or {}).get("n") or 0),
        "inpatients": int((inpatient or {}).get("n") or 0),
        "emergency": int((emergency or {}).get("n") or 0),
    }


def set_patient_status(conn, patient_id: str, status: str, updated_at: str):
    return execute(conn, "UPDATE patients SET status=?, updated_at=? WHERE id=?", (status, updated_at, patient_id))


def today_registry(conn, day: str, limit: int, scope_user_id: str | None = None):
    scope = ""
    params: list = [day, day]
    if scope_user_id:
        scope = f" AND {_LINKED}"
        params.extend([scope_user_id, scope_user_id, scope_user_id, scope_user_id, scope_user_id])
    params.append(limit)
    return rows(
        conn,
        f"""SELECT p.id, p.name, p.gender, p.primary_phone, p.created_at,
                   e.id AS encounter_id, e.status AS encounter_status, e.arrived_at,
                   ({CARE_SQL}) AS care_code
            FROM patients p
            LEFT JOIN encounters e ON e.id = (
              SELECT id FROM encounters WHERE patient_id=p.id AND substr(arrived_at,1,10)=?
              ORDER BY arrived_at DESC, id DESC LIMIT 1
            )
            WHERE (substr(p.created_at,1,10)=? OR e.id IS NOT NULL){scope}
            ORDER BY COALESCE(e.arrived_at, p.created_at) DESC, p.id
            LIMIT ?""",
        tuple(params),
    )

def q_clinical_2465(conn, p0, p1):
    return one(conn, "SELECT * FROM patients WHERE id=? OR hospital_no=?", (p0, p1))

def q_clinical_5090(conn, params):
    return execute(conn, """INSERT INTO patients(id, hospital_no, name, guardian_name, guardian_phone, primary_phone, alternate_phone,
               gender, dob, age_at_registration, age_unit, age_is_estimated, address, email, category_id, department_id,
               emergency_name, emergency_phone, notes, allergies, is_sample, status, search_text, created_by, created_at, updated_at)
               VALUES (:id,:hospital_no,:name,:guardian_name,:guardian_phone,:primary_phone,:alternate_phone,:gender,:dob,
               :age_at_registration,:age_unit,:age_is_estimated,:address,:email,:category_id,:department_id,:emergency_name,
               :emergency_phone,:notes,:allergies,:is_sample,:status,:search_text,:created_by,:created_at,:updated_at)""", params)

def q_clinical_7531(conn, params):
    return execute(conn, """UPDATE patients SET hospital_no=:hospital_no, name=:name, guardian_name=:guardian_name, guardian_phone=:guardian_phone,
           primary_phone=:primary_phone, alternate_phone=:alternate_phone, gender=:gender, dob=:dob,
           age_at_registration=:age_at_registration, age_unit=:age_unit, age_is_estimated=:age_is_estimated,
           address=:address, email=:email, category_id=:category_id, department_id=:department_id,
           emergency_name=:emergency_name, emergency_phone=:emergency_phone, notes=:notes, allergies=:allergies,
           status=:status, search_text=:search_text, updated_at=:updated_at WHERE id=:id""", params)

def q_clinical_15659(conn, p0):
    return one(conn, "SELECT * FROM patients WHERE id=?", (p0,))

def q_clinical_17937(conn, p0):
    return one(conn, "SELECT * FROM patients WHERE id=?", (p0,))

def q_clinical_25402(conn, p0):
    return one(conn, "SELECT * FROM patients WHERE id=?", (p0,))

def q_pharmacy_10684(conn):
    return rows(conn, """SELECT p.*, u.full_name AS doctor_name, pt.name AS patient_name, pt.primary_phone, pt.gender, pt.dob,
                  pt.age_at_registration, pt.age_unit, pt.age_is_estimated
           FROM prescriptions p
           JOIN patients pt ON pt.id=p.patient_id
           LEFT JOIN users u ON u.id=p.doctor_id
           WHERE p.status IN ('FINALIZED','PARTIAL')
           ORDER BY p.finalized_at""", ())

def q_billing_13318(conn, p0):
    return one(conn, "SELECT id FROM patients WHERE id=?", (p0,))

def q_billing_18932(conn, p0):
    return one(conn, "SELECT * FROM patients WHERE id=?", (p0,))

def q_billing_23116(conn, p0):
    return one(conn, "SELECT * FROM patients WHERE id=?", (p0,))

def q_wards_1067(conn, p0):
    return rows(conn, """SELECT b.*, r.name AS room_name, r.daily_rate_paise, r.ac, a.patient_id, p.name AS patient_name, a.id AS admission_id
               FROM beds b JOIN rooms r ON r.id=b.room_id
               LEFT JOIN admissions a ON a.id=b.current_admission_id
               LEFT JOIN patients p ON p.id=a.patient_id
               WHERE b.ward_id=? AND b.active=1 AND r.active=1 ORDER BY r.name, b.name""", (p0,))

def q_wards_2672(conn, p0):
    return one(conn, "SELECT id FROM patients WHERE id=?", (p0,))

def q_wards_27528(conn, p0):
    return one(conn, "SELECT id FROM patients WHERE id=?", (p0,))

def q_system_33662(conn, p0, p1):
    return rows(conn, "SELECT id, name, primary_phone, gender, hospital_no FROM patients WHERE search_text LIKE ? OR id LIKE ? ORDER BY name LIMIT 12", (p0, p1))

def q_system_35672(conn):
    return rows(conn, """SELECT q.id, q.token_no, q.status, q.doctor_id, q.arrived_at, q.encounter_id, p.name AS patient_name, p.id AS patient_id
           FROM queue_entries q JOIN patients p ON p.id=q.patient_id
           WHERE q.status NOT IN ('COMPLETED','CANCELLED') ORDER BY q.priority DESC, q.token_no LIMIT 12""", ())

def q_system_36093(conn, p0):
    return one(conn, "SELECT COUNT(*) AS n FROM patients WHERE substr(created_at,1,10)=?", (p0,))

def q_system_37908(conn, p0):
    return rows(conn, """SELECT q.*, p.name AS patient_name FROM queue_entries q JOIN patients p ON p.id=q.patient_id
               WHERE q.doctor_id=? AND q.status NOT IN ('COMPLETED','CANCELLED') ORDER BY q.token_no""", (p0,))

def q_system_38548(conn, p0):
    return one(conn, "SELECT COUNT(*) AS n FROM patients WHERE substr(created_at,1,10)=?", (p0,))

def q_system_40931(conn):
    return rows(conn, """SELECT w.name AS ward, b.name AS bed, b.status, p.name AS patient
               FROM beds b JOIN wards w ON w.id=b.ward_id LEFT JOIN admissions a ON a.id=b.current_admission_id
               LEFT JOIN patients p ON p.id=a.patient_id ORDER BY w.name, b.name""", ())

def q_system_48408(conn):
    return rows(conn, "SELECT id FROM patients WHERE is_sample=1", ())

def sample_names(conn):
    return rows(conn, "SELECT id, name FROM patients WHERE is_sample=1 ORDER BY name", ())

def q_notify_8600(conn, p0):
    return one(conn, "SELECT * FROM patients WHERE id=?", (p0,))

def patient_document_keys(conn, patient_id: str) -> list[str]:
    keys = []
    for row in rows(conn, "SELECT stored_name FROM documents WHERE patient_id=?", (patient_id,)):
        if row.get("stored_name"):
            keys.append(row["stored_name"])
    return keys


def purge_patient(conn, patient_id: str) -> None:
    pid = (patient_id,)
    exec_if(conn, "lab_results", "DELETE FROM lab_results WHERE lab_order_item_id IN (SELECT id FROM lab_order_items WHERE order_id IN (SELECT id FROM lab_orders WHERE patient_id=?))", pid)
    exec_if(conn, "lab_sample_items", "DELETE FROM lab_sample_items WHERE sample_id IN (SELECT id FROM lab_samples WHERE patient_id=?)", pid)
    if exec_if(conn, "lab_samples", "SELECT id FROM lab_samples WHERE patient_id=?", pid) is not None:
        for sample in rows(conn, "SELECT id FROM lab_samples WHERE patient_id=?", pid):
            execute(conn, "UPDATE lab_samples SET replaces_sample_id=NULL WHERE replaces_sample_id=?", (sample["id"],))
        execute(conn, "UPDATE lab_samples SET replaces_sample_id=NULL WHERE patient_id=?", pid)
        execute(conn, "DELETE FROM lab_samples WHERE patient_id=?", pid)
    exec_if(conn, "lab_reports", "DELETE FROM lab_reports WHERE patient_id=?", pid)
    exec_if(conn, "lab_order_items", "DELETE FROM lab_order_items WHERE order_id IN (SELECT id FROM lab_orders WHERE patient_id=?)", pid)
    exec_if(conn, "lab_orders", "DELETE FROM lab_orders WHERE patient_id=?", pid)
    exec_if(conn, "prescription_items", "DELETE FROM prescription_items WHERE prescription_id IN (SELECT id FROM prescriptions WHERE patient_id=?)", pid)
    exec_if(conn, "dispense_lines", "DELETE FROM dispense_lines WHERE patient_id=?", pid)
    exec_if(conn, "prescriptions", "DELETE FROM prescriptions WHERE patient_id=?", pid)
    exec_if(conn, "consultation_revisions", "DELETE FROM consultation_revisions WHERE consultation_id IN (SELECT id FROM consultations WHERE patient_id=?)", pid)
    exec_if(conn, "consultations", "DELETE FROM consultations WHERE patient_id=?", pid)
    exec_if(conn, "queue_entries", "DELETE FROM queue_entries WHERE patient_id=?", pid)
    exec_if(conn, "financial_adjustments", "DELETE FROM financial_adjustments WHERE invoice_id IN (SELECT id FROM invoices WHERE patient_id=?)", pid)
    exec_if(conn, "invoice_revisions", "DELETE FROM invoice_revisions WHERE invoice_id IN (SELECT id FROM invoices WHERE patient_id=?)", pid)
    exec_if(conn, "ot_charge_links", "DELETE FROM ot_charge_links WHERE ot_id IN (SELECT id FROM ot_cases WHERE patient_id=?)", pid)
    exec_if(conn, "invoice_items", "DELETE FROM invoice_items WHERE invoice_id IN (SELECT id FROM invoices WHERE patient_id=?)", pid)
    exec_if(conn, "payments", "DELETE FROM payments WHERE patient_id=?", pid)
    exec_if(conn, "deposits", "DELETE FROM deposits WHERE patient_id=?", pid)
    exec_if(conn, "invoices", "DELETE FROM invoices WHERE patient_id=?", pid)
    exec_if(conn, "beds", "UPDATE beds SET current_admission_id=NULL, status='AVAILABLE' WHERE current_admission_id IN (SELECT id FROM admissions WHERE patient_id=?)", pid)
    exec_if(conn, "admission_charges", "DELETE FROM admission_charges WHERE admission_id IN (SELECT id FROM admissions WHERE patient_id=?)", pid)
    exec_if(conn, "bed_movements", "DELETE FROM bed_movements WHERE patient_id=?", pid)
    exec_if(conn, "ot_preop_checks", "DELETE FROM ot_preop_checks WHERE preop_id IN (SELECT id FROM ot_preop_records WHERE ot_id IN (SELECT id FROM ot_cases WHERE patient_id=?))", pid)
    exec_if(conn, "ot_preop_records", "DELETE FROM ot_preop_records WHERE ot_id IN (SELECT id FROM ot_cases WHERE patient_id=?)", pid)
    exec_if(conn, "ot_intraop_records", "DELETE FROM ot_intraop_records WHERE ot_id IN (SELECT id FROM ot_cases WHERE patient_id=?)", pid)
    exec_if(conn, "ot_postop_records", "DELETE FROM ot_postop_records WHERE ot_id IN (SELECT id FROM ot_cases WHERE patient_id=?)", pid)
    exec_if(conn, "ot_team_members", "DELETE FROM ot_team_members WHERE ot_id IN (SELECT id FROM ot_cases WHERE patient_id=?)", pid)
    exec_if(conn, "ot_links", "DELETE FROM ot_links WHERE ot_id IN (SELECT id FROM ot_cases WHERE patient_id=?)", pid)
    exec_if(conn, "ot_booking_history", "DELETE FROM ot_booking_history WHERE ot_id IN (SELECT id FROM ot_cases WHERE patient_id=?)", pid)
    exec_if(conn, "ot_bookings", "DELETE FROM ot_bookings WHERE ot_id IN (SELECT id FROM ot_cases WHERE patient_id=?)", pid)
    exec_if(conn, "ot_cases", "DELETE FROM ot_cases WHERE patient_id=?", pid)
    exec_if(conn, "admissions", "DELETE FROM admissions WHERE patient_id=?", pid)
    exec_if(conn, "notifications", "DELETE FROM notifications WHERE patient_id=?", pid)
    exec_if(conn, "leads", "UPDATE leads SET patient_id=NULL WHERE patient_id=?", pid)
    exec_if(conn, "documents", "DELETE FROM documents WHERE patient_id=?", pid)
    exec_if(conn, "encounters", "DELETE FROM encounters WHERE patient_id=?", pid)
    execute(conn, "DELETE FROM patients WHERE id=?", pid)


def q_seed_17935(conn, p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11, p12, p13, p14):
    return execute(conn, """INSERT INTO patients(id, hospital_no, name, guardian_name, primary_phone, gender, age_at_registration, age_unit, age_is_estimated,
           address, category_id, department_id, allergies, is_sample, status, search_text, created_by, created_at, updated_at, dob)
           VALUES (?,?,?,?,?,?,?,'Y',0,?,?,?,?,1,'ACTIVE',?,'U-RECEPTION',?,?,?)""", (p0, p1, p2, p3, p4, p5, p6, p7, p8, p9, p10, p11, p12, p13, p14))

