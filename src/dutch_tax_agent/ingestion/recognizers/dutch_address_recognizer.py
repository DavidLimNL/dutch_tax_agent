"""Custom Presidio recognizer for Dutch addresses."""

import re
from typing import Optional

from presidio_analyzer import Pattern, PatternRecognizer


class DutchAddressRecognizer(PatternRecognizer):
    """Recognizes Dutch addresses including postal codes, street names, and cities."""

    def __init__(self) -> None:
        """Initialize Dutch address recognizer with patterns."""
        patterns = [
            # Dutch postal code: 4 digits + 2 letters (e.g., "1081LA", "1081 LA")
            Pattern(
                name="dutch_postal_code",
                regex=r"\b\d{4}\s?[A-Z]{2}\b",
                score=0.8,
            ),
            # Dutch postal code immediately followed by number (e.g., "1081LA72")
            # This handles cases where postal code and house number are concatenated
            Pattern(
                name="dutch_postal_code_number",
                regex=r"\b\d{4}\s?[A-Z]{2}\d+\b",
                score=0.85,
            ),
            # Street name + number (e.g., "G MAHLERLN 2970", "KALVERSTRAAT 123")
            # Pattern: starts with capital, has letters/spaces, ends with digits
            # Handles both single-word ("KALVERSTRAAT 123") and multi-word ("G MAHLERLN 2970") streets
            Pattern(
                name="dutch_street_address",
                regex=r"\b[A-Z](?:[A-Z]+|\s+[A-Z]+)*\s+\d+\b",
                score=0.7,
            ),
            # Postal code + city (e.g., "1081LA AMSTERDAM", "1234 AB ROTTERDAM")
            Pattern(
                name="dutch_postal_city",
                regex=r"\b\d{4}\s?[A-Z]{2}\s+[A-Z][A-Z\s]{2,}\b",
                score=0.9,
            ),
            # Full address pattern: street + postal code + city
            Pattern(
                name="dutch_full_address",
                regex=r"\b[A-Z](?:[A-Z]+|\s+[A-Z]+)*\s+\d+\s+\d{4}\s?[A-Z]{2}\s+[A-Z](?:[A-Z]+|\s+[A-Z]+)*\b",
                score=0.95,
            ),
            # Reversed patterns (for when entire text is reversed)
            # Postal code anywhere in text (not just at word boundary start)
            # Matches postal codes embedded in text (e.g., "1081LA" in "AMSTERDAM1081LA")
            Pattern(
                name="dutch_postal_code_anywhere",
                regex=r"\d{4}[A-Z]{2}",
                score=0.75,
            ),
            # City + postal code (reversed: city name followed by postal code)
            # Matches "AMSTERDAM1081LA" or "ROTTERDAM1234AB"
            Pattern(
                name="dutch_city_postal_code",
                regex=r"[A-Z]{3,}\d{4}[A-Z]{2}",
                score=0.85,
            ),
            # Reversed street address (number at end): letters then digits
            # Matches "KALVERSTRAAT123" or "MAHLERLN2970"
            # Requires at least 4 letters to reduce false positives
            Pattern(
                name="dutch_street_address_reversed",
                regex=r"[A-Z]{4,}\d+",
                score=0.7,
            ),
        ]

        super().__init__(
            supported_entity="NL_ADDRESS",
            patterns=patterns,
            context=[
                "adres",
                "address",
                "straat",
                "street",
                "postcode",
                "postal code",
                "woonplaats",
                "city",
                "gemeente",
                "municipality",
            ],
            supported_language="en",  # Use English as base language
        )

    def validate_result(self, pattern_text: str) -> Optional[bool]:
        """Validate Dutch address pattern.
        
        Args:
            pattern_text: The matched address string
            
        Returns:
            True if valid Dutch address format
        """
        text = pattern_text.strip()
        
        # Check for Dutch postal code pattern (4 digits + 2 letters)
        # This handles both standalone postal codes and postal codes followed by numbers
        # Also handles postal codes embedded in text (like "AMSTERDAM1081LA")
        postal_code_match = re.search(r"(\d{4}[A-Z]{2})", text)
        if postal_code_match:
            postal_code = postal_code_match.group(1)
            # Validate postal code format
            if len(postal_code) == 6 and postal_code[:4].isdigit() and postal_code[4:].isalpha():
                return True
        
        # Check for street + number pattern (normal order: letters then space then digits)
        # Should have at least one letter and one digit
        if re.search(r"[A-Z]", text) and re.search(r"\d", text):
            # Street name should have letters, number at least 1 digit
            # Pattern: first letter, then zero or more words (letter sequences), then space(s), then digits
            street_match = re.match(r"([A-Z](?:[A-Z]+|\s+[A-Z]+)*)\s+(\d+)", text)
            if street_match:
                street_part = street_match.group(1).strip()
                number_part = street_match.group(2)
                # Ensure street part has at least 2 letters (for names like "G MAHLERLN" or "KALVERSTRAAT")
                if len(re.findall(r"[A-Z]", street_part)) >= 2 and len(number_part) >= 1:
                    return True
        
        # Check for reversed street address (number at end: letters then digits, no space)
        # Pattern: letters followed directly by digits (e.g., "KALVERSTRAAT123")
        reversed_street_match = re.match(r"([A-Z]{4,})(\d+)", text)
        if reversed_street_match:
            street_part = reversed_street_match.group(1)
            number_part = reversed_street_match.group(2)
            # Ensure street part has at least 4 letters to reduce false positives
            # and number part has at least 1 digit
            if len(street_part) >= 4 and len(number_part) >= 1:
                return True
        
        # Check for city + postal code pattern (reversed: city name then postal code)
        # Pattern: letters (city) followed by postal code (e.g., "AMSTERDAM1081LA")
        city_postal_match = re.match(r"([A-Z]{3,})(\d{4}[A-Z]{2})", text)
        if city_postal_match:
            city_part = city_postal_match.group(1)
            postal_code = city_postal_match.group(2)
            # Validate postal code format and ensure city has at least 3 letters
            if len(city_part) >= 3 and len(postal_code) == 6 and postal_code[:4].isdigit() and postal_code[4:].isalpha():
                return True
        
        return False

    def analyze(self, text: str, entities: list[str], nlp_artifacts=None):  # type: ignore
        """Override analyze to add validation and improve detection."""
        results = super().analyze(text, entities, nlp_artifacts)

        # Filter and validate results
        validated_results = []
        for result in results:
            pattern_text = text[result.start : result.end]
            if self.validate_result(pattern_text):
                # Boost score for validated addresses
                result.score = min(0.95, result.score + 0.1)
                validated_results.append(result)

        return validated_results

