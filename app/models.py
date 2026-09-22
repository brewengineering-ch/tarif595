from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator


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
