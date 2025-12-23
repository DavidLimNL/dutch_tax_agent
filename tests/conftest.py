"""Pytest configuration and fixtures."""

import pytest
from pathlib import Path


@pytest.fixture
def sample_dutch_text() -> str:
    """Sample Dutch bank statement text."""
    return """
    ING Bank Statement
    Datum: 01-01-2024
    Rekeningnummer: NL91ABNA0417164300
    
    Saldo per 1 januari 2024: EUR 45,000.00
    
    Spaarrekening
    Rente ontvangen: EUR 150.00
    """


@pytest.fixture
def sample_us_broker_text() -> str:
    """Sample investment broker statement text."""
    return """
    Interactive Brokers Statement
    Date: January 1, 2024
    
    Total Portfolio Value: USD 85,000.00
    
    Realized Gains (2024): USD 5,200.00
    Dividends Received: USD 1,800.00
    """


@pytest.fixture
def sample_salary_text() -> str:
    """Sample salary statement text."""
    return """
    Salarisstrook
    Periode: Januari 2024
    
    Bruto salaris: EUR 4,500.00
    Loonheffing: EUR 1,350.00
    Netto salaris: EUR 3,150.00
    """


@pytest.fixture
def test_data_dir(tmp_path: Path) -> Path:
    """Create a temporary directory for test data."""
    test_dir = tmp_path / "test_data"
    test_dir.mkdir()
    return test_dir


