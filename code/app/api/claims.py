from fastapi import APIRouter, Query
from app.claim_schemas import ClaimCreate, ClaimUpdate, ClaimOut
from app.claim_repository import ClaimRepository

router = APIRouter(prefix="/claims", tags=["claims"])


@router.post("", response_model=ClaimOut, status_code=201)
def create_claim(payload: ClaimCreate):
    return ClaimRepository().create(payload)


@router.get("", response_model=list[ClaimOut])
def list_claims(tenant_id: str, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    return ClaimRepository().list(tenant_id, limit, offset)


@router.get("/{claim_no}", response_model=ClaimOut)
def get_claim(claim_no: str, tenant_id: str):
    return ClaimRepository().get(tenant_id, claim_no)


@router.put("/{claim_no}", response_model=ClaimOut)
def update_claim(claim_no: str, tenant_id: str, payload: ClaimUpdate):
    return ClaimRepository().update(tenant_id, claim_no, payload)
