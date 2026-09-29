# AIPF requirement status

Date: 2026-09-27  
Method: repository inspection. No feature was treated as complete because a table, route, or screen exists.  
This file is the section-34 audit. It is not a claim that the hospital system is operational.

Statuses: `COMPLETE` / `PARTIAL` / `MISSING` / `BROKEN`.

Nothing in the current tree is `COMPLETE` under the rule that requires schema, constraints, service, API, authorization, validation, transaction, audit, frontend, errors, realtime where required, tests, end-to-end proof, and production-safe behavior.

## A. Current architecture

```
Browser (React 19, Vite, TypeScript, Zustand, one custom stylesheet)
    |  HTTP JSON + in-process SSE. Token in Authorization, also accepted in the query string.
    v
Python stdlib ThreadingHTTPServer  (backend/aipf/server.py, 0.0.0.0:8787)
    |  SQL is written inside clinical.py, pharmacy.py, billing.py, wards.py, system.py, core.py, notify.py
    v
SQLite file data/hospital.db  (WAL, foreign_keys pragma ON, zero REFERENCES)
    + local files under data/documents, data/backups, data/branding
    + in-memory event hub (events.py)
    + one daemon thread for WhatsApp retry and the backup clock
```

Not present: FastAPI, Go, PostgreSQL, a repository layer, a StorageProvider, a WebSocket gateway, a migration history beyond version 1 `executescript`.

Clients do not open the database. That boundary is real.

## B. Current modules

| Module | Files | What the code actually does |
| --- | --- | --- |
| HTTP | `server.py` | Route table, session lookup, per-request SQLite connection, `BEGIN IMMEDIATE` on mutations |
| Identity | `core.py` | PBKDF2 passwords, roles, permissions, audit insert, sequences, master lists |
| Clinical | `clinical.py` | Patient, encounter, queue, consultation, prescription |
| Pharmacy | `pharmacy.py` | Product, batch, movement, dispense |
| Billing | `billing.py` | Invoice, payment, deposit, PDF payload |
| Wards | `wards.py` | Beds, admission, OT, lab orders, document files |
| System | `system.py` | Health, backup zip, leads, reports |
| Notify | `notify.py` | In-app rows, OpenWA provider, retry |
| PDF | `pdf.py` | Hand-written PDF 1.4 |
| Realtime | `events.py` | Process-local queue fan-out |
| Seed | `seed.py` | Demo hospital day |
| Tests | `tests/test_flows.py` | Eight function checks, not an end-to-end desk run |

## C. Database schema

`backend/aipf/schema.sql`, 41 tables. Version row is `1`. `data/hospital.db` exists (about 565 KB, 9 patients, 10 users) and was not modified for this audit.

Tables separate patient, encounter, admission, invoice, prescription, dispense line, product, batch, stock movement, payment, document metadata, lead, and OT case.

Missing from the schema itself:

- No `REFERENCES` / `FOREIGN KEY` except a check that `hospital_profile.id = 1` and `sequences` is not that kind of constraint
- No partial unique index for one open admission
- No payment idempotency key
- No supplier, purchase invoice, or goods-receipt tables
- Quantity columns are `REAL`
- `schema_migrations` has no checksum
- Migration v1 uses `executescript`, which can commit before the version row is written

## D. Existing APIs

Authenticated JSON routes exist for patients, OPD, queue, consultation, prescription, pharmacy, inventory, lab, invoices, deposits, beds, admissions, OT, documents, masters, users, roles, hospital profile, integrations, notifications, health, backups, reports, and audit.

Unauthenticated: `GET /api/public/branding`, `GET /api/public/accounts` (returns install passwords while `show_install_hints=1`), `POST /api/auth/login`.

Special paths outside the route table: SSE `/api/events`, logo, document file download. Those accept `?token=`.

`GET /api/deposits` runs SQL inside `server.py`.

## E. Existing frontend routes

`App.tsx`: `/`, `/register`, `/patients`, `/patients/:id`, `/queue`, `/doctor`, `/consult/:id`, `/pharmacy`, `/inventory`, `/lab`, `/billing`, `/billing/:id`, `/beds`, `/admissions`, `/admissions/:id`, `/ot`, `/ot/:id`, `/leads`, `/reports`, `/admin/master`, `/admin/staff`, `/admin/branding`, `/admin/integrations`, `/admin/health`, `/admin/backups`, `/admin/audit`, `/setup`, `/help`.

The nav hides links the role cannot see. The API is the only authorization that counts, and it is incomplete.

## F. Existing tests

`backend/tests/test_flows.py`:

- amount in words for 109987 rupees
- shared phone does not overwrite Rajesh Sharma
- OPD card fee then waiver, second encounter id
- dispense reduces stock, billed rate stays 150 paise, second full dispense fails
- two threads against quantity 1, one failure (SQLite writer lock)
- payment, reprint does not change invoice number, adjustment revision
- occupied bed refused, OT unsuccessful outcome
- reception cannot `backup.restore`

Not covered: PostgreSQL, foreign keys, queue authorization bypass, idempotent payment, refund link, multi-page PDF, record-level document access, backup restore while the server is stopped, WhatsApp, leads, health truthfulness.

## G. Existing integrations

- OpenWA: provider class and admin routes. Core billing does not wait on it. Not a working hospital integration until a host is configured and a live send succeeds.
- Website leads: local rows plus optional Mongo sync. Registration does not depend on it.
- Cloud backup: signed S3 PUT and a download checksum check. Not proven against a bucket.

## H. Existing migrations

`apply_migrations` in `db.py`. If `schema_migrations` max version is below 1, it runs `schema.sql` with `executescript` and inserts version 1. No later migration. No checksum. Not safe to describe as a production migrator.

## I. Existing security controls

- Password hash is PBKDF2-SHA256, compared with HMAC
- Bearer session, 16-hour sliding expiry, logout revokes the token
- `permit()` on most mutations
- Document bytes stored as `{uuid}.ext` under the documents directory; path escape is rejected
- Secrets masked in the config JSON response
- Unexpected exceptions return a generic 500

Not production-safe:

- `GET /api/public/accounts` publishes install passwords
- Session token is accepted from the query string and stored in `sessionStorage`
- `list_queue` applies a caller-supplied `doctor_id` before the `queue.view_all` check
- `patient.view` and `document.view` are global, not record-scoped
- No login throttle
- CORS reflects any Origin
- Backup zip contains `hospital.db`, which contains password hashes and integration secrets
- Reads of charts, documents, and PDFs are not audited

## J. Partial implementations

See the map below. The short version: the desks call real APIs and the domain tables are split correctly. Constraints, record scope, idempotency, packaging, purchase documents, production realtime, encrypted backup, and the PDF layout are not done. The engine is still SQLite behind inline SQL.

## Requirement map

| Requirement | Status | Evidence |
| --- | --- | --- |
| Patient ≠ encounter ≠ admission ≠ invoice | PARTIAL | Separate tables and id sequences. No foreign keys. |
| Phone ≠ identity | PARTIAL | `matches_by_phone` plus `confirm_new`. Test covers the Sharma family. No database unique rule, because a shared phone must not be unique. Service behavior holds. |
| Prescription ≠ dispense | PARTIAL | Finalize does not call stock movement. Dispense writes `dispense_lines`. |
| Product ≠ batch ≠ movement | PARTIAL | Three tables. `qty_on_hand` is updated by reading then writing. No database equality constraint. |
| Invoice ≠ payment | PARTIAL | Separate rows. Totals are cached by `recalc`, not checked by the database. |
| Finalized invoice immutable | PARTIAL | Line delete after finalize is refused. Adjustment writes a revision. Refund does not set `reverses` / `reversed_by`. |
| Document metadata ≠ bytes | PARTIAL | Row plus file. Access is not record-scoped. |
| Lead ≠ patient | PARTIAL | Separate table. Convert is two HTTP calls. |
| External failure does not block core work | PARTIAL | WhatsApp queue is skipped unless enabled. Cloud failure keeps the local zip. Not proven against a live outage. |
| PostgreSQL production database | PARTIAL | Engine, schema, and tests exist. The existing file still opens as SQLite until `AIPF_DATABASE_URL` is set. |
| SQLite only as a fallback behind one data API | PARTIAL | `connect()` chooses the engine. Most SQL is still written in the service modules and translated. |
| Repository / data-access boundary | PARTIAL | Stock deduction and the deposits query moved out of the HTTP file. Other SQL is still inline. |
| Foreign keys, checks, partial unique indexes | PARTIAL | PostgreSQL baseline adds foreign keys and payment/deposit amount checks. Open-admission unique index is migration v2 on both engines. SQLite cannot add foreign keys to the existing file without a rebuild, so the fallback does not enforce them. |
| Migration runner (version, once, transactional, checksum, clear failure) | PARTIAL | Versions 1 and 2, checksum, rollback on failure, repeat run is a no-op. Tested. Not a complete history of every later change. |
| Go rewrite | NOT STARTED | Correctly not started. Do not start it in this phase. |
| Patient register, search, timeline, documents | PARTIAL | APIs and screens exist. No family-link table. Documents are not access-scoped. |
| One safe reception transaction for register + OPD | BROKEN | Two HTTP calls. The second can fail after the patient row exists. |
| OPD fee, validity, doctor, queue | PARTIAL | Server decides the waiver when `use_opd_id` is sent. Test covers the 5-day card. |
| Doctor cannot read another queue by changing `doctor_id` | PARTIAL | Server rejects the cross-doctor request with 403 and writes `queue_denied`. Tested. Queue realtime and record scope are still incomplete. |
| Consultation history not silently overwritten | BROKEN | `save_consultation` updates the same row. Audit stores diagnosis text, not the full note history. |
| Structured prescription, draft/final, no stock change on finalize | PARTIAL | Fields exist. Allergy hard-stop does not. |
| Pharmacy hierarchy including packaging conversion | PARTIAL | `packaging_json` is stored and not applied. |
| Supplier, purchase invoice, goods receipt | MISSING | `PURCHASE` is only a movement type. |
| Barcode, batch, expiry, FEFO suggestion, substitution reason | PARTIAL | Expired batch refused unless config allows it. FEFO is a suggestion. Wrong product without `substituted: true` is accepted. |
| Stock formula and movement columns | PARTIAL | Movement types exist. Reconciliation is a query, not a constraint. |
| Atomic stock deduction on PostgreSQL | PARTIAL | `UPDATE ... WHERE qty_on_hand + delta >= 0` runs before the movement insert. Two-thread test passed on SQLite and PostgreSQL. Packaging, purchase documents, and the rest of pharmacy are not done. |
| Billing: multi-pay, deposit, discount, due, refund, adjustment, rate snapshot | PARTIAL | Implemented in Python. Overpayment is accepted and due is clamped to 0. |
| Server-calculated totals, frontend totals ignored | PARTIAL | `recalc` ignores client totals. The client still sends the payment amount, and the server does not reject an amount above due. |
| Idempotency keys on payments | MISSING | A retry inserts another payment row. |
| Refund references the payment it reverses | BROKEN | `refund()` inserts `kind=REFUND` and leaves `reverses` null. `recalc` ignores rows where `reverses` is set, so the column and the code disagree. |
| PDF production layout, pagination, no clipping, visual check | PARTIAL | Real text operators. Right edge is `len * size * 0.52`. Long lines are ellipsized. Page 2 does not repeat headings. Tests only check `%PDF`. |
| IPD admission, bed, transfer, charges, discharge summary | PARTIAL | Service refuses an occupied bed. No unique index. Bed master UI does not administer wards. |
| No double bed occupancy, transactional bed move | PARTIAL | Same request transaction. Not a constraint. |
| OT separate entity, outcomes including unsuccessful | PARTIAL | Test covers unsuccessful. Charges are manual. |
| Lab order through verified report | PARTIAL | Order, status, result text. No sample-collection desk. Finalize looks for the text `[PRICE PENDING]`, not `price_pending`. |
| Documents: checksum, type, size, safe name | PARTIAL | MIME is the declared type, not sniffed, except the logo. |
| Record-level document and patient authorization | MISSING | Any `document.view` user can open any document id. |
| Department and doctor scope | MISSING | |
| Audit of view, export, download, print, login | PARTIAL | Login, logout, and many mutations write audit rows. Chart view, PDF download, and document open do not. |
| Realtime without full page reload, reconnect-safe, multi-process | PARTIAL | SSE exists. `bump()` refetches the page query. Hub is in-process. Missed events are not replayed. |
| Backup: Postgres, documents, encryption, checksum, restore while stopped | PARTIAL | Local zip, SHA-256, retention by count. Secrets remain inside the database file. Restore runs while the process can still write. No `pg_dump`. No encryption. |
| StorageProvider | MISSING | `wards.store_document` writes a filesystem path. |
| Master data, no hardcoded payment modes | PARTIAL | Masters are rows. `money.tsx` hardcodes Cash, UPI, Card, Bank transfer, Cheque. |
| Health measures real state | PARTIAL | `SELECT 1`, disk, memory, PDF header, storage probe are real. Realtime is HEALTHY at zero clients. "Database pool" and "Configured ports" are sentences. |
| End-to-end scenario of 37 steps | MISSING | Eight unit-style checks only. |
| Definition of done for any module | MISSING | No module meets the 17-item gate. |

## What must not be called done

No module meets the definition of done. The desk is not an operational hospital system.

## Implementation progress after the audit

Phase 0 was started. It is not done. Phase 1 was started only for two security defects. Phase 2 has not been started.

Done in code, with tests:

- `AIPF_DATABASE_URL` selects PostgreSQL. Unset keeps SQLite as the developer fallback. `data/hospital.db` was not rewritten in this session. A copy of it accepted migration v2 (checksum column and indexes) without losing its 9 patients. The next server start will apply that same additive migration to the live file.
- Migration runner records version, name, checksum, and time. A failed migration rolls back and does not record the version. Running it twice stays at version 2.
- PostgreSQL baseline is compiled from `schema.sql` plus foreign keys. A test inserted an encounter for a missing patient and the database rejected it. Seed data that pointed a bed at an admission before the admission existed was reordered; that was a real integrity bug, not a workaround.
- One open admission per patient is a partial unique index on both engines.
- Stock deduction is `UPDATE batches SET qty_on_hand = qty_on_hand + ? WHERE id = ? AND qty_on_hand + ? >= -0.0001`. The movement row is inserted only if that update changes one row. Two pharmacists racing for the last sachet: one success, one failure, quantity 0, one movement. Proven on PostgreSQL, not only on the SQLite writer lock.
- `python -m aipf.pgcopy` copies SQLite into an empty migrated PostgreSQL database and refuses if the target already has patients. Tested. It does not delete the SQLite file.
- A doctor requesting another doctor's queue by `doctor_id` now gets 403, and the attempt is audited. Install passwords are not returned by `/api/public/accounts` unless `AIPF_DEV_HINTS=1`.
- PostgreSQL file-copy backup and restore return "not implemented" instead of zipping the wrong file. Health no longer marks the database pool, port scan, or realtime hub HEALTHY just because an object exists.

Still incomplete, and not hidden:

- Repository boundary covers stock and deposits only. Clinical, billing, wards, and system SQL are still in the service modules.
- SQLite fallback does not enforce foreign keys.
- No idempotency key, no payment reversal link, no overpayment rejection.
- Register and OPD are still two HTTP calls.
- Consultation still overwrites one row.
- Record-level patient and document authorization is not implemented.
- Session token is still accepted from the query string.
- PDF pagination and clipping are unchanged.
- Packaging, suppliers, purchase invoices, and goods receipts are not implemented.
- Realtime is still an in-process hub. A page event still refetches.
- PostgreSQL backup is `pg_dump` not implemented. Restore-while-stopped is not implemented. Secrets can still sit inside a SQLite backup zip.
- The 37-step end-to-end scenario was not run.
- Go was not started. That remains a later packaging decision.

Tests run in this session: `backend/tests/test_flows.py` and `backend/tests/test_phase0.py`. Both passed, including the PostgreSQL constraint, copy, and stock-race checks. The hospital server was not started.
