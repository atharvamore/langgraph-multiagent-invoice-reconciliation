# utils/logger.py
import logging
import os
import sys

LOG_DIR = "logs"
LOG_FILE = os.path.join(LOG_DIR, "reconciliation.log")

def setup_logger(name: str) -> logging.Logger:
    """Create a configured logger that writes to both stdout and the audit log file."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        
        # Ensure log directory exists
        os.makedirs(LOG_DIR, exist_ok=True)
        
        # Create formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # 1. Console Handler (for terminal visibility)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        # 2. File Handler (for permanent audit trails)
        file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        
    return logger
