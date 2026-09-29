# AI-PF ARCHITECTURE AUDIT

Date: 2026-09-27  
Scope: code inspection of the current repository. No new features were added. No rewrite was started. The hospital server was not started for this pass.

This report corrects one assumption before anything else.

The backend is **not FastAPI**. It is Python’s standard-library `http.server.ThreadingHTTPServer` in `backend/aipf/server.py`. There is no `requirements.txt`, no FastAPI app, and no PostgreSQL driver.

Current stack, as it actually exists:

| Layer | What is running | What the specification asked for |
| --- | --- | --- |
| Frontend | React 19, TypeScript, Vite 8, Zustand | React, TypeScript, Vite, Tailwind, Zustand |
| Backend | Python 3 service modules behind stdlib HTTP | Go, Chi-style routing, service + repository |
| Database | SQLite, WAL, file `data/hospital.db` | PostgreSQL on the hospital host, not exposed to clients |
| Realtime | In-process SSE | WebSocket or SSE |
| Documents | Local filesystem | StorageProvider (local / S3 / MinIO) |

Clients do not open the database. That boundary is real. Almost every other production boundary is only partly there.

---

## 1. Current architecture

```
Browser (React)
    |
    |  HTTP JSON + SSE   token in Authorization, also accepted in the query string
    v
ThreadingHTTPServer  (one process, 0.0.0.0:8787)
    |
    +-- route table in server.py
    +-- domain modules (clinical, pharmacy, billing, wards, notify, system)
    |       SQL is written inside those modules
    +-- SQLite connection per request
    +-- in-memory event hub
    +-- daemon thread: WhatsApp retry + backup clock
    +-- files under data/documents, data/backups, data/branding
```

There is **no repository layer**. There is **no storage-provider interface**. WhatsApp has a provider class. Cloud backup is two functions inside `system.py`, not a provider. Business rules live in Python, which is the right place, but they are bound to SQLite SQL and to one process.

Frontend routes are role-filtered in `App.tsx`. Pages call `/api/...`. They do not open SQLite. That part of the specification is met.

Tailwind is not used. Styling is one custom stylesheet. That is a presentation choice, not an architecture defect.

---

## 2. Current implementation status

Classification means: the behaviour exists in code and is wired from UI to API to a table. A table alone is not COMPLETE.

| Module | Status | Evidence |
| --- | --- | --- |
| Frontend shell, login, role nav | PARTIAL | Works as a desk UI. Business rules for phone choice and bill totals are mostly server-side. Some flows are two uncoordinated requests. |
| Authentication | PARTIAL | PBKDF2-SHA256, bearer sessions, 16-hour sliding expiry. Install passwords are published by an unauthenticated endpoint. |
| RBAC | PARTIAL | Roles and permissions exist and most mutations call `permit()`. Enforcement is action-level, not patient-level. One queue bypass is below. |
| Patient | PARTIAL | Register, search, phone match, explicit new-vs-existing, timeline. No family link table. No document-required workflow. |
| OPD / encounter | PARTIAL | Separate encounter id, fee snapshot, validity card, new visit under an old card. Register-then-OPD is not one transaction. |
| Queue / doctor assignment | PARTIAL | Statuses exist. SSE refresh exists. A doctor can request another doctor’s queue by passing `doctor_id`. |
| Consultation | PARTIAL | One editable consultation per encounter. Audit of diagnosis. No structured problem list. |
| Prescription | PARTIAL | Structured lines, draft vs finalized. Not the same record as dispensing. No allergy hard-stop. |
| Pharmacy dispensing | PARTIAL | Batch, expiry block, substitution reason, stock movement, invoice line. Packaging hierarchy is stored and not used. |
| Inventory ledger | PARTIAL | Movement table plus cached `qty_on_hand`. Reconciliation query exists. Purchase is a movement, not a supplier invoice. |
| Laboratory | PARTIAL | Master tests, custom test, order, status, result text, price snapshot. Result file link is a field, not a finished lab desk. |
| Billing | PARTIAL | Draft, items, discount, finalize, multi-pay, deposit, refund, void, adjustment, rate snapshot. See section 6. |
| Payments | PARTIAL | Separate payment rows. No idempotency key. Refund does not point at the payment it reverses. |
| Admissions | PARTIAL | Separate admission id, bed, transfer history, discharge summary, bed-day post. Not a full nursing chart. |
| Beds / wards / rooms | PARTIAL | Board, status, occupy by admission. Ward/room/bed create API exists; the bed UI does not administer the master. |
| OT | PARTIAL | Request, schedule, perform, notes, outcome including unsuccessful/aborted. Fee is optional and manual. |
| Documents | PARTIAL | Metadata plus binary on disk, checksum, type allow-list, path check. Any user with `document.view` can open any document id. |
| PDF | PARTIAL | Custom PDF, real text operators, logo JPEG embed, reprint is a GET. Not proven for long bills. See section 10. |
| Realtime | PARTIAL | SSE exists and is not a one-second poll. It is in-process only. A dropped client misses events until the next one. |
| Notifications | PARTIAL | In-app rows and a WhatsApp queue with retry. Sending works only if OpenWA is configured and reachable. |
| WhatsApp / OpenWA | PARTIAL | Provider abstraction and admin fields. Not a working hospital integration until a real OpenWA host is set. Billing does not wait on it. |
| Website leads | PARTIAL | Local lead rows, archive, manual create. Mongo sync needs `pymongo` and a URI. Hospital registration does not depend on it. |
| Backup | PARTIAL | Local zip of database and documents, checksum, retention, cloud PUT code. See section 11. |
| Restore | PARTIAL | Confirmation phrase, safety zip, file replace. Unsafe while the server is still accepting writes. |
| Health | PARTIAL | Several checks are real probes. A few lines are narrative, not measurements. See section 12. |
| Master data | PARTIAL | Lists, OPD types, services, lab tests are rows. Payment modes on the bill screen are hardcoded. |
| Audit logs | PARTIAL | Important mutations write audit rows. Not every read. Old/new JSON is inconsistent. |
| Configuration | PARTIAL | `app_config` plus hospital profile. Secrets masked on read. They still sit in the SQLite file. |
| Migrations | PARTIAL | Version 1 applies `schema.sql` on startup. No later migrations. `executescript` can commit a partial schema. |
| Tests | PARTIAL | `backend/tests/test_flows.py` covers phone identity, OPD validity, dispense, one concurrency case, payment, bed conflict, OT outcome, one permission denial. It does not cover PDF layout, restore, WhatsApp, or authorization bypasses. |
| Go backend | NOT IMPLEMENTED | |
| PostgreSQL | NOT IMPLEMENTED | |
| Repository layer | NOT IMPLEMENTED | |
| StorageProvider | NOT IMPLEMENTED | Direct filesystem paths. |
| Tauri / one-click installer | NOT IMPLEMENTED | `start-host.sh` only. |
| Excel export | NOT IMPLEMENTED | CSV only. |
| WebSocket | NOT IMPLEMENTED | SSE only. |
| Department-scoped records | NOT IMPLEMENTED | |
| Packaging conversion at dispense | SCHEMA ONLY | `packaging_json` is stored. Dispense quantity is a flat number. |
| Payment reversal link | SCHEMA ONLY | `payments.reversed_by` and `reverses` exist. Refund does not fill them. |
| Foreign keys | NOT IMPLEMENTED | `PRAGMA foreign_keys=ON` is set. The schema defines no `REFERENCES`. |

Nothing in this table is UI-only. The screens call the API. Several screens are thin over a partial service.

---

## 3. Database findings

Forty-one tables. The domain split the specification asked for is present as tables:

- `patients` is not `encounters`
- `encounters` is not `admissions`
- `admissions` is not `invoices`
- `prescriptions` / `prescription_items` is not `dispense_lines`
- `products` is not `batches`
- `batches.qty_on_hand` is not the only stock record; `stock_movements` exists
- `invoices` is not `payments`
- `documents` stores metadata; bytes are files named by id
- `leads` and `notifications` are outside the clinical tables

That conceptual split is the strongest part of the schema.

### Missing constraints

There are **zero foreign keys**. A dispense line can point at a missing batch. An invoice item can point at a missing invoice if a bug deletes the parent. `PRAGMA foreign_keys=ON` does nothing until `REFERENCES` exists.

Also missing:

- No unique constraint that one patient has only one open admission. The service checks this. The database does not.
- No unique constraint that a prescription line is dispensed once. The service checks remaining quantity. Two connections can still race if the database does not lock the row.
- No check that `invoices.net_paise = gross - discount + tax`, or that `due_paise = net - paid`. Totals are cached columns.
- No check that `batches.qty_on_hand` equals `SUM(stock_movements.qty)`.
- `payments.amount_paise` can be any integer. No check `> 0`.
- Money is integer paise, which is correct. Quantity is `REAL`, which will drift.
- Booleans are integers. Dates are text. Both are portable only if every query keeps using ISO strings.
- `role_permissions.role` does not reference `roles`. A typo creates an orphan grant.
- `users.department_id` does not reference `master_items`.
- Almost every clinical `*_id` column is the same: unconstrained text.

### Indexes

Useful indexes exist for phone, patient search, queue status, invoice number (unique), batch barcode, expiry, and audit time.

Missing for a real desk:

- `encounters(validity_until, patient_id)` for the OPD-card lookup
- `payments(received_at)` for the daily report, which uses `substr(received_at,1,10)` and will not use a normal index well
- `notifications(user_id, status)` for the bell
- `documents(entity_type, entity_id)`

`substr(...)` date filters will table-scan as the file grows. That is acceptable for a few thousand rows and not for years of OPD.

### Naming and duplication

- Encounter is the OPD visit. The UI also says OPD. One concept, two words. Acceptable if documented. It is not two tables.
- `master_items` is a generic list. OPD types, services, lab tests, wards, and products are separate tables. That split is right. Do not collapse them.
- `admission_charges` duplicates invoice lines. The charge row points at `invoice_item_id`. If those ever diverge, the bill and the ward chart disagree. One of them should be a view of the other.
- `hospital_no` duplicates `patients.id` in the seed. Two identifiers without a rule.

### Historical data risks

- Finalized invoice lines store `rate_paise` and `amount_paise`. Changing `products.sale_rate_paise` does not rewrite them. This rule is implemented.
- Deactivating a master item does not delete history. Implemented for `master_items`.
- Consultation update overwrites the row. History is only in `audit_logs`, and only diagnosis is stored as old/new, not the full note.
- Adjustment adds a line and a revision snapshot. Good. Refund does not write `invoice_revisions`.
- Sample patients are mixed into the live tables with `is_sample`. Clearing them is a hand-written delete list, not a cascade. Easy to leave stock movements or payments behind.

### Concurrency risks

SQLite in WAL mode allows many readers and one writer. The server opens `BEGIN IMMEDIATE` for mutating routes, so two pharmacists on this one process will queue, not both deduct the last tablet. That is true only while there is one process and one file.

`pharmacy.move()` also starts `BEGIN IMMEDIATE` if it is not already in a transaction. That protects direct calls. It does not add row locks that PostgreSQL will need later.

`qty_on_hand` is read, then updated. Correctness depends on the write lock, not on an atomic `UPDATE ... WHERE qty_on_hand >= ?`.

Restore replaces `hospital.db` while other requests can still be open (`tx=False` on that route). That can corrupt the file being restored or let a request write the old file after the swap.

---

## 4. Critical architecture check

| Rule | Verdict |
| --- | --- |
| Patient ≠ OPD ≠ admission ≠ bill | Held in the schema and in the id sequences (`P-`, `OPD-`, `ADM-`, `AIPF-BILL-`). |
| Phone ≠ patient identity | Held. Search returns matches. Create does not update an existing row. Test covers the Sharma family. |
| Prescription ≠ dispensing | Held. Finalize does not move stock. Dispense writes `dispense_lines` and `stock_movements`. |
| Product ≠ batch | Held as tables. UI can dispense without showing packaging. |
| Current stock ≠ ledger | Held as two stores. They are kept in the same function, not by a database constraint. A bug can make them diverge. The reconcile query can see that. Nothing blocks the dispense if they already diverge. |
| Invoice ≠ payment | Held. Payments are rows. Due is recalculated. |
| Finalized invoice ≠ silent edit | Held for line edits. Draft lines cannot be removed after finalize. Adjustment requires a reason and writes a revision. Refund and extra payment after finalize are allowed, which is correct, but they are not revisions. |
| Document metadata ≠ binary | Held. UUID file name, client filename is display-only, path is checked against the documents directory. |
| External integration ≠ core operation | Held in control flow. WhatsApp queue is skipped unless enabled. Lead sync failure returns an error and does not block registration. Cloud backup failure keeps the local zip. |

The rules are implemented as application behaviour. They are not enforced by the database. That is the main architectural gap, larger than the choice of language.

---

## 5. Implementation quality

### What is in the right place

- Bill totals are calculated in `billing.recalc`, not in React.
- Stock deduction is in `pharmacy._move`, not in the pharmacy page.
- OPD fee waiver is decided on the server when `use_opd_id` is sent.
- Frontend does not import a database driver.

### What is not

- Registering a patient and opening OPD are two HTTP calls. If the second fails, a patient exists with no visit. The specification wanted one reception action.
- Converting a website lead is the same pattern: create patient, then archive lead. Not one transaction.
- Payment mode buttons in `pages/money.tsx` are `Cash`, `UPI`, `Card`, `Bank transfer`, `Cheque`. The master list can add `Other` and the bill screen will ignore it.
- Gender and queue statuses are duplicated as literals in the UI and the server.
- `core.name_of` interpolates table and column names into SQL. Callers are internal today. It is still the wrong pattern.
- `server.py` builds one deposits query with an inline import. That is a sign the HTTP layer is doing data access.
- Lists use `LIMIT` and then return `total: len(items)`. That is not a total. There is no offset. A busy year will silently hide rows.
- Any SSE event calls `bump()`, and every open page refetches. That is not a one-second poll. It is still a full reload, not a patch of the changed row.
- Clock refresh every 30 seconds is local. It does not hit the API.

### Validation gaps

- Age, money, and quantity are checked in some paths and trusted in others. A negative adjustment is allowed. A negative payment is rejected. A zero-quantity dispense is rejected.
- Custom lab tests can be billed at zero and block finalize only if the description starts with `[PRICE PENDING]`. That marker is a string convention, not a column the database understands. `lab_order_items.price_pending` exists and is not what finalize checks.
- No idempotency key on payment or dispense. A double click is safe only because the write lock makes the second request see the first result. A timeout retry after a committed payment can charge twice.

### Error shape

Errors are `{"ok": false, "error": {"code", "message"}}`. Success is `{"ok": true, "data": ...}`. File responses are raw PDF or CSV, not that envelope. That split is fine. Unexpected exceptions return a generic 500 and do not leak a stack to the client. The server prints the traceback to its own log.

---

## 6. Security issues

These are ordered by how much they matter in a hospital LAN.

1. **Unauthenticated password list.** `GET /api/public/accounts` returns usernames and passwords while `show_install_hints` is `1`. The login page renders them. Anyone who can open the desk can enter as director. This must be off before the system is used for real patients.

2. **Session token in the URL.** SSE, PDF, document download, and CSV export put the bearer token in the query string. It will land in proxy logs, browser history, and screenshots. The token is also in `sessionStorage`, so any script injected into the page can read it. There is no httpOnly cookie.

3. **Queue authorization bypass.** In `clinical.list_queue`, if `doctor_id` is passed, the code filters to that doctor and never checks `queue.view_all`. A normal doctor can read another doctor’s queue.

4. **No record-level authorization.** `patient.view` means every patient. `document.view` plus a document id means every file. `billing.view` means every invoice. The specification said a normal doctor sees assigned patients. That rule is not implemented.

5. **CORS reflects any Origin.** Combined with a bearer token this is less severe than cookie CORS, but it is not a locked-down hospital API.

6. **No login throttling.** Password hashing is 80,000 PBKDF2 iterations, which is acceptable. Nothing slows repeated failures.

7. **Secrets in the database file, and therefore in the backup zip.** API keys are masked in JSON responses. The backup manifest redacts them. The zip still contains `hospital.db`, and that file contains `app_config` secrets and password hashes. The specification said secrets must not sit in backups in recoverable form. This does not meet that.

8. **Upload trust.** Documents check the declared MIME type and size, not the file bytes, except the logo. A file labelled `application/pdf` is stored as PDF. Path traversal is blocked by writing `{uuid}.ext` under the patient folder and rejecting paths outside `data/documents`.

9. **CSRF.** Mutations use `Authorization`, not cookies, so a hostile site cannot attach the token by itself. Token-in-query weakens that if a logged-in browser requests a crafted URL. There is no CSRF token.

10. **Audit of reads is absent.** Opening a patient record is not an audit event. For a hospital, viewing the chart should be attributable.

Password storage itself is not the problem. `pbkdf2$salt$hash` with HMAC compare is a real hash, not a plaintext password.

---

## 7. Billing issues

Implemented and structurally right:

- One invoice number sequence, unique index, reprint does not allocate a number.
- Lines store the rate used at the time.
- Draft can be edited. Finalized lines cannot be deleted.
- Adjustment writes `invoice_revisions` with before/after JSON.
- Cash and UPI are two payment rows. Due is `net - paid`.
- Deposit is a balance, and applying it writes a `DEPOSIT_APPLY` payment.
- Void is refused if money has been taken.
- Amount in words uses Indian grouping (lakh, crore) and hyphenated tens. The spec example `109987` rupees is covered by a unit test.
- Paise are integers.

Not complete:

- **No payment reversal link.** Refund inserts a new row with `kind=REFUND` and does not set `reverses` or `reversed_by`. The recalc ignores rows where those columns are set, so a future reversal that fills them would be excluded, while today’s refunds are included as negative paid. The two mechanisms disagree.
- **No idempotency.** Two identical payment posts create two payments.
- **Tax is a column, not a rule.** Nothing calculates GST or a service charge from master data.
- **Discount is bill-level on drafts only.** Line discount exists on the item table and is barely used by the UI.
- **Finalize checks a description prefix** for unpaid custom tests, not `price_pending`.
- **Supplementary bills.** If the invoice is already finalized, later pharmacy or lab charges call `open_draft` and can create another draft for the same encounter. That is safer than editing the old bill. The UI does not explain that a second bill appeared.
- **Register and bill are not one transaction** with the clinical write if they are separate HTTP calls. Inside one request, OPD creation and the fee line share the request transaction. Good.
- **Frontend sends the payment amount.** The server does not reject an overpayment. `recalc` treats due as zero if paid exceeds net, and the extra cash is still a payment row. Overpayment is not a controlled advance.

Financial writes that go through a mutating route are inside `BEGIN IMMEDIATE`. That is a transaction. It is not a financial ledger with immutability. Audit rows can be deleted by anyone who can write SQL on the file.

---

## 8. Pharmacy issues

Implemented:

- Product, batch, expiry, barcode, sale rate on the batch.
- Dispense writes a negative `DISPENSED` movement and updates `qty_on_hand` in the same function.
- Expired batches are refused unless `allow_expired_dispense=1`.
- Negative stock is refused unless `allow_negative_stock=1`.
- Substitution requires a reason and is marked on the dispense line.
- Partial quantity leaves the prescription `PARTIAL`.
- A second full dispense of an already dispensed line is rejected because status is no longer `FINALIZED` or `PARTIAL`, or remaining quantity is zero.
- A threaded test tries two movements against quantity 1 and expects one failure.

Not complete:

- Packaging (`box → strip → tablet`) is not applied. The pharmacist types a tablet count. A box scan does not mean 100 tablets.
- FEFO is a suggestion when `batch_id` is empty. The UI can still pick a later batch, including one that expires sooner. That is acceptable if it is explicit. The audit trail records the batch.
- No supplier, purchase invoice, or goods-receipt document. `PURCHASE` is just a movement type.
- No lock that the dispensed product matches the prescribed product unless the pharmacist sends ids. A substitution flag is optional. A wrong product id without `substituted: true` is accepted.
- Concurrent safety is the SQLite write lock, not an atomic stock update. It will not transfer unchanged to PostgreSQL.

---

## 9. Realtime issues

What exists:

- `events.py` is an in-memory fan-out.
- Domain functions call `publish()` after queue assignment, prescription finalize, dispense, invoice changes, admissions, OT, and lab.
- `GET /api/events` is Server-Sent Events. The browser uses `EventSource`. There is no `setInterval` fetch of the queue.
- On an event, the open page refetches.

What this is not:

- Not durable. If the process restarts, in-flight events are gone.
- Not multi-process. Two hospital server processes would each have their own hub. Pharmacy on process B would not see a prescription finalized on process A.
- Not a catch-up stream. Reconnect does not send missed events. The page looks current only after the next event, or a manual reload.
- Not a row patch. `bump()` reloads whatever the page last requested.

For one process and a small LAN, a finalized prescription will show on a pharmacy screen that already has SSE open, after that screen refetches. That meets the demonstration. It does not meet a production realtime gateway.

---

## 10. PDF issues

The renderer in `pdf.py` writes a real PDF 1.4 with Helvetica text operators and an optional JPEG XObject. It is not a screenshot. Reprint is `GET /api/invoices/:id/pdf` and does not insert a row.

This pass did not open a PDF. The following is from the generator, and it is enough to refuse a COMPLETE mark.

- Amounts are right-aligned by `len(text) * size * 0.52`. That is an estimate. Digits and commas will not line up. They can overlap the label.
- Long descriptions are cut with an ellipsis. They are not wrapped. A long medicine-plus-batch line is clipped.
- A page break starts a blank page. It does not repeat the hospital header or the column headings. A long IPD bill will be hard to read after page 1.
- There is no test that a 40-line bill paginates without drawing past the footer.
- The PAID mark is a rectangle with the word PAID, drawn only when `payment_status == PAID` and the bill is not void. That rule is in code. It has not been visually accepted.
- Helvetica has no rupee sign. Amounts are plain numbers. Amount in words is a text line and can itself be clipped at 110 characters.
- Logo embed depends on a JPEG SOF parser. PNG logos are accepted by the upload endpoint and will not embed.
- Page number placement uses another character-width guess.
- `generated_at` changes on every download, so two reprints are not byte-identical. The invoice number does not change. That part is correct.

Do not treat “a PDF file was produced” as a finished bill.

---

## 11. Backup issues

Status: **PARTIAL, local path works as code, not production-safe.**

| Requirement | State |
| --- | --- |
| Database backup | Zip contains `database/hospital.db` after a WAL checkpoint. |
| Document backup | Files under `data/documents` are added. |
| Configuration | A redacted manifest is added. The database file still holds the real config. |
| Audit | Included only because it is inside the database file. |
| Local backup | Implemented. |
| Cloud backup | S3-style signed PUT and a download verify are implemented. Not proven against R2, B2, or MinIO. A failure is recorded and the local zip is kept. |
| Checksum | SHA-256 of the zip. Verify re-reads the zip and checks that a database member exists. |
| Restore | Requires the text `RESTORE AIPF`, writes a safety zip, replaces the database file, deletes WAL sidecars, and tells the operator to restart. |
| Retention | Count cap deletes older files. The day setting is stored and not applied as an age rule. |
| Encryption | Not implemented. |
| Consistent snapshot under load | Checkpoint plus copy is not a quiesced backup. A request can write between checkpoint and zip. |
| Restore safety | The server stays up and keeps taking requests during restore. |

A cloud HTTP 200 is not treated as success by itself. The code downloads the object and compares size and checksum before `VERIFIED`. That part matches the specification. The rest does not.

---

## 12. Health-check audit

`GET /api/system/health` runs checks. It does not return a hardcoded HEALTHY.

| Check | Actually measured? |
| --- | --- |
| Application / API | The request arrived. True, and trivial. |
| Database | `SELECT 1` and latency. Real. |
| Database pool | Reads `PRAGMA journal_mode` and then describes SQLite. Not a pool. The text is honest that clients do not connect. The name “pool” overclaims. |
| Local storage / documents | Writes, reads, and deletes a probe file. Real. |
| File permissions | `os.access` write on the documents directory. Real. |
| Disk | `shutil.disk_usage`. Real. |
| CPU | `os.getloadavg` when the OS provides it. Real, coarse. |
| RAM | `/proc/meminfo` when present. Real. |
| Realtime | Reports the in-process subscriber count and marks the hub HEALTHY even at zero clients. The hub existing is not the same as a client receiving an event. |
| Queue worker | Heartbeat timestamp from the daemon thread. Real. |
| PDF | Builds a tiny PDF and checks the `%PDF` header. Real. Does not prove a hospital bill. |
| Backup scheduler / local backup | Looks at the last backup row and its age. Real. No backup is DEGRADED, not fake HEALTHY. |
| Cloud backup | NOT_CONFIGURED if no endpoint. Does not pretend success. |
| OpenWA | Live HTTP check only if enabled and a base URL exists. Otherwise NOT_CONFIGURED. |
| Website leads | NOT_CONFIGURED unless enabled. The enabled state does not ping Mongo on the health page; it tells the operator to use Test. |
| Scheduled jobs | Same heartbeat as the worker. |
| Configured ports | A sentence. It does not scan ports. |

Overall status ignores `NOT_CONFIGURED`, and becomes DEGRADED or CRITICAL from failed core checks. That is the right policy: WhatsApp must not mark the hospital critical. It must not be described as a measured port scan.

---

## 13. SQLite, PostgreSQL, and Go

### Option A — Python + SQLite

Fit for this hospital:

- One file is easy to copy and easy to lose.
- WAL plus `BEGIN IMMEDIATE` can serialize a reception desk, two doctors, and a pharmacy **on one process**. A 15-user LAN will feel the writer lock during dispense, which also writes invoice lines.
- No row-level locks, no `SELECT FOR UPDATE`, no connection pool, no online point-in-time recovery.
- Backup is “copy the file”. Restore races with live writers.
- Years of scans and bills will make full-zip backups and `substr` reports slow.
- Foreign keys are available and currently unused. Turning them on later does not fix the engine limits.

SQLite is a reasonable **single-developer store** while the domain model is still moving. It is not the production database for AIPF if more than one desk will take money and dispense stock at the same time, and if a disk failure must be recoverable without guessing which requests landed.

### Option B — Python + PostgreSQL

Fit:

- Keeps the service modules that already encode patient, OPD, stock, and bill rules.
- Gives real multi-user transactions, row locks, roles, `pg_dump`, and a backup story a hospital can operate.
- Requires a host install or a bundled PostgreSQL, which the specification already required.
- Requires the stock update and payment insert to be rewritten as locked statements. A naive swap of the driver will create the race SQLite’s file lock is currently hiding.
- Does not by itself add foreign keys, idempotency, or record-level security. Those are schema and service work.

This is the smallest step that matches the operational requirement.

### Option C — Go + PostgreSQL

Fit:

- Matches the original platform note.
- A Go server is a good long-term host: one binary, predictable memory, a real HTTP router.
- Today it means rewriting about 4,500 lines of domain Python, the PDF generator, the backup signer, and the tests, before the domain is stable.
- A rewrite now will copy the missing foreign keys and the authorization bugs into a second language, or it will stall the hospital while the port happens.
- Go does not make the data model correct.

Go is a packaging decision. It is not the next correctness decision.

### Recommendation

**Development, until you say otherwise: stay on Python. Stop treating SQLite as the hospital database.**

Use SQLite only so a developer can boot the desk. Do not add features on top of the missing constraints.

**Production: Option B, Python + PostgreSQL, on the hospital host, not exposed to client PCs.**

Do not start a Go rewrite in the next phase. Revisit Go only after the PostgreSQL schema has foreign keys, locked stock updates, idempotent payments, and the current tests passing against PostgreSQL. At that point a Go port is a move of a stable service, not a second design.

This is a recommendation, not a change. No code was migrated.

---

## 14. Migration plan, if Option B is accepted

Do this in order. Do not mix it with new wards, new WhatsApp features, or a Go port.

1. **Freeze features.** Bugfixes that protect money or stock are allowed. New modules are not.
2. **Write the constraints down as PostgreSQL DDL**, not as a SQLite dialect dump. Add foreign keys, check constraints, and unique partial indexes (one open admission per patient, unique invoice number).
3. **Replace cached-stock races** with `UPDATE batches SET qty_on_hand = qty_on_hand - $1 WHERE id = $2 AND qty_on_hand >= $1`, and insert the movement only if that update returns a row.
4. **Add idempotency keys** on payments and dispense requests.
5. **Introduce a repository boundary** in Python first: clinical, pharmacy, and billing stop embedding SQL in the HTTP file. The deposits query in `server.py` moves behind that boundary. This is what makes a later Go port possible.
6. **Point the same tests at PostgreSQL.** The existing flow tests are the acceptance list. Add the cases they skip: overpayment, double payment, doctor queue bypass, multi-page PDF, restore while the server is stopped.
7. **Backup becomes `pg_dump` plus the document tree**, encrypted, restored only while the API is stopped.
8. **Only then** decide whether the HTTP process stays Python or becomes Go. The DDL and the tests should not care.

SQLite can remain a developer fallback behind the repository. It should not be the file AIPF trusts with patients.

---

## 15. Exact next implementation phase

If the recommendation is accepted, the next phase is not a feature and not a rewrite.

**Phase name: schema and transaction hardening, then PostgreSQL.**

In scope:

- Foreign keys and the stock `UPDATE ... WHERE qty >=` rule
- Close the doctor queue bypass and turn off public passwords
- Payment idempotency and a real reversal link
- Repository seam in the Python services
- PostgreSQL migration runner and the current flow tests against it
- PDF pagination proof on a long bill, still the same invoice model

Out of scope until that phase is accepted and finished:

- New clinical modules
- Go rewrite
- Tauri installer
- More WhatsApp automation
- Tailwind restyle

If you reject Option B and want Go now, say so explicitly. That is a different phase: freeze the Python behaviour as the specification, and port it. It should not proceed from silence.

No application code was changed for this audit.
