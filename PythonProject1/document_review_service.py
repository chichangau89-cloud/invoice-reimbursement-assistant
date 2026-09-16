"""Multi-document reimbursement pre-audit with evidence-preserving retrieval."""
from datetime import date
from pathlib import Path
import re

from database_guide.db_demo import mysql
from ocr_service import extract_text, extract_fields
from policy_documents import active_policy
from policy_review_service import review_invoice
from policy_search import search_policies, PolicyUnavailable


def _first(patterns, text):
    for pattern in patterns:
        match = re.search(pattern, text, re.I | re.M)
        if match:
            return match.group(1).strip()
    return None


def document_kind(filename: str, text: str) -> str:
    value = (filename + '\n' + text[:2000]).lower()
    if any(word in value for word in ('行程单', '登机牌', '火车票', '车票', '酒店水单', '入住', '离店', 'trip', 'itinerary')):
        return 'itinerary'
    if any(word in value for word in ('审批单', '出差申请', '事前审批', '申请编号', 'approval')):
        return 'approval'
    if any(word in value for word in ('发票', '价税合计', '购买方', 'invoice')):
        return 'invoice'
    return 'other'


def extract_trip_fields(text: str) -> dict:
    return {
        'traveler': _first([r'(?:乘车人|旅客姓名|出行人|入住人)\s*[:：]\s*([^\n]{2,40})'], text),
        'departure_date': _first([r'(?:出发日期|乘车日期|出发时间|入住日期)\s*[:：]?\s*(\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}日?)'], text),
        'arrival_date': _first([r'(?:到达日期|离店日期|退房日期)\s*[:：]?\s*(\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}日?)'], text),
        'route': _first([r'(?:出发地|行程|路线)\s*[:：]\s*([^\n]{2,80})'], text),
        'order_no': _first([r'(?:订单号|行程单号|票号)\s*[:：]?\s*([0-9A-Z-]{6,})'], text),
    }


def extract_approval_fields(text: str) -> dict:
    return {
        'approval_no': _first([r'(?:审批编号|申请编号|单据编号)\s*[:：]?\s*([0-9A-Z-]{4,})'], text),
        'approval_date': _first([r'(?:审批日期|审批时间|申请日期)\s*[:：]?\s*(\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}日?)'], text),
        'approval_status': _first([r'(?:审批状态|审核状态)\s*[:：]\s*([^\n]{2,30})'], text),
    }


def recognize_document(path: Path, filename: str) -> dict:
    text, method = extract_text(path)
    kind = document_kind(filename, text)
    fields = extract_fields(text, filename) if kind == 'invoice' else (extract_trip_fields(text) if kind == 'itinerary' else extract_approval_fields(text) if kind == 'approval' else {})
    return {
        'filename': filename, 'kind': kind, 'recognized': bool(text.strip()), 'ocr_method': method,
        'raw_text_length': len(text), 'fields': fields,
    }


def _basis(rule_id: str, message: str) -> dict:
    return {'rule_id': rule_id, 'status': 'needs_evidence', 'message': message, 'values': {},
            'basis': {'file': '材料交叉校验', 'section': '提交材料与数据库记录', 'version': 'runtime',
                      'line_start': 0, 'line_end': 0, 'condition': message,
                      'evidence_required': '上传原始材料并人工核验', 'action': '补充或人工复核'}}


def historical_invoice_recall(invoice: dict) -> dict:
    active = active_policy()
    tenant = active['tenant_id'] if active else None
    number, issued = invoice.get('invoice_no'), invoice.get('issue_date')
    if not tenant or not number or not issued:
        return {'channel': 'mysql_exact_invoice', 'status': 'not_run', 'reason': '缺少当前租户、发票号码或开票日期，未做精确历史查重。', 'items': []}
    try:
        with mysql() as db, db.cursor() as cursor:
            cursor.execute('SELECT claim_no, invoice_no, issue_date, buyer_name, seller_name, total_amount '
                           'FROM invoices WHERE tenant_id=%s AND invoice_no=%s AND issue_date=%s ORDER BY updated_at DESC LIMIT 10',
                           (tenant, number, issued.replace('年', '-').replace('月', '-').replace('日', '')))
            rows = cursor.fetchall()
    except Exception as exc:
        return {'channel': 'mysql_exact_invoice', 'status': 'unavailable', 'reason': 'MySQL 历史发票查询失败，未将其作为通过依据。', 'items': []}
    return {'channel': 'mysql_exact_invoice', 'status': 'matched' if rows else 'clear',
            'reason': '按租户、发票号码和开票日期精确比对。', 'items': rows}


def policy_recall(invoice: dict, documents: list[dict], expense_type: str) -> dict:
    snippets = []
    for document in documents:
        snippets.append(document['kind'])
        snippets.extend(str(value) for value in document['fields'].values() if value)
    query = ' '.join(snippets)[:300] or (expense_type if expense_type != 'unknown' else '发票报销审核材料要求')
    try:
        found = search_policies(query, 5)
        return {'channel': 'milvus_policy', 'status': 'ok', 'query': query, 'items': found['items'],
                'reason': 'Milvus 召回候选条款后，已由 MySQL 校验正文与当前制度版本。'}
    except PolicyUnavailable as exc:
        return {'channel': 'milvus_policy', 'status': 'unavailable', 'reason': str(exc), 'items': []}


def material_checks(documents: list[dict], invoice: dict, historical: dict, expense_type: str) -> list[dict]:
    kinds = {document['kind'] for document in documents}
    checks = []
    if not invoice:
        checks.append(_basis('M01', '未识别到发票；无法执行金额、票号和购方核验。'))
    elif not invoice.get('invoice_no') or not invoice.get('issue_date') or invoice.get('amount') is None:
        checks.append(_basis('M01', '发票关键字段不完整；需人工核对票号、日期和价税合计。'))
    else:
        row = _basis('M01', '发票关键字段已从上传材料提取，仍需人工核对识别准确性。')
        row['status'] = 'pass'
        row['values'] = {'invoice_no': invoice['invoice_no'], 'issue_date': invoice['issue_date'], 'amount': invoice['amount']}
        checks.append(row)
    if expense_type in {'lodging', 'transport', 'self_drive'}:
        row = _basis('M02', '差旅类报销需关联行程单、酒店水单或交通凭证。')
        row['status'] = 'pass' if 'itinerary' in kinds else 'needs_evidence'
        checks.append(row)
    if expense_type == 'entertainment':
        row = _basis('M03', '业务招待需关联事前审批材料。')
        row['status'] = 'pass' if 'approval' in kinds else 'needs_evidence'
        checks.append(row)
    if historical['status'] == 'matched':
        row = _basis('M04', '历史库存在相同租户、票号和开票日期的记录，疑似重复报销。')
        row['status'] = 'flagged'; row['values'] = {'matches': len(historical['items'])}
        checks.append(row)
    elif historical['status'] == 'clear':
        row = _basis('M04', '未命中同租户、票号和开票日期完全相同的历史发票记录。')
        row['status'] = 'pass'; checks.append(row)
    else:
        checks.append(_basis('M04', historical['reason']))
    return checks


def review_case(paths: list[tuple[Path, str]], context) -> dict:
    documents = [recognize_document(path, filename) for path, filename in paths]
    invoice_docs = [item for item in documents if item['kind'] == 'invoice']
    invoice = invoice_docs[0]['fields'] if invoice_docs else {}
    if invoice_docs:
        invoice.update({'source_filename': invoice_docs[0]['filename'], 'recognized': invoice_docs[0]['recognized'],
                        'ocr_method': invoice_docs[0]['ocr_method']})
    base = review_invoice(invoice, context)
    historical = historical_invoice_recall(invoice)
    retrieved = policy_recall(invoice, documents, context.expense_type)
    evidence_checks = material_checks(documents, invoice, historical, context.expense_type)
    base['checks'] = evidence_checks + base.get('checks', [])
    base['documents'] = documents
    base['retrievals'] = [historical, retrieved]
    base['fields'] = invoice
    base['summary'] = f"已识别 {len(documents)} 份材料；执行 {len(base['checks'])} 项检查。{base['summary']}"
    return base
