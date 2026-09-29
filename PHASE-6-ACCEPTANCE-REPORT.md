# PHASE 6 ACCEPTANCE REPORT

Decision: PHASE 6 ACCEPTED

Phase 6 inpatient stay only. Phases 0–5 were not reopened except for the schema-version assertion required by the new migration.
Phase 4 remains the only financial source of truth. No inpatient payment, invoice, or refund table was added.

Gate: real HTTP against a throwaway PostgreSQL database. The database URL is not recorded here.
Schema version observed: 18.
Checks recorded: 105. Checks failed: 0.

## 1. Patient, encounter, admission, stay, ward, room, bed, movement, charge, and discharge stay separate

Result: PASS. 2 of 2 checks passed.

- PASS: admission without a bed stays requested
- PASS: charge rows are not payment rows

## 2. Patient identity is the patient id, not the phone

Result: PASS. 3 of 3 checks passed.

- PASS: patient is created by id
- PASS: shared phone does not merge patients
- PASS: admission cannot be created from a phone number

## 3. One patient can have many admissions over time

Result: PASS. 1 of 1 checks passed.

- PASS: the same patient can be admitted again after discharge

## 4. One open admission is a PostgreSQL constraint

Result: PASS. 3 of 3 checks passed.

- PASS: a second open admission is rejected
- PASS: open admission is a partial unique index
- PASS: PostgreSQL rejects a second open admission without the application

## 5. Status transitions are enforced on the server

Result: PASS. 7 of 7 checks passed.

- PASS: client status does not discharge a new admission
- PASS: client status is ignored
- PASS: discharge pending keeps the stay open
- PASS: pending discharge does not free the bed
- PASS: an admitted stay cannot be assigned as if it were requested
- PASS: a requested admission can be cancelled without deletion
- PASS: a discharged admission cannot be discharged again

## 6. Encounter must belong to the same patient

Result: PASS. 5 of 5 checks passed.

- PASS: encounter belongs to the patient
- PASS: second encounter is separate
- PASS: another patient's encounter is not attached
- PASS: missing and foreign encounters look the same
- PASS: unknown doctor is not attached

## 7. Wards, rooms, beds, and types come from the database

Result: PASS. 6 of 6 checks passed.

- PASS: ward names are not hardcoded in the inpatient module
- PASS: ward, room, and bed are created from the request
- PASS: created ward type is returned from the database
- PASS: duplicate ward code is rejected
- PASS: duplicate room name in a ward is rejected
- PASS: room cannot be attached to a missing ward

## 8. Referenced masters are deactivated, not deleted

Result: PASS. 4 of 4 checks passed.

- PASS: wards, admissions, and movements have no delete route
- PASS: a referenced ward is deactivated
- PASS: deactivation does not remove the historical admission
- PASS: there is no ward delete

## 9. Beds keep a permanent id

Result: PASS. 1 of 1 checks passed.

- PASS: bed id is unchanged after release

## 10. Bed status is not an arbitrary client string

Result: PASS. 1 of 1 checks passed.

- PASS: unknown bed status is rejected

## 11. A blocked bed cannot be assigned

Result: PASS. 2 of 2 checks passed.

- PASS: bed can be blocked by a known status
- PASS: a blocked bed cannot be assigned

## 12. One bed cannot have two active occupants

Result: PASS. 2 of 2 checks passed.

- PASS: assigned bed is occupied by one admission
- PASS: one current occupant is a partial unique index

## 13. One admission cannot have two current beds

Result: PASS. 1 of 1 checks passed.

- PASS: one current bed pointer is the same bed index

## 14. Assignment, movement, and discharge release are one transaction

Result: PASS. 2 of 2 checks passed.

- PASS: assignment occupies the selected bed
- PASS: movement changes the current bed

## 15. Bed history is append-only

Result: PASS. 1 of 1 checks passed.

- PASS: movement is appended

## 16. Concurrent admission to one bed yields one success and one conflict

Result: PASS. 3 of 3 checks passed.

- PASS: race setup admission exists
- PASS: two patients and one bed produce one success and one conflict
- PASS: the contested bed has one occupant

## 17. Concurrent movement leaves one current bed and no stale occupied bed

Result: PASS. 3 of 3 checks passed.

- PASS: the previous bed is not left occupied
- PASS: concurrent movement leaves one current bed
- PASS: the bed that was left is not occupied by the moved admission

## 18. Concurrent discharge yields one logical discharge

Result: PASS. 1 of 1 checks passed.

- PASS: concurrent discharge has one success

## 19. The same idempotency key is one admission, one assignment, and one discharge

Result: PASS. 3 of 3 checks passed.

- PASS: same admission key returns the same admission
- PASS: same assignment key does not create a second assignment
- PASS: same discharge key returns the discharged admission

## 20. Bed charges use the existing billing engine only

Result: PASS. 2 of 2 checks passed.

- PASS: service charge is an invoice line
- PASS: service price comes from the master, not the client

## 21. Historical bed rates are snapshotted

Result: PASS. 3 of 3 checks passed.

- PASS: assignment snapshots the room rate and ignores a client rate
- PASS: admission-day bed line uses the room rate
- PASS: later service price does not rewrite the line

## 22. The same admission, bed, and period is not billed twice

Result: PASS. 3 of 3 checks passed.

- PASS: the admission day is not billed a second time
- PASS: concurrent generation of the same period creates one line
- PASS: one charge per period is a partial unique index

## 23. Moving to a higher rate does not reprice earlier lines

Result: PASS. 2 of 2 checks passed.

- PASS: moving from 1000 rupees to 2000 rupees does not reprice the earlier line
- PASS: the later period uses the new rate

## 24. Discharge releases the bed

Result: PASS. 1 of 1 checks passed.

- PASS: discharge does not leave the last bed occupied

## 25. Due and settlement stay on the Phase 4 invoice

Result: PASS. 6 of 6 checks passed.

- PASS: billing user can sign in
- PASS: invoice total is the server total
- PASS: billing finalizes the inpatient invoice
- PASS: inpatient staff cannot settle the bill
- PASS: settlement uses the invoice payment path
- PASS: finalized inpatient invoice rejects a direct edit

## 26. Discharge summary is an A4 document

Result: PASS. 4 of 4 checks passed.

- PASS: discharge summary is a PDF
- PASS: page size is A4
- PASS: page is white and numbered
- PASS: rupee amount is drawn from the stored charges

## 27. Reprint is byte-identical and does not mutate records

Result: PASS. 4 of 4 checks passed.

- PASS: reprint bytes are identical
- PASS: generating the unchanged summary does not create a second document
- PASS: reprint does not add a document or a duplicate audit
- PASS: reprint does not mutate the admission or the patient

## 28. Discharge document uses StorageProvider

Result: PASS. 2 of 2 checks passed.

- PASS: discharge document is stored without a filesystem path
- PASS: document bytes are read through storage

## 29. Document retrieval is authorized on the server

Result: PASS. 3 of 3 checks passed.

- PASS: document retrieval is refused outside record scope
- PASS: missing and hidden documents look the same
- PASS: the admitting doctor can read the stored summary

## 30. Timeline and bed availability respect record scope

Result: PASS. 8 of 8 checks passed.

- PASS: admitting doctor can sign in
- PASS: second doctor can sign in
- PASS: an occupied bed does not reveal an out-of-scope patient
- PASS: another doctor cannot open the admission by changing the id
- PASS: missing and hidden admissions look the same
- PASS: timeline includes the stay and the movement
- PASS: the other doctor does not receive the timeline
- PASS: bed availability does not reveal an out-of-scope name

## 31. Authorization uses permission codes, not role names

Result: PASS. 8 of 8 checks passed.

- PASS: director can sign in
- PASS: nurse can sign in
- PASS: pharmacist can sign in
- PASS: authorization source does not branch on a role name
- PASS: pharmacist cannot admit
- PASS: permission change is visible without changing the role name
- PASS: movement requires a permission code
- PASS: a granted move code is enforced by the server

## 32. Audit has no delete route

Result: PASS. 1 of 1 checks passed.

- PASS: audit has no delete route

## 33. Schema change is a new versioned migration

Result: PASS. 2 of 2 checks passed.

- PASS: schema version includes the phase 6 postgres migration
- PASS: phase 6 did not edit an earlier migration

## 34. Locking and idempotency stay in the existing repository

Result: PASS. 3 of 3 checks passed.

- PASS: domain module does not contain a SQL statement
- PASS: occupancy lock is in the repository
- PASS: idempotency uses the existing key table

## 35. No second invoice, payment, or refund system

Result: PASS. 2 of 2 checks passed.

- PASS: no inpatient payment, invoice, or refund table exists
- PASS: inpatient module does not record payments

## Gate evidence

The gate started the hospital server and called it over HTTP. Occupancy and charge races used two concurrent requests.
PostgreSQL indexes and the rejected second open admission were read from the throwaway database after the HTTP calls.
The database URL is not included.

## Regression

Phase 0 expects SQLite schema 17. 0017 is shared. 0016 and 0018 are PostgreSQL-only.
Phase 5 expects PostgreSQL schema 18 because later migrations are applied with the existing ones.
Admission without a bed still returns REQUESTED. The room rate, not the client rate, is snapshotted.

## Remaining non-blocking limitations

ADMITTED remains the occupied status. It was not renamed to ACTIVE, because Phase 4, Phase 5, and the current desk already use ADMITTED.
DISCHARGE_PENDING and CANCELLED were added. A client cannot choose either status by sending a status string.
