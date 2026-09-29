import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, fileUrl, money, when } from "../api";
import { useApp } from "../store";
import { Empty, ErrorState, Field, Loading, Masters, Modal, Page, PatientLink, Status, run, useData } from "../ui";
const emptyForm = {
    name: "", primary_phone: "", alternate_phone: "", guardian_name: "", guardian_phone: "",
    gender: "Female", dob: "", age_at_registration: "", age_is_estimated: false, address: "",
    category_id: "", department_id: "", notes: "", allergies: "", emergency_name: "", emergency_phone: "",
    opd_type_id: "", doctor_id: "", chief_complaint: "", queue: true,
};
export function Register() {
    const navigate = useNavigate();
    const [params] = useSearchParams();
    const [form, setForm] = useState({ ...emptyForm, name: params.get("name") || "", primary_phone: params.get("phone") || "" });
    const [matches, setMatches] = useState([]);
    const [cards, setCards] = useState([]);
    const [chosen, setChosen] = useState(null);
    const [confirmNew, setConfirmNew] = useState(false);
    const [lookup, setLookup] = useState(params.get("phone") || "");
    const { data: types } = useData("/api/opd/types");
    const { data: doctors } = useData("/api/doctors");
    function set(key, value) {
        setForm((f) => ({ ...f, [key]: value }));
    }
    async function lookupPhone(phone) {
        if (phone.replace(/\D/g, "").length < 6) {
            setMatches([]);
            return;
        }
        const found = await api(`/api/patients/by-phone?phone=${encodeURIComponent(phone)}`);
        setMatches(found.items);
        setConfirmNew(false);
    }
    useEffect(() => {
        const existing = params.get("patient");
        if (!existing)
            return;
        api(`/api/patients/${existing}`).then(setChosen).catch(() => undefined);
    }, [params]);
    useEffect(() => {
        if (params.get("phone"))
            lookupPhone(params.get("phone") || "");
    }, [params]);
    useEffect(() => {
        if (!chosen) {
            setCards([]);
            return;
        }
        api(`/api/opd/valid?patient_id=${chosen.id}`).then((d) => setCards(d.items)).catch(() => setCards([]));
    }, [chosen]);
    async function submit(asNew) {
        if (matches.length && !chosen && !asNew && !confirmNew) {
            setConfirmNew(true);
            return;
        }
        await run(async () => {
            const person = {
                ...form,
                confirm_new: asNew || confirmNew || matches.length === 0,
                age_at_registration: form.age_at_registration === "" ? null : Number(form.age_at_registration),
            };
            if (form.opd_type_id) {
                await api("/api/visits", {
                    method: "POST",
                    body: JSON.stringify({
                        patient_id: chosen?.id,
                        patient: chosen ? undefined : person,
                        opd_type_id: form.opd_type_id,
                        doctor_id: form.doctor_id || null,
                        department_id: form.department_id || null,
                        chief_complaint: form.chief_complaint || form.notes,
                        queue: form.queue,
                        use_opd_id: form.use_opd_id || null,
                        ...(chosen ? {} : person),
                    }),
                });
                navigate("/queue");
                return;
            }
            const patient = chosen || await api("/api/patients", { method: "POST", body: JSON.stringify(person) });
            navigate(`/patients/${patient.id}`);
        }, chosen ? "Existing patient sent forward" : "Patient registered");
    }
    return (_jsx(Page, { title: "New Patient", note: "Register a new patient. Phone finds a possible match. It is not the patient identity.", actions: _jsx("button", { className: "btn", type: "button", onClick: () => { setForm(emptyForm); setChosen(null); setMatches([]); }, children: "Clear" }), children: _jsxs("div", { className: "grid-2", children: [_jsxs("form", { className: "panel", onSubmit: (e) => { e.preventDefault(); submit(false); }, children: [_jsx("h2", { children: chosen ? `Using ${chosen.name}` : "New registration" }), _jsxs("div", { className: "body grid-form", children: [_jsx("div", { className: "span-2 section-label", children: "Identity" }), _jsx(Field, { label: "Patient name", required: true, children: _jsx("input", { value: form.name, onChange: (e) => set("name", e.target.value), required: !chosen, autoFocus: true, disabled: !!chosen }) }), _jsx(Field, { label: "Gender", children: _jsx("div", { className: "seg", role: "group", "aria-label": "Gender", children: ["Female", "Male", "Other"].map((g) => (_jsx("button", { type: "button", className: form.gender === g ? "on" : "", onClick: () => set("gender", g), children: g }, g))) }) }), _jsx("div", { className: "span-2 section-label", children: "Demographics" }), _jsx(Field, { label: "Age (years)", children: _jsx("input", { value: form.age_at_registration, onChange: (e) => set("age_at_registration", e.target.value), disabled: !!chosen }) }), _jsx(Field, { label: "Date of birth", children: _jsx("input", { type: "date", value: form.dob, onChange: (e) => set("dob", e.target.value), disabled: !!chosen }) }), _jsx(Field, { label: "Category", children: _jsx("select", { value: form.category_id, onChange: (e) => set("category_id", e.target.value), disabled: !!chosen, children: _jsx(Masters, { type: "patient_category", label: "Category" }) }) }), _jsx(Field, { label: "Department", children: _jsx("select", { value: form.department_id, onChange: (e) => set("department_id", e.target.value), children: _jsx(Masters, { type: "department", label: "Department" }) }) }), _jsx("div", { className: "span-2 section-label", children: "Contact" }), _jsx(Field, { label: "Phone", children: _jsx("input", { value: form.primary_phone, onChange: (e) => set("primary_phone", e.target.value), onBlur: (e) => lookupPhone(e.target.value), disabled: !!chosen }) }), _jsx(Field, { label: "Alternate phone", children: _jsx("input", { value: form.alternate_phone, onChange: (e) => set("alternate_phone", e.target.value), disabled: !!chosen }) }), _jsx(Field, { label: "Guardian / parent", children: _jsx("input", { value: form.guardian_name, onChange: (e) => set("guardian_name", e.target.value), disabled: !!chosen }) }), _jsx(Field, { label: "Guardian phone", children: _jsx("input", { value: form.guardian_phone, onChange: (e) => set("guardian_phone", e.target.value), disabled: !!chosen }) }), _jsx("div", { className: "span-2 section-label", children: "Address" }), _jsx(Field, { label: "Address", className: "span-2", children: _jsx("input", { value: form.address, onChange: (e) => set("address", e.target.value), disabled: !!chosen }) }), _jsx("div", { className: "span-2 section-label", children: "Emergency and allergies" }), _jsx(Field, { label: "Emergency contact", children: _jsx("input", { value: form.emergency_name, onChange: (e) => set("emergency_name", e.target.value), disabled: !!chosen }) }), _jsx(Field, { label: "Emergency phone", children: _jsx("input", { value: form.emergency_phone, onChange: (e) => set("emergency_phone", e.target.value), disabled: !!chosen }) }), _jsx(Field, { label: "Allergies", className: "span-2", children: _jsx("input", { value: form.allergies, onChange: (e) => set("allergies", e.target.value), placeholder: "None known", disabled: !!chosen }) }), _jsx("div", { className: "span-2 section-label", children: "Start today's OPD visit" }), _jsx(Field, { label: "Short note", className: "span-2", children: _jsx("input", { value: form.notes, onChange: (e) => set("notes", e.target.value) }) }), _jsx(Field, { label: "OPD type", children: _jsxs("select", { value: form.opd_type_id, onChange: (e) => set("opd_type_id", e.target.value), children: [_jsx("option", { value: "", children: "Register only" }), (types?.items || []).map((t) => _jsxs("option", { value: t.id, children: [t.name, " \u00B7 ", money(t.fee_paise), " \u00B7 ", t.validity_days, "d"] }, t.id))] }) }), _jsx(Field, { label: "Doctor", children: _jsxs("select", { value: form.doctor_id, onChange: (e) => set("doctor_id", e.target.value), children: [_jsx("option", { value: "", children: "Assign later" }), (doctors?.items || []).map((d) => _jsxs("option", { value: d.id, children: [d.title, " ", d.full_name, " \u00B7 ", d.specialty] }, d.id))] }) }), _jsx(Field, { label: "Complaint", className: "span-2", children: _jsx("input", { value: form.chief_complaint, onChange: (e) => set("chief_complaint", e.target.value) }) }), cards.length > 0 && (_jsx(Field, { label: "Valid OPD card", className: "span-2", children: _jsxs("select", { value: form.use_opd_id || "", onChange: (e) => set("use_opd_id", e.target.value), children: [_jsx("option", { value: "", children: "Charge a new fee" }), cards.map((card) => _jsxs("option", { value: card.id, children: ["Use ", card.id, " \u00B7 ", card.opd_type_name, " \u00B7 valid till ", when(card.validity_until)] }, card.id))] }) })), _jsxs("label", { className: "span-2", children: [_jsx("input", { type: "checkbox", checked: form.queue, onChange: (e) => set("queue", e.target.checked) }), " Place in doctor queue"] }), _jsxs("div", { className: "span-2 row-actions", children: [_jsx("button", { className: "btn primary", type: "submit", children: chosen ? "Queue this patient" : "Register & continue" }), chosen && _jsx("button", { className: "btn", type: "button", onClick: () => { setChosen(null); setConfirmNew(false); }, children: "Not this person" })] })] })] }), _jsx("div", { children: _jsxs("div", { className: "panel", children: [_jsx("h2", { children: "Find an existing patient" }), _jsxs("div", { className: "body", children: [_jsx("form", { onSubmit: (e) => { e.preventDefault(); api(`/api/patients?q=${encodeURIComponent(lookup)}`).then((d) => setMatches(d.items)).catch(() => undefined); }, children: _jsx(Field, { label: "Name, phone, or patient ID", children: _jsx("input", { value: lookup, onChange: (e) => setLookup(e.target.value), placeholder: "Search before creating" }) }) }), matches.length === 0 && _jsx("p", { className: "muted", children: "A shared phone is not an identity. Search, then choose the person or confirm a new one." }), matches.length > 0 && !chosen && _jsx("div", { className: "warn", children: "Possible match on this phone. Choose the person, or confirm that this is someone else. Nothing is merged automatically." }), matches.map((p) => (_jsxs("div", { style: { borderBottom: "1px solid var(--line)", padding: "8px 0" }, children: [_jsx("strong", { children: p.name }), " ", _jsxs("span", { className: "muted", children: [p.id, " \u00B7 ", p.age_display, " \u00B7 ", p.gender] }), _jsxs("div", { className: "muted", children: [p.guardian_name || "No guardian", " \u00B7 ", p.address] }), _jsx("button", { className: "btn small", type: "button", onClick: () => setChosen(p), children: "Use existing patient" })] }, p.id))), confirmNew && matches.length > 0 && !chosen && (_jsxs("div", { className: "warn", children: ["This phone already belongs to ", matches.map((m) => m.name).join(", "), ". Create a new patient only if this is a different person.", _jsx("div", { style: { marginTop: 8 }, children: _jsx("button", { className: "btn primary", type: "button", onClick: () => submit(true), children: "Create new patient" }) })] }))] })] }) })] }) }));
}
export function Patients() {
    const canEdit = useApp((s) => s.can("patient.edit"));
    const [q, setQ] = useState("");
    const [path, setPath] = useState("/api/patients");
    useEffect(() => {
        const id = window.setTimeout(() => setPath(q.trim() ? `/api/patients?q=${encodeURIComponent(q.trim())}` : "/api/patients"), 180);
        return () => window.clearTimeout(id);
    }, [q]);
    const { data, error, loading } = useData(path);
    return (_jsxs(Page, { title: "Patients", note: "Search and manage hospital patients. Phone is not an identity.", actions: _jsx("form", { onSubmit: (e) => { e.preventDefault(); setPath(q.trim() ? `/api/patients?q=${encodeURIComponent(q.trim())}` : "/api/patients"); }, children: _jsx("input", { "aria-label": "Search patients", placeholder: "Name, phone, Patient ID", value: q, onChange: (e) => setQ(e.target.value), style: { width: 240 } }) }), children: [loading && !data && _jsx(Loading, { label: "Searching records\u2026" }), error && _jsx(ErrorState, { message: error }), !loading && data && !data.items?.length && _jsx(Empty, { text: "No patient matches that search." }), _jsx("div", { className: "table-wrap", children: _jsxs("table", { className: "data", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "Patient ID" }), _jsx("th", { children: "Name" }), _jsx("th", { children: "Age / sex" }), _jsx("th", { children: "Phone" }), _jsx("th", { children: "Guardian" }), _jsx("th", { children: "Category" }), _jsx("th", {})] }) }), _jsx("tbody", { children: (data?.items || []).map((p) => (_jsxs("tr", { children: [_jsx("td", { className: "pid", children: _jsx(Link, { to: `/patients/${p.id}`, children: p.id }) }), _jsx("td", { children: _jsxs("span", { className: "identity", children: [_jsx("span", { className: "avatar", children: String(p.name || "?").slice(0, 1) }), _jsxs("span", { children: [p.name, " ", p.is_sample ? _jsx("span", { className: "sample-badge", children: "SAMPLE" }) : null] })] }) }), _jsxs("td", { children: [p.age_display, " \u00B7 ", p.gender] }), _jsx("td", { children: p.primary_phone }), _jsx("td", { children: p.guardian_name }), _jsx("td", { children: p.category_name }), _jsxs("td", { className: "row-actions", children: [_jsx(Link, { className: "btn small", to: `/patients/${p.id}`, children: "View" }), canEdit && _jsx("button", { className: "btn small danger", type: "button", onClick: () => {
                                                    if (!window.confirm(`Permanently delete ${p.name} (${p.id})? Visits, bills, admissions, and documents for this patient are removed. This cannot be undone.`))
                                                        return;
                                                    run(() => api(`/api/patients/${p.id}`, { method: "DELETE" }), "Patient deleted");
                                                }, children: "Delete" })] })] }, p.id))) })] }) })] }));
}
function PatientMessage({ patient }) {
    const can = useApp((s) => s.can);
    const [text, setText] = useState("");
    if (!can("whatsapp.send"))
        return null;
    return (_jsxs("div", { className: "panel", children: [_jsx("h2", { children: "Message this patient" }), _jsxs("div", { className: "body", children: [_jsxs("p", { className: "muted", children: ["Sends to ", patient.primary_phone ? `the number ending ${String(patient.primary_phone).slice(-4)}` : "no phone on record", ". The provider is the one configured for the hospital, not a hardcoded service."] }), _jsx(Field, { label: "Message", children: _jsx("textarea", { value: text, onChange: (e) => setText(e.target.value) }) }), _jsx("button", { className: "btn", disabled: !text.trim() || !patient.primary_phone, onClick: () => {
                            if (!window.confirm(`Send this message to ${patient.name}?`))
                                return;
                            run(() => api("/api/whatsapp/messages", { method: "POST", body: JSON.stringify({ patient_id: patient.id, text, confirm: true }) }), "Message handed to the provider");
                        }, children: "Send message" })] })] }));
}
function SendDocument({ patient, documentId, title }) {
    const can = useApp((s) => s.can);
    if (!can("whatsapp.send"))
        return null;
    return (_jsx("button", { className: "btn small", onClick: () => {
            if (!window.confirm(`Send ${title} to ${patient.name}?`))
                return;
            run(() => api("/api/whatsapp/documents", { method: "POST", body: JSON.stringify({ patient_id: patient.id, document_id: documentId, confirm: true }) }), "Document handed to the provider");
        }, children: "Send" }));
}
export function PatientPage() {
    const { id } = useParams();
    const navigate = useNavigate();
    const canEdit = useApp((s) => s.can("patient.edit"));
    const { data, error, loading } = useData(id ? `/api/patients/${id}/timeline` : null);
    const [tab, setTab] = useState("overview");
    const [docOpen, setDocOpen] = useState(false);
    const [editing, setEditing] = useState(false);
    const [form, setForm] = useState(null);
    useEffect(() => {
        if (data?.patient && !editing)
            setForm(data.patient);
    }, [data, editing]);
    if (error)
        return _jsx(Page, { title: "Patient", children: _jsx(ErrorState, { message: error }) });
    if (loading && !data)
        return _jsx(Page, { title: "Patient", children: _jsx(Loading, { label: "Opening record\u2026" }) });
    if (!data)
        return _jsx(Page, { title: "Patient", children: _jsx(Loading, { label: "Opening record\u2026" }) });
    const p = data.patient;
    const latest = data.encounters?.[0];
    const tabs = [
        ["overview", "Overview"],
        ["opd", "Encounters"],
        ["prescriptions", "Prescriptions"],
        ["lab", "Lab"],
        ["documents", "Documents"],
        ["admissions", "Admissions"],
        ["bills", "Bills"],
        ["timeline", "Timeline"],
    ];
    return (_jsxs(Page, { kicker: "Patient ID", title: p.name, note: p.id, actions: _jsxs(_Fragment, { children: [_jsx(Link, { className: "btn primary", to: `/register?patient=${p.id}`, children: "New OPD" }), canEdit && _jsx("button", { className: "btn", type: "button", onClick: () => { setForm(p); setEditing(true); }, children: "Edit" }), _jsx("button", { className: "btn", type: "button", onClick: () => setDocOpen(true), children: "Add document" }), canEdit && _jsx("button", { className: "btn danger", type: "button", onClick: () => {
                        if (!window.confirm(`Permanently delete ${p.name} (${p.id})? Visits, bills, admissions, and documents for this patient are removed. This cannot be undone.`))
                            return;
                        run(async () => {
                            await api(`/api/patients/${p.id}`, { method: "DELETE" });
                            navigate("/patients");
                        }, "Patient deleted");
                    }, children: "Delete" }), p.is_sample ? _jsx("span", { className: "sample-badge", children: "SAMPLE" }) : null] }), children: [_jsxs("div", { className: "quick-actions", children: [_jsx(Link, { to: `/register?patient=${p.id}`, children: "New OPD" }), _jsx(Link, { to: "/queue", children: "Queue" }), latest && _jsx(Link, { to: `/consult/${latest.id}`, children: "Consultation" }), latest && _jsx(Link, { to: `/consult/${latest.id}`, children: "Prescription" }), _jsx(Link, { to: `/billing?patient=${p.id}`, children: "Billing" }), _jsx("button", { type: "button", onClick: () => setTab("documents"), children: "Documents" }), _jsx(Link, { to: "/lab", children: "Lab" }), _jsx(Link, { to: `/admissions?patient=${p.id}`, children: "Admission" }), _jsx(Link, { to: "/pharmacy", children: "Pharmacy" })] }), _jsxs("div", { className: "banner", children: [_jsxs("div", { children: [_jsxs("h2", { children: [p.name, " ", _jsx("span", { className: "pid", children: p.id })] }), _jsxs("div", { className: "muted", children: [p.age_display, " \u00B7 ", p.gender, " \u00B7 ", p.primary_phone || "no phone", " \u00B7 Guardian ", p.guardian_name || "—"] }), _jsxs("div", { className: "muted", children: [p.address || "Address not recorded", " \u00B7 ", p.category_name] }), (p.emergency_name || p.emergency_phone) && _jsxs("div", { className: "muted", children: ["Emergency ", p.emergency_name || "—", " \u00B7 ", p.emergency_phone || "no phone"] })] }), _jsx("div", { children: p.allergies ? _jsxs("div", { className: "allergy", children: ["Allergy: ", p.allergies] }) : _jsx("span", { className: "muted", children: "No allergy recorded" }) })] }), editing && form && (_jsxs("div", { className: "panel", children: [_jsx("h2", { children: "Edit patient" }), _jsxs("div", { className: "body grid-form", children: [_jsx(Field, { label: "Name", children: _jsx("input", { value: form.name || "", onChange: (e) => setForm({ ...form, name: e.target.value }) }) }), _jsx(Field, { label: "Phone", children: _jsx("input", { value: form.primary_phone || "", onChange: (e) => setForm({ ...form, primary_phone: e.target.value }) }) }), _jsx(Field, { label: "Gender", children: _jsx("input", { value: form.gender || "", onChange: (e) => setForm({ ...form, gender: e.target.value }) }) }), _jsx(Field, { label: "Age", children: _jsx("input", { value: form.age_at_registration ?? "", onChange: (e) => setForm({ ...form, age_at_registration: e.target.value }) }) }), _jsx(Field, { label: "Guardian", children: _jsx("input", { value: form.guardian_name || "", onChange: (e) => setForm({ ...form, guardian_name: e.target.value }) }) }), _jsx(Field, { label: "Guardian phone", children: _jsx("input", { value: form.guardian_phone || "", onChange: (e) => setForm({ ...form, guardian_phone: e.target.value }) }) }), _jsx(Field, { label: "Address", className: "span-2", children: _jsx("input", { value: form.address || "", onChange: (e) => setForm({ ...form, address: e.target.value }) }) }), _jsx(Field, { label: "Allergies", className: "span-2", children: _jsx("input", { value: form.allergies || "", onChange: (e) => setForm({ ...form, allergies: e.target.value }) }) }), _jsxs("div", { className: "row-actions", children: [_jsx("button", { className: "btn primary", type: "button", onClick: () => run(async () => {
                                            const age = form.age_at_registration === "" || form.age_at_registration == null ? null : Number(form.age_at_registration);
                                            await api(`/api/patients/${p.id}`, { method: "PATCH", body: JSON.stringify({ ...p, ...form, age_at_registration: age }) });
                                            setEditing(false);
                                        }, "Patient updated"), children: "Save" }), _jsx("button", { className: "btn", type: "button", onClick: () => { setEditing(false); setForm(p); }, children: "Cancel" })] })] })] })), _jsx("div", { className: "tabs", role: "tablist", children: tabs.map(([key, label]) => (_jsx("button", { type: "button", role: "tab", "aria-selected": tab === key, className: tab === key ? "on" : "", onClick: () => setTab(key), children: label }, key))) }), tab === "overview" && (_jsx("div", { className: "panel", children: _jsxs("div", { className: "body", children: [_jsxs("p", { children: [data.encounters?.length || 0, " encounters \u00B7 ", data.prescriptions?.length || 0, " prescriptions \u00B7 ", data.invoices?.length || 0, " bills \u00B7 ", data.documents?.length || 0, " documents"] }), _jsx("p", { className: "muted", children: latest ? `Latest visit ${latest.id} · ${when(latest.arrived_at)}` : "No OPD visit yet. Start today's OPD visit from New OPD." })] }) })), tab === "prescriptions" && (_jsxs("table", { className: "data", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "Prescription" }), _jsx("th", { children: "Encounter" }), _jsx("th", { children: "Status" }), _jsx("th", {})] }) }), _jsxs("tbody", { children: [(data.prescriptions || []).map((rx) => (_jsxs("tr", { children: [_jsx("td", { className: "pid", children: rx.id }), _jsx("td", { children: rx.encounter_id ? _jsx(Link, { to: `/consult/${rx.encounter_id}`, children: rx.encounter_id }) : "—" }), _jsx("td", { children: _jsx(Status, { value: rx.status }) }), _jsx("td", { children: rx.status === "FINALIZED" && _jsx("a", { href: fileUrl(`/api/prescriptions/${rx.id}/pdf`), target: "_blank", rel: "noreferrer", children: "Print" }) })] }, rx.id))), !data.prescriptions?.length && _jsx("tr", { children: _jsx("td", { colSpan: 4, className: "muted", children: "No prescription on this record." }) })] })] })), tab === "lab" && (_jsxs("table", { className: "data", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "Order" }), _jsx("th", { children: "When" }), _jsx("th", { children: "Status" })] }) }), _jsxs("tbody", { children: [(data.labs || []).map((lab) => (_jsxs("tr", { children: [_jsx("td", { children: _jsx(Link, { to: "/lab", children: lab.id }) }), _jsx("td", { children: when(lab.ordered_at) }), _jsx("td", { children: _jsx(Status, { value: lab.status }) })] }, lab.id))), !data.labs?.length && _jsx("tr", { children: _jsx("td", { colSpan: 3, className: "muted", children: "No lab order on this record." }) })] })] })), tab === "timeline" && (data.events?.length ? (_jsx("ol", { className: "timeline", children: data.events.map((ev, i) => (_jsxs("li", { children: [_jsx("span", { className: "muted", children: when(ev.at) }), _jsx("i", {}), _jsxs("div", { children: [_jsx("strong", { children: ev.title }), _jsx("div", { className: "muted", children: ev.detail })] })] }, i))) })) : _jsx(Empty, { text: "No visits, bills, or documents are on this record yet." })), tab === "opd" && (_jsxs("table", { className: "data", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "Encounter" }), _jsx("th", { children: "When" }), _jsx("th", { children: "Complaint" }), _jsx("th", { children: "Status" })] }) }), _jsx("tbody", { children: data.encounters.map((e) => (_jsxs("tr", { children: [_jsx("td", { children: _jsx(Link, { to: `/consult/${e.id}`, children: e.id }) }), _jsx("td", { children: when(e.arrived_at) }), _jsx("td", { children: e.chief_complaint }), _jsx("td", { children: _jsx(Status, { value: e.status }) })] }, e.id))) })] })), tab === "bills" && (_jsxs("table", { className: "data", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "Bill" }), _jsx("th", { children: "Type" }), _jsx("th", { children: "Status" }), _jsx("th", { className: "num", children: "Net" }), _jsx("th", { className: "num", children: "Due" })] }) }), _jsx("tbody", { children: data.invoices.map((e) => (_jsxs("tr", { children: [_jsx("td", { children: _jsx(Link, { to: `/billing/${e.id}`, children: e.number }) }), _jsx("td", { children: e.bill_type }), _jsx("td", { children: _jsx(Status, { value: e.payment_status }) }), _jsx("td", { className: "num", children: money(e.net_paise) }), _jsx("td", { className: "num", children: money(e.due_paise) })] }, e.id))) })] })), tab === "admissions" && (_jsxs("table", { className: "data", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "Admission" }), _jsx("th", { children: "Status" }), _jsx("th", { children: "Admitted" })] }) }), _jsx("tbody", { children: data.admissions.map((e) => _jsxs("tr", { children: [_jsx("td", { children: _jsx(Link, { to: `/admissions/${e.id}`, children: e.id }) }), _jsx("td", { children: _jsx(Status, { value: e.status }) }), _jsx("td", { children: when(e.admitted_at) })] }, e.id)) })] })), tab === "timeline" && _jsx(PatientMessage, { patient: p }), tab === "documents" && (_jsxs("table", { className: "data", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "When" }), _jsx("th", { children: "Type" }), _jsx("th", { children: "Title" }), _jsx("th", {})] }) }), _jsx("tbody", { children: data.documents.map((d) => (_jsxs("tr", { children: [_jsx("td", { children: when(d.uploaded_at) }), _jsx("td", { children: d.document_type }), _jsx("td", { children: d.title || d.filename }), _jsxs("td", { className: "row-actions", children: [_jsx("a", { href: fileUrl(`/api/documents/${d.id}/file`), target: "_blank", children: "Open" }), _jsx(SendDocument, { patient: p, documentId: d.id, title: d.title || d.filename })] })] }, d.id))) })] })), docOpen && _jsx(UploadDoc, { patientId: p.id, onClose: () => setDocOpen(false) })] }));
}
export function UploadDoc({ patientId, entityType, entityId, onClose }) {
    const [type, setType] = useState("Lab report");
    const [title, setTitle] = useState("");
    const { data } = useData("/api/master/document_type");
    return (_jsx(Modal, { title: "Add document", onClose: onClose, footer: _jsx("span", { className: "muted", children: "Stored on this server. 8 MB, PDF or image." }), children: _jsxs("div", { className: "grid-form", children: [_jsx(Field, { label: "Type", children: _jsx("select", { value: type, onChange: (e) => setType(e.target.value), children: (data?.items || [{ name: type }]).map((d) => _jsx("option", { children: d.name }, d.name)) }) }), _jsx(Field, { label: "Title", children: _jsx("input", { value: title, onChange: (e) => setTitle(e.target.value) }) }), _jsx(Field, { label: "File", className: "span-2", children: _jsx("input", { type: "file", accept: "application/pdf,image/*", onChange: async (e) => {
                            const file = e.target.files?.[0];
                            if (!file)
                                return;
                            const content_base64 = await fileToBase64(file);
                            await run(() => api("/api/documents", { method: "POST", body: JSON.stringify({ patient_id: patientId, document_type: type, title: title || file.name, filename: file.name, mime_type: file.type, content_base64, entity_type: entityType, entity_id: entityId }) }), "Document stored");
                            onClose();
                        } }) })] }) }));
}
function fileToBase64(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
        reader.onerror = reject;
        reader.readAsDataURL(file);
    });
}
function waited(iso) {
    if (!iso)
        return "—";
    const parsed = Date.parse(iso.includes("T") ? iso : iso.replace(" ", "T"));
    if (!Number.isFinite(parsed))
        return "—";
    const mins = Math.max(0, Math.round((Date.now() - parsed) / 60000));
    if (mins < 1)
        return "Just arrived";
    if (mins < 60)
        return `${mins} min`;
    return `${Math.floor(mins / 60)}h ${mins % 60}m`;
}
export function QueuePage({ mine = false }) {
    const canAssign = useApp((s) => s.can("opd.assign"));
    const { data, error, loading } = useData(`/api/queue${mine ? "?mine=1" : ""}`);
    const { data: doctors } = useData(canAssign ? "/api/doctors" : null);
    const [status, setStatus] = useState("ALL");
    const items = data?.items || [];
    const serving = items.find((q) => q.status === "CALLED" || q.status === "IN_CONSULTATION");
    const shown = items.filter((q) => status === "ALL" || q.status === status);
    const counts = items.reduce((acc, q) => { acc[q.status] = (acc[q.status] || 0) + 1; return acc; }, {});
    return (_jsxs(Page, { title: mine ? "Doctor Queue" : "Today's OPD", note: mine ? "The queue assigned to you. Calling does not open the consultation." : "Today's tokens. Calling does not open the consultation.", children: [serving && (_jsxs("div", { className: "panel", children: [_jsx("h2", { children: "Now serving" }), _jsxs("div", { className: "body identity", children: [_jsx("span", { className: "avatar", children: String(serving.patient_name || "?").slice(0, 1) }), _jsxs("div", { children: [_jsx("strong", { children: serving.patient_name }), _jsxs("div", { className: "muted", children: [serving.patient_id, " \u00B7 T-", String(serving.token_no).padStart(3, "0"), " \u00B7 ", waited(serving.arrived_at)] })] }), _jsx(Status, { value: serving.status }), _jsx(Link, { className: "btn primary", to: `/consult/${serving.encounter_id}`, children: "Open" })] })] })), _jsx("div", { className: "tabs", role: "tablist", "aria-label": "Queue status", children: ["ALL", "WAITING", "CALLED", "IN_CONSULTATION", "COMPLETED"].map((key) => (_jsxs("button", { type: "button", className: status === key ? "on" : "", onClick: () => setStatus(key), children: [key === "ALL" ? "All" : key.replaceAll("_", " "), " (", key === "ALL" ? items.length : counts[key] || 0, ")"] }, key))) }), loading && !data && _jsx(Loading, { label: "Opening the queue\u2026" }), error && _jsx(ErrorState, { message: error }), !loading && data && !data.items?.length && _jsx(Empty, { text: "Queue is clear." }), _jsx("div", { className: "table-wrap", children: _jsxs("table", { className: "data", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "Token" }), _jsx("th", { children: "Patient" }), _jsx("th", { children: "Wait" }), _jsx("th", { children: "Age / sex" }), _jsx("th", { children: "Doctor" }), _jsx("th", { children: "Priority" }), _jsx("th", { children: "Status" }), _jsx("th", {})] }) }), _jsx("tbody", { children: shown.map((q) => (_jsxs("tr", { children: [_jsx("td", { children: _jsxs("span", { className: "token", children: ["T-", String(q.token_no).padStart(3, "0")] }) }), _jsxs("td", { children: [_jsx(PatientLink, { id: q.patient_id, name: q.patient_name }), _jsx("div", { className: "muted pid", children: q.patient_id })] }), _jsx("td", { children: waited(q.arrived_at) }), _jsxs("td", { children: [q.age_display, " \u00B7 ", q.gender] }), _jsx("td", { children: canAssign ? (_jsxs("select", { "aria-label": `Doctor for ${q.patient_name}`, value: q.doctor_id || "", onChange: (e) => run(() => api(`/api/opd/${q.encounter_id}/assign`, { method: "POST", body: JSON.stringify({ doctor_id: e.target.value }) }), "Doctor assigned"), children: [_jsx("option", { value: "", children: "Unassigned" }), (doctors?.items || []).map((d) => _jsx("option", { value: d.id, children: d.full_name }, d.id))] })) : (q.doctor_name || "Unassigned") }), _jsx("td", { children: q.priority_label && q.priority_label !== "ROUTINE" ? _jsx(Status, { value: q.priority_label }) : _jsx("span", { className: "muted", children: "Routine" }) }), _jsx("td", { children: _jsx(Status, { value: q.status }) }), _jsxs("td", { className: "row-actions", children: [_jsx(Link, { className: "btn small", to: `/consult/${q.encounter_id}`, children: "Open" }), q.status === "WAITING" && _jsx("button", { className: "btn small", type: "button", onClick: () => run(() => api(`/api/queue/${q.id}/status`, { method: "POST", body: JSON.stringify({ status: "CALLED" }) }), "Called"), children: "Call" })] })] }, q.id))) })] }) })] }));
}
export function Documents() {
    const [query, setQuery] = useState("");
    const [path, setPath] = useState("/api/documents");
    const { data, error, loading } = useData(path);
    return (_jsxs(Page, { title: "Documents", note: "Search by patient ID, name, encounter, prescription, or document type.", actions: _jsx("form", { onSubmit: (e) => { e.preventDefault(); const q = query.trim(); setPath(q ? `/api/documents?q=${encodeURIComponent(q)}` : "/api/documents"); }, children: _jsx("input", { "aria-label": "Search documents", placeholder: "Patient ID, name, or document", value: query, onChange: (e) => setQuery(e.target.value), style: { width: 220 } }) }), children: [loading && !data && _jsx(Loading, { label: "Opening documents\u2026" }), error && _jsx(ErrorState, { message: error }), !loading && data && !data.items?.length && _jsx(Empty, { text: "No documents match this search." }), _jsx("div", { className: "table-wrap", children: _jsxs("table", { className: "data", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "When" }), _jsx("th", { children: "Type" }), _jsx("th", { children: "Patient" }), _jsx("th", { children: "Encounter" }), _jsx("th", { children: "Recorded by" }), _jsx("th", { children: "Status" }), _jsx("th", {})] }) }), _jsx("tbody", { children: (data?.items || []).map((d) => (_jsxs("tr", { children: [_jsx("td", { children: when(d.uploaded_at) }), _jsx("td", { children: d.document_type }), _jsxs("td", { children: [_jsx(Link, { to: `/patients/${d.patient_id}`, children: d.patient_name || d.patient_id }), _jsx("div", { className: "muted pid", children: d.patient_id })] }), _jsx("td", { className: "pid", children: d.notes || d.entity_id || "—" }), _jsx("td", { children: d.uploaded_by_name || "—" }), _jsx("td", { children: d.active ? "Filed" : "Withdrawn" }), _jsxs("td", { className: "row-actions", children: [_jsx("a", { href: fileUrl(`/api/documents/${d.id}/file`), target: "_blank", rel: "noreferrer", children: "View" }), _jsx("a", { href: fileUrl(`/api/documents/${d.id}/file`), target: "_blank", rel: "noreferrer", children: "Print" }), _jsx("a", { href: fileUrl(`/api/documents/${d.id}/file`), download: d.filename || "document.pdf", children: "Download" }), _jsx(SendDocument, { patient: { id: d.patient_id, name: d.patient_name || d.patient_id }, documentId: d.id, title: d.title || d.filename })] })] }, d.id))) })] }) })] }));
}
export function Leads() {
    const { data } = useData("/api/leads");
    const navigate = useNavigate();
    return (_jsxs(Page, { kicker: "Website", title: "Leads", actions: _jsx("button", { className: "btn", onClick: () => run(() => api("/api/leads/sync", { method: "POST" }), "Sync attempted"), children: "Sync" }), children: [_jsx("p", { className: "muted", children: "The public website is optional. If MongoDB is down, register the caller here or at the desk. The hospital does not stop." }), _jsxs("table", { className: "data", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "Name" }), _jsx("th", { children: "Phone" }), _jsx("th", { children: "Message" }), _jsx("th", { children: "Status" }), _jsx("th", {})] }) }), _jsx("tbody", { children: (data?.items || []).map((lead) => (_jsxs("tr", { children: [_jsx("td", { children: lead.name }), _jsx("td", { children: lead.phone }), _jsx("td", { children: lead.message }), _jsx("td", { children: _jsx(Status, { value: lead.status }) }), _jsxs("td", { className: "row-actions", children: [_jsx("button", { className: "btn small", onClick: () => navigate(`/register?phone=${encodeURIComponent(lead.phone || "")}&name=${encodeURIComponent(lead.name || "")}`), children: "Register" }), _jsx("button", { className: "btn small", onClick: () => run(() => api(`/api/leads/${lead.id}/archive`, { method: "POST" }), "Archived"), children: "Archive" })] })] }, lead.id))) })] })] }));
}
