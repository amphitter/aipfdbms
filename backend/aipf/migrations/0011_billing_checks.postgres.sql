-- Refund rows keep a positive amount and kind REFUND. A signed-amount check would reject them.
ALTER TABLE invoices ADD CONSTRAINT invoices_status_check
  CHECK (status IN ('DRAFT', 'FINALIZED', 'VOID'));

ALTER TABLE invoices ADD CONSTRAINT invoices_payment_status_check
  CHECK (payment_status IN ('UNPAID', 'PARTIAL', 'PAID', 'VOID'));

ALTER TABLE invoices ADD CONSTRAINT invoices_money_nonneg
  CHECK (
    gross_paise >= 0 AND discount_paise >= 0 AND tax_paise >= 0
    AND net_paise >= 0 AND paid_paise >= 0 AND due_paise >= 0
    AND deposit_applied_paise >= 0
  );

ALTER TABLE payments ADD CONSTRAINT payments_kind_check
  CHECK (kind IN ('PAYMENT', 'REFUND', 'DEPOSIT', 'DEPOSIT_APPLY'));

ALTER TABLE deposits ADD CONSTRAINT deposits_status_check
  CHECK (status IN ('OPEN', 'APPLIED', 'EXHAUSTED', 'REFUNDED'));

ALTER TABLE deposits ADD CONSTRAINT deposits_balance_check
  CHECK (
    amount_paise > 0
    AND balance_paise >= 0
    AND balance_paise <= amount_paise
    AND utilized_paise >= 0
    AND utilized_paise <= amount_paise
  );

ALTER TABLE financial_adjustments ADD CONSTRAINT financial_adjustments_status_check
  CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED'));
