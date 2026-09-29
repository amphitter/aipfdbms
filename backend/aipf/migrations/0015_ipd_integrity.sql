-- One open inpatient episode per patient, including a discharge that has not finished.
DROP INDEX IF EXISTS uq_admission_one_open;
CREATE UNIQUE INDEX IF NOT EXISTS uq_admission_one_open
  ON admissions(patient_id)
  WHERE status IN ('REQUESTED', 'ADMITTED', 'DISCHARGE_PENDING');

-- One current bed pointer per admission. A bed row can hold only one occupant.
CREATE UNIQUE INDEX IF NOT EXISTS uq_bed_current_admission
  ON beds(current_admission_id)
  WHERE current_admission_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_ward_code
  ON wards(code)
  WHERE code IS NOT NULL AND code <> '';

CREATE UNIQUE INDEX IF NOT EXISTS uq_room_ward_name
  ON rooms(ward_id, name);

CREATE UNIQUE INDEX IF NOT EXISTS uq_bed_room_name
  ON beds(room_id, name);

-- Admission-day and bed-day charges share one period. Manual service lines are not included.
CREATE UNIQUE INDEX IF NOT EXISTS uq_bed_day_charge
  ON admission_charges(admission_id, charge_date)
  WHERE source_module IN ('bed_day', 'admission');

ALTER TABLE admissions ADD COLUMN discharge_doctor_id TEXT;
ALTER TABLE admissions ADD COLUMN discharge_document_id TEXT;
ALTER TABLE admissions ADD COLUMN discharge_fingerprint TEXT;
ALTER TABLE admissions ADD COLUMN cancelled_at TEXT;
ALTER TABLE admissions ADD COLUMN cancel_reason TEXT;
ALTER TABLE wards ADD COLUMN department_id TEXT;
ALTER TABLE wards ADD COLUMN gender_policy TEXT;
ALTER TABLE rooms ADD COLUMN floor TEXT;
ALTER TABLE rooms ADD COLUMN notes TEXT;
ALTER TABLE beds ADD COLUMN bed_type TEXT;
