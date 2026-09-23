import re
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from app.models import QrBillRequest, ReimbursementSlipRequest, Tarif595Request, XmlAttachmentRequest
from app.pdf import (
    create_qr_bill_pdf,
    create_reimbursement_slip_pdf,
    create_tarif595_combined_pdf,
    create_tarif595_human_pdf,
    create_tarif595_machine_pdf,
    create_xml_attachment_pdf,
)

app = FastAPI(
    title="Tarif 595 PDF generator",
    description="Generate Swiss QR bills and Tarif 595 invoice documents without persisting data.",
    version="0.2.0",
)

INDEX_HTML = Path(__file__).with_name("index.html")
STATIC_DIRECTORY = Path(__file__).with_name("static")
app.mount("/static", StaticFiles(directory=STATIC_DIRECTORY), name="static")


def pdf_response(content: bytes, filename: str) -> Response:
    safe_filename = re.sub(r"[^A-Za-z0-9._-]+", "_", filename).strip("._") or "document.pdf"
    encoded_filename = quote(filename, safe="")
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (f"attachment; filename=\"{safe_filename}\"; filename*=UTF-8''{encoded_filename}")
        },
    )


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/qr-bill")
async def qr_bill(request: QrBillRequest) -> Response:
    return pdf_response(create_qr_bill_pdf(request), "qr-bill.pdf")


@app.post("/api/tarif595/human-readable")
async def tarif595_human_readable(request: Tarif595Request) -> Response:
    return pdf_response(
        create_tarif595_human_pdf(request),
        f"{request.invoice_number}-human-readable.pdf",
    )


@app.post("/api/tarif595/machine-readable")
async def tarif595_machine_readable(request: Tarif595Request) -> Response:
    return pdf_response(
        create_tarif595_machine_pdf(request),
        f"{request.invoice_number}-machine-readable.pdf",
    )


@app.post("/api/tarif595/combined")
async def tarif595_combined(request: Tarif595Request) -> Response:
    return pdf_response(
        create_tarif595_combined_pdf(request),
        f"{request.invoice_number}-complete.pdf",
    )


@app.post("/api/reimbursement-slip")
async def reimbursement_slip(request: ReimbursementSlipRequest) -> Response:
    return pdf_response(create_reimbursement_slip_pdf(request), "reimbursement-slip.pdf")


@app.post("/api/xml-attachment")
async def xml_attachment(request: XmlAttachmentRequest) -> Response:
    stem = request.filename.rsplit(".", 1)[0] if "." in request.filename else request.filename
    return pdf_response(create_xml_attachment_pdf(request), f"{stem}.pdf")
