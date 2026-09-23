from __future__ import annotations

import base64
import zlib
from collections.abc import Iterable
from datetime import date, datetime, time
from io import BytesIO
from xml.etree import ElementTree

import qrcode
from PIL import ImageDraw
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from app.invoice_xml import create_tarif595_xml
from app.models import (
    Party,
    QrBillRequest,
    ReimbursementSlipRequest,
    Tarif595Request,
    XmlAttachmentRequest,
    is_qr_iban,
)


def _qr_image(
    payload: str,
    *,
    swiss_cross: bool = False,
    error_correction: int = qrcode.constants.ERROR_CORRECT_M,
    version: int | None = None,
) -> ImageReader:
    qr = qrcode.QRCode(
        version=version,
        error_correction=error_correction,
        border=4,
        box_size=8,
    )
    qr.add_data(payload, optimize=0)
    qr.make(fit=version is None)
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


def _draw_invoice(pdf: canvas.Canvas, request: QrBillRequest, height: float) -> None:
    left = 20 * mm
    right = 190 * mm
    content_width = right - left
    invoice_date = request.invoice_date or date.today()
    invoice_number = request.invoice_number or request.reference or "Invoice"
    description = request.service_description or request.message or "Service"
    unit_price = request.service_unit_price
    if unit_price is None and request.amount is not None:
        unit_price = request.amount / request.service_quantity

    pdf.setFillColorRGB(0, 0, 0)
    pdf.setFont("Helvetica-Bold", 15)
    pdf.drawString(left, height - 20 * mm, request.creditor.name)
    pdf.setFont("Helvetica", 9)
    company_y = height - 26 * mm
    for line in (
        f"{request.creditor.street} {request.creditor.house_number}".strip(),
        f"{request.creditor.postal_code} {request.creditor.city}",
        request.creditor.country_code,
    ):
        pdf.drawString(left, company_y, line)
        company_y -= 4.5 * mm

    pdf.setFont("Helvetica-Bold", 24)
    pdf.drawRightString(right, height - 20 * mm, "INVOICE")
    pdf.setFont("Helvetica", 9)
    pdf.drawRightString(right, height - 28 * mm, f"Invoice no. {invoice_number}")
    pdf.drawRightString(right, height - 33 * mm, f"Date {invoice_date.strftime('%d.%m.%Y')}")

    address_y = height - 60 * mm
    pdf.setFont("Helvetica-Bold", 8)
    pdf.setFillColorRGB(0.35, 0.39, 0.44)
    pdf.drawString(left, address_y, "BILL TO")
    pdf.setFillColorRGB(0, 0, 0)
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(left, address_y - 6 * mm, request.debtor.name)
    pdf.setFont("Helvetica", 9)
    client_y = address_y - 11 * mm
    for line in (
        f"{request.debtor.street} {request.debtor.house_number}".strip(),
        f"{request.debtor.postal_code} {request.debtor.city}",
        request.debtor.country_code,
    ):
        pdf.drawString(left, client_y, line)
        client_y -= 4.5 * mm

    table_top = height - 100 * mm
    row_height = 9 * mm
    columns = [left, 105 * mm, 140 * mm, 160 * mm, right]
    pdf.setFillColorRGB(0.94, 0.95, 0.96)
    pdf.rect(left, table_top - row_height, content_width, row_height, stroke=0, fill=1)
    pdf.setFillColorRGB(0, 0, 0)
    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawString(columns[0] + 2 * mm, table_top - 5.8 * mm, "DESCRIPTION")
    pdf.drawString(columns[1] + 2 * mm, table_top - 5.8 * mm, "PERIOD")
    pdf.drawRightString(columns[3] - 2 * mm, table_top - 5.8 * mm, "QTY")
    pdf.drawRightString(columns[4] - 24 * mm, table_top - 5.8 * mm, "UNIT PRICE")
    pdf.drawRightString(columns[4] - 2 * mm, table_top - 5.8 * mm, "AMOUNT")

    row_y = table_top - row_height
    pdf.setStrokeColorRGB(0.82, 0.85, 0.88)
    pdf.line(left, row_y - row_height, right, row_y - row_height)
    pdf.setFont("Helvetica", 9)
    description_lines = _wrap_text(description, "Helvetica", 9, 80 * mm)
    pdf.drawString(columns[0] + 2 * mm, row_y - 5.8 * mm, description_lines[0])
    period = ""
    if request.service_date_begin and request.service_date_end:
        period = f"{request.service_date_begin.strftime('%d.%m.%Y')} - {request.service_date_end.strftime('%d.%m.%Y')}"
    pdf.drawString(columns[1] + 2 * mm, row_y - 5.8 * mm, period)
    pdf.drawRightString(columns[3] - 2 * mm, row_y - 5.8 * mm, f"{request.service_quantity:g}")
    if unit_price is not None:
        pdf.drawRightString(columns[4] - 24 * mm, row_y - 5.8 * mm, f"{unit_price:.2f}")
    if request.amount is not None:
        pdf.drawRightString(columns[4] - 2 * mm, row_y - 5.8 * mm, f"{request.amount:.2f}")

    total_y = row_y - 19 * mm
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawRightString(right - 35 * mm, total_y, "Total")
    total = f"{request.currency} {request.amount:.2f}" if request.amount is not None else "Open amount"
    pdf.drawRightString(right, total_y, total)
    pdf.setLineWidth(1)
    pdf.line(right - 76 * mm, total_y - 3 * mm, right, total_y - 3 * mm)

    if request.message:
        pdf.setFont("Helvetica", 8)
        pdf.setFillColorRGB(0.35, 0.39, 0.44)
        pdf.drawString(left, total_y, request.message)


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
    _draw_invoice(pdf, request, height)
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
    chunks = [request.xml_content[index : index + 1800] for index in range(0, len(request.xml_content), 1800)]
    for page_start in range(0, len(chunks), 4):
        pdf.setFont("Helvetica-Bold", 18)
        pdf.drawString(20 * mm, height - 20 * mm, request.title)
        pdf.setFont("Helvetica", 10)
        pdf.drawString(20 * mm, height - 28 * mm, f"Embedded XML filename: {request.filename}")
        pdf.drawString(
            20 * mm, height - 34 * mm, "Scan the QR codes in numerical order or extract the embedded XML file."
        )

        for position, chunk in enumerate(chunks[page_start : page_start + 4]):
            chunk_number = page_start + position + 1
            payload = f"TARIF595:{chunk_number}/{len(chunks)}:{chunk}"
            column = position % 2
            row = position // 2
            x = (20 + column * 95) * mm
            y = height - (120 + row * 120) * mm
            pdf.drawImage(
                _qr_image(payload, error_correction=qrcode.constants.ERROR_CORRECT_L),
                x,
                y,
                width=75 * mm,
                height=75 * mm,
            )
            pdf.setFont("Helvetica-Bold", 9)
            pdf.drawCentredString(x + 37.5 * mm, y - 5 * mm, f"XML part {chunk_number} of {len(chunks)}")
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


def create_tarif595_human_pdf(request: Tarif595Request) -> bytes:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    left = 10 * mm
    right = width - 10 * mm
    label_x = left + 18 * mm
    value_x = left + 45 * mm
    line_height = 4.2 * mm

    def date_text(value: date) -> str:
        return value.strftime("%d.%m.%Y")

    def row(
        y: float,
        label: str,
        value: str,
        *,
        section: str = "",
        second_label: str = "",
        second_value: str = "",
    ) -> float:
        pdf.setFont("Helvetica-Bold", 6.5)
        if section:
            section_lines = {
                "Rechnungssteller": ("Rechnungs-", "steller"),
                "Leistungserbringer": ("Leistungs-", "erbringer"),
            }.get(section, (section,))
            for index, section_line in enumerate(section_lines):
                pdf.drawString(left, y - index * 3 * mm, section_line)
        pdf.setFont("Helvetica", 6.5)
        pdf.drawString(label_x, y, label)
        pdf.setFont("Helvetica-Bold", 7)
        pdf.drawString(value_x, y, value)
        if second_label:
            pdf.setFont("Helvetica", 6.5)
            pdf.drawString(116 * mm, y, second_label)
            pdf.setFont("Helvetica-Bold", 7)
            pdf.drawString(148 * mm, y, second_value)
        return y - line_height

    pdf.setTitle("Rückforderungsbeleg")
    pdf.setFillColorRGB(0, 0, 0)
    pdf.setStrokeColorRGB(0, 0, 0)
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(left, height - 12 * mm, "Rückforderungsbeleg")
    pdf.setFont("Helvetica", 7)
    pdf.drawRightString(right, height - 10 * mm, "Release 5.0/General/de")
    pdf.drawRightString(right, height - 15 * mm, "Der Versicherung zustellen")
    pdf.drawImage(
        _qr_image(f"{request.invoice_number}|{request.provider_gln}|{request.service.amount:.2f}"),
        right - 12 * mm,
        height - 28 * mm,
        width=10 * mm,
        height=10 * mm,
    )

    y = height - 31 * mm
    pdf.setLineWidth(0.45)
    pdf.rect(left, y - 14 * mm, right - left, 14 * mm, stroke=1, fill=0)
    y = row(
        y - 3.7 * mm,
        "Identifikation",
        f"{int(datetime.combine(request.invoice_date, time.min).timestamp())} / "
        f"{date_text(request.invoice_date)} / {request.invoice_number}",
        section="Dokument",
        second_label="Seite",
        second_value="1",
    )
    y = row(
        y,
        "GLN-Nr.(B)",
        f"{request.provider_gln}  {request.qr_bill.creditor.name}",
        section="Rechnungssteller",
    )
    y = row(
        y,
        "ZSR-Nr.(B)",
        request.provider_zsr or "",
    )

    y -= 2 * mm
    patient_top = y + 2 * mm
    y = row(y, "Name", request.patient.family_name, section="Patient")
    y = row(y, "Vorname", request.patient.given_name)
    y = row(y, "Strasse", f"{request.patient.street} {request.patient.house_number}".strip())
    y = row(y, "PLZ", request.patient.postal_code)
    y = row(y, "Ort", request.patient.city)
    y = row(y, "Geburtsdatum", date_text(request.patient.birthdate))
    gender_text = "Herr / M" if request.patient.gender == "male" else "Frau / F"
    y = row(y, "Geschlecht", gender_text)
    y = row(y, "Falldatum", date_text(request.service.date_end))
    y = row(y, "Fall-Nr.", "")
    y = row(y, "AHV-Nr.", request.patient.ssn)
    y = row(y, "VEKA-Nr.", "")
    y = row(y, "Versicherten-Nr.", "")
    y = row(y, "Kanton", request.canton)
    y = row(y, "Kopie", "nein")
    y = row(
        y,
        "Vergütungsart",
        "TG",
        second_label="Rechnungs-Datum/-Nr.",
        second_value=f"{date_text(request.invoice_date)} / {request.invoice_number}",
    )
    y = row(y, "Gesetz", "VVG")
    y = row(
        y,
        "Behandlung",
        f"{date_text(request.service.date_begin)} - {date_text(request.service.date_end)}",
    )
    y = row(y, "Behandlungsart", "ambulant")
    y = row(y, "Behandlungsgrund", "Prävention")
    y = row(y, "Rolle/Ort", f"Andere · Betrieb · {request.qr_bill.creditor.name}")

    address_x = 116 * mm
    address_y = patient_top - 20 * mm
    pdf.setFont("Helvetica", 7.5)
    for line in (
        f"{request.patient.given_name} {request.patient.family_name}",
        f"{request.patient.street} {request.patient.house_number}".strip(),
        f"{request.patient.postal_code} {request.patient.city}",
    ):
        pdf.drawString(address_x, address_y, line)
        address_y -= 4.3 * mm

    provider_top = y + 1 * mm
    pdf.line(left, provider_top, right, provider_top)
    y = row(
        y - 2.5 * mm,
        "GLN-Nr.(P)",
        f"{request.provider_gln}  {request.qr_bill.creditor.name}",
        section="Leistungserbringer",
    )
    y = row(
        y,
        "GLN-Nr.(L)",
        f"{request.provider_location_gln}  "
        f"{request.qr_bill.creditor.street} {request.qr_bill.creditor.house_number} · "
        f"{request.qr_bill.creditor.postal_code} {request.qr_bill.creditor.city}",
    )
    y = row(y, "ZSR-Nr.(P)", request.provider_zsr or "")
    pdf.line(left, y + 1.5 * mm, right, y + 1.5 * mm)
    y = row(y - 1.5 * mm, "", "", section="Diagnose")

    notes_top = y + 1.5 * mm
    notes_height = 15 * mm
    pdf.rect(left, notes_top - notes_height, right - left, notes_height, stroke=1, fill=0)
    pdf.setFont("Helvetica-Bold", 6.5)
    pdf.drawString(left + 1 * mm, notes_top - 3.5 * mm, "Bemerkung")
    pdf.setFont("Helvetica", 6.5)
    note_lines = _wrap_text(request.notes or "-", "Helvetica", 6.5, right - value_x - 2 * mm)
    note_y = notes_top - 3.5 * mm
    for line in note_lines[:3]:
        pdf.drawString(value_x, note_y, line)
        note_y -= 3.5 * mm
    y = notes_top - notes_height - 5 * mm

    pdf.setFont("Helvetica", 6.5)
    pdf.drawString(left, y, "Partner")
    pdf.drawString(value_x, y, "GLN-/ZSR-/Sektion-Nr.")
    pdf.drawString(100 * mm, y, "Adresse")
    y -= 3.5 * mm
    pdf.setFont("Helvetica-Bold", 6.5)
    pdf.drawString(left, y, "1 - Versicherung")
    pdf.setFont("Helvetica", 6.5)
    pdf.drawString(value_x, y, request.insurer_gln)
    pdf.drawString(
        100 * mm,
        y,
        f"{request.insurer.name} · {request.insurer.street} {request.insurer.house_number} · "
        f"{request.insurer.postal_code} {request.insurer.city}",
    )
    y -= 8 * mm

    column_x = {
        "date": left,
        "tariff": left + 17 * mm,
        "code": left + 31 * mm,
        "quantity": left + 105 * mm,
        "price": left + 129 * mm,
        "vat": left + 151 * mm,
        "amount": right,
    }
    pdf.line(left, y + 2 * mm, right, y + 2 * mm)
    pdf.setFont("Helvetica", 6.5)
    pdf.drawString(column_x["date"], y, "Datum")
    pdf.drawString(column_x["tariff"], y, "Tarif")
    pdf.drawString(column_x["code"], y, "Tarifziffer / Leistung")
    pdf.drawRightString(column_x["quantity"], y, "Anzahl")
    pdf.drawRightString(column_x["price"], y, "Preis")
    pdf.drawRightString(column_x["vat"], y, "MWSt.")
    pdf.drawRightString(column_x["amount"], y, "Betrag")
    y -= 4.5 * mm
    pdf.setFont("Helvetica", 7)
    pdf.drawString(column_x["date"], y, date_text(request.service.date_begin))
    pdf.drawString(column_x["tariff"], y, "595")
    pdf.drawString(column_x["code"], y, request.service.code)
    pdf.drawRightString(column_x["quantity"], y, f"{request.service.quantity:g}")
    pdf.drawRightString(column_x["price"], y, f"{request.service.unit_price:.2f}")
    pdf.drawRightString(column_x["vat"], y, f"{request.service.vat_rate:.2f}")
    pdf.drawRightString(column_x["amount"], y, f"{request.service.amount:.2f}")
    y -= 4 * mm
    pdf.setFont("Helvetica-Bold", 6.5)
    for line in _wrap_text(request.service.name, "Helvetica-Bold", 6.5, 105 * mm)[:2]:
        pdf.drawString(column_x["code"], y, line)
        y -= 3.5 * mm

    total_y = 22 * mm
    pdf.line(130 * mm, total_y + 8 * mm, right, total_y + 8 * mm)
    pdf.setFont("Helvetica", 6.5)
    pdf.drawString(130 * mm, total_y + 3 * mm, "Code")
    pdf.drawString(145 * mm, total_y + 3 * mm, "Satz")
    pdf.drawString(160 * mm, total_y + 3 * mm, "Betrag")
    pdf.drawString(179 * mm, total_y + 3 * mm, "MWSt.")
    pdf.drawString(130 * mm, total_y - 1 * mm, "0")
    pdf.drawString(145 * mm, total_y - 1 * mm, f"{request.service.vat_rate:.2f}")
    pdf.drawString(160 * mm, total_y - 1 * mm, f"{request.service.amount:.2f}")
    pdf.drawString(179 * mm, total_y - 1 * mm, "0.00")
    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawRightString(right - 35 * mm, total_y - 8 * mm, "Gesamtbetrag:")
    pdf.drawRightString(right, total_y - 8 * mm, f"{request.service.amount:.2f}")
    pdf.drawRightString(right - 35 * mm, total_y - 14 * mm, "Rechnungsbetrag:")
    pdf.drawRightString(right, total_y - 14 * mm, f"{request.service.amount:.2f}")
    pdf.setFont("Helvetica", 6.5)
    pdf.drawString(130 * mm, total_y - 8 * mm, "Währung: CHF")

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def build_annex_qr_payloads(xml_content: bytes) -> list[str]:
    compressor = zlib.compressobj(level=9, wbits=-15)
    compressed = compressor.compress(xml_content) + compressor.flush()
    encoded = base64.b64encode(compressed).decode("ascii")
    chunk_size = 1262
    return [encoded[index : index + chunk_size].ljust(chunk_size) for index in range(0, len(encoded), chunk_size)]


def _xml_filename(invoice_number: str) -> str:
    stem = "".join(character if character.isalnum() or character in "._-" else "_" for character in invoice_number)
    return f"{stem.strip('._') or 'invoice'}.xml"


def create_tarif595_machine_pdf(
    request: Tarif595Request,
    xml_content: bytes | None = None,
) -> bytes:
    content = xml_content or create_tarif595_xml(request)
    payloads = build_annex_qr_payloads(content)
    xml_root = ElementTree.fromstring(content)
    invoice = xml_root.find(f".//{{{xml_root.tag.split('}')[0][1:]}}}invoice")
    guid = xml_root.attrib["guid"]
    timestamp = invoice.attrib["request_timestamp"] if invoice is not None else ""
    generated_at = f"{request.invoice_date.strftime('%d.%m.%Y')} 00:00:00"

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    left = 15 * mm
    right = width - 15 * mm
    qr_size = 53 * mm
    x_positions = [15 * mm, 78.5 * mm, 142 * mm]
    y_positions = [height - 118 * mm, height - 188 * mm]

    for page_start in range(0, len(payloads), 6):
        page_number = page_start // 6 + 1
        pdf.setFillColorRGB(0, 0, 0)
        pdf.setStrokeColorRGB(0, 0, 0)
        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(left, height - 12 * mm, "Rückforderungsbeleg QR-Code Blatt")
        pdf.setFont("Helvetica", 7)
        pdf.drawRightString(right - 14 * mm, height - 10 * mm, "Release 5.0/Annex/de")
        pdf.drawRightString(right - 14 * mm, height - 15 * mm, "Der Versicherung zustellen")
        pdf.drawImage(
            _qr_image(f"{timestamp}|{request.invoice_number}|{guid}"),
            right - 10 * mm,
            height - 22 * mm,
            width=10 * mm,
            height=10 * mm,
        )

        info_y = height - 29 * mm
        pdf.setFont("Helvetica", 7)
        pdf.drawString(left, info_y, "Identifikation:")
        pdf.setFont("Helvetica-Bold", 7)
        pdf.drawString(left + 19 * mm, info_y, f"{timestamp} / {generated_at} / {guid}")
        patient_text = (
            f"{'Herr' if request.patient.gender == 'male' else 'Frau'} "
            f"{request.patient.given_name} {request.patient.family_name} · "
            f"{request.patient.street} {request.patient.house_number} · "
            f"{request.patient.postal_code} {request.patient.city} · "
            f"Geburtsdatum: {request.patient.birthdate.strftime('%d.%m.%Y')} · "
            f"Geschlecht: {'Herr / M' if request.patient.gender == 'male' else 'Frau / F'}"
        )
        pdf.setFont("Helvetica", 7)
        pdf.drawString(left, info_y - 5 * mm, "PatientIn:")
        pdf.setFont("Helvetica-Bold", 7)
        pdf.drawString(left + 19 * mm, info_y - 5 * mm, patient_text)
        pdf.setLineWidth(0.45)
        pdf.line(left, info_y - 7 * mm, right, info_y - 7 * mm)

        for position, payload in enumerate(payloads[page_start : page_start + 6]):
            code_number = page_start + position + 1
            column = position % 3
            row = position // 3
            x = x_positions[column]
            y = y_positions[row]
            pdf.drawImage(
                _qr_image(
                    payload,
                    error_correction=qrcode.constants.ERROR_CORRECT_M,
                    version=29,
                ),
                x,
                y,
                width=qr_size,
                height=qr_size,
            )
            pdf.setFont("Helvetica-Bold", 7)
            pdf.drawCentredString(x + qr_size / 2, y - 5 * mm, f"QR-Code {code_number}")

        footer_y = 11 * mm
        pdf.line(left, footer_y + 3 * mm, right, footer_y + 3 * mm)
        pdf.setFont("Helvetica", 7)
        pdf.drawString(
            left,
            footer_y,
            f"Rückforderungsbeleg QR-Code Blatt, generiert am {generated_at}",
        )
        pdf.drawRightString(right, footer_y, f"Seite {page_number}")
        pdf.showPage()

    pdf.save()
    writer = PdfWriter()
    writer.append(BytesIO(buffer.getvalue()))
    writer.add_attachment(_xml_filename(request.invoice_number), content)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def create_tarif595_combined_pdf(request: Tarif595Request) -> bytes:
    xml_content = create_tarif595_xml(request)
    writer = PdfWriter()
    for content in (
        create_qr_bill_pdf(request.qr_bill),
        create_tarif595_human_pdf(request),
        create_tarif595_machine_pdf(request, xml_content),
    ):
        writer.append(BytesIO(content))

    writer.add_attachment(_xml_filename(request.invoice_number), xml_content)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()
