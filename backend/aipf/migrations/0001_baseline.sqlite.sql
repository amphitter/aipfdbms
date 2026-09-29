-- AI-PF Hospital Operations System
-- Relational schema v1. Master-data values are rows, not columns.

CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS roles (
  code TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT,
  active INTEGER NOT NULL DEFAULT 1,
  is_system INTEGER NOT NULL DEFAULT 0,
  sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS permissions (
  code TEXT PRIMARY KEY,
  module TEXT NOT NULL,
  description TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS role_permissions (
  role TEXT NOT NULL,
  permission TEXT NOT NULL,
  PRIMARY KEY (role, permission)
);

CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  username TEXT NOT NULL UNIQUE,
  full_name TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  title TEXT,
  specialty TEXT,
  department_id TEXT,
  phone TEXT,
  active INTEGER NOT NULL DEFAULT 1,
  is_admin_doctor INTEGER NOT NULL DEFAULT 0,
  must_change_password INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS user_roles (
  user_id TEXT NOT NULL,
  role TEXT NOT NULL,
  PRIMARY KEY (user_id, role)
);

CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  workstation TEXT,
  ip TEXT,
  user_agent TEXT,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  revoked_at TEXT
);

CREATE TABLE IF NOT EXISTS audit_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  user_id TEXT,
  username TEXT,
  action TEXT NOT NULL,
  module TEXT,
  entity TEXT,
  entity_id TEXT,
  old_value TEXT,
  new_value TEXT,
  reason TEXT,
  workstation TEXT,
  ip TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_at ON audit_logs(at);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_logs(entity, entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_logs(user_id, at);

CREATE TABLE IF NOT EXISTS app_config (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  is_secret INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT,
  updated_by TEXT
);

CREATE TABLE IF NOT EXISTS sequences (
  name TEXT NOT NULL,
  year INTEGER NOT NULL,
  next_value INTEGER NOT NULL,
  PRIMARY KEY (name, year)
);

CREATE TABLE IF NOT EXISTS hospital_profile (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  name TEXT NOT NULL,
  legal_name TEXT,
  tagline TEXT,
  address_line1 TEXT,
  address_line2 TEXT,
  city TEXT,
  state TEXT,
  pin TEXT,
  phone TEXT,
  email TEXT,
  website TEXT,
  registration_no TEXT,
  logo_path TEXT,
  logo_mono_path TEXT,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS master_items (
  id TEXT PRIMARY KEY,
  list_type TEXT NOT NULL,
  name TEXT NOT NULL,
  code TEXT,
  description TEXT,
  meta TEXT,
  sort_order INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_master_type ON master_items(list_type, active, sort_order);

CREATE TABLE IF NOT EXISTS opd_types (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  code TEXT,
  fee_paise INTEGER NOT NULL DEFAULT 0,
  validity_days INTEGER NOT NULL DEFAULT 1,
  description TEXT,
  services_included TEXT,
  departments TEXT,
  active INTEGER NOT NULL DEFAULT 1,
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS services (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  code TEXT,
  category TEXT NOT NULL,
  department_id TEXT,
  rate_paise INTEGER NOT NULL DEFAULT 0,
  unit TEXT,
  description TEXT,
  active INTEGER NOT NULL DEFAULT 1,
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lab_tests (
  id TEXT PRIMARY KEY,
  code TEXT,
  name TEXT NOT NULL,
  category TEXT,
  department_id TEXT,
  price_paise INTEGER NOT NULL DEFAULT 0,
  sample_type TEXT,
  preparation TEXT,
  tat_hours INTEGER,
  active INTEGER NOT NULL DEFAULT 1,
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS patients (
  id TEXT PRIMARY KEY,
  hospital_no TEXT,
  name TEXT NOT NULL,
  guardian_name TEXT,
  guardian_phone TEXT,
  primary_phone TEXT,
  alternate_phone TEXT,
  gender TEXT,
  dob TEXT,
  age_at_registration INTEGER,
  age_unit TEXT,
  age_is_estimated INTEGER NOT NULL DEFAULT 0,
  address TEXT,
  email TEXT,
  category_id TEXT,
  department_id TEXT,
  emergency_name TEXT,
  emergency_phone TEXT,
  notes TEXT,
  allergies TEXT,
  is_sample INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'ACTIVE',
  search_text TEXT,
  created_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_patient_phone ON patients(primary_phone);
CREATE INDEX IF NOT EXISTS idx_patient_phone2 ON patients(alternate_phone);
CREATE INDEX IF NOT EXISTS idx_patient_gphone ON patients(guardian_phone);
CREATE INDEX IF NOT EXISTS idx_patient_name ON patients(name);
CREATE INDEX IF NOT EXISTS idx_patient_search ON patients(search_text);
CREATE INDEX IF NOT EXISTS idx_patient_hno ON patients(hospital_no);

CREATE TABLE IF NOT EXISTS encounters (
  id TEXT PRIMARY KEY,
  patient_id TEXT NOT NULL,
  opd_type_id TEXT,
  parent_opd_id TEXT,
  fee_paise INTEGER NOT NULL DEFAULT 0,
  fee_waived_reason TEXT,
  validity_until TEXT,
  doctor_id TEXT,
  department_id TEXT,
  status TEXT NOT NULL DEFAULT 'OPEN',
  chief_complaint TEXT,
  visit_kind TEXT NOT NULL DEFAULT 'OPD',
  arrived_at TEXT NOT NULL,
  completed_at TEXT,
  created_by TEXT,
  created_at TEXT NOT NULL,
  is_sample INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_enc_patient ON encounters(patient_id, arrived_at);
CREATE INDEX IF NOT EXISTS idx_enc_doctor ON encounters(doctor_id, status);

CREATE TABLE IF NOT EXISTS queue_entries (
  id TEXT PRIMARY KEY,
  token_no INTEGER NOT NULL,
  encounter_id TEXT NOT NULL,
  patient_id TEXT NOT NULL,
  doctor_id TEXT,
  department_id TEXT,
  status TEXT NOT NULL DEFAULT 'WAITING',
  priority INTEGER NOT NULL DEFAULT 0,
  priority_label TEXT,
  arrived_at TEXT NOT NULL,
  called_at TEXT,
  started_at TEXT,
  completed_at TEXT,
  notes TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_queue_status ON queue_entries(status, doctor_id);
CREATE INDEX IF NOT EXISTS idx_queue_enc ON queue_entries(encounter_id);

CREATE TABLE IF NOT EXISTS consultations (
  id TEXT PRIMARY KEY,
  encounter_id TEXT NOT NULL,
  patient_id TEXT NOT NULL,
  doctor_id TEXT NOT NULL,
  symptoms TEXT,
  findings TEXT,
  diagnosis TEXT,
  notes TEXT,
  instructions TEXT,
  follow_up TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_consult_enc ON consultations(encounter_id);

CREATE TABLE IF NOT EXISTS prescriptions (
  id TEXT PRIMARY KEY,
  encounter_id TEXT NOT NULL,
  consultation_id TEXT,
  patient_id TEXT NOT NULL,
  doctor_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'DRAFT',
  notes TEXT,
  finalized_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_rx_enc ON prescriptions(encounter_id);
CREATE INDEX IF NOT EXISTS idx_rx_status ON prescriptions(status);

CREATE TABLE IF NOT EXISTS prescription_items (
  id TEXT PRIMARY KEY,
  prescription_id TEXT NOT NULL,
  product_id TEXT,
  medicine_name TEXT NOT NULL,
  strength TEXT,
  dose TEXT,
  frequency TEXT,
  route TEXT,
  duration TEXT,
  duration_days INTEGER,
  timing TEXT,
  food_instruction TEXT,
  quantity REAL,
  unit TEXT,
  notes TEXT,
  dispensed_qty REAL NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'PENDING',
  sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_rxi_rx ON prescription_items(prescription_id);

CREATE TABLE IF NOT EXISTS products (
  id TEXT PRIMARY KEY,
  brand TEXT,
  name TEXT NOT NULL,
  composition TEXT,
  strength TEXT,
  dosage_form TEXT,
  manufacturer TEXT,
  unit TEXT NOT NULL DEFAULT 'Tablet',
  packaging TEXT,
  packaging_json TEXT,
  barcode TEXT,
  purchase_rate_paise INTEGER NOT NULL DEFAULT 0,
  sale_rate_paise INTEGER NOT NULL DEFAULT 0,
  mrp_paise INTEGER,
  min_stock REAL NOT NULL DEFAULT 0,
  reorder_level REAL NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_product_barcode ON products(barcode);
CREATE INDEX IF NOT EXISTS idx_product_name ON products(name);

CREATE TABLE IF NOT EXISTS batches (
  id TEXT PRIMARY KEY,
  product_id TEXT NOT NULL,
  batch_no TEXT NOT NULL,
  mfg_date TEXT,
  expiry_date TEXT,
  purchase_rate_paise INTEGER NOT NULL DEFAULT 0,
  sale_rate_paise INTEGER NOT NULL DEFAULT 0,
  qty_on_hand REAL NOT NULL DEFAULT 0,
  unit TEXT,
  barcode TEXT,
  manufacturer TEXT,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_batch_product ON batches(product_id);
CREATE INDEX IF NOT EXISTS idx_batch_barcode ON batches(barcode);
CREATE INDEX IF NOT EXISTS idx_batch_expiry ON batches(expiry_date);

CREATE TABLE IF NOT EXISTS stock_movements (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id TEXT NOT NULL,
  batch_id TEXT NOT NULL,
  qty REAL NOT NULL,
  unit TEXT,
  movement_type TEXT NOT NULL,
  reference_type TEXT,
  reference_id TEXT,
  reason TEXT,
  user_id TEXT,
  workstation TEXT,
  at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_move_batch ON stock_movements(batch_id, at);
CREATE INDEX IF NOT EXISTS idx_move_product ON stock_movements(product_id, at);

CREATE TABLE IF NOT EXISTS dispense_lines (
  id TEXT PRIMARY KEY,
  prescription_id TEXT NOT NULL,
  prescription_item_id TEXT,
  patient_id TEXT NOT NULL,
  encounter_id TEXT,
  product_id TEXT NOT NULL,
  batch_id TEXT NOT NULL,
  qty REAL NOT NULL,
  unit TEXT,
  rate_paise INTEGER NOT NULL,
  amount_paise INTEGER NOT NULL,
  substituted INTEGER NOT NULL DEFAULT 0,
  substitution_reason TEXT,
  invoice_item_id TEXT,
  dispensed_by TEXT,
  dispensed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lab_orders (
  id TEXT PRIMARY KEY,
  encounter_id TEXT,
  admission_id TEXT,
  patient_id TEXT NOT NULL,
  doctor_id TEXT,
  status TEXT NOT NULL DEFAULT 'ORDERED',
  notes TEXT,
  ordered_at TEXT NOT NULL,
  created_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_lab_patient ON lab_orders(patient_id, ordered_at);
CREATE INDEX IF NOT EXISTS idx_lab_status ON lab_orders(status);

CREATE TABLE IF NOT EXISTS lab_order_items (
  id TEXT PRIMARY KEY,
  order_id TEXT NOT NULL,
  test_id TEXT,
  custom_name TEXT,
  price_paise INTEGER NOT NULL DEFAULT 0,
  price_pending INTEGER NOT NULL DEFAULT 0,
  sample_type TEXT,
  status TEXT NOT NULL DEFAULT 'ORDERED',
  result_text TEXT,
  result_at TEXT,
  resulted_by TEXT,
  document_id TEXT,
  invoice_item_id TEXT
);

CREATE TABLE IF NOT EXISTS invoices (
  id TEXT PRIMARY KEY,
  number TEXT NOT NULL UNIQUE,
  patient_id TEXT NOT NULL,
  encounter_id TEXT,
  admission_id TEXT,
  bill_type TEXT NOT NULL DEFAULT 'OPD',
  status TEXT NOT NULL DEFAULT 'DRAFT',
  payment_status TEXT NOT NULL DEFAULT 'UNPAID',
  gross_paise INTEGER NOT NULL DEFAULT 0,
  discount_paise INTEGER NOT NULL DEFAULT 0,
  tax_paise INTEGER NOT NULL DEFAULT 0,
  net_paise INTEGER NOT NULL DEFAULT 0,
  deposit_applied_paise INTEGER NOT NULL DEFAULT 0,
  paid_paise INTEGER NOT NULL DEFAULT 0,
  due_paise INTEGER NOT NULL DEFAULT 0,
  discount_reason TEXT,
  notes TEXT,
  revision INTEGER NOT NULL DEFAULT 0,
  finalized_at TEXT,
  finalized_by TEXT,
  voided_at TEXT,
  void_reason TEXT,
  created_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT,
  is_sample INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_inv_patient ON invoices(patient_id, created_at);
CREATE INDEX IF NOT EXISTS idx_inv_status ON invoices(status, payment_status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_inv_number ON invoices(number);

CREATE TABLE IF NOT EXISTS invoice_items (
  id TEXT PRIMARY KEY,
  invoice_id TEXT NOT NULL,
  source_module TEXT,
  source_id TEXT,
  master_item_id TEXT,
  description TEXT NOT NULL,
  category TEXT NOT NULL,
  rate_paise INTEGER NOT NULL,
  qty REAL NOT NULL DEFAULT 1,
  unit TEXT,
  discount_paise INTEGER NOT NULL DEFAULT 0,
  tax_paise INTEGER NOT NULL DEFAULT 0,
  amount_paise INTEGER NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_item_inv ON invoice_items(invoice_id);

CREATE TABLE IF NOT EXISTS payments (
  id TEXT PRIMARY KEY,
  invoice_id TEXT,
  patient_id TEXT NOT NULL,
  admission_id TEXT,
  kind TEXT NOT NULL DEFAULT 'PAYMENT',
  mode TEXT NOT NULL,
  amount_paise INTEGER NOT NULL,
  reference TEXT,
  notes TEXT,
  received_by TEXT,
  workstation TEXT,
  received_at TEXT NOT NULL,
  reversed_by TEXT,
  reverses TEXT
);
CREATE INDEX IF NOT EXISTS idx_pay_inv ON payments(invoice_id);
CREATE INDEX IF NOT EXISTS idx_pay_patient ON payments(patient_id, received_at);

CREATE TABLE IF NOT EXISTS deposits (
  id TEXT PRIMARY KEY,
  patient_id TEXT NOT NULL,
  admission_id TEXT,
  amount_paise INTEGER NOT NULL,
  balance_paise INTEGER NOT NULL,
  mode TEXT,
  reference TEXT,
  received_by TEXT,
  received_at TEXT NOT NULL,
  notes TEXT,
  status TEXT NOT NULL DEFAULT 'OPEN'
);

CREATE TABLE IF NOT EXISTS invoice_revisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_id TEXT NOT NULL,
  revision_no INTEGER NOT NULL,
  reason TEXT NOT NULL,
  user_id TEXT,
  workstation TEXT,
  at TEXT NOT NULL,
  before_json TEXT NOT NULL,
  after_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS wards (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  code TEXT,
  ward_type TEXT,
  ac INTEGER NOT NULL DEFAULT 0,
  description TEXT,
  active INTEGER NOT NULL DEFAULT 1,
  sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS rooms (
  id TEXT PRIMARY KEY,
  ward_id TEXT NOT NULL,
  name TEXT NOT NULL,
  room_type TEXT,
  ac INTEGER NOT NULL DEFAULT 0,
  daily_rate_paise INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS beds (
  id TEXT PRIMARY KEY,
  room_id TEXT NOT NULL,
  ward_id TEXT NOT NULL,
  name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'AVAILABLE',
  current_admission_id TEXT,
  active INTEGER NOT NULL DEFAULT 1,
  notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_bed_status ON beds(status, ward_id);

CREATE TABLE IF NOT EXISTS admissions (
  id TEXT PRIMARY KEY,
  patient_id TEXT NOT NULL,
  encounter_id TEXT,
  admission_type TEXT NOT NULL DEFAULT 'INPATIENT',
  status TEXT NOT NULL DEFAULT 'ADMITTED',
  ward_id TEXT,
  room_id TEXT,
  bed_id TEXT,
  doctor_id TEXT,
  department_id TEXT,
  diagnosis TEXT,
  reason TEXT,
  admitted_at TEXT,
  expected_discharge TEXT,
  discharged_at TEXT,
  discharge_summary TEXT,
  discharge_condition TEXT,
  daily_rate_paise INTEGER NOT NULL DEFAULT 0,
  requested_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT,
  is_sample INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_adm_patient ON admissions(patient_id);
CREATE INDEX IF NOT EXISTS idx_adm_status ON admissions(status);

CREATE TABLE IF NOT EXISTS bed_movements (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  admission_id TEXT NOT NULL,
  patient_id TEXT NOT NULL,
  from_bed_id TEXT,
  to_bed_id TEXT,
  reason TEXT,
  user_id TEXT,
  at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS admission_charges (
  id TEXT PRIMARY KEY,
  admission_id TEXT NOT NULL,
  charge_date TEXT NOT NULL,
  description TEXT NOT NULL,
  category TEXT NOT NULL,
  rate_paise INTEGER NOT NULL,
  qty REAL NOT NULL DEFAULT 1,
  amount_paise INTEGER NOT NULL,
  source_module TEXT,
  source_id TEXT,
  invoice_item_id TEXT,
  posted_by TEXT,
  posted_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ot_cases (
  id TEXT PRIMARY KEY,
  patient_id TEXT NOT NULL,
  encounter_id TEXT,
  admission_id TEXT,
  procedure_name TEXT NOT NULL,
  procedure_id TEXT,
  surgeon_id TEXT,
  assistants TEXT,
  ot_staff TEXT,
  anesthesia TEXT,
  status TEXT NOT NULL DEFAULT 'REQUESTED',
  scheduled_at TEXT,
  started_at TEXT,
  ended_at TEXT,
  pre_op_notes TEXT,
  procedure_notes TEXT,
  findings TEXT,
  complications TEXT,
  post_op_instructions TEXT,
  outcome TEXT,
  notes_by TEXT,
  notes_at TEXT,
  requested_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_ot_patient ON ot_cases(patient_id);
CREATE INDEX IF NOT EXISTS idx_ot_status ON ot_cases(status);

CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY,
  patient_id TEXT,
  entity_type TEXT,
  entity_id TEXT,
  document_type TEXT NOT NULL,
  title TEXT,
  filename TEXT NOT NULL,
  stored_name TEXT NOT NULL,
  mime_type TEXT,
  size_bytes INTEGER,
  checksum TEXT,
  uploaded_by TEXT,
  uploaded_at TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_docs_patient ON documents(patient_id, uploaded_at);

CREATE TABLE IF NOT EXISTS notifications (
  id TEXT PRIMARY KEY,
  channel TEXT NOT NULL DEFAULT 'WHATSAPP',
  patient_id TEXT,
  phone TEXT,
  user_id TEXT,
  message_type TEXT,
  template_id TEXT,
  body TEXT,
  document_id TEXT,
  status TEXT NOT NULL DEFAULT 'QUEUED',
  scheduled_at TEXT,
  sent_at TEXT,
  provider TEXT,
  provider_message_id TEXT,
  failure_reason TEXT,
  retry_count INTEGER NOT NULL DEFAULT 0,
  max_retries INTEGER NOT NULL DEFAULT 3,
  entity_type TEXT,
  entity_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_notif_status ON notifications(channel, status, scheduled_at);

CREATE TABLE IF NOT EXISTS notification_templates (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  channel TEXT NOT NULL DEFAULT 'WHATSAPP',
  message_type TEXT,
  body TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT
);

CREATE TABLE IF NOT EXISTS leads (
  id TEXT PRIMARY KEY,
  external_id TEXT,
  name TEXT,
  phone TEXT,
  email TEXT,
  message TEXT,
  source TEXT,
  status TEXT NOT NULL DEFAULT 'NEW',
  patient_id TEXT,
  raw_json TEXT,
  received_at TEXT,
  synced_at TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS backups (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL DEFAULT 'MANUAL',
  status TEXT NOT NULL,
  local_path TEXT,
  size_bytes INTEGER,
  checksum TEXT,
  cloud_status TEXT,
  cloud_error TEXT,
  cloud_key TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  created_by TEXT,
  notes TEXT,
  verified_at TEXT
);

CREATE TABLE IF NOT EXISTS health_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  overall TEXT NOT NULL,
  payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  level TEXT NOT NULL,
  module TEXT,
  message TEXT NOT NULL,
  user_id TEXT,
  entity TEXT,
  entity_id TEXT,
  extra TEXT
);
CREATE INDEX IF NOT EXISTS idx_logs_at ON app_logs(at);
