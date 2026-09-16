from fastapi import APIRouter, HTTPException, Query

from app.repositories import InvoiceRepository
from app.schemas import ImportInvoicesRequest, ImportResult, InvoiceOut

router = APIRouter(prefix="/invoices", tags=["invoices"])


@router.get("", response_model=list[InvoiceOut])
def list_invoices(
    tenant_id: str,
    claim_no: str | None = None,
    limit: int = Query(50, ge=1, le=500),
) -> list[dict]:
    try:
        return InvoiceRepository().list(tenant_id, claim_no, limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/import", response_model=ImportResult)
def import_invoices(payload: ImportInvoicesRequest) -> ImportResult:
    try:
        rows = InvoiceRepository().upsert_many(payload.invoices)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ImportResult(rows=rows)
