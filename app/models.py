from datetime import date, datetime
from decimal import Decimal
import re
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from app.xml_attachment import validate_xml_attachment


def normalize_iban(value: str) -> str:
    return value.replace(" ", "").upper()


def is_qr_iban(value: str) -> bool:
    normalized = normalize_iban(value)
    if len(normalized) < 9 or normalized[:2] not in {"CH", "LI"}:
        return False
    iid = normalized[4:9]
    return iid.isdigit() and 30000 <= int(iid) <= 31999


def is_valid_iso11649_reference(value: str) -> bool:
    normalized = value.replace(" ", "").upper()
    if not normalized.startswith("RF") or not (5 <= len(normalized) <= 25) or not normalized.isalnum():
        return False

    rearranged = normalized[4:] + normalized[:4]
    expanded = "".join(str(int(character, 36)) if character.isalpha() else character for character in rearranged)

    remainder = 0
    for character in expanded:
        remainder = (remainder * 10 + int(character)) % 97
    return remainder == 1


def is_valid_qr_reference(value: str) -> bool:
    normalized = value.replace(" ", "")
    if len(normalized) != 27 or not normalized.isdigit():
        return False

    table = [0, 9, 4, 6, 8, 2, 7, 1, 3, 5]
    carry = 0
    for digit in normalized:
        carry = table[(carry + int(digit)) % 10]
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
    amount: Decimal | None = Field(None, gt=Decimal("0"))
    currency: Literal["CHF", "EUR"] = "CHF"
    reference: str = Field("", max_length=27)
    message: str = Field("", max_length=140)
    bill_information: str = Field("", max_length=140)

    @field_validator("account")
    @classmethod
    def normalize_account(cls, value: str) -> str:
        return normalize_iban(value)

    @field_validator("reference")
    @classmethod
    def normalize_reference(cls, value: str) -> str:
        return value.replace(" ", "").upper()

    @model_validator(mode="after")
    def validate_reference_rules(self) -> "QrBillRequest":
        if not self.reference:
            return self

        if is_qr_iban(self.account):
            if not is_valid_qr_reference(self.reference):
                raise ValueError("QR-IBAN payments require a valid 27-digit QR reference.")
            return self

        if not is_valid_iso11649_reference(self.reference):
            raise ValueError("Non-QR IBAN payments require a valid ISO 11649 creditor reference.")
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
    document_guid: str = Field(default_factory=lambda: uuid4().hex, pattern=r"^[0-9A-Fa-f]{32}$")
    language: Literal["de", "fr", "it"] = "de"
    tiers: Literal["G", "P", "S"] = "G"


class XmlAttachmentRequest(BaseModel):
    filename: str = Field("invoice.xml", min_length=1, max_length=140)
    xml_content: str = Field(..., min_length=1, max_length=100000)

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,250}\.xml", value, re.IGNORECASE):
            raise ValueError("filename must be a safe XML filename")
        return value

    @field_validator("xml_content")
    @classmethod
    def validate_xml_content(cls, value: str) -> str:
        validate_xml_attachment(value)
        return value


class Patient(BaseModel):
    given_name: str = Field(..., min_length=1, max_length=35)
    family_name: str = Field(..., min_length=1, max_length=35)
    street: str = Field(..., min_length=1, max_length=70)
    house_number: str = Field("", max_length=16)
    postal_code: str = Field(..., min_length=1, max_length=16)
    city: str = Field(..., min_length=1, max_length=35)
    country_code: str = Field("CH", min_length=2, max_length=2)
    birthdate: date
    gender: Literal["male", "female", "diverse"]
    sex: Literal["male", "female"]
    ssn: str = Field(..., pattern=r"^(?:[0-9]{4,10}|756[0-9]{10}|438[0-9]{10})$")

    @field_validator("country_code")
    @classmethod
    def uppercase_country_code(cls, value: str) -> str:
        return value.upper()

    @property
    def name(self) -> str:
        return f"{self.given_name} {self.family_name}"

    def as_party(self) -> Party:
        return Party(
            name=self.name,
            street=self.street,
            house_number=self.house_number,
            postal_code=self.postal_code,
            city=self.city,
            country_code=self.country_code,
        )


class InvoiceRequest(BaseModel):
    invoice_number: str = Field(..., min_length=1, max_length=35)
    invoice_date: datetime
    document_guid: str = Field(default_factory=lambda: uuid4().hex, pattern=r"^[0-9A-Fa-f]{32}$")
    language: Literal["de", "fr", "it"] = "de"
    tiers: Literal["G", "P", "S"] = "G"

    practice: Party
    practice_gln: str = Field(..., pattern=r"^[0-9]{13}$")
    insurer: Party
    insurer_gln: str = Field(..., pattern=r"^[0-9]{13}$")
    patient: Patient

    account: str = Field(..., min_length=5, max_length=34)
    reference: str = Field("", max_length=27)
    amount: Decimal = Field(..., gt=Decimal("0"))
    message: str = Field("", max_length=140)
    notes: str = Field("", max_length=350)

    treatment_begin: date
    treatment_end: date
    canton: Literal[
        "AG", "AI", "AR", "BE", "BL", "BS", "FR", "GE", "GL", "GR", "JU",
        "LU", "NE", "NW", "OW", "SG", "SH", "SO", "SZ", "TI", "TG", "UR",
        "VD", "VS", "ZG", "ZH", "LI",
    ]
    treatment_reason: Literal["disease", "accident", "maternity", "prevention", "birthdefect", "unknown"] = "disease"
    role: Literal["physician", "physiotherapist", "psychologist", "other"] = "psychologist"

    tariff_type: str = Field("595", pattern=r"^[0-9A-Z]{3}$")
    service_code: str = Field(..., min_length=1, max_length=30)
    service_name: str = Field(..., min_length=1, max_length=350)
    quantity: Decimal = Field(Decimal("1"), gt=Decimal("0"))

    @field_validator("account")
    @classmethod
    def normalize_account(cls, value: str) -> str:
        return normalize_iban(value)

    @field_validator("reference")
    @classmethod
    def normalize_reference(cls, value: str) -> str:
        return value.replace(" ", "").upper()

    @model_validator(mode="after")
    def validate_invoice(self) -> "InvoiceRequest":
        QrBillRequest(
            account=self.account,
            creditor=self.practice,
            debtor=self.patient.as_party(),
            amount=self.amount,
            currency="CHF",
            reference=self.reference,
            message=self.message,
            bill_information="Tarif 595",
        )
        if self.treatment_end < self.treatment_begin:
            raise ValueError("treatment_end must not be before treatment_begin")
        return self

    def qr_bill_request(self) -> QrBillRequest:
        return QrBillRequest(
            account=self.account,
            creditor=self.practice,
            debtor=self.patient.as_party(),
            amount=self.amount,
            currency="CHF",
            reference=self.reference,
            message=self.message,
            bill_information=f"Tarif 595 / {self.invoice_number}",
        )

    def reimbursement_request(self) -> ReimbursementSlipRequest:
        return ReimbursementSlipRequest(
            provider_name=self.practice.name,
            insurer_name=self.insurer.name,
            insured_person=self.patient.name,
            invoice_number=self.invoice_number,
            treatment_period=f"{self.treatment_begin.isoformat()} to {self.treatment_end.isoformat()}",
            amount=self.amount,
            currency="CHF",
            notes=self.notes,
            document_guid=self.document_guid,
            language=self.language,
            tiers=self.tiers,
        )
