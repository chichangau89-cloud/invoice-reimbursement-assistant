from fastapi import APIRouter

from app.clients.milvus_client import MilvusVectorClient
from app.core.db import mysql_connection

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    result = {"status": "ok", "mysql": "unknown", "milvus": "unknown"}
    try:
        with mysql_connection(autocommit=True) as db, db.cursor() as cur:
            cur.execute("SELECT 1 AS ok")
            cur.fetchone()
        result["mysql"] = "ok"
    except Exception as exc:
        result["mysql"] = f"error: {exc}"

    client = None
    try:
        client = MilvusVectorClient()
        client.client.list_collections()
        result["milvus"] = "ok"
    except Exception as exc:
        result["milvus"] = f"error: {exc}"
    finally:
        if client:
            client.close()
    return result
