"""US broker statement parser agent."""

import json
import logging
from datetime import date

from langchain_core.messages import HumanMessage
from langsmith import traceable

from dutch_tax_agent.llm_factory import create_llm

logger = logging.getLogger(__name__)


@traceable(name="US Broker Parser Agent")
def us_broker_parser_agent(input_data: dict) -> dict:
    """Parse US brokerage statements for Box 3 assets.
    
    Extracts:
    - Investment portfolio value on Jan 1
    - Realized gains/losses during the year
    - Currency (typically USD)
    
    Args:
        input_data: Dict with doc_id, doc_text, filename, classification
        
    Returns:
        Dict with extracted Box 3 asset data (in USD, will be converted later)
    """
    doc_id = input_data["doc_id"]
    doc_text = input_data["doc_text"]
    filename = input_data["filename"]

    logger.info(f"US broker parser processing {filename}")

    llm = create_llm(temperature=0)

    prompt = f"""You are a specialized brokerage statement parser for Dutch tax purposes.

Extract Box 3 wealth data from brokerage statements (US brokers, crypto exchanges, etc.).

CRITICAL: Brokerages ALWAYS have TWO separate account types:
1. CASH/Savings account (cash balance, fiat currency, money market funds, uninvested cash) - use asset_type="savings"
2. INVESTMENT account (stocks, bonds, ETFs, mutual funds, crypto assets, options) - use asset_type="stocks" (or "crypto" for crypto holdings)

These MUST be extracted as SEPARATE items because Dutch Box 3 tax uses different fictional yield rates for savings vs investments.

⚠️ CRITICAL EXTRACTION WARNING ⚠️:
You MUST extract the INDIVIDUAL values of cash and equities/crypto/investments separately. 
DO NOT extract the TOTAL account value (which is typically the sum of cash + investments).
The document may show a "Total Account Value" or "Account Balance" that combines both - IGNORE this total.
Instead, find and extract:
- The individual CASH/Savings balance (separate line item or section)
- The individual INVESTMENT portfolio value (stocks/crypto/etc. - separate line item or section)
These are two distinct values that must be extracted separately, NOT as a combined total.

MANDATORY EXTRACTION RULE:
- You MUST ALWAYS extract BOTH a cash account AND an investment account
- If you can find one but not the other, set the missing one to 0 (zero)
- For example: If the document shows $10,000 cash but no investment holdings, extract:
  * One item with asset_type="savings" with the cash value
  * One item with asset_type="stocks" with value_eur_jan1=0 (or value_eur_dec31=0 if it's a Dec statement)
- This covers cases where shares were sold during the year, so Dec statements only show cash
- If you cannot find BOTH accounts (neither cash nor investment values), return empty box3_items array

IMPORTANT:
1. Determine the date range covered by this document (e.g., "1-Jan-2024 to 31-Jan-2024" or "31-Dec-2024")
2. Find the portfolio value on or near January 1st (the reference date for Box 3)
3. Find the portfolio value on or near December 31st (end of tax year, needed for actual return calculation)
4. If the document only covers one of these dates, extract that value. If it covers both, extract both.
5. ⚠️ CRITICAL DATE MAPPING FOR JANUARY STATEMENTS ⚠️:
   If this is a January statement that shows BOTH 31-Dec of the previous year (e.g., 31-Dec-2023) AND 31-Jan of the tax year (e.g., 31-Jan-2024):
   - value_eur_jan1 MUST be set to the 31-Dec (previous year) value (e.g., the 31-Dec-2023 value)
   - value_eur_dec31 MUST be set to null (we don't have Dec 31 of the tax year yet)
   - reference_date MUST be "2023-12-31" (or the actual 31-Dec date shown)
   - dec31_reference_date MUST be null
   - DO NOT use the 31-Jan value for value_eur_jan1 - that is WRONG
   - DO NOT use the 31-Dec value for value_eur_dec31 - that is WRONG
   - The field name "value_eur_jan1" means "value for the Jan 1 reference date", NOT "value on Jan 31"
   - Example: If cash shows $2,907.27 on 31-Dec-2023 and $3,061.94 on 31-Jan-2024:
     * CORRECT: value_eur_jan1=2907.27, value_eur_dec31=null, reference_date="2023-12-31"
     * WRONG: value_eur_jan1=3061.94, value_eur_dec31=2907.27 (this swaps the values!)
6. If the document doesn't cover Jan 1 or Dec 31 (or dates very close to them, accounting for weekends/holidays), you should still extract what you can, but note the date range.
7. Extract CASH/FIAT balance separately from INVESTMENT portfolio value (stocks, crypto, etc.) - these are INDIVIDUAL values, NOT the total account value. Look for separate line items showing cash balance vs. investment holdings value.
8. Find realized gains/losses for the tax year (typically only for investments)
9. Amounts may be in USD, EUR, or other currencies (preserve original currency)
10. Look for: stocks, bonds, ETFs, mutual funds, crypto assets
11. For crypto exchanges: extract fiat (EUR/USD) separately from crypto holdings
12. Extract account number/identifier if available (e.g., account number, account ID, statement number) - this is critical for matching accounts across different statements
13. Return ONLY valid JSON

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
      "value_eur_jan1": <value in original currency (will be converted later) or null if not available>,
      "value_eur_dec31": <value in original currency (will be converted later) or null if not available>,
      "original_value": <same as value_eur_jan1 if available, otherwise value_eur_dec31>,
      "original_currency": "USD" or "EUR" or other currency code,
      "realized_gains_eur": <number or null, typically only for investments>,
      "realized_losses_eur": <number or null, typically only for investments>,
      "reference_date": "YYYY-MM-DD" (the date of the value_eur_jan1, or closest to Jan 1),
      "dec31_reference_date": "YYYY-MM-DD" or null (the date of the value_eur_dec31, or closest to Dec 31),
      "description": "Account description (e.g., 'IBKR Cash Account' or 'IBKR Investment Portfolio')",
      "account_number": "Account number or identifier if available (e.g., '872', '123456789') or null",
      "extraction_confidence": <0.0 to 1.0>
    }}
  ]
}}

IMPORTANT DATE MAPPING RULES:
- If document shows data for 1-Jan-20XX, set value_eur_jan1 and reference_date="20XX-01-01"
- If document shows data for 31-Dec-20XX, set value_eur_dec31 and dec31_reference_date="20XX-12-31"
- ⚠️ CRITICAL FOR JANUARY STATEMENTS WITH BOTH DATES ⚠️:
  If a January statement shows BOTH 31-Dec of the previous year (e.g., 31-Dec-2023) AND 31-Jan of the tax year (e.g., 31-Jan-2024):
  - value_eur_jan1 = 31-Dec (previous year) value (e.g., 31-Dec-2023 value)
  - value_eur_dec31 = null (we don't have Dec 31 of the tax year yet)
  - reference_date = "2023-12-31" (the actual 31-Dec date shown)
  - dec31_reference_date = null
  - DO NOT confuse the field names: "value_eur_jan1" means "value for Jan 1 reference date", NOT "value on Jan 31"
  - DO NOT swap values: The 31-Dec value goes to value_eur_jan1, NOT to value_eur_dec31
  - The 31-Jan value should be IGNORED for Box 3 purposes (it's too far from the Jan 1 reference date)
- If document shows data for dates close to Jan 1 or Dec 31 (within 3 days, accounting for weekends/holidays), use those dates
- If document only has one of these dates, that's fine - set the other to null
- If document has neither Jan 1 nor Dec 31 (or close dates), still extract what you can but note the date range
- For original_value, use value_eur_jan1 if available, otherwise use value_eur_dec31

Examples:
- US Broker on 1-Jan-2024: $10,000 cash and $50,000 in stocks → TWO items (savings=$10k, stocks=$50k, both with value_eur_jan1 set)
- Crypto Exchange on 31-Dec-2024: €5,000 EUR balance and 2.5 BTC worth €100,000 → TWO items (savings=€5k, crypto=€100k, both with value_eur_dec31 set)
- US Broker on 31-Dec-2024: $15,000 cash but NO investment holdings (shares were sold) → TWO items (savings=$15k with value_eur_dec31, stocks=$0 with value_eur_dec31=0)
- US Broker on 1-Jan-2024: $0 cash but $30,000 in stocks → TWO items (savings=$0 with value_eur_jan1=0, stocks=$30k with value_eur_jan1)
- ⚠️ JANUARY STATEMENT WITH BOTH DATES (CRITICAL EXAMPLE) ⚠️:
  US Broker January 2024 statement showing:
  - Cash: $2,907.27 on 31-Dec-2023 and $3,061.94 on 31-Jan-2024
  - Stocks: $368,132.86 on 31-Dec-2023 and $395,212.54 on 31-Jan-2024
  → CORRECT extraction:
    * Cash item: value_eur_jan1=2907.27, value_eur_dec31=null, reference_date="2023-12-31", dec31_reference_date=null
    * Stocks item: value_eur_jan1=368132.86, value_eur_dec31=null, reference_date="2023-12-31", dec31_reference_date=null
  → WRONG extraction (DO NOT DO THIS):
    * Cash item: value_eur_jan1=3061.94, value_eur_dec31=2907.27 (values are swapped!)
    * The 31-Jan values should be IGNORED for Box 3 purposes

If you cannot find BOTH cash AND investment account values (neither can be extracted), return: {{"box3_items": [], "document_date_range": {{"start_date": null, "end_date": null}}}}
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

        # Ensure currency is set (default to USD for US brokers, but preserve EUR for crypto exchanges)
        box3_items = extracted_data.get("box3_items", [])
        for item in box3_items:
            if "original_currency" not in item:
                # Default to USD for US brokers, but validator will handle currency conversion
                item["original_currency"] = "USD"
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
            # Set original_value if not set (use jan1 if available, otherwise dec31)
            if "original_value" not in item:
                if item.get("value_eur_jan1") is not None:
                    item["original_value"] = item["value_eur_jan1"]
                elif item.get("value_eur_dec31") is not None:
                    item["original_value"] = item["value_eur_dec31"]
                else:
                    item["original_value"] = None
            if "extraction_confidence" not in item:
                # Default to 0.8 to match classification confidence default
                item["extraction_confidence"] = 0.8
            if "account_number" not in item:
                item["account_number"] = None

        # Post-processing: Ensure both cash (savings) and investment (stocks/crypto) accounts are present
        # If one is missing, add it with 0 value
        has_cash = any(item.get("asset_type") == "savings" for item in box3_items)
        has_investment = any(
            item.get("asset_type") in ["stocks", "bonds", "crypto", "other"]
            for item in box3_items
        )
        
        # Determine reference dates and account_number from existing items
        reference_date = None
        dec31_reference_date = None
        original_currency = "USD"
        account_number = None
        for item in box3_items:
            if item.get("reference_date"):
                reference_date = item["reference_date"]
            if item.get("dec31_reference_date"):
                dec31_reference_date = item["dec31_reference_date"]
            if item.get("original_currency"):
                original_currency = item["original_currency"]
            if item.get("account_number") and not account_number:
                account_number = item["account_number"]
        
        # Default reference dates if not found
        if not reference_date:
            doc_start = extracted_data.get("document_date_range", {}).get("start_date")
            if doc_start:
                reference_date = doc_start
            else:
                reference_date = date(2024, 1, 1).isoformat()
        
        # Add missing cash account with 0 value
        if not has_cash and has_investment:
            # Determine which date to use (prefer dec31 if available, otherwise jan1)
            value_jan1 = None
            value_dec31 = None
            if dec31_reference_date:
                value_dec31 = 0.0
            else:
                value_jan1 = 0.0
            
            cash_item = {
                "asset_type": "savings",
                "value_eur_jan1": value_jan1,
                "value_eur_dec31": value_dec31,
                "original_value": value_jan1 if value_jan1 is not None else value_dec31,
                "original_currency": original_currency,
                "realized_gains_eur": None,
                "realized_losses_eur": None,
                "reference_date": reference_date,
                "dec31_reference_date": dec31_reference_date,
                "description": f"{filename} Cash Account (defaulted to 0)",
                "account_number": account_number,  # Use account_number from other items if available
                "extraction_confidence": 0.5,  # Lower confidence since it's inferred
            }
            box3_items.append(cash_item)
            logger.info(f"Added missing cash account with 0 value for {filename}")
        
        # Add missing investment account with 0 value
        if not has_investment and has_cash:
            # Determine which date to use (prefer dec31 if available, otherwise jan1)
            value_jan1 = None
            value_dec31 = None
            if dec31_reference_date:
                value_dec31 = 0.0
            else:
                value_jan1 = 0.0
            
            investment_item = {
                "asset_type": "stocks",  # Default to stocks for investment account
                "value_eur_jan1": value_jan1,
                "value_eur_dec31": value_dec31,
                "original_value": value_jan1 if value_jan1 is not None else value_dec31,
                "original_currency": original_currency,
                "realized_gains_eur": None,
                "realized_losses_eur": None,
                "reference_date": reference_date,
                "dec31_reference_date": dec31_reference_date,
                "description": f"{filename} Investment Account (defaulted to 0)",
                "account_number": account_number,  # Use account_number from other items if available
                "extraction_confidence": 0.5,  # Lower confidence since it's inferred
            }
            box3_items.append(investment_item)
            logger.info(f"Added missing investment account with 0 value for {filename}")
        
        # Update extracted_data with potentially modified box3_items
        extracted_data["box3_items"] = box3_items

        logger.info(
            f"US broker parser extracted {len(box3_items)} items (cash={'yes' if has_cash else 'no'}, investment={'yes' if has_investment else 'no'})"
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
        logger.error(f"JSON parsing error in US broker parser: {e}")
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
        logger.error(f"US broker parser failed: {e}")
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


