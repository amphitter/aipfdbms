import { useState } from "react";
import { api, money, when } from "../api";
import { useApp } from "../store";
import { Field, Page, PatientSearchSelect, Status, run, useData, type PatientSummary } from "../ui";

export function StaffPage() {
  const me = useApp((s) => s.user);
  const { data } = useData<{ items: any[] }>("/api/users");
  const { data: roles } = useData<any>("/api/roles");
  const [form, setForm] = useState<any>({ username: "", full_name: "", password: "", roles: ["reception"] });
  const [editing, setEditing] = useState<any>(null);
  return (
    <Page title="Users & Roles" note="Edit a staff account, or permanently delete a login that is not on a consultation or prescription.">
      <div className="table-wrap"><table className="data">
        <thead><tr><th>Name</th><th>Username</th><th>Title</th><th>Roles</th><th>Active</th><th></th></tr></thead>
        <tbody>
          {(data?.items || []).map((u) => (
            <tr key={u.id}>
              <td>{u.full_name}</td>
              <td>{u.username}</td>
              <td>{u.title || "—"}</td>
              <td>{(u.roles || []).join(", ")}</td>
              <td>{u.active ? "Yes" : "No"}</td>
              <td className="row-actions">
                <button className="btn small" type="button" onClick={() => setEditing({ ...u, password: "" })}>Edit</button>
                <button className="btn small" type="button" onClick={() => run(() => api(`/api/users/${u.id}`, { method: "PATCH", body: JSON.stringify({ username: u.username, full_name: u.full_name, title: u.title, roles: u.roles, active: !u.active }) }), u.active ? "Account disabled" : "Account reactivated")}>{u.active ? "Disable" : "Reactivate"}</button>
                {me?.id !== u.id && <button className="btn small danger" type="button" onClick={() => {
                  if (!window.confirm(`Permanently delete ${u.full_name}? The login is removed. This cannot be undone.`)) return;
                  run(() => api(`/api/users/${u.id}`, { method: "DELETE" }), "Staff deleted");
                }}>Delete</button>}
              </td>
            </tr>
          ))}
        </tbody>
      </table></div>
      {editing && (
        <div className="panel">
          <h2>Edit {editing.full_name}</h2>
          <div className="body grid-form">
            <Field label="Full name"><input value={editing.full_name || ""} onChange={(e) => setEditing({ ...editing, full_name: e.target.value })} /></Field>
            <Field label="Username"><input value={editing.username || ""} onChange={(e) => setEditing({ ...editing, username: e.target.value })} /></Field>
            <Field label="Title"><input value={editing.title || ""} onChange={(e) => setEditing({ ...editing, title: e.target.value })} /></Field>
            <Field label="Specialty"><input value={editing.specialty || ""} onChange={(e) => setEditing({ ...editing, specialty: e.target.value })} /></Field>
            <Field label="Phone"><input value={editing.phone || ""} onChange={(e) => setEditing({ ...editing, phone: e.target.value })} /></Field>
            <Field label="New password"><input type="password" autoComplete="new-password" value={editing.password || ""} placeholder="Leave blank to keep" onChange={(e) => setEditing({ ...editing, password: e.target.value })} /></Field>
            <div className="span-2">
              <span>Roles</span>
              <div className="row-actions">
                {(roles?.items || []).map((r: any) => (
                  <label key={r.code} className="check-line">
                    <input type="checkbox" checked={(editing.roles || []).includes(r.code)} onChange={(e) => {
                      const next = new Set(editing.roles || []);
                      if (e.target.checked) next.add(r.code);
                      else next.delete(r.code);
                      setEditing({ ...editing, roles: [...next] });
                    }} />
                    {r.name}
                  </label>
                ))}
              </div>
            </div>
            <div className="row-actions">
              <button className="btn primary" type="button" onClick={() => run(async () => {
                const body: any = { username: editing.username, full_name: editing.full_name, title: editing.title, specialty: editing.specialty, phone: editing.phone, roles: editing.roles, active: Boolean(editing.active) };
                if (editing.password) body.password = editing.password;
                await api(`/api/users/${editing.id}`, { method: "PATCH", body: JSON.stringify(body) });
                setEditing(null);
              }, "Staff updated")}>Save</button>
              <button className="btn" type="button" onClick={() => setEditing(null)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
      <div className="panel">
        <h2>New staff account</h2>
        <div className="body grid-form">
          <Field label="Full name"><input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></Field>
          <Field label="Username"><input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} /></Field>
          <Field label="Password"><input type="password" autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></Field>
          <Field label="Role">
            <select value={form.roles[0]} onChange={(e) => setForm({ ...form, roles: [e.target.value] })}>
              {(roles?.items || []).map((r: any) => <option key={r.code} value={r.code}>{r.name}</option>)}
            </select>
          </Field>
          <button className="btn primary" onClick={() => run(() => api("/api/users", { method: "POST", body: JSON.stringify(form) }), "Staff account created")}>Create</button>
        </div>
      </div>
    </Page>
  );
}

export function Branding() {
  const { data } = useData<any>("/api/hospital");
  const [form, setForm] = useState<any>(null);
  const current = form || data || {};
  function set(key: string, value: string) {
    setForm({ ...current, [key]: value });
  }
  return (
    <Page kicker="Letterhead" title="Hospital branding" actions={<button className="btn primary" onClick={() => run(() => api("/api/hospital", { method: "PUT", body: JSON.stringify(current) }), "Hospital profile saved")}>Save</button>}>
      <div className="grid-2">
        <div className="panel">
          <h2>Identity used on new bills</h2>
          <div className="body grid-form">
            <Field label="Name"><input value={current.name || ""} onChange={(e) => set("name", e.target.value)} /></Field>
            <Field label="Legal name"><input value={current.legal_name || ""} onChange={(e) => set("legal_name", e.target.value)} /></Field>
            <Field label="Tagline" className="span-2"><input value={current.tagline || ""} onChange={(e) => set("tagline", e.target.value)} /></Field>
            <Field label="Address"><input value={current.address_line1 || ""} onChange={(e) => set("address_line1", e.target.value)} /></Field>
            <Field label="Area"><input value={current.address_line2 || ""} onChange={(e) => set("address_line2", e.target.value)} /></Field>
            <Field label="City"><input value={current.city || ""} onChange={(e) => set("city", e.target.value)} /></Field>
            <Field label="PIN"><input value={current.pin || ""} onChange={(e) => set("pin", e.target.value)} /></Field>
            <Field label="Phone"><input value={current.phone || ""} onChange={(e) => set("phone", e.target.value)} placeholder="Desk number for the bill" /></Field>
            <Field label="Email"><input value={current.email || ""} onChange={(e) => set("email", e.target.value)} /></Field>
            <Field label="Website"><input value={current.website || ""} onChange={(e) => set("website", e.target.value)} /></Field>
            <Field label="Bill prefix"><input value={current.bill_prefix || ""} onChange={(e) => set("bill_prefix", e.target.value)} /></Field>
          </div>
        </div>
        <div className="panel">
          <h2>Logo</h2>
          <div className="body">
            <img src="/api/public/logo" alt="Current logo" style={{ width: 120, height: 120, objectFit: "contain", background: "white", border: "1px solid var(--line)" }} />
            <p className="muted">PNG or JPEG, under 1.5 MB. New documents pick up the current logo. Old PDFs are not rewritten.</p>
            <input type="file" accept="image/png,image/jpeg" onChange={async (e) => {
              const file = e.target.files?.[0];
              if (!file) return;
              const content_base64 = await read64(file);
              await run(() => api("/api/branding/logo", { method: "POST", body: JSON.stringify({ content_base64, kind: "primary" }) }), "Logo replaced");
            }} />
          </div>
        </div>
      </div>
    </Page>
  );
}

function read64(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

function ManualMessage() {
  const [patient, setPatient] = useState<PatientSummary | null>(null);
  const [text, setText] = useState("");
  return (
    <div className="body grid-form">
      <PatientSearchSelect value={patient} onChange={setPatient} className="span-2" />
      <Field label="Message" className="span-2">
        <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="Confirm the recipient before sending." />
      </Field>
      <button className="btn primary" type="button" disabled={!patient || !text.trim()} onClick={() => {
        if (!patient) return;
        if (!window.confirm(`Send this message to ${patient.name}?`)) return;
        run(() => api("/api/whatsapp/messages", { method: "POST", body: JSON.stringify({ patient_id: patient.id, text, confirm: true }) }), "Message handed to the provider");
      }}>Send</button>
      {patient && <p className="muted">Recipient {patient.name} · {patient.primary_phone || "no phone"} · {patient.id}</p>}
    </div>
  );
}

export function Integrations() {
  const { data } = useData<any>("/api/integrations");
  const { data: templates } = useData<any>("/api/templates");
  const [wa, setWa] = useState<any>(null);
  const [leads, setLeads] = useState<any>(null);
  const [status, setStatus] = useState<any>(null);
  const [qr, setQr] = useState<any>(null);
  const [testPhone, setTestPhone] = useState("");
  const [draft, setDraft] = useState({ id: "", name: "", body: "", message_type: "visit_complete" });
  const { data: sent } = useData<any>("/api/notifications?channel=WHATSAPP");
  const whatsapp = wa || data?.whatsapp || {};
  const lead = leads || data?.leads || {};
  return (
    <Page kicker="Optional links" title="WhatsApp">
      <div className="warn">These connections are not required for registration, OPD, pharmacy, or billing. If they fail, the desk continues and the failed work stays queued.</div>
      <div className="grid-2">
        <div className="panel">
          <h2>WhatsApp / OpenWA</h2>
          <div className="body grid-form">
            <Field label="Base URL"><input value={whatsapp.base_url || ""} onChange={(e) => setWa({ ...whatsapp, base_url: e.target.value })} placeholder="http://openwa-host:2785" /></Field>
            <Field label="Session ID"><input value={whatsapp.session_id || ""} onChange={(e) => setWa({ ...whatsapp, session_id: e.target.value })} /></Field>
            <Field label="API key"><input value={whatsapp.api_key || ""} onChange={(e) => setWa({ ...whatsapp, api_key: e.target.value })} placeholder={whatsapp.api_key_set ? "Stored — type to replace" : "Not set"} /></Field>
            <Field label="Delay minutes"><input value={whatsapp.delay_minutes || 5} onChange={(e) => setWa({ ...whatsapp, delay_minutes: Number(e.target.value) })} /></Field>
            <label><input type="checkbox" checked={!!whatsapp.enabled} onChange={(e) => setWa({ ...whatsapp, enabled: e.target.checked })} /> Enable outbound messages</label>
            <div className="row-actions span-2">
              <button className="btn primary" onClick={() => run(() => api("/api/integrations/whatsapp", { method: "PUT", body: JSON.stringify(whatsapp) }), "WhatsApp settings saved")}>Save</button>
              <button className="btn" onClick={() => run(async () => setStatus(await api("/api/integrations/whatsapp/test", { method: "POST" })), "Connection checked")}>Check status</button>
              <button className="btn" onClick={() => run(async () => setQr(await api("/api/integrations/whatsapp/qr", { method: "POST" })), "QR requested")}>Show QR</button>
              <button className="btn" onClick={() => run(() => api("/api/integrations/whatsapp/reconnect", { method: "POST" }), "Reconnect requested")}>Reconnect</button>
              <button className="btn" onClick={() => run(() => api("/api/integrations/whatsapp/disconnect", { method: "POST" }), "Disconnect requested")}>Disconnect</button>
            </div>
            {status && <p className="span-2">{status.configured ? "Configured" : "Not configured"} · {status.reachable ? "Reachable" : "Not reachable"} · {status.authenticated ? "Authenticated" : "Not authenticated"} · {status.session_status || "unknown"} · {status.provider || "openwa"}</p>}
            {qr?.image && <img className="qr-preview span-2" src={qr.image} alt="WhatsApp pairing QR from the configured provider" />}
            {qr && !qr.image && <p className="span-2 muted">No QR image was returned. {qr.state || ""} {qr.detail || "The provider may already be paired, or it is not configured."}</p>}
            <Field label="Test phone"><input value={testPhone} onChange={(e) => setTestPhone(e.target.value)} placeholder="A number you control. No patient data is included." /></Field>
            <button className="btn" onClick={() => {
              if (!window.confirm(`Send a test message with no patient data to ${testPhone}?`)) return;
              run(() => api("/api/integrations/whatsapp/send-test", { method: "POST", body: JSON.stringify({ phone: testPhone }) }), "OpenWA accepted the test message");
            }}>Send test</button>
          </div>
        </div>
        <div className="panel">
          <h2>Website leads</h2>
          <div className="body grid-form">
            <Field label="MongoDB URI" className="span-2"><input value={lead.mongo_uri || ""} onChange={(e) => setLeads({ ...lead, mongo_uri: e.target.value })} placeholder={lead.mongo_uri_set ? "Stored — type to replace" : "mongodb+srv://…"} /></Field>
            <Field label="Database"><input value={lead.database || ""} onChange={(e) => setLeads({ ...lead, database: e.target.value })} /></Field>
            <Field label="Collection"><input value={lead.collection || "leads"} onChange={(e) => setLeads({ ...lead, collection: e.target.value })} /></Field>
            <label><input type="checkbox" checked={!!lead.enabled} onChange={(e) => setLeads({ ...lead, enabled: e.target.checked })} /> Enable sync</label>
            <div className="row-actions span-2">
              <button className="btn primary" onClick={() => run(() => api("/api/integrations/leads", { method: "PUT", body: JSON.stringify(lead) }), "Lead settings saved")}>Save</button>
              <button className="btn" onClick={() => run(async () => setStatus(await api("/api/integrations/leads/test", { method: "POST" })), "Lead connection checked")}>Test</button>
            </div>
          </div>
        </div>
      </div>
      <div className="panel">
        <h2>Message template</h2>
        <div className="body">
          <p className="muted">Variables: {(templates?.variables || []).map((v: string) => `{${v}}`).join("  ")}</p>
          {(templates?.items || []).map((t: any) => (
            <p key={t.id}><strong>{t.name}.</strong> {t.body} <button className="btn small" onClick={() => setDraft({ id: t.id, name: t.name, body: t.body, message_type: t.message_type || "visit_complete" })}>Edit</button></p>
          ))}
          <div className="grid-form">
            <Field label="Template name"><input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></Field>
            <Field label="Message" className="span-2"><textarea value={draft.body} onChange={(e) => setDraft({ ...draft, body: e.target.value })} /></Field>
            <button className="btn primary" onClick={() => run(() => api(draft.id ? `/api/templates/${draft.id}` : "/api/templates", { method: draft.id ? "PUT" : "POST", body: JSON.stringify(draft) }), "Template saved")}>{draft.id ? "Update template" : "Save template"}</button>
          </div>
        </div>
      </div>
      <div className="panel">
        <h2>Send a message</h2>
        <ManualMessage />
      </div>
      <div className="panel">
        <h2>Recent WhatsApp attempts</h2>
        <div className="body">
          <table className="data">
            <thead><tr><th>When</th><th>Status</th><th>Patient</th><th>Reference</th><th>Phone</th><th>Detail</th></tr></thead>
            <tbody>
              {(sent?.items || []).slice(0, 12).map((item: any) => (
                <tr key={item.id}>
                  <td>{when(item.created_at || item.sent_at)}</td>
                  <td><Status value={item.status} /></td>
                  <td className="pid">{item.patient_id || "—"}</td>
                  <td className="pid">{item.document_id || item.entity_id || item.message_type || "—"}</td>
                  <td>{item.phone ? `···${String(item.phone).slice(-4)}` : "—"}</td>
                  <td className="muted">{item.failure_reason || item.body}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {(sent?.items || []).length === 0 && <p className="muted">No WhatsApp notification has been recorded.</p>}
        </div>
      </div>
    </Page>
  );
}

export function HealthPage() {
  const { data, loading } = useData<any>("/api/system/health");
  return (
    <Page kicker="Diagnostics" title="System health" actions={<button className="btn" onClick={() => run(async () => api("/api/system/health"), "Health refreshed")}>Refresh</button>}>
      <div className="banner">
        <div>
          <div className="kicker">Overall</div>
          <h2>{data?.overall || (loading ? "Checking…" : "—")}</h2>
          <div className="muted">Checked {when(data?.checked_at)}. One diagnostics service — modules do not keep their own copies.</div>
        </div>
        <Status value={data?.overall} />
      </div>
      <table className="data">
        <thead><tr><th>Check</th><th>Status</th><th>Latency</th><th>Detail</th><th>Recommended action</th></tr></thead>
        <tbody>
          {(data?.checks || []).map((c: any) => (
            <tr key={c.name}>
              <td>{c.name}</td>
              <td><Status value={c.status} /></td>
              <td>{c.latency_ms != null ? `${c.latency_ms} ms` : "—"}</td>
              <td>{c.detail} {c.error && <span className="allergy">{c.error}</span>}</td>
              <td className="muted">{c.recommended_action}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Page>
  );
}

export function Backups() {
  const { data } = useData<any>("/api/backups");
  const { data: settings } = useData<any>("/api/backups/settings");
  const [form, setForm] = useState<any>(null);
  const current = form || settings || {};
  const [confirm, setConfirm] = useState("");
  return (
    <Page kicker="Protection" title="Backups" actions={<button className="btn primary" onClick={() => run(() => api("/api/backups", { method: "POST" }), "Local backup created")}>Back up now</button>}>
      <div className="warn">A cloud HTTP 200 is not treated as verified. The archive is checked for size and checksum. If the cloud fails, the local copy is kept.</div>
      <table className="data">
        <thead><tr><th>When</th><th>Kind</th><th>Status</th><th>Cloud</th><th>Checksum</th><th></th></tr></thead>
        <tbody>
          {(data?.items || []).map((b: any) => (
            <tr key={b.id}>
              <td>{when(b.started_at)}</td>
              <td>{b.kind}</td>
              <td><Status value={b.status} /></td>
              <td>{b.cloud_status || "—"} {b.cloud_error && <span className="muted">{b.cloud_error}</span>}</td>
              <td className="muted">{(b.checksum || "").slice(0, 12)}</td>
              <td><button className="btn small" onClick={() => run(() => api(`/api/backups/${b.id}/verify`, { method: "POST" }), "Archive verified")}>Verify</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="panel">
        <h2>Schedule and cloud</h2>
        <div className="body grid-form">
          <Field label="Time (24h)"><input value={current.backup_time || "02:00"} onChange={(e) => setForm({ ...current, backup_time: e.target.value })} /></Field>
          <Field label="Retention days"><input value={current.backup_retention_days || 30} onChange={(e) => setForm({ ...current, backup_retention_days: e.target.value })} /></Field>
          <Field label="Endpoint"><input value={current.cloud_endpoint || ""} onChange={(e) => setForm({ ...current, cloud_endpoint: e.target.value })} placeholder="S3, R2, B2, or MinIO" /></Field>
          <Field label="Bucket"><input value={current.cloud_bucket || ""} onChange={(e) => setForm({ ...current, cloud_bucket: e.target.value })} /></Field>
          <Field label="Region"><input value={current.cloud_region || ""} onChange={(e) => setForm({ ...current, cloud_region: e.target.value })} /></Field>
          <Field label="Access key"><input value={current.cloud_access_key || ""} onChange={(e) => setForm({ ...current, cloud_access_key: e.target.value })} /></Field>
          <Field label="Secret key"><input value={current.cloud_secret_key || ""} onChange={(e) => setForm({ ...current, cloud_secret_key: e.target.value })} /></Field>
          <button className="btn" onClick={() => run(() => api("/api/backups/settings", { method: "PUT", body: JSON.stringify(current) }), "Backup settings saved")}>Save settings</button>
        </div>
      </div>
      <div className="panel">
        <h2>Restore</h2>
        <div className="body">
          <p>Restore replaces the live database. Type <strong>RESTORE AIPF</strong>. A safety copy is written first. Restart the server afterwards.</p>
          <Field label="Confirmation"><input value={confirm} onChange={(e) => setConfirm(e.target.value)} /></Field>
          <Field label="Backup id"><input id="restore-id" placeholder="From the list above" /></Field>
          <button className="btn danger" onClick={() => run(() => api(`/api/backups/${(document.getElementById("restore-id") as HTMLInputElement).value}/restore`, { method: "POST", body: JSON.stringify({ confirm }) }), "Restore finished — restart the server")}>Restore</button>
        </div>
      </div>
    </Page>
  );
}

export function AuditPage() {
  const [module, setModule] = useState("");
  const { data } = useData<any>(`/api/audit?module=${module}`);
  return (
    <Page kicker="Trace" title="Audit" actions={
      <select value={module} onChange={(e) => setModule(e.target.value)}>
        <option value="">All modules</option>
        {["auth", "patients", "opd", "clinical", "pharmacy", "billing", "ipd", "ot", "lab", "documents", "admin", "backup", "whatsapp"].map((m) => <option key={m}>{m}</option>)}
      </select>
    }>
      <table className="data">
        <thead><tr><th>When</th><th>User</th><th>Action</th><th>Entity</th><th>Workstation</th></tr></thead>
        <tbody>
          {(data?.items || []).map((row: any) => (
            <tr key={row.id}>
              <td>{when(row.at)}</td>
              <td>{row.username}</td>
              <td>{row.action}</td>
              <td>{row.entity} {row.entity_id}</td>
              <td>{row.workstation}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Page>
  );
}

export function Reports() {
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const { data } = useData<any>(`/api/reports/daily?date=${date}`);
  return (
    <Page kicker="Reports" title="Daily operations" actions={
      <>
        <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        <a className="btn" href={`/api/reports/export?type=daily&date=${date}&token=${encodeURIComponent(sessionStorage.getItem("aipf-token") || "")}`}>CSV</a>
      </>
    }>
      <div className="stats">
        <div className="stat"><span>Patients</span><strong>{data?.patients}</strong></div>
        <div className="stat"><span>OPD</span><strong>{data?.opd}</strong></div>
        <div className="stat"><span>Admissions</span><strong>{data?.admissions}</strong></div>
        <div className="stat"><span>Discharges</span><strong>{data?.discharges}</strong></div>
        <div className="stat"><span>Dispensed</span><strong>{data?.dispensed}</strong></div>
        <div className="stat"><span>Outstanding</span><strong>{money(data?.outstanding_paise)}</strong></div>
      </div>
      <table className="data">
        <thead><tr><th>Mode</th><th>Kind</th><th className="num">Amount</th><th className="num">Count</th></tr></thead>
        <tbody>
          {(data?.payments || []).map((p: any, i: number) => (
            <tr key={i}><td>{p.mode}</td><td>{p.kind}</td><td className="num">{money(p.amount_paise)}</td><td className="num">{p.n}</td></tr>
          ))}
        </tbody>
      </table>
    </Page>
  );
}

export function SetupPage() {
  const { data } = useData<any>("/api/onboarding");
  return (
    <Page kicker="First days" title="Setup">
      <p>{data?.done || 0} of {data?.total || 0} ready. Critical lists are already loaded for AIPF. Fill the desk phone before printing bills.</p>
      <div className="row-actions" style={{ marginBottom: 12 }}>
        <button className="btn" onClick={() => window.dispatchEvent(new Event("aipf-replay-tour"))}>Replay tour</button>
        <button className="btn" onClick={() => window.dispatchEvent(new Event("aipf-start-demo"))}>Learn the workflow</button>
        <button className="btn" onClick={() => run(() => api("/api/admin/load-demo", { method: "POST" }), "Sample patients loaded")}>Load demo patients</button>
        <button className="btn danger" onClick={() => {
          if (!window.confirm("Remove every patient marked SAMPLE? Real registrations are not deleted.")) return;
          run(() => api("/api/admin/clear-sample", { method: "POST" }), "Sample patients removed");
        }}>Reset sample data</button>
      </div>
      <p className="muted">Demo patients are named DEMO and marked sample. Reset uses the existing sample clear. It cannot delete a patient who was registered as a real person.</p>
      <div className="stats"><div className="stat"><span>Progress</span><strong>{data ? Math.round((data.done / data.total) * 100) : 0}%</strong></div></div>
      {(data?.steps || []).map((step: any, index: number) => (
        <div className="panel" key={step.id}>
          <h2>Step {index + 1} · {step.title} · {step.done ? "Ready" : "Needs attention"}</h2>
          <div className="body">
            <p><strong>Why.</strong> {step.why}</p>
            <p className="muted"><strong>Example.</strong> {step.example}</p>
          </div>
        </div>
      ))}
    </Page>
  );
}

const HELP = [
  ["Getting started", "Sign in with the desk you are sitting at. Reception registers, the doctor consults, pharmacy dispenses, billing takes money. Nothing here depends on the internet."],
  ["Patient registration", "Phone is a search key, not an identity. If three Sharmas share 98111…, the desk must choose Use existing or Create new. The system will not overwrite Rajesh with Aarav."],
  ["OPD", "A 5-day card charges once. A return visit inside validity gets a new encounter number and a zero fee, linked to the original card. The visit is still recorded."],
  ["Doctor", "Open your queue, write structured notes, and finalize the prescription. Pharmacy sees it immediately. You do not have to retype the whole chart into one box."],
  ["Prescription", "Dose, route, duration, and food instruction are separate fields. 1-0-1 means morning and night. Finalize sends it to the pharmacy queue. It is not the same as dispensing."],
  ["Pharmacy", "Scan, pick the batch, confirm quantity. Stock falls only inside a transaction. An expired batch is refused. A substitution needs a written reason."],
  ["Inventory", "Stock is a ledger: opening, purchase, dispense, damage, expiry, loss. The on-hand figure must agree with the sum of movements. There is no silent edit."],
  ["Billing", "One invoice holds consultation, services, pharmacy, and lab. The rate on a line is the rate that was applied, even if the master price changes tomorrow. Finalize locks the charges. Payments can still arrive later."],
  ["IPD", "An admission is not a pile of OPDs. It has a bed, movements, daily charges, and one discharge. Post the bed charge deliberately so a day is never billed twice by accident."],
  ["OT", "Request, schedule, perform, then notes. Outcome may be successful, unsuccessful, or aborted. The case remains on the record either way."],
  ["Documents", "Aadhaar, reports, and discharge summaries sit on this server, linked to the patient. Filenames from the browser are not used as storage paths."],
  ["Reports", "Daily counts, collections by mode, and outstanding are calculated from the same records the desk uses."],
  ["Backup", "Local backup is mandatory. Cloud is optional and only marked verified after size and checksum agree. Restore asks you to type RESTORE AIPF."],
  ["System health", "Look here before blaming the software. Database, disk, storage, PDF, and the queue worker are checked in one place. OpenWA being offline does not make the hospital critical."],
];

export function HelpPage() {
  return (
    <Page kicker="Training" title="Help & training" actions={
      <>
        <button className="btn" onClick={() => window.dispatchEvent(new Event("aipf-replay-tour"))}>Replay tour</button>
        <button className="btn primary" onClick={() => window.dispatchEvent(new Event("aipf-start-demo"))}>Learn the workflow</button>
      </>
    }>
      <div className="panel help">
        <div className="body">
          <p>This guide stays in the application. A training video can be kept on the hospital server and opened from the desk; it is not loaded from the internet, so the ward still has it during an outage.</p>
          {HELP.map(([title, body]) => (
            <details key={title} open>
              <summary>{title}</summary>
              <p>{body}</p>
            </details>
          ))}
        </div>
      </div>
    </Page>
  );
}
