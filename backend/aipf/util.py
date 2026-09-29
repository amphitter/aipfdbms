"""Shared helpers: time, money, passwords, errors, identifiers."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Kolkata")

ONES = [
    "", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
    "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
    "Seventeen", "Eighteen", "Nineteen",
]
TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400, code: str = "error", details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.details = details or None


def now() -> datetime:
    return datetime.now(TZ)


def now_iso() -> str:
    return now().isoformat(timespec="seconds")


def today_str() -> str:
    return now().date().isoformat()


def year_now() -> int:
    return now().year


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt


def new_id(prefix: str = "") -> str:
    raw = uuid.uuid4().hex[:12]
    return f"{prefix}{raw}" if prefix else raw


def token() -> str:
    return secrets.token_urlsafe(32)


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 80_000)
    return f"pbkdf2${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt, hx = stored.split("$", 2)
    except ValueError:
        return False
    if scheme != "pbkdf2":
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 80_000)
    return hmac.compare_digest(dk.hex(), hx)


def digits(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def phone_key(value: str | None) -> str:
    d = digits(value)
    if len(d) >= 10:
        return d[-10:]
    return d


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def mask_secret(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "••••"
    return "••••" + value[-4:]


def is_masked(value: str | None) -> bool:
    return bool(value) and str(value).startswith("••••")


def two_digits(n: int) -> str:
    n = int(n)
    if n < 20:
        return ONES[n]
    tens, ones = divmod(n, 10)
    if ones == 0:
        return TENS[tens]
    return f"{TENS[tens]}-{ONES[ones]}"


def words_under_1000(n: int) -> str:
    n = int(n)
    if n < 100:
        return two_digits(n)
    hundreds, rest = divmod(n, 100)
    head = f"{ONES[hundreds]} Hundred"
    if rest:
        return f"{head} {two_digits(rest)}"
    return head


def indian_words(n: int) -> str:
    n = int(n)
    if n == 0:
        return "Zero"
    if n < 0:
        return "Minus " + indian_words(-n)
    parts: list[str] = []
    crore, n = divmod(n, 10_000_000)
    lakh, n = divmod(n, 100_000)
    thousand, n = divmod(n, 1_000)
    if crore:
        parts.append(f"{words_under_1000(crore)} Crore")
    if lakh:
        parts.append(f"{two_digits(lakh)} Lakh")
    if thousand:
        parts.append(f"{words_under_1000(thousand)} Thousand")
    if n:
        parts.append(words_under_1000(n))
    return " ".join(parts)


def amount_in_words(paise: int) -> str:
    paise = int(round(paise))
    sign = ""
    if paise < 0:
        sign = "Minus "
        paise = -paise
    rupees, p = divmod(paise, 100)
    text = f"{sign}Rupees {indian_words(rupees)}"
    if p:
        text += f" and {indian_words(p)} Paise"
    return text + " Only"


def format_inr_plain(paise: int) -> str:
    sign = "-" if int(paise) < 0 else ""
    paise = abs(int(round(paise)))
    rupees, p = divmod(paise, 100)
    s = str(rupees)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.append(head[-2:])
            head = head[:-2]
        if head:
            groups.append(head)
        s = ",".join(reversed(groups)) + "," + tail
    return f"{sign}{s}.{p:02d}"


def money_mul(rate_paise: int, qty) -> int:
    from decimal import Decimal, ROUND_HALF_UP

    value = Decimal(int(rate_paise)) * Decimal(str(qty))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def tax_from_bps(taxable_paise: int, bps: int) -> int:
    from decimal import Decimal, ROUND_HALF_UP

    if int(bps) < 0:
        raise ApiError("Configured tax rate is invalid.")
    value = (Decimal(int(taxable_paise)) * Decimal(int(bps))) / Decimal(10000)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def age_from_dob(dob: str | None, on: datetime | None = None) -> dict | None:
    if not dob:
        return None
    try:
        born = datetime.fromisoformat(dob[:10]).date()
    except ValueError:
        return None
    today = (on or now()).date()
    years = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    return {"years": years, "text": f"{years}Y"}


def display_age(patient: dict, on: datetime | None = None) -> str:
    computed = age_from_dob(patient.get("dob"), on)
    if computed:
        return computed["text"]
    if patient.get("age_at_registration") is None or patient.get("age_at_registration") == "":
        return "—"
    unit = patient.get("age_unit") or "Y"
    est = " est." if patient.get("age_is_estimated") else ""
    return f"{patient['age_at_registration']}{unit}{est}"


def clean_text(value, limit: int = 2000) -> str:
    if value is None:
        return ""
    text = str(value).replace("\x00", "").strip()
    return text[:limit]


_SECRET_PATTERNS = (
    (re.compile(r"(?i)\b(password|api[_-]?key|authorization|x-api-key)\s*[:=]\s*\S+"), r"\1=[redacted]"),
    (re.compile(r"(?i)\bbearer\s+\S+"), "Bearer [redacted]"),
    (re.compile(r"(?i)\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?)://\S+"), "[redacted-url]"),
    (re.compile(r"(?i)\bsqlite:/*\S+"), "[redacted-url]"),
)


def redact(text: str, limit: int | None = None) -> str:
    """Remove credentials and database URLs from text that may be logged."""
    value = "" if text is None else str(text)
    for pattern, repl in _SECRET_PATTERNS:
        value = pattern.sub(repl, value)
    if limit is not None and len(value) > limit:
        value = value[:limit]
    return value


def require(cond: bool, message: str, status: int = 400, code: str = "invalid"):
    if not cond:
        raise ApiError(message, status, code)


def add_minutes(iso: str, minutes: int) -> str:
    dt = parse_iso(iso) or now()
    return (dt + timedelta(minutes=minutes)).isoformat(timespec="seconds")


def safe_filename(name: str) -> str:
    name = (name or "document").replace("\\", "/").split("/")[-1].replace("\x00", "")
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip("._ ")[:120]
    return name or "document"
