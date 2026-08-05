# agents/matching_agent.py
import sqlite3
from rapidfuzz import fuzz
from config import settings
from utils.logger import setup_logger

logger = setup_logger("MatchingAgent")

class MatchingAgent:
    def __init__(self):
        """Store the database path used for writing matching logs."""
        self.db_path = settings.DB_PATH

    def compare_invoices(self, extracted: dict, reference: dict, processing_id: str) -> dict:
        """
        Compares the extracted invoice against the reference invoice.
        Returns similarity scores and calculated variances.
        """
        """Compute similarity and amount variance between extracted and reference invoices."""
        logger.info(f"Initiating invoice comparison for processing run: {processing_id}")
        
        ext_total = float(extracted.get("amount", 0.0))
        ref_total = float(reference.get("amount", 0.0))
        
        # 1. Calculate amount variance
        amount_variance = abs(ext_total - ref_total)
        amount_variance_pct = 0.0
        if ref_total > 0:
            amount_variance_pct = (amount_variance / ref_total) * 100

        # 2. String comparison score (Vendor Similarity)
        vendor_similarity = fuzz.token_sort_ratio(
            extracted.get("vendor", ""), reference.get("vendor", "")
        )

        # 3. Product list comparison
        ext_products = extracted.get("products", [])
        ref_products = reference.get("products", [])
        product_matches = []
        
        matched_count = 0
        for ext_p in ext_products:
            best_match_score = 0.0
            matched_ref_item = None
            
            for ref_p in ref_products:
                score = fuzz.token_sort_ratio(ext_p.get("name", ""), ref_p.get("name", ""))
                if score > best_match_score:
                    best_match_score = score
                    matched_ref_item = ref_p
            
            # Line matched above token threshold
            is_item_matched = best_match_score >= 80.0
            if is_item_matched:
                matched_count += 1
                
            product_matches.append({
                "extracted_item": ext_p.get("name"),
                "reference_item": matched_ref_item.get("name") if matched_ref_item else None,
                "similarity": best_match_score,
                "matched": is_item_matched
            })

        # Calculate overall match score
        total_items = max(len(ext_products), len(ref_products), 1)
        items_match_ratio = (matched_count / total_items) * 100
        overall_similarity = (vendor_similarity * 0.4) + (items_match_ratio * 0.6)

        result = {
            "amount_difference_pct": amount_variance_pct,
            "vendor_similarity": vendor_similarity,
            "overall_similarity": overall_similarity,
            "items_match_ratio": items_match_ratio,
            "details": product_matches
        }

        # Log comparison results to SQLite
        self._write_matching_log(processing_id, result)
        return result

    def _write_matching_log(self, processing_id: str, results: dict):
        """Persist matching results and advance the workflow state to MATCHED."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        is_matched = 1 if results["overall_similarity"] >= 85.0 else 0
        mismatch_details = f"Amount diff: {results['amount_difference_pct']:.2f}% | Items ratio: {results['items_match_ratio']:.2f}%"
        
        cursor.execute("""
            INSERT INTO matching_logs (processing_id, similarity_score, amount_difference_pct, is_matched, mismatch_details)
            VALUES (?, ?, ?, ?, ?)
        """, (processing_id, results["overall_similarity"], results["amount_difference_pct"], is_matched, mismatch_details))
        
        cursor.execute("""
            UPDATE processed_invoices
            SET state = 'MATCHED', updated_at = CURRENT_TIMESTAMP
            WHERE processing_id = ?
        """, (processing_id,))
        
        conn.commit()
        conn.close()
