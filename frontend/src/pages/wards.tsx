import { useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, money, when } from "../api";
import { useApp } from "../store";
import { Empty, ErrorState, Field, Flow, Loading, Page, PatientSearchSelect, Status, run, useData, type PatientSummary } from "../ui";

function freshKey() {
  return `desk-${Date.now().toString(36)}-${Math.random().toString(16).slice(2)}`;
}

function useActionKey() {
  const pending = useRef<Record<string, string>>({});
  return {
    keyFor(action: string) {
      if (!pending.current[action]) pending.current[action] = freshKey();
      return pending.current[action];
    },
    clear(action: string) {
      pending.current[action] = "";
    },
  };
}

export function Beds() {
  const { data, error, loading } = useData<any>("/api/beds");
  const [bed, setBed] = useState<any>(null);
  const [patient, setPatient] = useState<PatientSummary | null>(null);
  const [setup, setSetup] = useState({ ward: "", code: "", kind: "", room: "", rate: "1000", bedName: "1" });
  const keys = useActionKey();
  return (
    <Page title="Beds" note="Occupancy by ward and room. Sample beds from the install are marked and are not hospital capacity.">
      {loading && !data && <Loading label="Opening the bed board…" />}
      {error && <ErrorState message={error} />}
      <div className="beds">
        {(data?.wards || []).map((ward: any) => (
          <section key={ward.id}>
            <h3 className="ward-name">{ward.name}</h3>
            <div className="bed-grid">
              {(ward.beds || []).map((b: any) => (
                <button key={b.id} className={`bed ${b.status}`} onClick={() => setBed(b)}>
                  <strong>{b.room_name} · {b.name} {String(b.id).startsWith("BD-") ? <span className="sample-badge">SAMPLE</span> : null}</strong>
                  <Status value={b.status} />
                  <small>{b.patient_name || money(b.daily_rate_paise) + " / day"}</small>
                </button>
              ))}
            </div>
          </section>
        ))}
      </div>
      {bed && (
        <div className="panel" style={{ marginTop: 12 }}>
          <h2>{bed.room_name} {bed.name} · {bed.status}</h2>
          <div className="body">
            {bed.admission_id ? (
              <Link className="btn primary" to={`/admissions/${bed.admission_id}`}>Open {bed.patient_name}</Link>
            ) : bed.status === "AVAILABLE" ? (
              <div className="grid-form">
                <PatientSearchSelect value={patient} onChange={setPatient} />
                <button className="btn primary" disabled={!patient} onClick={() => run(() => api("/api/admissions", { method: "POST", body: JSON.stringify({ patient_id: patient?.id, bed_id: bed.id, reason: "Desk admission", idempotency_key: keys.keyFor("admit") }) }), "Admitted").then(() => keys.clear("admit"))}>Admit to this bed</button>
              </div>
            ) : (
              <div className="row-actions">
                <button className="btn" onClick={() => run(() => api(`/api/beds/${bed.id}/status`, { method: "POST", body: JSON.stringify({ status: "AVAILABLE" }) }), "Bed released")}>Mark available</button>
                <button className="btn" onClick={() => run(() => api(`/api/beds/${bed.id}/status`, { method: "POST", body: JSON.stringify({ status: "MAINTENANCE", notes: "Cleaning" }) }), "Blocked for maintenance")}>Maintenance</button>
              </div>
            )}
          </div>
        </div>
      )}
      <details className="panel" style={{ marginTop: 12 }}>
        <summary>Ward, room, and bed setup</summary>
        <div className="body grid-form">
          <Field label="Ward name"><input value={setup.ward} onChange={(e) => setSetup({ ...setup, ward: e.target.value })} /></Field>
          <Field label="Code"><input value={setup.code} onChange={(e) => setSetup({ ...setup, code: e.target.value })} /></Field>
          <Field label="Type from the register"><input value={setup.kind} onChange={(e) => setSetup({ ...setup, kind: e.target.value })} placeholder="Entered here, not a fixed list" /></Field>
          <Field label="Room"><input value={setup.room} onChange={(e) => setSetup({ ...setup, room: e.target.value })} /></Field>
          <Field label="Daily rate, whole rupees"><input value={setup.rate} onChange={(e) => setSetup({ ...setup, rate: e.target.value })} /></Field>
          <Field label="Bed"><input value={setup.bedName} onChange={(e) => setSetup({ ...setup, bedName: e.target.value })} /></Field>
          <button className="btn" onClick={() => run(async () => {
            const ward = await api<any>("/api/wards", { method: "POST", body: JSON.stringify({ name: setup.ward, code: setup.code, ward_type: setup.kind }) });
            const rupees = Number(setup.rate);
            const room = await api<any>("/api/rooms", { method: "POST", body: JSON.stringify({ ward_id: ward.id, name: setup.room, room_type: setup.kind, daily_rate_paise: Number.isInteger(rupees) ? rupees * 100 : 0 }) });
            await api("/api/beds", { method: "POST", body: JSON.stringify({ room_id: room.id, name: setup.bedName }) });
          }, "Ward, room, and bed saved")}>Save setup</button>
        </div>
      </details>
    </Page>
  );
}

export function Admissions() {
  const { id } = useParams();
  if (id) return <AdmissionDetail id={id} />;
  return <AdmissionList />;
}

function AdmissionList() {
  const { data, error, loading } = useData<{ items: any[] }>("/api/admissions?status=CURRENT");
  return (
    <Page title="Admissions" note="Active inpatient stays. Open a row for charges and discharge.">
      {loading && !data && <Loading label="Opening admissions…" />}
      {error && <ErrorState message={error} />}
      {!loading && data && !data.items?.length && <Empty text="No one is currently admitted." />}
      <div className="table-wrap"><table className="data">
        <thead><tr><th>Admission</th><th>Patient</th><th>Ward</th><th>Bed</th><th>Doctor</th><th>Since</th></tr></thead>
        <tbody>
          {(data?.items || []).map((a) => (
            <tr key={a.id}>
              <td><Link to={`/admissions/${a.id}`}>{a.id}</Link></td>
              <td>{a.patient_name}</td>
              <td>{a.ward_name}</td>
              <td>{a.bed_name}</td>
              <td>{a.doctor_name}</td>
              <td>{when(a.admitted_at)}</td>
            </tr>
          ))}
        </tbody>
      </table></div>
    </Page>
  );
}

function AdmissionDetail({ id }: { id: string }) {
  const { data } = useData<any>(`/api/admissions/${id}`);
  const { data: board } = useData<any>("/api/beds");
  const [summary, setSummary] = useState("");
  const [condition, setCondition] = useState("Stable");
  const [bed, setBed] = useState("");
  const [reason, setReason] = useState("Clinical transfer");
  const keys = useActionKey();
  if (!data) return <Page title="Admission"><Loading label="Opening admission…" /></Page>;
  const free = (board?.wards || []).flatMap((w: any) => (w.beds || []).filter((b: any) => b.status === "AVAILABLE").map((b: any) => ({ ...b, ward: w.name })));
  return (
    <Page kicker="Admission" title={`${data.patient_name}`} actions={<Status value={data.status} />}>
      <div className="banner">
        <div>
          <h2>{data.id}</h2>
          <div>{data.ward_name} · {data.room_name} · {data.bed_name} · {money(data.daily_rate_paise)} / day</div>
          <div className="muted">{data.diagnosis || data.reason} · {data.doctor_name}</div>
        </div>
        <Link to={`/patients/${data.patient_id}`}>Patient record</Link>
      </div>
      <div className="grid-2">
        <div className="panel">
          <h2>Charges</h2>
          <table className="data">
            <thead><tr><th>Date</th><th>Description</th><th className="num">Amount</th></tr></thead>
            <tbody>
              {(data.charges || []).map((c: any) => <tr key={c.id}><td>{c.charge_date}</td><td>{c.description}</td><td className="num">{money(c.amount_paise)}</td></tr>)}
            </tbody>
          </table>
          <div className="body row-actions">
            <button className="btn" onClick={() => run(() => api(`/api/admissions/${id}/bed-day`, { method: "POST", body: JSON.stringify({ idempotency_key: keys.keyFor("bed") }) }), "Today's bed charge posted").then(() => keys.clear("bed"))}>Post today's bed charge</button>
            {data.invoices?.[0] && <Link className="btn" to={`/billing/${data.invoices[0].id}`}>Open bill</Link>}
          </div>
        </div>
        <div className="panel">
          <h2>Move or discharge</h2>
          <div className="body grid-form">
            <Field label="Transfer to">
              <select value={bed} onChange={(e) => setBed(e.target.value)}>
                <option value="">Choose a free bed</option>
                {free.map((b: any) => <option key={b.id} value={b.id}>{b.ward} · {b.name}</option>)}
              </select>
            </Field>
            <Field label="Reason"><input value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
            <button className="btn" onClick={() => run(() => api(`/api/admissions/${id}/transfer`, { method: "POST", body: JSON.stringify({ bed_id: bed, reason, idempotency_key: keys.keyFor("move") }) }), "Transferred").then(() => keys.clear("move"))}>Transfer</button>
            <Field label="Discharge condition"><input value={condition} onChange={(e) => setCondition(e.target.value)} /></Field>
            <Field label="Discharge summary" className="span-2"><textarea value={summary} onChange={(e) => setSummary(e.target.value)} /></Field>
            <button className="btn danger" onClick={() => run(() => api(`/api/admissions/${id}/discharge`, { method: "POST", body: JSON.stringify({ discharge_summary: summary, discharge_condition: condition, idempotency_key: keys.keyFor("discharge") }) }), "Discharged and bed freed").then(() => keys.clear("discharge"))}>Discharge</button>
            <button className="btn" onClick={() => run(async () => {
              await api(`/api/admissions/${id}/discharge-document`, { method: "POST", body: JSON.stringify({ idempotency_key: keys.keyFor("summary") }) });
              const file = await api<Response>(`/api/admissions/${id}/discharge-document`);
              const blob = await file.blob();
              window.open(URL.createObjectURL(blob), "_blank", "noopener");
            }, "Discharge summary opened").then(() => keys.clear("summary"))}>Open discharge summary</button>
          </div>
        </div>
      </div>
    </Page>
  );
}

function localStamp(value: string) {
  if (!value) return "";
  return value.length === 16 ? `${value}:00` : value.slice(0, 19);
}

function TeamAssign({ caseId }: { caseId: string }) {
  const can = useApp((s) => s.can);
  const allowed = can("ot.team.manage") || can("ot.manage");
  const { data } = useData<{ items: any[] }>(allowed ? "/api/staff" : null);
  const [userId, setUserId] = useState("");
  const [fn, setFn] = useState("");
  const key = useRef("");
  if (!allowed) return null;
  return (
    <div className="grid-form span-2">
      <Field label="Team member">
        <select value={userId} onChange={(e) => { setUserId(e.target.value); key.current = ""; }}>
          <option value="">Choose a person</option>
          {(data?.items || []).map((person) => <option key={person.id} value={person.id}>{person.full_name}{person.title ? ` · ${person.title}` : ""}</option>)}
        </select>
      </Field>
      <Field label="Function">
        <select value={fn} onChange={(e) => { setFn(e.target.value); key.current = ""; }}>
          <option value="">Choose a function</option>
          <option value="surgeon">Surgeon</option>
          <option value="assistant">Assistant</option>
          <option value="anesthetist">Anesthetist</option>
          <option value="nurse">Nurse</option>
          <option value="technician">Technician</option>
        </select>
      </Field>
      <button className="btn small" disabled={!userId || !fn} onClick={() => {
        if (!userId || !fn) return;
        if (!key.current) key.current = freshKey();
        run(() => api(`/api/ot/${caseId}/team`, { method: "POST", body: JSON.stringify({ user_id: userId, function: fn, idempotency_key: key.current }) }), "Team member added").then(() => {
          key.current = "";
          setUserId("");
          setFn("");
        });
      }}>Add to team</button>
    </div>
  );
}

export function OtPage() {
  const { id } = useParams();
  const keys = useActionKey();
  const { data } = useData<{ items: any[] }>("/api/ot");
  const { data: theatres } = useData<{ items: any[] }>("/api/ot/theatres");
  const { data: procedures } = useData<{ items: any[] }>("/api/ot/procedures");
  const { data: doctors } = useData<{ items: any[] }>("/api/doctors");
  const selected = id || data?.items?.[0]?.id;
  const { data: one } = useData<any>(selected ? `/api/ot/${selected}` : null);
  const [request, setRequest] = useState({ patient_id: "", encounter_id: "", admission_id: "", procedure_id: "", indication: "", priority: "ROUTINE" });
  const [requestPatient, setRequestPatient] = useState<PatientSummary | null>(null);
  const [plan, setPlan] = useState({ theatre_id: "", surgeon_id: "", start_at: "", end_at: "", reason: "" });
  const [preop, setPreop] = useState({ consent_status: "OBTAINED", readiness: "READY", assessment: "" });
  const [intra, setIntra] = useState("");
  const [post, setPost] = useState("");
  const [notes, setNotes] = useState<any>({ outcome: "SUCCESSFUL", procedure_notes: "", findings: "", complications: "", post_op_instructions: "", pre_op_notes: "" });
  const act = (path: string, body: any, ok: string, key: string) => run(() => api(path, { method: "POST", body: JSON.stringify({ ...body, idempotency_key: keys.keyFor(key) }) }), ok).then(() => keys.clear(key));
  return (
    <Page title="Operating theatres" note="Scheduled, in progress, and completed cases. Cancelled and postponed stay on the record.">
      {one?.status && <Flow steps={["REQUESTED", "APPROVED", "SCHEDULED", "PRE_OP", "IN_PROGRESS", "RECOVERY", "COMPLETED"]} current={one.status} off={["CANCELLED", "POSTPONED"].includes(one.status) ? one.status : ""} />}
      <div className="panel" style={{ marginBottom: 16 }}>
        <h2>Request</h2>
        <div className="body grid-form">
          <PatientSearchSelect value={requestPatient} onChange={(patient) => { setRequestPatient(patient); setRequest({ ...request, patient_id: patient?.id || "" }); }} />
          <Field label="Encounter"><input value={request.encounter_id} onChange={(e) => setRequest({ ...request, encounter_id: e.target.value })} /></Field>
          <Field label="Admission"><input value={request.admission_id} onChange={(e) => setRequest({ ...request, admission_id: e.target.value })} /></Field>
          <Field label="Procedure">
            <select value={request.procedure_id} onChange={(e) => setRequest({ ...request, procedure_id: e.target.value })}>
              <option value="">Choose a procedure</option>
              {(procedures?.items || []).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>
          </Field>
          <Field label="Priority">
            <select value={request.priority} onChange={(e) => setRequest({ ...request, priority: e.target.value })}>
              <option>ROUTINE</option><option>URGENT</option><option>EMERGENCY</option>
            </select>
          </Field>
          <Field label="Indication" className="span-2"><input value={request.indication} onChange={(e) => setRequest({ ...request, indication: e.target.value })} /></Field>
          <button className="btn primary" onClick={() => act("/api/ot/requests", request, "Request recorded", "request")}>Request surgery</button>
        </div>
      </div>
      <div className="grid-2">
        <table className="data">
          <thead><tr><th>Case</th><th>Patient</th><th>Procedure</th><th>Status</th></tr></thead>
          <tbody>
            {(data?.items || []).map((item) => (
              <tr key={item.id}>
                <td><Link to={`/ot/${item.id}`}>{item.id}</Link></td>
                <td>{item.patient_name}</td>
                <td>{item.procedure_name}</td>
                <td><Status value={item.status} /> {item.outcome && <Status value={item.outcome} />}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {one && (
          <div className="panel">
            <h2>{one.procedure_name}</h2>
            <div className="body">
              <p>{one.patient_name} · Surgeon {one.surgeon_name || "—"} · Theatre {one.theatre_name || "—"} · <Status value={one.status} /></p>
              {one.indication && <p>{one.indication}</p>}
              {one.status === "NOTES_PENDING" && <div className="warn">OT notes are required. Record the outcome even if the procedure was unsuccessful or aborted.</div>}
              <div className="grid-form" style={{ marginTop: 10 }}>
                <Field label="Theatre">
                  {theatres && !(theatres.items || []).length ? (
                    <div className="warn">No OT theatres configured. <Link to="/admin/master?section=theatres">Configure Theatres</Link></div>
                  ) : (
                    <select value={plan.theatre_id} onChange={(e) => setPlan({ ...plan, theatre_id: e.target.value })}>
                      <option value="">Choose a theatre</option>
                      {(theatres?.items || []).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                    </select>
                  )}
                </Field>
                <Field label="Surgeon">
                  <select value={plan.surgeon_id} onChange={(e) => setPlan({ ...plan, surgeon_id: e.target.value })}>
                    <option value="">Choose a surgeon</option>
                    {(doctors?.items || []).map((item) => <option key={item.id} value={item.id}>{item.full_name}</option>)}
                  </select>
                </Field>
                <Field label="Start"><input type="datetime-local" value={plan.start_at} onChange={(e) => setPlan({ ...plan, start_at: e.target.value })} /></Field>
                <Field label="End"><input type="datetime-local" value={plan.end_at} onChange={(e) => setPlan({ ...plan, end_at: e.target.value })} /></Field>
                <Field label="Reason"><input value={plan.reason} onChange={(e) => setPlan({ ...plan, reason: e.target.value })} /></Field>
              </div>
              <div className="row-actions" style={{ marginTop: 10 }}>
                <button className="btn small" onClick={() => act(`/api/ot/${one.id}/approve`, {}, "Approved", "approve")}>Approve</button>
                <button className="btn small" onClick={() => act(`/api/ot/${one.id}/schedule`, { theatre_id: plan.theatre_id, surgeon_id: plan.surgeon_id, start_at: localStamp(plan.start_at), end_at: localStamp(plan.end_at) }, "Scheduled", "schedule")}>Schedule</button>
                <button className="btn small" onClick={() => act(`/api/ot/${one.id}/reschedule`, { theatre_id: plan.theatre_id, surgeon_id: plan.surgeon_id, start_at: localStamp(plan.start_at), end_at: localStamp(plan.end_at), reason: plan.reason || "Time moved" }, "Rescheduled", "reschedule")}>Reschedule</button>
              </div>
              <TeamAssign caseId={one.id} />
              <div className="grid-form" style={{ marginTop: 10 }}>
                <Field label="Consent">
                  <select value={preop.consent_status} onChange={(e) => setPreop({ ...preop, consent_status: e.target.value })}>
                    <option>PENDING</option><option>OBTAINED</option><option>REFUSED</option>
                  </select>
                </Field>
                <Field label="Readiness">
                  <select value={preop.readiness} onChange={(e) => setPreop({ ...preop, readiness: e.target.value })}>
                    <option>PENDING</option><option>READY</option><option>NOT_READY</option>
                  </select>
                </Field>
                <Field label="Pre-operative assessment" className="span-2"><textarea value={preop.assessment} onChange={(e) => setPreop({ ...preop, assessment: e.target.value })} /></Field>
                <button className="btn" onClick={() => act(`/api/ot/${one.id}/preop`, preop, "Pre-operative record saved", "preop")}>Save pre-op</button>
                <button className="btn" onClick={() => act(`/api/ot/${one.id}/start`, {}, "Procedure started", "start")}>Start</button>
                <Field label="Intra-operative note" className="span-2"><textarea value={intra} onChange={(e) => setIntra(e.target.value)} /></Field>
                <button className="btn" onClick={() => act(`/api/ot/${one.id}/intraop`, { notes: intra }, "Intra-operative note added", "intraop")}>Add intra-op</button>
                <button className="btn" onClick={() => act(`/api/ot/${one.id}/recovery`, {}, "In recovery", "recovery")}>Recovery</button>
                <Field label="Post-operative note" className="span-2"><textarea value={post} onChange={(e) => setPost(e.target.value)} /></Field>
                <button className="btn" onClick={() => act(`/api/ot/${one.id}/postop`, { notes: post }, "Post-operative note added", "postop")}>Add post-op</button>
                <button className="btn" onClick={() => act(`/api/ot/${one.id}/complete`, {}, "Case completed", "complete")}>Complete</button>
                <button className="btn" onClick={() => act(`/api/ot/${one.id}/charge`, {}, "Charge posted", "charge")}>Post charge</button>
                <button className="btn" onClick={() => run(async () => {
                  await api(`/api/ot/${one.id}/report`, { method: "POST", body: JSON.stringify({ idempotency_key: keys.keyFor("report") }) });
                  const file = await api<Response>(`/api/ot/${one.id}/report`);
                  window.open(URL.createObjectURL(await file.blob()), "_blank", "noopener");
                }, "Operation report opened").then(() => keys.clear("report"))}>Open report</button>
                <button className="btn danger" onClick={() => act(`/api/ot/${one.id}/cancel`, { reason: plan.reason || "Cancelled from the desk" }, "Cancelled", "cancel")}>Cancel</button>
              </div>
              {(one.intraop || []).length > 0 && <p style={{ marginTop: 10 }}>{one.intraop.length} intra-operative record{one.intraop.length === 1 ? "" : "s"} kept.</p>}
              <div className="grid-form" style={{ marginTop: 10 }}>
                <Field label="Outcome">
                  <select value={notes.outcome} onChange={(e) => setNotes({ ...notes, outcome: e.target.value })}>
                    <option>SUCCESSFUL</option>
                    <option>UNSUCCESSFUL</option>
                    <option>ABORTED</option>
                  </select>
                </Field>
                <Field label="Procedure notes" className="span-2"><textarea value={notes.procedure_notes} onChange={(e) => setNotes({ ...notes, procedure_notes: e.target.value })} /></Field>
                <button className="btn primary" onClick={() => run(() => api(`/api/ot/${one.id}/notes`, { method: "POST", body: JSON.stringify(notes) }), "OT notes recorded")}>Save legacy OT notes</button>
              </div>
              {one.procedure_notes && <p style={{ marginTop: 10 }}><strong>Recorded outcome {one.outcome}.</strong> {one.procedure_notes}</p>}
            </div>
          </div>
        )}
      </div>
    </Page>
  );
}
