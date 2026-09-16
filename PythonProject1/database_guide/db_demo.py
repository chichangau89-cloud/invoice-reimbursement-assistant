"""Learning CLI: files/CSV/JSON -> MySQL -> real embeddings -> Milvus -> MySQL.

Run from database_guide. No OCR, automatic policy parsing, or finance decision is implemented.
"""
import argparse
import csv
import hashlib
import json
import os
import re
import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

BASE = Path(__file__).resolve().parent


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def identity(parts):
    return digest(json.dumps(parts, ensure_ascii=False, separators=(",", ":")))


def config():
    from dotenv import load_dotenv
    load_dotenv(BASE.parent / ".env")
    if not os.getenv("MYSQL_PASSWORD") or "CHANGE_ME" in os.getenv("MYSQL_PASSWORD", ""):
        raise ValueError("Copy .env.example to .env and set MYSQL_PASSWORD first.")


def mysql():
    import pymysql
    return pymysql.connect(
        host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        port=int(os.getenv("MYSQL_PORT", "3307")),
        user=os.getenv("MYSQL_USER", "reimbursement_app"),
        password=os.environ["MYSQL_PASSWORD"],
        database=os.getenv("MYSQL_DATABASE", "reimbursement_demo"),
        charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
        autocommit=False, connect_timeout=10,
    )


def key(value):
    # Demo identifiers only; also keeps Milvus filter construction safe.
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
        raise ValueError(f"Identifier must be 1-64 ASCII letters/digits/_/-: {value!r}")
    return value


def import_invoices(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    values = []
    for r in rows:
        amount = Decimal(r["total_amount"])
        if not amount.is_finite() or abs(amount) >= Decimal("1e16"):
            raise ValueError("Amount is not a finite DECIMAL(18,2) value")
        if amount != amount.quantize(Decimal("0.01")):
            raise ValueError("Amount must have at most two decimal places")
        if not r["invoice_no"] or len(r["invoice_no"]) > 64:
            raise ValueError("Invalid invoice_no")
        if not re.fullmatch("[A-Z]{3}", r["currency"]):
            raise ValueError("Use a three-letter currency such as CNY")
        # CSV record_id is tenant-local; the database key includes tenant identity.
        row_id = identity([key(r["tenant_id"]), key(r["record_id"])])
        values.append((row_id, r["tenant_id"], r["claim_no"], r["invoice_no"],
                       date.fromisoformat(r["issue_date"]), r["buyer_name"],
                       r["seller_name"], amount, r["currency"]))
    with mysql() as db, db.cursor() as cur:
        cur.executemany("""
            INSERT INTO invoices
            (record_id,tenant_id,claim_no,invoice_no,issue_date,buyer_name,seller_name,total_amount,currency)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) AS incoming
            ON DUPLICATE KEY UPDATE claim_no=incoming.claim_no, invoice_no=incoming.invoice_no,
            issue_date=incoming.issue_date, buyer_name=incoming.buyer_name,
            seller_name=incoming.seller_name, total_amount=incoming.total_amount,
            currency=incoming.currency
        """, values)
        db.commit()
    print(f"MYSQL_INVOICES_OK rows={len(values)} (input rows processed)")


def import_knowledge(path):
    rows = json.loads(path.read_text(encoding="utf-8-sig"))
    values = []
    for r in rows:
        tenant = key(r["tenant_id"])
        if r["doc_type"] not in {"policy", "subject", "audit_case", "ticket_text"}:
            raise ValueError("Unsupported doc_type")
        if not r["content"].strip() or len(r["content"].encode("utf-8")) > 6000:
            raise ValueError("Split content into non-empty small clauses first")
        if not r["title"].strip() or len(r["title"].encode("utf-8")) > 600:
            raise ValueError("Title must be non-empty and at most 600 UTF-8 bytes")
        if type(r["chunk_no"]) is not int or r["chunk_no"] < 0:
            raise ValueError("chunk_no must be a non-negative integer")
        for field, limit in (("source_id", 128), ("source_version", 32)):
            if not r[field] or len(r[field]) > limit:
                raise ValueError(f"Invalid {field}")
        doc_id = identity([tenant, r["source_id"], r["source_version"], r["chunk_no"]])
        content_hash = identity([r["title"], r["content"], r["doc_type"]])
        values.append((doc_id, tenant, r["source_id"], r["source_version"],
                       r["chunk_no"], r["doc_type"], r["title"], r["content"], content_hash))
    with mysql() as db, db.cursor() as cur:
        cur.executemany("""
            INSERT INTO knowledge_chunks
            (id,tenant_id,source_id,source_version,chunk_no,doc_type,title,content,content_hash)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) AS incoming
            ON DUPLICATE KEY UPDATE doc_type=incoming.doc_type, title=incoming.title,
            content=incoming.content, content_hash=incoming.content_hash,
            sync_status='pending', is_active=TRUE
        """, values)
        db.commit()
    print(f"MYSQL_KNOWLEDGE_OK rows={len(values)}")


def attach(path, tenant, claim):
    key(tenant)
    path = path.resolve(strict=True)
    if not path.is_file():
        raise ValueError("Attachment must be a file")
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    file_hash = h.hexdigest()
    destination = BASE / "data" / "attachments" / tenant / file_hash
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        shutil.copyfile(path, destination)
    with mysql() as db, db.cursor() as cur:
        cur.execute("""INSERT INTO attachments
            (id,tenant_id,claim_no,original_name,storage_path,sha256,size_bytes)
            VALUES (%s,%s,%s,%s,%s,%s,%s) AS incoming
            ON DUPLICATE KEY UPDATE original_name=incoming.original_name,
            storage_path=incoming.storage_path""",
            (identity([tenant, claim, file_hash]), tenant, claim, path.name,
             destination.relative_to(BASE).as_posix(), file_hash, destination.stat().st_size))
        db.commit()
    print(f"ATTACHMENT_OK stored={destination}")


def vector_resources():
    from pymilvus import MilvusClient, DataType
    from sentence_transformers import SentenceTransformer
    model_id = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
    if model_id != "BAAI/bge-small-zh-v1.5":
        raise ValueError("This demo uses BGE-small-zh-v1.5; adapt encoding and collection for another model")
    model = SentenceTransformer(os.getenv("EMBEDDING_PATH") or model_id, device="cpu")
    dim = int(os.getenv("EMBEDDING_DIM", "512"))
    if model.get_sentence_embedding_dimension() != dim:
        raise ValueError("EMBEDDING_DIM does not match the loaded model")
    name = os.getenv("MILVUS_COLLECTION", "reimbursement_knowledge_bge_small_zh_v1")
    key(name)
    client = MilvusClient(uri=os.getenv("MILVUS_URI", "http://127.0.0.1:19530"),
                          token=os.getenv("MILVUS_TOKEN", ""), timeout=60)
    try:
        if not client.has_collection(collection_name=name):
            schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
            schema.add_field(field_name="id", datatype=DataType.VARCHAR, is_primary=True, max_length=64)
            for field, length in (("tenant_id", 64), ("doc_type", 32), ("source_id", 512),
                                  ("source_version", 128), ("title", 600), ("content", 6000),
                                  ("content_hash", 64), ("embedding_model", 128)):
                schema.add_field(field_name=field, datatype=DataType.VARCHAR, max_length=length)
            schema.add_field(field_name="vector", datatype=DataType.FLOAT_VECTOR, dim=dim)
            indexes = client.prepare_index_params()
            indexes.add_index(field_name="vector", index_type="AUTOINDEX", metric_type="COSINE")
            client.create_collection(collection_name=name, schema=schema,
                                     index_params=indexes, consistency_level="Strong")
        fields = client.describe_collection(collection_name=name)["fields"]
        vector = next(f for f in fields if f["name"] == "vector")
        if int(vector["params"]["dim"]) != dim:
            raise ValueError("Existing collection has a different vector dimension; use a new collection")
        client.load_collection(collection_name=name)
        return client, name, model, model_id
    except Exception:
        client.close()
        raise


def encode(model, texts):
    for text in texts:
        length = len(model.tokenizer(text, add_special_tokens=True, truncation=False)["input_ids"])
        if length > model.max_seq_length:
            raise ValueError(f"Text has {length} tokens; split below {model.max_seq_length} tokens")
    return model.encode(texts, normalize_embeddings=True, batch_size=16).tolist()


def sync(tenant):
    key(tenant)
    client, name, model, model_id = vector_resources()
    target = name + ":" + model_id
    count, after = 0, ""
    try:
        while True:
            with mysql() as db, db.cursor() as cur:
                cur.execute("""SELECT * FROM knowledge_chunks WHERE tenant_id=%s
                    AND is_active=TRUE AND id>%s
                    AND (sync_status<>'synced' OR sync_target<>%s)
                    ORDER BY id LIMIT 64""", (tenant, after, target))
                rows = cur.fetchall()
            if not rows:
                break
            vectors = encode(model, [r["title"] + "\n" + r["content"] for r in rows])
            fields = ("id", "tenant_id", "doc_type", "source_id", "source_version", "title", "content", "content_hash")
            entities = [dict({f: r[f] for f in fields}, vector=v, embedding_model=model_id)
                        for r, v in zip(rows, vectors)]
            client.upsert(collection_name=name, data=entities)
            with mysql() as db, db.cursor() as cur:
                for r in rows:
                    cur.execute("""UPDATE knowledge_chunks SET sync_status='synced',
                        sync_target=%s, synced_at=UTC_TIMESTAMP()
                        WHERE id=%s AND content_hash=%s AND is_active=TRUE""",
                        (target, r["id"], r["content_hash"]))
                db.commit()
            count += len(rows)
            after = rows[-1]["id"]
        print(f"MILVUS_SYNC_OK rows={count} collection={name}")
    finally:
        client.close()


def search(tenant, question, doc_type):
    key(tenant)
    client, name, model, model_id = vector_resources()
    try:
        vector = encode(model, ["为这个句子生成表示以用于检索相关文章：" + question])[0]
        hits = client.search(collection_name=name, data=[vector], anns_field="vector",
            filter=f'tenant_id == "{tenant}" and doc_type == "{doc_type}"', limit=10,
            output_fields=["content_hash", "embedding_model"],
            search_params={"metric_type": "COSINE", "params": {}}, consistency_level="Strong")[0]
        valid = []
        with mysql() as db, db.cursor() as cur:
            for hit in hits:
                cur.execute("SELECT * FROM knowledge_chunks WHERE id=%s AND tenant_id=%s AND is_active=TRUE",
                            (str(hit["id"]), tenant))
                row = cur.fetchone()
                if row and row["content_hash"] == hit["entity"]["content_hash"] and hit["entity"]["embedding_model"] == model_id:
                    valid.append({"id": row["id"], "score": hit["distance"], "source_id": row["source_id"],
                                  "source_version": row["source_version"], "title": row["title"], "content": row["content"]})
        print(json.dumps(valid[:3], ensure_ascii=False, indent=2))
        print(f"SEARCH_OK valid_candidates={len(valid[:3])}; similarity is NOT an approval decision")
    finally:
        client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("import-invoices", "import-knowledge"):
        sub.add_parser(command).add_argument("path", type=Path)
    a = sub.add_parser("attach")
    a.add_argument("path", type=Path)
    a.add_argument("--tenant", required=True)
    a.add_argument("--claim", required=True)
    sub.add_parser("sync").add_argument("--tenant", required=True)
    s = sub.add_parser("search")
    s.add_argument("question")
    s.add_argument("--tenant", required=True)
    s.add_argument("--type", choices=["policy", "subject", "audit_case", "ticket_text"], default="policy")
    args = parser.parse_args()
    config()
    if args.command == "import-invoices":
        import_invoices(args.path)
    elif args.command == "import-knowledge":
        import_knowledge(args.path)
    elif args.command == "attach":
        attach(args.path, args.tenant, args.claim)
    elif args.command == "sync":
        sync(args.tenant)
    elif args.command == "search":
        search(args.tenant, args.question, args.type)


if __name__ == "__main__":
    main()
