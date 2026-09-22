from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


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
    amount: Decimal = Field(..., gt=Decimal("0"))
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
            if not self.reference.isdigit():
                raise ValueError("QR-IBAN payments require a numeric QR reference.")
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


class XmlAttachmentRequest(BaseModel):
    title: str = Field("Tarif 595 XML attachment", min_length=1, max_length=140)
    filename: str = Field("invoice.xml", min_length=1, max_length=140)
    xml_content: str = Field(..., min_length=1, max_length=10000)
