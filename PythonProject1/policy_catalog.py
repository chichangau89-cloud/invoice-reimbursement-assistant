"""Read the active policy document catalogue and complete clauses from MySQL."""
import re

from database_guide.db_demo import mysql
from policy_audit import verified_bundle


class PolicyDocumentUnavailable(RuntimeError):
    pass


class PolicyDocumentNotFound(RuntimeError):
    pass


def _bundle_documents():
    try:
        bundle = verified_bundle()
    except Exception as exc:
        raise PolicyDocumentUnavailable(str(exc)) from exc
    documents = {}
    for document in bundle['documents']:
        match = re.fullmatch(r'报销制度(\d{2})_.+\.md', document['filename'])
        if not match:
            raise PolicyDocumentUnavailable('制度源文件命名无效，无法建立目录。')
        document_id = 'BX-' + match.group(1)
        documents[document_id] = {**document, 'document_id': document_id}
    if len(documents) != 9:
        raise PolicyDocumentUnavailable('当前制度版本不是完整的 9 个板块。')
    return bundle, documents


def list_policy_documents():
    bundle, documents = _bundle_documents()
    try:
        with mysql() as db, db.cursor() as cursor:
            cursor.execute(
                "SELECT source_id, COUNT(*) AS clause_count FROM knowledge_chunks "
                "WHERE tenant_id=%s AND source_version=%s AND doc_type='policy' "
                "AND is_active=TRUE AND sync_status='synced' GROUP BY source_id",
                (bundle['tenant_id'], bundle['version']),
            )
            stored = {row['source_id']: int(row['clause_count']) for row in cursor.fetchall()}
    except Exception as exc:
        raise PolicyDocumentUnavailable('制度目录读取失败，请检查 MySQL 连接。') from exc

    result = []
    for document_id in sorted(documents):
        document = documents[document_id]
        clause_count = stored.get(document['filename'], 0)
        result.append({
            'document_id': document_id,
            'title': document['title'],
            'filename': document['filename'],
            'status': bundle['status'],
            'clause_count': clause_count,
            'available': clause_count > 0,
        })
    return {
        'tenant_id': bundle['tenant_id'], 'version': bundle['version'],
        'policy_status': bundle['status'], 'count': len(result), 'items': result,
    }


def get_policy_document(document_id: str):
    if not re.fullmatch(r'BX-\d{2}', document_id):
        raise PolicyDocumentNotFound('制度板块标识无效。')
    bundle, documents = _bundle_documents()
    document = documents.get(document_id)
    if not document:
        raise PolicyDocumentNotFound('未找到该制度板块。')
    expected = {
        row['id']: row for row in bundle['clauses']
        if row['source_id'] == document['filename']
    }
    try:
        with mysql() as db, db.cursor() as cursor:
            cursor.execute(
                "SELECT id, source_id, source_version, chunk_no, title, content, content_hash "
                "FROM knowledge_chunks WHERE tenant_id=%s AND source_id=%s AND source_version=%s "
                "AND doc_type='policy' AND is_active=TRUE AND sync_status='synced' ORDER BY chunk_no",
                (bundle['tenant_id'], document['filename'], bundle['version']),
            )
            rows = cursor.fetchall()
    except Exception as exc:
        raise PolicyDocumentUnavailable('制度文件读取失败，请检查 MySQL 连接。') from exc
    if not rows or len(rows) != len(expected):
        raise PolicyDocumentUnavailable('制度文件未完整同步，不能展示不一致版本。')
    if any(row['id'] not in expected or expected[row['id']]['content_hash'] != row['content_hash'] for row in rows):
        raise PolicyDocumentUnavailable('制度文件内容与当前入库版本不一致。')
    return {
        'document_id': document_id, 'title': document['title'], 'filename': document['filename'],
        'tenant_id': bundle['tenant_id'], 'version': bundle['version'], 'policy_status': bundle['status'],
        'clauses': [
            {'chunk_no': row['chunk_no'], 'title': row['title'], 'content': row['content']}
            for row in rows
        ],
    }
