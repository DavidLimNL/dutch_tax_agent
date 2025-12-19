"""Currency conversion tool using ECB rates."""

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional


from dutch_tax_agent.config import settings

logger = logging.getLogger(__name__)


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
        """Get exchange rate for a specific date.
        
        Args:
            from_currency: Source currency code (e.g., "USD")
            to_currency: Target currency code (default: "EUR")
            reference_date: Date for the rate (default: Jan 1 of current year)
            
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

        # Create cache key
        cache_key = f"{reference_date.isoformat()}_{from_currency}_{to_currency}"

        # Check cache first
        if cache_key in self.rates_cache:
            logger.debug(f"Using cached rate for {cache_key}")
            return self.rates_cache[cache_key]

        # Try to fetch from ECB API (if we have an API key)
        if settings.ecb_api_key:
            try:
                rate = self._fetch_ecb_rate(from_currency, to_currency, reference_date)
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
            f"on {reference_date.isoformat()}"
        )

    def _fetch_ecb_rate(
        self, from_currency: str, to_currency: str, reference_date: date
    ) -> float:
        """Fetch rate from ECB API (placeholder - implement if needed).
        
        Args:
            from_currency: Source currency
            to_currency: Target currency
            reference_date: Date for rate
            
        Returns:
            Exchange rate
            
        Raises:
            NotImplementedError: ECB API integration not implemented
        """
        # This is a placeholder for actual ECB API integration
        # The ECB provides a free API at https://data.ecb.europa.eu/
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
        rate = self.get_rate(from_currency, to_currency, reference_date)
        converted = amount * rate
        logger.debug(
            f"Converted {amount} {from_currency} to {converted:.2f} {to_currency} "
            f"(rate: {rate})"
        )
        return converted


