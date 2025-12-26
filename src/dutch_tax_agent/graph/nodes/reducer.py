"""Reducer node: Aggregates results from all parser agents."""

import logging

from dutch_tax_agent.schemas.state import TaxGraphState

logger = logging.getLogger(__name__)


def reducer_node(state: TaxGraphState) -> dict:
    """Reducer node: Aggregates validated Box 1 and Box 3 items.
    
    This implements the REDUCE step of Map-Reduce pattern.
    After reduction, always proceeds to HITL control node for human decision.
    
    Args:
        state: Current graph state with extraction results
        
    Returns:
        Dict with state updates (routing handled by graph edges)
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

    # Calculate Box 3 totals (exclude mortgages and debts - they're liabilities, not assets)
    box3_total = sum(
        item.value_eur_jan1 for item in state.box3_asset_items
        if item.asset_type not in ["mortgage", "debt"]
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

    # Determine next status (but don't route - that's done by HITL control)
    if validation_errors:
        next_status = "quarantine"
        requires_review = True
        logger.warning(
            f"Validation failed with {len(validation_errors)} errors. "
            f"Proceeding to HITL control."
        )
    elif not state.box3_asset_items:
        next_status = "ready_for_calculation"
        requires_review = False
        logger.info("No Box 3 assets. Proceeding to HITL control.")
    else:
        next_status = "ready_for_calculation"
        requires_review = False
        logger.info("Validation passed. Proceeding to HITL control.")

    # Return state updates (routing to hitl_control is handled by graph edge)
    return {
        "box1_total_income": box1_total,
        "box3_total_assets_jan1": box3_total,
        "validation_errors": validation_errors,
        "validation_warnings": validation_warnings,
        "status": next_status,
        "requires_human_review": requires_review,
    }


