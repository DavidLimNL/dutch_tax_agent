"""Dispatcher node: Routes documents to specialized parser agents."""

import logging

from langchain_core.messages import HumanMessage
from langgraph.types import Command, Send

from dutch_tax_agent.llm_factory import create_llm
from dutch_tax_agent.schemas.documents import DocumentClassification
from dutch_tax_agent.schemas.state import TaxGraphState

logger = logging.getLogger(__name__)


def classify_document(doc_text: str, doc_id: str) -> DocumentClassification:
    """Classify a document to determine which parser agent to use.
    
    Args:
        doc_text: Scrubbed document text
        doc_id: Document ID
        
    Returns:
        DocumentClassification with type and confidence
    """
    llm = create_llm(temperature=0)

    prompt = f"""Classify this financial document into ONE of these categories:
- dutch_bank_statement: Dutch bank statement (ING, ABN AMRO, Rabobank, etc.)
- us_broker_statement: US brokerage statement (Interactive Brokers, Schwab, etc.)
- crypto_broker_statement: Crypto exchange/broker statement (Coinbase, Binance, Kraken, etc.)
- salary_statement: Salary slip or income statement
- mortgage_statement: Mortgage or property-related document
- unknown: Cannot determine type

Document text (first 500 chars):
{doc_text[:500]}

Respond with ONLY the category name and your confidence (0-1), separated by a comma.
Example: dutch_bank_statement,0.95
"""

    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        response_text = response.content.strip()

        # Parse response
        parts = response_text.split(",")
        doc_type = parts[0].strip()
        
        # Extract confidence if provided, otherwise default to 0.8
        # 0.8 is a moderate confidence level - high enough to proceed with routing,
        # but low enough to indicate uncertainty when LLM doesn't provide explicit confidence
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

        logger.info(f"Classified doc {doc_id} as {doc_type} (confidence: {confidence})")

        return DocumentClassification(
            doc_id=doc_id,
            doc_type=doc_type,  # type: ignore
            confidence=confidence,
            reasoning="Classified based on document content analysis",
        )

    except Exception as e:
        logger.error(f"Failed to classify document {doc_id}: {e}")
        return DocumentClassification(
            doc_id=doc_id,
            doc_type="unknown",
            confidence=0.0,
            reasoning=f"Classification failed: {e}",
        )


def dispatcher_node(state: TaxGraphState) -> Command:
    """Dispatcher node: Classifies documents and routes to parser agents.
    
    Uses Command to both update state and perform parallel routing via Send objects.
    
    Args:
        state: Current graph state with documents
        
    Returns:
        Command with state updates and Send objects for parallel routing
    """
    logger.info(f"Dispatching {len(state.documents)} documents")

    if not state.documents:
        logger.warning("No documents to dispatch. Check if PII scrubbing succeeded.")
        # Return Command with just state update, no routing (will end)
        return Command(
            update={"status": "no_documents"}
        )

    classified_docs = []
    sends = []

    for doc in state.documents:
        # Classify the document
        classification = classify_document(doc.scrubbed_text, doc.doc_id)

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

    logger.info(f"Created {len(sends)} Send objects for parallel processing")

    # Use Command to update state and route to multiple nodes in parallel
    return Command(
        update={
            "classified_documents": classified_docs,
            "status": "extracting",
        },
        goto=sends,
    )


