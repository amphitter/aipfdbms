# API catalog

The source of truth is `build_routes()` in `backend/aipf/server.py`, plus the special handlers in that same file. This list is the catalog as of the current tree. It does not document every request field.

Base URL in development: the desk on port 5173 proxies `/api` to `http://127.0.0.1:8787`. Calling the API directly also works.

## Envelope

Success:

```json
{"ok": true, "data": {}}
```

Failure:

```json
{"ok": false, "error": {"code": "forbidden", "message": "You do not have permission for this action."}}
```

`POST`, `PUT`, `PATCH`, and `DELETE` run inside a transaction unless the route was registered with `tx=False`. A 500 from inside that transaction is rolled back.

## Authentication

| Header or field | Use |
| --- | --- |
| `Authorization: Bearer <token>` | JSON requests |
| `?token=` | Event stream and file downloads, where the browser cannot set a header |
| `X-Workstation` | Stored on the session |
| `Idempotency-Key` or JSON `idempotency_key` | Required by some money and stock writes. Reuse the same key to replay the same result. |
| `Content-Type: application/json` | JSON body |

Public routes, no token:

| Method | Path |
| --- | --- |
| GET | `/api/public/branding` |
| GET | `/api/public/accounts` |
| GET | `/api/public/logo` |
| POST | `/api/auth/login` |

`/api/public/accounts` returns an empty list. It does not publish passwords.

## Special handlers

These are not in `build_routes()`:

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/api/events` | Server-sent events. Requires a token. |
| GET | `/api/public/logo` and `/api/branding/logo` | Current hospital logo, or 404. |
| POST | `/api/branding/logo` | JSON `content_base64`. Requires `config.manage`. |
| GET | `/api/documents/:id/file` | Requires `document.view` and record scope. |

Anything else that is not under `/api` is a static file from `frontend/dist`, or a one-line plain-text notice if that directory does not exist.

## Auth and session

| Method | Path | Permission |
| --- | --- | --- |
| POST | `/api/auth/login` | public |
| POST | `/api/auth/logout` | signed in |
| POST | `/api/auth/stream-ticket` | signed in |
| GET | `/api/auth/stream-ticket` | signed in |
| GET | `/api/auth/me` | signed in |
| POST | `/api/auth/password` | signed in |

## Desk

| Method | Path | Permission |
| --- | --- | --- |
| GET | `/api/dashboard` | signed in |
| GET | `/api/search` | signed in |
| GET | `/api/onboarding` | signed in |
| GET | `/api/doctors` | signed in |
| GET | `/api/staff` | signed in, and `ot.view`, `ot.team.manage`, `ot.manage`, or `user.manage` |
| GET | `/api/notifications/mine` | signed in |
| GET | `/api/notifications` | signed in; another user's rows require `audit.view` |
| POST | `/api/notifications/:id/read` | signed in |
| POST | `/api/notifications/:id/retry` | `whatsapp.send` |
| POST | `/api/notifications/:id/cancel` | `whatsapp.send` |

## Patients, OPD, queue, consultation

| Method | Path | Permission |
| --- | --- | --- |
| GET | `/api/patients` | `patient.view` |
| GET | `/api/patients/by-phone` | `patient.view` |
| POST | `/api/patients` | `patient.create` |
| GET | `/api/patients/:id` | `patient.view` |
| PATCH | `/api/patients/:id` | `patient.edit` |
| GET | `/api/patients/:id/timeline` | `patient.view` |
| GET | `/api/opd/types` | `opd.view` |
| POST | `/api/opd/types` | `master.manage` |
| PATCH | `/api/opd/types/:id` | `master.manage` |
| GET | `/api/opd/valid` | `opd.view` |
| POST | `/api/opd` | `opd.create` |
| POST | `/api/visits` | `opd.create` |
| GET | `/api/opd/:id` | `opd.view` |
| POST | `/api/opd/:id/assign` | `opd.assign` |
| GET | `/api/queue` | `queue.view` |
| POST | `/api/queue/:id/status` | `queue.manage` |
| POST | `/api/consultations` | `consultation.create` |
| POST | `/api/prescriptions` | `prescription.create` |
| PUT | `/api/prescriptions/:id` | `prescription.create` |
| POST | `/api/prescriptions/:id/finalize` | `prescription.create` |
| GET | `/api/prescriptions/:id` | `prescription.view` |
| GET | `/api/prescriptions/:id/pdf` | `prescription.view` |

Patient reads also apply record scope. A doctor without `patient.view_all` receives 404 for a patient they are not linked to.

## Pharmacy and inventory

| Method | Path | Permission |
| --- | --- | --- |
| GET | `/api/formulary` | `prescription.create` |
| GET | `/api/pharmacy/queue` | `pharmacy.view` |
| GET | `/api/pharmacy/lookup` | `pharmacy.view` |
| POST | `/api/pharmacy/dispense` | `pharmacy.dispense` |
| GET | `/api/inventory/products` | `inventory.view` |
| POST | `/api/inventory/products` | `inventory.edit` |
| PATCH | `/api/inventory/products/:id` | `inventory.edit` |
| GET | `/api/inventory/products/:id` | `inventory.view` |
| POST | `/api/inventory/batches` | `inventory.edit` |
| POST | `/api/inventory/movements` | `inventory.adjust` |
| GET | `/api/inventory/barcode-types` | `inventory.view` |
| POST | `/api/inventory/barcode-types` | `master.manage` |
| POST | `/api/inventory/skus` | `inventory.edit` |
| POST | `/api/inventory/barcodes` | `inventory.edit` |
| POST | `/api/inventory/barcodes/resolve` | signed in |
| POST | `/api/inventory/receive` | `inventory.edit` |
| GET | `/api/inventory/ledger` | `inventory.view` |
| GET | `/api/inventory/alerts` | `inventory.view` |
| GET | `/api/inventory/reconcile/:id` | `inventory.view` |

Dispense requires an idempotency key.

## Laboratory

| Method | Path | Permission |
| --- | --- | --- |
| GET | `/api/lab/tests` | signed in |
| POST | `/api/lab/tests` | `master.manage` |
| PATCH | `/api/lab/tests/:id` | `master.manage` |
| POST | `/api/lab/orders` | `lab.order` |
| GET | `/api/lab/orders` | `lab.view` |
| GET | `/api/lab/orders/:id` | `lab.view` |
| POST | `/api/lab/orders/:id/cancel` | `lab.order.cancel` |
| POST | `/api/lab/orders/:id/samples` | `lab.sample.collect` |
| POST | `/api/lab/samples/:id/reject` | `lab.sample.reject` |
| POST | `/api/lab/samples/:id/receive` | `lab.sample.process` |
| POST | `/api/lab/samples/:id/process` | `lab.sample.process` |
| GET | `/api/lab/queue` | `lab.view` |
| POST | `/api/lab/orders/:id/status` | `lab.result` — direct status jumps are rejected |
| POST | `/api/lab/items/:id/result` | `lab.result` |
| POST | `/api/lab/results/:id/verify` | `lab.result.verify` |
| POST | `/api/lab/results/:id/correct` | `lab.result.correct` |
| POST | `/api/lab/orders/:id/report` | `lab.report.generate` |
| GET | `/api/lab/orders/:id/report` | `lab.report.view` |

Laboratory prices are snapshotted through billing. There is no laboratory payment table.

## Billing

| Method | Path | Permission |
| --- | --- | --- |
| GET | `/api/services` | signed in |
| POST | `/api/services` | `master.manage` |
| PATCH | `/api/services/:id` | `master.manage` |
| GET | `/api/invoices` | `billing.view` |
| POST | `/api/invoices` | `billing.create` |
| GET | `/api/invoices/:id` | `billing.view` |
| GET | `/api/invoices/:id/document` | `billing.view` |
| GET | `/api/invoices/:id/pdf` | `billing.print` |
| POST | `/api/invoices/:id/items` | `billing.create` |
| DELETE | `/api/invoice-items/:id` | `billing.create` |
| POST | `/api/invoices/:id/discount` | `billing.create` |
| POST | `/api/invoices/:id/finalize` | `billing.finalize` |
| POST | `/api/invoices/:id/payments` | `payment.create` |
| POST | `/api/invoices/:id/deposit` | `deposit.allocate` |
| POST | `/api/invoices/:id/refund` | `payment.refund` |
| POST | `/api/invoices/:id/void` | `billing.void` |
| POST | `/api/invoices/:id/adjust` | `financial_adjustment.create` |
| POST | `/api/deposits` | `deposit.create` |
| POST | `/api/deposits/:id/refund` | `payment.refund` |
| GET | `/api/deposits` | `billing.view` |
| GET | `/api/reports/billing` | `billing.report` |

Amounts are integer paise. The server calculates totals. A client-supplied price is not the source of truth.

## IPD

| Method | Path | Permission |
| --- | --- | --- |
| GET | `/api/beds` | `bed.view` or `ipd.bed.view` |
| POST | `/api/beds/:id/status` | `bed.manage` |
| GET | `/api/admissions` | `admission.view` or `ipd.admission.view` |
| POST | `/api/admissions` | `admission.manage` or `ipd.admission.create` |
| GET | `/api/admissions/:id` | `admission.view` or `ipd.admission.view` |
| POST | `/api/admissions/:id/assign` | `admission.manage` or `ipd.bed.assign` |
| POST | `/api/admissions/:id/transfer` | `admission.manage`, `ipd.bed.move`, or `ipd.bed.assign` |
| POST | `/api/admissions/:id/charges` | `admission.manage` or `ipd.admission.manage` |
| POST | `/api/admissions/:id/bed-day` | `admission.manage` or `ipd.admission.manage` |
| POST | `/api/admissions/:id/discharge-pending` | `admission.manage` or `ipd.discharge.finalize` |
| POST | `/api/admissions/:id/cancel` | `admission.manage` or `ipd.admission.create` |
| POST | `/api/admissions/:id/discharge` | `admission.manage` or `ipd.discharge.finalize` |
| POST | `/api/admissions/:id/discharge-document` | `admission.manage`, `ipd.discharge.document`, or `document.upload` |
| GET | `/api/admissions/:id/discharge-document` | `admission.view`, `ipd.admission.view`, or `document.view` |
| POST | `/api/wards` | `master.manage` |
| PATCH | `/api/wards/:id` | `master.manage` |
| POST | `/api/rooms` | `master.manage` |
| POST | `/api/beds` | `master.manage` |

## Operation theatre

| Method | Path | Permission |
| --- | --- | --- |
| GET | `/api/ot` | `ot.view` |
| POST | `/api/ot` | `ot.manage` — older notes-path create |
| GET | `/api/ot/theatres` | `ot.view` |
| POST | `/api/ot/theatres` | `ot.theatre.manage` or `ot.manage` |
| PUT | `/api/ot/theatres/:id` | `ot.theatre.manage` or `ot.manage` |
| GET | `/api/ot/procedures` | `ot.view` |
| POST | `/api/ot/procedures` | `ot.procedure.manage` or `ot.manage` |
| PUT | `/api/ot/procedures/:id` | `ot.procedure.manage` or `ot.manage` |
| GET | `/api/ot/checklist` | `ot.view` |
| POST | `/api/ot/checklist` | `ot.theatre.manage` or `ot.manage` |
| POST | `/api/ot/requests` | `ot.request` or `ot.manage` |
| GET | `/api/ot/:id` | `ot.view` |
| POST | `/api/ot/:id` | `ot.manage` |
| POST | `/api/ot/:id/notes` | `ot.manage` |
| POST | `/api/ot/:id/approve` | `ot.approve` or `ot.manage` |
| POST | `/api/ot/:id/schedule` | `ot.schedule` or `ot.manage` |
| POST | `/api/ot/:id/reschedule` | `ot.schedule` or `ot.manage` |
| POST | `/api/ot/:id/cancel` | `ot.cancel` or `ot.manage` |
| POST | `/api/ot/:id/postpone` | `ot.cancel`, `ot.schedule`, or `ot.manage` |
| POST | `/api/ot/:id/team` | `ot.team.manage` or `ot.manage` |
| POST | `/api/ot/:id/preop` | `ot.preop.record` or `ot.manage` |
| POST | `/api/ot/:id/start` | `ot.start` or `ot.manage` |
| POST | `/api/ot/:id/intraop` | `ot.intraop.record` or `ot.manage` |
| POST | `/api/ot/:id/recovery` | `ot.complete` or `ot.manage` |
| POST | `/api/ot/:id/complete` | `ot.complete` or `ot.manage` |
| POST | `/api/ot/:id/postop` | `ot.postop.record` or `ot.manage` |
| POST | `/api/ot/:id/charge` | `ot.charge.post` or `ot.manage` |
| POST | `/api/ot/:id/report` | `ot.report.generate`, `ot.manage`, or `document.upload` |
| GET | `/api/ot/:id/report` | `ot.view` or `document.view` |
| POST | `/api/ot/:id/links` | `ot.request`, `ot.manage`, or `ot.intraop.record` |

There is no theatre delete route. A charge creates a billing invoice line. It does not create an OT payment.

## Documents and master data

| Method | Path | Permission |
| --- | --- | --- |
| GET | `/api/documents` | `document.view` |
| POST | `/api/documents` | `document.upload` |
| POST | `/api/documents/:id/deactivate` | `document.deactivate` |
| GET | `/api/master/:type` | signed in |
| POST | `/api/master/:type` | `master.manage` |
| PATCH | `/api/master/:type/:id` | `master.manage` |
| POST | `/api/master/:type/:id/deactivate` | `master.manage` |

## Staff, hospital, integrations

| Method | Path | Permission |
| --- | --- | --- |
| GET | `/api/users` | `user.manage` |
| POST | `/api/users` | `user.manage` |
| PATCH | `/api/users/:id` | `user.manage` |
| GET | `/api/roles` | `role.manage` |
| PUT | `/api/roles/:code/permissions` | `role.manage` |
| GET | `/api/hospital` | signed in |
| PUT | `/api/hospital` | `config.manage` |
| GET | `/api/config` | `config.manage` |
| POST | `/api/admin/load-demo` | `config.manage` |
| POST | `/api/admin/clear-sample` | `config.manage` |
| GET | `/api/integrations` | `config.manage` |
| PUT | `/api/integrations/whatsapp` | `whatsapp.configure` |
| POST | `/api/integrations/whatsapp/test` | `whatsapp.configure` |
| POST | `/api/integrations/whatsapp/qr` | `whatsapp.configure` |
| POST | `/api/integrations/whatsapp/reconnect` | `whatsapp.configure` |
| POST | `/api/integrations/whatsapp/disconnect` | `whatsapp.configure` |
| POST | `/api/integrations/whatsapp/send-test` | `whatsapp.send` |
| POST | `/api/whatsapp/messages` | `whatsapp.send` |
| POST | `/api/whatsapp/documents` | `whatsapp.send` |
| PUT | `/api/integrations/leads` | `leads.manage` |
| POST | `/api/integrations/leads/test` | `leads.view` |
| POST | `/api/leads/sync` | `leads.manage` |
| GET | `/api/leads` | `leads.view` |
| POST | `/api/leads` | `leads.manage` |
| POST | `/api/leads/:id/archive` | `leads.manage` |
| GET | `/api/templates` | signed in |
| POST | `/api/templates` | `whatsapp.configure` |
| PUT | `/api/templates/:id` | `whatsapp.configure` |

## Health, backup, reports, audit

| Method | Path | Permission |
| --- | --- | --- |
| GET | `/api/system/health` | `health.view` |
| GET | `/api/system/health/:name` | `health.view` |
| GET | `/api/backups` | `backup.view` |
| GET | `/api/backups/settings` | `backup.view` |
| PUT | `/api/backups/settings` | `config.manage` |
| POST | `/api/backups` | `backup.create` — 501 on PostgreSQL |
| POST | `/api/backups/:id/verify` | `backup.view` |
| POST | `/api/backups/:id/restore` | `backup.restore` — body `confirm` must be `RESTORE AIPF`; 501 on PostgreSQL |
| DELETE | `/api/backups/:id` | `backup.restore` |
| GET | `/api/reports/daily` | `report.view` |
| GET | `/api/reports/pharmacy` | `report.view` |
| GET | `/api/reports/export` | `report.export` |
| GET | `/api/audit` | `audit.view` |
| GET | `/api/logs` | `audit.view` |

There is no `DELETE /api/audit`.
