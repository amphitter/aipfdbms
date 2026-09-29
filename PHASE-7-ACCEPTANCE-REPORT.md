# PHASE 7 ACCEPTANCE REPORT

Decision: PHASE 7 ACCEPTED

Phase 7 operating theatre only. Phases 0–6 were not reopened except for the schema-version assertion required by the new migration.
Phase 4 remains the only financial source of truth. No OT payment, invoice, or refund table was added.

Gate: real HTTP against a throwaway PostgreSQL database. The database URL is not recorded here.
Schema version observed: 18.
Checks recorded: 111. Checks failed: 0.

## 1. Patient, encounter, admission, request, booking, theatre, procedure, team, pre-op, intra-op, post-op, and document stay separate

Result: PASS. 4 of 4 checks passed.

- PASS: request id is not the patient, encounter, or admission id
- PASS: booking id is separate from the case id
- PASS: team member is a separate record
- PASS: post-operative id is separate from the intra-operative id

## 2. Patient identity is the patient id, not the phone

Result: PASS. 2 of 2 checks passed.

- PASS: patient is created by id
- PASS: OT request cannot be created from a phone number

## 3. A foreign encounter is rejected

Result: PASS. 3 of 3 checks passed.

- PASS: encounter belongs to the patient
- PASS: another patient's encounter is not attached
- PASS: missing and foreign encounters look the same

## 4. A foreign admission is rejected

Result: PASS. 3 of 3 checks passed.

- PASS: second patient can be admitted
- PASS: another patient's admission is not attached
- PASS: missing and foreign admissions look the same

## 5. Missing and unauthorized OT records look the same

Result: PASS. 3 of 3 checks passed.

- PASS: second doctor can sign in
- PASS: an out-of-scope case looks like a missing case
- PASS: the list does not include the other doctor's case

## 6. Theatres come from the database

Result: PASS. 4 of 4 checks passed.

- PASS: theatre names are not hardcoded in the theatre module
- PASS: theatres are created from the request
- PASS: duplicate theatre code is rejected
- PASS: created theatre name is returned from the database

## 7. Procedures come from the database

Result: PASS. 3 of 3 checks passed.

- PASS: procedure price and admission rule come from the request
- PASS: duplicate procedure code is rejected
- PASS: renaming the procedure does not rewrite the requested name

## 8. Referenced masters are not deleted

Result: PASS. 4 of 4 checks passed.

- PASS: a theatre is not deleted
- PASS: a theatre can be deactivated and still read
- PASS: an inactive theatre cannot be booked
- PASS: there is no theatre delete route

## 9. Status transitions are enforced on the server

Result: PASS. 7 of 7 checks passed.

- PASS: a request cannot be scheduled before approval
- PASS: approval is a server transition
- PASS: start is rejected before the pre-operative step
- PASS: start moves the case into progress
- PASS: completion is rejected before recovery
- PASS: recovery follows the operative record
- PASS: completion is recorded by the server

## 10. Client JSON cannot force completed

Result: PASS. 2 of 2 checks passed.

- PASS: client status does not complete a new request
- PASS: status JSON cannot force completed

## 11. The accepted notes path still completes

Result: PASS. 2 of 2 checks passed.

- PASS: legacy notes still ask the billing engine for the configured fee
- PASS: performed still requires notes and notes still complete the case

## 12. The same theatre cannot hold two overlapping bookings

Result: PASS. 3 of 3 checks passed.

- PASS: schedule creates a booking
- PASS: overlapping theatre booking is rejected
- PASS: a booking that starts when the previous one ends is allowed

## 13. The same surgeon cannot hold two overlapping bookings

Result: PASS. 1 of 1 checks passed.

- PASS: overlapping surgeon booking is rejected

## 14. Different theatres at the same time can both succeed

Result: PASS. 1 of 1 checks passed.

- PASS: a different theatre can be booked at the same time

## 15. Concurrent theatre overlap yields one success and one conflict

Result: PASS. 1 of 1 checks passed.

- PASS: concurrent theatre overlap yields one success and one conflict

## 16. Concurrent surgeon overlap yields one success and one conflict

Result: PASS. 1 of 1 checks passed.

- PASS: concurrent surgeon overlap yields one success and one conflict

## 17. The same case has one logical booking

Result: PASS. 1 of 1 checks passed.

- PASS: two schedule requests for one case leave one booking

## 18. Reschedule and cancel preserve history

Result: PASS. 2 of 2 checks passed.

- PASS: reschedule appends history and keeps one booking
- PASS: cancellation keeps the booking history

## 19. A cancelled case stays readable

Result: PASS. 1 of 1 checks passed.

- PASS: a cancelled case remains readable

## 20. Pre-op, consent, and readiness stay separate from the operative record

Result: PASS. 2 of 2 checks passed.

- PASS: pre-operative record is stored separately
- PASS: a later pre-operative record does not erase the first

## 21. Start waits for consent, readiness, and the checklist

Result: PASS. 3 of 3 checks passed.

- PASS: checklist item is database-managed
- PASS: start is rejected until consent is obtained
- PASS: start is rejected until the required checklist item is satisfied

## 22. Intra-operative records are not overwritten

Result: PASS. 2 of 2 checks passed.

- PASS: recovery waits for an intra-operative record
- PASS: a second intra-operative record does not replace the first

## 23. Post-operative records are not overwritten

Result: PASS. 1 of 1 checks passed.

- PASS: a second post-operative record does not replace the first

## 24. Concurrent completion is one logical completion

Result: PASS. 2 of 2 checks passed.

- PASS: same completion key does not create a second completion
- PASS: concurrent completion leaves one completed case

## 25. Concurrent start is one logical start

Result: PASS. 1 of 1 checks passed.

- PASS: concurrent start yields one success and one conflict

## 26. Charges go through Phase 4 only

Result: PASS. 3 of 3 checks passed.

- PASS: billing user can sign in
- PASS: charge returns the Phase 4 invoice line
- PASS: the line is an OT category on the invoice

## 27. Client price and tax are ignored

Result: PASS. 1 of 1 checks passed.

- PASS: client price and tax do not set the line

## 28. The procedure price is snapshotted

Result: PASS. 1 of 1 checks passed.

- PASS: a later procedure price does not rewrite the line

## 29. The same case, procedure, and purpose is one charge

Result: PASS. 2 of 2 checks passed.

- PASS: a second charge request does not add a line
- PASS: concurrent charge requests create one line

## 30. A billed cancellation does not delete financial rows

Result: PASS. 1 of 1 checks passed.

- PASS: cancellation does not delete the invoice line

## 31. Pharmacy stock is not mutated by OT

Result: PASS. 2 of 2 checks passed.

- PASS: theatre module does not write stock movements
- PASS: linking a prescription does not move stock

## 32. Laboratory orders stay in the laboratory module

Result: PASS. 2 of 2 checks passed.

- PASS: a laboratory order is linked, not copied into an OT order
- PASS: another patient's laboratory order cannot be linked

## 33. Inpatient OT uses the admission identity

Result: PASS. 5 of 5 checks passed.

- PASS: admission starts requested until a bed is assigned
- PASS: a procedure that requires admission rejects a request without one
- PASS: request keeps the admission id
- PASS: scheduling waits until the admission is occupied
- PASS: bed assignment uses the existing admission

## 34. Timeline events respect record scope

Result: PASS. 3 of 3 checks passed.

- PASS: reception can sign in
- PASS: the operating doctor sees the OT event
- PASS: a user without OT view does not see the operative event

## 35. Authorization uses permission codes, not role names

Result: PASS. 8 of 8 checks passed.

- PASS: director can sign in
- PASS: operating doctor can sign in
- PASS: nurse can sign in
- PASS: laboratory user can sign in
- PASS: authorization source does not branch on a role name
- PASS: view permission cannot start a procedure
- PASS: a laboratory role with only OT view cannot approve
- PASS: a non-doctor role can approve when it holds the permission code

## 36. Audit has no delete route

Result: PASS. 1 of 1 checks passed.

- PASS: audit has no delete route

## 37. The operation report is an A4 document from stored data

Result: PASS. 2 of 2 checks passed.

- PASS: report names the stored procedure
- PASS: report is an A4 PDF with a white page and a second page

## 38. Reprint is byte-identical and does not mutate records

Result: PASS. 4 of 4 checks passed.

- PASS: two reads of the report are byte-identical
- PASS: reprint does not change the case timestamp
- PASS: reading the report does not create a document or an audit row
- PASS: a changed record is a new document, not a silent reprint

## 39. Documents use StorageProvider

Result: PASS. 2 of 2 checks passed.

- PASS: report bytes are read through storage
- PASS: report metadata does not expose a storage path

## 40. Document retrieval is authorized on the server

Result: PASS. 1 of 1 checks passed.

- PASS: an unauthorized report looks like a missing report

## 41. Schema change is a new versioned migration

Result: PASS. 2 of 2 checks passed.

- PASS: schema version is the phase 7 postgres migration
- PASS: phase 7 added a new migration and left earlier files in place

## 42. Locking stays in the repository

Result: PASS. 2 of 2 checks passed.

- PASS: domain module does not contain a SQL statement
- PASS: theatre and surgeon locks are in the repository

## 43. Idempotency uses the existing key table

Result: PASS. 5 of 5 checks passed.

- PASS: idempotency uses the existing key table
- PASS: same request key returns the same case
- PASS: same key with a different request conflicts
- PASS: same schedule key returns the same booking
- PASS: same start key replays the started case

## 44. No second invoice, payment, or refund system

Result: PASS. 2 of 2 checks passed.

- PASS: theatre module does not record payments
- PASS: no OT invoice, payment, or refund table exists

## 45. Realtime events carry record scope

Result: PASS. 2 of 2 checks passed.

- PASS: events carry the patient and the view permission
- PASS: the existing stream filters a permission on the event

## 46. Existing OT notes still bill the procedure master fee

Result: PASS. 1 of 1 checks passed.

- PASS: legacy notes bill the master fee instead of the client fee

## Gate evidence

The gate started the hospital server and called it over HTTP. Theatre, surgeon, start, completion, and charge races used two concurrent requests.
Booking counts, document counts, audit counts, and stock counts were read from the throwaway database after the HTTP calls.
The database URL is not included.

## Regression

The accepted PERFORMED to NOTES_PENDING to notes path still completes a case and bills the configured procedure fee.
SQLite schema is 17 because 0017 is shared. PostgreSQL schema is 18 because 0018 is PostgreSQL-only.

## Remaining non-blocking limitations

The older status endpoint still allows REQUESTED to PERFORMED so the accepted notes path and the current desk remain usable. It does not accept a jump to COMPLETED.
Operation notes from that older endpoint still complete the case. The new workflow completes only from recovery.
