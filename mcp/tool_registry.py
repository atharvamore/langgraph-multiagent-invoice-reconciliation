# mcp/tool_registry.py
import sqlite3
import pandas as pd
from langchain_core.tools import tool
from config import settings

@tool
def get_system_summary() -> dict:
    """Retrieves aggregation counts of decisions (APPROVED, REJECTED, HUMAN_REVIEW) from invoice database logs."""
    conn = sqlite3.connect(settings.DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT decision, COUNT(*) FROM processed_invoices GROUP BY decision
    """)
    rows = cursor.fetchall()
    conn.close()
    return {row[0]: row[1] for row in rows}

@tool
def fetch_pending_reviews() -> list:
    """Lists all invoices currently waiting in the manual human review queue."""
    conn = sqlite3.connect(settings.DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT processing_id, file_name, comments FROM processed_invoices 
        WHERE decision = 'HUMAN_REVIEW' AND state = 'HUMAN_REVIEW'
    """)
    results = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return results

@tool
def query_rejections_by_reason() -> list:
    """Aggregates rejection reasons and comments to identify processing trends for rejected invoices."""
    conn = sqlite3.connect(settings.DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT processing_id, comments FROM processed_invoices 
        WHERE decision = 'REJECTED'
    """)
    results = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return results


class MCPInvoiceTools:
    """
    Standardized tool interfaces exposing data actions to the LLM agent.
    Provides backward-compatible method access alongside LangChain @tool definitions.
    """
    def __init__(self):
        self.db_path = settings.DB_PATH

    def get_system_summary(self) -> dict:

        return get_system_summary.invoke({})

    def fetch_pending_reviews(self) -> list:
        return fetch_pending_reviews.invoke({})

    def query_rejections_by_reason(self) -> list:
        return query_rejections_by_reason.invoke({})

    @staticmethod
    def get_registered_tools() -> list:
        """Returns list of LangChain @tool objects for LLM tool binding."""
        return [get_system_summary, fetch_pending_reviews, query_rejections_by_reason]
