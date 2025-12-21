"""Currency conversion tool using ECB rates."""

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional


from dutch_tax_agent.config import settings

logger = logging.getLogger(__name__)


def parse_currency_string(value: str) -> float:
    """Parse a currency string to float, removing currency symbols and formatting.
    
    Handles strings like "$1.10", "€1,234.56", "1,234.56", etc.
    
    Args:
        value: String value that may contain currency symbols, commas, etc.
        
    Returns:
        Float value parsed from the string
        
    Raises:
        ValueError: If the string cannot be parsed to a float
    """
    if not isinstance(value, str):
        raise ValueError(f"Expected string, got {type(value)}")
    
    # Remove common currency symbols
    cleaned = value.replace("$", "").replace("€", "").replace("£", "").replace("¥", "")
    
    # Remove commas (thousand separators)
    cleaned = cleaned.replace(",", "")
    
    # Remove whitespace
    cleaned = cleaned.strip()
    
    # Try to convert to float
    try:
        return float(cleaned)
    except ValueError as e:
        raise ValueError(f"Could not parse currency string '{value}' to float: {e}") from e


class CurrencyConverter:
    """Converts currencies using ECB rates (cached with fallback to API)."""

    def __init__(self, cache_path: Optional[Path] = None) -> None:
        """Initialize currency converter.
        
        Args:
            cache_path: Path to cached rates JSON file
        """
        self.cache_path = cache_path or settings.data_dir / "ecb_rates_cache.json"
        self.rates_cache: dict = {}
        self._load_cache()

    def _load_cache(self) -> None:
        """Load cached rates from file."""
        if self.cache_path.exists():
            try:
                with open(self.cache_path, "r") as f:
                    self.rates_cache = json.load(f)
                logger.info(f"Loaded currency rates cache from {self.cache_path}")
            except Exception as e:
                logger.warning(f"Failed to load rates cache: {e}")
                self.rates_cache = {}
        else:
            logger.warning(f"No rates cache found at {self.cache_path}")
            self.rates_cache = {}

    def _save_cache(self) -> None:
        """Save rates cache to file."""
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_path, "w") as f:
                json.dump(self.rates_cache, f, indent=2)
            logger.info(f"Saved currency rates cache to {self.cache_path}")
        except Exception as e:
            logger.error(f"Failed to save rates cache: {e}")

    def get_rate(
        self,
        from_currency: str,
        to_currency: str = "EUR",
        reference_date: Optional[date] = None,
    ) -> float:
        """Get exchange rate for a specific year (uses Jan 1 rate for the year).
        
        Args:
            from_currency: Source currency code (e.g., "USD")
            to_currency: Target currency code (default: "EUR")
            reference_date: Any date in the year (default: Jan 1 of current year)
                          The rate used will be for Jan 1 of that year
            
        Returns:
            Exchange rate (e.g., 1.12 means 1 USD = 1.12 EUR)
            
        Raises:
            ValueError: If rate cannot be found
        """
        # Normalize currency codes
        from_currency = from_currency.upper()
        to_currency = to_currency.upper()

        # If same currency, rate is 1.0
        if from_currency == to_currency:
            return 1.0

        # Default to Jan 1 if no date specified
        if reference_date is None:
            reference_date = date(datetime.now().year, 1, 1)

        # Always use Jan 1 of the reference_date's year for simplicity
        # This ensures we use the year's exchange rate regardless of the specific date
        year_date = date(reference_date.year, 1, 1)

        # Create cache key using Jan 1 of the year
        cache_key = f"{year_date.isoformat()}_{from_currency}_{to_currency}"

        # Check cache first
        if cache_key in self.rates_cache:
            logger.debug(f"Using cached rate for {cache_key}")
            return self.rates_cache[cache_key]

        # Try to fetch from ECB API (if we have an API key)
        if settings.ecb_api_key:
            try:
                rate = self._fetch_ecb_rate(from_currency, to_currency, year_date)
                self.rates_cache[cache_key] = rate
                self._save_cache()
                return rate
            except Exception as e:
                logger.warning(f"Failed to fetch ECB rate: {e}")

        # Fall back to hardcoded rates for common conversions
        # These are approximate rates for demonstration purposes
        hardcoded_rates = {
            "2022-01-01_USD_EUR": 0.88,
            "2023-01-01_USD_EUR": 0.94,
            "2024-01-01_USD_EUR": 0.91,
            "2025-01-01_USD_EUR": 0.92,
            "2022-01-01_GBP_EUR": 1.19,
            "2023-01-01_GBP_EUR": 1.13,
            "2024-01-01_GBP_EUR": 1.15,
            "2025-01-01_GBP_EUR": 1.17,
        }

        if cache_key in hardcoded_rates:
            rate = hardcoded_rates[cache_key]
            logger.info(f"Using hardcoded rate for {cache_key}: {rate}")
            self.rates_cache[cache_key] = rate
            return rate

        # If we can't find a rate, raise an error
        raise ValueError(
            f"No exchange rate found for {from_currency} to {to_currency} "
            f"for year {reference_date.year}"
        )

    def _fetch_ecb_rate(
        self, from_currency: str, to_currency: str, reference_date: date
    ) -> float:
        """Fetch rate from ECB API (placeholder - implement if needed).
        
        Args:
            from_currency: Source currency
            to_currency: Target currency
            reference_date: Date for rate (should be Jan 1 of the year)
            
        Returns:
            Exchange rate
            
        Raises:
            NotImplementedError: ECB API integration not implemented
        """
        # This is a placeholder for actual ECB API integration
        # The ECB provides a free API at https://data.ecb.europa.eu/
        # When implemented, fetch the rate for Jan 1 of the reference_date's year
        raise NotImplementedError("ECB API integration not yet implemented")

    def convert(
        self,
        amount: float,
        from_currency: str,
        to_currency: str = "EUR",
        reference_date: Optional[date] = None,
    ) -> float:
        """Convert an amount from one currency to another.
        
        Args:
            amount: Amount to convert
            from_currency: Source currency code
            to_currency: Target currency code
            reference_date: Date for exchange rate
            
        Returns:
            Converted amount
        """
        # Determine the actual date used (always Jan 1 of the year)
        if reference_date is None:
            actual_date = date(datetime.now().year, 1, 1)
        else:
            actual_date = date(reference_date.year, 1, 1)
        
        rate = self.get_rate(from_currency, to_currency, reference_date)
        converted = amount * rate
        logger.info(
            f"Currency conversion: {amount:,.2f} {from_currency} → {converted:,.2f} {to_currency} "
            f"(rate: {rate:.6f}, reference_date: {actual_date})"
        )
        return converted


