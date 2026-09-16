from fastapi import APIRouter, HTTPException

from app.clients.llm_client import LLMClient, LLMError
from app.llm_schemas import ExtractInvoiceRequest, InvoiceExtraction

router = APIRouter(prefix="/llm", tags=["llm"])


@router.post("/extract-invoice", response_model=InvoiceExtraction)
def extract_invoice(payload: ExtractInvoiceRequest) -> InvoiceExtraction:
    """Extract candidates from pasted/OCR text; does not import into MySQL."""
    try:
        return LLMClient().extract_document_fields(payload.text)
    except LLMError as exc:
        status = 503 if exc.code == "LLM_NOT_CONFIGURED" else 502
        raise HTTPException(status_code=status, detail=exc.code) from None
