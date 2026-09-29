import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError, api, fileUrl, money, when } from "../api";
import { useApp } from "../store";
import { Empty, ErrorState, Field, Flow, Loading, Modal, Page, Status, run, useData } from "../ui";
import { prepareBarcode } from "../barcode";
import { BarcodeScanner, PhonePair } from "../scanner";

export function Consult() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { data, error } = useData<any>(id ? `/api/opd/${id}` : null);
  const { data: tests } = useData<{ items: any[] }>("/api/lab/tests");
  const [clinicalText, setClinicalText] = useState<string | null>(null);
  const [rxLines, setRxLines] = useState<any[] | null>(null);
  const [labOpen, setLabOpen] = useState(false);

  if (error) return <Page title="OPD"><ErrorState message={error} /></Page>;
  if (!data) return <Page title="OPD"><Loading label="Opening OPD…" /></Page>;

  const patient = data.patient;
  const consultation = data.consultation || {};
  const notes = clinicalText ?? consultation.notes ?? consultation.symptoms ?? "";
  const savedRx = data.prescriptions?.[0];
  const medicines = rxLines ?? savedRx?.items ?? [];
  const labOrders = data.lab_orders || [];

  async function saveNotes(complete = false) {
    await run(async () => {
      await api("/api/consultations", {
        method: "POST",
        body: JSON.stringify({
          ...consultation,
          encounter_id: data.id,
          symptoms: notes,
          findings: consultation.findings || "",
          diagnosis: consultation.diagnosis || "",
          notes,
          instructions: consultation.instructions || "",
          follow_up: consultation.follow_up || "",
          complete,
        }),
      });
      if (complete) navigate("/doctor");
    }, complete ? "OPD completed" : "Notes saved");
  }

  async function savePrescription() {
    await run(async () => {
      const body = { encounter_id: data.id, items: medicines.filter((line: any) => line.medicine_name?.trim()) };
      if (!body.items.length) throw new Error("Add at least one medicine, or leave the prescription empty.");
      const saved = savedRx && savedRx.status === "DRAFT"
        ? await api<any>(`/api/prescriptions/${savedRx.id}`, { method: "PUT", body: JSON.stringify(body) })
        : await api<any>("/api/prescriptions", { method: "POST", body: JSON.stringify(body) });
      if (saved?.status === "DRAFT") await api(`/api/prescriptions/${saved.id}/finalize`, { method: "POST" });
    }, "Prescription saved");
  }

  return (
    <Page kicker="Doctor workspace" title="OPD" note="Open → work → complete" actions={<Link className="btn" to="/doctor">Back to queue</Link>}>
      <section className="opd-patient-header">
        <div>
          <h2>{patient.name}</h2>
          <p className="pid">Patient ID: {patient.id} · OPD: {data.id}</p>
          <p>{patient.age_display || "Age not recorded"} · {patient.gender || "Gender not recorded"} · {patient.primary_phone || "Phone not recorded"}</p>
        </div>
        <div>
          <strong>{data.department_name || "Department not recorded"}</strong>
          <p className="muted">{data.doctor_name || "Doctor not assigned"} · {data.opd_type_name || "OPD"}</p>
          {patient.allergies && <p className="allergy">Allergy: {patient.allergies}</p>}
        </div>
      </section>

      <div className="opd-workspace">
        <section className="panel opd-notes">
          <header><h2>Symptoms / Clinical Notes</h2></header>
          <div className="body">
            <textarea className="clinical-notes" value={notes} onChange={(event) => setClinicalText(event.target.value)} placeholder="Write symptoms and clinical notes…" />
            <button className="btn" type="button" onClick={() => saveNotes(false)}>Save Notes</button>
          </div>
        </section>

        <section className="panel opd-prescription">
          <header><h2>Prescription</h2></header>
          <div className="body">
            {medicines.map((line: any, index: number) => (
              <div className="prescription-row" key={index}>
                <MedicinePicker value={line.medicine_name || ""} onChange={(value) => editLine(medicines, setRxLines, index, { medicine_name: value })} />
                <input aria-label="Dose" placeholder="Dose" value={line.dose || ""} onChange={(event) => editLine(medicines, setRxLines, index, { dose: event.target.value })} />
                <input aria-label="Frequency" placeholder="Frequency" value={line.frequency || line.dose || ""} onChange={(event) => editLine(medicines, setRxLines, index, { frequency: event.target.value })} />
                <input aria-label="Duration" placeholder="Duration" value={line.duration || ""} onChange={(event) => editLine(medicines, setRxLines, index, { duration: event.target.value })} />
                <input aria-label="Quantity" placeholder="Quantity" value={line.quantity || ""} onChange={(event) => editLine(medicines, setRxLines, index, { quantity: Number(event.target.value) })} />
                <input aria-label="Instructions" placeholder="Instructions" value={line.food_instruction || ""} onChange={(event) => editLine(medicines, setRxLines, index, { food_instruction: event.target.value })} />
                <button className="btn small" type="button" aria-label="Remove medicine" onClick={() => setRxLines(medicines.filter((_: any, i: number) => i !== index))}>Remove</button>
              </div>
            ))}
            {!medicines.length && <p className="muted">No medicine added.</p>}
            <div className="row-actions">
              <button className="btn" type="button" onClick={() => setRxLines([...medicines, { medicine_name: "", dose: "", frequency: "", duration: "", quantity: "", food_instruction: "" }])}>+ Add Medicine</button>
              <button className="btn primary" type="button" onClick={savePrescription}>Save Prescription</button>
              {savedRx?.status === "FINALIZED" && <a className="btn" href={fileUrl(`/api/prescriptions/${savedRx.id}/pdf`)} target="_blank" rel="noreferrer">Print Prescription</a>}
            </div>
          </div>
        </section>
      </div>

      <section className="panel opd-labs">
        <header><h2>Lab Tests</h2><button className="btn small" type="button" onClick={() => setLabOpen((open) => !open)}>+ Add Lab Test</button></header>
        <div className="body">
          {labOrders.length === 0 && !labOpen && <p className="muted">No laboratory test requested.</p>}
          {labOrders.map((order: any) => <div className="lab-line" key={order.id}><strong>{order.test_name || order.custom_name || order.id}</strong><span>{simpleLabStatus(order.status)}</span></div>)}
          {labOpen && <TestOrder tests={tests?.items || []} patientId={patient.id} encounterId={data.id} onDone={() => setLabOpen(false)} />}
        </div>
      </section>

      <div className="opd-complete-bar">
        <span className="muted">Save notes and prescription before completing.</span>
        <button className="btn primary" type="button" onClick={() => saveNotes(true)}>COMPLETE OPD</button>
      </div>
    </Page>
  );
}

function simpleLabStatus(status?: string) {
  if (status === "REPORT_UPLOADED") return "REPORT UPLOADED";
  if (status === "SAMPLE_COLLECTED") return "SAMPLE COLLECTED";
  return "PENDING";
}

function MedicinePicker({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const [query, setQuery] = useState(value);
  const [items, setItems] = useState<any[]>([]);
  useEffect(() => {
    const term = query.trim();
    if (term.length < 2) { setItems([]); return; }
    const timer = window.setTimeout(() => api<{ items: any[] }>(`/api/formulary?q=${encodeURIComponent(term)}`).then((row) => setItems(row.items || [])).catch(() => setItems([])), 220);
    return () => window.clearTimeout(timer);
  }, [query]);
  return <div className="medicine-picker"><input aria-label="Medicine" placeholder="Search medicine…" value={query} list="formulary-options" onChange={(event) => { setQuery(event.target.value); onChange(event.target.value); }} /><datalist id="formulary-options">{items.map((item) => <option key={item.id} value={`${item.name}${item.strength ? ` ${item.strength}` : ""}`} />)}</datalist></div>;
}

function editLine(lines: any[], setItems: (v: any[]) => void, index: number, patch: any) {
  setItems(lines.map((line, i) => i === index ? { ...line, ...patch } : line));
}

function TestOrder({ tests, patientId, encounterId, onDone }: any) {
  const [picked, setPicked] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const visibleTests = (tests || []).filter((test: any) => String(test.name || "").toLowerCase().includes(query.trim().toLowerCase()));
  return (
    <div className="lab-request-form">
      <Field label="Search laboratory test"><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search CBC, LFT…" /></Field>
      <div className="grid-form">{visibleTests.map((test: any) => <label key={test.id}><input type="checkbox" checked={picked.includes(test.id)} onChange={(event) => setPicked(event.target.checked ? [...picked, test.id] : picked.filter((id) => id !== test.id))} /> {test.name}</label>)}</div>
      <button className="btn primary" type="button" disabled={!picked.length} onClick={() => run(async () => { await api("/api/lab/orders", { method: "POST", body: JSON.stringify({ patient_id: patientId, encounter_id: encounterId, priority: "ROUTINE", tests: picked.map((test_id) => ({ test_id })) }) }); onDone(); }, "Lab test requested")}>Request Lab Test</button>
    </div>
  );
}

function dispenseKey() {
  return `disp-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export function Pharmacy() {
  const { data, error, loading } = useData<{ items: any[] }>("/api/pharmacy/queue");
  const [current, setCurrent] = useState<string>("");
  const [scan, setScan] = useState("");
  const [hit, setHit] = useState<any>(null);
  const [scanError, setScanError] = useState("");
  const [unknown, setUnknown] = useState(false);
  const [scanner, setScanner] = useState(false);
  const [registering, setRegistering] = useState(false);
  const [, setBusy] = useState(false);
  const canEdit = useApp((s) => s.can("inventory.edit"));
  const canInventory = useApp((s) => s.can("inventory.view"));
  const rx = (data?.items || []).find((r) => r.id === current) || data?.items?.[0];
  const [lines, setLines] = useState<Record<string, any>>({});
  const held = useRef<{ stamp: string; key: string }>({ stamp: "", key: "" });

  async function lookup(code: string) {
    const prepared = prepareBarcode(code);
    setScan(prepared.code);
    setScanError("");
    setHit(null);
    setUnknown(false);
    if (prepared.error) {
      setScanError(prepared.error);
      return;
    }
    try {
      setHit(await api<any>("/api/inventory/barcodes/resolve", { method: "POST", body: JSON.stringify({ code: prepared.code }) }));
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setUnknown(true);
        setScanError("Barcode not registered");
        return;
      }
      setScanError(err instanceof Error ? err.message : "The hospital server could not be reached. Check the connection, then try the same barcode again.");
    }
  }

  async function onScan(e: React.FormEvent) {
    e.preventDefault();
    await lookup(scan);
  }

  function draftFor(item: any) {
    return lines[item.id] || {
      qty: Math.max((item.quantity || 0) - (item.dispensed_qty || 0), 0),
      batch_id: "",
      product_id: item.product_id,
      reason: "",
    };
  }

  function applyScan(item: any, batchId = "") {
    if (!hit?.product) return;
    const draft = draftFor(item);
    setLines({
      ...lines,
      [item.id]: {
        ...draft,
        product_id: hit.product.id,
        batch_id: batchId,
      },
    });
  }

  function payloadLines() {
    return (rx?.items || []).map((item: any) => {
      const draft = draftFor(item);
      const productId = draft.product_id || item.product_id;
      const substituted = Boolean(item.product_id && productId && productId !== item.product_id);
      return {
        item_id: item.id,
        qty: Number(draft.qty) || 0,
        batch_id: draft.batch_id,
        product_id: productId,
        substituted,
        substitution_reason: substituted ? draft.reason || "" : "",
      };
    }).filter((line: any) => line.qty > 0);
  }

  async function confirmDispense() {
    const selected = payloadLines();
    if (!rx || !selected.length) return;
    if (selected.some((line: any) => !line.batch_id)) {
      setScanError("Choose a batch for each line. The scan does not choose one.");
      return;
    }
    if (selected.some((line: any) => line.substituted && !line.substitution_reason)) {
      setScanError("A substitution needs a reason. The prescription is not rewritten.");
      return;
    }
    const stamp = JSON.stringify({ prescription_id: rx.id, lines: selected });
    if (held.current.stamp !== stamp) held.current = { stamp, key: dispenseKey() };
    setBusy(true);
    try {
      await run(() => api("/api/pharmacy/dispense", {
        method: "POST",
        headers: { "Idempotency-Key": held.current.key },
        body: JSON.stringify({ prescription_id: rx.id, lines: selected }),
      }), "Dispensed. Stock and the draft charge were updated.");
      held.current = { stamp: "", key: "" };
      setHit(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Page title="Pharmacy" note="Medicine master, packaging, barcode, and batch. Medicine is issued from Billing. A scan only identifies a barcode." actions={canInventory ? <Link className="btn" to="/inventory">Open inventory</Link> : undefined}>
      <Flow steps={["Scan", "Package identified", "Select batch", "Confirm dispense"]} current={hit ? "Select batch" : scan ? "Scan" : ""} />
      <form className="panel scanner" onSubmit={onScan}>
        <div className="body">
          <Field label="Scan barcode">
            <input value={scan} onChange={(e) => { setScan(e.target.value); setHit(null); setUnknown(false); }} placeholder="USB scanner or typed code. Enter identifies it. It does not dispense." />
          </Field>
          <button type="button" className="btn" onClick={() => setScanner(true)}>Scan with webcam</button>
          <PhonePair onUse={(code) => lookup(code)} />
          <p className="muted">A scan only identifies the package. It does not choose a batch, dispense, or change stock.</p>
          {scanError && <div className="warn">{scanError}</div>}
          {unknown && (
            <div className="row-actions">
              {canEdit && <button type="button" className="btn primary" onClick={() => setRegistering(true)}>Register New Medicine</button>}
              {!canEdit && <span className="muted">This login cannot register a medicine. Scan again, or ask the store.</span>}
              <button type="button" className="btn" onClick={() => setScanner(true)}>Scan Again</button>
            </div>
          )}
          {hit && (
            <div>
              <p><strong>{hit.product.name}</strong> {hit.product.strength}</p>
              <p>{hit.sku ? `Packaging ${hit.sku.name} · ${hit.sku.units_per_pack} ${hit.product.unit} per ${hit.sku.unit}` : "No package conversion stored"} · stock {hit.product.stock} {hit.product.unit}</p>
              <p className="muted">Select a batch, enter the quantity, then confirm. Scanning did not change stock.</p>
              {hit.matched_batch && <p className="muted">This barcode also names batch {hit.matched_batch.batch_no}. Still select it below.</p>}
              {(hit.suggestions || []).slice(0, 4).map((batch: any) => (
                <button key={batch.id} type="button" className="btn small" style={{ marginRight: 6 }} onClick={() => rx?.items?.[0] && applyScan(rx.items.find((item: any) => item.product_id === hit.product.id) || rx.items[0], batch.id)}>
                  Select {batch.batch_no} · exp {batch.expiry_date || "—"} · {batch.qty_on_hand}
                </button>
              ))}
            </div>
          )}
        </div>
      </form>
      {scanner && <BarcodeScanner onClose={() => setScanner(false)} onUse={(code) => { setScanner(false); lookup(code); }} />}
      {registering && <RegisterMedicine barcode={scan} onClose={() => setRegistering(false)} onRegistered={(value) => { setRegistering(false); lookup(value); }} />}
      {loading && !data && <Loading label="Opening the pharmacy queue…" />}
      {error && <ErrorState message={error} />}
      {!loading && data && !data.items?.length && <Empty text="No prescription is waiting. A finalized prescription appears here." />}
      <div className="grid-2">
        <div className="table-wrap"><table className="data">
          <thead><tr><th>When</th><th>Patient</th><th>Doctor</th><th>Status</th></tr></thead>
          <tbody>
            {(data?.items || []).map((r: any) => (
              <tr key={r.id} className={rx?.id === r.id ? "selected" : ""} onClick={() => setCurrent(r.id)} style={{ cursor: "pointer" }}>
                <td>{when(r.finalized_at)}</td>
                <td>{r.patient_name}<div className="muted">{r.id}</div></td>
                <td>{r.doctor_name}</td>
                <td><Status value={r.status} /></td>
              </tr>
            ))}
          </tbody>
        </table></div>
        <div className="panel">
          <h2>{rx ? rx.patient_name : "No prescription waiting"}</h2>
          <div className="body">
            {(rx?.items || []).map((item: any) => {
              const draft = draftFor(item);
              const remaining = Math.max((item.quantity || 0) - (item.dispensed_qty || 0), 0);
              const productId = draft.product_id || item.product_id;
              const substituted = Boolean(item.product_id && productId && productId !== item.product_id);
              return (
                <div key={item.id} style={{ borderBottom: "1px solid var(--line)", padding: "8px 0" }}>
                  <strong>{item.medicine_name}</strong> {item.strength}
                  <div className="muted">{item.dose} · {item.duration} · {item.food_instruction}</div>
                  <div className="muted">Prescribed {item.quantity} {item.unit} · dispensed {item.dispensed_qty || 0} · remaining {remaining}</div>
                  {hit && <button type="button" className="btn small" onClick={() => applyScan(item)}>Apply scan to this line</button>}
                  <div className="grid-form" style={{ marginTop: 6 }}>
                    <Field label="Batch"><BatchSelect productId={productId} value={draft.batch_id} onChange={(batch_id, product_id) => setLines({ ...lines, [item.id]: { ...draft, batch_id, product_id } })} /></Field>
                    <Field label="Qty"><input value={draft.qty} onChange={(e) => setLines({ ...lines, [item.id]: { ...draft, qty: Number(e.target.value) } })} /></Field>
                    {substituted && <Field label="Substitution reason" className="span-2"><input value={draft.reason} onChange={(e) => setLines({ ...lines, [item.id]: { ...draft, reason: e.target.value } })} placeholder="Required. The prescribed name stays as written." /></Field>}
                  </div>
                </div>
              );
            })}
            {rx && <p className="muted">Issuing medicine onto a bill is done at Billing. This older dispense action still posts to the pharmacy API and changes stock. Do not use it for a bill.</p>}
            {rx && <button className="btn" onClick={confirmDispense}>Record a pharmacy dispense</button>}
          </div>
        </div>
      </div>
    </Page>
  );
}

function BatchSelect({ productId, value, onChange }: { productId?: string; value: string; onChange: (batch: string, product: string) => void }) {
  const { data } = useData<any>(productId ? `/api/inventory/products/${productId}` : null);
  if (!productId) return <input placeholder="Link a product" disabled />;
  return (
    <select value={value} onChange={(e) => onChange(e.target.value, productId)}>
      <option value="">FEFO suggestion</option>
      {(data?.batches || []).filter((b: any) => b.qty_on_hand > 0).map((b: any) => (
        <option key={b.id} value={b.id}>{b.batch_no} · exp {b.expiry_date || "—"} · {b.qty_on_hand} · {money(b.sale_rate_paise)}</option>
      ))}
    </select>
  );
}

export function RegisterMedicine({ barcode, onClose, onRegistered }: { barcode: string; onClose: () => void; onRegistered: (barcode: string) => void }) {
  const { data: types } = useData<{ items: any[] }>("/api/inventory/barcode-types");
  const [name, setName] = useState("");
  const [brand, setBrand] = useState("");
  const [composition, setComposition] = useState("");
  const [strength, setStrength] = useState("");
  const [unit, setUnit] = useState("Tablet");
  const [manufacturer, setManufacturer] = useState("");
  const [skuName, setSkuName] = useState("Strip");
  const [skuUnit, setSkuUnit] = useState("Strip");
  const [packSize, setPackSize] = useState("");
  const [code, setCode] = useState(barcode);
  const [barcodeType, setBarcodeType] = useState("");
  const [batchNo, setBatchNo] = useState("");
  const [mfg, setMfg] = useState("");
  const [expiry, setExpiry] = useState("");
  const [qty, setQty] = useState("");
  const [busy, setBusy] = useState(false);

  async function save() {
    if (!name.trim() || !skuName.trim() || !skuUnit.trim() || !packSize || !code.trim() || !barcodeType) {
      throw new Error("Enter the medicine, package, package size, barcode, and barcode type. Nothing is assumed.");
    }
    if ((batchNo.trim() || Number(qty) > 0) && (!batchNo.trim() || !(Number(qty) > 0) || !mfg || !expiry)) {
      throw new Error("To receive stock, enter the batch, manufactured date, expiry, and quantity. Otherwise leave all four blank.");
    }
    setBusy(true);
    try {
      const product = await api<any>("/api/inventory/products", { method: "POST", body: JSON.stringify({ name, brand, composition, strength, unit, manufacturer }) });
      const sku = await api<any>("/api/inventory/skus", { method: "POST", body: JSON.stringify({ product_id: product.id, name: skuName, unit: skuUnit, units_per_pack: Number(packSize) }) });
      await api("/api/inventory/barcodes", { method: "POST", body: JSON.stringify({ sku_id: sku.id, value: code.trim(), barcode_type: barcodeType, scope: "SKU" }) });
      if (batchNo.trim() && Number(qty) > 0) {
        await api("/api/inventory/receive", { method: "POST", body: JSON.stringify({ barcode: code.trim(), batch_no: batchNo.trim(), mfg_date: mfg, expiry_date: expiry, qty: Number(qty) }) });
      }
      onRegistered(code.trim());
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Register medicine" onClose={onClose} footer={<button className="btn primary" disabled={busy} onClick={() => run(save, batchNo && Number(qty) > 0 ? "Medicine registered and stock received" : "Medicine registered. No stock was added.")}>Save product, package, and barcode</button>}>
      <p className="muted">An unknown barcode is not a product. Register the medicine, then the package, then the barcode. Stock is added only if you also enter a batch and a quantity.</p>
      <div className="grid-form">
        <Field label="Medicine name"><input value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Brand"><input value={brand} onChange={(e) => setBrand(e.target.value)} /></Field>
        <Field label="Composition"><input value={composition} onChange={(e) => setComposition(e.target.value)} /></Field>
        <Field label="Strength"><input value={strength} onChange={(e) => setStrength(e.target.value)} /></Field>
        <Field label="Base unit"><input value={unit} onChange={(e) => setUnit(e.target.value)} /></Field>
        <Field label="Manufacturer"><input value={manufacturer} onChange={(e) => setManufacturer(e.target.value)} /></Field>
        <Field label="Package name"><input value={skuName} onChange={(e) => setSkuName(e.target.value)} /></Field>
        <Field label="Package unit"><input value={skuUnit} onChange={(e) => setSkuUnit(e.target.value)} /></Field>
        <Field label="Base units in this package"><input value={packSize} onChange={(e) => setPackSize(e.target.value)} placeholder="Enter the count. Do not assume 10." /></Field>
        <Field label="Barcode"><input value={code} onChange={(e) => setCode(e.target.value)} /></Field>
        <Field label="Barcode type">
          <select value={barcodeType} onChange={(e) => setBarcodeType(e.target.value)}>
            <option value="">{(types?.items || []).length ? "Choose a configured type" : "No barcode types configured"}</option>
            {(types?.items || []).map((item) => <option key={item.code} value={item.code}>{item.name}</option>)}
          </select>
        </Field>
        <Field label="Batch, optional"><input value={batchNo} onChange={(e) => setBatchNo(e.target.value)} /></Field>
        <Field label="Manufactured, if receiving"><input value={mfg} onChange={(e) => setMfg(e.target.value)} placeholder="YYYY-MM-DD" /></Field>
        <Field label="Expiry, if receiving"><input value={expiry} onChange={(e) => setExpiry(e.target.value)} placeholder="YYYY-MM-DD" /></Field>
        <Field label="Quantity to receive, optional"><input value={qty} onChange={(e) => setQty(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}
function labStage(item: any, order: any) {
  if (item.document_id || order.status === "REPORT_UPLOADED") return "REPORT UPLOADED";
  if (["SAMPLE_COLLECTED", "PROCESSING", "RESULT_PENDING", "RESULT_ENTERED", "VERIFIED"].includes(item.status)) return "SAMPLE COLLECTED";
  return "PENDING";
}

function fileToBase64(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

export function LabPage() {
  const can = useApp((state) => state.can);
  const { data, error, loading } = useData<{ items: any[] }>("/api/lab/orders");
  const [uploading, setUploading] = useState<string | null>(null);
  const [sending, setSending] = useState<string | null>(null);

  async function upload(order: any, file: File) {
    if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) throw new Error("Upload the actual laboratory report as a PDF.");
    setUploading(order.id);
    try {
      const content_base64 = await fileToBase64(file);
      await run(() => api(`/api/lab/orders/${order.id}/report-upload`, { method: "POST", body: JSON.stringify({ filename: file.name, title: file.name, mime_type: "application/pdf", content_base64 }) }), "Report uploaded");
    } finally {
      setUploading(null);
    }
  }

  async function sendReport(order: any, documentId: string) {
    setSending(order.id);
    try {
      await run(() => api("/api/whatsapp/documents", { method: "POST", body: JSON.stringify({ patient_id: order.patient_id, document_id: documentId, caption: `${order.patient_name} laboratory report`, confirm: true }) }), "Report sent via WhatsApp");
    } finally {
      setSending(null);
    }
  }

  return (
    <Page title="Laboratory" note="Pending → sample collected → report uploaded">
      {loading && !data && <Loading label="Opening laboratory queue…" />}
      {error && <ErrorState message={error} />}
      {!loading && data && !data.items?.length && <Empty text="No laboratory tests are waiting." />}
      <div className="lab-queue">
        {(data?.items || []).flatMap((order: any) => (order.items || []).map((item: any) => ({ order, item }))).map(({ order, item }: any) => {
          const stage = labStage(item, order);
          const documentId = item.document_id;
          return (
            <section className="panel lab-card" key={item.id}>
              <header>
                <div><h2>{item.test_name || item.custom_name || item.id}</h2><p className="muted">Patient: {order.patient_name} · Patient ID: <span className="pid">{order.patient_id}</span> · OPD: <span className="pid">{order.encounter_id || "—"}</span></p></div>
                <strong>{stage}</strong>
              </header>
              <div className="body">
                {stage === "PENDING" && can("lab.sample.collect") && <button className="btn primary" type="button" onClick={() => run(() => api(`/api/lab/orders/${order.id}/samples`, { method: "POST", body: JSON.stringify({ item_ids: [item.id], idempotency_key: `collect-${item.id}` }) }), "Sample collected")}>COLLECT SAMPLE</button>}
                {stage === "SAMPLE COLLECTED" && can("document.upload") && (
                  <label className="btn primary report-upload">UPLOAD REPORT
                    <input type="file" accept="application/pdf,.pdf" disabled={uploading === order.id} onChange={(event) => { const file = event.target.files?.[0]; if (file) upload(order, file).catch((error: Error) => useApp.getState().toast(error.message, "bad")); event.currentTarget.value = ""; }} />
                  </label>
                )}
                {stage === "REPORT UPLOADED" && documentId && (
                  <div className="row-actions">
                    <a className="btn" href={fileUrl(`/api/documents/${documentId}/file`)} target="_blank" rel="noreferrer">VIEW REPORT</a>
                    <a className="btn" href={fileUrl(`/api/documents/${documentId}/file`)} download>DOWNLOAD</a>
                    {can("whatsapp.send") && <button className="btn" type="button" disabled={sending === order.id} onClick={() => sendReport(order, documentId).catch((error: Error) => useApp.getState().toast(error.message || "WhatsApp delivery failed", "bad"))}>{sending === order.id ? "Sending…" : "SEND VIA WHATSAPP"}</button>}
                  </div>
                )}
                {stage === "REPORT UPLOADED" && !documentId && <p className="muted">Report uploaded. The document link is being refreshed.</p>}
              </div>
            </section>
          );
        })}
      </div>
    </Page>
  );
}
