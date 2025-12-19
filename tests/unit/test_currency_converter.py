"""Unit tests for currency converter."""

from datetime import date

import pytest

from dutch_tax_agent.tools import CurrencyConverter


def test_currency_converter_same_currency():
    """Test conversion when source and target are the same."""
    converter = CurrencyConverter()

    result = converter.convert(100.0, "EUR", "EUR")
    assert result == 100.0


def test_currency_converter_usd_to_eur():
    """Test USD to EUR conversion using cached rates."""
    converter = CurrencyConverter()

    # Use Jan 1, 2024 rate (0.91 from cache)
    result = converter.convert(
        100.0,
        "USD",
        "EUR",
        reference_date=date(2024, 1, 1)
    )

    assert result == pytest.approx(91.0, rel=0.01)


def test_currency_converter_missing_rate():
    """Test error handling when rate is not available."""
    converter = CurrencyConverter()

    with pytest.raises(ValueError):
        converter.convert(
            100.0,
            "JPY",  # Not in cache
            "EUR",
            reference_date=date(2024, 1, 1)
        )


def test_currency_converter_get_rate():
    """Test getting exchange rate."""
    converter = CurrencyConverter()

    rate = converter.get_rate(
        "USD",
        "EUR",
        reference_date=date(2024, 1, 1)
    )

    assert rate == pytest.approx(0.91, rel=0.01)


