"""Custom Presidio recognizer for Dutch dates of birth."""

from presidio_analyzer import Pattern, PatternRecognizer


class DutchDOBRecognizer(PatternRecognizer):
    """Recognizes dates of birth in Dutch format (DD-MM-YYYY)."""

    def __init__(self) -> None:
        """Initialize DOB recognizer."""
        patterns = [
            Pattern(
                name="dob_pattern_dashes",
                regex=r"\b\d{2}-\d{2}-\d{4}\b",  # DD-MM-YYYY
                score=0.6,
            ),
            Pattern(
                name="dob_pattern_slashes",
                regex=r"\b\d{2}/\d{2}/\d{4}\b",  # DD/MM/YYYY
                score=0.6,
            ),
            Pattern(
                name="dob_pattern_dots",
                regex=r"\b\d{2}\.\d{2}\.\d{4}\b",  # DD.MM.YYYY
                score=0.6,
            ),
        ]

        # Context words that indicate this is a date of birth
        context = [
            "geboren",
            "geboortedatum",
            "date of birth",
            "DOB",
            "birth date",
            "geboorte",
        ]

        super().__init__(
            supported_entity="NL_DATE_OF_BIRTH",
            patterns=patterns,
            context=context,
            supported_language="en",  # Use English as base language
        )

    def analyze(self, text: str, entities: list[str], nlp_artifacts=None):  # type: ignore
        """Override analyze to boost score when context is present."""
        results = super().analyze(text, entities, nlp_artifacts)

        # Check if any context words are near the detected date
        for result in results:
            # Look for context within 50 chars before the match
            context_start = max(0, result.start - 50)
            context_text = text[context_start : result.start].lower()

            for ctx_word in self.context:
                if ctx_word.lower() in context_text:
                    # Boost score significantly if context is present
                    result.score = 0.95
                    break

        return results

