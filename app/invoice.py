from __future__ import annotations

from decimal import Decimal

from lxml import etree

from app.models import InvoiceRequest, Party, Patient, is_qr_iban
from app.xml_attachment import INVOICE_NAMESPACE, validate_xml_attachment


NSMAP = {
    "invoice": INVOICE_NAMESPACE,
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
    "xenc": "http://www.w3.org/2001/04/xmlenc#",
    "ds": "http://www.w3.org/2000/09/xmldsig#",
}


def _element(parent: etree._Element, element_name: str, **attributes: object) -> etree._Element:
    return etree.SubElement(
        parent,
        etree.QName(INVOICE_NAMESPACE, element_name),
        {key: str(value) for key, value in attributes.items() if value is not None},
    )


def _postal(parent: etree._Element, party: Party | Patient) -> None:
    postal = _element(parent, "postal")
    street_value = f"{party.street} {party.house_number}".strip()
    street = _element(
        postal,
        "street",
        street_name=party.street,
        house_no=party.house_number or None,
    )
    street.text = street_value
    _element(postal, "zip").text = party.postal_code
    _element(postal, "city").text = party.city
    country = _element(postal, "country", country_code=party.country_code)
    country.text = party.country_code


def _company(parent: etree._Element, party: Party) -> None:
    company = _element(parent, "company")
    _element(company, "companyname").text = party.name
    _postal(company, party)


def _person(parent: etree._Element, patient: Patient) -> None:
    person = _element(parent, "person")
    _element(person, "familyname").text = patient.family_name
    _element(person, "givenname").text = patient.given_name
    _postal(person, patient)


def _balance(parent: etree._Element, amount: Decimal) -> None:
    balance = _element(
        parent,
        "balance",
        currency="CHF",
        amount=amount,
        amount_due=amount,
    )
    vat = _element(balance, "vat", vat="0")
    _element(vat, "vat_rate", vat_rate="0", amount=amount, vat="0")


def create_invoice_xml(request: InvoiceRequest) -> str:
    timestamp = int(request.invoice_date.timestamp())
    request_date = request.invoice_date.isoformat()
    root = etree.Element(
        etree.QName(INVOICE_NAMESPACE, "request"),
        nsmap=NSMAP,
        language=request.language,
        modus="production",
        guid=request.document_guid,
    )
    root.set(
        etree.QName(NSMAP["xsi"], "schemaLocation"),
        f"{INVOICE_NAMESPACE} generalInvoiceRequest_500.xsd",
    )

    processing = _element(root, "processing")
    _element(
        processing,
        "transport",
        **{"from": request.practice_gln, "to": request.insurer_gln},
    )

    payload = _element(root, "payload", request_type="invoice", request_subtype="normal")
    _element(
        payload,
        "invoice",
        request_timestamp=timestamp,
        request_date=request_date,
        request_id=request.invoice_number,
    )
    body = _element(payload, "body", role=request.role, place="practice")
    prolog = _element(body, "prolog")
    _element(prolog, "generator", name="tarif595", version="1")
    if request.notes:
        _element(body, "remark").text = request.notes

    tiers_names = {"G": "tiers_garant", "P": "tiers_payant", "S": "tiers_soldant"}
    tiers_attributes = {}
    if request.tiers == "P":
        tiers_attributes["allowModification"] = "false"
    elif request.tiers == "S":
        tiers_attributes["allowTS"] = "false"
    tiers = _element(body, tiers_names[request.tiers], **tiers_attributes)

    billers = _element(tiers, "billers")
    biller = _element(billers, "biller_gln", gln=request.practice_gln)
    _company(biller, request.practice)

    debitor = _element(tiers, "debitor", gln="2006666666008")
    _person(debitor, request.patient)

    providers = _element(tiers, "providers")
    provider = _element(
        providers,
        "provider_gln",
        gln=request.practice_gln,
        gln_location=request.practice_gln,
    )
    _company(provider, request.practice)

    insurance = _element(tiers, "insurance", gln=request.insurer_gln)
    _company(insurance, request.insurer)

    patient = _element(
        tiers,
        "patient",
        gender=request.patient.gender,
        sex=request.patient.sex,
        birthdate=request.patient.birthdate.isoformat(),
        ssn=request.patient.ssn,
    )
    _person(patient, request.patient)

    guarantor = _element(tiers, "guarantor")
    _person(guarantor, request.patient)
    _element(tiers, "partners")
    _balance(tiers, request.amount)

    creditor_tag = "esrQR" if is_qr_iban(request.account) else "esrQRRed"
    creditor_attributes: dict[str, object] = {"iban": request.account}
    if request.reference:
        creditor_attributes["reference_number"] = request.reference
    creditor_payment = _element(body, creditor_tag, **creditor_attributes)
    creditor = _element(creditor_payment, "creditor")
    _company(creditor, request.practice)

    _element(body, "law", type="KVG")
    _element(
        body,
        "treatment",
        date_begin=request.treatment_begin.isoformat(),
        date_end=request.treatment_end.isoformat(),
        canton=request.canton,
        treatment="ambulatory",
        reason=request.treatment_reason,
    )
    services = _element(body, "services")
    unit = request.amount / request.quantity
    _element(
        services,
        "service",
        record_id="1",
        tariff_type=request.tariff_type,
        code=request.service_code,
        name=request.service_name,
        quantity=request.quantity,
        date_begin=f"{request.treatment_begin.isoformat()}T00:00:00",
        provider_id=request.practice_gln,
        responsible_id=request.practice_gln,
        unit=unit,
        unit_factor="1",
        amount=request.amount,
        vat_rate="0",
    )

    xml = etree.tostring(
        root,
        encoding="UTF-8",
        xml_declaration=True,
        pretty_print=True,
    ).decode("utf-8")
    validate_xml_attachment(xml)
    return xml
