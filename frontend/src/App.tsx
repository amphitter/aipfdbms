import { useEffect, useRef, useState, type ReactNode } from "react";
import { NavLink, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { api, fileUrl, setWorkstation, type User } from "./api";
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

type NavItem = { to: string; label: string; icon: string; perm?: string };
type NavGroup = { group: string; items: NavItem[] };

const NAV: NavGroup[] = [
  { group: "Primary", items: [
    { to: "/", label: "Today", icon: "dashboard" },
  ]},
  { group: "Clinical", items: [
    { to: "/patients", label: "Patients", icon: "group", perm: "patient.view" },
    { to: "/register", label: "OPD", icon: "stethoscope", perm: "patient.create" },
    { to: "/queue", label: "Queue", icon: "low_priority", perm: "queue.view" },
    { to: "/doctor", label: "Doctor Queue", icon: "person_apron", perm: "consultation.create" },
    { to: "/admissions", label: "Admissions", icon: "hotel", perm: "admission.view" },
    { to: "/beds", label: "Beds", icon: "single_bed", perm: "bed.view" },
    { to: "/ot", label: "OT", icon: "medical_services", perm: "ot.view" },
    { to: "/lab", label: "Lab", icon: "biotech", perm: "lab.view" },
  ]},
  { group: "Operations", items: [
    { to: "/billing", label: "Billing", icon: "receipt_long", perm: "billing.view" },
    { to: "/inventory", label: "Inventory", icon: "inventory_2", perm: "inventory.view" },
    { to: "/pharmacy", label: "Pharmacy", icon: "medication", perm: "pharmacy.view" },
    { to: "/documents", label: "Documents", icon: "description", perm: "document.view" },
  ]},
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
  ]},
];

const CRUMBS: Record<string, string> = {
  "/": "Today",
  "/register": "OPD",
  "/patients": "Clinical Operations Desk · Patients",
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

function crumbsFor(path: string) {
  if (CRUMBS[path]) return [{ to: path, label: CRUMBS[path] }];
  if (path.startsWith("/patients/")) return [{ to: "/patients", label: "Patients" }, { to: path, label: "Record" }];
  if (path.startsWith("/billing/")) return [{ to: "/billing", label: "Billing" }, { to: path, label: "Bill" }];
  if (path.startsWith("/consult/")) return [{ to: "/doctor", label: "Doctor queue" }, { to: path, label: "Consultation" }];
  if (path.startsWith("/admissions/")) return [{ to: "/admissions", label: "Admissions" }, { to: path, label: "Admission" }];
  if (path.startsWith("/ot/")) return [{ to: "/ot", label: "OT" }, { to: path, label: "Case" }];
  if (path.startsWith("/inventory/")) return [{ to: "/inventory", label: "Inventory" }, { to: path, label: "Stock" }];
  return [{ to: path, label: "Desk" }];
}

function Guard({ perm, children }: { perm: string; children: ReactNode }) {
  const allowed = useApp((s) => s.can(perm));
  if (!allowed) return <p className="muted">You do not have permission for this desk.</p>;
  return <>{children}</>;
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
    if (!token) return;
    api<User>("/api/auth/me").then(setUser).catch(() => clear());
  }, [token, setUser, clear]);

  useEffect(() => {
    const denied = () => clear();
    const forbidden = (event: Event) => {
      const message = (event as CustomEvent).detail || "You do not have permission for this action.";
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
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const typing = !!target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT" || target.isContentEditable);
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        document.getElementById("global-search")?.focus();
        return;
      }
      if (typing) return;
      if (event.key === "/") {
        event.preventDefault();
        document.getElementById("global-search")?.focus();
      } else if (event.key.toLowerCase() === "n" && can("patient.create")) {
        navigate("/register");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [can, navigate]);

  const bumpRef = useRef(bump);
  bumpRef.current = bump;
  useEffect(() => {
    if (!token) return;
    let source: EventSource | null = null;
    let cancelled = false;
    let retry: number | undefined;
    const connect = () => {
      api<{ token: string }>("/api/auth/stream-ticket", { method: "POST", body: "{}" }).then((ticket) => {
        if (cancelled) return;
        source = new EventSource(`/api/events?token=${encodeURIComponent(ticket.token)}`);
        source.onmessage = (message) => {
          let detail: { event?: string } | null = null;
          try {
            detail = JSON.parse(message.data);
          } catch {
            detail = null;
          }
          if (detail?.event) window.dispatchEvent(new CustomEvent("aipf-live", { detail }));
          bumpRef.current();
        };
        source.onerror = () => {
          source?.close();
          source = null;
          if (!cancelled) retry = window.setTimeout(connect, 15000);
        };
      }).catch((err: Error) => {
        useApp.getState().toast(err.message || "Live updates could not start.", "bad");
        if (!cancelled) retry = window.setTimeout(connect, 15000);
      });
    };
    connect();
    return () => {
      cancelled = true;
      if (retry) window.clearTimeout(retry);
      source?.close();
    };
  }, [token]);

  if (token && !user) {
    return <div className="login-main" style={{ minHeight: "100vh" }}><p className="muted">Opening the local hospital server…</p></div>;
  }
  if (!user) return <Login />;

  return (
    <div className={`${menu ? "app rail-open" : "app"}${compact ? " rail-compact" : ""}`}>
      <a className="skip" href="#stage">Skip to content</a>
      <aside className="rail">
        <nav className="nav" aria-label="Hospital desks">
          {NAV.map((group) => {
            const items = group.items.filter((item) => !item.perm || can(item.perm));
            if (!items.length) return null;
            return (
              <div key={group.group}>
                <div className="nav-label">{group.group}</div>
                {items.map((item) => (
                  <NavLink key={item.to} to={item.to} end={item.to === "/"} data-tour={item.to} title={compact ? item.label : undefined} onClick={() => setMenu(false)}>
                    <Icon name={item.icon} />
                    <span className="label">{item.label}</span>
                  </NavLink>
                ))}
              </div>
            );
          })}
        </nav>
        <div className="rail-foot">
          <NavLink to="/help" title={compact ? "Help & Docs" : undefined} onClick={() => setMenu(false)}>
            <Icon name="help" />
            <span>Help & Docs</span>
          </NavLink>
          <button
            className="rail-toggle"
            type="button"
            aria-label={compact ? "Expand sidebar" : "Collapse sidebar"}
            onClick={() => {
              const next = !compact;
              setCompact(next);
              localStorage.setItem("aipf-rail", next ? "compact" : "full");
            }}
          >
            <Icon name={compact ? "left_panel_open" : "left_panel_close"} />
          </button>
        </div>
      </aside>
      {menu && <button className="rail-backdrop" type="button" aria-label="Close navigation" onClick={() => setMenu(false)} />}
      <div className="work">
        <Topbar onMenu={() => setMenu((open) => !open)} />
        <main className="stage" id="stage">
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/register" element={<Guard perm="patient.create"><Register /></Guard>} />
            <Route path="/patients" element={<Guard perm="patient.view"><Patients /></Guard>} />
            <Route path="/patients/:id" element={<Guard perm="patient.view"><PatientPage /></Guard>} />
            <Route path="/queue" element={<Guard perm="queue.view"><QueuePage /></Guard>} />
            <Route path="/doctor" element={<Guard perm="consultation.create"><QueuePage mine /></Guard>} />
            <Route path="/consult/:id" element={<Guard perm="consultation.create"><Consult /></Guard>} />
            <Route path="/pharmacy" element={<Guard perm="pharmacy.view"><Pharmacy /></Guard>} />
            <Route path="/inventory" element={<Guard perm="inventory.view"><Inventory /></Guard>} />
            <Route path="/inventory/:view" element={<Guard perm="inventory.view"><Inventory /></Guard>} />
            <Route path="/lab" element={<Guard perm="lab.view"><LabPage /></Guard>} />
            <Route path="/billing" element={<Guard perm="billing.view"><Billing /></Guard>} />
            <Route path="/billing/:id" element={<Guard perm="billing.view"><InvoicePage /></Guard>} />
            <Route path="/beds" element={<Guard perm="bed.view"><Beds /></Guard>} />
            <Route path="/admissions" element={<Guard perm="admission.view"><Admissions /></Guard>} />
            <Route path="/admissions/:id" element={<Guard perm="admission.view"><Admissions /></Guard>} />
            <Route path="/ot" element={<Guard perm="ot.view"><OtPage /></Guard>} />
            <Route path="/ot/:id" element={<Guard perm="ot.view"><OtPage /></Guard>} />
            <Route path="/documents" element={<Guard perm="document.view"><Documents /></Guard>} />
            <Route path="/leads" element={<Guard perm="leads.view"><Leads /></Guard>} />
            <Route path="/reports" element={<Guard perm="report.view"><Reports /></Guard>} />
            <Route path="/admin/master" element={<Guard perm="master.manage"><MasterPage /></Guard>} />
            <Route path="/admin/staff" element={<Guard perm="user.manage"><StaffPage /></Guard>} />
            <Route path="/admin/branding" element={<Guard perm="config.manage"><Branding /></Guard>} />
            <Route path="/admin/integrations" element={<Guard perm="whatsapp.configure"><Integrations /></Guard>} />
            <Route path="/admin/health" element={<Guard perm="health.view"><HealthPage /></Guard>} />
            <Route path="/admin/backups" element={<Guard perm="backup.view"><Backups /></Guard>} />
            <Route path="/admin/audit" element={<Guard perm="audit.view"><AuditPage /></Guard>} />
            <Route path="/setup" element={<Guard perm="config.manage"><SetupPage /></Guard>} />
            <Route path="/help" element={<HelpPage />} />
            <Route path="/pair/:token" element={<PairPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
      <BottomNav />
      <SpotlightTour />
      <GuidedDemo />
      <div className="toasts" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.tone || ""}`} role="status">
            <span>{t.text}</span>
            <button type="button" aria-label="Dismiss notification" onClick={() => dismiss(t.id)}>×</button>
          </div>
        ))}
      </div>
    </div>
  );
}

function Topbar({ onMenu }: { onMenu: () => void }) {
  const user = useApp((s) => s.user);
  const clear = useApp((s) => s.clear);
  const navigate = useNavigate();
  const location = useLocation();
  const crumb = crumbsFor(location.pathname)[0];
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<any>(null);

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

  return (
    <header className="topbar">
      <div className="top-brand">
        <button className="btn small menu-btn" type="button" onClick={onMenu} aria-label="Open navigation">Menu</button>
        <img src="/logo.jpg" alt="" />
        <div className="crumb-line">
          <strong>AIPF Mission Hospital</strong>
          <span>{crumb?.label || "Clinical Operations Desk"}</span>
        </div>
      </div>
      <div className="search">
        <Icon name="search" className="search-icon" size={16} />
        <label className="skip" htmlFor="global-search">Search</label>
        <input
          id="global-search"
          type="search"
          placeholder="Search Patient ID, Name, Phone, OPD ID, Bill ID..."
          value={q}
          aria-label="Search by patient ID, name, phone, OPD, admission, bill, prescription, or document"
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Escape") { setQ(""); setHits(null); } }}
        />
        <kbd>Ctrl+K</kbd>
        {hits && (
          <div className="search-pop" role="listbox">
            {hits.patients?.map((p: any) => (
              <a key={p.id} href={`/patients/${p.id}`} onClick={(e) => { e.preventDefault(); setQ(""); setHits(null); navigate(`/patients/${p.id}`); }}>
                Patient {p.name} <small>{p.id} · {p.primary_phone}</small>
              </a>
            ))}
            {hits.encounters?.map((row: any) => (
              <a key={row.id} href={`/consult/${row.id}`} onClick={(e) => { e.preventDefault(); setQ(""); setHits(null); navigate(`/consult/${row.id}`); }}>
                OPD {row.id} <small>{row.patient_id} · {row.status}</small>
              </a>
            ))}
            {hits.prescriptions?.map((row: any) => (
              <a key={row.id} href={row.encounter_id ? `/consult/${row.encounter_id}` : `/patients/${row.patient_id}`} onClick={(e) => { e.preventDefault(); setQ(""); setHits(null); navigate(row.encounter_id ? `/consult/${row.encounter_id}` : `/patients/${row.patient_id}`); }}>
                Prescription {row.id} <small>{row.patient_id} · {row.status}</small>
              </a>
            ))}
            {hits.admissions?.map((row: any) => (
              <a key={row.id} href={`/admissions/${row.id}`} onClick={(e) => { e.preventDefault(); setQ(""); setHits(null); navigate(`/admissions/${row.id}`); }}>
                Admission {row.id} <small>{row.patient_id} · {row.status}</small>
              </a>
            ))}
            {hits.invoices?.map((p: any) => (
              <a key={p.id} href={`/billing/${p.id}`} onClick={(e) => { e.preventDefault(); setQ(""); setHits(null); navigate(`/billing/${p.id}`); }}>
                Bill {p.number} <small>{p.patient_id} · {p.payment_status}</small>
              </a>
            ))}
            {hits.documents?.map((d: any) => (
              <a key={d.id} href={fileUrl(`/api/documents/${d.id}/file`)} target="_blank" rel="noreferrer" onClick={() => { setQ(""); setHits(null); }}>
                Document {d.document_type} <small>{d.patient_id} · {d.title || d.filename}</small>
              </a>
            ))}
            {hits.products?.map((p: any) => (
              <a key={p.id} href="/inventory" onClick={(e) => { e.preventDefault(); setQ(""); setHits(null); navigate("/inventory"); }}>
                {p.name} {p.strength} <small>{p.barcode}</small>
              </a>
            ))}
            {!hits.patients?.length && !hits.invoices?.length && !hits.products?.length && !hits.encounters?.length && !hits.admissions?.length && !hits.documents?.length && !hits.prescriptions?.length && <div className="hit muted">No match</div>}
          </div>
        )}
      </div>
      <div className="top-meta">
        <WhatsAppChip />
        <Bell />
        <UserMenu user={user} onSignOut={() => { api("/api/auth/logout", { method: "POST" }).catch(() => undefined); clear(); }} />
      </div>
    </header>
  );
}

function BottomNav() {
  const can = useApp((s) => s.can);
  const items: Array<{ to: string; label: string; perm?: string }> = [
    { to: "/", label: "Today" },
    { to: "/patients", label: "Patients", perm: "patient.view" },
    { to: "/queue", label: "Queue", perm: "queue.view" },
    { to: "/billing", label: "Billing", perm: "billing.view" },
  ].filter((item) => !item.perm || can(item.perm));
  return (
    <nav className="bottom-nav" aria-label="Main">
      {items.map((item) => (
        <NavLink key={item.to} to={item.to} end={item.to === "/"}>{item.label}</NavLink>
      ))}
      <button type="button" onClick={() => document.querySelector<HTMLButtonElement>(".menu-btn")?.click()}>More</button>
    </nav>
  );
}

function initials(name?: string) {
  const parts = (name || "").trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] || "") + (parts[1]?.[0] || "")).toUpperCase() || "A";
}

function WhatsAppChip() {
  const configure = useApp((s) => s.can("whatsapp.configure"));
  const send = useApp((s) => s.can("whatsapp.send"));
  const [state, setState] = useState("checking");
  useEffect(() => {
    if (!configure) return;
    api<{ state?: string; ok?: boolean }>("/api/integrations/whatsapp/test", { method: "POST", body: "{}" })
      .then((row) => setState(row.state === "connected" || row.ok ? "connected" : "offline"))
      .catch(() => setState("offline"));
  }, [configure]);
  if (!configure && !send) return null;
  const label = configure ? (state === "connected" ? "Connected" : state === "offline" ? "Not connected" : "Checking") : "Send only";
  return (
      <NavLink className={`wa-chip ${configure ? state : ""}`} to={configure ? "/admin/integrations" : "/help"} title={`WhatsApp ${label}`}>
      <span className={`wa-dot ${configure ? state : ""}`} />
      <span>WhatsApp {label}</span>
    </NavLink>
  );
}

function UserMenu({ user, onSignOut }: { user: User | null; onSignOut: () => void }) {
  const [open, setOpen] = useState(false);
  const name = [user?.title, user?.full_name].filter(Boolean).join(" ");
  return (
    <div className="user-wrap">
      <button className="user-chip" type="button" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        <span><strong>{name || "Staff"}</strong><small>{user?.roles?.[0] || "Staff"}</small></span>
        <span className="avatar">{initials(user?.full_name)}</span>
      </button>
      {open && (
        <div className="user-pop">
          <button type="button" onClick={onSignOut}>Sign out</button>
        </div>
      )}
    </div>
  );
}

function Bell() {
  const { data } = useData<{ items: any[] }>("/api/notifications/mine");
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const notes = (data?.items || []).filter((n) => n.status === "UNREAD").slice(0, 8);
  return (
    <div className="bell-wrap">
      <button className="icon-btn" type="button" aria-expanded={open} aria-label="Notifications" onClick={() => setOpen((v) => !v)}>
        <Icon name="notifications" size={20} />
        {notes.length > 0 && <span className="badge">{notes.length}</span>}
      </button>
      {open && (
        <div className="note-pop" role="menu">
          {notes.length === 0 && <div className="hit muted">No notes waiting.</div>}
          {notes.map((note) => (
            <button key={note.id} className="note" type="button" onClick={() => {
              api(`/api/notifications/${note.id}/read`, { method: "POST" }).catch(() => undefined);
              setOpen(false);
              if (note.entity_type === "ot" && note.entity_id) navigate(`/ot/${note.entity_id}`);
              else if (note.entity_type === "patient" && note.entity_id) navigate(`/patients/${note.entity_id}`);
            }}>
              <strong>{note.message_type || "Note"}</strong>
              <div className="muted">{note.body || "Open the related record."}</div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function Login() {
  const setSession = useApp((s) => s.setSession);
  const toast = useApp((s) => s.toast);
  const dismiss = useApp((s) => s.dismiss);
  const [brand, setBrand] = useState<any>(null);
  const [accounts, setAccounts] = useState<any[]>([]);
  const [username, setUsername] = useState("reception");
  const [password, setPassword] = useState("");
  const [desk, setDesk] = useState(sessionStorage.getItem("aipf-workstation") || "Reception");
  const [busy, setBusy] = useState(false);
  const toasts = useApp((s) => s.toasts);

  useEffect(() => {
    fetch("/api/public/branding").then((r) => r.json()).then((j) => setBrand(j.data)).catch(() => undefined);
    fetch("/api/public/accounts").then((r) => r.json()).then((j) => setAccounts(j.data?.items || [])).catch(() => undefined);
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setWorkstation(desk);
    try {
      const data = await api<{ token: string; user: User }>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ username, password, workstation: desk }),
      });
      setSession(data.token, data.user);
    } catch (err) {
      toast((err as Error).message, "bad");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login">
      <section className="login-main">
        <form className="login-card" onSubmit={submit}>
          <img src="/logo.jpg" alt="" width={56} height={56} style={{ borderRadius: "50%" }} />
          <h2>Welcome back</h2>
          <p className="muted">{brand?.name || "AIPF Mission Hospital"}. The workstation is written into the audit log.</p>
          <div className="grid-form" style={{ marginTop: 12 }}>
            <Field label="Workstation" className="span-2"><input value={desk} onChange={(e) => setDesk(e.target.value)} /></Field>
            <Field label="Username" required><input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus /></Field>
            <Field label="Password" required><input type="password" value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
          </div>
          <div style={{ marginTop: 12 }}>
            <button className="btn primary" disabled={busy}>{busy ? "Checking…" : "Sign in"}</button>
          </div>
        </form>
        {accounts.length > 0 && (
          <table className="accounts">
            <thead>
              <tr><th>Username</th><th>Role</th></tr>
            </thead>
            <tbody>
              {accounts.map((a) => (
                <tr key={a.username} onClick={() => setUsername(a.username)} style={{ cursor: "pointer" }}>
                  <td>{a.username}</td><td>{a.role}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="muted">Passwords are not shown here. Change them under Users & roles after the first sign-in.</p>
        <div className="toasts">
          {toasts.map((t) => (
            <div key={t.id} className={`toast ${t.tone || ""}`} role="status">
              <span>{t.text}</span>
              <button type="button" aria-label="Dismiss notification" onClick={() => dismiss(t.id)}>×</button>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
