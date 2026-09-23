import base64
from io import BytesIO
from pathlib import Path
import sys
import zlib

from fastapi.testclient import TestClient
from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app
from app.invoice_xml import create_tarif595_xml, validate_tarif595_xml
from app.models import QrBillRequest, Tarif595Request
from app.pdf import build_annex_qr_payloads, build_swiss_qr_payload


client = TestClient(app)


def tarif595_payload() -> dict:
    return {
        "qr_bill": {
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
            "invoice_number": "T595-2026-0001",
            "invoice_date": "2026-09-16",
            "service_description": "Health promotion service",
            "service_date_begin": "2026-09-01",
            "service_date_end": "2026-09-15",
            "service_quantity": "1",
            "service_unit_price": "125.40",
        },
        "invoice_number": "T595-2026-0001",
        "invoice_date": "2026-09-16",
        "provider_gln": "7601001302112",
        "provider_location_gln": "7601001302112",
        "provider_zsr": "Q987654",
        "insurer_gln": "7634567890000",
        "insurer": {
            "name": "Example Versicherung",
            "street": "Kassengraben",
            "house_number": "222",
            "postal_code": "4000",
            "city": "Basel",
        },
        "patient": {
            "given_name": "Max",
            "family_name": "Muster",
            "gender": "male",
            "birthdate": "1980-12-01",
            "ssn": "7561234567890",
            "street": "Musterweg",
            "house_number": "5",
            "postal_code": "3000",
            "city": "Bern",
        },
        "canton": "ZH",
        "service": {
            "code": "595.100",
            "name": "Health promotion service",
            "date_begin": "2026-09-01",
            "date_end": "2026-09-15",
            "quantity": "1",
            "unit_price": "125.40",
            "vat_rate": "0",
        },
        "notes": "Generated for direct reimbursement.",
    }


def test_index_exposes_all_document_types() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "Swiss QR bill" in response.text
    assert "Tarif 595 invoice" in response.text
    assert 'id="qr-section"' in response.text
    assert 'id="tarif-section"' in response.text
    assert "Generate human-readable PDF" in response.text
    assert "Generate machine-readable PDF" in response.text
    assert "Generate combined PDF" in response.text


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
            "invoice_number": "T595-2026-0001",
            "invoice_date": "2026-09-16",
            "service_description": "Health promotion service",
            "service_date_begin": "2026-09-01",
            "service_date_end": "2026-09-15",
            "service_quantity": "1",
            "service_unit_price": "125.40",
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
    assert "INVOICE" in text
    assert "T595-2026-0001" in text
    assert "Example Practice AG" in text
    assert "Max Muster" in text
    assert "Health promotion service" in text
    assert "CHF 125.40" in text


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


def test_qr_bill_generation_rejects_invalid_iban() -> None:
    payload = tarif595_payload()["qr_bill"]
    payload["account"] = "CH4431999123000889013"

    response = client.post("/api/qr-bill", json=payload)

    assert response.status_code == 422
    assert "valid Swiss or Liechtenstein IBAN" in response.text


def test_qr_bill_generation_requires_reference_for_qr_iban() -> None:
    payload = tarif595_payload()["qr_bill"]
    payload["reference"] = ""

    response = client.post("/api/qr-bill", json=payload)

    assert response.status_code == 422
    assert "require a QR reference" in response.text


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
            "amount": "125.40",
            "currency": "CHF",
            "notes": "Generated for direct reimbursement.",
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


def test_xml_attachment_generation_returns_pdf() -> None:
    response = client.post(
        "/api/xml-attachment",
        json={
            "title": "Tarif 595 XML attachment",
            "filename": "invoice.xml",
            "xml_content": '<invoice version="5.0"><total currency="CHF">125.40</total></invoice>',
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    attachments = PdfReader(BytesIO(response.content)).attachments
    assert attachments["invoice.xml"][0] == b'<invoice version="5.0"><total currency="CHF">125.40</total></invoice>'


def test_xml_attachment_sanitizes_content_disposition_filename() -> None:
    response = client.post(
        "/api/xml-attachment",
        json={
            "title": "Tarif 595 XML attachment",
            "filename": 'bad"\r\nname.xml',
            "xml_content": '<invoice version="5.0"><total currency="CHF">125.40</total></invoice>',
        },
    )

    assert response.status_code == 200
    assert 'filename="bad_name.pdf"' in response.headers["content-disposition"]
    assert "%0D%0A" in response.headers["content-disposition"]


def test_tarif595_xml_conforms_to_general_invoice_request_500_schema() -> None:
    content = create_tarif595_xml(Tarif595Request.model_validate(tarif595_payload()))

    validate_tarif595_xml(content)
    assert b'tariff_type="595"' in content
    assert b'type="VVG"' in content


def test_annex_qr_payloads_reconstruct_the_xml() -> None:
    content = create_tarif595_xml(Tarif595Request.model_validate(tarif595_payload()))
    payloads = build_annex_qr_payloads(content)

    assert all(len(payload) == 1262 for payload in payloads)
    compressed = base64.b64decode("".join(payloads).rstrip())
    assert zlib.decompress(compressed, wbits=-15) == content


def test_tarif595_document_endpoints_return_expected_pdfs() -> None:
    responses = {
        name: client.post(f"/api/tarif595/{name}", json=tarif595_payload())
        for name in ("human-readable", "machine-readable", "combined")
    }

    for response in responses.values():
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.content.startswith(b"%PDF")

    machine = PdfReader(BytesIO(responses["machine-readable"].content))
    machine_text = "\n".join(page.extract_text() for page in machine.pages)
    human_text = PdfReader(BytesIO(responses["human-readable"].content)).pages[0].extract_text()
    combined = PdfReader(BytesIO(responses["combined"].content))
    assert "Rückforderungsbeleg" in human_text
    assert "Rechnungs-" in human_text
    assert "steller" in human_text
    assert "Patient" in human_text
    assert "Leistungs-" in human_text
    assert "erbringer" in human_text
    assert "Tarifziffer / Leistung" in human_text
    assert "595" in human_text
    assert "Gesamtbetrag:" in human_text
    assert "Rückforderungsbeleg QR-Code Blatt" in machine_text
    assert "Release 5.0/Annex/de" in machine_text
    assert "QR-Code 1" in machine_text
    assert "PatientIn:" in machine_text
    assert machine.attachments["T595-2026-0001.xml"][0].startswith(b"<?xml")
    assert len(combined.pages) == 3
    assert combined.attachments["T595-2026-0001.xml"][0].startswith(b"<?xml")


def test_tarif595_documents_reject_mismatched_totals() -> None:
    payload = tarif595_payload()
    payload["service"]["unit_price"] = "120.00"

    response = client.post("/api/tarif595/combined", json=payload)

    assert response.status_code == 422
    assert "must equal quantity multiplied by unit price" in response.text
