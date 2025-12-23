"""Investment broker statement parser agent."""

import json
import logging
from datetime import date

from langchain_core.messages import HumanMessage
from langsmith import traceable

from dutch_tax_agent.llm_factory import create_llm

logger = logging.getLogger(__name__)


def _get_jan_period_prompt(doc_text: str) -> str:
    """Generate prompt for January period statements."""
    return f"""You are a specialized brokerage statement parser for Dutch tax purposes.

Extract Box 3 wealth data from a JANUARY PERIOD brokerage statement.

This is a January statement that may show:
- 1-Jan of the tax year (e.g., 1-Jan-2024) - PREFERRED: use this value for value_eur_jan1 if available
- 31-Dec of the previous year (e.g., 31-Dec-2023) - FALLBACK: use this value for value_eur_jan1 ONLY if 1-Jan is not available
- 31-Jan of the tax year (e.g., 31-Jan-2024) - IGNORE this value for Box 3 purposes

CRITICAL: Brokerages ALWAYS have TWO separate account types:
1. CASH/Savings account (cash balance, fiat currency, money market funds, uninvested cash) - use asset_type="savings"
2. INVESTMENT account (stocks, bonds, ETFs, mutual funds, crypto assets, options) - use asset_type="stocks" (or "crypto" for crypto holdings)

These MUST be extracted as SEPARATE items because Dutch Box 3 tax uses different fictional yield rates for savings vs investments.

⚠️ CRITICAL EXTRACTION WARNING ⚠️:
You MUST extract the INDIVIDUAL values of cash and equities/crypto/investments separately. 
DO NOT extract the TOTAL account value (which is typically the sum of cash + investments).

⚠️ INDIVIDUAL STOCK/ETF POSITIONS ⚠️:
Some statements show individual stock/ETF positions instead of (or in addition to) a combined investment account value.
- PRIORITY: When extracting individual positions, ALWAYS prioritize positions from the "Open Positions" table or section over positions from "Trades" sections
- If the statement has both "Open Positions" and "Trades" sections, ONLY extract from "Open Positions" (trades are historical transactions, not current holdings)
- If the statement lists individual stocks/ETFs with their values (e.g., "AAPL: $1,500", "VTI: $1,200"), extract EACH position separately
- Include an "individual_positions" array in the investment account box3_item
- Each position should include: symbol, description, quantity (if available), value, and date
- The validator will sum these individual positions to get the total investment account value
- If BOTH individual positions AND a combined total are shown, extract both (the validator will verify they match)
- If ONLY individual positions are shown (no combined total), extract them and leave value_eur_jan1/value_eur_dec31 as null (validator will sum them)
- Remember this is only valid for stocks, investments, and crypto positions. Cash positions are extracted separately.

⚠️ CRITICAL: DO NOT CALCULATE OR INFER TOTALS ⚠️:
- You MUST ONLY extract value_eur_jan1 if there is an EXPLICIT total value stated in the document
- DO NOT calculate totals by summing individual positions - the validator will do that
- DO NOT infer or estimate totals - if you cannot find an explicit total statement, set value_eur_jan1 to null
- DO NOT use approximate values or round numbers - only use exact values from the document
- If the document shows individual positions but NO explicit total, set value_eur_jan1 to null and focus on extracting the individual positions accurately
- Be careful with European number formats: dots (.) are thousands separators, commas (,) are decimal separators (e.g., "88.004,12" = 88004.12)

MANDATORY EXTRACTION RULE:
- You MUST ALWAYS extract BOTH a cash account AND an investment account
- If you can find one but not the other, set the missing one to 0 (zero)

⚠️ CRITICAL DATE MAPPING FOR JANUARY STATEMENTS ⚠️:
PRIORITY ORDER for value_eur_jan1:
1. FIRST: Look for 1-Jan of the tax year (e.g., 1-Jan-2024) - this is the PREFERRED value
2. SECOND: If 1-Jan is not available, use 31-Dec of the previous year (e.g., 31-Dec-2023)
3. NEVER: Use 31-Jan value - that is WRONG and too far from the Jan 1 reference date

⚠️ CRITICAL BALANCE SHEET COLUMN SELECTION ⚠️:
When you see a BALANCE SHEET or similar table with multiple date columns, you MUST:
- ✅ USE the "Last Period" column (often labeled "Last Period", "Previous Period", "Beginning", "as of 12/31/23", "as of 31-Dec-2023")
- ✅ USE values from dates like "12/31/23", "31-Dec-2023", "12/31/2023", or any December 31st date from the PREVIOUS year
- ❌ DO NOT USE the "This Period" column (often labeled "This Period", "Current Period", "Ending", "as of 1/31/24", "as of 31-Jan-2024")
- ❌ DO NOT USE values from dates like "1/31/24", "31-Jan-2024", "1/31/2024", or any January 31st date from the CURRENT year

Example: If you see a balance sheet like:
  "Last Period (as of 12/31/23) | This Period (as of 1/31/24)"
  "Cash: $X,XXX.XX | $Y,YYY.YY"
  "Stocks: $XXX,XXX.XX | $YYY,YYY.YY"
→ CORRECT: Extract values from the "Last Period" column (the left column with 12/31/23 date)
→ WRONG: Do NOT extract values from the "This Period" column (the right column with 1/31/24 date)

Rules:
- value_eur_jan1 MUST be set to the 1-Jan value if available, otherwise use the 31-Dec (previous year) value from the "Last Period" column
- value_eur_dec31 MUST be set to null (we don't have Dec 31 of the tax year yet)
- reference_date MUST be "2024-01-01" if using 1-Jan value, or "2023-12-31" (or the actual 31-Dec date shown) if using Dec 31 value
- dec31_reference_date MUST be null
- DO NOT use the 31-Jan value for value_eur_jan1 - that is WRONG
- DO NOT use the 31-Dec value for value_eur_dec31 - that is WRONG
- The field name "value_eur_jan1" means "value for the Jan 1 reference date", NOT "value on Jan 31"

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
      "value_eur_jan1": <value in original currency from 1-Jan if available, otherwise from 31-Dec of previous year, or null if only individual positions are shown>,
      "value_eur_dec31": null,
      "original_value": <same as value_eur_jan1, or null if only individual positions are shown>,
      "original_currency": "USD" or "EUR" or other currency code,
      "realized_gains_eur": <number or null, typically only for investments>,
      "realized_losses_eur": <number or null, typically only for investments>,
      "reference_date": "YYYY-MM-DD" (use "2024-01-01" if 1-Jan value available, otherwise use the 31-Dec date of previous year, e.g., "2023-12-31"),
      "dec31_reference_date": null,
      "description": "Account description (e.g., 'IBKR Cash Account' or 'IBKR Investment Portfolio')",
      "account_number": "Account number or identifier if available (e.g., '872', '123456789') or null",
      "extraction_confidence": <0.0 to 1.0>,
      "individual_positions": [
        {{
          "symbol": "AAPL" or ticker symbol,
          "description": "Full name of the security (e.g., 'Apple Inc.')",
          "quantity": <number of shares (required)>,
          "price": <price per share in original currency (required)>,
          "currency": "USD" or "EUR" or other currency code,
          "date": "YYYY-MM-DD" (the date this price is for, e.g., "2024-01-01" or "2023-12-31")
        }}
      ] or null (only include for investment accounts with individual positions shown)
    }}
  ]
}}

Examples:
- If cash shows $5,000 on 1-Jan-2024 and $4,500 on 31-Dec-2023:
  → CORRECT: value_eur_jan1=5000, value_eur_dec31=null, reference_date="2024-01-01" (use the 1-Jan value!)
- If cash shows $4,500 on 31-Dec-2023 and $5,200 on 31-Jan-2024, but NO 1-Jan value:
  → CORRECT: value_eur_jan1=4500, value_eur_dec31=null, reference_date="2023-12-31" (fallback to Dec 31)
  → WRONG: value_eur_jan1=5200, value_eur_dec31=4500 (never use 31-Jan value!)
- Balance sheet example with "Last Period" and "This Period" columns:
  Balance sheet shows:
    "Last Period (as of 12/31/23) | This Period (as of 1/31/24)"
    "Cash, BDP, MMFs: $X,XXX.XX | $Y,YYY.YY"
    "Stocks: $XXX,XXX.XX | $YYY,YYY.YY"
  → CORRECT: Extract values from the "Last Period" column (left column with 12/31/23 date)
  → WRONG: Do NOT extract values from the "This Period" column (right column with 1/31/24 date)
- Individual positions example:
  Statement shows individual positions:
    "AAPL: 10 shares @ $150 = $1,500"
    "VTI: 5 shares @ $240 = $1,200"
    "Total portfolio value: $2,700"  ← EXPLICIT total found
  → CORRECT: Extract individual_positions array with quantity=10, price=150 for AAPL and quantity=5, price=240 for VTI, AND include value_eur_jan1=2700 (explicit total found)
  
  Statement shows individual positions WITHOUT explicit total:
    "AAPL: 10 shares @ $150 = $1,500"
    "VTI: 5 shares @ $240 = $1,200"
    (No "Total" line shown)
  → CORRECT: Extract individual_positions array with quantity=10, price=150 for AAPL and quantity=5, price=240 for VTI, value_eur_jan1=null (no explicit total, validator will calculate quantity×price and sum)
  → WRONG: value_eur_jan1=2700 (DO NOT calculate by summing positions!)

If you cannot find BOTH cash AND investment account values (neither can be extracted), return: {{"box3_items": [], "document_date_range": {{"start_date": null, "end_date": null}}}}
"""


def _get_dec_period_prompt(doc_text: str) -> str:
    """Generate prompt for December period statements."""
    return f"""You are a specialized brokerage statement parser for Dutch tax purposes.

Extract Box 3 wealth data from a DECEMBER PERIOD brokerage statement.

This is a December statement that shows:
- 31-Dec of the tax year (e.g., 31-Dec-2024) - this value goes to value_eur_dec31
- We do NOT have Jan 1 data in a December statement, so value_eur_jan1 must be null

CRITICAL: Brokerages ALWAYS have TWO separate account types:
1. CASH/Savings account (cash balance, fiat currency, money market funds, uninvested cash) - use asset_type="savings"
2. INVESTMENT account (stocks, bonds, ETFs, mutual funds, crypto assets, options) - use asset_type="stocks" (or "crypto" for crypto holdings)

These MUST be extracted as SEPARATE items because Dutch Box 3 tax uses different fictional yield rates for savings vs investments.

⚠️ CRITICAL EXTRACTION WARNING ⚠️:
You MUST extract the INDIVIDUAL values of cash and equities/crypto/investments separately. 
DO NOT extract the TOTAL account value (which is typically the sum of cash + investments).

⚠️ INDIVIDUAL STOCK/ETF POSITIONS ⚠️:
Some statements show individual stock/ETF positions instead of (or in addition to) a combined investment account value.
- PRIORITY: When extracting individual positions, ALWAYS prioritize positions from the "Open Positions" table or section over positions from "Trades" sections
- If the statement has both "Open Positions" and "Trades" sections, ONLY extract from "Open Positions" (trades are historical transactions, not current holdings)
- If the statement lists individual stocks/ETFs with their prices and quantities (e.g., "AAPL: 10 shares @ $150", "VTI: 5 shares @ $240"), extract EACH position separately
- Include an "individual_positions" array in the investment account box3_item
- Each position should include: symbol, description, quantity (number of shares), price (price per share in original currency), and date
- DO NOT extract the total position value - extract the price per share instead
- The validator will calculate the value by multiplying quantity × price for each position, then sum them to get the total investment account value
- If BOTH individual positions AND a combined total are shown, extract both (the validator will verify they match)
- If ONLY individual positions are shown (no combined total), extract them and leave value_eur_dec31 as null (validator will calculate and sum them)
- Remember this is only valid for stocks, investments, and crypto positions. Cash positions are extracted separately.

⚠️ CRITICAL: DO NOT CALCULATE OR INFER TOTALS ⚠️:
- You MUST ONLY extract value_eur_dec31 if there is an EXPLICIT total value stated in the document
- DO NOT calculate totals by summing individual positions - the validator will do that
- DO NOT infer or estimate totals - if you cannot find an explicit total statement, set value_eur_dec31 to null
- DO NOT use approximate values or round numbers - only use exact values from the document
- If the document shows individual positions but NO explicit total, set value_eur_dec31 to null and focus on extracting the individual positions accurately
- Be careful with European number formats: dots (.) are thousands separators, commas (,) are decimal separators (e.g., "88.004,12" = 88004.12)

MANDATORY EXTRACTION RULE:
- You MUST ALWAYS extract BOTH a cash account AND an investment account
- If you can find one but not the other, set the missing one to 0 (zero)
- This covers cases where shares were sold during the year, so Dec statements only show cash

⚠️ CRITICAL DATE MAPPING FOR DECEMBER STATEMENTS ⚠️:
- value_eur_dec31 MUST be set to the Dec 31 value shown in the document
- value_eur_jan1 MUST be set to null (we don't have Jan 1 data in a December statement)
- reference_date MUST be "2024-01-01" (the tax year's Jan 1, even though we don't have that value)
- dec31_reference_date MUST be "2024-12-31" (the actual Dec 31 date shown)
- DO NOT put the Dec 31 value into value_eur_jan1 - that is WRONG

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
      "value_eur_jan1": null,
      "value_eur_dec31": <value in original currency from 31-Dec of tax year, or null if only individual positions are shown>,
      "original_value": <same as value_eur_dec31, or null if only individual positions are shown>,
      "original_currency": "USD" or "EUR" or other currency code,
      "realized_gains_eur": <number or null, typically only for investments>,
      "realized_losses_eur": <number or null, typically only for investments>,
      "reference_date": "YYYY-MM-DD" (the tax year's Jan 1, e.g., "2024-01-01"),
      "dec31_reference_date": "YYYY-MM-DD" (the actual Dec 31 date shown, e.g., "2024-12-31"),
      "description": "Account description (e.g., 'IBKR Cash Account' or 'IBKR Investment Portfolio')",
      "account_number": "Account number or identifier if available (e.g., '872', '123456789') or null",
      "extraction_confidence": <0.0 to 1.0>,
      "individual_positions": [
        {{
          "symbol": "AAPL" or ticker symbol,
          "description": "Full name of the security (e.g., 'Apple Inc.')",
          "quantity": <number of shares (required)>,
          "price": <price per share in original currency (required)>,
          "currency": "USD" or "EUR" or other currency code,
          "date": "YYYY-MM-DD" (the date this price is for, e.g., "2024-12-31")
        }}
      ] or null (only include for investment accounts with individual positions shown)
    }}
  ]
}}

Example: December 2024 statement showing:
- Cash: $2,000 on 31-Dec-2024
- Stocks: $100,000 on 31-Dec-2024
→ CORRECT extraction:
  * Cash item: value_eur_jan1=null, value_eur_dec31=2000, reference_date="2024-01-01", dec31_reference_date="2024-12-31"
  * Stocks item: value_eur_jan1=null, value_eur_dec31=100000, reference_date="2024-01-01", dec31_reference_date="2024-12-31"
→ WRONG extraction (DO NOT DO THIS):
  * Cash item: value_eur_jan1=2000, value_eur_dec31=null, reference_date="2024-12-31" (Dec 31 value should go to value_eur_dec31!)
- Individual positions example:
  Statement shows individual positions on 31-Dec-2024:
    "AAPL: 10 shares @ $150 = $1,500"
    "VTI: 5 shares @ $240 = $1,200"
    "Total portfolio value: $2,700"  ← EXPLICIT total found
  → CORRECT: Extract individual_positions array with quantity=10, price=150 for AAPL and quantity=5, price=240 for VTI, AND include value_eur_dec31=2700 (explicit total found)
  
  Statement shows individual positions WITHOUT explicit total:
    "AAPL: 10 shares @ $150 = $1,500"
    "VTI: 5 shares @ $240 = $1,200"
    (No "Total" line shown)
  → CORRECT: Extract individual_positions array with quantity=10, price=150 for AAPL and quantity=5, price=240 for VTI, value_eur_dec31=null (no explicit total, validator will calculate quantity×price and sum)
  → WRONG: value_eur_dec31=2700 (DO NOT calculate by summing positions!)

If you cannot find BOTH cash AND investment account values (neither can be extracted), return: {{"box3_items": [], "document_date_range": {{"start_date": null, "end_date": null}}}}
"""


def _get_dec_prev_year_prompt(doc_text: str) -> str:
    """Generate prompt for December period statements of the previous year (used as Jan 1 value)."""
    return f"""You are a specialized brokerage statement parser for Dutch tax purposes.

Extract Box 3 wealth data from a DECEMBER PERIOD STATEMENT OF THE PREVIOUS YEAR.

This is a December statement from the PREVIOUS year (e.g., Dec 2023 for tax year 2024) that shows:
- 31-Dec of the previous year (e.g., 31-Dec-2023) - this value goes to value_eur_jan1 (as it represents the Jan 1 value for the tax year)
- We do NOT have Dec 31 of the tax year in this document, so value_eur_dec31 must be null

CRITICAL: This document is being used as a substitute for the Jan 1 value because:
- The January statement may only have 31-Jan values (which are too far from Jan 1)
- The January statement may not have 31-Dec of the previous year values
- This December statement of the previous year provides the closest approximation to Jan 1

CRITICAL: Brokerages ALWAYS have TWO separate account types:
1. CASH/Savings account (cash balance, fiat currency, money market funds, uninvested cash) - use asset_type="savings"
2. INVESTMENT account (stocks, bonds, ETFs, mutual funds, crypto assets, options) - use asset_type="stocks" (or "crypto" for crypto holdings)

These MUST be extracted as SEPARATE items because Dutch Box 3 tax uses different fictional yield rates for savings vs investments.

⚠️ CRITICAL EXTRACTION WARNING ⚠️:
You MUST extract the INDIVIDUAL values of cash and equities/crypto/investments separately. 
DO NOT extract the TOTAL account value (which is typically the sum of cash + investments).

⚠️ INDIVIDUAL STOCK/ETF POSITIONS ⚠️:
Some statements show individual stock/ETF positions instead of (or in addition to) a combined investment account value.
- PRIORITY: When extracting individual positions, ALWAYS prioritize positions from the "Open Positions" table or section over positions from "Trades" sections
- If the statement has both "Open Positions" and "Trades" sections, ONLY extract from "Open Positions" (trades are historical transactions, not current holdings)
- If the statement lists individual stocks/ETFs with their values (e.g., "AAPL: $1,500", "VTI: $1,200"), extract EACH position separately
- Include an "individual_positions" array in the investment account box3_item
- Each position should include: symbol, description, quantity (if available), value, and date
- The validator will sum these individual positions to get the total investment account value
- If BOTH individual positions AND a combined total are shown, extract both (the validator will verify they match)
- If ONLY individual positions are shown (no combined total), extract them and leave value_eur_jan1 as null (validator will sum them)
- Remember this is only valid for stocks, investments, and crypto positions. Cash positions are extracted separately.

⚠️ CRITICAL: DO NOT CALCULATE OR INFER TOTALS ⚠️:
- You MUST ONLY extract value_eur_jan1 if there is an EXPLICIT total value stated in the document
- DO NOT calculate totals by summing individual positions - the validator will do that
- DO NOT infer or estimate totals - if you cannot find an explicit total statement, set value_eur_jan1 to null
- DO NOT use approximate values or round numbers - only use exact values from the document
- If the document shows individual positions but NO explicit total, set value_eur_jan1 to null and focus on extracting the individual positions accurately
- Be careful with European number formats: dots (.) are thousands separators, commas (,) are decimal separators (e.g., "88.004,12" = 88004.12)

MANDATORY EXTRACTION RULE:
- You MUST ALWAYS extract BOTH a cash account AND an investment account
- If you can find one but not the other, set the missing one to 0 (zero)

⚠️ CRITICAL DATE MAPPING FOR DECEMBER PREVIOUS YEAR STATEMENTS ⚠️:
- value_eur_jan1 MUST be set to the Dec 31 value shown in the document (from the previous year)
- value_eur_dec31 MUST be set to null (we don't have Dec 31 of the tax year in this document)
- reference_date MUST be set to the actual Dec 31 date shown (e.g., "2023-12-31" for a Dec 2023 statement)
- dec31_reference_date MUST be null
- DO NOT put the Dec 31 value into value_eur_dec31 - that is WRONG
- The field name "value_eur_jan1" means "value for the Jan 1 reference date", and this Dec 31 value is being used as a proxy for Jan 1

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
      "value_eur_jan1": <value in original currency from 31-Dec of previous year, or null if only individual positions are shown>,
      "value_eur_dec31": null,
      "original_value": <same as value_eur_jan1, or null if only individual positions are shown>,
      "original_currency": "USD" or "EUR" or other currency code,
      "realized_gains_eur": <number or null, typically only for investments>,
      "realized_losses_eur": <number or null, typically only for investments>,
      "reference_date": "YYYY-MM-DD" (the actual Dec 31 date shown, e.g., "2023-12-31"),
      "dec31_reference_date": null,
      "description": "Account description (e.g., 'IBKR Cash Account' or 'IBKR Investment Portfolio')",
      "account_number": "Account number or identifier if available (e.g., '872', '123456789') or null",
      "extraction_confidence": <0.0 to 1.0>,
      "individual_positions": [
        {{
          "symbol": "AAPL" or ticker symbol,
          "description": "Full name of the security (e.g., 'Apple Inc.')",
          "quantity": <number of shares (required)>,
          "price": <price per share in original currency (required)>,
          "currency": "USD" or "EUR" or other currency code,
          "date": "YYYY-MM-DD" (the date this price is for, e.g., "2023-12-31")
        }}
      ] or null (only include for investment accounts with individual positions shown)
    }}
  ]
}}

Example: December 2023 statement (for tax year 2024) showing:
- Cash: $2,000 on 31-Dec-2023
- Stocks: $100,000 on 31-Dec-2023
→ CORRECT extraction:
  * Cash item: value_eur_jan1=2000, value_eur_dec31=null, reference_date="2023-12-31", dec31_reference_date=null
  * Stocks item: value_eur_jan1=100000, value_eur_dec31=null, reference_date="2023-12-31", dec31_reference_date=null
→ WRONG extraction (DO NOT DO THIS):
  * Cash item: value_eur_jan1=null, value_eur_dec31=2000, reference_date="2024-01-01", dec31_reference_date="2023-12-31" (Dec 31 value should go to value_eur_jan1, not value_eur_dec31!)
- Individual positions example:
  Statement shows individual positions on 31-Dec-2023:
    "AAPL: 10 shares @ $150 = $1,500"
    "VTI: 5 shares @ $240 = $1,200"
    "Total portfolio value: $2,700"  ← EXPLICIT total found
  → CORRECT: Extract individual_positions array with both positions, AND include value_eur_jan1=2700 (explicit total found)
  
  Statement shows individual positions WITHOUT explicit total:
    "AAPL: 10 shares @ $150 = $1,500"
    "VTI: 5 shares @ $240 = $1,200"
    (No "Total" line shown)
  → CORRECT: Extract individual_positions array with both positions, value_eur_jan1=null (no explicit total, validator will sum)
  → WRONG: value_eur_jan1=2700 (DO NOT calculate by summing positions!)

If you cannot find BOTH cash AND investment account values (neither can be extracted), return: {{"box3_items": [], "document_date_range": {{"start_date": null, "end_date": null}}}}
"""


def _get_full_year_prompt(doc_text: str) -> str:
    """Generate prompt for full year statements."""
    return f"""You are a specialized brokerage statement parser for Dutch tax purposes.

Extract Box 3 wealth data from a FULL YEAR brokerage statement.

This is a full year statement that may show:
- Both Jan 1 (or close to it) and Dec 31 (or close to it) values - extract BOTH when available
- OR only Dec 31 values if the account was opened mid-year (e.g., account opened in July, statement covers July to Dec 31)
- For accounts opened mid-year: the statement is still a full_year statement, but there will be no Jan 1 data (account didn't exist then)

CRITICAL: Brokerages ALWAYS have TWO separate account types:
1. CASH/Savings account (cash balance, fiat currency, money market funds, uninvested cash) - use asset_type="savings"
2. INVESTMENT account (stocks, bonds, ETFs, mutual funds, crypto assets, options) - use asset_type="stocks" (or "crypto" for crypto holdings)

These MUST be extracted as SEPARATE items because Dutch Box 3 tax uses different fictional yield rates for savings vs investments.

⚠️ CRITICAL EXTRACTION WARNING ⚠️:
You MUST extract the INDIVIDUAL values of cash and equities/crypto/investments separately. 
DO NOT extract the TOTAL account value (which is typically the sum of cash + investments).

⚠️ INDIVIDUAL STOCK/ETF POSITIONS ⚠️:
Some statements show individual stock/ETF positions instead of (or in addition to) a combined investment account value.
- PRIORITY: When extracting individual positions, ALWAYS prioritize positions from the "Open Positions" table or section over positions from "Trades" sections
- If the statement has both "Open Positions" and "Trades" sections, ONLY extract from "Open Positions" (trades are historical transactions, not current holdings)
- If the statement lists individual stocks/ETFs with their values (e.g., "AAPL: $1,500", "VTI: $1,200"), extract EACH position separately
- Include an "individual_positions" array in the investment account box3_item
- Each position should include: symbol, description, quantity (if available), value, and date
- The validator will sum these individual positions to get the total investment account value
- If BOTH individual positions AND a combined total are shown, extract both (the validator will verify they match)
- If ONLY individual positions are shown (no combined total), extract them and leave value_eur_jan1/value_eur_dec31 as null (validator will sum them)
- Remember this is only valid for stocks, investments, and crypto positions. Cash positions are extracted separately.

⚠️ CRITICAL: DO NOT CALCULATE OR INFER TOTALS ⚠️:
- You MUST ONLY extract value_eur_jan1 or value_eur_dec31 if there is an EXPLICIT total value stated in the document
- DO NOT calculate totals by summing individual positions - the validator will do that
- DO NOT infer or estimate totals - if you cannot find an explicit total statement, set value_eur_jan1/value_eur_dec31 to null
- DO NOT use approximate values or round numbers - only use exact values from the document
- If the document shows individual positions but NO explicit total, set value_eur_jan1/value_eur_dec31 to null and focus on extracting the individual positions accurately
- Be careful with European number formats: dots (.) are thousands separators, commas (,) are decimal separators (e.g., "88.004,12" = 88004.12)

MANDATORY EXTRACTION RULE:
- You MUST ALWAYS extract BOTH a cash account AND an investment account
- If you can find one but not the other, set the missing one to 0 (zero)

IMPORTANT DATE MAPPING:
- If document shows data for 1-Jan-20XX, set value_eur_jan1 and reference_date="20XX-01-01"
- If document shows data for 31-Dec-20XX, set value_eur_dec31 and dec31_reference_date="20XX-12-31"
- If document shows data for dates close to Jan 1 or Dec 31 (within 3 days, accounting for weekends/holidays), use those dates
- If account was opened mid-year (e.g., July 1, 2024) and statement shows account opening date to Dec 31:
  * value_eur_jan1 should be null (account didn't exist on Jan 1)
  * value_eur_dec31 should be set to the Dec 31 value shown
  * reference_date should be set to the account opening date (e.g., "2024-07-01") or the earliest date shown in the statement
  * dec31_reference_date should be "20XX-12-31"
- If document only has one of these dates, that's fine - set the other to null
- For original_value, use value_eur_jan1 if available, otherwise use value_eur_dec31

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
      "value_eur_jan1": <value in original currency or null if not available, or null if only individual positions are shown>,
      "value_eur_dec31": <value in original currency or null if not available, or null if only individual positions are shown>,
      "original_value": <same as value_eur_jan1 if available, otherwise value_eur_dec31, or null if only individual positions are shown>,
      "original_currency": "USD" or "EUR" or other currency code,
      "realized_gains_eur": <number or null, typically only for investments>,
      "realized_losses_eur": <number or null, typically only for investments>,
      "reference_date": "YYYY-MM-DD" (the date of the value_eur_jan1, or closest to Jan 1),
      "dec31_reference_date": "YYYY-MM-DD" or null (the date of the value_eur_dec31, or closest to Dec 31),
      "description": "Account description (e.g., 'IBKR Cash Account' or 'IBKR Investment Portfolio')",
      "account_number": "Account number or identifier if available (e.g., '872', '123456789') or null",
      "extraction_confidence": <0.0 to 1.0>,
      "individual_positions": [
        {{
          "symbol": "AAPL" or ticker symbol,
          "description": "Full name of the security (e.g., 'Apple Inc.')",
          "quantity": <number of shares (required)>,
          "price": <price per share in original currency (required)>,
          "currency": "USD" or "EUR" or other currency code,
          "date": "YYYY-MM-DD" (the date this price is for, e.g., "2024-01-01" or "2024-12-31")
        }}
      ] or null (only include for investment accounts with individual positions shown)
    }}
  ]
}}

Examples:
- Full year statement showing $10,000 cash and $50,000 in stocks on both Jan 1 and Dec 31:
  → TWO items (savings=$10k, stocks=$50k, both with value_eur_jan1 and value_eur_dec31 set)
- Full year statement showing only Dec 31 values (account existed all year):
  → TWO items (savings and stocks, both with value_eur_jan1=null, value_eur_dec31 set)
- Full year statement for account opened mid-year (e.g., July 1, 2024) showing Dec 31 values:
  → TWO items (savings and stocks, both with value_eur_jan1=null, value_eur_dec31 set, reference_date="2024-07-01" or account opening date)
- Individual positions example:
  Statement shows individual positions:
    Jan 1, 2024:
      "AAPL: 10 shares @ $150 = $1,500"
      "VTI: 5 shares @ $240 = $1,200"
      "Total portfolio value: $2,700"  ← EXPLICIT total found
    Dec 31, 2024:
      "AAPL: 10 shares @ $160 = $1,600"
      "VTI: 5 shares @ $250 = $1,250"
      "Total portfolio value: $2,850"  ← EXPLICIT total found
  → CORRECT: Extract individual_positions array with positions for both dates, AND include value_eur_jan1=2700 and value_eur_dec31=2850 (explicit totals found)
  
  Statement shows individual positions WITHOUT explicit totals:
    Dec 31, 2024:
      "AAPL: 10 shares @ $160 = $1,600"
      "VTI: 5 shares @ $250 = $1,250"
      (No "Total" line shown)
  → CORRECT: Extract individual_positions array with both positions, value_eur_dec31=null (no explicit total, validator will sum)
  → WRONG: value_eur_dec31=2850 (DO NOT calculate by summing positions!)

If you cannot find BOTH cash AND investment account values (neither can be extracted), return: {{"box3_items": [], "document_date_range": {{"start_date": null, "end_date": null}}}}
"""


@traceable(name="Investment Broker Parser Agent")
def investment_broker_parser_agent(input_data: dict) -> dict:
    """Parse investment brokerage statements for Box 3 assets.
    
    Handles both US and European investment broker statements.
    
    Extracts:
    - Investment portfolio value on Jan 1
    - Realized gains/losses during the year
    - Currency (USD, EUR, or other)
    
    Args:
        input_data: Dict with doc_id, doc_text, filename, classification
        
    Returns:
        Dict with extracted Box 3 asset data (will be converted to EUR later)
    """
    doc_id = input_data["doc_id"]
    doc_text = input_data["doc_text"]
    filename = input_data["filename"]
    classification = input_data.get("classification", {})
    statement_subtype = classification.get("statement_subtype")

    logger.info(
        f"Investment broker parser processing {filename} "
        f"(subtype: {statement_subtype or 'unknown'})"
    )

    llm = create_llm(temperature=0)

    # Select prompt based on statement subtype
    if statement_subtype == "jan_period":
        prompt = _get_jan_period_prompt(doc_text)
    elif statement_subtype == "dec_period":
        prompt = _get_dec_period_prompt(doc_text)
    elif statement_subtype == "dec_prev_year":
        prompt = _get_dec_prev_year_prompt(doc_text)
    elif statement_subtype == "full_year":
        prompt = _get_full_year_prompt(doc_text)
    else:
        # Fallback to a generic prompt if subtype is not available
        logger.warning(
            f"No statement subtype provided for {filename}, using generic prompt"
        )
        prompt = _get_full_year_prompt(doc_text)  # Use full_year as default fallback

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
            
            # Validate and log individual positions if present
            if "individual_positions" in item and item["individual_positions"]:
                positions = item["individual_positions"]
                if isinstance(positions, list) and len(positions) > 0:
                    logger.info(
                        f"Found {len(positions)} individual positions for {item.get('asset_type', 'unknown')} "
                        f"account in {filename}"
                    )
                    # Validate position structure
                    for pos_idx, pos in enumerate(positions):
                        if not isinstance(pos, dict):
                            logger.warning(
                                f"Invalid position structure at index {pos_idx} in {filename}: "
                                f"expected dict, got {type(pos)}"
                            )
                            continue
                        required_fields = ["symbol", "quantity", "price", "date"]
                        missing_fields = [f for f in required_fields if f not in pos]
                        if missing_fields:
                            logger.warning(
                                f"Position {pos.get('symbol', f'at index {pos_idx}')} in {filename} "
                                f"missing required fields: {missing_fields}"
                            )

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
            f"Investment broker parser extracted {len(box3_items)} items (cash={'yes' if has_cash else 'no'}, investment={'yes' if has_investment else 'no'})"
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
        logger.error(f"JSON parsing error in investment broker parser: {e}")
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
        logger.error(f"Investment broker parser failed: {e}")
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

