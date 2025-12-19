"""Custom Presidio recognizer for Dutch BSN (Burgerservicenummer).

Implements the 11-proef (Elfproef) validation algorithm to prevent false positives.
"""

from typing import Optional

from presidio_analyzer import Pattern, PatternRecognizer


class BsnRecognizer(PatternRecognizer):
    """Recognizes Dutch BSN numbers with 11-proef validation."""

    def __init__(self) -> None:
        """Initialize BSN recognizer with patterns and validation."""
        patterns = [
            Pattern(
                name="bsn_pattern",
                regex=r"\b\d{9}\b",  # 9 digits
                score=0.5,  # Initial score, will be boosted by validation
            ),
            Pattern(
                name="bsn_pattern_with_spaces",
                regex=r"\b\d{3}\s?\d{2}\s?\d{4}\b",  # Format: 123 45 6789
                score=0.5,
            ),
            Pattern(
                name="bsn_pattern_with_dots",
                regex=r"\b\d{3}\.\d{2}\.\d{4}\b",  # Format: 123.45.6789
                score=0.5,
            ),
        ]

        super().__init__(
            supported_entity="NL_BSN",
            patterns=patterns,
            context=[
                "BSN",
                "burgerservicenummer",
                "sofinummer",
                "sofi",
                "citizen service number",
                "citizenservicenumber",
                "service number",
            ],
            supported_language="en",  # Use English as base language
        )

    def validate_result(self, pattern_text: str) -> Optional[bool]:
        """Validate BSN using 11-proef algorithm.
        
        Args:
            pattern_text: The matched BSN string
            
        Returns:
            True if valid BSN, False otherwise
        """
        # Clean the input (remove spaces, dots)
        bsn = pattern_text.replace(" ", "").replace(".", "").strip()

        # Must be exactly 9 digits
        if not bsn.isdigit() or len(bsn) != 9:
            return False

        # Convert to list of integers
        digits = [int(d) for d in bsn]

        # 11-proef algorithm
        # Multiply each digit by its weight (9, 8, 7, 6, 5, 4, 3, 2, -1)
        # Sum must be divisible by 11
        weights = [9, 8, 7, 6, 5, 4, 3, 2, -1]
        checksum = sum(digit * weight for digit, weight in zip(digits, weights))

        return checksum % 11 == 0

    def analyze(self, text: str, entities: list[str], nlp_artifacts=None):  # type: ignore
        """Override analyze to add validation."""
        results = super().analyze(text, entities, nlp_artifacts)

        # Filter results to only include valid BSNs
        validated_results = []
        for result in results:
            pattern_text = text[result.start : result.end]
            if self.validate_result(pattern_text):
                # Boost score for validated BSN
                result.score = 0.95
                validated_results.append(result)

        return validated_results

