# Phase 3 acceptance

Decision: **PHASE 3 ACCEPTED**

Phase 0, Phase 1, and Phase 2 were not reopened. Phase 4 billing, Lab, IPD, and OT were not started. `data/hospital.db` was not opened for writing. It is still 569344 bytes.

The workflow ran through `python -m aipf.server` against a throwaway PostgreSQL database. That database was dropped afterward. No password or database URL was written into the repository.

Barcode letters AB–AF are the barcode gate. The workflow items that an earlier list also numbered around AB and AC are in A–AA, so neither set is dropped.

## A–AF

| Item | Result | Evidence |
| --- | --- | --- |
| A. Prescription is not dispensing | PASS | A finalized prescription is a queue record. Dispensing is a separate transaction. The draft charge is a third record. A stock movement is a fourth. |
| B. Finalize does not reduce stock | PASS | After finalize, `BAT-PR-PARA` was unchanged. The doctor has no `pharmacy.dispense` effect on this path. |
| C. Only a valid dispense changes prescription stock | PASS | Unknown scans, resolve, and a rejected receive left the movement count unchanged. A confirmed dispense wrote `DISPENSED` and reduced the selected batch. |
| D. Partial dispensing | PASS | Dispensing 4 of 10 left status `PARTIAL` and remaining 6. A request for 7 was rejected. The last 6 completed it and removed it from the queue. The total never exceeded 10. |
| E. Substitution | PASS | A different product without the flag returned 409 `product_mismatch` and moved no stock. A flag without a reason was rejected. An explicit reason dispensed the substitute and left the prescribed name and product id unchanged. |
| F. FEFO and batch rejection | PASS | Resolve ordered the earlier usable batch first. The pharmacist could confirm a later valid batch. Expired, inactive, insufficient, and a batch from another product were rejected. |
| G. Concurrent stock | PASS | Two simultaneous dispenses of the last unit produced one success and one failure. On-hand stayed 0. One `DISPENSED` movement was written. |
| H. Dispense idempotency | PASS | The HTTP dispense requires an idempotency key. The same key returned the stored result and did not move stock again. A different payload for that key returned 409. Two simultaneous calls with one key created one dispense line. |
| I. Ledger | PASS | Receive wrote `PURCHASE`. Dispense wrote `DISPENSED`. Adjustment wrote `LOST`. Quantity is the conditional batch update after which the movement is inserted. A direct negative update was rejected by PostgreSQL. |
| J. Adjustments | PASS | `POST /api/inventory/movements` requires `inventory.adjust`. A movement without a reason was rejected. A permitted movement with a reason wrote the ledger. |
| K. Pharmacist permission | PASS | The seeded pharmacist role no longer receives `inventory.adjust`. The pharmacist received 403 on an adjustment and could still dispense. Migration `0008` also removes that grant if an older seed had inserted it. |
| L. Product, package, batch, and stock stay separate | PASS | A product has packages. A package has barcodes. A batch has quantity. A manufacturer barcode did not select a batch. An explicit batch barcode identified a batch and still did not dispense. |
| M. Packaging conversions | PASS | Seed text such as “1 box = 10 strips” created no package size other than the base unit of 1. Omitting `units_per_pack` was rejected. A strip of 10 was stored only because it was entered. Receive of 3 added 3 base units, not 30. |
| N. Billing boundary | PASS | Dispense added a pharmacy line to the existing draft invoice, with the batch rate, product, quantity, patient, and encounter. The invoice stayed `DRAFT`. Changing the master and batch rates did not rewrite the line. No second billing system was added. |
| O. Local stock | PASS | The dispense and receive path uses the local PostgreSQL transaction. No external service is called. |
| P. Purchasing boundary | PASS | The barcode receive path resolves, selects or creates a batch, takes manufacturing and expiry dates, takes an explicit base quantity, and writes `PURCHASE`. There is no supplier, purchase order, or GRN table. |
| Q. Record scope | PASS | The other doctor received 404 for the prescription and 403 for finalize. The doctor received 403 for the pharmacy queue. Phase 1 regression still passed. |
| R. Ownership fields | PASS | Creating a prescription with another patient id and doctor id was rejected. The owner could not reassign `patient_id` on update. The stored encounter and prescribing doctor were used. |
| S. Audit | PASS | Dispense was audited as ids and status. The consultation marker was not copied into the audit text. |
| T. Realtime | PASS | `pharmacy.dispensed` carries `patient_id` and was delivered to the pharmacist. It was not delivered to the other doctor. The payload had no consultation note. |
| U. Doctor workflow | PASS | HTTP covered consultation, draft prescription, finalize, and the pharmacy queue appearing only after finalize. The consultation screen still saves and finalizes through those APIs. |
| V. Pharmacist workflow | PASS | The pharmacy page scans through resolve, applies a batch only after a click, and dispenses only from the confirm button with an idempotency key. The HTTP workflow covered queue, resolve, confirm, and dispense. A browser was not driven. |
| W. Inventory workflow | PASS | The inventory page can register a package and a barcode from the configured type list, receive into a batch, and read the ledger. Adjustment controls are shown only with `inventory.adjust`. |
| X. Database integrity | PASS | Package, barcode, and dispense-idempotency foreign keys are present. One active barcode value is unique. A product cannot have two batches with the same number. PostgreSQL checks non-negative stock, prescription status, and movement type. |
| Y. Unknown scan | PASS | An unknown code returned 404. Product count and movement count were unchanged. Receive of that code did not create a product. |
| Z. No barcode required | PASS | A product with no barcode row was received and dispensed by an explicit batch and quantity. |
| AA. Tests and regressions | PASS | `tests/test_phase3.py`, `test_flows.py`, `test_phase0.py`, `test_phase1.py`, and `test_phase2.py`: 18 passed. `py_compile` passed. `python3 -m aipf.secret_scan` passed. |
| AB. Barcode/SKU Architecture | PASS | The chain is product, packaging SKU, barcode, batch, stock. Barcode scope is `SKU` unless an explicit `BATCH` barcode is registered. Types live in `barcode_types`, not in a frontend list. A camera can later write into the same scan field without a domain change. |
| AC. Barcode Resolution | PASS | `POST /api/inventory/barcodes/resolve` returns the package, the stored pack size, and FEFO suggestions. It does not select a batch for a package barcode, dispense, or create stock. |
| AD. Barcode Validation | PASS | An active value cannot be saved twice. An unknown type is rejected. A retired or unknown value does not create a product. Resolution is an exact trimmed match, not a name search. |
| AE. Barcode Concurrency/Dispensing | PASS | A scan does not dispense. Dispense still requires a confirmed batch and quantity, and the stock lock is the same conditional update used for a typed dispense. The strip size is not applied silently. |
| AF. Barcode HTTP/E2E | PASS | Register, duplicate rejection, resolve, batch-scoped resolve, receive, and the consultation-to-dispense path were HTTP calls to the real server on throwaway PostgreSQL. |

## What the workflow now guarantees

A doctor can write and finalize a prescription. That does not touch stock. The pharmacist sees the queue, scans a barcode into a focused field, and still has to choose the batch and quantity. Only that confirmed dispense reduces stock, writes the ledger, and adds a snapshotted line to the existing draft bill.

A barcode names a package, or an explicitly registered batch. It never names a product by guessing, and it never creates one. Package size is whatever was stored. The seed sentence “1 box = 10 strips” is a label, not a conversion.

An adjustment is a different permission from dispensing. The pharmacist can receive and dispense. The pharmacist cannot post an adjustment unless a role grant actually includes `inventory.adjust`.

## Non-blocking notes

- No browser was driven. The pharmacy and inventory screens call the APIs verified above.
- `allow_expired_dispense` remains a hospital setting and defaults off. The acceptance request was rejected. `allow_negative_stock` also defaults off. PostgreSQL now rejects a negative on-hand quantity even if that switch is turned on; that failure is a transaction abort rather than the usual stock message.
- `inventory.updated` has no patient id, so any signed-in event stream can see a stock change. It carries no clinical text. Patient-linked dispense events are filtered.
- Supplier purchasing and GRN were not built. The receive path is the boundary.
- The live SQLite file was not migrated. A later startup applies `0008_pharmacy_barcode.sql` and, on PostgreSQL, `0009_pharmacy_checks.postgres.sql`.
- Ruff and mypy were not run. They are still not installed.
