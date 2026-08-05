# agents/decision_agent.py
import sqlite3
import os
import shutil
from config import settings
from utils.logger import setup_logger

logger = setup_logger("DecisionAgent")

class DecisionAgent:
    def __init__(self):
        """Store the database path used to persist the final routing decision."""
        self.db_path = settings.DB_PATH

    def make_decision(self, comparison_report: dict, processing_id: str, source_file_path: str) -> str:
        """
        Applies company policy thresholds to determine the final state.
        Moves the invoice files to their target directories.
        """
        """Route the invoice to approve, review, or reject based on comparison results."""
        variance = comparison_report.get("amount_difference_pct", 100.0)
        overall_similarity = comparison_report.get("overall_similarity", 0.0)
        
        logger.info(f"Evaluating decision policies for {processing_id}. Variance: {variance:.2f}%")
        
        filename = os.path.basename(source_file_path)

        # if variance < 5.0 and overall_similarity >= 80.0:
        #     decision = "APPROVED"
        #     dest_dir = settings.PROCESSED_DIR
        #     comments = f"Auto-Approved: Variance within acceptable limits ({variance:.2f}%)."
        #     state = "COMPLETED"
        # elif variance <= 15.0:
        #     decision = "HUMAN_REVIEW"
        #     dest_dir = settings.HUMAN_REVIEW_DIR
        #     comments = f"Needs Human Review: Variance is {variance:.2f}% (acceptable threshold is <5.0%)."
        #     state = "HUMAN_REVIEW"
        # else:
        #     decision = "REJECTED"
        #     dest_dir = settings.REJECTED_DIR
        #     comments = f"Auto-Rejected: Amount variance exceeds acceptable limits ({variance:.2f}%)."
        #     state = "COMPLETED"


        # Auto-approve near-perfect matches
        if variance < 5.0 and overall_similarity >= 80.0:
            decision = "APPROVED"
            dest_dir = settings.PROCESSED_DIR
            comments = f"Auto-Approved: Variance within acceptable limits ({variance:.2f}%)."
            state = "COMPLETED"
        
        # Everything else goes to a human
        else:
            decision = "HUMAN_REVIEW"
            dest_dir = settings.HUMAN_REVIEW_DIR
            comments = f"Needs Human Review: Variance is {variance:.2f}% (acceptable threshold is <5.0%)."
            state = "HUMAN_REVIEW"


        # Move file to its target folder
        if os.path.exists(source_file_path):
            shutil.move(source_file_path, os.path.join(dest_dir, filename))
            logger.info(f"Invoice file moved to directory: {dest_dir}")

        # Update database
        self._record_decision(processing_id, decision, state, comments)
        return decision

    def _record_decision(self, processing_id: str, decision: str, state: str, comments: str):
        """Write the final decision to workflow tables and sync the invoice master row."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Pull the extracted invoice identity so we can sync the master invoice row too.
        cursor.execute("""
            SELECT extracted_json FROM processed_invoices WHERE processing_id = ?
        """, (processing_id,))
        row = cursor.fetchone()

        invoice_no = None
        vendor = None
        if row and row[0]:
            try:
                import json
                extracted = json.loads(row[0])
                invoice_no = extracted.get("invoice_no")
                vendor = extracted.get("vendor")
            except Exception:
                invoice_no = None
                vendor = None

        cursor.execute("""
            UPDATE processed_invoices
            SET state = ?, decision = ?, comments = ?, updated_at = CURRENT_TIMESTAMP
            WHERE processing_id = ?
        """, (state, decision, comments, processing_id))

        # Keep the master invoice table aligned with the workflow result.
        if invoice_no and vendor:
            cursor.execute("""
                UPDATE invoices
                SET status = ?, invoice_date = invoice_date
                WHERE invoice_no = ? AND vendor = ?
            """, (decision, invoice_no, vendor))

        conn.commit()
        conn.close()
