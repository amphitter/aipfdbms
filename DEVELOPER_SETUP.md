# Developer setup

Local setup for a new developer who has just received the AIPF Mission Hospital repository.

This file describes the code that is in the repository now. Commands below were checked on Linux in the environment that produced this document, except where a line says **Not verified in this environment.**

The hospital application does not load a `.env` file. It reads the process environment. `.env.example` is a checklist, not an automatic config file.

## Quick start

From the repository root (the folder that contains `backend/`, `frontend/`, and `start-host.sh`):

1. Install Python 3.10 or newer, Node.js with npm, and PostgreSQL. Versions are not pinned by the repository. See [Prerequisites](#prerequisites).
2. Create a PostgreSQL role and an empty database. See [PostgreSQL](#postgresql).
3. Install the backend package:

   ```bash
   python3 -m pip install -r backend/requirements.txt
   ```

4. Start the API. Replace the password and use at least 12 characters for the seed password. Run this from `backend/`:

   ```bash
   cd backend
   export AIPF_ENV=development
   export AIPF_DATABASE_URL='postgresql://aipf:your-password@127.0.0.1:5432/aipf_dev'
   export AIPF_SEED_PASSWORD='CHANGE_ME_at_least_12'
   export AIPF_PORT=8787
   python3 -m aipf.server
   ```

   The first start migrates the empty database and seeds it. Leave this terminal open.

5. In a second terminal, from `frontend/`:

   ```bash
   cd frontend
   npm install
   npm run dev -- --host 0.0.0.0 --port 5173
   ```

6. Open `http://127.0.0.1:5173`. Sign in as `director` with the value of `AIPF_SEED_PASSWORD`.

7. Confirm the API without the browser:

   ```bash
   curl -s http://127.0.0.1:8787/api/public/branding
   ```

   A signed-in health check is `GET /api/system/health`. It is not public.

Details, Windows notes, and what not to do are below.

---

## What this system is

This is a local-first Hospital Information and Operations System for AIPF Mission Hospital, Shahpurpur, Fatehpur Beri, New Delhi 110074.

Staff browsers talk only to the hospital application. They do not connect to PostgreSQL. Patient records, documents, bills, and stock stay on the computer that runs the API unless an administrator turns on WhatsApp, website leads, or cloud backup in the application settings.

Money is stored as integer paise. The billing service calculates invoice totals. The browser is not the source of truth for a bill.

### Implemented

These areas have working backend modules, API routes, and desk screens:

| Area | Where it lives |
| --- | --- |
| Patient registration and search | `backend/aipf/clinical.py`, desk routes under `/patients` |
| OPD encounter and queue | `clinical.py`, `/queue`, `/doctor` |
| Consultation and prescription | `clinical.py`, `/consult/:id` |
| Pharmacy dispensing | `backend/aipf/pharmacy.py`, `/pharmacy` |
| Inventory, batches, stock ledger, barcode lookup | `pharmacy.py`, `/inventory` |
| Billing, payments, deposits, refunds, adjustments | `backend/aipf/billing.py`, `/billing` |
| Laboratory orders, samples, results, reports | `backend/aipf/laboratory.py`, `/lab` |
| Admission, ward, room, bed, bed movement, discharge | `backend/aipf/wards.py`, `/beds`, `/admissions` |
| Operation theatre request through report and charge | `backend/aipf/theatre.py`, `/ot` |
| Documents | `backend/aipf/storage.py` and the documents routes |
| Audit log, no delete route | `GET /api/audit` |
| Staff, roles, permission codes, record scope | `backend/aipf/core.py`, `backend/aipf/access.py` |
| Realtime | Server-sent events at `GET /api/events` |
| Health report | `GET /api/system/health` |
| SQLite file backup and restore | `backend/aipf/system.py`, Admin > Backups |

Phone numbers are search data. They are not a unique patient identity, and the application does not merge two patients because they share a phone.

### Partially implemented

- **PostgreSQL backup and restore.** `create_backup` and `restore_backup` return HTTP 501 on PostgreSQL: "not implemented for PostgreSQL". The SQLite file copy is not used as a fallback.
- **Cloud backup.** An S3-compatible upload is coded inside the backup function. That function refuses to run on PostgreSQL. With no cloud endpoint configured, health reports cloud backup as `NOT_CONFIGURED`.
- **Realtime.** One in-process hub. A second API process would not share it. The health check reports Realtime as `DEGRADED` even when a browser is connected. That text is in `health_report`.
- **WhatsApp.** An OpenWA provider exists. Seeded config has `wa_enabled` set to `0`. It is not required for registration, OPD, pharmacy, or billing.
- **Website leads.** Optional MongoDB sync. The driver is imported only when a test or sync runs. `pymongo` is not in `backend/requirements.txt`. Seeded config has `leads_enabled` set to `0`.
- **PDF rupee glyph.** `pdf.py` can draw a rupee mark with Pillow and a DejaVu font. Pillow is not in `requirements.txt`. PDF generation continues if that import fails.
- **Host shortcut.** `./start-host.sh` starts the API and the Vite development server. It does not build `frontend/dist` and it does not install a service.
- **Log directory.** Startup creates `data/logs`. The application does not write log files there. Application messages go to the `app_logs` table. HTTP access lines are suppressed. Unexpected exceptions are printed to the API process stderr.

### Not implemented

- WebSocket. The desk uses server-sent events.
- JWT. Sessions are random bearer tokens.
- A silent switch to SQLite when PostgreSQL is down, or when `AIPF_ENV=production` has no PostgreSQL URL.
- A second invoice, payment, or refund system for laboratory, IPD, or OT. Those charges go through billing.
- A separate migration command. Migrations run when the API starts.
- A repository command that resets the development database.
- A committed security-contact address.
- Docker, a systemd unit, or a Windows service installer. None of those files are in the repository.
- A frontend test script. `frontend/package.json` has no `test` script.

---

## Tech stack

Versions are not pinned unless the table says they are.

| Layer | What the repository uses |
| --- | --- |
| Frontend language | TypeScript |
| Frontend UI | React 19 (`react` and `react-dom` `^19.2.8`) |
| Frontend build | Vite 8 (`vite` `^8.3.0`) with `@vitejs/plugin-react` |
| Frontend routing | `react-router-dom` `^7.18.4`, `BrowserRouter` |
| Frontend state | Zustand `^5.0.15` in `frontend/src/store.ts` |
| Frontend CSS | Hand-written CSS in `frontend/src/styles.css`, `index.css`, and `App.css`. No Tailwind and no component library. |
| Frontend data loading | `fetch` in `frontend/src/api.ts` and the `useData` hook in `frontend/src/ui.tsx` |
| Frontend lint | Oxlint (`npm run lint`) |
| Backend language | Python. Not pinned. The server uses runtime `list \| tuple`, which needs Python 3.10 or newer. |
| Backend server | The standard-library `ThreadingHTTPServer` in `backend/aipf/server.py`. Not FastAPI, Flask, or Uvicorn. |
| API shape | JSON routes under `/api`. Success is `{"ok": true, "data": ...}`. Failure is `{"ok": false, "error": {"code", "message"}}`. |
| Authentication | Bearer token. The server stores a SHA-256 digest in `sessions`. Session length is 16 hours (`SESSION_HOURS` in `core.py`). |
| Authorization | Permission codes in `core.permit` / `core.permit_any`. Record scope is in `access.py`. Role names are not the authorization check. |
| Domain layer | `clinical.py`, `pharmacy.py`, `billing.py`, `laboratory.py`, `wards.py`, `theatre.py`, `system.py`, `notify.py` |
| Repository layer | `backend/aipf/repo/*.py`. SQL lives here. |
| Database | PostgreSQL through `psycopg` 3 (`psycopg[binary]>=3.2`). Development may also use SQLite, but only with an explicit `sqlite:///` URL. |
| Migrations | SQL files in `backend/aipf/migrations/`, applied by `backend/aipf/migrate.py` at startup. |
| Transactions | Each request opens its own connection (`autocommit=True` on PostgreSQL, then an explicit `BEGIN`). There is no connection pool. The health report says so. |
| Storage | `StorageProvider` / `LocalStorageProvider` in `storage.py`. Root is `data/documents`. |
| Realtime | In-process queues in `events.py`, delivered as `text/event-stream`. |
| PDF | A small PDF writer in `backend/aipf/pdf.py`. Not ReportLab. A4 pages are 595.28 by 841.89 points. |
| Tests | `pytest`, imported by `backend/tests/`. pytest is not listed in `requirements.txt`. |
| HTTP tests | The phase tests start `python3 -m aipf.server` and call it with `urllib`. |
| Test database | Phase tests create and drop their own PostgreSQL databases. They must not be pointed at production. |

This document's environment verified Python 3.13.14, Node v20.20.2, npm 10.8.2, Vite v8.3.1, psycopg 3.3.6, and PostgreSQL 17.11. Those are the tools that happened to be available. They are not a project requirement, except for the Python 3.10 floor implied by the code.

---

## Architecture

```text
Browser
  |  HTTP to the Vite desk in development (port 5173)
  |  The desk proxies /api to 127.0.0.1:8787
  |  SSE: GET /api/events?token=...
  v
Frontend (React)
  |  Authorization header is UX only
  v
Backend API  (ThreadingHTTPServer, 0.0.0.0:8787)
  |
  +-- session lookup and permission check
  |
  +-- domain services (clinical, pharmacy, billing, laboratory, wards, theatre)
  |     business rules live here
  |     do not put SQL here
  |
  +-- repositories (backend/aipf/repo)
  |     SQL, locks, and constraints live here
  |
  +-- PostgreSQL
  |     production database
  |     clients never receive a connection
  |
  +-- StorageProvider
  |     document bytes under data/documents
  |
  +-- realtime hub
  |     in-process only
  |
  +-- PDF renderer
        bytes returned by the API, then stored through StorageProvider
```

There is no WebSocket server.

Responsibilities:

- **Frontend.** Screens, forms, and permission-based hiding of navigation. A hidden button is not a security boundary.
- **API.** Authentication, permission checks, transactions, and the JSON envelope.
- **Domain services.** Status transitions, money, clinical rules, and who may touch a record.
- **Repositories.** SQL. Overlap locks for theatres and surgeons are here, not in JavaScript.
- **PostgreSQL.** Durable rows, check constraints, and foreign keys compiled into the PostgreSQL migrations.
- **Storage.** File bytes. The API authorizes the user, then reads bytes by storage key. It does not return a filesystem path as the way to open a file.
- **Realtime.** Tells an already-open desk to refresh. It is not a second copy of the database.

---

## Prerequisites

Install these before the first run.

| Tool | Required version | How to check |
| --- | --- | --- |
| Git | Not pinned. Needed only to clone. This working copy has no `.git` directory, so a remote URL is not recorded here. | `git --version` — **Not verified in this environment.** |
| Python | Not pinned. Use 3.10 or newer. | `python3 --version` |
| pip | The pip that belongs to that Python. | `python3 -m pip --version` |
| Node.js | Not pinned. Vite 8 was started here with Node v20.20.2. | `node --version` |
| npm | The npm that belongs to that Node. This repository uses npm, not pnpm or yarn. `package-lock.json` is present. | `npm --version` |
| PostgreSQL server | Not pinned. Production must use PostgreSQL. This environment used 17.11. | `psql --version` |
| PostgreSQL client | `psql`, so you can create the role and database. | `psql --version` |
| A browser | Not pinned. | Open `http://127.0.0.1:5173` after the desk starts. |

Optional:

- **pytest.** Required only to run `backend/tests/`. It is not in `requirements.txt`. This environment already had pytest 9.0.3. If `python3 -m pytest` fails with `No module named pytest`, install pytest yourself. No version is pinned.
- **Pillow.** Optional. Used only for the rupee glyph in PDFs.
- **pymongo.** Optional. Required only if you enable website-lead sync.
- **VS Code.** Not required. The repository does not ship recommended extensions.

A virtual environment is not required and is not included. If you create one, activate it before `pip install` and before `python3 -m aipf.server`.

---

## Clone

This working copy does not contain `.git`, so the clone URL is not in the repository. Use the URL your team gave you.

```bash
git clone <repository-url>
cd <repository-directory>
```

**Not verified in this environment.** After clone, the working directory must be the folder that contains `backend/`, `frontend/`, `data/`, and `start-host.sh`.

There is one application, not a multi-package workspace. Run backend commands in `backend/`. Run frontend commands in `frontend/`.

---

## Project structure

```text
.
├── start-host.sh              # starts API, then Vite; SQLite only if no database URL is set
├── README.md
├── DEVELOPER_SETUP.md         # this file
├── API.md                     # route catalog
├── .env.example               # checklist; not loaded by the app
├── backend/
│   ├── requirements.txt       # psycopg[binary]>=3.2
│   ├── tests/                 # pytest files
│   └── aipf/
│       ├── server.py          # HTTP server and route table
│       ├── migrate.py         # migration runner
│       ├── migrations/        # versioned SQL
│       ├── schema.sql         # baseline tables
│       ├── schema_compile.py  # builds the PostgreSQL baseline
│       ├── repo/              # SQL
│       ├── clinical.py
│       ├── pharmacy.py
│       ├── billing.py
│       ├── laboratory.py
│       ├── wards.py
│       ├── theatre.py
│       ├── core.py            # sessions, permissions, numbering
│       ├── access.py          # record scope
│       ├── storage.py
│       ├── events.py
│       ├── pdf.py
│       ├── seed.py
│       └── system.py          # health, backup, integrations
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── index.html
│   ├── public/
│   └── src/
│       ├── main.tsx
│       ├── App.tsx            # routes and navigation
│       ├── api.ts
│       ├── store.ts
│       ├── pages/
│       └── styles.css
└── data/
    ├── documents/             # StorageProvider root
    ├── backups/               # local backup zip files
    ├── branding/              # uploaded logo files
    └── hospital.db            # SQLite file used only when a sqlite URL points here
```

Change application behaviour in `backend/aipf/` and `frontend/src/`.

Do not hand-edit an already-applied file in `backend/aipf/migrations/`. Do not hand-edit PostgreSQL to "fix" a migration. Do not treat `data/hospital.db` as production.

`data/migration_error.txt` is a leftover note in this working tree. The current code does not write that file.

---

## Environment variables

The process environment is the only configuration channel. There is no `python-dotenv` import.

| Variable | When | Example | Purpose |
| --- | --- | --- | --- |
| `AIPF_ENV` | Optional. Default `development`. | `development` | `production` requires a PostgreSQL URL and refuses SQLite. |
| `AIPF_DATABASE_URL` | Required for `python3 -m aipf.server`. | `postgresql://aipf:your-password@127.0.0.1:5432/aipf_dev` | Database. `postgresql://`, `postgres://`, or an explicit `sqlite:///` URL. |
| `AIPF_PORT` | Optional. Default `8787`. | `8787` | API listen port. The Vite proxy is hardcoded to `127.0.0.1:8787`. |
| `AIPF_SEED_PASSWORD` | Required only while the database has no users. | `CHANGE_ME_at_least_12` | Password for every seeded account. Minimum 12 characters. Not stored in source. |
| `AIPF_TEST_POSTGRES` | Tests only. Not read by the server. | `postgresql://aipf:your-password@127.0.0.1:5432/postgres` | Admin URL used by acceptance tests to create and drop throwaway databases. |
| `PHASE1_REQUIRE_POSTGRES` | Tests only. | `1` | If set to `1`, Phase 1 fails instead of skipping when no PostgreSQL URL is set. |
| `PHASE2_REQUIRE_POSTGRES` | Tests only. | `1` | Same for Phase 2. |
| `PHASE3_REQUIRE_POSTGRES` | Tests only. | `1` | Same for Phase 3. |

There is no frontend `VITE_` variable. The desk calls relative `/api` paths. There is no JWT secret, no CORS origin variable, no storage-path variable, and no SMTP variable.

WhatsApp, MongoDB, and S3 settings are rows in the application config table, edited under Admin > Integrations and Admin > Backups. They are not environment variables. Seeded secret keys (`wa_api_key`, `leads_mongo_uri`, `cloud_access_key`, `cloud_secret_key`) start empty.

`start-host.sh` is the exception to "no URL means refuse": if `AIPF_DATABASE_URL` is empty, the script exports `sqlite:///<repository>/data/hospital.db` and prints that it did so. `python3 -m aipf.server` does not do that. With no URL, it raises `No database configured` and does not open SQLite.

Copy `.env.example`, fill it in, and export it yourself:

```bash
set -a
source .env.example
set +a
```

That `source` is a bash feature. The application still does not read the file on its own. Do not commit a filled-in copy. There is no root `.gitignore` in this repository, so a `.env` file is not ignored by a project rule.

---

## PostgreSQL

```text
PostgreSQL server
    -> database
    -> application role
    -> AIPF_DATABASE_URL
    -> API startup runs migrations
    -> seed runs only if there are no users
    -> application
```

Do not create the application tables by hand. The migration runner does that.

### Install and check

Install PostgreSQL from your operating system's packages. The repository does not ship an installer.

```bash
psql --version
```

This environment installed Debian's `postgresql` package, which created cluster `17/main` on port 5432 but did not start it (`policy-rc.d` refused the service start). The verified start command here was:

```bash
sudo pg_ctlcluster 17 main start
pg_lsclusters
```

`pg_lsclusters` should show `online`. Other Linux distributions and Windows use different service commands. Those commands were **not verified in this environment.**

### Create the role and database

The repository does not prescribe the role name or the database name. `aipf` and `aipf_dev` below are examples. Do not use a database name that the tests drop (`aipf_phase0`, `aipf_stock`, `aipf_phase1` through `aipf_phase7`, `aipf_p7smoke`).

On Debian, the local `postgres` operating-system user can connect with peer authentication:

```bash
sudo -u postgres psql
```

Then:

```sql
CREATE ROLE aipf LOGIN PASSWORD 'your-password';
CREATE DATABASE aipf_dev OWNER aipf;
```

Quit `psql` with `\q`.

Test the connection. This prints the database name and the role, not the password:

```bash
psql "postgresql://aipf:your-password@127.0.0.1:5432/aipf_dev" -c "SELECT current_database(), current_user;"
```

The API sets the PostgreSQL session time zone to `UTC` on each connection. Application timestamps are generated in `Asia/Kolkata` by `util.now()`. That zone is hardcoded. It is not an environment variable.

### Acceptance-test role

Phase tests connect to `AIPF_TEST_POSTGRES` and run `CREATE DATABASE` / `DROP DATABASE`. The role in that URL needs permission to create and drop databases. A local superuser URL, or a role created with `CREATEDB`, can do that. Point it at a maintenance database such as `postgres`, not at a hospital database you care about, and never at production.

```text
AIPF_TEST_POSTGRES=postgresql://aipf:your-password@127.0.0.1:5432/postgres
```

---

## Migrations

Migrations are SQL files in `backend/aipf/migrations/`.

| File | Applies to |
| --- | --- |
| `0001_baseline.sqlite.sql` | SQLite baseline |
| `0001_baseline.postgres.sql` | PostgreSQL baseline, compiled from `schema.sql` plus foreign keys |
| `0002_operational_indexes.sql` | both |
| `0003_idempotency_and_lab_results.sql` | both |
| `0004_iam_security.sql` | both |
| `0005_users_active_check.postgres.sql` | PostgreSQL only |
| `0006_queue_integrity.sql` | both |
| `0007_clinical_status_check.postgres.sql` | PostgreSQL only |
| `0008_pharmacy_barcode.sql` | both |
| `0009_pharmacy_checks.postgres.sql` | PostgreSQL only |
| `0010_billing_controls.sql` | both |
| `0011_billing_checks.postgres.sql` | PostgreSQL only |
| `0012_laboratory_workflow.sql` | both |
| `0013_laboratory_checks.postgres.sql` | PostgreSQL only |
| `0014_lab_active_collection.sql` | both |
| `0015_ipd_integrity.sql` | both |
| `0016_ipd_checks.postgres.sql` | PostgreSQL only |
| `0017_ot_workflow.sql` | both |
| `0018_ot_checks.postgres.sql` | PostgreSQL only |

A file named `NNNN_name.sql` applies to both dialects. A file named `NNNN_name.postgres.sql` or `NNNN_name.sqlite.sql` applies only to that dialect. If both a shared file and a dialect file exist for the same number, the dialect file is the one that runs.

The runner does not require the version numbers to be contiguous. SQLite skips the PostgreSQL-only files, so its highest applied version is 17. PostgreSQL applies `0018`, so its highest version is 18.

### What startup does

`python3 -m aipf.server` calls `init_db()`, which:

1. Opens `AIPF_DATABASE_URL`.
2. Calls `apply_migrations()`.
3. Adds any new permission grants to roles that already exist.
4. Ensures barcode types.
5. Calls `seed_if_empty()`. If any user already exists, seed does nothing.

There is no `python -m aipf.migrate` command. `migrate.py` has no `__main__` block.

### Checksums

Each applied file's SHA-256 is stored in `schema_migrations.checksum`.

On every startup the runner:

- refuses to start if an applied version has no file on disk
- refuses to start if a stored checksum does not match the file
- does not rewrite the stored checksum
- does not run that migration again
- rolls back a migration that fails and does not record its version

Do not edit a migration that has already been applied. Add a new file with the next version number.

### Inspect the version

After the API has started once:

```sql
SELECT version, name, checksum IS NOT NULL AS has_checksum
FROM schema_migrations
ORDER BY version;
```

```sql
SELECT MAX(version) FROM schema_migrations;
```

A fresh PostgreSQL database in this environment reported `18`.

### Copy an existing SQLite file

If you already have `data/hospital.db` and want those rows in an empty migrated PostgreSQL database:

```bash
cd backend
export AIPF_DATABASE_URL='postgresql://aipf:your-password@127.0.0.1:5432/aipf_dev'
python3 -m aipf.pgcopy
```

Optional first argument: path to a SQLite file. The default is `data/hospital.db`. The command migrates the PostgreSQL target, then copies. It refuses if the target already has patients. It does not delete the SQLite file.

**Not re-run in this documentation pass.** The command and its refusal rule are in `backend/aipf/pgcopy.py`.

---

## First-time initialization

### Step 1 — Start PostgreSQL

Confirm port 5432 is accepting connections. On the Debian layout used here, `pg_lsclusters` shows `online`.

### Step 2 — Create the database

Use the SQL in [PostgreSQL](#postgresql). Leave it empty. Do not create `patients` or `users` yourself.

### Step 3 — Set the environment

From `backend/`:

```bash
export AIPF_ENV=development
export AIPF_DATABASE_URL='postgresql://aipf:your-password@127.0.0.1:5432/aipf_dev'
export AIPF_SEED_PASSWORD='CHANGE_ME_at_least_12'
export AIPF_PORT=8787
```

`AIPF_SEED_PASSWORD` must be at least 12 characters. The same value is hashed for every seeded account. It is not written into the repository.

### Step 4 — Start the API

```bash
python3 -m aipf.server
```

That start applies migrations. You do not run a second migrate command.

Expected stdout:

```text
AIPF hospital server on http://0.0.0.0:8787
Database postgres. Client PCs do not connect to it.
```

### Step 5 — Seed

Seed runs inside that same start, only when the `users` table is empty. You do not run a separate seed command. If users already exist, changing `AIPF_SEED_PASSWORD` does nothing.

There is no repository command that wipes a database. Do not delete `data/hospital.db` unless you intend to discard that SQLite file. If that file was seeded earlier, its password is whatever was in the environment then. It is not in this repository. Use a new PostgreSQL database when you need a password you know.

### Step 6 — Development users

Seeded usernames, from `backend/aipf/seed.py`:

| Username | Person in the seed | Role |
| --- | --- | --- |
| `director` | Samuel Thomas | `admin`, and also `doctor` |
| `reception` | Lata Minj | `reception` |
| `dr.anita` | Anita Rao | `doctor` |
| `dr.imran` | Imran Qureshi | `doctor` |
| `dr.priya` | Priya Nair | `doctor` |
| `dr.joseph` | Joseph Mathew | `doctor` |
| `pharmacy` | Ramesh Yadav | `pharmacist` |
| `billing` | Sunita Paul | `billing` |
| `nurse` | Anjali Kerketta | `nurse` |
| `lab` | Deepak Oraon | `lab` |

These are development seed accounts. The password is `AIPF_SEED_PASSWORD` from the first seed. Change it after sign-in. Do not reuse it on a production host.

The login form pre-fills the username `reception`. It does not know the password. `GET /api/public/accounts` returns an empty list.

### Step 7 — Start the desk

See [Frontend](#frontend). Open `http://127.0.0.1:5173`.

---

## Backend

From the repository root:

```bash
python3 -m pip install -r backend/requirements.txt
cd backend
export AIPF_ENV=development
export AIPF_DATABASE_URL='postgresql://aipf:your-password@127.0.0.1:5432/aipf_dev'
export AIPF_SEED_PASSWORD='CHANGE_ME_at_least_12'
export AIPF_PORT=8787
python3 -m aipf.server
```

| Item | Value |
| --- | --- |
| Listen address | `0.0.0.0` (hardcoded `HOST`) |
| Port | `AIPF_PORT`, default `8787` |
| Reload | None. Restart the process after a Python change. |
| Access log | Suppressed. `log_message` returns without printing. |
| Error log | Tracebacks go to the process stderr. |
| Worker | A daemon thread named `aipf-worker` runs every 8 seconds. It retries the notification queue and may run a scheduled backup. |

There is no `--reload` flag and no Uvicorn command.

### Checks

Public, no token:

```bash
curl -s http://127.0.0.1:8787/api/public/branding
```

Expected: `"ok": true` and `"name": "AIPF Mission Hospital"` after seed.

Health requires a signed-in user with `health.view`. Without a token it returns 401 `Sign in required.` That is the current behaviour, not a failed install.

A non-API path returns plain text until `frontend/dist` exists:

```text
AIPF hospital API is running. Open the desk application.
```

### Startup failures

| Message | Meaning |
| --- | --- |
| `No database configured` | `AIPF_DATABASE_URL` is empty and you did not use `start-host.sh`. |
| `AIPF_ENV=production requires AIPF_DATABASE_URL to be a PostgreSQL URL` | Production will not open SQLite. |
| `PostgreSQL is configured but unavailable` | The URL is set, but the server refused the connection. SQLite was not used. |
| `PostgreSQL support requires psycopg` | `backend/requirements.txt` is not installed. |
| `Migration ... checksum mismatch` | An applied SQL file was edited. Startup stops. The stored checksum is left as it was. |
| `Set AIPF_SEED_PASSWORD` | The database has no users, and the password is missing or shorter than 12 characters. |

`start-host.sh` from the repository root starts the API in the background and then runs the Vite desk. If `AIPF_ENV=production` and `AIPF_DATABASE_URL` is empty, the script exits before starting either process. If the URL is empty and the environment is not production, the script points SQLite at `data/hospital.db`. Prefer the two-terminal setup above when you are developing against PostgreSQL.

---

## Frontend

Package manager is npm. Scripts in `frontend/package.json`:

| Script | Command | What it does |
| --- | --- | --- |
| `dev` | `vite` | Development desk |
| `build` | `tsc -b && vite build` | Typecheck and write `frontend/dist` |
| `lint` | `oxlint` | Lint. This environment finished with warnings and exit code 0. |
| `preview` | `vite preview` | Serves the built desk on port 5173 |

There is no `test` script.

```bash
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 5173
```

`vite.config.ts` already sets host `0.0.0.0`, port `5173`, and `strictPort: true`. The extra flags match `start-host.sh`. If 5173 is taken, Vite stops. It does not pick another port.

Open `http://127.0.0.1:5173`.

The dev server proxies `/api` to `http://127.0.0.1:8787`. The browser does not call port 8787 directly during development. Leave the API on 8787, or the proxy will miss it. There is no environment variable to change that proxy target.

`npm run build` and `npm run preview` were **not verified in this environment.** If `frontend/dist` exists, the API serves those files for paths that are not under `/api`.

---

## Run the complete system

Terminal 1, PostgreSQL. It must already be listening on 5432. This environment used:

```bash
sudo pg_ctlcluster 17 main start
```

**The service command is Debian-specific.** Confirm with `pg_lsclusters` or `psql`.

Terminal 2, API, from `backend/`:

```bash
export AIPF_ENV=development
export AIPF_DATABASE_URL='postgresql://aipf:your-password@127.0.0.1:5432/aipf_dev'
export AIPF_SEED_PASSWORD='CHANGE_ME_at_least_12'
export AIPF_PORT=8787
python3 -m aipf.server
```

Terminal 3, desk, from `frontend/`:

```bash
npm run dev -- --host 0.0.0.0 --port 5173
```

Browser: `http://127.0.0.1:5173`.

Another computer on the LAN can open `http://<this-computer>:5173`. The Vite process on this computer proxies `/api` to `127.0.0.1:8787`. The other computer still does not connect to PostgreSQL.

| Service | URL |
| --- | --- |
| Desk | `http://127.0.0.1:5173` |
| API | `http://127.0.0.1:8787` |
| PostgreSQL | `127.0.0.1:5432`, application role only, not from the browser |

Checklist:

- [ ] PostgreSQL accepts the application URL
- [ ] API stdout says `Database postgres`
- [ ] `curl -s http://127.0.0.1:8787/api/public/branding` returns `"ok": true`
- [ ] `http://127.0.0.1:5173` shows the sign-in form
- [ ] `director` can sign in with the seed password
- [ ] A patient search returns rows after seed (`GET /api/patients`)
- [ ] The desk receives SSE after sign-in (browser network panel, `text/event-stream`)
- [ ] A signed-in user with `health.view` can open `GET /api/system/health`
- [ ] An invoice or OT report PDF downloads only after sign-in

A fresh database can report overall health `DEGRADED` while the API is fine. The realtime check is written as `DEGRADED`, and "no backup yet" is also `DEGRADED`. Look at the Database and Local file storage lines.

---

## Authentication and first login

Sign-in is `POST /api/auth/login` with JSON:

```json
{"username": "director", "password": "the-seed-password", "workstation": "Reception"}
```

The response contains `token` and `user`. The desk stores the token in `sessionStorage` under `aipf-token` and sends `Authorization: Bearer <token>`. It is not a JWT. The `sessions` table stores the SHA-256 digest, the user id, workstation, IP, and expiry. A wrong password returns 401 `Those credentials were not accepted.` The message does not say whether the username exists.

Sessions last 16 hours and slide forward while the desk is used. `POST /api/auth/logout` revokes the token. A 401 clears the token in the browser.

`POST /api/auth/password` changes the signed-in user's password. The new password must be at least 8 characters. The seed password must be at least 12. Staff passwords set by an administrator also require at least 8 characters.

`POST /api/auth/stream-ticket` issues a 90-second token used only for the event stream.

Authorization is permission codes. The `admin` role is granted every code in `PERMISSIONS`. Other roles get the lists in `ROLE_MATRIX`. A request still fails if the permission is missing, even if the username looks like a director. There is no hidden admin bypass in `permit()`.

Record scope is separate from the permission code. Without `patient.view_all`, a doctor sees a patient only when they are linked as encounter doctor, queue doctor, admission doctor, operating surgeon, or prescribing doctor. A missing record and an out-of-scope record both return 404 `That record was not found.`

Frontend `can()` only hides navigation. The API checks again.

To add another developer account, sign in as someone with `user.manage` (the seeded `director` has it) and use Staff, or `POST /api/users`. Choose a role that already exists. The password in that request must be at least 8 characters.

---

## Roles and permissions

Seeded role codes:

| Code | Desk name in the seed | Typical use |
| --- | --- | --- |
| `admin` | Admin doctor | Every permission code. The seeded director also has the `doctor` role. |
| `doctor` | Doctor | Own queue, consultation, prescription, lab order, OT workflow, limited IPD. No `patient.view_all`. |
| `reception` | Reception | Registration, queue, documents, leads. Has `patient.view_all`. |
| `pharmacist` | Pharmacist | Dispense and stock. Has `patient.view_all`. |
| `billing` | Billing | Invoices, payments, refunds, adjustments. Has `patient.view_all`. |
| `nurse` | Nursing | Beds, admission support, OT pre-op and post-op notes. Has `patient.view_all`. |
| `lab` | Laboratory | Samples, results, reports. Has `patient.view_all`. Does not get OT approve unless you grant `ot.approve`. |

Change grants with `PUT /api/roles/:code/permissions` and permission `role.manage`. Send `{"permissions": ["code", ...]}`. The next request reloads permissions from the database. The user does not need a new login for a permission change to take effect on the API. The desk's `can()` updates when `/api/auth/me` is loaded again.

Do not add an `if role == "admin"` check. Add a permission code and grant it.

`patient.view_all` does not open documents. Document reads need `document.view`, and either `document.view_all`, or a clinical link, or being the uploader.

Queue changes without `queue.view_all` are limited to the caller's own queue entries.

---

## Daily workflow

```bash
git pull
```

**Not verified in this environment.**

If `backend/requirements.txt` changed:

```bash
python3 -m pip install -r backend/requirements.txt
```

If `frontend/package.json` or `package-lock.json` changed:

```bash
cd frontend
npm install
```

Start PostgreSQL, then the API, then the desk, as in [Run the complete system](#run-the-complete-system). Migrations run on API startup. Restart the API after pulling a new migration. You do not run a migrate command.

After a frontend-only change, Vite reloads the desk. After a Python change, stop the API process and start it again.

### Reset

There is no safe reset command in the repository.

- `POST /api/admin/clear-sample` removes seeded sample patients. It requires `config.manage`. It does not drop the schema and it does not reset passwords.
- Dropping a PostgreSQL database you created for yourself is a database-administration action, not an application command. Do not point that action at a database that has real patients.
- Do not delete `data/hospital.db` as a routine step. `start-host.sh` uses that file when no URL is set.

---

## Testing

From `backend/`:

```bash
python3 -m pytest tests/test_flows.py tests/test_phase0.py -q
```

`test_flows.py` opens a temporary SQLite file. It does not use `AIPF_DATABASE_URL`.

`test_phase0.py` always runs the SQLite migration check. Its PostgreSQL checks run only when `AIPF_TEST_POSTGRES` is a PostgreSQL URL.

There is no `npm test`.

A secret scan, from `backend/`:

```bash
python3 -m aipf.secret_scan
```

Expected last line: `secret scan passed`.

---

## Acceptance and regression tests

These files exist:

| File | What it covers | PostgreSQL |
| --- | --- | --- |
| `tests/test_phase0.py` | Migrations, stock concurrency, foreign keys | PostgreSQL section skips unless `AIPF_TEST_POSTGRES` is set |
| `tests/test_phase1.py` | Permissions, sessions, record scope | HTTP matrix skips unless `AIPF_TEST_POSTGRES` or `AIPF_DATABASE_URL` is PostgreSQL. `PHASE1_REQUIRE_POSTGRES=1` makes the skip a failure. |
| `tests/test_phase2.py` | Queue and clinical HTTP | Same pattern, `PHASE2_REQUIRE_POSTGRES` |
| `tests/test_phase3.py` | Pharmacy HTTP | Same pattern, `PHASE3_REQUIRE_POSTGRES` |
| `tests/test_phase4.py` | Billing HTTP | Fails if `AIPF_TEST_POSTGRES` is missing |
| `tests/test_phase5.py` | Laboratory HTTP | Fails if `AIPF_TEST_POSTGRES` is missing. Also reads `/tmp/aipf_pg_url` if the variable is empty. Prefer the variable. |
| `tests/test_phase6.py` | IPD HTTP | Same as Phase 5 |
| `tests/test_phase7.py` | OT HTTP | Same as Phase 5. Writes `PHASE-7-ACCEPTANCE-REPORT.md` from the run. |
| `tests/test_flows.py` | Cross-module rules on temporary SQLite | No PostgreSQL URL required |

Run the set from `backend/`:

```bash
export AIPF_TEST_POSTGRES='postgresql://aipf:your-password@127.0.0.1:5432/postgres'
python3 -m pytest tests/test_phase0.py tests/test_phase1.py tests/test_phase2.py tests/test_phase3.py tests/test_phase4.py tests/test_phase5.py tests/test_phase6.py tests/test_phase7.py tests/test_flows.py -q
```

The phase HTTP tests start their own API processes on ports 8794, 8795, 8796, 8797, and on a free port at or above 8798, 8799, or 8817. They do not use the desk. They do not need port 5173.

Do not point `AIPF_TEST_POSTGRES` at a production database. The tests drop and recreate databases, seed them, and issue concurrent writes. A URL that can do that against production is a production incident.

Phase 4, 5, 6, and 7 fail closed when PostgreSQL is not configured. Do not skip them to make a local run look green, and do not weaken a failing assertion.

---

## Test database

`AIPF_TEST_POSTGRES` is an administration URL. The tests connect to it, then:

- `DROP DATABASE` / `CREATE DATABASE` for `aipf_phase0`, `aipf_stock`, `aipf_phase1`, `aipf_phase2`, `aipf_phase3`, `aipf_phase4`, `aipf_phase5`, `aipf_phase6`, `aipf_phase7`, and `aipf_p7smoke`
- start a temporary API against that new database
- seed it with a random `AIPF_SEED_PASSWORD` generated inside the test
- drop the database again

They do not migrate your `aipf_dev` database unless you named it one of those names. Name the development database something else anyway.

SQLite tests use `tempfile` directories and delete them. They do not open `data/hospital.db`.

**Never run these tests against production.**

Phase 5, 6, and 7 will also read a PostgreSQL URL from `/tmp/aipf_pg_url` if `AIPF_TEST_POSTGRES` is unset. That file is not a project configuration standard. Do not put a production URL there.

---

## Manual smoke test

Sign in as `director` for the admin checks, then as the desk user named in each section. The seed password is the same for all of them until someone changes it.

Authentication:

- [ ] `director` signs in
- [ ] a wrong password is rejected
- [ ] sign out, then call an authenticated route and get 401
- [ ] `lab` cannot open a route that requires a permission the lab role does not have

Patient and OPD:

- [ ] Register a patient
- [ ] Search by name and by phone
- [ ] Two patients may share a phone; search must not merge them
- [ ] Create an encounter and see a queue token

Pharmacy:

- [ ] Look up a seeded barcode, for example `AIPFAZI500`, at `GET /api/pharmacy/lookup?code=AIPFAZI500`
- [ ] Dispense from a finalized prescription
- [ ] Stock ledger shows the movement; the on-hand quantity changes once

Billing:

- [ ] Open a draft invoice
- [ ] Finalize it
- [ ] Record a payment with an `Idempotency-Key`
- [ ] Download the invoice PDF while signed in

Laboratory:

- [ ] Order a test on an encounter
- [ ] Collect a sample
- [ ] Enter a result
- [ ] Verify it
- [ ] Generate the report

IPD:

- [ ] Create an admission
- [ ] Assign a bed
- [ ] Move the bed
- [ ] Discharge

OT:

- [ ] Create a theatre and a procedure from the desk or the API. Do not expect `OT-1` to exist in code.
- [ ] Request, approve, schedule
- [ ] Record pre-op, including consent and the required checklist item
- [ ] Start, record intra-op, move to recovery, complete
- [ ] Post the charge and confirm the invoice line
- [ ] Generate the operation report and download it twice; the bytes should match

---

## API development

The route table is `build_routes()` in `backend/aipf/server.py`. A grouped catalog is in [API.md](API.md).

A route is registered as method, path, function, permission, whether authentication is required, and whether the handler runs inside a transaction. `POST`, `PUT`, `PATCH`, and `DELETE` use a transaction unless the route passes `tx=False`.

Add a route only after the domain function and the permission code exist. Do not authorize with a role name.

Useful local calls:

```bash
curl -s http://127.0.0.1:8787/api/public/branding
```

```bash
curl -s -X POST http://127.0.0.1:8787/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"director","password":"the-seed-password","workstation":"Docs"}'
```

```bash
curl -s http://127.0.0.1:8787/api/auth/me \
  -H "Authorization: Bearer THE_TOKEN"
```

File and event URLs also accept `?token=` because a browser cannot set `Authorization` on an `<img>` or `EventSource` request. Prefer the header for JSON calls.

---

## Database development

```text
domain service
    -> repository function in backend/aipf/repo
    -> PostgreSQL
```

Do not execute SQL from `clinical.py`, `pharmacy.py`, `billing.py`, `laboratory.py`, `wards.py`, `theatre.py`, or `system.py`. Those modules call repository functions. Locks and overlap checks belong in the repository.

To add a table or column:

1. Add a new file `backend/aipf/migrations/0019_short_name.sql` (use the next free number).
2. Put PostgreSQL-only constraints in `0019_short_name.postgres.sql` if SQLite cannot run them.
3. Add repository functions for the new SQL.
4. Call those functions from the domain service.
5. Restart the API against a development database and confirm `schema_migrations` gained a row.
6. Add a test. If the rule is a concurrency rule, test it on PostgreSQL.

Do not edit `0001` through `0018` after they have been applied. A checksum mismatch refuses startup.

Foreign keys for the PostgreSQL baseline are listed in `backend/aipf/constraints.py`. `schema_compile.py` emits `ALTER TABLE ... ADD CONSTRAINT` for that list. Do not add a foreign key there for a column that points at more than one kind of id. A wrong foreign key is worse than a missing one. OT workflow tables added in `0017` are not in that list; their integrity is enforced in the domain and repository code and in the PostgreSQL checks in `0018`.

Indexes go in the new migration, not in an old one.

The idempotency table is `idempotency_keys`, created by migration `0003`. Reuse it. Do not add a second idempotency system for one module.

---

## Storage and documents

`get_storage()` returns `LocalStorageProvider` rooted at `data/documents`. There is no storage environment variable and no second provider in the repository.

Domain code asks the provider to save and read bytes by a relative key. Keys must not be absolute, must not contain `..`, and must not contain backslashes.

The `documents` table stores metadata: patient, entity, type, title, filename, storage key (`stored_name`), MIME type, size, SHA-256 checksum, uploader, and time. `GET /api/documents/:id/file` checks `document.view` and record scope, then writes the bytes. It does not return a filesystem path for the browser to open.

Deactivate a document with `POST /api/documents/:id/deactivate`. That is not a silent physical delete of the clinical record.

Uploaded logo files go to `data/branding/` through the branding handler, not through `StorageProvider`. The public logo URL is `GET /api/public/logo`.

---

## Realtime

The desk uses server-sent events, not WebSocket.

1. After sign-in, the desk calls `POST /api/auth/stream-ticket`.
2. It opens `EventSource` on `/api/events?token=<stream ticket>`.
3. The server sends `data: {"event": "...", "data": {...}}`.
4. If the event has `patient_id`, the server drops it unless this user can view that patient.
5. If the event has `permission`, the server drops it unless this user holds that code.
6. The desk treats a message as "refresh now". It does not apply the payload as a local database.

The connection is kept with a 15-second heartbeat (`ping` when the queue is empty). The hub is in memory. Restarting the API drops every subscriber. A second API process does not see the first process's events.

Event names published by the current code include `patient.updated`, `queue.updated`, `clinical.updated`, `prescription.finalized`, `pharmacy.dispensed`, `inventory.updated`, `invoice.updated`, `lab.updated`, `admission.updated`, `beds.updated`, `ipd.admission.created`, `ipd.bed.assigned`, `ipd.bed.moved`, `ipd.bed.released`, `ipd.discharge.completed`, `ot.updated`, `document.updated`, `master.updated`, `staff.updated`, `notification.updated`, `leads.updated`, and `backup.updated`.

To debug: open the browser network panel, select the `events` request, and confirm `text/event-stream`. Then perform an action in another session. Do not poll the list endpoints once a second as a substitute.

---

## PDF and reports

`backend/aipf/pdf.py` writes PDF bytes. Callers include invoice, prescription, laboratory report, discharge summary, and operation report.

Pages for a full bill, discharge summary, laboratory report, and operation report use A4 (595.28 by 841.89). The writer draws a white page. Text is PDF text, not a screenshot.

Generate a report from rows the service has already stored. Do not recalculate a bill total, tax, or OT price inside the PDF. Reprint of an unchanged stored document must return the same bytes and must not insert another document, another audit row, or another charge. A correction is a new document, not a reprint.

Download through the API while signed in, for example `GET /api/invoices/:id/pdf` or `GET /api/ot/:id/report`. Check the file with a PDF reader. The health check's PDF probe only confirms the writer can emit a `%PDF` header.

---

## Master data

Administrators with `master.manage` edit lists at `/admin/master` and ` /api/master/:type`.

Seeded `master_items` types include `department`, `patient_category`, `payment_mode`, `deposit_type`, `tax_rate`, `document_type`, `condition`, `procedure`, and `unit`.

Separate tables, also edited through the API rather than hardcoded names:

- OPD types (`/api/opd/types`)
- services (`/api/services`)
- laboratory tests (`/api/lab/tests`)
- pharmacy products, packaging, and barcodes (`/api/inventory/...`)
- wards, rooms, and beds (`/api/wards`, `/api/rooms`, `/api/beds`)
- OT theatres, procedures, and checklist items (`/api/ot/theatres`, `/api/ot/procedures`, `/api/ot/checklist`)

Deactivate a referenced master. Do not physically delete it. Theatre and procedure delete routes do not exist. `POST /api/master/:type/:id/deactivate` is the master-list path.

Seeded sample patients are not master data. Clear them later with `POST /api/admin/clear-sample` if you are about to start a live register. Keep departments, beds, the formulary, and the price lists.

Set the hospital phone under Branding before the first printed bill. The logo on a new document is the uploaded seal.

---

## Security

- Do not commit `.env`, database URLs, or passwords. There is no root `.gitignore`, so this is a manual rule.
- Do not put a password in source. `AIPF_SEED_PASSWORD` is the seed channel. `python3 -m aipf.secret_scan` fails the process if it finds a committed credential pattern.
- Do not bypass authentication in development. The API has no development backdoor.
- Frontend permission checks are not authorization.
- Do not trust a patient id from the browser without `access.guard_patient` or the equivalent record-scope check.
- Do not return filesystem paths from the API.
- Do not run the phase tests against production.
- Do not log the bearer token or `AIPF_DATABASE_URL`.

The repository does not define a security-reporting address. Report a vulnerability to the hospital's technical owner through the channel your team already uses. Do not commit the secret or a working exploit to fix it.

---

## Backup and restore

### What works on SQLite

With a `sqlite:///` URL, a user with `backup.create` can `POST /api/backups`. The archive is a zip under `data/backups/`. It includes the SQLite database file and document files. Verify with `POST /api/backups/:id/verify`. Restore with `POST /api/backups/:id/restore` and JSON `{"confirm": "RESTORE AIPF"}`. Restore replaces `data/hospital.db` and asks you to restart the API. A safety zip is written first.

Seeded schedule settings are `backup_enabled=1`, `backup_time=02:00`, retention 30 days, maximum 30 archives. The worker inside the API process is what runs that clock. If the API is not running at 02:00, the clock does not run.

### What does not work on PostgreSQL

`POST /api/backups` and `POST /api/backups/:id/restore` return 501 on PostgreSQL. No database is replaced. Cloud upload is inside that same function, so it is also not reached on PostgreSQL.

Cloud backup is **not currently a production-ready PostgreSQL feature.** Local PostgreSQL backup is **not currently available** in the application. Use PostgreSQL's own backup tools for a production database. Those tools are not wrapped by this repository, and this document does not invent a wrapper.

Deleting a backup archive requires `backup.restore` and `DELETE /api/backups/:id`. That deletes an archive, not clinical rows.

---

## Health and troubleshooting

`GET /api/system/health` requires `health.view`. Component names include Application, API, Database, Database latency, Database pool, Local file storage, Document storage, File permissions, Disk capacity, CPU, RAM, Realtime, Queue worker, PDF engine, Backup scheduler, Local backup, Cloud backup, OpenWA, Website leads, Scheduled jobs, and Configured ports.

`GET /api/system/health/:name` accepts aliases `database`, `storage`, `whatsapp`, `backup`, `realtime`, `leads`, and `pdf`.

There is no public health URL.

| Problem | Likely cause | Check | Fix |
| --- | --- | --- | --- |
| `No database configured` | `python3 -m aipf.server` with no URL | `echo "$AIPF_DATABASE_URL"` in that same shell | Export a PostgreSQL URL, or use `start-host.sh` only if you intend to use SQLite |
| `PostgreSQL is configured but unavailable` | Server down, wrong host, wrong password, or `pg_hba` rejection | `psql` with the same URL | Start PostgreSQL. Do not switch the URL to SQLite to hide the failure in production. |
| `checksum mismatch` | An applied migration file was edited | The error names the version and both hashes | Restore the file or add a new migration. Do not update `schema_migrations` by hand. |
| Port 8787 already in use | Another API, or a leftover test | The process listening on 8787 | Stop it, or set `AIPF_PORT`. If you change the port, the Vite proxy still calls 8787 until you edit `vite.config.ts`. |
| Port 5173 already in use | Another Vite | Vite's `strictPort` error | Stop the other process. |
| Desk loads, API calls fail | API not on 8787, or proxy error | `curl http://127.0.0.1:8787/api/public/branding` and `curl http://127.0.0.1:5173/api/public/branding` | Start the API on 8787. |
| Sign-in says credentials were not accepted | Wrong password, or this database was seeded with a different password | `SELECT COUNT(*) FROM users;` | Use the original seed password, or use a new empty database so seed runs again. |
| Health is 401 | No token, or the token expired | Call `/api/public/branding` first | Sign in as `director` and call health with the bearer token. |
| Health overall is `DEGRADED` | Realtime is always reported `DEGRADED`; a new database has no backup | Read the Database line | A `HEALTHY` database line means the connection works. |
| `Migration ... failed and was not recorded` | SQL error; the transaction rolled back | The exception text | Fix the new migration file before it is applied. Do not mark it applied by hand. |
| Document download 404 | Missing, inactive, or outside record scope | Same message for both | Sign in as a user who may see that patient, or as a user with `document.view_all`. |
| Permission denied | The role lacks the code | `GET /api/auth/me` and look at `permissions` | Grant the code. Do not special-case the role name. |
| Schema version 17 on PostgreSQL | Startup did not apply `0018`, or you are looking at SQLite | `SELECT MAX(version) FROM schema_migrations;` | Restart the API against the PostgreSQL URL. SQLite staying at 17 is expected. |

---

## Windows

The repository has no PowerShell script and no Windows installer. `start-host.sh` is bash. On Windows, use two PowerShell windows, or run the bash script from Git Bash or WSL.

**PowerShell form was not verified in this environment.** The programs are the same ones verified on Linux.

```powershell
python --version
node --version
npm --version
psql --version
```

Use whichever command runs Python 3.10 or newer. On this Linux host that command is `python3`.

```powershell
cd backend
python -m pip install -r requirements.txt
$env:AIPF_ENV = "development"
$env:AIPF_DATABASE_URL = "postgresql://aipf:your-password@127.0.0.1:5432/aipf_dev"
$env:AIPF_SEED_PASSWORD = "CHANGE_ME_at_least_12"
$env:AIPF_PORT = "8787"
python -m aipf.server
```

```powershell
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 5173
```

PostgreSQL on Windows is usually a service started from Services or `pg_ctl`. That start command was **not verified in this environment.** After it is running, the `CREATE ROLE` / `CREATE DATABASE` SQL is the same. `psql` must be on `PATH`.

If `npm` or `python` is not found, the installer did not add it to `PATH`. Open a new terminal after installing.

Port conflicts are the same as on Linux: 5432, 8787, and 5173.

A virtual environment, if you choose to make one, activates with `.\.venv\Scripts\Activate.ps1`. The repository does not require that.

---

## Production and development

| | Development | Production |
| --- | --- | --- |
| `AIPF_ENV` | `development` or unset | `production` |
| Database | PostgreSQL URL, or an explicit `sqlite:///` URL | PostgreSQL URL required. Missing URL or a down server: startup fails. SQLite is not opened. |
| `start-host.sh` | If the URL is empty, sets SQLite to `data/hospital.db` | Refuses to start when the URL is empty. If the URL is set, it still launches Vite's dev server. |
| Secrets | Seed password in the shell only | Not the seed password. Create staff through the API and do not commit the URL. |
| CORS | Reflects the request `Origin`, or `*` if there is no Origin | Same code. There is no allow-list variable. |
| Storage | `data/documents` on the API host | Same. There is no cloud document store. |
| Logging | stderr plus `app_logs` | Same. No log-level variable. |
| Backups | SQLite zip backup works. PostgreSQL application backup does not. | Use PostgreSQL backup tools. The in-app backup returns 501. |
| Migrations | Applied on startup | Applied on startup. Do not edit an applied file. |
| Authentication | Seeded accounts | Change those passwords before real use, or do not seed sample patients on the live database. |
| Desk | Vite on 5173 | `npm run build` can fill `frontend/dist`, which the API can serve. That build was not verified here, and `start-host.sh` does not run it. |

`AIPF_ENV=production` with a SQLite URL was verified to raise `SQLite was not used`.

---

## Contribution rules

- Add a new migration. Do not edit an applied one.
- Keep SQL in `backend/aipf/repo/`.
- Put business rules in the domain module, not in the React page and not in the repository.
- Authorize with permission codes.
- Enforce record scope on the server.
- Add a test for a business invariant. Test a concurrency rule on PostgreSQL.
- Do not delete audit rows. There is no audit delete route.
- Do not add `ot_invoices`, `lab_payments`, or another financial table. Billing is the financial source of truth.
- Do not write document bytes outside `StorageProvider`.
- Do not hardcode theatre names, procedure names, ward names, or fee amounts in domain logic. Read them from the database.
- Do not weaken `tests/test_phase0.py` through `tests/test_phase7.py` to make a change pass.

---

## How to add a feature

1. Read the domain module that already owns the workflow.
2. Name the entities and the status transitions. The server owns transitions. Client JSON must not set a completed status.
3. Add a new migration file. Include a PostgreSQL check when the column has a closed set of values.
4. Add repository functions. Put locks there if two requests can conflict.
5. Add the domain rules. Reject a foreign patient, encounter, or admission. Return the same not-found message for missing and out-of-scope records.
6. Add or reuse a permission code. Grant it in `ROLE_MATRIX` only for roles that should have it on a new database. `ensure_default_grants()` adds new codes to roles that already exist.
7. Write an audit row for the change. Do not provide a delete for that audit.
8. Publish an event if an open desk must refresh. Include `patient_id` and, when the event is module-specific, `permission`.
9. Register the route in `server.py`.
10. Add the screen in `frontend/src/pages/` and a permission-gated nav item if it is a new desk.
11. Add tests. Use a throwaway database.
12. Run the phase files that cover the modules you touched, plus `tests/test_flows.py`.
13. If the rule can race, run it on PostgreSQL with two concurrent requests.
14. Update this file only if a command, port, or environment variable changed.

---

## Verification of this document

Checked in this environment while writing this file:

| Check | Result |
| --- | --- |
| `python3 -m pip install -r backend/requirements.txt` | Installed psycopg 3.3.6 |
| `npm install` in `frontend/` | Added 35 packages |
| `npm run lint` | Exit 0, 12 warnings, 0 errors |
| `npm run dev -- --host 0.0.0.0 --port 5173` | Vite v8.3.1 on port 5173 |
| PostgreSQL 17.11 cluster start and `psql` connection | Connected as the application role |
| API startup against that empty database | Listening on `0.0.0.0:8787`, dialect `postgres`, schema version 18, 10 users |
| `GET /api/public/branding` | 200, name AIPF Mission Hospital |
| `POST /api/auth/login` as `director` | 200 |
| `GET /api/auth/me` | 200 |
| `GET /api/patients?limit=2` | 200, two seeded patients |
| `GET /api/system/health` with a token | 200. Database `HEALTHY`. Overall `DEGRADED` as described above. |
| `GET /api/system/health` without a token | 401 |
| Desk proxy `http://127.0.0.1:5173/api/public/branding` | 200 |
| Missing `AIPF_DATABASE_URL` | `No database configured` |
| `AIPF_ENV=production` with a SQLite URL | Refused. SQLite was not used. |
| `python3 -m pytest tests/test_flows.py tests/test_phase0.py -q` | 14 passed |
| `python3 -m pytest tests/test_phase0.py::test_postgres_constraints_and_copy` with `AIPF_TEST_POSTGRES` | 1 passed |
| Full `tests/test_phase0.py` through `tests/test_phase7.py` plus `tests/test_flows.py` with `AIPF_TEST_POSTGRES` | 22 passed |
| `python3 -m aipf.secret_scan` | `secret scan passed` |

Not verified in this environment:

- `git clone`
- Windows service start, PowerShell, and `psql` on Windows
- `npm run build`
- `npm run preview`
- `python3 -m aipf.pgcopy`
- A production host with a real off-site backup
