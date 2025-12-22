"""Custom Presidio recognizer for addresses from configuration file.

Handles variations including:
- Full addresses (street + postal code + city)
- Postal codes with/without spaces
- Street addresses
- Case-insensitive matching
- Reversed/inverted addresses
"""

import json
import logging
from typing import Optional

from presidio_analyzer import Pattern, PatternRecognizer

from dutch_tax_agent.config import settings

logger = logging.getLogger(__name__)


class AddressRecognizer(PatternRecognizer):
    """Recognizes addresses from pii_addresses.json configuration file."""

    def __init__(self) -> None:
        """Initialize address recognizer by loading addresses from config file."""
        addresses_file = settings.data_dir / "pii_addresses.json"
        
        if not addresses_file.exists():
            logger.warning(
                f"PII addresses file not found at {addresses_file}. "
                "Address recognition will be disabled."
            )
            patterns = []
            self.addresses = []
        else:
            try:
                with open(addresses_file, "r", encoding="utf-8") as f:
                    config = json.load(f)
                
                self.addresses = config.get("addresses", [])
                patterns = self._build_patterns(self.addresses)
                
                logger.info(
                    f"Loaded {len(self.addresses)} address(es) from {addresses_file}"
                )
            except Exception as e:
                logger.error(f"Failed to load PII addresses from {addresses_file}: {e}")
                patterns = []
                self.addresses = []

        super().__init__(
            supported_entity="NL_ADDRESS",
            patterns=patterns,
            supported_language="en",
        )

    def _build_patterns(self, address_configs: list[dict]) -> list[Pattern]:
        """Build regex patterns for all address variations.
        
        Args:
            address_configs: List of address dicts with keys: street, number, postal_code, city, province, country, full_address
            
        Returns:
            List of Pattern objects for address matching
        """
        patterns = []
        
        for idx, addr_config in enumerate(address_configs):
            street = addr_config.get("street", "").strip().upper()
            number = addr_config.get("number", "").strip().upper()
            postal_code = addr_config.get("postal_code", "").strip().upper().replace(" ", "")
            
            # Support both single city string and list of cities (for Dutch/English variations)
            city_input = addr_config.get("city", "")
            if isinstance(city_input, list):
                cities = [c.strip().upper() for c in city_input if c]
            elif city_input:
                cities = [city_input.strip().upper()]
            else:
                cities = []
            
            # Support both single country string and list of countries (for Dutch/English variations)
            country_input = addr_config.get("country", "")
            if isinstance(country_input, list):
                countries = [c.strip().upper() for c in country_input if c]
            elif country_input:
                countries = [country_input.strip().upper()]
            else:
                countries = []
            
            # Support both single province string and list of provinces (for Dutch/English variations)
            province_input = addr_config.get("province", "")
            if isinstance(province_input, list):
                provinces = [p.strip().upper() for p in province_input if p]
            elif province_input:
                provinces = [province_input.strip().upper()]
            else:
                provinces = []
            
            full_address = addr_config.get("full_address", "").strip().upper()
            
            if not street and not postal_code and not full_address:
                logger.warning(f"Skipping incomplete address config: {addr_config}")
                continue
            
            # Pattern 1: Full address (if provided)
            # Matches: "KALVERSTRAAT 123 1081LA AMSTERDAM"
            if full_address:
                full_pattern = r"(?i)\b" + self._escape_regex(full_address) + r"\b"
                patterns.append(
                    Pattern(
                        name=f"full_address_{idx}",
                        regex=full_pattern,
                        score=0.95,  # High confidence for full address
                    )
                )
                
                # Full address concatenated (no spaces)
                full_no_space = full_address.replace(" ", "")
                full_no_space_pattern = r"(?i)\b" + self._escape_regex(full_no_space) + r"\b"
                patterns.append(
                    Pattern(
                        name=f"full_address_concatenated_{idx}",
                        regex=full_no_space_pattern,
                        score=0.95,
                    )
                )
            
            # Pattern 2: Postal code (if provided)
            # Matches: "1081LA", "1081 LA"
            if postal_code:
                # Format: 4 digits + 2 letters
                if len(postal_code) == 6 and postal_code[:4].isdigit() and postal_code[4:].isalpha():
                    # Postal code with optional space: "1081 LA" or "1081LA"
                    digits = postal_code[:4]
                    letters = postal_code[4:]
                    postal_pattern = r"(?i)\b" + self._escape_regex(digits) + r"\s?" + self._escape_regex(letters) + r"\b"
                    patterns.append(
                        Pattern(
                            name=f"postal_code_{idx}",
                            regex=postal_pattern,
                            score=0.90,  # High confidence for postal code
                        )
                    )
                    
                    # Postal code without space
                    postal_no_space_pattern = r"(?i)\b" + self._escape_regex(postal_code) + r"\b"
                    patterns.append(
                        Pattern(
                            name=f"postal_code_no_space_{idx}",
                            regex=postal_no_space_pattern,
                            score=0.90,
                        )
                    )
            
            # Pattern 3: Street name only (if provided)
            # Matches: "KALVERSTRAAT"
            if street:
                street_pattern = r"(?i)\b" + self._escape_regex(street) + r"\b"
                patterns.append(
                    Pattern(
                        name=f"street_{idx}",
                        regex=street_pattern,
                        score=0.85,  # High confidence for street name
                    )
                )
            
            # Pattern 4: Street + Number (if both provided)
            # Matches: "KALVERSTRAAT 123", "KALVERSTRAAT123"
            if street and number:
                # Street + space + number
                street_number_pattern = (
                    r"(?i)\b" + self._escape_regex(street) + r"\s+" 
                    + self._escape_regex(number) + r"\b"
                )
                patterns.append(
                    Pattern(
                        name=f"street_number_{idx}",
                        regex=street_number_pattern,
                        score=0.95,  # Very high confidence for street + number
                    )
                )
                
                # Street + number concatenated (no space)
                street_number_concatenated = street + number
                street_number_concatenated_pattern = (
                    r"(?i)\b" + self._escape_regex(street_number_concatenated) + r"\b"
                )
                patterns.append(
                    Pattern(
                        name=f"street_number_concatenated_{idx}",
                        regex=street_number_concatenated_pattern,
                        score=0.95,
                    )
                )
            
            # Pattern 5: Number only (if provided, lower confidence to avoid false positives)
            # Matches: "123"
            if number:
                number_pattern = r"(?i)\b" + self._escape_regex(number) + r"\b"
                patterns.append(
                    Pattern(
                        name=f"number_{idx}",
                        regex=number_pattern,
                        score=0.60,  # Lower confidence for number alone (might be false positive)
                    )
                )
            
            # Pattern 6: Cities (if provided) - supports multiple city names (Dutch/English)
            # Matches: "AMSTERDAM", "DEN HAAG", "THE HAGUE"
            for city_idx, city in enumerate(cities):
                city_pattern = r"(?i)\b" + self._escape_regex(city) + r"\b"
                patterns.append(
                    Pattern(
                        name=f"city_{idx}_{city_idx}",
                        regex=city_pattern,
                        score=0.80,  # Medium-high confidence for city (might have false positives)
                    )
                )
            
            # Pattern 7: Street + Number + Postal Code (if all provided)
            if street and number and postal_code and len(postal_code) == 6:
                digits = postal_code[:4]
                letters = postal_code[4:]
                # With spaces: "KALVERSTRAAT 123 1234 AB"
                street_number_postal_pattern = (
                    r"(?i)\b" + self._escape_regex(street) + r"\s+" 
                    + self._escape_regex(number) + r"\s+"
                    + self._escape_regex(digits) + r"\s?" + self._escape_regex(letters) + r"\b"
                )
                patterns.append(
                    Pattern(
                        name=f"street_number_postal_{idx}",
                        regex=street_number_postal_pattern,
                        score=0.95,
                    )
                )
            
            # Pattern 8: Street + Postal Code (if both provided, no number)
            if street and postal_code and len(postal_code) == 6:
                digits = postal_code[:4]
                letters = postal_code[4:]
                street_postal_pattern = (
                    r"(?i)\b" + self._escape_regex(street) + r"\s+" 
                    + self._escape_regex(digits) + r"\s?" + self._escape_regex(letters) + r"\b"
                )
                patterns.append(
                    Pattern(
                        name=f"street_postal_{idx}",
                        regex=street_postal_pattern,
                        score=0.95,
                    )
                )
            
            # Pattern 9: Postal Code + City (if both provided)
            # Handles both "1234AB" and "1234 AB" formats
            # Supports multiple city names (Dutch/English)
            if postal_code and cities and len(postal_code) == 6:
                digits = postal_code[:4]
                letters = postal_code[4:]
                for city_idx, city in enumerate(cities):
                    # Pattern: "1234 AB CITY" or "1234AB CITY"
                    postal_city_pattern = (
                        r"(?i)\b" + self._escape_regex(digits) + r"\s?" + self._escape_regex(letters)
                        + r"\s+" + self._escape_regex(city) + r"\b"
                    )
                    patterns.append(
                        Pattern(
                            name=f"postal_city_{idx}_{city_idx}",
                            regex=postal_city_pattern,
                            score=0.95,
                        )
                    )
            
            # Pattern 10: Countries (if provided) - supports multiple country names (Dutch/English)
            # Matches: "NETHERLANDS", "THE NETHERLANDS", "NEDERLAND", "HOLLAND"
            # No word boundaries to catch countries that may appear without clear boundaries
            for country_idx, country in enumerate(countries):
                country_pattern = r"(?i)" + self._escape_regex(country)
                patterns.append(
                    Pattern(
                        name=f"country_{idx}_{country_idx}",
                        regex=country_pattern,
                        score=0.75,  # Medium confidence for country (might have false positives)
                    )
                )
            
            # Pattern 10b: Provinces (if provided) - supports multiple province names (Dutch/English)
            # Matches: "ZUIDHOLLAND", "NOORDHOLLAND", etc.
            # No word boundaries to catch provinces that may appear without clear boundaries
            for province_idx, province in enumerate(provinces):
                province_pattern = r"(?i)" + self._escape_regex(province)
                patterns.append(
                    Pattern(
                        name=f"province_{idx}_{province_idx}",
                        regex=province_pattern,
                        score=0.80,  # Medium-high confidence for province
                    )
                )
            
            # Pattern 11: City + Country (if both provided)
            # Supports multiple city and country variations
            if cities and countries:
                for city_idx, city in enumerate(cities):
                    for country_idx, country in enumerate(countries):
                        city_country_pattern = (
                            r"(?i)\b" + self._escape_regex(city) + r"\s+" 
                            + self._escape_regex(country) + r"\b"
                        )
                        patterns.append(
                            Pattern(
                                name=f"city_country_{idx}_{city_idx}_{country_idx}",
                                regex=city_country_pattern,
                                score=0.90,
                            )
                        )
            
            # Pattern 12: Postal Code + City + Country (if all provided)
            if postal_code and cities and countries and len(postal_code) == 6:
                digits = postal_code[:4]
                letters = postal_code[4:]
                for city_idx, city in enumerate(cities):
                    for country_idx, country in enumerate(countries):
                        # Pattern: "1234 AB CITY COUNTRY" or "1234AB CITY COUNTRY"
                        postal_city_country_pattern = (
                            r"(?i)\b" + self._escape_regex(digits) + r"\s?" + self._escape_regex(letters)
                            + r"\s+" + self._escape_regex(city) + r"\s+" + self._escape_regex(country) + r"\b"
                        )
                        patterns.append(
                            Pattern(
                                name=f"postal_city_country_{idx}_{city_idx}_{country_idx}",
                                regex=postal_city_country_pattern,
                                score=0.95,
                            )
                        )
            
            # Pattern 13: Reversed full address (if full_address exists)
            # No word boundaries to catch reversed text on separate lines
            # Remove spaces before reversing to match documents where spaces are removed
            if full_address:
                full_no_spaces = full_address.replace(" ", "")
                reversed_full = full_no_spaces[::-1]  # Reverse character by character
                reversed_full_pattern = r"(?i)" + self._escape_regex(reversed_full)
                patterns.append(
                    Pattern(
                        name=f"reversed_full_address_{idx}",
                        regex=reversed_full_pattern,
                        score=0.90,
                    )
                )
            
            # Pattern 14: Reversed street name (if provided)
            # Matches reversed street names (e.g., "TSAERTS" for "STREET")
            # No word boundaries to catch reversed text on separate lines
            # Remove spaces before reversing to match documents where spaces are removed
            if street:
                street_no_spaces = street.replace(" ", "")
                reversed_street = street_no_spaces[::-1]
                reversed_street_pattern = r"(?i)" + self._escape_regex(reversed_street)
                patterns.append(
                    Pattern(
                        name=f"reversed_street_{idx}",
                        regex=reversed_street_pattern,
                        score=0.85,
                    )
                )
            
            # Pattern 15: Reversed street + number (if both provided)
            # Matches reversed combinations (e.g., "321TSAERTS" for "STREET 123")
            # No word boundaries to catch reversed text on separate lines
            # Remove spaces before reversing to match documents where spaces are removed
            if street and number:
                street_no_spaces = street.replace(" ", "")
                
                # Case 1: Full reversal of "number + street" string (spaces removed)
                combined_no_spaces = number + street_no_spaces
                reversed_street_number = combined_no_spaces[::-1]
                reversed_street_number_pattern = r"(?i)" + self._escape_regex(reversed_street_number)
                patterns.append(
                    Pattern(
                        name=f"reversed_street_number_{idx}",
                        regex=reversed_street_number_pattern,
                        score=0.95,
                    )
                )
                
                # Case 2: Number NOT reversed + street reversed (e.g., "123TSAERTS" for "STREET 123")
                reversed_street_only = street_no_spaces[::-1]
                number_not_reversed_street_reversed = number + reversed_street_only
                number_not_reversed_street_reversed_pattern = r"(?i)" + self._escape_regex(number_not_reversed_street_reversed)
                patterns.append(
                    Pattern(
                        name=f"number_not_reversed_street_reversed_{idx}",
                        regex=number_not_reversed_street_reversed_pattern,
                        score=0.95,
                    )
                )
                
                # Case 3: Reversed street + reversed number (both reversed separately, street first)
                reversed_number = number[::-1]
                reversed_street_reversed_number = reversed_street_only + reversed_number
                reversed_street_reversed_number_pattern = r"(?i)" + self._escape_regex(reversed_street_reversed_number)
                patterns.append(
                    Pattern(
                        name=f"reversed_street_reversed_number_{idx}",
                        regex=reversed_street_reversed_number_pattern,
                        score=0.95,
                    )
                )
                
                # Case 4: Reversed number + reversed street (both reversed separately, number first)
                # Matches "27TAARTSAAREDNAV" for "VAN DER AASTRAAT 72"
                reversed_number_reversed_street = reversed_number + reversed_street_only
                reversed_number_reversed_street_pattern = r"(?i)" + self._escape_regex(reversed_number_reversed_street)
                patterns.append(
                    Pattern(
                        name=f"reversed_number_reversed_street_{idx}",
                        regex=reversed_number_reversed_street_pattern,
                        score=0.95,
                    )
                )
            
            # Pattern 16: Reversed cities (if provided)
            # Matches reversed city names (e.g., "YTIC" for "CITY")
            # No word boundaries to catch reversed text on separate lines
            # Remove spaces before reversing to match documents where spaces are removed
            for city_idx, city in enumerate(cities):
                city_no_spaces = city.replace(" ", "")
                reversed_city = city_no_spaces[::-1]
                reversed_city_pattern = r"(?i)" + self._escape_regex(reversed_city)
                patterns.append(
                    Pattern(
                        name=f"reversed_city_{idx}_{city_idx}",
                        regex=reversed_city_pattern,
                        score=0.80,
                    )
                )
            
            # Pattern 16b: Reversed provinces (if provided)
            # Matches reversed province names (e.g., "DNALLOHDIUZ" for "ZUIDHOLLAND")
            # No word boundaries to catch reversed text on separate lines
            # Remove spaces before reversing to match documents where spaces are removed
            for province_idx, province in enumerate(provinces):
                province_no_spaces = province.replace(" ", "")
                reversed_province = province_no_spaces[::-1]
                reversed_province_pattern = r"(?i)" + self._escape_regex(reversed_province)
                patterns.append(
                    Pattern(
                        name=f"reversed_province_{idx}_{province_idx}",
                        regex=reversed_province_pattern,
                        score=0.80,
                    )
                )
            
            # Pattern 16c: Reversed countries (if provided)
            # Matches reversed country names (e.g., "SDNALREHTEN" for "NETHERLANDS")
            # No word boundaries to catch reversed text on separate lines
            # Remove spaces before reversing to match documents where spaces are removed
            for country_idx, country in enumerate(countries):
                country_no_spaces = country.replace(" ", "")
                reversed_country = country_no_spaces[::-1]
                reversed_country_pattern = r"(?i)" + self._escape_regex(reversed_country)
                patterns.append(
                    Pattern(
                        name=f"reversed_country_{idx}_{country_idx}",
                        regex=reversed_country_pattern,
                        score=0.75,
                    )
                )
            
            # Pattern 17: Reversed postal code (if provided)
            # Matches reversed postal codes like "BA4321" for "1234AB"
            # No word boundaries to catch reversed text on separate lines
            if postal_code and len(postal_code) == 6:
                reversed_postal = postal_code[::-1]
                reversed_postal_pattern = r"(?i)" + self._escape_regex(reversed_postal)
                patterns.append(
                    Pattern(
                        name=f"reversed_postal_code_{idx}",
                        regex=reversed_postal_pattern,
                        score=0.90,
                    )
                )
                
                # Also handle reversed digits + reversed letters separately
                digits = postal_code[:4]
                letters = postal_code[4:]
                reversed_digits = digits[::-1]
                reversed_letters = letters[::-1]
                reversed_postal_separate = reversed_digits + reversed_letters
                reversed_postal_separate_pattern = r"(?i)" + self._escape_regex(reversed_postal_separate)
                patterns.append(
                    Pattern(
                        name=f"reversed_postal_code_separate_{idx}",
                        regex=reversed_postal_separate_pattern,
                        score=0.90,
                    )
                )
            
            # Pattern 18: Reversed postal code + city (if both provided)
            # Matches reversed combinations (e.g., "YTICBA4321" for "1234AB CITY")
            # No word boundaries to catch reversed text on separate lines
            # Remove spaces before reversing to match documents where spaces are removed
            if postal_code and cities and len(postal_code) == 6:
                reversed_postal = postal_code[::-1]
                for city_idx, city in enumerate(cities):
                    city_no_spaces = city.replace(" ", "")
                    reversed_city = city_no_spaces[::-1]
                    
                    # Case 1: Full reversal of "postal city" string (spaces removed from city)
                    postal_city_combined_no_spaces = postal_code + city_no_spaces
                    reversed_postal_city_full = postal_city_combined_no_spaces[::-1]
                    reversed_postal_city_full_pattern = r"(?i)" + self._escape_regex(reversed_postal_city_full)
                    patterns.append(
                        Pattern(
                            name=f"reversed_postal_city_full_{idx}_{city_idx}",
                            regex=reversed_postal_city_full_pattern,
                            score=0.95,
                        )
                    )
                    
                    # Case 2: Full reversal of "postal city" string without space (already handled above)
                    # This case is the same as Case 1 now
                    
                    # Case 3: Reversed city + reversed postal (both reversed separately, concatenated)
                    reversed_postal_city = reversed_city + reversed_postal
                    reversed_postal_city_pattern = r"(?i)" + self._escape_regex(reversed_postal_city)
                    patterns.append(
                        Pattern(
                            name=f"reversed_postal_city_{idx}_{city_idx}",
                            regex=reversed_postal_city_pattern,
                            score=0.95,
                        )
                    )
                    
                    # Case 4: City NOT reversed + postal reversed (spaces removed from city)
                    city_no_spaces_not_reversed = city_no_spaces
                    city_not_reversed_postal_reversed = city_no_spaces_not_reversed + reversed_postal
                    city_not_reversed_postal_reversed_pattern = r"(?i)" + self._escape_regex(city_not_reversed_postal_reversed)
                    patterns.append(
                        Pattern(
                            name=f"city_not_reversed_postal_reversed_{idx}_{city_idx}",
                            regex=city_not_reversed_postal_reversed_pattern,
                            score=0.95,
                        )
                    )
                    
                    # Case 5: Reversed city + postal NOT reversed
                    reversed_city_postal_not_reversed = reversed_city + postal_code
                    reversed_city_postal_not_reversed_pattern = r"(?i)" + self._escape_regex(reversed_city_postal_not_reversed)
                    patterns.append(
                        Pattern(
                            name=f"reversed_city_postal_not_reversed_{idx}_{city_idx}",
                            regex=reversed_city_postal_not_reversed_pattern,
                            score=0.95,
                        )
                    )
            
            # Pattern 19: Reversed street + number + postal code (if all provided)
            # No word boundaries to catch reversed text on separate lines
            # Remove spaces before reversing to match documents where spaces are removed
            if street and number and postal_code and len(postal_code) == 6:
                reversed_postal = postal_code[::-1]
                street_no_spaces = street.replace(" ", "")
                reversed_street = street_no_spaces[::-1]
                reversed_number = number[::-1]
                # Reversed: postal + number + street (concatenated)
                reversed_street_number_postal = reversed_postal + reversed_number + reversed_street
                reversed_street_number_postal_pattern = r"(?i)" + self._escape_regex(reversed_street_number_postal)
                patterns.append(
                    Pattern(
                        name=f"reversed_street_number_postal_{idx}",
                        regex=reversed_street_number_postal_pattern,
                        score=0.95,
                    )
                )
        
        return patterns

    def _escape_regex(self, text: str) -> str:
        """Escape special regex characters.
        
        Args:
            text: Text to escape
            
        Returns:
            Escaped regex pattern
        """
        import re
        return re.escape(text)

    def validate_result(self, pattern_text: str) -> Optional[bool]:
        """Validate that the matched text is actually an address from the config.
        
        This helps reduce false positives by checking if the match
        corresponds to a known address part.
        
        Args:
            pattern_text: The matched text
            
        Returns:
            True if valid address match, False otherwise
        """
        text_upper = pattern_text.strip().upper()
        
        # Check against all address parts
        for addr_config in self.addresses:
            street = addr_config.get("street", "").strip().upper()
            number = addr_config.get("number", "").strip().upper()
            postal_code = addr_config.get("postal_code", "").strip().upper().replace(" ", "")
            
            # Support both single city string and list of cities (for Dutch/English variations)
            city_input = addr_config.get("city", "")
            if isinstance(city_input, list):
                cities = [c.strip().upper() for c in city_input if c]
            elif city_input:
                cities = [city_input.strip().upper()]
            else:
                cities = []
            
            # Support both single country string and list of countries (for Dutch/English variations)
            country_input = addr_config.get("country", "")
            if isinstance(country_input, list):
                countries = [c.strip().upper() for c in country_input if c]
            elif country_input:
                countries = [country_input.strip().upper()]
            else:
                countries = []
            
            # Support both single province string and list of provinces (for Dutch/English variations)
            province_input = addr_config.get("province", "")
            if isinstance(province_input, list):
                provinces = [p.strip().upper() for p in province_input if p]
            elif province_input:
                provinces = [province_input.strip().upper()]
            else:
                provinces = []
            
            full_address = addr_config.get("full_address", "").strip().upper()
            
            # Check exact matches
            if text_upper == street:
                return True
            
            # Check against all city variations
            if text_upper in cities:
                return True
            
            # Check against all country variations
            if text_upper in countries:
                return True
            
            # Check against all province variations
            if text_upper in provinces:
                return True
            
            # Check number (only if it's part of a street+number combination to avoid false positives)
            if number:
                if text_upper == number:
                    # Only validate if street is also present in the match context
                    # This is a simple check - in practice, the pattern matching handles this better
                    pass
            
            # Check postal code (with/without space: "1234AB" or "1234 AB")
            if postal_code and len(postal_code) == 6:
                digits = postal_code[:4]
                letters = postal_code[4:]
                if text_upper == postal_code or text_upper == f"{digits} {letters}":
                    return True
            
            # Check full address variations
            if full_address:
                if text_upper == full_address or text_upper == full_address.replace(" ", ""):
                    return True
            
            # Check street + number combinations
            if street and number:
                if text_upper == f"{street} {number}" or text_upper == f"{street}{number}":
                    return True
            
            # Check street + number + postal code
            if street and number and postal_code and len(postal_code) == 6:
                digits = postal_code[:4]
                letters = postal_code[4:]
                if (text_upper == f"{street} {number} {postal_code}" or 
                    text_upper == f"{street} {number} {digits} {letters}" or
                    text_upper == f"{street}{number}{postal_code}"):
                    return True
            
            # Check street + postal code
            if street and postal_code and len(postal_code) == 6:
                digits = postal_code[:4]
                letters = postal_code[4:]
                if (text_upper == f"{street} {postal_code}" or 
                    text_upper == f"{street} {digits} {letters}" or
                    text_upper == f"{street}{postal_code}"):
                    return True
            
            # Check postal code + city (handles both "1234AB" and "1234 AB")
            # Supports multiple city names (Dutch/English)
            if postal_code and cities and len(postal_code) == 6:
                digits = postal_code[:4]
                letters = postal_code[4:]
                for city in cities:
                    if (text_upper == f"{postal_code} {city}" or 
                        text_upper == f"{digits} {letters} {city}" or
                        text_upper == f"{postal_code}{city}"):
                        return True
            
            # Check city + country
            if cities and countries:
                for city in cities:
                    for country in countries:
                        if text_upper == f"{city} {country}":
                            return True
            
            # Check postal code + city + country
            if postal_code and cities and countries and len(postal_code) == 6:
                digits = postal_code[:4]
                letters = postal_code[4:]
                for city in cities:
                    for country in countries:
                        if (text_upper == f"{postal_code} {city} {country}" or
                            text_upper == f"{digits} {letters} {city} {country}"):
                            return True
            
            # Check reversed variations (remove spaces before reversing)
            if full_address:
                full_no_spaces = full_address.replace(" ", "")
                reversed_full = full_no_spaces[::-1]
                if text_upper == reversed_full:
                    return True
            
            # Check reversed street (remove spaces before reversing)
            if street:
                street_no_spaces = street.replace(" ", "")
                reversed_street = street_no_spaces[::-1]
                if text_upper == reversed_street:
                    return True
            
            # Check reversed street + number (remove spaces before reversing)
            if street and number:
                street_no_spaces = street.replace(" ", "")
                
                # Case 1: Full reversal of "number + street" string (spaces removed)
                combined_no_spaces = number + street_no_spaces
                reversed_street_number = combined_no_spaces[::-1]
                if text_upper == reversed_street_number:
                    return True
                
                # Case 2: Number NOT reversed + street reversed (e.g., "123TSAERTS")
                reversed_street_only = street_no_spaces[::-1]
                number_not_reversed_street_reversed = number + reversed_street_only
                if text_upper == number_not_reversed_street_reversed:
                    return True
                
                # Case 3: Reversed street + reversed number (both reversed separately, street first)
                reversed_number = number[::-1]
                reversed_street_reversed_number = reversed_street_only + reversed_number
                if text_upper == reversed_street_reversed_number:
                    return True
                
                # Case 4: Reversed number + reversed street (both reversed separately, number first)
                reversed_number_reversed_street = reversed_number + reversed_street_only
                if text_upper == reversed_number_reversed_street:
                    return True
            
            # Check reversed cities (remove spaces before reversing)
            for city in cities:
                city_no_spaces = city.replace(" ", "")
                reversed_city = city_no_spaces[::-1]
                if text_upper == reversed_city:
                    return True
            
            # Check reversed provinces (remove spaces before reversing)
            for province in provinces:
                province_no_spaces = province.replace(" ", "")
                reversed_province = province_no_spaces[::-1]
                if text_upper == reversed_province:
                    return True
            
            # Check reversed countries (remove spaces before reversing)
            for country in countries:
                country_no_spaces = country.replace(" ", "")
                reversed_country = country_no_spaces[::-1]
                if text_upper == reversed_country:
                    return True
            
            # Check reversed postal code
            if postal_code and len(postal_code) == 6:
                reversed_postal = postal_code[::-1]
                if text_upper == reversed_postal:
                    return True
                
                digits = postal_code[:4]
                letters = postal_code[4:]
                reversed_digits = digits[::-1]
                reversed_letters = letters[::-1]
                reversed_postal_separate = reversed_digits + reversed_letters
                if text_upper == reversed_postal_separate:
                    return True
            
            # Check reversed postal code + city (remove spaces before reversing)
            if postal_code and cities and len(postal_code) == 6:
                reversed_postal = postal_code[::-1]
                for city in cities:
                    city_no_spaces = city.replace(" ", "")
                    reversed_city = city_no_spaces[::-1]
                    
                    # Case 1: Full reversal of "postal city" string (spaces removed from city)
                    postal_city_combined_no_spaces = postal_code + city_no_spaces
                    reversed_postal_city_full = postal_city_combined_no_spaces[::-1]
                    if text_upper == reversed_postal_city_full:
                        return True
                    
                    # Case 3: Reversed city + reversed postal (both reversed separately)
                    reversed_postal_city = reversed_city + reversed_postal
                    if text_upper == reversed_postal_city:
                        return True
                    
                    # Case 4: City NOT reversed + postal reversed (spaces removed from city)
                    city_no_spaces_not_reversed = city_no_spaces
                    city_not_reversed_postal_reversed = city_no_spaces_not_reversed + reversed_postal
                    if text_upper == city_not_reversed_postal_reversed:
                        return True
                    
                    # Case 5: Reversed city + postal NOT reversed
                    reversed_city_postal_not_reversed = reversed_city + postal_code
                    if text_upper == reversed_city_postal_not_reversed:
                        return True
            
            # Check reversed street + number + postal code (remove spaces before reversing)
            if street and number and postal_code and len(postal_code) == 6:
                reversed_postal = postal_code[::-1]
                street_no_spaces = street.replace(" ", "")
                reversed_street = street_no_spaces[::-1]
                reversed_number = number[::-1]
                reversed_street_number_postal = reversed_postal + reversed_number + reversed_street
                if text_upper == reversed_street_number_postal:
                    return True
        
        return None  # Let Presidio decide based on pattern score

