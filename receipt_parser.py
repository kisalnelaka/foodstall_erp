"""
AI-powered receipt & bill parsing engine using Google Gemini Vision (gemini-2.5-flash).
Extracts structured supplier deliveries, line items, costs, and expense categories from bill photos.
"""

import base64
import json
import logging
import os
import re
from typing import Any, Dict, Optional
import aiohttp

logger = logging.getLogger("sumiyuru-erp.receipt_parser")

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"


def get_api_key() -> str:
    """Retrieves the Gemini API key from environment or .env file."""
    key = os.environ.get("GEMINI_API_KEY", "")
    if key:
        return key

    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("GEMINI_API_KEY="):
                    return line.strip().split("=", 1)[1].strip()
    return ""


SYSTEM_PROMPT = """You are an expert accounting assistant for 'Sumiyuru Catering & Roadside Stall' in Sri Lanka.
Your task is to analyze photos of bills, receipts, invoices, or handwritten chits, and extract precise structured accounting data.

Context of the business:
- Known Suppliers: 'Delish' (Bakery Buns, Bread, Roast Paan, Theti Paan), 'Nishan' (Nishan Buns, Dosa, Parata, Toast Bread), 'Hoppers' (String Hoppers), 'PW Farm' (Chicken, Sausages), 'Nirosha' (Chicken, Super Prawns), 'In-House Kitchen', 'Godrej' (Coffee Dispenser).
- Common expenses: Chicken/meat restock, cooking gas, grocery bags/packaging, petrol/diesel fuel, fly zapper, spices, vegetables/onions, helper wages.
- Currency: Sri Lankan Rupee (LKR / Rs.).

Extract the data strictly into the following JSON structure:
{
  "bill_type": "supplier_delivery" | "expense_purchase" | "general_receipt",
  "vendor_name": "Name of vendor or merchant",
  "bill_date": "YYYY-MM-DD" or null if unreadable,
  "invoice_number": "Invoice or bill number" or null,
  "total_amount": 0.0,
  "line_items": [
    {
      "item_name": "Description of item",
      "quantity": 1.0,
      "unit_price": 0.0,
      "total_price": 0.0
    }
  ],
  "suggested_category": "Morning Delivery Cash" | "Chicken & Meat" | "Packaging & Supplies" | "Fuel & Transport" | "Utilities & Gas" | "Store Maintenance" | "Groceries & Spices" | "Other Expenses",
  "suggested_payment_source": "Morning Cash Envelope" | "Master Reserve" | "Direct Till",
  "confidence_score": 0.95,
  "verification_status": "VERIFIED" | "NEEDS_REVIEW",
  "summary_note": "Concise 1-sentence explanation of the bill"
}

Ensure all numerical prices are extracted as numbers (not strings). If an item total does not equal quantity * unit_price, explain in summary_note. Return ONLY valid JSON, enclosed in ```json ```.
"""


async def parse_receipt_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> Dict[str, Any]:
    """
    Sends receipt image bytes to Gemini 2.5 Flash and returns structured JSON analysis.
    """
    api_key = get_api_key()
    if not api_key:
        raise ValueError("GEMINI_API_KEY not configured. Set GEMINI_API_KEY in .env")

    base64_data = base64.b64encode(image_bytes).decode("utf-8")

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": SYSTEM_PROMPT},
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": base64_data
                        }
                    },
                    {"text": "Analyze this receipt image and return the structured JSON accounting extraction."}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 2048,
            "responseMimeType": "application/json"
        }
    }

    url = f"{GEMINI_API_URL}?key={api_key}"

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status != 200:
                err_text = await resp.text()
                logger.error(f"Gemini API returned status {resp.status}: {err_text}")
                raise RuntimeError(f"Gemini Vision API error (HTTP {resp.status}): {err_text[:300]}")

            result = await resp.json()
            try:
                candidates = result.get("candidates", [])
                if not candidates:
                    raise ValueError("No output candidates returned from Gemini.")

                content_parts = candidates[0].get("content", {}).get("parts", [])
                raw_text = content_parts[0].get("text", "").strip()

                # Parse JSON
                if "```json" in raw_text:
                    raw_text = re.search(r"```json\s*(.*?)\s*```", raw_text, re.DOTALL).group(1)
                elif "```" in raw_text:
                    raw_text = re.search(r"```\s*(.*?)\s*```", raw_text, re.DOTALL).group(1)

                parsed = json.loads(raw_text)
                return parsed
            except Exception as parse_err:
                logger.error(f"Failed to decode Gemini JSON response: {parse_err}")
                return {
                    "bill_type": "general_receipt",
                    "vendor_name": "Unspecified Vendor",
                    "bill_date": None,
                    "total_amount": 0.0,
                    "line_items": [],
                    "confidence_score": 0.5,
                    "verification_status": "NEEDS_REVIEW",
                    "summary_note": f"Raw parse error: {str(parse_err)}"
                }
