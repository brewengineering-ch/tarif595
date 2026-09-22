# tarif595

Minimal open source web application to generate the three PDF documents typically needed for Swiss Tarif 595 workflows:

1. Swiss QR bill PDF
2. Human-readable Rückforderungsbeleg PDF
3. Attachment PDF with the XML invoice encoded as a QR code

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
- `POST /api/reimbursement-slip`
- `POST /api/xml-attachment`

Interactive API documentation is available at `/docs`.

## Tests

```bash
pip install -r requirements.txt
pip install pytest httpx
pytest
```