# Phase 1 acceptance

Decision: **PHASE 1 ACCEPTED**

Phase 0 was not reopened. Phase 2 was not started. `data/hospital.db` was not opened for writing. It is still 569344 bytes, version 1, with no checksum column.

The HTTP matrix ran against a throwaway PostgreSQL database created for the run and dropped afterward. No `aipf%` database remains. The seed password and database URL were not written into the repository, the audit log, or this report.

## A–O

| Item | Result | Evidence |
| --- | --- | --- |
| A. Identity schema | PASS | `users.password_hash` is the only password column. `last_login_at` is set on login. Sessions store a SHA-256 digest, not the bearer. `user_roles`, `role_permissions`, and `sessions` have foreign keys. `users_active_check` exists on PostgreSQL. |
| B. Permissions, not role names | PASS | `permit()` no longer treats the role name `admin` as allow-all. Removing `user.manage` from the admin role made the director's staff list return 403. Frontend `can()` checks permissions only. |
| C. Seeded roles are defaults | PASS | Hospital roles are rows in `ROLE_MATRIX`, applied by seed and by `ensure_default_grants` when roles already exist. Changing the doctor role's permissions changed access on the next request. |
| D. Login, disable, session, expiry | PASS | Bad password and a disabled account return the same 401. Disable revokes sessions. Logout rejects the old bearer. A session whose `expires_at` is in the past is rejected. |
| E. Server authorization | PASS | Every non-public API requires a session before the handler runs. Sensitive routes name a permission. See the catalog below. |
| F. Record scope | PASS | Doctor Anita could read her assigned patient and not Rajesh Sharma's chart, queue, encounter, consultation, invoice list, or document. Reception could open the document. Pharmacy's `patient.view_all` did not open it. |
| G. Admin workflows are gated | PASS | Staff create, disable, password reset, and role-permission changes require `user.manage` or `role.manage`. The other five desks received 403 on `/api/users`. |
| H. Audit without secrets | PASS | Login success, login failure, logout, user create, user update, user disable, password change, password reset, role permission change, authorization denial, record denial, and queue denial were present. The password and bearer were absent from audit text. |
| I. 401 / 403 / 404 | PASS | No session is 401. A missing permission is 403. A patient or document outside scope is 404 and does not include the patient's name. |
| J. Frontend is UX only | PASS | Navigation and routes are hidden by permission. A 401 clears the session. A 403 raises a toast. No browser was driven; `tests/test_phase1.py` asserts those source behaviors. |
| K. Direct API matrix | PASS | Administrator, doctor, receptionist, pharmacist, lab, and billing were called over HTTP. 105 checks, 0 failed. |
| L. `tests/test_phase1.py` | PASS | Static scan and the HTTP matrix both passed. |
| M. Regression | PASS | `py_compile` passed. `tests/test_flows.py`, `tests/test_phase0.py`, and `tests/test_phase1.py`: 16 passed. `python3 -m aipf.secret_scan` passed. |
| N. Real server | PASS | `python -m aipf.server` served the matrix on port 8794 against throwaway PostgreSQL. The process was stopped and the database dropped. |
| O. Bypass and secret search | PASS | No `admin` role-name allow-all remains in backend or frontend. Anonymous routes are branding, empty account hints, and login. Secret scan passed. |

## Record scope

Permissions decide the action. These rules decide the record. Role names are not consulted.

- `patient.view_all` may read every patient. Reception, pharmacy, billing, nursing, laboratory, and the administrator role receive it. A doctor does not.
- Without that permission, a patient is visible only through a clinical link: encounter doctor, queue doctor, admission doctor, operating surgeon, or prescribing doctor. A miss is 404.
- `document.view_all` may open any file. Reception and the administrator role receive it. `patient.view_all` does not. Anyone else may open a file they uploaded, or a file for a clinically linked patient.
- Without `queue.view_all`, queue read and queue status changes are limited to the caller's own doctor id. A cross-doctor request is 403.
- Without `consultation.manage_all`, a consultation or prescription can be written only on the caller's own encounter.

## Protected endpoints

Public, no session: `GET /api/public/branding`, `GET /api/public/accounts`, `GET /api/public/logo`, `POST /api/auth/login`.

Special cases, still authorized in the handler: `GET /api/events` requires a session and drops events that carry a `patient_id` outside scope. `GET /api/documents/:id/file` requires `document.view` and the document rule. `POST /api/branding/logo` requires `config.manage`.

Signed-in, no extra permission, because every desk needs them and they are not another patient's chart: `GET /api/auth/me`, `POST /api/auth/logout`, `POST /api/auth/password`, `POST /api/auth/stream-ticket`, `GET /api/dashboard`, `GET /api/search`, `GET /api/onboarding`, `GET /api/doctors`, `GET /api/services`, `GET /api/lab/tests`, `GET /api/master/:type`, `GET /api/hospital`, `GET /api/notifications/mine`, `GET /api/notifications`, `POST /api/notifications/:id/read`, `GET /api/templates`. Dashboard money and the global queue are omitted without the matching permission. Search and clinical lists are record-scoped.

| Permission | Endpoints |
| --- | --- |
| patient.view | `GET /api/patients`, `GET /api/patients/by-phone`, `GET /api/patients/:id`, `GET /api/patients/:id/timeline` |
| patient.create | `POST /api/patients` |
| patient.edit | `PATCH /api/patients/:id` |
| opd.view | `GET /api/opd/types`, `GET /api/opd/valid`, `GET /api/opd/:id` |
| opd.create | `POST /api/opd` |
| opd.assign | `POST /api/opd/:id/assign` |
| queue.view | `GET /api/queue` |
| queue.manage | `POST /api/queue/:id/status` |
| consultation.create | `POST /api/consultations` |
| prescription.view | `GET /api/prescriptions/:id`, `GET /api/prescriptions/:id/pdf` |
| prescription.create | `POST /api/prescriptions`, `PUT /api/prescriptions/:id`, `POST /api/prescriptions/:id/finalize`, `GET /api/formulary` |
| pharmacy.view | `GET /api/pharmacy/queue`, `GET /api/pharmacy/lookup` |
| pharmacy.dispense | `POST /api/pharmacy/dispense` |
| inventory.view | `GET /api/inventory/products`, `GET /api/inventory/products/:id`, `GET /api/inventory/ledger`, `GET /api/inventory/alerts`, `GET /api/inventory/reconcile/:id` |
| inventory.edit | `POST /api/inventory/products`, `PATCH /api/inventory/products/:id`, `POST /api/inventory/batches` |
| inventory.adjust | `POST /api/inventory/movements` |
| lab.view | `GET /api/lab/orders`, `GET /api/lab/orders/:id` |
| lab.order | `POST /api/lab/orders` |
| lab.result | `POST /api/lab/orders/:id/status`, `POST /api/lab/items/:id/result` |
| billing.view | `GET /api/invoices`, `GET /api/invoices/:id`, `GET /api/invoices/:id/document`, `GET /api/deposits` |
| billing.create | `POST /api/invoices`, `POST /api/invoices/:id/items`, `DELETE /api/invoice-items/:id`, `POST /api/invoices/:id/discount`, `POST /api/invoices/:id/payments`, `POST /api/invoices/:id/deposit`, `POST /api/deposits` |
| billing.finalize | `POST /api/invoices/:id/finalize`, `POST /api/invoices/:id/adjust` |
| billing.refund | `POST /api/invoices/:id/refund`, `POST /api/invoices/:id/void` |
| billing.print | `GET /api/invoices/:id/pdf` |
| bed.view | `GET /api/beds` |
| bed.manage | `POST /api/beds/:id/status` |
| admission.view | `GET /api/admissions`, `GET /api/admissions/:id` |
| admission.manage | `POST /api/admissions`, transfer, charges, bed-day, discharge |
| ot.view | `GET /api/ot`, `GET /api/ot/:id` |
| ot.manage | `POST /api/ot`, `POST /api/ot/:id`, `POST /api/ot/:id/notes` |
| document.view | `GET /api/documents`, `GET /api/documents/:id/file` |
| document.upload | `POST /api/documents` |
| document.deactivate | `POST /api/documents/:id/deactivate` |
| master.manage | master, service, OPD type, lab test, ward, room, and bed writes |
| user.manage | `GET/POST /api/users`, `PATCH /api/users/:id` |
| role.manage | `GET /api/roles`, `PUT /api/roles/:code/permissions` |
| config.manage | hospital, config, integrations, backup settings, clear sample, logo upload |
| whatsapp.configure | WhatsApp settings, templates, connection actions |
| whatsapp.send | send-test, notification retry and cancel |
| leads.view | `GET /api/leads`, lead connection test |
| leads.manage | lead writes, sync, archive |
| health.view | `GET /api/system/health`, `GET /api/system/health/:name` |
| backup.view | backup list, settings, verify |
| backup.create | `POST /api/backups` |
| backup.restore | restore and delete |
| report.view | daily and pharmacy reports |
| report.export | `GET /api/reports/export` |
| audit.view | `GET /api/audit`, `GET /api/logs` |

`patient.view_all`, `document.view_all`, `queue.view_all`, and `consultation.manage_all` are scope permissions. They are not separate routes.

## Non-blocking notes

- Events that do not carry `patient_id`, such as an invoice update that carries only an invoice id, are still delivered to any signed-in stream. The stream credential is a 90-second ticket, not the desk bearer.
- Signed-in reference reads listed above do not have their own permission code. They do require a session.
- No browser was driven. The frontend checks are source assertions.
- Ruff and mypy were not run. They are still not installed.
- Finalized-invoice immutability remains application-enforced, as in Phase 0.
- The live SQLite file was not migrated. A later startup will apply `0004_iam_security.sql` and, on PostgreSQL, `0005_users_active_check.postgres.sql`.
