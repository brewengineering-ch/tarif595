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
from pystrich.datamatrix import DataMatrixData, DataMatrixEncoder
from pystrich.datamatrix.placement import DataMatrixPlacer
from pystrich.datamatrix.textencoder import TextEncoder, _SQUARE_SPECS

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


class _PageControlTextEncoder(TextEncoder):
    def _select_spec(self, unpadded_len: int, symbol_shape: str):
        selected = super()._select_spec(unpadded_len, symbol_shape)
        required = next(
            spec
            for spec in _SQUARE_SPECS
            if (spec.region_cols + 2) * spec.h_regions == 24
        )
        return required if selected.data_words < required.data_words else selected


class _PageControlDataMatrix(DataMatrixEncoder):
    def __init__(self, payload: str) -> None:
        encoder = _PageControlTextEncoder()
        codewords = encoder.encode(
            DataMatrixData(payload, encoding="ascii"),
            symbol_shape="square",
        )
        self.width = 0
        self.height = 0
        self.regions = (encoder.spec.h_regions, encoder.spec.v_regions)
        self.quiet_zone = 0
        self.matrix = [[None] * encoder.mapping_cols for _ in range(encoder.mapping_rows)]
        DataMatrixPlacer().place(codewords, self.matrix)


def build_page_control_payload(request: ReimbursementSlipRequest, page_number: int) -> str:
    return f"FD50{request.document_guid}{request.language}{request.tiers}GR{page_number:02d}"


def _page_control_datamatrix(payload: str):
    image = _PageControlDataMatrix(payload).get_pilimage(cellsize=10)
    if image.size != (240, 240):
        raise ValueError("Page control Data Matrix must contain exactly 24x24 modules.")
    return image


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
    margin = 12 * mm
    content_width = width - 2 * margin
    label_width = 42 * mm
    green = (0.9, 1, 0.9)

    def draw_row(y: float, label: str, value: str, *, row_height: float = 8 * mm) -> float:
        pdf.setFillColorRGB(*green)
        pdf.rect(margin, y - row_height, label_width, row_height, stroke=0, fill=1)
        pdf.setFillColorRGB(1, 1, 1)
        pdf.rect(margin + label_width, y - row_height, content_width - label_width, row_height, stroke=0, fill=1)
        pdf.setStrokeColorRGB(0, 0, 0)
        pdf.rect(margin, y - row_height, content_width, row_height, stroke=1, fill=0)
        pdf.line(margin + label_width, y - row_height, margin + label_width, y)
        pdf.setFillColorRGB(0, 0, 0)
        pdf.setFont("Helvetica-Bold", 7)
        pdf.drawString(margin + 1.5 * mm, y - 3.3 * mm, label)
        pdf.setFont("Helvetica", 9)
        value_lines = _wrap_text(value or "-", "Helvetica", 9, content_width - label_width - 4 * mm)
        text = pdf.beginText(margin + label_width + 2 * mm, y - 3.5 * mm)
        text.setLeading(3.6 * mm)
        for line in value_lines[:2]:
            text.textLine(line)
        pdf.drawText(text)
        return y - row_height

    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(margin, height - 18 * mm, "Rückforderungsbeleg")
    pdf.setFont("Helvetica", 7)
    barcode_size = 9 * mm
    barcode_x = width - margin - barcode_size
    barcode_y = height - 23 * mm
    header_right = barcode_x - 4 * mm
    pdf.drawRightString(header_right, height - 16 * mm, f"Release 5.0 / General / {request.language}")
    pdf.line(width - 65 * mm, height - 18 * mm, header_right, height - 18 * mm)
    pdf.drawRightString(header_right, height - 22 * mm, "Der Versicherung zustellen")
    pdf.drawImage(
        ImageReader(_page_control_datamatrix(build_page_control_payload(request, 1))),
        barcode_x,
        barcode_y,
        width=barcode_size,
        height=barcode_size,
        mask="auto",
    )

    y = height - 30 * mm
    y = draw_row(y, "Dokument", f"Rechnungsnummer {request.invoice_number}")
    y = draw_row(y, "Rechnungssteller", request.provider_name)
    y = draw_row(y, "Patient", request.insured_person)

    y -= 5 * mm
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(margin, y, "Rechnungsangaben")
    y -= 2 * mm
    y = draw_row(y, "Versicherung", request.insurer_name)
    y = draw_row(y, "Behandlung", request.treatment_period)
    y = draw_row(y, "Leistungserbringer", request.provider_name)

    y -= 5 * mm
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(margin, y, "Bemerkung")
    y -= 2 * mm
    notes_height = 25 * mm
    pdf.setFillColorRGB(*green)
    pdf.rect(margin, y - notes_height, content_width, notes_height, stroke=0, fill=1)
    pdf.setStrokeColorRGB(0, 0, 0)
    pdf.rect(margin, y - notes_height, content_width, notes_height, stroke=1, fill=0)
    pdf.setFillColorRGB(0, 0, 0)
    pdf.setFont("Helvetica", 8)
    text = pdf.beginText(margin + 2 * mm, y - 4 * mm)
    text.setLeading(3.5 * mm)
    for line in _wrap_text(request.notes or "-", "Helvetica", 8, content_width - 4 * mm)[:6]:
        text.textLine(line)
    pdf.drawText(text)
    y -= notes_height + 9 * mm

    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(margin, y, "Leistungsübersicht")
    y -= 2 * mm
    table_height = 17 * mm
    columns = [
        ("Behandlung", 58 * mm),
        ("Rechnungsnummer", 54 * mm),
        ("Währung", 28 * mm),
        ("Betrag", content_width - 140 * mm),
    ]
    x = margin
    pdf.setFillColorRGB(*green)
    pdf.rect(margin, y - 6 * mm, content_width, 6 * mm, stroke=0, fill=1)
    pdf.setFillColorRGB(0, 0, 0)
    for heading, column_width in columns:
        pdf.setFont("Helvetica-Bold", 7)
        pdf.drawString(x + 1.5 * mm, y - 4 * mm, heading)
        pdf.line(x, y - table_height, x, y)
        x += column_width
    pdf.line(margin + content_width, y - table_height, margin + content_width, y)
    pdf.rect(margin, y - table_height, content_width, table_height, stroke=1, fill=0)
    pdf.line(margin, y - 6 * mm, margin + content_width, y - 6 * mm)

    pdf.setFont("Helvetica", 9)
    x = margin
    values = [
        request.treatment_period,
        request.invoice_number,
        request.currency,
        f"{request.amount:.2f}",
    ]
    for (heading, column_width), value in zip(columns, values, strict=True):
        if heading == "Betrag":
            pdf.drawRightString(x + column_width - 2 * mm, y - 12 * mm, value)
        else:
            clipped = _wrap_text(value, "Helvetica", 9, column_width - 3 * mm)[0]
            pdf.drawString(x + 1.5 * mm, y - 12 * mm, clipped)
        x += column_width

    total_y = 28 * mm
    total_label_x = width - margin - 63 * mm
    pdf.setFillColorRGB(*green)
    pdf.rect(total_label_x, total_y, 37 * mm, 8 * mm, stroke=0, fill=1)
    pdf.rect(total_label_x + 39 * mm, total_y, 24 * mm, 8 * mm, stroke=0, fill=1)
    pdf.setFillColorRGB(0, 0, 0)
    pdf.setStrokeColorRGB(0, 0, 0)
    pdf.rect(total_label_x, total_y, 37 * mm, 8 * mm, stroke=1, fill=0)
    pdf.rect(total_label_x + 39 * mm, total_y, 24 * mm, 8 * mm, stroke=1, fill=0)
    pdf.setFont("Helvetica-Bold", 8)
    pdf.drawString(total_label_x + 1.5 * mm, total_y + 2.5 * mm, "Rechnungsbetrag:")
    pdf.drawRightString(
        total_label_x + 61.5 * mm,
        total_y + 2.5 * mm,
        f"{request.amount:.2f}",
    )
    pdf.setFont("Helvetica", 7)
    pdf.drawString(margin, total_y + 2.5 * mm, f"Währung: {request.currency}")

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
