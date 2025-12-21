"""Tax credit calculation tools."""

import json
import logging
from math import floor

from dutch_tax_agent.config import settings

logger = logging.getLogger(__name__)


def get_general_tax_credit(
    taxable_income: float,
    tax_year: int,
    born_before_1963: bool = False  # Not used for AHK amount, only for transferability
) -> float:
    """Calculate the General Tax Credit (Algemene Heffingskorting).
    
    Formula is income-dependent.
    """
    rates_path = settings.data_dir / "box3_rates_2022_2025.json"
    with open(rates_path, "r") as f:
        all_rates = json.load(f)
        
    if str(tax_year) not in all_rates:
        raise ValueError(f"No rates for {tax_year}")
        
    ahk_params = all_rates[str(tax_year)]["general_tax_credit"]
    
    max_credit = ahk_params["max_credit"]
    pivot = ahk_params["pivot_income"]
    end_point = ahk_params["end_point"]
    rate = ahk_params["phase_out_rate"]
    
    if taxable_income <= pivot:
        return max_credit
    elif taxable_income >= end_point:
        return 0.0
    else:
        # Formula: Max - Rate * (Income - Pivot)
        credit = max_credit - rate * (taxable_income - pivot)
        return max(0.0, credit)

