CREATE TABLE IF NOT EXISTS claims (
 tenant_id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 claim_no VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 payload JSON NOT NULL,
 version INT UNSIGNED NOT NULL DEFAULT 1,
 status VARCHAR(16) NOT NULL DEFAULT 'draft',
 latest_audit_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
 PRIMARY KEY (tenant_id, claim_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE IF NOT EXISTS audit_runs (
 audit_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
 tenant_id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 claim_no VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
 claim_version INT UNSIGNED NOT NULL,
 decision VARCHAR(24) NOT NULL,
 risk_level VARCHAR(16) NOT NULL,
 input_snapshot JSON NOT NULL,
 result JSON NOT NULL,
 stale BOOLEAN NOT NULL DEFAULT FALSE,
 created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
 INDEX idx_claim_history (tenant_id, claim_no, created_at),
 FOREIGN KEY (tenant_id, claim_no) REFERENCES claims(tenant_id, claim_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
