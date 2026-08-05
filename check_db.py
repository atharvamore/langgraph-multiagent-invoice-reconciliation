import sqlite3
import os

def check_invoices_table():
    """Inspect the invoices table schema and print every stored record."""
    db_path = os.path.join("database", "company.db")
    print(f"--- ANALYZING TABLE STRUCTURE: {db_path} ---")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get exact column names
        cursor.execute("PRAGMA table_info(invoices)")
        columns = [col[1] for col in cursor.fetchall()]
        print(f"Columns found: {columns}\n")
        
        # Fetch all records
        cursor.execute("SELECT * FROM invoices")
        rows = cursor.fetchall()
        
        print(f"Total invoices stored: {len(rows)}")
        print("-" * 50)
        
        # Print each row matching data to its column name
        for row in rows:
            row_data = dict(zip(columns, row))
            print(f"Invoice: {row_data.get('invoice_no', 'N/A')}")
            for key, value in row_data.items():
                if key != 'invoice_no':
                    print(f"  {key}: {value}")
            print("-" * 30)
                
    except sqlite3.Error as e:
        print(f"Database error: {e}")
    finally:
        if 'conn' in locals() and conn:
            conn.close()

if __name__ == "__main__":
    check_invoices_table()
