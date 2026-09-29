ALTER TABLE lab_tests ADD COLUMN container_type TEXT;
ALTER TABLE lab_tests ADD COLUMN unit TEXT;
ALTER TABLE lab_tests ADD COLUMN reference_range TEXT;
ALTER TABLE lab_tests ADD COLUMN reference_low TEXT;
ALTER TABLE lab_tests ADD COLUMN reference_high TEXT;
ALTER TABLE lab_tests ADD COLUMN critical_low TEXT;
ALTER TABLE lab_tests ADD COLUMN critical_high TEXT;
ALTER TABLE lab_tests ADD COLUMN methodology TEXT;
ALTER TABLE lab_tests ADD COLUMN result_type TEXT;
ALTER TABLE lab_tests ADD COLUMN updated_at TEXT;

ALTER TABLE lab_orders ADD COLUMN priority TEXT NOT NULL DEFAULT 'ROUTINE';
ALTER TABLE lab_orders ADD COLUMN cancelled_at TEXT;
ALTER TABLE lab_orders ADD COLUMN cancelled_by TEXT;
ALTER TABLE lab_orders ADD COLUMN cancel_reason TEXT;

ALTER TABLE lab_results ADD COLUMN result_type TEXT;
ALTER TABLE lab_results ADD COLUMN reference_low TEXT;
ALTER TABLE lab_results ADD COLUMN reference_high TEXT;
ALTER TABLE lab_results ADD COLUMN critical_low TEXT;
ALTER TABLE lab_results ADD COLUMN critical_high TEXT;
ALTER TABLE lab_results ADD COLUMN methodology TEXT;
ALTER TABLE lab_results ADD COLUMN abnormal_flag TEXT;
ALTER TABLE lab_results ADD COLUMN critical_flag INTEGER NOT NULL DEFAULT 0;
ALTER TABLE lab_results ADD COLUMN remarks TEXT;
ALTER TABLE lab_results ADD COLUMN revision_no INTEGER NOT NULL DEFAULT 1;
ALTER TABLE lab_results ADD COLUMN supersedes_id TEXT;
ALTER TABLE lab_results ADD COLUMN correction_reason TEXT;
ALTER TABLE lab_results ADD COLUMN verified_by TEXT;
ALTER TABLE lab_results ADD COLUMN verified_at TEXT;

CREATE TABLE IF NOT EXISTS lab_samples (
  id TEXT PRIMARY KEY,
  accession_no TEXT NOT NULL UNIQUE,
  patient_id TEXT NOT NULL,
  encounter_id TEXT,
  order_id TEXT NOT NULL,
  specimen_type TEXT,
  container_type TEXT,
  status TEXT NOT NULL,
  collected_at TEXT,
  collected_by TEXT,
  collection_location TEXT,
  collection_notes TEXT,
  received_at TEXT,
  received_by TEXT,
  rejected_at TEXT,
  rejected_by TEXT,
  rejection_reason TEXT,
  replaces_sample_id TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (patient_id) REFERENCES patients(id),
  FOREIGN KEY (encounter_id) REFERENCES encounters(id),
  FOREIGN KEY (order_id) REFERENCES lab_orders(id),
  FOREIGN KEY (collected_by) REFERENCES users(id),
  FOREIGN KEY (received_by) REFERENCES users(id),
  FOREIGN KEY (rejected_by) REFERENCES users(id),
  FOREIGN KEY (replaces_sample_id) REFERENCES lab_samples(id)
);

CREATE TABLE IF NOT EXISTS lab_sample_items (
  sample_id TEXT NOT NULL,
  order_item_id TEXT NOT NULL,
  PRIMARY KEY (sample_id, order_item_id),
  FOREIGN KEY (sample_id) REFERENCES lab_samples(id),
  FOREIGN KEY (order_item_id) REFERENCES lab_order_items(id)
);

CREATE TABLE IF NOT EXISTS lab_reports (
  id TEXT PRIMARY KEY,
  order_id TEXT NOT NULL,
  patient_id TEXT NOT NULL,
  encounter_id TEXT,
  document_id TEXT NOT NULL,
  fingerprint TEXT NOT NULL,
  generated_by TEXT,
  generated_at TEXT NOT NULL,
  FOREIGN KEY (order_id) REFERENCES lab_orders(id),
  FOREIGN KEY (patient_id) REFERENCES patients(id),
  FOREIGN KEY (encounter_id) REFERENCES encounters(id),
  FOREIGN KEY (document_id) REFERENCES documents(id),
  FOREIGN KEY (generated_by) REFERENCES users(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_lab_tests_code ON lab_tests(code) WHERE code IS NOT NULL AND code <> '';
CREATE UNIQUE INDEX IF NOT EXISTS uq_lab_result_current ON lab_results(lab_order_item_id) WHERE status IN ('ENTERED', 'VERIFIED');
CREATE UNIQUE INDEX IF NOT EXISTS uq_lab_report_fingerprint ON lab_reports(order_id, fingerprint);
CREATE INDEX IF NOT EXISTS idx_lab_samples_order ON lab_samples(order_id, status);
CREATE INDEX IF NOT EXISTS idx_lab_samples_queue ON lab_samples(status, collected_at);
CREATE INDEX IF NOT EXISTS idx_lab_sample_items_item ON lab_sample_items(order_item_id);
CREATE INDEX IF NOT EXISTS idx_lab_reports_order ON lab_reports(order_id, generated_at);

INSERT INTO master_items(id, list_type, name, code, description, meta, sort_order, active, created_at)
SELECT 'MR-LAB-HAEM', 'lab_rejection_reason', 'Haemolysed', 'HAEMOLYSED', 'Sample is haemolysed', '{}', 1, 1, '2026-01-01T00:00:00+05:30'
WHERE NOT EXISTS (SELECT 1 FROM master_items WHERE id = 'MR-LAB-HAEM');
INSERT INTO master_items(id, list_type, name, code, description, meta, sort_order, active, created_at)
SELECT 'MR-LAB-INSUF', 'lab_rejection_reason', 'Insufficient', 'INSUFFICIENT', 'Quantity is not enough', '{}', 2, 1, '2026-01-01T00:00:00+05:30'
WHERE NOT EXISTS (SELECT 1 FROM master_items WHERE id = 'MR-LAB-INSUF');
INSERT INTO master_items(id, list_type, name, code, description, meta, sort_order, active, created_at)
SELECT 'MR-LAB-LABEL', 'lab_rejection_reason', 'Mislabeled', 'MISLABELED', 'Identity on the container does not match', '{}', 3, 1, '2026-01-01T00:00:00+05:30'
WHERE NOT EXISTS (SELECT 1 FROM master_items WHERE id = 'MR-LAB-LABEL');
INSERT INTO master_items(id, list_type, name, code, description, meta, sort_order, active, created_at)
SELECT 'MR-LAB-CLOT', 'lab_rejection_reason', 'Clotted', 'CLOTTED', 'Sample is clotted', '{}', 4, 1, '2026-01-01T00:00:00+05:30'
WHERE NOT EXISTS (SELECT 1 FROM master_items WHERE id = 'MR-LAB-CLOT');
INSERT INTO master_items(id, list_type, name, code, description, meta, sort_order, active, created_at)
SELECT 'MR-LAB-OTHER', 'lab_rejection_reason', 'Other', 'OTHER', 'Another configured reason; notes are required', '{}', 5, 1, '2026-01-01T00:00:00+05:30'
WHERE NOT EXISTS (SELECT 1 FROM master_items WHERE id = 'MR-LAB-OTHER');
