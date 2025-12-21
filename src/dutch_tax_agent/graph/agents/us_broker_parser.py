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

CRITICAL: Brokerages typically have TWO separate account types:
1. CASH/Savings account (cash balance, fiat currency, money market funds, uninvested cash)
2. INVESTMENT account (stocks, bonds, ETFs, mutual funds, crypto assets, options)

These MUST be extracted as SEPARATE items because Dutch Box 3 tax uses different fictional yield rates for savings vs investments.

IMPORTANT:
1. Find the portfolio value on or near January 1st
2. Extract CASH/FIAT balance separately from INVESTMENT portfolio value (stocks, crypto, etc.)
3. Find realized gains/losses for the tax year (typically only for investments)
4. Amounts may be in USD, EUR, or other currencies (preserve original currency)
5. Look for: stocks, bonds, ETFs, mutual funds, crypto assets
6. For crypto exchanges: extract fiat (EUR/USD) separately from crypto holdings
7. Return ONLY valid JSON

Document:
{doc_text}

Return JSON in this EXACT format:
{{
  "box3_items": [
    {{
      "asset_type": "savings" or "stocks" or "bonds" or "crypto" or "other",
      "value_eur_jan1": <value in original currency (will be converted later)>,
      "original_value": <same as value_eur_jan1>,
      "original_currency": "USD" or "EUR" or other currency code,
      "realized_gains_eur": <number or null, typically only for investments>,
      "realized_losses_eur": <number or null, typically only for investments>,
      "reference_date": "YYYY-MM-DD",
      "description": "Account description (e.g., 'IBKR Cash Account' or 'IBKR Investment Portfolio')",
      "extraction_confidence": <0.0 to 1.0>
    }}
  ]
}}

Examples:
- US Broker: $10,000 cash and $50,000 in stocks → TWO items (savings=$10k, stocks=$50k)
- Crypto Exchange: €5,000 EUR balance and 2.5 BTC worth €100,000 → TWO items (savings=€5k, crypto=€100k)

If no data found, return: {{"box3_items": []}}
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

        # Ensure currency is set (default to USD for US brokers, but preserve EUR for crypto exchanges)
        for item in extracted_data.get("box3_items", []):
            if "original_currency" not in item:
                # Default to USD for US brokers, but validator will handle currency conversion
                item["original_currency"] = "USD"
            if "reference_date" not in item:
                item["reference_date"] = date(2024, 1, 1).isoformat()
            if "extraction_confidence" not in item:
                # Default to 0.8 to match classification confidence default
                item["extraction_confidence"] = 0.8

        logger.info(
            f"US broker parser extracted {len(extracted_data.get('box3_items', []))} items"
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


