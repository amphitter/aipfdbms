ALTER TABLE ot_cases ADD CONSTRAINT ot_cases_status_known CHECK (
  status IN (
    'REQUESTED', 'APPROVED', 'SCHEDULED', 'PRE_OP', 'IN_PROGRESS',
    'PERFORMED', 'NOTES_PENDING', 'RECOVERY', 'COMPLETED', 'CANCELLED', 'POSTPONED'
  )
);

ALTER TABLE ot_cases ADD CONSTRAINT ot_cases_priority_known CHECK (
  priority IS NULL OR priority IN ('ROUTINE', 'URGENT', 'EMERGENCY')
);
