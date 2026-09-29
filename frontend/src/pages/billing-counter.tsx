import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, api, fileUrl, money, paise } from "../api";
import { prepareBarcode } from "../barcode";
import { RegisterMedicine } from "./clinical";
import { BarcodeScanner } from "../scanner";
import { useApp } from "../store";
import { Field, Loading, Modal, PatientSearchSelect, Status, run, useData, type PatientSummary } from "../ui";

function freshKey(scope: string) {
  const id = typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : String(Date.now());
  return `${scope}-${id}`;
}

function initials(name?: string) {
  const parts = (name || "").trim().split(/\s+/).filter(Boolean).slice(0, 2);
  return parts.map((part) => part[0]?.toUpperCase() || "").join("") || "PT";
}

function issued(item: any) {
  const qty = Number(item?.quantity || 0);
  const done = Number(item?.dispensed_qty || 0);
  return item?.status === "DISPENSED" || item?.status === "SUBSTITUTED" || (qty > 0 && done + 0.0001 >= qty);
}

function fillTemplate(text: string, values: Record<string, string>) {
  return text.replace(/\{\{\s*([a-z_]+)\s*\}\}/g, (_, key) => values[key] || "");
}

export function BillingCounter() {
  const [params] = useSearchParams();
  const can = useApp((s) => s.can);
  const canIssue = can("billing.medicine_issue");
  const [patientChoice, setPatientChoice] = useState<PatientSummary | null>(null);
  const [patientId, setPatientId] = useState(params.get("patient") || "");
  const [encounterId, setEncounterId] = useState("");
  const [desk, setDesk] = useState<any>(null);
  const [invoice, setInvoice] = useState<any>(null);
  const [notes, setNotes] = useState("");
  const [docCount, setDocCount] = useState<number | null>(null);
  const [discount, setDiscount] = useState("0");
  const [discountReason, setDiscountReason] = useState("");
  const [medicineQuery, setMedicineQuery] = useState("");
  const [medicines, setMedicines] = useState<any[]>([]);
  const [picked, setPicked] = useState<any>(null);
  const [batchId, setBatchId] = useState("");
  const [qty, setQty] = useState("1");
  const [manualRate, setManualRate] = useState("");
  const [selectedRx, setSelectedRx] = useState<string[]>([]);
  const [scanner, setScanner] = useState(false);
  const [unknownCode, setUnknownCode] = useState("");
  const [registering, setRegistering] = useState(false);
  const [extra, setExtra] = useState("service");
  const [fullRx, setFullRx] = useState(false);
  const [whatsapp, setWhatsapp] = useState(false);
  const [message, setMessage] = useState("");
  const [showBills, setShowBills] = useState(false);
  const [busy, setBusy] = useState(false);
  const issueKey = useRef("");
  const { data: services } = useData<{ items: any[] }>(extra === "service" || extra === "" ? "/api/services" : null);
  const { data: labs } = useData<{ items: any[] }>(extra === "lab" ? "/api/lab/tests" : null);
  const { data: bills, error: billsError, loading: billsLoading } = useData<{ items: any[] }>(showBills ? "/api/invoices" : null);

  async function loadDesk(id = patientId, encounter = encounterId) {
    if (!id) return;
    const row = await api<any>(`/api/billing/desk?patient_id=${encodeURIComponent(id)}&encounter_id=${encodeURIComponent(encounter)}`);
    setDesk(row);
    setInvoice(row.invoice);
    setNotes(row.invoice?.notes || "");
    setDiscount(((row.invoice?.discount_paise || 0) / 100).toFixed(2));
    if (!encounter && row.encounter?.id) setEncounterId(row.encounter.id);
    api<{ items: any[] }>(`/api/documents?patient_id=${encodeURIComponent(id)}`).then((docs) => setDocCount((docs.items || []).length)).catch(() => setDocCount(null));
  }

  useEffect(() => {
    if (!patientId) return;
    loadDesk(patientId, encounterId).catch((err: Error) => useApp.getState().toast(err.message, "bad"));
  }, [patientId, encounterId]);

  useEffect(() => {
    if (!canIssue) return;
    const handle = window.setTimeout(() => {
      api<{ items: any[] }>(`/api/billing/medicines?q=${encodeURIComponent(medicineQuery.trim())}`)
        .then((row) => setMedicines(row.items || []))
        .catch(() => setMedicines([]));
    }, 180);
    return () => window.clearTimeout(handle);
  }, [medicineQuery, canIssue]);

  const patient = desk?.patient;
  const encounter = desk?.encounter;
  const prescription = (encounter?.prescriptions || []).find((row: any) => row.status === "FINALIZED" || row.status === "PARTIAL" || row.status === "DISPENSED") || encounter?.prescriptions?.[0];
  const batch = (picked?.batches || []).find((row: any) => row.id === batchId) || picked?.batches?.[0];
  const ratePaise = batch?.rate_paise || (manualRate ? paise(manualRate) : 0);
  const preview = ratePaise * (Number(qty) || 0);

  async function choosePatient(row: PatientSummary | null) {
    if (!row) {
      setPatientChoice(null);
      setPatientId("");
      setDesk(null);
      setInvoice(null);
      setEncounterId("");
      return;
    }
    setPatientChoice(row);
    setEncounterId("");
    setPatientId(row.id);
    setPicked(null);
    setSelectedRx([]);
  }

  useEffect(() => {
    const initial = params.get("patient");
    if (!initial) return;
    api<any>(`/api/patients/${encodeURIComponent(initial)}`).then(setPatientChoice).catch(() => undefined);
  }, [params]);

  async function ensureDraft() {
    if (invoice?.status === "DRAFT") return invoice;
    if (!patientId) throw new Error("Choose a patient first.");
    const draft = await api<any>("/api/invoices", {
      method: "POST",
      body: JSON.stringify({ patient_id: patientId, encounter_id: encounter?.id || null, bill_type: "OPD" }),
    });
    const full = await api<any>(`/api/invoices/${draft.id}`);
    setInvoice(full);
    return full;
  }

  async function postIssue(draftId: string, body: any) {
    if (!issueKey.current) issueKey.current = freshKey("issue");
    try {
      return await api<any>(`/api/invoices/${draftId}/issue`, {
        method: "POST",
        body: JSON.stringify({ ...body, idempotency_key: issueKey.current }),
      });
    } catch (err) {
      if (err instanceof ApiError && err.code === "qty_mismatch") {
        if (!window.confirm(`${err.message}\n\nThe doctor's prescription will not be changed.`)) {
          throw new ApiError("Not billed. The prescription was not changed.", 409, "cancelled");
        }
        return api<any>(`/api/invoices/${draftId}/issue`, {
          method: "POST",
          body: JSON.stringify({ ...body, confirm: true, idempotency_key: issueKey.current }),
        });
      }
      throw err;
    }
  }

  async function addMedicine(lines: any[]) {
    if (!canIssue) throw new Error("You can bill other charges, but you cannot issue medicine stock.");
    try {
      const draft = await ensureDraft();
      const result = await postIssue(draft.id, { items: lines });
      if (result.warnings?.length) useApp.getState().toast(result.warnings.join(" "), "warn");
      await loadDesk();
      return result;
    } finally {
      issueKey.current = "";
    }
  }

  async function identify(raw: string) {
    const prepared = prepareBarcode(raw);
    setUnknownCode("");
    if (prepared.error) throw new Error(prepared.error);
    try {
      const hit = await api<any>("/api/inventory/barcodes/resolve", { method: "POST", body: JSON.stringify({ code: prepared.code }) });
      const found = await api<{ items: any[] }>(`/api/billing/medicines?q=${encodeURIComponent(hit.product?.id || prepared.code)}`);
      const product = (found.items || []).find((item) => item.id === hit.product?.id) || found.items?.[0];
      if (!product) throw new Error("The barcode was identified, but its batches could not be opened.");
      setPicked(product);
      setBatchId(hit.matched_batch?.id || product.batches?.[0]?.id || "");
      setMedicineQuery(product.name || "");
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setUnknownCode(prepared.code);
        setPicked(null);
        return;
      }
      throw err;
    }
  }

  function chooseMedicine(product: any) {
    setPicked(product);
    setUnknownCode("");
    const usable = (product.batches || []).find((row: any) => Number(row.qty_on_hand) > 0) || product.batches?.[0];
    setBatchId(usable?.id || "");
    setManualRate("");
  }

  const pendingIds = (prescription?.items || []).filter((item: any) => !issued(item) && item.product_id).map((item: any) => item.id);

  return (
    <div className="bill-desk">
      <header className="bill-title">
        <div>
          <h1>Billing</h1>
          <p>Create bill, add prescription medicines, issue and deduct stock, collect payment.</p>
        </div>
        <div className="row-actions">
          <Link className="btn" to="/register">New Patient</Link>
          <Link className="btn" to="/queue">View Queue</Link>
          <Link className="btn" to="/">Today's OPD</Link>
          <button className="btn" type="button" onClick={() => setShowBills((open) => !open)}>{showBills ? "Hide bills" : "All bills"}</button>
        </div>
      </header>
      <div className="bill-search">
        <PatientSearchSelect value={patientChoice} onChange={choosePatient} />
      </div>

      <section className="patient-head">
        <div className="avatar" aria-hidden="true">{initials(patient?.name)}</div>
        <div className="patient-id">
          <h2>{patient?.name || "Select a patient"} {encounter && <span className="opd-pill">OPD patient</span>}</h2>
          <p>{patient ? <>Patient ID: <span className="pid">{patient.id}</span> · Age: {patient.age || "not recorded"} · {patient.gender || "Gender not recorded"}</> : "Search by Patient ID, name, or phone. A scan does not change stock."}</p>
          {patient && <p className="sub">{patient.phone || "No phone"}{patient.guardian_name ? ` · Guardian: ${patient.guardian_name}` : ""}</p>}
        </div>
        <div className="patient-meta">
          <Field label="Encounter">
            <select aria-label="Encounter" value={encounterId} onChange={(e) => { setEncounterId(e.target.value); setSelectedRx([]); }} disabled={!desk?.encounters?.length}>
              {!desk?.encounters?.length && <option value="">No visit yet</option>}
              {(desk?.encounters || []).map((row: any) => <option key={row.id} value={row.id}>{row.id}</option>)}
            </select>
          </Field>
          <span>{encounter?.arrived_at ? encounter.arrived_at.replace("T", " ").slice(0, 16) : "No visit time"}</span>
        </div>
        <div className="patient-meta">
          <strong>Doctor</strong>
          <span>{encounter?.doctor_name || "Not assigned"}</span>
          <span>{encounter?.department_name || "Department not recorded"}</span>
        </div>
        <div className="patient-links">
          {patient && <Link className="btn small" to={`/patients/${patient.id}`}>View patient</Link>}
          {patient && <Link className="btn small" to={`/patients/${patient.id}`}>Documents{docCount === null ? "" : ` (${docCount})`}</Link>}
          {patient && <Link className="btn small" to={`/patients/${patient.id}`}>History</Link>}
        </div>
      </section>

      <div className="bill-columns">
        <div className="bill-stack">
          <section className="bill-col">
            <header><h2>Prescription</h2>{prescription && <Status value={prescription.status} />}</header>
            {prescription && <p className="muted">{prescription.id} · {encounter?.doctor_name || "Doctor not recorded"}</p>}
            {!encounter && <p className="muted">Choose a patient. The visit prescription appears here. Billing does not create a second prescription.</p>}
            {encounter && !prescription && <p className="muted">This visit has no prescription yet. You can still search and bill a medicine.</p>}
            {prescription && (
              <table className="data rx-table">
                <thead><tr><th></th><th>#</th><th>Medicine</th><th>Dose</th><th>Duration</th><th className="num">Qty</th><th>Status</th></tr></thead>
                <tbody>
                  {(prescription.items || []).map((item: any, index: number) => {
                    const done = issued(item);
                    return (
                      <tr key={item.id}>
                        <td><input type="checkbox" aria-label={`Select ${item.medicine_name}`} disabled={done || !item.product_id} checked={selectedRx.includes(item.id)} onChange={(e) => setSelectedRx(e.target.checked ? [...selectedRx, item.id] : selectedRx.filter((id) => id !== item.id))} /></td>
                        <td>{index + 1}</td>
                        <td>{item.medicine_name} {item.strength}{!item.product_id && <small className="warn">Not linked to stock</small>}</td>
                        <td>{item.dose || item.frequency || "—"}</td>
                        <td>{item.duration || "—"}</td>
                        <td className="num">{item.quantity || 1}</td>
                        <td><span className={done ? "pill ok" : "pill wait"}>{done ? "Added" : "Pending"}</span></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
            {prescription && (
              <div className="row-actions">
                <label className="check-line"><input type="checkbox" checked={!!pendingIds.length && pendingIds.every((id: string) => selectedRx.includes(id))} onChange={(e) => setSelectedRx(e.target.checked ? pendingIds : [])} /> Select all</label>
                <button className="btn primary" type="button" disabled={!selectedRx.length || !canIssue} onClick={() => run(() => addMedicine(selectedRx.map((id) => ({ prescription_item_id: id }))), "Selected medicines issued and added to the bill")}>Add selected to bill</button>
                <button className="btn" type="button" onClick={() => setFullRx(true)}>View full prescription</button>
              </div>
            )}
          </section>
          <section className="bill-col">
            <header><h2>Add other item</h2></header>
            <div className="extra-tabs">
              {[["service", "Service"], ["lab", "Lab test"], ["other", "Other"], ["custom", "Custom"]].map(([id, label]) => (
                <button key={id} type="button" className={extra === id ? "on" : ""} onClick={() => setExtra(id)}>{label}</button>
              ))}
            </div>
            {extra === "service" && <ChargeList rows={(services?.items || []).filter((row) => row.active !== 0)} label={(row) => row.name} price={(row) => row.rate_paise} onAdd={(row) => run(async () => { await ensureDraft().then((draft) => api(`/api/invoices/${draft.id}/items`, { method: "POST", body: JSON.stringify({ source_module: "service", master_item_id: row.id, category: "HOSPITAL SERVICES", description: row.name, qty: 1 }) })); await loadDesk(); }, "Service added")} />}
            {extra === "lab" && <ChargeList rows={(labs?.items || []).filter((row) => row.active !== 0)} label={(row) => row.name} price={(row) => row.price_paise} onAdd={(row) => run(async () => { await ensureDraft().then((draft) => api(`/api/invoices/${draft.id}/items`, { method: "POST", body: JSON.stringify({ source_module: "lab", master_item_id: row.id, category: "LABORATORY", description: row.name, qty: 1 }) })); await loadDesk(); }, "Lab test added")} />}
            {(extra === "other" || extra === "custom") && <ExtraCharge kind={extra} services={[]} labs={[]} onClose={() => setExtra("service")} onAdd={async (body) => { const draft = await ensureDraft(); await api(`/api/invoices/${draft.id}/items`, { method: "POST", body: JSON.stringify(body) }); await loadDesk(); }} />}
          </section>
        </div>

        <section className="bill-col">
          <header><h2>Add medicine to bill</h2></header>
          {!canIssue && <p className="muted">You can add services, but issuing medicine stock needs the medicine-issue permission.</p>}
          <button className="scan-plate" type="button" onClick={() => setScanner(true)}>
            <strong>Scan barcode</strong>
            <span>Click to scan or use the camera. The scan only identifies the package.</span>
          </button>
          <Field label="Search medicine">
            <input aria-label="Search medicine" value={medicineQuery} onChange={(e) => setMedicineQuery(e.target.value)} placeholder="Search by name, brand, composition, strength, SKU, or barcode" />
          </Field>
          {!!medicines.length && medicineQuery.trim() && (
            <ul className="med-hits">
              {medicines.map((item) => (
                <li key={item.id}><button type="button" onClick={() => chooseMedicine(item)}>{item.name} {item.strength} <small>{item.brand || item.composition || item.id}</small></button></li>
              ))}
            </ul>
          )}
          {unknownCode && (
            <div className="unknown-code">
              <strong>Barcode not registered</strong>
              <p>Code {unknownCode}. No medicine or batch was created, and stock did not change.</p>
              {can("inventory.edit") ? <button className="btn" type="button" onClick={() => setRegistering(true)}>Register new medicine</button> : <p className="muted">A person with inventory permission must register this code. It stays on screen.</p>}
            </div>
          )}
          {picked && (
            <div className="med-card">
              <div className="med-mark" aria-hidden="true">Rx</div>
              <div>
                <h3>{picked.name} {picked.strength}</h3>
                <p>Brand: {picked.brand || "Not recorded"} · Composition: {picked.composition || "Not recorded"}</p>
                <p>Form: {picked.dosage_form || picked.unit || "Not recorded"}</p>
              </div>
            </div>
          )}
          <div className="batch-row">
            <Field label="Batch">
              <select aria-label="Batch" value={batch?.id || ""} onChange={(e) => setBatchId(e.target.value)} disabled={!picked}>
                {(picked?.batches || []).map((row: any) => <option key={row.id} value={row.id}>{row.batch_no} (exp {row.expiry_date || "none"})</option>)}
                {!picked?.batches?.length && <option value="">No batch in stock</option>}
              </select>
            </Field>
            <div className="stock-badge">{batch ? batch.qty_on_hand : "—"}<small>in stock</small></div>
          </div>
          <div className="med-figures">
            <Field label="Rate (Rs)">
              <input aria-label="Rate" value={batch?.rate_paise ? (batch.rate_paise / 100).toFixed(2) : manualRate} readOnly={!!batch?.rate_paise} onChange={(e) => setManualRate(e.target.value)} />
            </Field>
            <Field label="Quantity"><input aria-label="Quantity" value={qty} onChange={(e) => setQty(e.target.value)} /></Field>
            <Field label="Amount"><input aria-label="Amount" readOnly value={(preview / 100).toFixed(2)} /></Field>
          </div>
          <p className="muted">{batch?.rate_source === "master" ? "Rate is the medicine master price and will be snapshotted on the line." : batch?.rate_source === "batch" ? "No master price. The batch price will be snapshotted." : "Enter a rate. It is snapshotted on the line."}</p>
          <button className="btn add-bill" type="button" disabled={!picked || !batch || busy} onClick={() => {
            setBusy(true);
            run(async () => {
              await addMedicine([{
                product_id: picked.id,
                batch_id: batch.id,
                qty: Number(qty),
                rate_paise: batch.rate_paise ? undefined : paise(manualRate),
                prescription_item_id: (prescription?.items || []).find((item: any) => selectedRx.includes(item.id) && item.product_id === picked.id)?.id,
              }]);
              setQty("1");
            }, "Medicine issued and added to the bill").finally(() => setBusy(false));
          }}>Add to bill</button>
        </section>

        <div className="bill-stack">
          <section className="bill-col">
            <header><h2>Bill items ({invoice?.items?.length || 0})</h2>{invoice && <Status value={invoice.status} />}</header>
            {!invoice && <p className="muted">No draft yet. Adding a line opens one.</p>}
            {invoice && (
              <table className="data bill-lines">
                <thead><tr><th>#</th><th>Item</th><th className="num">Qty</th><th className="num">Rate</th><th className="num">Amount</th><th></th></tr></thead>
                <tbody>
                  {(invoice.items || []).map((line: any, index: number) => (
                    <BillLine key={line.id} index={index + 1} line={line} draft={invoice.status === "DRAFT"} onChanged={loadDesk} />
                  ))}
                  {!invoice.items?.length && <tr><td colSpan={6}>No lines yet.</td></tr>}
                </tbody>
              </table>
            )}
            {invoice?.status === "DRAFT" && !!invoice.items?.length && (
              <button className="btn danger clear-all" type="button" onClick={() => {
                if (!window.confirm("Remove every draft line? Issued medicines will be returned to stock.")) return;
                run(async () => {
                  for (const line of invoice.items) await api(`/api/invoice-items/${line.id}`, { method: "DELETE" });
                  await loadDesk();
                }, "Draft lines removed");
              }}>Clear all items</button>
            )}
          </section>
          <section className="bill-col">
            <header><h2>Bill summary</h2></header>
            <dl className="bill-summary">
              <div><dt>Subtotal</dt><dd>{money(invoice?.gross_paise || 0)}</dd></div>
              <div><dt>Discount</dt><dd className="discount-edit"><input aria-label="Discount rupees" value={discount} onChange={(e) => setDiscount(e.target.value)} onBlur={() => {
                if (!invoice || invoice.status !== "DRAFT") return;
                const next = paise(discount);
                if (next === Number(invoice.discount_paise || 0)) return;
                const reason = next > 0 ? (discountReason || window.prompt("Reason for this discount") || "") : "";
                if (next > 0 && !reason) return;
                setDiscountReason(reason);
                run(async () => {
                  const saved = await api<any>(`/api/invoices/${invoice.id}/discount`, { method: "POST", body: JSON.stringify({ discount_paise: next, reason }) });
                  setInvoice(saved);
                }, "Discount saved");
              }} /> {money(invoice?.discount_paise || 0)}</dd></div>
              <div><dt>Tax / service charge</dt><dd>{money(invoice?.tax_paise || 0)}</dd></div>
              <div className="net"><dt>Net total</dt><dd>{money(invoice?.net_paise || 0)}</dd></div>
              <div><dt>Paid</dt><dd>{money(invoice?.paid_paise || 0)}</dd></div>
              <div className="due"><dt>Due</dt><dd>{money(invoice?.due_paise || 0)}</dd></div>
            </dl>
            <p className="words">{invoice?.amount_in_words || ""}</p>
            {invoice && <Link className="btn small" to={`/billing/${invoice.id}`}>Take payment</Link>}
          </section>
        </div>
      </div>

      <footer className="bill-sticky">
        <Field label="Notes">
          <input aria-label="Bill notes" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Notes (optional)" />
        </Field>
        <div className="row-actions">
          <button className="btn" type="button" disabled={!patientId} onClick={() => run(async () => {
            const draft = await ensureDraft();
            const saved = await api<any>(`/api/invoices/${draft.id}/notes`, { method: "POST", body: JSON.stringify({ notes }) });
            setInvoice(saved);
          }, "Draft saved")}>Save draft</button>
          <button className="btn finalize" type="button" disabled={!invoice || invoice.status !== "DRAFT" || !can("billing.finalize")} onClick={() => run(async () => {
            await api(`/api/invoices/${invoice.id}/finalize`, { method: "POST", body: "{}" });
            await loadDesk();
          }, "Bill finalized")}>Finalize bill</button>
          {invoice && <a className="btn" href={fileUrl(`/api/invoices/${invoice.id}/pdf`)} target="_blank" rel="noreferrer">Print bill</a>}
          {prescription && <a className="btn" href={fileUrl(`/api/prescriptions/${prescription.id}/pdf`)} target="_blank" rel="noreferrer">Print prescription</a>}
          <button className="btn primary" type="button" disabled={!patient} onClick={() => {
            const values = {
              patient_name: patient?.name || "",
              patient_id: patient?.id || "",
              bill_number: invoice?.number || "",
              amount: money(invoice?.net_paise || 0),
              doctor_name: encounter?.doctor_name || "",
              hospital_name: "the hospital",
            };
            api<any>("/api/public/branding").then((brand) => {
              values.hospital_name = brand?.name || values.hospital_name;
            }).catch(() => undefined).finally(() => {
              setMessage(fillTemplate("Hello {{patient_name}} ({{patient_id}}). Bill {{bill_number}} for {{amount}} is ready. — {{doctor_name}}, {{hospital_name}}", values));
              setWhatsapp(true);
            });
          }}>Send via WhatsApp</button>
        </div>
      </footer>

      {showBills && (
        <section className="panel">
          <h2>Bills</h2>
          <div className="body">
            {billsLoading && <Loading label="Opening bills…" />}
            {billsError && <p className="warn">{billsError}</p>}
            <table className="data">
              <tbody>
                {(bills?.items || []).map((row) => (
                  <tr key={row.id}><td><Link to={`/billing/${row.id}`}>{row.number}</Link></td><td>{row.patient_name}</td><td><Status value={row.status} /></td><td className="num">{money(row.due_paise)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {scanner && <BarcodeScanner onClose={() => setScanner(false)} onUse={(code) => { setScanner(false); run(() => identify(code), "Barcode identified. Stock was not changed."); }} />}
      {registering && <RegisterMedicine barcode={unknownCode} onClose={() => setRegistering(false)} onRegistered={(code) => { setRegistering(false); run(() => identify(code), "Medicine registered. Stock was not changed by the barcode."); }} />}
      {fullRx && prescription && (
        <Modal title={prescription.id} onClose={() => setFullRx(false)} footer={<a className="btn" href={fileUrl(`/api/prescriptions/${prescription.id}/pdf`)} target="_blank" rel="noreferrer">Open stored prescription</a>}>
          <ul className="rx-list">
            {(prescription.items || []).map((item: any) => (
              <li key={item.id}><span><strong>{item.medicine_name} {item.strength}</strong><small>{[item.dose, item.frequency, item.duration, item.quantity].filter(Boolean).join(" · ")}</small></span><em>{issued(item) ? "Added" : "Pending"}</em></li>
            ))}
          </ul>
        </Modal>
      )}
      {whatsapp && patient && (
        <WhatsAppSend patientId={patient.id} invoiceId={invoice?.id || ""} text={message} onText={setMessage} onClose={() => setWhatsapp(false)} />
      )}
    </div>
  );
}

function ChargeList({ rows, label, price, onAdd }: { rows: any[]; label: (row: any) => string; price: (row: any) => number; onAdd: (row: any) => void }) {
  const [q, setQ] = useState("");
  const shown = rows.filter((row) => label(row).toLowerCase().includes(q.trim().toLowerCase())).slice(0, 8);
  return (
    <div>
      <input aria-label="Search charge" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search the catalogue" />
      <ul className="charge-list">
        {shown.map((row) => (
          <li key={row.id}><span>{label(row)}</span><strong>{money(price(row))}</strong><button className="btn small" type="button" onClick={() => onAdd(row)}>Add</button></li>
        ))}
        {!shown.length && <li className="muted">Nothing in this catalogue matches.</li>}
      </ul>
    </div>
  );
}

function BillLine({ index, line, draft, onChanged }: { index: number; line: any; draft: boolean; onChanged: () => Promise<void> }) {
  const [qty, setQty] = useState(String(line.qty));
  const [batches, setBatches] = useState<any[]>([]);
  const medicine = line.source_module === "billing_issue" || line.source_module === "pharmacy";
  useEffect(() => {
    if (!medicine || !draft || !line.master_item_id) return;
    api<{ items: any[] }>(`/api/billing/medicines?q=${encodeURIComponent(line.master_item_id)}`).then((row) => {
      const product = (row.items || []).find((item) => item.id === line.master_item_id);
      setBatches(product?.batches || []);
    }).catch(() => setBatches([]));
  }, [medicine, draft, line.master_item_id]);
  function revise(body: any, ok: string) {
    run(async () => {
      try {
        await api(`/api/invoice-items/${line.id}/revise`, { method: "POST", body: JSON.stringify(body) });
      } catch (err) {
        if (err instanceof ApiError && err.code === "qty_mismatch" && window.confirm(`${err.message}\n\nThe prescription will not be changed.`)) {
          await api(`/api/invoice-items/${line.id}/revise`, { method: "POST", body: JSON.stringify({ ...body, confirm: true }) });
        } else throw err;
      }
      await onChanged();
    }, ok);
  }
  return (
    <tr>
      <td>{index}</td>
      <td>
        {line.description}
        <small>{line.category}</small>
        {medicine && draft && !!batches.length && (
          <select aria-label={`Batch for ${line.description}`} defaultValue="" onChange={(e) => { if (e.target.value) revise({ batch_id: e.target.value, qty: Number(qty) }, "Batch changed and stock adjusted"); }}>
            <option value="">Change batch</option>
            {batches.map((row) => <option key={row.id} value={row.id}>{row.batch_no} · stock {row.qty_on_hand}</option>)}
          </select>
        )}
      </td>
      <td className="num">
        {medicine && draft ? <input aria-label={`Quantity for ${line.description}`} value={qty} onChange={(e) => setQty(e.target.value)} onBlur={() => {
          if (Number(qty) === Number(line.qty)) return;
          revise({ qty: Number(qty) }, "Quantity updated and stock adjusted");
        }} /> : line.qty}
      </td>
      <td className="num">{money(line.rate_paise)}</td>
      <td className="num">{money(line.amount_paise)}</td>
      <td>{draft && <button className="btn small danger" type="button" onClick={() => {
        if (!window.confirm(medicine ? "Remove this medicine and return the stock?" : "Remove this line?")) return;
        run(async () => {
          await api(`/api/invoice-items/${line.id}`, { method: "DELETE" });
          await onChanged();
        }, medicine ? "Line removed and stock returned" : "Line removed");
      }}>Remove</button>}</td>
    </tr>
  );
}

function ExtraCharge({ kind, services, labs, onClose, onAdd }: { kind: string; services: any[]; labs: any[]; onClose: () => void; onAdd: (body: any) => Promise<void> }) {
  const [id, setId] = useState("");
  const [description, setDescription] = useState("");
  const [rate, setRate] = useState("");
  const [qty, setQty] = useState("1");
  const title = kind === "service" ? "Service" : kind === "lab" ? "Lab test" : kind === "custom" ? "Custom charge" : "Other charge";
  return (
    <form className="extra-form" onSubmit={(event) => {
      event.preventDefault();
      const body = kind === "service"
        ? { source_module: "service", master_item_id: id, category: "HOSPITAL SERVICES", description: services.find((row) => row.id === id)?.name || "Service", qty: 1 }
        : kind === "lab"
          ? { source_module: "lab", master_item_id: id, category: "LABORATORY", description: labs.find((row) => row.id === id)?.name || "Lab test", qty: 1 }
          : { source_module: "manual", category: "OTHER", description, qty: Number(qty) || 1, rate_paise: paise(rate) };
      run(() => onAdd(body).then(onClose), "Charge added");
    }}>
      <strong>{title}</strong>
      {kind === "service" && <select aria-label="Service" value={id} onChange={(e) => setId(e.target.value)}><option value="">Choose a service</option>{services.filter((row) => row.active !== 0).map((row) => <option key={row.id} value={row.id}>{row.name} · {money(row.rate_paise)}</option>)}</select>}
      {kind === "lab" && <select aria-label="Lab test" value={id} onChange={(e) => setId(e.target.value)}><option value="">Choose a test</option>{labs.filter((row) => row.active !== 0).map((row) => <option key={row.id} value={row.id}>{row.name} · {money(row.price_paise)}</option>)}</select>}
      {(kind === "other" || kind === "custom") && (
        <>
          <input aria-label="Charge description" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Description" />
          <input aria-label="Charge rate" value={rate} onChange={(e) => setRate(e.target.value)} placeholder="Rate Rs" />
          {kind === "custom" && <input aria-label="Charge quantity" value={qty} onChange={(e) => setQty(e.target.value)} placeholder="Qty" />}
        </>
      )}
      <button className="btn primary" type="submit">Add charge</button>
      <button className="btn" type="button" onClick={onClose}>Cancel</button>
    </form>
  );
}

function WhatsAppSend({ patientId, invoiceId, text, onText, onClose }: { patientId: string; invoiceId: string; text: string; onText: (value: string) => void; onClose: () => void }) {
  const [docs, setDocs] = useState<any[]>([]);
  const [documentId, setDocumentId] = useState("");
  const [confirm, setConfirm] = useState(false);
  useEffect(() => {
    api<{ items: any[] }>(`/api/documents?patient_id=${encodeURIComponent(patientId)}`).then((row) => {
      const items = (row.items || []).filter((item) => !invoiceId || item.entity_id === invoiceId || item.entity_type === "prescription");
      setDocs(items);
    }).catch(() => setDocs([]));
  }, [patientId, invoiceId]);
  return (
    <Modal title="Send via WhatsApp" onClose={onClose} footer={
      <button className="btn primary" type="button" disabled={!confirm} onClick={() => run(async () => {
        if (documentId) {
          await api("/api/whatsapp/documents", { method: "POST", body: JSON.stringify({ patient_id: patientId, document_id: documentId, caption: text, confirm: true }) });
        } else {
          await api("/api/whatsapp/messages", { method: "POST", body: JSON.stringify({ patient_id: patientId, text, confirm: true }) });
        }
        onClose();
      }, documentId ? "Document sent" : "Message sent")}>Send</button>
    }>
      <p className="muted">The message is sent through the hospital WhatsApp connection. Credentials stay on the server. If WhatsApp is not connected, the send fails and nothing is marked sent.</p>
      <Field label="Message">
        <textarea aria-label="WhatsApp message" value={text} onChange={(e) => onText(e.target.value)} rows={4} />
      </Field>
      <Field label="Stored document">
        <select aria-label="Stored document" value={documentId} onChange={(e) => setDocumentId(e.target.value)}>
          <option value="">Message only</option>
          {docs.map((doc) => <option key={doc.id} value={doc.id}>{doc.title || doc.filename}</option>)}
        </select>
      </Field>
      {!docs.length && <p className="muted">No stored bill or prescription file was found. Print stores a prescription file. The bill PDF is generated when you print it.</p>}
      <label className="check-line"><input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} /> I confirm this recipient and message.</label>
    </Modal>
  );
}
