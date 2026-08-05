# agents/intake_agent.py
import os
import uuid
import shutil
import sqlite3
from config import settings
from utils.logger import setup_logger

logger = setup_logger("IntakeAgent")

class IntakeAgent:
    def __init__(self):
        """Initialize the intake agent and ensure the working folders exist."""
        self.db_path = settings.DB_PATH
        self._ensure_folders_exist()

    def _ensure_folders_exist(self):
        """Create the intake, processing, output, and review folders if needed."""
        for path in [settings.INCOMING_DIR, settings.PROCESSING_DIR, 
                     settings.PROCESSED_DIR, settings.REJECTED_DIR, settings.HUMAN_REVIEW_DIR]:
            os.makedirs(path, exist_ok=True)

    def register_new_file(self, file_path: str):
        """Register a new file, resolve path if in incoming_invoices, copy it into processing, and create DB record."""
        file_name = os.path.basename(file_path)
        processing_id = f"PRC-{uuid.uuid4().hex[:8].upper()}"
        logger.info(f"Ingesting file: {file_name}. Generated ProcessingID: {processing_id}")

        if not os.path.exists(file_path):
            alt_path = os.path.join(settings.INCOMING_DIR, file_name)
            if os.path.exists(alt_path):
                file_path = alt_path

        # Copy file into the processing area to avoid file lock issues
        dest_path = os.path.join(settings.PROCESSING_DIR, f"{processing_id}_{file_name}")
        shutil.copy2(file_path, dest_path)
        
        # Log to database
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO processed_invoices (id, processing_id, file_name, state, decision)
                VALUES (?, ?, ?, ?, ?)
            """, (processing_id, processing_id, file_name, "INTAKE", "PENDING"))
            conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Failed to write state logs to DB for {processing_id}: {e}")
        finally:
            conn.close()

        return processing_id, dest_path
