# database/seed_data.py
import sqlite3
import os
import sys

# Append project root to path to allow absolute imports when running directly
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vector_db.vector_service import VectorStorageService

DB_PATH = os.path.join("database", "company.db")
SCHEMA_PATH = os.path.join("database", "schema.sql")

def init_db():
    """Create the SQLite schema for the invoice reconciliation database."""
    if not os.path.exists("database"):
        os.makedirs("database")
        
    with open(SCHEMA_PATH, "r") as f:
        schema_sql = f.read()
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.executescript(schema_sql)
    conn.commit()
    conn.close()
    print("Database schema applied successfully.")

def seed_company_invoices():
    """Insert trusted approved reference invoices and index their line items into ChromaDB."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Check if data already exists
    cursor.execute("SELECT COUNT(*) FROM invoices")
    if cursor.fetchone()[0] > 0:
        print("Database already contains SQL data.")
    else:
        # Seed approved reference invoices
        reference_invoices = [
            ("INV-2026-001", "Acme Corporation", "2026-03-01", "USD", 15000.00, 1200.00),
            ("INV-2026-002", "Globex Industries", "2026-03-05", "USD", 850.50, 0.00),
            ("INV-2026-003", "Initech Solutions", "2026-03-10", "USD", 4320.00, 345.60)
        ]
        
        for idx, inv in enumerate(reference_invoices):
            inv_id = f"ref_id_00{idx+1}"
            cursor.execute("""
                INSERT INTO invoices (id, invoice_no, vendor, invoice_date, currency, amount, gst, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'APPROVED')
            """, (inv_id, inv[0], inv[1], inv[2], inv[3], inv[4], inv[5]))
            
        # Seed items
        items = [
            ("ref_id_001", "Enterprise Cloud Licensing", 1, 15000.00, 15000.00),
            ("ref_id_002", "Mechanical Keyboard Upgrades", 10, 85.05, 850.50),
            ("ref_id_003", "Network Integration Consultancy", 24, 180.00, 4320.00)
        ]
        
        for item in items:
            cursor.execute("""
                INSERT INTO invoice_items (invoice_id, name, quantity, unit_price, total_price)
                VALUES (?, ?, ?, ?, ?)
            """, item)
            
        conn.commit()
        print("Database seeded with relational SQL records.")
    
    conn.close()

    # --- Seed ChromaDB Vector Database ---
    print("Indexing reference items into ChromaDB Vector Store...")
    vector_service = VectorStorageService()
    
    # Index descriptions matching our seeded database items
    reference_embeddings = [
        ("item_001", "INV-2026-001", "Enterprise Cloud Licensing"),
        ("item_002", "INV-2026-002", "Mechanical Keyboard Upgrades"),
        ("item_003", "INV-2026-003", "Network Integration Consultancy")
    ]
    
    for item_id, invoice_no, description in reference_embeddings:
        try:
            vector_service.add_line_item(
                item_id=item_id,
                invoice_no=invoice_no,
                description=description
            )
            print(f"Indexed line item: '{description}' -> Invoice {invoice_no}")
        except Exception as e:
            print(f"Error indexing {description}: {str(e)}")

    print("Vector indexing sequence completed.")

if __name__ == "__main__":
    init_db()
    seed_company_invoices()
