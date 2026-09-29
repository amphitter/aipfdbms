# Phase 0 acceptance report

Date: 2026-09-27. Gate rerun after blocker remediation. Evidence is from the filesystem, a throwaway PostgreSQL database, and a real `python -m aipf.server` process. The live file `data/hospital.db` was not opened for writing.

Decision: **PHASE 0 ACCEPTED**

No Phase 1 work was started.

## A. PostgreSQL — PASS

- `AIPF_ENV=production` with no database URL raises `RuntimeError` and does not open SQLite.
- `AIPF_ENV=production` with a `sqlite:///` URL raises and does not open SQLite.
- A PostgreSQL URL pointing at port 1 raises `RuntimeError` (`PostgreSQL is configured but unavailable`). The message states SQLite was not used. No SQLite connection was returned.
- A reachable PostgreSQL URL returns dialect `postgres`.
- The real server was started with `AIPF_ENV=production` and a throwaway PostgreSQL URL. `GET /api/system/health` returned 200 and the Database check was `HEALTHY`.

## B. Migration System — PASS

Files discovered on disk:

- `backend/aipf/migrations/0001_baseline.sqlite.sql` (sha256 `41ad40bfc193`)
- `backend/aipf/migrations/0001_baseline.postgres.sql` (sha256 `bd5d711bc6a6`)
- `backend/aipf/migrations/0002_operational_indexes.sql` (sha256 `7923f2ffebf0`)
- `backend/aipf/migrations/0003_idempotency_and_lab_results.sql` (sha256 `1bb7e39fd16b`)

On a fresh PostgreSQL database, `apply_migrations` returned 3, then 3 again. `applied_at` did not change on the second run. Each stored checksum matched the file hash.

After `UPDATE schema_migrations SET checksum='tampered' WHERE version=1`, startup raised a checksum mismatch and left the stored value `tampered`. It did not rewrite the checksum and did not re-run the migration.

`apply_statements` with invalid SQL raised and left zero rows for version 99.

A copy of `data/hospital.db` (not the live file) had version 1 and no checksum column. The runner added the column, left the version-1 checksum null, applied versions 2 and 3, and kept all 9 patients. The live file is still 569344 bytes, version 1, name `initial hospital schema`, `applied_at=2026-09-27T01:58:46+05:30`, 9 patients, and still has no checksum column.

## C. Repository Boundary — PASS

`clinical.py`, `pharmacy.py`, `billing.py`, `wards.py`, `system.py`, `core.py`, `notify.py`, `seed.py`, and `server.py` contain no direct SQL call sites.

Repository modules present and used: `patients.py`, `encounters.py`, `billing.py`, `payments.py`, `pharmacy.py`, `inventory.py`, `lab.py`, `ipd.py`, `ot.py`, `documents.py`, `users.py`, `sessions.py`, `audit.py`, `masters.py`, `notifications.py`, `wards.py`.

## D. Database Constraints — PASS

On PostgreSQL:

- Inserting an encounter for patient `NO-SUCH` raised `ForeignKeyViolation`.
- A second open admission (`ADMITTED` then `REQUESTED`) for the same patient raised `UniqueViolation` on `uq_admission_one_open`. The service also rejected a second `admit` with “This patient already has an open admission.”
- `payments.amount_paise = 0` raised `CheckViolation`. The service also rejected a non-positive payment.
- `lab_results` exists with id, lab order item, value, units, reference range, status, entered by/at, finalized by/at, and document link. A finalized result row was written (`13.2 g/dL`, range `12-15`).
- `idempotency_keys` exists.
- Key id, name, patient, invoice number, and amount columns checked in `information_schema` are `NOT NULL` (11 columns).

Finalized-invoice immutability was exercised: adding a line to a finalized invoice is rejected by the service and by `POST /api/invoices/:id/items` (HTTP 400).

## E. Transaction Safety — PASS

Inside `db.Tx` on PostgreSQL, committed rows `a` and `b` remained. A duplicate primary-key insert in a later transaction rolled back; row `c` was absent.

## F. Atomic Stock — PASS

On PostgreSQL batch `BAT-PR-ORS`, two concurrent dispense requests for quantity 1 from quantity 1 left quantity `0.0`, one `DISPENSED` movement, and one error. A further dispense of 5 was rejected and wrote no movement.

## G. Payment Idempotency — PASS

Database uniqueness is `idempotency_keys` primary key plus `uq_payments_idempotency`.

- The same key and payload returned the original payment id and did not create a second payment.
- The same key with a different amount returned HTTP 409 and left the payment count at 1.
- Two concurrent identical requests created one payment.
- A refund row’s `reverses` column referenced the original payment id.

The same replay and conflict behavior was confirmed over HTTP, including the `Idempotency-Key` header.

## H. SQLite Fallback Safety — PASS

- Unset `AIPF_DATABASE_URL` raises `RuntimeError` (`Refusing to guess`). It does not open `data/hospital.db`.
- An explicit `sqlite:///` URL opens SQLite.
- Production never opens SQLite, including when the URL is missing, is a SQLite URL, or the PostgreSQL server is down.

## I. StorageProvider — PASS

`StorageProvider` implements `save`, `read`, `delete`, `exists`, and `metadata`. `get_storage()` returns `LocalStorageProvider`.

Those methods were called. Document upload and download go through the provider: a stored text file read back as `gate-document`, and an HTTP PNG upload read back with a PNG signature.

## J. Security Foundation — PASS

`python -m aipf.secret_scan` passed. Install passwords are not in `server.py`, `seed.py`, `README.md`, the frontend, or tests. Seeded passwords come from `AIPF_SEED_PASSWORD` and are not written into the repository. Tests create a temporary password in the process environment. `GET /api/public/accounts` returns `{items: []}`.

## K. HTTP/API Verification — PASS

`python -m aipf.server` was started against throwaway PostgreSQL with `AIPF_ENV=production` (pid 5525, port 8791). It was stopped after the checks. The process is not still running, and the throwaway database was dropped.

- Unauthenticated `GET /api/patients`: 401
- Invalid JSON login: 400
- Login: 200 with a token
- `GET /api/system/health`: 200, Database `HEALTHY`
- Authenticated patient create: 200
- Missing patient: 404
- `GET /api/inventory/products`: 200
- Invoice finalize: 200
- Edit of that finalized invoice: 400
- Repeated payment with the same idempotency key: 200 replay
- Same key, different payload: 409
- Document upload and file read: 200
- Public accounts: no passwords

## L. Tests — PASS

- `python3 -m py_compile` on `backend/aipf/*.py`: passed
- `python3 tests/test_flows.py`: `all hospital flow checks passed`
- `python3 tests/test_phase0.py` with `AIPF_TEST_POSTGRES` set: `phase 0 checks passed`
- Secret scan: passed

Ruff and mypy are not installed. Static lint and type checking were **NOT RUN**. That is recorded under remaining defects and was not treated as a passing check.

## M. Remaining Defects

- No ruff or mypy configuration is installed, so lint and type checks were not run.
- Finalized-invoice immutability is enforced by the billing service and the HTTP API, not by a database trigger. A direct SQL update could still change a finalized row. The application path rejects the edit.
- `data/hospital.db` is still the pre-checksum version 1 file. That was intentional. A copy proved the runner can move it forward without deleting patients and without inventing a checksum for version 1.
- Repository functions are a mechanical extraction of the previous queries. Domain modules no longer contain SQL, but the repository API is not yet a small hand-written set of operations.

None of these failed a Phase 0 blocker.

## N. Phase 0 Decision

**PHASE 0 ACCEPTED**

Phase 1 was not started.
