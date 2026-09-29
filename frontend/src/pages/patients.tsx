import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, getToken } from "../api";
import { Icon } from "../icons";
import { useApp } from "../store";
import { ErrorState, Field, Modal, Page } from "../ui";

type Patient = {
  id: string;
  name: string;
  gender?: string;
  age_display?: string;
  primary_phone?: string;
  guardian_name?: string;
  department_name?: string;
  care_code?: string;
  care_label?: string;
  last_encounter_id?: string;
  last_encounter_at?: string;
  is_sample?: number;
};

type Registry = {
  items: Patient[];
  total: number;
  page: number;
  page_size: number;
  summary?: {
    active?: number;
    registered_today?: number;
    opd_today?: number;
    waiting?: number;
    inpatients?: number;
    emergency?: number;
  };
  beds?: { configured?: boolean; occupancy_pct?: number | null } | null;
};

const CARE = [
  ["", "All statuses"],
  ["ACTIVE", "Active"],
  ["INACTIVE", "Inactive"],
  ["OPD", "Active OPD"],
  ["WAITING", "Waiting"],
  ["IN_CONSULTATION", "In consultation"],
  ["ADMITTED", "Admitted"],
  ["DISCHARGED", "Discharged"],
  ["EMERGENCY", "Emergency"],
];

function phone(value?: string) {
  if (!value) return "—";
  const digits = String(value).replace(/\D/g, "");
  if (digits.length === 10) return `+91 ${digits}`;
  return value;
}

function shortDay(iso?: string) {
  if (!iso) return "";
  const [year, month, day] = iso.slice(0, 10).split("-").map(Number);
  if (!year || !month || !day) return iso.slice(0, 10);
  return new Date(year, month - 1, day).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

function initials(name?: string) {
  const parts = (name || "").trim().split(/\s+/).filter(Boolean);
  return ((parts[0]?.[0] || "") + (parts[1]?.[0] || "")).toUpperCase() || "?";
}

function downloadCsv(rows: Patient[]) {
  const header = ["Patient ID", "Name", "Phone", "Guardian", "Age", "Gender", "Status", "Last encounter"];
  const body = rows.map((row) => [row.id, row.name, row.primary_phone || "", row.guardian_name || "", row.age_display || "", row.gender || "", row.care_label || "", row.last_encounter_id || ""].map((cell) => `"${String(cell).replaceAll("\"", "\"\"")}"`).join(","));
  const blob = new Blob([[header.join(","), ...body].join("\n")], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "selected-patients.csv";
  link.click();
  URL.revokeObjectURL(url);
}

function count(value?: number) {
  return new Intl.NumberFormat("en-IN").format(Number(value) || 0);
}

function parseCsv(text: string) {
  const lines = text.replace(/^\uFEFF/, "").split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  if (lines.length < 2) return [];
  const headers = lines[0].split(",").map((cell) => cell.trim().toLowerCase().replace(/\s+/g, "_"));
  return lines.slice(1).map((line) => {
    const cells = line.split(",").map((cell) => cell.trim().replace(/^"|"$/g, ""));
    const row: Record<string, string> = {};
    headers.forEach((header, index) => {
      row[header] = cells[index] || "";
    });
    return {
      name: row.name || row.patient_name || "",
      gender: row.gender || "",
      primary_phone: row.primary_phone || row.phone || row.mobile || "",
      guardian_name: row.guardian_name || row.guardian || "",
      guardian_phone: row.guardian_phone || "",
      dob: row.dob || row.date_of_birth || "",
      age_at_registration: row.age_at_registration || row.age || "",
      address: row.address || "",
    };
  }).filter((row) => row.name);
}

export function Patients() {
  const can = useApp((s) => s.can);
  const toast = useApp((s) => s.toast);
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState(params.get("q") || "");
  const [debounced, setDebounced] = useState(q);
  const [data, setData] = useState<Registry | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [menu, setMenu] = useState("");
  const [importOpen, setImportOpen] = useState(false);
  const [messageOpen, setMessageOpen] = useState(false);
  const [message, setMessage] = useState("");
  const [view, setView] = useState(() => localStorage.getItem("aipf-patient-view") === "cards" ? "cards" : "table");
  const { data: departments } = useDepartments();

  const page = Math.max(1, Number(params.get("page") || 1));
  const sort = params.get("sort") || "registered";
  const direction = params.get("direction") === "asc" ? "asc" : "desc";
  const filters = {
    department_id: params.get("department_id") || "",
    status: params.get("status") || "",
    gender: params.get("gender") || "",
    age: params.get("age") || "",
    registered: params.get("registered") || "",
  };

  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(q.trim()), 280);
    return () => window.clearTimeout(id);
  }, [q]);

  const path = useMemo(() => {
    const query = new URLSearchParams();
    query.set("page", String(page));
    query.set("page_size", "50");
    query.set("sort", sort);
    query.set("direction", direction);
    if (debounced) query.set("q", debounced);
    Object.entries(filters).forEach(([key, value]) => {
      if (value) query.set(key, value);
    });
    return `/api/patients?${query}`;
  }, [page, sort, direction, debounced, filters.department_id, filters.status, filters.gender, filters.age, filters.registered]);

  useEffect(() => {
    let live = true;
    setRefreshing(Boolean(data));
    if (!data) setLoading(true);
    api<Registry>(path)
      .then((next) => {
        if (!live) return;
        setData(next);
        setError("");
        setSelected((ids) => ids.filter((id) => next.items.some((item) => item.id === id)));
      })
      .catch((err: Error) => {
        if (live && !data) setError(err.message || "Unable to load patients.");
        if (live && data) toast(err.message || "Unable to refresh patients.", "bad");
      })
      .finally(() => {
        if (live) {
          setLoading(false);
          setRefreshing(false);
        }
      });
    return () => {
      live = false;
    };
  }, [path]);

  useEffect(() => {
    let timer: number | undefined;
    const onLive = (event: Event) => {
      const name = String((event as CustomEvent).detail?.event || "");
      if (!/patient|queue|admission|encounter|clinical/.test(name)) return;
      if (timer) window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        api<Registry>(path).then(setData).catch(() => undefined);
      }, 1500);
    };
    window.addEventListener("aipf-live", onLive);
    return () => {
      window.removeEventListener("aipf-live", onLive);
      if (timer) window.clearTimeout(timer);
    };
  }, [path]);

  function setFilter(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    next.set("page", "1");
    setParams(next);
  }

  function resetFilters() {
    setQ("");
    setDebounced("");
    setParams({});
  }

  function toggleSort(next: string) {
    const query = new URLSearchParams(params);
    if (sort === next) query.set("direction", direction === "asc" ? "desc" : "asc");
    else {
      query.set("sort", next);
      query.set("direction", next === "name" ? "asc" : "desc");
    }
    query.set("page", "1");
    setParams(query);
  }

  function goPage(next: number) {
    const query = new URLSearchParams(params);
    query.set("page", String(next));
    setParams(query);
  }

  const items = data?.items || [];
  const total = data?.total || 0;
  const size = data?.page_size || 50;
  const from = total ? (page - 1) * size + 1 : 0;
  const to = Math.min(page * size, total);
  const pages = Math.max(1, Math.ceil(total / size));
  const summary = data?.summary || {};
  const filtered = Boolean(debounced || Object.values(filters).some(Boolean));
  const allChecked = items.length > 0 && items.every((item) => selected.includes(item.id));

  async function exportList() {
    const query = path.split("?")[1] || "";
    const response = await fetch(`/api/patients/export?${query}`, { headers: { Authorization: `Bearer ${getToken()}` } });
    if (!response.ok) {
      toast("The list could not be exported.", "bad");
      return;
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "patients.csv";
    link.click();
    URL.revokeObjectURL(url);
  }

  async function deactivate() {
    if (!selected.length) return;
    if (!window.confirm(`Mark ${selected.length} patient${selected.length === 1 ? "" : "s"} inactive? Their history stays on the record.`)) return;
    try {
      await api("/api/patients/status", { method: "POST", body: JSON.stringify({ ids: selected, status: "INACTIVE" }) });
      toast("Patients marked inactive.", "ok");
      setSelected([]);
      const next = await api<Registry>(path);
      setData(next);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Those records were not updated.", "bad");
    }
  }

  async function sendSelected() {
    if (!message.trim()) return;
    let sent = 0;
    for (const id of selected) {
      try {
        await api("/api/whatsapp/messages", { method: "POST", body: JSON.stringify({ patient_id: id, text: message, confirm: true }) });
        sent += 1;
      } catch (err) {
        toast(err instanceof Error ? err.message : "WhatsApp did not accept the message.", "bad");
        break;
      }
    }
    if (sent) toast(`${sent} message${sent === 1 ? "" : "s"} handed to the provider.`, "ok");
    setMessageOpen(false);
    setMessage("");
  }

  return (
    <Page
      title="Patients"
      note="Clinical Registry / UHID Master Archive. Register and manage hospital patients, medical history, encounters and demographics."
      actions={
        <>
          <button className="btn" type="button" onClick={exportList}>Export list</button>
          {can("patient.create") && <button className="btn" type="button" onClick={() => setImportOpen(true)}>Import records</button>}
          {can("patient.create") && <Link className="btn primary" to="/register">+ New patient registration</Link>}
        </>
      }
    >
      <div className="registry">
        <div className="reg-stats">
          <Stat label="Total active patients" value={summary.active} hint={summary.registered_today ? `+${count(summary.registered_today)} today` : "None registered today"} to="/patients" />
          {summary.opd_today != null && <Stat label="OPD encounters" value={summary.opd_today} hint={summary.waiting != null ? `${count(summary.waiting)} waiting` : ""} to="/queue" />}
          {summary.inpatients != null && <Stat label="Inpatient admissions" value={summary.inpatients} hint={data?.beds?.configured && data.beds.occupancy_pct != null ? `${data.beds.occupancy_pct}% occupancy` : data?.beds ? "Bed master not configured" : ""} to="/admissions" />}
          {summary.emergency != null && <Stat label="Emergency admissions" value={summary.emergency} hint="Current emergency load" to="/admissions" />}
        </div>

        <form className="reg-search" onSubmit={(event) => event.preventDefault()}>
          <Icon name="search" size={16} />
          <input
            aria-label="Search patients"
            placeholder="Search by patient name, Patient ID, mobile, or guardian"
            value={q}
            onChange={(event) => {
              setQ(event.target.value);
              if (page !== 1) goPage(1);
            }}
          />
          {refreshing && <span className="muted">Updating</span>}
        </form>

        <div className="reg-filters">
          <select aria-label="Department" value={filters.department_id} onChange={(event) => setFilter("department_id", event.target.value)}>
            <option value="">Department</option>
            {(departments || []).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
          <select aria-label="Patient status" value={filters.status} onChange={(event) => setFilter("status", event.target.value)}>
            {CARE.map(([value, label]) => <option key={value || "all"} value={value}>{label}</option>)}
          </select>
          <select aria-label="Gender" value={filters.gender} onChange={(event) => setFilter("gender", event.target.value)}>
            <option value="">Gender</option>
            <option>Female</option>
            <option>Male</option>
            <option>Other</option>
          </select>
          <select aria-label="Age" value={filters.age} onChange={(event) => setFilter("age", event.target.value)}>
            <option value="">Age</option>
            <option value="0-17">0–17</option>
            <option value="18-39">18–39</option>
            <option value="40-59">40–59</option>
            <option value="60+">60+</option>
            <option value="unknown">Age not recorded</option>
          </select>
          <input aria-label="Registered date" type="date" value={filters.registered} onChange={(event) => setFilter("registered", event.target.value)} />
          <button className="btn small" type="button" onClick={resetFilters}>Reset filters</button>
          <div className="reg-switch" role="group" aria-label="Directory view">
            <button type="button" className={view === "table" ? "on" : ""} onClick={() => { setView("table"); localStorage.setItem("aipf-patient-view", "table"); }}>Table</button>
            <button type="button" className={view === "cards" ? "on" : ""} onClick={() => { setView("cards"); localStorage.setItem("aipf-patient-view", "cards"); }}>Cards</button>
          </div>
        </div>

        {loading && !data && <div className="panel"><div className="skeleton-rows" aria-hidden="true"><span /><span /><span /><span /><span /></div></div>}
        {error && !data && <ErrorState message={error} />}
        {data && !items.length && (
          <div className="empty">
            <p>{filtered ? "No matching patients" : "No patients found"}</p>
            <p className="muted">{filtered ? "Search by Patient ID, name or phone." : "Try changing your search or filters."}</p>
            <button className="btn" type="button" onClick={resetFilters}>{filtered ? "Clear search" : "Clear filters"}</button>
          </div>
        )}

        {!!items.length && view === "table" && (
          <div className="panel reg-table-wrap">
            <div className="table-wrap">
              <table className="data registry-table">
                <thead>
                  <tr>
                    <th><input type="checkbox" aria-label="Select patients on this page" checked={allChecked} onChange={() => setSelected(allChecked ? [] : items.map((item) => item.id))} /></th>
                    <th><button type="button" className="sort" onClick={() => toggleSort("name")}>Patient</button></th>
                    <th><button type="button" className="sort" onClick={() => toggleSort("id")}>Patient ID</button></th>
                    <th>Phone & guardian</th>
                    <th>Age / gender</th>
                    <th className="hide-tablet">Blood group</th>
                    <th><button type="button" className="sort" onClick={() => toggleSort("encounter")}>Last encounter</button></th>
                    <th>Current status</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((patient) => (
                    <tr key={patient.id} className="click-row" tabIndex={0} onClick={() => navigate(`/patients/${patient.id}`)} onKeyDown={(event) => { if (event.key === "Enter") navigate(`/patients/${patient.id}`); }}>
                      <td onClick={(event) => event.stopPropagation()}><input type="checkbox" aria-label={`Select ${patient.name}`} checked={selected.includes(patient.id)} onChange={() => setSelected((ids) => ids.includes(patient.id) ? ids.filter((id) => id !== patient.id) : [...ids, patient.id])} /></td>
                      <td>
                        <span className="identity">
                          <span className="avatar" aria-hidden="true">{initials(patient.name)}</span>
                          <span>{patient.name}{patient.is_sample ? <span className="sample-badge">SAMPLE</span> : null}</span>
                        </span>
                      </td>
                      <td className="pid">{patient.id}</td>
                      <td>{phone(patient.primary_phone)}<small className="muted block">{patient.guardian_name ? `Guardian: ${patient.guardian_name}` : "Guardian: —"}</small></td>
                      <td>{patient.age_display || "—"} / {patient.gender || "—"}</td>
                      <td className="hide-tablet">—</td>
                      <td>{patient.last_encounter_id ? <><span>{shortDay(patient.last_encounter_at)}</span><small className="muted block">{patient.last_encounter_id}</small></> : "—"}</td>
                      <td><span className={`reg-badge ${patient.care_code || ""}`}>{patient.care_label || "—"}</span></td>
                      <td onClick={(event) => event.stopPropagation()}>
                        <div className="row-actions">
                          <Link className="btn small" to={`/patients/${patient.id}`}>View patient</Link>
                          {(can("opd.view") || can("opd.create")) && <Link className="btn small" to={patient.last_encounter_id && can("consultation.create") ? `/consult/${patient.last_encounter_id}` : `/register?patient=${patient.id}`}>Open OPD</Link>}
                          <button className="btn small" type="button" aria-label={`More actions for ${patient.name}`} aria-expanded={menu === patient.id} onClick={() => setMenu(menu === patient.id ? "" : patient.id)}><Icon name="more_vert" size={14} /></button>
                          {menu === patient.id && <RowMenu patient={patient} can={can} onClose={() => setMenu("")} />}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {!!items.length && (
          <div className={view === "cards" ? "reg-cards" : "reg-cards mobile-only"}>
            {items.map((patient) => (
              <article key={patient.id} className="reg-card">
                <button type="button" className="reg-card-main" onClick={() => navigate(`/patients/${patient.id}`)}>
                  <span className="avatar">{initials(patient.name)}</span>
                  <span>
                    <strong>{patient.name}</strong>
                    <span className="pid">{patient.id}</span>
                    <span className="muted">{patient.age_display || "—"} / {patient.gender || "—"} · {phone(patient.primary_phone)}</span>
                    <span className="muted">{patient.guardian_name ? `Guardian: ${patient.guardian_name}` : "Guardian: —"}</span>
                    <span className="muted">{patient.last_encounter_id ? `${patient.last_encounter_id} · ${shortDay(patient.last_encounter_at)}` : "No encounter"}</span>
                  </span>
                </button>
                <div className="reg-card-foot">
                  <span className={`reg-badge ${patient.care_code || ""}`}>{patient.care_label || "—"}</span>
                  <span className="row-actions" onClick={(event) => event.stopPropagation()}>
                    <Link className="btn small" to={`/patients/${patient.id}`}>View</Link>
                    {(can("opd.view") || can("opd.create")) && <Link className="btn small" to={`/register?patient=${patient.id}`}>OPD</Link>}
                    {can("billing.view") && <Link className="btn small" to={`/billing?patient=${patient.id}`}>Billing</Link>}
                  </span>
                </div>
              </article>
            ))}
          </div>
        )}

        {!!total && (
          <div className="reg-page">
            <span>Showing {from}–{to} of {count(total)}</span>
            <div>
              <button className="btn small" type="button" disabled={page <= 1} onClick={() => goPage(page - 1)}>Previous</button>
              {Array.from({ length: pages }, (_, index) => index + 1).filter((n) => n === 1 || n === pages || Math.abs(n - page) <= 1).map((n) => (
                <button key={n} className={`btn small ${n === page ? "primary" : ""}`} type="button" onClick={() => goPage(n)}>{n}</button>
              ))}
              <button className="btn small" type="button" disabled={page >= pages} onClick={() => goPage(page + 1)}>Next</button>
            </div>
          </div>
        )}

        {!!selected.length && (
          <div className="reg-bulk" role="region" aria-label="Selected patients">
            <strong>{selected.length} patient{selected.length === 1 ? "" : "s"} selected</strong>
            {can("whatsapp.send") && <button className="btn small" type="button" onClick={() => setMessageOpen(true)}>Send WhatsApp</button>}
            <button className="btn small" type="button" onClick={() => downloadCsv(items.filter((item) => selected.includes(item.id)))}>Export</button>
            {can("patient.edit") && <button className="btn small" type="button" onClick={deactivate}>Deactivate</button>}
            <button className="btn small" type="button" onClick={() => setSelected([])}>Clear selection</button>
          </div>
        )}
      </div>

      {importOpen && (
        <Modal title="Import records" onClose={() => setImportOpen(false)} footer={<span className="muted">A matching phone does not merge patients. Those rows are skipped.</span>}>
          <Field label="CSV file">
            <input type="file" accept=".csv,text/csv" onChange={async (event) => {
              const file = event.target.files?.[0];
              if (!file) return;
              const rows = parseCsv(await file.text());
              if (!rows.length) {
                toast("The file had no patient rows.", "bad");
                return;
              }
              try {
                const result = await api<{ created: any[]; skipped: any[]; errors: any[] }>("/api/patients/import", { method: "POST", body: JSON.stringify({ rows }) });
                toast(`${result.created.length} registered, ${result.skipped.length} skipped as possible matches, ${result.errors.length} not imported.`, result.errors.length ? "warn" : "ok");
                setImportOpen(false);
                setData(await api<Registry>(path));
              } catch (err) {
                toast(err instanceof Error ? err.message : "Import did not complete.", "bad");
              }
            }} />
          </Field>
          <p className="muted">Columns: name, gender, phone, guardian, dob, age, address. Patient ID is assigned by the hospital. Nothing is merged automatically.</p>
        </Modal>
      )}
      {messageOpen && (
        <Modal title="Send WhatsApp" onClose={() => setMessageOpen(false)} footer={<button className="btn primary" type="button" disabled={!message.trim()} onClick={sendSelected}>Send to {selected.length}</button>}>
          <Field label="Message"><textarea value={message} onChange={(event) => setMessage(event.target.value)} /></Field>
          <p className="muted">Each selected patient is confirmed as the recipient. The hospital WhatsApp gateway must be connected.</p>
        </Modal>
      )}
    </Page>
  );
}

function Stat({ label, value, hint, to }: { label: string; value?: number; hint?: string; to: string }) {
  return (
    <Link className="reg-stat" to={to}>
      <span>{label}</span>
      <strong>{value == null ? "—" : count(value)}</strong>
      {hint ? <small>{hint}</small> : null}
    </Link>
  );
}

function RowMenu({ patient, can, onClose }: { patient: Patient; can: (code: string) => boolean; onClose: () => void }) {
  const items = [
    { to: `/patients/${patient.id}`, label: "View patient", show: true },
    { to: `/register?patient=${patient.id}`, label: "Create new encounter", show: can("opd.create") },
    { to: `/billing?patient=${patient.id}`, label: "Billing", show: can("billing.view") },
    { to: `/patients/${patient.id}?tab=documents`, label: "Documents", show: can("document.view") },
    { to: `/patients/${patient.id}?tab=timeline`, label: "History", show: true },
  ].filter((item) => item.show);
  return (
    <div className="more-menu row-menu" role="menu">
      {items.map((item) => <Link key={item.label} role="menuitem" to={item.to} onClick={onClose}>{item.label}</Link>)}
    </div>
  );
}

function useDepartments() {
  const [items, setItems] = useState<{ id: string; name: string }[]>([]);
  useEffect(() => {
    api<{ items: { id: string; name: string }[] }>("/api/master/department").then((row) => setItems(row.items || [])).catch(() => undefined);
  }, []);
  return { data: items };
}
