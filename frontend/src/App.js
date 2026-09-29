import { jsx as _jsx, Fragment as _Fragment, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useRef, useState } from "react";
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { api, fileUrl, setWorkstation } from "./api";
import { useData } from "./ui";
import { Admissions, Beds, OtPage } from "./pages/wards";
import { Billing, InvoicePage } from "./pages/money";
import { Consult, LabPage, Pharmacy } from "./pages/clinical";
import { Documents, Leads, PatientPage, Patients, QueuePage, Register } from "./pages/desk";
import { Home } from "./pages/today";
import { AuditPage, Backups, Branding, HealthPage, HelpPage, Integrations, Reports, SetupPage, StaffPage } from "./pages/admin";
import { Inventory } from "./pages/inventory";
import { MasterPage } from "./pages/masters";
import { useApp } from "./store";
import { Field } from "./ui";
import { GuidedDemo, SpotlightTour } from "./tour";
import { PairPage } from "./scanner";
import { Icon } from "./icons";
const NAV = [
    { group: "Primary", items: [
            { to: "/", label: "Today", icon: "dashboard" },
        ] },
    { group: "Clinical", items: [
            { to: "/patients", label: "Patients", icon: "group", perm: "patient.view" },
            { to: "/register", label: "OPD", icon: "stethoscope", perm: "patient.create" },
            { to: "/queue", label: "Queue", icon: "low_priority", perm: "queue.view" },
            { to: "/doctor", label: "Doctor Queue", icon: "person_apron", perm: "consultation.create" },
            { to: "/admissions", label: "Admissions", icon: "hotel", perm: "admission.view" },
            { to: "/beds", label: "Beds", icon: "single_bed", perm: "bed.view" },
            { to: "/ot", label: "OT", icon: "medical_services", perm: "ot.view" },
            { to: "/lab", label: "Lab", icon: "biotech", perm: "lab.view" },
        ] },
    { group: "Operations", items: [
            { to: "/billing", label: "Billing", icon: "receipt_long", perm: "billing.view" },
            { to: "/inventory", label: "Inventory", icon: "inventory_2", perm: "inventory.view" },
            { to: "/pharmacy", label: "Pharmacy", icon: "medication", perm: "pharmacy.view" },
            { to: "/documents", label: "Documents", icon: "description", perm: "document.view" },
        ] },
    { group: "Admin", items: [
            { to: "/admin/master", label: "Master Data", icon: "dataset", perm: "master.manage" },
            { to: "/admin/staff", label: "Users & Roles", icon: "manage_accounts", perm: "user.manage" },
            { to: "/admin/integrations", label: "WhatsApp", icon: "chat", perm: "whatsapp.configure" },
            { to: "/admin/health", label: "System", icon: "dns", perm: "health.view" },
            { to: "/setup", label: "Settings", icon: "settings", perm: "config.manage" },
            { to: "/admin/backups", label: "Backup", icon: "backup", perm: "backup.view" },
            { to: "/reports", label: "Reports", icon: "summarize", perm: "report.view" },
            { to: "/admin/audit", label: "Audit", icon: "policy", perm: "audit.view" },
            { to: "/admin/branding", label: "Branding", icon: "palette", perm: "config.manage" },
            { to: "/leads", label: "Website leads", icon: "campaign", perm: "leads.view" },
        ] },
];
const CRUMBS = {
    "/": "Today",
    "/register": "OPD",
    "/patients": "Patients",
    "/queue": "Queue",
    "/doctor": "Doctor queue",
    "/pharmacy": "Pharmacy",
    "/inventory": "Inventory",
    "/lab": "Lab",
    "/billing": "Billing",
    "/beds": "Beds",
    "/admissions": "Admissions",
    "/ot": "OT",
    "/documents": "Documents",
    "/leads": "Website leads",
    "/reports": "Reports",
    "/admin/master": "Master data",
    "/admin/staff": "Users & roles",
    "/admin/branding": "Branding",
    "/admin/integrations": "WhatsApp",
    "/admin/health": "System health",
    "/admin/backups": "Backup",
    "/admin/audit": "Audit",
    "/setup": "Settings",
    "/help": "Help & training",
};
function crumbsFor(path) {
    if (CRUMBS[path])
        return [{ to: path, label: CRUMBS[path] }];
    if (path.startsWith("/patients/"))
        return [{ to: "/patients", label: "Patients" }, { to: path, label: "Record" }];
    if (path.startsWith("/billing/"))
        return [{ to: "/billing", label: "Billing" }, { to: path, label: "Bill" }];
    if (path.startsWith("/consult/"))
        return [{ to: "/doctor", label: "Doctor queue" }, { to: path, label: "Consultation" }];
    if (path.startsWith("/admissions/"))
        return [{ to: "/admissions", label: "Admissions" }, { to: path, label: "Admission" }];
    if (path.startsWith("/ot/"))
        return [{ to: "/ot", label: "OT" }, { to: path, label: "Case" }];
    if (path.startsWith("/inventory/"))
        return [{ to: "/inventory", label: "Inventory" }, { to: path, label: "Stock" }];
    return [{ to: path, label: "Desk" }];
}
function Guard({ perm, children }) {
    const allowed = useApp((s) => s.can(perm));
    if (!allowed)
        return _jsx("p", { className: "muted", children: "You do not have permission for this desk." });
    return _jsx(_Fragment, { children: children });
}
export default function App() {
    const token = useApp((s) => s.token);
    const user = useApp((s) => s.user);
    const setUser = useApp((s) => s.setUser);
    const clear = useApp((s) => s.clear);
    const bump = useApp((s) => s.bump);
    const toasts = useApp((s) => s.toasts);
    const dismiss = useApp((s) => s.dismiss);
    const can = useApp((s) => s.can);
    const [menu, setMenu] = useState(false);
    const [compact, setCompact] = useState(() => localStorage.getItem("aipf-rail") === "compact");
    useEffect(() => {
        if (!token)
            return;
        api("/api/auth/me").then(setUser).catch(() => clear());
    }, [token, setUser, clear]);
    useEffect(() => {
        const denied = () => clear();
        const forbidden = (event) => {
            const message = event.detail || "You do not have permission for this action.";
            useApp.getState().toast(String(message), "warn");
        };
        window.addEventListener("aipf-unauthorized", denied);
        window.addEventListener("aipf-forbidden", forbidden);
        return () => {
            window.removeEventListener("aipf-unauthorized", denied);
            window.removeEventListener("aipf-forbidden", forbidden);
        };
    }, [clear]);
    const navigate = useNavigate();
    useEffect(() => {
        const onKey = (event) => {
            const target = event.target;
            const typing = !!target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT" || target.isContentEditable);
            if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
                event.preventDefault();
                document.getElementById("global-search")?.focus();
                return;
            }
            if (typing)
                return;
            if (event.key === "/") {
                event.preventDefault();
                document.getElementById("global-search")?.focus();
            }
            else if (event.key.toLowerCase() === "n" && can("patient.create")) {
                navigate("/register");
            }
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [can, navigate]);
    const bumpRef = useRef(bump);
    bumpRef.current = bump;
    useEffect(() => {
        if (!token)
            return;
        let source = null;
        let cancelled = false;
        let retry;
        const connect = () => {
            api("/api/auth/stream-ticket", { method: "POST", body: "{}" }).then((ticket) => {
                if (cancelled)
                    return;
                source = new EventSource(`/api/events?token=${encodeURIComponent(ticket.token)}`);
                source.onmessage = (message) => {
                    let detail = null;
                    try {
                        detail = JSON.parse(message.data);
                    }
                    catch {
                        detail = null;
                    }
                    if (detail?.event)
                        window.dispatchEvent(new CustomEvent("aipf-live", { detail }));
                    bumpRef.current();
                };
                source.onerror = () => {
                    source?.close();
                    source = null;
                    if (!cancelled)
                        retry = window.setTimeout(connect, 15000);
                };
            }).catch((err) => {
                useApp.getState().toast(err.message || "Live updates could not start.", "bad");
                if (!cancelled)
                    retry = window.setTimeout(connect, 15000);
            });
        };
        connect();
        return () => {
            cancelled = true;
            if (retry)
                window.clearTimeout(retry);
            source?.close();
        };
    }, [token]);
    if (token && !user) {
        return _jsx("div", { className: "login-main", style: { minHeight: "100vh" }, children: _jsx("p", { className: "muted", children: "Opening the local hospital server\u2026" }) });
    }
    if (!user)
        return _jsx(Login, {});
    return (_jsxs("div", { className: `${menu ? "app rail-open" : "app"}${compact ? " rail-compact" : ""}`, children: [_jsx("a", { className: "skip", href: "#stage", children: "Skip to content" }), _jsxs("aside", { className: "rail", children: [_jsx("nav", { className: "nav", "aria-label": "Hospital desks", children: NAV.map((group) => {
                            const items = group.items.filter((item) => !item.perm || can(item.perm));
                            if (!items.length)
                                return null;
                            return (_jsxs("div", { children: [_jsx("div", { className: "nav-label", children: group.group }), items.map((item) => (_jsxs(NavLink, { to: item.to, end: item.to === "/", "data-tour": item.to, title: compact ? item.label : undefined, onClick: () => setMenu(false), children: [_jsx(Icon, { name: item.icon }), _jsx("span", { className: "label", children: item.label })] }, item.to)))] }, group.group));
                        }) }), _jsxs("div", { className: "rail-foot", children: [_jsxs(NavLink, { to: "/help", title: compact ? "Help & Docs" : undefined, onClick: () => setMenu(false), children: [_jsx(Icon, { name: "help" }), _jsx("span", { children: "Help & Docs" })] }), _jsx("button", { className: "rail-toggle", type: "button", "aria-label": compact ? "Expand sidebar" : "Collapse sidebar", onClick: () => {
                                    const next = !compact;
                                    setCompact(next);
                                    localStorage.setItem("aipf-rail", next ? "compact" : "full");
                                }, children: _jsx(Icon, { name: compact ? "left_panel_open" : "left_panel_close" }) })] })] }), menu && _jsx("button", { className: "rail-backdrop", type: "button", "aria-label": "Close navigation", onClick: () => setMenu(false) }), _jsxs("div", { className: "work", children: [_jsx(Topbar, { onMenu: () => setMenu((open) => !open) }), _jsx("main", { className: "stage", id: "stage", children: _jsxs(Routes, { children: [_jsx(Route, { path: "/", element: _jsx(Home, {}) }), _jsx(Route, { path: "/register", element: _jsx(Guard, { perm: "patient.create", children: _jsx(Register, {}) }) }), _jsx(Route, { path: "/patients", element: _jsx(Guard, { perm: "patient.view", children: _jsx(Patients, {}) }) }), _jsx(Route, { path: "/patients/:id", element: _jsx(Guard, { perm: "patient.view", children: _jsx(PatientPage, {}) }) }), _jsx(Route, { path: "/queue", element: _jsx(Guard, { perm: "queue.view", children: _jsx(QueuePage, {}) }) }), _jsx(Route, { path: "/doctor", element: _jsx(Guard, { perm: "consultation.create", children: _jsx(QueuePage, { mine: true }) }) }), _jsx(Route, { path: "/consult/:id", element: _jsx(Guard, { perm: "consultation.create", children: _jsx(Consult, {}) }) }), _jsx(Route, { path: "/pharmacy", element: _jsx(Guard, { perm: "pharmacy.view", children: _jsx(Pharmacy, {}) }) }), _jsx(Route, { path: "/inventory", element: _jsx(Guard, { perm: "inventory.view", children: _jsx(Inventory, {}) }) }), _jsx(Route, { path: "/inventory/:view", element: _jsx(Guard, { perm: "inventory.view", children: _jsx(Inventory, {}) }) }), _jsx(Route, { path: "/lab", element: _jsx(Guard, { perm: "lab.view", children: _jsx(LabPage, {}) }) }), _jsx(Route, { path: "/billing", element: _jsx(Guard, { perm: "billing.view", children: _jsx(Billing, {}) }) }), _jsx(Route, { path: "/billing/:id", element: _jsx(Guard, { perm: "billing.view", children: _jsx(InvoicePage, {}) }) }), _jsx(Route, { path: "/beds", element: _jsx(Guard, { perm: "bed.view", children: _jsx(Beds, {}) }) }), _jsx(Route, { path: "/admissions", element: _jsx(Guard, { perm: "admission.view", children: _jsx(Admissions, {}) }) }), _jsx(Route, { path: "/admissions/:id", element: _jsx(Guard, { perm: "admission.view", children: _jsx(Admissions, {}) }) }), _jsx(Route, { path: "/ot", element: _jsx(Guard, { perm: "ot.view", children: _jsx(OtPage, {}) }) }), _jsx(Route, { path: "/ot/:id", element: _jsx(Guard, { perm: "ot.view", children: _jsx(OtPage, {}) }) }), _jsx(Route, { path: "/documents", element: _jsx(Guard, { perm: "document.view", children: _jsx(Documents, {}) }) }), _jsx(Route, { path: "/leads", element: _jsx(Guard, { perm: "leads.view", children: _jsx(Leads, {}) }) }), _jsx(Route, { path: "/reports", element: _jsx(Guard, { perm: "report.view", children: _jsx(Reports, {}) }) }), _jsx(Route, { path: "/admin/master", element: _jsx(Guard, { perm: "master.manage", children: _jsx(MasterPage, {}) }) }), _jsx(Route, { path: "/admin/staff", element: _jsx(Guard, { perm: "user.manage", children: _jsx(StaffPage, {}) }) }), _jsx(Route, { path: "/admin/branding", element: _jsx(Guard, { perm: "config.manage", children: _jsx(Branding, {}) }) }), _jsx(Route, { path: "/admin/integrations", element: _jsx(Guard, { perm: "whatsapp.configure", children: _jsx(Integrations, {}) }) }), _jsx(Route, { path: "/admin/health", element: _jsx(Guard, { perm: "health.view", children: _jsx(HealthPage, {}) }) }), _jsx(Route, { path: "/admin/backups", element: _jsx(Guard, { perm: "backup.view", children: _jsx(Backups, {}) }) }), _jsx(Route, { path: "/admin/audit", element: _jsx(Guard, { perm: "audit.view", children: _jsx(AuditPage, {}) }) }), _jsx(Route, { path: "/setup", element: _jsx(Guard, { perm: "config.manage", children: _jsx(SetupPage, {}) }) }), _jsx(Route, { path: "/help", element: _jsx(HelpPage, {}) }), _jsx(Route, { path: "/pair/:token", element: _jsx(PairPage, {}) }), _jsx(Route, { path: "*", element: _jsx(Navigate, { to: "/", replace: true }) })] }) })] }), _jsx(BottomNav, {}), _jsx(SpotlightTour, {}), _jsx(GuidedDemo, {}), _jsx("div", { className: "toasts", "aria-live": "polite", children: toasts.map((t) => (_jsxs("div", { className: `toast ${t.tone || ""}`, role: "status", children: [_jsx("span", { children: t.text }), _jsx("button", { type: "button", "aria-label": "Dismiss notification", onClick: () => dismiss(t.id), children: "\u00D7" })] }, t.id))) })] }));
}
function Topbar({ onMenu }) {
    const user = useApp((s) => s.user);
    const clear = useApp((s) => s.clear);
    const navigate = useNavigate();
    const location = useLocation();
    const crumb = crumbsFor(location.pathname)[0];
    const [q, setQ] = useState("");
    const [hits, setHits] = useState(null);
    useEffect(() => {
        if (q.trim().length < 2) {
            setHits(null);
            return;
        }
        const id = window.setTimeout(() => {
            api(`/api/search?q=${encodeURIComponent(q)}`).then(setHits).catch(() => setHits(null));
        }, 180);
        return () => window.clearTimeout(id);
    }, [q]);
    return (_jsxs("header", { className: "topbar", children: [_jsxs("div", { className: "top-brand", children: [_jsx("button", { className: "btn small menu-btn", type: "button", onClick: onMenu, "aria-label": "Open navigation", children: "Menu" }), _jsx("img", { src: "/logo.jpg", alt: "" }), _jsxs("div", { className: "crumb-line", children: [_jsx("strong", { children: "AIPF Mission Hospital" }), _jsx("span", { children: crumb?.label || "Clinical Operations Desk" })] })] }), _jsxs("div", { className: "search", children: [_jsx(Icon, { name: "search", className: "search-icon", size: 16 }), _jsx("label", { className: "skip", htmlFor: "global-search", children: "Search" }), _jsx("input", { id: "global-search", type: "search", placeholder: "Search Patient ID, Name, Phone, OPD ID, Bill ID...", value: q, "aria-label": "Search by patient ID, name, phone, OPD, admission, bill, prescription, or document", onChange: (e) => setQ(e.target.value), onKeyDown: (e) => { if (e.key === "Escape") {
                            setQ("");
                            setHits(null);
                        } } }), _jsx("kbd", { children: "Ctrl+K" }), hits && (_jsxs("div", { className: "search-pop", role: "listbox", children: [hits.patients?.map((p) => (_jsxs("a", { href: `/patients/${p.id}`, onClick: (e) => { e.preventDefault(); setQ(""); setHits(null); navigate(`/patients/${p.id}`); }, children: ["Patient ", p.name, " ", _jsxs("small", { children: [p.id, " \u00B7 ", p.primary_phone] })] }, p.id))), hits.encounters?.map((row) => (_jsxs("a", { href: `/consult/${row.id}`, onClick: (e) => { e.preventDefault(); setQ(""); setHits(null); navigate(`/consult/${row.id}`); }, children: ["OPD ", row.id, " ", _jsxs("small", { children: [row.patient_id, " \u00B7 ", row.status] })] }, row.id))), hits.prescriptions?.map((row) => (_jsxs("a", { href: row.encounter_id ? `/consult/${row.encounter_id}` : `/patients/${row.patient_id}`, onClick: (e) => { e.preventDefault(); setQ(""); setHits(null); navigate(row.encounter_id ? `/consult/${row.encounter_id}` : `/patients/${row.patient_id}`); }, children: ["Prescription ", row.id, " ", _jsxs("small", { children: [row.patient_id, " \u00B7 ", row.status] })] }, row.id))), hits.admissions?.map((row) => (_jsxs("a", { href: `/admissions/${row.id}`, onClick: (e) => { e.preventDefault(); setQ(""); setHits(null); navigate(`/admissions/${row.id}`); }, children: ["Admission ", row.id, " ", _jsxs("small", { children: [row.patient_id, " \u00B7 ", row.status] })] }, row.id))), hits.invoices?.map((p) => (_jsxs("a", { href: `/billing/${p.id}`, onClick: (e) => { e.preventDefault(); setQ(""); setHits(null); navigate(`/billing/${p.id}`); }, children: ["Bill ", p.number, " ", _jsxs("small", { children: [p.patient_id, " \u00B7 ", p.payment_status] })] }, p.id))), hits.documents?.map((d) => (_jsxs("a", { href: fileUrl(`/api/documents/${d.id}/file`), target: "_blank", rel: "noreferrer", onClick: () => { setQ(""); setHits(null); }, children: ["Document ", d.document_type, " ", _jsxs("small", { children: [d.patient_id, " \u00B7 ", d.title || d.filename] })] }, d.id))), hits.products?.map((p) => (_jsxs("a", { href: "/inventory", onClick: (e) => { e.preventDefault(); setQ(""); setHits(null); navigate("/inventory"); }, children: [p.name, " ", p.strength, " ", _jsx("small", { children: p.barcode })] }, p.id))), !hits.patients?.length && !hits.invoices?.length && !hits.products?.length && !hits.encounters?.length && !hits.admissions?.length && !hits.documents?.length && !hits.prescriptions?.length && _jsx("div", { className: "hit muted", children: "No match" })] }))] }), _jsxs("div", { className: "top-meta", children: [_jsx(WhatsAppChip, {}), _jsx(Bell, {}), _jsx(UserMenu, { user: user, onSignOut: () => { api("/api/auth/logout", { method: "POST" }).catch(() => undefined); clear(); } })] })] }));
}
function BottomNav() {
    const can = useApp((s) => s.can);
    const items = [
        { to: "/", label: "Today" },
        { to: "/patients", label: "Patients", perm: "patient.view" },
        { to: "/queue", label: "Queue", perm: "queue.view" },
        { to: "/billing", label: "Billing", perm: "billing.view" },
    ].filter((item) => !item.perm || can(item.perm));
    return (_jsxs("nav", { className: "bottom-nav", "aria-label": "Main", children: [items.map((item) => (_jsx(NavLink, { to: item.to, end: item.to === "/", children: item.label }, item.to))), _jsx("button", { type: "button", onClick: () => document.querySelector(".menu-btn")?.click(), children: "More" })] }));
}
function initials(name) {
    const parts = (name || "").trim().split(/\s+/).filter(Boolean);
    return ((parts[0]?.[0] || "") + (parts[1]?.[0] || "")).toUpperCase() || "A";
}
function WhatsAppChip() {
    const configure = useApp((s) => s.can("whatsapp.configure"));
    const send = useApp((s) => s.can("whatsapp.send"));
    const [state, setState] = useState("checking");
    useEffect(() => {
        if (!configure)
            return;
        api("/api/integrations/whatsapp/test", { method: "POST", body: "{}" })
            .then((row) => setState(row.state === "connected" || row.ok ? "connected" : "offline"))
            .catch(() => setState("offline"));
    }, [configure]);
    if (!configure && !send)
        return null;
    const label = configure ? (state === "connected" ? "Connected" : state === "offline" ? "Not connected" : "Checking") : "Send only";
    return (_jsxs(NavLink, { className: `wa-chip ${configure ? state : ""}`, to: configure ? "/admin/integrations" : "/help", title: `WhatsApp ${label}`, children: [_jsx("span", { className: `wa-dot ${configure ? state : ""}` }), _jsxs("span", { children: ["WhatsApp ", label] })] }));
}
function UserMenu({ user, onSignOut }) {
    const [open, setOpen] = useState(false);
    const name = [user?.title, user?.full_name].filter(Boolean).join(" ");
    return (_jsxs("div", { className: "user-wrap", children: [_jsxs("button", { className: "user-chip", type: "button", "aria-expanded": open, onClick: () => setOpen((v) => !v), children: [_jsxs("span", { children: [_jsx("strong", { children: name || "Staff" }), _jsx("small", { children: user?.roles?.[0] || "Staff" })] }), _jsx("span", { className: "avatar", children: initials(user?.full_name) })] }), open && (_jsx("div", { className: "user-pop", children: _jsx("button", { type: "button", onClick: onSignOut, children: "Sign out" }) }))] }));
}
function Bell() {
    const { data } = useData("/api/notifications/mine");
    const [open, setOpen] = useState(false);
    const navigate = useNavigate();
    const notes = (data?.items || []).filter((n) => n.status === "UNREAD").slice(0, 8);
    return (_jsxs("div", { className: "bell-wrap", children: [_jsxs("button", { className: "icon-btn", type: "button", "aria-expanded": open, "aria-label": "Notifications", onClick: () => setOpen((v) => !v), children: [_jsx(Icon, { name: "notifications", size: 20 }), notes.length > 0 && _jsx("span", { className: "badge", children: notes.length })] }), open && (_jsxs("div", { className: "note-pop", role: "menu", children: [notes.length === 0 && _jsx("div", { className: "hit muted", children: "No notes waiting." }), notes.map((note) => (_jsxs("button", { className: "note", type: "button", onClick: () => {
                            api(`/api/notifications/${note.id}/read`, { method: "POST" }).catch(() => undefined);
                            setOpen(false);
                            if (note.entity_type === "ot" && note.entity_id)
                                navigate(`/ot/${note.entity_id}`);
                            else if (note.entity_type === "patient" && note.entity_id)
                                navigate(`/patients/${note.entity_id}`);
                        }, children: [_jsx("strong", { children: note.message_type || "Note" }), _jsx("div", { className: "muted", children: note.body || "Open the related record." })] }, note.id)))] }))] }));
}
function useHealth() {
    const tick = useApp((s) => s.tick);
    const [data, setData] = useState(null);
    useEffect(() => {
        api("/api/dashboard").then(setData).catch(() => undefined);
    }, [tick]);
    return { data };
}
function Login() {
    const setSession = useApp((s) => s.setSession);
    const toast = useApp((s) => s.toast);
    const dismiss = useApp((s) => s.dismiss);
    const [brand, setBrand] = useState(null);
    const [accounts, setAccounts] = useState([]);
    const [username, setUsername] = useState("reception");
    const [password, setPassword] = useState("");
    const [desk, setDesk] = useState(sessionStorage.getItem("aipf-workstation") || "Reception");
    const [busy, setBusy] = useState(false);
    const toasts = useApp((s) => s.toasts);
    useEffect(() => {
        fetch("/api/public/branding").then((r) => r.json()).then((j) => setBrand(j.data)).catch(() => undefined);
        fetch("/api/public/accounts").then((r) => r.json()).then((j) => setAccounts(j.data?.items || [])).catch(() => undefined);
    }, []);
    async function submit(e) {
        e.preventDefault();
        setBusy(true);
        setWorkstation(desk);
        try {
            const data = await api("/api/auth/login", {
                method: "POST",
                body: JSON.stringify({ username, password, workstation: desk }),
            });
            setSession(data.token, data.user);
        }
        catch (err) {
            toast(err.message, "bad");
        }
        finally {
            setBusy(false);
        }
    }
    return (_jsx("div", { className: "login", style: { backgroundImage: "url(/hospital.png)" }, children: _jsxs("section", { className: "login-main", children: [_jsxs("form", { className: "login-card", onSubmit: submit, children: [_jsx("img", { src: "/logo.jpg", alt: "", width: 56, height: 56, style: { borderRadius: "50%" } }), _jsx("h2", { children: "Welcome back" }), _jsxs("p", { className: "muted", children: [brand?.name || "AIPF Mission Hospital", ". The workstation is written into the audit log."] }), _jsxs("div", { className: "grid-form", style: { marginTop: 12 }, children: [_jsx(Field, { label: "Workstation", className: "span-2", children: _jsx("input", { value: desk, onChange: (e) => setDesk(e.target.value) }) }), _jsx(Field, { label: "Username", required: true, children: _jsx("input", { value: username, onChange: (e) => setUsername(e.target.value), autoFocus: true }) }), _jsx(Field, { label: "Password", required: true, children: _jsx("input", { type: "password", value: password, onChange: (e) => setPassword(e.target.value) }) })] }), _jsx("div", { style: { marginTop: 12 }, children: _jsx("button", { className: "btn primary", disabled: busy, children: busy ? "Checking…" : "Sign in" }) })] }), accounts.length > 0 && (_jsxs("table", { className: "accounts", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "Username" }), _jsx("th", { children: "Role" })] }) }), _jsx("tbody", { children: accounts.map((a) => (_jsxs("tr", { onClick: () => setUsername(a.username), style: { cursor: "pointer" }, children: [_jsx("td", { children: a.username }), _jsx("td", { children: a.role })] }, a.username))) })] })), _jsx("p", { className: "muted", children: "Passwords are not shown here. Change them under Users & roles after the first sign-in." }), _jsx("div", { className: "toasts", children: toasts.map((t) => (_jsxs("div", { className: `toast ${t.tone || ""}`, role: "status", children: [_jsx("span", { children: t.text }), _jsx("button", { type: "button", "aria-label": "Dismiss notification", onClick: () => dismiss(t.id), children: "\u00D7" })] }, t.id))) })] }) }));
}
