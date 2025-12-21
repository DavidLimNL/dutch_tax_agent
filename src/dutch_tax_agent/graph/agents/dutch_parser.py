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
1. Look for account balances on or near January 1st (the reference date for Box 3)
2. Identify the account type: savings, investment (stocks/bonds), crypto, or other
3. Extract each account type separately (e.g., if there's both a savings and investment account, create two items)
4. Look for realized gains, dividends, or interest income during the year
5. All amounts should be in EUR
6. Return ONLY valid JSON, no additional text

Document:
{doc_text}

Return JSON in this EXACT format:
{{
  "box3_items": [
    {{
      "asset_type": "savings" or "stocks" or "bonds" or "crypto" or "other",
      "value_eur_jan1": <number>,
      "realized_gains_eur": <number or null>,
      "reference_date": "YYYY-MM-DD",
      "description": "Account name or description (e.g., 'ING Spaarrekening' or 'ABN AMRO Beleggingsrekening')",
      "original_currency": "EUR",
      "extraction_confidence": <0.0 to 1.0>
    }}
  ]
}}

Example: If a statement shows €20,000 in savings and €30,000 in investments, return TWO items:
- One with asset_type="savings", value_eur_jan1=20000
- One with asset_type="stocks", value_eur_jan1=30000

If no Box 3 data is found, return: {{"box3_items": []}}
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

        # Add reference date and other missing fields if not present
        for item in extracted_data.get("box3_items", []):
            if "reference_date" not in item:
                item["reference_date"] = date(2024, 1, 1).isoformat()
            if "original_currency" not in item:
                item["original_currency"] = "EUR"
            if "extraction_confidence" not in item:
                # Default to 0.8 to match classification confidence default
                item["extraction_confidence"] = 0.8

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


