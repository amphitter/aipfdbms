import { Fragment, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, fileUrl, money, paise, when } from "../api";
import { useApp } from "../store";
import { Field, Loading, Page, Status, run, useData } from "../ui";

export { BillingCounter as Billing } from "./billing-counter";

function freshKey(scope: string) {
  const id = typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : String(Date.now());
  return `${scope}-${id}`;
}

export function InvoicePage() {
  const { id } = useParams();
  const { data } = useData<any>(id ? `/api/invoices/${id}` : null);
  const { data: doc } = useData<any>(id ? `/api/invoices/${id}/document` : null);
  const { data: services } = useData<{ items: any[] }>("/api/services");
  const { data: deposits } = useData<{ items: any[] }>(data ? `/api/deposits?patient_id=${data.patient_id}` : null);
  const { data: modes } = useData<{ items: any[] }>("/api/master/payment_mode");
  const { data: depositTypes } = useData<{ items: any[] }>("/api/master/deposit_type");
  const { data: taxRates } = useData<{ items: any[] }>("/api/master/tax_rate");
  const can = useApp((s) => s.can);
  const [service, setService] = useState("");
  const [taxCode, setTaxCode] = useState("");
  const [discount, setDiscount] = useState("");
  const [reason, setReason] = useState("");
  const [mode, setMode] = useState("");
  const [amount, setAmount] = useState("");
  const [reference, setReference] = useState("");
  const [depositType, setDepositType] = useState("");
  const [depositAmount, setDepositAmount] = useState("");
  const [refundPayment, setRefundPayment] = useState("");
  const [refundAmount, setRefundAmount] = useState("");
  const [refundReason, setRefundReason] = useState("");
  const modeNames = (modes?.items || []).map((item) => item.name).filter(Boolean);
  const typeNames = (depositTypes?.items || []).map((item) => item.name).filter(Boolean);
  useEffect(() => {
    if (modeNames.length && !modeNames.includes(mode)) setMode(modeNames[0]);
  }, [modeNames.join("|")]);
  useEffect(() => {
    if (typeNames.length && !typeNames.includes(depositType)) setDepositType(typeNames[0]);
  }, [typeNames.join("|")]);
  if (!data) return <Page title="Bill"><Loading label="Opening bill…" /></Page>;
  const grouped = groupItems(data.items || []);
  return (
    <Page kicker="Bill" title={data.number} actions={
      <>
        <a className="btn" href={fileUrl(`/api/invoices/${data.id}/pdf`)} target="_blank" rel="noreferrer">Print bill</a>
        <Link className="btn" to={`/patients/${data.patient_id}`}>Documents</Link>
      </>
    }>
      <div className="grid-2">
        <div className="bill">
          <div className="bill-head">
            <img src="/api/public/logo" alt="" />
            <div>
              <h3>{doc?.hospital?.name || "AIPF Mission Hospital"}</h3>
              <div>{doc?.hospital?.tagline}</div>
              <div className="muted">{doc?.hospital?.address_line1}, {doc?.hospital?.address_line2}, {doc?.hospital?.city} {doc?.hospital?.pin}</div>
            </div>
          </div>
          <div className="bill-grid">
            {(doc?.fields || []).map((f: any) => (
              <div key={f.label}><strong>{f.label}</strong>{f.value || "—"}</div>
            ))}
          </div>
          <div className="panel-h" style={{ marginTop: 8 }}>Services / billing transactions</div>
          <table className="data">
            <thead><tr><th>Description</th><th>Category</th><th className="num">Rate</th><th className="num">Qty</th><th className="num">Amount</th></tr></thead>
            <tbody>
              {grouped.map(([cat, items]) => (
                <Fragment key={cat}>
                  <tr><td colSpan={5}><strong>{cat}</strong></td></tr>
                  {items.map((item: any) => (
                    <tr key={item.id}>
                      <td>{item.description} {data.status === "DRAFT" && <button className="btn small" onClick={() => run(() => api(`/api/invoice-items/${item.id}`, { method: "DELETE" }), "Line removed")}>Remove</button>}</td>
                      <td>{item.category}</td>
                      <td className="num">{money(item.rate_paise)}</td>
                      <td className="num">{item.qty}</td>
                      <td className="num">{money(item.amount_paise)}</td>
                    </tr>
                  ))}
                </Fragment>
              ))}
            </tbody>
          </table>
          <div style={{ display: "flex", justifyContent: "space-between", marginTop: 8 }}>
            <div>
              {data.payment_status === "PAID" && data.status !== "VOID" ? <div className="paid-stamp">PAID<div style={{ fontSize: 11 }}>{when(data.finalized_at)}</div></div> : <Status value={data.payment_status} />}
              <p><strong>Amount in words.</strong> {data.amount_in_words}</p>
            </div>
            <table className="data" style={{ width: 280 }}>
              <tbody>
                <tr><td>Gross</td><td className="num">{money(data.gross_paise)}</td></tr>
                <tr><td>Discount</td><td className="num">{money(data.discount_paise)}</td></tr>
                <tr><td>Tax</td><td className="num">{money(data.tax_paise)}</td></tr>
                <tr><td>Net</td><td className="num">{money(data.net_paise)}</td></tr>
                <tr><td>Deposit applied</td><td className="num">{money(data.deposit_applied_paise)}</td></tr>
                <tr><td>Paid</td><td className="num">{money(data.paid_paise)}</td></tr>
                <tr><td>Due</td><td className="num">{money(data.due_paise)}</td></tr>
              </tbody>
            </table>
          </div>
          <p className="muted">Reprint does not create a new bill. Number {data.number} stays with this invoice.</p>
        </div>
        <div>
          {data.status === "DRAFT" && (
            <div className="panel">
              <h2>Before finalizing</h2>
              <div className="body grid-form">
                <Field label="Add service" className="span-2">
                  <select value={service} onChange={(e) => setService(e.target.value)}>
                    <option value="">Choose</option>
                    {(services?.items || []).map((s) => <option key={s.id} value={s.id}>{s.name} · {money(s.rate_paise)}</option>)}
                  </select>
                </Field>
                <Field label="Tax rate">
                  <select value={taxCode} onChange={(e) => setTaxCode(e.target.value)}>
                    <option value="">No tax</option>
                    {(taxRates?.items || []).map((rate) => <option key={rate.id} value={rate.code || rate.name}>{rate.name}</option>)}
                  </select>
                </Field>
                <button className="btn" onClick={() => {
                  const chosen = services?.items?.find((s: any) => s.id === service);
                  if (!chosen) return;
                  run(() => api(`/api/invoices/${data.id}/items`, { method: "POST", body: JSON.stringify({ description: chosen.name, category: chosen.category, qty: 1, unit: chosen.unit, source_module: "service", master_item_id: chosen.id, tax_code: taxCode }) }), "Service added");
                }}>Add</button>
                <Field label="Bill discount (Rs)"><input value={discount} onChange={(e) => setDiscount(e.target.value)} /></Field>
                <Field label="Reason"><input value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
                <button className="btn" onClick={() => run(() => api(`/api/invoices/${data.id}/discount`, { method: "POST", body: JSON.stringify({ discount_paise: paise(discount), reason }) }), "Discount applied")}>Apply discount</button>
                <button className="btn" type="button" onClick={() => run(() => Promise.resolve({}), "Draft is saved. Finalize bill when the charges are complete.")}>Save draft</button>
                <button className="btn primary" onClick={() => run(() => api(`/api/invoices/${data.id}/finalize`, { method: "POST" }), "Bill finalized. The print dialog does not open.")}>Finalize bill</button>
              </div>
            </div>
          )}
          <div className="panel">
            <h2>Payment</h2>
            <div className="body grid-form">
              <Field label="Mode">
                <select value={mode} onChange={(e) => setMode(e.target.value)}>
                  {modeNames.map((name) => <option key={name}>{name}</option>)}
                </select>
              </Field>
              <Field label="Amount (Rs)"><input value={amount} onChange={(e) => setAmount(e.target.value)} placeholder={String((data.due_paise || 0) / 100)} /></Field>
              <Field label="Reference" className="span-2"><input value={reference} onChange={(e) => setReference(e.target.value)} placeholder="UPI ref / cheque no." /></Field>
              {can("payment.create") && <button className="btn primary" onClick={() => run(() => api(`/api/invoices/${data.id}/payments`, { method: "POST", body: JSON.stringify({ mode, amount_paise: paise(amount || (data.due_paise || 0) / 100), reference, idempotency_key: freshKey("pay") }) }), "Payment recorded")}>Receive payment</button>}
              {can("deposit.create") && (
                <>
                  <Field label="Deposit type">
                    <select value={depositType} onChange={(e) => setDepositType(e.target.value)}>
                      {typeNames.map((name) => <option key={name}>{name}</option>)}
                    </select>
                  </Field>
                  <Field label="Deposit (Rs)"><input value={depositAmount} onChange={(e) => setDepositAmount(e.target.value)} /></Field>
                  <button className="btn" onClick={() => run(() => api("/api/deposits", { method: "POST", body: JSON.stringify({ patient_id: data.patient_id, amount_paise: paise(depositAmount), mode, deposit_type: depositType, idempotency_key: freshKey("dep") }) }), "Deposit received. It is not applied to this bill until you allocate it.")}>Receive deposit</button>
                </>
              )}
              {(deposits?.items || []).filter((d: any) => d.balance_paise > 0 && d.status !== "REFUNDED").map((d: any) => (
                <Fragment key={d.id}>
                  {can("deposit.allocate") && <button className="btn" onClick={() => run(() => api(`/api/invoices/${data.id}/deposit`, { method: "POST", body: JSON.stringify({ deposit_id: d.id, amount_paise: d.balance_paise, idempotency_key: freshKey("alloc") }) }), "Deposit allocated")}>Allocate {money(d.balance_paise)} {d.deposit_type || "deposit"}</button>}
                  {can("payment.refund") && <button className="btn" onClick={() => run(() => api(`/api/deposits/${d.id}/refund`, { method: "POST", body: JSON.stringify({ reason: "Unused deposit refund", idempotency_key: freshKey("dref") }) }), "Unused deposit refunded")}>Refund unused {money(d.balance_paise)}</button>}
                </Fragment>
              ))}
            </div>
          </div>
          <div className="panel">
            <h2>Payments on this bill</h2>
            <table className="data">
              <tbody>
                {(data.payments || []).map((p: any) => (
                  <tr key={p.id}><td>{when(p.received_at)}</td><td>{p.kind}</td><td>{p.mode}</td><td className="num">{money(p.amount_paise)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.status === "FINALIZED" && (
            <div className="panel">
              <h2>Correction — not a silent edit</h2>
              <div className="body grid-form">
                <Field label="Adjustment Rs (negative reduces)"><input id="adj" /></Field>
                <Field label="Reason"><input id="adj-reason" /></Field>
                <button className="btn" onClick={() => {
                  const amount_paise = paise((document.getElementById("adj") as HTMLInputElement).value);
                  const why = (document.getElementById("adj-reason") as HTMLInputElement).value;
                  run(() => api(`/api/invoices/${data.id}/adjust`, { method: "POST", body: JSON.stringify({ amount_paise, description: "Adjustment", reason: why }) }), "Adjustment recorded");
                }}>Post adjustment</button>
                {can("payment.refund") && (
                  <>
                    <Field label="Refund this payment">
                      <select value={refundPayment} onChange={(e) => setRefundPayment(e.target.value)}>
                        <option value="">Choose</option>
                        {(data.payments || []).filter((p: any) => p.kind !== "REFUND").map((p: any) => (
                          <option key={p.id} value={p.id}>{p.kind} {p.mode} {money(p.amount_paise)}</option>
                        ))}
                      </select>
                    </Field>
                    <Field label="Refund Rs"><input value={refundAmount} onChange={(e) => setRefundAmount(e.target.value)} /></Field>
                    <Field label="Refund reason" className="span-2"><input value={refundReason} onChange={(e) => setRefundReason(e.target.value)} /></Field>
                    <button className="btn danger" onClick={() => {
                      const chosen = (data.payments || []).find((p: any) => p.id === refundPayment);
                      if (!chosen || !refundReason) return;
                      run(() => api(`/api/invoices/${data.id}/refund`, { method: "POST", body: JSON.stringify({ payment_id: chosen.id, amount_paise: paise(refundAmount), mode: chosen.mode, reason: refundReason, idempotency_key: freshKey("ref") }) }), "Refund recorded");
                    }}>Refund</button>
                  </>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </Page>
  );
}

function groupItems(items: any[]) {
  const order = ["CONSULTATION", "HOSPITAL SERVICES", "PHARMACY", "LABORATORY", "IPD", "OT", "PROCEDURE", "OTHER", "ADJUSTMENT"];
  const map = new Map<string, any[]>();
  for (const item of items) {
    const key = item.category || "OTHER";
    map.set(key, [...(map.get(key) || []), item]);
  }
  return [...map.entries()].sort((a, b) => order.indexOf(a[0]) - order.indexOf(b[0]));
}
