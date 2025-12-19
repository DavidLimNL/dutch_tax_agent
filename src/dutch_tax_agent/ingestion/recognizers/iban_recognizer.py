"""Custom Presidio recognizer for Dutch IBAN numbers."""

from typing import Optional

from presidio_analyzer import Pattern, PatternRecognizer


class DutchIBANRecognizer(PatternRecognizer):
    """Recognizes Dutch IBAN numbers (format: NL91ABNA0417164300)."""

    def __init__(self) -> None:
        """Initialize IBAN recognizer."""
        patterns = [
            Pattern(
                name="iban_pattern",
                regex=r"\bNL\d{2}[A-Z]{4}\d{10}\b",  # Standard format
                score=0.9,
            ),
            Pattern(
                name="iban_pattern_with_spaces",
                regex=r"\bNL\d{2}\s?[A-Z]{4}\s?\d{4}\s?\d{4}\s?\d{2}\b",  # With spaces
                score=0.9,
            ),
        ]

        super().__init__(
            supported_entity="NL_IBAN",
            patterns=patterns,
            context=["IBAN", "rekening", "account", "bankrekening", "bank account"],
            supported_language="en",  # Use English as base language
        )

    def validate_result(self, pattern_text: str) -> Optional[bool]:
        """Basic IBAN validation (format check).
        
        Args:
            pattern_text: The matched IBAN string
            
        Returns:
            True if valid format
        """
        # Clean the input
        iban = pattern_text.replace(" ", "").strip()

        # Must start with NL and be 18 characters
        if not iban.startswith("NL") or len(iban) != 18:
            return False

        # Check digit portion
        check_digits = iban[2:4]
        if not check_digits.isdigit():
            return False

        # Bank code (4 letters)
        bank_code = iban[4:8]
        if not bank_code.isalpha():
            return False

        # Account number (10 digits)
        account_number = iban[8:]
        if not account_number.isdigit() or len(account_number) != 10:
            return False

        return True

    def analyze(self, text: str, entities: list[str], nlp_artifacts=None):  # type: ignore
        """Override analyze to add validation."""
        results = super().analyze(text, entities, nlp_artifacts)

        # Filter results to only include valid IBANs
        validated_results = []
        for result in results:
            pattern_text = text[result.start : result.end]
            if self.validate_result(pattern_text):
                validated_results.append(result)

        return validated_results

