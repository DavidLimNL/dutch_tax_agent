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

    return {
        "box1_income_items": all_box1_items,
        "box3_asset_items": all_box3_items,
        "validation_errors": list(state.validation_errors) + all_errors,
        "status": "validating",
    }

