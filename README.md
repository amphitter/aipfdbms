# AI-PF Hospital Operations System

Local-first operations software for AIPF Mission Hospital, Shahpurpur, Fatehpur Beri, New Delhi 110074.

Staff browsers talk only to the hospital application. They never connect to the database. Patient records, documents, bills, and stock stay on this computer unless an administrator explicitly turns on WhatsApp, website leads, or cloud backup.

## New developer

Follow [DEVELOPER_SETUP.md](DEVELOPER_SETUP.md) from the top if you just cloned the repository. It has the real ports, environment variables, PostgreSQL setup, migrations, first sign-in, and tests. The route list is in [API.md](API.md).

`./start-host.sh` is a host shortcut. If `AIPF_DATABASE_URL` is not set, that script uses the local SQLite file. `python3 -m aipf.server` does not. Production must set `AIPF_ENV=production` and a PostgreSQL URL. It does not fall back to SQLite.

## Start the hospital server

From this folder:

```bash
./start-host.sh
```

- API: `http://<this-computer>:8787`
- Desk: `http://<this-computer>:5173` during development

Other PCs on the LAN open the desk address. The internet is not required for registration, OPD, pharmacy, billing, wards, or local backup.

## First sign-in

Usernames are created by the seed. The password is not stored in this repository. Set `AIPF_SEED_PASSWORD` in the environment before the first seed, then sign in with that value and change it under Staff.

## What is already configured

Departments, OPD cards (including the 5-day card), services, lab tests, wards and beds, a house formulary with batches, and an opening-day workload so each desk has something to do. Clear sample patients from the database only after you are ready to start the live register; the master data should stay.

Set the hospital phone under Branding before the first printed bill. The logo on new documents is the uploaded seal, not a hardcoded file in the bill renderer.

## Architecture

```
Browser desks  →  application API  →  service layer  →  local database
                                      document store
                                      realtime events
                                      backup / health / WhatsApp / leads
```

Production database is PostgreSQL on the hospital host, not exposed to client PCs. Set `AIPF_ENV=production` and `AIPF_DATABASE_URL` to a PostgreSQL URL before starting the API. Install `backend/requirements.txt` first. If that URL is missing or the server is down, startup fails. It does not open SQLite.

Development may use SQLite only when `AIPF_DATABASE_URL` is an explicit `sqlite:///` URL. Schema changes go through the startup migration runner. A SQLite file can be copied into an empty migrated PostgreSQL database with `python -m aipf.pgcopy` from the `backend` directory; the copy refuses to run if the target already has patients, and it does not delete the SQLite file.

External systems sit behind providers:

- WhatsApp: OpenWA, only from the backend
- Website leads: optional MongoDB sync into the local lead table
- Cloud backup: S3-compatible (S3, R2, B2, MinIO), verified by size and checksum

If those are down, local work continues. Failed WhatsApp sends retry a finite number of times and never block a bill.
