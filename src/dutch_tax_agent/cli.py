"""Command-line interface for Dutch Tax Agent with HITL support."""

import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from dutch_tax_agent.agent import DutchTaxAgent
from dutch_tax_agent.checkpoint_utils import list_all_threads, thread_exists
from dutch_tax_agent.graph import create_tax_graph

app = typer.Typer(
    name="dutch-tax-agent",
    help="Dutch Tax Agent - Zero-Trust AI Tax Assistant with Human-in-the-Loop",
    add_completion=False,
)
console = Console()


@app.command()
def ingest(
    input_dir: Path = typer.Option(..., "--input-dir", "-i", help="Directory containing PDF tax documents"),
    year: int = typer.Option(2024, "--year", "-y", help="Tax year to process (2022-2025)"),
    thread_id: Optional[str] = typer.Option(None, "--thread-id", "-t", help="Thread ID (for adding to existing thread)"),
    no_fiscal_partner: bool = typer.Option(False, "--no-fiscal-partner", help="Disable fiscal partnership"),
):
    """Process documents and add to thread.
    
    If thread_id is not provided, creates a new thread.
    If thread_id is provided, adds documents to existing thread.
    """
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

    # Determine if this is initial or incremental ingestion
    is_initial = thread_id is None

    # Create agent
    agent = DutchTaxAgent(
        thread_id=thread_id,
        tax_year=year,
        has_fiscal_partner=not no_fiscal_partner
    )

    try:
        state = agent.ingest_documents(pdf_files, is_initial=is_initial)
        
        if is_initial:
            console.print(f"\n[green]✓[/green] Created thread: [bold]{agent.thread_id}[/bold]")
        else:
            console.print(f"\n[green]✓[/green] Updated thread: [bold]{agent.thread_id}[/bold]")
            
    except Exception as e:
        console.print(f"[bold red]Error: {e}[/bold red]")
        raise typer.Exit(1)


@app.command()
def status(
    thread_id: str = typer.Option(..., "--thread-id", "-t", help="Thread ID to view"),
):
    """Show thread status and extracted data."""
    
    agent = DutchTaxAgent(thread_id=thread_id)
    
    try:
        status_info = agent.get_status()
        
        if "error" in status_info:
            console.print(f"[red]Error: {status_info['error']}[/red]")
            raise typer.Exit(1)
        
        # Display status
        console.print(f"\n[bold blue]Thread: {status_info['thread_id']}[/bold blue]\n")
        console.print(f"[bold]Status:[/bold] {status_info['status']}")
        console.print(f"[bold]Tax Year:[/bold] {status_info['tax_year']}")
        console.print(f"[bold]Next Action:[/bold] {status_info['awaiting_action']}")
        
        # Documents table
        console.print(f"\n[bold]Documents ({status_info['documents_processed']}):[/bold]")
        if status_info['documents']:
            doc_table = Table(show_header=True, header_style="bold cyan")
            doc_table.add_column("ID", style="dim")
            doc_table.add_column("Filename")
            doc_table.add_column("Pages", justify="right")
            
            for doc in status_info['documents']:
                doc_table.add_row(doc['id'], doc['filename'], str(doc['pages']))
            
            console.print(doc_table)
        else:
            console.print("  [dim]No documents processed[/dim]")
        
        # Financial summary
        console.print(f"\n[bold cyan]Box 1: Income[/bold cyan]")
        console.print(f"  Total: [green]€{status_info['box1_total']:,.2f}[/green]")
        
        console.print(f"\n[bold cyan]Box 3: Assets[/bold cyan]")
        console.print(f"  Total: [green]€{status_info['box3_total']:,.2f}[/green]")
        
        # Display Box 3 assets table (same format as aggregator)
        if status_info.get('box3_items'):
            box3_table = Table(title="Box 3 Assets", show_header=True, header_style="bold magenta")
            box3_table.add_column("Description", style="cyan", no_wrap=False)
            box3_table.add_column("Asset Type", style="green")
            box3_table.add_column("Account Number", style="yellow")
            box3_table.add_column("Source File", style="blue", no_wrap=False)
            box3_table.add_column("Jan 1 (€)", justify="right", style="bold")
            box3_table.add_column("Dec 31 (€)", justify="right", style="bold")
            box3_table.add_column("Notes", style="dim", no_wrap=False)
            
            for asset_data in status_info['box3_items']:
                account_num = asset_data["account_number"]
                if account_num:
                    account_num_text = Text(account_num, style="bold cyan")
                else:
                    account_num_text = ""
                
                box3_table.add_row(
                    asset_data["description"],
                    asset_data["asset_type"],
                    account_num_text,
                    asset_data["source_filename"],
                    f"{asset_data['jan1']:,.2f}",
                    f"{asset_data['dec31']:,.2f}",
                    "",  # Notes column - empty for now
                )
            
            console.print(box3_table)
        
        # Validation
        if status_info['validation_warnings']:
            console.print(f"\n[yellow]⚠️  Warnings ({len(status_info['validation_warnings'])}):[/yellow]")
            for warning in status_info['validation_warnings']:
                console.print(f"  • {warning}")
        
        if status_info['validation_errors']:
            console.print(f"\n[red]❌ Errors ({len(status_info['validation_errors'])}):[/red]")
            for error in status_info['validation_errors']:
                console.print(f"  • {error}")
        
        # Next steps
        if status_info['awaiting_action'] == 'await_human':
            console.print(f"\n[yellow]Next steps:[/yellow]")
            console.print(f"  • Add more documents: [dim]dutch-tax-agent ingest -i <dir> -t {thread_id}[/dim]")
            console.print(f"  • Calculate taxes: [dim]dutch-tax-agent calculate -t {thread_id}[/dim]")
            console.print(f"  • Remove documents: [dim]dutch-tax-agent remove -t {thread_id} -d <id>[/dim]")
        
    except Exception as e:
        console.print(f"[bold red]Error: {e}[/bold red]")
        raise typer.Exit(1)


@app.command()
def calculate(
    thread_id: str = typer.Option(..., "--thread-id", "-t", help="Thread ID to calculate"),
):
    """Calculate taxes for a thread."""
    
    agent = DutchTaxAgent(thread_id=thread_id)
    
    try:
        agent.calculate_taxes()
        console.print("\n[bold green]✓ Tax calculation complete![/bold green]\n")
    except Exception as e:
        console.print(f"[bold red]Error: {e}[/bold red]")
        raise typer.Exit(1)


@app.command()
def remove(
    thread_id: str = typer.Option(..., "--thread-id", "-t", help="Thread ID"),
    doc_id: Optional[list[str]] = typer.Option(None, "--doc-id", "-d", help="Document ID(s) to remove"),
    filename: Optional[list[str]] = typer.Option(None, "--filename", help="Filename(s) to remove"),
    all: bool = typer.Option(False, "--all", help="Remove all documents"),
):
    """Remove processed documents from a thread."""
    
    if not doc_id and not filename and not all:
        console.print("[red]Error: Must specify -d/--doc-id, --filename, or --all[/red]")
        raise typer.Exit(1)
    
    if all:
        # Confirm
        confirmed = typer.confirm("Remove ALL documents from this thread?")
        if not confirmed:
            console.print("Cancelled")
            raise typer.Exit(0)
    
    agent = DutchTaxAgent(thread_id=thread_id)
    
    try:
        agent.remove_documents(
            doc_ids=doc_id,
            filenames=filename,
            remove_all=all
        )
        console.print("\n[green]✓ Documents removed and totals recalculated[/green]\n")
        
        # Show updated status
        console.print("[dim]Updated status:[/dim]")
        status_info = agent.get_status()
        console.print(f"  Documents: {status_info['documents_processed']}")
        console.print(f"  Box 1 Total: €{status_info['box1_total']:,.2f}")
        console.print(f"  Box 3 Total: €{status_info['box3_total']:,.2f}")
        
    except Exception as e:
        console.print(f"[bold red]Error: {e}[/bold red]")
        raise typer.Exit(1)


@app.command()
def threads(
    limit: int = typer.Option(50, "--limit", "-l", help="Maximum number of threads to show"),
):
    """List all threads."""
    
    graph = create_tax_graph()
    
    try:
        threads_list = list_all_threads(graph.checkpointer, limit=limit)
        
        if not threads_list:
            console.print("[dim]No threads found[/dim]")
            return
        
        console.print(f"\n[bold]Threads ({len(threads_list)}):[/bold]\n")
        
        threads_table = Table(show_header=True, header_style="bold cyan")
        threads_table.add_column("Thread ID", style="cyan")
        threads_table.add_column("Tax Year", justify="center")
        threads_table.add_column("Documents", justify="right")
        threads_table.add_column("Next Action", style="dim")
        threads_table.add_column("Last Updated", style="dim")
        
        for thread in threads_list:
            threads_table.add_row(
                thread['thread_id'],
                str(thread['tax_year']),
                str(thread['document_count']),
                thread['next_action'],
                thread['last_updated'].split('T')[0] if thread['last_updated'] else "N/A"
            )
        
        console.print(threads_table)
        
    except Exception as e:
        console.print(f"[bold red]Error: {e}[/bold red]")
        raise typer.Exit(1)


@app.command()
def version():
    """Show version information."""
    try:
        from dutch_tax_agent import __version__
        console.print(f"Dutch Tax Agent v{__version__}")
    except ImportError:
        console.print("Dutch Tax Agent (version unknown)")


if __name__ == "__main__":
    app()
