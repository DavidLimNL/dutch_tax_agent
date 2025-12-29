"""Display utilities for consistent formatting of tax data."""

from typing import Union

from rich.console import Console
from rich.table import Table
from rich.text import Text

from dutch_tax_agent.schemas.tax_entities import Box3Asset

console = Console()


def print_box3_assets_table(assets: list[Union[Box3Asset, dict]], title: str = "Box 3 Assets") -> None:
    """Print Box 3 assets in a standardized table format.
    
    Args:
        assets: List of Box3Asset objects or dictionaries containing asset data
        title: Table title (default: "Box 3 Assets")
    """
    if not assets:
        return
    
    table = Table(title=title, show_header=True, header_style="bold magenta")
    table.add_column("#", style="dim", justify="right")
    table.add_column("Description", style="cyan", no_wrap=False)
    table.add_column("Asset Type", style="green")
    table.add_column("Account Number", style="yellow")
    table.add_column("Source File", style="blue", no_wrap=False)
    table.add_column("Jan 1 (€)", justify="right", style="bold")
    table.add_column("Dec 31 (€)", justify="right", style="bold")
    table.add_column("Deposits (€)", justify="right", style="dim")
    table.add_column("Withdrawals (€)", justify="right", style="dim")
    table.add_column("Direct Income (€)", justify="right", style="dim")
    table.add_column("Actual Return (€)", justify="right", style="bold")
    table.add_column("Notes", style="dim", no_wrap=False)
    
    for i, asset in enumerate(assets):
        # Handle both Box3Asset objects and dictionaries
        if isinstance(asset, Box3Asset):
            account_num = asset.account_number
            description = asset.description or "Unknown"
            asset_type = asset.asset_type
            source_filename = asset.source_filename
            jan1 = asset.value_eur_jan1
            dec31 = asset.value_eur_dec31 or 0.0
            deposits = asset.deposits_eur
            withdrawals = asset.withdrawals_eur
            direct_income = asset.realized_gains_eur
            actual_return = asset.actual_return_eur
            notes = ""  # Notes column - empty for now
        else:
            # Dictionary format (from get_status())
            account_num = asset.get("account_number")
            description = asset.get("description", "Unknown")
            asset_type = asset.get("asset_type", "")
            source_filename = asset.get("source_filename", "")
            jan1 = asset.get("jan1", 0.0)
            dec31 = asset.get("dec31", 0.0)
            deposits = asset.get("deposits")
            withdrawals = asset.get("withdrawals")
            direct_income = asset.get("direct_income")
            actual_return = asset.get("actual_return")
            notes = asset.get("notes", "")
        
        # Format account number
        if account_num:
            account_num_text = Text(account_num, style="bold cyan")
        else:
            account_num_text = ""
        
        # Format optional numeric fields, showing "unknown" if None
        deposits_str = f"{deposits:,.2f}" if deposits is not None else "unknown"
        withdrawals_str = f"{withdrawals:,.2f}" if withdrawals is not None else "unknown"
        direct_income_str = f"{direct_income:,.2f}" if direct_income is not None else "unknown"
        actual_return_str = f"{actual_return:,.2f}" if actual_return is not None else "unknown"
        
        table.add_row(
            str(i),
            description,
            asset_type,
            account_num_text,
            source_filename,
            f"{jan1:,.2f}",
            f"{dec31:,.2f}",
            deposits_str,
            withdrawals_str,
            direct_income_str,
            actual_return_str,
            notes if notes else "",
        )
    
    console.print(table)

