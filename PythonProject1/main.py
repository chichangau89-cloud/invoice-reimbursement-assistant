from pathlib import Path
from uuid import uuid4
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / '.env')
import re

from fastapi import FastAPI, HTTPException, Request, Query, Body
from policy_search import search_policies, PolicyUnavailable
from policy_catalog import (list_policy_documents, get_policy_document,
                            PolicyDocumentUnavailable, PolicyDocumentNotFound)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from ocr_service import recognize_invoice
from policy_review_service import review_invoice
from policy_audit import AuditContext
from document_review_service import review_case
import json
from email.parser import BytesParser
from email.policy import default as email_policy

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads" / "invoices"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
CASE_DIR = BASE_DIR / "uploads" / "cases"
CASE_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}
MAX_FILE_SIZE = 10 * 1024 * 1024

app = FastAPI(title="发票报销审核助手")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:8080", "http://127.0.0.1:8080"], allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["*"])

@app.get('/api/policies/documents')
def policy_documents():
    try:
        return list_policy_documents()
    except PolicyDocumentUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get('/api/policies/documents/{document_id}')
def policy_document(document_id: str):
    try:
        return get_policy_document(document_id)
    except PolicyDocumentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PolicyDocumentUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get('/api/policies/search')
def policies_search(q: str = Query('发票报销制度', min_length=1, max_length=200), limit: int = Query(5, ge=1, le=10)):
    q = q.strip()
    if not q:
        raise HTTPException(status_code=422, detail='请输入检索内容。')
    try:
        return search_policies(q, limit)
    except PolicyUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

def parse_multipart_files(body: bytes, content_type: str) -> list[tuple[str, bytes]]:
    if '\r' in content_type or '\n' in content_type:
        raise HTTPException(status_code=400, detail='上传格式无效')
    message=BytesParser(policy=email_policy).parsebytes(('Content-Type: '+content_type+'\r\nMIME-Version: 1.0\r\n\r\n').encode()+body)
    files=[p for p in message.walk() if p.get_param('name',header='content-disposition') in {'file','files'} and p.get_filename()]
    if not files:
        raise HTTPException(status_code=400, detail='请上传 file 或 files 文件字段')
    return [(Path(part.get_filename().replace('\\','/')).name, part.get_payload(decode=True) or b'') for part in files]


def parse_multipart(body: bytes, content_type: str) -> tuple[str, bytes]:
    files = parse_multipart_files(body, content_type)
    if len(files) != 1:
        raise HTTPException(status_code=400, detail='请上传一个 file 文件字段')
    return files[0]

@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

@app.post("/api/invoices/upload")
async def upload_invoice(request: Request) -> JSONResponse:
    content_type = request.headers.get("content-type", "")
    if not content_type.startswith("multipart/form-data"):
        raise HTTPException(status_code=415, detail="请使用 multipart/form-data 上传文件")
    body=bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body)>MAX_FILE_SIZE+65536:
            raise HTTPException(status_code=413, detail='文件不能超过10 MB')
    filename, content = parse_multipart(bytes(body), content_type)
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="仅支持 PDF、PNG、JPG、JPEG 文件")
    if not content:
        raise HTTPException(status_code=400, detail="上传文件为空")
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="文件不能超过 10 MB")
    stored_name = f"{uuid4().hex}{extension}"
    target = UPLOAD_DIR / stored_name
    target.write_bytes(content)
    return JSONResponse(status_code=201, content={"message":"发票上传成功", "filename":filename, "stored_filename":stored_name, "size":len(content), "path":str(target.relative_to(BASE_DIR)), "status":"uploaded", "review_url":f"/api/invoices/{stored_name}/review"})


@app.post('/api/audits/documents')
async def upload_audit_documents(request: Request) -> JSONResponse:
    content_type = request.headers.get('content-type', '')
    if not content_type.startswith('multipart/form-data'):
        raise HTTPException(status_code=415, detail='请使用 multipart/form-data 上传材料')
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_FILE_SIZE * 6 + 65536:
            raise HTTPException(status_code=413, detail='材料总大小不能超过 60 MB')
    files = parse_multipart_files(bytes(body), content_type)
    if len(files) > 6:
        raise HTTPException(status_code=400, detail='一次最多上传 6 份材料')
    case_id = uuid4().hex
    case_path = CASE_DIR / case_id
    case_path.mkdir()
    saved = []
    for index, (filename, content) in enumerate(files, 1):
        extension = Path(filename).suffix.lower()
        if extension not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f'{filename} 不是支持的 PDF、PNG、JPG、JPEG 文件')
        if not content or len(content) > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail=f'{filename} 为空或超过 10 MB')
        stored_name = f'{index:02d}_{uuid4().hex}{extension}'
        (case_path / stored_name).write_bytes(content)
        saved.append({'filename': filename, 'stored_name': stored_name, 'size': len(content)})
    (case_path / 'manifest.json').write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding='utf-8')
    return JSONResponse(status_code=201, content={'message': '审核材料上传成功', 'case_id': case_id,
                        'documents': saved, 'review_url': f'/api/audits/{case_id}/review'})


@app.post('/api/audits/{case_id}/review')
def review_uploaded_case(case_id: str, context: AuditContext | None = Body(default=None)) -> JSONResponse:
    if not re.fullmatch(r'[a-f0-9]{32}', case_id):
        raise HTTPException(status_code=404, detail='未找到审核材料')
    case_path = CASE_DIR / case_id
    manifest_path = case_path / 'manifest.json'
    if not manifest_path.is_file():
        raise HTTPException(status_code=404, detail='未找到审核材料')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    paths = [(case_path / item['stored_name'], item['filename']) for item in manifest]
    if any(not path.is_file() for path, _ in paths):
        raise HTTPException(status_code=409, detail='审核材料不完整，请重新上传')
    result = review_case(paths, context or AuditContext())
    result.update({'case_id': case_id, 'report_id': uuid4().hex})
    report_dir = BASE_DIR / 'uploads' / 'reviews'
    report_dir.mkdir(exist_ok=True)
    (report_dir / (result['report_id'] + '.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return JSONResponse(content=result)

@app.post("/api/invoices/{stored_filename}/review")
def review_uploaded_invoice(stored_filename: str, context: AuditContext | None = Body(default=None)) -> JSONResponse:
    safe_name = Path(stored_filename).name
    path = UPLOAD_DIR / safe_name
    if not re.fullmatch(r'[a-f0-9]{32}\.(pdf|png|jpg|jpeg)',stored_filename) or safe_name != stored_filename or not path.is_file():
        raise HTTPException(status_code=404, detail="未找到已上传发票")
    fields = recognize_invoice(path, safe_name)
    result = review_invoice(fields, context or AuditContext())
    report={"filename":safe_name,"fields":fields,**result}
    report_dir=BASE_DIR/'uploads'/'reviews'
    report_dir.mkdir(exist_ok=True)
    report['report_id']=uuid4().hex
    (report_dir/(report['report_id']+'.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return JSONResponse(content=report)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
