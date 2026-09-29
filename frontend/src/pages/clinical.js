import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError, api, fileUrl, money, when } from "../api";
import { useApp } from "../store";
import { Empty, ErrorState, Field, Flow, Loading, Modal, Page, Status, run, useData } from "../ui";
import { prepareBarcode } from "../barcode";
import { BarcodeScanner, PhonePair } from "../scanner";
export function Consult() {
    const { id } = useParams();
    const { data, error } = useData(id ? `/api/opd/${id}` : null);
    const { data: tests } = useData("/api/lab/tests");
    const [note, setNote] = useState(null);
    const [items, setItems] = useState(null);
    const [testOpen, setTestOpen] = useState(false);
    const [otOpen, setOtOpen] = useState(false);
    const [admitOpen, setAdmitOpen] = useState(false);
    const navigate = useNavigate();
    if (error)
        return _jsx(Page, { title: "Encounter", children: _jsx(ErrorState, { message: error }) });
    if (!data)
        return _jsx(Page, { title: "Encounter", children: _jsx(Loading, { label: "Opening encounter\u2026" }) });
    const p = data.patient;
    const consult = note || data.consultation || { symptoms: "", findings: "", diagnosis: "", notes: "", instructions: "", follow_up: "" };
    const rx = data.prescriptions?.[0];
    const lines = items || rx?.items || [{ medicine_name: "", strength: "", dose: "1-0-1", route: "Oral", duration: "5 Days", duration_days: 5, food_instruction: "After food", quantity: 10, unit: "Tablet" }];
    async function saveNote(complete = false) {
        await run(async () => {
            await api("/api/consultations", { method: "POST", body: JSON.stringify({ ...consult, encounter_id: data.id, complete }) });
            if (complete)
                navigate("/doctor");
        }, complete ? "Visit completed" : "Consultation saved");
    }
    async function saveRx(finalize) {
        await run(async () => {
            const body = { encounter_id: data.id, items: lines.filter((l) => l.medicine_name) };
            const saved = rx && rx.status === "DRAFT"
                ? await api(`/api/prescriptions/${rx.id}`, { method: "PUT", body: JSON.stringify(body) })
                : await api("/api/prescriptions", { method: "POST", body: JSON.stringify(body) });
            if (finalize)
                await api(`/api/prescriptions/${saved.id}/finalize`, { method: "POST" });
        }, finalize ? "Prescription sent to pharmacy" : "Prescription saved");
    }
    return (_jsxs(Page, { kicker: "Encounter", title: p.name, note: data.id, actions: _jsx(Link, { className: "btn", to: "/doctor", children: "Back to queue" }), children: [_jsxs("div", { className: "banner", children: [_jsxs("div", { children: [_jsxs("h2", { children: [p.name, " ", _jsx("span", { className: "muted", children: p.id })] }), _jsxs("div", { className: "identity", children: [p.id, " \u00B7 ", p.age_display, " \u00B7 ", p.gender, " \u00B7 ", p.primary_phone || "no phone", " \u00B7 ", data.opd_type_name, " \u00B7 ", data.doctor_name || "Unassigned"] }), _jsxs("div", { className: "muted", children: ["Token ", data.queue?.token_no ? `T-${String(data.queue.token_no).padStart(3, "0")}` : "—", " \u00B7 ", data.chief_complaint || "No complaint recorded", " \u00B7 valid ", when(data.validity_until)] })] }), _jsxs("div", { children: [p.allergies && _jsxs("div", { className: "allergy", children: ["Allergy: ", p.allergies] }), _jsx("div", { style: { marginTop: 8 }, children: _jsx(Status, { value: data.queue?.status || data.status }) })] })] }), _jsxs("div", { className: "consult-grid", children: [_jsxs("div", { className: "panel", children: [_jsx("h2", { children: "History" }), _jsxs("div", { className: "body", children: [_jsx("p", { className: "muted", children: p.address }), _jsxs("p", { children: ["Guardian ", p.guardian_name || "—"] }), data.admission && _jsxs("p", { children: ["Active admission ", data.admission.id, " \u00B7 ", _jsx(Status, { value: data.admission.status })] }), _jsx(Link, { to: `/patients/${p.id}`, children: "Full record" }), _jsx("div", { className: "row-actions", style: { marginTop: 12 }, children: (data.queue?.allowed_next || []).map((s) => (_jsx("button", { className: "btn small", onClick: () => run(() => api(`/api/queue/${data.queue.id}/status`, { method: "POST", body: JSON.stringify({ status: s }) }), s), children: s.replaceAll("_", " ") }, s))) })] })] }), _jsxs("div", { className: "consult-main", children: [_jsxs("div", { className: "panel", children: [_jsx("h2", { children: "Consultation" }), _jsxs("div", { className: "body grid-form", children: [_jsx(Field, { label: "Symptoms", className: "span-2", children: _jsx("textarea", { value: consult.symptoms || "", onChange: (e) => setNote({ ...consult, symptoms: e.target.value }) }) }), _jsx(Field, { label: "Findings", className: "span-2", children: _jsx("textarea", { value: consult.findings || "", onChange: (e) => setNote({ ...consult, findings: e.target.value }) }) }), _jsx(Field, { label: "Diagnosis", className: "span-2", children: _jsx("input", { value: consult.diagnosis || "", onChange: (e) => setNote({ ...consult, diagnosis: e.target.value }) }) }), _jsx(Field, { label: "Instructions", className: "span-2", children: _jsx("textarea", { value: consult.instructions || "", onChange: (e) => setNote({ ...consult, instructions: e.target.value }) }) }), _jsx(Field, { label: "Follow-up", children: _jsx("input", { value: consult.follow_up || "", onChange: (e) => setNote({ ...consult, follow_up: e.target.value }) }) }), _jsx(Field, { label: "Clinical note", children: _jsx("input", { value: consult.notes || "", onChange: (e) => setNote({ ...consult, notes: e.target.value }) }) }), _jsxs("div", { className: "span-2 row-actions", children: [_jsx("button", { className: "btn", onClick: () => saveNote(false), children: "Save notes" }), _jsx("button", { className: "btn primary", onClick: () => saveNote(true), children: "Save and complete" })] })] })] }), _jsxs("div", { className: "panel", children: [_jsx("h2", { children: "Prescription" }), _jsxs("div", { className: "body", children: [lines.map((line, index) => (_jsxs("div", { className: "rx-row", children: [_jsx("input", { placeholder: "Medicine", value: line.medicine_name || "", onChange: (e) => editLine(lines, setItems, index, { medicine_name: e.target.value }), list: "formulary", onBlur: () => suggest(line, lines, setItems, index) }), _jsx("input", { placeholder: "Strength", value: line.strength || "", onChange: (e) => editLine(lines, setItems, index, { strength: e.target.value }) }), _jsx("input", { placeholder: "1-0-1", value: line.dose || "", onChange: (e) => editLine(lines, setItems, index, { dose: e.target.value }) }), _jsx("input", { placeholder: "5 Days", value: line.duration || "", onChange: (e) => editLine(lines, setItems, index, { duration: e.target.value }) }), _jsx("input", { placeholder: "After food", value: line.food_instruction || "", onChange: (e) => editLine(lines, setItems, index, { food_instruction: e.target.value }) }), _jsx("input", { placeholder: "Qty", value: line.quantity || "", onChange: (e) => editLine(lines, setItems, index, { quantity: Number(e.target.value) }) }), _jsx("button", { className: "btn small", onClick: () => setItems(lines.filter((_, i) => i !== index)), children: "\u00D7" })] }, index))), _jsx("datalist", { id: "formulary" }), _jsxs("div", { className: "row-actions", children: [_jsx("button", { className: "btn", onClick: () => setItems([...lines, { medicine_name: "", dose: "1-0-1", route: "Oral", duration: "5 Days", quantity: 10, unit: "Tablet", food_instruction: "After food" }]), children: "Add medicine" }), _jsx("button", { className: "btn", onClick: () => saveRx(false), children: "Save draft" }), _jsx("button", { className: "btn primary", onClick: () => saveRx(true), children: "Finalize prescription" })] }), rx && _jsxs("p", { className: "muted", children: [rx.id, " \u00B7 ", _jsx(Status, { value: rx.status })] }), rx?.status === "FINALIZED" && (_jsxs("div", { className: "row-actions", children: [_jsx("a", { className: "btn", href: fileUrl(`/api/prescriptions/${rx.id}/pdf`), target: "_blank", rel: "noreferrer", children: "Print prescription" }), _jsx(Link, { className: "btn", to: `/patients/${data.patient?.id || data.patient_id}`, children: "Documents" })] }))] })] })] })] }), _jsxs("div", { className: "row-actions", style: { marginTop: 8 }, children: [_jsx("button", { className: "btn", onClick: () => setTestOpen(true), children: "Order test" }), _jsx("button", { className: "btn", onClick: () => setOtOpen(true), children: "Request OT" }), _jsx("button", { className: "btn", onClick: () => setAdmitOpen(true), children: "Request admission" }), data.invoices?.[0] && _jsxs(Link, { className: "btn", to: `/billing/${data.invoices[0].id}`, children: ["Bill ", data.invoices[0].number] })] }), testOpen && (_jsx(Modal, { title: "Order test", onClose: () => setTestOpen(false), children: _jsx(TestOrder, { tests: tests?.items || [], patientId: p.id, encounterId: data.id, onDone: () => setTestOpen(false) }) })), otOpen && (_jsx(Modal, { title: "OT request", onClose: () => setOtOpen(false), children: _jsx(OtRequest, { patientId: p.id, encounterId: data.id, admissionId: data.admission?.id, onDone: (id) => { setOtOpen(false); navigate(`/ot/${id}`); } }) })), admitOpen && (_jsx(Modal, { title: "Admission", onClose: () => setAdmitOpen(false), children: _jsx(AdmitRequest, { patientId: p.id, encounterId: data.id, onDone: (id) => { setAdmitOpen(false); navigate(`/admissions/${id}`); } }) }))] }));
}
function editLine(lines, setItems, index, patch) {
    setItems(lines.map((line, i) => i === index ? { ...line, ...patch } : line));
}
async function suggest(line, lines, setItems, index) {
    if (!line.medicine_name || line.product_id)
        return;
    try {
        const found = await api(`/api/formulary?q=${encodeURIComponent(line.medicine_name)}`);
        const hit = found.items[0];
        if (!hit)
            return;
        editLine(lines, setItems, index, { product_id: hit.id, medicine_name: hit.name, strength: hit.strength, unit: hit.unit });
    }
    catch {
        /* free text remains valid */
    }
}
function TestOrder({ tests, patientId, encounterId, onDone }) {
    const [picked, setPicked] = useState([]);
    const [custom, setCustom] = useState("");
    const [priority, setPriority] = useState("ROUTINE");
    return (_jsxs("div", { children: [_jsx("div", { className: "grid-form", children: (tests || []).map((t) => (_jsxs("label", { children: [_jsx("input", { type: "checkbox", checked: picked.includes(t.id), onChange: (e) => setPicked(e.target.checked ? [...picked, t.id] : picked.filter((id) => id !== t.id)) }), " ", t.name, " \u00B7 ", money(t.price_paise)] }, t.id))) }), _jsx(Field, { label: "Priority", children: _jsxs("select", { value: priority, onChange: (e) => setPriority(e.target.value), children: [_jsx("option", { children: "ROUTINE" }), _jsx("option", { children: "URGENT" }), _jsx("option", { children: "STAT" })] }) }), _jsx(Field, { label: "Custom test if it is not in the list", children: _jsx("input", { value: custom, onChange: (e) => setCustom(e.target.value) }) }), _jsx("button", { className: "btn primary", style: { marginTop: 10 }, onClick: () => run(async () => {
                    await api("/api/lab/orders", { method: "POST", body: JSON.stringify({ patient_id: patientId, encounter_id: encounterId, priority, tests: [...picked.map((id) => ({ test_id: id })), ...(custom ? [{ custom_name: custom }] : [])] }) });
                    onDone();
                }, "Test ordered and sent to billing"), children: "Order" })] }));
}
function OtRequest({ patientId, encounterId, admissionId, onDone }) {
    const [name, setName] = useState("");
    return (_jsxs("div", { className: "grid-form", children: [_jsx(Field, { label: "Procedure", className: "span-2", children: _jsx("input", { value: name, onChange: (e) => setName(e.target.value) }) }), _jsx("button", { className: "btn primary", onClick: () => run(async () => {
                    const created = await api("/api/ot", { method: "POST", body: JSON.stringify({ patient_id: patientId, encounter_id: encounterId, admission_id: admissionId, procedure_name: name }) });
                    onDone(created.id);
                }, "OT requested"), children: "Request" })] }));
}
function AdmitRequest({ patientId, encounterId, onDone }) {
    const { data } = useData("/api/beds");
    const [bed, setBed] = useState("");
    const [reason, setReason] = useState("");
    const beds = (data?.wards || []).flatMap((w) => (w.beds || []).filter((b) => b.status === "AVAILABLE").map((b) => ({ ...b, ward: w.name })));
    return (_jsxs("div", { className: "grid-form", children: [_jsx(Field, { label: "Reason", className: "span-2", children: _jsx("input", { value: reason, onChange: (e) => setReason(e.target.value) }) }), _jsx(Field, { label: "Bed", className: "span-2", children: _jsxs("select", { value: bed, onChange: (e) => setBed(e.target.value), children: [_jsx("option", { value: "", children: "Request without a bed" }), beds.map((b) => _jsxs("option", { value: b.id, children: [b.ward, " \u00B7 ", b.room_name, " \u00B7 ", b.name] }, b.id))] }) }), _jsx("button", { className: "btn primary", onClick: () => run(async () => {
                    const created = await api("/api/admissions", { method: "POST", body: JSON.stringify({ patient_id: patientId, encounter_id: encounterId, bed_id: bed || null, reason, diagnosis: reason }) });
                    onDone(created.id);
                }, "Admission recorded"), children: "Admit" })] }));
}
function dispenseKey() {
    return `disp-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}
export function Pharmacy() {
    const { data, error, loading } = useData("/api/pharmacy/queue");
    const [current, setCurrent] = useState("");
    const [scan, setScan] = useState("");
    const [hit, setHit] = useState(null);
    const [scanError, setScanError] = useState("");
    const [unknown, setUnknown] = useState(false);
    const [scanner, setScanner] = useState(false);
    const [registering, setRegistering] = useState(false);
    const [busy, setBusy] = useState(false);
    const canEdit = useApp((s) => s.can("inventory.edit"));
    const canInventory = useApp((s) => s.can("inventory.view"));
    const rx = (data?.items || []).find((r) => r.id === current) || data?.items?.[0];
    const [lines, setLines] = useState({});
    const held = useRef({ stamp: "", key: "" });
    async function lookup(code) {
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
            setHit(await api("/api/inventory/barcodes/resolve", { method: "POST", body: JSON.stringify({ code: prepared.code }) }));
        }
        catch (err) {
            if (err instanceof ApiError && err.status === 404) {
                setUnknown(true);
                setScanError("Barcode not registered");
                return;
            }
            setScanError(err instanceof Error ? err.message : "The hospital server could not be reached. Check the connection, then try the same barcode again.");
        }
    }
    async function onScan(e) {
        e.preventDefault();
        await lookup(scan);
    }
    function draftFor(item) {
        return lines[item.id] || {
            qty: Math.max((item.quantity || 0) - (item.dispensed_qty || 0), 0),
            batch_id: "",
            product_id: item.product_id,
            reason: "",
        };
    }
    function applyScan(item, batchId = "") {
        if (!hit?.product)
            return;
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
        return (rx?.items || []).map((item) => {
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
        }).filter((line) => line.qty > 0);
    }
    async function confirmDispense() {
        const selected = payloadLines();
        if (!rx || !selected.length)
            return;
        if (selected.some((line) => !line.batch_id)) {
            setScanError("Choose a batch for each line. The scan does not choose one.");
            return;
        }
        if (selected.some((line) => line.substituted && !line.substitution_reason)) {
            setScanError("A substitution needs a reason. The prescription is not rewritten.");
            return;
        }
        const stamp = JSON.stringify({ prescription_id: rx.id, lines: selected });
        if (held.current.stamp !== stamp)
            held.current = { stamp, key: dispenseKey() };
        setBusy(true);
        try {
            await run(() => api("/api/pharmacy/dispense", {
                method: "POST",
                headers: { "Idempotency-Key": held.current.key },
                body: JSON.stringify({ prescription_id: rx.id, lines: selected }),
            }), "Dispensed. Stock and the draft charge were updated.");
            held.current = { stamp: "", key: "" };
            setHit(null);
        }
        finally {
            setBusy(false);
        }
    }
    return (_jsxs(Page, { title: "Pharmacy", note: "Medicine master, packaging, barcode, and batch. Medicine is issued from Billing. A scan only identifies a barcode.", actions: canInventory ? _jsx(Link, { className: "btn", to: "/inventory", children: "Open inventory" }) : undefined, children: [_jsx(Flow, { steps: ["Scan", "Package identified", "Select batch", "Confirm dispense"], current: hit ? "Select batch" : scan ? "Scan" : "" }), _jsx("form", { className: "panel scanner", onSubmit: onScan, children: _jsxs("div", { className: "body", children: [_jsx(Field, { label: "Scan barcode", children: _jsx("input", { value: scan, onChange: (e) => { setScan(e.target.value); setHit(null); setUnknown(false); }, placeholder: "USB scanner or typed code. Enter identifies it. It does not dispense." }) }), _jsx("button", { type: "button", className: "btn", onClick: () => setScanner(true), children: "Scan with webcam" }), _jsx(PhonePair, { onUse: (code) => lookup(code) }), _jsx("p", { className: "muted", children: "A scan only identifies the package. It does not choose a batch, dispense, or change stock." }), scanError && _jsx("div", { className: "warn", children: scanError }), unknown && (_jsxs("div", { className: "row-actions", children: [canEdit && _jsx("button", { type: "button", className: "btn primary", onClick: () => setRegistering(true), children: "Register New Medicine" }), !canEdit && _jsx("span", { className: "muted", children: "This login cannot register a medicine. Scan again, or ask the store." }), _jsx("button", { type: "button", className: "btn", onClick: () => setScanner(true), children: "Scan Again" })] })), hit && (_jsxs("div", { children: [_jsxs("p", { children: [_jsx("strong", { children: hit.product.name }), " ", hit.product.strength] }), _jsxs("p", { children: [hit.sku ? `Packaging ${hit.sku.name} · ${hit.sku.units_per_pack} ${hit.product.unit} per ${hit.sku.unit}` : "No package conversion stored", " \u00B7 stock ", hit.product.stock, " ", hit.product.unit] }), _jsx("p", { className: "muted", children: "Select a batch, enter the quantity, then confirm. Scanning did not change stock." }), hit.matched_batch && _jsxs("p", { className: "muted", children: ["This barcode also names batch ", hit.matched_batch.batch_no, ". Still select it below."] }), (hit.suggestions || []).slice(0, 4).map((batch) => (_jsxs("button", { type: "button", className: "btn small", style: { marginRight: 6 }, onClick: () => rx?.items?.[0] && applyScan(rx.items.find((item) => item.product_id === hit.product.id) || rx.items[0], batch.id), children: ["Select ", batch.batch_no, " \u00B7 exp ", batch.expiry_date || "—", " \u00B7 ", batch.qty_on_hand] }, batch.id)))] }))] }) }), scanner && _jsx(BarcodeScanner, { onClose: () => setScanner(false), onUse: (code) => { setScanner(false); lookup(code); } }), registering && _jsx(RegisterMedicine, { barcode: scan, onClose: () => setRegistering(false), onRegistered: (value) => { setRegistering(false); lookup(value); } }), loading && !data && _jsx(Loading, { label: "Opening the pharmacy queue\u2026" }), error && _jsx(ErrorState, { message: error }), !loading && data && !data.items?.length && _jsx(Empty, { text: "No prescription is waiting. A finalized prescription appears here." }), _jsxs("div", { className: "grid-2", children: [_jsx("div", { className: "table-wrap", children: _jsxs("table", { className: "data", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "When" }), _jsx("th", { children: "Patient" }), _jsx("th", { children: "Doctor" }), _jsx("th", { children: "Status" })] }) }), _jsx("tbody", { children: (data?.items || []).map((r) => (_jsxs("tr", { className: rx?.id === r.id ? "selected" : "", onClick: () => setCurrent(r.id), style: { cursor: "pointer" }, children: [_jsx("td", { children: when(r.finalized_at) }), _jsxs("td", { children: [r.patient_name, _jsx("div", { className: "muted", children: r.id })] }), _jsx("td", { children: r.doctor_name }), _jsx("td", { children: _jsx(Status, { value: r.status }) })] }, r.id))) })] }) }), _jsxs("div", { className: "panel", children: [_jsx("h2", { children: rx ? rx.patient_name : "No prescription waiting" }), _jsxs("div", { className: "body", children: [(rx?.items || []).map((item) => {
                                        const draft = draftFor(item);
                                        const remaining = Math.max((item.quantity || 0) - (item.dispensed_qty || 0), 0);
                                        const productId = draft.product_id || item.product_id;
                                        const substituted = Boolean(item.product_id && productId && productId !== item.product_id);
                                        return (_jsxs("div", { style: { borderBottom: "1px solid var(--line)", padding: "8px 0" }, children: [_jsx("strong", { children: item.medicine_name }), " ", item.strength, _jsxs("div", { className: "muted", children: [item.dose, " \u00B7 ", item.duration, " \u00B7 ", item.food_instruction] }), _jsxs("div", { className: "muted", children: ["Prescribed ", item.quantity, " ", item.unit, " \u00B7 dispensed ", item.dispensed_qty || 0, " \u00B7 remaining ", remaining] }), hit && _jsx("button", { type: "button", className: "btn small", onClick: () => applyScan(item), children: "Apply scan to this line" }), _jsxs("div", { className: "grid-form", style: { marginTop: 6 }, children: [_jsx(Field, { label: "Batch", children: _jsx(BatchSelect, { productId: productId, value: draft.batch_id, onChange: (batch_id, product_id) => setLines({ ...lines, [item.id]: { ...draft, batch_id, product_id } }) }) }), _jsx(Field, { label: "Qty", children: _jsx("input", { value: draft.qty, onChange: (e) => setLines({ ...lines, [item.id]: { ...draft, qty: Number(e.target.value) } }) }) }), substituted && _jsx(Field, { label: "Substitution reason", className: "span-2", children: _jsx("input", { value: draft.reason, onChange: (e) => setLines({ ...lines, [item.id]: { ...draft, reason: e.target.value } }), placeholder: "Required. The prescribed name stays as written." }) })] })] }, item.id));
                                    }), rx && _jsx("p", { className: "muted", children: "Issuing medicine onto a bill is done at Billing. This older dispense action still posts to the pharmacy API and changes stock. Do not use it for a bill." }), rx && _jsx("button", { className: "btn", disabled: busy, onClick: confirmDispense, children: "Record a pharmacy dispense" })] })] })] })] }));
}
function BatchSelect({ productId, value, onChange }) {
    const { data } = useData(productId ? `/api/inventory/products/${productId}` : null);
    if (!productId)
        return _jsx("input", { placeholder: "Link a product", disabled: true });
    return (_jsxs("select", { value: value, onChange: (e) => onChange(e.target.value, productId), children: [_jsx("option", { value: "", children: "FEFO suggestion" }), (data?.batches || []).filter((b) => b.qty_on_hand > 0).map((b) => (_jsxs("option", { value: b.id, children: [b.batch_no, " \u00B7 exp ", b.expiry_date || "—", " \u00B7 ", b.qty_on_hand, " \u00B7 ", money(b.sale_rate_paise)] }, b.id)))] }));
}
export function RegisterMedicine({ barcode, onClose, onRegistered }) {
    const { data: types } = useData("/api/inventory/barcode-types");
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
            const product = await api("/api/inventory/products", { method: "POST", body: JSON.stringify({ name, brand, composition, strength, unit, manufacturer }) });
            const sku = await api("/api/inventory/skus", { method: "POST", body: JSON.stringify({ product_id: product.id, name: skuName, unit: skuUnit, units_per_pack: Number(packSize) }) });
            await api("/api/inventory/barcodes", { method: "POST", body: JSON.stringify({ sku_id: sku.id, value: code.trim(), barcode_type: barcodeType, scope: "SKU" }) });
            if (batchNo.trim() && Number(qty) > 0) {
                await api("/api/inventory/receive", { method: "POST", body: JSON.stringify({ barcode: code.trim(), batch_no: batchNo.trim(), mfg_date: mfg, expiry_date: expiry, qty: Number(qty) }) });
            }
            onRegistered(code.trim());
        }
        finally {
            setBusy(false);
        }
    }
    return (_jsxs(Modal, { title: "Register medicine", onClose: onClose, footer: _jsx("button", { className: "btn primary", disabled: busy, onClick: () => run(save, batchNo && Number(qty) > 0 ? "Medicine registered and stock received" : "Medicine registered. No stock was added."), children: "Save product, package, and barcode" }), children: [_jsx("p", { className: "muted", children: "An unknown barcode is not a product. Register the medicine, then the package, then the barcode. Stock is added only if you also enter a batch and a quantity." }), _jsxs("div", { className: "grid-form", children: [_jsx(Field, { label: "Medicine name", children: _jsx("input", { value: name, onChange: (e) => setName(e.target.value) }) }), _jsx(Field, { label: "Brand", children: _jsx("input", { value: brand, onChange: (e) => setBrand(e.target.value) }) }), _jsx(Field, { label: "Composition", children: _jsx("input", { value: composition, onChange: (e) => setComposition(e.target.value) }) }), _jsx(Field, { label: "Strength", children: _jsx("input", { value: strength, onChange: (e) => setStrength(e.target.value) }) }), _jsx(Field, { label: "Base unit", children: _jsx("input", { value: unit, onChange: (e) => setUnit(e.target.value) }) }), _jsx(Field, { label: "Manufacturer", children: _jsx("input", { value: manufacturer, onChange: (e) => setManufacturer(e.target.value) }) }), _jsx(Field, { label: "Package name", children: _jsx("input", { value: skuName, onChange: (e) => setSkuName(e.target.value) }) }), _jsx(Field, { label: "Package unit", children: _jsx("input", { value: skuUnit, onChange: (e) => setSkuUnit(e.target.value) }) }), _jsx(Field, { label: "Base units in this package", children: _jsx("input", { value: packSize, onChange: (e) => setPackSize(e.target.value), placeholder: "Enter the count. Do not assume 10." }) }), _jsx(Field, { label: "Barcode", children: _jsx("input", { value: code, onChange: (e) => setCode(e.target.value) }) }), _jsx(Field, { label: "Barcode type", children: _jsxs("select", { value: barcodeType, onChange: (e) => setBarcodeType(e.target.value), children: [_jsx("option", { value: "", children: (types?.items || []).length ? "Choose a configured type" : "No barcode types configured" }), (types?.items || []).map((item) => _jsx("option", { value: item.code, children: item.name }, item.code))] }) }), _jsx(Field, { label: "Batch, optional", children: _jsx("input", { value: batchNo, onChange: (e) => setBatchNo(e.target.value) }) }), _jsx(Field, { label: "Manufactured, if receiving", children: _jsx("input", { value: mfg, onChange: (e) => setMfg(e.target.value), placeholder: "YYYY-MM-DD" }) }), _jsx(Field, { label: "Expiry, if receiving", children: _jsx("input", { value: expiry, onChange: (e) => setExpiry(e.target.value), placeholder: "YYYY-MM-DD" }) }), _jsx(Field, { label: "Quantity to receive, optional", children: _jsx("input", { value: qty, onChange: (e) => setQty(e.target.value) }) })] })] }));
}
function keyFor(prefix) {
    return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
export function LabPage() {
    const can = useApp((s) => s.can);
    const { data, error, loading } = useData("/api/lab/orders");
    const { data: queue } = useData(can("lab.view") ? "/api/lab/queue" : null);
    const { data: reasons } = useData("/api/master/lab_rejection_reason");
    const [text, setText] = useState({});
    const [reason, setReason] = useState("HAEMOLYSED");
    return (_jsxs(Page, { title: "Lab", note: "Diagnostic orders, samples, and results. Each stage is a separate action.", children: [_jsx(Flow, { steps: ["Order", "Collection", "Processing", "Result", "Report"] }), loading && !data && _jsx(Loading, { label: "Opening laboratory orders\u2026" }), error && _jsx(ErrorState, { message: error }), !loading && data && !data.items?.length && _jsx(Empty, { text: "No laboratory order is open." }), _jsx("p", { className: "muted", children: "A range flag is not a diagnosis. The queue refreshes from laboratory events, not a timer." }), can("lab.sample.process") && (_jsxs("div", { className: "panel", children: [_jsx("h2", { children: "Processing queue" }), _jsxs("div", { className: "body", children: [(queue?.items || []).length === 0 && _jsx("p", { className: "muted", children: "No sample is waiting." }), (queue?.items || []).map((sample) => (_jsxs("div", { className: "row-actions", style: { marginBottom: 8 }, children: [_jsx("strong", { children: sample.accession_no }), " ", _jsx(Status, { value: sample.status }), " ", _jsx("span", { className: "muted", children: sample.priority }), _jsx("button", { className: "btn small", onClick: () => run(() => api(`/api/lab/samples/${sample.id}/process`, { method: "POST", body: JSON.stringify({ idempotency_key: keyFor("process") }) }), "In process"), children: "Process" })] }, sample.id)))] })] })), (data?.items || []).map((order) => (_jsxs("div", { className: "panel", children: [_jsxs("h2", { children: [order.id, " \u00B7 ", order.patient_name, " \u00B7 ", order.status] }), _jsxs("div", { className: "body", children: [_jsxs("div", { className: "row-actions", style: { marginBottom: 8 }, children: [can("lab.sample.collect") && _jsx("button", { className: "btn small", onClick: () => run(() => api(`/api/lab/orders/${order.id}/samples`, { method: "POST", body: JSON.stringify({ item_ids: (order.items || []).filter((item) => item.status === "SAMPLE_PENDING" || item.status === "RECOLLECTION_REQUIRED").map((item) => item.id), idempotency_key: keyFor("collect") }) }), "Sample collected"), children: "Collect waiting tests" }), can("lab.order.cancel") && _jsx("button", { className: "btn small", onClick: () => run(() => api(`/api/lab/orders/${order.id}/cancel`, { method: "POST", body: JSON.stringify({ reason: "Cancelled from the laboratory desk", idempotency_key: keyFor("cancel") }) }), "Order cancelled"), children: "Cancel order" }), can("lab.report.generate") && _jsx("button", { className: "btn small", onClick: () => run(() => api(`/api/lab/orders/${order.id}/report`, { method: "POST", body: JSON.stringify({ idempotency_key: keyFor("report") }) }), "Report stored"), children: "Generate report" }), can("lab.report.view") && order.reports?.[0] && _jsx("a", { className: "btn small", href: fileUrl(`/api/lab/orders/${order.id}/report`), target: "_blank", children: "Open report" })] }), (order.items || []).map((item) => (_jsxs("div", { className: "grid-form", style: { marginBottom: 8 }, children: [_jsxs("div", { children: [_jsx("strong", { children: item.custom_name || item.test_id }), " ", _jsx(Status, { value: item.status }), _jsxs("div", { className: "muted", children: [money(item.price_paise), " ", item.price_pending ? "· price pending at billing" : ""] }), (item.samples || []).map((sample) => _jsxs("div", { className: "muted", children: [sample.accession_no, " \u00B7 ", sample.status] }, sample.id))] }), can("lab.result") && (_jsx(Field, { label: "Result", children: _jsx("input", { value: text[item.id] ?? item.current_result?.value_text ?? "", onChange: (e) => setText({ ...text, [item.id]: e.target.value }) }) })), can("lab.result") && _jsx("button", { className: "btn small", onClick: () => run(() => api(`/api/lab/items/${item.id}/result`, { method: "POST", body: JSON.stringify({ value: text[item.id] || item.current_result?.value_text, idempotency_key: keyFor("result") }) }), "Result entered"), children: "Enter result" }), can("lab.result.verify") && item.current_result?.status === "ENTERED" && _jsx("button", { className: "btn small", onClick: () => run(() => api(`/api/lab/results/${item.current_result.id}/verify`, { method: "POST", body: JSON.stringify({ idempotency_key: keyFor("verify") }) }), "Verified"), children: "Verify" }), can("lab.result.correct") && item.current_result?.status === "VERIFIED" && _jsx("button", { className: "btn small", onClick: () => run(() => api(`/api/lab/results/${item.current_result.id}/correct`, { method: "POST", body: JSON.stringify({ value: text[item.id] || item.current_result.value_text, reason: "Corrected from the laboratory desk", idempotency_key: keyFor("correct") }) }), "Correction entered"), children: "Correct" }), can("lab.sample.reject") && (item.samples || []).filter((sample) => sample.status !== "REJECTED").map((sample) => (_jsxs("div", { className: "row-actions", children: [_jsx("select", { value: reason, onChange: (e) => setReason(e.target.value), children: (reasons?.items || []).map((entry) => _jsx("option", { value: entry.code, children: entry.name }, entry.code)) }), _jsxs("button", { className: "btn small", onClick: () => run(() => api(`/api/lab/samples/${sample.id}/reject`, { method: "POST", body: JSON.stringify({ reason_code: reason, notes: reason === "OTHER" ? "See the laboratory note" : "", idempotency_key: keyFor("reject") }) }), "Sample rejected"), children: ["Reject ", sample.accession_no] })] }, sample.id)))] }, item.id)))] })] }, order.id)))] }));
}
