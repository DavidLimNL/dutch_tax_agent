"""Statutory (Fictional) Box 3 tax calculation.

This module implements:
1. The "Savings Variant" (Spaarvariant) - Standard for 2023-2025 (and opt-in for 2022).
2. The "Legacy Method" (Old Bracket System) - Applicable only for 2022.

For 2022, it automatically calculates both and selects the most favorable one.
"""

import json
import logging
from typing import Optional

from dutch_tax_agent.config import settings
from dutch_tax_agent.graph.nodes.box3.optimization import optimize_partner_allocation
from dutch_tax_agent.schemas.state import TaxGraphState
from dutch_tax_agent.schemas.tax_entities import Box3Asset, Box3Calculation

logger = logging.getLogger(__name__)


def load_rates(tax_year: int) -> dict:
    """Load Box 3 rates for a specific tax year."""
    rates_path = settings.data_dir / "box3_rates_2022_2025.json"
    with open(rates_path, "r") as f:
        all_rates = json.load(f)
    
    year_str = str(tax_year)
    if year_str not in all_rates:
        raise ValueError(f"Box 3 rates not available for year {tax_year}")
    
    return all_rates[year_str]


def _calculate_legacy_2022(
    assets: list[Box3Asset],
    rates: dict,
    fiscal_partners: bool = False
) -> Box3Calculation:
    """Calculate 2022 tax using the old bracket-based mix method."""
    tax_free_allowance = rates["tax_free_allowance"] * (2 if fiscal_partners else 1)
    
    # Exclude mortgages and debts from total_assets (they're liabilities, not assets)
    total_assets = sum(a.value_eur_jan1 for a in assets if a.asset_type not in ["mortgage", "debt"])
    # TODO: Mortgages and debts are extracted separately but not yet included in calculations
    # Mortgages (asset_type="mortgage") and other debts (asset_type="debt") are handled differently by tax office
    total_debts = 0.0
    
    net_wealth = total_assets - total_debts
    taxable_wealth = max(0, net_wealth - tax_free_allowance)
    
    legacy_params = rates["legacy_system"]
    brackets = legacy_params["brackets"]
    
    deemed_income = 0.0
    breakdown = {}
    
    # Logic: Fill brackets sequentially
    remaining_wealth = taxable_wealth
    current_floor = 0.0
    
    for i, bracket in enumerate(brackets):
        if remaining_wealth <= 0:
            break
            
        width = (bracket["max_wealth"] - bracket["min_wealth"]) if bracket["max_wealth"] else float('inf')
        
        # In the old system, the bracket applied to the chunk of wealth
        in_bracket = min(remaining_wealth, width)
        
        savings_part = in_bracket * bracket["savings_percentage"]
        invest_part = in_bracket * bracket["investments_percentage"]
        
        income = (savings_part * bracket["yield_savings"]) + (invest_part * bracket["yield_investments"])
        deemed_income += income
        
        breakdown[f"legacy_bracket_{i+1}"] = {
            "amount_in_bracket": in_bracket,
            "savings_part": savings_part,
            "invest_part": invest_part,
            "yield": income
        }
        
        remaining_wealth -= in_bracket

    tax_owed = deemed_income * rates["tax_rate"]
    
    return Box3Calculation(
        method="fictional_yield", # Internal marker, refined in wrapper
        tax_year=2022,
        total_assets_jan1=total_assets,
        total_debts_jan1=total_debts,
        net_wealth_jan1=net_wealth,
        tax_free_allowance=tax_free_allowance,
        taxable_wealth=taxable_wealth,
        deemed_income=deemed_income,
        tax_rate=rates["tax_rate"],
        tax_owed=tax_owed,
        calculation_breakdown=breakdown
    )


def _calculate_savings_variant(
    assets: list[Box3Asset],
    rates: dict,
    tax_year: int,
    fiscal_partners: bool = False
) -> Box3Calculation:
    """Calculate tax using the Savings Variant (actual allocation, fictional yield)."""
    sv_rates = rates["savings_variant"]
    
    # 1. Categorize assets per Dutch tax law (Category I, II, III)
    # Category I (Savings): Bank accounts, cash, deposits
    # Category II (Other Assets): Stocks, ETFs (mutual funds), bonds, crypto, 
    #                             real estate, loans receivable
    # Category III (Debts): Mortgage on 2nd home, student loans, consumer credit
    # Note: Primary residence mortgage is Box 1, not Box 3
    
    cat_savings = sum(a.value_eur_jan1 for a in assets if a.asset_type in ["savings", "checking"])
    cat_other = sum(a.value_eur_jan1 for a in assets if a.asset_type in ["stocks", "bonds", "crypto", "property", "other"])
    
    # Debts: Category III (mortgage on 2nd home, credit cards, etc.)
    # Note: Primary residence mortgage is Box 1, not Box 3
    # TODO: Mortgages and debts are extracted separately but not yet included in calculations
    # Mortgages (asset_type="mortgage") and other debts (asset_type="debt") are handled differently by tax office
    cat_debts = 0.0 
    
    debt_threshold = sv_rates["debt_threshold"] * (2 if fiscal_partners else 1)
    deductible_debt = max(0, cat_debts - debt_threshold)
    
    rentability_base = cat_savings + cat_other - deductible_debt
    
    # 2. Calculate Fictitious Return
    return_savings = cat_savings * sv_rates["yield_savings"]
    return_other = cat_other * sv_rates["yield_other"]
    return_debt = deductible_debt * sv_rates["yield_debts"]
    
    total_fictitious_return = return_savings + return_other - return_debt
    if total_fictitious_return < 0:
        total_fictitious_return = 0.0
        
    # 3. Effective Rate
    if rentability_base > 0:
        effective_rate = total_fictitious_return / rentability_base
    else:
        effective_rate = 0.0
        
    # 4. Taxable Base
    tax_free_allowance = rates["tax_free_allowance"] * (2 if fiscal_partners else 1)
    taxable_base = max(0, rentability_base - tax_free_allowance)
    
    # 5. Tax Calculation
    box3_income = taxable_base * effective_rate
    tax_owed = box3_income * rates["tax_rate"]
    
    breakdown = {
        "cat_savings": cat_savings,
        "cat_other": cat_other,
        "cat_debts": cat_debts,
        "return_savings": return_savings,
        "return_other": return_other,
        "return_debt": return_debt,
        "effective_rate": effective_rate
    }
    
    return Box3Calculation(
        method="savings_variant",
        tax_year=tax_year,
        total_assets_jan1=cat_savings + cat_other,
        total_debts_jan1=cat_debts,
        net_wealth_jan1=cat_savings + cat_other - cat_debts,
        tax_free_allowance=tax_free_allowance,
        taxable_wealth=taxable_base,
        deemed_income=box3_income,
        tax_rate=rates["tax_rate"],
        tax_owed=tax_owed,
        calculation_breakdown=breakdown
    )


def calculate_statutory_tax(
    assets: list[Box3Asset],
    tax_year: int,
    fiscal_partner: bool = False
) -> Box3Calculation:
    """Main entry point for statutory Box 3 calculation."""
    logger.info(f"Calculating statutory Box 3 tax for {tax_year} (Partner: {fiscal_partner})")
    
    rates = load_rates(tax_year)
    
    # Always calculate Savings Variant (valid for all years in scope)
    result_sv = _calculate_savings_variant(assets, rates, tax_year, fiscal_partner)
    
    if tax_year == 2022:
        # For 2022, compare with Legacy
        result_legacy = _calculate_legacy_2022(assets, rates, fiscal_partner)
        
        if result_legacy.tax_owed < result_sv.tax_owed:
            logger.info("2022: Legacy method is more favorable.")
            result_legacy.method = "fictional_yield" # Official name for old method
            result_legacy.calculation_breakdown["note"] = "Legacy method selected (lower tax)"
            return result_legacy
        else:
            logger.info("2022: Savings Variant is more favorable.")
            result_sv.calculation_breakdown["note"] = "Savings Variant selected (lower tax)"
            return result_sv
            
    return result_sv


def statutory_calculation_node(state: TaxGraphState) -> dict:
    """Node for calculating statutory Box 3 tax with fiscal partner optimization."""
    has_partner = state.fiscal_partner is not None and state.fiscal_partner.is_fiscal_partner
    
    result = calculate_statutory_tax(
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
    
    return {"box3_fictional_yield_result": result}

