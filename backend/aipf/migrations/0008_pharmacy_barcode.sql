-- Product, package, and barcode are not the same thing as a batch.
-- A package size is stored only when someone enters it. Nothing here assumes a box size.
-- Supplier purchasing and GRN documents are not part of this migration.

CREATE TABLE IF NOT EXISTS barcode_types (
  code TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS packaging_skus (
  id TEXT PRIMARY KEY,
  product_id TEXT NOT NULL REFERENCES products(id),
  name TEXT NOT NULL,
  unit TEXT NOT NULL,
  units_per_pack INTEGER NOT NULL CHECK (units_per_pack > 0),
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sku_product ON packaging_skus(product_id);

CREATE TABLE IF NOT EXISTS barcodes (
  id TEXT PRIMARY KEY,
  sku_id TEXT NOT NULL REFERENCES packaging_skus(id),
  batch_id TEXT REFERENCES batches(id),
  value TEXT NOT NULL,
  barcode_type TEXT NOT NULL REFERENCES barcode_types(code),
  scope TEXT NOT NULL DEFAULT 'SKU' CHECK (scope IN ('SKU', 'BATCH')),
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK ((scope = 'SKU' AND batch_id IS NULL) OR (scope = 'BATCH' AND batch_id IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_barcode_active ON barcodes(value) WHERE active = 1;
CREATE INDEX IF NOT EXISTS idx_barcode_sku ON barcodes(sku_id);

CREATE TABLE IF NOT EXISTS dispense_idempotency (
  idempotency_key TEXT PRIMARY KEY,
  request_hash TEXT NOT NULL,
  prescription_id TEXT NOT NULL REFERENCES prescriptions(id),
  result_json TEXT,
  created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_batch_product_no ON batches(product_id, batch_no);

DELETE FROM role_permissions WHERE role = 'pharmacist' AND permission = 'inventory.adjust';
