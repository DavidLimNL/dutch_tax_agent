"""Aggregation and orchestration nodes for the main graph."""

import logging

from dutch_tax_agent.schemas.state import TaxGraphState
from dutch_tax_agent.schemas.tax_entities import Box1Income, Box3Asset

logger = logging.getLogger(__name__)


def aggregate_extraction_node(state: TaxGraphState) -> dict:
    """Aggregate validated results into the state.
    
    This node collects all the validated Box1/Box3 items from parallel parser agents.
    The validated results are accumulated in state.validated_results by the validator nodes.
    
    Args:
        state: Current graph state with validated_results from validators
        
    Returns:
        Updated state dict
    """
    # Get validated results from state (accumulated from parallel validator executions)
    validated_results = state.validated_results
    
    logger.info(f"Aggregating {len(validated_results)} validated results")

    all_box1_items = []
    all_box3_items = []
    all_errors = []

    for result in validated_results:
        # Parse Box1 items
        for item_dict in result.get("validated_box1_items", []):
            all_box1_items.append(Box1Income(**item_dict))

        # Parse Box3 items
        for item_dict in result.get("validated_box3_items", []):
            all_box3_items.append(Box3Asset(**item_dict))

        # Collect errors
        all_errors.extend(result.get("validation_errors", []))

    logger.info(
        f"Aggregated: {len(all_box1_items)} Box1 items, "
        f"{len(all_box3_items)} Box3 items, "
        f"{len(all_errors)} errors"
    )

    # Clear document text after aggregation to reduce token usage and memory
    # The full document text is no longer needed since we have structured extraction results
    # Note: Parser agents received data via Send objects, not from state, so we can safely clear:
    # - documents: Full scrubbed document text
    # - classified_documents: Contains doc_text that was only needed for routing
    doc_count = len(state.documents)
    doc_chars = sum(len(doc.scrubbed_text) for doc in state.documents)
    classified_count = len(state.classified_documents)
    classified_chars = sum(
        len(doc.get("doc_text", "")) for doc in state.classified_documents
    )
    
    if doc_count > 0 or classified_count > 0:
        total_chars = doc_chars + classified_chars
        logger.info(
            f"Clearing {doc_count} documents and {classified_count} classified entries "
            f"({total_chars:,} characters) from state after successful extraction. "
            f"Structured data retained."
        )

    return {
        "box1_income_items": all_box1_items,
        "box3_asset_items": all_box3_items,
        "validation_errors": list(state.validation_errors) + all_errors,
        "status": "validating",
        "documents": [],  # Clear to save memory and tokens
        "classified_documents": [],  # Clear classified_documents.doc_text as well
    }

