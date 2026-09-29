CREATE TABLE IF NOT EXISTS queue_days (
  day TEXT PRIMARY KEY,
  next_token INTEGER NOT NULL
);

ALTER TABLE queue_entries ADD COLUMN service_day TEXT;
UPDATE queue_entries SET service_day = substr(created_at, 1, 10) WHERE service_day IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_queue_token_day ON queue_entries(service_day, token_no);
CREATE UNIQUE INDEX IF NOT EXISTS uq_queue_open_encounter
  ON queue_entries(encounter_id) WHERE status NOT IN ('COMPLETED', 'CANCELLED');

CREATE TABLE IF NOT EXISTS consultation_revisions (
  id TEXT PRIMARY KEY,
  consultation_id TEXT NOT NULL REFERENCES consultations(id),
  encounter_id TEXT NOT NULL REFERENCES encounters(id),
  doctor_id TEXT NOT NULL REFERENCES users(id),
  diagnosis TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_consult_rev ON consultation_revisions(consultation_id, created_at);
