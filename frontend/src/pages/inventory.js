import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ApiError, api, money, paise } from "../api";
import { prepareBarcode } from "../barcode";
import { BarcodeScanner, PhonePair } from "../scanner";
import { useApp } from "../store";
import { Empty, ErrorState, Field, Loading, Modal, Page, Status, run, useData } from "../ui";
import { RegisterMedicine } from "./clinical";
const VIEWS = [
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
function plusDays(days) {
    const d = new Date();
    d.setDate(d.getDate() + days);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function batchStatus(product, batch) {
    if (product && !product.active)
        return "Inactive";
    if (!batch)
        return "No batch";
    const today = localToday();
    if (batch.expiry_date && batch.expiry_date < today)
        return "Expired";
    if (batch.expiry_date && batch.expiry_date <= plusDays(90))
        return "Expiring";
    if (Number(product?.stock) <= Number(product?.reorder_level || 0))
        return "Low";
    return "In stock";
}
function productBody(product, patch = {}) {
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
    const { data, error, loading } = useData("/api/inventory/products?all=1");
    const { data: alerts } = useData("/api/inventory/alerts");
    const products = data?.items || [];
    const [code, setCode] = useState("");
    const [hit, setHit] = useState(null);
    const [unknown, setUnknown] = useState(false);
    const [scanError, setScanError] = useState("");
    const [scanner, setScanner] = useState(false);
    const [registering, setRegistering] = useState(false);
    const manualRef = useRef(null);
    async function identify(value = code) {
        const prepared = prepareBarcode(value);
        setCode(prepared.code);
        setHit(null);
        setUnknown(false);
        setScanError("");
        if (!prepared.code)
            return;
        if (prepared.error) {
            setScanError(prepared.error);
            return;
        }
        try {
            setHit(await api("/api/inventory/barcodes/resolve", { method: "POST", body: JSON.stringify({ code: prepared.code }) }));
        }
        catch (err) {
            if (err instanceof ApiError && err.status === 404) {
                setUnknown(true);
                setScanError("Barcode not registered");
                return;
            }
            setScanError(err instanceof Error ? err.message : "The barcode could not be checked.");
        }
    }
    function go(next, productId = "") {
        navigate(productId ? `/inventory/${next}?product=${encodeURIComponent(productId)}` : `/inventory/${next}`);
    }
    return (_jsxs(Page, { title: "Inventory", note: "Medicines, batches, and hospital stock. A scan only identifies a barcode and does not change stock.", actions: _jsx("button", { className: "btn primary scan-launch", type: "button", onClick: () => setScanner(true), children: "Scan barcode" }), children: [_jsx("nav", { className: "inv-nav", "aria-label": "Inventory", children: VIEWS.map(([id, label]) => (_jsx(Link, { className: view === id ? "on" : "", to: `/inventory/${id}`, children: label }, id))) }), _jsx("form", { className: "panel lookup-sheet", onSubmit: (e) => { e.preventDefault(); identify(); }, children: _jsxs("div", { className: "body", children: [_jsxs("div", { className: "grid-form", children: [_jsx(Field, { label: "Barcode", children: _jsx("input", { ref: manualRef, "aria-label": "Barcode", value: code, placeholder: "Scan or type the barcode. This does not change stock.", onChange: (e) => { setCode(e.target.value); setHit(null); setUnknown(false); setScanError(""); } }) }), _jsxs("div", { className: "row-actions", children: [_jsx("button", { className: "btn", type: "submit", children: "Look up" }), _jsx("button", { className: "btn", type: "button", onClick: () => setScanner(true), children: "Scan with webcam" }), _jsx(PhonePair, { onUse: (value) => identify(value) })] })] }), scanError && _jsxs("div", { className: "warn", role: "status", children: [scanError, unknown ? ". No medicine was created." : ""] }), unknown && (_jsxs("div", { className: "row-actions", children: [canEdit && _jsx("button", { className: "btn primary", type: "button", onClick: () => setRegistering(true), children: "Register New Medicine" }), _jsx("button", { className: "btn", type: "button", onClick: () => setScanner(true), children: "Scan Again" }), _jsx("button", { className: "btn", type: "button", onClick: () => { setUnknown(false); manualRef.current?.focus(); }, children: "Enter Manually" })] })), hit && _jsx(KnownBarcode, { hit: hit, code: code, onProduct: () => go("medicines", hit.product.id), onBatches: () => go("batches", hit.product.id), onReceive: () => go("receive", hit.product.id), onAgain: () => setScanner(true) })] }) }), loading && !data && _jsx(Loading, { label: "Opening inventory\u2026" }), error && _jsx(ErrorState, { message: error }), view === "home" && _jsx(Dashboard, { alerts: alerts, products: products, onOpen: go }), view === "medicines" && _jsx(Medicines, { products: products, canEdit: canEdit, focus: focus }), view === "packaging" && _jsx(Packaging, { products: products, canEdit: canEdit }), view === "barcodes" && _jsx(Barcodes, { products: products, canEdit: canEdit }), view === "batches" && _jsx(Batches, { products: products, focus: focus, onReceive: (id) => go("receive", id) }), view === "stock" && _jsx(Stock, { products: products, onOpen: go }), view === "movements" && _jsx(Movements, { products: products, focus: focus }), view === "receive" && _jsx(Receive, { products: products, hit: hit, code: code, focus: focus, canEdit: canEdit, onIdentify: identify, onScan: () => setScanner(true) }), view === "adjustments" && _jsx(Adjustments, { products: products, canAdjust: canAdjust, focus: focus }), view === "low" && _jsx(AlertList, { title: "Low stock", rows: alerts?.low_stock || [], kind: "low", onReceive: (id) => go("receive", id) }), view === "expiring" && _jsx(AlertList, { title: "Expiring within 90 days", rows: alerts?.expiring || [], kind: "expiry", onReceive: (id) => go("receive", id) }), view === "expired" && _jsx(AlertList, { title: "Expired stock still on hand", rows: alerts?.expired || [], kind: "expiry", onReceive: (id) => go("receive", id) }), _jsx("div", { className: "scan-dock", children: _jsx("button", { className: "btn primary", type: "button", onClick: () => setScanner(true), children: "Scan barcode" }) }), scanner && _jsx(BarcodeScanner, { onClose: () => setScanner(false), onUse: (value) => { setScanner(false); identify(value); } }), registering && _jsx(RegisterMedicine, { barcode: unknown ? code : "", onClose: () => setRegistering(false), onRegistered: (value) => { setRegistering(false); identify(value); } }, code || "new")] }));
}
function KnownBarcode({ hit, code, onProduct, onBatches, onReceive, onAgain }) {
    const product = hit.product || {};
    return (_jsxs("div", { className: "known-barcode", role: "status", children: [_jsxs("p", { children: [_jsx("strong", { children: product.name }), " ", product.strength ? _jsx("span", { className: "muted", children: product.strength }) : null] }), _jsxs("p", { children: ["Brand ", product.brand || "—", " \u00B7 Composition ", product.composition || "—", " \u00B7 Manufacturer ", product.manufacturer || "—"] }), _jsxs("p", { children: ["SKU ", hit.sku?.name || "—", " \u00B7 Pack size ", hit.sku ? `${hit.sku.units_per_pack} ${product.unit || "base units"} per ${hit.sku.unit}` : "—", " \u00B7 Barcode ", hit.barcode?.value || code] }), _jsxs("div", { className: "row-actions", children: [_jsx("button", { className: "btn", type: "button", onClick: onProduct, children: "View Product" }), _jsx("button", { className: "btn", type: "button", onClick: onBatches, children: "View Batches" }), _jsx("button", { className: "btn", type: "button", onClick: onReceive, children: "Receive Stock" }), _jsx("button", { className: "btn", type: "button", onClick: onAgain, children: "Scan Again" })] })] }));
}
function Dashboard({ alerts, products, onOpen }) {
    const active = products.filter((item) => item.active).length;
    return (_jsxs("div", { children: [_jsxs("div", { className: "stats", children: [_jsxs("button", { className: "stat", type: "button", onClick: () => onOpen("medicines"), children: [_jsx("span", { children: "Medicines" }), _jsx("strong", { children: active })] }), _jsxs("button", { className: "stat", type: "button", onClick: () => onOpen("low"), children: [_jsx("span", { children: "Low stock" }), _jsx("strong", { children: alerts?.low_stock?.length || 0 })] }), _jsxs("button", { className: "stat", type: "button", onClick: () => onOpen("expiring"), children: [_jsx("span", { children: "Expiring 90d" }), _jsx("strong", { children: alerts?.expiring?.length || 0 })] }), _jsxs("button", { className: "stat", type: "button", onClick: () => onOpen("expired"), children: [_jsx("span", { children: "Expired on shelf" }), _jsx("strong", { children: alerts?.expired?.length || 0 })] })] }), _jsxs("p", { className: "muted", children: ["Ledger mismatches: ", alerts?.mismatches?.length || 0, ". Stock changes from receive, adjustment, dispensing, or a billing issue. A billing decrease names the bill."] })] }));
}
function Medicines({ products, canEdit, focus }) {
    const [q, setQ] = useState("");
    const [show, setShow] = useState("all");
    const [editing, setEditing] = useState(null);
    const needle = q.trim().toLowerCase();
    const rows = products.filter((item) => {
        if (show === "active" && !item.active)
            return false;
        if (show === "inactive" && item.active)
            return false;
        if (focus && !needle && item.id !== focus)
            return false;
        if (!needle)
            return true;
        return `${item.name} ${item.brand} ${item.composition} ${item.id}`.toLowerCase().includes(needle);
    });
    return (_jsxs("div", { children: [_jsxs("div", { className: "row-actions", children: [_jsx("input", { "aria-label": "Search medicines", placeholder: "Search name, brand, composition", value: q, onChange: (e) => setQ(e.target.value) }), _jsxs("select", { "aria-label": "Medicine status", value: show, onChange: (e) => setShow(e.target.value), children: [_jsx("option", { value: "all", children: "All" }), _jsx("option", { value: "active", children: "Active" }), _jsx("option", { value: "inactive", children: "Inactive" })] }), canEdit && _jsx("button", { className: "btn primary", type: "button", onClick: () => setEditing({}), children: "Add medicine" })] }), !rows.length && _jsx(Empty, { text: "No medicine matches that search." }), _jsx("div", { className: "table-wrap", children: _jsxs("table", { className: "data", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "Medicine" }), _jsx("th", { children: "Brand" }), _jsx("th", { children: "Composition" }), _jsx("th", { children: "Status" }), _jsx("th", {})] }) }), _jsx("tbody", { children: rows.map((item) => (_jsxs("tr", { children: [_jsxs("td", { children: [item.name, " ", _jsx("span", { className: "muted", children: item.strength })] }), _jsx("td", { children: item.brand || "—" }), _jsx("td", { children: item.composition || "—" }), _jsx("td", { children: item.active ? "Active" : "Inactive" }), _jsxs("td", { className: "row-actions", children: [canEdit && _jsx("button", { className: "btn small", type: "button", onClick: () => setEditing(item), children: "Edit" }), canEdit && _jsx("button", { className: "btn small", type: "button", onClick: () => {
                                                    const next = !item.active;
                                                    if (!window.confirm(next ? `Reactivate ${item.name}?` : `Deactivate ${item.name}? History and the ledger stay.`))
                                                        return;
                                                    run(() => api(`/api/inventory/products/${item.id}`, { method: "PATCH", body: JSON.stringify(productBody(item, { active: next })) }), next ? "Medicine reactivated" : "Medicine deactivated");
                                                }, children: item.active ? "Deactivate" : "Activate" })] })] }, item.id))) })] }) }), editing && _jsx(MedicineForm, { product: editing, onClose: () => setEditing(null) })] }));
}
function MedicineForm({ product, onClose }) {
    const [form, setForm] = useState({ unit: "Tablet", ...product, active: product.id ? Boolean(product.active) : true });
    const set = (key, value) => setForm({ ...form, [key]: value });
    return (_jsxs(Modal, { title: product.id ? "Edit medicine" : "Add medicine", onClose: onClose, footer: _jsx("button", { className: "btn primary", type: "button", onClick: () => run(async () => {
                const body = productBody(form);
                if (product.id)
                    await api(`/api/inventory/products/${product.id}`, { method: "PATCH", body: JSON.stringify(body) });
                else
                    await api("/api/inventory/products", { method: "POST", body: JSON.stringify(body) });
                onClose();
            }, product.id ? "Medicine updated" : "Medicine added. Add a package and barcode separately."), children: "Save medicine" }), children: [_jsx("p", { className: "muted", children: "This saves the product only. Package, barcode, and batch stay separate." }), _jsxs("div", { className: "grid-form", children: [_jsx(Field, { label: "Name", children: _jsx("input", { value: form.name || "", onChange: (e) => set("name", e.target.value) }) }), _jsx(Field, { label: "Brand", children: _jsx("input", { value: form.brand || "", onChange: (e) => set("brand", e.target.value) }) }), _jsx(Field, { label: "Composition", children: _jsx("input", { value: form.composition || "", onChange: (e) => set("composition", e.target.value) }) }), _jsx(Field, { label: "Strength", children: _jsx("input", { value: form.strength || "", onChange: (e) => set("strength", e.target.value) }) }), _jsx(Field, { label: "Form", children: _jsx("input", { value: form.dosage_form || "", onChange: (e) => set("dosage_form", e.target.value) }) }), _jsx(Field, { label: "Manufacturer", children: _jsx("input", { value: form.manufacturer || "", onChange: (e) => set("manufacturer", e.target.value) }) }), _jsx(Field, { label: "Base unit", children: _jsx("input", { value: form.unit || "", onChange: (e) => set("unit", e.target.value) }) }), _jsx(Field, { label: "Reorder level", children: _jsx("input", { value: form.reorder_level || "", onChange: (e) => set("reorder_level", e.target.value) }) })] })] }));
}
function Packaging({ products, canEdit }) {
    const [q, setQ] = useState("");
    const [productId, setProductId] = useState("");
    const [name, setName] = useState("");
    const [unit, setUnit] = useState("");
    const [size, setSize] = useState("");
    const needle = q.trim().toLowerCase();
    const rows = products.flatMap((product) => (product.skus || []).map((sku) => ({ ...sku, product })))
        .filter((sku) => !needle || `${sku.product.name} ${sku.name} ${sku.unit}`.toLowerCase().includes(needle));
    return (_jsxs("div", { children: [_jsx("input", { "aria-label": "Search packages", placeholder: "Search package or medicine", value: q, onChange: (e) => setQ(e.target.value) }), _jsx("div", { className: "table-wrap", children: _jsxs("table", { className: "data", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "Medicine" }), _jsx("th", { children: "Package" }), _jsx("th", { children: "Pack size" }), _jsx("th", { children: "Status" }), _jsx("th", {})] }) }), _jsx("tbody", { children: rows.map((sku) => (_jsxs("tr", { children: [_jsx("td", { children: sku.product.name }), _jsx("td", { children: sku.name }), _jsxs("td", { children: [sku.units_per_pack, " ", sku.product.unit, " per ", sku.unit] }), _jsx("td", { children: sku.active ? "Active" : "Inactive" }), _jsx("td", { children: canEdit && _jsx("button", { className: "btn small", type: "button", onClick: () => run(() => api(`/api/inventory/skus/${sku.id}`, { method: "PATCH", body: JSON.stringify({ active: !sku.active }) }), sku.active ? "Package deactivated" : "Package reactivated"), children: sku.active ? "Deactivate" : "Activate" }) })] }, sku.id))) })] }) }), !rows.length && _jsx(Empty, { text: "No package is stored yet." }), canEdit && (_jsxs("div", { className: "panel", children: [_jsx("h2", { children: "Add package" }), _jsxs("div", { className: "body grid-form", children: [_jsx(Field, { label: "Medicine", children: _jsxs("select", { value: productId, onChange: (e) => setProductId(e.target.value), children: [_jsx("option", { value: "", children: "Choose" }), products.filter((item) => item.active).map((item) => _jsx("option", { value: item.id, children: item.name }, item.id))] }) }), _jsx(Field, { label: "Package name", children: _jsx("input", { value: name, onChange: (e) => setName(e.target.value) }) }), _jsx(Field, { label: "Package unit", children: _jsx("input", { value: unit, onChange: (e) => setUnit(e.target.value) }) }), _jsx(Field, { label: "Base units in this package", children: _jsx("input", { value: size, onChange: (e) => setSize(e.target.value), placeholder: "Enter the count. Do not assume 10." }) }), _jsx("button", { className: "btn primary", type: "button", onClick: () => run(() => api("/api/inventory/skus", { method: "POST", body: JSON.stringify({ product_id: productId, name, unit, units_per_pack: Number(size) }) }), "Package saved"), children: "Save package" })] })] }))] }));
}
function Barcodes({ products, canEdit }) {
    const { data: types } = useData("/api/inventory/barcode-types");
    const [q, setQ] = useState("");
    const [skuId, setSkuId] = useState("");
    const [value, setValue] = useState("");
    const [barcodeType, setBarcodeType] = useState("");
    const needle = q.trim().toLowerCase();
    const skus = products.flatMap((product) => (product.skus || []).filter((sku) => sku.active).map((sku) => ({ ...sku, product })));
    const rows = products.flatMap((product) => (product.barcodes || []).map((code) => ({ ...code, product })))
        .filter((code) => !needle || `${code.value} ${code.product.name} ${code.sku_name}`.toLowerCase().includes(needle));
    return (_jsxs("div", { children: [_jsx("input", { "aria-label": "Search barcodes", placeholder: "Search barcode or medicine", value: q, onChange: (e) => setQ(e.target.value) }), _jsx("div", { className: "table-wrap", children: _jsxs("table", { className: "data", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "Barcode" }), _jsx("th", { children: "Type" }), _jsx("th", { children: "Medicine" }), _jsx("th", { children: "Package" }), _jsx("th", { children: "Status" }), _jsx("th", {})] }) }), _jsx("tbody", { children: rows.map((code) => (_jsxs("tr", { children: [_jsx("td", { children: code.value }), _jsx("td", { children: code.barcode_type }), _jsx("td", { children: code.product.name }), _jsxs("td", { children: [code.sku_name, " \u00B7 ", code.units_per_pack] }), _jsx("td", { children: code.active ? "Active" : "Inactive" }), _jsx("td", { children: canEdit && _jsx("button", { className: "btn small", type: "button", onClick: () => run(() => api(`/api/inventory/barcodes/${code.id}`, { method: "PATCH", body: JSON.stringify({ active: !code.active }) }), code.active ? "Barcode deactivated" : "Barcode reactivated"), children: code.active ? "Deactivate" : "Activate" }) })] }, code.id))) })] }) }), !rows.length && _jsx(Empty, { text: "No barcode is registered." }), canEdit && (_jsxs("div", { className: "panel", children: [_jsx("h2", { children: "Register barcode" }), _jsxs("div", { className: "body grid-form", children: [_jsx(Field, { label: "Package", children: _jsxs("select", { value: skuId, onChange: (e) => setSkuId(e.target.value), children: [_jsx("option", { value: "", children: "Choose a package" }), skus.map((sku) => _jsxs("option", { value: sku.id, children: [sku.product.name, " \u00B7 ", sku.name] }, sku.id))] }) }), _jsx(Field, { label: "Barcode", children: _jsx("input", { value: value, onChange: (e) => setValue(e.target.value) }) }), _jsx(Field, { label: "Barcode type", children: _jsxs("select", { value: barcodeType, onChange: (e) => setBarcodeType(e.target.value), children: [_jsx("option", { value: "", children: (types?.items || []).length ? "Choose a configured type" : "No barcode types configured" }), (types?.items || []).map((item) => _jsx("option", { value: item.code, children: item.name }, item.code))] }) }), _jsx("button", { className: "btn primary", type: "button", onClick: () => run(() => api("/api/inventory/barcodes", { method: "POST", body: JSON.stringify({ sku_id: skuId, value, barcode_type: barcodeType, scope: "SKU" }) }), "Barcode registered"), children: "Save barcode" })] })] }))] }));
}
function Batches({ products, focus, onReceive }) {
    const [q, setQ] = useState(focus);
    const needle = q.trim().toLowerCase();
    const rows = products.flatMap((product) => (product.batches || []).map((batch) => ({ ...batch, product })))
        .filter((batch) => !needle || `${batch.product.name} ${batch.product.id} ${batch.batch_no}`.toLowerCase().includes(needle));
    return (_jsxs("div", { children: [_jsx("input", { "aria-label": "Search batches", placeholder: "Search medicine or batch", value: q, onChange: (e) => setQ(e.target.value) }), !rows.length && _jsx(Empty, { text: "No batch is stored. Receive stock to create one." }), _jsx("div", { className: "table-wrap", children: _jsxs("table", { className: "data", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "Medicine" }), _jsx("th", { children: "Batch" }), _jsx("th", { children: "Expiry" }), _jsx("th", { className: "num", children: "On hand" }), _jsx("th", { children: "Status" }), _jsx("th", {})] }) }), _jsx("tbody", { children: rows.map((batch) => (_jsxs("tr", { children: [_jsx("td", { children: batch.product.name }), _jsx("td", { children: batch.batch_no }), _jsx("td", { children: batch.expiry_date || "—" }), _jsxs("td", { className: "num", children: [batch.qty_on_hand, " ", batch.unit] }), _jsx("td", { children: _jsx(Status, { value: batchStatus(batch.product, batch) }) }), _jsx("td", { children: _jsx("button", { className: "btn small", type: "button", onClick: () => onReceive(batch.product.id), children: "Receive" }) })] }, batch.id))) })] }) })] }));
}
function stockRows(products) {
    return products.flatMap((product) => {
        const sku = (product.skus || []).find((item) => item.active) || product.skus?.[0];
        const barcode = (product.barcodes || []).filter((item) => item.active).map((item) => item.value).join(", ");
        const batches = product.batches?.length ? product.batches : [null];
        return batches.map((batch) => ({ product, sku, barcode, batch, key: batch?.id || product.id }));
    });
}
function Stock({ products, onOpen }) {
    const [q, setQ] = useState("");
    const [status, setStatus] = useState("all");
    const needle = q.trim().toLowerCase();
    const rows = stockRows(products).filter((row) => {
        const label = batchStatus(row.product, row.batch);
        if (status !== "all" && label !== status)
            return false;
        if (!needle)
            return true;
        return `${row.product.name} ${row.product.brand} ${row.product.composition} ${row.sku?.name || ""} ${row.barcode} ${row.batch?.batch_no || ""}`.toLowerCase().includes(needle);
    });
    return (_jsxs("div", { children: [_jsxs("div", { className: "row-actions", children: [_jsx("input", { "aria-label": "Search stock", placeholder: "Search medicine, brand, composition, barcode, batch", value: q, onChange: (e) => setQ(e.target.value) }), _jsx("select", { "aria-label": "Stock status", value: status, onChange: (e) => setStatus(e.target.value), children: ["all", "In stock", "Low", "Expiring", "Expired", "Inactive", "No batch"].map((item) => _jsx("option", { value: item, children: item === "all" ? "All statuses" : item }, item)) })] }), !rows.length && _jsx(Empty, { text: "No stock matches that filter." }), _jsx("div", { className: "table-wrap", children: _jsxs("table", { className: "data", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "Medicine" }), _jsx("th", { children: "Brand" }), _jsx("th", { children: "Composition" }), _jsx("th", { children: "SKU" }), _jsx("th", { children: "Barcode" }), _jsx("th", { children: "Batch" }), _jsx("th", { children: "Expiry" }), _jsx("th", { className: "num", children: "Qty" }), _jsx("th", { children: "Unit" }), _jsx("th", { className: "num", children: "Purchase" }), _jsx("th", { className: "num", children: "Sale" }), _jsx("th", { children: "Status" }), _jsx("th", {})] }) }), _jsx("tbody", { children: rows.map((row) => (_jsxs("tr", { children: [_jsx("td", { children: row.product.name }), _jsx("td", { children: row.product.brand || "—" }), _jsx("td", { children: row.product.composition || "—" }), _jsx("td", { children: row.sku ? `${row.sku.name} · ${row.sku.units_per_pack}` : "—" }), _jsx("td", { children: row.barcode || "—" }), _jsx("td", { children: row.batch?.batch_no || "—" }), _jsx("td", { children: row.batch?.expiry_date || "—" }), _jsx("td", { className: "num", children: row.batch ? row.batch.qty_on_hand : row.product.stock }), _jsx("td", { children: row.batch?.unit || row.product.unit }), _jsx("td", { className: "num", children: money(row.batch?.purchase_rate_paise ?? row.product.purchase_rate_paise) }), _jsx("td", { className: "num", children: money(row.batch?.sale_rate_paise ?? row.product.sale_rate_paise) }), _jsx("td", { children: _jsx(Status, { value: batchStatus(row.product, row.batch) }) }), _jsxs("td", { className: "row-actions", children: [_jsx("button", { className: "btn small", type: "button", onClick: () => onOpen("medicines", row.product.id), children: "View" }), _jsx("button", { className: "btn small", type: "button", onClick: () => onOpen("receive", row.product.id), children: "Receive" }), _jsx("button", { className: "btn small", type: "button", onClick: () => onOpen("adjustments", row.product.id), children: "Adjust" }), _jsx("button", { className: "btn small", type: "button", onClick: () => onOpen("movements", row.product.id), children: "View movements" })] })] }, row.key))) })] }) })] }));
}
function Movements({ products, focus }) {
    const [productId, setProductId] = useState(focus);
    const { data, error, loading } = useData(`/api/inventory/ledger${productId ? `?product_id=${encodeURIComponent(productId)}` : ""}`);
    return (_jsxs("div", { children: [_jsx(Field, { label: "Medicine", children: _jsxs("select", { "aria-label": "Movement medicine", value: productId, onChange: (e) => setProductId(e.target.value), children: [_jsx("option", { value: "", children: "All recent movements" }), products.map((item) => _jsx("option", { value: item.id, children: item.name }, item.id))] }) }), loading && !data && _jsx(Loading, { label: "Opening the ledger\u2026" }), error && _jsx(ErrorState, { message: error }), !loading && data && !data.items?.length && _jsx(Empty, { text: "No stock movement is recorded for that filter." }), _jsx("div", { className: "table-wrap", children: _jsxs("table", { className: "data", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "When" }), _jsx("th", { children: "Medicine" }), _jsx("th", { children: "Batch" }), _jsx("th", { children: "Type" }), _jsx("th", { className: "num", children: "Qty" }), _jsx("th", { children: "Reason" }), _jsx("th", { children: "Who" })] }) }), _jsx("tbody", { children: (data?.items || []).map((item) => (_jsxs("tr", { children: [_jsx("td", { children: item.at }), _jsx("td", { children: item.product_name }), _jsx("td", { children: item.batch_no }), _jsx("td", { children: item.movement_type }), _jsx("td", { className: "num", children: item.qty }), _jsx("td", { children: item.explained_by || item.reason || "—" }), _jsx("td", { children: item.user_name || "—" })] }, item.id))) })] }) })] }));
}
function Receive({ products, hit, code, focus, canEdit, onIdentify, onScan }) {
    const [picked, setPicked] = useState(null);
    const chosen = picked ?? hit?.product?.id ?? focus;
    const product = products.find((item) => item.id === chosen) || (hit?.product?.id === chosen ? hit.product : null);
    const batches = (products.find((item) => item.id === chosen)?.batches || []).filter((item) => item.active !== 0);
    const [batchId, setBatchId] = useState("");
    const [batchNo, setBatchNo] = useState("");
    const [mfg, setMfg] = useState("");
    const [expiry, setExpiry] = useState("");
    const [qty, setQty] = useState("");
    const [purchase, setPurchase] = useState("");
    const [sale, setSale] = useState("");
    if (!canEdit)
        return _jsx("p", { className: "muted", children: "You can look up stock, but not receive it." });
    return (_jsxs("div", { className: "panel", children: [_jsx("h2", { children: "Receive stock" }), _jsxs("div", { className: "body grid-form", children: [_jsx("p", { className: "muted span-2", children: "Identify the package, choose or create a batch, enter the quantity, then confirm. The scan itself does not receive stock or create a batch." }), _jsx(Field, { label: "Package barcode", children: _jsx("input", { "aria-label": "Receive barcode", defaultValue: code, onBlur: (e) => { if (e.target.value.trim())
                                onIdentify(e.target.value); } }, code) }), _jsx("div", { className: "row-actions", children: _jsx("button", { className: "btn", type: "button", onClick: onScan, children: "Scan barcode" }) }), _jsx(Field, { label: "Medicine", children: _jsxs("select", { "aria-label": "Receive medicine", value: chosen, onChange: (e) => { setPicked(e.target.value); setBatchId(""); }, children: [_jsx("option", { value: "", children: "Choose a registered medicine" }), products.filter((item) => item.active).map((item) => _jsxs("option", { value: item.id, children: [item.name, " ", item.strength] }, item.id))] }) }), _jsx(Field, { label: "Existing batch", children: _jsxs("select", { "aria-label": "Existing batch", value: batchId, onChange: (e) => setBatchId(e.target.value), children: [_jsx("option", { value: "", children: "Create a new batch" }), batches.map((item) => _jsxs("option", { value: item.id, children: [item.batch_no, " \u00B7 exp ", item.expiry_date || "—", " \u00B7 ", item.qty_on_hand] }, item.id))] }) }), !batchId && (_jsxs(_Fragment, { children: [_jsx(Field, { label: "New batch number", children: _jsx("input", { "aria-label": "New batch number", value: batchNo, onChange: (e) => setBatchNo(e.target.value) }) }), _jsx(Field, { label: "Manufactured", children: _jsx("input", { "aria-label": "Manufactured date", value: mfg, onChange: (e) => setMfg(e.target.value), placeholder: "YYYY-MM-DD" }) }), _jsx(Field, { label: "Expiry", children: _jsx("input", { "aria-label": "Expiry date", value: expiry, onChange: (e) => setExpiry(e.target.value), placeholder: "YYYY-MM-DD" }) }), _jsx(Field, { label: "Purchase price Rs", children: _jsx("input", { value: purchase, onChange: (e) => setPurchase(e.target.value) }) }), _jsx(Field, { label: "Sale price Rs", children: _jsx("input", { value: sale, onChange: (e) => setSale(e.target.value) }) })] })), _jsx(Field, { label: `Quantity in ${product?.unit || "base units"}`, children: _jsx("input", { "aria-label": "Receive quantity", value: qty, onChange: (e) => setQty(e.target.value) }) }), _jsx("button", { className: "btn primary", type: "button", disabled: !chosen || !(Number(qty) > 0), onClick: () => {
                            if (!window.confirm(`Receive ${qty} ${product?.unit || "units"} of ${product?.name || "this medicine"}?`))
                                return;
                            const body = { product_id: chosen, qty: Number(qty) };
                            if (hit?.product?.id === chosen && code)
                                body.barcode = code;
                            if (batchId)
                                body.batch_id = batchId;
                            else
                                Object.assign(body, { batch_no: batchNo, mfg_date: mfg, expiry_date: expiry, purchase_rate_paise: paise(purchase), sale_rate_paise: paise(sale) });
                            run(() => api("/api/inventory/receive", { method: "POST", body: JSON.stringify(body) }), "Stock received and written to the ledger");
                        }, children: "Confirm receive" })] })] }));
}
function Adjustments({ products, canAdjust, focus }) {
    const [productId, setProductId] = useState(focus);
    const [batchId, setBatchId] = useState("");
    const [type, setType] = useState("ADJUSTMENT");
    const [qty, setQty] = useState("");
    const [reason, setReason] = useState("");
    const batches = products.find((item) => item.id === productId)?.batches || [];
    if (!canAdjust)
        return _jsx("p", { className: "muted", children: "Adjustments need the inventory adjustment permission." });
    return (_jsxs("div", { className: "panel", children: [_jsx("h2", { children: "Adjustment" }), _jsxs("div", { className: "body grid-form", children: [_jsx(Field, { label: "Medicine", children: _jsxs("select", { "aria-label": "Adjustment medicine", value: productId, onChange: (e) => { setProductId(e.target.value); setBatchId(""); }, children: [_jsx("option", { value: "", children: "Choose" }), products.map((item) => _jsx("option", { value: item.id, children: item.name }, item.id))] }) }), _jsx(Field, { label: "Batch", children: _jsxs("select", { "aria-label": "Adjustment batch", value: batchId, onChange: (e) => setBatchId(e.target.value), children: [_jsx("option", { value: "", children: "Choose" }), batches.map((item) => _jsxs("option", { value: item.id, children: [item.batch_no, " \u00B7 ", item.qty_on_hand] }, item.id))] }) }), _jsx(Field, { label: "Movement", children: _jsx("select", { "aria-label": "Movement type", value: type, onChange: (e) => setType(e.target.value), children: ["ADJUSTMENT", "DAMAGED", "EXPIRED", "LOST", "RETURN"].map((item) => _jsx("option", { children: item }, item)) }) }), _jsx(Field, { label: "Quantity", children: _jsx("input", { "aria-label": "Adjustment quantity", value: qty, onChange: (e) => setQty(e.target.value) }) }), _jsx(Field, { label: "Reason", className: "span-2", children: _jsx("input", { "aria-label": "Adjustment reason", value: reason, onChange: (e) => setReason(e.target.value) }) }), _jsx("button", { className: "btn primary", type: "button", onClick: () => {
                            if (!window.confirm("Post this stock movement?"))
                                return;
                            run(() => api("/api/inventory/movements", { method: "POST", body: JSON.stringify({ batch_id: batchId, qty: Number(qty), movement_type: type, reason }) }), "Stock movement recorded");
                        }, children: "Confirm adjustment" })] })] }));
}
function AlertList({ title, rows, kind, onReceive }) {
    return (_jsxs("div", { children: [_jsx("h2", { className: "section-label", children: title }), !rows.length && _jsx(Empty, { text: "Nothing is on this list." }), _jsx("div", { className: "table-wrap", children: _jsxs("table", { className: "data", children: [_jsx("thead", { children: _jsxs("tr", { children: [_jsx("th", { children: "Medicine" }), kind === "expiry" && _jsx("th", { children: "Batch" }), kind === "expiry" && _jsx("th", { children: "Expiry" }), _jsx("th", { className: "num", children: "On hand" }), _jsx("th", {})] }) }), _jsx("tbody", { children: rows.map((item) => (_jsxs("tr", { children: [_jsx("td", { children: item.name || item.product_name }), kind === "expiry" && _jsx("td", { children: item.batch_no }), kind === "expiry" && _jsx("td", { children: item.expiry_date }), _jsxs("td", { className: "num", children: [item.stock ?? item.qty_on_hand, " ", item.unit || ""] }), _jsx("td", { children: _jsx("button", { className: "btn small", type: "button", onClick: () => onReceive(item.product_id || item.id), children: "Receive" }) })] }, item.id))) })] }) })] }));
}
