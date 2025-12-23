"""Main entry point for the Dutch Tax Agent."""

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.logging import RichHandler
from rich.progress import Progress, SpinnerColumn, TextColumn

from dutch_tax_agent.checkpoint_utils import generate_thread_id
from dutch_tax_agent.config import settings
from dutch_tax_agent.graph import create_tax_graph
from dutch_tax_agent.ingestion import PDFParser, PIIScrubber
from dutch_tax_agent.schemas.state import TaxGraphState

# Setup logging
console = Console()
logging.basicConfig(
    level=settings.log_level,
    format="%(message)s",
    handlers=[RichHandler(rich_tracebacks=True, console=console)],
)

# Suppress verbose Presidio logging
logging.getLogger("presidio_analyzer").setLevel(logging.WARNING)
logging.getLogger("presidio_anonymizer").setLevel(logging.WARNING)
# Suppress specific Presidio internal loggers that generate INFO/WARNING messages
logging.getLogger("presidio_analyzer.entity_recognizer").setLevel(logging.ERROR)
logging.getLogger("presidio_analyzer.recognizers_loader_utils").setLevel(logging.ERROR)

logger = logging.getLogger(__name__)


class DutchTaxAgent:
    """Main orchestrator for the Dutch Tax Agent."""

    def __init__(self, tax_year: int = 2024, has_fiscal_partner: bool = True, thread_id: Optional[str] = None) -> None:
        """Initialize the tax agent.
        
        Args:
            tax_year: Tax year to process (2022-2025)
            has_fiscal_partner: Whether to assume fiscal partnership (default: True)
            thread_id: Optional thread ID for checkpointing (generated if not provided)
        """
        self.tax_year = tax_year
        self.has_fiscal_partner = has_fiscal_partner
        self.thread_id = thread_id or generate_thread_id(prefix=f"tax{tax_year}")
        self.pdf_parser = PDFParser()
        self.pii_scrubber = PIIScrubber()
        self.graph = create_tax_graph()

        logger.info(
            f"Initialized Dutch Tax Agent for tax year {tax_year} "
            f"(fiscal partner: {has_fiscal_partner}, thread: {self.thread_id})"
        )

    def process_documents(self, pdf_paths: list[Path]) -> TaxGraphState:
        """Process a list of PDF documents through the entire pipeline.
        
        Args:
            pdf_paths: List of paths to PDF files
            
        Returns:
            Final TaxGraphState with all calculations
        """
        console.print(f"\n[bold blue]🇳🇱 Dutch Tax Agent - Tax Year {self.tax_year}[/bold blue]\n")

        # Phase 1: Ingestion (Safe Zone)
        console.print("[bold]Phase 1: Document Ingestion & PII Scrubbing[/bold]")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Parsing PDFs...", total=len(pdf_paths))

            parsed_docs = []
            for pdf_path in pdf_paths:
                try:
                    result = self.pdf_parser.parse(pdf_path)
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
            logger.info(f"Parsed DOCS: {parsed_docs[0]}")

            # Scrub PII (ZERO-TRUST: Documents that fail scrubbing are excluded)
            progress.update(task, description="Scrubbing PII...")
            try:
                scrubbed_docs = self.pii_scrubber.scrub_batch(parsed_docs)
                if len(scrubbed_docs) < len(parsed_docs):
                    console.print(
                        f"[yellow]⚠️[/yellow] Scrubbed {len(scrubbed_docs)}/{len(parsed_docs)} documents "
                        f"({len(parsed_docs) - len(scrubbed_docs)} failed scrubbing and were excluded)"
                    )
                else:
                    console.print(f"[green]✓[/green] Scrubbed PII from {len(scrubbed_docs)} documents")
            except RuntimeError as e:
                console.print(f"[bold red]❌ SECURITY ERROR: {e}[/bold red]")
                console.print(
                    "[yellow]No documents will be processed to prevent PII exposure.[/yellow]"
                )
                raise

        #  TO BE REMOVED LATER
        logger.info(f"Scrubbed DOCS: {scrubbed_docs[0]}")
        return

        # Phase 2 & 3: LangGraph Processing
        console.print("\n[bold]Phase 2: LangGraph Map-Reduce Extraction[/bold]")

        # Set up fiscal partner if assumed (default behavior)
        fiscal_partner = None
        if self.has_fiscal_partner:
            from datetime import date
            from dutch_tax_agent.schemas.tax_entities import FiscalPartner
            # Default: Assume partner born after 1963 (no transferability, but can use own credit)
            # User can override this if needed via future configuration
            fiscal_partner = FiscalPartner(
                date_of_birth=date(1970, 1, 1),  # Default DOB (after 1963 threshold)
                box1_income_gross=0.0,
                is_fiscal_partner=True
            )
            logger.info("Fiscal partner assumed (default configuration)")

        initial_state = TaxGraphState(
            documents=scrubbed_docs,
            tax_year=self.tax_year,
            fiscal_partner=fiscal_partner,
        )

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Running LangGraph pipeline...")
            
            try:
                # Create config with thread_id for checkpointing
                config = {
                    "configurable": {
                        "thread_id": self.thread_id
                    }
                }
                
                if settings.enable_checkpointing:
                    logger.info(f"Executing graph with checkpointing (thread: {self.thread_id})")
                    console.print(f"[dim]Thread ID: {self.thread_id}[/dim]")
                else:
                    logger.info("Executing graph without checkpointing")
                
                # Use invoke() with config for checkpointing support
                # To trace execution, see docs/execution_flow.md
                # Or uncomment below to use streaming mode:
                # final_state = None
                # for event in self.graph.stream(initial_state, config=config):
                #     node_name = list(event.keys())[0] if event else "unknown"
                #     logger.info(f"Executing node: {node_name}")
                #     console.print(f"[dim]→ Node: {node_name}[/dim]")
                #     final_state = list(event.values())[0]
                
                final_state = self.graph.invoke(initial_state, config=config)
                progress.update(task, description="Pipeline complete!", completed=True)
            except Exception as e:
                console.print(f"[red]❌ Graph execution failed: {e}[/red]")
                raise

        # Display results
        self._display_results(final_state)

        return final_state

    def _display_results(self, state: TaxGraphState) -> None:
        """Display the final results in a nice format.
        
        Args:
            state: Final graph state
        """
        console.print("\n[bold]📊 Tax Processing Results[/bold]\n")

        # Handle both dict and Pydantic state
        if isinstance(state, dict):
            box1_total = state.get("box1_total_income", 0.0)
            box3_total = state.get("box3_total_assets_jan1", 0.0)
            box1_items = state.get("box1_income_items", [])
            box3_items = state.get("box3_asset_items", [])
            tax_year = state.get("tax_year", 2024)
        else:
            box1_total = state.box1_total_income
            box3_total = state.box3_total_assets_jan1
            box1_items = state.box1_income_items
            box3_items = state.box3_asset_items
            tax_year = state.tax_year
        
        # Box 1 Summary
        console.print("[bold cyan]Box 1: Income from Employment[/bold cyan]")
        console.print(f"Total Income: [green]€{box1_total:,.2f}[/green]")
        console.print(f"Items: {len(box1_items)}")

        # Box 3 Summary
        console.print(f"\n[bold cyan]Box 3: Wealth (Jan 1, {tax_year})[/bold cyan]")
        console.print(f"Total Assets: [green]€{box3_total:,.2f}[/green]")
        console.print(f"Items: {len(box3_items)}")

        # Box 3 Calculations
        fictional = state.get("box3_fictional_yield_result") if isinstance(state, dict) else state.box3_fictional_yield_result
        actual = state.get("box3_actual_return_result") if isinstance(state, dict) else state.box3_actual_return_result
        recommendation_reasoning = state.get("recommendation_reasoning") if isinstance(state, dict) else getattr(state, "recommendation_reasoning", None)
        
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
        validation_warnings = state.get("validation_warnings", []) if isinstance(state, dict) else state.validation_warnings
        validation_errors = state.get("validation_errors", []) if isinstance(state, dict) else state.validation_errors
        
        if validation_warnings:
            console.print(f"\n[bold yellow]⚠️  Warnings ({len(validation_warnings)}):[/bold yellow]")
            for warning in validation_warnings:
                console.print(f"  • {warning}")

        if validation_errors:
            console.print(f"\n[bold red]❌ Errors ({len(validation_errors)}):[/bold red]")
            for error in validation_errors:
                console.print(f"  • {error}")


def main(input_dir: Optional[Path] = None, tax_year: int = 2024, has_fiscal_partner: bool = True, thread_id: Optional[str] = None) -> None:
    """Main entry point.
    
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
    agent = DutchTaxAgent(tax_year=tax_year, has_fiscal_partner=has_fiscal_partner, thread_id=thread_id)

    try:
        agent.process_documents(pdf_files)
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

