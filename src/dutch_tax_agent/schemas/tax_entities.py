"""Tax-specific entity schemas (Box 1 & Box 3)."""

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field


class FiscalPartner(BaseModel):
    """Fiscal partner (non-working partner) information for tax optimization.
    
    This represents Partner B in a fiscal partnership where only one partner
    generates Box 1 income. The date of birth is critical for determining
    eligibility for the "Aanrechtsubsidie" (transferability of General Tax Credit).
    
    Key rules:
    - Born before Jan 1, 1963: Can transfer 100% of AHK to working partner (2022)
    - Born on/after Jan 1, 1963: Transferability phased out (0% in 2023-2025)
    - However, the partner can still use their own credit against Box 3 tax
    """

    date_of_birth: date = Field(
        description="Date of birth (critical for Aanrechtsubsidie eligibility)"
    )
    box1_income_gross: float = Field(
        default=0.0,
        description="Box 1 gross income (typically 0.0 for non-working partner)",
    )
    is_fiscal_partner: bool = Field(
        default=True,
        description="Whether this is a fiscal partnership",
    )


class Box1Income(BaseModel):
    """Box 1: Income from employment, business, or home ownership."""

    source_doc_id: str = Field(description="Links to ScrubbedDocument")
    source_filename: str = Field(description="For audit trail")
    source_page: Optional[int] = Field(None, description="Page number in PDF")
    
    income_type: Literal["salary", "bonus", "freelance", "rental"] = Field(
        description="Type of Box 1 income"
    )
    
    # Financial data
    gross_amount_eur: float = Field(description="Gross income in EUR")
    tax_withheld_eur: float = Field(default=0.0, description="Tax already withheld")
    
    # Period information
    period_start: date = Field(description="Start of income period")
    period_end: date = Field(description="End of income period")
    
    # Original values (for audit)
    original_amount: Optional[float] = None
    original_currency: str = "EUR"
    
    # Metadata
    extraction_confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    original_text_snippet: Optional[str] = Field(
        None,
        description="The raw line from PDF that contained this data",
    )


class Box3Asset(BaseModel):
    """Box 3: Wealth (savings, investments, property) on reference date (Jan 1)."""

    source_doc_id: str = Field(description="Links to ScrubbedDocument")
    source_filename: str = Field(description="For audit trail")
    source_page: Optional[int] = Field(None, description="Page number in PDF")
    
    asset_type: Literal["savings", "stocks", "bonds", "crypto", "property", "other"] = Field(
        description="Type of Box 3 asset"
    )
    
    # Core values (normalized to EUR on Jan 1)
    value_eur_jan1: float = Field(
        description="Asset value in EUR on January 1st (reference date)"
    )
    
    # For "Actual Return" method (Box 3 new law)
    realized_gains_eur: Optional[float] = Field(
        None,
        description="Actual gains/dividends during the year (for new Box 3 method)",
    )
    realized_losses_eur: Optional[float] = Field(
        None,
        description="Realized losses during the year",
    )
    
    # Additional fields for Actual Return calculation (unrealized gains)
    value_eur_dec31: Optional[float] = Field(
        None,
        description="Asset value in EUR on December 31st (end of tax year) for unrealized gains calculation",
    )
    deposits_eur: Optional[float] = Field(
        None,
        description="Money deposited/added to this asset during the tax year",
    )
    withdrawals_eur: Optional[float] = Field(
        None,
        description="Money withdrawn/removed from this asset during the tax year",
    )
    
    # Original values
    original_value: Optional[float] = None
    original_currency: str = "EUR"
    conversion_rate: Optional[float] = Field(
        None,
        description="Exchange rate used if converted from foreign currency",
    )
    
    # Reference date
    reference_date: date = Field(
        description="Should be January 1st of the tax year"
    )
    
    # Description
    description: Optional[str] = Field(
        None,
        description="Human-readable description (e.g., 'ING Savings Account')",
    )
    
    # Metadata
    extraction_confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    original_text_snippet: Optional[str] = Field(
        None,
        description="The raw line from PDF",
    )


class Box3Calculation(BaseModel):
    """Result of a Box 3 tax calculation (either Fictional Yield or Actual Return)."""

    method: Literal["fictional_yield", "actual_return", "savings_variant"] = Field(
        description="Which calculation method was used"
    )
    tax_year: int = Field(description="Tax year (2022-2025)")
    
    # Input totals
    total_assets_jan1: float = Field(description="Sum of all Box 3 assets on Jan 1")
    total_debts_jan1: float = Field(
        default=0.0,
        description="Sum of debts (mortgage, etc.)",
    )
    net_wealth_jan1: float = Field(description="Assets - Debts")
    
    # Tax-free allowance
    tax_free_allowance: float = Field(
        description="Heffingsvrij vermogen (e.g., €57,000 in 2024)"
    )
    taxable_wealth: float = Field(description="Net wealth - allowance")
    
    # Calculation specifics
    fictional_yield_rate: Optional[float] = Field(
        None,
        description="If fictional_yield method, the % rate used",
    )
    actual_gains: Optional[float] = Field(
        None,
        description="If actual_return method, the total realized gains",
    )
    
    # Result
    deemed_income: float = Field(description="Grondslag sparen en beleggen")
    tax_rate: float = Field(
        default=0.32,
        description="Box 3 tax rate (32% in recent years)",
    )
    tax_owed: float = Field(description="Final Box 3 tax amount")
    
    # Optimization results
    partner_split: Optional[dict[str, float]] = Field(
        None,
        description="Optimization split: {'partner_a': amount, 'partner_b': amount}"
    )
    
    # Breakdown (for transparency)
    calculation_breakdown: dict = Field(
        default_factory=dict,
        description="Detailed breakdown of the calculation steps",
    )


class TaxReport(BaseModel):
    """Final tax report combining all data."""

    tax_year: int
    generated_at: date = Field(default_factory=date.today)
    
    # Box 1 Summary
    box1_total_income: float
    box1_total_tax_withheld: float
    box1_items: list[Box1Income]
    
    # Box 3 Summary
    box3_total_assets: float
    box3_items: list[Box3Asset]
    
    # Box 3 Calculations (both methods)
    box3_fictional_yield: Optional[Box3Calculation] = None
    box3_actual_return: Optional[Box3Calculation] = None
    
    # Recommendation
    recommended_method: Optional[Literal["fictional_yield", "actual_return"]] = None
    recommendation_reasoning: Optional[str] = None
    potential_savings: Optional[float] = Field(
        None,
        description="Tax savings if using recommended method vs. default",
    )
    
    # Validation status
    validation_errors: list[str] = Field(default_factory=list)
    validation_warnings: list[str] = Field(default_factory=list)

