import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, money, when } from "../api";
import { Icon } from "../icons";
import { useApp } from "../store";
import { ErrorState, Loading, Page, PatientLink, Status } from "../ui";

type Tone = "" | "normal" | "pending" | "critical" | "done";

const CLOSED = new Set(["COMPLETED", "CANCELLED", "DISCHARGED", "VOID"]);

function num(value: unknown) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function formatDay(iso?: string) {
  if (!iso || !/^\d{4}-\d{2}-\d{2}$/.test(iso)) return "";
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(year, month - 1, day).toLocaleDateString("en-IN", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}

function versus(today: unknown, yesterday: unknown, asMoney = false) {
  if (today == null || yesterday == null) return "";
  const delta = Number(today) - Number(yesterday);
  if (!Number.isFinite(delta) || delta === 0) return "";
  const shown = asMoney ? money(Math.abs(delta)) : String(Math.abs(delta));
  return delta > 0 ? `${shown} more than yesterday` : `${shown} fewer than yesterday`;
}

function healthLabel(value?: string) {
  const state = (value || "").toUpperCase();
  if (!state || state === "UNKNOWN") return "No health check yet";
  if (state === "UNCHECKED") return "No health check yet";
  if (state === "OFFLINE") return "Offline";
  return state.charAt(0) + state.slice(1).toLowerCase();
}

function healthTone(value?: string) {
  const state = (value || "").toUpperCase();
  if (state === "HEALTHY") return "ok";
  if (state === "DEGRADED" || state === "WARNING") return "wait";
  if (state === "CRITICAL" || state === "OFFLINE") return "bad";
  return "";
}

function waLabel(state?: string) {
  if (state === "connected") return "Connected";
  if (state === "configured") return "Not checked";
  return "Not connected";
}

function token(n: unknown) {
  return `T-${String(n ?? "").padStart(3, "0")}`;
}

function actionLabel(action?: string) {
  const known: Record<string, string> = {
    login: "Signed in",
    login_failed: "Sign-in failed",
    backup_create: "Backup saved",
    payment: "Payment recorded",
    patient_create: "Patient registered",
    patient_update: "Patient updated",
    invoice_finalize: "Bill finalized",
    whatsapp_config: "WhatsApp settings saved",
  };
  if (!action) return "Activity";
  return known[action] || action.replaceAll("_", " ");
}

function applyLive(prev: any, detail: any) {
  if (!prev || !detail?.event) return prev;
  const data = detail.data || {};
  const event = String(detail.event);
  const next = {
    ...prev,
    queue: Array.isArray(prev.queue) ? prev.queue.map((row: any) => ({ ...row })) : [],
    my_queue: Array.isArray(prev.my_queue) ? prev.my_queue.map((row: any) => ({ ...row })) : [],
    ot: Array.isArray(prev.ot) ? prev.ot.map((row: any) => ({ ...row })) : [],
  };
  if (event === "queue.updated" && data.id && data.status) {
    const patch = (row: any) => (row.id === data.id ? { ...row, status: data.status } : row);
    next.queue = next.queue.map(patch).filter((row: any) => !CLOSED.has(row.status));
    next.my_queue = next.my_queue.map(patch).filter((row: any) => !CLOSED.has(row.status));
  }
  if (String(event).includes("ot") && data.id && data.status) {
    next.ot = next.ot.map((row: any) => (row.id === data.id ? { ...row, status: data.status } : row));
  }
  return next;
}

function Metric({ to, label, value, hint, tone = "" }: { to: string; label: string; value: string | number; hint?: string; tone?: Tone }) {
  return (
    <Link className={`metric ${tone}`} to={to}>
      <strong>{value}</strong>
      <span>{label}</span>
      {hint ? <small>{hint}</small> : null}
    </Link>
  );
}

function Head({ icon, title, to, label = "Open" }: { icon: string; title: string; to?: string; label?: string }) {
  return (
    <header className="dash-h">
      <h2><Icon name={icon} size={16} /> {title}</h2>
      {to ? <Link to={to}>{label}</Link> : null}
    </header>
  );
}

function Quiet({ text }: { text: string }) {
  return <p className="quiet">{text}</p>;
}

export function Home() {
  const can = useApp((s) => s.can);
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [more, setMore] = useState(false);
  const moreRef = useRef<HTMLDivElement>(null);
  const requestId = useRef(0);
  const hasData = useRef(false);

  const load = useCallback(async () => {
    const id = ++requestId.current;
    try {
      const next = await api<any>("/api/dashboard");
      if (id !== requestId.current) return;
      hasData.current = true;
      setData(next);
      setError("");
    } catch (err) {
      if (id !== requestId.current) return;
      if (!hasData.current) setError(err instanceof Error ? err.message : "Today could not load.");
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    let timer: number | undefined;
    const onLive = (event: Event) => {
      const detail = (event as CustomEvent).detail;
      setData((prev: any) => applyLive(prev, detail));
      if (timer) window.clearTimeout(timer);
      timer = window.setTimeout(() => load(), 2000);
    };
    window.addEventListener("aipf-live", onLive);
    return () => {
      window.removeEventListener("aipf-live", onLive);
      if (timer) window.clearTimeout(timer);
    };
  }, [load]);

  useEffect(() => {
    if (!more) return;
    const close = (event: MouseEvent) => {
      if (!moreRef.current?.contains(event.target as Node)) setMore(false);
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
    { n: c.queue_waiting, label: "Waiting in queue", to: "/queue", perm: "queue.view", tone: "pending" as Tone },
    { n: c.queue_pharmacy, label: "Waiting for pharmacy", to: "/pharmacy", perm: "pharmacy.view", tone: "pending" as Tone },
    { n: c.pharmacy_queue, label: "Prescriptions to dispense", to: "/pharmacy", perm: "pharmacy.view", tone: "pending" as Tone },
    { n: c.pending_reports, label: "Lab orders open", to: "/lab", perm: "lab.view", tone: "pending" as Tone },
    { n: c.pending_bills, label: "Draft bills", to: "/billing", perm: "billing.view", tone: "pending" as Tone },
    { n: c.bills_due, label: "Bills with a balance", to: "/billing", perm: "billing.view", tone: "pending" as Tone },
    { n: c.low_stock, label: "Low stock", to: "/inventory/low", perm: "inventory.view", tone: "pending" as Tone },
    { n: c.expiring, label: "Expiring soon", to: "/inventory/expiring", perm: "inventory.view", tone: "pending" as Tone },
    { n: c.expired, label: "Expired stock", to: "/inventory/expired", perm: "inventory.view", tone: "critical" as Tone },
    { n: c.ot_open, label: "OT cases still open", to: "/ot", perm: "ot.view", tone: "pending" as Tone },
    { n: c.whatsapp_failed_today, label: "WhatsApp failed today", to: "/admin/integrations", perm: "whatsapp.configure", tone: "critical" as Tone },
    { n: c.leads_new, label: "New leads", to: "/leads", perm: "leads.view", tone: "pending" as Tone },
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

  return (
    <Page
      title="Today"
      note={data?.today ? formatDay(data.today) : ""}
      actions={
        <>
          {can("patient.create") && <Link className="btn primary" to="/register">Register patient</Link>}
          {can("opd.create") && <Link className="btn" to="/register">Create OPD</Link>}
          {can("queue.view") && <Link className="btn" to="/queue">Open queue</Link>}
          {can("billing.create") && <Link className="btn" to="/billing">Create bill</Link>}
          {!!moreItems.length && (
            <div className="more-wrap" ref={moreRef}>
              <button className="btn" type="button" aria-expanded={more} aria-haspopup="menu" onClick={() => setMore((open) => !open)}>
                More <Icon name="more" size={14} />
              </button>
              {more && (
                <div className="more-menu" role="menu">
                  {moreItems.map((item) => (
                    <Link key={item.to} role="menuitem" to={item.to} onClick={() => setMore(false)}>{item.label}</Link>
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      }
    >
      {loading && !data && <Loading label="Opening today's floor…" />}
      {error && !data && <ErrorState message={error} />}
      {data && (
        <div className="dash">
          <div className="context-strip">
            {data.hospital?.name && (
              <span className="context-chip">
                <Icon name="admissions" size={14} />
                <span>{data.hospital.name}{data.hospital.city ? ` · ${data.hospital.city}` : ""}</span>
              </span>
            )}
            {can("health.view") && (
              <Link className={`context-chip ${healthTone(data.health_overall)}`} to="/admin/health">
                <span className="dot" />
                <span>System {healthLabel(data.health_overall)}{data.health_at ? ` · ${when(data.health_at)}` : ""}</span>
              </Link>
            )}
            {(can("whatsapp.configure") || can("whatsapp.send")) && (
              can("whatsapp.configure") ? (
                <Link className={`context-chip ${data.whatsapp?.state === "connected" ? "ok" : "wait"}`} to="/admin/integrations">
                  <span className="dot" />
                  <span>WhatsApp {waLabel(data.whatsapp?.state)}</span>
                </Link>
              ) : (
                <span className="context-chip wait">
                  <span className="dot" />
                  <span>WhatsApp {waLabel(data.whatsapp?.state)}</span>
                </span>
              )
            )}
            {can("backup.view") && data.backup && (
              <Link className="context-chip ok" to="/admin/backups">
                <span className="dot" />
                <span>Backup {String(data.backup.status || "").replaceAll("_", " ")} · {when(data.backup.started_at)}{data.backup.cloud_status ? ` · cloud ${String(data.backup.cloud_status).replaceAll("_", " ")}` : ""}</span>
              </Link>
            )}
            {can("backup.view") && !data.backup && (
              <Link className="context-chip wait" to="/admin/backups">
                <span className="dot" />
                <span>No backup yet</span>
              </Link>
            )}
          </div>

          {(clinical || financial || stock) && (
            <div className="kpi-groups">
              {clinical && (
                <section className="panel">
                  <Head icon="patients" title="Clinical" to={can("queue.view") ? "/queue" : "/patients"} />
                  <div className="metric-grid">
                    {can("patient.view") && <Metric to="/patients" label="Patients today" value={num(c.patients_today)} hint={versus(c.patients_today, c.patients_yesterday)} tone="normal" />}
                    {can("opd.view") && <Metric to={can("queue.view") ? "/queue" : "/patients"} label="OPD today" value={num(c.opd_today)} hint={versus(c.opd_today, c.opd_yesterday)} tone="normal" />}
                    {can("queue.view") && <Metric to="/queue" label="Waiting" value={num(c.queue_waiting)} tone={num(c.queue_waiting) ? "pending" : "normal"} />}
                    {(can("queue.view") || can("consultation.create")) && <Metric to={can("consultation.create") ? "/doctor" : "/queue"} label="In consultation" value={num(c.queue_consulting)} tone={num(c.queue_consulting) ? "normal" : ""} />}
                    {showAdmissions && <Metric to="/admissions" label="Admitted now" value={num(c.admissions_active)} tone="normal" />}
                    {showBeds && c.beds_configured && <Metric to="/beds" label="Beds available" value={num(c.beds_available)} hint={`${num(c.beds_occupied)} occupied`} tone={num(c.beds_available) ? "done" : "pending"} />}
                  </div>
                </section>
              )}
              {financial && (
                <section className="panel">
                  <Head icon="billing" title="Money" to="/billing" />
                  <div className="metric-grid">
                    <Metric to="/billing" label="Collected today" value={money(c.revenue_paise)} hint={versus(c.revenue_paise, c.revenue_yesterday_paise, true)} tone={num(c.revenue_paise) ? "done" : ""} />
                    <Metric to="/billing" label="Outstanding" value={money(c.outstanding_paise)} tone={num(c.outstanding_paise) ? "pending" : "done"} />
                    <Metric to="/billing" label="Draft bills" value={num(c.pending_bills)} tone={num(c.pending_bills) ? "pending" : "done"} />
                    <Metric to="/billing" label="Balances due" value={num(c.bills_due)} hint={num(c.bills_partial) ? `${num(c.bills_partial)} partial` : ""} tone={num(c.bills_due) ? "pending" : "done"} />
                    {num(c.refunds_paise) > 0 && <Metric to="/billing" label="Refunds today" value={money(c.refunds_paise)} tone="critical" />}
                  </div>
                </section>
              )}
              {stock && (
                <section className="panel">
                  <Head icon="inventory" title="Stock" to="/inventory" />
                  <div className="metric-grid">
                    <Metric to="/inventory/low" label="Low stock" value={num(c.low_stock)} tone={num(c.low_stock) ? "pending" : "done"} />
                    <Metric to="/inventory/expiring" label="Expiring soon" value={num(c.expiring)} tone={num(c.expiring) ? "pending" : "done"} />
                    <Metric to="/inventory/expired" label="Expired" value={num(c.expired)} tone={num(c.expired) ? "critical" : "done"} />
                    {can("pharmacy.view") && <Metric to="/pharmacy" label="To dispense" value={num(c.pharmacy_queue)} tone={num(c.pharmacy_queue) ? "pending" : ""} />}
                  </div>
                </section>
              )}
            </div>
          )}

          {!!flow.length && (
            <section className="panel">
              <Head icon="opd" title="Today's flow" />
              <div className="ops-flow">
                {flow.map((step) => (
                  <Link key={step.label} className={`metric ${step.tone || ""}`} to={step.to}>
                    <strong>{num(step.n)}</strong>
                    <span>{step.label}</span>
                  </Link>
                ))}
              </div>
            </section>
          )}

          <div className="board">
            {(can("queue.view_all") || (data.queue || []).length > 0) && (
              <section className="panel span-2">
                <Head icon="queue" title="Live queue" to="/queue" />
                {(data.queue || []).length === 0 ? <Quiet text="No open tokens." /> : (
                  <div className="table-wrap">
                    <table className="data">
                      <thead><tr><th>Token</th><th>Patient</th><th>Doctor</th><th>Status</th><th></th></tr></thead>
                      <tbody>
                        {data.queue.map((row: any) => (
                          <tr key={row.id}>
                            <td><span className="token">{token(row.token_no)}</span></td>
                            <td><PatientLink id={row.patient_id} name={row.patient_name} /></td>
                            <td>{row.doctor_name || "—"}</td>
                            <td><Status value={row.status} /></td>
                            <td>{can("consultation.create") && row.encounter_id ? <Link to={`/consult/${row.encounter_id}`}>Open</Link> : <Link to="/queue">Queue</Link>}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            )}

            {can("consultation.create") && (!can("queue.view_all") || (data.my_queue || []).length > 0) && (
              <section className="panel">
                <Head icon="doctor" title="Your patients" to="/doctor" />
                {(data.my_queue || []).length === 0 ? <Quiet text="Nothing is assigned to you." /> : (
                  <ul className="plain-list">
                    {data.my_queue.map((row: any) => (
                      <li key={row.id}>
                        <span><span className="token">{token(row.token_no)}</span> {row.patient_name}</span>
                        {row.encounter_id ? <Link to={`/consult/${row.encounter_id}`}>Consult</Link> : <Status value={row.status} />}
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            )}

            {can("queue.view_all") && (
              <section className="panel">
                <Head icon="doctor" title="Doctor activity" to="/queue" />
                {(data.doctors || []).length === 0 ? <Quiet text="No doctor has an open token." /> : (
                  <ul className="plain-list">
                    {data.doctors.map((row: any) => (
                      <li key={row.id}>
                        <span>{row.name || "Doctor"}</span>
                        <span className={num(row.consulting) ? "metric-note normal" : "metric-note pending"}>{num(row.consulting) ? `${num(row.consulting)} consulting` : `${num(row.open_n)} open`}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            )}

            <section className={`panel ${attention.some((item) => item.tone === "critical") ? "critical" : attention.length ? "pending" : ""}`}>
              <Head icon="reports" title="Needs attention" />
              {attention.length === 0 ? <Quiet text="Nothing is waiting on this desk." /> : (
                <ul className="plain-list">
                  {attention.map((item) => (
                    <li key={item.label}>
                      <Link to={item.to}>{item.label}</Link>
                      <span className={`count ${item.tone}`}>{num(item.n)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            {(showAdmissions || showBeds) && (
              <section className={`panel ${showBeds && !c.beds_configured ? "pending" : ""}`}>
                <Head icon="beds" title="Admissions and beds" to={showBeds ? "/beds" : "/admissions"} />
                {showAdmissions && (
                  <ul className="plain-list">
                    <li><Link to="/admissions">Admitted now</Link><span className="count normal">{num(c.admissions_active)}</span></li>
                    <li><Link to="/admissions">Admitted today</Link><span className="count">{num(c.admissions_today)}</span></li>
                    <li><Link to="/admissions">Discharged today</Link><span className="count done">{num(c.discharges_today)}</span></li>
                  </ul>
                )}
                {showBeds && !c.beds_configured && (
                  <div className="bed-alert">
                    <strong>Bed master not configured</strong>
                    <p>Hospital beds are not on file. Sample install beds are not counted as capacity.</p>
                    {can("master.manage") && <Link className="btn small primary" to="/admin/master?section=beds">Configure beds</Link>}
                  </div>
                )}
                {showBeds && c.beds_configured && (
                  <ul className="plain-list">
                    <li><Link to="/beds">Available</Link><span className="count done">{num(c.beds_available)}</span></li>
                    <li><Link to="/beds">Occupied</Link><span className="count pending">{num(c.beds_occupied)}</span></li>
                    <li><Link to="/beds">Blocked</Link><span className="count">{num(c.beds_blocked)}</span></li>
                    {(data.wards || []).map((ward: any) => (
                      <li key={ward.ward}><Link to="/beds">{ward.ward}</Link><span className="muted">{num(ward.occupied)} / {num(ward.total)}</span></li>
                    ))}
                  </ul>
                )}
              </section>
            )}

            {can("ot.view") && (
              <section className="panel">
                <Head icon="ot" title="Operation theatre" to="/ot" />
                {(data.ot || []).length === 0 ? <Quiet text="No OT cases today." /> : (
                  <ul className="plain-list">
                    {data.ot.map((row: any) => (
                      <li key={row.id}>
                        <Link to={`/ot/${row.id}`}>{row.procedure_name || "OT case"}<small>{row.patient_name}{row.surgeon_name ? ` · ${row.surgeon_name}` : ""}</small></Link>
                        <Status value={row.status} />
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            )}

            {can("lab.view") && (
              <section className="panel">
                <Head icon="lab" title="Laboratory" to="/lab" />
                {(data.lab || []).length === 0 ? <Quiet text="No open lab orders." /> : (
                  <ul className="plain-list">
                    {data.lab.map((row: any) => (
                      <li key={row.id}>
                        <Link to="/lab">{row.test_name || "Lab order"}<small>{row.patient_name}</small></Link>
                        <Status value={row.status} />
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            )}

            {financial && (
              <section className="panel">
                <Head icon="billing" title="Billing" to="/billing" />
                {(data.bills || []).length === 0 ? <Quiet text="No bills yet." /> : (
                  <div className="table-wrap">
                    <table className="data">
                      <thead><tr><th>Bill</th><th>Patient</th><th>Status</th><th className="num">Due</th></tr></thead>
                      <tbody>
                        {data.bills.map((row: any) => (
                          <tr key={row.id}>
                            <td><Link to={`/billing/${row.id}`}>{row.number || "Draft"}</Link></td>
                            <td>{row.patient_name}</td>
                            <td><Status value={row.status === "DRAFT" ? "DRAFT" : row.payment_status || row.status} /></td>
                            <td className="num">{money(row.due_paise)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            )}

            {(can("pharmacy.view") || stock) && (
              <section className="panel">
                <Head icon="pharmacy" title="Pharmacy and inventory" to={can("pharmacy.view") ? "/pharmacy" : "/inventory"} />
                <ul className="plain-list">
                  {can("pharmacy.view") && <li><Link to="/pharmacy">Waiting for pharmacy</Link><span className={`count ${num(c.queue_pharmacy) ? "pending" : ""}`}>{num(c.queue_pharmacy)}</span></li>}
                  {can("pharmacy.view") && <li><Link to="/pharmacy">Prescriptions to dispense</Link><span className={`count ${num(c.pharmacy_queue) ? "pending" : ""}`}>{num(c.pharmacy_queue)}</span></li>}
                  {stock && <li><Link to="/inventory/movements">Issues today</Link><span className="count">{num(c.pharmacy_issues_today)}</span></li>}
                  {stock && <li><Link to="/inventory/low">Low stock</Link><span className={`count ${num(c.low_stock) ? "pending" : "done"}`}>{num(c.low_stock)}</span></li>}
                  {stock && <li><Link to="/inventory/expiring">Expiring soon</Link><span className={`count ${num(c.expiring) ? "pending" : "done"}`}>{num(c.expiring)}</span></li>}
                  {stock && <li><Link to="/inventory/expired">Expired</Link><span className={`count ${num(c.expired) ? "critical" : "done"}`}>{num(c.expired)}</span></li>}
                </ul>
                {stock && !!(data.stock?.low || []).length && <p className="quiet">Low: {data.stock.low.map((row: any) => row.name).filter(Boolean).join(", ")}</p>}
                {stock && !!(data.stock?.expiring || []).length && <p className="quiet">Expiring: {data.stock.expiring.map((row: any) => row.name).filter(Boolean).join(", ")}</p>}
                {stock && !!(data.stock?.expired || []).length && <p className="quiet">Expired: {data.stock.expired.map((row: any) => row.name).filter(Boolean).join(", ")}</p>}
              </section>
            )}

            {can("patient.view") && (
              <section className="panel span-2">
                <Head icon="patients" title="Today's patients" to="/patients" label="View all" />
                <p className="quiet">{num(c.patients_today)} registered today{c.opd_today != null ? ` · ${num(c.opd_today)} OPD encounters` : ""}{c.admissions_active != null && (can("admission.view") || can("ipd.admission.view")) ? ` · ${num(c.admissions_active)} inpatients` : ""}{c.emergency_active != null ? ` · ${num(c.emergency_active)} emergency` : ""}</p>
                {(data.today_patients || []).length === 0 ? <Quiet text="No patients registered or seen today." /> : (
                  <div className="table-wrap">
                    <table className="data">
                      <thead><tr><th>Patient</th><th>ID</th><th>Encounter</th><th>Status</th></tr></thead>
                      <tbody>
                        {data.today_patients.map((row: any) => (
                          <tr key={row.id}>
                            <td><PatientLink id={row.id} name={row.name} /></td>
                            <td className="pid">{row.id}</td>
                            <td>{row.encounter_id ? <Link to={`/consult/${row.encounter_id}`}>{row.encounter_id}</Link> : "—"}</td>
                            <td><Status value={row.care_label || row.care_code} /></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                <p className="quiet"><Link to="/patients">Open patients</Link></p>
              </section>
            )}

            {can("patient.view") && (
              <section className="panel">
                <Head icon="patients" title="Recent patients" to="/patients" />
                {(data.patients || []).length === 0 ? <Quiet text="No visits yet." /> : (
                  <ul className="plain-list">
                    {data.patients.map((row: any) => (
                      <li key={row.encounter_id || row.id}>
                        <PatientLink id={row.id} name={row.name} />
                        <span className="muted">{row.doctor_name || when(row.arrived_at)}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            )}

            {can("document.view") && (
              <section className="panel">
                <Head icon="documents" title="Documents" to="/documents" />
                {(data.documents || []).length === 0 ? <Quiet text={num(c.documents_today) ? `${num(c.documents_today)} uploaded today.` : "No documents uploaded."} /> : (
                  <>
                  {num(c.documents_today) > 0 && <p className="quiet">{num(c.documents_today)} uploaded today.</p>}
                  <ul className="plain-list">
                    {data.documents.map((row: any) => (
                      <li key={row.id}>
                        <span>{row.title || row.document_type}<small>{row.patient_name || "Unlinked"}</small></span>
                        <span className="muted">{when(row.uploaded_at)}</span>
                      </li>
                    ))}
                  </ul>
                  </>
                )}
              </section>
            )}

            {can("audit.view") && (
              <section className="panel">
                <Head icon="audit" title="Activity" to="/admin/audit" />
                {(data.activity || []).length === 0 ? <Quiet text="No activity recorded." /> : (
                  <ul className="plain-list">
                    {data.activity.map((row: any, index: number) => (
                      <li key={`${row.at}-${row.action}-${index}`}>
                        <span>{actionLabel(row.action)}<small>{row.username || row.entity}</small></span>
                        <span className="muted">{when(row.at)}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            )}

            {(can("whatsapp.configure") || can("whatsapp.send")) && (
              <section className="panel">
                <Head icon="whatsapp" title="WhatsApp" to={can("whatsapp.configure") ? "/admin/integrations" : undefined} />
                <p className="quiet">{data.whatsapp?.state === "not_configured" ? "Not connected. OpenWA is not configured." : `WhatsApp ${waLabel(data.whatsapp?.state)}.`}</p>
                <ul className="plain-list">
                  <li><span>Queued</span><span className="count">{num(c.whatsapp_queued)}</span></li>
                  <li><span>Sent today</span><span className="count done">{num(c.whatsapp_sent_today)}</span></li>
                  <li><span>Failed today</span><span className={`count ${num(c.whatsapp_failed_today) ? "critical" : ""}`}>{num(c.whatsapp_failed_today)}</span></li>
                </ul>
              </section>
            )}

            {can("backup.view") && (
              <section className="panel">
                <Head icon="backup" title="Backup" to="/admin/backups" />
                {data.backup ? (
                  <ul className="plain-list">
                    <li><span>Status</span><Status value={data.backup.status} /></li>
                    <li><span>Started</span><span className="muted">{when(data.backup.started_at)}</span></li>
                    <li><span>Cloud</span><span className="muted">{data.backup.cloud_status || "—"}</span></li>
                  </ul>
                ) : <Quiet text="No backup yet." />}
              </section>
            )}

            {can("health.view") && (
              <section className="panel">
                <Head icon="system" title="System health" to="/admin/health" />
                <p className={`quiet health-line ${healthTone(data.health_overall)}`}>
                  <span className="dot" /> {healthLabel(data.health_overall)}
                  {data.health_at ? ` · checked ${when(data.health_at)}` : ""}
                </p>
              </section>
            )}
          </div>
        </div>
      )}
    </Page>
  );
}
