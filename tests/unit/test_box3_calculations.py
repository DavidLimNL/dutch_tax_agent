"""Unit tests for Box 3 calculations."""

from datetime import date

import pytest

from dutch_tax_agent.graph.nodes.box3.statutory_calculation import calculate_statutory_tax as calculate_fictional_yield
from dutch_tax_agent.graph.nodes.box3.actual_return import calculate_actual_return
from dutch_tax_agent.schemas.tax_entities import Box3Asset


@pytest.fixture
def sample_assets() -> list[Box3Asset]:
    """Create sample Box 3 assets for testing."""
    return [
        Box3Asset(
            source_doc_id="doc1",
            source_filename="bank_statement.pdf",
            asset_type="savings",
            value_eur_jan1=50000.0,
            realized_gains_eur=150.0,
            reference_date=date(2024, 1, 1),
            description="ING Savings Account",
        ),
        Box3Asset(
            source_doc_id="doc2",
            source_filename="broker_statement.pdf",
            asset_type="stocks",
            value_eur_jan1=30000.0,
            realized_gains_eur=2500.0,
            reference_date=date(2024, 1, 1),
            description="Investment Portfolio",
        ),
    ]


def test_fictional_yield_calculation(sample_assets):
    """Test fictional yield calculation."""
    result = calculate_fictional_yield(sample_assets, 2024)

    assert result.method == "savings_variant"  # For 2024, uses savings variant method
    assert result.tax_year == 2024
    assert result.total_assets_jan1 == 80000.0
    assert result.net_wealth_jan1 == 80000.0
    assert result.tax_owed > 0


def test_actual_return_calculation(sample_assets):
    """Test actual return calculation."""
    result = calculate_actual_return(sample_assets, 2024)

    assert result.method == "actual_return"
    assert result.tax_year == 2024
    assert result.actual_gains == 2650.0  # 150 + 2500
    assert result.tax_owed > 0


def test_box3_with_zero_assets():
    """Test Box 3 calculation with no assets."""
    result = calculate_fictional_yield([], 2024)

    assert result.total_assets_jan1 == 0.0
    assert result.tax_owed == 0.0


def test_box3_below_tax_free_allowance():
    """Test Box 3 when wealth is below tax-free allowance."""
    small_assets = [
        Box3Asset(
            source_doc_id="doc1",
            source_filename="test.pdf",
            asset_type="savings",
            value_eur_jan1=30000.0,
            reference_date=date(2024, 1, 1),
            description="Small savings",
        )
    ]

    result = calculate_fictional_yield(small_assets, 2024)

    # Should have minimal or zero tax due to allowance
    assert result.taxable_wealth == 0.0
    assert result.tax_owed == 0.0


