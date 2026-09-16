"""Explicit live integration test: creates isolated synthetic records; no deletion."""
import os
import sys
import json
from pathlib import Path
from uuid import uuid4
os.environ.setdefault("HF_HUB_OFFLINE", "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app.main import app
from app.claim_repository import ClaimRepository
from app.claim_schemas import ClaimUpdate
from app.schemas import AuditResult


def main():
    tenant = "claims_test_" + uuid4().hex[:12]
    evidence = {"tenant_id": tenant, "checks": []}
    with TestClient(app) as c:
        def call(method, url, status=200, **kwargs):
            r = c.request(method, url, **kwargs)
            assert r.status_code == status, (url, r.status_code, r.text[:500])
            evidence["checks"].append({"method": method, "url": url, "status": r.status_code})
            return r.json()
        base = {"applicant_name": "测试员工", "department": "测试部门", "expense_type": "travel",
                "amount": "680.00", "currency": "CNY", "business_purpose": "集成测试，不是真实报销"}
        url = "/api/claims/TEST-001"
        created = call("POST", "/api/claims", status=201, json={**base, "tenant_id": tenant, "claim_no": "TEST-001"})
        assert created["version"] == 1
        call("POST", "/api/claims", status=409, json={**base, "tenant_id": tenant, "claim_no": "TEST-001"})
        call("GET", url, status=404, params={"tenant_id": tenant+"_other"})
        call("POST", "/api/audits/claims/MISSING/run", status=404, json={"tenant_id": tenant, "use_llm": False})
        call("POST", "/api/invoices/import", json={"invoices": [{"tenant_id": tenant, "record_id": "r1", "claim_no": "TEST-001",
             "invoice_no": "TEST-INV-001", "issue_date": "2026-09-16", "buyer_name": "测试公司", "seller_name": "测试酒店", "total_amount": "680.00"}]})
        current = call("GET", url, params={"tenant_id": tenant})
        assert current["version"] == 2
        first = call("POST", "/api/audits/claims/TEST-001/run", json={"tenant_id": tenant, "use_llm": True})
        assert first["llm_report"]["status"] == "generated", first["llm_report"]
        assert not first["stale"] and len(first["input_snapshot"]["invoices"]) == 1
        aid = first["audit_id"]
        fetched = call("GET", "/api/audits/"+aid, params={"tenant_id": tenant})
        assert fetched == first
        call("GET", "/api/audits/"+aid, status=404, params={"tenant_id": tenant+"_other"})
        current = call("GET", url, params={"tenant_id": tenant})
        assert current["status"] == "audited" and current["latest_audit_id"] == aid
        changed = call("PUT", url, params={"tenant_id": tenant}, json={**base, "amount": "700.00", "expected_version": 2})
        assert changed["version"] == 3 and changed["latest_audit_id"] is None and changed["status"] == "draft"
        call("PUT", url, status=409, params={"tenant_id": tenant}, json={**base, "expected_version": 2})
        old = call("GET", "/api/audits/"+aid, params={"tenant_id": tenant})
        assert old["input_snapshot"]["claim"]["amount"] == "680.00"
        second = call("POST", "/api/audits/claims/TEST-001/run", json={"tenant_id": tenant, "use_llm": False})
        assert second["audit_id"] != aid and second["claim_version"] == 3
        history = call("GET", "/api/audits/claims/TEST-001", params={"tenant_id": tenant})
        assert len(history) == 2
        assert len(call("GET", "/api/audits/claims/TEST-001", params={"tenant_id": tenant,"limit":1,"offset":1})) == 1
        # Simulate update during a long-running audit: historical record is retained but cannot publish latest status.
        repo = ClaimRepository()
        repo.update(tenant, "TEST-001", ClaimUpdate(**base, expected_version=3))
        stale = repo.save_audit(tenant, "TEST-001", 3, second["input_snapshot"], AuditResult.model_validate(second))
        assert stale["stale"] and repo.get(tenant,"TEST-001")["status"] == "draft"
        evidence["first_audit"] = first
        evidence["second_audit_id"] = second["audit_id"]
        evidence["stale_audit_id"] = stale["audit_id"]
    # New application client / fresh DB connection must still find the committed record.
    with TestClient(app) as c:
        assert c.get("/api/audits/"+aid,params={"tenant_id":tenant}).json()["audit_id"] == aid
    target = Path(__file__).resolve().parents[2]/"PythonProject1"/"verification"/(tenant+".json")
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(evidence, ensure_ascii=False, indent=2),encoding="utf-8")
    print("PASS",len(evidence["checks"]),"HTTP checks; snapshots, version conflict, tenant isolation, stale completion, durable read")
    print("REPORT",target)


if __name__ == "__main__":
    main()
