import json
from fastapi import APIRouter, HTTPException, Query
from app.schemas import AuditRunRequest
from app.claim_schemas import SavedAudit
from app.claim_repository import ClaimRepository
from app.services import AuditService

router = APIRouter(prefix="/audits", tags=["audits"])


@router.post("/claims/{claim_no}/run", response_model=SavedAudit)
def run_claim_audit(claim_no: str, payload: AuditRunRequest):
    repo = ClaimRepository()
    claim, invoices, attachments = repo.snapshot(payload.tenant_id, claim_no)
    snapshot = json.loads(json.dumps({"claim": claim, "invoices": invoices,
        "attachments": attachments, "request": payload.model_dump(),
        "rule_version": "duplicate-invoice-v1", "pipeline_version": "claims-persistence-v1"}, default=str))
    result = AuditService().run_claim_audit(payload.tenant_id, claim_no, payload.policy_question,
                                          payload.use_llm, invoice_snapshot=invoices)
    return repo.save_audit(payload.tenant_id, claim_no, claim["version"], snapshot, result)


@router.get("/claims/{claim_no}", response_model=list[SavedAudit])
def audit_history(claim_no: str, tenant_id: str, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    return ClaimRepository().history(tenant_id, claim_no, limit, offset)


@router.get("/{audit_id}", response_model=SavedAudit)
def get_audit(audit_id: str, tenant_id: str):
    return ClaimRepository().get_audit(tenant_id, audit_id)
