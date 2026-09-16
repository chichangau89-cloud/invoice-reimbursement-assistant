from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.schemas import AttachmentOut
from app.services import AttachmentService

router = APIRouter(prefix="/attachments", tags=["attachments"])


@router.post("", response_model=AttachmentOut)
def upload_attachment(
    tenant_id: str = Form(...),
    claim_no: str = Form(...),
    file: UploadFile = File(...),
) -> AttachmentOut:
    try:
        return AttachmentService().save(file, tenant_id, claim_no)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
