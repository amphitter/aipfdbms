import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api, statusTone } from "./api";
import { useApp } from "./store";

export function Page({ kicker, title, note, actions, children }: { kicker?: string; title: string; note?: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <section>
      <header className="page-h">
        <div>
          {kicker && <div className="kicker">{kicker}</div>}
          <h1>{title}</h1>
          {note && <p className="page-note">{note}</p>}
        </div>
        {actions && <div className="page-actions">{actions}</div>}
      </header>
      {children}
    </section>
  );
}

export function Status({ value }: { value?: string | null }) {
  if (!value) return <span className="muted">—</span>;
  return <span className={`status ${statusTone(value)}`}>{value.replaceAll("_", " ")}</span>;
}

export function Field({ label, children, className = "", required = false }: { label: string; children: ReactNode; className?: string; required?: boolean }) {
  return (
    <label className={`field ${className}`}>
      <span>{label}{required && <em className="req">Required</em>}</span>
      {children}
    </label>
  );
}

export function Modal({ title, onClose, children, footer }: { title: string; onClose: () => void; children: ReactNode; footer?: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const titleId = `dialog-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key !== "Tab" || !ref.current) return;
      const focusable = Array.from(ref.current.querySelectorAll<HTMLElement>("button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])"));
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    window.addEventListener("keydown", onKey);
    ref.current?.querySelector<HTMLElement>("button, [href], input, select, textarea")?.focus();
    return () => { window.removeEventListener("keydown", onKey); previous?.focus(); };
  }, [onClose]);
  return (
    <div className="modal-back" onMouseDown={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby={titleId} ref={ref} onMouseDown={(event) => event.stopPropagation()}>
        <header>
          <h3 id={titleId}>{title}</h3>
          <button className="icon-btn modal-close" type="button" onClick={onClose} aria-label={`Close ${title}`}>×</button>
        </header>
        <div className="body">{children}</div>
        {footer && <footer>{footer}</footer>}
      </div>
    </div>
  );
}

export function Empty({ text, action }: { text: string; action?: ReactNode }) {
  return <div className="empty"><p>{text}</p>{action}</div>;
}

export function Loading({ label = "Opening records…" }: { label?: string }) {
  return (
    <div className="loading" role="status">
      <div className="skeleton-rows" aria-hidden="true"><span /><span /><span /></div>
      <p className="muted">{label}</p>
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="error-state" role="alert">
      <strong>This desk could not load.</strong>
      <p>{message}</p>
      <button className="btn" type="button" onClick={() => useApp.getState().bump()}>Retry</button>
    </div>
  );
}

export function Flow({ steps, current, off }: { steps: string[]; current?: string; off?: string }) {
  const index = steps.findIndex((step) => step === current);
  return (
    <ol className="flow" aria-label="Workflow">
      {steps.map((step, i) => (
        <li key={step} className={off && off === current ? "" : current === step ? "on" : index > i ? "done" : ""}>{step.replaceAll("_", " ")}</li>
      ))}
      {off && current === off && <li className="off">{off.replaceAll("_", " ")}</li>}
    </ol>
  );
}

export function useData<T>(path: string | null) {
  const tick = useApp((s) => s.tick);
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(Boolean(path));
  useEffect(() => {
    if (!path) {
      setLoading(false);
      return;
    }
    let live = true;
    setLoading(true);
    api<T>(path)
      .then((d) => {
        if (live) {
          setData(d);
          setError("");
        }
      })
      .catch((e: Error) => live && setError(e.message))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [path, tick]);
  return { data, error, loading };
}

export function run(action: () => Promise<unknown>, ok: string) {
  const toast = useApp.getState().toast;
  return action()
    .then((result) => {
      toast(ok, "ok");
      useApp.getState().bump();
      return result;
    })
    .catch((e: Error) => {
      toast(e.message, "bad");
      throw e;
    });
}

export type PatientSummary = {
  id: string;
  name: string;
  hospital_no?: string;
  guardian_name?: string;
  primary_phone?: string;
  age_display?: string;
  age_at_registration?: number | string | null;
  gender?: string;
  status?: string;
};

function maskPhone(value?: string | null) {
  const digits = String(value || "").replace(/\D/g, "");
  if (!digits) return "Phone not recorded";
  if (digits.length <= 4) return digits;
  return `${digits.slice(0, 2)}••••${digits.slice(-2)}`;
}

export function PatientSearchSelect({
  value,
  onChange,
  label = "Patient",
  placeholder = "Search patient by name, phone, Patient ID...",
  disabled = false,
  required = false,
  className = "",
  onRegister,
}: {
  value: PatientSummary | null;
  onChange: (patient: PatientSummary | null) => void;
  label?: string;
  placeholder?: string;
  disabled?: boolean;
  required?: boolean;
  className?: string;
  onRegister?: () => void;
}) {
  const root = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const requestRef = useRef(0);
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<PatientSummary[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [active, setActive] = useState(-1);

  useEffect(() => {
    const close = (event: MouseEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  useEffect(() => {
    if (disabled || value || query.trim().length < 2) {
      setItems([]);
      setLoading(false);
      return;
    }
    const term = query.trim().replace(/\s+/g, " ");
    const requestId = ++requestRef.current;
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setLoading(true);
      setError("");
      setOpen(true);
      api<{ items: PatientSummary[] }>(`/api/patients?q=${encodeURIComponent(term)}&limit=12`, { signal: controller.signal })
        .then((data) => {
          if (requestId !== requestRef.current) return;
          setItems(data.items || []);
          setActive(-1);
        })
        .catch((err: Error) => {
          if (err.name !== "AbortError" && requestId === requestRef.current) setError("Patient search is unavailable. Try again.");
        })
        .finally(() => requestId === requestRef.current && setLoading(false));
    }, 240);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [query, disabled, value]);

  function select(patient: PatientSummary) {
    onChange(patient);
    setQuery("");
    setItems([]);
    setOpen(false);
    setActive(-1);
  }

  function keyDown(event: ReactKeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") {
      setOpen(false);
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setOpen(true);
      setActive((index) => Math.min(index + 1, items.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((index) => Math.max(index - 1, 0));
    } else if (event.key === "Enter" && active >= 0 && items[active]) {
      event.preventDefault();
      select(items[active]);
    }
  }

  return (
    <div className={`patient-select ${className}`} ref={root}>
      <Field label={label} required={required}>
        {value ? (
          <div className="patient-selected" role="status">
            <div className="patient-selected-copy">
              <strong>✓ {value.name}</strong>
              <span className="pid">{value.id}</span>
              <small>{value.guardian_name ? `Guardian: ${value.guardian_name} · ` : ""}{value.age_display || "Age not recorded"} · {value.gender || "Gender not recorded"} · {maskPhone(value.primary_phone)}</small>
            </div>
            {!disabled && <button className="btn small" type="button" onClick={() => { onChange(null); setQuery(""); window.setTimeout(() => inputRef.current?.focus(), 0); }}>Change patient</button>}
          </div>
        ) : (
          <input
            ref={inputRef}
            role="combobox"
            aria-expanded={open}
            aria-controls="patient-search-results"
            aria-autocomplete="list"
            aria-activedescendant={active >= 0 ? `patient-result-${active}` : undefined}
            value={query}
            disabled={disabled}
            placeholder={placeholder}
            onFocus={() => query.trim().length >= 2 && setOpen(true)}
            onChange={(event) => { setQuery(event.target.value); setOpen(event.target.value.trim().length >= 2); }}
            onKeyDown={keyDown}
          />
        )}
      </Field>
      {!value && open && query.trim().length >= 2 && (
        <div className="patient-results" id="patient-search-results" role="listbox">
          {loading && <div className="patient-result-status" role="status">Searching patients…</div>}
          {!loading && error && <div className="patient-result-status error">{error}</div>}
          {!loading && !error && items.map((patient, index) => (
            <button
              className={`patient-result ${index === active ? "active" : ""}`}
              id={`patient-result-${index}`}
              key={patient.id}
              type="button"
              role="option"
              aria-selected={index === active}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => select(patient)}
              onMouseEnter={() => setActive(index)}
            >
              <strong>{patient.name}</strong><span className="pid">{patient.id}</span>
              <small>{patient.guardian_name ? `Guardian: ${patient.guardian_name}` : "Guardian not recorded"} · {patient.age_display || "Age not recorded"} · {patient.gender || "Gender not recorded"} · {maskPhone(patient.primary_phone)}</small>
            </button>
          ))}
          {!loading && !error && items.length === 0 && <div className="patient-result-status">No patient found for “{query.trim()}”.</div>}
          {!loading && onRegister && items.length === 0 && <button className="patient-register-link" type="button" onClick={onRegister}>Register new patient</button>}
        </div>
      )}
    </div>
  );
}

export function PatientLink({ id, name }: { id: string; name?: string }) {
  return <Link to={`/patients/${id}`}>{name || id}</Link>;
}

export function Masters({ type, label }: { type: string; label: string }) {
  const { data } = useData<{ items: any[] }>(`/api/master/${type}`);
  return (
    <>
      <option value="">{label}</option>
      {(data?.items || []).map((item) => (
        <option key={item.id} value={item.id}>{item.name}</option>
      ))}
    </>
  );
}
