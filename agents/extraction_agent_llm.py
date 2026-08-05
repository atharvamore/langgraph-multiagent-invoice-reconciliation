# agents/extraction_agent_llm.py
import json
import re
import os
import sqlite3
import base64
from groq import Groq
from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage
from config import settings
from guardrails.schemas import ExtractedInvoice
from utils.logger import setup_logger

logger = setup_logger("StructuredExtractionAgent")

SYSTEM_EXTRACTION_PROMPT = (
    "Extract invoice data and return only valid JSON with keys: "
    "invoice_no, vendor, invoice_date, currency, amount, gst, products. "
    "Each product must include name, quantity, unit_price, total_price. "
    "Treat 'amount' as the final invoice total including GST, not the subtotal. "
    "Ensure the product totals plus GST align with the amount."
)

class StructuredExtractionAgent:
    def __init__(self):
        """Initialize the Groq client and provider-agnostic settings for structured invoice extraction."""
        self.api_key = settings.GROQ_API_KEY
        self.model = settings.GROQ_MODEL
        self.vision_model = settings.GROQ_VISION_MODEL
        self.provider = settings.MODEL_PROVIDER
        self.client = None
        if self.api_key:
            self.client = Groq(api_key=self.api_key)

    def _get_unified_chat_model(self, model_name: str):
        """Helper to create a provider-agnostic chat model instance."""
        try:
            return init_chat_model(
                model=model_name,
                model_provider=self.provider,
                api_key=self.api_key,
                temperature=0
            )
        except Exception as e:
            logger.warning(f"init_chat_model failed for {model_name} with provider {self.provider}: {e}")
            return None

    def parse_to_structured_json(self, raw_text: str, processing_id: str, file_path: str = None) -> dict:
        """Convert raw invoice text or image into structured JSON and persist it for the workflow."""
        logger.info(f"Extracting structured JSON for Processing ID: {processing_id}")
        
        # Determine if input is an image file suitable for Groq Vision
        is_image = False
        if file_path and os.path.exists(file_path):
            ext = os.path.splitext(file_path)[1].lower()
            if ext in ['.png', '.jpg', '.jpeg', '.tiff', '.bmp']:
                is_image = True

        if not self.api_key:
            logger.warning("No active API key. Running offline parser fallback.")
            parsed_data = self._offline_parser_fallback(raw_text)
        else:
            logger.info(f"Routing document text content to Groq Model ({self.model})...")
            parsed_data = self._query_groq_structured_outputs(raw_text)

        # Update DB with extracted JSON structure
        conn = sqlite3.connect(settings.DB_PATH)
        cursor = conn.cursor()
        try:
            cursor.execute("""
                UPDATE processed_invoices
                SET extracted_json = ?, state = 'EXTRACTED', updated_at = CURRENT_TIMESTAMP
                WHERE processing_id = ?
            """, (json.dumps(parsed_data), processing_id))
            conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Error persisting extracted JSON to database: {e}")
        finally:
            conn.close()

        return parsed_data

    def _query_groq_vision(self, image_path: str, fallback_text: str) -> dict:
        """Ask Groq Vision (llama-3.2-11b-vision-preview) to parse an invoice image directly."""
        try:
            with open(image_path, "rb") as img_file:
                base64_image = base64.b64encode(img_file.read()).decode("utf-8")

            ext = os.path.splitext(image_path)[1].lower()
            mime_type = "image/png" if ext == ".png" else "image/jpeg"

            response = self.client.chat.completions.create(
                model=self.vision_model,
                messages=[
                    {"role": "system", "content": SYSTEM_EXTRACTION_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Extract structured invoice JSON from this image:"},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}
                            }
                        ]
                    }
                ],
                response_format={"type": "json_object"},
                temperature=0,
            )

            content = response.choices[0].message.content or "{}"
            parsed_data = json.loads(content)
            ExtractedInvoice(**parsed_data)
            logger.info(f"Successfully extracted document JSON via Groq Vision Model ({self.vision_model}).")
            return parsed_data

        except Exception as e:
            logger.error(f"Groq Vision SDK call failed: {str(e)}. Falling back to text extraction.")
            return self._query_groq_structured_outputs(fallback_text)

    def _sanitize_and_normalize_data(self, parsed_data: dict) -> dict:
        """Clean up keys, currencies, and numeric types from LLM JSON output."""
        if not isinstance(parsed_data, dict):
            return parsed_data
            
        # Map common alias names to schema field names
        if "amount" not in parsed_data or not parsed_data["amount"]:
            for alias in ["total_amount", "total", "grand_total", "total_price", "amount_due", "balance_due"]:
                if alias in parsed_data and parsed_data[alias]:
                    parsed_data["amount"] = parsed_data[alias]
                    break

        if "gst" not in parsed_data or parsed_data["gst"] is None:
            for alias in ["tax", "vat", "sales_tax", "tax_amount"]:
                if alias in parsed_data and parsed_data[alias] is not None:
                    parsed_data["gst"] = parsed_data[alias]
                    break

        # Convert strings with $ / commas to clean floats
        for field in ["amount", "gst"]:
            if field in parsed_data:
                v = parsed_data[field]
                if isinstance(v, str):
                    clean_v = re.sub(r"[^\d.]", "", v)
                    parsed_data[field] = float(clean_v) if clean_v else 0.0
                elif v is None:
                    parsed_data[field] = 0.0

        if "products" in parsed_data and isinstance(parsed_data["products"], list):
            for prod in parsed_data["products"]:
                if isinstance(prod, dict):
                    for k in ["quantity", "unit_price", "total_price"]:
                        if k in prod:
                            v = prod[k]
                            if isinstance(v, str):
                                clean_v = re.sub(r"[^\d.]", "", v)
                                prod[k] = float(clean_v) if clean_v else 0.0
                            elif v is None:
                                prod[k] = 0.0

        return parsed_data

    def _query_groq_structured_outputs(self, text_content: str) -> dict:
        """Ask Groq for schema-shaped JSON and validate the returned structure."""
        try:
            prompt = f"Extract structured data from this invoice content:\n\n{text_content}"

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_EXTRACTION_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0,
            )

            content = response.choices[0].message.content or "{}"
            parsed_data = json.loads(content)
            parsed_data = self._sanitize_and_normalize_data(parsed_data)

            # Validate/normalize the model output shape against the expected schema.
            ExtractedInvoice(**parsed_data)
            logger.info(f"Successfully received structured response from Groq Text Model ({self.model}).")
            return parsed_data

        except Exception as e:
            logger.error(f"Groq SDK call failed: {str(e)}. Falling back to offline parse.")
            return self._offline_parser_fallback(text_content)

    def _offline_parser_fallback(self, text_content: str) -> dict:
        """
        A rule-based parser that handles data dynamically using known vendors
        from the database when no LLM API key is configured or the API fails.
        """
        """Extract invoice fields with regex and database vendor hints when LLM output is unavailable."""
        lines = text_content.split("\n")
        data = {
            "invoice_no": "UNKNOWN",
            "vendor": "UNKNOWN",
            "invoice_date": "2026-01-01",
            "currency": "USD",
            "amount": 0.0,
            "gst": 0.0,
            "products": []
        }
        
        # --- 2. INSERT REGEX EXTRACTION HERE ---
        # Search the entire raw text for the Date pattern
        date_match = re.search(r'Date:\s*(\d{4}-\d{2}-\d{2})', text_content)
        if date_match:
            data["invoice_date"] = date_match.group(1)

        # Search the entire raw text for the GST pattern
        gst_match = re.search(r'GST:\s*\$?([\d,]+\.\d{2})', text_content)
        if gst_match:
            data["gst"] = float(gst_match.group(1).replace(',', ''))
        # ---------------------------------------
        
        # 1. Dynamically fetch known vendors from the database
        known_vendors = []
        try:
            conn = sqlite3.connect(settings.DB_PATH)
            cursor = conn.cursor()
            # Fetch unique vendors that have already been saved to the invoices table
            cursor.execute("SELECT DISTINCT vendor FROM invoices WHERE vendor IS NOT NULL")
            known_vendors = [row[0] for row in cursor.fetchall()]
            conn.close()
        except sqlite3.Error as e:
            logger.error(f"Failed to fetch vendors for offline parser: {e}")
            # Failsafe list in case the database connection drops
            known_vendors = ["Acme", "Globex", "Initech"]

        # 2. Extract Data using the dynamic vendor list
        for line in lines:
            if "INV-" in line:
                parts = line.split()
                for p in parts:
                    if "INV-" in p:
                        data["invoice_no"] = p.strip().replace(":", "")
            
            # Check the line against our dynamic list of vendors
            for vendor in known_vendors:
                if vendor in line:
                    if ":" in line:
                        data["vendor"] = line.strip().split(":")[-1].strip()
                    else:
                        data["vendor"] = vendor
                    break  # Stop checking other vendors once a match is found in this line

            # if "Total Amount" in line or "Amount" in line or "Total" in line:
            #     try:
            #         nums = [float(s) for s in line.replace("$", "").replace(",", "").split() if s.replace('.', '', 1).isdigit()]
            #         if nums:
            #             data["amount"] = nums[0]
            #     except Exception:
            #         pass

        # --- INSERT THE TABLE EXTRACTION REGEX HERE ---
        in_items_section = False
        extracted_products = []

        for line in lines:
            if "Description" in line and "Qty" in line:
                in_items_section = True
                continue
            
            if "Subtotal" in line or "Total Amount" in line:
                in_items_section = False
            
            if in_items_section and line.strip():
                match = re.search(r'^(.*?)\s+(\d+)\s+\$?([\d,]+\.\d{2})\s+\$?([\d,]+\.\d{2})$', line.strip())
                if match:
                    extracted_products.append({
                        "name": match.group(1).strip(),
                        "quantity": int(match.group(2)),
                        "unit_price": float(match.group(3).replace(',', '')),
                        "total_price": float(match.group(4).replace(',', ''))
                    })

        if extracted_products:
            data["products"] = extracted_products
            subtotal = sum(item["total_price"] for item in extracted_products)
            # Force the amount to strictly equal items + gst
            data["amount"] = round(subtotal + data["gst"], 2)
        elif not data["products"] and data["amount"] > 0:
            data["products"].append({
                "name": "Default Extracted Item",
                "quantity": 1,
                "unit_price": data["amount"],
                "total_price": data["amount"]
            })
        # -----------------------------------------------

        logger.info(f"DEBUG - Offline Parser found {len(data['products'])} items, Amount: {data['amount']} for Vendor: {data['vendor']}")
        
        return data
