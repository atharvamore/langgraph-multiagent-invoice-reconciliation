# agents/retrieval_agent.py
import sqlite3
from rapidfuzz import fuzz
from config import settings
from utils.logger import setup_logger
from vector_db.vector_service import VectorStorageService
from rapidfuzz import process

logger = setup_logger("CompanyRetrievalAgent")

class CompanyRetrievalAgent:
    def __init__(self):
        """Initialize the retrieval agent with SQLite access and the vector store."""
        self.db_path = settings.DB_PATH
        self.vector_service = VectorStorageService()

    def retrieve_reference_invoice(self, extracted_invoice: dict, processing_id: str) -> dict:
        """
        Finds the best matching invoice in the database.
        Preference order:
        1. Exact approved invoice number + vendor match
        2. Ranked candidate search across approved and pending invoices using
           vendor similarity, item overlap, amount proximity, and semantic hints.
        """
        invoice_no = extracted_invoice.get("invoice_no")
        vendor = extracted_invoice.get("vendor")
        extracted_products = extracted_invoice.get("products", [])
        
        logger.info(f"Retrieving company reference invoice matching No: {invoice_no}, Vendor: {vendor}")
        
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Step 1: Look for exact invoice number and vendor match
        # We allow any status here because newly loaded PENDING invoices should
        # still be discoverable as the intended comparison target.
        cursor.execute("""
            SELECT * FROM invoices 
            WHERE invoice_no = ? AND vendor = ?
            ORDER BY CASE status
                WHEN 'APPROVED' THEN 0
                WHEN 'PENDING' THEN 1
                ELSE 2
            END
        """, (invoice_no, vendor))
        exact_rows = cursor.fetchall()

        if exact_rows:
            reference_data = dict(exact_rows[0])
            reference_data["products"] = self._load_items_for_invoice(cursor, reference_data["id"])
            conn.close()
            logger.info(f"Exact database reference match discovered: {reference_data['id']}")
            return reference_data

        logger.warning(
            f"No exact approved SQL match for invoice {invoice_no}. "
            "Running ranked candidate selection across approved and pending invoices..."
        )

        cursor.execute("""
            SELECT * FROM invoices
            WHERE invoice_no != ?
            ORDER BY CASE status
                WHEN 'APPROVED' THEN 0
                WHEN 'PENDING' THEN 1
                ELSE 2
            END, invoice_date DESC
        """, (invoice_no,))
        all_candidates = cursor.fetchall()
        conn.close()

        vendor_candidates = self._filter_vendor_candidates(vendor, all_candidates)
        best_candidate = self._select_best_candidate(extracted_invoice, vendor_candidates)
        if best_candidate:
            logger.info(
                f"Ranked match selected from DB: Invoice {best_candidate['invoice_no']} "
                f"(status={best_candidate['status']})"
            )
            return best_candidate

        # Final fallback: semantic search, but only if it can map to a real DB invoice.
        logger.warning("Ranked candidate search found no usable match. Trying vector search fallback...")
        if extracted_products:
            sample_product = extracted_products[0].get("name", "")
            vector_matches = self.vector_service.query_similar_items(sample_product, limit=3)
            matched_invoice_no = self._resolve_invoice_from_vector_matches(vector_matches)
            if matched_invoice_no:
                conn = sqlite3.connect(self.db_path)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM invoices WHERE invoice_no = ?", (matched_invoice_no,))
                ref_row = cursor.fetchone()
                if ref_row:
                    reference_data = dict(ref_row)
                    reference_data["products"] = self._load_items_for_invoice(cursor, reference_data["id"])
                    conn.close()
                    logger.info(f"Semantic match found from Vector DB: Invoice {matched_invoice_no}")
                    return reference_data
                conn.close()

        logger.error(f"No reference match found for invoice: {invoice_no}")
        return None

    def _load_items_for_invoice(self, cursor, invoice_id: str) -> list[dict]:
        """Load all line items associated with one invoice row."""
        cursor.execute("SELECT * FROM invoice_items WHERE invoice_id = ?", (invoice_id,))
        return [dict(row) for row in cursor.fetchall()]

    def _select_best_candidate(self, extracted_invoice: dict, candidates) -> dict | None:
        """Score candidate invoices and return the highest-quality match."""
        extracted_vendor = extracted_invoice.get("vendor", "") or ""
        extracted_products = extracted_invoice.get("products", []) or []
        extracted_amount = float(extracted_invoice.get("amount", 0.0) or 0.0)

        best_score = 0.0
        best_candidate = None

        for row in candidates:
            candidate = dict(row)
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            candidate["products"] = self._load_items_for_invoice(cursor, candidate["id"])
            conn.close()

            vendor_score = fuzz.token_sort_ratio(extracted_vendor, candidate.get("vendor", ""))
            amount_score = self._amount_score(extracted_amount, float(candidate.get("amount", 0.0) or 0.0))
            items_score = self._items_score(extracted_products, candidate.get("products", []))
            status_bonus = 100.0 if candidate.get("status") == "PENDING" else 90.0
            date_score = self._date_score(extracted_invoice.get("invoice_date"), candidate.get("invoice_date"))

            # Vendor similarity is a hard gate for non-exact matches.
            if vendor_score < 75.0:
                continue

            overall = (
                vendor_score * 0.45 +
                items_score * 0.30 +
                amount_score * 0.15 +
                date_score * 0.05 +
                status_bonus * 0.05
            )

            if overall > best_score:
                best_score = overall
                best_candidate = candidate

        if best_candidate and best_score >= 55.0:
            return best_candidate
        return None

    def _filter_vendor_candidates(self, extracted_vendor: str, candidates) -> list[dict]:
        """
        Prefer candidates from the same vendor family before running the full score.
        This prevents line-item similarity from pulling in the wrong company invoice.
        """
        """Restrict the candidate pool to invoices from the same or similar vendor."""
        extracted_vendor = extracted_vendor or ""
        if not extracted_vendor:
            return [dict(row) for row in candidates]

        rows = [dict(row) for row in candidates]
        exact_vendor_matches = [row for row in rows if row.get("vendor", "").strip().lower() == extracted_vendor.strip().lower()]
        if exact_vendor_matches:
            return exact_vendor_matches

        close_vendor_matches = []
        for row in rows:
            score = fuzz.token_sort_ratio(extracted_vendor, row.get("vendor", ""))
            if score >= 75.0:
                close_vendor_matches.append(row)

        if close_vendor_matches:
            return close_vendor_matches

        return rows

    def _items_score(self, extracted_products: list[dict], reference_products: list[dict]) -> float:
        """Measure how closely the extracted line items match the reference items."""
        if not extracted_products or not reference_products:
            return 0.0

        total = 0.0
        for ext_item in extracted_products:
            best = 0.0
            ext_name = ext_item.get("name", "")
            for ref_item in reference_products:
                score = fuzz.token_sort_ratio(ext_name, ref_item.get("name", ""))
                if score > best:
                    best = score
            total += best

        return total / max(len(extracted_products), 1)

    def _amount_score(self, extracted_amount: float, reference_amount: float) -> float:
        """Convert amount difference into a similarity-style score."""
        if extracted_amount <= 0 or reference_amount <= 0:
            return 0.0
        diff_pct = abs(extracted_amount - reference_amount) / reference_amount * 100
        return max(0.0, 100.0 - min(diff_pct, 100.0))

    def _date_score(self, extracted_date: str, reference_date: str) -> float:
        """Assign a simple score for exact or near-exact invoice-date alignment."""
        if not extracted_date or not reference_date:
            return 0.0
        return 100.0 if extracted_date == reference_date else 60.0

    def _resolve_invoice_from_vector_matches(self, vector_matches) -> str | None:
        """Translate a vector search hit back into an invoice number if possible."""
        if not vector_matches or not vector_matches.get("metadatas"):
            return None

        for metadata_group in vector_matches["metadatas"]:
            for meta in metadata_group:
                invoice_no = meta.get("invoice_no")
                if invoice_no:
                    return invoice_no
        return None
