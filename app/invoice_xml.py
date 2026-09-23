from datetime import UTC, datetime, time
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from lxml import etree

from app.models import InvoiceCompany, InvoicePatient, Party, Tarif595Request

INVOICE_NAMESPACE = "http://www.forum-datenaustausch.ch/invoice"
XSI_NAMESPACE = "http://www.w3.org/2001/XMLSchema-instance"
SCHEMA_DIRECTORY = Path(__file__).with_name("schemas")


def _tag(name: str) -> str:
    return f"{{{INVOICE_NAMESPACE}}}{name}"


def _element(parent: etree._Element, tag_name: str, **attributes: object) -> etree._Element:
    return etree.SubElement(
        parent,
        _tag(tag_name),
        **{key: str(value) for key, value in attributes.items() if value is not None and value != ""},
    )


def _text_element(parent: etree._Element, tag_name: str, text: object) -> etree._Element:
    element = _element(parent, tag_name)
    element.text = str(text)
    return element


def _postal(parent: etree._Element, party: Party | InvoiceCompany | InvoicePatient) -> None:
    postal = _element(parent, "postal")
    street_text = f"{party.street} {party.house_number}".strip()
    street = _text_element(postal, "street", street_text)
    street.set("street_name", party.street)
    if party.house_number:
        street.set("house_no", party.house_number)
    _text_element(postal, "zip", party.postal_code)
    _text_element(postal, "city", party.city)


def _company(parent: etree._Element, party: Party | InvoiceCompany) -> None:
    company = _element(parent, "company")
    _text_element(company, "companyname", party.name)
    _postal(company, party)


def _person(parent: etree._Element, patient: InvoicePatient) -> None:
    person = _element(parent, "person")
    _text_element(person, "familyname", patient.family_name)
    _text_element(person, "givenname", patient.given_name)
    _postal(person, patient)


def _money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"


class _SchemaResolver(etree.Resolver):
    def resolve(self, url: str, public_id: str | None, context: object) -> object | None:
        if url.endswith("xmldsig-core-schema.xsd"):
            return self.resolve_filename(str(SCHEMA_DIRECTORY / "xmldsig-core-schema.xsd"), context)
        if url.endswith("xenc-schema.xsd"):
            return self.resolve_filename(str(SCHEMA_DIRECTORY / "xenc-schema.xsd"), context)
        return None


@lru_cache(maxsize=1)
def _invoice_schema() -> etree.XMLSchema:
    parser = etree.XMLParser(load_dtd=False, no_network=True)
    parser.resolvers.add(_SchemaResolver())
    document = etree.parse(str(SCHEMA_DIRECTORY / "generalInvoiceRequest_500.xsd"), parser)
    return etree.XMLSchema(document)


def validate_tarif595_xml(content: bytes) -> None:
    document = etree.fromstring(content)
    _invoice_schema().assertValid(document)


def create_tarif595_xml(request: Tarif595Request) -> bytes:
    root = etree.Element(
        _tag("request"),
        nsmap={"invoice": INVOICE_NAMESPACE, "xsi": XSI_NAMESPACE},
        language="de",
        modus="production",
        guid=uuid4().hex,
        validation_status="0",
    )
    root.set(
        f"{{{XSI_NAMESPACE}}}schemaLocation",
        f"{INVOICE_NAMESPACE} generalInvoiceRequest_500.xsd",
    )

    processing = _element(root, "processing")
    _element(processing, "transport", **{"from": request.provider_gln, "to": request.insurer_gln})

    payload = _element(root, "payload", request_type="invoice", request_subtype="normal")
    invoice_datetime = datetime.combine(request.invoice_date, time.min, tzinfo=UTC)
    _element(
        payload,
        "invoice",
        request_timestamp=int(invoice_datetime.timestamp()),
        request_date=f"{request.invoice_date.isoformat()}T00:00:00",
        request_id=request.invoice_number,
    )
    body = _element(payload, "body", role="other", place="company")
    prolog = _element(body, "prolog")
    _element(prolog, "generator", name="tarif595", version="1")
    if request.notes:
        _text_element(body, "remark", request.notes)

    reimbursement = _element(body, "tiers_garant")
    billers = _element(reimbursement, "billers")
    biller = _element(billers, "biller_gln", gln=request.provider_gln)
    _company(biller, request.qr_bill.creditor)
    if request.provider_zsr:
        biller_zsr = _element(billers, "biller_zsr", zsr=request.provider_zsr)
        _company(biller_zsr, request.qr_bill.creditor)

    debitor = _element(reimbursement, "debitor", gln=request.insurer_gln)
    _company(debitor, request.insurer)

    providers = _element(reimbursement, "providers")
    provider = _element(
        providers,
        "provider_gln",
        gln=request.provider_gln,
        gln_location=request.provider_location_gln,
    )
    _company(provider, request.qr_bill.creditor)
    if request.provider_zsr:
        provider_zsr = _element(providers, "provider_zsr", zsr=request.provider_zsr)
        _company(provider_zsr, request.qr_bill.creditor)

    insurance = _element(reimbursement, "insurance", gln=request.insurer_gln)
    _company(insurance, request.insurer)

    patient = _element(
        reimbursement,
        "patient",
        gender=request.patient.gender,
        sex=request.patient.gender,
        birthdate=request.patient.birthdate.isoformat(),
        ssn=request.patient.ssn,
    )
    _person(patient, request.patient)
    guarantor = _element(reimbursement, "guarantor")
    _person(guarantor, request.patient)
    _element(reimbursement, "partners")

    amount = request.service.amount
    vat_rate = request.service.vat_rate
    vat_amount = (amount - amount / (Decimal("1") + vat_rate / Decimal("100")) if vat_rate else Decimal("0")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    balance = _element(
        reimbursement,
        "balance",
        currency="CHF",
        amount=_money(amount),
        amount_due=_money(amount),
    )
    vat = _element(balance, "vat", vat=_money(vat_amount))
    _element(
        vat,
        "vat_rate",
        vat_rate=_money(vat_rate),
        amount=_money(amount),
        vat=_money(vat_amount),
    )

    payment_name = "esrQR" if request.qr_bill.reference.isdigit() else "esrQRRed"
    payment_attributes: dict[str, str] = {
        "iban": request.qr_bill.account,
        "payment_reason": request.qr_bill.message,
    }
    if request.qr_bill.reference:
        payment_attributes["reference_number"] = request.qr_bill.reference
    payment = _element(body, payment_name, **payment_attributes)
    creditor = _element(payment, "creditor")
    _company(creditor, request.qr_bill.creditor)

    _element(body, "law", type="VVG")
    _element(
        body,
        "treatment",
        date_begin=request.service.date_begin.isoformat(),
        date_end=request.service.date_end.isoformat(),
        canton=request.canton,
        reason="prevention",
    )
    services = _element(body, "services")
    _element(
        services,
        "service",
        record_id="1",
        tariff_type="595",
        code=request.service.code,
        name=request.service.name,
        quantity=str(request.service.quantity),
        date_begin=f"{request.service.date_begin.isoformat()}T00:00:00",
        date_end=f"{request.service.date_end.isoformat()}T00:00:00",
        provider_id=request.provider_gln,
        responsible_id=request.provider_gln,
        unit=_money(request.service.unit_price),
        amount=_money(amount),
        vat_rate=_money(vat_rate),
    )

    content = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=False)
    validate_tarif595_xml(content)
    return content
