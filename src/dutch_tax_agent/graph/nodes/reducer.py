"""Reducer node: Aggregates results from all parser agents."""

import logging

from langgraph.graph import END
from langgraph.types import Command

from dutch_tax_agent.schemas.state import TaxGraphState

logger = logging.getLogger(__name__)


def reducer_node(state: TaxGraphState) -> Command:
    """Reducer node: Aggregates validated Box 1 and Box 3 items.
    
    This implements the REDUCE step of Map-Reduce pattern.
    Uses Command to both update state and determine routing.
    
    Args:
        state: Current graph state with extraction results
        
    Returns:
        Command with state updates and routing decision
    """
    logger.info(f"Reducing {len(state.extraction_results)} extraction results")

    # Count successful extractions
    successful = [r for r in state.extraction_results if r.status == "success"]
    errors = [r for r in state.extraction_results if r.status == "error"]

    logger.info(
        f"Extraction summary: {len(successful)} successful, {len(errors)} failed"
    )

    # Calculate Box 1 totals
    box1_total = sum(
        item.gross_amount_eur for item in state.box1_income_items
    )

    # Calculate Box 3 totals
    box3_total = sum(
        item.value_eur_jan1 for item in state.box3_asset_items
    )

    logger.info(
        f"Aggregated totals: Box 1 = €{box1_total:,.2f}, "
        f"Box 3 = €{box3_total:,.2f}"
    )

    # Validate data completeness
    # Start with existing validation errors/warnings from validator
    validation_errors = list(state.validation_errors)
    validation_warnings = list(state.validation_warnings)

    # Check for critical missing data
    if not state.box1_income_items and not state.box3_asset_items:
        validation_errors.append(
            "No financial data extracted from any documents"
        )

    # Check for low confidence extractions
    low_confidence_items = [
        item for item in state.box1_income_items
        if item.extraction_confidence < 0.7
    ]
    if low_confidence_items:
        validation_warnings.append(
            f"{len(low_confidence_items)} Box 1 items have low confidence scores"
        )

    low_confidence_assets = [
        asset for asset in state.box3_asset_items
        if asset.extraction_confidence < 0.7
    ]
    if low_confidence_assets:
        validation_warnings.append(
            f"{len(low_confidence_assets)} Box 3 assets have low confidence scores"
        )

    # Determine next status and routing
    if validation_errors:
        next_status = "quarantine"
        requires_review = True
        next_node = END
        logger.warning(
            f"Validation failed with {len(validation_errors)} errors. "
            f"Sending to quarantine."
        )
    elif not state.box3_asset_items:
        next_status = "complete"
        requires_review = False
        next_node = END
        logger.info("No Box 3 assets, completing without Box 3 calculation.")
    else:
        next_status = "ready_for_calculation"
        requires_review = False
        next_node = "start_box3"
        logger.info("Validation passed. Ready for Box 3 calculation.")

    # Use Command to update state and route to next node
    return Command(
        update={
            "box1_total_income": box1_total,
            "box3_total_assets_jan1": box3_total,
            "validation_errors": validation_errors,
            "validation_warnings": validation_warnings,
            "status": next_status,
            "requires_human_review": requires_review,
        },
        goto=next_node,
    )


