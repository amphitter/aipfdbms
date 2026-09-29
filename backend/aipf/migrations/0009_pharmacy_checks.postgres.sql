ALTER TABLE batches ADD CONSTRAINT batches_qty_nonneg CHECK (qty_on_hand >= 0);

ALTER TABLE prescriptions ADD CONSTRAINT prescriptions_status_chk
  CHECK (status IN ('DRAFT', 'FINALIZED', 'PARTIAL', 'DISPENSED', 'CANCELLED'));

ALTER TABLE prescription_items ADD CONSTRAINT prescription_items_status_chk
  CHECK (status IN ('PENDING', 'PRESCRIBED', 'PARTIAL', 'DISPENSED', 'SUBSTITUTED', 'CANCELLED'));

ALTER TABLE dispense_lines ADD CONSTRAINT dispense_lines_qty_chk CHECK (qty > 0);

ALTER TABLE stock_movements ADD CONSTRAINT stock_movements_type_chk
  CHECK (movement_type IN ('OPENING', 'PURCHASE', 'RETURN', 'ADJUSTMENT', 'DISPENSED', 'DAMAGED', 'EXPIRED', 'LOST'));
