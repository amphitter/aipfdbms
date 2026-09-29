"""Short-lived desk-to-phone barcode handoff.

The token is the only secret. It never carries a patient, a bill, or a credential.
A submitted value is a barcode string. It does not dispense or change stock.
Tokens live in this process and expire after two minutes.
"""

from __future__ import annotations

import hashlib
import threading
import time
from urllib.parse import urlparse

from .util import ApiError, token

_LOCK = threading.Lock()
_PAIRS: dict[str, dict] = {}
_TTL = 120


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _purge(now: float) -> None:
    stale = [key for key, row in _PAIRS.items() if row["expires"] < now]
    for key in stale:
        _PAIRS.pop(key, None)


def _origin(value: str) -> str:
    parsed = urlparse((value or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise ApiError("The pairing page address is not valid.")
    if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ApiError("The pairing page address is not valid.")
    return f"{parsed.scheme}://{parsed.netloc}"


def _can_pair(user) -> None:
    perms = set((user or {}).get("permissions") or [])
    if "pharmacy.view" not in perms and "inventory.view" not in perms:
        raise ApiError("You do not have permission for this action.", 403, "forbidden")


def create_pair(user, origin: str) -> dict:
    _can_pair(user)
    page = _origin(origin)
    raw = token()
    now = time.time()
    with _LOCK:
        _purge(now)
        _PAIRS[_hash(raw)] = {"user_id": user.get("id"), "expires": now + _TTL, "code": "", "used": False}
    url = f"{page}/pair/{raw}"
    svg = ""
    try:
        import segno

        svg = segno.make(url, error="m").svg_inline(scale=4, border=2)
    except Exception:
        svg = ""
    return {"token": raw, "expires_in": _TTL, "url": url, "svg": svg}


def submit_pair(raw: str, code: str) -> dict:
    cleaned = " ".join(str(code or "").split())
    if not cleaned or len(cleaned) > 80:
        raise ApiError("Enter the barcode only.")
    now = time.time()
    with _LOCK:
        _purge(now)
        row = _PAIRS.get(_hash(raw))
        if not row or row["expires"] < now:
            raise ApiError("This pairing code has expired. Start again from the desk.", 404, "not_found")
        if row["used"]:
            raise ApiError("This pairing code was already used.", 409, "conflict")
        row["used"] = True
        row["code"] = cleaned
    return {"ok": True}


def read_pair(user, raw: str) -> dict:
    _can_pair(user)
    now = time.time()
    with _LOCK:
        _purge(now)
        row = _PAIRS.get(_hash(raw))
        if not row or row.get("user_id") != (user or {}).get("id") or row["expires"] < now:
            raise ApiError("This pairing code has expired. Start again from the desk.", 404, "not_found")
        if not row["used"]:
            return {"status": "waiting", "expires_in": max(0, int(row["expires"] - now))}
        return {"status": "ready", "code": row["code"], "expires_in": max(0, int(row["expires"] - now))}
