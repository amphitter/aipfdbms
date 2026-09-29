import { jsx as _jsx, jsxs as _jsxs, Fragment as _Fragment } from "react/jsx-runtime";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, statusTone } from "./api";
import { useApp } from "./store";
export function Page({ kicker, title, note, actions, children }) {
    return (_jsxs("section", { children: [_jsxs("header", { className: "page-h", children: [_jsxs("div", { children: [kicker && _jsx("div", { className: "kicker", children: kicker }), _jsx("h1", { children: title }), note && _jsx("p", { className: "page-note", children: note })] }), actions && _jsx("div", { className: "page-actions", children: actions })] }), children] }));
}
export function Status({ value }) {
    if (!value)
        return _jsx("span", { className: "muted", children: "\u2014" });
    return _jsx("span", { className: `status ${statusTone(value)}`, children: value.replaceAll("_", " ") });
}
export function Field({ label, children, className = "", required = false }) {
    return (_jsxs("label", { className: `field ${className}`, children: [_jsxs("span", { children: [label, required && _jsx("em", { className: "req", children: "Required" })] }), children] }));
}
export function Modal({ title, onClose, children, footer }) {
    const ref = useRef(null);
    useEffect(() => {
        const onKey = (event) => {
            if (event.key === "Escape")
                onClose();
        };
        window.addEventListener("keydown", onKey);
        ref.current?.querySelector("button, [href], input, select, textarea")?.focus();
        return () => window.removeEventListener("keydown", onKey);
    }, [onClose]);
    return (_jsx("div", { className: "modal-back", onMouseDown: onClose, children: _jsxs("div", { className: "modal", role: "dialog", "aria-modal": "true", "aria-label": title, ref: ref, onMouseDown: (event) => event.stopPropagation(), children: [_jsxs("header", { children: [_jsx("h3", { children: title }), _jsx("button", { className: "btn small", type: "button", onClick: onClose, children: "Close" })] }), _jsx("div", { className: "body", children: children }), footer && _jsx("footer", { children: footer })] }) }));
}
export function Empty({ text, action }) {
    return _jsxs("div", { className: "empty", children: [_jsx("p", { children: text }), action] });
}
export function Loading({ label = "Opening records…" }) {
    return (_jsxs("div", { className: "loading", role: "status", children: [_jsxs("div", { className: "skeleton-rows", "aria-hidden": "true", children: [_jsx("span", {}), _jsx("span", {}), _jsx("span", {})] }), _jsx("p", { className: "muted", children: label })] }));
}
export function ErrorState({ message }) {
    return (_jsxs("div", { className: "error-state", role: "alert", children: [_jsx("strong", { children: "This desk could not load." }), _jsx("p", { children: message }), _jsx("button", { className: "btn", type: "button", onClick: () => useApp.getState().bump(), children: "Retry" })] }));
}
export function Flow({ steps, current, off }) {
    const index = steps.findIndex((step) => step === current);
    return (_jsxs("ol", { className: "flow", "aria-label": "Workflow", children: [steps.map((step, i) => (_jsx("li", { className: off && off === current ? "" : current === step ? "on" : index > i ? "done" : "", children: step.replaceAll("_", " ") }, step))), off && current === off && _jsx("li", { className: "off", children: off.replaceAll("_", " ") })] }));
}
export function useData(path) {
    const tick = useApp((s) => s.tick);
    const [data, setData] = useState(null);
    const [error, setError] = useState("");
    const [loading, setLoading] = useState(Boolean(path));
    useEffect(() => {
        if (!path) {
            setLoading(false);
            return;
        }
        let live = true;
        setLoading(true);
        api(path)
            .then((d) => {
            if (live) {
                setData(d);
                setError("");
            }
        })
            .catch((e) => live && setError(e.message))
            .finally(() => live && setLoading(false));
        return () => {
            live = false;
        };
    }, [path, tick]);
    return { data, error, loading };
}
export function run(action, ok) {
    const toast = useApp.getState().toast;
    return action()
        .then((result) => {
        toast(ok, "ok");
        useApp.getState().bump();
        return result;
    })
        .catch((e) => {
        toast(e.message, "bad");
        throw e;
    });
}
export function PatientLink({ id, name }) {
    return _jsx(Link, { to: `/patients/${id}`, children: name || id });
}
export function Masters({ type, label }) {
    const { data } = useData(`/api/master/${type}`);
    return (_jsxs(_Fragment, { children: [_jsx("option", { value: "", children: label }), (data?.items || []).map((item) => (_jsx("option", { value: item.id, children: item.name }, item.id)))] }));
}
