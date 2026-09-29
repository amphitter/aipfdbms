ALTER TABLE stock_movements DROP CONSTRAINT IF EXISTS stock_movements_type_chk;
ALTER TABLE stock_movements ADD CONSTRAINT stock_movements_type_chk
  CHECK (movement_type IN (
    'OPENING', 'PURCHASE', 'RETURN', 'ADJUSTMENT', 'DISPENSED', 'DAMAGED', 'EXPIRED', 'LOST',
    'BILLING_ISSUE', 'BILLING_RETURN'
  ));
