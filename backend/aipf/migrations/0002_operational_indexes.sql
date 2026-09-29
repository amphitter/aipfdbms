CREATE UNIQUE INDEX IF NOT EXISTS uq_admission_one_open
  ON admissions(patient_id) WHERE status IN ('REQUESTED', 'ADMITTED');
CREATE INDEX IF NOT EXISTS idx_enc_validity ON encounters(patient_id, validity_until);
CREATE INDEX IF NOT EXISTS idx_pay_received ON payments(received_at);
CREATE INDEX IF NOT EXISTS idx_notif_user ON notifications(user_id, status);
CREATE INDEX IF NOT EXISTS idx_docs_entity ON documents(entity_type, entity_id);
