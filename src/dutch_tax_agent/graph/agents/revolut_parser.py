"""Revolut statement parser agent."""

import json
import logging
from datetime import date
from pathlib import Path

from langchain_core.messages import HumanMessage
from langsmith import traceable

from dutch_tax_agent.llm_factory import create_llm

logger = logging.getLogger(__name__)


@traceable(name="Revolut Parser Agent")
def revolut_parser_agent(input_data: dict) -> dict:
    """Parse Revolut transaction statements for Box 3 assets.
    
    Extracts:
    - Period (tax year or date range)
    - Opening balance (balance at start of period)
    - Closing balance (balance at end of period)
    - Currency
    
    Note: Only the first 1000 characters of the document are provided to save LLM credits.
    This should be sufficient as Revolut statements typically have the key information
    (period, opening balance, closing balance) in the header section.
    
    Args:
        input_data: Dict with doc_id, doc_text (truncated to 1000 chars), filename, classification
        
    Returns:
        Dict with extracted Box 3 asset data (will be converted to EUR later)
    """
    doc_id = input_data["doc_id"]
    doc_text = input_data["doc_text"]
    filename = input_data["filename"]
    classification = input_data.get("classification", {})
    tax_year = classification.get("tax_year")

    logger.info(f"Revolut parser processing {filename} (tax_year: {tax_year})")

    llm = create_llm(temperature=0)

    prompt = f"""You are a specialized Revolut statement parser for Dutch tax purposes.

Extract Box 3 wealth data from a Revolut transaction statement.

IMPORTANT: This document has been truncated to the first 1000 characters to save costs. 
The key information (period, opening balance, closing balance, currency) should be in this section.

CRITICAL EXTRACTION REQUIREMENTS:
1. Extract the STATEMENT PERIOD (start date and end date) - this is typically a tax year or date range
2. Extract the OPENING BALANCE (balance at the start of the period)
3. Extract the CLOSING BALANCE (balance at the end of the period)
4. Extract the CURRENCY (EUR, USD, GBP, etc.)

MAPPING TO TAX YEAR REFERENCE DATES:
- If the statement period starts on January 1st of the tax year (or close to it), map opening balance to value_eur_jan1
- If the statement period ends on December 31st of the tax year (or close to it), map closing balance to value_eur_dec31
- If the statement period doesn't align with tax year boundaries:
  * If statement covers full tax year (Jan 1 to Dec 31), use opening balance for value_eur_jan1 and closing balance for value_eur_dec31
  * If statement only covers part of the year, prioritize the date that matches the tax year reference date
  * If statement period is unclear, use opening balance for value_eur_jan1 and closing balance for value_eur_dec31 as defaults

Revolut accounts are typically savings/cash accounts, so use asset_type="savings".

Document (first 1000 chars):
{doc_text}

Return JSON in this EXACT format:
{{
  "document_date_range": {{
    "start_date": "YYYY-MM-DD" or null,
    "end_date": "YYYY-MM-DD" or null
  }},
  "box3_items": [
    {{
      "asset_type": "savings",
      "value_eur_jan1": <opening balance in original currency if period starts at tax year start, or null>,
      "value_eur_dec31": <closing balance in original currency if period ends at tax year end, or null>,
      "original_value": <opening balance if value_eur_jan1 is set, otherwise closing balance if value_eur_dec31 is set, or null>,
      "original_currency": "EUR" or "USD" or "GBP" or other currency code,
      "realized_gains_eur": null,
      "realized_losses_eur": null,
      "reference_date": "YYYY-MM-DD" (start date of statement period, or tax year Jan 1 if period unclear),
      "dec31_reference_date": "YYYY-MM-DD" or null (end date of statement period, or tax year Dec 31 if period unclear),
      "description": "Revolut Account Statement",
      "account_number": null,
      "extraction_confidence": <0.0 to 1.0>
    }}
  ]
}}

Examples:
- Statement period: 2024-01-01 to 2024-12-31, Opening: €5,000, Closing: €6,000, Currency: EUR
  → value_eur_jan1=5000, value_eur_dec31=6000, reference_date="2024-01-01", dec31_reference_date="2024-12-31"

- Statement period: 2024-06-01 to 2024-12-31, Opening: €3,000, Closing: €4,500, Currency: EUR
  → value_eur_jan1=null (period doesn't start at tax year start), value_eur_dec31=4500, reference_date="2024-06-01", dec31_reference_date="2024-12-31"

- Statement period: 2024-01-01 to 2024-06-30, Opening: €2,000, Closing: €2,500, Currency: USD
  → value_eur_jan1=2000, value_eur_dec31=null (period doesn't end at tax year end), reference_date="2024-01-01", dec31_reference_date="2024-06-30"

- Statement period unclear, Opening: €1,000, Closing: €1,200, Currency: EUR
  → value_eur_jan1=1000, value_eur_dec31=1200, reference_date="2024-01-01" (default to tax year start), dec31_reference_date="2024-12-31" (default to tax year end)

If no balance data found, return: {{"box3_items": [], "document_date_range": {{"start_date": null, "end_date": null}}}}
"""

    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        response_text = response.content.strip()

        # Clean markdown
        if "```json" in response_text:
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif "```" in response_text:
            response_text = response_text.split("```")[1].split("```")[0].strip()

        extracted_data = json.loads(response_text)

        # Ensure document_date_range exists
        if "document_date_range" not in extracted_data:
            extracted_data["document_date_range"] = {"start_date": None, "end_date": None}

        # Validate and set defaults for box3_items
        box3_items = extracted_data.get("box3_items", [])
        for item in box3_items:
            if "asset_type" not in item:
                item["asset_type"] = "savings"
            if "original_currency" not in item:
                item["original_currency"] = "EUR"  # Default to EUR for Revolut
            if "reference_date" not in item:
                # Try to infer from document_date_range or default to tax year Jan 1
                doc_start = extracted_data.get("document_date_range", {}).get("start_date")
                if doc_start:
                    item["reference_date"] = doc_start
                elif tax_year:
                    item["reference_date"] = date(tax_year, 1, 1).isoformat()
                else:
                    item["reference_date"] = date(2024, 1, 1).isoformat()
            if "dec31_reference_date" not in item:
                # Try to infer from document_date_range or default to tax year Dec 31
                doc_end = extracted_data.get("document_date_range", {}).get("end_date")
                if doc_end:
                    item["dec31_reference_date"] = doc_end
                elif tax_year:
                    item["dec31_reference_date"] = date(tax_year, 12, 31).isoformat()
                else:
                    item["dec31_reference_date"] = None
            if "value_eur_jan1" not in item:
                item["value_eur_jan1"] = None
            if "value_eur_dec31" not in item:
                item["value_eur_dec31"] = None
            # Set original_value if not set (use jan1 if available, otherwise dec31)
            if "original_value" not in item:
                if item.get("value_eur_jan1") is not None:
                    item["original_value"] = item["value_eur_jan1"]
                elif item.get("value_eur_dec31") is not None:
                    item["original_value"] = item["value_eur_dec31"]
                else:
                    item["original_value"] = None
            if "realized_gains_eur" not in item:
                item["realized_gains_eur"] = None
            if "realized_losses_eur" not in item:
                item["realized_losses_eur"] = None
            if "description" not in item:
                item["description"] = "Revolut Account Statement"
            if "account_number" not in item or item["account_number"] is None or item["account_number"] == "":
                # Extract account_number from filename (without extension, lowercase for case-insensitive matching)
                # This allows matching with CSV files: rev_savings_eur.pdf matches rev_savings_eur.csv
                filename_stem = Path(filename).stem.lower()
                item["account_number"] = filename_stem
                logger.info(f"Set account_number from filename: {filename_stem}")
            if "extraction_confidence" not in item:
                # Default to 0.8 to match classification confidence default
                item["extraction_confidence"] = 0.8

        logger.info(
            f"Revolut parser extracted {len(box3_items)} items, "
            f"date range: {extracted_data.get('document_date_range', {}).get('start_date')} to "
            f"{extracted_data.get('document_date_range', {}).get('end_date')}"
        )

        # Return state update that will be merged into TaxGraphState.extraction_results
        return {
            "extraction_results": [
                {
                    "doc_id": doc_id,
                    "source_filename": filename,
                    "status": "success",
                    "extracted_data": extracted_data,
                    "errors": [],
                    "warnings": [],
                }
            ]
        }

    except json.JSONDecodeError as e:
        logger.error(f"JSON parsing error in Revolut parser: {e}")
        return {
            "extraction_results": [
                {
                    "doc_id": doc_id,
                    "source_filename": filename,
                    "status": "error",
                    "extracted_data": {},
                    "errors": [f"JSON parsing error: {e}"],
                    "warnings": [],
                }
            ]
        }
    except Exception as e:
        logger.error(f"Revolut parser failed: {e}")
        return {
            "extraction_results": [
                {
                    "doc_id": doc_id,
                    "source_filename": filename,
                    "status": "error",
                    "extracted_data": {},
                    "errors": [str(e)],
                    "warnings": [],
                }
            ]
        }

