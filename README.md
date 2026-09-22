# tarif595

Minimal open source web application to generate the three PDF documents typically needed for Swiss Tarif 595 workflows:

1. Swiss QR bill PDF
2. Human-readable Rückforderungsbeleg PDF
3. Attachment PDF with the XML invoice encoded as a QR code

The application exposes both:

- a single Web form that generates each document or one combined PDF from the same invoice data
- a JSON API for integration and automation

No request payloads or generated files are persisted by the application. PDFs are created in memory and streamed directly to the caller.

## Quick start

### Local development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/.

### Docker

```bash
docker build -t tarif595 .
docker run --rm -p 8000:8000 tarif595
```

## Shared invoice API

- `POST /api/invoice/qr-bill`
- `POST /api/invoice/reimbursement-slip`
- `POST /api/invoice/xml-attachment`
- `POST /api/invoice/combined`

The original specialized endpoints remain available for backwards compatibility.

Interactive API documentation is available at `/docs`.

## Reference documentation

The repository includes these official references:

- [Swiss Implementation Guidelines for the QR-bill, version 2.3](docs/ig-qr-bill-v2.3-en.pdf), which defines the QR payload and provides the schematic payment-part example used by this application.
- [General Invoice Request 5.0 detailed print template](docs/printTemplates_GIReq500_DetailG.pdf) from the [Forum Datenaustausch invoice standard](https://www.forum-datenaustausch.ch/xml-standards/rechnung), which provides the visual reference for the Rückforderungsbeleg.
- [General Invoice Request 5.0 annex print template](docs/printTemplates_GIReq500_Annex.pdf), which defines the XML QR-code sheet layout and structured-append encoding.
- [General Invoice Request 5.0 XML Schema](docs/generalInvoiceRequest_500.xsd), which is used at runtime to validate XML before generating an attachment PDF.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```