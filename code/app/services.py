import hashlib
import shutil
from pathlib import Path

from fastapi import UploadFile

from app.clients.llm_client import LLMClient, LLMError
from app.llm_schemas import LLMReport
from app.clients.embedding_client import get_embedding_client
from app.clients.milvus_client import MilvusVectorClient
from app.core.config import get_settings
from app.core.ids import identity, validate_key
from app.repositories import AttachmentRepository, InvoiceRepository, KnowledgeRepository
from app.schemas import AttachmentOut, AuditResult, CheckResult, KnowledgeSearchHit


class AttachmentService:
    def __init__(self) -> None:
        self.repo = AttachmentRepository()

    def save(self, file: UploadFile, tenant_id: str, claim_no: str) -> AttachmentOut:
        validate_key(tenant_id, "tenant_id")
        settings = get_settings()
        root = settings.attachment_root / tenant_id
        root.mkdir(parents=True, exist_ok=True)

        temp_path = root / f".{file.filename or 'upload'}.tmp"
        h = hashlib.sha256()
        size = 0
        with temp_path.open("wb") as out:
            while chunk := file.file.read(1024 * 1024):
                h.update(chunk)
                size += len(chunk)
                out.write(chunk)
        sha256 = h.hexdigest()
        destination = root / sha256
        if not destination.exists():
            shutil.move(str(temp_path), str(destination))
        else:
            temp_path.unlink(missing_ok=True)

        row = {
            "id": identity([tenant_id, claim_no, sha256]),
            "tenant_id": tenant_id,
            "claim_no": claim_no,
            "original_name": Path(file.filename or "upload.bin").name,
            "storage_path": destination.relative_to(get_settings().attachment_root.parent).as_posix(),
            "sha256": sha256,
            "size_bytes": size,
        }
        self.repo.insert(row)
        return AttachmentOut(**row)


class KnowledgeService:
    def __init__(self) -> None:
        self.repo = KnowledgeRepository()

    def sync_pending(self, tenant_id: str) -> int:
        validate_key(tenant_id, "tenant_id")
        embedding = get_embedding_client()
        target = f"{get_settings().milvus_collection}:{embedding.model_id}"
        vector_client = MilvusVectorClient()
        count = 0
        after = ""
        try:
            while True:
                rows = self.repo.pending_for_sync(tenant_id, target, after=after)
                if not rows:
                    break
                vectors = embedding.embed_texts([row["title"] + "\n" + row["content"] for row in rows])
                fields = (
                    "id",
                    "tenant_id",
                    "doc_type",
                    "source_id",
                    "source_version",
                    "title",
                    "content",
                    "content_hash",
                )
                documents = [
                    dict({field: row[field] for field in fields}, vector=vector, embedding_model=embedding.model_id)
                    for row, vector in zip(rows, vectors)
                ]
                vector_client.upsert(documents)
                self.repo.mark_synced(rows, target)
                count += len(rows)
                after = rows[-1]["id"]
        finally:
            vector_client.close()
        return count

    def search(self, tenant_id: str, question: str, doc_type: str, limit: int) -> list[KnowledgeSearchHit]:
        validate_key(tenant_id, "tenant_id")
        embedding = get_embedding_client()
        vector_client = MilvusVectorClient()
        try:
            hits = vector_client.search(
                vector=embedding.embed_query(question),
                tenant_id=tenant_id,
                doc_type=doc_type,
                limit=limit,
            )
        finally:
            vector_client.close()

        valid: list[KnowledgeSearchHit] = []
        for hit in hits:
            row = self.repo.get_active(str(hit["id"]), tenant_id)
            entity = hit.get("entity", {})
            if row and row["content_hash"] == entity.get("content_hash") and entity.get("embedding_model") == embedding.model_id:
                valid.append(
                    KnowledgeSearchHit(
                        id=row["id"],
                        score=float(hit["distance"]),
                        source_id=row["source_id"],
                        source_version=row["source_version"],
                        title=row["title"],
                        content=row["content"],
                    )
                )
        return valid


class AuditService:
    def __init__(self) -> None:
        self.invoice_repo = InvoiceRepository()
        self.knowledge = KnowledgeService()

    def run_claim_audit(self, tenant_id: str, claim_no: str, policy_question: str | None, use_llm: bool = True, invoice_snapshot: list[dict] | None = None) -> AuditResult:
        validate_key(tenant_id, "tenant_id")
        invoices = invoice_snapshot if invoice_snapshot is not None else self.invoice_repo.list_claim_invoices(tenant_id, claim_no)
        checks: list[CheckResult] = []

        if not invoices:
            checks.append(
                CheckResult(
                    check_type="invoice_presence",
                    status="review",
                    risk_level="medium",
                    message="未查询到该报销单的发票记录，需要补充发票或确认数据是否已导入。",
                    suggestions=["上传或导入发票后重新审核"],
                )
            )
        else:
            duplicate_evidence = []
            for invoice in invoices:
                matches = self.invoice_repo.find_duplicate_invoice(
                    tenant_id, invoice["invoice_no"], invoice["issue_date"]
                )
                other_claims = [row for row in matches if row["claim_no"] != claim_no]
                if other_claims:
                    duplicate_evidence.append(
                        {
                            "invoice_no": invoice["invoice_no"],
                            "issue_date": str(invoice["issue_date"]),
                            "matched_claims": sorted({row["claim_no"] for row in other_claims}),
                        }
                    )
            checks.append(
                CheckResult(
                    check_type="duplicate_invoice",
                    status="fail" if duplicate_evidence else "pass",
                    risk_level="high" if duplicate_evidence else "low",
                    message="发现同租户下相同发票号和开票日期的其他报销单。"
                    if duplicate_evidence
                    else "未发现同租户下相同发票号和开票日期的其他报销单。",
                    evidences=duplicate_evidence,
                    suggestions=["核对是否重复报销"] if duplicate_evidence else [],
                )
            )

        query = policy_question or f"报销单 {claim_no} 发票重复报销 合规审核"
        try:
            policy_hits = self.knowledge.search(tenant_id, query, "policy", 3)
        except Exception as exc:
            policy_hits = []
            checks.append(
                CheckResult(
                    check_type="policy_retrieval",
                    status="review",
                    risk_level="medium",
                    message=f"制度知识库检索失败：{exc}",
                    suggestions=["检查 Milvus 服务、Embedding 模型和知识库同步状态"],
                )
            )

        if any(check.status == "fail" for check in checks):
            decision = "rejected"
            risk = "high"
        elif any(check.status == "review" for check in checks):
            decision = "manual_review"
            risk = "medium"
        else:
            decision = "approved"
            risk = "low"

        report = [
            f"# 报销单 {claim_no} 审核报告",
            f"- 租户：{tenant_id}",
            f"- 结论：{decision}",
            f"- 风险等级：{risk}",
            "",
            "## 检查结果",
        ]
        report.extend([f"- {check.check_type}: {check.status}，{check.message}" for check in checks])
        if policy_hits:
            report.append("")
            report.append("## 召回制度依据")
            report.extend([f"- {hit.title}（{hit.source_id}/{hit.source_version}，score={hit.score:.4f}）" for hit in policy_hits])

        llm = LLMClient()
        llm_report = LLMReport(status="disabled" if not use_llm else "not_configured")
        if use_llm and llm.configured:
            try:
                llm_report = llm.generate_audit_report(checks, policy_hits, decision, risk)
                report.extend(["", "## 大模型辅助说明（以结构化规则结果为准）",
                               llm_report.explanation.summary])
            except LLMError as exc:
                llm_report = LLMReport(status="failed", model=llm.settings.llm_model, error_code=exc.code)
                report.extend(["", "大模型说明生成失败，以上为规则生成的报告。"])

        return AuditResult(
            claim_no=claim_no,
            tenant_id=tenant_id,
            decision=decision,
            risk_level=risk,
            check_results=checks,
            policy_hits=policy_hits,
            report_markdown="\n".join(report),
            llm_report=llm_report,
        )
