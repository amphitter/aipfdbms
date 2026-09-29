import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, money, when } from "../api";
import { Icon } from "../icons";
import { useApp } from "../store";
import { ErrorState, Loading, Page, PatientLink, Status } from "../ui";
const CLOSED = new Set(["COMPLETED", "CANCELLED", "DISCHARGED", "VOID"]);
function num(value) {
    const n = Number(value);
    return Number.isFinite(n) ? n : 0;
}
function formatDay(iso) {
    if (!iso || !/^\d{4}-\d{2}-\d{2}$/.test(iso))
        return "";
    const [year, month, day] = iso.split("-").map(Number);
    return new Date(year, month - 1, day).toLocaleDateString("en-IN", {
        weekday: "long",
        day: "numeric",
        month: "long",
        year: "numeric",
    });
}
function versus(today, yesterday, asMoney = false) {
    if (today == null || yesterday == null)
        return "";
    const delta = Number(today) - Number(yesterday);
    if (!Number.isFinite(delta) || delta === 0)
        return "";
    const shown = asMoney ? money(Math.abs(delta)) : String(Math.abs(delta));
    return delta > 0 ? `${shown} more than yesterday` : `${shown} fewer than yesterday`;
}
function healthLabel(value) {
    const state = (value || "").toUpperCase();
    if (!state || state === "UNKNOWN")
        return "No health check yet";
    if (state === "UNCHECKED")
        return "No health check yet";
    if (state === "OFFLINE")
        return "Offline";
    return state.charAt(0) + state.slice(1).toLowerCase();
}
function healthTone(value) {
    const state = (value || "").toUpperCase();
    if (state === "HEALTHY")
        return "ok";
    if (state === "DEGRADED" || state === "WARNING")
        return "wait";
    if (state === "CRITICAL" || state === "OFFLINE")
        return "bad";
    return "";
}
function waLabel(state) {
    if (state === "connected")
        return "Connected";
    if (state === "configured")
        return "Not checked";
    return "Not connected";
}
function token(n) {
    return `T-${String(n ?? "").padStart(3, "0")}`;
}
function actionLabel(action) {
    const known = {
        login: "Signed in",
        login_failed: "Sign-in failed",
        backup_create: "Backup saved",
        payment: "Payment recorded",
        patient_create: "Patient registered",
        patient_update: "Patient updated",
        invoice_finalize: "Bill finalized",
        whatsapp_config: "WhatsApp settings saved",
    };
    if (!action)
        return "Activity";
    return known[action] || action.replaceAll("_", " ");
}
function applyLive(prev, detail) {
    if (!prev || !detail?.event)
        return prev;
    const data = detail.data || {};
    const event = String(detail.event);
    const next = {
        ...prev,
        queue: Array.isArray(prev.queue) ? prev.queue.map((row) => ({ ...row })) : [],
        my_queue: Array.isArray(prev.my_queue) ? prev.my_queue.map((row) => ({ ...row })) : [],
        ot: Array.isArray(prev.ot) ? prev.ot.map((row) => ({ ...row })) : [],
    };
    if (event === "queue.updated" && data.id && data.status) {
        const patch = (row) => (row.id === data.id ? { ...row, status: data.status } : row);
        next.queue = next.queue.map(patch).filter((row) => !CLOSED.has(row.status));
        next.my_queue = next.my_queue.map(patch).filter((row) => !CLOSED.has(row.status));
    }
    if (String(event).includes("ot") && data.id && data.status) {
        next.ot = next.ot.map((row) => (row.id === data.id ? { ...row, status: data.status } : row));
    }
    return next;
}
function Metric({ to, label, value, hint, tone = "" }) {
    return (_jsxs(Link, { className: `metric ${tone}`, to: to, children: [_jsx("strong", { children: value }), _jsx("span", { children: label }), hint ? _jsx("small", { children: hint }) : null] }));
}
function Head({ icon, title, to, label = "Open" }) {
    return (_jsxs("header", { className: "dash-h", children: [_jsxs("h2", { children: [_jsx(Icon, { name: icon, size: 16 }), " ", title] }), to ? _jsx(Link, { to: to, children: label }) : null] }));
}
function Quiet({ text }) {
    return _jsx("p", { className: "quiet", children: text });
}
export function Home() {
    const can = useApp((s) => s.can);
    const [data, setData] = useState(null);
    const [error, setError] = useState("");
    const [loading, setLoading] = useState(true);
    const [more, setMore] = useState(false);
    const moreRef = useRef(null);
    const requestId = useRef(0);
    const hasData = useRef(false);
    const load = useCallback(async () => {
        const id = ++requestId.current;
        try {
            const next = await api("/api/dashboard");
            if (id !== requestId.current)
                return;
            hasData.current = true;
            setData(next);
            setError("");
        }
        catch (err) {
            if (id !== requestId.current)
                return;
            if (!hasData.current)
                setError(err instanceof Error ? err.message : "Today could not load.");
        }
        finally {
            if (id === requestId.current)
                setLoading(false);
        }
    }, []);
    useEffect(() => {
        load();
    }, [load]);
    useEffect(() => {
        let timer;
        const onLive = (event) => {
            const detail = event.detail;
            setData((prev) => applyLive(prev, detail));
            if (timer)
                window.clearTimeout(timer);
            timer = window.setTimeout(() => load(), 2000);
        };
        window.addEventListener("aipf-live", onLive);
        return () => {
            window.removeEventListener("aipf-live", onLive);
            if (timer)
                window.clearTimeout(timer);
        };
    }, [load]);
    useEffect(() => {
        if (!more)
            return;
        const close = (event) => {
            if (!moreRef.current?.contains(event.target))
                setMore(false);
        };
        window.addEventListener("mousedown", close);
        return () => window.removeEventListener("mousedown", close);
    }, [more]);
    const c = data?.counts || {};
    const scope = data?.scope || {};
    const financial = Boolean(scope.financial && (can("billing.view") || can("report.view")));
    const stock = Boolean(scope.stock && (can("inventory.view") || can("report.view")));
    const clinical = can("patient.view") || can("opd.view") || can("queue.view");
    const showBeds = can("bed.view") || can("ipd.bed.view");
    const showAdmissions = can("admission.view") || can("ipd.admission.view");
    const moreItems = [
        { to: "/pharmacy", label: "Pharmacy", perm: "pharmacy.view" },
        { to: "/inventory", label: "Inventory", perm: "inventory.view" },
        { to: "/lab", label: "Laboratory", perm: "lab.view" },
        { to: "/admissions", label: "Admissions", perm: "admission.view" },
        { to: "/beds", label: "Beds", perm: "bed.view" },
        { to: "/ot", label: "Operation theatre", perm: "ot.view" },
        { to: "/documents", label: "Documents", perm: "document.view" },
        { to: "/reports", label: "Reports", perm: "report.view" },
        { to: "/leads", label: "Leads", perm: "leads.view" },
        { to: "/doctor", label: "My queue", perm: "consultation.create" },
    ].filter((item) => can(item.perm));
    const attention = [
        { n: c.queue_waiting, label: "Waiting in queue", to: "/queue", perm: "queue.view", tone: "pending" },
        { n: c.queue_pharmacy, label: "Waiting for pharmacy", to: "/pharmacy", perm: "pharmacy.view", tone: "pending" },
        { n: c.pharmacy_queue, label: "Prescriptions to dispense", to: "/pharmacy", perm: "pharmacy.view", tone: "pending" },
        { n: c.pending_reports, label: "Lab orders open", to: "/lab", perm: "lab.view", tone: "pending" },
        { n: c.pending_bills, label: "Draft bills", to: "/billing", perm: "billing.view", tone: "pending" },
        { n: c.bills_due, label: "Bills with a balance", to: "/billing", perm: "billing.view", tone: "pending" },
        { n: c.low_stock, label: "Low stock", to: "/inventory/low", perm: "inventory.view", tone: "pending" },
        { n: c.expiring, label: "Expiring soon", to: "/inventory/expiring", perm: "inventory.view", tone: "pending" },
        { n: c.expired, label: "Expired stock", to: "/inventory/expired", perm: "inventory.view", tone: "critical" },
        { n: c.ot_open, label: "OT cases still open", to: "/ot", perm: "ot.view", tone: "pending" },
        { n: c.whatsapp_failed_today, label: "WhatsApp failed today", to: "/admin/integrations", perm: "whatsapp.configure", tone: "critical" },
        { n: c.leads_new, label: "New leads", to: "/leads", perm: "leads.view", tone: "pending" },
    ].filter((item) => num(item.n) > 0 && can(item.perm));
    const flow = [
        { n: c.patients_today, label: "Registered", to: "/patients", show: can("patient.view") },
        { n: c.opd_today, label: "OPD", to: can("queue.view") ? "/queue" : "/patients", show: can("opd.view") },
        { n: c.queue_waiting, label: "Waiting", to: "/queue", show: can("queue.view"), tone: num(c.queue_waiting) ? "pending" : "" },
        { n: c.queue_consulting, label: "In consult", to: can("consultation.create") ? "/doctor" : "/queue", show: can("queue.view") || can("consultation.create"), tone: num(c.queue_consulting) ? "normal" : "" },
        { n: c.queue_pharmacy, label: "Pharmacy", to: "/pharmacy", show: can("pharmacy.view"), tone: num(c.queue_pharmacy) ? "pending" : "" },
        { n: c.queue_billing, label: "For billing", to: "/billing", show: can("billing.view"), tone: num(c.queue_billing) ? "pending" : "" },
        { n: c.admissions_today, label: "Admitted", to: "/admissions", show: showAdmissions },
        { n: c.discharges_today, label: "Discharged", to: "/admissions", show: showAdmissions, tone: num(c.discharges_today) ? "done" : "" },
        { n: c.pending_reports, label: "Lab open", to: "/lab", show: can("lab.view"), tone: num(c.pending_reports) ? "pending" : "" },
        { n: c.ot_today, label: "OT", to: "/ot", show: can("ot.view") },
        { n: c.bills_today, label: "Bills", to: "/billing", show: financial },
        { n: c.bills_paid_today, label: "Paid", to: "/billing", show: financial, tone: num(c.bills_paid_today) ? "done" : "" },
    ].filter((step) => step.show);
    return (_jsxs(Page, { title: "Today", note: data?.today ? formatDay(data.today) : "", actions: _jsxs(_Fragment, { children: [can("patient.create") && _jsx(Link, { className: "btn primary", to: "/register", children: "Register patient" }), can("opd.create") && _jsx(Link, { className: "btn", to: "/register", children: "Create OPD" }), can("queue.view") && _jsx(Link, { className: "btn", to: "/queue", children: "Open queue" }), can("billing.create") && _jsx(Link, { className: "btn", to: "/billing", children: "Create bill" }), !!moreItems.length && (_jsxs("div", { className: "more-wrap", ref: moreRef, children: [_jsxs("button", { className: "btn", type: "button", "aria-expanded": more, "aria-haspopup": "menu", onClick: () => setMore((open) => !open), children: ["More ", _jsx(Icon, { name: "more", size: 14 })] }), more && (_jsx("div", { className: "more-menu", role: "menu", children: moreItems.map((item) => (_jsx(Link, { role: "menuitem", to: item.to, onClick: () => setMore(false), children: item.label }, item.to))) }))] }))] }), children: [loading && !data && _jsx(Loading, { label: "Opening today's floor\u2026" }), error && !data && _jsx(ErrorState, { message: error }), data && (_jsxs("div", { className: "dash", children: [_jsxs("div", { className: "context-strip", children: [data.hospital?.name && (_jsxs("span", { className: "context-chip", children: [_jsx(Icon, { name: "admissions", size: 14 }), _jsxs("span", { children: [data.hospital.name, data.hospital.city ? ` · ${data.hospital.city}` : ""] })] })), can("health.view") && (_jsxs(Link, { className: `context-chip ${healthTone(data.health_overall)}`, to: "/admin/health", children: [_jsx("span", { className: "dot" }), _jsxs("span", { children: ["System ", healthLabel(data.health_overall), data.health_at ? ` · ${when(data.health_at)}` : ""] })] })), (can("whatsapp.configure") || can("whatsapp.send")) && (can("whatsapp.configure") ? (_jsxs(Link, { className: `context-chip ${data.whatsapp?.state === "connected" ? "ok" : "wait"}`, to: "/admin/integrations", children: [_jsx("span", { className: "dot" }), _jsxs("span", { children: ["WhatsApp ", waLabel(data.whatsapp?.state)] })] })) : (_jsxs("span", { className: "context-chip wait", children: [_jsx("span", { className: "dot" }), _jsxs("span", { children: ["WhatsApp ", waLabel(data.whatsapp?.state)] })] }))), can("backup.view") && data.backup && (_jsxs(Link, { className: "context-chip ok", to: "/admin/backups", children: [_jsx("span", { className: "dot" }), _jsxs("span", { children: ["Backup ", data.backup.status, " \u00B7 ", when(data.backup.started_at), data.backup.cloud_status ? ` · cloud ${data.backup.cloud_status}` : ""] })] })), can("backup.view") && !data.backup && (_jsxs(Link, { className: "context-chip wait", to: "/admin/backups", children: [_jsx("span", { className: "dot" }), _jsx("span", { children: "No backup yet" })] }))] }), (clinical || financial || stock) && (_jsxs("div", { className: "kpi-groups", children: [clinical && (_jsxs("section", { className: "panel", children: [_jsx(Head, { icon: "patients", title: "Clinical", to: can("queue.view") ? "/queue" : "/patients" }), _jsxs("div", { className: "metric-grid", children: [can("patient.view") && _jsx(Metric, { to: "/patients", label: "Patients today", value: num(c.patients_today), hint: versus(c.patients_today, c.patients_yesterday), tone: "normal" }), can("opd.view") && _jsx(Metric, { to: can("queue.view") ? "/queue" : "/patients", label: "OPD today", value: num(c.opd_today), hint: versus(c.opd_today, c.opd_yesterday), tone: "normal" }), can("queue.view") && _jsx(Metric, { to: "/queue", label: "Waiting", value: num(c.queue_waiting), tone: num(c.queue_waiting) ? "pending" : "normal" }), (can("queue.view") || can("consultation.create")) && _jsx(Metric, { to: can("consultation.create") ? "/doctor" : "/queue", label: "In consultation", value: num(c.queue_consulting), tone: num(c.queue_consulting) ? "normal" : "" }), showAdmissions && _jsx(Metric, { to: "/admissions", label: "Admitted now", value: num(c.admissions_active), tone: "normal" }), showBeds && c.beds_configured && _jsx(Metric, { to: "/beds", label: "Beds available", value: num(c.beds_available), hint: `${num(c.beds_occupied)} occupied`, tone: num(c.beds_available) ? "done" : "pending" })] })] })), financial && (_jsxs("section", { className: "panel", children: [_jsx(Head, { icon: "billing", title: "Money", to: "/billing" }), _jsxs("div", { className: "metric-grid", children: [_jsx(Metric, { to: "/billing", label: "Collected today", value: money(c.revenue_paise), hint: versus(c.revenue_paise, c.revenue_yesterday_paise, true), tone: num(c.revenue_paise) ? "done" : "" }), _jsx(Metric, { to: "/billing", label: "Outstanding", value: money(c.outstanding_paise), tone: num(c.outstanding_paise) ? "pending" : "done" }), _jsx(Metric, { to: "/billing", label: "Draft bills", value: num(c.pending_bills), tone: num(c.pending_bills) ? "pending" : "done" }), _jsx(Metric, { to: "/billing", label: "Balances due", value: num(c.bills_due), hint: num(c.bills_partial) ? `${num(c.bills_partial)} partial` : "", tone: num(c.bills_due) ? "pending" : "done" }), num(c.refunds_paise) > 0 && _jsx(Metric, { to: "/billing", label: "Refunds today", value: money(c.refunds_paise), tone: "critical" })] })] })), stock && (_jsxs("section", { className: "panel", children: [_jsx(Head, { icon: "inventory", title: "Stock", to: "/inventory" }), _jsxs("div", { className: "metric-grid", children: [_jsx(Metric, { to: "/inventory/low", label: "Low stock", value: num(c.low_stock), tone: num(c.low_stock) ? "pending" : "done" }), _jsx(Metric, { to: "/inventory/expiring", label: "Expiring soon", value: num(c.expiring), tone: num(c.expiring) ? "pending" : "done" }), _jsx(Metric, { to: "/inventory/expired", label: "Expired", value: num(c.expired), tone: num(c.expired) ? "critical" : "done" }), can("pharmacy.view") && _jsx(Metric, { to: "/pharmacy", label: "To dispense", value: num(c.pharmacy_queue), tone: num(c.pharmacy_queue) ? "pending" : "" })] })] }))] })), !!flow.length && (_jsxs("section", { className: "panel", children: [_jsx(Head, { icon: "opd", title: "Today's flow" }), _jsx("div", { className: "ops-flow", children: flow.map((step) => (_jsxs(Link, { className: `metric ${step.tone || ""}`, to: step.to, children: [_jsx("strong", { children: num(step.n) }), _jsx("span", { children: step.label })] }, step.label))) })] })), _jsxs("div", { className: "board", children: [(can("queue.view_all") || (data.queue || []).length > 0) && (_jsxs("section", { className: "panel span-2", children: [_jsx(Head, { icon: "queue", title: "Live queue", to: "/queue" }), (data.queue || []).length === 0 ? _jsx(Quiet, { text: "No open tokens." }) : (_jsx("div", { className: "table-wrap", children: _jsxs("table", { className: "data", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "Token" }), _jsx("th", { children: "Patient" }), _jsx("th", { children: "Doctor" }), _jsx("th", { children: "Status" }), _jsx("th", {})] }) }), _jsx("tbody", { children: data.queue.map((row) => (_jsxs("tr", { children: [_jsx("td", { children: _jsx("span", { className: "token", children: token(row.token_no) }) }), _jsx("td", { children: _jsx(PatientLink, { id: row.patient_id, name: row.patient_name }) }), _jsx("td", { children: row.doctor_name || "—" }), _jsx("td", { children: _jsx(Status, { value: row.status }) }), _jsx("td", { children: can("consultation.create") && row.encounter_id ? _jsx(Link, { to: `/consult/${row.encounter_id}`, children: "Open" }) : _jsx(Link, { to: "/queue", children: "Queue" }) })] }, row.id))) })] }) }))] })), can("consultation.create") && (!can("queue.view_all") || (data.my_queue || []).length > 0) && (_jsxs("section", { className: "panel", children: [_jsx(Head, { icon: "doctor", title: "Your patients", to: "/doctor" }), (data.my_queue || []).length === 0 ? _jsx(Quiet, { text: "Nothing is assigned to you." }) : (_jsx("ul", { className: "plain-list", children: data.my_queue.map((row) => (_jsxs("li", { children: [_jsxs("span", { children: [_jsx("span", { className: "token", children: token(row.token_no) }), " ", row.patient_name] }), row.encounter_id ? _jsx(Link, { to: `/consult/${row.encounter_id}`, children: "Consult" }) : _jsx(Status, { value: row.status })] }, row.id))) }))] })), can("queue.view_all") && (_jsxs("section", { className: "panel", children: [_jsx(Head, { icon: "doctor", title: "Doctor activity", to: "/queue" }), (data.doctors || []).length === 0 ? _jsx(Quiet, { text: "No doctor has an open token." }) : (_jsx("ul", { className: "plain-list", children: data.doctors.map((row) => (_jsxs("li", { children: [_jsx("span", { children: row.name || "Doctor" }), _jsx("span", { className: num(row.consulting) ? "metric-note normal" : "metric-note pending", children: num(row.consulting) ? `${num(row.consulting)} consulting` : `${num(row.open_n)} open` })] }, row.id))) }))] })), _jsxs("section", { className: `panel ${attention.some((item) => item.tone === "critical") ? "critical" : attention.length ? "pending" : ""}`, children: [_jsx(Head, { icon: "reports", title: "Needs attention" }), attention.length === 0 ? _jsx(Quiet, { text: "Nothing is waiting on this desk." }) : (_jsx("ul", { className: "plain-list", children: attention.map((item) => (_jsxs("li", { children: [_jsx(Link, { to: item.to, children: item.label }), _jsx("span", { className: `count ${item.tone}`, children: num(item.n) })] }, item.label))) }))] }), (showAdmissions || showBeds) && (_jsxs("section", { className: `panel ${showBeds && !c.beds_configured ? "pending" : ""}`, children: [_jsx(Head, { icon: "beds", title: "Admissions and beds", to: showBeds ? "/beds" : "/admissions" }), showAdmissions && (_jsxs("ul", { className: "plain-list", children: [_jsxs("li", { children: [_jsx(Link, { to: "/admissions", children: "Admitted now" }), _jsx("span", { className: "count normal", children: num(c.admissions_active) })] }), _jsxs("li", { children: [_jsx(Link, { to: "/admissions", children: "Admitted today" }), _jsx("span", { className: "count", children: num(c.admissions_today) })] }), _jsxs("li", { children: [_jsx(Link, { to: "/admissions", children: "Discharged today" }), _jsx("span", { className: "count done", children: num(c.discharges_today) })] })] })), showBeds && !c.beds_configured && (_jsxs("div", { className: "bed-alert", children: [_jsx("strong", { children: "Bed master not configured" }), _jsx("p", { children: "Hospital beds are not on file. Sample install beds are not counted as capacity." }), can("master.manage") && _jsx(Link, { className: "btn small primary", to: "/admin/master?section=beds", children: "Configure beds" })] })), showBeds && c.beds_configured && (_jsxs("ul", { className: "plain-list", children: [_jsxs("li", { children: [_jsx(Link, { to: "/beds", children: "Available" }), _jsx("span", { className: "count done", children: num(c.beds_available) })] }), _jsxs("li", { children: [_jsx(Link, { to: "/beds", children: "Occupied" }), _jsx("span", { className: "count pending", children: num(c.beds_occupied) })] }), _jsxs("li", { children: [_jsx(Link, { to: "/beds", children: "Blocked" }), _jsx("span", { className: "count", children: num(c.beds_blocked) })] }), (data.wards || []).map((ward) => (_jsxs("li", { children: [_jsx(Link, { to: "/beds", children: ward.ward }), _jsxs("span", { className: "muted", children: [num(ward.occupied), " / ", num(ward.total)] })] }, ward.ward)))] }))] })), can("ot.view") && (_jsxs("section", { className: "panel", children: [_jsx(Head, { icon: "ot", title: "Operation theatre", to: "/ot" }), (data.ot || []).length === 0 ? _jsx(Quiet, { text: "No OT cases today." }) : (_jsx("ul", { className: "plain-list", children: data.ot.map((row) => (_jsxs("li", { children: [_jsxs(Link, { to: `/ot/${row.id}`, children: [row.procedure_name || "OT case", _jsxs("small", { children: [row.patient_name, row.surgeon_name ? ` · ${row.surgeon_name}` : ""] })] }), _jsx(Status, { value: row.status })] }, row.id))) }))] })), can("lab.view") && (_jsxs("section", { className: "panel", children: [_jsx(Head, { icon: "lab", title: "Laboratory", to: "/lab" }), (data.lab || []).length === 0 ? _jsx(Quiet, { text: "No open lab orders." }) : (_jsx("ul", { className: "plain-list", children: data.lab.map((row) => (_jsxs("li", { children: [_jsxs(Link, { to: "/lab", children: [row.test_name || "Lab order", _jsx("small", { children: row.patient_name })] }), _jsx(Status, { value: row.status })] }, row.id))) }))] })), financial && (_jsxs("section", { className: "panel", children: [_jsx(Head, { icon: "billing", title: "Billing", to: "/billing" }), (data.bills || []).length === 0 ? _jsx(Quiet, { text: "No bills yet." }) : (_jsx("div", { className: "table-wrap", children: _jsxs("table", { className: "data", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "Bill" }), _jsx("th", { children: "Patient" }), _jsx("th", { children: "Status" }), _jsx("th", { className: "num", children: "Due" })] }) }), _jsx("tbody", { children: data.bills.map((row) => (_jsxs("tr", { children: [_jsx("td", { children: _jsx(Link, { to: `/billing/${row.id}`, children: row.number || "Draft" }) }), _jsx("td", { children: row.patient_name }), _jsx("td", { children: _jsx(Status, { value: row.status === "DRAFT" ? "DRAFT" : row.payment_status || row.status }) }), _jsx("td", { className: "num", children: money(row.due_paise) })] }, row.id))) })] }) }))] })), (can("pharmacy.view") || stock) && (_jsxs("section", { className: "panel", children: [_jsx(Head, { icon: "pharmacy", title: "Pharmacy and inventory", to: can("pharmacy.view") ? "/pharmacy" : "/inventory" }), _jsxs("ul", { className: "plain-list", children: [can("pharmacy.view") && _jsxs("li", { children: [_jsx(Link, { to: "/pharmacy", children: "Waiting for pharmacy" }), _jsx("span", { className: `count ${num(c.queue_pharmacy) ? "pending" : ""}`, children: num(c.queue_pharmacy) })] }), can("pharmacy.view") && _jsxs("li", { children: [_jsx(Link, { to: "/pharmacy", children: "Prescriptions to dispense" }), _jsx("span", { className: `count ${num(c.pharmacy_queue) ? "pending" : ""}`, children: num(c.pharmacy_queue) })] }), stock && _jsxs("li", { children: [_jsx(Link, { to: "/inventory/movements", children: "Issues today" }), _jsx("span", { className: "count", children: num(c.pharmacy_issues_today) })] }), stock && _jsxs("li", { children: [_jsx(Link, { to: "/inventory/low", children: "Low stock" }), _jsx("span", { className: `count ${num(c.low_stock) ? "pending" : "done"}`, children: num(c.low_stock) })] }), stock && _jsxs("li", { children: [_jsx(Link, { to: "/inventory/expiring", children: "Expiring soon" }), _jsx("span", { className: `count ${num(c.expiring) ? "pending" : "done"}`, children: num(c.expiring) })] }), stock && _jsxs("li", { children: [_jsx(Link, { to: "/inventory/expired", children: "Expired" }), _jsx("span", { className: `count ${num(c.expired) ? "critical" : "done"}`, children: num(c.expired) })] })] }), stock && !!(data.stock?.low || []).length && _jsxs("p", { className: "quiet", children: ["Low: ", data.stock.low.map((row) => row.name).filter(Boolean).join(", ")] }), stock && !!(data.stock?.expiring || []).length && _jsxs("p", { className: "quiet", children: ["Expiring: ", data.stock.expiring.map((row) => row.name).filter(Boolean).join(", ")] }), stock && !!(data.stock?.expired || []).length && _jsxs("p", { className: "quiet", children: ["Expired: ", data.stock.expired.map((row) => row.name).filter(Boolean).join(", ")] })] })), can("patient.view") && (_jsxs("section", { className: "panel", children: [_jsx(Head, { icon: "patients", title: "Recent patients", to: "/patients" }), (data.patients || []).length === 0 ? _jsx(Quiet, { text: "No visits yet." }) : (_jsx("ul", { className: "plain-list", children: data.patients.map((row) => (_jsxs("li", { children: [_jsx(PatientLink, { id: row.id, name: row.name }), _jsx("span", { className: "muted", children: row.doctor_name || when(row.arrived_at) })] }, row.encounter_id || row.id))) }))] })), can("document.view") && (_jsxs("section", { className: "panel", children: [_jsx(Head, { icon: "documents", title: "Documents", to: "/documents" }), _jsxs("p", { className: "quiet", children: [num(c.documents_today), " uploaded today."] }), (data.documents || []).length === 0 ? _jsx(Quiet, { text: "No documents uploaded." }) : (_jsx("ul", { className: "plain-list", children: data.documents.map((row) => (_jsxs("li", { children: [_jsxs("span", { children: [row.title || row.document_type, _jsx("small", { children: row.patient_name || "Unlinked" })] }), _jsx("span", { className: "muted", children: when(row.uploaded_at) })] }, row.id))) }))] })), can("audit.view") && (_jsxs("section", { className: "panel", children: [_jsx(Head, { icon: "audit", title: "Activity", to: "/admin/audit" }), (data.activity || []).length === 0 ? _jsx(Quiet, { text: "No activity recorded." }) : (_jsx("ul", { className: "plain-list", children: data.activity.map((row, index) => (_jsxs("li", { children: [_jsxs("span", { children: [actionLabel(row.action), _jsx("small", { children: row.username || row.entity })] }), _jsx("span", { className: "muted", children: when(row.at) })] }, `${row.at}-${row.action}-${index}`))) }))] })), (can("whatsapp.configure") || can("whatsapp.send")) && (_jsxs("section", { className: "panel", children: [_jsx(Head, { icon: "whatsapp", title: "WhatsApp", to: can("whatsapp.configure") ? "/admin/integrations" : undefined }), _jsx("p", { className: "quiet", children: data.whatsapp?.state === "not_configured" ? "Not connected. OpenWA is not configured." : `WhatsApp ${waLabel(data.whatsapp?.state)}.` }), _jsxs("ul", { className: "plain-list", children: [_jsxs("li", { children: [_jsx("span", { children: "Queued" }), _jsx("span", { className: "count", children: num(c.whatsapp_queued) })] }), _jsxs("li", { children: [_jsx("span", { children: "Sent today" }), _jsx("span", { className: "count done", children: num(c.whatsapp_sent_today) })] }), _jsxs("li", { children: [_jsx("span", { children: "Failed today" }), _jsx("span", { className: `count ${num(c.whatsapp_failed_today) ? "critical" : ""}`, children: num(c.whatsapp_failed_today) })] })] })] })), can("backup.view") && (_jsxs("section", { className: "panel", children: [_jsx(Head, { icon: "backup", title: "Backup", to: "/admin/backups" }), data.backup ? (_jsxs("ul", { className: "plain-list", children: [_jsxs("li", { children: [_jsx("span", { children: "Status" }), _jsx(Status, { value: data.backup.status })] }), _jsxs("li", { children: [_jsx("span", { children: "Started" }), _jsx("span", { className: "muted", children: when(data.backup.started_at) })] }), _jsxs("li", { children: [_jsx("span", { children: "Cloud" }), _jsx("span", { className: "muted", children: data.backup.cloud_status || "—" })] })] })) : _jsx(Quiet, { text: "No backup yet." })] })), can("health.view") && (_jsxs("section", { className: "panel", children: [_jsx(Head, { icon: "system", title: "System health", to: "/admin/health" }), _jsxs("p", { className: `quiet health-line ${healthTone(data.health_overall)}`, children: [_jsx("span", { className: "dot" }), " ", healthLabel(data.health_overall), data.health_at ? ` · checked ${when(data.health_at)}` : ""] })] }))] })] }))] }));
}
