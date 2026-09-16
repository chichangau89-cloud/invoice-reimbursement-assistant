"""Read-only policy retrieval using the existing knowledge synchronization contract."""
import os
import re
from functools import lru_cache
from threading import Lock

from database_guide.db_demo import mysql
from policy_documents import active_policy

MODEL_ID = 'BAAI/bge-small-zh-v1.5'
_model_lock = Lock()


class PolicyUnavailable(RuntimeError):
    pass


@lru_cache(maxsize=1)
def embedding_model():
    from sentence_transformers import SentenceTransformer
    if os.getenv('EMBEDDING_MODEL', MODEL_ID) != MODEL_ID:
        raise PolicyUnavailable('当前集合需要 BAAI/bge-small-zh-v1.5 模型，请检查配置。')
    return SentenceTransformer(os.getenv('EMBEDDING_PATH') or MODEL_ID, device='cpu', local_files_only=True)


def search_policies(query: str, limit: int = 5) -> dict:
    active = active_policy()
    tenant = os.getenv('POLICY_TENANT_ID') or (active['tenant_id'] if active else 'demo-company')
    if active and active['tenant_id'] != tenant:
        active = None
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', tenant):
        raise PolicyUnavailable('POLICY_TENANT_ID 配置无效。')
    collection = os.getenv('MILVUS_COLLECTION', 'reimbursement_knowledge_bge_small_zh_v1')
    client = None
    try:
        from pymilvus import MilvusClient
        with _model_lock:
            model = embedding_model()
            vector = model.encode(['为这个句子生成表示以用于检索相关文章：' + query], normalize_embeddings=True).tolist()
        client = MilvusClient(uri=os.environ['MILVUS_URI'], token=os.getenv('MILVUS_TOKEN') or '', timeout=15)
        if not client.has_collection(collection_name=collection):
            raise PolicyUnavailable('配置的制度集合不存在，请检查 MILVUS_COLLECTION。')
        schema = client.describe_collection(collection_name=collection)
        dimension = next(f['params']['dim'] for f in schema['fields'] if f['name'] == 'vector')
        if int(dimension) != len(vector[0]):
            raise PolicyUnavailable('向量模型维度与制度集合不一致。')
        client.load_collection(collection_name=collection)
        version_filter = ''
        if active:
            if not re.fullmatch(r'[A-Za-z0-9._-]{1,32}', active['version']):
                raise PolicyUnavailable('制度版本标识无效')
            version_filter = f' and source_version == "{active["version"]}"'
        hits = client.search(collection_name=collection, data=vector, anns_field='vector',
            filter=f'tenant_id == "{tenant}" and doc_type == "policy" and embedding_model == "{MODEL_ID}"'+version_filter,
            limit=limit * 4, output_fields=['content_hash', 'embedding_model'],
            search_params={'metric_type': 'COSINE', 'params': {}}, consistency_level='Strong')[0]
        items = []
        if hits:
            with mysql() as db, db.cursor() as cursor:
                for hit in hits:
                    cursor.execute('SELECT id,source_id,source_version,title,content,content_hash,chunk_no '
                        'FROM knowledge_chunks WHERE id=%s AND tenant_id=%s AND doc_type=%s AND is_active=TRUE',
                        (str(hit['id']), tenant, 'policy'))
                    row = cursor.fetchone()
                    if row and (not active or row['source_version'] == active['version']) and row['content_hash'] == hit['entity']['content_hash'] and hit['entity']['embedding_model'] == MODEL_ID:
                        items.append({**row, 'score': float(hit['distance'])})
                    if len(items) == limit:
                        break
        return {'query': query, 'source': 'milvus', 'tenant_id': tenant, 'collection': collection,
                'items': items, 'count': len(items), 'is_demo': tenant == 'demo-company',
                'policy_status': active['status'] if active else 'unverified'}
    except PolicyUnavailable:
        raise
    except (ImportError, OSError) as exc:
        raise PolicyUnavailable('制度检索依赖或本地向量模型未就绪，请安装 requirements-policies.txt 并设置 EMBEDDING_PATH。') from exc
    except Exception as exc:
        raise PolicyUnavailable('制度检索失败，请检查 Milvus、MySQL 连接、认证与集合结构。') from exc
    finally:
        if client is not None:
            client.close()
