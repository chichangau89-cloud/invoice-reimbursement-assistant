from datetime import datetime
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.core.ids import validate_key
from app.schemas import InvoiceIn, AuditResult


class ClaimData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    applicant_name: str = Field(min_length=1, max_length=100)
    department: str = Field(min_length=1, max_length=100)
    expense_type: str = Field(min_length=1, max_length=64)
    amount: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    currency: str = "CNY"
    business_purpose: str = Field(min_length=1, max_length=2000)
    approval_status: Literal["pending", "approved", "rejected"] = "pending"

    @field_validator("currency")
    @classmethod
    def currency_valid(cls, value):
        return InvoiceIn.validate_currency(value)

    @field_validator("applicant_name", "department", "expense_type", "business_purpose")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()


class ClaimCreate(ClaimData):
    tenant_id: str
    claim_no: str

    @field_validator("tenant_id", "claim_no")
    @classmethod
    def key_valid(cls, value):
        return validate_key(value)


class ClaimUpdate(ClaimData):
    expected_version: int = Field(ge=1)


class ClaimOut(ClaimCreate):
    version: int
    status: Literal["draft", "audited"]
    latest_audit_id: str | None
    created_at: datetime
    updated_at: datetime


class SavedAudit(AuditResult):
    audit_id: str
    claim_version: int
    stale: bool
    created_at: datetime
    input_snapshot: dict
