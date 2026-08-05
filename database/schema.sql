-- SQLite Database Schema for Invoice Reconciliation

CREATE TABLE IF NOT EXISTS invoices (
    id TEXT PRIMARY KEY,
    invoice_no TEXT NOT NULL,
    vendor TEXT NOT NULL,
    invoice_date TEXT NOT NULL,
    currency TEXT DEFAULT 'USD',
    amount REAL NOT NULL,
    gst REAL DEFAULT 0.0,
    status TEXT DEFAULT 'PENDING' -- PENDING, APPROVED, REJECTED, HUMAN_REVIEW
);

CREATE TABLE IF NOT EXISTS invoice_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id TEXT NOT NULL,
    name TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL,
    total_price REAL NOT NULL,
    FOREIGN KEY (invoice_id) REFERENCES invoices (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS processed_invoices (
    id TEXT PRIMARY KEY,
    processing_id TEXT NOT NULL UNIQUE,
    file_name TEXT NOT NULL,
    extracted_json TEXT,
    state TEXT NOT NULL, -- INTAKE, DETECTED, EXTRACTED, VALIDATED, MATCHED, DECIDED, COMPLETED
    decision TEXT, -- APPROVED, REJECTED, HUMAN_REVIEW
    comments TEXT,
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS validation_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    processing_id TEXT NOT NULL,
    rule_name TEXT NOT NULL,
    status TEXT NOT NULL, -- PASS, FAIL
    error_message TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (processing_id) REFERENCES processed_invoices (processing_id)
);

CREATE TABLE IF NOT EXISTS matching_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    processing_id TEXT NOT NULL,
    similarity_score REAL NOT NULL,
    amount_difference_pct REAL NOT NULL,
    is_matched INTEGER DEFAULT 0,
    mismatch_details TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (processing_id) REFERENCES processed_invoices (processing_id)
);

CREATE TABLE IF NOT EXISTS human_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    processing_id TEXT NOT NULL,
    reviewer_comments TEXT,
    original_state TEXT,
    updated_state TEXT,
    reviewed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (processing_id) REFERENCES processed_invoices (processing_id)
);