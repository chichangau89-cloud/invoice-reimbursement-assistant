-- Local learning schema, not a full production finance schema.
USE reimbursement_demo;

CREATE TABLE IF NOT EXISTS invoices (
    record_id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    tenant_id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    claim_no VARCHAR(64) NOT NULL,
    invoice_no VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    issue_date DATE NOT NULL,
    buyer_name VARCHAR(200) NOT NULL,
    seller_name VARCHAR(200) NOT NULL,
    total_amount DECIMAL(18,2) NOT NULL,
    currency CHAR(3) NOT NULL DEFAULT 'CNY',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_invoice_lookup (tenant_id, invoice_no, issue_date),
    INDEX idx_claim (tenant_id, claim_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS attachments (
    id CHAR(64) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    tenant_id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    claim_no VARCHAR(64) NOT NULL,
    original_name VARCHAR(255) NOT NULL,
    storage_path VARCHAR(1000) NOT NULL,
    sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    size_bytes BIGINT UNSIGNED NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_attachment_claim (tenant_id, claim_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id CHAR(64) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    tenant_id VARCHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    source_id VARCHAR(128) NOT NULL,
    source_version VARCHAR(32) NOT NULL,
    chunk_no INT UNSIGNED NOT NULL,
    doc_type VARCHAR(32) NOT NULL,
    title VARCHAR(200) NOT NULL,
    content TEXT NOT NULL,
    content_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    sync_status VARCHAR(16) NOT NULL DEFAULT 'pending',
    sync_target VARCHAR(512) NOT NULL DEFAULT '',
    synced_at DATETIME NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_sync (sync_status, is_active),
    INDEX idx_source (tenant_id, source_id, source_version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
