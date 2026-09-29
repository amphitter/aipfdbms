"""Structured hospital PDFs. Text is real PDF text, not a screenshot."""

from __future__ import annotations

from pathlib import Path

from .util import amount_in_words, format_inr_plain, now_iso


_RUPEE_JPEG: bytes | None = None


def rupee_jpeg() -> bytes | None:
    global _RUPEE_JPEG
    if _RUPEE_JPEG:
        return _RUPEE_JPEG
    try:
        import io

        from PIL import Image, ImageDraw, ImageFont

        image = Image.new("RGB", (72, 72), (255, 255, 255))
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 56)
        draw.text((6, 4), "₹", font=font, fill=(20, 16, 12))
        buf = io.BytesIO()
        image.save(buf, format="JPEG", quality=92)
        _RUPEE_JPEG = buf.getvalue()
        return _RUPEE_JPEG
    except Exception:
        return None


def _latin1(value) -> str:
    """Helvetica is Latin-1. An em dash would otherwise be drawn as a question mark."""
    text = str(value if value is not None else "")
    text = (
        text.replace("\u2014", "-")
        .replace("\u2013", "-")
        .replace("\u2026", "...")
        .replace("\u20b9", "Rs.")
        .replace("\u00a0", " ")
    )
    return "".join(ch if ord(ch) < 256 else "-" for ch in text)


def _esc(value) -> str:
    return (
        str(value if value is not None else "")
        .replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .replace("\r", " ")
        .replace("\n", " ")
    )


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 4 or data[0:2] != b"\xff\xd8":
        return None
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2):
            height = int.from_bytes(data[i + 5 : i + 7], "big")
            width = int.from_bytes(data[i + 7 : i + 9], "big")
            return width, height
        if marker == 0xD8:
            i += 2
            continue
        if marker == 0xD9 or marker == 0xDA:
            break
        if i + 4 > len(data):
            break
        length = int.from_bytes(data[i + 2 : i + 4], "big")
        if length < 2:
            break
        i += 2 + length
    return None


class PDF:
    def __init__(self, width: float = 595.28, height: float = 841.89):
        self.W = width
        self.H = height
        self.pages: list[list[str]] = []
        self.ops: list[str] = []
        self.images: list[dict] = []
        self.y = 32.0

    def new_page(self) -> None:
        if self.ops:
            self.pages.append(self.ops)
        self.ops = []
        self.y = 28.0

    def ensure(self, height: float) -> None:
        if self.y + height > self.H - 36:
            self.new_page()

    def text(self, x: float, y_top: float, value, size: float = 9, font: str = "F1", color: str = "0 0 0") -> None:
        y = self.H - y_top - size
        self.ops.append(
            f"{color} rg BT /{font} {size:.2f} Tf 1 0 0 1 {x:.2f} {y:.2f} Tm ({_esc(_latin1(value))}) Tj ET"
        )

    def text_right(self, right: float, y_top: float, value, size: float = 9, font: str = "F1") -> None:
        # Approximate width: Helvetica average 0.5em. Good enough for amounts.
        text = str(value)
        width = len(text) * size * 0.52
        self.text(right - width, y_top, text, size, font)

    def rect(self, x: float, y_top: float, w: float, h: float, stroke: str = "0 0 0", fill: str | None = None, sw: float = 0.6) -> None:
        y = self.H - y_top - h
        if fill:
            self.ops.append(f"{fill} rg {x:.2f} {y:.2f} {w:.2f} {h:.2f} re f")
        self.ops.append(f"{stroke} RG {sw:.2f} w {x:.2f} {y:.2f} {w:.2f} {h:.2f} re S")

    def line(self, x1: float, y1: float, x2: float, y2: float, sw: float = 0.4) -> None:
        self.ops.append(
            f"0 0 0 RG {sw:.2f} w {x1:.2f} {self.H - y1:.2f} m {x2:.2f} {self.H - y2:.2f} l S"
        )

    def image(self, name: str, x: float, y_top: float, w: float, h: float) -> None:
        y = self.H - y_top - h
        self.ops.append(f"q {w:.2f} 0 0 {h:.2f} {x:.2f} {y:.2f} cm /{name} Do Q")

    def add_jpeg(self, data: bytes, name: str = "Im1") -> str | None:
        size = _jpeg_size(data)
        if not size:
            return None
        self.images.append({"name": name, "data": data, "w": size[0], "h": size[1]})
        return name

    def finish(self) -> bytes:
        if self.ops:
            self.pages.append(self.ops)
            self.ops = []
        total = len(self.pages) or 1
        if not self.pages:
            self.pages = [[]]
        for i, page in enumerate(self.pages, start=1):
            label = f"Page {i} of {total}"
            y = 18
            page.append(
                f"0.25 0.22 0.18 rg BT /F1 7 Tf 1 0 0 1 {self.W - 28 - len(label) * 3.6:.2f} {y:.2f} Tm ({_esc(label)}) Tj ET"
            )
        return _build(self.pages, self.W, self.H, self.images)


def _build(pages: list[list[str]], width: float, height: float, images: list[dict]) -> bytes:
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    font1 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    font2 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")
    font3 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Times-Bold >>")
    image_ids = {}
    for image in images:
        data = image["data"]
        body = (
            f"<< /Type /XObject /Subtype /Image /Width {image['w']} /Height {image['h']} "
            f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length {len(data)} >>\nstream\n"
        ).encode("latin1") + data + b"\nendstream"
        image_ids[image["name"]] = add(body)

    content_ids = []
    for page in pages:
        stream = "\n".join(page).encode("latin1", errors="replace")
        content_ids.append(
            add(
                f"<< /Length {len(stream)} >>\nstream\n".encode("latin1")
                + stream
                + b"\nendstream"
            )
        )

    page_ids = []
    for cid in content_ids:
        xobjects = " ".join(f"/{name} {oid} 0 R" for name, oid in image_ids.items())
        xobj = f"/XObject << {xobjects} >>" if xobjects else ""
        page_ids.append(
            add(
                (
                    f"<< /Type /Page /Parent PAGES 0 R /MediaBox [0 0 {width:.2f} {height:.2f}] "
                    f"/Resources << /Font << /F1 {font1} 0 R /F2 {font2} 0 R /F3 {font3} 0 R >> {xobj} >> "
                    f"/Contents {cid} 0 R >>"
                ).encode("latin1")
            )
        )

    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    pages_id = add(f"<< /Type /Pages /Count {len(page_ids)} /Kids [{kids}] >>".encode("latin1"))
    # Fix parent references now that pages object id is known.
    for pid in page_ids:
        objects[pid - 1] = objects[pid - 1].replace(b"/Parent PAGES 0 R", f"/Parent {pages_id} 0 R".encode())
    catalog_id = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode("latin1"))

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{i} 0 obj\n".encode("latin1"))
        out.extend(obj)
        out.extend(b"\nendobj\n")
    xref = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode("latin1"))
    out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode("latin1"))
    out.extend(
        f"trailer << /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode(
            "latin1"
        )
    )
    return bytes(out)


def _wrap_words(value, limit: int) -> list[str]:
    words = str(value or "").split()
    if not words:
        return [""]
    lines = []
    current = ""
    for word in words:
        trial = word if not current else f"{current} {word}"
        if len(trial) <= limit:
            current = trial
            continue
        if current:
            lines.append(current)
        current = word if len(word) <= limit else word[:limit]
    if current:
        lines.append(current)
    return lines


def _pieces(value, size: int) -> list[str]:
    text = str(value or "")
    if len(text) <= size:
        return [text]
    return [text[i : i + size] for i in range(0, len(text), size)]


def _clip(value, limit: int) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


CATEGORY_ORDER = [
    "CONSULTATION",
    "HOSPITAL SERVICES",
    "PHARMACY",
    "LABORATORY",
    "IPD",
    "OT",
    "PROCEDURE",
    "OTHER",
    "ADJUSTMENT",
]


def render_lab_report(payload: dict) -> bytes:
    """Draw a report from values already stored. This does not price or interpret."""
    pdf = PDF()
    rupee = pdf.add_jpeg(rupee_jpeg() or b"", "ImRupee") if rupee_jpeg() else None

    def header() -> None:
        pdf.text(36, pdf.y, payload.get("hospital_name") or "Hospital", 13, "F2")
        pdf.y += 16
        if payload.get("hospital_address"):
            pdf.text(36, pdf.y, payload["hospital_address"], 8, "F1", "0.25 0.22 0.18")
            pdf.y += 12
        pdf.text(36, pdf.y, "Laboratory report", 11, "F2")
        pdf.text(360, pdf.y, payload.get("reported_at") or "", 8)
        pdf.y += 14
        pdf.line(36, pdf.y, 560, pdf.y, 0.6)
        pdf.y += 8
        pdf.text(36, pdf.y, f"Patient {payload.get('patient_id') or ''}  {payload.get('patient_name') or ''}", 9, "F2")
        pdf.y += 12
        pdf.text(36, pdf.y, f"Encounter {payload.get('encounter_id') or '—'}", 8)
        pdf.text(220, pdf.y, f"Admission {payload.get('admission_id') or '—'}", 8)
        pdf.text(400, pdf.y, f"Order {payload.get('order_id') or ''}", 8)
        pdf.y += 12
        pdf.text(36, pdf.y, f"Priority {payload.get('priority') or 'ROUTINE'}", 8)
        pdf.y += 8
        pdf.text(36, pdf.y, "An abnormal or critical flag is a range comparison, not a diagnosis.", 8, "F1", "0.35 0.2 0.1")
        pdf.y += 14

    header()
    for result in payload.get("results") or []:
        block = 78
        remarks = str(result.get("remarks") or "")
        lines = _pieces(remarks, 48) if remarks else []
        pdf.ensure(block + min(len(lines), 8) * 12)
        if pdf.y <= 40:
            header()
        top = pdf.y
        pdf.rect(36, top, 524, 16, "0.45 0.38 0.28", "0.96 0.94 0.90")
        pdf.text(42, top + 4, result.get("test_name") or "Test", 9, "F2")
        pdf.text(360, top + 4, result.get("accession_no") or "", 8)
        pdf.y = top + 20
        pdf.text(42, pdf.y, f"Result  {result.get('value') or ''}", 10, "F2")
        if result.get("unit"):
            pdf.text(280, pdf.y, result["unit"], 9)
        pdf.y += 14
        pdf.text(42, pdf.y, f"Reference  {result.get('reference_range') or 'Not configured'}", 8)
        pdf.y += 12
        flag = result.get("abnormal_flag") or "No range flag"
        critical = "Critical" if result.get("critical_flag") else "Not critical"
        pdf.text(42, pdf.y, f"Flag  {flag}  ·  {critical}", 8)
        pdf.y += 12
        pdf.text(42, pdf.y, f"Method  {result.get('methodology') or '—'}", 8)
        if result.get("price_pending"):
            pdf.text(360, pdf.y, "Price pending", 8)
        elif result.get("rate_paise") is not None:
            amount = format_inr_plain(int(result["rate_paise"]))
            if rupee:
                pdf.image(rupee, 400, pdf.y - 1, 9, 9)
                pdf.text(412, pdf.y, amount, 8)
            else:
                pdf.text(400, pdf.y, f"Rs {amount}", 8)
        pdf.y += 12
        for line in lines:
            pdf.ensure(12)
            if pdf.y <= 40:
                header()
            pdf.text(42, pdf.y, line, 8, "F1", "0.2 0.18 0.16")
            pdf.y += 12
        pdf.y += 8
    pdf.ensure(28)
    pdf.text(36, pdf.y, "Reprinting this report does not change the stored result.", 8, "F1", "0.25 0.22 0.18")
    return pdf.finish()


def render_invoice_pdf(payload: dict, slip: bool = False) -> bytes:
    """A4 invoice. A short bill stays on one page. A long bill repeats the header."""
    width, height = (420, 640) if slip else (595.28, 841.89)
    pdf = PDF(width, height)
    margin = 28 if not slip else 18
    right = width - margin
    hospital = payload.get("hospital") or {}
    invoice = payload.get("invoice") or {}
    logo = payload.get("logo_bytes")
    if logo:
        pdf.add_jpeg(logo, "Im1")
    rupee_name = pdf.add_jpeg(rupee_jpeg() or b"", "ImRupee") if rupee_jpeg() else None
    number = invoice.get("number") or ""
    generated = str(payload.get("generated_at") or "")[:16].replace("T", " ")
    bottom = 46

    def paint_page(continued: bool = False) -> None:
        if pdf.ops:
            pdf.line(margin, pdf.H - 36, right, pdf.H - 36, 0.3)
            pdf.text(margin, pdf.H - 30, _pieces(f"{number}  |  {hospital.get('name') or 'Hospital'}  |  Generated {generated}", 100)[0], 7, "F1", "0.3 0.26 0.2")
        pdf.new_page()
        pdf.rect(0, 0, pdf.W, pdf.H, "1 1 1", "1 1 1", 0)
        pdf.y = 24
        name = hospital.get("name") or "Hospital"
        if logo and pdf.images:
            pdf.image("Im1", margin, pdf.y, 28, 28)
            text_x = margin + 34
        else:
            text_x = margin
        pdf.text(text_x, pdf.y, name, 13 if not slip else 11, "F2")
        pdf.text_right(right, pdf.y, "TAX INVOICE" if not continued else "TAX INVOICE - CONTINUED", 9, "F2")
        pdf.y += 14
        address = _join_unique([
            hospital.get("address_line1"),
            hospital.get("address_line2"),
            hospital.get("city"),
            hospital.get("pin"),
        ])
        if address:
            pdf.text(text_x, pdf.y, _pieces(address, 78)[0], 8, "F1", "0.28 0.25 0.2")
            pdf.y += 11
        contact = "  |  ".join(
            part
            for part in [
                f"Tel {hospital['phone']}" if hospital.get("phone") else "",
                hospital.get("email") or "",
                f"Reg {hospital['registration_no']}" if hospital.get("registration_no") else "",
            ]
            if part
        )
        if contact:
            pdf.text(text_x, pdf.y, _pieces(contact, 90)[0], 8, "F1", "0.28 0.25 0.2")
            pdf.y += 11
        pdf.y += 2
        pdf.line(margin, pdf.y, right, pdf.y, 0.6)
        pdf.y += 8
        pdf.text(margin, pdf.y, number, 9, "F2")
        when = f"{(invoice.get('finalized_at') or invoice.get('created_at') or '')[:16].replace('T', ' ')}"
        pdf.text_right(right, pdf.y, when, 8)
        pdf.y += 12
        if rupee_name:
            pdf.image(rupee_name, margin, pdf.y, 9, 9)
            pdf.text(margin + 12, pdf.y, "Amounts in Indian Rupees", 8, "F2")
            pdf.y += 12

    def identity() -> None:
        fields = [
            field
            for field in (payload.get("fields") or [])
            if "hospital no" not in str(field.get("label") or "").lower()
            and str(field.get("value") or "").strip() not in {"", "-", "\u2014", "None"}
        ]
        cols = 2
        col_w = (right - margin) / cols
        for index, field in enumerate(fields):
            column = index % cols
            if column == 0 and pdf.y + 12 > pdf.H - bottom:
                paint_page(True)
            y = pdf.y
            x = margin + column * col_w
            label = str(field.get("label") or "")
            value = field.get("value") or "-"
            pdf.text(x, y, _pieces(f"{label}: {value}", 42)[0], 8)
            if column == cols - 1 or index == len(fields) - 1:
                pdf.y = y + 12
        pdf.y += 2
        pdf.line(margin, pdf.y, right, pdf.y, 0.3)
        pdf.y += 8

    def table_head() -> None:
        pdf.text(margin, pdf.y, "Description", 8, "F2")
        pdf.text(margin + 280, pdf.y, "Qty", 8, "F2")
        pdf.text_right(right - 70, pdf.y, "Rate", 8, "F2")
        pdf.text_right(right, pdf.y, "Amount", 8, "F2")
        pdf.y += 4
        pdf.line(margin, pdf.y, right, pdf.y, 0.4)
        pdf.y += 8

    def room(height: float) -> None:
        if pdf.y + height > pdf.H - bottom:
            paint_page(True)
            table_head()

    paint_page(False)
    identity()
    table_head()
    items = payload.get("items") or []
    totals_h = 118
    for item in items:
        parts = _wrap_words(item.get("description") or "Service", 48)
        block = 12 + 11 * max(0, len(parts) - 1)
        if pdf.y + block + totals_h > pdf.H - bottom:
            paint_page(True)
            table_head()
        rate = format_inr_plain(item.get("rate_paise") or 0)
        amount = format_inr_plain(item.get("amount_paise") or 0)
        qty = item.get("qty")
        qty_s = str(int(qty)) if float(qty or 0) == int(float(qty or 0)) else f"{float(qty or 0):g}"
        pdf.text(margin, pdf.y, parts[0], 8)
        pdf.text(margin + 280, pdf.y, qty_s, 8)
        pdf.text_right(right - 70, pdf.y, rate, 8)
        pdf.text_right(right, pdf.y, amount, 8)
        pdf.y += 11
        for extra in parts[1:]:
            if pdf.y + 12 > pdf.H - bottom:
                paint_page(True)
                table_head()
            pdf.text(margin + 8, pdf.y, extra, 7.5, "F1", "0.25 0.22 0.18")
            pdf.y += 10
        pdf.y += 2
    pdf.y += 4
    pdf.line(margin, pdf.y, right, pdf.y, 0.4)
    pdf.y += 8

    totals = [
        ("Gross", invoice.get("gross_paise") or 0),
        ("Discount", invoice.get("discount_paise") or 0),
        ("Tax", invoice.get("tax_paise") or 0),
        ("Net", invoice.get("net_paise") or 0),
        ("Paid", invoice.get("paid_paise") or 0),
        ("Due", invoice.get("due_paise") or 0),
    ]
    if pdf.y + 14 * len(totals) + 36 > pdf.H - bottom:
        paint_page(True)
    for label, amount in totals:
        font = "F2" if label in ("Net", "Due", "Paid") else "F1"
        pdf.text(right - 160, pdf.y, label, 8, font)
        if label == "Net" and rupee_name:
            pdf.image(rupee_name, right - 78, pdf.y - 1, 8, 8)
        pdf.text_right(right, pdf.y, format_inr_plain(amount), 8, font)
        pdf.y += 12
    words = amount_in_words(int(invoice.get("net_paise") or 0))
    pdf.y += 4
    for line in _pieces(f"Amount in words: {words}", 88):
        pdf.text(margin, pdf.y, line, 8, "F2")
        pdf.y += 11
    status = "VOID" if invoice.get("status") == "VOID" else (invoice.get("payment_status") or "DUE")
    pdf.text(margin, pdf.y, f"Payment status: {status}", 8, "F2")
    cashier = payload.get("cashier") or ""
    if cashier:
        pdf.text_right(right, pdf.y, f"Cashier: {cashier}", 8)
    pdf.y += 14
    payments = payload.get("payments") or []
    if payments:
        pdf.text(margin, pdf.y, "Payment history", 8, "F2")
        pdf.y += 11
        for pay in payments:
            if pdf.y + 12 > pdf.H - bottom:
                paint_page(True)
            line = "  ".join(
                part
                for part in [
                    str(pay.get("received_at") or "")[:16].replace("T", " "),
                    pay.get("kind") or "PAYMENT",
                    pay.get("mode") or "",
                    format_inr_plain(pay.get("amount_paise") or 0),
                    pay.get("reference") or "",
                ]
                if part
            )
            pdf.text(margin, pdf.y, _pieces(line, 96)[0], 7.5)
            pdf.y += 10
    pdf.line(margin, pdf.H - 36, right, pdf.H - 36, 0.3)
    pdf.text(
        margin,
        pdf.H - 30,
        _pieces(f"{number}  |  {hospital.get('name') or 'Hospital'}  |  Generated {generated}", 100)[0],
        7,
        "F1",
        "0.3 0.26 0.2",
    )
    return pdf.finish()


def render_discharge_summary(payload: dict) -> bytes:
    """Draw a discharge summary from values already stored. This does not reprice care."""
    pdf = PDF()
    pdf.rect(0, 0, pdf.W, pdf.H, "1 1 1", "1 1 1", 0)
    rupee = pdf.add_jpeg(rupee_jpeg() or b"", "ImRupee") if rupee_jpeg() else None
    pdf.text(36, pdf.y, payload.get("hospital_name") or "Hospital", 14, "F2")
    pdf.y += 16
    if payload.get("hospital_address"):
        pdf.text(36, pdf.y, payload["hospital_address"], 8, "F1", "0.25 0.22 0.18")
        pdf.y += 12
    pdf.text(36, pdf.y, "Discharge summary", 12, "F2")
    pdf.text(400, pdf.y, payload.get("discharged_at") or "", 8)
    pdf.y += 14
    pdf.line(36, pdf.y, 560, pdf.y, 0.6)
    pdf.y += 10
    pdf.text(36, pdf.y, f"Patient {payload.get('patient_id') or ''}  {payload.get('patient_name') or ''}", 10, "F2")
    pdf.y += 14
    pdf.text(36, pdf.y, f"Admission {payload.get('admission_id') or ''}", 9)
    pdf.text(280, pdf.y, f"Admitted {payload.get('admitted_at') or '—'}", 8)
    pdf.y += 12
    pdf.text(36, pdf.y, f"Condition {payload.get('condition') or '—'}", 9)
    pdf.text(280, pdf.y, f"Doctor {payload.get('doctor') or '—'}", 8)
    pdf.y += 16
    pdf.text(36, pdf.y, "Summary", 10, "F2")
    pdf.y += 14
    for piece in _pieces(payload.get("summary") or "", 48):
        pdf.ensure(14)
        if pdf.y < 48:
            pdf.rect(0, 0, pdf.W, pdf.H, "1 1 1", "1 1 1", 0)
        pdf.text(36, pdf.y, piece, 9)
        pdf.y += 12
    pdf.y += 8
    pdf.ensure(28)
    pdf.text(36, pdf.y, "Charges already posted. This page does not calculate a new total.", 8, "F1", "0.25 0.22 0.18")
    pdf.y += 14
    total = 0
    for charge in payload.get("charges") or []:
        pdf.ensure(16)
        amount = int(charge.get("amount_paise") or 0)
        total += amount
        pdf.text(36, pdf.y, _clip(charge.get("description") or "Charge", 70), 8)
        if rupee:
            pdf.image("ImRupee", 430, pdf.y - 1, 10, 10)
            pdf.text(444, pdf.y, format_inr_plain(amount), 8)
        else:
            pdf.text(420, pdf.y, format_inr_plain(amount), 8)
        pdf.y += 12
    pdf.ensure(28)
    pdf.y += 6
    pdf.text(36, pdf.y, "Amount in words", 8, "F2")
    pdf.y += 12
    pdf.text(36, pdf.y, amount_in_words(total), 8)
    return pdf.finish()


def _qty(value) -> str:
    if value in (None, ""):
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number == int(number):
        return str(int(number))
    return f"{number:g}"


def _join_unique(parts) -> str:
    seen = []
    for part in parts:
        text = str(part or "").strip()
        if text and text not in seen:
            seen.append(text)
    return ", ".join(seen)


def render_prescription_pdf(payload: dict) -> bytes:
    """One white prescription sheet. Page 2 is only the continuation, never a separate file."""
    pdf = PDF()
    margin, right = 36, 595.28 - 36
    hospital = payload.get("hospital") or {}
    patient = payload.get("patient") or {}
    rx = payload.get("prescription") or {}
    logo = payload.get("logo_bytes")
    if logo:
        pdf.add_jpeg(logo, "Im1")
    bottom = 58
    continued = {"value": False}

    def footer(hint: str = "") -> None:
        y = pdf.H - 48
        pdf.line(margin, y, right, y, 0.4)
        address = _join_unique([hospital.get("address_line1"), hospital.get("city"), hospital.get("pin"), hospital.get("phone")])
        pdf.text(margin, y + 5, _pieces(f"{hospital.get('name') or 'Hospital'}  |  {address}", 88)[0], 7, "F1", "0.3 0.26 0.2")
        stamp = "  |  ".join(
            part
            for part in [
                rx.get("id") or "",
                f"Patient {patient.get('id') or ''}",
                f"OPD {rx.get('encounter_id') or ''}",
                f"Generated {(payload.get('generated_at') or '')[:10]}",
            ]
            if part
        )
        pdf.text(margin, y + 15, stamp, 7, "F1", "0.3 0.26 0.2")
        if hint:
            pdf.text(right - 150, y + 15, hint, 7, "F1", "0.3 0.26 0.2")

    def header(continued_page: bool = False) -> None:
        pdf.new_page()
        pdf.rect(0, 0, pdf.W, pdf.H, "1 1 1", "1 1 1", 0)
        pdf.y = 28
        text_x = margin
        if logo and pdf.images and not continued_page:
            pdf.image("Im1", margin, pdf.y, 32, 32)
            text_x = margin + 40
        pdf.text(text_x, pdf.y, hospital.get("name") or "Hospital", 14, "F2")
        pdf.y += 16
        address = _join_unique([hospital.get("address_line1"), hospital.get("address_line2"), hospital.get("city"), hospital.get("pin")])
        if address and not continued_page:
            pdf.text(text_x, pdf.y, _pieces(address, 80)[0], 8, "F1", "0.28 0.25 0.2")
            pdf.y += 11
        contact = "  |  ".join(part for part in [hospital.get("phone"), hospital.get("email")] if part)
        if contact and not continued_page:
            pdf.text(text_x, pdf.y, contact, 8, "F1", "0.28 0.25 0.2")
            pdf.y += 12
        else:
            pdf.y += 4
        pdf.line(margin, pdf.y, right, pdf.y, 0.7)
        pdf.y += 10
        title = "Prescription - Continued. Print both sides." if continued_page else "Prescription"
        pdf.text(margin, pdf.y, title, 12, "F2")
        pdf.text_right(right, pdf.y, rx.get("id") or "", 9, "F2")
        pdf.y += 14
        pdf.line(margin, pdf.y, right, pdf.y, 0.3)
        pdf.y += 8
        if continued_page:
            pdf.text(margin, pdf.y, f"{patient.get('name') or '-'}   Patient ID {patient.get('id') or '-'}   OPD {rx.get('encounter_id') or '-'}", 8)
            pdf.y += 12
            pdf.line(margin, pdf.y, right, pdf.y, 0.3)
            pdf.y += 8

    def identity() -> None:
        facts = [
            ("Patient", patient.get("name") or "-"),
            ("Guardian", patient.get("guardian_name") or "-"),
            ("Age", payload.get("age") or "-"),
            ("Gender", patient.get("gender") or "-"),
            ("Phone", patient.get("primary_phone") or "-"),
            ("Patient ID", patient.get("id") or "-"),
            ("OPD / encounter", rx.get("encounter_id") or "-"),
            ("Doctor", payload.get("doctor") or "-"),
            ("Department", payload.get("department") or ""),
            ("Date", str(rx.get("finalized_at") or rx.get("created_at") or "")[:16].replace("T", " ") or "-"),
        ]
        facts = [pair for pair in facts if str(pair[1] or "").strip() not in {"", "-"}]
        for index in range(0, len(facts), 2):
            left = facts[index]
            pdf.text(margin, pdf.y, f"{left[0]}: {left[1]}", 9)
            if index + 1 < len(facts):
                right_fact = facts[index + 1]
                pdf.text(margin + 270, pdf.y, f"{right_fact[0]}: {right_fact[1]}", 9)
            pdf.y += 13
        pdf.y += 2
        pdf.line(margin, pdf.y, right, pdf.y, 0.4)
        pdf.y += 10

    def block_lines(item: dict, index: int) -> list[str]:
        title = " ".join(part for part in [item.get("medicine_name"), item.get("strength")] if part)
        lines = [f"{index}. {title or 'Medicine'}"]
        details = [
            ("Dosage", item.get("dose")),
            ("Frequency", item.get("frequency")),
            ("Duration", item.get("duration")),
            ("Quantity", " ".join(part for part in [_qty(item.get("quantity")), item.get("unit") or ""] if part).strip()),
            ("Route", item.get("route")),
            ("Instructions", " ".join(part for part in [item.get("food_instruction"), item.get("notes")] if part)),
        ]
        for label, value in details:
            if value:
                lines.append(f"    {label}: {value}")
        return lines

    def block_height(lines: list[str]) -> float:
        return 8 + sum(12 if not line.startswith("    ") else 11 for line in lines)

    header(False)
    identity()
    pdf.text(margin, pdf.y, "Rx", 12, "F2")
    pdf.y += 16
    for index, item in enumerate(payload.get("items") or [], start=1):
        lines = block_lines(item, index)
        height = block_height(lines)
        if pdf.y + height > pdf.H - bottom:
            footer()
            continued["value"] = True
            header(True)
        for line in lines:
            wrapped = _pieces(line, 88)
            pdf.text(margin, pdf.y, wrapped[0], 10 if not line.startswith("    ") else 9, "F2" if not line.startswith("    ") else "F1")
            pdf.y += 13 if not line.startswith("    ") else 12
            for extra in wrapped[1:]:
                pdf.text(margin + 16, pdf.y, extra, 9)
                pdf.y += 11
        pdf.y += 6
    advice = rx.get("notes") or payload.get("advice") or ""
    if advice:
        lines = _pieces(f"Advice: {advice}", 88)
        if pdf.y + 14 * len(lines) > pdf.H - bottom:
            footer()
            continued["value"] = True
            header(True)
        pdf.line(margin, pdf.y, right, pdf.y, 0.3)
        pdf.y += 8
        for line in lines:
            pdf.text(margin, pdf.y, line, 9)
            pdf.y += 12
    if pdf.y + 36 > pdf.H - bottom:
        footer()
        continued["value"] = True
        header(True)
    pdf.y += 16
    pdf.line(right - 180, pdf.y, right, pdf.y, 0.4)
    pdf.y += 6
    pdf.text(right - 180, pdf.y, payload.get("doctor") or "Prescriber", 9, "F2")
    footer()
    return pdf.finish()


def render_ot_report(payload: dict) -> bytes:
    """A4 operation report drawn only from values already stored."""
    pdf = PDF()
    pdf.rect(0, 0, pdf.W, pdf.H, "1 1 1", "1 1 1", 0)

    def ensure(height: float) -> None:
        if pdf.y + height > pdf.H - 36:
            pdf.new_page()
            pdf.rect(0, 0, pdf.W, pdf.H, "1 1 1", "1 1 1", 0)
            pdf.y = 36

    def block(title: str, body: str) -> None:
        ensure(28)
        pdf.text(36, pdf.y, title, 10, "F2")
        pdf.y += 14
        for piece in _pieces(body or "—", 64) or ["—"]:
            ensure(14)
            pdf.text(36, pdf.y, piece, 9)
            pdf.y += 12
        pdf.y += 6

    pdf.text(36, pdf.y, payload.get("hospital_name") or "Hospital", 14, "F2")
    pdf.y += 16
    if payload.get("hospital_address"):
        pdf.text(36, pdf.y, payload["hospital_address"], 8, "F1", "0.25 0.22 0.18")
        pdf.y += 12
    pdf.text(36, pdf.y, "Operation report", 12, "F2")
    pdf.text(400, pdf.y, payload.get("case_id") or "", 8)
    pdf.y += 14
    pdf.line(36, pdf.y, 560, pdf.y, 0.6)
    pdf.y += 12
    pdf.text(36, pdf.y, f"Patient {payload.get('patient_id') or ''}  {payload.get('patient_name') or ''}", 10, "F2")
    pdf.y += 14
    rows = [
        ("Procedure", payload.get("procedure_name") or "—"),
        ("Indication", payload.get("indication") or "—"),
        ("Theatre", payload.get("theatre") or "—"),
        ("Surgeon", payload.get("surgeon") or "—"),
        ("Scheduled", payload.get("scheduled_at") or "—"),
        ("Started", payload.get("started_at") or "—"),
        ("Completed", payload.get("completed_at") or "—"),
    ]
    for label, value in rows:
        ensure(14)
        pdf.text(36, pdf.y, label, 8, "F2")
        pdf.text(120, pdf.y, _clip(value, 80), 8)
        pdf.y += 12
    pdf.y += 6
    preop = (payload.get("preop") or [None])[-1] or {}
    block("Pre-operative record", " ".join(x for x in [
        f"Consent {preop.get('consent_status') or '—'}",
        f"Readiness {preop.get('readiness') or '—'}",
        preop.get("assessment") or "",
    ] if x))
    for index, note in enumerate(payload.get("intraop") or [], start=1):
        block(f"Intra-operative record {index}", " ".join(x for x in [note.get("notes"), note.get("findings"), note.get("complications")] if x))
    for index, note in enumerate(payload.get("postop") or [], start=1):
        block(f"Post-operative record {index}", " ".join(x for x in [note.get("notes"), note.get("instructions"), note.get("condition")] if x))
    team = ", ".join(f"{member.get('function_code') or 'staff'} {member.get('user_id') or ''}" for member in payload.get("team") or [] if not member.get("removed_at"))
    block("Team", team or "—")
    ensure(20)
    pdf.text(36, pdf.y, "Prepared from the stored operation record. This page does not calculate a charge.", 8, "F1", "0.25 0.22 0.18")
    return pdf.finish()


def load_logo(path: str | None) -> bytes | None:
    if not path:
        return None
    file = Path(path)
    if file.exists() and file.stat().st_size < 2_000_000:
        return file.read_bytes()
    return None
