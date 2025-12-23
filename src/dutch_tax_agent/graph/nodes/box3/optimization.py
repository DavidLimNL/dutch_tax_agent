"""Fiscal Partnership Optimization for Box 3.

This module implements the logic to split Box 3 assets between partners
to maximize the utilization of the non-working partner's General Tax Credit.

Critical Change for 2025:
- In 2022-2024: Box 3 income did NOT affect the General Tax Credit (AHK).
  Allocating excess income to Partner B was harmless.
- In 2025: Box 3 income NOW affects Aggregate Income, which affects AHK phase-out.
  If Partner B's income exceeds the pivot threshold (~€28,406), their AHK shrinks,
  creating a "phantom tax" of ~6.3% (phase-out rate), pushing effective marginal
  rate to ~42.3% (36% Box 3 + 6.3% AHK reduction). Partner A stays at flat 36%.
  
Solution: Implement "Smart Cap" for 2025 that prevents Partner B's income from
exceeding the pivot threshold.
"""

import json
import logging
from typing import Optional

from dutch_tax_agent.config import settings
from dutch_tax_agent.schemas.state import TaxGraphState
from dutch_tax_agent.schemas.tax_entities import Box3Calculation
from dutch_tax_agent.tools.tax_credits import get_general_tax_credit

logger = logging.getLogger(__name__)


def optimize_partner_allocation(
    statutory_result: Box3Calculation,
    partner_b_dob_year: int,
    tax_year: int
) -> Box3Calculation:
    """Optimize the allocation of Box 3 wealth between partners.
    
    Strategy:
    1. Calculate Partner B's (non-working) max potential General Tax Credit (AHK).
    2. Determine how much Box 3 tax liability is needed to fully use this credit.
    3. Back-calculate the required Box 3 capital to generate that liability.
    4. Apply "Smart Cap" logic:
       - For 2025: Cap Partner B's income at pivot threshold to avoid AHK phase-out
       - For 2022-2024: Cap at Income_Needed (cleaner, even though neutral above)
    5. Allocate remaining capital to Partner A.
    
    Critical for 2025: Box 3 income affects Aggregate Income, which affects AHK.
    Exceeding the pivot threshold creates a "phantom tax" of ~6.3% (phase-out rate),
    making Partner B's effective marginal rate ~42.3% vs Partner A's flat 36%.
    """
    logger.info(f"Running Fiscal Partner Optimization for Box 3 (Year: {tax_year})")
    
    # Clone result to avoid mutation
    optimized_result = statutory_result.model_copy(deep=True)
    
    # Load AHK parameters for pivot threshold check (2025)
    rates_path = settings.data_dir / "box3_rates_2022_2025.json"
    with open(rates_path, "r") as f:
        all_rates = json.load(f)
    
    if str(tax_year) not in all_rates:
        logger.warning(f"No rates for {tax_year}. Skipping optimization.")
        return optimized_result
    
    ahk_params = all_rates[str(tax_year)]["general_tax_credit"]
    pivot_income = ahk_params["pivot_income"]
    max_credit = ahk_params["max_credit"]
    
    # 1. Calculate Partner B's Max Credit (assuming 0 Box 1 income initially)
    max_ahk_b = get_general_tax_credit(0.0, tax_year)
    
    # 2. Target Tax for B (to fully use the credit)
    target_tax_b = max_ahk_b
    
    # 3. Required Box 3 Income to generate target tax
    box3_rate = statutory_result.tax_rate
    required_income_b = target_tax_b / box3_rate
    
    # 4. Required Capital
    # We use the *effective rate* calculated in the statutory method
    # Income = Capital * Effective_Rate
    # Capital = Income / Effective_Rate
    
    total_capital = statutory_result.taxable_wealth # This is the BASE (after allowance)
    effective_rate = statutory_result.deemed_income / total_capital if total_capital > 0 else 0
    
    if effective_rate <= 0:
        logger.warning("Effective rate is 0. Cannot optimize allocation.")
        return optimized_result

    required_capital_b = required_income_b / effective_rate
    
    # 5. Smart Cap Logic (2025 vs 2022-2024)
    is_2025 = tax_year == 2025
    
    if is_2025:
        # 2025: Box 3 income affects AHK phase-out
        # We must cap Partner B's income at the pivot threshold to avoid phantom tax
        # Calculate max Box 3 income Partner B can have without triggering phase-out
        max_income_b = pivot_income  # Partner B has 0 Box 1 income, so this is the cap
        
        # Calculate corresponding capital allocation
        max_capital_b = max_income_b / effective_rate if effective_rate > 0 else 0
        
        # Use the MINIMUM of (required_capital_b, max_capital_b, total_capital)
        # This ensures we:
        # - Don't exceed the pivot (avoiding phantom tax)
        # - Don't allocate more than needed (to use credit)
        # - Don't allocate more than available
        alloc_b = min(required_capital_b, max_capital_b, total_capital)
        alloc_a = total_capital - alloc_b
        
        # Calculate actual income and tax for Partner B
        actual_income_b = alloc_b * effective_rate
        actual_tax_b = actual_income_b * box3_rate
        
        # Recalculate AHK with actual income (iterative feedback)
        actual_ahk_b = get_general_tax_credit(actual_income_b, tax_year)
        net_tax_b = max(0.0, actual_tax_b - actual_ahk_b)
        used_credit = min(actual_tax_b, actual_ahk_b)
        
        if alloc_b >= max_capital_b and max_capital_b < total_capital:
            msg = (
                f"Allocated €{alloc_b:,.2f} to Partner B (capped at pivot threshold €{pivot_income:,.0f} "
                f"to avoid AHK phase-out). Remaining €{alloc_a:,.2f} to Partner A. "
                f"Used €{used_credit:,.2f} credit, net tax B: €{net_tax_b:,.2f}"
            )
        elif alloc_b >= total_capital:
            msg = (
                f"Allocated 100% (€{alloc_b:,.2f}) to Partner B. "
                f"Capital insufficient to fully use credit or reach pivot cap."
            )
        else:
            msg = (
                f"Allocated €{alloc_b:,.2f} to Partner B to absorb €{used_credit:,.2f} credit. "
                f"Remaining €{alloc_a:,.2f} to Partner A."
            )
    else:
        # 2022-2024: Box 3 income does NOT affect AHK
        # Cap at Income_Needed for cleanliness (neutral above, but cleaner)
        if required_capital_b > total_capital:
            # We don't have enough capital to use the full credit
            # Allocate 100% to B
            alloc_b = total_capital
            alloc_a = 0.0
            actual_income_b = alloc_b * effective_rate
            actual_tax_b = actual_income_b * box3_rate
            actual_ahk_b = get_general_tax_credit(actual_income_b, tax_year)
            used_credit = min(actual_tax_b, actual_ahk_b)
            msg = "Allocated 100% to Partner B (Capital insufficient to fully use credit)"
        else:
            # Optimal split: allocate exactly what's needed
            alloc_b = required_capital_b
            alloc_a = total_capital - required_capital_b
            used_credit = target_tax_b
            msg = f"Allocated €{alloc_b:,.2f} to Partner B to absorb €{used_credit:,.2f} credit."

    # 6. Apply to result
    optimized_result.partner_split = {
        "partner_a": alloc_a,
        "partner_b": alloc_b,
    }
    
    # Calculate savings
    # Without optimization: 
    # If A earns high income, their AHK is 0. 
    # If B has no income, their AHK is wasted (if born > 1963).
    # Savings = used_credit (that would otherwise be lost)
    
    # Note: If born < 1963, they could transfer it anyway. 
    # But allocating "own tax" is always cleaner.
    # The savings calculation depends on A's income status, which we assume is high.
    
    optimized_result.calculation_breakdown["optimization_savings"] = used_credit
    optimized_result.calculation_breakdown["optimization_note"] = msg
    
    logger.info(f"Optimization complete: {msg}")
    
    return optimized_result

