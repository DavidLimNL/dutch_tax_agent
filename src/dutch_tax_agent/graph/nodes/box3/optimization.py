"""Fiscal Partnership Optimization for Box 3.

This module implements the logic to split Box 3 assets between partners
to maximize the utilization of the non-working partner's General Tax Credit.
"""

import logging
from typing import Optional

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
    4. Allocate that amount to Partner B.
    5. Allocate the rest to Partner A.
    """
    logger.info("Running Fiscal Partner Optimization for Box 3")
    
    # Clone result to avoid mutation
    optimized_result = statutory_result.model_copy(deep=True)
    
    # 1. Calculate Partner B's Max Credit (assuming 0 Box 1 income initially)
    # Note: As Box 3 income increases, the credit DECREASES. 
    # This creates a feedback loop.
    # Simplified approach: Use iterative solver or just assume max credit first, 
    # then adjust if income pushes it down.
    # Given the phase-out starts at ~€22k+, and credit is ~€3k.
    # Tax is ~32%. So needed income is ~€9k. 
    # €9k is well below the pivot (~€22k), so credit stays at max.
    # SAFE ASSUMPTION: Credit is at maximum for the "absorption" phase.
    
    max_ahk_b = get_general_tax_credit(0.0, tax_year)
    
    # 2. Target Tax for B
    target_tax_b = max_ahk_b
    
    # 3. Required Box 3 Income
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
    
    # 5. Allocation Logic
    if required_capital_b > total_capital:
        # We don't have enough capital to use the full credit
        # Allocate 100% to B
        alloc_b = total_capital
        alloc_a = 0.0
        used_credit = alloc_b * effective_rate * box3_rate
        msg = "Allocated 100% to Partner B (Capital insufficient to fully use credit)"
    else:
        # Optimal split
        alloc_b = required_capital_b
        alloc_a = total_capital - required_capital_b
        used_credit = target_tax_b
        msg = f"Allocated €{alloc_b:,.2f} to Partner B to absorb €{used_credit:,.2f} credit."

    # 6. Apply to result
    optimized_result.partner_split = {
        "partner_a": alloc_a,
        "partner_b": alloc_b,
        "note": msg
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
    
    logger.info(f"Optimization complete: {msg}")
    
    return optimized_result


def optimization_node(state: TaxGraphState) -> dict:
    """Node that optimizes statutory calculation if partner exists."""
    if not state.fiscal_partner or not state.fiscal_partner.is_fiscal_partner:
        logger.info("No fiscal partner - skipping optimization")
        return {} # No changes
        
    if not state.box3_fictional_yield_result:
        return {}
        
    partner_dob = state.fiscal_partner.date_of_birth
    
    optimized = optimize_partner_allocation(
        state.box3_fictional_yield_result,
        partner_dob.year,
        state.tax_year
    )
    
    # We update the fictional yield result with the optimized version
    return {"box3_fictional_yield_result": optimized}

