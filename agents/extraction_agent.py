# agents/extraction_agent.py
import sqlite3
from ocr.ocr_engine import OCRExtractorService
from config import settings
from utils.logger import setup_logger

logger = setup_logger("ExtractionAgent")

class ExtractionAgent:
    def __init__(self):
        """Create the raw-text extraction agent with its OCR backend."""
        self.ocr_service = OCRExtractorService()

    def extract_raw_text(self, file_path: str, needs_ocr: bool, processing_id: str) -> str:
        """Extract raw text from the document or fallback gracefully to visual VLM extraction."""
        logger.info(f"Starting raw text extraction for {processing_id}")
        
        raw_text = ""
        if needs_ocr:
            try:
                raw_text = self.ocr_service.extract_via_ocr(file_path)
            except Exception as e:
                logger.warning(f"OCR engine extraction failed ({e}). Routing image directly to Groq Vision model...")
                raw_text = f"[IMAGE_FILE: {file_path}]"
        else:
            raw_text = self.ocr_service.extract_from_digital_pdf(file_path)

        # Update extraction status in DB
        conn = sqlite3.connect(settings.DB_PATH)
        cursor = conn.cursor()
        try:
            cursor.execute("""
                UPDATE processed_invoices
                SET state = 'EXTRACTED', updated_at = CURRENT_TIMESTAMP
                WHERE processing_id = ?
            """, (processing_id,))
            conn.commit()
        except sqlite3.Error as e:
            logger.error(f"DB update failed during extraction phase for {processing_id}: {e}")
        finally:
            conn.close()

        return raw_text
