# agents/file_detection_agent.py
import os
import pypdf
from config import settings
from utils.logger import setup_logger

logger = setup_logger("FileDetectionAgent")

class FileDetectionAgent:
    SUPPORTED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".txt"}

    def analyze_file(self, file_path: str) -> dict:
        """Inspect a file extension and decide whether the document is supported and OCR is needed."""
        _, ext = os.path.splitext(file_path.lower())
        result = {
            "is_supported": False,
            "ext": ext,
            "requires_ocr": True,
            "error": None
        }

        if ext not in self.SUPPORTED_EXTENSIONS:
            result["error"] = f"Unsupported file type: {ext}"
            return result

        result["is_supported"] = True

        # Plain text files do NOT require OCR
        if ext == ".txt":
            result["requires_ocr"] = False
            return result

        if ext == ".pdf":
            try:
                has_selectable_text = self._has_selectable_text(file_path)
                result["requires_ocr"] = not has_selectable_text
                logger.info(f"PDF Analysis complete. Requires OCR: {result['requires_ocr']}")
            except Exception as e:
                result["is_supported"] = False
                result["error"] = f"Corrupted or unreadable PDF: {str(e)}"
        else:
            # Images require OCR
            result["requires_ocr"] = True

        return result

    def _has_selectable_text(self, pdf_path: str) -> bool:
        """Check whether the first pages of a PDF contain readable embedded text."""
        try:
            with open(pdf_path, 'rb') as f:
                reader = pypdf.PdfReader(f)
                for page in reader.pages[:2]:
                    text = page.extract_text() or ""
                    if len(text.strip()) > 50:
                        return True
        except Exception:
            pass
        return False
