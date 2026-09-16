import json
import unittest
from unittest.mock import patch
from datetime import date

import httpx
from fastapi.testclient import TestClient

from app.clients.llm_client import LLMClient, LLMError
from app.core.config import Settings
from app.llm_schemas import LLMReport
from app.main import app
from app.services import AuditService


def settings(**kwargs):
    return Settings(_env_file=None, DASHSCOPE_API_KEY="test-key", LLM_MAX_RETRIES=0, **kwargs)


def response(content, finish="stop"):
    return httpx.Response(200, json={"choices": [{"finish_reason": finish,
                          "message": {"content": json.dumps(content)}}],
                          "usage": {"total_tokens": 8}})


def fields():
    return dict.fromkeys(["invoice_no", "issue_date", "buyer_name", "seller_name", "total_amount", "currency"])


class LLMTests(unittest.TestCase):
    def client(self, handler, **kwargs):
        return LLMClient(settings(**kwargs), httpx.MockTransport(handler))

    def test_extract_evidence_and_missing(self):
        data = fields()
        data["invoice_no"] = {"value": "123", "evidence": "invoice 123"}
        def handler(request):
            body = json.loads(request.content)
            self.assertFalse(body["enable_thinking"])
            self.assertEqual(body["response_format"], {"type": "json_object"})
            return response(data)
        result = self.client(handler).extract_document_fields("invoice 123")
        self.assertTrue(result.needs_confirmation)
        self.assertIn("total_amount", result.missing_fields)
        self.assertNotIn("invoice_no", result.missing_fields)

    def test_reject_invented_evidence(self):
        data = fields()
        data["invoice_no"] = {"value": "999", "evidence": "invoice 999"}
        with self.assertRaisesRegex(LLMError, "UNGROUNDED"):
            self.client(lambda r: response(data)).extract_document_fields("invoice 123")

    def test_reject_extra_decision_field(self):
        data = fields(); data["decision"] = "approved"
        with self.assertRaisesRegex(LLMError, "INVALID_OUTPUT"):
            self.client(lambda r: response(data)).extract_document_fields("invoice")

    def test_reject_truncated_output(self):
        with self.assertRaisesRegex(LLMError, "INCOMPLETE_OUTPUT"):
            self.client(lambda r: response(fields(), "length")).extract_document_fields("invoice")

    def test_error_body_never_exposed(self):
        with self.assertRaises(LLMError) as ctx:
            self.client(lambda r: httpx.Response(401, text="test-key secret")).extract_document_fields("invoice")
        self.assertEqual(str(ctx.exception), "LLM_HTTP_401")

    def test_reject_unknown_citation(self):
        with self.assertRaisesRegex(LLMError, "UNKNOWN_CITATION"):
            self.client(lambda r: response({"summary": "Explanation", "cited_policy_ids": ["fake"]})).generate_audit_report([], [], "manual_review", "medium")

    def test_malformed_provider_envelope(self):
        with self.assertRaisesRegex(LLMError, "INVALID_OUTPUT"):
            self.client(lambda r: httpx.Response(200, json={"choices": [None]})).extract_document_fields("invoice")

    def test_connection_failure(self):
        def handler(request):
            raise httpx.ConnectError("private-network-detail", request=request)
        with self.assertRaisesRegex(LLMError, "LLM_CONNECTION_FAILED"):
            self.client(handler).extract_document_fields("invoice")

    def test_retry_transient(self):
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(503) if len(calls) == 1 else response(fields())
        config = settings(); config.llm_max_retries = 1
        with patch("app.clients.llm_client.time.sleep"):
            LLMClient(config, httpx.MockTransport(handler)).extract_document_fields("invoice")
        self.assertEqual(len(calls), 2)

    def test_prevent_sending_key_to_other_host(self):
        with self.assertRaisesRegex(LLMError, "INVALID_BASE_URL"):
            self.client(lambda r: self.fail("network called"), LLM_BASE_URL="https://example.com").extract_document_fields("invoice")

    def test_api_bad_input_and_failure(self):
        with TestClient(app) as client:
            self.assertEqual(client.post("/api/llm/extract-invoice", json={"text": ""}).status_code, 422)
            with patch("app.api.llm.LLMClient.extract_document_fields", side_effect=LLMError("LLM_NOT_CONFIGURED")):
                r = client.post("/api/llm/extract-invoice", json={"text": "invoice"})
                self.assertEqual(r.status_code, 503)
                self.assertEqual(r.json()["detail"], "LLM_NOT_CONFIGURED")

    def test_audit_failure_preserves_rule_decision(self):
        invoice = {"invoice_no": "123", "issue_date": date(2026, 9, 15)}
        service = AuditService()
        with patch.object(service.invoice_repo, "list_claim_invoices", return_value=[invoice]), \
             patch.object(service.invoice_repo, "find_duplicate_invoice", return_value=[{"claim_no": "other"}]), \
             patch.object(service.knowledge, "search", return_value=[]), \
             patch("app.services.LLMClient") as factory:
            factory.return_value.configured = True
            factory.return_value.settings.llm_model = "test-model"
            factory.return_value.generate_audit_report.side_effect = LLMError("LLM_CONNECTION_FAILED")
            result = service.run_claim_audit("demo", "claim", None)
            self.assertEqual(result.decision, "rejected")
            self.assertEqual(result.llm_report.status, "failed")
            self.assertIn("rejected", result.report_markdown)

    def test_audit_disabled_does_not_call_model(self):
        service = AuditService()
        with patch.object(service.invoice_repo, "list_claim_invoices", return_value=[]), \
             patch.object(service.knowledge, "search", return_value=[]), \
             patch("app.services.LLMClient") as factory:
            result = service.run_claim_audit("demo", "claim", None, use_llm=False)
            factory.return_value.generate_audit_report.assert_not_called()
            self.assertEqual(result.llm_report.status, "disabled")
            self.assertEqual(result.decision, "manual_review")


if __name__ == "__main__":
    unittest.main()
