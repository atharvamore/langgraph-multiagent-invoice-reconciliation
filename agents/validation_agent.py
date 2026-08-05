# agents/validation_agent.py
import sqlite3
import datetime
from config import settings
from utils.logger import setup_logger

logger = setup_logger("ValidationAgent")

class ValidationAgent:
    def __init__(self):
        """Store the database path used for business-rule validation."""
        self.db_path = settings.DB_PATH

    def run_business_validation(self, extracted_data: dict, processing_id: str) -> tuple[bool, list[str]]:
        """
        Applies business validation rules to the extracted data.
        """
        """Check for duplicates, date issues, and invalid line item values."""
        errors = []
        logger.info(f"Running business validation rules for: {processing_id}")

        # Rule 1: Duplicate Invoice Check
        invoice_no = extracted_data.get("invoice_no")
        vendor = extracted_data.get("vendor")
        if self._is_duplicate(invoice_no, vendor):
            err_msg = f"Duplicate Invoice Detected: {invoice_no} from {vendor} has already been processed."
            errors.append(err_msg)
            self._log_validation_rule(processing_id, "duplicate_check", "FAIL", err_msg)
        else:
            self._log_validation_rule(processing_id, "duplicate_check", "PASS")

        # Rule 2: Future Date Check
        invoice_date_str = extracted_data.get("invoice_date")
        try:
            invoice_date = datetime.datetime.strptime(invoice_date_str, "%Y-%m-%d").date()
            if invoice_date > datetime.date.today():
                err_msg = f"Invalid Date: Invoice date {invoice_date_str} cannot be in the future."
                errors.append(err_msg)
                self._log_validation_rule(processing_id, "future_date_check", "FAIL", err_msg)
            else:
                self._log_validation_rule(processing_id, "future_date_check", "PASS")
        except ValueError:
            # If the format is invalid but missed by structural schemas
            err_msg = f"Unparseable invoice date: {invoice_date_str}"
            errors.append(err_msg)
            self._log_validation_rule(processing_id, "future_date_check", "FAIL", err_msg)

        # Rule 3: Zero or Negative Item Prices Check
        products = extracted_data.get("products", [])
        for item in products:
            name = item.get("name", "Unknown")
            qty = item.get("quantity", 0)
            unit_price = item.get("unit_price", 0.0)
            if qty <= 0 or unit_price <= 0:
                err_msg = f"Non-positive quantity or price for line item: '{name}' (Qty: {qty}, Price: {unit_price})"
                errors.append(err_msg)
                self._log_validation_rule(processing_id, "positive_values_check", "FAIL", err_msg)
                break
        else:
            self._log_validation_rule(processing_id, "positive_values_check", "PASS")

        passed = len(errors) == 0
        state = "VALIDATED" if passed else "VALIDATED_FAIL"
        
        self._update_invoice_state(processing_id, state)
        return passed, errors

    def _is_duplicate(self, invoice_no: str, vendor: str) -> bool:
        """Checks if the invoice number already exists among approved reference records."""
        """Return True when an approved invoice with the same number and vendor already exists."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM invoices 
            WHERE invoice_no = ? AND vendor = ? AND status = 'APPROVED'
        """, (invoice_no, vendor))
        count = cursor.fetchone()[0]
        conn.close()
        return count > 0

    def _log_validation_rule(self, processing_id: str, rule: str, status: str, err_msg: str = None):
        """Insert one business-rule validation result into the logs table."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO validation_logs (processing_id, rule_name, status, error_message)
            VALUES (?, ?, ?, ?)
        """, (processing_id, rule, status, err_msg))
        conn.commit()
        conn.close()

    def _update_invoice_state(self, processing_id: str, state: str):
        """Update the workflow state for the current processed invoice record."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE processed_invoices
            SET state = ?, updated_at = CURRENT_TIMESTAMP
            WHERE processing_id = ?
        """, (state, processing_id))
        conn.commit()
        conn.close()
