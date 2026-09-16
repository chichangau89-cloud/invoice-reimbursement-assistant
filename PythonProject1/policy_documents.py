"""Markdown -> complete clauses JSON -> versioned MySQL/Milvus import.

No sentence/table splitting of stored clauses. Long embedding inputs are pooled
over overlapping token windows, without truncating the stored source text.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
BUNDLE = ROOT / 'policy_data' / 'clauses.json'
TENANT = 'xiaoer-policy-draft'


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def convert(directory: Path, tenant=TENANT):
    from database_guide.db_demo import identity, key
    key(tenant)
    files = sorted(directory.glob('报销制度[0-9][0-9]_*.md'))
    if len(files) != 9:
        raise ValueError(f'需要00—08共9份文件，实际找到{len(files)}份')
    documents, clauses = [], []
    texts = {p.name: p.read_text(encoding='utf-8-sig') for p in files}
    version = 'V1.0-draft-' + sha(json.dumps(texts, ensure_ascii=False, sort_keys=True))[:12]
    for filename, text in texts.items():
        matches = list(re.finditer(r'^##\s+(.+)$', text, re.M))
        if not matches:
            raise ValueError(f'{filename}缺少二级条款标题')
        header = text[:matches[0].start()].strip()
        title = re.search(r'^#\s+(.+)$', text, re.M).group(1)
        number = re.search(r'报销制度(\d+)_', filename).group(1)
        documents.append({'filename': filename, 'title': title, 'sha256': sha(text), 'status': 'draft'})
        for i, match in enumerate(matches):
            end = matches[i+1].start() if i+1 < len(matches) else len(text)
            section = text[match.start():end].strip()
            content = f'来源文件：{filename}\n状态：企业适配草案（未签发）\n{header}\n\n{section}'
            clause_title = f'{title} / {match.group(1)}'
            if len(content.encode('utf-8')) > 6000 or len(clause_title.encode('utf-8')) > 600:
                raise ValueError(f'{filename}/{match.group(1)}超出集合字段容量，拒绝自动截断')
            row = {'tenant_id': tenant, 'source_id': filename, 'source_version': version,
                'chunk_no': i+1, 'doc_type': 'policy', 'title': clause_title, 'content': content,
                'document_id': 'BX-'+number, 'section': match.group(1), 'status': 'draft',
                'line_start': text[:match.start()].count('\n')+1,
                'line_end': text[:end].rstrip().count('\n')+1}
            row['id'] = identity([tenant, filename, version, i+1])
            row['content_hash'] = identity([clause_title, content, 'policy'])
            clauses.append(row)
    rule_clause = next(c for c in clauses if c['document_id']=='BX-07' and c['section']=='二、执行规则表')
    rules = []
    for line in rule_clause['content'].splitlines():
        cells = [s.strip() for s in line.strip('|').split('|')]
        if cells and re.fullmatch(r'R\d{2}', cells[0]):
            rules.append(dict(zip(['id','condition','evidence','action','reference'], cells), clause_id=rule_clause['id']))
    if {r['id'] for r in rules} != {f'R{i:02}' for i in range(1,19)}:
        raise ValueError('规则表R01—R18不完整')
    # Bounds come from identified rule rows, never a retrieved arbitrary number.
    for rule in rules:
        if rule['id'] in {'R02','R03','R04','R05','R06'}:
            rule['threshold'] = re.search(r'>\s*(\d+)\s*(?:元|补)', rule['condition']+' '+rule['action']).group(1)
    lodging_clause = next(c for c in clauses if c['document_id']=='BX-02' and c['section']=='第二条 境内标准')
    lodging = {}
    for line in lodging_clause['content'].splitlines():
        cells = [s.strip() for s in line.strip('|').split('|')]
        if len(cells)==8 and cells[0] in ['A','B','C']:
            lodging[cells[0]] = [re.search(r'\d+', cells[5]).group(), re.search(r'\d+', cells[6]).group()]
    if len(lodging)!=3:
        raise ValueError('住宿档位表不完整')
    return {'format_version':1, 'tenant_id':tenant, 'version':version, 'status':'draft',
        'documents':documents, 'clauses':clauses, 'rules':rules,
        'lodging': {'limits':lodging, 'clause_id':lodging_clause['id']}}


def load_bundle():
    return json.loads(BUNDLE.read_text(encoding='utf-8'))


def embed_complete(model, rows):
    import numpy as np
    tokenizer = model.tokenizer
    vectors = []
    for row in rows:
        ids = tokenizer(row['title']+'\n'+row['content'], add_special_tokens=False)['input_ids']
        window = model.max_seq_length-16
        parts = [tokenizer.decode(ids[n:n+window], skip_special_tokens=True) for n in range(0,len(ids),window-64)]
        vector = model.encode(parts, normalize_embeddings=True).mean(axis=0)
        vector /= np.linalg.norm(vector)
        vectors.append(vector.tolist())
    return vectors


def ingest(bundle):
    from database_guide.db_demo import mysql, import_knowledge
    from policy_search import embedding_model, MODEL_ID
    from pymilvus import MilvusClient
    rows = bundle['clauses']
    model = embedding_model()
    collection = os.environ['MILVUS_COLLECTION']
    client = MilvusClient(uri=os.environ['MILVUS_URI'], token=os.getenv('MILVUS_TOKEN') or '', timeout=30)
    try:
        fields = client.describe_collection(collection_name=collection)['fields']
        dim = int(next(f['params']['dim'] for f in fields if f['name']=='vector'))
        if dim != model.get_sentence_embedding_dimension():
            raise ValueError('向量维度不匹配，未写入')
        vectors = embed_complete(model, rows)
        # Preserve existing data; new batch version produces different primary keys.
        with mysql() as db, db.cursor() as cursor:
            cursor.execute('SELECT * FROM knowledge_chunks WHERE tenant_id=%s', (bundle['tenant_id'],))
            backup = cursor.fetchall()
        backup_path = ROOT/'policy_data'/('before-import-'+bundle['version']+'.json')
        if not backup_path.exists():
            backup_path.write_text(json.dumps(backup, ensure_ascii=False, default=str, indent=2), encoding='utf-8')
        staging = ROOT/'policy_data'/'knowledge-import.json'
        staging.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
        import_knowledge(staging)
        fields = ['id','tenant_id','doc_type','source_id','source_version','title','content','content_hash']
        entities = [dict({f:r[f] for f in fields}, vector=v, embedding_model=MODEL_ID) for r,v in zip(rows,vectors)]
        for n in range(0,len(entities),16):
            client.upsert(collection_name=collection, data=entities[n:n+16])
        client.flush(collection_name=collection)
        client.load_collection(collection_name=collection)
        count = client.query(collection_name=collection,
            filter=f'tenant_id == "{bundle["tenant_id"]}" and source_version == "{bundle["version"]}"',
            output_fields=['count(*)'], consistency_level='Strong')[0]['count(*)']
        if count != len(rows):
            raise ValueError('Milvus入库条数与JSON不一致，不切换当前版本')
        with mysql() as db, db.cursor() as cursor:
            for row in rows:
                cursor.execute("UPDATE knowledge_chunks SET sync_status='synced',sync_target=%s,synced_at=UTC_TIMESTAMP() WHERE id=%s AND content_hash=%s",
                    (collection+':'+MODEL_ID,row['id'],row['content_hash']))
            db.commit()
        active = dict(tenant_id=bundle['tenant_id'], version=bundle['version'], status='draft', count=count)
        temporary = ROOT/'policy_data'/'active.tmp'
        temporary.write_text(json.dumps(active,ensure_ascii=False,indent=2),encoding='utf-8')
        temporary.replace(ROOT/'policy_data'/'active.json')
        print(f'POLICY_IMPORT_OK documents={len(bundle["documents"])} clauses={count} version={bundle["version"]}', flush=True)
    finally:
        client.close()


def active_policy():
    path = ROOT/'policy_data'/'active.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None


def main():
    from dotenv import load_dotenv
    load_dotenv(ROOT/'.env')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT.parent)
    parser.add_argument('--ingest', action='store_true')
    args=parser.parse_args()
    bundle=convert(args.source)
    BUNDLE.parent.mkdir(exist_ok=True)
    BUNDLE.write_text(json.dumps(bundle,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'CLAUSES_JSON_OK documents={len(bundle["documents"])} clauses={len(bundle["clauses"])} rules={len(bundle["rules"])}',flush=True)
    if args.ingest:
        ingest(bundle)


if __name__=='__main__':
    main()
