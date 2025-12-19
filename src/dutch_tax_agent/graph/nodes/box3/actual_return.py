"""Actual Return calculation node and logic for Box 3 tax (new law).

This module contains both the LangGraph node and the calculation logic.
"""

import json
import logging

from dutch_tax_agent.config import settings
from dutch_tax_agent.schemas.state import TaxGraphState
from dutch_tax_agent.schemas.tax_entities import Box3Asset, Box3Calculation

logger = logging.getLogger(__name__)


def calculate_actual_return(
    assets: list[Box3Asset],
    tax_year: int,
) -> Box3Calculation:
    """Calculate Box 3 tax using the Actual Return method.
    
    This method:
    1. Uses the actual realized gains/losses from investments
    2. Still applies the tax-free allowance
    3. Taxes the actual gains (not fictional yields)
    
    Args:
        assets: List of Box 3 assets
        tax_year: Tax year for calculation
        
    Returns:
        Box3Calculation with actual return details
    """
    logger.info(f"Calculating Box 3 using Actual Return method for {tax_year}")

    # Load rates for tax-free allowance and tax rate
    rates_path = settings.data_dir / "box3_rates_2022_2025.json"
    with open(rates_path, "r") as f:
        all_rates = json.load(f)

    rates = all_rates[str(tax_year)]

    # Calculate total wealth
    total_assets = sum(asset.value_eur_jan1 for asset in assets)
    total_debts = 0.0
    net_wealth = total_assets - total_debts

    # Calculate actual gains
    total_gains = 0.0
    total_losses = 0.0

    for asset in assets:
        if asset.realized_gains_eur:
            total_gains += asset.realized_gains_eur
        if asset.realized_losses_eur:
            total_losses += abs(asset.realized_losses_eur)

    actual_return = total_gains - total_losses

    logger.info(
        f"Actual returns: Gains = €{total_gains:,.2f}, "
        f"Losses = €{total_losses:,.2f}, "
        f"Net = €{actual_return:,.2f}"
    )

    # Apply tax-free allowance (proportional to wealth)
    tax_free_allowance = rates["tax_free_allowance"]

    # If wealth < allowance, reduce the taxable portion proportionally
    if net_wealth < tax_free_allowance:
        allowance_factor = 0.0
    else:
        allowance_factor = (net_wealth - tax_free_allowance) / net_wealth

    taxable_gains = max(0, actual_return * allowance_factor)

    logger.info(
        f"Taxable gains after allowance adjustment: €{taxable_gains:,.2f}"
    )

    # Calculate tax
    tax_rate = rates["tax_rate"]
    tax_owed = taxable_gains * tax_rate

    logger.info(
        f"Actual Return: Taxable gains = €{taxable_gains:,.2f}, "
        f"Tax (@ {tax_rate*100}%) = €{tax_owed:,.2f}"
    )

    breakdown = {
        "total_gains": total_gains,
        "total_losses": total_losses,
        "net_actual_return": actual_return,
        "allowance_factor": allowance_factor,
        "taxable_gains": taxable_gains,
    }

    return Box3Calculation(
        method="actual_return",
        tax_year=tax_year,
        total_assets_jan1=total_assets,
        total_debts_jan1=total_debts,
        net_wealth_jan1=net_wealth,
        tax_free_allowance=tax_free_allowance,
        taxable_wealth=net_wealth - tax_free_allowance,
        fictional_yield_rate=None,
        actual_gains=actual_return,
        deemed_income=taxable_gains,
        tax_rate=tax_rate,
        tax_owed=tax_owed,
        calculation_breakdown=breakdown,
    )


def actual_return_node(state: TaxGraphState) -> dict:
    """LangGraph node that calculates Box 3 using actual return method.
    
    Args:
        state: Main graph state with box3_asset_items
        
    Returns:
        Dict with actual_return_calculation result
    """
    logger.info("Running actual return calculation node")

    result = calculate_actual_return(state.box3_asset_items, state.tax_year)

    return {"box3_actual_return_result": result}

