"""Main entry point for the Dutch Tax Agent with HITL support.

This module provides a legacy entry point for backward compatibility.
The main CLI interface is in cli.py, and the core agent logic is in agent.py.
"""

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Optional

from rich.console import Console

# Import agent for backward compatibility
from dutch_tax_agent.agent import DutchTaxAgent

# Setup console for legacy CLI
console = Console()
logger = logging.getLogger(__name__)


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
