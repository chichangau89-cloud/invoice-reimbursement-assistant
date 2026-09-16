import json
from uuid import uuid4
from pymysql.err import IntegrityError
from app.core.db import mysql_connection
from app.core.ids import validate_key


class NotFoundError(Exception):
    pass


class ConflictError(Exception):
    pass


def decoded(value):
    return json.loads(value) if isinstance(value, str) else value


def claim_row(row):
    if row is None:
        raise NotFoundError("Claim not found")
    row = dict(row)
    payload = decoded(row.pop("payload"))
    return {**payload, **row}


def audit_row(row):
    if row is None:
        raise NotFoundError("Audit not found")
    row = dict(row)
    result = decoded(row.pop("result"))
    row["input_snapshot"] = decoded(row["input_snapshot"])
    return {**result, **row}


class ClaimRepository:
    def create(self, payload):
        data = payload.model_dump(mode="json")
        tenant, claim = data.pop("tenant_id"), data.pop("claim_no")
        try:
            with mysql_connection() as db, db.cursor() as cur:
                cur.execute("INSERT INTO claims (tenant_id,claim_no,payload) VALUES (%s,%s,%s)",
                            (tenant, claim, json.dumps(data, ensure_ascii=False)))
                cur.execute("SELECT * FROM claims WHERE tenant_id=%s AND claim_no=%s", (tenant, claim))
                result = claim_row(cur.fetchone())
                db.commit()
                return result
        except IntegrityError as exc:
            if exc.args[0] == 1062:
                raise ConflictError("Claim already exists") from None
            raise

    def get(self, tenant, claim):
        validate_key(tenant, "tenant_id"); validate_key(claim, "claim_no")
        with mysql_connection(True) as db, db.cursor() as cur:
            cur.execute("SELECT * FROM claims WHERE tenant_id=%s AND claim_no=%s", (tenant, claim))
            return claim_row(cur.fetchone())

    def list(self, tenant, limit, offset):
        validate_key(tenant, "tenant_id")
        with mysql_connection(True) as db, db.cursor() as cur:
            cur.execute("SELECT * FROM claims WHERE tenant_id=%s ORDER BY created_at DESC,claim_no LIMIT %s OFFSET %s", (tenant, limit, offset))
            return [claim_row(row) for row in cur.fetchall()]

    def update(self, tenant, claim, payload):
        validate_key(tenant, "tenant_id"); validate_key(claim, "claim_no")
        data = payload.model_dump(mode="json")
        version = data.pop("expected_version")
        with mysql_connection() as db, db.cursor() as cur:
            cur.execute("SELECT * FROM claims WHERE tenant_id=%s AND claim_no=%s FOR UPDATE", (tenant, claim))
            current = claim_row(cur.fetchone())
            if current["version"] != version:
                raise ConflictError("Claim changed; reload and retry")
            cur.execute("UPDATE claims SET payload=%s,version=version+1,status='draft',latest_audit_id=NULL WHERE tenant_id=%s AND claim_no=%s",
                        (json.dumps(data, ensure_ascii=False), tenant, claim))
            cur.execute("SELECT * FROM claims WHERE tenant_id=%s AND claim_no=%s", (tenant, claim))
            result = claim_row(cur.fetchone()); db.commit()
            return result

    def snapshot(self, tenant, claim):
        validate_key(tenant, "tenant_id"); validate_key(claim, "claim_no")
        with mysql_connection() as db, db.cursor() as cur:
            # Consistent snapshot; no locks held during network/model calls.
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            cur.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT")
            cur.execute("SELECT * FROM claims WHERE tenant_id=%s AND claim_no=%s", (tenant, claim))
            row = claim_row(cur.fetchone())
            cur.execute("SELECT * FROM invoices WHERE tenant_id=%s AND claim_no=%s ORDER BY record_id", (tenant, claim))
            invoices = list(cur.fetchall())
            cur.execute("SELECT * FROM attachments WHERE tenant_id=%s AND claim_no=%s ORDER BY id", (tenant, claim))
            attachments = list(cur.fetchall())
            db.commit()
            return row, invoices, attachments

    def save_audit(self, tenant, claim, version, snapshot, result):
        audit_id = uuid4().hex
        with mysql_connection() as db, db.cursor() as cur:
            cur.execute("SELECT * FROM claims WHERE tenant_id=%s AND claim_no=%s FOR UPDATE", (tenant, claim))
            current = claim_row(cur.fetchone())
            # Invoice/attachment imports do not bump claim version: compare snapshots too.
            cur.execute("SELECT * FROM invoices WHERE tenant_id=%s AND claim_no=%s ORDER BY record_id", (tenant, claim))
            invoices = json.loads(json.dumps(list(cur.fetchall()), default=str))
            cur.execute("SELECT * FROM attachments WHERE tenant_id=%s AND claim_no=%s ORDER BY id", (tenant, claim))
            attachments = json.loads(json.dumps(list(cur.fetchall()), default=str))
            stale = current["version"] != version or invoices != snapshot["invoices"] or attachments != snapshot["attachments"]
            cur.execute("INSERT INTO audit_runs (audit_id,tenant_id,claim_no,claim_version,decision,risk_level,input_snapshot,result,stale) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (audit_id, tenant, claim, version, result.decision, result.risk_level,
                         json.dumps(snapshot, ensure_ascii=False), result.model_dump_json(), stale))
            if not stale:
                cur.execute("UPDATE claims SET status='audited',latest_audit_id=%s WHERE tenant_id=%s AND claim_no=%s", (audit_id, tenant, claim))
            cur.execute("SELECT * FROM audit_runs WHERE audit_id=%s", (audit_id,))
            saved = audit_row(cur.fetchone()); db.commit()
            return saved

    def get_audit(self, tenant, audit_id):
        validate_key(tenant, "tenant_id")
        with mysql_connection(True) as db, db.cursor() as cur:
            cur.execute("SELECT * FROM audit_runs WHERE tenant_id=%s AND audit_id=%s", (tenant, audit_id))
            return audit_row(cur.fetchone())

    def history(self, tenant, claim, limit, offset):
        self.get(tenant, claim)
        with mysql_connection(True) as db, db.cursor() as cur:
            cur.execute("SELECT * FROM audit_runs WHERE tenant_id=%s AND claim_no=%s ORDER BY created_at DESC,audit_id DESC LIMIT %s OFFSET %s", (tenant, claim, limit, offset))
            return [audit_row(row) for row in cur.fetchall()]
