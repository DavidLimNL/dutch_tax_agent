"""Salary statement parser agent."""

import json
import logging
import re
from datetime import date

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

    # Get tax year from classification if available
    classification = input_data.get("classification", {})
    tax_year = classification.get("tax_year")
    
    prompt = f"""You are a specialized salary statement parser for Dutch tax purposes.

Extract Box 1 income data (employment income).

IMPORTANT:
1. Find gross salary/income amounts
2. Find tax withheld (loonheffing/inhouding)
3. Identify the period (month/quarter/year)
4. Determine the document date range (start_date and end_date) that this document covers
5. For year-end statements (Jaaropgaaf), the document typically covers the full tax year (e.g., 2024-01-01 to 2024-12-31)
6. All amounts should be in EUR
7. Return ONLY valid JSON

Document:
{doc_text}

Return JSON in this EXACT format:
{{
  "document_date_range": {{
    "start_date": "YYYY-MM-DD" or null,
    "end_date": "YYYY-MM-DD" or null
  }},
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

For year-end statements (Jaaropgaaf), set document_date_range to cover the full tax year.
For monthly/quarterly statements, set document_date_range to the period covered by the statement.

If no income data found, return: {{"box1_items": [], "document_date_range": {{"start_date": null, "end_date": null}}}}
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
        
        # If document_date_range is missing or incomplete, try to infer it
        doc_date_range = extracted_data.get("document_date_range", {})
        doc_start = doc_date_range.get("start_date")
        doc_end = doc_date_range.get("end_date")
        
        # If date range is missing, try to infer from box1_items or filename
        if not doc_start or not doc_end:
            # Check if this is a year-end statement (Jaaropgaaf)
            is_jaaropgaaf = "jaaropgaaf" in filename.lower() or "jaar" in filename.lower()
            
            # Try to extract tax year from filename if not in classification
            inferred_tax_year = tax_year
            if not inferred_tax_year:
                # Look for 4-digit year in filename (e.g., "2024-Jaaropgaaf-750241-2024-12.pdf")
                year_matches = re.findall(r'\b(20\d{2})\b', filename)
                if year_matches:
                    try:
                        inferred_tax_year = int(year_matches[0])
                        # Validate reasonable year range
                        if 2000 <= inferred_tax_year <= 2100:
                            logger.info(f"Inferred tax year {inferred_tax_year} from filename {filename}")
                    except (ValueError, TypeError):
                        pass
            
            # Try to infer from box1_items periods
            box1_items = extracted_data.get("box1_items", [])
            if box1_items:
                # Find the earliest period_start and latest period_end
                period_starts = []
                period_ends = []
                for item in box1_items:
                    if item.get("period_start"):
                        try:
                            period_starts.append(date.fromisoformat(item["period_start"]))
                        except (ValueError, TypeError):
                            pass
                    if item.get("period_end"):
                        try:
                            period_ends.append(date.fromisoformat(item["period_end"]))
                        except (ValueError, TypeError):
                            pass
                
                if period_starts and period_ends:
                    inferred_start = min(period_starts)
                    inferred_end = max(period_ends)
                    
                    # If this is a year-end statement and we have a tax year, use full year
                    if is_jaaropgaaf and inferred_tax_year:
                        inferred_start = date(inferred_tax_year, 1, 1)
                        inferred_end = date(inferred_tax_year, 12, 31)
                    
                    if not doc_start:
                        doc_start = inferred_start.isoformat()
                    if not doc_end:
                        doc_end = inferred_end.isoformat()
                elif is_jaaropgaaf and inferred_tax_year:
                    # For year-end statements, use full tax year
                    doc_start = date(inferred_tax_year, 1, 1).isoformat()
                    doc_end = date(inferred_tax_year, 12, 31).isoformat()
            
            # Update document_date_range
            extracted_data["document_date_range"] = {
                "start_date": doc_start,
                "end_date": doc_end
            }

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
            f"Salary parser extracted {len(extracted_data.get('box1_items', []))} items, "
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


