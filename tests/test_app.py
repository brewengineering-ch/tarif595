from io import BytesIO
from pathlib import Path
import sys

from fastapi.testclient import TestClient
from pypdf import PdfReader
import zxingcpp

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app
from app.models import QrBillRequest, ReimbursementSlipRequest
from app.pdf import _page_control_datamatrix, build_page_control_payload, build_swiss_qr_payload
from app.xml_attachment import encode_xml_attachment


client = TestClient(app)
VALID_INVOICE_XML = (
    Path(__file__).parent / "fixtures" / "general_invoice_request.xml"
).read_text()
INVOICE_REQUEST = {
    "invoice_number": "T595-2026-0001",
    "invoice_date": "2026-09-22T16:00:00+02:00",
    "document_guid": "3c6bc0bd140c4226b9aab71c57178000",
    "language": "de",
    "tiers": "G",
    "role": "psychologist",
    "practice": {
        "name": "Example Practice AG",
        "street": "Bahnhofstrasse",
        "house_number": "1",
        "postal_code": "8001",
        "city": "Zürich",
        "country_code": "CH",
    },
    "practice_gln": "7601001302112",
    "insurer": {
        "name": "Example Versicherung",
        "street": "Versicherungsweg",
        "house_number": "2",
        "postal_code": "3000",
        "city": "Bern",
        "country_code": "CH",
    },
    "insurer_gln": "7634567890000",
    "patient": {
        "given_name": "Max",
        "family_name": "Muster",
        "street": "Musterweg",
        "house_number": "5",
        "postal_code": "3000",
        "city": "Bern",
        "country_code": "CH",
        "birthdate": "1986-02-28",
        "gender": "male",
        "sex": "male",
        "ssn": "7561234567890",
    },
    "account": "CH4431999123000889012",
    "reference": "210000000003139471430009017",
    "amount": "125.40",
    "message": "Tarif 595 invoice",
    "notes": "Generated for direct reimbursement.",
    "treatment_begin": "2026-09-01",
    "treatment_end": "2026-09-15",
    "canton": "BE",
    "treatment_reason": "disease",
    "tariff_type": "595",
    "service_code": "T595.001",
    "service_name": "Tarif 595 service",
    "quantity": "1",
}


def test_index_exposes_all_document_types() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.text.count("<form") == 1
    assert "Generate QR bill" in response.text
    assert "Generate reimbursement slip" in response.text
    assert "Generate XML attachment" in response.text
    assert "Generate combined PDF" in response.text


def test_shared_invoice_generates_each_pdf_and_combined_document() -> None:
    endpoints = {
        "/api/invoice/qr-bill": 1,
        "/api/invoice/reimbursement-slip": 1,
        "/api/invoice/xml-attachment": 1,
        "/api/invoice/combined": 3,
    }

    for endpoint, expected_pages in endpoints.items():
        response = client.post(endpoint, json=INVOICE_REQUEST)
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        reader = PdfReader(BytesIO(response.content))
        assert len(reader.pages) == expected_pages

    combined = client.post("/api/invoice/combined", json=INVOICE_REQUEST)
    attachments = PdfReader(BytesIO(combined.content)).attachments
    generated_xml = attachments["T595-2026-0001.xml"][0]
    assert b"<invoice:request" in generated_xml
    assert b'request_id="T595-2026-0001"' in generated_xml
    assert b"<invoice:service " in generated_xml


def test_healthcheck() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_qr_bill_generation_returns_pdf() -> None:
    response = client.post(
        "/api/qr-bill",
        json={
            "account": "CH4431999123000889012",
            "creditor": {
                "name": "Example Practice AG",
                "street": "Bahnhofstrasse",
                "house_number": "1",
                "postal_code": "8001",
                "city": "Zürich",
                "country_code": "CH",
            },
            "debtor": {
                "name": "Max Muster",
                "street": "Musterweg",
                "house_number": "5",
                "postal_code": "3000",
                "city": "Bern",
                "country_code": "CH",
            },
            "amount": "125.40",
            "currency": "CHF",
            "reference": "210000000003139471430009017",
            "message": "Tarif 595 invoice",
            "bill_information": "Tarif 595",
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    page = PdfReader(BytesIO(response.content)).pages[0]
    text = page.extract_text()
    assert round(float(page.mediabox.width), 2) == 595.28
    assert round(float(page.mediabox.height), 2) == 841.89
    assert "Receipt" in text
    assert "Payment part" in text
    assert "Account / Payable to" in text
    assert "Acceptance point" in text


def test_qr_bill_generation_supports_scor_reference_with_non_qr_iban() -> None:
    response = client.post(
        "/api/qr-bill",
        json={
            "account": "CH9300762011623852957",
            "creditor": {
                "name": "Example Practice AG",
                "street": "Bahnhofstrasse",
                "house_number": "1",
                "postal_code": "8001",
                "city": "Zürich",
                "country_code": "CH",
            },
            "debtor": {
                "name": "Max Muster",
                "street": "Musterweg",
                "house_number": "5",
                "postal_code": "3000",
                "city": "Bern",
                "country_code": "CH",
            },
            "amount": "125.40",
            "currency": "CHF",
            "reference": "RF18539007547034",
            "message": "Tarif 595 invoice",
            "bill_information": "Tarif 595",
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


def test_qr_bill_generation_supports_open_amount_bills() -> None:
    response = client.post(
        "/api/qr-bill",
        json={
            "account": "CH4431999123000889012",
            "creditor": {
                "name": "Example Practice AG",
                "street": "Bahnhofstrasse",
                "house_number": "1",
                "postal_code": "8001",
                "city": "Zürich",
                "country_code": "CH",
            },
            "debtor": {
                "name": "Max Muster",
                "street": "Musterweg",
                "house_number": "5",
                "postal_code": "3000",
                "city": "Bern",
                "country_code": "CH",
            },
            "currency": "CHF",
            "reference": "210000000003139471430009017",
            "message": "Tarif 595 invoice",
            "bill_information": "Tarif 595",
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


def test_qr_payload_uses_combined_addresses_when_house_number_is_missing() -> None:
    payload = build_swiss_qr_payload(
        QrBillRequest(
            account="CH9300762011623852957",
            creditor={
                "name": "Example Practice AG",
                "street": "Bahnhofstrasse",
                "house_number": "",
                "postal_code": "8001",
                "city": "Zürich",
                "country_code": "CH",
            },
            debtor={
                "name": "Max Muster",
                "street": "Musterweg",
                "house_number": "",
                "postal_code": "3000",
                "city": "Bern",
                "country_code": "CH",
            },
            amount="125.40",
            currency="CHF",
            reference="RF18539007547034",
            message="Tarif 595 invoice",
            bill_information="Tarif 595",
        )
    ).splitlines()

    assert payload[4] == "K"
    assert payload[19] == "K"


def test_qr_bill_generation_rejects_qrr_reference_with_non_qr_iban() -> None:
    response = client.post(
        "/api/qr-bill",
        json={
            "account": "CH9300762011623852957",
            "creditor": {
                "name": "Example Practice AG",
                "street": "Bahnhofstrasse",
                "house_number": "1",
                "postal_code": "8001",
                "city": "Zürich",
                "country_code": "CH",
            },
            "debtor": {
                "name": "Max Muster",
                "street": "Musterweg",
                "house_number": "5",
                "postal_code": "3000",
                "city": "Bern",
                "country_code": "CH",
            },
            "amount": "125.40",
            "currency": "CHF",
            "reference": "210000000003139471430009017",
            "message": "Tarif 595 invoice",
            "bill_information": "Tarif 595",
        },
    )

    assert response.status_code == 422
    assert "valid ISO 11649" in response.text


def test_qr_bill_generation_rejects_invalid_scor_reference() -> None:
    response = client.post(
        "/api/qr-bill",
        json={
            "account": "CH9300762011623852957",
            "creditor": {
                "name": "Example Practice AG",
                "street": "Bahnhofstrasse",
                "house_number": "",
                "postal_code": "8001",
                "city": "Zürich",
                "country_code": "CH",
            },
            "debtor": {
                "name": "Max Muster",
                "street": "Musterweg",
                "house_number": "",
                "postal_code": "3000",
                "city": "Bern",
                "country_code": "CH",
            },
            "amount": "125.40",
            "currency": "CHF",
            "reference": "RF18539007547035",
            "message": "Tarif 595 invoice",
            "bill_information": "Tarif 595",
        },
    )

    assert response.status_code == 422
    assert "valid ISO 11649" in response.text


def test_qr_bill_generation_rejects_non_numeric_reference_with_qr_iban() -> None:
    response = client.post(
        "/api/qr-bill",
        json={
            "account": "CH4431999123000889012",
            "creditor": {
                "name": "Example Practice AG",
                "street": "Bahnhofstrasse",
                "house_number": "1",
                "postal_code": "8001",
                "city": "Zürich",
                "country_code": "CH",
            },
            "debtor": {
                "name": "Max Muster",
                "street": "Musterweg",
                "house_number": "5",
                "postal_code": "3000",
                "city": "Bern",
                "country_code": "CH",
            },
            "amount": "125.40",
            "currency": "CHF",
            "reference": "RF18539007547034",
            "message": "Tarif 595 invoice",
            "bill_information": "Tarif 595",
        },
    )

    assert response.status_code == 422
    assert "27-digit QR reference" in response.text


def test_qr_bill_generation_rejects_invalid_checksum_reference_with_qr_iban() -> None:
    response = client.post(
        "/api/qr-bill",
        json={
            "account": "CH4431999123000889012",
            "creditor": {
                "name": "Example Practice AG",
                "street": "Bahnhofstrasse",
                "house_number": "1",
                "postal_code": "8001",
                "city": "Zürich",
                "country_code": "CH",
            },
            "debtor": {
                "name": "Max Muster",
                "street": "Musterweg",
                "house_number": "5",
                "postal_code": "3000",
                "city": "Bern",
                "country_code": "CH",
            },
            "amount": "125.40",
            "currency": "CHF",
            "reference": "210000000003139471430009018",
            "message": "Tarif 595 invoice",
            "bill_information": "Tarif 595",
        },
    )

    assert response.status_code == 422
    assert "27-digit QR reference" in response.text


def test_reimbursement_slip_generation_returns_pdf() -> None:
    response = client.post(
        "/api/reimbursement-slip",
        json={
            "provider_name": "Example Practice AG",
            "insurer_name": "Example Versicherung",
            "insured_person": "Max Muster",
            "invoice_number": "T595-2026-0001",
            "treatment_period": "2026-09-01 to 2026-09-15",
            "document_guid": "3c6bc0bd140c4226b9aab71c57178000",
            "language": "de",
            "tiers": "G",
            "amount": "125.40",
            "currency": "CHF",
            "notes": "Generated for direct reimbursement.",
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    text = PdfReader(BytesIO(response.content)).pages[0].extract_text()
    assert "Release 5.0 / General / de" in text
    assert "Der Versicherung zustellen" in text
    assert "Rechnungsangaben" in text
    assert "Leistungsübersicht" in text
    assert "Rechnungsbetrag:" in text
    assert "T595-2026-0001" in text
    assert "125.40" in text


def test_reimbursement_page_control_datamatrix() -> None:
    request = ReimbursementSlipRequest(
        provider_name="Example Practice AG",
        insurer_name="Example Versicherung",
        insured_person="Max Muster",
        invoice_number="T595-2026-0001",
        treatment_period="2026-09-01 to 2026-09-15",
        document_guid="00000000000000000000000000000000",
        language="de",
        tiers="G",
        amount="125.40",
    )

    payload = build_page_control_payload(request, 1)
    image = _page_control_datamatrix(payload)
    decoded = zxingcpp.read_barcode(image)

    assert payload == "FD5000000000000000000000000000000000deGGR01"
    assert len(payload.encode("ascii")) == 43
    assert image.size == (240, 240)
    assert decoded is not None
    assert decoded.format == zxingcpp.BarcodeFormat.DataMatrix
    assert decoded.text == payload


def test_xml_attachment_generation_returns_pdf() -> None:
    response = client.post(
        "/api/xml-attachment",
        json={
            "filename": "invoice.xml",
            "xml_content": VALID_INVOICE_XML,
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    reader = PdfReader(BytesIO(response.content))
    text = reader.pages[0].extract_text()
    assert "Rückforderungsbeleg QR-Code Blatt" in text
    assert "Release 5.0/Annex/de" in text
    assert "Petra Muster-Meier" in text
    assert "QR-Code 1" in text
    assert reader.attachments["invoice.xml"][0] == VALID_INVOICE_XML.encode()
    assert encode_xml_attachment(VALID_INVOICE_XML).startswith("7V")


def test_xml_attachment_rejects_xml_that_does_not_match_schema() -> None:
    response = client.post(
        "/api/xml-attachment",
        json={
            "filename": "invoice.xml",
            "xml_content": '<invoice version="5.0"><total currency="CHF">125.40</total></invoice>',
        },
    )

    assert response.status_code == 422
    assert "does not conform to General Invoice Request 5.0" in response.text


def test_xml_attachment_rejects_malformed_xml() -> None:
    response = client.post(
        "/api/xml-attachment",
        json={"filename": "invoice.xml", "xml_content": "<invoice>"},
    )

    assert response.status_code == 422
    assert "XML is not well-formed" in response.text


def test_xml_attachment_rejects_unsafe_filename() -> None:
    response = client.post(
        "/api/xml-attachment",
        json={
            "filename": "bad name.xml",
            "xml_content": VALID_INVOICE_XML,
        },
    )

    assert response.status_code == 422
    assert "safe XML filename" in response.text
