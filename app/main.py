import re
from urllib.parse import quote

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response

from app.invoice import create_invoice_xml
from app.models import (
    InvoiceRequest,
    QrBillRequest,
    ReimbursementSlipRequest,
    XmlAttachmentRequest,
)
from app.pdf import (
    create_combined_pdf,
    create_qr_bill_pdf,
    create_reimbursement_slip_pdf,
    create_xml_attachment_pdf,
)

app = FastAPI(
    title="Tarif 595 PDF generator",
    description="Generate all Swiss Tarif 595 invoice documents from one invoice.",
    version="0.2.0",
)


INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Tarif 595 PDF generator</title>
    <style>
      body { font-family: sans-serif; margin: 2rem auto; max-width: 1050px; padding: 0 1rem; color: #1f2328; }
      h1 { margin-bottom: 0.35rem; }
      h2 { font-size: 1.1rem; margin: 0 0 0.75rem; grid-column: 1 / -1; }
      form { display: grid; gap: 1rem; }
      fieldset { border: 1px solid #d0d7de; border-radius: 8px; padding: 1rem; }
      legend { font-weight: 700; padding: 0 0.4rem; }
      .fields { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 0.75rem 1rem; }
      label { display: block; font-size: 0.9rem; }
      label.wide { grid-column: 1 / -1; }
      input, textarea, select { width: 100%; padding: 0.5rem; margin-top: 0.25rem; box-sizing: border-box; }
      .actions { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 0.75rem; }
      button { padding: 0.75rem 1rem; cursor: pointer; }
      button.primary { background: #1f883d; border: 1px solid #1a7f37; color: white; font-weight: 700; }
      .status { min-height: 1.25rem; margin: 0; }
    </style>
  </head>
  <body>
    <h1>Tarif 595 PDF generator</h1>
    <p>Enter the invoice once, then generate any individual document or one combined PDF. Data is processed in memory and is not persisted.</p>

    <form id="invoice-form">
      <fieldset>
        <legend>Invoice</legend>
        <div class="fields">
          <label>Invoice number <input name="invoice_number" value="T595-2026-0001" required /></label>
          <label>Invoice date <input name="invoice_date" type="datetime-local" required /></label>
          <label>Language
            <select name="language"><option>de</option><option>fr</option><option>it</option></select>
          </label>
          <label>Billing method
            <select name="tiers"><option value="G">Tiers Garant</option><option value="P">Tiers Payant</option><option value="S">Tiers Soldant</option></select>
          </label>
          <label>Professional role
            <select name="role"><option value="psychologist">Psychologist</option><option value="physician">Physician</option><option value="physiotherapist">Physiotherapist</option><option value="other">Other</option></select>
          </label>
          <label>Document GUID <input name="document_guid" pattern="[0-9A-Fa-f]{32}" maxlength="32" required /></label>
          <label class="wide">Notes <textarea name="notes">Generated for direct reimbursement.</textarea></label>
        </div>
      </fieldset>

      <fieldset>
        <legend>Practice and payment</legend>
        <div class="fields">
          <label>Practice name <input name="practice_name" value="Example Practice AG" required /></label>
          <label>Practice GLN <input name="practice_gln" value="7601001302112" pattern="[0-9]{13}" required /></label>
          <label>Street <input name="practice_street" value="Bahnhofstrasse" required /></label>
          <label>House number <input name="practice_house_number" value="1" /></label>
          <label>Postal code <input name="practice_postal_code" value="8001" required /></label>
          <label>City <input name="practice_city" value="Zürich" required /></label>
          <label>Country <input name="practice_country_code" value="CH" maxlength="2" required /></label>
          <label>IBAN / QR-IBAN <input name="account" value="CH4431999123000889012" required /></label>
          <label>Reference <input name="reference" value="210000000003139471430009017" /></label>
          <label>Amount (CHF) <input name="amount" value="125.40" type="number" min="0.01" step="0.01" required /></label>
          <label class="wide">Payment message <input name="message" value="Tarif 595 invoice" /></label>
        </div>
      </fieldset>

      <fieldset>
        <legend>Patient</legend>
        <div class="fields">
          <label>Given name <input name="patient_given_name" value="Max" required /></label>
          <label>Family name <input name="patient_family_name" value="Muster" required /></label>
          <label>Street <input name="patient_street" value="Musterweg" required /></label>
          <label>House number <input name="patient_house_number" value="5" /></label>
          <label>Postal code <input name="patient_postal_code" value="3000" required /></label>
          <label>City <input name="patient_city" value="Bern" required /></label>
          <label>Country <input name="patient_country_code" value="CH" maxlength="2" required /></label>
          <label>Date of birth <input name="patient_birthdate" type="date" value="1986-02-28" required /></label>
          <label>Gender
            <select name="patient_gender"><option value="male">Male</option><option value="female">Female</option><option value="diverse">Diverse</option></select>
          </label>
          <label>Administrative sex
            <select name="patient_sex"><option value="male">Male</option><option value="female">Female</option></select>
          </label>
          <label>Swiss social security number <input name="patient_ssn" value="7561234567890" required /></label>
        </div>
      </fieldset>

      <fieldset>
        <legend>Insurer</legend>
        <div class="fields">
          <label>Insurer name <input name="insurer_name" value="Example Versicherung" required /></label>
          <label>Insurer GLN <input name="insurer_gln" value="7634567890000" pattern="[0-9]{13}" required /></label>
          <label>Street <input name="insurer_street" value="Versicherungsweg" required /></label>
          <label>House number <input name="insurer_house_number" value="2" /></label>
          <label>Postal code <input name="insurer_postal_code" value="3000" required /></label>
          <label>City <input name="insurer_city" value="Bern" required /></label>
          <label>Country <input name="insurer_country_code" value="CH" maxlength="2" required /></label>
        </div>
      </fieldset>

      <fieldset>
        <legend>Treatment and service</legend>
        <div class="fields">
          <label>Treatment begin <input name="treatment_begin" type="date" value="2026-09-01" required /></label>
          <label>Treatment end <input name="treatment_end" type="date" value="2026-09-15" required /></label>
          <label>Canton <input name="canton" value="BE" maxlength="2" required /></label>
          <label>Reason
            <select name="treatment_reason"><option value="disease">Disease</option><option value="accident">Accident</option><option value="maternity">Maternity</option><option value="prevention">Prevention</option><option value="birthdefect">Birth defect</option><option value="unknown">Unknown</option></select>
          </label>
          <label>Tariff type <input name="tariff_type" value="595" maxlength="3" required /></label>
          <label>Service code <input name="service_code" value="T595.001" required /></label>
          <label>Quantity <input name="quantity" type="number" value="1" min="0.01" step="0.01" required /></label>
          <label class="wide">Service name <input name="service_name" value="Tarif 595 service" required /></label>
        </div>
      </fieldset>

      <div class="actions">
        <button type="submit" data-endpoint="/api/invoice/qr-bill" data-filename="qr-bill.pdf">Generate QR bill</button>
        <button type="submit" data-endpoint="/api/invoice/reimbursement-slip" data-filename="reimbursement-slip.pdf">Generate reimbursement slip</button>
        <button type="submit" data-endpoint="/api/invoice/xml-attachment" data-filename="xml-attachment.pdf">Generate XML attachment</button>
        <button type="submit" class="primary" data-endpoint="/api/invoice/combined" data-filename="invoice-documents.pdf">Generate combined PDF</button>
      </div>
      <p class="status" role="status" aria-live="polite"></p>
    </form>

    <script>
      const form = document.querySelector("#invoice-form");
      const status = form.querySelector(".status");
      const localNow = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 16);
      form.elements.invoice_date.value = localNow;
      form.elements.document_guid.value = crypto.randomUUID().replaceAll("-", "");

      const party = (data, prefix) => ({
        name: data[`${prefix}_name`],
        street: data[`${prefix}_street`],
        house_number: data[`${prefix}_house_number`],
        postal_code: data[`${prefix}_postal_code`],
        city: data[`${prefix}_city`],
        country_code: data[`${prefix}_country_code`]
      });

      const payload = () => {
        const data = Object.fromEntries(new FormData(form).entries());
        return {
          invoice_number: data.invoice_number,
          invoice_date: new Date(data.invoice_date).toISOString(),
          document_guid: data.document_guid,
          language: data.language,
          tiers: data.tiers,
          role: data.role,
          practice: party(data, "practice"),
          practice_gln: data.practice_gln,
          insurer: party(data, "insurer"),
          insurer_gln: data.insurer_gln,
          patient: {
            given_name: data.patient_given_name,
            family_name: data.patient_family_name,
            street: data.patient_street,
            house_number: data.patient_house_number,
            postal_code: data.patient_postal_code,
            city: data.patient_city,
            country_code: data.patient_country_code,
            birthdate: data.patient_birthdate,
            gender: data.patient_gender,
            sex: data.patient_sex,
            ssn: data.patient_ssn
          },
          account: data.account,
          reference: data.reference,
          amount: data.amount,
          message: data.message,
          notes: data.notes,
          treatment_begin: data.treatment_begin,
          treatment_end: data.treatment_end,
          canton: data.canton.toUpperCase(),
          treatment_reason: data.treatment_reason,
          tariff_type: data.tariff_type.toUpperCase(),
          service_code: data.service_code,
          service_name: data.service_name,
          quantity: data.quantity
        };
      };

      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const button = event.submitter;
        status.textContent = "Generating PDF...";
        const response = await fetch(button.dataset.endpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload())
        });
        if (!response.ok) {
          let message = response.statusText;
          try {
            const body = await response.json();
            message = JSON.stringify(body.detail ?? body);
          } catch (_) {
            message = await response.text();
          }
          status.textContent = `Request failed (${response.status}): ${message}`;
          return;
        }
        const objectUrl = URL.createObjectURL(await response.blob());
        const link = document.createElement("a");
        link.href = objectUrl;
        link.download = button.dataset.filename;
        link.click();
        setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
        status.textContent = `${button.dataset.filename} ready.`;
      });
    </script>
  </body>
</html>
"""


def pdf_response(content: bytes, filename: str) -> Response:
    safe_filename = re.sub(r'[^A-Za-z0-9._-]+', "_", filename).strip("._") or "document.pdf"
    encoded_filename = quote(filename, safe="")
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{safe_filename}"; '
                f"filename*=UTF-8''{encoded_filename}"
            )
        },
    )


def _xml_request(request: InvoiceRequest) -> XmlAttachmentRequest:
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", request.invoice_number).strip("._") or "invoice"
    return XmlAttachmentRequest(
        filename=f"{safe_stem}.xml",
        xml_content=create_invoice_xml(request),
    )


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return INDEX_HTML


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/invoice/qr-bill")
async def invoice_qr_bill(request: InvoiceRequest) -> Response:
    return pdf_response(create_qr_bill_pdf(request.qr_bill_request()), "qr-bill.pdf")


@app.post("/api/invoice/reimbursement-slip")
async def invoice_reimbursement_slip(request: InvoiceRequest) -> Response:
    return pdf_response(
        create_reimbursement_slip_pdf(request.reimbursement_request()),
        "reimbursement-slip.pdf",
    )


@app.post("/api/invoice/xml-attachment")
async def invoice_xml_attachment(request: InvoiceRequest) -> Response:
    xml_request = _xml_request(request)
    return pdf_response(create_xml_attachment_pdf(xml_request), "xml-attachment.pdf")


@app.post("/api/invoice/combined")
async def invoice_combined(request: InvoiceRequest) -> Response:
    xml_request = _xml_request(request)
    qr_bill = create_qr_bill_pdf(request.qr_bill_request())
    reimbursement = create_reimbursement_slip_pdf(request.reimbursement_request())
    attachment = create_xml_attachment_pdf(xml_request)
    combined = create_combined_pdf(
        qr_bill,
        reimbursement,
        attachment,
        xml_filename=xml_request.filename,
        xml_content=xml_request.xml_content,
    )
    return pdf_response(combined, "invoice-documents.pdf")


@app.post("/api/qr-bill")
async def qr_bill(request: QrBillRequest) -> Response:
    return pdf_response(create_qr_bill_pdf(request), "qr-bill.pdf")


@app.post("/api/reimbursement-slip")
async def reimbursement_slip(request: ReimbursementSlipRequest) -> Response:
    return pdf_response(create_reimbursement_slip_pdf(request), "reimbursement-slip.pdf")


@app.post("/api/xml-attachment")
async def xml_attachment(request: XmlAttachmentRequest) -> Response:
    stem = request.filename.rsplit(".", 1)[0] if "." in request.filename else request.filename
    return pdf_response(create_xml_attachment_pdf(request), f"{stem}.pdf")
