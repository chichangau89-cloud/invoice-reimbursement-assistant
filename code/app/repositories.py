from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.core.db import mysql_connection
from app.core.ids import identity, validate_key
from app.schemas import InvoiceIn, KnowledgeItemIn


class InvoiceRepository:
    def upsert_many(self, invoices: list[InvoiceIn]) -> int:
        values = []
        for item in invoices:
            tenant = validate_key(item.tenant_id, "tenant_id")
            row_id = identity([tenant, validate_key(item.record_id, "record_id")])
            values.append(
                (
                    row_id,
                    tenant,
                    item.claim_no,
                    item.invoice_no,
                    item.issue_date,
                    item.buyer_name,
                    item.seller_name,
                    item.total_amount,
                    item.currency,
                )
            )
        with mysql_connection() as db, db.cursor() as cur:
            # Serialize input changes with audit completion and invalidate old summaries.
            affected = {(item.tenant_id, item.claim_no) for item in invoices}
            for value in values:
                cur.execute("SELECT tenant_id,claim_no FROM invoices WHERE record_id=%s", (value[0],))
                prior = cur.fetchone()
                if prior:
                    affected.add((prior["tenant_id"], prior["claim_no"]))
            for tenant, claim in sorted(affected):
                cur.execute("SELECT claim_no FROM claims WHERE tenant_id=%s AND claim_no=%s FOR UPDATE", (tenant, claim))
                cur.execute("UPDATE claims SET version=version+1,status='draft',latest_audit_id=NULL WHERE tenant_id=%s AND claim_no=%s", (tenant, claim))
            cur.executemany(
                """
                INSERT INTO invoices
                (record_id,tenant_id,claim_no,invoice_no,issue_date,buyer_name,seller_name,total_amount,currency)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) AS incoming
                ON DUPLICATE KEY UPDATE claim_no=incoming.claim_no, invoice_no=incoming.invoice_no,
                issue_date=incoming.issue_date, buyer_name=incoming.buyer_name,
                seller_name=incoming.seller_name, total_amount=incoming.total_amount,
                currency=incoming.currency
                """,
                values,
            )
            db.commit()
        return len(values)

    def list(self, tenant_id: str, claim_no: str | None, limit: int) -> list[dict]:
        validate_key(tenant_id, "tenant_id")
        sql = "SELECT * FROM invoices WHERE tenant_id=%s"
        params: list[object] = [tenant_id]
        if claim_no:
            sql += " AND claim_no=%s"
            params.append(claim_no)
        sql += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)
        with mysql_connection(autocommit=True) as db, db.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())

    def find_duplicate_invoice(self, tenant_id: str, invoice_no: str, issue_date: date) -> list[dict]:
        with mysql_connection(autocommit=True) as db, db.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM invoices
                WHERE tenant_id=%s AND invoice_no=%s AND issue_date=%s
                ORDER BY created_at DESC
                """,
                (tenant_id, invoice_no, issue_date),
            )
            return list(cur.fetchall())

    def list_claim_invoices(self, tenant_id: str, claim_no: str) -> list[dict]:
        with mysql_connection(autocommit=True) as db, db.cursor() as cur:
            cur.execute(
                "SELECT * FROM invoices WHERE tenant_id=%s AND claim_no=%s ORDER BY issue_date",
                (tenant_id, claim_no),
            )
            return list(cur.fetchall())


class AttachmentRepository:
    def insert(self, row: dict) -> None:
        with mysql_connection() as db, db.cursor() as cur:
            cur.execute("SELECT claim_no FROM claims WHERE tenant_id=%s AND claim_no=%s FOR UPDATE", (row["tenant_id"], row["claim_no"]))
            cur.execute("UPDATE claims SET version=version+1,status='draft',latest_audit_id=NULL WHERE tenant_id=%s AND claim_no=%s", (row["tenant_id"], row["claim_no"]))
            cur.execute(
                """
                INSERT INTO attachments
                (id,tenant_id,claim_no,original_name,storage_path,sha256,size_bytes)
                VALUES (%s,%s,%s,%s,%s,%s,%s) AS incoming
                ON DUPLICATE KEY UPDATE original_name=incoming.original_name,
                storage_path=incoming.storage_path
                """,
                (
                    row["id"],
                    row["tenant_id"],
                    row["claim_no"],
                    row["original_name"],
                    row["storage_path"],
                    row["sha256"],
                    row["size_bytes"],
                ),
            )
            db.commit()


class KnowledgeRepository:
    def upsert_many(self, items: list[KnowledgeItemIn]) -> int:
        values = []
        for item in items:
            tenant = validate_key(item.tenant_id, "tenant_id")
            doc_id = identity([tenant, item.source_id, item.source_version, item.chunk_no])
            content_hash = identity([item.title, item.content, item.doc_type])
            values.append(
                (
                    doc_id,
                    tenant,
                    item.source_id,
                    item.source_version,
                    item.chunk_no,
                    item.doc_type,
                    item.title,
                    item.content,
                    content_hash,
                )
            )
        with mysql_connection() as db, db.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO knowledge_chunks
                (id,tenant_id,source_id,source_version,chunk_no,doc_type,title,content,content_hash)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) AS incoming
                ON DUPLICATE KEY UPDATE doc_type=incoming.doc_type, title=incoming.title,
                content=incoming.content, content_hash=incoming.content_hash,
                sync_status='pending', is_active=TRUE
                """,
                values,
            )
            db.commit()
        return len(values)

    def pending_for_sync(self, tenant_id: str, target: str, after: str = "", limit: int = 64) -> list[dict]:
        with mysql_connection(autocommit=True) as db, db.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM knowledge_chunks
                WHERE tenant_id=%s AND is_active=TRUE AND id>%s
                AND (sync_status<>'synced' OR sync_target<>%s)
                ORDER BY id LIMIT %s
                """,
                (tenant_id, after, target, limit),
            )
            return list(cur.fetchall())

    def mark_synced(self, rows: list[dict], target: str) -> None:
        with mysql_connection() as db, db.cursor() as cur:
            for row in rows:
                cur.execute(
                    """
                    UPDATE knowledge_chunks SET sync_status='synced',
                    sync_target=%s, synced_at=UTC_TIMESTAMP()
                    WHERE id=%s AND content_hash=%s AND is_active=TRUE
                    """,
                    (target, row["id"], row["content_hash"]),
                )
            db.commit()

    def get_active(self, doc_id: str, tenant_id: str) -> dict | None:
        with mysql_connection(autocommit=True) as db, db.cursor() as cur:
            cur.execute(
                "SELECT * FROM knowledge_chunks WHERE id=%s AND tenant_id=%s AND is_active=TRUE",
                (doc_id, tenant_id),
            )
            return cur.fetchone()
