CREATE TABLE IF NOT EXISTS ot_theatres (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL,
  name TEXT NOT NULL,
  location TEXT,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_ot_theatre_code ON ot_theatres(lower(code));

CREATE TABLE IF NOT EXISTS ot_procedures (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL,
  name TEXT NOT NULL,
  department_id TEXT,
  category TEXT,
  price_paise INTEGER NOT NULL CHECK (price_paise >= 0),
  duration_minutes INTEGER NOT NULL DEFAULT 60 CHECK (duration_minutes > 0),
  require_admission INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_ot_procedure_code ON ot_procedures(lower(code));

CREATE TABLE IF NOT EXISTS ot_checklist_items (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL,
  label TEXT NOT NULL,
  required INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  sort_order INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_ot_checklist_code ON ot_checklist_items(lower(code));

CREATE TABLE IF NOT EXISTS ot_bookings (
  id TEXT PRIMARY KEY,
  ot_id TEXT NOT NULL,
  theatre_id TEXT NOT NULL,
  surgeon_id TEXT,
  start_at TEXT NOT NULL,
  end_at TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('SCHEDULED', 'PRE_OP', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED', 'POSTPONED')),
  created_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ot_booking_theatre ON ot_bookings(theatre_id, status, start_at, end_at);
CREATE INDEX IF NOT EXISTS idx_ot_booking_surgeon ON ot_bookings(surgeon_id, status, start_at, end_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_ot_one_active_booking ON ot_bookings(ot_id) WHERE status IN ('SCHEDULED', 'PRE_OP', 'IN_PROGRESS');

CREATE TABLE IF NOT EXISTS ot_booking_history (
  id TEXT PRIMARY KEY,
  booking_id TEXT,
  ot_id TEXT NOT NULL,
  action TEXT NOT NULL,
  theatre_id TEXT,
  surgeon_id TEXT,
  start_at TEXT,
  end_at TEXT,
  reason TEXT,
  actor_id TEXT,
  at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ot_booking_history ON ot_booking_history(ot_id, at);

CREATE TABLE IF NOT EXISTS ot_team_members (
  id TEXT PRIMARY KEY,
  ot_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  function_code TEXT NOT NULL,
  assigned_by TEXT,
  assigned_at TEXT NOT NULL,
  removed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_ot_team_case ON ot_team_members(ot_id, removed_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_ot_one_surgeon ON ot_team_members(ot_id) WHERE function_code = 'surgeon' AND removed_at IS NULL;

CREATE TABLE IF NOT EXISTS ot_preop_records (
  id TEXT PRIMARY KEY,
  ot_id TEXT NOT NULL,
  consent_status TEXT NOT NULL CHECK (consent_status IN ('PENDING', 'OBTAINED', 'REFUSED')),
  readiness TEXT NOT NULL CHECK (readiness IN ('PENDING', 'READY', 'NOT_READY')),
  assessment TEXT,
  allergies TEXT,
  recorded_by TEXT,
  recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ot_preop_case ON ot_preop_records(ot_id, recorded_at);

CREATE TABLE IF NOT EXISTS ot_preop_checks (
  id TEXT PRIMARY KEY,
  preop_id TEXT NOT NULL,
  item_id TEXT NOT NULL,
  satisfied INTEGER NOT NULL DEFAULT 0,
  note TEXT
);
CREATE INDEX IF NOT EXISTS idx_ot_preop_checks ON ot_preop_checks(preop_id);

CREATE TABLE IF NOT EXISTS ot_intraop_records (
  id TEXT PRIMARY KEY,
  ot_id TEXT NOT NULL,
  notes TEXT NOT NULL,
  findings TEXT,
  complications TEXT,
  anesthesia TEXT,
  recorded_by TEXT,
  recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ot_intraop_case ON ot_intraop_records(ot_id, recorded_at);

CREATE TABLE IF NOT EXISTS ot_postop_records (
  id TEXT PRIMARY KEY,
  ot_id TEXT NOT NULL,
  notes TEXT NOT NULL,
  instructions TEXT,
  condition TEXT,
  recorded_by TEXT,
  recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ot_postop_case ON ot_postop_records(ot_id, recorded_at);

CREATE TABLE IF NOT EXISTS ot_links (
  id TEXT PRIMARY KEY,
  ot_id TEXT NOT NULL,
  module TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  linked_by TEXT,
  linked_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_ot_link ON ot_links(ot_id, module, entity_id);

CREATE TABLE IF NOT EXISTS ot_charge_links (
  id TEXT PRIMARY KEY,
  ot_id TEXT NOT NULL,
  procedure_id TEXT NOT NULL,
  purpose TEXT NOT NULL,
  invoice_item_id TEXT NOT NULL,
  price_paise INTEGER NOT NULL,
  created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_ot_charge_purpose ON ot_charge_links(ot_id, procedure_id, purpose);

ALTER TABLE ot_cases ADD COLUMN priority TEXT;
ALTER TABLE ot_cases ADD COLUMN indication TEXT;
ALTER TABLE ot_cases ADD COLUMN theatre_id TEXT;
ALTER TABLE ot_cases ADD COLUMN consent_status TEXT;
ALTER TABLE ot_cases ADD COLUMN readiness TEXT;
ALTER TABLE ot_cases ADD COLUMN approved_at TEXT;
ALTER TABLE ot_cases ADD COLUMN approved_by TEXT;
ALTER TABLE ot_cases ADD COLUMN started_by TEXT;
ALTER TABLE ot_cases ADD COLUMN completed_at TEXT;
ALTER TABLE ot_cases ADD COLUMN completed_by TEXT;
ALTER TABLE ot_cases ADD COLUMN cancelled_at TEXT;
ALTER TABLE ot_cases ADD COLUMN cancel_reason TEXT;
ALTER TABLE ot_cases ADD COLUMN cancelled_by TEXT;
ALTER TABLE ot_cases ADD COLUMN postponed_at TEXT;
ALTER TABLE ot_cases ADD COLUMN postpone_reason TEXT;
ALTER TABLE ot_cases ADD COLUMN report_document_id TEXT;
ALTER TABLE ot_cases ADD COLUMN report_fingerprint TEXT;
ALTER TABLE ot_cases ADD COLUMN price_snapshot_paise INTEGER;
ALTER TABLE ot_cases ADD COLUMN procedure_code TEXT;
