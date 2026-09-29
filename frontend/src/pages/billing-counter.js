import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, api, fileUrl, money, paise } from "../api";
import { prepareBarcode } from "../barcode";
import { RegisterMedicine } from "./clinical";
import { BarcodeScanner } from "../scanner";
import { useApp } from "../store";
import { Field, Loading, Modal, Status, run, useData } from "../ui";
function freshKey(scope) {
    const id = typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : String(Date.now());
    return `${scope}-${id}`;
}
function initials(name) {
    const parts = (name || "").trim().split(/\s+/).filter(Boolean).slice(0, 2);
    return parts.map((part) => part[0]?.toUpperCase() || "").join("") || "PT";
}
function issued(item) {
    const qty = Number(item?.quantity || 0);
    const done = Number(item?.dispensed_qty || 0);
    return item?.status === "DISPENSED" || item?.status === "SUBSTITUTED" || (qty > 0 && done + 0.0001 >= qty);
}
function fillTemplate(text, values) {
    return text.replace(/\{\{\s*([a-z_]+)\s*\}\}/g, (_, key) => values[key] || "");
}
export function BillingCounter() {
    const [params] = useSearchParams();
    const can = useApp((s) => s.can);
    const canIssue = can("billing.medicine_issue");
    const [query, setQuery] = useState(params.get("patient") || "");
    const [hits, setHits] = useState([]);
    const [patientId, setPatientId] = useState(params.get("patient") || "");
    const [encounterId, setEncounterId] = useState("");
    const [desk, setDesk] = useState(null);
    const [invoice, setInvoice] = useState(null);
    const [notes, setNotes] = useState("");
    const [docCount, setDocCount] = useState(null);
    const [discount, setDiscount] = useState("0");
    const [discountReason, setDiscountReason] = useState("");
    const [medicineQuery, setMedicineQuery] = useState("");
    const [medicines, setMedicines] = useState([]);
    const [picked, setPicked] = useState(null);
    const [batchId, setBatchId] = useState("");
    const [qty, setQty] = useState("1");
    const [manualRate, setManualRate] = useState("");
    const [selectedRx, setSelectedRx] = useState([]);
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
    const { data: services } = useData(extra === "service" || extra === "" ? "/api/services" : null);
    const { data: labs } = useData(extra === "lab" ? "/api/lab/tests" : null);
    const { data: bills, error: billsError, loading: billsLoading } = useData(showBills ? "/api/invoices" : null);
    async function loadDesk(id = patientId, encounter = encounterId) {
        if (!id)
            return;
        const row = await api(`/api/billing/desk?patient_id=${encodeURIComponent(id)}&encounter_id=${encodeURIComponent(encounter)}`);
        setDesk(row);
        setInvoice(row.invoice);
        setNotes(row.invoice?.notes || "");
        setDiscount(((row.invoice?.discount_paise || 0) / 100).toFixed(2));
        if (!encounter && row.encounter?.id)
            setEncounterId(row.encounter.id);
        api(`/api/documents?patient_id=${encodeURIComponent(id)}`).then((docs) => setDocCount((docs.items || []).length)).catch(() => setDocCount(null));
    }
    useEffect(() => {
        if (!patientId)
            return;
        loadDesk(patientId, encounterId).catch((err) => useApp.getState().toast(err.message, "bad"));
    }, [patientId, encounterId]);
    useEffect(() => {
        if (!canIssue)
            return;
        const handle = window.setTimeout(() => {
            api(`/api/billing/medicines?q=${encodeURIComponent(medicineQuery.trim())}`)
                .then((row) => setMedicines(row.items || []))
                .catch(() => setMedicines([]));
        }, 180);
        return () => window.clearTimeout(handle);
    }, [medicineQuery, canIssue]);
    const patient = desk?.patient;
    const encounter = desk?.encounter;
    const prescription = (encounter?.prescriptions || []).find((row) => row.status === "FINALIZED" || row.status === "PARTIAL" || row.status === "DISPENSED") || encounter?.prescriptions?.[0];
    const batch = (picked?.batches || []).find((row) => row.id === batchId) || picked?.batches?.[0];
    const ratePaise = batch?.rate_paise || (manualRate ? paise(manualRate) : 0);
    const preview = ratePaise * (Number(qty) || 0);
    async function searchPatients(event) {
        event.preventDefault();
        const found = await api(`/api/patients?q=${encodeURIComponent(query.trim())}`);
        setHits(found.items || []);
        if ((found.items || []).length === 1)
            choosePatient(found.items[0]);
    }
    function choosePatient(row) {
        setHits([]);
        setEncounterId("");
        setPatientId(row.id);
        setPicked(null);
        setSelectedRx([]);
    }
    async function ensureDraft() {
        if (invoice?.status === "DRAFT")
            return invoice;
        if (!patientId)
            throw new Error("Choose a patient first.");
        const draft = await api("/api/invoices", {
            method: "POST",
            body: JSON.stringify({ patient_id: patientId, encounter_id: encounter?.id || null, bill_type: "OPD" }),
        });
        const full = await api(`/api/invoices/${draft.id}`);
        setInvoice(full);
        return full;
    }
    async function postIssue(draftId, body) {
        if (!issueKey.current)
            issueKey.current = freshKey("issue");
        try {
            return await api(`/api/invoices/${draftId}/issue`, {
                method: "POST",
                body: JSON.stringify({ ...body, idempotency_key: issueKey.current }),
            });
        }
        catch (err) {
            if (err instanceof ApiError && err.code === "qty_mismatch") {
                if (!window.confirm(`${err.message}\n\nThe doctor's prescription will not be changed.`)) {
                    throw new ApiError("Not billed. The prescription was not changed.", 409, "cancelled");
                }
                return api(`/api/invoices/${draftId}/issue`, {
                    method: "POST",
                    body: JSON.stringify({ ...body, confirm: true, idempotency_key: issueKey.current }),
                });
            }
            throw err;
        }
    }
    async function addMedicine(lines) {
        if (!canIssue)
            throw new Error("You can bill other charges, but you cannot issue medicine stock.");
        try {
            const draft = await ensureDraft();
            const result = await postIssue(draft.id, { items: lines });
            if (result.warnings?.length)
                useApp.getState().toast(result.warnings.join(" "), "wait");
            await loadDesk();
            return result;
        }
        finally {
            issueKey.current = "";
        }
    }
    async function identify(raw) {
        const prepared = prepareBarcode(raw);
        setUnknownCode("");
        if (prepared.error)
            throw new Error(prepared.error);
        try {
            const hit = await api("/api/inventory/barcodes/resolve", { method: "POST", body: JSON.stringify({ code: prepared.code }) });
            const found = await api(`/api/billing/medicines?q=${encodeURIComponent(hit.product?.id || prepared.code)}`);
            const product = (found.items || []).find((item) => item.id === hit.product?.id) || found.items?.[0];
            if (!product)
                throw new Error("The barcode was identified, but its batches could not be opened.");
            setPicked(product);
            setBatchId(hit.matched_batch?.id || product.batches?.[0]?.id || "");
            setMedicineQuery(product.name || "");
        }
        catch (err) {
            if (err instanceof ApiError && err.status === 404) {
                setUnknownCode(prepared.code);
                setPicked(null);
                return;
            }
            throw err;
        }
    }
    function chooseMedicine(product) {
        setPicked(product);
        setUnknownCode("");
        const usable = (product.batches || []).find((row) => Number(row.qty_on_hand) > 0) || product.batches?.[0];
        setBatchId(usable?.id || "");
        setManualRate("");
    }
    const pendingIds = (prescription?.items || []).filter((item) => !issued(item) && item.product_id).map((item) => item.id);
    return (_jsxs("div", { className: "bill-desk", children: [_jsxs("header", { className: "bill-title", children: [_jsxs("div", { children: [_jsx("h1", { children: "Billing" }), _jsx("p", { children: "Create bill, add prescription medicines, issue and deduct stock, collect payment." })] }), _jsxs("div", { className: "row-actions", children: [_jsx(Link, { className: "btn", to: "/register", children: "New Patient" }), _jsx(Link, { className: "btn", to: "/queue", children: "View Queue" }), _jsx(Link, { className: "btn", to: "/", children: "Today's OPD" }), _jsx("button", { className: "btn", type: "button", onClick: () => setShowBills((open) => !open), children: showBills ? "Hide bills" : "All bills" })] })] }), _jsxs("form", { className: "bill-search", onSubmit: searchPatients, children: [_jsx("input", { "aria-label": "Find patient", value: query, onChange: (e) => setQuery(e.target.value), placeholder: "Patient ID, name, or phone" }), _jsx("button", { className: "btn", type: "submit", children: "Find" })] }), !!hits.length && (_jsx("div", { className: "bill-hits", children: hits.map((row) => (_jsxs("button", { type: "button", onClick: () => choosePatient(row), children: [_jsx("strong", { children: row.name }), _jsx("span", { children: row.id })] }, row.id))) })), _jsxs("section", { className: "patient-head", children: [_jsx("div", { className: "avatar", "aria-hidden": "true", children: initials(patient?.name) }), _jsxs("div", { className: "patient-id", children: [_jsxs("h2", { children: [patient?.name || "Select a patient", " ", encounter && _jsx("span", { className: "opd-pill", children: "OPD patient" })] }), _jsx("p", { children: patient ? _jsxs(_Fragment, { children: ["Patient ID: ", _jsx("span", { className: "pid", children: patient.id }), " \u00B7 Age: ", patient.age || "not recorded", " \u00B7 ", patient.gender || "Gender not recorded"] }) : "Search by Patient ID, name, or phone. A scan does not change stock." }), patient && _jsxs("p", { className: "sub", children: [patient.phone || "No phone", patient.guardian_name ? ` · Guardian: ${patient.guardian_name}` : ""] })] }), _jsxs("div", { className: "patient-meta", children: [_jsx(Field, { label: "Encounter", children: _jsxs("select", { "aria-label": "Encounter", value: encounterId, onChange: (e) => { setEncounterId(e.target.value); setSelectedRx([]); }, disabled: !desk?.encounters?.length, children: [!desk?.encounters?.length && _jsx("option", { value: "", children: "No visit yet" }), (desk?.encounters || []).map((row) => _jsx("option", { value: row.id, children: row.id }, row.id))] }) }), _jsx("span", { children: encounter?.arrived_at ? encounter.arrived_at.replace("T", " ").slice(0, 16) : "No visit time" })] }), _jsxs("div", { className: "patient-meta", children: [_jsx("strong", { children: "Doctor" }), _jsx("span", { children: encounter?.doctor_name || "Not assigned" }), _jsx("span", { children: encounter?.department_name || "Department not recorded" })] }), _jsxs("div", { className: "patient-links", children: [patient && _jsx(Link, { className: "btn small", to: `/patients/${patient.id}`, children: "View patient" }), patient && _jsxs(Link, { className: "btn small", to: `/patients/${patient.id}`, children: ["Documents", docCount === null ? "" : ` (${docCount})`] }), patient && _jsx(Link, { className: "btn small", to: `/patients/${patient.id}`, children: "History" })] })] }), _jsxs("div", { className: "bill-columns", children: [_jsxs("div", { className: "bill-stack", children: [_jsxs("section", { className: "bill-col", children: [_jsxs("header", { children: [_jsx("h2", { children: "Prescription" }), prescription && _jsx(Status, { value: prescription.status })] }), prescription && _jsxs("p", { className: "muted", children: [prescription.id, " \u00B7 ", encounter?.doctor_name || "Doctor not recorded"] }), !encounter && _jsx("p", { className: "muted", children: "Choose a patient. The visit prescription appears here. Billing does not create a second prescription." }), encounter && !prescription && _jsx("p", { className: "muted", children: "This visit has no prescription yet. You can still search and bill a medicine." }), prescription && (_jsxs("table", { className: "data rx-table", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", {}), _jsx("th", { children: "#" }), _jsx("th", { children: "Medicine" }), _jsx("th", { children: "Dose" }), _jsx("th", { children: "Duration" }), _jsx("th", { className: "num", children: "Qty" }), _jsx("th", { children: "Status" })] }) }), _jsx("tbody", { children: (prescription.items || []).map((item, index) => {
                                                    const done = issued(item);
                                                    return (_jsxs("tr", { children: [_jsx("td", { children: _jsx("input", { type: "checkbox", "aria-label": `Select ${item.medicine_name}`, disabled: done || !item.product_id, checked: selectedRx.includes(item.id), onChange: (e) => setSelectedRx(e.target.checked ? [...selectedRx, item.id] : selectedRx.filter((id) => id !== item.id)) }) }), _jsx("td", { children: index + 1 }), _jsxs("td", { children: [item.medicine_name, " ", item.strength, !item.product_id && _jsx("small", { className: "warn", children: "Not linked to stock" })] }), _jsx("td", { children: item.dose || item.frequency || "—" }), _jsx("td", { children: item.duration || "—" }), _jsx("td", { className: "num", children: item.quantity || 1 }), _jsx("td", { children: _jsx("span", { className: done ? "pill ok" : "pill wait", children: done ? "Added" : "Pending" }) })] }, item.id));
                                                }) })] })), prescription && (_jsxs("div", { className: "row-actions", children: [_jsxs("label", { className: "check-line", children: [_jsx("input", { type: "checkbox", checked: !!pendingIds.length && pendingIds.every((id) => selectedRx.includes(id)), onChange: (e) => setSelectedRx(e.target.checked ? pendingIds : []) }), " Select all"] }), _jsx("button", { className: "btn primary", type: "button", disabled: !selectedRx.length || !canIssue, onClick: () => run(() => addMedicine(selectedRx.map((id) => ({ prescription_item_id: id }))), "Selected medicines issued and added to the bill"), children: "Add selected to bill" }), _jsx("button", { className: "btn", type: "button", onClick: () => setFullRx(true), children: "View full prescription" })] }))] }), _jsxs("section", { className: "bill-col", children: [_jsx("header", { children: _jsx("h2", { children: "Add other item" }) }), _jsx("div", { className: "extra-tabs", children: [["service", "Service"], ["lab", "Lab test"], ["other", "Other"], ["custom", "Custom"]].map(([id, label]) => (_jsx("button", { type: "button", className: extra === id ? "on" : "", onClick: () => setExtra(id), children: label }, id))) }), extra === "service" && _jsx(ChargeList, { rows: (services?.items || []).filter((row) => row.active !== 0), label: (row) => row.name, price: (row) => row.rate_paise, onAdd: (row) => run(async () => { await ensureDraft().then((draft) => api(`/api/invoices/${draft.id}/items`, { method: "POST", body: JSON.stringify({ source_module: "service", master_item_id: row.id, category: "HOSPITAL SERVICES", description: row.name, qty: 1 }) })); await loadDesk(); }, "Service added") }), extra === "lab" && _jsx(ChargeList, { rows: (labs?.items || []).filter((row) => row.active !== 0), label: (row) => row.name, price: (row) => row.price_paise, onAdd: (row) => run(async () => { await ensureDraft().then((draft) => api(`/api/invoices/${draft.id}/items`, { method: "POST", body: JSON.stringify({ source_module: "lab", master_item_id: row.id, category: "LABORATORY", description: row.name, qty: 1 }) })); await loadDesk(); }, "Lab test added") }), (extra === "other" || extra === "custom") && _jsx(ExtraCharge, { kind: extra, services: [], labs: [], onClose: () => setExtra("service"), onAdd: async (body) => { const draft = await ensureDraft(); await api(`/api/invoices/${draft.id}/items`, { method: "POST", body: JSON.stringify(body) }); await loadDesk(); } })] })] }), _jsxs("section", { className: "bill-col", children: [_jsx("header", { children: _jsx("h2", { children: "Add medicine to bill" }) }), !canIssue && _jsx("p", { className: "muted", children: "You can add services, but issuing medicine stock needs the medicine-issue permission." }), _jsxs("button", { className: "scan-plate", type: "button", onClick: () => setScanner(true), children: [_jsx("strong", { children: "Scan barcode" }), _jsx("span", { children: "Click to scan or use the camera. The scan only identifies the package." })] }), _jsx(Field, { label: "Search medicine", children: _jsx("input", { "aria-label": "Search medicine", value: medicineQuery, onChange: (e) => setMedicineQuery(e.target.value), placeholder: "Search by name, brand, composition, strength, SKU, or barcode" }) }), !!medicines.length && medicineQuery.trim() && (_jsx("ul", { className: "med-hits", children: medicines.map((item) => (_jsx("li", { children: _jsxs("button", { type: "button", onClick: () => chooseMedicine(item), children: [item.name, " ", item.strength, " ", _jsx("small", { children: item.brand || item.composition || item.id })] }) }, item.id))) })), unknownCode && (_jsxs("div", { className: "unknown-code", children: [_jsx("strong", { children: "Barcode not registered" }), _jsxs("p", { children: ["Code ", unknownCode, ". No medicine or batch was created, and stock did not change."] }), can("inventory.edit") ? _jsx("button", { className: "btn", type: "button", onClick: () => setRegistering(true), children: "Register new medicine" }) : _jsx("p", { className: "muted", children: "A person with inventory permission must register this code. It stays on screen." })] })), picked && (_jsxs("div", { className: "med-card", children: [_jsx("div", { className: "med-mark", "aria-hidden": "true", children: "Rx" }), _jsxs("div", { children: [_jsxs("h3", { children: [picked.name, " ", picked.strength] }), _jsxs("p", { children: ["Brand: ", picked.brand || "Not recorded", " \u00B7 Composition: ", picked.composition || "Not recorded"] }), _jsxs("p", { children: ["Form: ", picked.dosage_form || picked.unit || "Not recorded"] })] })] })), _jsxs("div", { className: "batch-row", children: [_jsx(Field, { label: "Batch", children: _jsxs("select", { "aria-label": "Batch", value: batch?.id || "", onChange: (e) => setBatchId(e.target.value), disabled: !picked, children: [(picked?.batches || []).map((row) => _jsxs("option", { value: row.id, children: [row.batch_no, " (exp ", row.expiry_date || "none", ")"] }, row.id)), !picked?.batches?.length && _jsx("option", { value: "", children: "No batch in stock" })] }) }), _jsxs("div", { className: "stock-badge", children: [batch ? batch.qty_on_hand : "—", _jsx("small", { children: "in stock" })] })] }), _jsxs("div", { className: "med-figures", children: [_jsx(Field, { label: "Rate (Rs)", children: _jsx("input", { "aria-label": "Rate", value: batch?.rate_paise ? (batch.rate_paise / 100).toFixed(2) : manualRate, readOnly: !!batch?.rate_paise, onChange: (e) => setManualRate(e.target.value) }) }), _jsx(Field, { label: "Quantity", children: _jsx("input", { "aria-label": "Quantity", value: qty, onChange: (e) => setQty(e.target.value) }) }), _jsx(Field, { label: "Amount", children: _jsx("input", { "aria-label": "Amount", readOnly: true, value: (preview / 100).toFixed(2) }) })] }), _jsx("p", { className: "muted", children: batch?.rate_source === "master" ? "Rate is the medicine master price and will be snapshotted on the line." : batch?.rate_source === "batch" ? "No master price. The batch price will be snapshotted." : "Enter a rate. It is snapshotted on the line." }), _jsx("button", { className: "btn add-bill", type: "button", disabled: !picked || !batch || busy, onClick: () => {
                                    setBusy(true);
                                    run(async () => {
                                        await addMedicine([{
                                                product_id: picked.id,
                                                batch_id: batch.id,
                                                qty: Number(qty),
                                                rate_paise: batch.rate_paise ? undefined : paise(manualRate),
                                                prescription_item_id: (prescription?.items || []).find((item) => selectedRx.includes(item.id) && item.product_id === picked.id)?.id,
                                            }]);
                                        setQty("1");
                                    }, "Medicine issued and added to the bill").finally(() => setBusy(false));
                                }, children: "Add to bill" })] }), _jsxs("div", { className: "bill-stack", children: [_jsxs("section", { className: "bill-col", children: [_jsxs("header", { children: [_jsxs("h2", { children: ["Bill items (", invoice?.items?.length || 0, ")"] }), invoice && _jsx(Status, { value: invoice.status })] }), !invoice && _jsx("p", { className: "muted", children: "No draft yet. Adding a line opens one." }), invoice && (_jsxs("table", { className: "data bill-lines", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "#" }), _jsx("th", { children: "Item" }), _jsx("th", { className: "num", children: "Qty" }), _jsx("th", { className: "num", children: "Rate" }), _jsx("th", { className: "num", children: "Amount" }), _jsx("th", {})] }) }), _jsxs("tbody", { children: [(invoice.items || []).map((line, index) => (_jsx(BillLine, { index: index + 1, line: line, draft: invoice.status === "DRAFT", onChanged: loadDesk }, line.id))), !invoice.items?.length && _jsx("tr", { children: _jsx("td", { colSpan: 6, children: "No lines yet." }) })] })] })), invoice?.status === "DRAFT" && !!invoice.items?.length && (_jsx("button", { className: "btn danger clear-all", type: "button", onClick: () => {
                                            if (!window.confirm("Remove every draft line? Issued medicines will be returned to stock."))
                                                return;
                                            run(async () => {
                                                for (const line of invoice.items)
                                                    await api(`/api/invoice-items/${line.id}`, { method: "DELETE" });
                                                await loadDesk();
                                            }, "Draft lines removed");
                                        }, children: "Clear all items" }))] }), _jsxs("section", { className: "bill-col", children: [_jsx("header", { children: _jsx("h2", { children: "Bill summary" }) }), _jsxs("dl", { className: "bill-summary", children: [_jsxs("div", { children: [_jsx("dt", { children: "Subtotal" }), _jsx("dd", { children: money(invoice?.gross_paise || 0) })] }), _jsxs("div", { children: [_jsx("dt", { children: "Discount" }), _jsxs("dd", { className: "discount-edit", children: [_jsx("input", { "aria-label": "Discount rupees", value: discount, onChange: (e) => setDiscount(e.target.value), onBlur: () => {
                                                                    if (!invoice || invoice.status !== "DRAFT")
                                                                        return;
                                                                    const next = paise(discount);
                                                                    if (next === Number(invoice.discount_paise || 0))
                                                                        return;
                                                                    const reason = next > 0 ? (discountReason || window.prompt("Reason for this discount") || "") : "";
                                                                    if (next > 0 && !reason)
                                                                        return;
                                                                    setDiscountReason(reason);
                                                                    run(async () => {
                                                                        const saved = await api(`/api/invoices/${invoice.id}/discount`, { method: "POST", body: JSON.stringify({ discount_paise: next, reason }) });
                                                                        setInvoice(saved);
                                                                    }, "Discount saved");
                                                                } }), " ", money(invoice?.discount_paise || 0)] })] }), _jsxs("div", { children: [_jsx("dt", { children: "Tax / service charge" }), _jsx("dd", { children: money(invoice?.tax_paise || 0) })] }), _jsxs("div", { className: "net", children: [_jsx("dt", { children: "Net total" }), _jsx("dd", { children: money(invoice?.net_paise || 0) })] }), _jsxs("div", { children: [_jsx("dt", { children: "Paid" }), _jsx("dd", { children: money(invoice?.paid_paise || 0) })] }), _jsxs("div", { className: "due", children: [_jsx("dt", { children: "Due" }), _jsx("dd", { children: money(invoice?.due_paise || 0) })] })] }), _jsx("p", { className: "words", children: invoice?.amount_in_words || "" }), invoice && _jsx(Link, { className: "btn small", to: `/billing/${invoice.id}`, children: "Take payment" })] })] })] }), _jsxs("footer", { className: "bill-sticky", children: [_jsx(Field, { label: "Notes", children: _jsx("input", { "aria-label": "Bill notes", value: notes, onChange: (e) => setNotes(e.target.value), placeholder: "Notes (optional)" }) }), _jsxs("div", { className: "row-actions", children: [_jsx("button", { className: "btn", type: "button", disabled: !patientId, onClick: () => run(async () => {
                                    const draft = await ensureDraft();
                                    const saved = await api(`/api/invoices/${draft.id}/notes`, { method: "POST", body: JSON.stringify({ notes }) });
                                    setInvoice(saved);
                                }, "Draft saved"), children: "Save draft" }), _jsx("button", { className: "btn finalize", type: "button", disabled: !invoice || invoice.status !== "DRAFT" || !can("billing.finalize"), onClick: () => run(async () => {
                                    await api(`/api/invoices/${invoice.id}/finalize`, { method: "POST", body: "{}" });
                                    await loadDesk();
                                }, "Bill finalized"), children: "Finalize bill" }), invoice && _jsx("a", { className: "btn", href: fileUrl(`/api/invoices/${invoice.id}/pdf`), target: "_blank", rel: "noreferrer", children: "Print bill" }), prescription && _jsx("a", { className: "btn", href: fileUrl(`/api/prescriptions/${prescription.id}/pdf`), target: "_blank", rel: "noreferrer", children: "Print prescription" }), _jsx("button", { className: "btn primary", type: "button", disabled: !patient, onClick: () => {
                                    const values = {
                                        patient_name: patient?.name || "",
                                        patient_id: patient?.id || "",
                                        bill_number: invoice?.number || "",
                                        amount: money(invoice?.net_paise || 0),
                                        doctor_name: encounter?.doctor_name || "",
                                        hospital_name: "the hospital",
                                    };
                                    api("/api/public/branding").then((brand) => {
                                        values.hospital_name = brand?.name || values.hospital_name;
                                    }).catch(() => undefined).finally(() => {
                                        setMessage(fillTemplate("Hello {{patient_name}} ({{patient_id}}). Bill {{bill_number}} for {{amount}} is ready. — {{doctor_name}}, {{hospital_name}}", values));
                                        setWhatsapp(true);
                                    });
                                }, children: "Send via WhatsApp" })] })] }), showBills && (_jsxs("section", { className: "panel", children: [_jsx("h2", { children: "Bills" }), _jsxs("div", { className: "body", children: [billsLoading && _jsx(Loading, { label: "Opening bills\u2026" }), billsError && _jsx("p", { className: "warn", children: billsError }), _jsx("table", { className: "data", children: _jsx("tbody", { children: (bills?.items || []).map((row) => (_jsxs("tr", { children: [_jsx("td", { children: _jsx(Link, { to: `/billing/${row.id}`, children: row.number }) }), _jsx("td", { children: row.patient_name }), _jsx("td", { children: _jsx(Status, { value: row.status }) }), _jsx("td", { className: "num", children: money(row.due_paise) })] }, row.id))) }) })] })] })), scanner && _jsx(BarcodeScanner, { onClose: () => setScanner(false), onUse: (code) => { setScanner(false); run(() => identify(code), "Barcode identified. Stock was not changed."); } }), registering && _jsx(RegisterMedicine, { barcode: unknownCode, onClose: () => setRegistering(false), onRegistered: (code) => { setRegistering(false); run(() => identify(code), "Medicine registered. Stock was not changed by the barcode."); } }), fullRx && prescription && (_jsx(Modal, { title: prescription.id, onClose: () => setFullRx(false), footer: _jsx("a", { className: "btn", href: fileUrl(`/api/prescriptions/${prescription.id}/pdf`), target: "_blank", rel: "noreferrer", children: "Open stored prescription" }), children: _jsx("ul", { className: "rx-list", children: (prescription.items || []).map((item) => (_jsxs("li", { children: [_jsxs("span", { children: [_jsxs("strong", { children: [item.medicine_name, " ", item.strength] }), _jsx("small", { children: [item.dose, item.frequency, item.duration, item.quantity].filter(Boolean).join(" · ") })] }), _jsx("em", { children: issued(item) ? "Added" : "Pending" })] }, item.id))) }) })), whatsapp && patient && (_jsx(WhatsAppSend, { patientId: patient.id, invoiceId: invoice?.id || "", text: message, onText: setMessage, onClose: () => setWhatsapp(false) }))] }));
}
function ChargeList({ rows, label, price, onAdd }) {
    const [q, setQ] = useState("");
    const shown = rows.filter((row) => label(row).toLowerCase().includes(q.trim().toLowerCase())).slice(0, 8);
    return (_jsxs("div", { children: [_jsx("input", { "aria-label": "Search charge", value: q, onChange: (e) => setQ(e.target.value), placeholder: "Search the catalogue" }), _jsxs("ul", { className: "charge-list", children: [shown.map((row) => (_jsxs("li", { children: [_jsx("span", { children: label(row) }), _jsx("strong", { children: money(price(row)) }), _jsx("button", { className: "btn small", type: "button", onClick: () => onAdd(row), children: "Add" })] }, row.id))), !shown.length && _jsx("li", { className: "muted", children: "Nothing in this catalogue matches." })] })] }));
}
function BillLine({ index, line, draft, onChanged }) {
    const [qty, setQty] = useState(String(line.qty));
    const [batches, setBatches] = useState([]);
    const medicine = line.source_module === "billing_issue" || line.source_module === "pharmacy";
    useEffect(() => {
        if (!medicine || !draft || !line.master_item_id)
            return;
        api(`/api/billing/medicines?q=${encodeURIComponent(line.master_item_id)}`).then((row) => {
            const product = (row.items || []).find((item) => item.id === line.master_item_id);
            setBatches(product?.batches || []);
        }).catch(() => setBatches([]));
    }, [medicine, draft, line.master_item_id]);
    function revise(body, ok) {
        run(async () => {
            try {
                await api(`/api/invoice-items/${line.id}/revise`, { method: "POST", body: JSON.stringify(body) });
            }
            catch (err) {
                if (err instanceof ApiError && err.code === "qty_mismatch" && window.confirm(`${err.message}\n\nThe prescription will not be changed.`)) {
                    await api(`/api/invoice-items/${line.id}/revise`, { method: "POST", body: JSON.stringify({ ...body, confirm: true }) });
                }
                else
                    throw err;
            }
            await onChanged();
        }, ok);
    }
    return (_jsxs("tr", { children: [_jsx("td", { children: index }), _jsxs("td", { children: [line.description, _jsx("small", { children: line.category }), medicine && draft && !!batches.length && (_jsxs("select", { "aria-label": `Batch for ${line.description}`, defaultValue: "", onChange: (e) => { if (e.target.value)
                            revise({ batch_id: e.target.value, qty: Number(qty) }, "Batch changed and stock adjusted"); }, children: [_jsx("option", { value: "", children: "Change batch" }), batches.map((row) => _jsxs("option", { value: row.id, children: [row.batch_no, " \u00B7 stock ", row.qty_on_hand] }, row.id))] }))] }), _jsx("td", { className: "num", children: medicine && draft ? _jsx("input", { "aria-label": `Quantity for ${line.description}`, value: qty, onChange: (e) => setQty(e.target.value), onBlur: () => {
                        if (Number(qty) === Number(line.qty))
                            return;
                        revise({ qty: Number(qty) }, "Quantity updated and stock adjusted");
                    } }) : line.qty }), _jsx("td", { className: "num", children: money(line.rate_paise) }), _jsx("td", { className: "num", children: money(line.amount_paise) }), _jsx("td", { children: draft && _jsx("button", { className: "btn small danger", type: "button", onClick: () => {
                        if (!window.confirm(medicine ? "Remove this medicine and return the stock?" : "Remove this line?"))
                            return;
                        run(async () => {
                            await api(`/api/invoice-items/${line.id}`, { method: "DELETE" });
                            await onChanged();
                        }, medicine ? "Line removed and stock returned" : "Line removed");
                    }, children: "Remove" }) })] }));
}
function ExtraCharge({ kind, services, labs, onClose, onAdd }) {
    const [id, setId] = useState("");
    const [description, setDescription] = useState("");
    const [rate, setRate] = useState("");
    const [qty, setQty] = useState("1");
    const title = kind === "service" ? "Service" : kind === "lab" ? "Lab test" : kind === "custom" ? "Custom charge" : "Other charge";
    return (_jsxs("form", { className: "extra-form", onSubmit: (event) => {
            event.preventDefault();
            const body = kind === "service"
                ? { source_module: "service", master_item_id: id, category: "HOSPITAL SERVICES", description: services.find((row) => row.id === id)?.name || "Service", qty: 1 }
                : kind === "lab"
                    ? { source_module: "lab", master_item_id: id, category: "LABORATORY", description: labs.find((row) => row.id === id)?.name || "Lab test", qty: 1 }
                    : { source_module: "manual", category: "OTHER", description, qty: Number(qty) || 1, rate_paise: paise(rate) };
            run(() => onAdd(body).then(onClose), "Charge added");
        }, children: [_jsx("strong", { children: title }), kind === "service" && _jsxs("select", { "aria-label": "Service", value: id, onChange: (e) => setId(e.target.value), children: [_jsx("option", { value: "", children: "Choose a service" }), services.filter((row) => row.active !== 0).map((row) => _jsxs("option", { value: row.id, children: [row.name, " \u00B7 ", money(row.rate_paise)] }, row.id))] }), kind === "lab" && _jsxs("select", { "aria-label": "Lab test", value: id, onChange: (e) => setId(e.target.value), children: [_jsx("option", { value: "", children: "Choose a test" }), labs.filter((row) => row.active !== 0).map((row) => _jsxs("option", { value: row.id, children: [row.name, " \u00B7 ", money(row.price_paise)] }, row.id))] }), (kind === "other" || kind === "custom") && (_jsxs(_Fragment, { children: [_jsx("input", { "aria-label": "Charge description", value: description, onChange: (e) => setDescription(e.target.value), placeholder: "Description" }), _jsx("input", { "aria-label": "Charge rate", value: rate, onChange: (e) => setRate(e.target.value), placeholder: "Rate Rs" }), kind === "custom" && _jsx("input", { "aria-label": "Charge quantity", value: qty, onChange: (e) => setQty(e.target.value), placeholder: "Qty" })] })), _jsx("button", { className: "btn primary", type: "submit", children: "Add charge" }), _jsx("button", { className: "btn", type: "button", onClick: onClose, children: "Cancel" })] }));
}
function WhatsAppSend({ patientId, invoiceId, text, onText, onClose }) {
    const [docs, setDocs] = useState([]);
    const [documentId, setDocumentId] = useState("");
    const [confirm, setConfirm] = useState(false);
    useEffect(() => {
        api(`/api/documents?patient_id=${encodeURIComponent(patientId)}`).then((row) => {
            const items = (row.items || []).filter((item) => !invoiceId || item.entity_id === invoiceId || item.entity_type === "prescription");
            setDocs(items);
        }).catch(() => setDocs([]));
    }, [patientId, invoiceId]);
    return (_jsxs(Modal, { title: "Send via WhatsApp", onClose: onClose, footer: _jsx("button", { className: "btn primary", type: "button", disabled: !confirm, onClick: () => run(async () => {
                if (documentId) {
                    await api("/api/whatsapp/documents", { method: "POST", body: JSON.stringify({ patient_id: patientId, document_id: documentId, caption: text, confirm: true }) });
                }
                else {
                    await api("/api/whatsapp/messages", { method: "POST", body: JSON.stringify({ patient_id: patientId, text, confirm: true }) });
                }
                onClose();
            }, documentId ? "Document sent" : "Message sent"), children: "Send" }), children: [_jsx("p", { className: "muted", children: "The message is sent through the hospital WhatsApp connection. Credentials stay on the server. If WhatsApp is not connected, the send fails and nothing is marked sent." }), _jsx(Field, { label: "Message", children: _jsx("textarea", { "aria-label": "WhatsApp message", value: text, onChange: (e) => onText(e.target.value), rows: 4 }) }), _jsx(Field, { label: "Stored document", children: _jsxs("select", { "aria-label": "Stored document", value: documentId, onChange: (e) => setDocumentId(e.target.value), children: [_jsx("option", { value: "", children: "Message only" }), docs.map((doc) => _jsx("option", { value: doc.id, children: doc.title || doc.filename }, doc.id))] }) }), !docs.length && _jsx("p", { className: "muted", children: "No stored bill or prescription file was found. Print stores a prescription file. The bill PDF is generated when you print it." }), _jsxs("label", { className: "check-line", children: [_jsx("input", { type: "checkbox", checked: confirm, onChange: (e) => setConfirm(e.target.checked) }), " I confirm this recipient and message."] })] }));
}
