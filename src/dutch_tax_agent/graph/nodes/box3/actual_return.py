"""Actual Return calculation node and logic for Box 3 tax (Hoge Raad method).

This module contains both the LangGraph node and the calculation logic.
"""

import json
import logging

from dutch_tax_agent.config import settings
from dutch_tax_agent.graph.nodes.box3.optimization import optimize_partner_allocation
from dutch_tax_agent.schemas.state import TaxGraphState
from dutch_tax_agent.schemas.tax_entities import Box3Asset, Box3Calculation

logger = logging.getLogger(__name__)


def calculate_actual_return(
    assets: list[Box3Asset],
    tax_year: int,
    fiscal_partners: bool = False
) -> Box3Calculation:
    """Calculate Box 3 tax using the Actual Return method (Rebuttal Scheme).
    
    Formula per Hoge Raad:
    Return = Direct Returns (Interest + Dividends + Rent) 
             + Indirect Returns (Value_End - Value_Start - Deposits + Withdrawals)
             - Costs (Generally not deductible, except debt interest)
             
    Note: Unrealized gains ARE taxable.
    """
    logger.info(f"Calculating Box 3 using Actual Return method for {tax_year}")

    # Load rates for tax-free allowance and tax rate
    rates_path = settings.data_dir / "box3_rates_2022_2025.json"
    with open(rates_path, "r") as f:
        all_rates = json.load(f)

    rates = all_rates[str(tax_year)]

    # Calculate total wealth (Jan 1)
    total_assets = sum(asset.value_eur_jan1 for asset in assets)
    total_debts = 0.0 # TODO: Handle debts if present
    net_wealth = total_assets - total_debts

    # Calculate Actual Return components
    direct_return = 0.0
    indirect_return = 0.0
    
    for asset in assets:
        # Direct: Dividends, Interest, etc.
        if asset.realized_gains_eur:
            direct_return += asset.realized_gains_eur
            
        # Indirect: Value changes (Unrealized)
        # Only if we have end-of-year value. If not, we might assume 0 change or missing data.
        if asset.value_eur_dec31 is not None:
            start_val = asset.value_eur_jan1
            end_val = asset.value_eur_dec31
            dep = asset.deposits_eur or 0.0
            withd = asset.withdrawals_eur or 0.0
            
            # Delta = (End - Start - Deposits + Withdrawals)
            delta = end_val - start_val - dep + withd
            indirect_return += delta
            
    total_actual_return = direct_return + indirect_return
    
    logger.info(
        f"Actual returns: Direct = €{direct_return:,.2f}, "
        f"Indirect (Unrealized) = €{indirect_return:,.2f}, "
        f"Total = €{total_actual_return:,.2f}"
    )

    # Calculate tax
    # IMPORTANT: Per Hoge Raad ruling, the tax-free allowance is NOT used 
    # in the actual return calculation itself. The comparison is:
    # Theoretical_Tax_Actual = Actual_Return_Total * Tax_Rate
    # Final_Tax = Min(Statutory_Tax, Theoretical_Tax_Actual)
    # The allowance influences the statutory calculation, but not this one.
    tax_rate = rates["tax_rate"]
    theoretical_tax = total_actual_return * tax_rate
    
    # If actual return is negative, tax is 0
    if theoretical_tax < 0:
        theoretical_tax = 0.0

    breakdown = {
        "direct_return": direct_return,
        "indirect_return": indirect_return,
        "total_actual_return": total_actual_return,
        "note": "Includes unrealized gains (paper gains)."
    }

    return Box3Calculation(
        method="actual_return",
        tax_year=tax_year,
        total_assets_jan1=total_assets,
        total_debts_jan1=total_debts,
        net_wealth_jan1=net_wealth,
        tax_free_allowance=rates["tax_free_allowance"] * (2 if fiscal_partners else 1),
        taxable_wealth=net_wealth, # Not relevant for this calc but kept for schema
        deemed_income=total_actual_return,
        tax_rate=tax_rate,
        tax_owed=theoretical_tax,
        calculation_breakdown=breakdown,
        actual_gains=total_actual_return
    )


def actual_return_node(state: TaxGraphState) -> dict:
    """LangGraph node that calculates Box 3 using actual return method with fiscal partner optimization."""
    logger.info("Running actual return calculation node")
    
    has_partner = state.fiscal_partner is not None and state.fiscal_partner.is_fiscal_partner

    result = calculate_actual_return(
        state.box3_asset_items, 
        state.tax_year,
        has_partner
    )
    
    # Apply fiscal partner optimization if applicable
    if has_partner and state.fiscal_partner:
        partner_dob = state.fiscal_partner.date_of_birth
        result = optimize_partner_allocation(
            result,
            partner_dob.year,
            state.tax_year
        )

    return {"box3_actual_return_result": result}
