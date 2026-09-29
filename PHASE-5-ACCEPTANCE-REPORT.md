# PHASE 5 ACCEPTED

Phase 5 laboratory workflow only. Phase 4 was not reopened. Phase 6 was not started.
The billing engine remains the only financial source of truth. No laboratory payment table was added.

Gate: real HTTP against a throwaway PostgreSQL database. The database URL is not recorded here.
Schema version observed: 18.
Checks recorded: 109. Checks failed: 0.

## 1. Test master is database-managed

Result: PASS. 3 of 3 checks passed.

- PASS: schema version is the current postgres migration
- PASS: configured test is returned by the catalogue API
- PASS: duplicate test code is rejected

## 2. Referenced tests are deactivated, not deleted

Result: PASS. 3 of 3 checks passed.

- PASS: inactive test cannot be ordered
- PASS: historical order remains after deactivation
- PASS: there is no delete of a referenced test

## 3. Price is snapshotted through the billing engine

Result: PASS. 2 of 2 checks passed.

- PASS: master price of 500 rupees is snapshotted in integer paise
- PASS: later master price of 700 rupees does not rewrite the line

## 4. No second billing or lab payment system

Result: PASS. 6 of 6 checks passed.

- PASS: billing user can sign in
- PASS: laboratory domain does not record payments
- PASS: ordering does not create a payment
- PASS: cancellation adds no payment
- PASS: billing finalizes the invoice the lab line sits on
- PASS: laboratory user cannot post a financial adjustment

## 5. Client price and tax are ignored

Result: PASS. 2 of 2 checks passed.

- PASS: client price and tax are not stored
- PASS: custom test is price pending rather than a client price

## 6. Order is bound to patient and encounter

Result: PASS. 2 of 2 checks passed.

- PASS: encounter belongs to the patient
- PASS: doctor orders on the linked encounter

## 7. Admission is bound when supplied

Result: PASS. 2 of 2 checks passed.

- PASS: admission is stored when it belongs to the patient
- PASS: another patient's admission is not attached

## 8. Phone is not an identity

Result: PASS. 3 of 3 checks passed.

- PASS: patient is created by id
- PASS: shared phone does not merge patients
- PASS: order cannot be created from a phone number

## 9. Another patient's encounter is rejected

Result: PASS. 2 of 2 checks passed.

- PASS: another patient's encounter is not attached
- PASS: missing and foreign encounters look the same

## 10. Many tests keep separate lifecycles

Result: PASS. 2 of 2 checks passed.

- PASS: one order holds three distinct tests
- PASS: unordered tests stay pending while one is collected

## 11. Status transitions are explicit

Result: PASS. 9 of 9 checks passed.

- PASS: laboratory page does not post an arbitrary status
- PASS: arbitrary status jump is rejected
- PASS: result entry cannot skip collection
- PASS: postgres check lab_orders_status_check
- PASS: postgres check lab_orders_priority_check
- PASS: postgres check lab_order_items_status_check
- PASS: postgres check lab_samples_status_check
- PASS: postgres check lab_results_status_check
- PASS: postgres check lab_results_revision_positive

## 12. Accession numbers are unique and concurrency-safe

Result: PASS. 5 of 5 checks passed.

- PASS: repeating the order key does not create a second order
- PASS: postgres enforces accession uniqueness and laboratory checks
- PASS: concurrent collections receive distinct accessions
- PASS: concurrent retry of one collection key creates one sample
- PASS: ten concurrent collections receive ten distinct accessions

## 13. Collection is a real sample record

Result: PASS. 4 of 4 checks passed.

- PASS: collection creates one accessioned sample
- PASS: two tests of one specimen can share a collection
- PASS: postgres prevents two active collections of one ordered test
- PASS: concurrent collection of one test creates one sample

## 14. Rejection keeps the sample and allows recollection

Result: PASS. 4 of 4 checks passed.

- PASS: unknown rejection reason is rejected
- PASS: configured rejection reason is accepted
- PASS: unknown reason after rejection does not mutate the sample
- PASS: rejected sample is kept and recollection has a new accession

## 15. Processing queue is event-scoped, not polled

Result: PASS. 5 of 5 checks passed.

- PASS: collection event reaches the laboratory user only
- PASS: processing queue lists the collected sample
- PASS: the other doctor's queue does not list it
- PASS: receipt is an explicit step
- PASS: processed samples leave the queue

## 16. Result types are structured

Result: PASS. 2 of 2 checks passed.

- PASS: numeric result is stored
- PASS: positive or negative is a result value, not a flag

## 17. Reference range is snapshotted at result time

Result: PASS. 2 of 2 checks passed.

- PASS: range is snapshotted onto the result
- PASS: historical range is not rewritten from today's master

## 18. Abnormal and critical come only from configured ranges

Result: PASS. 6 of 6 checks passed.

- PASS: low flag comes from the configured range
- PASS: a text value is not turned into a diagnosis flag
- PASS: critical flag is calculated from the snapshotted critical range
- PASS: critical result is audited
- PASS: PDF says a flag is not a diagnosis
- PASS: timeline does not call the flag a diagnosis

## 19. Entry and verification are different permissions

Result: PASS. 9 of 9 checks passed.

- PASS: laboratory user can sign in
- PASS: technician can enter but is not granted verification
- PASS: doctor cannot enter a result
- PASS: technician verification is forbidden
- PASS: doctor verification is forbidden
- PASS: the same user verifies only after the permission is granted
- PASS: revoked verification permission is enforced
- PASS: holder of the verify permission can verify the correction
- PASS: concurrent verification commits one verified result

## 20. Correction preserves the previous result

Result: PASS. 3 of 3 checks passed.

- PASS: technician cannot correct a verified result
- PASS: correction is a new revision with a reason
- PASS: previous value, actor, and time remain

## 21. PDF is rendered from stored results

Result: PASS. 3 of 3 checks passed.

- PASS: report is generated from verified results
- PASS: linked doctor can fetch the stored PDF
- PASS: PDF uses the result-time method, not the later master

## 22. Report can span pages and shows the rupee sign

Result: PASS. 2 of 2 checks passed.

- PASS: long report has a second page
- PASS: rupee sign is embedded and the snapshotted amount is shown

## 23. Reprint does not mutate the database

Result: PASS. 2 of 2 checks passed.

- PASS: reprint is byte-identical and writes nothing
- PASS: generating an unchanged report does not create a document

## 24. Documents go through StorageProvider

Result: PASS. 2 of 2 checks passed.

- PASS: report response has no filesystem path
- PASS: stored checksum matches the PDF bytes

## 25. Document fetch is authorized

Result: PASS. 4 of 4 checks passed.

- PASS: report fetch outside scope matches a missing report
- PASS: document file outside scope matches a missing file
- PASS: linked doctor with document permission can open the file
- PASS: a path is not accepted as a document id

## 26. Timeline and doctor access follow permission and scope

Result: PASS. 6 of 6 checks passed.

- PASS: second doctor can sign in
- PASS: another doctor cannot open the order
- PASS: the linked doctor can open the same order
- PASS: timeline shows sample, verified result, and report
- PASS: billing timeline does not receive laboratory detail
- PASS: unlinked doctor timeline is not found

## 27. Authorization uses permission codes

Result: PASS. 8 of 8 checks passed.

- PASS: director can sign in
- PASS: doctor can sign in
- PASS: pharmacist can sign in
- PASS: doctor permissions do not include verify or view-all
- PASS: authorization source does not branch on a role name
- PASS: order permission is required before the record is touched
- PASS: verification can be granted by permission code
- PASS: audit rows cannot be deleted through the API

## 28. Cancellation keeps the order and the invoice line

Result: PASS. 4 of 4 checks passed.

- PASS: cancellation keeps the order and the invoice line
- PASS: cancelled order is still readable
- PASS: inpatient cancellation still keeps the row
- PASS: phase 4 adjustment reverses the charge without deleting the lab line

## 29. Repeat tests are distinct instances

Result: PASS. 2 of 2 checks passed.

- PASS: repeat test creates two item ids
- PASS: repeat collections get distinct accessions

Critical laboratory or financial failures were not skipped. A failed critical check is PHASE 5 NOT ACCEPTED.
