from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response

from app.models import QrBillRequest, ReimbursementSlipRequest, XmlAttachmentRequest
from app.pdf import create_qr_bill_pdf, create_reimbursement_slip_pdf, create_xml_attachment_pdf

app = FastAPI(
    title="Tarif 595 PDF generator",
    description="Generate Swiss QR bill, Rückforderungsbeleg and XML attachment PDFs without persisting data.",
    version="0.1.0",
)


INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Tarif 595 PDF generator</title>
    <style>
      body { font-family: sans-serif; margin: 2rem auto; max-width: 1100px; padding: 0 1rem; }
      h1, h2 { margin-bottom: 0.5rem; }
      .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 1rem; }
      form { border: 1px solid #d0d7de; border-radius: 8px; padding: 1rem; }
      label { display: block; font-size: 0.95rem; margin-top: 0.75rem; }
      input, textarea, select { width: 100%; padding: 0.5rem; margin-top: 0.25rem; box-sizing: border-box; }
      button { margin-top: 1rem; padding: 0.6rem 1rem; }
      .status { margin-top: 0.75rem; font-size: 0.95rem; }
      .download-link { display: inline-block; margin-top: 0.5rem; }
      code { background: #f6f8fa; padding: 0.1rem 0.3rem; border-radius: 4px; }
    </style>
  </head>
  <body>
    <h1>Tarif 595 PDF generator</h1>
    <p>All documents are generated on demand and returned directly to the browser or API client. The app does not persist submitted data or generated files.</p>
    <p>API endpoints: <code>POST /api/qr-bill</code>, <code>POST /api/reimbursement-slip</code>, <code>POST /api/xml-attachment</code>.</p>
    <div class="grid">
      <form data-endpoint="/api/qr-bill" data-filename="qr-bill.pdf">
        <h2>Swiss QR bill</h2>
        <label>Creditor name <input name="creditor_name" value="Example Practice AG" /></label>
        <label>Creditor street <input name="creditor_street" value="Bahnhofstrasse" /></label>
        <label>Creditor house number <input name="creditor_house_number" value="1" /></label>
        <label>Creditor postal code <input name="creditor_postal_code" value="8001" /></label>
        <label>Creditor city <input name="creditor_city" value="Zürich" /></label>
        <label>Creditor country <input name="creditor_country_code" value="CH" /></label>
        <label>Debtor name <input name="debtor_name" value="Max Muster" /></label>
        <label>Debtor street <input name="debtor_street" value="Musterweg" /></label>
        <label>Debtor house number <input name="debtor_house_number" value="5" /></label>
        <label>Debtor postal code <input name="debtor_postal_code" value="3000" /></label>
        <label>Debtor city <input name="debtor_city" value="Bern" /></label>
        <label>Debtor country <input name="debtor_country_code" value="CH" /></label>
        <label>IBAN <input name="account" value="CH4431999123000889012" /></label>
        <label>Amount <input name="amount" value="125.40" type="number" step="0.01" /></label>
        <label>Currency
          <select name="currency"><option>CHF</option><option>EUR</option></select>
        </label>
        <label>Reference <input name="reference" value="210000000003139471430009017" /></label>
        <label>Message <input name="message" value="Tarif 595 invoice" /></label>
        <label>Bill information <input name="bill_information" value="Tarif 595" /></label>
        <button type="submit">Download PDF</button>
        <p class="status" role="status" aria-live="polite"></p>
        <a class="download-link" hidden></a>
      </form>

      <form data-endpoint="/api/reimbursement-slip" data-filename="reimbursement-slip.pdf">
        <h2>Rückforderungsbeleg</h2>
        <label>Provider name <input name="provider_name" value="Example Practice AG" /></label>
        <label>Insurer name <input name="insurer_name" value="Example Versicherung" /></label>
        <label>Insured person <input name="insured_person" value="Max Muster" /></label>
        <label>Invoice number <input name="invoice_number" value="T595-2026-0001" /></label>
        <label>Treatment period <input name="treatment_period" value="2026-09-01 to 2026-09-15" /></label>
        <label>Amount <input name="amount" value="125.40" type="number" step="0.01" /></label>
        <label>Currency
          <select name="currency"><option>CHF</option><option>EUR</option></select>
        </label>
        <label>Notes <textarea name="notes">Generated for direct reimbursement.</textarea></label>
        <button type="submit">Download PDF</button>
        <p class="status" role="status" aria-live="polite"></p>
        <a class="download-link" hidden></a>
      </form>

      <form data-endpoint="/api/xml-attachment" data-filename="xml-attachment.pdf">
        <h2>XML attachment</h2>
        <label>Title <input name="title" value="Tarif 595 XML attachment" /></label>
        <label>Filename <input name="filename" value="invoice.xml" /></label>
        <label>XML content
          <textarea name="xml_content" rows="14">&lt;invoice version="5.0"&gt;
  &lt;provider&gt;Example Practice AG&lt;/provider&gt;
  &lt;patient&gt;Max Muster&lt;/patient&gt;
  &lt;total currency="CHF"&gt;125.40&lt;/total&gt;
&lt;/invoice&gt;</textarea>
        </label>
        <button type="submit">Download PDF</button>
        <p class="status" role="status" aria-live="polite"></p>
        <a class="download-link" hidden></a>
      </form>
    </div>

    <script>
      const toJson = (form) => {
        const data = Object.fromEntries(new FormData(form).entries());
        if (form.dataset.endpoint === "/api/qr-bill") {
          return {
            account: data.account,
            creditor: {
              name: data.creditor_name, street: data.creditor_street, house_number: data.creditor_house_number,
              postal_code: data.creditor_postal_code, city: data.creditor_city, country_code: data.creditor_country_code
            },
            debtor: {
              name: data.debtor_name, street: data.debtor_street, house_number: data.debtor_house_number,
              postal_code: data.debtor_postal_code, city: data.debtor_city, country_code: data.debtor_country_code
            },
            amount: data.amount,
            currency: data.currency,
            reference: data.reference,
            message: data.message,
            bill_information: data.bill_information
          };
        }
        return data;
      };

      document.querySelectorAll("form[data-endpoint]").forEach((form) => {
        form.addEventListener("submit", async (event) => {
          event.preventDefault();
          const status = form.querySelector(".status");
          const downloadLink = form.querySelector(".download-link");
          if (downloadLink.dataset.objectUrl) {
            URL.revokeObjectURL(downloadLink.dataset.objectUrl);
            delete downloadLink.dataset.objectUrl;
          }
          status.textContent = "Generating PDF...";
          downloadLink.hidden = true;
          const response = await fetch(form.dataset.endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(toJson(form))
          });
          if (!response.ok) {
            let message = response.statusText;
            try {
              const payload = await response.json();
              message = JSON.stringify(payload.detail ?? payload);
            } catch (_) {
              message = await response.text();
            }
            status.textContent = `Request failed (${response.status}): ${message}`;
            return;
          }
          const blob = await response.blob();
          const link = document.createElement("a");
          link.href = URL.createObjectURL(blob);
          link.download = form.dataset.filename;
          link.click();
          downloadLink.href = link.href;
          downloadLink.download = form.dataset.filename;
          downloadLink.textContent = `Download ${form.dataset.filename} again`;
          downloadLink.dataset.objectUrl = link.href;
          downloadLink.hidden = false;
          status.textContent = "PDF ready.";
        });
      });
    </script>
  </body>
</html>
"""


def pdf_response(content: bytes, filename: str) -> Response:
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return INDEX_HTML


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/qr-bill")
async def qr_bill(request: QrBillRequest) -> Response:
    return pdf_response(create_qr_bill_pdf(request), "qr-bill.pdf")


@app.post("/api/reimbursement-slip")
async def reimbursement_slip(request: ReimbursementSlipRequest) -> Response:
    return pdf_response(create_reimbursement_slip_pdf(request), "reimbursement-slip.pdf")


@app.post("/api/xml-attachment")
async def xml_attachment(request: XmlAttachmentRequest) -> Response:
    return pdf_response(create_xml_attachment_pdf(request), "xml-attachment.pdf")
