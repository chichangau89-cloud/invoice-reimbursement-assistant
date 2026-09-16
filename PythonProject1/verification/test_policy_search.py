import unittest
from unittest.mock import patch, MagicMock
import sys
import types
from fastapi.testclient import TestClient
from main import app
from policy_search import PolicyUnavailable, search_policies, MODEL_ID


class PolicyApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_blank_and_excessive_queries_rejected(self):
        for params in ({'q': ' '}, {'q': 'x' * 201}, {'q': '住宿', 'limit': 11}):
            self.assertEqual(self.client.get('/api/policies/search', params=params).status_code, 422)

    def test_backend_failure_is_not_sample_success(self):
        with patch('main.search_policies', side_effect=PolicyUnavailable('制度服务暂不可用')):
            response = self.client.get('/api/policies/search', params={'q': '住宿'})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {'detail': '制度服务暂不可用'})

    def test_empty_result_is_distinct_from_failure(self):
        with patch('main.search_policies', return_value={'items': [], 'count': 0, 'source': 'milvus'}):
            response = self.client.get('/api/policies/search', params={'q': '住宿'}, headers={'Origin': 'http://localhost:8080'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['items'], [])
        self.assertEqual(response.headers['access-control-allow-origin'], 'http://localhost:8080')

    def test_retrieval_filters_tenant_and_skips_stale_or_inactive_rows(self):
        client = MagicMock()
        client.describe_collection.return_value = {'fields': [{'name': 'vector', 'params': {'dim': 2}}]}
        client.search.return_value = [[{'id': i, 'distance': .8, 'entity': {'content_hash': 'current', 'embedding_model': MODEL_ID}} for i in ['stale', 'inactive', 'valid']]]
        cursor = MagicMock()
        cursor.fetchone.side_effect = [{'content_hash': 'old'}, None, {'id': 'valid', 'content_hash': 'current', 'title': '有效制度'}]
        db = MagicMock()
        db.__enter__.return_value.cursor.return_value.__enter__.return_value = cursor
        model = MagicMock()
        model.encode.return_value.tolist.return_value = [[.1, .2]]
        fake_module = types.SimpleNamespace(MilvusClient=MagicMock(return_value=client))
        with patch.dict(sys.modules, {'pymilvus': fake_module}), patch.dict('os.environ', {'MILVUS_URI': 'http://test:19530', 'POLICY_TENANT_ID': 'test-company'}), patch('policy_search.embedding_model', return_value=model), patch('policy_search.mysql', return_value=db):
            result = search_policies('住宿', 1)
        self.assertEqual([item['id'] for item in result['items']], ['valid'])
        self.assertIn('tenant_id == "test-company"', client.search.call_args.kwargs['filter'])
        self.assertIn('doc_type == "policy"', client.search.call_args.kwargs['filter'])
        self.assertIn('is_active=TRUE', cursor.execute.call_args.args[0])
        client.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
