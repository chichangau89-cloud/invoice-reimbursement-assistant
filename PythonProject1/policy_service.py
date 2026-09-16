"""Compatibility facade; no sample fallback or amount substring checks."""
from policy_review_service import review_invoice
from policy_search import search_policies


def retrieve_policies(query, limit=3):
    return search_policies(query, limit)['items'], 'milvus'
