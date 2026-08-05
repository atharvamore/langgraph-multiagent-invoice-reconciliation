import sqlite3
import uuid
import json
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from vector_db.vector_service import VectorStorageService

DB_PATH = os.path.join("database", "company.db")

def load_invoices_from_json(json_filepath):
    """Append JSON invoice records to SQLite as pending invoices and index item embeddings."""
    if not os.path.exists(json_filepath):
        print(f"❌ Error: File '{json_filepath}' not found.")
        return

    with open(json_filepath, 'r') as file:
        invoice_data_list = json.load(file)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    vector_service = VectorStorageService()
    success_count = 0

    for inv in invoice_data_list:
        invoice_id = str(uuid.uuid4())
        
        # Insert into SQLite as PENDING so the pipeline can validate and approve it later.
        cursor.execute("""
            INSERT INTO invoices (id, invoice_no, vendor, invoice_date, currency, amount, gst, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING')
        """, (invoice_id, inv["invoice_no"], inv["vendor"], inv["invoice_date"], 
              inv.get("currency", "USD"), inv["amount"], inv.get("gst", 0.0)))

        # Insert items into SQLite and ChromaDB
        for item in inv.get("items", []):
            item_vector_id = str(uuid.uuid4())
            
            cursor.execute("""
                INSERT INTO invoice_items (invoice_id, name, quantity, unit_price, total_price)
                VALUES (?, ?, ?, ?, ?)
            """, (invoice_id, item["name"], item["quantity"], item["unit_price"], item["total_price"]))

            try:
                vector_service.add_line_item(
                    item_id=item_vector_id,
                    invoice_no=inv["invoice_no"],
                    description=item["name"]
                )
            except Exception as e:
                print(f"⚠️ Vector indexing failed for {item['name']}: {e}")
        
        success_count += 1

    conn.commit()
    conn.close()
    print(f"✅ Successfully loaded {success_count} invoices from {json_filepath} into the database as PENDING records!")

if __name__ == "__main__":
    # ONLY CHANGE THIS LINE to point to your newly generated JSON file
    JSON_FILE_PATH = "it_company_bills_01.json" 
    
    load_invoices_from_json(JSON_FILE_PATH)
