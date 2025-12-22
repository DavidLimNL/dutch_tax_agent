"""Dispatcher node: Routes documents to specialized parser agents."""

import logging

from langchain_core.messages import HumanMessage
from langgraph.graph import END
from langgraph.types import Command, Send

from dutch_tax_agent.llm_factory import create_llm
from dutch_tax_agent.schemas.documents import DocumentClassification
from dutch_tax_agent.schemas.state import TaxGraphState

logger = logging.getLogger(__name__)


def classify_document(doc_text: str, doc_id: str, tax_year: int | None = None) -> DocumentClassification:
    """Classify a document to determine which parser agent to use and extract tax year.
    
    Args:
        doc_text: Scrubbed document text
        doc_id: Document ID
        tax_year: Tax year being processed (used to distinguish dec_period from dec_prev_year)
        
    Returns:
        DocumentClassification with type, confidence, and tax year
    """
    llm = create_llm(temperature=0)

    tax_year_context = ""
    if tax_year is not None:
        tax_year_context = f"\n\nIMPORTANT CONTEXT: The tax year being processed is {tax_year}. Use this to distinguish between dec_period (Dec {tax_year}) and dec_prev_year (Dec {tax_year - 1})."

    prompt = f"""Classify this financial document and extract the tax year.

First, classify into ONE of these categories:
- dutch_bank_statement: Dutch bank statement (ING, ABN AMRO, Rabobank, etc.)
- us_broker_statement: US brokerage statement (Interactive Brokers, Schwab, etc.)
- crypto_broker_statement: Crypto exchange/broker statement (Coinbase, Binance, Kraken, etc.)
- salary_statement: Salary slip or income statement
- mortgage_statement: Mortgage or property-related document
- unknown: Cannot determine type

Second, extract the tax year from the document. Look for:
- Dates in the document (especially January 1st dates or statement periods)
- Year references (e.g., "2024", "tax year 2024", "fiscal year 2024")
- Statement periods that indicate the tax year

Third, IF the document is a us_broker_statement or crypto_broker_statement, identify the statement subtype:
- jan_period: January period statement (typically shows Dec 31 of previous year and/or Jan 31 of tax year)
- dec_period: December period statement of the TAX YEAR (e.g., Dec 2024 for tax year 2024, shows Dec 31 of the tax year)
- dec_prev_year: December period statement of the PREVIOUS YEAR (e.g., Dec 2023 for tax year 2024, shows Dec 31 of the previous year - this should be used as Jan 1 value)
- full_year: Full year statement (covers the entire tax year, typically shows both Jan 1 and Dec 31 values)
- null: If it's not a broker statement, or if the subtype cannot be determined

IMPORTANT: To distinguish between dec_period and dec_prev_year:
- Look at the dates in the document and compare them to the tax year being processed
- If the document shows Dec 31 of the tax year (e.g., 2024-12-31 for tax year 2024), use dec_period
- If the document shows Dec 31 of the previous year (e.g., 2023-12-31 for tax year 2024), use dec_prev_year
- If the tax year is unclear, check the document dates: if it's clearly from the previous year (e.g., "December 2023" statement when processing tax year 2024), use dec_prev_year
{tax_year_context}

Document text (first 1000 chars):
{doc_text[:1000]}

Respond with FOUR values separated by commas:
1. Category name
2. Confidence (0-1)
3. Tax year (as integer, or "null" if not found/unclear)
4. Statement subtype (jan_period, dec_period, dec_prev_year, full_year, or "null" if not applicable/unclear)

Example: dutch_bank_statement,0.95,2024,null
Example: us_broker_statement,0.90,2024,dec_period
Example: us_broker_statement,0.90,2024,dec_prev_year
Example: crypto_broker_statement,0.85,2024,jan_period
Example if year unclear: us_broker_statement,0.90,null,full_year
"""

    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        response_text = response.content.strip()

        # Parse response
        parts = [p.strip() for p in response_text.split(",")]
        doc_type = parts[0].strip()
        
        # Extract confidence if provided, otherwise default to 0.8
        if len(parts) > 1:
            try:
                confidence = float(parts[1].strip())
                # Clamp confidence to valid range [0, 1]
                confidence = max(0.0, min(1.0, confidence))
            except (ValueError, IndexError):
                logger.warning(
                    f"Could not parse confidence from LLM response: {response_text}. "
                    f"Defaulting to 0.8"
                )
                confidence = 0.8
        else:
            logger.warning(
                f"LLM did not provide confidence score for {doc_id}. "
                f"Response: {response_text}. Defaulting to 0.8"
            )
            confidence = 0.8

        # Extract tax year if provided
        tax_year = None
        if len(parts) > 2:
            tax_year_str = parts[2].strip().lower()
            if tax_year_str != "null" and tax_year_str != "none":
                try:
                    tax_year = int(tax_year_str)
                    # Validate reasonable tax year range (2000-2100)
                    if tax_year < 2000 or tax_year > 2100:
                        logger.warning(
                            f"Tax year {tax_year} seems unreasonable for {doc_id}, "
                            f"setting to None"
                        )
                        tax_year = None
                except (ValueError, TypeError):
                    logger.warning(
                        f"Could not parse tax year from LLM response: {tax_year_str}. "
                        f"Response: {response_text}"
                    )
                    tax_year = None

        # Extract statement subtype if provided (only relevant for broker statements)
        statement_subtype = None
        if len(parts) > 3:
            subtype_str = parts[3].strip().lower()
            if subtype_str not in ["null", "none", ""]:
                if subtype_str in ["jan_period", "dec_period", "dec_prev_year", "full_year"]:
                    # Only set subtype for broker statements
                    if doc_type in ["us_broker_statement", "crypto_broker_statement"]:
                        statement_subtype = subtype_str  # type: ignore
                    else:
                        logger.debug(
                            f"Subtype {subtype_str} provided for non-broker document {doc_id}, ignoring"
                        )
                else:
                    logger.warning(
                        f"Unknown statement subtype '{subtype_str}' for {doc_id}. "
                        f"Expected: jan_period, dec_period, dec_prev_year, full_year, or null"
                    )

        logger.info(
            f"Classified doc {doc_id} as {doc_type} "
            f"(confidence: {confidence}, tax_year: {tax_year}, subtype: {statement_subtype})"
        )

        return DocumentClassification(
            doc_id=doc_id,
            doc_type=doc_type,  # type: ignore
            confidence=confidence,
            reasoning="Classified based on document content analysis",
            tax_year=tax_year,
            statement_subtype=statement_subtype,
        )

    except Exception as e:
        logger.error(f"Failed to classify document {doc_id}: {e}")
        return DocumentClassification(
            doc_id=doc_id,
            doc_type="unknown",
            confidence=0.0,
            reasoning=f"Classification failed: {e}",
            tax_year=None,
        )


def dispatcher_node(state: TaxGraphState) -> Command:
    """Dispatcher node: Classifies documents and routes to parser agents.
    
    Checks both document type and tax year. Documents with mismatched tax years
    are quarantined instead of being routed to parsers.
    
    Uses Command to both update state and perform parallel routing via Send objects.
    
    Args:
        state: Current graph state with documents
        
    Returns:
        Command with state updates and Send objects for parallel routing
    """
    logger.info(
        f"Dispatching {len(state.documents)} documents for tax year {state.tax_year}"
    )

    if not state.documents:
        logger.warning("No documents to dispatch. Check if PII scrubbing succeeded.")
        # Return Command with just state update, no routing (will end)
        return Command(
            update={"status": "no_documents"}
        )

    classified_docs = []
    quarantined_docs = []
    sends = []

    for doc in state.documents:
        # Classify the document (includes type and tax year extraction)
        # Pass tax_year to help distinguish between dec_period and dec_prev_year
        classification = classify_document(doc.scrubbed_text, doc.doc_id, tax_year=state.tax_year)

        # Check if tax year matches
        tax_year_mismatch = False
        if classification.tax_year is not None:
            if classification.tax_year != state.tax_year:
                tax_year_mismatch = True
                logger.warning(
                    f"Tax year mismatch for doc {doc.doc_id} ({doc.filename}): "
                    f"document year={classification.tax_year}, "
                    f"calculation year={state.tax_year}. Quarantining."
                )
        else:
            # If tax year couldn't be extracted, log a warning but don't quarantine
            # (we allow processing if year is unclear, but user should verify)
            logger.warning(
                f"Could not extract tax year from doc {doc.doc_id} ({doc.filename}). "
                f"Proceeding with processing, but user should verify."
            )

        # If tax year doesn't match, quarantine the document
        if tax_year_mismatch:
            quarantined_docs.append({
                "doc_id": doc.doc_id,
                "filename": doc.filename,
                "reason": f"Tax year mismatch: document year={classification.tax_year}, "
                         f"calculation year={state.tax_year}",
                "classification": classification.model_dump(),
            })
            continue

        # Route to appropriate parser based on classification
        if classification.doc_type == "dutch_bank_statement":
            target_node = "dutch_parser"
        elif classification.doc_type == "us_broker_statement":
            target_node = "us_broker_parser"
        elif classification.doc_type == "crypto_broker_statement":
            # Crypto brokers also have cash (fiat) and crypto holdings, similar to US brokers
            target_node = "us_broker_parser"
        elif classification.doc_type == "salary_statement":
            target_node = "salary_parser"
        elif classification.doc_type == "mortgage_statement":
            target_node = "dutch_parser"  # Handle with Dutch parser
        else:
            # Unknown documents skip parsing
            logger.warning(f"Unknown document type for {doc.doc_id}, skipping")
            continue

        # Store classification info
        classified_docs.append({
            "doc_id": doc.doc_id,
            "doc_text": doc.scrubbed_text,
            "filename": doc.filename,
            "target_node": target_node,
            "classification": classification.model_dump(),
        })

        # Create Send object for parallel routing
        sends.append(
            Send(
                target_node,
                {
                    "doc_id": doc.doc_id,
                    "doc_text": doc.scrubbed_text,
                    "filename": doc.filename,
                    "classification": classification.model_dump(),
                },
            )
        )

        logger.info(f"Routing doc {doc.doc_id} to {target_node}")

    # Determine status based on whether any documents were quarantined
    if quarantined_docs:
        logger.warning(
            f"Quarantined {len(quarantined_docs)} document(s) due to tax year mismatch"
        )
        status = "quarantine" if not sends else "extracting"
    else:
        status = "extracting"

    logger.info(
        f"Created {len(sends)} Send objects for parallel processing, "
        f"quarantined {len(quarantined_docs)} document(s)"
    )

    # Use Command to update state and route to multiple nodes in parallel
    # If all documents were quarantined, end the graph
    goto_value = sends if sends else END
    
    return Command(
        update={
            "classified_documents": classified_docs,
            "quarantined_documents": quarantined_docs,
            "status": status,
            "requires_human_review": len(quarantined_docs) > 0,
        },
        goto=goto_value,
    )


