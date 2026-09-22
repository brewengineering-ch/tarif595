from __future__ import annotations

from io import BytesIO
from typing import Iterable

import qrcode
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from app.models import Party, QrBillRequest, ReimbursementSlipRequest, XmlAttachmentRequest, is_qr_iban


def _qr_image(payload: str) -> ImageReader:
    image = qrcode.make(payload)
    output = BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return ImageReader(output)


def _party_lines(party: Party) -> list[str]:
    line_2 = f"{party.street} {party.house_number}".strip()
    return [party.name, line_2, f"{party.postal_code} {party.city}", party.country_code]


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
            f"{request.amount:.2f}",
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
    width, height = A4

    pdf.setTitle("Swiss QR bill")
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(20 * mm, height - 20 * mm, "Swiss QR bill")

    pdf.setFont("Helvetica", 10)
    pdf.drawString(20 * mm, height - 28 * mm, "Generated in memory for Tarif 595 workflows.")

    _text_block(pdf, 20 * mm, height - 45 * mm, "Creditor", _party_lines(request.creditor))
    _text_block(pdf, 110 * mm, height - 45 * mm, "Debtor", _party_lines(request.debtor))

    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(20 * mm, height - 90 * mm, f"Amount: {request.amount:.2f} {request.currency}")
    pdf.setFont("Helvetica", 10)
    pdf.drawString(20 * mm, height - 98 * mm, f"Account: {request.account}")
    pdf.drawString(20 * mm, height - 106 * mm, f"Reference: {request.reference or '-'}")
    pdf.drawString(20 * mm, height - 114 * mm, f"Message: {request.message or '-'}")
    pdf.drawString(20 * mm, height - 122 * mm, f"Bill information: {request.bill_information or '-'}")

    pdf.drawImage(_qr_image(build_swiss_qr_payload(request)), 20 * mm, 30 * mm, width=55 * mm, height=55 * mm)
    pdf.setFont("Helvetica", 9)
    pdf.drawString(20 * mm, 25 * mm, "Swiss QR payload encoded according to the SPC structure.")

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
    return buffer.getvalue()
