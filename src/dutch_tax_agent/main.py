"""Main entry point for the Dutch Tax Agent with HITL support."""

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.logging import RichHandler
from rich.progress import Progress, SpinnerColumn, TextColumn

from dutch_tax_agent.checkpoint_utils import generate_thread_id
from dutch_tax_agent.config import settings
from dutch_tax_agent.document_manager import DocumentManager
from dutch_tax_agent.graph import create_tax_graph
from dutch_tax_agent.ingestion import PDFParser, PIIScrubber
from dutch_tax_agent.schemas.state import TaxGraphState
from dutch_tax_agent.session_manager import SessionManager

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
        self.session_manager = SessionManager()

        logger.info(
            f"Initialized Dutch Tax Agent for tax year {tax_year} "
            f"(fiscal partner: {has_fiscal_partner}, thread: {self.thread_id})"
        )

    def ingest_documents(
        self, 
        pdf_paths: list[Path],
        is_initial: bool = False
    ) -> TaxGraphState:
        """Ingest documents (initial or incremental).
        
        Args:
            pdf_paths: List of paths to PDF files
            is_initial: If True, creates new session. If False, adds to existing session.
            
        Returns:
            TaxGraphState after ingestion (paused at HITL control)
        """
        console.print(f"\n[bold blue]🇳🇱 Dutch Tax Agent - Tax Year {self.tax_year}[/bold blue]\n")

        # Get existing state if resuming
        if not is_initial:
            state = self.session_manager.get_current_state(
                self.graph.checkpointer,
                self.thread_id
            )
            if not state:
                raise ValueError(f"Session {self.thread_id} not found. Use is_initial=True to create new session.")
            
            # Find new documents (skip already processed)
            pdf_paths = self.document_manager.find_new_documents(
                pdf_paths, 
                state.processed_documents
            )
            
            if not pdf_paths:
                console.print("[yellow]⚠️  No new documents found[/yellow]")
                return state

        console.print(f"[bold]Processing {len(pdf_paths)} document(s)[/bold]\n")

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
            # Create initial state
            initial_state = TaxGraphState(
                documents=scrubbed_docs,
                tax_year=self.tax_year,
                fiscal_partner=fiscal_partner,
                session_id=self.thread_id,
                next_action="await_human",
                processed_documents=doc_metadata,
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
            
            # Register session
            self.session_manager.create_session(
                self.thread_id,
                self.tax_year,
                self.has_fiscal_partner
            )
            
        else:
            # Incremental: update state and resume
            state = self.session_manager.get_current_state(
                self.graph.checkpointer,
                self.thread_id
            )
            
            updates = {
                "documents": scrubbed_docs,
                "processed_documents": state.processed_documents + doc_metadata,
                "next_action": "ingest_more",
            }
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task = progress.add_task("Processing new documents...")
                
                try:
                    final_state_dict = self.session_manager.update_and_resume(
                        self.graph,
                        self.thread_id,
                        updates
                    )
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
        state = self.session_manager.get_current_state(
            self.graph.checkpointer,
            self.thread_id
        )
        if not state:
            raise ValueError(f"Session {self.thread_id} not found")

        # Remove documents
        updated_docs, removed_ids = self.document_manager.remove_documents(
            state.processed_documents,
            doc_ids=doc_ids,
            filenames=filenames,
            remove_all=remove_all
        )

        console.print(f"[green]✓[/green] Removed {len(removed_ids)} document(s)")

        # Recalculate totals
        updated_totals = self.document_manager.recalculate_totals_from_items(
            state.box1_income_items,
            state.box3_asset_items,
            removed_ids
        )

        # Update state (don't resume, just update checkpoint)
        config = {"configurable": {"thread_id": self.thread_id}}
        self.graph.update_state(
            config,
            {
                "processed_documents": updated_docs,
                **updated_totals,
                "last_command": "remove"
            }
        )

        # Get updated state
        updated_state = self.session_manager.get_current_state(
            self.graph.checkpointer,
            self.thread_id
        )

        console.print(f"[dim]Recalculated totals - Box 1: €{updated_state.box1_total_income:,.2f}, "
                     f"Box 3: €{updated_state.box3_total_assets_jan1:,.2f}[/dim]")

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
                final_state_dict = self.session_manager.update_and_resume(
                    self.graph,
                    self.thread_id,
                    updates
                )
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
        """Get current session status.
        
        Returns:
            Dict with session status information
        """
        # First check if session exists in registry
        session_info = self.session_manager.get_session(self.thread_id)
        if not session_info:
            return {"error": "Session not found in registry"}
        
        # Try to get state from checkpoint
        state = self.session_manager.get_current_state(
            self.graph.checkpointer,
            self.thread_id
        )
        if not state:
            # Session exists in registry but checkpoint can't be parsed
            return {
                "error": "Session found in registry but checkpoint state could not be loaded. "
                        "The checkpoint may be corrupted or in an unexpected format.",
                "session_id": self.thread_id,
                "tax_year": session_info.get("tax_year"),
                "created_at": session_info.get("created_at"),
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
            })
        
        return {
            "session_id": self.thread_id,
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


def main(input_dir: Optional[Path] = None, tax_year: int = 2024, has_fiscal_partner: bool = True, thread_id: Optional[str] = None) -> None:
    """Main entry point (legacy function for backward compatibility).
    
    Args:
        input_dir: Directory containing PDF files
        tax_year: Tax year to process (2022-2025)
        has_fiscal_partner: Whether to assume fiscal partnership (default: True)
        thread_id: Optional thread ID for resuming from checkpoint
    """
    if not input_dir:
        input_dir = Path("./sample_docs")

    if not input_dir.exists():
        console.print(f"[red]Error: Directory not found: {input_dir}[/red]")
        sys.exit(1)

    # Find all PDFs (case-insensitive: .pdf, .PDF, .Pdf, etc.)
    pdf_files = [
        f for f in input_dir.iterdir()
        if f.is_file() and f.suffix.lower() == ".pdf"
    ]

    if not pdf_files:
        console.print(f"[red]Error: No PDF files found in {input_dir}[/red]")
        sys.exit(1)

    console.print(f"[bold]Found {len(pdf_files)} PDF files[/bold]\n")

    # Create agent and process
    agent = DutchTaxAgent(thread_id=thread_id, tax_year=tax_year, has_fiscal_partner=has_fiscal_partner)

    try:
        # Use new HITL workflow
        agent.ingest_documents(pdf_files, is_initial=True)
        
        # Auto-calculate for backward compatibility
        agent.calculate_taxes()
        
    except Exception as e:
        console.print(f"[bold red]Fatal error: {e}[/bold red]")
        logger.exception("Fatal error during processing")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Dutch Tax Agent - Zero-Trust AI Tax Assistant"
    )
    parser.add_argument(
        "--input-dir",
        "-i",
        type=str,
        default="./sample_docs",
        help="Directory containing PDF tax documents (default: ./sample_docs)",
    )
    parser.add_argument(
        "--year",
        "-y",
        type=int,
        default=2024,
        help="Tax year to process (2022-2025, default: 2024)",
    )
    parser.add_argument(
        "--no-fiscal-partner",
        action="store_true",
        help="Disable fiscal partnership optimization (default: fiscal partner assumed)",
    )
    parser.add_argument(
        "--thread-id",
        "-t",
        type=str,
        default=None,
        help="Thread ID for resuming from checkpoint (generates new if not provided)",
    )
    
    args = parser.parse_args()
    
    # Expand user home directory (~) and convert to Path
    input_dir_str = os.path.expanduser(args.input_dir)
    input_dir = Path(input_dir_str)
    
    main(
        input_dir=input_dir,
        tax_year=args.year,
        has_fiscal_partner=not args.no_fiscal_partner,
        thread_id=args.thread_id
    )
