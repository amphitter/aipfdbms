-- Deposit receipts stay distinct from invoice payments. Allocation is explicit.
ALTER TABLE deposits ADD COLUMN encounter_id TEXT;
ALTER TABLE deposits ADD COLUMN deposit_type TEXT;
ALTER TABLE deposits ADD COLUMN utilized_paise INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS financial_adjustments (
  id TEXT PRIMARY KEY,
  invoice_id TEXT NOT NULL,
  amount_paise INTEGER NOT NULL,
  description TEXT NOT NULL,
  reason TEXT NOT NULL,
  status TEXT NOT NULL,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  approved_by TEXT,
  approved_at TEXT,
  FOREIGN KEY (invoice_id) REFERENCES invoices(id),
  FOREIGN KEY (created_by) REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_adjustments_invoice ON financial_adjustments(invoice_id);
