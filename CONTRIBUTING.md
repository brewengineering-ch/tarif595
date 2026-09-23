# Contributing

Contributions are welcome, including first-time contributions. You do not need to
understand the complete Tarif 595 standard before improving a focused part of the
application.

## Set up the project

The project requires Python 3.12 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

On Windows PowerShell, activate the environment with
`.venv\Scripts\Activate.ps1`.

Run the application:

```bash
uvicorn app.main:app --reload
```

Then open <http://127.0.0.1:8000/>.

## Make a change

1. Keep changes focused and preserve the existing API unless the change explicitly
   requires an API update.
2. Add or update a test when behavior changes.
3. Run the checks below before opening a pull request.

```bash
ruff check .
ruff format --check .
pytest
```

Run `ruff format .` to apply the standard Python formatting automatically. Many
editor integrations can run Ruff whenever you save a file.

## Find the relevant code

| Path | Purpose |
| --- | --- |
| `app/main.py` | HTTP routes and download responses |
| `app/models.py` | API input models and validation rules |
| `app/invoice_xml.py` | generalInvoiceRequest 5.0 XML generation and validation |
| `app/pdf.py` | QR bill, reimbursement slip, and annex PDF generation |
| `app/index.html` | Web UI structure |
| `app/static/` | Web UI styles and browser behavior |
| `app/schemas/` | External XML schemas used to validate generated invoices |
| `tests/test_app.py` | API, PDF, XML, and validation tests |

The XML schemas are standards documents. Do not edit them as part of normal source
formatting or cleanup.

## Good first contributions

- Improve instructions or labels that are difficult to understand.
- Add a focused test for an uncovered validation case.
- Simplify duplicated code without changing generated documents.
- Improve accessibility or mobile usability in the Web UI.

If a change affects the QR bill or XML format, include the standard or rule that
motivated it in the pull request description.
