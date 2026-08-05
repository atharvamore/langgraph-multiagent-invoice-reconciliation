# guardrails/schemas.py
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional
import re

class ExtractedProductItem(BaseModel):
    """Schema for one extracted invoice line item."""
    name: str = Field(description="Name or descriptive title of the product or service")
    quantity: int = Field(description="Total quantity units purchased")
    unit_price: float = Field(description="Unit cost of the individual item")
    total_price: float = Field(description="The calculated final cost for this product line")

class ExtractedInvoice(BaseModel):
    """Schema for the structured invoice object produced by the extraction step."""
    invoice_no: str = Field(description="Unique code identifying the invoice")
    vendor: str = Field(description="Official business name of the vendor")
    invoice_date: str = Field(description="Date specified on the document (YYYY-MM-DD format if readable)")
    currency: str = Field(default="USD", description="Currency symbol or abbreviation")
    amount: float = Field(description="The final total amount due (including taxes/GST)")
    gst: Optional[float] = Field(default=0.0, description="Goods and Services Tax / sales tax charged")
    products: List[ExtractedProductItem] = Field(description="Detailed itemized lines of products/services")

    @field_validator("invoice_date")
    @classmethod
    def clean_date_format(cls, value: str) -> str:
        """Normalize the invoice date field into a clean string format."""
        # Basic regex to match common YYYY-MM-DD
        if re.match(r"^\d{4}-\d{2}-\d{2}$", value):
            return value
        # Simple extraction helper for validation errors
        return value.strip()
