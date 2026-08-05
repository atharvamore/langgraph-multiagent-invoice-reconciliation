# guardrails/validators.py
import sqlite3
from guardrails.schemas import ExtractedInvoice
from config import settings
from utils.logger import setup_logger

logger = setup_logger("GuardrailValidator")

class GuardrailValidator:
    def __init__(self):
        """Store the database path used for validation logging."""
        self.db_path = settings.DB_PATH

    def audit_and_validate(self, extracted_data: dict, processing_id: str) -> tuple[bool, list[str]]:
        """Validate schema, required fields, and invoice math before business processing."""
        validation_errors = []
        logger.info(f"Initiating schema guardrail checks for: {processing_id}")

        # Check 1: Pydantic Schema Verification
        try:
            validated_obj = ExtractedInvoice(**extracted_data)
        except Exception as e:
            err_msg = f"Pydantic Validation failed: {str(e)}"
            validation_errors.append(err_msg)
            self._log_validation_rule(processing_id, "schema_validation", "FAIL", err_msg)
            return False, validation_errors

        self._log_validation_rule(processing_id, "schema_validation", "PASS")

        # Check 2: Verifying Critical Fields
        required_fields = ["invoice_no", "vendor", "invoice_date", "amount"]
        for field in required_fields:
            val = getattr(validated_obj, field, None)
            if val is None or str(val).strip() in ["", "UNKNOWN"]:
                err_msg = f"Missing core mandatory field: {field}"
                validation_errors.append(err_msg)
                self._log_validation_rule(processing_id, f"field_check_{field}", "FAIL", err_msg)
            elif isinstance(val, (int, float)) and val <= 0:
                err_msg = f"Missing core mandatory field: {field} (amount must be positive)"
                validation_errors.append(err_msg)
                self._log_validation_rule(processing_id, f"field_check_{field}", "FAIL", err_msg)

        # Check 3: Line Item Total vs Invoice Total Sum Check
        tolerance = 1.00

        normalized_items = []
        for item in validated_obj.products:
            expected_item_total = float(item.quantity) * float(item.unit_price)
            if abs(float(item.total_price) - expected_item_total) <= tolerance:
                normalized_items.append(expected_item_total)
            else:
                normalized_items.append(float(item.total_price))

        calculated_subtotal = sum(normalized_items)
        calculated_grand_total = calculated_subtotal + float(validated_obj.gst or 0.0)

        if validated_obj.products:
            amount_base = float(validated_obj.amount or 0.0)
            diff = abs(calculated_grand_total - amount_base)
            diff_pct = (diff / amount_base) * 100 if amount_base > 0 else 100.0

            if diff_pct <= 5.0:
                warn_msg = (
                    f"Invoice line items + GST ({calculated_grand_total}) differs from "
                    f"stated total ({validated_obj.amount}) by {diff_pct:.2f}%, continuing."
                )
                self._log_validation_rule(processing_id, "sum_matching_check", "PASS", warn_msg)
            else:
                err_msg = (
                    f"Invoice line items + GST ({calculated_grand_total}) does not align with "
                    f"stated total ({validated_obj.amount}); variance is {diff_pct:.2f}%"
                )
                validation_errors.append(err_msg)
                self._log_validation_rule(processing_id, "sum_matching_check", "FAIL", err_msg)
        else:
            self._log_validation_rule(processing_id, "sum_matching_check", "PASS")

        passed = len(validation_errors) == 0
        return passed, validation_errors

    def _log_validation_rule(self, processing_id: str, rule: str, status: str, err_msg: str = None):
        """Save the outcome of one guardrail check into the validation log table."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO validation_logs (processing_id, rule_name, status, error_message)
                VALUES (?, ?, ?, ?)
            """, (processing_id, rule, status, err_msg))
            conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Failed writing validation log for rule: {rule}: {e}")
        finally:
            conn.close()
