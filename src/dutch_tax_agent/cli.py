"""Command-line interface for Dutch Tax Agent."""

from pathlib import Path

import typer
from rich.console import Console

from dutch_tax_agent.main import DutchTaxAgent

app = typer.Typer(
    name="dutch-tax-agent",
    help="Dutch Tax Agent - Zero-Trust AI Tax Assistant",
    add_completion=False,
)
console = Console()


@app.command()
def process(
    input_dir: Path = typer.Option(
        Path("./sample_docs"),
        "--input-dir",
        "-i",
        help="Directory containing PDF tax documents",
    ),
    tax_year: int = typer.Option(
        2024,
        "--year",
        "-y",
        help="Tax year to process (2022-2025)",
    ),
    no_fiscal_partner: bool = typer.Option(
        False,
        "--no-fiscal-partner",
        help="Disable fiscal partnership optimization (default: fiscal partner assumed)",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose logging",
    ),
) -> None:
    """Process tax documents and generate report."""

    if not input_dir.exists():
        console.print(f"[red]Error: Directory not found: {input_dir}[/red]")
        raise typer.Exit(1)

    # Find PDFs (case-insensitive: .pdf, .PDF, .Pdf, etc.)
    pdf_files = [
        f for f in input_dir.iterdir()
        if f.is_file() and f.suffix.lower() == ".pdf"
    ]

    if not pdf_files:
        console.print(f"[red]Error: No PDF files found in {input_dir}[/red]")
        raise typer.Exit(1)

    console.print(f"[bold]Found {len(pdf_files)} PDF files[/bold]\n")

    # Create and run agent
    agent = DutchTaxAgent(tax_year=tax_year, has_fiscal_partner=not no_fiscal_partner)

    try:
        agent.process_documents(pdf_files)
        console.print("\n[bold green]✓ Processing complete![/bold green]\n")
    except Exception as e:
        console.print(f"[bold red]Error: {e}[/bold red]")
        raise typer.Exit(1)


@app.command()
def version() -> None:
    """Show version information."""
    from dutch_tax_agent import __version__

    console.print(f"Dutch Tax Agent v{__version__}")


if __name__ == "__main__":
    app()

