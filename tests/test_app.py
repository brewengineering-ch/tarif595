from pathlib import Path
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import app


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
