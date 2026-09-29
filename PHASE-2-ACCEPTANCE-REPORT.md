# Phase 2 acceptance

Decision: **PHASE 2 ACCEPTED**

Phase 0 and Phase 1 were not reopened. Phase 3 was not started. `data/hospital.db` was not opened for writing. It is still 569344 bytes.

The workflow ran through `python -m aipf.server` against a throwaway PostgreSQL database. That database was dropped afterward. No password or database URL was written into the repository.

## A–S

| Item | Result | Evidence |
| --- | --- | --- |
| A. Patient model | PASS | Patient id is permanent and is not the phone number. Edit kept the same id. A patient, an encounter, and an invoice remain different records. |
| B. Search and existing detection | PASS | Searching the shared Sharma phone returned the family, not one merged record. Creating another person on that phone without confirmation returned 409 `possible_match`. Explicit confirmation created a new patient and left Rajesh Sharma unchanged. |
| C. OPD / encounter | PASS | A return visit created a second encounter for the same patient. An unknown patient was rejected. A visit with an unknown OPD type rolled back and left no patient and no encounter. |
| D. Doctor assignment | PASS | The visit stored the selected doctor. A doctor calling assign on another encounter was forbidden. |
| E. Queue | PASS | Registration created a queue entry. Status values are the existing controlled set. Jumping from waiting straight to completed was rejected. A doctor cannot open or change another doctor's queue by changing `doctor_id` or `queue_id`. |
| F. Queue concurrency | PASS | Six simultaneous registrations received six different tokens. Sequence numbers are allocated with one atomic update, so encounter and patient ids do not collide either. |
| G. Consultation | PASS | The assigned doctor created and updated the note. The previous diagnosis was kept in `consultation_revisions`. The other doctor was forbidden. Completing the visit completed the queue and the encounter. |
| H. Patient timeline | PASS | The assigned doctor saw both encounters and the consultation. The other doctor's timeline request returned 404. |
| I. Record-level security | PASS | Phase 1 patient, queue, and consultation rules still apply. Direct changes to `doctor_id`, `queue_id`, and `encounter_id` did not bypass them. |
| J. Realtime | PASS | The existing event stream delivered `queue.updated` with a patient id to reception. The same event was not delivered to a doctor who cannot see that patient. The payload has no clinical note. |
| K. Frontend workflow | PASS | Reception search, choose existing or confirm new, register the visit, and land on the queue. The doctor queue opens the encounter. Save and complete are separate actions. A browser was not driven; the pages call the APIs the HTTP workflow verified. |
| L. Database integrity | PASS | Encounter, queue, and consultation foreign keys remain. A day cannot issue the same token twice. An encounter cannot have two open queue rows. PostgreSQL checks the queue and encounter statuses. Phone is indexed, not unique. |
| M. Audit | PASS | Patient create, visit, queue create, and consultation create or update were present. The consultation note was not copied into the audit text. |
| N. Tests | PASS | `tests/test_phase2.py` passed. |
| O. HTTP / E2E | PASS | Reception search, new patient, visit, doctor queue, consultation, completion, and the other doctor's denial were all HTTP calls to the real server. |
| P. Phase 0 regression | PASS | `tests/test_phase0.py` passed, including the PostgreSQL copy check. |
| Q. Phase 1 regression | PASS | `tests/test_phase1.py` and `tests/test_flows.py` passed. `py_compile` and `python3 -m aipf.secret_scan` passed. |
| R. Remaining defects | PASS | No critical Phase 2 defect remains. Non-blocking notes are below. |
| S. Phase 2 decision | PASS | **PHASE 2 ACCEPTED** |

## What the workflow now guarantees

A patient is the permanent person. A visit is a new encounter. The encounter is not an admission and it is not the invoice, although registration still opens the existing draft bill so the visit can be billed later.

Phone is only a search key. Two people may share it. The server will not create the second person unless the desk confirms that the matches are someone else. A later visit selects the existing patient and opens a new encounter.

Queue position comes from a locked daily counter. A doctor without `queue.view_all` sees and changes only their own queue. A doctor without `consultation.manage_all` can write a consultation only on an encounter assigned to them.

## Non-blocking notes

- No browser was driven. The desk and consultation screens are the workflow above, not a visual redesign.
- Vitals are not part of the current product. None were invented.
- Events that do not carry `patient_id` can still reach any signed-in stream. Queue and consultation events now carry it and are filtered.
- Ruff and mypy were not run. They are still not installed.
- The live SQLite file was not migrated. A later startup applies `0006_queue_integrity.sql` and, on PostgreSQL, `0007_clinical_status_check.postgres.sql`.
