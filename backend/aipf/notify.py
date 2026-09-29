"""WhatsApp provider abstraction and the notification queue. Billing never waits on this."""

from __future__ import annotations

from aipf.repo import billing as billing_sql
from aipf.repo import notifications as notifications_sql
from aipf.repo import patients as patients_sql

import base64
import json
import mimetypes
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .core import audit, config_get, hospital
from .db import one, rows
from .events import publish
from .util import ApiError, clean_text, new_id, now_iso, redact, require

TEMPLATE_VARS = ["hospital_name", "patient_name", "bill_number", "visit_date", "doctor_name", "document_name"]


class WhatsAppProvider:
    name = "none"

    def send_text(self, phone: str, text: str) -> dict:
        raise ApiError("WhatsApp provider is not configured.")

    def send_document(self, phone: str, filename: str, data: bytes, caption: str) -> dict:
        raise ApiError("WhatsApp provider is not configured.")

    def check_connection(self) -> dict:
        return {"ok": False, "state": "not_configured", "detail": "OpenWA is not configured. Hospital work continues without it."}

    def get_session_status(self) -> dict:
        return self.check_connection()

    def get_qr_code(self) -> dict:
        return {"ok": False, "detail": "No session."}

    def disconnect(self) -> dict:
        return {"ok": True}

    def reconnect(self) -> dict:
        return self.check_connection()


def openwa_api_root(base_url: str) -> str:
    """Documented REST root is the origin plus one /api prefix. A configured URL that already ends in /api is not doubled."""
    base = (base_url or "").strip()
    if not base:
        return ""
    parts = urlsplit(base)
    if not parts.scheme or not parts.netloc:
        return ""
    path = (parts.path or "").rstrip("/")
    if path.lower().endswith("/api"):
        path = path[: -len("/api")]
    root_path = f"{path}/api" if path else "/api"
    return urlunsplit((parts.scheme, parts.netloc, root_path, "", "")).rstrip("/")


def confirmed_message_id(result: dict | None) -> str:
    """OpenWA confirms submission with messageId. HTTP success alone is not confirmation."""
    if not isinstance(result, dict) or not result.get("ok"):
        return ""
    message_id = result.get("messageId")
    if not isinstance(message_id, str):
        return ""
    message_id = message_id.strip()
    if not message_id or len(message_id) > 200:
        return ""
    return message_id


def safe_failure_reason(result: dict | None) -> str:
    result = result or {}
    detail = result.get("detail") or result.get("state") or "OpenWA did not confirm the message."
    text = " ".join(redact(str(detail), 400).split())
    return text or "OpenWA did not confirm the message."


def _json_object(raw: str) -> dict:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _provider_text(raw: str) -> str:
    parsed = _json_object(raw)
    message = parsed.get("message") or parsed.get("error") or parsed.get("detail")
    if isinstance(message, list):
        message = "; ".join(str(item) for item in message[:4])
    text = str(message or "").strip()
    if not text and raw and not parsed:
        text = raw.strip()
    return " ".join(redact(text, 240).split())


def _http_failure(status: int, raw: str, path: str) -> dict:
    if status in (401, 403):
        state = "unauthorized"
    elif status == 404:
        state = "not_found"
    elif status == 409:
        state = "conflict"
    elif status in (408, 429) or status >= 500:
        state = "unavailable"
    else:
        state = "error"
    detail = f"OpenWA returned {status}"
    if path:
        detail += f" for {path}"
    detail += "."
    body = _provider_text(raw)
    if body:
        detail = f"{detail} {body}"
    return {
        "ok": False,
        "state": state,
        "http_status": status,
        "detail": detail[:400],
        "retryable": status in (408, 409, 429) or status >= 500,
    }


def _is_timeout(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    text = str(exc).lower()
    return "timed out" in text or "timeout" in text


def _url_failure(exc: urllib.error.URLError) -> dict:
    reason = getattr(exc, "reason", exc)
    if _is_timeout(reason) or _is_timeout(exc):
        return {"ok": False, "state": "timeout", "detail": "OpenWA timed out.", "retryable": True}
    return {"ok": False, "state": "unreachable", "detail": "OpenWA could not be reached.", "retryable": True}


def _log_whatsapp(method: str, path: str, status, state: str) -> None:
    code = "-" if status is None else status
    print(
        f"AIPF whatsapp method={method} path={path} status={code} state={state}",
        file=sys.stderr,
        flush=True,
    )


class OpenWAProvider(WhatsAppProvider):
    """HTTP adapter for the documented OpenWA REST API. Does not administer OpenWA."""

    name = "openwa"

    def __init__(self, base_url: str, api_key: str, session_id: str):
        self.base_url = (base_url or "").strip()
        self.api_key = api_key or ""
        self.session_id = (session_id or "").strip()
        self.status_timeout = 8
        self.text_timeout = 8
        self.file_timeout = 20

    def _scrub(self, text: str) -> str:
        cleaned = redact(text or "", 400)
        key = self.api_key
        if key and len(key) >= 4:
            cleaned = cleaned.replace(key, "[redacted]")
        return cleaned

    def _session_error(self) -> dict | None:
        session = self.session_id
        if not session:
            return {"ok": False, "state": "not_configured", "detail": "OpenWA session id is not set."}
        if any(mark in session for mark in ("/", "\\", "?", "#", " ")):
            return {"ok": False, "state": "not_configured", "detail": "OpenWA session id is not a single path segment."}
        return None

    def _request(self, method: str, path: str, body: dict | None = None, timeout: int = 8, *, auth: bool = True, confirm: str | None = None) -> dict:
        root = openwa_api_root(self.base_url)
        if not root:
            return {"ok": False, "state": "not_configured", "detail": "OpenWA base URL is not set."}
        url = f"{root}{path}"
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if auth and self.api_key:
            req.add_header("X-API-Key", self.api_key)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as res:
                raw = res.read().decode("utf-8", errors="replace")
                parsed = _json_object(raw)
                if confirm == "messageId":
                    message_id = parsed.get("messageId")
                    if 200 <= res.status < 300 and isinstance(message_id, str) and message_id.strip():
                        result = {
                            "ok": True,
                            "state": "accepted",
                            "http_status": res.status,
                            "messageId": message_id.strip(),
                        }
                    else:
                        result = {
                            "ok": False,
                            "state": "unconfirmed",
                            "http_status": res.status,
                            "detail": "OpenWA did not return a message id. The message was not marked sent.",
                            "retryable": True,
                        }
                elif 200 <= res.status < 300:
                    result = {"ok": True, "state": "ok", "http_status": res.status}
                    if isinstance(parsed.get("status"), str):
                        result["status"] = parsed["status"]
                    qr = parsed.get("qrCode")
                    if isinstance(qr, str) and qr.strip():
                        result["qrCode"] = qr.strip()
                else:
                    result = _http_failure(res.status, raw, path)
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            result = _http_failure(exc.code, raw, path)
        except TimeoutError:
            result = {"ok": False, "state": "timeout", "detail": "OpenWA timed out.", "retryable": True}
        except urllib.error.URLError as exc:
            result = _url_failure(exc)
        except Exception as exc:
            if _is_timeout(exc):
                result = {"ok": False, "state": "timeout", "detail": "OpenWA timed out.", "retryable": True}
            else:
                result = {"ok": False, "state": "unreachable", "detail": "OpenWA could not be reached.", "retryable": True}
        if result.get("detail"):
            result["detail"] = self._scrub(str(result["detail"]))
        if not result.get("ok"):
            _log_whatsapp(method, path, result.get("http_status"), str(result.get("state") or "error"))
        return result

    def probe(self) -> dict:
        configured = bool(openwa_api_root(self.base_url) and self.api_key and self.session_id and self._session_error() is None)
        result = {
            "configured": configured,
            "reachable": False,
            "authenticated": False,
            "session_status": "not_configured",
            "provider": self.name,
            "detail": "",
        }
        if not openwa_api_root(self.base_url):
            result["detail"] = "OpenWA base URL is not set."
            return result
        health = self._request("GET", "/health", timeout=self.status_timeout, auth=False)
        if health.get("state") == "timeout":
            result["session_status"] = "timeout"
            result["detail"] = health.get("detail") or "OpenWA timed out."
            return result
        if not health.get("ok") and not health.get("http_status"):
            result["session_status"] = "unreachable"
            result["detail"] = health.get("detail") or "OpenWA could not be reached."
            return result
        result["reachable"] = True
        if not self.api_key:
            result["session_status"] = "missing_key"
            result["detail"] = "OpenWA API key is not set."
            return result
        missing = self._session_error()
        if missing:
            result["session_status"] = "missing_session"
            result["detail"] = missing["detail"]
            return result
        session = self._request("GET", f"/sessions/{self.session_id}", timeout=self.status_timeout, auth=True)
        code = session.get("http_status")
        if session.get("state") == "unauthorized" or code in (401, 403):
            result["session_status"] = "unauthorized"
            result["detail"] = session.get("detail") or "OpenWA rejected the API key."
            return result
        if session.get("state") == "not_found" or code == 404:
            result["authenticated"] = True
            result["session_status"] = "not_found"
            result["detail"] = session.get("detail") or "OpenWA session was not found."
            return result
        if session.get("state") == "timeout":
            result["session_status"] = "timeout"
            result["detail"] = session.get("detail") or "OpenWA timed out."
            return result
        if session.get("ok"):
            status = str(session.get("status") or "unknown")
            result["authenticated"] = True
            result["session_status"] = status
            result["detail"] = f"OpenWA session status is {status}."
            return result
        result["session_status"] = str(session.get("state") or "error")
        result["detail"] = session.get("detail") or "OpenWA session status could not be read."
        return result

    def check_connection(self) -> dict:
        return self.probe()

    def get_session_status(self) -> dict:
        missing = self._session_error()
        if missing:
            return missing
        return self._request("GET", f"/sessions/{self.session_id}", timeout=self.status_timeout)

    def get_qr_code(self) -> dict:
        missing = self._session_error()
        if missing:
            return missing
        return self._request("GET", f"/sessions/{self.session_id}/qr", timeout=self.status_timeout)

    def send_text(self, phone: str, text: str) -> dict:
        missing = self._session_error()
        if missing:
            return missing
        body = {"chatId": _chat_id(phone), "text": text}
        return self._request(
            "POST",
            f"/sessions/{self.session_id}/messages/send-text",
            body,
            timeout=self.text_timeout,
            confirm="messageId",
        )

    def send_document(self, phone: str, filename: str, data: bytes, caption: str) -> dict:
        missing = self._session_error()
        if missing:
            return missing
        name = Path(filename or "document").name or "document"
        mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        body = {
            "chatId": _chat_id(phone),
            "base64": base64.b64encode(data or b"").decode(),
            "mimetype": mime,
            "filename": name,
        }
        if caption:
            body["caption"] = caption
        return self._request(
            "POST",
            f"/sessions/{self.session_id}/messages/send-document",
            body,
            timeout=self.file_timeout,
            confirm="messageId",
        )

    def disconnect(self) -> dict:
        missing = self._session_error()
        if missing:
            return missing
        return self._request("POST", f"/sessions/{self.session_id}/logout", timeout=self.status_timeout)

    def reconnect(self) -> dict:
        missing = self._session_error()
        if missing:
            return missing
        return self._request("POST", f"/sessions/{self.session_id}/start", timeout=self.status_timeout)


def _chat_id(phone: str) -> str:
    digits = "".join(ch for ch in phone if ch.isdigit())
    if digits.startswith("0"):
        digits = "91" + digits[1:]
    if len(digits) == 10:
        digits = "91" + digits
    return f"{digits}@c.us"


def provider_from_config(conn) -> WhatsAppProvider:
    if config_get(conn, "wa_enabled", "0") != "1" and not config_get(conn, "wa_base_url", ""):
        return WhatsAppProvider()
    base = config_get(conn, "wa_base_url", "")
    if not base:
        return WhatsAppProvider()
    return OpenWAProvider(base, config_get(conn, "wa_api_key", ""), config_get(conn, "wa_session_id", ""))


def render_template(body: str, variables: dict) -> str:
    text = body or ""
    safe = {key: str(variables.get(key) or "") for key in TEMPLATE_VARS}
    for key, value in safe.items():
        text = text.replace("{" + key + "}", value)
    unknown = [token for token in _braces(text)]
    if unknown:
        raise ApiError("Template uses unknown variables: " + ", ".join(unknown))
    return text


def _braces(text: str) -> list[str]:
    import re
    return [m for m in re.findall(r"\{([a-z_]+)\}", text) if m not in TEMPLATE_VARS]


def validate_template(body: str) -> str:
    render_template(body, {key: key for key in TEMPLATE_VARS})
    return body


def list_templates(conn) -> list[dict]:
    return notifications_sql.q_notify_6419(conn)


def save_template(conn, user, payload: dict, template_id: str | None = None) -> dict:
    body = validate_template(payload.get("body") or "")
    name = clean_text(payload.get("name"), 80)
    require(name and body, "Name and message are required.")
    if template_id:
        notifications_sql.q_notify_6764(conn, name, body, clean_text(payload.get("message_type"), 40), 1 if payload.get("active", True) else 0, now_iso(), template_id)
    else:
        template_id = new_id("TPL")
        notifications_sql.q_notify_7093(conn, template_id, name, clean_text(payload.get("message_type") or "visit_complete", 40), body, now_iso())
    audit(conn, user, "template_save", "whatsapp", "template", template_id)
    return notifications_sql.q_notify_7479(conn, template_id)


def notify_in_app(conn, user_id: str, title: str, body: str, entity_type: str, entity_id: str):
    nid = new_id("NT")
    notifications_sql.q_notify_7681(conn, nid, user_id, title, body, entity_type, entity_id, now_iso(), now_iso())
    publish("notification.updated", {"id": nid, "user_id": user_id})
    return nid


def maybe_queue_bill_message(conn, user, invoice_id: str):
    if config_get(conn, "wa_enabled", "0") != "1":
        return None
    invoice = billing_sql.q_notify_8207(conn, invoice_id)
    if not invoice or invoice["status"] != "FINALIZED":
        return None
    existing = notifications_sql.q_notify_8360(conn, invoice_id)
    if existing:
        return existing["id"]
    patient = patients_sql.q_notify_8600(conn, invoice["patient_id"])
    phone = (patient or {}).get("primary_phone")
    if not phone:
        return None
    template = notifications_sql.q_notify_8775(conn)
    h = hospital(conn)
    body = render_template(
        (template or {}).get("body") or "Thank you for visiting {hospital_name}. Bill {bill_number} is ready for {patient_name}.",
        {
            "hospital_name": h.get("name") or "AIPF Mission Hospital",
            "patient_name": patient["name"],
            "bill_number": invoice["number"],
            "visit_date": (invoice.get("finalized_at") or "")[:10],
            "doctor_name": "",
            "document_name": "Bill",
        },
    )
    delay = int(config_get(conn, "whatsapp_delay_minutes", "5") or 5)
    from .util import add_minutes
    scheduled = add_minutes(now_iso(), delay)
    nid = new_id("NT")
    notifications_sql.q_notify_9591(conn, nid, patient["id"], phone, (template or {}).get("id"), body, scheduled, invoice_id, now_iso(), now_iso())
    audit(conn, user, "whatsapp_queue", "whatsapp", "notification", nid, new={"invoice": invoice["number"], "scheduled_at": scheduled})
    publish("notification.updated", {"id": nid, "status": "QUEUED"})
    return nid


def list_notifications(conn, channel: str = "", status: str = "", user_id: str = "") -> dict:
    return {"items": notifications_sql.list_notifications(conn, channel, status, user_id)}


def mark_read(conn, user, notification_id: str) -> dict:
    row = notifications_sql.q_notify_10846(conn, notification_id)
    require(row, "Notification not found.", 404, "not_found")
    if row["channel"] == "IN_APP" and row.get("user_id") not in (user["id"], None):
        raise ApiError("This notification belongs to someone else.", 403, "forbidden")
    notifications_sql.q_notify_11155(conn, now_iso(), notification_id)
    return notifications_sql.q_notify_11276(conn, notification_id)


def process_queue(conn, limit: int = 5) -> int:
    due = notifications_sql.q_notify_11408(conn, now_iso(), limit)
    provider = provider_from_config(conn)
    handled = 0
    for note in due:
        notifications_sql.q_notify_11724(conn, now_iso(), note["id"])
        if not isinstance(provider, OpenWAProvider):
            _fail(conn, note, "WhatsApp provider is not configured.")
            handled += 1
            continue
        try:
            result = provider.send_text(note.get("phone") or "", note.get("body") or "")
        except Exception as exc:
            result = {"ok": False, "state": "error", "detail": safe_failure_reason({"detail": str(exc)})}
        message_id = confirmed_message_id(result)
        if message_id:
            notifications_sql.q_notify_12356(conn, now_iso(), message_id[:120], now_iso(), note["id"])
        else:
            _fail(conn, note, safe_failure_reason(result))
        handled += 1
        publish("notification.updated", {"id": note["id"]})
    return handled


def _fail(conn, note: dict, reason: str):
    retries = int(note.get("retry_count") or 0) + 1
    max_retries = int(note.get("max_retries") or 3)
    status = "FAILED" if retries >= max_retries else "QUEUED"
    from .util import add_minutes
    scheduled = add_minutes(now_iso(), min(30, 2 ** retries))
    notifications_sql.q_notify_13150(conn, status, retries, clean_text(reason, 400), scheduled, now_iso(), note["id"])


def retry_notification(conn, user, notification_id: str) -> dict:
    note = notifications_sql.q_notify_13458(conn, notification_id)
    require(note, "Notification not found.", 404, "not_found")
    notifications_sql.q_notify_13597(conn, now_iso(), now_iso(), notification_id)
    audit(conn, user, "whatsapp_retry", "whatsapp", "notification", notification_id)
    return notifications_sql.q_notify_13876(conn, notification_id)


def cancel_notification(conn, user, notification_id: str) -> dict:
    notifications_sql.q_notify_14021(conn, now_iso(), notification_id)
    audit(conn, user, "whatsapp_cancel", "whatsapp", "notification", notification_id)
    return notifications_sql.q_notify_14267(conn, notification_id)


def connection_status(conn) -> dict:
    provider = provider_from_config(conn)
    if not isinstance(provider, OpenWAProvider):
        return {
            "configured": False,
            "reachable": False,
            "authenticated": False,
            "session_status": "not_configured",
            "provider": "none",
        }
    probe = provider.probe()
    status = str(probe.get("session_status") or "unknown")
    return {
        "configured": bool(probe.get("configured")),
        "reachable": bool(probe.get("reachable")),
        "authenticated": bool(probe.get("authenticated")),
        "session_status": status,
        "provider": "openwa",
    }


def qr_status(conn) -> dict:
    result = provider_from_config(conn).get_qr_code()
    safe = _safe_provider(result)
    image = _qr_image(result)
    if image:
        safe["ok"] = True
        safe["state"] = result.get("status") or result.get("state") or "qr_ready"
        safe["detail"] = ""
        safe["image"] = image
    return safe


def send_patient_message(conn, user, payload: dict) -> dict:
    from .access import guard_patient
    from .core import permit

    permit(user, "whatsapp.send", conn, "whatsapp_send")
    require(payload.get("confirm") is True, "Confirm the recipient before sending.")
    patient_id = clean_text(payload.get("patient_id"), 40)
    guard_patient(conn, user, patient_id)
    patient = patients_sql.q_notify_8600(conn, patient_id)
    require(patient, "That record was not found.", 404, "not_found")
    phone = clean_text(payload.get("phone") or patient.get("primary_phone"), 20)
    require(phone, "This patient has no phone number.")
    text = clean_text(payload.get("text"), 1000)
    require(text, "Write the message before sending.")
    try:
        result = provider_from_config(conn).send_text(phone, text)
    except ApiError as exc:
        result = {"ok": False, "detail": exc.message, "state": "error"}
    _record_attempt(conn, patient_id, phone, "manual", text, result, "patient", patient_id, None)
    audit(conn, user, "whatsapp_manual", "whatsapp", "patient", patient_id, new={"ok": bool(confirmed_message_id(result)), "phone_last4": phone[-4:]})
    if not confirmed_message_id(result):
        raise ApiError(safe_failure_reason(result))
    safe = _safe_provider(result)
    safe["patient_id"] = patient_id
    safe["patient_name"] = patient.get("name")
    return safe


def send_patient_document(conn, user, payload: dict) -> dict:
    from .access import can_read_document, guard_patient, hide_record
    from .core import permit
    from .wards import document_file

    permit(user, "whatsapp.send", conn, "whatsapp_document")
    require(payload.get("confirm") is True, "Confirm the recipient before sending.")
    patient_id = clean_text(payload.get("patient_id"), 40)
    document_id = clean_text(payload.get("document_id"), 40)
    guard_patient(conn, user, patient_id)
    patient = patients_sql.q_notify_8600(conn, patient_id)
    require(patient, "That record was not found.", 404, "not_found")
    phone = clean_text(patient.get("primary_phone"), 20)
    require(phone, "This patient has no phone number.")
    doc, data = document_file(conn, document_id)
    if doc.get("patient_id") != patient_id or not can_read_document(conn, user, doc):
        hide_record(conn, user, "document", document_id)
    caption = clean_text(payload.get("caption") or doc.get("title") or doc.get("filename"), 240)
    try:
        result = provider_from_config(conn).send_document(phone, doc.get("filename") or "document.pdf", data, caption)
    except ApiError as exc:
        result = {"ok": False, "detail": exc.message, "state": "error"}
    _record_attempt(conn, patient_id, phone, "document", caption, result, "document", document_id, document_id)
    audit(conn, user, "whatsapp_document", "whatsapp", "document", document_id, new={"patient_id": patient_id, "ok": bool(confirmed_message_id(result))})
    if not confirmed_message_id(result):
        raise ApiError(safe_failure_reason(result))
    safe = _safe_provider(result)
    safe["document_id"] = document_id
    return safe


def _record_attempt(conn, patient_id, phone, message_type, body, result, entity_type, entity_id, document_id):
    message_id = confirmed_message_id(result)
    notifications_sql.record_outbound(
        conn,
        new_id("NT"),
        patient_id,
        phone,
        message_type,
        clean_text(body, 1000),
        "SENT" if message_id else "FAILED",
        now_iso() if message_id else None,
        None if message_id else safe_failure_reason(result),
        entity_type,
        entity_id,
        document_id,
        now_iso(),
        message_id or None,
    )


def _safe_provider(result: dict | None) -> dict:
    result = result or {}
    message_id = confirmed_message_id(result)
    if message_id:
        return {"ok": True, "state": "accepted", "detail": "", "messageId": message_id}
    detail = result.get("detail") or result.get("state") or ""
    return {
        "ok": False,
        "state": result.get("state") or "error",
        "detail": safe_failure_reason(result) if detail else "",
    }


def _qr_image(result: dict) -> str:
    for key in ("image", "qr", "qrCode", "qrcode", "base64", "dataUrl", "data_url"):
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            text = value.strip()
            if text.startswith("data:image"):
                return text
            if len(text) > 80 and " " not in text[:40]:
                return "data:image/png;base64," + text
    nested = result.get("data")
    if isinstance(nested, dict):
        return _qr_image(nested)
    return ""
