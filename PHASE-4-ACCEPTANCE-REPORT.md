# PHASE 4 ACCEPTED

Gate: real HTTP against a throwaway PostgreSQL database, plus the checks below.
The database URL is not recorded here.

Schema version observed: 18.
Checks passed: 117. Checks failed: 0.

Critical invariants covered: server totals, integer paise, snapshotted rates, draft/finalize/void, no overpay, idempotent payments and refunds, deposits separate from invoice payments, configured modes and tax, invoice numbers, permissions, record scope, audit retention, one PDF document, PostgreSQL checks.
