"""Validator node: Validates and normalizes extracted data."""

import logging
from datetime import date, datetime

from pydantic import ValidationError as PydanticValidationError

from dutch_tax_agent.schemas.state import TaxGraphState
from dutch_tax_agent.tools.currency import CurrencyConverter, parse_currency_string
from dutch_tax_agent.tools.date_utils import check_document_has_required_dates
from dutch_tax_agent.tools.data_validator import DataValidator, ValidationError

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
        validation_warnings = []
        
        # Extract the structured data
        extracted_data = extraction_result.extracted_data
        logger.debug(f"Extracted data for doc_id {doc_id}: {extracted_data}")
        
        # Check if this is a broker statement by looking at classified_documents
        is_broker_statement = False
        for classified_doc in state.classified_documents:
            if classified_doc.get("doc_id") == doc_id:
                doc_type = classified_doc.get("classification", {}).get("doc_type", "")
                if doc_type in ["us_broker_statement", "crypto_broker_statement"]:
                    is_broker_statement = True
                break
        
        # Fallback: check filename for broker-related keywords
        if not is_broker_statement:
            is_broker_statement = (
                "broker" in source_filename.lower() or
                "ibkr" in source_filename.lower() or
                "schwab" in source_filename.lower() or
                "fidelity" in source_filename.lower() or
                "crypto" in source_filename.lower() or
                "exchange" in source_filename.lower()
            )
        
        # Validate Box 1 income items
        for item_data in extracted_data.get("box1_items", []):
            try:
                # Parse original_amount if present (may come as string from LLM)
                original_amount = item_data.get("original_amount")
                if original_amount is not None:
                    if isinstance(original_amount, str):
                        original_amount = parse_currency_string(original_amount)
                    else:
                        original_amount = float(original_amount)
                    item_data["original_amount"] = original_amount
                
                # Convert currency if needed
                if item_data.get("original_currency", "EUR") != "EUR":
                    # Use parsed original_amount or default to 0
                    amount_to_convert = original_amount if original_amount is not None else item_data.get("gross_amount_eur", 0)
                    # Ensure amount is a float
                    if isinstance(amount_to_convert, str):
                        amount_to_convert = parse_currency_string(amount_to_convert)
                    else:
                        amount_to_convert = float(amount_to_convert)
                    item_data["gross_amount_eur"] = converter.convert(
                        amount_to_convert,
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
        
        # Check document date range and validate it has Jan 1 or Dec 31
        doc_date_range = extracted_data.get("document_date_range", {})
        doc_start = doc_date_range.get("start_date")
        doc_end = doc_date_range.get("end_date")
        
        # Parse dates if they're strings
        parsed_start = None
        parsed_end = None
        if doc_start:
            if isinstance(doc_start, str):
                try:
                    parsed_start = datetime.fromisoformat(doc_start).date()
                except (ValueError, AttributeError):
                    pass
            elif isinstance(doc_start, date):
                parsed_start = doc_start
        if doc_end:
            if isinstance(doc_end, str):
                try:
                    parsed_end = datetime.fromisoformat(doc_end).date()
                except (ValueError, AttributeError):
                    pass
            elif isinstance(doc_end, date):
                parsed_end = doc_end
        
        doc_range_tuple = (parsed_start, parsed_end) if parsed_start or parsed_end else None
        
        # Check if document has required dates
        has_jan1, has_dec31, date_warning = check_document_has_required_dates(
            doc_range_tuple, state.tax_year
        )
        
        # Check if any box3 items have jan1 or dec31 values
        # Only perform this check if there are actually box3_items in the document
        box3_items = extracted_data.get("box3_items", [])
        if box3_items:
            has_jan1_value = False
            has_dec31_value = False
            for asset_data in box3_items:
                if asset_data.get("value_eur_jan1") is not None:
                    has_jan1_value = True
                if asset_data.get("value_eur_dec31") is not None:
                    has_dec31_value = True
            
            # If document has box3 items but doesn't have either Jan 1 or Dec 31 values, quarantine it
            if not has_jan1_value and not has_dec31_value:
                quarantine_reason = (
                    f"Document {source_filename} does not contain values for "
                    f"January 1st or December 31st of tax year {state.tax_year}. "
                    f"Document date range: {doc_start} to {doc_end}"
                )
                validation_errors.append(quarantine_reason)
                logger.warning(quarantine_reason)
            elif date_warning:
                validation_warnings.append(f"Date warning for {source_filename}: {date_warning}")
            
            # For broker statements: Check if both cash and investment accounts are present
            # Broker statements should always have both (even if one is 0)
            # If box3_items is empty, it means the parser couldn't extract either account
            # Check if this looks like a broker statement by checking if we have any items
            # and if they have descriptions that suggest broker accounts
            # Also check if we have both savings and investment types
            has_cash = any(item.get("asset_type") in ["savings", "checking"] for item in box3_items)
            has_investment = any(
                item.get("asset_type") in ["stocks", "bonds", "crypto", "other"]
                for item in box3_items
            )
            
            # If this is a broker statement but we don't have both accounts, quarantine
            # Note: Post-processing in the parser should have added missing accounts with 0,
            # so if both are still missing, it means the parser couldn't extract either account
            if is_broker_statement and not (has_cash and has_investment):
                quarantine_reason = (
                    f"Broker statement {source_filename} is missing both cash and investment account values. "
                    f"At least one account type must be extractable. Found: cash={'yes' if has_cash else 'no'}, "
                    f"investment={'yes' if has_investment else 'no'}"
                )
                validation_errors.append(quarantine_reason)
                logger.warning(quarantine_reason)
        elif date_warning:
            # Only log date warnings if there are no box3 items (for box1-only documents)
            validation_warnings.append(f"Date warning for {source_filename}: {date_warning}")
        
        # Additional check: If box3_items is empty, check if this is a broker statement
        # If it is, quarantine it (broker statements should always have at least one account)
        if not box3_items and is_broker_statement:
            quarantine_reason = (
                f"Broker statement {source_filename} could not extract either cash or investment account values. "
                f"At least one account type must be extractable to process this document."
            )
            validation_errors.append(quarantine_reason)
            logger.warning(quarantine_reason)
        
        # Determine if this is a dec_period statement (December statement of tax year)
        # by checking if document end date is around Dec 31 of tax year
        is_dec_period = False
        if parsed_end:
            tax_year_dec31 = date(state.tax_year, 12, 31)
            days_from_dec31 = abs((parsed_end - tax_year_dec31).days)
            if days_from_dec31 <= 3:
                is_dec_period = True
        # Also check if all box3 items have null jan1 values (another indicator of dec_period)
        if not is_dec_period:
            all_jan1_null = all(
                item.get("value_eur_jan1") is None 
                for item in extracted_data.get("box3_items", [])
            )
            if all_jan1_null and extracted_data.get("box3_items"):
                is_dec_period = True
        
        # Validate Box 3 asset items
        for asset_data in extracted_data.get("box3_items", []):
            try:
                # Check for individual positions and sum them if present
                individual_positions = asset_data.get("individual_positions")
                if individual_positions and isinstance(individual_positions, list) and len(individual_positions) > 0:
                    logger.info(
                        f"Processing {len(individual_positions)} individual positions for "
                        f"{asset_data.get('asset_type', 'unknown')} account in {source_filename}"
                    )
                    
                    # Group positions by date and sum values
                    jan1_positions = []
                    dec31_positions = []
                    other_positions = []
                    
                    for pos in individual_positions:
                        if not isinstance(pos, dict):
                            logger.warning(
                                f"Skipping invalid position in {source_filename}: {pos}"
                            )
                            continue
                        
                        pos_date_str = pos.get("date")
                        pos_quantity = pos.get("quantity")
                        pos_price = pos.get("price")
                        pos_currency = pos.get("currency", asset_data.get("original_currency", "USD"))
                        
                        # Calculate value from quantity × price
                        if pos_quantity is None or pos_price is None:
                            logger.warning(
                                f"Position {pos.get('symbol', 'unknown')} missing quantity or price in {source_filename}. "
                                f"quantity={pos_quantity}, price={pos_price}"
                            )
                            continue
                        
                        # Parse quantity and price
                        if isinstance(pos_quantity, str):
                            pos_quantity = parse_currency_string(pos_quantity)
                        else:
                            pos_quantity = float(pos_quantity)
                        
                        if isinstance(pos_price, str):
                            pos_price = parse_currency_string(pos_price)
                        else:
                            pos_price = float(pos_price)
                        
                        # Calculate position value: quantity × price
                        pos_value = pos_quantity * pos_price
                        
                        logger.debug(
                            f"Calculated position value for {pos.get('symbol', 'unknown')}: "
                            f"{pos_quantity} shares × {pos_price} {pos_currency} = {pos_value} {pos_currency}"
                        )
                        
                        # Determine which date bucket this position belongs to
                        if pos_date_str:
                            try:
                                pos_date = datetime.fromisoformat(pos_date_str).date()
                                tax_year_jan1 = date(state.tax_year, 1, 1)
                                tax_year_dec31 = date(state.tax_year, 12, 31)
                                
                                # Check if date is close to Jan 1 (within 3 days)
                                days_from_jan1 = abs((pos_date - tax_year_jan1).days)
                                days_from_dec31 = abs((pos_date - tax_year_dec31).days)
                                
                                if days_from_jan1 <= 3:
                                    jan1_positions.append((pos_value, pos_currency, pos.get("symbol")))
                                elif days_from_dec31 <= 3:
                                    dec31_positions.append((pos_value, pos_currency, pos.get("symbol")))
                                elif is_dec_period and parsed_end:
                                    # For dec_period statements, also check if position date is close to document end date
                                    days_from_doc_end = abs((pos_date - parsed_end).days)
                                    if days_from_doc_end <= 3:
                                        dec31_positions.append((pos_value, pos_currency, pos.get("symbol")))
                                        logger.debug(
                                            f"Position {pos.get('symbol', 'unknown')} with date {pos_date} "
                                            f"included in Dec 31 bucket (close to document end date {parsed_end})"
                                        )
                                    else:
                                        other_positions.append((pos_value, pos_currency, pos.get("symbol"), pos_date))
                                else:
                                    other_positions.append((pos_value, pos_currency, pos.get("symbol"), pos_date))
                            except (ValueError, AttributeError) as e:
                                logger.warning(
                                    f"Could not parse date '{pos_date_str}' for position "
                                    f"{pos.get('symbol', 'unknown')} in {source_filename}: {e}"
                                )
                                # For dec_period statements, default to Dec 31; otherwise default to Jan 1
                                if is_dec_period:
                                    dec31_positions.append((pos_value, pos_currency, pos.get("symbol")))
                                    logger.debug(
                                        f"Position {pos.get('symbol', 'unknown')} with unparseable date defaulted to Dec 31 "
                                        f"(dec_period statement)"
                                    )
                                else:
                                    jan1_positions.append((pos_value, pos_currency, pos.get("symbol")))
                                    logger.debug(
                                        f"Position {pos.get('symbol', 'unknown')} with unparseable date defaulted to Jan 1"
                                    )
                        else:
                            # No date specified: for dec_period statements, default to Dec 31; otherwise default to Jan 1
                            if is_dec_period:
                                dec31_positions.append((pos_value, pos_currency, pos.get("symbol")))
                                logger.debug(
                                    f"Position {pos.get('symbol', 'unknown')} missing date in {source_filename}, "
                                    f"defaulting to Dec 31 (dec_period statement)"
                                )
                            else:
                                jan1_positions.append((pos_value, pos_currency, pos.get("symbol")))
                                logger.debug(
                                    f"Position {pos.get('symbol', 'unknown')} missing date in {source_filename}, "
                                    f"defaulting to Jan 1"
                                )
                    
                    # Sum Jan 1 positions (convert to same currency first)
                    if jan1_positions:
                        jan1_sum = 0.0
                        base_currency = asset_data.get("original_currency", "USD")
                        for pos_value, pos_currency, symbol in jan1_positions:
                            if pos_currency != base_currency:
                                # Convert to base currency using Jan 1 exchange rate
                                converted_value = converter.convert(
                                    pos_value,
                                    pos_currency,
                                    base_currency,
                                    date(state.tax_year, 1, 1),
                                )
                                jan1_sum += converted_value
                                logger.debug(
                                    f"Converted {symbol} {pos_value} {pos_currency} to {converted_value} {base_currency} "
                                    f"for Jan 1 sum"
                                )
                            else:
                                jan1_sum += pos_value
                        
                        # If jan1_value was not set or is null, use the sum
                        if asset_data.get("value_eur_jan1") is None:
                            asset_data["value_eur_jan1"] = jan1_sum
                            logger.info(
                                f"Summed {len(jan1_positions)} individual positions for Jan 1: "
                                f"{base_currency} {jan1_sum:,.2f} in {source_filename}"
                            )
                        else:
                            # Both individual positions and combined total exist - verify they match
                            existing_jan1 = asset_data.get("value_eur_jan1")
                            if isinstance(existing_jan1, str):
                                existing_jan1 = parse_currency_string(existing_jan1)
                            else:
                                existing_jan1 = float(existing_jan1)
                            
                            # Allow small discrepancy (1% or $10, whichever is larger) due to rounding
                            discrepancy = abs(existing_jan1 - jan1_sum)
                            threshold = max(existing_jan1 * 0.01, 10.0)
                            
                            # Prioritize sum value over combined total
                            asset_data["value_eur_jan1"] = jan1_sum
                            
                            if discrepancy > threshold:
                                warning_msg = (
                                    f"Jan 1 value mismatch in {source_filename}: "
                                    f"combined total={existing_jan1:,.2f}, "
                                    f"sum of individual positions={jan1_sum:,.2f}, "
                                    f"difference={discrepancy:,.2f}. Using sum of individual positions."
                                )
                                validation_warnings.append(warning_msg)
                                logger.warning(warning_msg)
                            else:
                                logger.info(
                                    f"Jan 1 values match: combined={existing_jan1:,.2f}, "
                                    f"sum={jan1_sum:,.2f} in {source_filename}. Using sum of individual positions."
                                )
                    
                    # Sum Dec 31 positions (convert to same currency first)
                    if dec31_positions:
                        dec31_sum = 0.0
                        base_currency = asset_data.get("original_currency", "USD")
                        for pos_value, pos_currency, symbol in dec31_positions:
                            if pos_currency != base_currency:
                                # Convert to base currency using Dec 31 exchange rate
                                converted_value = converter.convert(
                                    pos_value,
                                    pos_currency,
                                    base_currency,
                                    date(state.tax_year, 12, 31),
                                )
                                dec31_sum += converted_value
                                logger.debug(
                                    f"Converted {symbol} {pos_value} {pos_currency} to {converted_value} {base_currency} "
                                    f"for Dec 31 sum"
                                )
                            else:
                                dec31_sum += pos_value
                        
                        # If dec31_value was not set or is null, use the sum
                        if asset_data.get("value_eur_dec31") is None:
                            asset_data["value_eur_dec31"] = dec31_sum
                            logger.info(
                                f"Summed {len(dec31_positions)} individual positions for Dec 31: "
                                f"{base_currency} {dec31_sum:,.2f} in {source_filename}"
                            )
                        else:
                            # Both individual positions and combined total exist - verify they match
                            existing_dec31 = asset_data.get("value_eur_dec31")
                            if isinstance(existing_dec31, str):
                                existing_dec31 = parse_currency_string(existing_dec31)
                            else:
                                existing_dec31 = float(existing_dec31)
                            
                            # Allow small discrepancy (1% or $10, whichever is larger) due to rounding
                            discrepancy = abs(existing_dec31 - dec31_sum)
                            threshold = max(existing_dec31 * 0.01, 10.0)
                            
                            # Prioritize sum value over combined total
                            asset_data["value_eur_dec31"] = dec31_sum
                            
                            if discrepancy > threshold:
                                warning_msg = (
                                    f"Dec 31 value mismatch in {source_filename}: "
                                    f"combined total={existing_dec31:,.2f}, "
                                    f"sum of individual positions={dec31_sum:,.2f}, "
                                    f"difference={discrepancy:,.2f}. Using sum of individual positions."
                                )
                                validation_warnings.append(warning_msg)
                                logger.warning(warning_msg)
                            else:
                                logger.info(
                                    f"Dec 31 values match: combined={existing_dec31:,.2f}, "
                                    f"sum={dec31_sum:,.2f} in {source_filename}. Using sum of individual positions."
                                )
                    
                    # Log positions that don't match Jan 1 or Dec 31
                    if other_positions:
                        logger.warning(
                            f"Found {len(other_positions)} positions with dates not matching Jan 1 or Dec 31 "
                            f"in {source_filename}. These positions were not included in the sum."
                        )
                
                # Convert currency if needed for Jan 1 value
                jan1_value = asset_data.get("value_eur_jan1")
                dec31_value = asset_data.get("value_eur_dec31")
                
                # Ensure values are floats (may come as strings from JSON)
                if jan1_value is not None:
                    if isinstance(jan1_value, str):
                        jan1_value = parse_currency_string(jan1_value)
                    else:
                        jan1_value = float(jan1_value)
                
                if dec31_value is not None:
                    if isinstance(dec31_value, str):
                        dec31_value = parse_currency_string(dec31_value)
                    else:
                        dec31_value = float(dec31_value)
                
                # Convert currency if needed for Jan 1 value
                if jan1_value is not None and asset_data.get("original_currency", "EUR") != "EUR":
                    # Use Jan 1 as reference date for conversion
                    converted_jan1 = converter.convert(
                        jan1_value,
                        asset_data["original_currency"],
                        "EUR",
                        date(state.tax_year, 1, 1),
                    )
                    asset_data["value_eur_jan1"] = converted_jan1
                    # Store conversion rate for reference
                    asset_data["conversion_rate"] = converter.get_rate(
                        asset_data["original_currency"],
                        "EUR",
                        date(state.tax_year, 1, 1),
                    )
                elif jan1_value is not None:
                    # Already in EUR, just ensure it's stored as float
                    asset_data["value_eur_jan1"] = jan1_value
                
                # Convert currency if needed for Dec 31 value
                if dec31_value is not None and asset_data.get("original_currency", "EUR") != "EUR":
                    # Use Dec 31 as reference date for conversion
                    converted_dec31 = converter.convert(
                        dec31_value,
                        asset_data["original_currency"],
                        "EUR",
                        date(state.tax_year, 12, 31),
                    )
                    asset_data["value_eur_dec31"] = converted_dec31
                    # Store conversion rate (use the one for Jan 1 if both exist, or Dec 31)
                    if jan1_value is None:
                        asset_data["conversion_rate"] = converter.get_rate(
                            asset_data["original_currency"],
                            "EUR",
                            date(state.tax_year, 12, 31),
                        )
                elif dec31_value is not None:
                    # Already in EUR, just ensure it's stored as float
                    asset_data["value_eur_dec31"] = dec31_value
                
                # Parse original_value if present (may come as string from LLM)
                # If individual positions were summed, use the summed value
                original_value = asset_data.get("original_value")
                if original_value is not None:
                    if isinstance(original_value, str):
                        original_value = parse_currency_string(original_value)
                    else:
                        original_value = float(original_value)
                    asset_data["original_value"] = original_value
                elif individual_positions and (jan1_value is not None or dec31_value is not None):
                    # If we summed individual positions but original_value wasn't set, use the summed value
                    # Prefer jan1 if available, otherwise dec31
                    if jan1_value is not None:
                        asset_data["original_value"] = jan1_value
                    elif dec31_value is not None:
                        asset_data["original_value"] = dec31_value
                
                # Validate and construct Box3Asset
                box3_asset = validator.validate_box3_asset(
                    asset_data, doc_id, source_filename, state.tax_year
                )
                validated_box3_items.append(box3_asset)
                logger.debug(
                    f"Validated Box3 asset: Jan1=€{box3_asset.value_eur_jan1 or 0:,.2f}, "
                    f"Dec31=€{box3_asset.value_eur_dec31 or 0:,.2f}"
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
            "validation_warnings": validation_warnings,
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


