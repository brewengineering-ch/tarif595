from io import BytesIO
from pathlib import Path
import sys

from fastapi.testclient import TestClient
from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app
from app.models import QrBillRequest
from app.pdf import build_swiss_qr_payload


client = TestClient(app)


def test_index_exposes_all_document_types() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "Swiss QR bill" in response.text
    assert "Rückforderungsbeleg" in response.text
    assert "XML attachment" in response.text


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
