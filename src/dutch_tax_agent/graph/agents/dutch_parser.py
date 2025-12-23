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

    prompt = f"""You are a specialized Dutch tax document parser. Extract Box 3 wealth data from this FULL YEAR bank statement.

CRITICAL: Dutch banks often have multiple account types that MUST be extracted as SEPARATE items:
1. SAVINGS accounts (spaarrekening) - cash deposits, savings
2. CURRENT/CHECKING accounts (betaalrekening) - transaction accounts, checking accounts
3. INVESTMENT accounts (beleggingsrekening) - stocks, bonds, ETFs, mutual funds
4. CRYPTO accounts (if applicable)
5. MORTGAGE balances (hypotheek) - mortgage debt on second homes (primary residence is Box 1, not Box 3)
6. CREDIT CARD balances (creditcard) - outstanding credit card debt

These MUST be extracted as SEPARATE items because Dutch Box 3 tax uses different fictional yield rates for savings vs investments vs debts.

IMPORTANT INSTRUCTIONS:
1. This is a FULL YEAR statement - it should show balances for both the beginning and end of the tax year
2. Look for account balances on or near January 1st (the reference date for Box 3) - this goes to value_eur_jan1
3. Look for account balances on or near December 31st (end of tax year) - this goes to value_eur_dec31
4. If the statement shows BOTH dates in separate columns (e.g., "Balance 31-12-2023" and "Balance 31-12-2024"):
   - value_eur_jan1 = value from the PREVIOUS year's Dec 31 column (e.g., 31-12-2023)
   - value_eur_dec31 = value from the CURRENT year's Dec 31 column (e.g., 31-12-2024)
5. If the statement only shows one date, extract that value and set the other to null
6. Identify the account type:
   - "savings" for savings accounts (spaarrekening) - dedicated savings accounts
   - "checking" for current/checking accounts (betaalrekening) - transaction/checking accounts (also called personal accounts)
   - "stocks" for investment accounts (beleggingsrekening) with stocks, ETFs, mutual funds
   - "bonds" for bond holdings
   - "crypto" for cryptocurrency accounts
   - "mortgage" for mortgage balances (hypotheek) on second homes - MUST use "mortgage" not "debt"
   - "debt" for credit card balances (creditcard) and other non-mortgage debts
   - "other" for any other asset types
7. Extract each account type separately (e.g., if there's a savings account, a current account, a mortgage, and a credit card, create FOUR separate items)
8. Look for realized gains, dividends, or interest income during the year
9. Extract account number or IBAN if available - this is critical for matching accounts across different statements
10. All amounts should be in EUR
11. Return ONLY valid JSON, no additional text

⚠️ CRITICAL: European number format parsing ⚠️:
- Dots (.) are THOUSANDS separators, NOT decimal points
- Commas (,) are DECIMAL separators
- Example: "10.000,00" = 10000.00 (ten thousand euros)
- Example: "8.500,50" = 8500.50 (eight thousand five hundred euros and 50 cents)
- Example: "0,02" = 0.02 (two cents)
- DO NOT confuse the format - always parse dots as thousands and commas as decimals

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
      "asset_type": "savings" or "checking" or "stocks" or "bonds" or "crypto" or "mortgage" or "debt" or "other",
      "value_eur_jan1": <number or null if not available>,
      "value_eur_dec31": <number or null if not available>,
      "realized_gains_eur": <number or null>,
      "reference_date": "YYYY-MM-DD" (the date of the value_eur_jan1, or closest to Jan 1),
      "dec31_reference_date": "YYYY-MM-DD" or null (the date of the value_eur_dec31, or closest to Dec 31),
      "description": "Account name or description (e.g., 'ING Spaarrekening', 'ABN AMRO Betaalrekening', 'ING Hypotheek', 'Creditcard ING')",
      "account_number": "Account number or IBAN if available (e.g., 'NL91ABNA0417164300', '123456789') or null",
      "original_currency": "EUR",
      "extraction_confidence": <0.0 to 1.0>
    }}
  ]
}}

DATE MAPPING RULES:
- If the statement shows BOTH 31-12-2023 AND 31-12-2024 in separate columns:
  * value_eur_jan1 = value from the 31-12-2023 column (previous year's Dec 31, used as proxy for Jan 1)
  * value_eur_dec31 = value from the 31-12-2024 column (current year's Dec 31)
  * reference_date = "2024-01-01" (the tax year's Jan 1)
  * dec31_reference_date = "2024-12-31" (the actual Dec 31 date shown)
  * Example: Table with columns "Balance 31-12-2023 | Balance 31-12-2024" showing "10.000,00 | 8.500,50":
    → CORRECT: value_eur_jan1=10000.00, value_eur_dec31=8500.50, reference_date="2024-01-01", dec31_reference_date="2024-12-31"
    → WRONG: value_eur_jan1=8500.50, value_eur_dec31=10000.00 (values are swapped - using wrong column!)
- If the statement shows data for 1-Jan-20XX, set value_eur_jan1 and reference_date="20XX-01-01"
- If the statement shows data for 31-Dec-20XX, set value_eur_dec31 and dec31_reference_date="20XX-12-31"
- If the statement shows dates close to Jan 1 or Dec 31 (within 3 days, accounting for weekends/holidays), use those dates
- If the statement only has one of these dates, that's fine - set the other to null

EXAMPLES:
Example 1: Full year statement showing both dates in a table:
  "Balance 31-12-2023 | Balance 31-12-2024"
  "10.000,00          | 8.500,50"
  "500,25             | 450,75"
  → Extract TWO items (one for each account):
    * First account: value_eur_jan1=10000.00, value_eur_dec31=8500.50, reference_date="2024-01-01", dec31_reference_date="2024-12-31"
    * Second account: value_eur_jan1=500.25, value_eur_dec31=450.75, reference_date="2024-01-01", dec31_reference_date="2024-12-31"

Example 2: Statement showing €20,000 in savings, €5,000 in current account, €30,000 in investments, and €150,000 mortgage on both Jan 1 and Dec 31:
  → Extract FOUR items:
    * asset_type="savings", value_eur_jan1=20000, value_eur_dec31=20000, description="ING Spaarrekening"
    * asset_type="checking", value_eur_jan1=5000, value_eur_dec31=5000, description="ING Betaalrekening"
    * asset_type="stocks", value_eur_jan1=30000, value_eur_dec31=30000, description="ABN AMRO Beleggingsrekening"
    * asset_type="mortgage", value_eur_jan1=150000, value_eur_dec31=150000, description="ING Hypotheek"

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


