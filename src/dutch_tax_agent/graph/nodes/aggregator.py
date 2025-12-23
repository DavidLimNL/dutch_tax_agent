"""Aggregation and orchestration nodes for the main graph."""

import logging
from collections import defaultdict
from datetime import date, datetime

from rich.console import Console
from rich.table import Table
from rich.text import Text

from dutch_tax_agent.schemas.state import TaxGraphState
from dutch_tax_agent.schemas.tax_entities import Box1Income, Box3Asset

logger = logging.getLogger(__name__)
console = Console()


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
    all_warnings = []
    
    # Build a map of doc_id -> extraction_result to check which values were actually extracted
    # This helps us distinguish between "value was 0.0" and "value was not provided (defaulted to 0.0)"
    extraction_map = {}
    for extraction_result in state.extraction_results:
        extraction_map[extraction_result.doc_id] = extraction_result

    for result in validated_results:
        doc_id = result.get("doc_id")
        extraction_result = extraction_map.get(doc_id) if doc_id else None
        
        # Parse Box1 items
        for item_dict in result.get("validated_box1_items", []):
            all_box1_items.append(Box1Income(**item_dict))

        # Parse Box3 items (will be merged later)
        # Store metadata about which values were actually extracted
        for item_dict in result.get("validated_box3_items", []):
            asset = Box3Asset(**item_dict)
            # Check if this value was actually extracted (not defaulted)
            if extraction_result:
                extracted_data = extraction_result.extracted_data
                box3_items = extracted_data.get("box3_items", [])
                
                # Store document date range for merging priority
                doc_date_range = extracted_data.get("document_date_range", {})
                doc_start = doc_date_range.get("start_date")
                doc_end = doc_date_range.get("end_date")
                # Parse dates if they're strings
                if doc_start and isinstance(doc_start, str):
                    try:
                        doc_start = datetime.fromisoformat(doc_start).date()
                    except (ValueError, AttributeError):
                        doc_start = None
                if doc_end and isinstance(doc_end, str):
                    try:
                        doc_end = datetime.fromisoformat(doc_end).date()
                    except (ValueError, AttributeError):
                        doc_end = None
                asset._doc_start_date = doc_start if isinstance(doc_start, date) else None
                asset._doc_end_date = doc_end if isinstance(doc_end, date) else None
                
                # Find the matching item by account_number (preferred) or description and asset_type
                for extracted_item in box3_items:
                    # Match by account_number if available, otherwise by description
                    matches = False
                    if asset.account_number and extracted_item.get("account_number"):
                        matches = (extracted_item.get("account_number") == asset.account_number and
                                 extracted_item.get("asset_type") == asset.asset_type)
                    elif not asset.account_number and not extracted_item.get("account_number"):
                        matches = (extracted_item.get("description") == asset.description and
                                 extracted_item.get("asset_type") == asset.asset_type)
                    
                    if matches:
                        # Check if values were actually extracted (not None in raw extraction)
                        asset._jan1_was_extracted = extracted_item.get("value_eur_jan1") is not None
                        asset._dec31_was_extracted = extracted_item.get("value_eur_dec31") is not None
                        break
                else:
                    # If we can't find the item, assume both were extracted (conservative)
                    asset._jan1_was_extracted = True
                    asset._dec31_was_extracted = asset.value_eur_dec31 is not None
            else:
                # If we can't find extraction result, assume both were extracted (conservative)
                asset._jan1_was_extracted = True
                asset._dec31_was_extracted = asset.value_eur_dec31 is not None
                asset._doc_start_date = None
                asset._doc_end_date = None
            
            all_box3_items.append(asset)

        # Collect errors and warnings
        all_errors.extend(result.get("validation_errors", []))
        all_warnings.extend(result.get("validation_warnings", []))
    
    # Merge Box3Asset items from the same account
    # Accounts are identified by account_number + asset_type (preferred) or description + asset_type (fallback)
    account_map: dict[tuple[str, str, str], list[Box3Asset]] = defaultdict(list)
    
    for asset in all_box3_items:
        # Create a key: prefer account_number if available, otherwise use description
        # Format: (match_type, identifier, asset_type) where match_type is "account_number" or "description"
        if asset.account_number:
            account_key = ("account_number", asset.account_number, asset.asset_type)
        else:
            # Fallback to description if account_number is not available
            account_key = ("description", asset.description or "", asset.asset_type)
        account_map[account_key].append(asset)
    
    # Merge assets for each account
    merged_box3_items = []
    quarantined_assets = []
    # Collect asset information for table display
    asset_table_data = []
    
    for account_key, assets in account_map.items():
        if len(assets) == 1:
            # No merging needed - check if it has both values that were actually extracted
            asset = assets[0]
            # Check if values were actually extracted (not defaulted)
            # has_jan1: True if value was extracted AND value is not None
            jan1_was_extracted = getattr(asset, '_jan1_was_extracted', True)  # Default to True if not set
            has_jan1 = jan1_was_extracted and asset.value_eur_jan1 is not None
            # has_dec31: True if value exists (regardless of whether it was explicitly extracted)
            has_dec31 = asset.value_eur_dec31 is not None
            
            # Track notes for table display
            asset_note = ""
            
            # Check for mid-year account opening scenario (single asset case)
            # If Jan 1 is missing but Dec 31 is present, account was opened mid-year - set Jan 1 to 0
            if not has_jan1 and has_dec31:
                # Account was opened after January - Jan 1 value should be 0.0
                doc_start = getattr(asset, '_doc_start_date', None)
                asset_note = (
                    f"Mid-year opening: Jan 1 not found but Dec 31 present"
                    f"{f', doc starts {doc_start}' if doc_start else ''}"
                )
                # Create a new asset with Jan 1 set to 0.0 and reference_date set to tax year's Jan 1
                tax_year = state.tax_year
                asset = Box3Asset(
                    source_doc_id=asset.source_doc_id,
                    source_filename=asset.source_filename,
                    source_page=asset.source_page,
                    asset_type=asset.asset_type,
                    value_eur_jan1=0.0,
                    value_eur_dec31=asset.value_eur_dec31,
                    realized_gains_eur=asset.realized_gains_eur,
                    realized_losses_eur=asset.realized_losses_eur,
                    original_value=asset.original_value,
                    original_currency=asset.original_currency,
                    conversion_rate=asset.conversion_rate,
                    reference_date=date(tax_year, 1, 1),  # Jan 1 of tax year for the 0.0 value
                    description=asset.description,
                    account_number=asset.account_number,
                    extraction_confidence=asset.extraction_confidence,
                    original_text_snippet=asset.original_text_snippet,
                )
                has_jan1 = True
            
            # Check for mid-year statement ending before Dec 31 (single asset case)
            # If Jan 1 is present but Dec 31 is missing, statement ends mid-year - set Dec 31 to 0
            if has_jan1 and not has_dec31:
                # Statement doesn't cover Dec 31 - Dec 31 value should be 0.0
                doc_end = getattr(asset, '_doc_end_date', None)
                tax_year = state.tax_year
                dec31_target = date(tax_year, 12, 31)
                if asset_note:
                    asset_note += "; "
                asset_note += (
                    f"Mid-year ending: Dec 31 not found"
                    f"{f', doc ends {doc_end}' if doc_end else ''}"
                )
                # Create a new asset with Dec 31 set to 0.0
                asset = Box3Asset(
                    source_doc_id=asset.source_doc_id,
                    source_filename=asset.source_filename,
                    source_page=asset.source_page,
                    asset_type=asset.asset_type,
                    value_eur_jan1=asset.value_eur_jan1,
                    value_eur_dec31=0.0,
                    realized_gains_eur=asset.realized_gains_eur,
                    realized_losses_eur=asset.realized_losses_eur,
                    original_value=asset.original_value,
                    original_currency=asset.original_currency,
                    conversion_rate=asset.conversion_rate,
                    reference_date=asset.reference_date,
                    description=asset.description,
                    account_number=asset.account_number,
                    extraction_confidence=asset.extraction_confidence,
                    original_text_snippet=asset.original_text_snippet,
                )
                has_dec31 = True
            
            if has_jan1 and has_dec31:
                merged_box3_items.append(asset)
                # Collect data for table display
                asset_table_data.append({
                    "description": asset.description or "Unknown",
                    "asset_type": asset.asset_type,
                    "account_number": asset.account_number or "",
                    "source_filename": asset.source_filename,
                    "jan1": asset.value_eur_jan1,
                    "dec31": asset.value_eur_dec31 or 0,
                    "notes": asset_note,
                })
            else:
                # Quarantine: missing required dates for actual return calculation
                missing_dates = []
                if not has_jan1:
                    missing_dates.append("January 1st")
                if not has_dec31:
                    missing_dates.append("December 31st")
                
                quarantine_msg = (
                    f"Box3Asset for account '{asset.description or 'Unknown'}' "
                    f"({asset.asset_type}) from {asset.source_filename} is missing "
                    f"value for {', '.join(missing_dates)}. "
                    f"Both Jan 1 and Dec 31 values are required for actual return calculation."
                )
                quarantined_assets.append((asset, quarantine_msg))
                logger.warning(quarantine_msg)
        else:
            # Merge multiple assets for the same account
            match_type = account_key[0]
            identifier = account_key[1]
            asset_type = account_key[2]
            logger.info(
                f"Merging {len(assets)} Box3Asset items for account: "
                f"{match_type}='{identifier}', asset_type='{asset_type}'"
            )
            
            # Use the first asset as the base
            base_asset = assets[0]
            
            # Track notes for merged assets
            merged_notes = []
            
            # Get tax year for reference date comparison
            tax_year = state.tax_year
            
            # Find January-dated documents (doc_start or doc_end in January)
            jan_documents = []
            for a in assets:
                doc_start = getattr(a, '_doc_start_date', None)
                doc_end = getattr(a, '_doc_end_date', None)
                doc_in_jan = False
                if doc_start and doc_start.month == 1:
                    doc_in_jan = True
                elif doc_end and doc_end.month == 1:
                    doc_in_jan = True
                if doc_in_jan:
                    jan_documents.append(a)
            
            # Find December-dated documents (doc_start or doc_end in December)
            dec_documents = []
            for a in assets:
                doc_start = getattr(a, '_doc_start_date', None)
                doc_end = getattr(a, '_doc_end_date', None)
                doc_in_dec = False
                if doc_start and doc_start.month == 12:
                    doc_in_dec = True
                elif doc_end and doc_end.month == 12:
                    doc_in_dec = True
                if doc_in_dec:
                    dec_documents.append(a)
            
            # Extract Jan 1 value from January-dated documents (preferred) or from other documents with Jan 1 values
            # This includes dec_prev_year documents (December statements of previous year used as Jan 1 value)
            merged_jan1 = None
            has_jan1 = False
            if jan_documents:
                # Look for Jan 1 value in January documents (preferred)
                for a in jan_documents:
                    if getattr(a, '_jan1_was_extracted', True) and a.value_eur_jan1 is not None:
                        merged_jan1 = a.value_eur_jan1
                        has_jan1 = True
                        break
                # If not found but we have January documents, assume 0
                if not has_jan1:
                    merged_jan1 = 0.0
                    has_jan1 = True
                    logger.info(
                        f"No Jan 1 value found in January documents for {base_asset.description or 'Unknown'} "
                        f"({base_asset.asset_type}), assuming 0.0"
                    )
            else:
                # No January documents found - check all assets for Jan 1 values
                # This handles cases like dec_prev_year documents (December of previous year used as Jan 1)
                for a in assets:
                    if getattr(a, '_jan1_was_extracted', True) and a.value_eur_jan1 is not None:
                        merged_jan1 = a.value_eur_jan1
                        has_jan1 = True
                        logger.info(
                            f"Found Jan 1 value from non-January document for {base_asset.description or 'Unknown'} "
                            f"({base_asset.asset_type}) - likely from December statement of previous year"
                        )
                        break
                
                if not has_jan1:
                    # Check if this is a mid-year account opening scenario
                    # If we have Dec 31 data but no Jan 1 data, account was opened mid-year
                    # In this case, Jan 1 value should be 0.0 (account didn't exist on Jan 1)
                    # Check if any asset has a Dec 31 value
                    has_dec31_value = any(a.value_eur_dec31 is not None for a in assets)
                    if has_dec31_value:
                        # Account was opened after January - Jan 1 value should be 0.0
                        merged_jan1 = 0.0
                        has_jan1 = True
                        merged_notes.append("Mid-year opening: Jan 1 not found but Dec 31 present")
                    else:
                        # No Jan 1 value found in any document - cannot determine Jan 1 value
                        logger.warning(
                            f"No January-dated documents or Jan 1 values found for {base_asset.description or 'Unknown'} "
                            f"({base_asset.asset_type}), cannot determine Jan 1 value"
                        )
            
            # Extract Dec 31 value from December-dated documents only
            merged_dec31 = None
            has_dec31 = False
            if dec_documents:
                # Look for Dec 31 value in December documents
                for a in dec_documents:
                    if a.value_eur_dec31 is not None and getattr(a, '_dec31_was_extracted', True):
                        merged_dec31 = a.value_eur_dec31
                        has_dec31 = True
                        break
                # If not found but we have December documents, assume 0
                if not has_dec31:
                    merged_dec31 = 0.0
                    has_dec31 = True
                    logger.info(
                        f"No Dec 31 value found in December documents for {base_asset.description or 'Unknown'} "
                        f"({base_asset.asset_type}), assuming 0.0"
                    )
            else:
                # No December documents found - check if this is a mid-year statement ending before Dec 31
                if has_jan1:
                    # If we have Jan 1 data but no Dec 31 data, statement ends mid-year - set Dec 31 to 0
                    merged_dec31 = 0.0
                    has_dec31 = True
                    merged_notes.append("Mid-year ending: Dec 31 not found")
                else:
                    # No December documents found - cannot determine Dec 31 value
                    logger.warning(
                        f"No December-dated documents found for {base_asset.description or 'Unknown'} "
                        f"({base_asset.asset_type}), cannot determine Dec 31 value"
                    )
            
            # Quarantine if we don't have both values from appropriate documents
            if not (has_jan1 and has_dec31):
                missing_dates = []
                if not has_jan1:
                    missing_dates.append("January 1st")
                if not has_dec31:
                    missing_dates.append("December 31st")
                
                all_source_filenames = [a.source_filename for a in assets]
                quarantine_msg = (
                    f"Box3Asset for account '{base_asset.description or 'Unknown'}' "
                    f"({base_asset.asset_type}) from merged documents "
                    f"({', '.join(set(all_source_filenames))}) is missing "
                    f"values for {', '.join(missing_dates)}. "
                    f"Both Jan 1 and Dec 31 values are required for actual return calculation."
                )
                quarantined_assets.append((base_asset, quarantine_msg))
                logger.warning(quarantine_msg)
                continue  # Skip adding to merged_box3_items
            
            # Combine realized gains/losses (sum them)
            total_gains = sum(a.realized_gains_eur or 0.0 for a in assets)
            total_losses = sum(a.realized_losses_eur or 0.0 for a in assets)
            
            # Combine source documents (keep track of all source doc IDs)
            all_source_doc_ids = [a.source_doc_id for a in assets]
            all_source_filenames = [a.source_filename for a in assets]
            
            # Create merged asset
            # Use Jan 1 of tax year as the reference_date for merged assets
            merged_reference_date = date(tax_year, 1, 1)
            
            merged_asset = Box3Asset(
                source_doc_id=base_asset.source_doc_id,  # Use first doc_id as primary
                source_filename=", ".join(set(all_source_filenames)),  # Combine filenames
                source_page=base_asset.source_page,
                asset_type=base_asset.asset_type,
                value_eur_jan1=merged_jan1,
                value_eur_dec31=merged_dec31,
                realized_gains_eur=total_gains if total_gains > 0 else None,
                realized_losses_eur=total_losses if total_losses > 0 else None,
                original_value=base_asset.original_value,
                original_currency=base_asset.original_currency,
                conversion_rate=base_asset.conversion_rate,
                reference_date=merged_reference_date,  # Always use Jan 1 for merged assets
                description=base_asset.description,
                account_number=base_asset.account_number,  # Preserve account_number from base asset
                extraction_confidence=min(a.extraction_confidence for a in assets),  # Use lowest confidence
                original_text_snippet=base_asset.original_text_snippet,
            )
            
            merged_box3_items.append(merged_asset)
            # Collect data for table display
            notes_str = "; ".join(merged_notes) if merged_notes else "Merged"
            asset_table_data.append({
                "description": merged_asset.description or "Unknown",
                "asset_type": merged_asset.asset_type,
                "account_number": merged_asset.account_number or "",
                "source_filename": f"{len(assets)} documents",
                "jan1": merged_jan1,
                "dec31": merged_dec31 or 0,
                "notes": notes_str,
            })
    
    # Add quarantine errors for assets missing required dates
    if quarantined_assets:
        for asset, msg in quarantined_assets:
            all_errors.append(msg)
        logger.warning(
            f"Quarantined {len(quarantined_assets)} Box3Asset item(s) missing required dates "
            f"for actual return calculation"
        )
    
    all_box3_items = merged_box3_items

    # After merging, remove validation errors that were resolved by aggregation
    # These are errors about missing Jan 1 or Dec 31 values that were filled in during merging
    resolved_errors = []
    remaining_errors = []
    
    # Build a set of all source filenames from successfully merged assets with both values
    # Note: merged assets may have comma-separated filenames, so we need to check all of them
    successfully_merged_files = set()
    for asset in merged_box3_items:
        if asset.value_eur_jan1 is not None and asset.value_eur_dec31 is not None:
            # Split comma-separated filenames and add each one
            filenames = [f.strip() for f in asset.source_filename.split(",")]
            successfully_merged_files.update(filenames)
    
    # Filter out errors about missing values for files that were successfully merged
    for error in all_errors:
        # Check if this is a Box3 validation error about missing values
        if "Box3 validation error" in error and "must have at least one of value_eur_jan1 or value_eur_dec31" in error:
            # Extract filename from error message
            # Error format: "Box3 validation error in {filename}: ..."
            if " in " in error:
                filename = error.split(" in ", 1)[1].split(":", 1)[0].strip()
                if filename in successfully_merged_files:
                    # This error was resolved by merging - remove it
                    resolved_errors.append(error)
                    continue
        
        # Keep all other errors
        remaining_errors.append(error)
    
    if resolved_errors:
        logger.info(
            f"Resolved {len(resolved_errors)} validation error(s) through aggregation: "
            f"missing values were filled in by merging documents"
        )
        for error in resolved_errors:
            logger.debug(f"Resolved error: {error}")
    
    all_errors = remaining_errors

    logger.info(
        f"Aggregated: {len(all_box1_items)} Box1 items, "
        f"{len(all_box3_items)} Box3 items (after merging and quarantine), "
        f"{len(quarantined_assets)} Box3 items quarantined (missing required dates), "
        f"{len(all_errors)} errors"
    )

    # Display assets in a table format
    if asset_table_data:
        table = Table(title="Box 3 Assets", show_header=True, header_style="bold magenta")
        table.add_column("Description", style="cyan", no_wrap=False)
        table.add_column("Asset Type", style="green")
        table.add_column("Account Number", style="yellow")
        table.add_column("Source File", style="blue", no_wrap=False)
        table.add_column("Jan 1 (€)", justify="right", style="bold")
        table.add_column("Dec 31 (€)", justify="right", style="bold")
        table.add_column("Notes", style="dim", no_wrap=False)
        
        for asset_data in asset_table_data:
            account_num = asset_data["account_number"]
            if account_num:
                account_num_text = Text(account_num, style="bold cyan")
            else:
                account_num_text = ""
            
            table.add_row(
                asset_data["description"],
                asset_data["asset_type"],
                account_num_text,
                asset_data["source_filename"],
                f"{asset_data['jan1']:,.2f}",
                f"{asset_data['dec31']:,.2f}",
                asset_data["notes"] if asset_data["notes"] else "",
            )
        
        console.print(table)

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
        "validation_warnings": list(state.validation_warnings) + all_warnings,
        "status": "validating",
        "documents": [],  # Clear to save memory and tokens
        "classified_documents": [],  # Clear classified_documents.doc_text as well
    }

