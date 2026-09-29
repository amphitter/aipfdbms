CREATE TABLE IF NOT EXISTS idempotency_keys (
  idempotency_key TEXT PRIMARY KEY,
  scope TEXT NOT NULL,
  request_hash TEXT NOT NULL,
  entity_id TEXT,
  created_at TEXT NOT NULL
);
ALTER TABLE payments ADD COLUMN idempotency_key TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS uq_payments_idempotency
  ON payments(idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE TABLE IF NOT EXISTS lab_results (
  id TEXT PRIMARY KEY,
  lab_order_item_id TEXT NOT NULL REFERENCES lab_order_items(id),
  value_text TEXT,
  units TEXT,
  reference_range TEXT,
  status TEXT NOT NULL DEFAULT 'ENTERED',
  entered_by TEXT REFERENCES users(id),
  entered_at TEXT,
  finalized_by TEXT REFERENCES users(id),
  finalized_at TEXT,
  document_id TEXT REFERENCES documents(id)
);
CREATE INDEX IF NOT EXISTS idx_lab_results_item ON lab_results(lab_order_item_id);
