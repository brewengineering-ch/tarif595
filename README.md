# tarif595

Minimal open source web application to generate the documents needed for Swiss Tarif 595 workflows:

1. Swiss QR bill PDF
2. Human-readable Rückforderungsbeleg PDF
3. Machine-readable annex PDF with the schema-valid XML 5.0 invoice compressed, Base64-encoded and split across numbered QR codes
4. Combined PDF containing all three documents

The application exposes both:

- a simple Web UI for one-off document generation
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

## API

- `POST /api/qr-bill`
- `POST /api/tarif595/human-readable`
- `POST /api/tarif595/machine-readable`
- `POST /api/tarif595/combined`
- `POST /api/reimbursement-slip`
- `POST /api/xml-attachment`

Interactive API documentation is available at `/docs`.

## Reference documentation

- [QR-bill – Swiss Payment Standards](https://www.six-group.com/en/products-services/banking-services/payment-standardization/standards/qr-bill.html)
- [Swiss Payment Standards Download Center](https://www.six-group.com/en/products-services/banking-services/payment-standardization/downloads-faq/download-center.html)
- [Implementation Guidelines for the QR-bill, version 2.3 (PDF)](https://www.six-group.com/dam/download/banking-services/standardization/qr-bill/ig-qr-bill-v2.3-en.pdf)
- [Forum Datenaustausch: generalInvoiceRequest 5.0 documentation and XSD](https://www.forum-datenaustausch.ch/xml-standards/rechnung)

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```