import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, fileUrl, money, when } from "../api";
import { useApp } from "../store";
import { Empty, ErrorState, Field, Loading, Masters, Modal, Page, PatientSearchSelect, Status, run, useData, type PatientSummary } from "../ui";

const emptyForm = {
  name: "", primary_phone: "", alternate_phone: "", guardian_name: "", guardian_phone: "",
  gender: "Female", dob: "", age_at_registration: "", age_is_estimated: false, address: "",
  category_id: "", department_id: "", notes: "", allergies: "", emergency_name: "", emergency_phone: "",
  opd_type_id: "", doctor_id: "", chief_complaint: "", queue: true,
};

export function Register() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [form, setForm] = useState<any>({ ...emptyForm, name: params.get("name") || "", primary_phone: params.get("phone") || "" });
  const [matches, setMatches] = useState<any[]>([]);
  const [cards, setCards] = useState<any[]>([]);
  const [chosen, setChosen] = useState<any>(null);
  const [confirmNew, setConfirmNew] = useState(false);
  const { data: types } = useData<{ items: any[] }>("/api/opd/types");
  const { data: doctors } = useData<{ items: any[] }>("/api/doctors");

  function set(key: string, value: any) {
    setForm((f: any) => ({ ...f, [key]: value }));
  }

  function patientFields(patient: any) {
    return {
      name: patient.name || "",
      primary_phone: patient.primary_phone || "",
      alternate_phone: patient.alternate_phone || "",
      guardian_name: patient.guardian_name || "",
      guardian_phone: patient.guardian_phone || "",
      gender: patient.gender || "",
      dob: patient.dob || "",
      age_at_registration: patient.age_at_registration ?? "",
      age_is_estimated: Boolean(patient.age_is_estimated),
      address: patient.address || "",
      category_id: patient.category_id || "",
      department_id: patient.department_id || "",
      notes: patient.notes || "",
      allergies: patient.allergies || "",
      emergency_name: patient.emergency_name || "",
      emergency_phone: patient.emergency_phone || "",
    };
  }

  async function choosePatient(summary: PatientSummary | null) {
    if (!summary) {
      setChosen(null);
      setForm((current: any) => ({ ...emptyForm, opd_type_id: current.opd_type_id, doctor_id: current.doctor_id, department_id: current.department_id, chief_complaint: current.chief_complaint, queue: current.queue }));
      setCards([]);
      return;
    }
    const full = await api<any>(`/api/patients/${summary.id}`);
    setChosen(full);
    setForm((current: any) => ({ ...current, ...patientFields(full) }));
    setConfirmNew(false);
  }

  useEffect(() => {
    const existing = params.get("patient");
    if (!existing) return;
    api<any>(`/api/patients/${existing}`).then((patient) => {
      setChosen(patient);
      setForm((current: any) => ({ ...current, ...patientFields(patient) }));
    }).catch(() => undefined);
  }, [params]);

  useEffect(() => {
    if (!chosen) {
      setCards([]);
      return;
    }
    api<{ items: any[] }>(`/api/opd/valid?patient_id=${chosen.id}`).then((d) => setCards(d.items)).catch(() => setCards([]));
  }, [chosen]);

  async function submit(asNew: boolean) {
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
      if (chosen) {
        await api(`/api/patients/${chosen.id}`, {
          method: "PATCH",
          body: JSON.stringify({
            ...patientFields(form),
            age_at_registration: form.age_at_registration === "" ? null : Number(form.age_at_registration),
            status: chosen.status,
          }),
        });
      }
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
      const patient = chosen || await api<any>("/api/patients", { method: "POST", body: JSON.stringify(person) });
      navigate(`/patients/${patient.id}`);
    }, chosen ? "Existing patient sent forward" : "Patient registered");
  }

  return (
    <Page title="New Patient" note="Register a new patient. Phone finds a possible match. It is not the patient identity." actions={<button className="btn" type="button" onClick={() => { setForm(emptyForm); setChosen(null); setMatches([]); }}>Clear</button>}>
      <div className="grid-2">
        <form className="panel" onSubmit={(e) => { e.preventDefault(); submit(false); }}>
          <h2>{chosen ? `Using ${chosen.name}` : "New registration"}</h2>
          <div className="body grid-form">
            <div className="span-2 section-label">Patient information</div>
            {chosen && <div className="span-2 patient-selected"><strong>{chosen.name}</strong><span className="pid">Permanent Patient ID: {chosen.id}</span></div>}
            <div className="span-2 section-label">Identity</div>
            <Field label="Patient name" required><input value={form.name} onChange={(e) => set("name", e.target.value)} required={!chosen} autoFocus /></Field>
            <Field label="Gender">
              <div className="seg" role="group" aria-label="Gender">
                {["Female", "Male", "Other"].map((g) => (
                  <button type="button" key={g} className={form.gender === g ? "on" : ""} onClick={() => set("gender", g)}>{g}</button>
                ))}
              </div>
            </Field>
            <div className="span-2 section-label">Demographics</div>
            <Field label="Age (years)">
              <input value={form.age_at_registration} onChange={(e) => set("age_at_registration", e.target.value)} />
            </Field>
            <Field label="Date of birth"><input type="date" value={form.dob} onChange={(e) => set("dob", e.target.value)} /></Field>
            <Field label="Category">
              <select value={form.category_id} onChange={(e) => set("category_id", e.target.value)}><Masters type="patient_category" label="Category" /></select>
            </Field>
            <Field label="Department">
              <select value={form.department_id} onChange={(e) => set("department_id", e.target.value)}><Masters type="department" label="Department" /></select>
            </Field>
            <div className="span-2 section-label">Contact</div>
            <Field label="Phone">
              <input value={form.primary_phone} onChange={(e) => set("primary_phone", e.target.value)} />
            </Field>
            <Field label="Alternate phone"><input value={form.alternate_phone} onChange={(e) => set("alternate_phone", e.target.value)} /></Field>
            <Field label="Guardian / parent"><input value={form.guardian_name} onChange={(e) => set("guardian_name", e.target.value)} /></Field>
            <Field label="Guardian phone"><input value={form.guardian_phone} onChange={(e) => set("guardian_phone", e.target.value)} /></Field>
            <div className="span-2 section-label">Address</div>
            <Field label="Address" className="span-2"><input value={form.address} onChange={(e) => set("address", e.target.value)} /></Field>
            <div className="span-2 section-label">Emergency and allergies</div>
            <Field label="Emergency contact"><input value={form.emergency_name} onChange={(e) => set("emergency_name", e.target.value)} /></Field>
            <Field label="Emergency phone"><input value={form.emergency_phone} onChange={(e) => set("emergency_phone", e.target.value)} /></Field>
            <Field label="Allergies" className="span-2"><input value={form.allergies} onChange={(e) => set("allergies", e.target.value)} placeholder="None known" /></Field>
            <div className="span-2 section-label">Start today's OPD visit</div>
            <Field label="Short note" className="span-2"><input value={form.notes} onChange={(e) => set("notes", e.target.value)} /></Field>
            <Field label="OPD type">
              <select value={form.opd_type_id} onChange={(e) => set("opd_type_id", e.target.value)}>
                <option value="">Register only</option>
                {(types?.items || []).map((t) => <option key={t.id} value={t.id}>{t.name} · {money(t.fee_paise)} · {t.validity_days}d</option>)}
              </select>
              {form.opd_type_id && <small className="muted">Configured OPD fee: {money((types?.items || []).find((t) => t.id === form.opd_type_id)?.fee_paise)}</small>}
            </Field>
            <Field label="Doctor">
              <select value={form.doctor_id} onChange={(e) => set("doctor_id", e.target.value)}>
                <option value="">Assign later</option>
                {(doctors?.items || []).map((d) => <option key={d.id} value={d.id}>{d.title} {d.full_name} · {d.specialty}</option>)}
              </select>
            </Field>
            <Field label="Complaint" className="span-2"><input value={form.chief_complaint} onChange={(e) => set("chief_complaint", e.target.value)} /></Field>
            {cards.length > 0 && (
              <Field label="Valid OPD card" className="span-2">
                <select value={form.use_opd_id || ""} onChange={(e) => set("use_opd_id", e.target.value)}>
                  <option value="">Charge a new fee</option>
                  {cards.map((card) => <option key={card.id} value={card.id}>Use {card.id} · {card.opd_type_name} · valid till {when(card.validity_until)}</option>)}
                </select>
              </Field>
            )}
            <label className="span-2"><input type="checkbox" checked={form.queue} onChange={(e) => set("queue", e.target.checked)} /> Place in doctor queue</label>
            <div className="span-2 row-actions">
              <button className="btn primary" type="submit">{chosen ? "Queue this patient" : "Register & continue"}</button>
              {chosen && <button className="btn" type="button" onClick={() => { setChosen(null); setConfirmNew(false); }}>Not this person</button>}
            </div>
          </div>
        </form>
        <div>
          <div className="panel">
            <h2>Find an existing patient</h2>
            <div className="body">
              <PatientSearchSelect value={chosen} onChange={choosePatient} onRegister={() => setConfirmNew(true)} />
              {matches.length > 0 && !chosen && <div className="warn">Possible match found. Choose the existing person above, or confirm that this is a new person. Nothing is merged automatically.</div>}
              {confirmNew && !chosen && <div className="warn">You are registering a new person. Shared phone numbers are allowed; confirm this is not one of the patients above.</div>}
            </div>
          </div>
        </div>
      </div>
    </Page>
  );
}

export { Patients } from "./patients";

function PatientMessage({ patient }: { patient: any }) {
  const can = useApp((s) => s.can);
  const [text, setText] = useState("");
  if (!can("whatsapp.send")) return null;
  return (
    <div className="panel">
      <h2>Message this patient</h2>
      <div className="body">
        <p className="muted">Sends to {patient.primary_phone ? `the number ending ${String(patient.primary_phone).slice(-4)}` : "no phone on record"}. The provider is the one configured for the hospital, not a hardcoded service.</p>
        <Field label="Message"><textarea value={text} onChange={(e) => setText(e.target.value)} /></Field>
        <button className="btn" disabled={!text.trim() || !patient.primary_phone} onClick={() => {
          if (!window.confirm(`Send this message to ${patient.name}?`)) return;
          run(() => api("/api/whatsapp/messages", { method: "POST", body: JSON.stringify({ patient_id: patient.id, text, confirm: true }) }), "Message handed to the provider");
        }}>Send message</button>
      </div>
    </div>
  );
}

function SendDocument({ patient, documentId, title }: { patient: any; documentId: string; title: string }) {
  const can = useApp((s) => s.can);
  if (!can("whatsapp.send")) return null;
  return (
    <button className="btn small" onClick={() => {
      if (!window.confirm(`Send ${title} to ${patient.name}?`)) return;
      run(() => api("/api/whatsapp/documents", { method: "POST", body: JSON.stringify({ patient_id: patient.id, document_id: documentId, confirm: true }) }), "Document handed to the provider");
    }}>Send</button>
  );
}

export function PatientPage() {
  const { id } = useParams();
  const [params] = useSearchParams();
  const can = useApp((s) => s.can);
  const canEdit = can("patient.edit");
  const { data, error, loading } = useData<any>(id ? `/api/patients/${id}/timeline` : null);
  const [tab, setTab] = useState(params.get("tab") || "overview");
  const [docOpen, setDocOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<any>(null);
  useEffect(() => {
    if (data?.patient && !editing) setForm(data.patient);
  }, [data, editing]);
  useEffect(() => {
    const next = params.get("tab");
    if (next) setTab(next);
  }, [params]);
  if (error) return <Page title="Patient"><ErrorState message={error} /></Page>;
  if (loading && !data) return <Page title="Patient"><Loading label="Opening record…" /></Page>;
  if (!data) return <Page title="Patient"><Loading label="Opening record…" /></Page>;
  const p = data.patient;
  const latest = data.current?.last_encounter_id
    ? { id: data.current.last_encounter_id, arrived_at: data.current.last_encounter_at }
    : data.encounters?.[data.encounters.length - 1];
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
  return (
    <Page title={p.name} note={p.id} actions={
      <>
        {can("opd.create") && <Link className="btn primary" to={`/register?patient=${p.id}`}>New OPD</Link>}
        {can("billing.view") && <Link className="btn" to={`/billing?patient=${p.id}`}>Billing</Link>}
        {can("document.view") && <button className="btn" type="button" onClick={() => setTab("documents")}>Documents</button>}
        <button className="btn" type="button" onClick={() => setTab("timeline")}>History</button>
        {canEdit && <button className="btn" type="button" onClick={() => { setForm(p); setEditing(true); }}>Edit</button>}
        {can("document.upload") && <button className="btn" type="button" onClick={() => setDocOpen(true)}>Add document</button>}
        {canEdit && p.status !== "INACTIVE" && <button className="btn danger" type="button" onClick={() => {
          if (!window.confirm(`Mark ${p.name} (${p.id}) inactive? Clinical, dispensing, billing, admission, and document history stays linked.`)) return;
          run(() => api("/api/patients/status", { method: "POST", body: JSON.stringify({ ids: [p.id], status: "INACTIVE" }) }), "Patient marked inactive");
        }}>Deactivate</button>}
      </>
    }>
      <section className="profile-head">
        <span className="avatar" aria-hidden="true">{String(p.name || "?").slice(0, 1)}</span>
        <div>
          <h2>{p.name} {p.is_sample ? <span className="sample-badge">SAMPLE</span> : null}</h2>
          <div className="pid">{p.id}</div>
          <p>{p.age_display || "—"} / {p.gender || "—"} · {p.primary_phone || "—"} · Guardian: {p.guardian_name || "—"}</p>
          <span className={`reg-badge ${data.current?.care_code || ""}`}>{data.current?.care_label || p.status || "—"}</span>
        </div>
        <div className="profile-care">
          <span>Department</span><strong>{data.current?.department_name || p.department_name || "—"}</strong>
          <span>Doctor</span><strong>{data.current?.last_doctor_name || "—"}</strong>
          <span>Encounter</span><strong>{latest?.id || "—"}</strong>
          <span>Queue</span><strong>{data.current?.queue_status || "—"}</strong>
          <span>Admission</span><strong>{data.current?.admission_status || "—"}</strong>
          <span>Bed</span><strong>{data.current?.bed_name || data.current?.bed_id || "—"}</strong>
        </div>
      </section>
      <div className="quick-actions">
        {can("opd.create") && <Link to={`/register?patient=${p.id}`}>Register OPD</Link>}
        {can("queue.view") && <Link to="/queue">Open doctor queue</Link>}
        {can("billing.view") && <Link to={`/billing?patient=${p.id}`}>Start billing</Link>}
        {latest && can("prescription.view") && <Link to={`/consult/${latest.id}`}>View prescription</Link>}
        {can("lab.view") && <button type="button" onClick={() => setTab("lab")}>View lab reports</button>}
        {can("document.view") && <button type="button" onClick={() => setTab("documents")}>View documents</button>}
        <button type="button" onClick={() => setTab("timeline")}>View history</button>
      </div>
      {p.allergies ? <div className="allergy">Allergy: {p.allergies}</div> : <p className="muted">No allergy recorded</p>}
      {editing && form && (
        <div className="panel">
          <h2>Edit patient</h2>
          <div className="body grid-form">
            <Field label="Name"><input value={form.name || ""} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
            <Field label="Phone"><input value={form.primary_phone || ""} onChange={(e) => setForm({ ...form, primary_phone: e.target.value })} /></Field>
            <Field label="Gender"><input value={form.gender || ""} onChange={(e) => setForm({ ...form, gender: e.target.value })} /></Field>
            <Field label="Age"><input value={form.age_at_registration ?? ""} onChange={(e) => setForm({ ...form, age_at_registration: e.target.value })} /></Field>
            <Field label="Guardian"><input value={form.guardian_name || ""} onChange={(e) => setForm({ ...form, guardian_name: e.target.value })} /></Field>
            <Field label="Guardian phone"><input value={form.guardian_phone || ""} onChange={(e) => setForm({ ...form, guardian_phone: e.target.value })} /></Field>
            <Field label="Address" className="span-2"><input value={form.address || ""} onChange={(e) => setForm({ ...form, address: e.target.value })} /></Field>
            <Field label="Allergies" className="span-2"><input value={form.allergies || ""} onChange={(e) => setForm({ ...form, allergies: e.target.value })} /></Field>
            <div className="row-actions">
              <button className="btn primary" type="button" onClick={() => run(async () => {
                const age = form.age_at_registration === "" || form.age_at_registration == null ? null : Number(form.age_at_registration);
                await api(`/api/patients/${p.id}`, { method: "PATCH", body: JSON.stringify({ ...p, ...form, age_at_registration: age }) });
                setEditing(false);
              }, "Patient updated")}>Save</button>
              <button className="btn" type="button" onClick={() => { setEditing(false); setForm(p); }}>Cancel</button>
            </div>
          </div>
        </div>
      )}
      <div className="tabs" role="tablist">
        {tabs.map(([key, label]) => (
          <button key={key} type="button" role="tab" aria-selected={tab === key} className={tab === key ? "on" : ""} onClick={() => setTab(key)}>{label}</button>
        ))}
      </div>
      {tab === "overview" && (
        <div className="grid-2">
          <div className="panel">
            <h2>Demographics</h2>
            <dl className="profile-facts">
              <div><dt>Patient ID</dt><dd className="pid">{p.id}</dd></div>
              <div><dt>Date of birth / age</dt><dd>{p.dob || "—"} · {p.age_display || "—"}</dd></div>
              <div><dt>Gender</dt><dd>{p.gender || "—"}</dd></div>
              <div><dt>Blood group</dt><dd>—</dd></div>
              <div><dt>Phone</dt><dd>{p.primary_phone || "—"}</dd></div>
              <div><dt>Alternate phone</dt><dd>{p.alternate_phone || "—"}</dd></div>
              <div><dt>Guardian</dt><dd>{p.guardian_name || "—"}</dd></div>
              <div><dt>Guardian phone</dt><dd>{p.guardian_phone || "—"}</dd></div>
              <div><dt>Address</dt><dd>{p.address || "—"}</dd></div>
              <div><dt>Email</dt><dd>{p.email || "—"}</dd></div>
            </dl>
          </div>
          <div className="panel">
            <h2>Recent activity</h2>
            {data.events?.length ? (
              <ol className="timeline">
                {data.events.slice(0, 6).map((ev: any, i: number) => (
                  <li key={`${ev.kind}-${ev.id}-${i}`}>
                    <span className="muted">{when(ev.at)}</span>
                    <div><strong>{ev.title}</strong><div className="muted">{ev.detail || "—"}</div></div>
                  </li>
                ))}
              </ol>
            ) : <p className="quiet">No visits, bills, or documents are on this record yet.</p>}
          </div>
        </div>
      )}
      {tab === "prescriptions" && (
        <table className="data">
          <thead><tr><th>Prescription</th><th>Encounter</th><th>Status</th><th></th></tr></thead>
          <tbody>
            {(data.prescriptions || []).map((rx: any) => (
              <tr key={rx.id}>
                <td className="pid">{rx.id}</td>
                <td>{rx.encounter_id ? <Link to={`/consult/${rx.encounter_id}`}>{rx.encounter_id}</Link> : "—"}</td>
                <td><Status value={rx.status} /></td>
                <td>{rx.status === "FINALIZED" && <a href={fileUrl(`/api/prescriptions/${rx.id}/pdf`)} target="_blank" rel="noreferrer">Print</a>}</td>
              </tr>
            ))}
            {!data.prescriptions?.length && <tr><td colSpan={4} className="muted">No prescription on this record.</td></tr>}
          </tbody>
        </table>
      )}
      {tab === "lab" && (
        <table className="data">
          <thead><tr><th>Order</th><th>When</th><th>Status</th></tr></thead>
          <tbody>
            {(data.labs || []).map((lab: any) => (
              <tr key={lab.id}><td><Link to="/lab">{lab.id}</Link></td><td>{when(lab.ordered_at)}</td><td><Status value={lab.status} /></td></tr>
            ))}
            {!data.labs?.length && <tr><td colSpan={3} className="muted">No lab order on this record.</td></tr>}
          </tbody>
        </table>
      )}
      {tab === "timeline" && (
        data.events?.length ? (
          <ol className="timeline">
            {data.events.map((ev: any, i: number) => (
              <li key={i}>
                <span className="muted">{when(ev.at)}</span>
                <i />
                <div><strong>{ev.title}</strong><div className="muted">{ev.detail}</div></div>
              </li>
            ))}
          </ol>
        ) : <Empty text="No visits, bills, or documents are on this record yet." />
      )}
      {tab === "opd" && (
        <table className="data">
          <thead><tr><th>Encounter</th><th>When</th><th>Complaint</th><th>Status</th></tr></thead>
          <tbody>
            {data.encounters.map((e: any) => (
              <tr key={e.id}><td><Link to={`/consult/${e.id}`}>{e.id}</Link></td><td>{when(e.arrived_at)}</td><td>{e.chief_complaint}</td><td><Status value={e.status} /></td></tr>
            ))}
          </tbody>
        </table>
      )}
      {tab === "bills" && (
        <table className="data">
          <thead><tr><th>Bill</th><th>Type</th><th>Status</th><th className="num">Net</th><th className="num">Due</th></tr></thead>
          <tbody>
            {data.invoices.map((e: any) => (
              <tr key={e.id}><td><Link to={`/billing/${e.id}`}>{e.number}</Link></td><td>{e.bill_type}</td><td><Status value={e.payment_status} /></td><td className="num">{money(e.net_paise)}</td><td className="num">{money(e.due_paise)}</td></tr>
            ))}
          </tbody>
        </table>
      )}
      {tab === "admissions" && (
        <table className="data">
          <thead><tr><th>Admission</th><th>Status</th><th>Admitted</th></tr></thead>
          <tbody>{data.admissions.map((e: any) => <tr key={e.id}><td><Link to={`/admissions/${e.id}`}>{e.id}</Link></td><td><Status value={e.status} /></td><td>{when(e.admitted_at)}</td></tr>)}</tbody>
        </table>
      )}
      {tab === "timeline" && <PatientMessage patient={p} />}
      {tab === "documents" && (
        <table className="data">
          <thead><tr><th>When</th><th>Type</th><th>Title</th><th></th></tr></thead>
          <tbody>
            {data.documents.map((d: any) => (
              <tr key={d.id}>
                <td>{when(d.uploaded_at)}</td>
                <td>{d.document_type}</td>
                <td>{d.title || d.filename}</td>
                <td className="row-actions">
                  <a href={fileUrl(`/api/documents/${d.id}/file`)} target="_blank">Open</a>
                  <SendDocument patient={p} documentId={d.id} title={d.title || d.filename} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {docOpen && <UploadDoc patientId={p.id} onClose={() => setDocOpen(false)} />}
    </Page>
  );
}

export function UploadDoc({ patientId, entityType, entityId, onClose }: { patientId: string; entityType?: string; entityId?: string; onClose: () => void }) {
  const [type, setType] = useState("Lab report");
  const [title, setTitle] = useState("");
  const { data } = useData<{ items: any[] }>("/api/master/document_type");
  return (
    <Modal title="Add document" onClose={onClose} footer={<span className="muted">Stored on this server. 8 MB, PDF or image.</span>}>
      <div className="grid-form">
        <Field label="Type">
          <select value={type} onChange={(e) => setType(e.target.value)}>
            {(data?.items || [{ name: type }]).map((d) => <option key={d.name}>{d.name}</option>)}
          </select>
        </Field>
        <Field label="Title"><input value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
        <Field label="File" className="span-2">
          <input type="file" accept="application/pdf,image/*" onChange={async (e) => {
            const file = e.target.files?.[0];
            if (!file) return;
            const content_base64 = await fileToBase64(file);
            await run(() => api("/api/documents", { method: "POST", body: JSON.stringify({ patient_id: patientId, document_type: type, title: title || file.name, filename: file.name, mime_type: file.type, content_base64, entity_type: entityType, entity_id: entityId }) }), "Document stored");
            onClose();
          }} />
        </Field>
      </div>
    </Modal>
  );
}

function fileToBase64(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

export function QueuePage({ mine = false }: { mine?: boolean }) {
  const canAssign = useApp((state) => state.can("opd.assign"));
  const { data, error, loading } = useData<{ items: any[] }>(`/api/queue${mine ? "?mine=1" : ""}`);
  const { data: doctors } = useData<{ items: any[] }>(canAssign ? "/api/doctors" : null);
  const items = data?.items || [];
  return (
    <Page title={mine ? "Doctor Queue" : "Today's OPD"} note="Call the next patient, then open the OPD workspace.">
      {loading && !data && <Loading label="Opening the queue…" />}
      {error && <ErrorState message={error} />}
      {!loading && data && !items.length && <Empty text="Queue is clear." />}
      <section className="panel simple-queue">
        <header><h2>Today's Queue</h2></header>
        <div className="body">
          {items.map((q) => (
            <article className="queue-card" key={q.id}>
              <div>
                <strong>{q.patient_name}</strong>
                <div className="muted pid">{q.patient_id} · T-{String(q.token_no).padStart(3, "0")}</div>
                <div>{q.age_display || "Age not recorded"} · {q.gender || "Gender not recorded"} · {q.doctor_name || "Doctor not assigned"}</div>
              </div>
              <div className="queue-card-actions">
                {canAssign && <select aria-label={`Doctor for ${q.patient_name}`} value={q.doctor_id || ""} onChange={(event) => run(() => api(`/api/opd/${q.encounter_id}/assign`, { method: "POST", body: JSON.stringify({ doctor_id: event.target.value }) }), "Doctor assigned")}>
                  <option value="">Assign doctor</option>
                  {(doctors?.items || []).map((doctor) => <option key={doctor.id} value={doctor.id}>{doctor.title || "Dr."} {doctor.full_name} · {doctor.specialty || ""}</option>)}
                </select>}
                {q.status === "WAITING" && <button className="btn primary" type="button" onClick={() => run(() => api(`/api/queue/${q.id}/status`, { method: "POST", body: JSON.stringify({ status: "CALLED" }) }), "Patient called")}>CALL PATIENT</button>}
                {q.status === "CALLED" && <span className="status normal">CALLED</span>}
                <Link className="btn" to={`/consult/${q.encounter_id}`}>Open OPD</Link>
              </div>
            </article>
          ))}
        </div>
      </section>
    </Page>
  );
}

export function Documents() {
  const [query, setQuery] = useState("");
  const [path, setPath] = useState("/api/documents");
  const { data, error, loading } = useData<{ items: any[] }>(path);
  return (
    <Page title="Documents" note="Search by patient ID, name, encounter, prescription, or document type." actions={
      <form onSubmit={(e) => { e.preventDefault(); const q = query.trim(); setPath(q ? `/api/documents?q=${encodeURIComponent(q)}` : "/api/documents"); }}>
        <input aria-label="Search documents" placeholder="Patient ID, name, or document" value={query} onChange={(e) => setQuery(e.target.value)} style={{ width: 220 }} />
      </form>
    }>
      {loading && !data && <Loading label="Opening documents…" />}
      {error && <ErrorState message={error} />}
      {!loading && data && !data.items?.length && <Empty text="No documents match this search." />}
      <div className="table-wrap">
        <table className="data">
          <thead><tr><th>When</th><th>Type</th><th>Patient</th><th>Encounter</th><th>Recorded by</th><th>Status</th><th></th></tr></thead>
          <tbody>
            {(data?.items || []).map((d) => (
              <tr key={d.id}>
                <td>{when(d.uploaded_at)}</td>
                <td>{d.document_type}</td>
                <td><Link to={`/patients/${d.patient_id}`}>{d.patient_name || d.patient_id}</Link><div className="muted pid">{d.patient_id}</div></td>
                <td className="pid">{d.notes || d.entity_id || "—"}</td>
                <td>{d.uploaded_by_name || "—"}</td>
                <td>{d.active ? "Filed" : "Withdrawn"}</td>
                <td className="row-actions">
                  <a href={fileUrl(`/api/documents/${d.id}/file`)} target="_blank" rel="noreferrer">View</a>
                  <a href={fileUrl(`/api/documents/${d.id}/file`)} target="_blank" rel="noreferrer">Print</a>
                  <a href={fileUrl(`/api/documents/${d.id}/file`)} download={d.filename || "document.pdf"}>Download</a>
                  <SendDocument patient={{ id: d.patient_id, name: d.patient_name || d.patient_id }} documentId={d.id} title={d.title || d.filename} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Page>
  );
}

export function Leads() {
  const { data } = useData<{ items: any[] }>("/api/leads");
  const navigate = useNavigate();
  return (
    <Page kicker="Website" title="Leads" actions={<button className="btn" onClick={() => run(() => api("/api/leads/sync", { method: "POST" }), "Sync attempted")}>Sync</button>}>
      <p className="muted">The public website is optional. If MongoDB is down, register the caller here or at the desk. The hospital does not stop.</p>
      <table className="data">
        <thead><tr><th>Name</th><th>Phone</th><th>Message</th><th>Status</th><th></th></tr></thead>
        <tbody>
          {(data?.items || []).map((lead) => (
            <tr key={lead.id}>
              <td>{lead.name}</td>
              <td>{lead.phone}</td>
              <td>{lead.message}</td>
              <td><Status value={lead.status} /></td>
              <td className="row-actions">
                <button className="btn small" onClick={() => navigate(`/register?phone=${encodeURIComponent(lead.phone || "")}&name=${encodeURIComponent(lead.name || "")}`)}>Register</button>
                <button className="btn small" onClick={() => run(() => api(`/api/leads/${lead.id}/archive`, { method: "POST" }), "Archived")}>Archive</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Page>
  );
}
