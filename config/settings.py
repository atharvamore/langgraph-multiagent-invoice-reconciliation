# config/settings.py
import os
from dotenv import load_dotenv

# Force load environment variables from .env file overriding stale OS environment variables
load_dotenv(override=True)

DB_PATH = "database/company.db"
INCOMING_DIR = "incoming_invoices"
PROCESSING_DIR = "processing"
PROCESSED_DIR = "processed"
REJECTED_DIR = "rejected"
HUMAN_REVIEW_DIR = "human_review"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")  
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "openai/gpt-oss-120b")
MODEL_PROVIDER = os.getenv("MODEL_PROVIDER", "groq")
