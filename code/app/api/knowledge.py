from fastapi import APIRouter, HTTPException

from app.repositories import KnowledgeRepository
from app.schemas import ImportResult, KnowledgeImportRequest, KnowledgeSearchHit, KnowledgeSearchRequest
from app.services import KnowledgeService

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.post("/import", response_model=ImportResult)
def import_knowledge(payload: KnowledgeImportRequest) -> ImportResult:
    try:
        rows = KnowledgeRepository().upsert_many(payload.items)
        if payload.sync_to_milvus:
            tenants = sorted({item.tenant_id for item in payload.items})
            service = KnowledgeService()
            for tenant_id in tenants:
                service.sync_pending(tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ImportResult(rows=rows)


@router.post("/sync/{tenant_id}", response_model=ImportResult)
def sync_knowledge(tenant_id: str) -> ImportResult:
    try:
        rows = KnowledgeService().sync_pending(tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ImportResult(rows=rows)


@router.post("/search", response_model=list[KnowledgeSearchHit])
def search_knowledge(payload: KnowledgeSearchRequest) -> list[KnowledgeSearchHit]:
    try:
        return KnowledgeService().search(
            tenant_id=payload.tenant_id,
            question=payload.question,
            doc_type=payload.doc_type,
            limit=payload.limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
