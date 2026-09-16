from fastapi import FastAPI

from app.api import attachments, audits, health, invoices, knowledge, llm


app = FastAPI(title="Reimbursement Audit Assistant API", version="0.1.0")

app.include_router(health.router)
app.include_router(invoices.router, prefix="/api")
app.include_router(attachments.router, prefix="/api")
app.include_router(knowledge.router, prefix="/api")
app.include_router(audits.router, prefix="/api")

app.include_router(llm.router, prefix="/api")

from fastapi import Request
from fastapi.responses import JSONResponse
from app.api import claims
from app.claim_repository import NotFoundError, ConflictError

app.include_router(claims.router, prefix="/api")


@app.exception_handler(NotFoundError)
async def not_found(request: Request, exc: NotFoundError):
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(ConflictError)
async def conflict(request: Request, exc: ConflictError):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(ValueError)
async def invalid_input(request: Request, exc: ValueError):
    return JSONResponse(status_code=422, content={"detail": "Invalid input"})
