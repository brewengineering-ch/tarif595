from __future__ import annotations

from base64 import b64encode
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
import zlib
from zoneinfo import ZoneInfo

from lxml import etree


INVOICE_NAMESPACE = "http://www.forum-datenaustausch.ch/invoice"
NAMESPACES = {"invoice": INVOICE_NAMESPACE}
SCHEMA_PATH = Path(__file__).resolve().parents[1] / "docs" / "generalInvoiceRequest_500.xsd"
MAX_QR_SYMBOLS = 16
MAX_QR_PAYLOAD_SIZE = 1000
SWISS_TIMEZONE = ZoneInfo("Europe/Zurich")
EXTERNAL_SCHEMAS = {
    "http://www.w3.org/TR/xmldsig-core/xmldsig-core-schema.xsd": b"""\
<schema xmlns="http://www.w3.org/2001/XMLSchema"
        targetNamespace="http://www.w3.org/2000/09/xmldsig#"
        elementFormDefault="qualified">
  <element name="Signature" type="anyType"/>
</schema>""",
    "http://www.w3.org/TR/xmlenc-core1/xenc-schema.xsd": b"""\
<schema xmlns="http://www.w3.org/2001/XMLSchema"
        targetNamespace="http://www.w3.org/2001/04/xmlenc#"
        elementFormDefault="qualified">
  <element name="EncryptedData" type="anyType"/>
</schema>""",
}


@dataclass(frozen=True)
class XmlAttachmentMetadata:
    guid: str
    language: str
    tiers: str
    request_id: str
    request_date: datetime
    patient: str


class _OfflineSchemaResolver(etree.Resolver):
    def resolve(self, url: str, public_id: str | None, context: object):
        schema = EXTERNAL_SCHEMAS.get(url)
        if schema is None:
            return None
        return self.resolve_string(schema, context)


def encode_xml_attachment(xml_content: str) -> str:
    compressor = zlib.compressobj(level=9, wbits=-15)
    compressed = compressor.compress(xml_content.encode("utf-8")) + compressor.flush()
    return b64encode(compressed).decode("ascii")


@lru_cache(maxsize=1)
def _schema() -> etree.XMLSchema:
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    parser.resolvers.add(_OfflineSchemaResolver())
    return etree.XMLSchema(etree.parse(SCHEMA_PATH, parser))


def _parse_xml(xml_content: str) -> etree._Element:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False)
    try:
        return etree.fromstring(xml_content.encode("utf-8"), parser)
    except etree.XMLSyntaxError as exc:
        raise ValueError(f"XML is not well-formed: {exc.msg}") from exc


def validate_xml_attachment(xml_content: str) -> None:
    root = _parse_xml(xml_content)
    if not _schema().validate(root):
        error = _schema().error_log.last_error
        detail = error.message if error is not None else "unknown schema error"
        raise ValueError(f"XML does not conform to General Invoice Request 5.0: {detail}")

    payload = encode_xml_attachment(xml_content)
    if len(payload) > MAX_QR_SYMBOLS * MAX_QR_PAYLOAD_SIZE:
        raise ValueError("XML is too large to encode in the maximum 16 QR symbols")


def _required_attribute(element: etree._Element | None, name: str) -> str:
    if element is None or not element.get(name):
        raise ValueError(f"Validated XML is missing required metadata: {name}")
    return element.get(name, "")


def extract_xml_attachment_metadata(xml_content: str) -> XmlAttachmentMetadata:
    root = _parse_xml(xml_content)
    invoice = root.find("invoice:payload/invoice:invoice", NAMESPACES)
    patients = root.xpath(
        "invoice:payload/invoice:body/*[starts-with(local-name(), 'tiers_')]/invoice:patient",
        namespaces=NAMESPACES,
    )
    if not patients:
        raise ValueError("Validated XML is missing patient data")
    patient = patients[0]

    person = patient.find("invoice:person", NAMESPACES)
    postal = person.find("invoice:postal", NAMESPACES) if person is not None else None
    if person is None or postal is None:
        raise ValueError("Validated XML is missing patient address data")

    street = postal.find("invoice:street", NAMESPACES)
    street_value = (street.text or "").strip() if street is not None else ""
    patient_parts = [
        " ".join(
            filter(
                None,
                [
                    (person.findtext("invoice:givenname", namespaces=NAMESPACES) or "").strip(),
                    (person.findtext("invoice:familyname", namespaces=NAMESPACES) or "").strip(),
                ],
            )
        ),
        street_value,
        " ".join(
            filter(
                None,
                [
                    (postal.findtext("invoice:zip", namespaces=NAMESPACES) or "").strip(),
                    (postal.findtext("invoice:city", namespaces=NAMESPACES) or "").strip(),
                ],
            )
        ),
        f"Geburtsdatum: {_required_attribute(patient, 'birthdate')}",
        f"Geschlecht: {_required_attribute(patient, 'gender')}",
    ]

    tiers_element = patient.getparent()
    tiers_map = {"tiers_garant": "G", "tiers_payant": "P", "tiers_soldant": "S"}
    tiers = tiers_map.get(etree.QName(tiers_element).localname, "G")

    return XmlAttachmentMetadata(
        guid=_required_attribute(root, "guid"),
        language=_required_attribute(root, "language"),
        tiers=tiers,
        request_id=_required_attribute(invoice, "request_id"),
        request_date=datetime.fromtimestamp(
            int(_required_attribute(invoice, "request_timestamp")),
            tz=SWISS_TIMEZONE,
        ),
        patient=" · ".join(part for part in patient_parts if part),
    )
