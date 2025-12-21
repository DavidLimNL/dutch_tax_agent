"""Salary statement parser agent."""

import json
import logging

from langchain_core.messages import HumanMessage
from langsmith import traceable

from dutch_tax_agent.llm_factory import create_llm

logger = logging.getLogger(__name__)


@traceable(name="Salary Parser Agent")
def salary_parser_agent(input_data: dict) -> dict:
    """Parse salary statements for Box 1 income.
    
    Extracts:
    - Gross salary amount
    - Tax withheld
    - Period of employment
    
    Args:
        input_data: Dict with doc_id, doc_text, filename, classification
        
    Returns:
        Dict with extracted Box 1 income data
    """
    doc_id = input_data["doc_id"]
    doc_text = input_data["doc_text"]
    filename = input_data["filename"]

    logger.info(f"Salary parser processing {filename}")

    llm = create_llm(temperature=0)

    prompt = f"""You are a specialized salary statement parser for Dutch tax purposes.

Extract Box 1 income data (employment income).

IMPORTANT:
1. Find gross salary/income amounts
2. Find tax withheld (loonheffing/inhouding)
3. Identify the period (month/quarter/year)
4. All amounts should be in EUR
5. Return ONLY valid JSON

Document:
{doc_text}

Return JSON in this EXACT format:
{{
  "box1_items": [
    {{
      "income_type": "salary" or "bonus" or "freelance",
      "gross_amount_eur": <number>,
      "tax_withheld_eur": <number>,
      "period_start": "YYYY-MM-DD",
      "period_end": "YYYY-MM-DD",
      "original_currency": "EUR",
      "extraction_confidence": <0.0 to 1.0>
    }}
  ]
}}

If no income data found, return: {{"box1_items": []}}
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

        # Validate and set defaults
        for item in extracted_data.get("box1_items", []):
            if "original_currency" not in item:
                item["original_currency"] = "EUR"
            if "extraction_confidence" not in item:
                # Default to 0.8 to match classification confidence default
                item["extraction_confidence"] = 0.8
            if "tax_withheld_eur" not in item:
                item["tax_withheld_eur"] = 0.0

        logger.info(
            f"Salary parser extracted {len(extracted_data.get('box1_items', []))} items"
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
        logger.error(f"JSON parsing error in salary parser: {e}")
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
        logger.error(f"Salary parser failed: {e}")
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


