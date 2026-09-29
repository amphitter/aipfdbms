import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useApp } from "./store";
const TOUR = [
    { id: "/", title: "Today", body: "This is the floor. It shows what needs attention now: the queue, admissions, pharmacy, lab, bills, and system status. It is not a wall of decorative cards.", perm: "" },
    { id: "/patients", title: "Patients", body: "Search and open a record here. The permanent patient ID is the identity. A phone number is only a way to find someone.", perm: "patient.view" },
    { id: "/register", title: "OPD", body: "Register a person, then start the encounter and place them in the queue. Phone matches are a warning, never an automatic merge.", perm: "patient.create" },
    { id: "/queue", title: "Queue", body: "Reception watches tokens, wait time, and status here. Calling a patient is a separate click from opening the list.", perm: "queue.view" },
    { id: "/doctor", title: "Doctor queue", body: "Open your patient, write the consultation, and finalize the prescription. Pharmacy sees it only after you send it.", perm: "consultation.create" },
    { id: "/pharmacy", title: "Pharmacy", body: "Scan to identify the package, choose the batch, enter the quantity, then confirm. A scan does not dispense.", perm: "pharmacy.view" },
    { id: "/inventory", title: "Inventory", body: "Register the medicine, then the package, then the barcode, then the batch. An unknown scan does not create a product.", perm: "inventory.view" },
    { id: "/lab", title: "Lab", body: "An order moves through collection, processing, result, and report. Each stage is a deliberate action.", perm: "lab.view" },
    { id: "/admissions", title: "Admissions", body: "An admission has a ward, room, bed, charges, and a discharge. It is not a stack of OPD visits.", perm: "admission.view" },
    { id: "/ot", title: "OT", body: "A case moves from requested to approved, scheduled, pre-op, in progress, recovery, and completed. Cancelled and postponed stay visible.", perm: "ot.view" },
    { id: "/billing", title: "Billing", body: "The server calculates the invoice. Finalize locks the charges. A later correction is a reversal, not a silent edit.", perm: "billing.view" },
    { id: "/documents", title: "Documents", body: "Reports and scans stay on this server and belong to a patient. Open the patient record to add one.", perm: "document.view" },
    { id: "/setup", title: "Settings", body: "Hospital setup, branding, and the replay controls live with administration. Skip does not hide a permission error.", perm: "config.manage" },
    { id: "/help", title: "Help", body: "Replay this tour or start Learn the workflow from Help. The walkthrough never clicks, bills, or dispenses for you.", perm: "" },
];
const DEMO = [
    { to: "/register", title: "Register a patient", task: "Open OPD and enter the person yourself. Phone finds possible matches. It does not merge two people." },
    { to: "/register", title: "Create an OPD encounter", task: "Choose an OPD type and, if you mean to, place the patient in the queue. This guide will not submit the form." },
    { to: "/queue", title: "Open the queue", task: "See the token, wait, doctor, and status. Calling a token is your click, not this panel's." },
    { to: "/doctor", title: "Open the doctor queue", task: "Open a waiting patient when you are ready to consult. The guide does not open a chart for you." },
    { to: "/pharmacy", title: "Pharmacy", task: "Scan or type a barcode to identify a package. Choose a batch and confirm before anything is dispensed." },
    { to: "/lab", title: "Lab", task: "Follow an order from collection to result and report. Do not mark a stage complete unless that work is done." },
    { to: "/billing", title: "Billing", task: "Open a bill and read draft, finalized, paid, and due. Do not take a payment unless you intend to." },
    { to: "/documents", title: "Documents", task: "Documents belong to a patient. Open a record from here if you need to file one." },
    { to: "/inventory", title: "Inventory", task: "An unknown barcode stays unknown until you register the product, package, and barcode." },
    { to: "/admissions", title: "Admissions", task: "Open a current admission to see ward, bed, charges, and discharge. Do not discharge from this walkthrough unless you mean to." },
    { to: "/ot", title: "OT", task: "Read the case state. Moving a case forward is a separate confirmation, not part of this guide." },
    { to: "/help", title: "Finish on Help", task: "You opened each desk yourself. Replay this any time from Help." },
];
function seenKey(userId) {
    return `aipf-tour:${userId}`;
}
export function SpotlightTour() {
    const user = useApp((s) => s.user);
    const can = useApp((s) => s.can);
    const steps = useMemo(() => TOUR.filter((step) => !step.perm || can(step.perm)), [can, user]);
    const [open, setOpen] = useState(false);
    const [step, setStep] = useState(0);
    const [box, setBox] = useState(null);
    const current = steps[step];
    const admin = Boolean(user && (can("config.manage") || can("user.manage")));
    useEffect(() => {
        if (!user)
            return;
        if (admin && !localStorage.getItem(seenKey(user.id)))
            setOpen(true);
        const replay = () => {
            localStorage.removeItem(seenKey(user.id));
            setStep(0);
            setOpen(true);
        };
        window.addEventListener("aipf-replay-tour", replay);
        return () => window.removeEventListener("aipf-replay-tour", replay);
    }, [user, admin]);
    useEffect(() => {
        if (!open || !current)
            return;
        const place = () => {
            const node = document.querySelector(`[data-tour="${current.id}"]`);
            if (!node) {
                setBox(null);
                return;
            }
            const rect = node.getBoundingClientRect();
            setBox({ top: rect.top - 4, left: rect.left - 4, width: Math.max(rect.width, 28) + 8, height: rect.height + 8 });
        };
        place();
        window.addEventListener("resize", place);
        return () => window.removeEventListener("resize", place);
    }, [open, current]);
    if (!open || !user || !current)
        return null;
    function finish(skipped) {
        if (user)
            localStorage.setItem(seenKey(user.id), skipped ? "skipped" : "finished");
        setOpen(false);
    }
    const cardTop = box ? Math.min(box.top + box.height + 12, window.innerHeight - 240) : 88;
    const cardLeft = box ? Math.min(Math.max(16, box.left), window.innerWidth - 380) : 24;
    return (_jsxs("div", { className: "tour-layer", role: "dialog", "aria-label": "First-time tour", children: [box && _jsx("div", { className: "tour-ring", style: { top: box.top, left: box.left, width: box.width, height: box.height } }), _jsxs("div", { className: "tour-card", style: { top: cardTop, left: cardLeft }, children: [_jsxs("div", { className: "kicker", children: ["Step ", step + 1, " of ", steps.length] }), _jsx("h2", { children: current.title }), _jsx("p", { children: current.body }), _jsx("p", { className: "muted", children: "You control this tour. It does not open desks or complete work for you." }), _jsxs("div", { className: "row-actions", children: [_jsx("button", { className: "btn small", type: "button", disabled: step === 0, onClick: () => setStep((n) => Math.max(0, n - 1)), children: "Back" }), step < steps.length - 1 ? (_jsx("button", { className: "btn small primary", type: "button", onClick: () => setStep((n) => n + 1), children: "Next" })) : (_jsx("button", { className: "btn small primary", type: "button", onClick: () => finish(false), children: "Finish" })), _jsx("button", { className: "btn small", type: "button", onClick: () => finish(true), children: "Skip" })] })] })] }));
}
export function GuidedDemo() {
    const [open, setOpen] = useState(false);
    const [step, setStep] = useState(0);
    const [opened, setOpened] = useState({});
    const navigate = useNavigate();
    const can = useApp((s) => s.can);
    const steps = DEMO.filter((item) => {
        if (item.to === "/register")
            return can("patient.create");
        if (item.to === "/queue")
            return can("queue.view");
        if (item.to === "/doctor")
            return can("consultation.create");
        if (item.to === "/pharmacy")
            return can("pharmacy.view");
        if (item.to === "/lab")
            return can("lab.view");
        if (item.to === "/billing")
            return can("billing.view");
        if (item.to === "/documents")
            return can("document.view");
        if (item.to === "/inventory")
            return can("inventory.view");
        if (item.to === "/admissions")
            return can("admission.view");
        if (item.to === "/ot")
            return can("ot.view");
        return true;
    });
    const current = steps[step];
    useEffect(() => {
        const start = () => {
            setStep(0);
            setOpened({});
            setOpen(true);
        };
        window.addEventListener("aipf-start-demo", start);
        return () => window.removeEventListener("aipf-start-demo", start);
    }, []);
    if (!open || !current)
        return null;
    const ready = !!opened[step];
    return (_jsxs("aside", { className: "demo-panel", role: "dialog", "aria-label": "Learn the workflow", children: [_jsxs("div", { className: "kicker", children: ["Learn the workflow \u00B7 ", step + 1, " of ", steps.length] }), _jsx("h2", { children: current.title }), _jsx("p", { children: current.task }), _jsx("p", { className: "muted", children: "This walkthrough does not click for you and does not create a bill, a dispense, or a patient." }), _jsxs("div", { className: "row-actions", children: [_jsx("button", { className: "btn small primary", type: "button", onClick: () => { navigate(current.to); setOpened({ ...opened, [step]: true }); }, children: "Open this desk" }), _jsx("button", { className: "btn small", type: "button", disabled: step === 0, onClick: () => setStep((n) => n - 1), children: "Back" }), step < steps.length - 1 ? (_jsx("button", { className: "btn small", type: "button", disabled: !ready, onClick: () => setStep((n) => n + 1), children: "Next" })) : (_jsx("button", { className: "btn small", type: "button", disabled: !ready, onClick: () => setOpen(false), children: "Finish" })), _jsx("button", { className: "btn small", type: "button", onClick: () => setOpen(false), children: "Skip" })] })] }));
}
