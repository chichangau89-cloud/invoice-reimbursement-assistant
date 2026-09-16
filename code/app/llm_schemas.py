from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExtractedField(StrictModel):
    value: str = Field(min_length=1, max_length=500)
    evidence: str = Field(min_length=1, max_length=2000)


class InvoiceFields(StrictModel):
    invoice_no: ExtractedField | None
    issue_date: ExtractedField | None
    buyer_name: ExtractedField | None
    seller_name: ExtractedField | None
    total_amount: ExtractedField | None
    currency: ExtractedField | None


class ExtractInvoiceRequest(StrictModel):
    text: str = Field(min_length=1, max_length=20000)


class InvoiceExtraction(StrictModel):
    model: str
    fields: InvoiceFields
    missing_fields: list[str]
    needs_confirmation: Literal[True] = True
    usage: dict[str, int]


class AuditExplanation(StrictModel):
    summary: str = Field(min_length=1, max_length=2000)
    cited_policy_ids: list[str] = Field(max_length=10)


class LLMReport(StrictModel):
    status: Literal["generated", "failed", "disabled", "not_configured"]
    model: str | None = None
    explanation: AuditExplanation | None = None
    usage: dict[str, int] = Field(default_factory=dict)
    error_code: str | None = None
