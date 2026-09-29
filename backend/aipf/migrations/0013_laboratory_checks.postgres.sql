ALTER TABLE lab_orders DROP CONSTRAINT IF EXISTS lab_orders_status_check;
ALTER TABLE lab_orders ADD CONSTRAINT lab_orders_status_check CHECK (status IN (
  'ORDERED', 'BILLED', 'SAMPLE_PENDING', 'SAMPLE_COLLECTED', 'PROCESSING',
  'RESULT_ENTERED', 'VERIFIED', 'RESULTED', 'CANCELLED', 'RECOLLECTION_REQUIRED'
));

ALTER TABLE lab_orders DROP CONSTRAINT IF EXISTS lab_orders_priority_check;
ALTER TABLE lab_orders ADD CONSTRAINT lab_orders_priority_check CHECK (priority IN ('ROUTINE', 'URGENT', 'STAT'));

ALTER TABLE lab_order_items DROP CONSTRAINT IF EXISTS lab_order_items_status_check;
ALTER TABLE lab_order_items ADD CONSTRAINT lab_order_items_status_check CHECK (status IN (
  'ORDERED', 'SAMPLE_PENDING', 'SAMPLE_COLLECTED', 'PROCESSING', 'RESULT_PENDING',
  'RESULT_ENTERED', 'VERIFIED', 'RESULTED', 'CANCELLED', 'RECOLLECTION_REQUIRED'
));

ALTER TABLE lab_samples DROP CONSTRAINT IF EXISTS lab_samples_status_check;
ALTER TABLE lab_samples ADD CONSTRAINT lab_samples_status_check CHECK (status IN (
  'COLLECTED', 'RECEIVED', 'PROCESSING', 'REJECTED', 'RECOLLECTION_REQUIRED'
));

ALTER TABLE lab_samples DROP CONSTRAINT IF EXISTS lab_samples_accession_present;
ALTER TABLE lab_samples ADD CONSTRAINT lab_samples_accession_present CHECK (length(accession_no) > 0);

ALTER TABLE lab_results DROP CONSTRAINT IF EXISTS lab_results_status_check;
ALTER TABLE lab_results ADD CONSTRAINT lab_results_status_check CHECK (status IN (
  'ENTERED', 'VERIFIED', 'SUPERSEDED', 'FINALIZED'
));

ALTER TABLE lab_results DROP CONSTRAINT IF EXISTS lab_results_revision_positive;
ALTER TABLE lab_results ADD CONSTRAINT lab_results_revision_positive CHECK (revision_no >= 1);

ALTER TABLE lab_tests DROP CONSTRAINT IF EXISTS lab_tests_result_type_check;
ALTER TABLE lab_tests ADD CONSTRAINT lab_tests_result_type_check CHECK (
  result_type IS NULL OR result_type IN ('numeric', 'text', 'qualitative', 'positive_negative', 'normal_abnormal')
);

ALTER TABLE lab_results DROP CONSTRAINT IF EXISTS lab_results_result_type_check;
ALTER TABLE lab_results ADD CONSTRAINT lab_results_result_type_check CHECK (
  result_type IS NULL OR result_type IN ('numeric', 'text', 'qualitative', 'positive_negative', 'normal_abnormal')
);

ALTER TABLE lab_results DROP CONSTRAINT IF EXISTS lab_results_critical_flag_check;
ALTER TABLE lab_results ADD CONSTRAINT lab_results_critical_flag_check CHECK (critical_flag IN (0, 1));
