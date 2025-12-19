"""Validator node: Validates and normalizes extracted data."""

import logging
from datetime import date

from pydantic import ValidationError as PydanticValidationError

from dutch_tax_agent.schemas.state import TaxGraphState
from dutch_tax_agent.tools.currency import CurrencyConverter
from dutch_tax_agent.tools.validators import DataValidator, ValidationError

logger = logging.getLogger(__name__)


def validator_node(state: TaxGraphState) -> dict:
    """Validator node: Validates extraction results and normalizes currency.
    
    This node runs AFTER each parser agent and BEFORE the aggregator.
    It ensures data quality and performs deterministic currency conversion.
    
    In the map-reduce pattern, this node is invoked once per parser completion,
    receiving the full state with the latest extraction_results accumulated.
    
    Args:
        state: Current graph state with extraction_results from parser agents
        
    Returns:
        dict with validated entities and errors to be added to state.validated_results
    """
    logger.info(f"Validator invoked with {len(state.extraction_results)} extraction results")
    
    # Process only the most recently added extraction result(s)
    # Since parsers run in parallel and each adds one result, we validate the latest one
    if not state.extraction_results:
        logger.warning("No extraction results to validate")
        return {"validated_results": []}
    
    # Get the last extraction result (most recently added by a parser)
    extraction_result = state.extraction_results[-1]
    
    doc_id = extraction_result.doc_id
    source_filename = extraction_result.source_filename

    logger.info(f"Validating extraction result from {source_filename}")

    validator = DataValidator()
    converter = CurrencyConverter()

    validated_box1_items = []
    validated_box3_items = []
    validation_errors = []

    # Extract the structured data
    extracted_data = extraction_result.extracted_data
    logger.info(f"Extracted doc_id {doc_id}")
    logger.debug(f"Extracted data: {extracted_data}")

    # Validate Box 1 income items
    for item_data in extracted_data.get("box1_items", []):
        try:
            # Convert currency if needed
            if item_data.get("original_currency", "EUR") != "EUR":
                original_amount = item_data.get("original_amount", 0)
                item_data["gross_amount_eur"] = converter.convert(
                    original_amount,
                    item_data["original_currency"],
                    "EUR",
                    date(2024, 1, 1),  # Use Jan 1 as reference date
                )

            # Validate and construct Box1Income
            box1_item = validator.validate_box1_income(
                item_data, doc_id, source_filename
            )
            validated_box1_items.append(box1_item)
            logger.debug(
                f"Validated Box1 item: €{box1_item.gross_amount_eur:,.2f}"
            )

        except (ValidationError, PydanticValidationError) as e:
            error_msg = f"Box1 validation error in {source_filename}: {e}"
            validation_errors.append(error_msg)
            logger.error(error_msg)

    # Validate Box 3 asset items
    for asset_data in extracted_data.get("box3_items", []):
        try:
            # Convert currency if needed
            if asset_data.get("original_currency", "EUR") != "EUR":
                original_value = asset_data.get("original_value", 0)
                conversion_rate = converter.get_rate(
                    asset_data["original_currency"],
                    "EUR",
                    date(2024, 1, 1),
                )
                asset_data["value_eur_jan1"] = original_value * conversion_rate
                asset_data["conversion_rate"] = conversion_rate

            # Validate and construct Box3Asset
            box3_asset = validator.validate_box3_asset(
                asset_data, doc_id, source_filename
            )
            validated_box3_items.append(box3_asset)
            logger.debug(
                f"Validated Box3 asset: €{box3_asset.value_eur_jan1:,.2f}"
            )

        except (ValidationError, PydanticValidationError) as e:
            error_msg = f"Box3 validation error in {source_filename}: {e}"
            validation_errors.append(error_msg)
            logger.error(error_msg)

    logger.info(
        f"Validation complete: {len(validated_box1_items)} Box1 items, "
        f"{len(validated_box3_items)} Box3 assets, "
        f"{len(validation_errors)} errors"
    )

    # Return validated results to be accumulated in state.validated_results
    result = {
        "doc_id": doc_id,
        "validated_box1_items": [item.model_dump() for item in validated_box1_items],
        "validated_box3_items": [asset.model_dump() for asset in validated_box3_items],
        "validation_errors": validation_errors,
    }
    
    return {
        "validated_results": [result],  # Will be accumulated via list concatenation
    }


