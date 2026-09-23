from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

MODULO_97 = 97
QR_REFERENCE_CHECKSUM_TABLE = (0, 9, 4, 6, 8, 2, 7, 1, 3, 5)


def _remove_spaces_and_uppercase(value: str) -> str:
    return value.replace(" ", "").upper()


def _iso_modulo_97(value: str) -> int:
    rearranged = value[4:] + value[:4]
    remainder = 0
    for character in rearranged:
        digits = str(int(character, 36)) if character.isalpha() else character
        for digit in digits:
            remainder = (remainder * 10 + int(digit)) % MODULO_97
    return remainder


def normalize_iban(value: str) -> str:
    return _remove_spaces_and_uppercase(value)


def is_qr_iban(value: str) -> bool:
    normalized = normalize_iban(value)
    if len(normalized) < 9 or normalized[:2] not in {"CH", "LI"}:
        return False
    iid = normalized[4:9]
    return iid.isdigit() and 30000 <= int(iid) <= 31999


def is_valid_swiss_iban(value: str) -> bool:
    normalized = normalize_iban(value)
    if len(normalized) != 21 or normalized[:2] not in {"CH", "LI"} or not normalized.isalnum():
        return False
    return _iso_modulo_97(normalized) == 1


def is_valid_iso11649_reference(value: str) -> bool:
    normalized = _remove_spaces_and_uppercase(value)
    if not normalized.startswith("RF") or not (5 <= len(normalized) <= 25) or not normalized.isalnum():
        return False
    return _iso_modulo_97(normalized) == 1


def is_valid_qr_reference(value: str) -> bool:
    normalized = value.replace(" ", "")
    if len(normalized) != 27 or not normalized.isdigit():
        return False

    carry = 0
    for digit in normalized:
        carry = QR_REFERENCE_CHECKSUM_TABLE[(carry + int(digit)) % 10]
    return carry == 0


class Party(BaseModel):
    name: str = Field(..., min_length=1, max_length=70)
    street: str = Field(..., min_length=1, max_length=70)
    house_number: str = Field("", max_length=16)
    postal_code: str = Field(..., min_length=1, max_length=16)
    city: str = Field(..., min_length=1, max_length=35)
    country_code: str = Field(..., min_length=2, max_length=2)

    @field_validator("country_code")
    @classmethod
    def uppercase_country_code(cls, value: str) -> str:
        return value.upper()


class QrBillRequest(BaseModel):
    account: str = Field(..., min_length=5, max_length=34)
    creditor: Party
    debtor: Party
    amount: Decimal | None = Field(None, gt=Decimal("0"), le=Decimal("999999999.99"))
    currency: Literal["CHF", "EUR"] = "CHF"
    reference: str = Field("", max_length=27)
    message: str = Field("", max_length=140)
    bill_information: str = Field("", max_length=140)
    invoice_number: str = Field("", max_length=35)
    invoice_date: date | None = None
    service_description: str = Field("", max_length=350)
    service_date_begin: date | None = None
    service_date_end: date | None = None
    service_quantity: Decimal = Field(Decimal("1"), gt=Decimal("0"))
    service_unit_price: Decimal | None = Field(None, ge=Decimal("0"))

    @field_validator("account")
    @classmethod
    def normalize_account(cls, value: str) -> str:
        normalized = normalize_iban(value)
        if not is_valid_swiss_iban(normalized):
            raise ValueError("Account must be a valid Swiss or Liechtenstein IBAN.")
        return normalized

    @field_validator("reference")
    @classmethod
    def normalize_reference(cls, value: str) -> str:
        return _remove_spaces_and_uppercase(value)

    @model_validator(mode="after")
    def validate_reference_rules(self) -> "QrBillRequest":
        if is_qr_iban(self.account):
            if not self.reference:
                raise ValueError("QR-IBAN payments require a QR reference.")
            if not is_valid_qr_reference(self.reference):
                raise ValueError("QR-IBAN payments require a valid 27-digit QR reference.")
            return self

        if not self.reference:
            return self
        if not is_valid_iso11649_reference(self.reference):
            raise ValueError("Non-QR IBAN payments require a valid ISO 11649 creditor reference.")
        return self

    @model_validator(mode="after")
    def validate_invoice_line(self) -> "QrBillRequest":
        if self.service_date_begin and self.service_date_end and self.service_date_end < self.service_date_begin:
            raise ValueError("Service end date must not be before its start date.")
        if self.amount is not None and self.service_unit_price is not None:
            line_total = (self.service_quantity * self.service_unit_price).quantize(Decimal("0.01"))
            if line_total != self.amount.quantize(Decimal("0.01")):
                raise ValueError("Invoice line total must equal the QR bill amount.")
        return self


class ReimbursementSlipRequest(BaseModel):
    provider_name: str = Field(..., min_length=1, max_length=70)
    insurer_name: str = Field(..., min_length=1, max_length=70)
    insured_person: str = Field(..., min_length=1, max_length=70)
    invoice_number: str = Field(..., min_length=1, max_length=35)
    treatment_period: str = Field(..., min_length=1, max_length=70)
    amount: Decimal = Field(..., gt=Decimal("0"))
    currency: Literal["CHF", "EUR"] = "CHF"
    notes: str = Field("", max_length=500)


class XmlAttachmentRequest(BaseModel):
    title: str = Field("Tarif 595 XML attachment", min_length=1, max_length=140)
    filename: str = Field("invoice.xml", min_length=1, max_length=140)
    xml_content: str = Field(..., min_length=1, max_length=10000)


class InvoiceCompany(BaseModel):
    name: str = Field(..., min_length=1, max_length=35)
    street: str = Field(..., min_length=1, max_length=35)
    house_number: str = Field("", max_length=10)
    postal_code: str = Field(..., min_length=1, max_length=9)
    city: str = Field(..., min_length=1, max_length=35)


class InvoicePatient(BaseModel):
    family_name: str = Field(..., min_length=1, max_length=35)
    given_name: str = Field(..., min_length=1, max_length=35)
    gender: Literal["male", "female"]
    birthdate: date
    ssn: str = Field(..., pattern=r"^(?:[0-9]{4,10}|756[0-9]{10}|438[0-9]{10})$")
    street: str = Field(..., min_length=1, max_length=35)
    house_number: str = Field("", max_length=10)
    postal_code: str = Field(..., min_length=1, max_length=9)
    city: str = Field(..., min_length=1, max_length=35)


class Tarif595Service(BaseModel):
    code: str = Field(..., min_length=1, max_length=30)
    name: str = Field(..., min_length=1, max_length=350)
    date_begin: date
    date_end: date
    quantity: Decimal = Field(..., gt=Decimal("0"))
    unit_price: Decimal = Field(..., ge=Decimal("0"))
    vat_rate: Decimal = Field(Decimal("0"), ge=Decimal("0"), le=Decimal("100"))

    @model_validator(mode="after")
    def validate_date_range(self) -> "Tarif595Service":
        if self.date_end < self.date_begin:
            raise ValueError("Service end date must not be before its start date.")
        return self

    @property
    def amount(self) -> Decimal:
        return (self.quantity * self.unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class Tarif595Request(BaseModel):
    qr_bill: QrBillRequest
    invoice_number: str = Field(..., min_length=1, max_length=35)
    invoice_date: date
    provider_gln: str = Field(..., pattern=r"^[0-9]{13}$")
    provider_location_gln: str = Field(..., pattern=r"^[0-9]{13}$")
    provider_zsr: str | None = Field(None, pattern=r"^[A-Z][0-9]{6}$")
    insurer_gln: str = Field(..., pattern=r"^[0-9]{13}$")
    insurer: InvoiceCompany
    patient: InvoicePatient
    canton: Literal[
        "AG",
        "AI",
        "AR",
        "BE",
        "BL",
        "BS",
        "FR",
        "GE",
        "GL",
        "GR",
        "JU",
        "LU",
        "NE",
        "NW",
        "OW",
        "SG",
        "SH",
        "SO",
        "SZ",
        "TG",
        "TI",
        "UR",
        "VD",
        "VS",
        "ZG",
        "ZH",
        "LI",
    ]
    service: Tarif595Service
    notes: str = Field("", max_length=350)

    @field_validator("provider_zsr")
    @classmethod
    def normalize_zsr(cls, value: str | None) -> str | None:
        return value.upper() if value else None

    @model_validator(mode="after")
    def validate_invoice_consistency(self) -> "Tarif595Request":
        if self.qr_bill.amount is None:
            raise ValueError("Tarif 595 documents require a QR bill amount.")
        if self.qr_bill.amount.quantize(Decimal("0.01")) != self.service.amount:
            raise ValueError("QR bill amount must equal quantity multiplied by unit price.")
        if self.qr_bill.currency != "CHF":
            raise ValueError("generalInvoiceRequest 5.0 requires CHF.")
        xsd_limits = {
            "creditor name": (self.qr_bill.creditor.name, 35),
            "creditor street": (self.qr_bill.creditor.street, 35),
            "creditor house number": (self.qr_bill.creditor.house_number, 10),
            "creditor postal code": (self.qr_bill.creditor.postal_code, 9),
        }
        for label, (value, maximum) in xsd_limits.items():
            if len(value) > maximum:
                raise ValueError(f"Tarif 595 {label} must not exceed {maximum} characters.")
        return self
