"""Dutch bank statement parser agent."""

import json
import logging
from datetime import date

from langchain_core.messages import HumanMessage
from langsmith import traceable

from dutch_tax_agent.llm_factory import create_llm

logger = logging.getLogger(__name__)


@traceable(name="Dutch Parser Agent")
def dutch_parser_agent(input_data: dict) -> dict:
    """Parse Dutch bank statements for Box 3 assets.
    
    Extracts:
    - Savings account balances on Jan 1
    - Investment account balances on Jan 1
    - Realized gains/dividends (for actual return method)
    
    Args:
        input_data: Dict with keys:
            - doc_id: Document ID
            - doc_text: Scrubbed document text
            - filename: Original filename
            - classification: Document classification info
            
    Returns:
        Dict with extracted Box 3 asset data
    """
    doc_id = input_data["doc_id"]
    doc_text = input_data["doc_text"]
    filename = input_data["filename"]

    logger.info(f"Dutch parser processing {filename}")

    llm = create_llm(temperature=0)

    prompt = f"""You are a specialized Dutch tax document parser. Extract Box 3 wealth data from this bank statement.

CRITICAL: Dutch banks often have multiple account types:
1. SAVINGS accounts (spaarrekening) - cash deposits, savings
2. INVESTMENT accounts (beleggingsrekening) - stocks, bonds, ETFs, mutual funds
3. CRYPTO accounts (if applicable)

These MUST be extracted as SEPARATE items because Dutch Box 3 tax uses different fictional yield rates for savings vs investments.

IMPORTANT INSTRUCTIONS:
1. Determine the date range covered by this document (e.g., "1-Jan-2024 to 31-Jan-2024" or "31-Dec-2024")
2. Look for account balances on or near January 1st (the reference date for Box 3)
3. Look for account balances on or near December 31st (end of tax year, needed for actual return calculation)
4. If the document only covers one of these dates, extract that value. If it covers both, extract both.
5. ⚠️ CRITICAL: If this is a January statement that shows BOTH 31-Dec of the previous year AND 31-Jan of the tax year, you MUST use the 31-Dec (previous year) value for value_eur_jan1, NOT the 31-Jan value. The 31-Dec value is closest to 1-Jan and is what we need for Box 3 calculations.
6. If the document doesn't cover Jan 1 or Dec 31 (or dates very close to them, accounting for weekends/holidays), you should still extract what you can, but note the date range.
6. Identify the account type: savings, investment (stocks/bonds), crypto, or other
7. Extract each account type separately (e.g., if there's both a savings and investment account, create two items)
8. Look for realized gains, dividends, or interest income during the year
9. Extract account number or IBAN if available - this is critical for matching accounts across different statements
10. All amounts should be in EUR
11. Return ONLY valid JSON, no additional text

Document:
{doc_text}

Return JSON in this EXACT format:
{{
  "document_date_range": {{
    "start_date": "YYYY-MM-DD" or null,
    "end_date": "YYYY-MM-DD" or null
  }},
  "box3_items": [
    {{
      "asset_type": "savings" or "stocks" or "bonds" or "crypto" or "other",
      "value_eur_jan1": <number or null if not available>,
      "value_eur_dec31": <number or null if not available>,
      "realized_gains_eur": <number or null>,
      "reference_date": "YYYY-MM-DD" (the date of the value_eur_jan1, or closest to Jan 1),
      "dec31_reference_date": "YYYY-MM-DD" or null (the date of the value_eur_dec31, or closest to Dec 31),
      "description": "Account name or description (e.g., 'ING Spaarrekening' or 'ABN AMRO Beleggingsrekening')",
      "account_number": "Account number or IBAN if available (e.g., 'NL91ABNA0417164300', '123456789') or null",
      "original_currency": "EUR",
      "extraction_confidence": <0.0 to 1.0>
    }}
  ]
}}

IMPORTANT:
- If document shows data for 1-Jan-20XX, set value_eur_jan1 and reference_date="20XX-01-01"
- If document shows data for 31-Dec-20XX, set value_eur_dec31 and dec31_reference_date="20XX-12-31"
- ⚠️ CRITICAL FOR JANUARY STATEMENTS: If a January statement shows BOTH 31-Dec of the previous year (e.g., 31-Dec-2023) AND 31-Jan of the tax year (e.g., 31-Jan-2024), you MUST use the 31-Dec (previous year) value for value_eur_jan1, NOT the 31-Jan value. The 31-Dec value is closest to 1-Jan and is what we need for Box 3 calculations.
- If document shows data for dates close to Jan 1 or Dec 31 (within 3 days, accounting for weekends/holidays), use those dates
- If document only has one of these dates, that's fine - set the other to null
- If document has neither Jan 1 nor Dec 31 (or close dates), still extract what you can but note the date range

Example: If a statement shows €20,000 in savings on 1-Jan-2024 and €30,000 in investments on 1-Jan-2024, return TWO items:
- One with asset_type="savings", value_eur_jan1=20000, value_eur_dec31=null
- One with asset_type="stocks", value_eur_jan1=30000, value_eur_dec31=null

Example: If a statement shows €25,000 in savings on 31-Dec-2024, return:
- One with asset_type="savings", value_eur_jan1=null, value_eur_dec31=25000

If no Box 3 data is found, return: {{"box3_items": [], "document_date_range": {{"start_date": null, "end_date": null}}}}
"""

    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        response_text = response.content.strip()

        # Remove markdown code blocks if present
        if response_text.startswith("```json"):
            response_text = response_text.split("```json")[1].split("```")[0].strip()
        elif response_text.startswith("```"):
            response_text = response_text.split("```")[1].split("```")[0].strip()

        # Parse JSON
        extracted_data = json.loads(response_text)

        # Ensure document_date_range exists
        if "document_date_range" not in extracted_data:
            extracted_data["document_date_range"] = {"start_date": None, "end_date": None}
        
        # Add reference date and other missing fields if not present
        for item in extracted_data.get("box3_items", []):
            if "reference_date" not in item:
                # Try to infer from document_date_range or default to Jan 1
                doc_start = extracted_data.get("document_date_range", {}).get("start_date")
                if doc_start:
                    item["reference_date"] = doc_start
                else:
                    item["reference_date"] = date(2024, 1, 1).isoformat()
            if "dec31_reference_date" not in item:
                item["dec31_reference_date"] = None
            if "value_eur_jan1" not in item:
                item["value_eur_jan1"] = None
            if "value_eur_dec31" not in item:
                item["value_eur_dec31"] = None
            if "original_currency" not in item:
                item["original_currency"] = "EUR"
            if "extraction_confidence" not in item:
                # Default to 0.8 to match classification confidence default
                item["extraction_confidence"] = 0.8
            if "account_number" not in item:
                item["account_number"] = None

        logger.info(
            f"Dutch parser extracted {len(extracted_data.get('box3_items', []))} items from {filename}"
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
        logger.error(f"Failed to parse JSON from Dutch parser for {filename}: {e}")
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
        logger.error(f"Dutch parser failed for {filename}: {e}")
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


