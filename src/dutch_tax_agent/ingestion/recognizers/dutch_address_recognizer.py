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
            # Dutch postal code immediately followed by number (e.g., "2597SM72")
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
        postal_code_match = re.search(r"(\d{4}\s?[A-Z]{2})(?:\d+)?", text)
        if postal_code_match:
            postal_code = postal_code_match.group(1).replace(" ", "")
            # Validate postal code format
            if len(postal_code) == 6 and postal_code[:4].isdigit() and postal_code[4:].isalpha():
                return True
        
        # Check for street + number pattern
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

