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
    
    The validator processes ALL extraction results that haven't been validated yet,
    identified by comparing doc_ids with already-validated results.
    
    Args:
        state: Current graph state with extraction_results from parser agents
        
    Returns:
        dict with validated entities and errors to be added to state.validated_results
    """
    logger.info(f"Validator invoked with {len(state.extraction_results)} extraction results")
    
    if not state.extraction_results:
        logger.warning("No extraction results to validate")
        return {"validated_results": []}
    
    # Get set of already-validated doc_ids to avoid duplicate processing
    validated_doc_ids = {
        result.get("doc_id") for result in state.validated_results
        if result.get("doc_id")
    }
    
    # Find extraction results that haven't been validated yet
    unvalidated_results = [
        result for result in state.extraction_results
        if result.doc_id not in validated_doc_ids
    ]
    
    if not unvalidated_results:
        logger.info("All extraction results have already been validated")
        return {"validated_results": []}
    
    logger.info(f"Processing {len(unvalidated_results)} unvalidated extraction results")
    
    validator = DataValidator()
    converter = CurrencyConverter()
    
    validated_results = []
    
    # Process each unvalidated extraction result
    for extraction_result in unvalidated_results:
        doc_id = extraction_result.doc_id
        source_filename = extraction_result.source_filename
        
        logger.info(f"Validating extraction result from {source_filename} (doc_id: {doc_id})")
        
        validated_box1_items = []
        validated_box3_items = []
        validation_errors = []
        
        # Extract the structured data
        extracted_data = extraction_result.extracted_data
        logger.debug(f"Extracted data for doc_id {doc_id}: {extracted_data}")
        
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
            f"Validation complete for {doc_id}: {len(validated_box1_items)} Box1 items, "
            f"{len(validated_box3_items)} Box3 assets, "
            f"{len(validation_errors)} errors"
        )
        
        # Create validated result for this extraction
        result = {
            "doc_id": doc_id,
            "validated_box1_items": [item.model_dump() for item in validated_box1_items],
            "validated_box3_items": [asset.model_dump() for asset in validated_box3_items],
            "validation_errors": validation_errors,
        }
        validated_results.append(result)
    
    total_box1 = sum(len(r["validated_box1_items"]) for r in validated_results)
    total_box3 = sum(len(r["validated_box3_items"]) for r in validated_results)
    total_errors = sum(len(r["validation_errors"]) for r in validated_results)
    
    logger.info(
        f"Total validation summary: {total_box1} Box1 items, "
        f"{total_box3} Box3 assets, {total_errors} errors across "
        f"{len(validated_results)} documents"
    )
    
    return {
        "validated_results": validated_results,  # Will be accumulated via list concatenation
    }


