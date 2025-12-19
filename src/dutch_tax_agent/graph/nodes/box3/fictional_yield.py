"""Fictional Yield calculation node and logic for Box 3 tax (old law).

This module contains both the LangGraph node and the calculation logic.
"""

import json
import logging

from dutch_tax_agent.config import settings
from dutch_tax_agent.schemas.state import TaxGraphState
from dutch_tax_agent.schemas.tax_entities import Box3Asset, Box3Calculation

logger = logging.getLogger(__name__)


def load_box3_rates(tax_year: int) -> dict:
    """Load Box 3 rates for a specific tax year.
    
    Args:
        tax_year: Tax year (2022-2025)
        
    Returns:
        Dict with tax_free_allowance, tax_rate, and brackets
        
    Raises:
        ValueError: If tax year not supported
    """
    rates_path = settings.data_dir / "box3_rates_2022_2025.json"

    with open(rates_path, "r") as f:
        all_rates = json.load(f)

    year_str = str(tax_year)
    if year_str not in all_rates:
        raise ValueError(f"Box 3 rates not available for year {tax_year}")

    return all_rates[year_str]


def calculate_fictional_yield(
    assets: list[Box3Asset],
    tax_year: int,
) -> Box3Calculation:
    """Calculate Box 3 tax using the Fictional Yield method.
    
    This method:
    1. Assumes assets are split between "savings" and "investments"
    2. Applies different fictional yield rates to each category
    3. Calculates deemed income based on these fictional yields
    4. Applies the Box 3 tax rate
    
    Args:
        assets: List of Box 3 assets
        tax_year: Tax year for calculation
        
    Returns:
        Box3Calculation with detailed breakdown
    """
    logger.info(f"Calculating Box 3 using Fictional Yield method for {tax_year}")

    # Load rates for this year
    rates = load_box3_rates(tax_year)

    # Calculate total wealth
    total_assets = sum(asset.value_eur_jan1 for asset in assets)
    total_debts = 0.0  # TODO: Add debt tracking if needed
    net_wealth = total_assets - total_debts

    logger.info(f"Total net wealth on Jan 1: €{net_wealth:,.2f}")

    # Apply tax-free allowance
    tax_free_allowance = rates["tax_free_allowance"]
    taxable_wealth = max(0, net_wealth - tax_free_allowance)

    logger.info(
        f"Taxable wealth after €{tax_free_allowance:,.2f} allowance: "
        f"€{taxable_wealth:,.2f}"
    )

    # Calculate actual savings vs investments from extracted assets
    # This uses the actual asset_type from documents (more accurate than bracket percentages)
    actual_savings = sum(
        asset.value_eur_jan1
        for asset in assets
        if asset.asset_type == "savings"
    )
    actual_investments = sum(
        asset.value_eur_jan1
        for asset in assets
        if asset.asset_type in ["stocks", "bonds", "crypto", "other"]
    )

    logger.info(
        f"Asset breakdown: Savings = €{actual_savings:,.2f}, "
        f"Investments = €{actual_investments:,.2f}"
    )

    # Determine which bracket(s) apply
    brackets = rates["brackets"]
    deemed_income = 0.0
    breakdown = {}

    for bracket in brackets:
        bracket_min = bracket["min_wealth"]
        bracket_max = bracket["max_wealth"]

        # Determine amount of wealth in this bracket
        if bracket_max is None:
            # Unlimited upper bracket
            wealth_in_bracket = max(0, taxable_wealth - bracket_min)
        else:
            wealth_in_bracket = max(
                0,
                min(taxable_wealth, bracket_max) - bracket_min
            )

        if wealth_in_bracket <= 0:
            continue

        # Use actual asset breakdown if available, otherwise fall back to bracket percentages
        if actual_savings + actual_investments > 0:
            # Calculate proportion of savings vs investments
            total_typed_assets = actual_savings + actual_investments
            savings_ratio = actual_savings / total_typed_assets
            investments_ratio = actual_investments / total_typed_assets

            # Apply these ratios to wealth in this bracket
            savings_portion = wealth_in_bracket * savings_ratio
            investments_portion = wealth_in_bracket * investments_ratio

            logger.debug(
                f"Using actual asset breakdown: {savings_ratio*100:.1f}% savings, "
                f"{investments_ratio*100:.1f}% investments"
            )
        else:
            # Fall back to bracket percentages if no asset types specified
            savings_portion = wealth_in_bracket * bracket["savings_percentage"]
            investments_portion = wealth_in_bracket * bracket["investments_percentage"]

            logger.debug(
                f"Using bracket percentages: {bracket['savings_percentage']*100:.1f}% savings, "
                f"{bracket['investments_percentage']*100:.1f}% investments"
            )

        # Apply fictional yields
        savings_yield = savings_portion * bracket["fictional_yield_savings"]
        investments_yield = investments_portion * bracket["fictional_yield_investments"]

        bracket_deemed_income = savings_yield + investments_yield
        deemed_income += bracket_deemed_income

        # Track for transparency
        bracket_key = f"bracket_{bracket_min}_to_{bracket_max or 'unlimited'}"
        breakdown[bracket_key] = {
            "wealth_in_bracket": wealth_in_bracket,
            "savings_portion": savings_portion,
            "investments_portion": investments_portion,
            "deemed_income": bracket_deemed_income,
            "uses_actual_asset_types": actual_savings + actual_investments > 0,
        }

        logger.debug(
            f"Bracket {bracket_min}-{bracket_max or 'unlimited'}: "
            f"€{wealth_in_bracket:,.2f} -> €{bracket_deemed_income:,.2f} deemed income"
        )

    # Calculate tax
    tax_rate = rates["tax_rate"]
    tax_owed = deemed_income * tax_rate

    logger.info(
        f"Fictional Yield: Deemed income = €{deemed_income:,.2f}, "
        f"Tax (@ {tax_rate*100}%) = €{tax_owed:,.2f}"
    )

    return Box3Calculation(
        method="fictional_yield",
        tax_year=tax_year,
        total_assets_jan1=total_assets,
        total_debts_jan1=total_debts,
        net_wealth_jan1=net_wealth,
        tax_free_allowance=tax_free_allowance,
        taxable_wealth=taxable_wealth,
        fictional_yield_rate=None,  # Varies by bracket
        actual_gains=None,
        deemed_income=deemed_income,
        tax_rate=tax_rate,
        tax_owed=tax_owed,
        calculation_breakdown=breakdown,
    )


def fictional_yield_node(state: TaxGraphState) -> dict:
    """LangGraph node that calculates Box 3 using fictional yield method.
    
    Args:
        state: Main graph state with box3_asset_items
        
    Returns:
        Dict with fictional_yield_calculation result
    """
    logger.info("Running fictional yield calculation node")

    result = calculate_fictional_yield(state.box3_asset_items, state.tax_year)

    return {"box3_fictional_yield_result": result}

