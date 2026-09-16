"""Explicit, additive schema migration. Never runs on API startup."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.db import mysql_connection

if __name__ == "__main__":
    sql = (Path(__file__).resolve().parents[1] / "migrations/001_claims_audit_runs.sql").read_text(encoding="utf-8")
    with mysql_connection() as db, db.cursor() as cur:
        for statement in sql.split(";"):
            if statement.strip():
                cur.execute(statement)
        db.commit()
    print("Migration complete: claims, audit_runs")
