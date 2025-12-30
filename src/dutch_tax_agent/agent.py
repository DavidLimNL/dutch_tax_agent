"""Core agent orchestrator for the Dutch Tax Agent with HITL support."""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.logging import RichHandler
from rich.progress import Progress, SpinnerColumn, TextColumn
from langgraph.types import Command

from dutch_tax_agent.checkpoint_utils import generate_thread_id, get_thread_state, thread_exists
from dutch_tax_agent.config import settings
from dutch_tax_agent.document_manager import DocumentManager
from dutch_tax_agent.graph import create_tax_graph
from dutch_tax_agent.ingestion import PDFParser, PIIScrubber
from dutch_tax_agent.ingestion.csv_parser import parse_csv
from dutch_tax_agent.schemas.state import TaxGraphState, Replace
from dutch_tax_agent.schemas.tax_entities import Box3Asset

# Suppress all Presidio logging BEFORE basicConfig to prevent any output
# Use NullHandler to completely silence Presidio loggers
_null_handler = logging.NullHandler()
_presidio_loggers = [
    "presidio_analyzer",
    "presidio_anonymizer",
    "presidio_analyzer.analyzer_engine",
    "presidio_analyzer.nlp_engine_provider",
    "presidio_analyzer.entity_recognizer",
    "presidio_analyzer.recognizers_loader_utils",
]
for logger_name in _presidio_loggers:
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.CRITICAL)
    logger.addHandler(_null_handler)
    logger.propagate = False

# Create a filter to suppress Presidio log messages
class PresidioFilter(logging.Filter):
    """Filter out all Presidio-related log messages."""
    def filter(self, record):
        # Check if the logger name contains presidio
        if "presidio" in record.name.lower():
            return False
        # Check the module path in the record
        if hasattr(record, "pathname") and "presidio" in record.pathname.lower():
            return False
        # Check the filename (e.g., analyzer_engine.py, entity_recognizer.py, etc.)
        presidio_files = [
            "analyzer_engine.py",
            "nlp_engine_provider.py",
            "entity_recognizer.py",
            "recognizers_loader_utils.py",
        ]
        if hasattr(record, "filename"):
            if any(fname in record.filename for fname in presidio_files):
                return False
        return True

# Setup logging
console = Console()
rich_handler = RichHandler(rich_tracebacks=True, console=console)
presidio_filter = PresidioFilter()
rich_handler.addFilter(presidio_filter)
logging.basicConfig(
    level=settings.log_level,
    format="%(message)s",
    handlers=[rich_handler],
)
# Also add filter to root logger to catch any messages
logging.getLogger().addFilter(presidio_filter)

logger = logging.getLogger(__name__)


class DutchTaxAgent:
    """Main orchestrator for the Dutch Tax Agent with HITL support."""

    def __init__(
        self, 
        thread_id: Optional[str] = None,
        tax_year: int = 2024,
        has_fiscal_partner: bool = True
    ) -> None:
        """Initialize the tax agent.
        
        Args:
            thread_id: Optional thread ID for checkpointing (generated if not provided)
            tax_year: Tax year to process (2022-2025)
            has_fiscal_partner: Whether to assume fiscal partnership (default: True)
        """
        self.tax_year = tax_year
        self.has_fiscal_partner = has_fiscal_partner
        self.thread_id = thread_id or generate_thread_id(prefix=f"tax{tax_year}")
        self.pdf_parser = PDFParser()
        self.pii_scrubber = PIIScrubber()
        self.graph = create_tax_graph()
        self.document_manager = DocumentManager()

        logger.info(
            f"Initialized Dutch Tax Agent for tax year {tax_year} "
            f"(fiscal partner: {has_fiscal_partner}, thread: {self.thread_id})"
        )

    def ingest_documents(
        self, 
        pdf_paths: list[Path],
        csv_files: Optional[list[Path]] = None,
        is_initial: bool = False
    ) -> TaxGraphState:
        """Ingest documents (initial or incremental).
        
        Args:
            pdf_paths: List of paths to PDF files
            csv_files: Optional list of paths to CSV transaction files
            is_initial: If True, creates new thread. If False, adds to existing thread.
            
        Returns:
            TaxGraphState after ingestion (paused at HITL control)
        """
        console.print(f"\n[bold blue]🇳🇱 Dutch Tax Agent - Tax Year {self.tax_year}[/bold blue]\n")

        # Initialize csv_files if not provided
        csv_files = csv_files or []

        # Get existing state if resuming
        if not is_initial:
            state = get_thread_state(
                self.graph.checkpointer,
                self.thread_id
            )
            if not state:
                raise ValueError(f"Thread {self.thread_id} not found. Use is_initial=True to create new thread.")
            
            # Find new documents (skip already processed)
            pdf_paths = self.document_manager.find_new_documents(
                pdf_paths, 
                state.processed_documents
            )
            
            # Find new CSV files (skip already processed)
            csv_files = self.document_manager.find_new_documents(
                csv_files,
                state.processed_documents
            )
            
            if not pdf_paths and not csv_files:
                console.print("[yellow]⚠️  No new documents found[/yellow]")
                return state

        total_files = len(pdf_paths) + len(csv_files)
        console.print(f"[bold]Processing {len(pdf_paths)} PDF(s) and {len(csv_files)} CSV(s)[/bold]\n")

        # Phase 1: Ingestion (Safe Zone)
        console.print("[bold]Phase 1: Document Ingestion & PII Scrubbing[/bold]")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Parsing PDFs...", total=len(pdf_paths))

            parsed_docs = []
            doc_metadata = []
            for pdf_path in pdf_paths:
                try:
                    # Parse PDF
                    result = self.pdf_parser.parse(pdf_path)
                    
                    # Generate hash
                    doc_hash = self.document_manager.hash_pdf(pdf_path)
                    
                    # Create metadata
                    metadata = self.document_manager.create_document_metadata(
                        filename=pdf_path.name,
                        doc_hash=doc_hash,
                        page_count=result["page_count"]
                    )
                    doc_metadata.append(metadata)
                    
                    parsed_docs.append({
                        "text": result["text"],
                        "filename": pdf_path.name,
                        "page_count": result["page_count"],
                        "doc_id": metadata["id"],  # Pass the ID to ensure consistency
                    })
                    progress.advance(task)
                except Exception as e:
                    console.print(f"[red]❌ Failed to parse {pdf_path.name}: {e}[/red]")
                    continue

            console.print(f"[green]✓[/green] Parsed {len(parsed_docs)} documents")

            #  TO BE REMOVED LATER
            # logger.info(f"Parsed DOCS: {parsed_docs[0]}")

            # Scrub PII (ZERO-TRUST: Documents that fail scrubbing are excluded)
            progress.update(task, description="Scrubbing PII...")
            try:
                scrubbed_docs = self.pii_scrubber.scrub_batch(parsed_docs)
                if len(scrubbed_docs) < len(parsed_docs):
                    console.print(
                        f"[yellow]⚠️[/yellow] Scrubbed {len(scrubbed_docs)}/{len(parsed_docs)} documents "
                        f"({len(parsed_docs) - len(scrubbed_docs)} failed scrubbing and were excluded)"
                    )
                    # Remove metadata for failed documents
                    doc_metadata = doc_metadata[:len(scrubbed_docs)]
                else:
                    console.print(f"[green]✓[/green] Scrubbed PII from {len(scrubbed_docs)} documents")
            except RuntimeError as e:
                console.print(f"[bold red]❌ SECURITY ERROR: {e}[/bold red]")
                console.print(
                    "[yellow]No documents will be processed to prevent PII exposure.[/yellow]"
                )
                raise

        #  TO BE REMOVED LATER
        # logger.info(f"Scrubbed DOCS: {scrubbed_docs[0]}")
        # return

        # Process CSV files (deterministic, no LLM)
        csv_box3_items = []
        csv_metadata = []
        
        if csv_files:
            console.print("\n[bold]Processing CSV Transaction Files[/bold]")
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task = progress.add_task("Parsing CSV files...", total=len(csv_files))
                
                for csv_path in csv_files:
                    try:
                        # Parse CSV (automatically detects format)
                        csv_data = parse_csv(csv_path, tax_year=self.tax_year)
                        
                        # Generate hash
                        csv_hash = self.document_manager.hash_file(csv_path)
                        
                        # Create metadata
                        metadata = self.document_manager.create_document_metadata(
                            filename=csv_path.name,
                            doc_hash=csv_hash,
                            page_count=0  # CSVs don't have pages
                        )
                        csv_metadata.append(metadata)
                        
                        # Create Box3Asset from CSV data
                        from datetime import date
                        jan1 = csv_data.get("jan1_balance_eur")
                        dec31 = csv_data.get("dec31_balance_eur")
                        deposits = csv_data["total_deposits_eur"]
                        withdrawals = csv_data["total_withdrawals_eur"]
                        
                        # Get realized gains if available (investment fund format)
                        realized_gains = csv_data.get("realized_gains_eur", 0.0)
                        
                        # Calculate Actual Return
                        # For EUR savings accounts, prefer realized interest (realized_gains_eur)
                        # But fall back to formula if realized_gains_eur is not available
                        # For foreign currency accounts, use formula to capture FX gains
                        currency = csv_data["currency"]
                        is_eur_savings = currency == "EUR"  # CSV files default to "savings" asset_type
                        actual_return = None
                        if jan1 is not None and dec31 is not None:
                            if is_eur_savings:
                                # EUR savings: prefer realized gains (sum of RETURN PAID transactions)
                                # But fall back to formula if realized_gains is None or 0
                                formula_result = (dec31 - jan1) - (deposits - withdrawals)
                                if realized_gains is not None and realized_gains > 0:
                                    actual_return = realized_gains
                                else:
                                    # Fall back to formula when realized_gains is not available
                                    actual_return = formula_result
                            else:
                                # Foreign currency: use formula to capture FX gains
                                actual_return = (dec31 - jan1) - (deposits - withdrawals)
                        
                        asset = Box3Asset(
                            source_doc_id=metadata["id"],
                            source_filename=csv_path.name,
                            source_page=None,
                            asset_type="savings",  # Default type
                            value_eur_jan1=jan1 if jan1 is not None else 0.0,  # Box3Asset requires a value, use 0.0 if unknown
                            value_eur_dec31=dec31,
                            deposits_eur=deposits,
                            withdrawals_eur=withdrawals,
                            realized_gains_eur=realized_gains if realized_gains > 0 else None,
                            actual_return_eur=actual_return,
                            original_value=jan1 if jan1 is not None else None,
                            original_currency=csv_data["currency"],
                            reference_date=date(self.tax_year, 1, 1),
                            description=f"CSV Transaction File: {csv_path.stem}",
                            account_number=csv_path.stem.lower(),  # Use filename as account number (lowercase for case-insensitive matching)
                            extraction_confidence=1.0,  # Deterministic parsing
                            original_text_snippet=None,
                        )
                        csv_box3_items.append(asset)
                        
                        # Print CSV extraction summary
                        summary_parts = []
                        if jan1 is not None:
                            summary_parts.append(f"Jan 1: €{jan1:,.2f}")
                        if dec31 is not None:
                            summary_parts.append(f"Dec 31: €{dec31:,.2f}")
                        summary_parts.extend([
                            f"Deposits: €{deposits:,.2f}",
                            f"Withdrawals: €{withdrawals:,.2f}",
                        ])
                        if realized_gains > 0:
                            summary_parts.append(f"Realized gains: €{realized_gains:,.2f}")
                        console.print(
                            f"[green]✓[/green] {csv_path.name}: {', '.join(summary_parts)}"
                        )
                        
                        progress.advance(task)
                    except Exception as e:
                        console.print(f"[red]❌ Failed to parse {csv_path.name}: {e}[/red]")
                        logger.exception(f"CSV parsing error for {csv_path.name}")
                        # Continue processing other CSV files even if one fails
                        continue
                
                if csv_box3_items:
                    console.print(f"[green]✓[/green] Processed {len(csv_box3_items)} CSV file(s)")
                elif csv_files:
                    console.print(f"[yellow]⚠️[/yellow] No CSV files were successfully processed")

        # Check if we have any documents to process
        if not scrubbed_docs and not csv_box3_items:
            console.print("\n[yellow]⚠️[/yellow] No documents or CSV files were successfully processed")
            console.print("[dim]Please check your input files and try again[/dim]")
            # Create a minimal state to avoid errors
            if is_initial:
                initial_state = TaxGraphState(
                    tax_year=self.tax_year,
                    session_id=self.thread_id,
                    next_action="await_human",
                    processed_documents=doc_metadata + csv_metadata,
                    processing_started_at=datetime.now(timezone.utc).isoformat(),
                )
                config = {"configurable": {"thread_id": self.thread_id}}
                self.graph.invoke(initial_state, config=config)
                return initial_state
            else:
                state = get_thread_state(self.graph.checkpointer, self.thread_id)
                return state

        # Phase 2: LangGraph Processing
        console.print("\n[bold]Phase 2: LangGraph Extraction & Validation[/bold]")

        # Set up fiscal partner if assumed (default behavior)
        fiscal_partner = None
        if self.has_fiscal_partner:
            from datetime import date
            from dutch_tax_agent.schemas.tax_entities import FiscalPartner
            # Default: Assume partner born after 1963 (no transferability, but can use own credit)
            fiscal_partner = FiscalPartner(
                date_of_birth=date(1970, 1, 1),  # Default DOB (after 1963 threshold)
                box1_income_gross=0.0,
                is_fiscal_partner=True
            )
            logger.info("Fiscal partner assumed (default configuration)")

        # Build or update state
        if is_initial:
            # Create initial state with CSV Box3 items already included
            initial_state = TaxGraphState(
                documents=scrubbed_docs,
                tax_year=self.tax_year,
                fiscal_partner=fiscal_partner,
                session_id=self.thread_id,
                next_action="await_human",
                processed_documents=doc_metadata + csv_metadata,
                box3_asset_items=csv_box3_items,
                box3_total_assets_jan1=sum(item.value_eur_jan1 for item in csv_box3_items),
                processing_started_at=datetime.now(timezone.utc).isoformat(),
            )
            
            # Execute graph (will pause at HITL node)
            config = {"configurable": {"thread_id": self.thread_id}}
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task = progress.add_task("Running extraction pipeline...")
                
                try:
                    if settings.enable_checkpointing:
                        logger.info(f"Executing graph with checkpointing (thread: {self.thread_id})")
                        console.print(f"[dim]Thread ID: {self.thread_id}[/dim]")
                    else:
                        logger.info("Executing graph without checkpointing")
                    
                    final_state_dict = self.graph.invoke(initial_state, config=config)
                    # LangGraph returns dict, convert to TaxGraphState for type safety
                    final_state = TaxGraphState(**final_state_dict) if isinstance(final_state_dict, dict) else final_state_dict
                    progress.update(task, description="Extraction complete!", completed=True)
                except Exception as e:
                    console.print(f"[red]❌ Graph execution failed: {e}[/red]")
                    raise
            
        else:
            # Incremental: update state and resume
            state = get_thread_state(
                self.graph.checkpointer,
                self.thread_id
            )
            
            # Merge CSV Box3 items with existing items by account_number + asset_type
            # This ensures PDF and CSV files for the same account are merged
            from collections import defaultdict
            account_map: dict[tuple[str, str], list] = defaultdict(list)
            
            # Add existing items to account map
            for existing_asset in state.box3_asset_items:
                if existing_asset.account_number:
                    account_key = (existing_asset.account_number, existing_asset.asset_type)
                else:
                    account_key = (existing_asset.description or "", existing_asset.asset_type)
                account_map[account_key].append(existing_asset)
            
            # Add CSV items to account map (will merge with existing if same account)
            for csv_asset in csv_box3_items:
                if csv_asset.account_number:
                    account_key = (csv_asset.account_number, csv_asset.asset_type)
                else:
                    account_key = (csv_asset.description or "", csv_asset.asset_type)
                account_map[account_key].append(csv_asset)
            
            # Merge assets for each account
            updated_box3_items = []
            for account_key, assets in account_map.items():
                if len(assets) == 1:
                    # No merging needed
                    updated_box3_items.append(assets[0])
                else:
                    # Merge multiple assets for the same account
                    base_asset = assets[0]
                    
                    # Combine values: prefer non-zero/non-None values
                    merged_jan1 = None
                    merged_dec31 = None
                    merged_deposits = 0.0
                    merged_withdrawals = 0.0
                    merged_gains = 0.0
                    merged_losses = 0.0
                    
                    for asset in assets:
                        # Jan 1: prefer non-zero values, then non-None
                        if merged_jan1 is None or merged_jan1 == 0.0:
                            if asset.value_eur_jan1 is not None and asset.value_eur_jan1 != 0.0:
                                merged_jan1 = asset.value_eur_jan1
                            elif asset.value_eur_jan1 is not None:
                                merged_jan1 = asset.value_eur_jan1
                        
                        # Dec 31: prefer non-zero values, then non-None
                        if merged_dec31 is None or merged_dec31 == 0.0:
                            if asset.value_eur_dec31 is not None and asset.value_eur_dec31 != 0.0:
                                merged_dec31 = asset.value_eur_dec31
                            elif asset.value_eur_dec31 is not None:
                                merged_dec31 = asset.value_eur_dec31
                        
                        # Sum deposits, withdrawals, gains, losses
                        merged_deposits += asset.deposits_eur or 0.0
                        merged_withdrawals += asset.withdrawals_eur or 0.0
                        merged_gains += asset.realized_gains_eur or 0.0
                        merged_losses += asset.realized_losses_eur or 0.0
                    
                    # Calculate actual return if we have both jan1 and dec31
                    # For EUR savings accounts, use strictly realized interest (realized_gains_eur)
                    # For foreign currency accounts, use formula to capture FX gains
                    is_eur_savings = (
                        base_asset.original_currency == "EUR" and 
                        base_asset.asset_type == "savings"
                    )
                    actual_return = None
                    if merged_jan1 is not None and merged_dec31 is not None:
                        if is_eur_savings:
                            # EUR savings: use realized gains only (sum of RETURN PAID transactions)
                            actual_return = merged_gains if merged_gains > 0 else None
                        else:
                            # Foreign currency: use formula to capture FX gains
                            actual_return = (merged_dec31 - merged_jan1) - (merged_deposits - merged_withdrawals)
                    
                    # Use Jan 1 value as default if still None
                    if merged_jan1 is None:
                        merged_jan1 = 0.0
                    
                    # Combine source filenames
                    all_filenames = [a.source_filename for a in assets]
                    combined_filename = ", ".join(set(all_filenames))
                    
                    # Create merged asset
                    merged_asset = Box3Asset(
                        source_doc_id=base_asset.source_doc_id,  # Use first doc_id
                        source_filename=combined_filename,
                        source_page=base_asset.source_page,
                        asset_type=base_asset.asset_type,
                        value_eur_jan1=merged_jan1,
                        value_eur_dec31=merged_dec31,
                        deposits_eur=merged_deposits if merged_deposits > 0 else None,
                        withdrawals_eur=merged_withdrawals if merged_withdrawals > 0 else None,
                        realized_gains_eur=merged_gains if merged_gains > 0 else None,
                        realized_losses_eur=merged_losses if merged_losses > 0 else None,
                        actual_return_eur=actual_return,
                        original_value=base_asset.original_value,
                        original_currency=base_asset.original_currency,
                        conversion_rate=base_asset.conversion_rate,
                        reference_date=base_asset.reference_date,
                        description=base_asset.description,
                        account_number=base_asset.account_number,  # Keep account_number
                        extraction_confidence=min(a.extraction_confidence for a in assets),
                        original_text_snippet=base_asset.original_text_snippet,
                    )
                    updated_box3_items.append(merged_asset)
                    logger.info(
                        f"Merged {len(assets)} assets for account {account_key[0]} "
                        f"({account_key[1]}): {combined_filename}"
                    )
            
            updated_box3_total = sum(item.value_eur_jan1 for item in updated_box3_items)
            
            updates = {
                "documents": scrubbed_docs,
                "processed_documents": state.processed_documents + doc_metadata + csv_metadata,
                "box3_asset_items": Replace(updated_box3_items),
                "box3_total_assets_jan1": updated_box3_total,
                "next_action": "ingest_more",
                "classified_documents": [],  # Clear old classifications to ensure new documents are processed
            }
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task = progress.add_task("Processing new documents...")
                
                try:
                    # Update state and resume execution
                    config = {"configurable": {"thread_id": self.thread_id}}
                    self.graph.update_state(config, updates)
                    
                    # Resume execution - use invoke to execute past the interrupt_before
                    # When using interrupt_before, stream() will hit the interrupt immediately
                    # invoke() will execute through the interrupt and continue to completion
                    
                    try:
                        # Use Command to force routing to hitl_control if resuming
                        # This ensures that even if the pending task was cleared by update_state,
                        # we explicitly tell the graph where to resume.
                        resume_command = Command(goto="hitl_control")
                        
                        final_state_dict = self.graph.invoke(resume_command, config=config)
                        
                        # Handle case where invoke returns None (rare but possible with some configurations)
                        if final_state_dict is None:
                            from dutch_tax_agent.checkpoint_utils import get_checkpoint_state
                            final_state_dict = get_checkpoint_state(self.graph.checkpointer, self.thread_id)
                    except Exception as e:
                        logger.error(f"Graph invoke failed: {e}")
                        # Fallback: get state from checkpoint
                        from dutch_tax_agent.checkpoint_utils import get_checkpoint_state
                        final_state_dict = get_checkpoint_state(self.graph.checkpointer, self.thread_id)
                    
                    # Ensure we have a valid state dict
                    if final_state_dict is None:
                        raise RuntimeError("Failed to get final state from graph execution or checkpoint")
                    
                    # LangGraph returns dict, convert to TaxGraphState for type safety
                    final_state = TaxGraphState(**final_state_dict) if isinstance(final_state_dict, dict) else final_state_dict
                    progress.update(task, description="Processing complete!", completed=True)
                except Exception as e:
                    console.print(f"[red]❌ Failed to process documents: {e}[/red]")
                    raise

        # Display summary
        self._display_ingestion_summary(final_state)

        return final_state

    def remove_documents(
        self,
        doc_ids: Optional[list[str]] = None,
        filenames: Optional[list[str]] = None,
        remove_all: bool = False
    ) -> TaxGraphState:
        """Remove processed documents and recalculate.
        
        Args:
            doc_ids: Optional list of document IDs to remove
            filenames: Optional list of filenames to remove
            remove_all: If True, remove all documents
            
        Returns:
            Updated TaxGraphState
        """
        state = get_thread_state(
            self.graph.checkpointer,
            self.thread_id
        )
        if not state:
            raise ValueError(f"Thread {self.thread_id} not found")

        # Remove documents
        updated_docs, removed_ids = self.document_manager.remove_documents(
            state.processed_documents,
            doc_ids=doc_ids,
            filenames=filenames,
            remove_all=remove_all
        )

        console.print(f"[green]✓[/green] Removed {len(removed_ids)} document(s)")

        # Also filter extraction_results and validated_results
        removed_ids_set = set(removed_ids)

        # Recalculate totals and filter items
        # Also pass removed_filenames to handle cases where doc_ids might not match
        # (e.g. if items were created with random IDs but processed_docs has hash IDs)
        removed_filenames = [
            doc["filename"] 
            for doc in state.processed_documents 
            if doc["id"] in removed_ids_set
        ]
        
        updated_totals = self.document_manager.recalculate_totals_from_items(
            state.box1_income_items,
            state.box3_asset_items,
            removed_ids,
            removed_filenames=removed_filenames
        )

        removed_filenames_set = set(removed_filenames)
        
        updated_extraction_results = [
            result for result in state.extraction_results
            if result.doc_id not in removed_ids_set and result.source_filename not in removed_filenames_set
        ]
        updated_validated_results = [
            result for result in state.validated_results
            if result.get("doc_id") not in removed_ids_set and 
            (not result.get("validated_box1_items") or result["validated_box1_items"][0].get("source_filename") not in removed_filenames_set) and
            (not result.get("validated_box3_items") or result["validated_box3_items"][0].get("source_filename") not in removed_filenames_set)
        ]

        # Update state - need to use update_and_resume with a dummy node to ensure checkpoint is created
        # Since box1_income_items and box3_asset_items use Annotated[list, add], we need to
        # replace them completely by passing the full filtered list
        config = {"configurable": {"thread_id": self.thread_id}}
        
        # Create a complete state update
        state_updates = {
            "processed_documents": updated_docs,
            "extraction_results": Replace(updated_extraction_results),
            "validated_results": Replace(updated_validated_results),
            "box1_income_items": Replace(updated_totals["box1_income_items"]),
            "box3_asset_items": Replace(updated_totals["box3_asset_items"]),
            "box1_total_income": updated_totals["box1_total_income"],
            "box3_total_assets_jan1": updated_totals["box3_total_assets_jan1"],
            "last_command": "remove"
        }
        
        # Log what we're removing
        logger.info(
            f"Removing documents: {removed_ids}. "
            f"Filtering {len(state.box1_income_items)} Box1 items and "
            f"{len(state.box3_asset_items)} Box3 items"
        )
        
        # Update state - this should create a new checkpoint
        logger.info(f"Updating state with {len(state_updates)} fields")
        self.graph.update_state(config, state_updates)
        
        # Verify the update by getting the state again
        updated_state = get_thread_state(
            self.graph.checkpointer,
            self.thread_id
        )
        
        if not updated_state:
            raise RuntimeError("Failed to persist state update after document removal")
        
        # Verify documents were actually removed
        remaining_doc_ids = {doc["id"] for doc in updated_state.processed_documents}
        not_removed = [doc_id for doc_id in removed_ids if doc_id in remaining_doc_ids]
        if not_removed:
            logger.warning(
                f"Some documents were not properly removed: {not_removed}. "
                f"This may indicate a checkpoint persistence issue."
            )
        
        # Verify items were filtered
        remaining_box1_count = len(updated_state.box1_income_items)
        remaining_box3_count = len(updated_state.box3_asset_items)
        expected_box1_count = len(updated_totals["box1_income_items"])
        expected_box3_count = len(updated_totals["box3_asset_items"])
        
        if remaining_box1_count != expected_box1_count:
            logger.warning(
                f"Box1 item count mismatch: expected {expected_box1_count}, "
                f"got {remaining_box1_count}"
            )
        if remaining_box3_count != expected_box3_count:
            logger.warning(
                f"Box3 item count mismatch: expected {expected_box3_count}, "
                f"got {remaining_box3_count}"
            )
        
        logger.info(
            f"State update verified: {len(updated_state.processed_documents)} documents, "
            f"{remaining_box1_count} Box1 items, {remaining_box3_count} Box3 items"
        )

        console.print(f"[dim]Recalculated totals - Box 1: €{updated_state.box1_total_income:,.2f}, "
                     f"Box 3: €{updated_state.box3_total_assets_jan1:,.2f}[/dim]")

        return updated_state

    def remove_box3_assets(
        self,
        indices: Optional[list[int]] = None,
        remove_all: bool = False
    ) -> TaxGraphState:
        """Remove Box 3 assets by index and recalculate.

        Args:
            indices: List of asset indices to remove
            remove_all: If True, remove all assets

        Returns:
            Updated TaxGraphState
        """
        state = get_thread_state(
            self.graph.checkpointer,
            self.thread_id
        )
        if not state:
            raise ValueError(f"Thread {self.thread_id} not found")

        current_assets = state.box3_asset_items
        
        if remove_all:
            updated_assets = []
            removed_count = len(current_assets)
        else:
            if not indices:
                return state
                
            # Validate indices
            indices_set = set(indices)
            max_index = len(current_assets) - 1
            
            invalid_indices = [i for i in indices_set if i < 0 or i > max_index]
            if invalid_indices:
                raise ValueError(f"Invalid indices: {invalid_indices}. Max index is {max_index}")
            
            updated_assets = [
                asset for i, asset in enumerate(current_assets)
                if i not in indices_set
            ]
            removed_count = len(current_assets) - len(updated_assets)

        # Recalculate total
        new_total = sum(asset.value_eur_jan1 for asset in updated_assets)
        
        # Update state
        config = {"configurable": {"thread_id": self.thread_id}}
        
        state_updates = {
            "box3_asset_items": Replace(updated_assets),
            "box3_total_assets_jan1": new_total,
            "last_command": "remove-asset"
        }
        
        logger.info(f"Removing {removed_count} Box 3 assets. New total: {new_total}")
        
        self.graph.update_state(config, state_updates)
        
        # Retrieve and return updated state
        updated_state = get_thread_state(
            self.graph.checkpointer,
            self.thread_id
        )
        
        return updated_state

    def calculate_taxes(self) -> TaxGraphState:
        """Trigger Box 3 calculation.
        
        Returns:
            Final TaxGraphState with calculations complete
        """
        console.print("\n[bold]Phase 3: Tax Calculation[/bold]")

        # Update state to trigger calculation
        updates = {
            "next_action": "calculate",
            "last_command": "calculate"
        }

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Running Box 3 calculations...")
            
            try:
                # Update state and resume execution
                config = {"configurable": {"thread_id": self.thread_id}}
                logger.info(f"Applying state updates: {list(updates.keys())}")
                self.graph.update_state(config, updates)
                
                # Resume execution with None input (continues from checkpoint)
                logger.info(f"Resuming graph execution (thread: {self.thread_id})")
                final_state_dict = None
                for event in self.graph.stream(None, config=config, stream_mode="updates"):
                    node_name = list(event.keys())[0] if event else "unknown"
                    logger.info(f"Graph executing node: {node_name}")
                    if node_name != "__interrupt__":
                        final_state_dict = list(event.values())[0] if event else None
                
                # If stream didn't yield any non-interrupt events, get state from checkpoint
                if final_state_dict is None:
                    logger.warning("Stream yielded no non-interrupt events, getting state from checkpoint")
                    from dutch_tax_agent.checkpoint_utils import get_checkpoint_state
                    final_state_dict = get_checkpoint_state(self.graph.checkpointer, self.thread_id)
                
                # LangGraph returns dict, convert to TaxGraphState for type safety
                final_state = TaxGraphState(**final_state_dict) if isinstance(final_state_dict, dict) else final_state_dict
                progress.update(task, description="Calculation complete!", completed=True)
            except Exception as e:
                console.print(f"[red]❌ Calculation failed: {e}[/red]")
                raise

        # Display results
        self._display_results(final_state)

        return final_state

    def get_status(self) -> dict:
        """Get current thread status.
        
        Returns:
            Dict with thread status information
        """
        # Try to get state from checkpoint
        state = get_thread_state(
            self.graph.checkpointer,
            self.thread_id
        )
        if not state:
            return {
                "error": "Thread not found or checkpoint state could not be loaded. "
                        "The checkpoint may be corrupted or in an unexpected format.",
                "thread_id": self.thread_id,
            }

        # Prepare Box 3 asset items for display
        box3_items_data = []
        for asset in state.box3_asset_items:
            box3_items_data.append({
                "description": asset.description or "Unknown",
                "asset_type": asset.asset_type,
                "account_number": asset.account_number or "",
                "source_filename": asset.source_filename,
                "jan1": asset.value_eur_jan1,
                "dec31": asset.value_eur_dec31 or 0.0,
                "deposits": asset.deposits_eur,
                "withdrawals": asset.withdrawals_eur,
                "direct_income": asset.realized_gains_eur,  # Using realized_gains_eur as direct income placeholder (preserve None for "unknown")
                "actual_return": asset.actual_return_eur,
            })
        
        return {
            "thread_id": self.thread_id,
            "status": state.status,
            "tax_year": state.tax_year,
            "documents_processed": len(state.processed_documents),
            "documents": [
                {
                    "id": doc["id"],
                    "filename": doc["filename"],
                    "pages": doc["page_count"]
                }
                for doc in state.processed_documents
            ],
            "box1_total": state.box1_total_income,
            "box3_total": state.box3_total_assets_jan1,
            "box3_items": box3_items_data,
            "validation_errors": state.validation_errors,
            "validation_warnings": state.validation_warnings,
            "awaiting_action": state.next_action
        }

    def _display_ingestion_summary(self, state: TaxGraphState) -> None:
        """Display summary after ingestion.
        
        Args:
            state: Current graph state (TaxGraphState object)
        """
        console.print("\n[bold]📄 Document Processing Summary[/bold]\n")
        
        console.print(f"[bold]Documents:[/bold] {len(state.processed_documents)}")
        for doc in state.processed_documents:
            console.print(f"  • {doc['filename']} ({doc['page_count']} pages)")
        
        console.print(f"\n[bold cyan]Box 1: Income[/bold cyan]")
        console.print(f"Total: [green]€{state.box1_total_income:,.2f}[/green]")
        console.print(f"Items: {len(state.box1_income_items)}")

        console.print(f"\n[bold cyan]Box 3: Assets (Jan 1, {state.tax_year})[/bold cyan]")
        console.print(f"Total: [green]€{state.box3_total_assets_jan1:,.2f}[/green]")
        console.print(f"Items: {len(state.box3_asset_items)}")
        
        # Display Box 3 assets table
        if state.box3_asset_items:
            from dutch_tax_agent.display_utils import print_box3_assets_table
            print_box3_assets_table(state.box3_asset_items)

        if state.validation_warnings:
            console.print(f"\n[yellow]⚠️  Warnings ({len(state.validation_warnings)}):[/yellow]")
            for warning in state.validation_warnings:
                console.print(f"  • {warning}")

        if state.validation_errors:
            console.print(f"\n[red]❌ Errors ({len(state.validation_errors)}):[/red]")
            for error in state.validation_errors:
                console.print(f"  • {error}")

        console.print(f"\n[yellow]⏸  Paused - awaiting command[/yellow]")
        console.print(f"[dim]Use 'dutch-tax-agent calculate --thread-id {self.thread_id}' to proceed[/dim]")

    def _display_results(self, state: TaxGraphState) -> None:
        """Display the final results in a nice format.
        
        Args:
            state: Final graph state (TaxGraphState object)
        """
        console.print("\n[bold]📊 Tax Calculation Results[/bold]\n")

        # Box 1 Summary
        console.print("[bold cyan]Box 1: Income from Employment[/bold cyan]")
        console.print(f"Total Income: [green]€{state.box1_total_income:,.2f}[/green]")
        console.print(f"Items: {len(state.box1_income_items)}")

        # Box 3 Summary
        console.print(f"\n[bold cyan]Box 3: Wealth (Jan 1, {state.tax_year})[/bold cyan]")
        console.print(f"Total Assets: [green]€{state.box3_total_assets_jan1:,.2f}[/green]")
        console.print(f"Items: {len(state.box3_asset_items)}")

        # Box 3 Calculations
        fictional = state.box3_fictional_yield_result
        actual = state.box3_actual_return_result
        recommendation_reasoning = state.recommendation_reasoning
        
        if fictional and actual:
            console.print("\n[bold yellow]Box 3 Tax Comparison[/bold yellow]")

            console.print("\n[bold]Method A: Fictional Yield (Old Law)[/bold]")
            console.print(f"  Deemed Income: €{fictional.deemed_income:,.2f}")
            console.print(f"  Tax Owed: [red]€{fictional.tax_owed:,.2f}[/red]")

            console.print("\n[bold]Method B: Actual Return (New Law)[/bold]")
            console.print(f"  Actual Gains: €{actual.actual_gains or 0:,.2f}")
            console.print(f"  Tax Owed: [red]€{actual.tax_owed:,.2f}[/red]")

            difference = fictional.tax_owed - actual.tax_owed
            if difference > 0:
                console.print(
                    f"\n[bold green]💰 Potential Savings: €{difference:,.2f}[/bold green]"
                )
            else:
                console.print(
                    f"\n[bold yellow]⚠️  Actual Return method costs €{abs(difference):,.2f} more[/bold yellow]"
                )

            if recommendation_reasoning:
                console.print("\n[bold]Recommendation:[/bold]")
                console.print(recommendation_reasoning)

        # Warnings & Errors
        if state.validation_warnings:
            console.print(f"\n[bold yellow]⚠️  Warnings ({len(state.validation_warnings)}):[/bold yellow]")
            for warning in state.validation_warnings:
                console.print(f"  • {warning}")

        if state.validation_errors:
            console.print(f"\n[bold red]❌ Errors ({len(state.validation_errors)}):[/bold red]")
            for error in state.validation_errors:
                console.print(f"  • {error}")

