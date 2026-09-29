import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, money, paise } from "../api";
import { Empty, Field, Page, run, useData } from "../ui";

const LISTS = [
  ["department", "Departments"],
  ["patient_category", "Patient categories"],
  ["payment_mode", "Payment modes"],
  ["document_type", "Document types"],
  ["condition", "Conditions"],
  ["procedure", "Procedures"],
  ["unit", "Units"],
];

const SECTIONS = ["lists", "opd", "services", "lab", "procedures", "theatres", "checklist", "wards", "rooms", "beds"];

function matches(text: string, q: string) {
  return !q || text.toLowerCase().includes(q.trim().toLowerCase());
}

function erase(path: string, label: string) {
  if (!window.confirm(`Permanently delete ${label}? This cannot be undone.`)) return;
  run(() => api(path, { method: "DELETE" }), "Deleted");
}

function flip(item: any, path: string, body: any, label: string) {
  const next = !item.active;
  if (!window.confirm(next ? `Reactivate ${label}? Historical records stay as they were.` : `Deactivate ${label}? It will not be offered for new work. Historical records stay.`)) return;
  run(() => api(path, { method: "PATCH", body: JSON.stringify({ ...body, active: next }) }), next ? "Reactivated" : "Deactivated");
}

export function MasterPage() {
  const [params, setParams] = useSearchParams();
  const section = SECTIONS.includes(params.get("section") || "") ? params.get("section")! : "lists";
  const [q, setQ] = useState("");
  function open(next: string) {
    setQ("");
    setParams({ section: next });
  }
  return (
    <Page title="Master Data" note="Clinical, billing, and infrastructure lists. Add, edit, or permanently delete an unused record. Deactivate one that history still uses.">
      <div className="tabs" role="tablist">
        {[["lists", "Lists"], ["opd", "OPD types"], ["services", "Services"], ["lab", "Lab tests"], ["procedures", "OT procedures"], ["theatres", "Theatres"], ["checklist", "OT checklist"], ["wards", "Wards"], ["rooms", "Rooms"], ["beds", "Beds"]].map(([id, label]) => (
          <button key={id} className={section === id ? "on" : ""} type="button" onClick={() => open(id)}>{label}</button>
        ))}
      </div>
      <input aria-label="Filter master data" placeholder="Search this list" value={q} onChange={(e) => setQ(e.target.value)} />
      {section === "lists" && <GenericLists q={q} />}
      {section === "opd" && <OpdTypes q={q} />}
      {section === "services" && <Services q={q} />}
      {section === "lab" && <LabTests q={q} />}
      {section === "procedures" && <Procedures q={q} />}
      {section === "theatres" && <Theatres q={q} />}
      {section === "checklist" && <Checklist q={q} />}
      {section === "wards" && <Wards q={q} />}
      {section === "rooms" && <Rooms q={q} />}
      {section === "beds" && <Beds q={q} />}
    </Page>
  );
}

function GenericLists({ q }: { q: string }) {
  const [type, setType] = useState("department");
  const { data } = useData<{ items: any[] }>(`/api/master/${type}?all=1`);
  const [name, setName] = useState("");
  const [editing, setEditing] = useState<any>(null);
  const rows = (data?.items || []).filter((item) => matches(item.name || "", q));
  return (
    <div className="grid-2">
      <div>
        <div className="tabs">
          {LISTS.map(([id, label]) => <button key={id} className={type === id ? "on" : ""} type="button" onClick={() => setType(id)}>{label}</button>)}
        </div>
        {!rows.length && <Empty text="Nothing matches." />}
        <table className="data">
          <thead><tr><th>Name</th><th>Code</th><th>Active</th><th></th></tr></thead>
          <tbody>
            {rows.map((item) => (
              <tr key={item.id}>
                <td>{item.name}</td>
                <td>{item.code || "—"}</td>
                <td>{item.active ? "Yes" : "No"}</td>
                <td className="row-actions">
                  <button className="btn small" type="button" onClick={() => setEditing(item)}>Edit</button>
                  <button className="btn small" type="button" onClick={() => flip(item, `/api/master/${type}/${item.id}`, { name: item.name, code: item.code, description: item.description, sort_order: item.sort_order }, item.name)}>{item.active ? "Deactivate" : "Activate"}</button>
                  <button className="btn small danger" type="button" onClick={() => erase(`/api/master/${type}/${item.id}`, item.name)}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="panel">
        <h2>{editing ? "Edit" : "Add"} {type.replaceAll("_", " ")}</h2>
        <div className="body">
          <Field label="Name"><input value={editing ? editing.name : name} onChange={(e) => editing ? setEditing({ ...editing, name: e.target.value }) : setName(e.target.value)} /></Field>
          <Field label="Code"><input value={editing?.code || ""} onChange={(e) => setEditing({ ...(editing || { name }), code: e.target.value })} /></Field>
          <Field label="Description"><input value={editing?.description || ""} onChange={(e) => setEditing({ ...(editing || { name }), description: e.target.value })} /></Field>
          <Field label="Sort"><input value={editing?.sort_order ?? ""} onChange={(e) => setEditing({ ...(editing || { name }), sort_order: e.target.value })} /></Field>
          <button className="btn primary" type="button" onClick={() => run(async () => {
            const body = { name: editing ? editing.name : name, code: editing?.code || "", description: editing?.description || "", sort_order: Number(editing?.sort_order || 0), active: editing ? Boolean(editing.active) : true };
            if (editing?.id) await api(`/api/master/${type}/${editing.id}`, { method: "PATCH", body: JSON.stringify(body) });
            else await api(`/api/master/${type}`, { method: "POST", body: JSON.stringify(body) });
            setName("");
            setEditing(null);
          }, editing?.id ? "Updated" : "Added")}>{editing?.id ? "Save" : "Add"}</button>
          {editing?.id && <button className="btn" type="button" onClick={() => setEditing(null)}>Cancel</button>}
        </div>
      </div>
    </div>
  );
}

function OpdTypes({ q }: { q: string }) {
  const { data } = useData<{ items: any[] }>("/api/opd/types?all=1");
  const [form, setForm] = useState<any>({ name: "", fee: "", days: "1" });
  const rows = (data?.items || []).filter((item) => matches(item.name || "", q));
  return (
    <Section title="OPD types" rows={rows} onSave={() => run(() => api(form.id ? `/api/opd/types/${form.id}` : "/api/opd/types", { method: form.id ? "PATCH" : "POST", body: JSON.stringify({ name: form.name, code: form.code, fee_paise: paise(form.fee), validity_days: Number(form.days || 1), description: form.description, services_included: form.services_included, departments: form.departments, sort_order: form.sort_order, active: form.active !== false }) }), form.id ? "OPD type updated" : "OPD type added")}>
      <table className="data">
        <thead><tr><th>Name</th><th className="num">Fee</th><th>Validity</th><th>Active</th><th></th></tr></thead>
        <tbody>{rows.map((item) => (
          <tr key={item.id}>
            <td>{item.name}</td>
            <td className="num">{money(item.fee_paise)}</td>
            <td>{item.validity_days} days</td>
            <td>{item.active ? "Yes" : "No"}</td>
            <td className="row-actions">
              <button className="btn small" type="button" onClick={() => setForm({ ...item, fee: (item.fee_paise || 0) / 100, days: item.validity_days })}>Edit</button>
              <button className="btn small" type="button" onClick={() => flip(item, `/api/opd/types/${item.id}`, { name: item.name, code: item.code, fee_paise: item.fee_paise, validity_days: item.validity_days, description: item.description, services_included: item.services_included, departments: item.departments, sort_order: item.sort_order }, item.name)}>{item.active ? "Deactivate" : "Activate"}</button>
              <button className="btn small danger" type="button" onClick={() => erase(`/api/opd/types/${item.id}`, item.name)}>Delete</button>
            </td>
          </tr>
        ))}</tbody>
      </table>
      <div className="grid-form">
        <Field label="Name"><input value={form.name || ""} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
        <Field label="Code"><input value={form.code || ""} onChange={(e) => setForm({ ...form, code: e.target.value })} /></Field>
        <Field label="Fee Rs"><input value={form.fee ?? ""} onChange={(e) => setForm({ ...form, fee: e.target.value })} /></Field>
        <Field label="Validity days"><input value={form.days ?? ""} onChange={(e) => setForm({ ...form, days: e.target.value })} /></Field>
        <Field label="Description" className="span-2"><input value={form.description || ""} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
        <Field label="Services included" className="span-2"><input value={form.services_included || ""} onChange={(e) => setForm({ ...form, services_included: e.target.value })} /></Field>
      </div>
      {form.id && <button className="btn" type="button" onClick={() => setForm({ name: "", fee: "", days: "1" })}>Cancel</button>}
    </Section>
  );
}

function Services({ q }: { q: string }) {
  const { data } = useData<{ items: any[] }>("/api/services?all=1");
  const [form, setForm] = useState<any>({ name: "", category: "HOSPITAL SERVICES", rate: "" });
  const rows = (data?.items || []).filter((item) => matches(`${item.name} ${item.category}`, q));
  return (
    <Section title="Services" rows={rows} onSave={() => run(() => api(form.id ? `/api/services/${form.id}` : "/api/services", { method: form.id ? "PATCH" : "POST", body: JSON.stringify({ name: form.name, code: form.code, category: form.category, rate_paise: paise(form.rate), unit: form.unit, description: form.description, sort_order: form.sort_order, active: form.active !== false }) }), form.id ? "Service updated" : "Service added")}>
      <table className="data">
        <thead><tr><th>Name</th><th>Category</th><th className="num">Rate</th><th>Active</th><th></th></tr></thead>
        <tbody>{rows.map((item) => (
          <tr key={item.id}>
            <td>{item.name}</td>
            <td>{item.category}</td>
            <td className="num">{money(item.rate_paise)}</td>
            <td>{item.active ? "Yes" : "No"}</td>
            <td className="row-actions">
              <button className="btn small" type="button" onClick={() => setForm({ ...item, rate: (item.rate_paise || 0) / 100 })}>Edit</button>
              <button className="btn small" type="button" onClick={() => flip(item, `/api/services/${item.id}`, { name: item.name, code: item.code, category: item.category, rate_paise: item.rate_paise, unit: item.unit, description: item.description, sort_order: item.sort_order }, item.name)}>{item.active ? "Deactivate" : "Activate"}</button>
              <button className="btn small danger" type="button" onClick={() => erase(`/api/services/${item.id}`, item.name)}>Delete</button>
            </td>
          </tr>
        ))}</tbody>
      </table>
      <div className="grid-form">
        <Field label="Name"><input value={form.name || ""} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
        <Field label="Code"><input value={form.code || ""} onChange={(e) => setForm({ ...form, code: e.target.value })} /></Field>
        <Field label="Category"><input value={form.category || ""} onChange={(e) => setForm({ ...form, category: e.target.value })} /></Field>
        <Field label="Rate Rs"><input value={form.rate ?? ""} onChange={(e) => setForm({ ...form, rate: e.target.value })} /></Field>
        <Field label="Unit"><input value={form.unit || ""} onChange={(e) => setForm({ ...form, unit: e.target.value })} /></Field>
        <Field label="Description" className="span-2"><input value={form.description || ""} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
      </div>
      {form.id && <button className="btn" type="button" onClick={() => setForm({ name: "", category: "HOSPITAL SERVICES", rate: "" })}>Cancel</button>}
    </Section>
  );
}

function LabTests({ q }: { q: string }) {
  const { data } = useData<{ items: any[] }>("/api/lab/tests?all=1");
  const [form, setForm] = useState<any>({ name: "", code: "", price: "", sample_type: "Blood" });
  const rows = (data?.items || []).filter((item) => matches(`${item.name} ${item.code}`, q));
  return (
    <Section title="Lab tests" rows={rows} onSave={() => run(() => api(form.id ? `/api/lab/tests/${form.id}` : "/api/lab/tests", { method: form.id ? "PATCH" : "POST", body: JSON.stringify({ ...form, price_paise: paise(form.price), active: form.active !== false }) }), form.id ? "Test updated" : "Test added")}>
      <table className="data">
        <thead><tr><th>Name</th><th>Code</th><th>Sample</th><th className="num">Price</th><th>Active</th><th></th></tr></thead>
        <tbody>{rows.map((item) => (
          <tr key={item.id}>
            <td>{item.name}</td>
            <td>{item.code}</td>
            <td>{item.sample_type}</td>
            <td className="num">{money(item.price_paise)}</td>
            <td>{item.active ? "Yes" : "No"}</td>
            <td className="row-actions">
              <button className="btn small" type="button" onClick={() => setForm({ ...item, price: (item.price_paise || 0) / 100 })}>Edit</button>
              <button className="btn small" type="button" onClick={() => flip(item, `/api/lab/tests/${item.id}`, { name: item.name, code: item.code, price_paise: item.price_paise, sample_type: item.sample_type }, item.name)}>{item.active ? "Deactivate" : "Activate"}</button>
              <button className="btn small danger" type="button" onClick={() => erase(`/api/lab/tests/${item.id}`, item.name)}>Delete</button>
            </td>
          </tr>
        ))}</tbody>
      </table>
      <div className="grid-form">
        <Field label="Name"><input value={form.name || ""} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
        <Field label="Code"><input value={form.code || ""} onChange={(e) => setForm({ ...form, code: e.target.value })} /></Field>
        <Field label="Category"><input value={form.category || ""} onChange={(e) => setForm({ ...form, category: e.target.value })} /></Field>
        <Field label="Price Rs"><input value={form.price ?? ""} onChange={(e) => setForm({ ...form, price: e.target.value })} /></Field>
        <Field label="Sample"><input value={form.sample_type || ""} onChange={(e) => setForm({ ...form, sample_type: e.target.value })} /></Field>
        <Field label="Turnaround hours"><input value={form.tat_hours ?? ""} onChange={(e) => setForm({ ...form, tat_hours: e.target.value })} /></Field>
        <Field label="Preparation" className="span-2"><input value={form.preparation || ""} onChange={(e) => setForm({ ...form, preparation: e.target.value })} /></Field>
      </div>
      {form.id && <button className="btn" type="button" onClick={() => setForm({ name: "", code: "", price: "", sample_type: "Blood" })}>Cancel</button>}
    </Section>
  );
}

function Procedures({ q }: { q: string }) {
  const { data, error } = useData<{ items: any[] }>("/api/ot/procedures?all=1");
  const [form, setForm] = useState<any>({ name: "", code: "", price: "", duration_minutes: "60" });
  const rows = (data?.items || []).filter((item) => matches(`${item.name} ${item.code}`, q));
  return (
    <Section title="OT procedures" error={error} rows={rows} onSave={() => run(() => api(form.id ? `/api/ot/procedures/${form.id}` : "/api/ot/procedures", { method: form.id ? "PUT" : "POST", body: JSON.stringify({ name: form.name, code: form.code, price_paise: paise(form.price), duration_minutes: Number(form.duration_minutes || 60), category: form.category, department_id: form.department_id, require_admission: form.require_admission, active: form.active !== false }) }), form.id ? "Procedure updated" : "Procedure added")}>
      <table className="data">
        <thead><tr><th>Name</th><th>Code</th><th className="num">Price</th><th>Active</th><th></th></tr></thead>
        <tbody>{rows.map((item) => (
          <tr key={item.id}>
            <td>{item.name}</td>
            <td>{item.code}</td>
            <td className="num">{money(item.price_paise)}</td>
            <td>{item.active ? "Yes" : "No"}</td>
            <td className="row-actions">
              <button className="btn small" type="button" onClick={() => setForm({ ...item, price: (item.price_paise || 0) / 100 })}>Edit</button>
              <button className="btn small" type="button" onClick={() => {
                const next = !item.active;
                if (!window.confirm(next ? `Reactivate ${item.name}?` : `Deactivate ${item.name}? Past OT records stay valid.`)) return;
                run(() => api(`/api/ot/procedures/${item.id}`, { method: "PUT", body: JSON.stringify({ name: item.name, code: item.code, price_paise: item.price_paise, duration_minutes: item.duration_minutes, category: item.category, department_id: item.department_id, require_admission: item.require_admission, active: next }) }), next ? "Reactivated" : "Deactivated");
              }}>{item.active ? "Deactivate" : "Activate"}</button>
              <button className="btn small danger" type="button" onClick={() => erase(`/api/ot/procedures/${item.id}`, item.name)}>Delete</button>
            </td>
          </tr>
        ))}</tbody>
      </table>
      <div className="grid-form">
        <Field label="Name"><input value={form.name || ""} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
        <Field label="Code"><input value={form.code || ""} onChange={(e) => setForm({ ...form, code: e.target.value })} /></Field>
        <Field label="Category"><input value={form.category || ""} onChange={(e) => setForm({ ...form, category: e.target.value })} /></Field>
        <Field label="Price Rs"><input value={form.price ?? ""} onChange={(e) => setForm({ ...form, price: e.target.value })} /></Field>
        <Field label="Minutes"><input value={form.duration_minutes ?? ""} onChange={(e) => setForm({ ...form, duration_minutes: e.target.value })} /></Field>
        <label className="check-line"><input type="checkbox" checked={Boolean(form.require_admission)} onChange={(e) => setForm({ ...form, require_admission: e.target.checked })} /> Admission required</label>
      </div>
      {form.id && <button className="btn" type="button" onClick={() => setForm({ name: "", code: "", price: "", duration_minutes: "60" })}>Cancel</button>}
    </Section>
  );
}

function Theatres({ q }: { q: string }) {
  const { data, error } = useData<{ items: any[] }>("/api/ot/theatres?all=1");
  const [form, setForm] = useState<any>({ name: "", code: "", location: "" });
  const rows = (data?.items || []).filter((item) => matches(`${item.name} ${item.code}`, q));
  return (
    <Section title="Theatres" error={error} rows={rows} onSave={() => run(() => api(form.id ? `/api/ot/theatres/${form.id}` : "/api/ot/theatres", { method: form.id ? "PUT" : "POST", body: JSON.stringify({ name: form.name, code: form.code, location: form.location, active: form.active !== false }) }), form.id ? "Theatre updated" : "Theatre added")}>
      <table className="data">
        <thead><tr><th>Name</th><th>Code</th><th>Location</th><th>Active</th><th></th></tr></thead>
        <tbody>{rows.map((item) => (
          <tr key={item.id}>
            <td>{item.name}</td>
            <td>{item.code}</td>
            <td>{item.location || "—"}</td>
            <td>{item.active ? "Yes" : "No"}</td>
            <td className="row-actions">
              <button className="btn small" type="button" onClick={() => setForm(item)}>Edit</button>
              <button className="btn small" type="button" onClick={() => {
                const next = !item.active;
                if (!window.confirm(next ? `Reactivate ${item.name}?` : `Deactivate ${item.name}? It will leave the scheduling list. Past cases stay.`)) return;
                run(() => api(`/api/ot/theatres/${item.id}`, { method: "PUT", body: JSON.stringify({ name: item.name, code: item.code, location: item.location, active: next }) }), next ? "Reactivated" : "Deactivated");
              }}>{item.active ? "Deactivate" : "Activate"}</button>
              <button className="btn small danger" type="button" onClick={() => erase(`/api/ot/theatres/${item.id}`, item.name)}>Delete</button>
            </td>
          </tr>
        ))}</tbody>
      </table>
      <div className="grid-form">
        <Field label="Name"><input value={form.name || ""} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
        <Field label="Code"><input value={form.code || ""} onChange={(e) => setForm({ ...form, code: e.target.value })} /></Field>
        <Field label="Location"><input value={form.location || ""} onChange={(e) => setForm({ ...form, location: e.target.value })} /></Field>
      </div>
      {form.id && <button className="btn" type="button" onClick={() => setForm({ name: "", code: "", location: "" })}>Cancel</button>}
    </Section>
  );
}

function Checklist({ q }: { q: string }) {
  const { data, error } = useData<{ items: any[] }>("/api/ot/checklist?all=1");
  const [form, setForm] = useState<any>({ code: "", label: "", required: true, sort_order: "0" });
  const rows = (data?.items || []).filter((item) => matches(`${item.label} ${item.code}`, q));
  return (
    <Section title="OT checklist" error={error} rows={rows} onSave={() => run(() => api(form.id ? `/api/ot/checklist/${form.id}` : "/api/ot/checklist", { method: form.id ? "PUT" : "POST", body: JSON.stringify({ code: form.code, label: form.label, required: Boolean(form.required), sort_order: Number(form.sort_order || 0), active: form.active !== false }) }), form.id ? "Checklist item updated" : "Checklist item added")}>
      <table className="data">
        <thead><tr><th>Label</th><th>Code</th><th>Required</th><th>Active</th><th></th></tr></thead>
        <tbody>{rows.map((item) => (
          <tr key={item.id}>
            <td>{item.label}</td>
            <td>{item.code}</td>
            <td>{item.required ? "Yes" : "No"}</td>
            <td>{item.active ? "Yes" : "No"}</td>
            <td className="row-actions">
              <button className="btn small" type="button" onClick={() => setForm(item)}>Edit</button>
              <button className="btn small" type="button" onClick={() => {
                const next = !item.active;
                if (!window.confirm(next ? `Reactivate ${item.label}?` : `Deactivate ${item.label}? Past cases stay.`)) return;
                run(() => api(`/api/ot/checklist/${item.id}`, { method: "PUT", body: JSON.stringify({ code: item.code, label: item.label, required: item.required, sort_order: item.sort_order, active: next }) }), next ? "Reactivated" : "Deactivated");
              }}>{item.active ? "Deactivate" : "Activate"}</button>
              <button className="btn small danger" type="button" onClick={() => erase(`/api/ot/checklist/${item.id}`, item.label)}>Delete</button>
            </td>
          </tr>
        ))}</tbody>
      </table>
      <div className="grid-form">
        <Field label="Label"><input value={form.label || ""} onChange={(e) => setForm({ ...form, label: e.target.value })} /></Field>
        <Field label="Code"><input value={form.code || ""} onChange={(e) => setForm({ ...form, code: e.target.value })} /></Field>
        <Field label="Sort"><input value={form.sort_order ?? ""} onChange={(e) => setForm({ ...form, sort_order: e.target.value })} /></Field>
        <label className="check-line"><input type="checkbox" checked={form.required !== false && form.required !== 0} onChange={(e) => setForm({ ...form, required: e.target.checked })} /> Required before surgery</label>
      </div>
      {form.id && <button className="btn" type="button" onClick={() => setForm({ code: "", label: "", required: true, sort_order: "0" })}>Cancel</button>}
    </Section>
  );
}

function useFacilities() {
  return useData<{ wards: any[]; rooms: any[]; beds: any[] }>("/api/facilities?all=1");
}

function Wards({ q }: { q: string }) {
  const { data } = useFacilities();
  const [form, setForm] = useState<any>({ name: "", code: "", ward_type: "GENERAL" });
  const rows = (data?.wards || []).filter((item) => matches(`${item.name} ${item.code}`, q));
  return (
    <Section title="Wards" rows={rows} onSave={() => run(() => api(form.id ? `/api/wards/${form.id}` : "/api/wards", { method: form.id ? "PATCH" : "POST", body: JSON.stringify({ name: form.name, code: form.code, ward_type: form.ward_type, ac: form.ac, description: form.description, sort_order: form.sort_order, active: form.active !== false }) }), form.id ? "Ward updated" : "Ward added")}>
      <table className="data">
        <thead><tr><th>Name</th><th>Code</th><th>Type</th><th>Active</th><th></th></tr></thead>
        <tbody>{rows.map((item) => (
          <tr key={item.id}>
            <td>{item.name}</td>
            <td>{item.code}</td>
            <td>{item.ward_type}</td>
            <td>{item.active ? "Yes" : "No"}</td>
            <td className="row-actions">
              <button className="btn small" type="button" onClick={() => setForm(item)}>Edit</button>
              <button className="btn small" type="button" onClick={() => flip(item, `/api/wards/${item.id}`, { name: item.name, code: item.code, ward_type: item.ward_type, ac: item.ac, description: item.description, sort_order: item.sort_order }, item.name)}>{item.active ? "Deactivate" : "Activate"}</button>
              <button className="btn small danger" type="button" onClick={() => erase(`/api/wards/${item.id}`, item.name)}>Delete</button>
            </td>
          </tr>
        ))}</tbody>
      </table>
      <div className="grid-form">
        <Field label="Name"><input value={form.name || ""} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
        <Field label="Code"><input value={form.code || ""} onChange={(e) => setForm({ ...form, code: e.target.value })} /></Field>
        <Field label="Type"><input value={form.ward_type || ""} onChange={(e) => setForm({ ...form, ward_type: e.target.value })} /></Field>
        <Field label="Description" className="span-2"><input value={form.description || ""} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
      </div>
      {form.id && <button className="btn" type="button" onClick={() => setForm({ name: "", code: "", ward_type: "GENERAL" })}>Cancel</button>}
    </Section>
  );
}

function Rooms({ q }: { q: string }) {
  const { data } = useFacilities();
  const [form, setForm] = useState<any>({ ward_id: "", name: "", room_type: "GENERAL", rate: "" });
  const rows = (data?.rooms || []).filter((item) => matches(`${item.name} ${item.ward_name}`, q));
  return (
    <Section title="Rooms" rows={rows} onSave={() => run(() => api(form.id ? `/api/rooms/${form.id}` : "/api/rooms", { method: form.id ? "PATCH" : "POST", body: JSON.stringify(form.id ? { name: form.name, room_type: form.room_type, daily_rate_paise: paise(form.rate), active: form.active !== false } : { ward_id: form.ward_id, name: form.name, room_type: form.room_type, daily_rate_paise: paise(form.rate) }) }), form.id ? "Room updated" : "Room added")}>
      <table className="data">
        <thead><tr><th>Ward</th><th>Room</th><th className="num">Daily rate</th><th>Active</th><th></th></tr></thead>
        <tbody>{rows.map((item) => (
          <tr key={item.id}>
            <td>{item.ward_name}</td>
            <td>{item.name}</td>
            <td className="num">{money(item.daily_rate_paise)}</td>
            <td>{item.active ? "Yes" : "No"}</td>
            <td className="row-actions">
              <button className="btn small" type="button" onClick={() => setForm({ ...item, rate: (item.daily_rate_paise || 0) / 100 })}>Edit</button>
              <button className="btn small" type="button" onClick={() => flip(item, `/api/rooms/${item.id}`, { name: item.name, room_type: item.room_type, daily_rate_paise: item.daily_rate_paise }, item.name)}>{item.active ? "Deactivate" : "Activate"}</button>
              <button className="btn small danger" type="button" onClick={() => erase(`/api/rooms/${item.id}`, item.name)}>Delete</button>
            </td>
          </tr>
        ))}</tbody>
      </table>
      <div className="grid-form">
        {!form.id && (
          <Field label="Ward">
            <select value={form.ward_id || ""} onChange={(e) => setForm({ ...form, ward_id: e.target.value })}>
              <option value="">Choose</option>
              {(data?.wards || []).filter((item) => item.active).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>
          </Field>
        )}
        <Field label="Name"><input value={form.name || ""} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
        <Field label="Type"><input value={form.room_type || ""} onChange={(e) => setForm({ ...form, room_type: e.target.value })} /></Field>
        <Field label="Daily rate Rs"><input value={form.rate ?? ""} onChange={(e) => setForm({ ...form, rate: e.target.value })} /></Field>
      </div>
    </Section>
  );
}

function Beds({ q }: { q: string }) {
  const { data } = useFacilities();
  const [form, setForm] = useState<any>({ ward_id: "", room_id: "", name: "" });
  const rooms = useMemo(() => (data?.rooms || []).filter((item) => item.active && (!form.ward_id || item.ward_id === form.ward_id)), [data, form.ward_id]);
  const rows = (data?.beds || []).filter((item) => matches(`${item.name} ${item.room_name} ${item.ward_name}`, q));
  return (
    <Section title="Beds" rows={rows} onSave={() => run(async () => {
      if (form.id) {
        await api(`/api/beds/${form.id}`, { method: "PATCH", body: JSON.stringify({ name: form.name, active: form.active !== false }) });
        return;
      }
      const count = Math.max(1, Math.min(40, Number(form.count || 1)));
      for (let i = 1; i <= count; i += 1) {
        await api("/api/beds", { method: "POST", body: JSON.stringify({ room_id: form.room_id, name: count === 1 ? form.name : `${form.name} ${i}` }) });
      }
    }, form.id ? "Bed updated" : "Beds added")}>
      <p className="muted">A bed is added under a ward and room. Delete removes an unused bed. If an admission has used it, deactivate it instead.</p>
      <table className="data">
        <thead><tr><th>Ward</th><th>Room</th><th>Bed</th><th>Status</th><th>Active</th><th></th></tr></thead>
        <tbody>{rows.map((item) => (
          <tr key={item.id}>
            <td>{item.ward_name}</td>
            <td>{item.room_name}</td>
            <td>{item.name} {String(item.id).startsWith("BD-") ? <span className="sample-badge">SAMPLE</span> : null}</td>
            <td>{item.status}</td>
            <td>{item.active ? "Yes" : "No"}</td>
            <td className="row-actions">
              <button className="btn small" type="button" onClick={() => setForm(item)}>Edit</button>
              <button className="btn small" type="button" onClick={() => flip(item, `/api/beds/${item.id}`, { name: item.name }, item.name)}>{item.active ? "Deactivate" : "Activate"}</button>
              <button className="btn small danger" type="button" onClick={() => erase(`/api/beds/${item.id}`, item.name)}>Delete</button>
            </td>
          </tr>
        ))}</tbody>
      </table>
      <div className="grid-form">
        {!form.id && (
          <>
            <Field label="Ward">
              <select value={form.ward_id || ""} onChange={(e) => setForm({ ...form, ward_id: e.target.value, room_id: "" })}>
                <option value="">Choose</option>
                {(data?.wards || []).filter((item) => item.active).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
              </select>
            </Field>
            <Field label="Room">
              <select value={form.room_id || ""} onChange={(e) => setForm({ ...form, room_id: e.target.value })}>
                <option value="">Choose</option>
                {rooms.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
              </select>
            </Field>
          </>
        )}
        <Field label="Bed name"><input value={form.name || ""} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
        {!form.id && <Field label="How many"><input value={form.count || "1"} onChange={(e) => setForm({ ...form, count: e.target.value })} /></Field>}
      </div>
    </Section>
  );
}

function Section({ title, rows, error, onSave, children }: { title: string; rows: any[]; error?: string; onSave: () => void; children: any }) {
  return (
    <div className="panel">
      <h2>{title}</h2>
      <div className="body">
        {error && <div className="warn">{error}</div>}
        {!error && !rows.length && <Empty text="Nothing matches." />}
        {children}
        <button className="btn primary" type="button" onClick={onSave} style={{ marginTop: 8 }}>Save</button>
      </div>
    </div>
  );
}
