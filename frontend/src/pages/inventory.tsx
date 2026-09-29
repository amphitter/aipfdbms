import { useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ApiError, api, money, paise } from "../api";
import { prepareBarcode } from "../barcode";
import { BarcodeScanner, PhonePair } from "../scanner";
import { useApp } from "../store";
import { Empty, ErrorState, Field, Loading, Modal, Page, Status, run, useData } from "../ui";
import { RegisterMedicine } from "./clinical";

const VIEWS: [string, string][] = [
  ["home", "Dashboard"],
  ["medicines", "Medicines"],
  ["packaging", "Packaging"],
  ["barcodes", "Barcodes"],
  ["batches", "Batches"],
  ["stock", "Stock"],
  ["movements", "Stock movements"],
  ["receive", "Receive"],
  ["adjustments", "Adjustments"],
  ["low", "Low stock"],
  ["expiring", "Expiring soon"],
  ["expired", "Expired"],
];

const VIEW_IDS = new Set(VIEWS.map(([id]) => id));

function localToday() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function plusDays(days: number) {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function batchStatus(product: any, batch: any) {
  if (product && !product.active) return "Inactive";
  if (!batch) return "No batch";
  const today = localToday();
  if (batch.expiry_date && batch.expiry_date < today) return "Expired";
  if (batch.expiry_date && batch.expiry_date <= plusDays(90)) return "Expiring";
  if (Number(product?.stock) <= Number(product?.reorder_level || 0)) return "Low";
  return "In stock";
}

function productBody(product: any, patch: any = {}) {
  const next = { ...product, ...patch };
  return {
    brand: next.brand || "",
    name: next.name || "",
    composition: next.composition || "",
    strength: next.strength || "",
    dosage_form: next.dosage_form || "",
    manufacturer: next.manufacturer || "",
    unit: next.unit || "Tablet",
    packaging: next.packaging || "",
    packaging_json: next.packaging_json || {},
    barcode: next.barcode || "",
    purchase_rate_paise: Number(next.purchase_rate_paise || 0),
    sale_rate_paise: Number(next.sale_rate_paise || 0),
    mrp_paise: Number(next.mrp_paise || 0),
    min_stock: Number(next.min_stock || 0),
    reorder_level: Number(next.reorder_level || 0),
    active: next.active !== false && next.active !== 0,
  };
}

export function Inventory() {
  const { view: raw = "home" } = useParams();
  const view = VIEW_IDS.has(raw) ? raw : "home";
  const [params] = useSearchParams();
  const focus = params.get("product") || "";
  const navigate = useNavigate();
  const canEdit = useApp((s) => s.can("inventory.edit"));
  const canAdjust = useApp((s) => s.can("inventory.adjust"));
  const { data, error, loading } = useData<{ items: any[] }>("/api/inventory/products?all=1");
  const { data: alerts } = useData<any>("/api/inventory/alerts");
  const products = data?.items || [];
  const [code, setCode] = useState("");
  const [hit, setHit] = useState<any>(null);
  const [unknown, setUnknown] = useState(false);
  const [scanError, setScanError] = useState("");
  const [scanner, setScanner] = useState(false);
  const [registering, setRegistering] = useState(false);
  const manualRef = useRef<HTMLInputElement>(null);

  async function identify(value = code) {
    const prepared = prepareBarcode(value);
    setCode(prepared.code);
    setHit(null);
    setUnknown(false);
    setScanError("");
    if (!prepared.code) return;
    if (prepared.error) {
      setScanError(prepared.error);
      return;
    }
    try {
      setHit(await api<any>("/api/inventory/barcodes/resolve", { method: "POST", body: JSON.stringify({ code: prepared.code }) }));
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setUnknown(true);
        setScanError("Barcode not registered");
        return;
      }
      setScanError(err instanceof Error ? err.message : "The barcode could not be checked.");
    }
  }

  function go(next: string, productId = "") {
    navigate(productId ? `/inventory/${next}?product=${encodeURIComponent(productId)}` : `/inventory/${next}`);
  }

  return (
    <Page title="Inventory" note="Medicines, batches, and hospital stock. A scan only identifies a barcode and does not change stock." actions={<button className="btn primary scan-launch" type="button" onClick={() => setScanner(true)}>Scan barcode</button>}>
      <nav className="inv-nav" aria-label="Inventory">
        {VIEWS.map(([id, label]) => (
          <Link key={id} className={view === id ? "on" : ""} to={`/inventory/${id}`}>{label}</Link>
        ))}
      </nav>
      <form className="panel lookup-sheet" onSubmit={(e) => { e.preventDefault(); identify(); }}>
        <div className="body">
          <div className="grid-form">
            <Field label="Barcode">
              <input ref={manualRef} aria-label="Barcode" value={code} placeholder="Scan or type the barcode. This does not change stock." onChange={(e) => { setCode(e.target.value); setHit(null); setUnknown(false); setScanError(""); }} />
            </Field>
            <div className="row-actions">
              <button className="btn" type="submit">Look up</button>
              <button className="btn" type="button" onClick={() => setScanner(true)}>Scan with webcam</button>
              <PhonePair onUse={(value) => identify(value)} />
            </div>
          </div>
          {scanError && <div className="warn" role="status">{scanError}{unknown ? ". No medicine was created." : ""}</div>}
          {unknown && (
            <div className="row-actions">
              {canEdit && <button className="btn primary" type="button" onClick={() => setRegistering(true)}>Register New Medicine</button>}
              <button className="btn" type="button" onClick={() => setScanner(true)}>Scan Again</button>
              <button className="btn" type="button" onClick={() => { setUnknown(false); manualRef.current?.focus(); }}>Enter Manually</button>
            </div>
          )}
          {hit && <KnownBarcode hit={hit} code={code} onProduct={() => go("medicines", hit.product.id)} onBatches={() => go("batches", hit.product.id)} onReceive={() => go("receive", hit.product.id)} onAgain={() => setScanner(true)} />}
        </div>
      </form>
      {loading && !data && <Loading label="Opening inventory…" />}
      {error && <ErrorState message={error} />}
      {view === "home" && <Dashboard alerts={alerts} products={products} onOpen={go} />}
      {view === "medicines" && <Medicines products={products} canEdit={canEdit} focus={focus} />}
      {view === "packaging" && <Packaging products={products} canEdit={canEdit} />}
      {view === "barcodes" && <Barcodes products={products} canEdit={canEdit} />}
      {view === "batches" && <Batches products={products} focus={focus} onReceive={(id) => go("receive", id)} />}
      {view === "stock" && <Stock products={products} onOpen={go} />}
      {view === "movements" && <Movements products={products} focus={focus} />}
      {view === "receive" && <Receive products={products} hit={hit} code={code} focus={focus} canEdit={canEdit} onIdentify={identify} onScan={() => setScanner(true)} />}
      {view === "adjustments" && <Adjustments products={products} canAdjust={canAdjust} focus={focus} />}
      {view === "low" && <AlertList title="Low stock" rows={alerts?.low_stock || []} kind="low" onReceive={(id) => go("receive", id)} />}
      {view === "expiring" && <AlertList title="Expiring within 90 days" rows={alerts?.expiring || []} kind="expiry" onReceive={(id) => go("receive", id)} />}
      {view === "expired" && <AlertList title="Expired stock still on hand" rows={alerts?.expired || []} kind="expiry" onReceive={(id) => go("receive", id)} />}
      <div className="scan-dock">
        <button className="btn primary" type="button" onClick={() => setScanner(true)}>Scan barcode</button>
      </div>
      {scanner && <BarcodeScanner onClose={() => setScanner(false)} onUse={(value) => { setScanner(false); identify(value); }} />}
      {registering && <RegisterMedicine key={code || "new"} barcode={unknown ? code : ""} onClose={() => setRegistering(false)} onRegistered={(value) => { setRegistering(false); identify(value); }} />}
    </Page>
  );
}

function KnownBarcode({ hit, code, onProduct, onBatches, onReceive, onAgain }: { hit: any; code: string; onProduct: () => void; onBatches: () => void; onReceive: () => void; onAgain: () => void }) {
  const product = hit.product || {};
  return (
    <div className="known-barcode" role="status">
      <p><strong>{product.name}</strong> {product.strength ? <span className="muted">{product.strength}</span> : null}</p>
      <p>Brand {product.brand || "—"} · Composition {product.composition || "—"} · Manufacturer {product.manufacturer || "—"}</p>
      <p>SKU {hit.sku?.name || "—"} · Pack size {hit.sku ? `${hit.sku.units_per_pack} ${product.unit || "base units"} per ${hit.sku.unit}` : "—"} · Barcode {hit.barcode?.value || code}</p>
      <div className="row-actions">
        <button className="btn" type="button" onClick={onProduct}>View Product</button>
        <button className="btn" type="button" onClick={onBatches}>View Batches</button>
        <button className="btn" type="button" onClick={onReceive}>Receive Stock</button>
        <button className="btn" type="button" onClick={onAgain}>Scan Again</button>
      </div>
    </div>
  );
}

function Dashboard({ alerts, products, onOpen }: { alerts: any; products: any[]; onOpen: (view: string) => void }) {
  const active = products.filter((item) => item.active).length;
  return (
    <div>
      <div className="stats">
        <button className="stat" type="button" onClick={() => onOpen("medicines")}><span>Medicines</span><strong>{active}</strong></button>
        <button className="stat" type="button" onClick={() => onOpen("low")}><span>Low stock</span><strong>{alerts?.low_stock?.length || 0}</strong></button>
        <button className="stat" type="button" onClick={() => onOpen("expiring")}><span>Expiring 90d</span><strong>{alerts?.expiring?.length || 0}</strong></button>
        <button className="stat" type="button" onClick={() => onOpen("expired")}><span>Expired on shelf</span><strong>{alerts?.expired?.length || 0}</strong></button>
      </div>
      <p className="muted">Ledger mismatches: {alerts?.mismatches?.length || 0}. Stock changes from receive, adjustment, dispensing, or a billing issue. A billing decrease names the bill.</p>
    </div>
  );
}

function Medicines({ products, canEdit, focus }: { products: any[]; canEdit: boolean; focus: string }) {
  const [q, setQ] = useState("");
  const [show, setShow] = useState("all");
  const [editing, setEditing] = useState<any>(null);
  const needle = q.trim().toLowerCase();
  const rows = products.filter((item) => {
    if (show === "active" && !item.active) return false;
    if (show === "inactive" && item.active) return false;
    if (focus && !needle && item.id !== focus) return false;
    if (!needle) return true;
    return `${item.name} ${item.brand} ${item.composition} ${item.id}`.toLowerCase().includes(needle);
  });
  return (
    <div>
      <div className="row-actions">
        <input aria-label="Search medicines" placeholder="Search name, brand, composition" value={q} onChange={(e) => setQ(e.target.value)} />
        <select aria-label="Medicine status" value={show} onChange={(e) => setShow(e.target.value)}>
          <option value="all">All</option>
          <option value="active">Active</option>
          <option value="inactive">Inactive</option>
        </select>
        {canEdit && <button className="btn primary" type="button" onClick={() => setEditing({})}>Add medicine</button>}
      </div>
      {!rows.length && <Empty text="No medicine matches that search." />}
      <div className="table-wrap"><table className="data">
        <thead><tr><th>Medicine</th><th>Brand</th><th>Composition</th><th>Status</th><th></th></tr></thead>
        <tbody>
          {rows.map((item) => (
            <tr key={item.id}>
              <td>{item.name} <span className="muted">{item.strength}</span></td>
              <td>{item.brand || "—"}</td>
              <td>{item.composition || "—"}</td>
              <td>{item.active ? "Active" : "Inactive"}</td>
              <td className="row-actions">
                {canEdit && <button className="btn small" type="button" onClick={() => setEditing(item)}>Edit</button>}
                {canEdit && <button className="btn small" type="button" onClick={() => {
                  const next = !item.active;
                  if (!window.confirm(next ? `Reactivate ${item.name}?` : `Deactivate ${item.name}? History and the ledger stay.`)) return;
                  run(() => api(`/api/inventory/products/${item.id}`, { method: "PATCH", body: JSON.stringify(productBody(item, { active: next })) }), next ? "Medicine reactivated" : "Medicine deactivated");
                }}>{item.active ? "Deactivate" : "Activate"}</button>}
              </td>
            </tr>
          ))}
        </tbody>
      </table></div>
      {editing && <MedicineForm product={editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

function MedicineForm({ product, onClose }: { product: any; onClose: () => void }) {
  const [form, setForm] = useState<any>({ unit: "Tablet", ...product, active: product.id ? Boolean(product.active) : true });
  const set = (key: string, value: any) => setForm({ ...form, [key]: value });
  return (
    <Modal title={product.id ? "Edit medicine" : "Add medicine"} onClose={onClose} footer={<button className="btn primary" type="button" onClick={() => run(async () => {
      const body = productBody(form);
      if (product.id) await api(`/api/inventory/products/${product.id}`, { method: "PATCH", body: JSON.stringify(body) });
      else await api("/api/inventory/products", { method: "POST", body: JSON.stringify(body) });
      onClose();
    }, product.id ? "Medicine updated" : "Medicine added. Add a package and barcode separately.")}>Save medicine</button>}>
      <p className="muted">This saves the product only. Package, barcode, and batch stay separate.</p>
      <div className="grid-form">
        <Field label="Name"><input value={form.name || ""} onChange={(e) => set("name", e.target.value)} /></Field>
        <Field label="Brand"><input value={form.brand || ""} onChange={(e) => set("brand", e.target.value)} /></Field>
        <Field label="Composition"><input value={form.composition || ""} onChange={(e) => set("composition", e.target.value)} /></Field>
        <Field label="Strength"><input value={form.strength || ""} onChange={(e) => set("strength", e.target.value)} /></Field>
        <Field label="Form"><input value={form.dosage_form || ""} onChange={(e) => set("dosage_form", e.target.value)} /></Field>
        <Field label="Manufacturer"><input value={form.manufacturer || ""} onChange={(e) => set("manufacturer", e.target.value)} /></Field>
        <Field label="Base unit"><input value={form.unit || ""} onChange={(e) => set("unit", e.target.value)} /></Field>
        <Field label="Reorder level"><input value={form.reorder_level || ""} onChange={(e) => set("reorder_level", e.target.value)} /></Field>
      </div>
    </Modal>
  );
}

function Packaging({ products, canEdit }: { products: any[]; canEdit: boolean }) {
  const [q, setQ] = useState("");
  const [productId, setProductId] = useState("");
  const [name, setName] = useState("");
  const [unit, setUnit] = useState("");
  const [size, setSize] = useState("");
  const needle = q.trim().toLowerCase();
  const rows = products.flatMap((product) => (product.skus || []).map((sku: any) => ({ ...sku, product })))
    .filter((sku) => !needle || `${sku.product.name} ${sku.name} ${sku.unit}`.toLowerCase().includes(needle));
  return (
    <div>
      <input aria-label="Search packages" placeholder="Search package or medicine" value={q} onChange={(e) => setQ(e.target.value)} />
      <div className="table-wrap"><table className="data">
        <thead><tr><th>Medicine</th><th>Package</th><th>Pack size</th><th>Status</th><th></th></tr></thead>
        <tbody>
          {rows.map((sku) => (
            <tr key={sku.id}>
              <td>{sku.product.name}</td>
              <td>{sku.name}</td>
              <td>{sku.units_per_pack} {sku.product.unit} per {sku.unit}</td>
              <td>{sku.active ? "Active" : "Inactive"}</td>
              <td>{canEdit && <button className="btn small" type="button" onClick={() => run(() => api(`/api/inventory/skus/${sku.id}`, { method: "PATCH", body: JSON.stringify({ active: !sku.active }) }), sku.active ? "Package deactivated" : "Package reactivated")}>{sku.active ? "Deactivate" : "Activate"}</button>}</td>
            </tr>
          ))}
        </tbody>
      </table></div>
      {!rows.length && <Empty text="No package is stored yet." />}
      {canEdit && (
        <div className="panel">
          <h2>Add package</h2>
          <div className="body grid-form">
            <Field label="Medicine">
              <select value={productId} onChange={(e) => setProductId(e.target.value)}>
                <option value="">Choose</option>
                {products.filter((item) => item.active).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
              </select>
            </Field>
            <Field label="Package name"><input value={name} onChange={(e) => setName(e.target.value)} /></Field>
            <Field label="Package unit"><input value={unit} onChange={(e) => setUnit(e.target.value)} /></Field>
            <Field label="Base units in this package"><input value={size} onChange={(e) => setSize(e.target.value)} placeholder="Enter the count. Do not assume 10." /></Field>
            <button className="btn primary" type="button" onClick={() => run(() => api("/api/inventory/skus", { method: "POST", body: JSON.stringify({ product_id: productId, name, unit, units_per_pack: Number(size) }) }), "Package saved")}>Save package</button>
          </div>
        </div>
      )}
    </div>
  );
}

function Barcodes({ products, canEdit }: { products: any[]; canEdit: boolean }) {
  const { data: types } = useData<{ items: any[] }>("/api/inventory/barcode-types");
  const [q, setQ] = useState("");
  const [skuId, setSkuId] = useState("");
  const [value, setValue] = useState("");
  const [barcodeType, setBarcodeType] = useState("");
  const needle = q.trim().toLowerCase();
  const skus = products.flatMap((product) => (product.skus || []).filter((sku: any) => sku.active).map((sku: any) => ({ ...sku, product })));
  const rows = products.flatMap((product) => (product.barcodes || []).map((code: any) => ({ ...code, product })))
    .filter((code) => !needle || `${code.value} ${code.product.name} ${code.sku_name}`.toLowerCase().includes(needle));
  return (
    <div>
      <input aria-label="Search barcodes" placeholder="Search barcode or medicine" value={q} onChange={(e) => setQ(e.target.value)} />
      <div className="table-wrap"><table className="data">
        <thead><tr><th>Barcode</th><th>Type</th><th>Medicine</th><th>Package</th><th>Status</th><th></th></tr></thead>
        <tbody>
          {rows.map((code) => (
            <tr key={code.id}>
              <td>{code.value}</td>
              <td>{code.barcode_type}</td>
              <td>{code.product.name}</td>
              <td>{code.sku_name} · {code.units_per_pack}</td>
              <td>{code.active ? "Active" : "Inactive"}</td>
              <td>{canEdit && <button className="btn small" type="button" onClick={() => run(() => api(`/api/inventory/barcodes/${code.id}`, { method: "PATCH", body: JSON.stringify({ active: !code.active }) }), code.active ? "Barcode deactivated" : "Barcode reactivated")}>{code.active ? "Deactivate" : "Activate"}</button>}</td>
            </tr>
          ))}
        </tbody>
      </table></div>
      {!rows.length && <Empty text="No barcode is registered." />}
      {canEdit && (
        <div className="panel">
          <h2>Register barcode</h2>
          <div className="body grid-form">
            <Field label="Package">
              <select value={skuId} onChange={(e) => setSkuId(e.target.value)}>
                <option value="">Choose a package</option>
                {skus.map((sku) => <option key={sku.id} value={sku.id}>{sku.product.name} · {sku.name}</option>)}
              </select>
            </Field>
            <Field label="Barcode"><input value={value} onChange={(e) => setValue(e.target.value)} /></Field>
            <Field label="Barcode type">
              <select value={barcodeType} onChange={(e) => setBarcodeType(e.target.value)}>
                <option value="">{(types?.items || []).length ? "Choose a configured type" : "No barcode types configured"}</option>
                {(types?.items || []).map((item) => <option key={item.code} value={item.code}>{item.name}</option>)}
              </select>
            </Field>
            <button className="btn primary" type="button" onClick={() => run(() => api("/api/inventory/barcodes", { method: "POST", body: JSON.stringify({ sku_id: skuId, value, barcode_type: barcodeType, scope: "SKU" }) }), "Barcode registered")}>Save barcode</button>
          </div>
        </div>
      )}
    </div>
  );
}

function Batches({ products, focus, onReceive }: { products: any[]; focus: string; onReceive: (id: string) => void }) {
  const [q, setQ] = useState(focus);
  const needle = q.trim().toLowerCase();
  const rows = products.flatMap((product) => (product.batches || []).map((batch: any) => ({ ...batch, product })))
    .filter((batch) => !needle || `${batch.product.name} ${batch.product.id} ${batch.batch_no}`.toLowerCase().includes(needle));
  return (
    <div>
      <input aria-label="Search batches" placeholder="Search medicine or batch" value={q} onChange={(e) => setQ(e.target.value)} />
      {!rows.length && <Empty text="No batch is stored. Receive stock to create one." />}
      <div className="table-wrap"><table className="data">
        <thead><tr><th>Medicine</th><th>Batch</th><th>Expiry</th><th className="num">On hand</th><th>Status</th><th></th></tr></thead>
        <tbody>
          {rows.map((batch) => (
            <tr key={batch.id}>
              <td>{batch.product.name}</td>
              <td>{batch.batch_no}</td>
              <td>{batch.expiry_date || "—"}</td>
              <td className="num">{batch.qty_on_hand} {batch.unit}</td>
              <td><Status value={batchStatus(batch.product, batch)} /></td>
              <td><button className="btn small" type="button" onClick={() => onReceive(batch.product.id)}>Receive</button></td>
            </tr>
          ))}
        </tbody>
      </table></div>
    </div>
  );
}

function stockRows(products: any[]) {
  return products.flatMap((product) => {
    const sku = (product.skus || []).find((item: any) => item.active) || product.skus?.[0];
    const barcode = (product.barcodes || []).filter((item: any) => item.active).map((item: any) => item.value).join(", ");
    const batches = product.batches?.length ? product.batches : [null];
    return batches.map((batch: any) => ({ product, sku, barcode, batch, key: batch?.id || product.id }));
  });
}

function Stock({ products, onOpen }: { products: any[]; onOpen: (view: string, productId?: string) => void }) {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("all");
  const needle = q.trim().toLowerCase();
  const rows = stockRows(products).filter((row) => {
    const label = batchStatus(row.product, row.batch);
    if (status !== "all" && label !== status) return false;
    if (!needle) return true;
    return `${row.product.name} ${row.product.brand} ${row.product.composition} ${row.sku?.name || ""} ${row.barcode} ${row.batch?.batch_no || ""}`.toLowerCase().includes(needle);
  });
  return (
    <div>
      <div className="row-actions">
        <input aria-label="Search stock" placeholder="Search medicine, brand, composition, barcode, batch" value={q} onChange={(e) => setQ(e.target.value)} />
        <select aria-label="Stock status" value={status} onChange={(e) => setStatus(e.target.value)}>
          {["all", "In stock", "Low", "Expiring", "Expired", "Inactive", "No batch"].map((item) => <option key={item} value={item}>{item === "all" ? "All statuses" : item}</option>)}
        </select>
      </div>
      {!rows.length && <Empty text="No stock matches that filter." />}
      <div className="table-wrap"><table className="data">
        <thead><tr><th>Medicine</th><th>Brand</th><th>Composition</th><th>SKU</th><th>Barcode</th><th>Batch</th><th>Expiry</th><th className="num">Qty</th><th>Unit</th><th className="num">Purchase</th><th className="num">Sale</th><th>Status</th><th></th></tr></thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key}>
              <td>{row.product.name}</td>
              <td>{row.product.brand || "—"}</td>
              <td>{row.product.composition || "—"}</td>
              <td>{row.sku ? `${row.sku.name} · ${row.sku.units_per_pack}` : "—"}</td>
              <td>{row.barcode || "—"}</td>
              <td>{row.batch?.batch_no || "—"}</td>
              <td>{row.batch?.expiry_date || "—"}</td>
              <td className="num">{row.batch ? row.batch.qty_on_hand : row.product.stock}</td>
              <td>{row.batch?.unit || row.product.unit}</td>
              <td className="num">{money(row.batch?.purchase_rate_paise ?? row.product.purchase_rate_paise)}</td>
              <td className="num">{money(row.batch?.sale_rate_paise ?? row.product.sale_rate_paise)}</td>
              <td><Status value={batchStatus(row.product, row.batch)} /></td>
              <td className="row-actions">
                <button className="btn small" type="button" onClick={() => onOpen("medicines", row.product.id)}>View</button>
                <button className="btn small" type="button" onClick={() => onOpen("receive", row.product.id)}>Receive</button>
                <button className="btn small" type="button" onClick={() => onOpen("adjustments", row.product.id)}>Adjust</button>
                <button className="btn small" type="button" onClick={() => onOpen("movements", row.product.id)}>View movements</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table></div>
    </div>
  );
}

function Movements({ products, focus }: { products: any[]; focus: string }) {
  const [productId, setProductId] = useState(focus);
  const { data, error, loading } = useData<any>(`/api/inventory/ledger${productId ? `?product_id=${encodeURIComponent(productId)}` : ""}`);
  return (
    <div>
      <Field label="Medicine">
        <select aria-label="Movement medicine" value={productId} onChange={(e) => setProductId(e.target.value)}>
          <option value="">All recent movements</option>
          {products.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
      </Field>
      {loading && !data && <Loading label="Opening the ledger…" />}
      {error && <ErrorState message={error} />}
      {!loading && data && !data.items?.length && <Empty text="No stock movement is recorded for that filter." />}
      <div className="table-wrap"><table className="data">
        <thead><tr><th>When</th><th>Medicine</th><th>Batch</th><th>Type</th><th className="num">Qty</th><th>Reason</th><th>Who</th></tr></thead>
        <tbody>
          {(data?.items || []).map((item: any) => (
            <tr key={item.id}>
              <td>{item.at}</td>
              <td>{item.product_name}</td>
              <td>{item.batch_no}</td>
              <td>{item.movement_type}</td>
              <td className="num">{item.qty}</td>
              <td>{item.explained_by || item.reason || "—"}</td>
              <td>{item.user_name || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table></div>
    </div>
  );
}

function Receive({ products, hit, code, focus, canEdit, onIdentify, onScan }: { products: any[]; hit: any; code: string; focus: string; canEdit: boolean; onIdentify: (value?: string) => void; onScan: () => void }) {
  const [picked, setPicked] = useState<string | null>(null);
  const chosen = picked ?? hit?.product?.id ?? focus;
  const product = products.find((item) => item.id === chosen) || (hit?.product?.id === chosen ? hit.product : null);
  const batches = (products.find((item) => item.id === chosen)?.batches || []).filter((item: any) => item.active !== 0);
  const [batchId, setBatchId] = useState("");
  const [batchNo, setBatchNo] = useState("");
  const [mfg, setMfg] = useState("");
  const [expiry, setExpiry] = useState("");
  const [qty, setQty] = useState("");
  const [purchase, setPurchase] = useState("");
  const [sale, setSale] = useState("");
  if (!canEdit) return <p className="muted">You can look up stock, but not receive it.</p>;
  return (
    <div className="panel">
      <h2>Receive stock</h2>
      <div className="body grid-form">
        <p className="muted span-2">Identify the package, choose or create a batch, enter the quantity, then confirm. The scan itself does not receive stock or create a batch.</p>
        <Field label="Package barcode">
          <input aria-label="Receive barcode" defaultValue={code} key={code} onBlur={(e) => { if (e.target.value.trim()) onIdentify(e.target.value); }} />
        </Field>
        <div className="row-actions"><button className="btn" type="button" onClick={onScan}>Scan barcode</button></div>
        <Field label="Medicine">
          <select aria-label="Receive medicine" value={chosen} onChange={(e) => { setPicked(e.target.value); setBatchId(""); }}>
            <option value="">Choose a registered medicine</option>
            {products.filter((item) => item.active).map((item) => <option key={item.id} value={item.id}>{item.name} {item.strength}</option>)}
          </select>
        </Field>
        <Field label="Existing batch">
          <select aria-label="Existing batch" value={batchId} onChange={(e) => setBatchId(e.target.value)}>
            <option value="">Create a new batch</option>
            {batches.map((item: any) => <option key={item.id} value={item.id}>{item.batch_no} · exp {item.expiry_date || "—"} · {item.qty_on_hand}</option>)}
          </select>
        </Field>
        {!batchId && (
          <>
            <Field label="New batch number"><input aria-label="New batch number" value={batchNo} onChange={(e) => setBatchNo(e.target.value)} /></Field>
            <Field label="Manufactured"><input aria-label="Manufactured date" value={mfg} onChange={(e) => setMfg(e.target.value)} placeholder="YYYY-MM-DD" /></Field>
            <Field label="Expiry"><input aria-label="Expiry date" value={expiry} onChange={(e) => setExpiry(e.target.value)} placeholder="YYYY-MM-DD" /></Field>
            <Field label="Purchase price Rs"><input value={purchase} onChange={(e) => setPurchase(e.target.value)} /></Field>
            <Field label="Sale price Rs"><input value={sale} onChange={(e) => setSale(e.target.value)} /></Field>
          </>
        )}
        <Field label={`Quantity in ${product?.unit || "base units"}`}><input aria-label="Receive quantity" value={qty} onChange={(e) => setQty(e.target.value)} /></Field>
        <button className="btn primary" type="button" disabled={!chosen || !(Number(qty) > 0)} onClick={() => {
          if (!window.confirm(`Receive ${qty} ${product?.unit || "units"} of ${product?.name || "this medicine"}?`)) return;
          const body: any = { product_id: chosen, qty: Number(qty) };
          if (hit?.product?.id === chosen && code) body.barcode = code;
          if (batchId) body.batch_id = batchId;
          else Object.assign(body, { batch_no: batchNo, mfg_date: mfg, expiry_date: expiry, purchase_rate_paise: paise(purchase), sale_rate_paise: paise(sale) });
          run(() => api("/api/inventory/receive", { method: "POST", body: JSON.stringify(body) }), "Stock received and written to the ledger");
        }}>Confirm receive</button>
      </div>
    </div>
  );
}

function Adjustments({ products, canAdjust, focus }: { products: any[]; canAdjust: boolean; focus: string }) {
  const [productId, setProductId] = useState(focus);
  const [batchId, setBatchId] = useState("");
  const [type, setType] = useState("ADJUSTMENT");
  const [qty, setQty] = useState("");
  const [reason, setReason] = useState("");
  const batches = products.find((item) => item.id === productId)?.batches || [];
  if (!canAdjust) return <p className="muted">Adjustments need the inventory adjustment permission.</p>;
  return (
    <div className="panel">
      <h2>Adjustment</h2>
      <div className="body grid-form">
        <Field label="Medicine">
          <select aria-label="Adjustment medicine" value={productId} onChange={(e) => { setProductId(e.target.value); setBatchId(""); }}>
            <option value="">Choose</option>
            {products.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
        </Field>
        <Field label="Batch">
          <select aria-label="Adjustment batch" value={batchId} onChange={(e) => setBatchId(e.target.value)}>
            <option value="">Choose</option>
            {batches.map((item: any) => <option key={item.id} value={item.id}>{item.batch_no} · {item.qty_on_hand}</option>)}
          </select>
        </Field>
        <Field label="Movement">
          <select aria-label="Movement type" value={type} onChange={(e) => setType(e.target.value)}>
            {["ADJUSTMENT", "DAMAGED", "EXPIRED", "LOST", "RETURN"].map((item) => <option key={item}>{item}</option>)}
          </select>
        </Field>
        <Field label="Quantity"><input aria-label="Adjustment quantity" value={qty} onChange={(e) => setQty(e.target.value)} /></Field>
        <Field label="Reason" className="span-2"><input aria-label="Adjustment reason" value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
        <button className="btn primary" type="button" onClick={() => {
          if (!window.confirm("Post this stock movement?")) return;
          run(() => api("/api/inventory/movements", { method: "POST", body: JSON.stringify({ batch_id: batchId, qty: Number(qty), movement_type: type, reason }) }), "Stock movement recorded");
        }}>Confirm adjustment</button>
      </div>
    </div>
  );
}

function AlertList({ title, rows, kind, onReceive }: { title: string; rows: any[]; kind: "low" | "expiry"; onReceive: (id: string) => void }) {
  return (
    <div>
      <h2 className="section-label">{title}</h2>
      {!rows.length && <Empty text="Nothing is on this list." />}
      <div className="table-wrap"><table className="data">
        <thead><tr><th>Medicine</th>{kind === "expiry" && <th>Batch</th>}{kind === "expiry" && <th>Expiry</th>}<th className="num">On hand</th><th></th></tr></thead>
        <tbody>
          {rows.map((item) => (
            <tr key={item.id}>
              <td>{item.name || item.product_name}</td>
              {kind === "expiry" && <td>{item.batch_no}</td>}
              {kind === "expiry" && <td>{item.expiry_date}</td>}
              <td className="num">{item.stock ?? item.qty_on_hand} {item.unit || ""}</td>
              <td><button className="btn small" type="button" onClick={() => onReceive(item.product_id || item.id)}>Receive</button></td>
            </tr>
          ))}
        </tbody>
      </table></div>
    </div>
  );
}
