from __future__ import annotations

from io import BytesIO
from typing import Iterable

import qrcode
from PIL import ImageDraw
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from app.models import Party, QrBillRequest, ReimbursementSlipRequest, XmlAttachmentRequest, is_qr_iban


def _qr_image(payload: str, *, swiss_cross: bool = False) -> ImageReader:
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4, box_size=8)
    qr.add_data(payload)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    if swiss_cross:
        draw = ImageDraw.Draw(image)
        size = image.size[0]
        emblem_size = round(size * 7 / 46)
        emblem_left = (size - emblem_size) // 2
        emblem_top = (size - emblem_size) // 2
        emblem_right = emblem_left + emblem_size
        emblem_bottom = emblem_top + emblem_size
        draw.rectangle((emblem_left, emblem_top, emblem_right, emblem_bottom), fill="black")

        arm = max(2, emblem_size // 6)
        inset = max(2, emblem_size // 4)
        mid_x = size // 2
        mid_y = size // 2
        draw.rectangle((mid_x - arm // 2, emblem_top + inset, mid_x + arm // 2, emblem_bottom - inset), fill="white")
        draw.rectangle((emblem_left + inset, mid_y - arm // 2, emblem_right - inset, mid_y + arm // 2), fill="white")

    output = BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return ImageReader(output)


def _party_lines(party: Party) -> list[str]:
    line_2 = f"{party.street} {party.house_number}".strip()
    return [party.name, line_2, f"{party.postal_code} {party.city}"]


def _group_from_right(value: str, group_size: int) -> str:
    groups: list[str] = []
    while value:
        groups.append(value[-group_size:])
        value = value[:-group_size]
    return " ".join(reversed(groups))


def _format_account(account: str) -> str:
    return " ".join(account[index : index + 4] for index in range(0, len(account), 4))


def _format_reference(reference: str) -> str:
    if not reference:
        return ""
    if reference.startswith("RF"):
        return " ".join(reference[index : index + 4] for index in range(0, len(reference), 4))
    return _group_from_right(reference, 5)


def _wrap_text(value: str, font_name: str, font_size: float, max_width: float) -> list[str]:
    lines: list[str] = []
    for paragraph in value.splitlines() or [""]:
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = words.pop(0)
        for word in words:
            candidate = f"{current} {word}"
            if stringWidth(candidate, font_name, font_size) <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def _draw_field(
    pdf: canvas.Canvas,
    x: float,
    y: float,
    label: str,
    lines: Iterable[str],
    *,
    max_width: float,
    value_font_size: float = 8,
    leading: float = 3.2 * mm,
) -> float:
    pdf.setFont("Helvetica-Bold", 6)
    pdf.drawString(x, y, label)
    current_y = y - 3 * mm
    pdf.setFont("Helvetica", value_font_size)
    for value in lines:
        for line in _wrap_text(str(value), "Helvetica", value_font_size, max_width):
            pdf.drawString(x, current_y, line)
            current_y -= leading
    return current_y - 1.5 * mm


def _draw_cut_mark(pdf: canvas.Canvas, x: float, y: float, *, vertical: bool = False) -> None:
    pdf.saveState()
    pdf.setLineWidth(0.45)
    pdf.circle(x, y, 0.8 * mm, stroke=1, fill=0)
    if vertical:
        pdf.line(x - 1.6 * mm, y + 2.8 * mm, x - 0.4 * mm, y + 0.6 * mm)
        pdf.line(x + 1.6 * mm, y + 2.8 * mm, x + 0.4 * mm, y + 0.6 * mm)
    else:
        pdf.line(x + 0.6 * mm, y + 0.4 * mm, x + 2.8 * mm, y + 1.6 * mm)
        pdf.line(x + 0.6 * mm, y - 0.4 * mm, x + 2.8 * mm, y - 1.6 * mm)
    pdf.restoreState()


def _address_fields(party: Party) -> list[str]:
    if party.house_number:
        return [
            "S",
            party.name,
            party.street,
            party.house_number,
            party.postal_code,
            party.city,
            party.country_code,
        ]
    return [
        "K",
        party.name,
        party.street,
        f"{party.postal_code} {party.city}",
        "",
        "",
        party.country_code,
    ]


def _text_block(pdf: canvas.Canvas, x: float, y: float, title: str, lines: Iterable[str]) -> float:
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(x, y, title)
    pdf.setFont("Helvetica", 10)
    current_y = y - 5 * mm
    for line in lines:
        pdf.drawString(x, current_y, str(line))
        current_y -= 4.5 * mm
    return current_y


def _wrap_preview_lines(value: str, width: int, max_lines: int) -> list[str]:
    wrapped: list[str] = []
    for raw_line in value.splitlines() or [""]:
        wrapped.extend(raw_line[index : index + width] for index in range(0, len(raw_line), width) or [0])
        if len(wrapped) >= max_lines:
            return wrapped[:max_lines]
    return wrapped[:max_lines]


def build_swiss_qr_payload(request: QrBillRequest) -> str:
    creditor = request.creditor
    debtor = request.debtor
    amount = f"{request.amount:.2f}" if request.amount is not None else ""
    if not request.reference:
        reference_type = "NON"
    elif is_qr_iban(request.account):
        reference_type = "QRR"
    else:
        reference_type = "SCOR"
    return "\n".join(
        [
            "SPC",
            "0200",
            "1",
            request.account,
            *_address_fields(creditor),
            "",
            "",
            "",
            "",
            "",
            "",
            amount,
            request.currency,
            *_address_fields(debtor),
            reference_type,
            request.reference or "",
            request.message,
            request.bill_information,
            "EPD",
        ]
    )


def create_qr_bill_pdf(request: QrBillRequest) -> bytes:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    _, height = A4
    section_height = 105 * mm
    receipt_width = 62 * mm
    receipt_x = 5 * mm
    payment_x = 67 * mm
    details_x = 118 * mm

    pdf.setTitle("Swiss QR bill")
    pdf.setStrokeColorRGB(0.35, 0.35, 0.35)
    pdf.setDash(1, 2)
    pdf.line(0, section_height, A4[0], section_height)
    pdf.line(receipt_width, 0, receipt_width, section_height)
    pdf.setDash()
    _draw_cut_mark(pdf, 4 * mm, section_height)
    _draw_cut_mark(pdf, receipt_width, section_height - 4 * mm, vertical=True)

    pdf.setFillColorRGB(0, 0, 0)
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(receipt_x, 98 * mm, "Receipt")
    pdf.drawString(payment_x, 98 * mm, "Payment part")

    account_lines = [_format_account(request.account), *_party_lines(request.creditor)]
    reference = _format_reference(request.reference)

    receipt_y = _draw_field(
        pdf,
        receipt_x,
        91 * mm,
        "Account / Payable to",
        account_lines,
        max_width=52 * mm,
        value_font_size=7,
        leading=3 * mm,
    )
    if reference:
        receipt_y = _draw_field(
            pdf,
            receipt_x,
            receipt_y,
            "Reference",
            [reference],
            max_width=52 * mm,
            value_font_size=7,
            leading=3 * mm,
        )
    _draw_field(
        pdf,
        receipt_x,
        receipt_y,
        "Payable by",
        _party_lines(request.debtor),
        max_width=52 * mm,
        value_font_size=7,
        leading=3 * mm,
    )

    pdf.setFont("Helvetica-Bold", 6)
    pdf.drawString(receipt_x, 36 * mm, "Currency")
    pdf.drawString(37 * mm, 36 * mm, "Amount")
    pdf.setFont("Helvetica", 8)
    pdf.drawString(receipt_x, 32.5 * mm, request.currency)
    if request.amount is not None:
        pdf.drawRightString(57 * mm, 32.5 * mm, f"{request.amount:.2f}")
    else:
        pdf.rect(36 * mm, 19 * mm, 21 * mm, 13 * mm, stroke=1, fill=0)
    pdf.setFont("Helvetica-Bold", 6)
    pdf.drawRightString(57 * mm, 21 * mm, "Acceptance point")

    qr_size = 46 * mm
    pdf.drawImage(
        _qr_image(build_swiss_qr_payload(request), swiss_cross=True),
        payment_x,
        42 * mm,
        width=qr_size,
        height=qr_size,
    )

    details_y = _draw_field(
        pdf,
        details_x,
        94 * mm,
        "Account / Payable to",
        account_lines,
        max_width=87 * mm,
        leading=3.2 * mm,
    )
    if reference:
        details_y = _draw_field(
            pdf,
            details_x,
            details_y,
            "Reference",
            [reference],
            max_width=87 * mm,
            leading=3.2 * mm,
        )

    additional_information = [value for value in (request.message, request.bill_information) if value]
    if additional_information:
        details_y = _draw_field(
            pdf,
            details_x,
            details_y,
            "Additional information",
            additional_information,
            max_width=87 * mm,
            leading=3.2 * mm,
        )
    _draw_field(
        pdf,
        details_x,
        details_y,
        "Payable by",
        _party_lines(request.debtor),
        max_width=87 * mm,
        leading=3.2 * mm,
    )

    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawString(payment_x, 36 * mm, "Currency")
    pdf.drawString(91 * mm, 36 * mm, "Amount")
    pdf.setFont("Helvetica", 10)
    pdf.drawString(payment_x, 31.5 * mm, request.currency)
    if request.amount is not None:
        pdf.drawRightString(113 * mm, 31.5 * mm, f"{request.amount:.2f}")
    else:
        pdf.rect(90 * mm, 16 * mm, 23 * mm, 15 * mm, stroke=1, fill=0)

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def create_reimbursement_slip_pdf(request: ReimbursementSlipRequest) -> bytes:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    pdf.setTitle("Rückforderungsbeleg")
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(20 * mm, height - 20 * mm, "Rückforderungsbeleg")
    pdf.setFont("Helvetica", 10)
    pdf.drawString(20 * mm, height - 28 * mm, "Human-readable reimbursement slip for Tarif 595 invoices.")

    y = height - 45 * mm
    fields = [
        ("Leistungserbringer", request.provider_name),
        ("Versicherung", request.insurer_name),
        ("Versicherte Person", request.insured_person),
        ("Rechnungsnummer", request.invoice_number),
        ("Behandlungsperiode", request.treatment_period),
        ("Betrag", f"{request.amount:.2f} {request.currency}"),
        ("Notizen", request.notes or "-"),
    ]

    for label, value in fields:
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(20 * mm, y, label)
        pdf.setFont("Helvetica", 10)
        text = pdf.beginText(70 * mm, y)
        for line in str(value).splitlines() or ["-"]:
            text.textLine(line)
        pdf.drawText(text)
        y -= max(8 * mm, (len(str(value).splitlines()) + 1) * 5 * mm)

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def create_xml_attachment_pdf(request: XmlAttachmentRequest) -> bytes:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    pdf.setTitle(request.title)
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(20 * mm, height - 20 * mm, request.title)
    pdf.setFont("Helvetica", 10)
    pdf.drawString(20 * mm, height - 28 * mm, f"Embedded XML filename: {request.filename}")

    pdf.drawImage(_qr_image(request.xml_content), 20 * mm, height - 105 * mm, width=65 * mm, height=65 * mm)

    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(100 * mm, height - 45 * mm, "XML preview")
    pdf.setFont("Helvetica", 8)
    preview = request.xml_content[:1200]
    text = pdf.beginText(100 * mm, height - 52 * mm)
    for raw_line in _wrap_preview_lines(preview, width=55, max_lines=35):
        text.textLine(raw_line)
    if len(request.xml_content) > len(preview):
        text.textLine("...")
    pdf.drawText(text)

    pdf.showPage()
    pdf.save()
    writer = PdfWriter()
    reader = PdfReader(BytesIO(buffer.getvalue()))
    for page in reader.pages:
        writer.add_page(page)
    writer.add_attachment(request.filename, request.xml_content.encode("utf-8"))
    output = BytesIO()
    writer.write(output)
    return output.getvalue()
