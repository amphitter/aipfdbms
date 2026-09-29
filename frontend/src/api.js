const TOKEN_KEY = "aipf-token";
export function getToken() {
    return sessionStorage.getItem(TOKEN_KEY) || "";
}
export function setToken(token) {
    sessionStorage.setItem(TOKEN_KEY, token);
}
export function clearToken() {
    sessionStorage.removeItem(TOKEN_KEY);
}
export function workstation() {
    return sessionStorage.getItem("aipf-workstation") || "";
}
export function setWorkstation(name) {
    sessionStorage.setItem("aipf-workstation", name);
}
export class ApiError extends Error {
    status;
    code;
    constructor(message, status = 400, code = "") {
        super(message);
        this.status = status;
        this.code = code;
    }
}
const inflight = new Map();
export async function api(path, opts = {}) {
    const method = (opts.method || "GET").toUpperCase();
    const key = method + " " + path;
    if (method === "GET" && inflight.has(key))
        return inflight.get(key);
    const work = request(path, opts);
    if (method === "GET") {
        inflight.set(key, work);
        work.finally(() => inflight.delete(key));
    }
    return work;
}
function staffError(message, status) {
    const raw = typeof message === "string" ? message.trim() : "";
    if (!raw || status >= 500 || /traceback|sqlite|psycopg|operationalerror|internal server error|exception|syntax error/i.test(raw)) {
        return status >= 500
            ? "The hospital server could not complete that. Try again, or open System Health if it keeps failing."
            : "That action was refused. Check the fields and try again.";
    }
    return raw;
}
async function request(path, opts) {
    const headers = new Headers(opts.headers || {});
    if (opts.body && !headers.has("Content-Type"))
        headers.set("Content-Type", "application/json");
    const token = getToken();
    if (token)
        headers.set("Authorization", `Bearer ${token}`);
    const desk = workstation();
    if (desk)
        headers.set("X-Workstation", desk);
    const res = await fetch(path, { ...opts, headers });
    if (res.status === 401) {
        clearToken();
        window.dispatchEvent(new Event("aipf-unauthorized"));
    }
    const type = res.headers.get("content-type") || "";
    if (type.includes("application/pdf") || type.includes("text/csv")) {
        if (!res.ok)
            throw new ApiError("The file could not be prepared.", res.status);
        return res;
    }
    const json = await res.json().catch(() => ({}));
    if (res.status === 403) {
        window.dispatchEvent(new CustomEvent("aipf-forbidden", { detail: json.error?.message || "You do not have permission for this action." }));
    }
    if (!res.ok || json.ok === false) {
        throw new ApiError(staffError(json.error?.message, res.status), res.status, json.error?.code || "");
    }
    return json.data;
}
export function money(paise) {
    const value = (Number(paise) || 0) / 100;
    return new Intl.NumberFormat("en-IN", {
        style: "currency",
        currency: "INR",
        minimumFractionDigits: 2,
    }).format(value);
}
export function paise(rupees) {
    const n = typeof rupees === "number" ? rupees : Number(String(rupees).replace(/,/g, ""));
    if (!Number.isFinite(n))
        return 0;
    return Math.round(n * 100);
}
export function when(iso) {
    if (!iso)
        return "—";
    return iso.replace("T", " ").slice(0, 16);
}
export function day(iso) {
    if (!iso)
        return "—";
    return iso.slice(0, 10);
}
export function person(title, name) {
    return [title, name].filter(Boolean).join(" ");
}
export function fileUrl(path) {
    const token = getToken();
    const join = path.includes("?") ? "&" : "?";
    return `${path}${join}token=${encodeURIComponent(token)}`;
}
export function statusTone(status) {
    const s = (status || "").toUpperCase();
    if (["PAID", "COMPLETED", "DISPENSED", "HEALTHY", "AVAILABLE", "RESULTED", "SUCCESSFUL", "ADMITTED"].includes(s))
        return "ok";
    if (["PARTIAL", "WAITING", "CALLED", "QUEUED", "REQUESTED", "SCHEDULED", "DEGRADED", "UNPAID", "DRAFT", "NOTES_PENDING", "RESERVED"].includes(s))
        return "wait";
    if (["FAILED", "CRITICAL", "CANCELLED", "VOID", "EXPIRED", "UNSUCCESSFUL", "ABORTED", "BLOCKED", "LOW", "INACTIVE"].includes(s))
        return "bad";
    if (s === "EXPIRING" || s === "NO BATCH")
        return "wait";
    if (s === "IN STOCK")
        return "ok";
    if (["IN_CONSULTATION", "PROCESSING", "OCCUPIED", "FINALIZED", "PERFORMED", "IN_PROGRESS", "PRE_OP", "RECOVERY", "APPROVED"].includes(s))
        return "info";
    return "";
}
