from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator


from app.llm_schemas import LLMReport


DocType = Literal["policy", "subject", "audit_case", "ticket_text"]


class InvoiceIn(BaseModel):
    tenant_id: str
    record_id: str
    claim_no: str
    invoice_no: str
    issue_date: date
    buyer_name: str
    seller_name: str
    total_amount: Decimal
    currency: str = "CNY"

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        if len(value) != 3 or not value.isalpha() or value.upper() != value:
            raise ValueError("currency must be a three-letter uppercase code such as CNY")
        return value

    @field_validator("total_amount")
    @classmethod
    def validate_amount(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or abs(value) >= Decimal("1e16"):
            raise ValueError("total_amount must fit DECIMAL(18,2)")
        if value != value.quantize(Decimal("0.01")):
            raise ValueError("total_amount must have at most two decimal places")
        return value


class InvoiceOut(BaseModel):
    record_id: str
    tenant_id: str
    claim_no: str
    invoice_no: str
    issue_date: date
    buyer_name: str
    seller_name: str
    total_amount: Decimal
    currency: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ImportInvoicesRequest(BaseModel):
    invoices: list[InvoiceIn] = Field(min_length=1, max_length=500)


class ImportResult(BaseModel):
    rows: int


class AttachmentOut(BaseModel):
    id: str
    tenant_id: str
    claim_no: str
    original_name: str
    storage_path: str
    sha256: str
    size_bytes: int


class KnowledgeItemIn(BaseModel):
    tenant_id: str
    source_id: str = Field(max_length=128)
    source_version: str = Field(max_length=32)
    chunk_no: int = Field(ge=0)
    doc_type: DocType
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 6000:
            raise ValueError("content must be at most 6000 UTF-8 bytes")
        return value


class KnowledgeImportRequest(BaseModel):
    items: list[KnowledgeItemIn] = Field(min_length=1, max_length=200)
    sync_to_milvus: bool = True


class KnowledgeSearchRequest(BaseModel):
    tenant_id: str
    question: str = Field(min_length=1)
    doc_type: DocType = "policy"
    limit: int = Field(5, ge=1, le=20)


class KnowledgeSearchHit(BaseModel):
    id: str
    score: float
    source_id: str
    source_version: str
    title: str
    content: str


class AuditRunRequest(BaseModel):
    tenant_id: str
    policy_question: str | None = None
    use_llm: bool = True


class CheckResult(BaseModel):
    check_type: str
    status: Literal["pass", "fail", "review"]
    risk_level: Literal["low", "medium", "high"]
    message: str
    evidences: list[dict] = []
    suggestions: list[str] = []


class AuditResult(BaseModel):
    claim_no: str
    tenant_id: str
    decision: Literal["approved", "rejected", "manual_review"]
    risk_level: Literal["low", "medium", "high"]
    check_results: list[CheckResult]
    policy_hits: list[KnowledgeSearchHit] = []
    report_markdown: str
    llm_report: LLMReport | None = None
