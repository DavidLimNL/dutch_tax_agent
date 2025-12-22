"""Custom Presidio recognizer for personal names from configuration file.

Handles variations including:
- Full name (with/without spaces, concatenated)
- First + Last name combinations
- Individual name parts (first, last, middle)
- Reversed/inverted names (e.g., "JOHNDOE" -> "EODNHOJ")
- Case-insensitive matching
"""

import json
import logging
from pathlib import Path
from typing import Optional

from presidio_analyzer import Pattern, PatternRecognizer

from dutch_tax_agent.config import settings

logger = logging.getLogger(__name__)


class NameRecognizer(PatternRecognizer):
    """Recognizes personal names from pii_names.json configuration file."""

    def __init__(self) -> None:
        """Initialize name recognizer by loading names from config file."""
        names_file = settings.data_dir / "pii_names.json"
        
        if not names_file.exists():
            logger.warning(
                f"PII names file not found at {names_file}. "
                "Name recognition will be disabled."
            )
            patterns = []
            self.name_parts = []
        else:
            try:
                with open(names_file, "r", encoding="utf-8") as f:
                    config = json.load(f)
                
                self.name_parts = config.get("names", [])
                patterns = self._build_patterns(self.name_parts)
                
                logger.info(
                    f"Loaded {len(self.name_parts)} name(s) from {names_file}"
                )
            except Exception as e:
                logger.error(f"Failed to load PII names from {names_file}: {e}")
                patterns = []
                self.name_parts = []

        super().__init__(
            supported_entity="PERSON_NAME",
            patterns=patterns,
            supported_language="en",
        )

    def _build_patterns(self, name_configs: list[dict]) -> list[Pattern]:
        """Build regex patterns for all name variations.
        
        Args:
            name_configs: List of name dicts with keys: first, last, middle, full_name
            
        Returns:
            List of Pattern objects for name matching
        """
        patterns = []
        
        for name_config in name_configs:
            first = name_config.get("first", "").strip().upper()
            last = name_config.get("last", "").strip().upper()
            middle = name_config.get("middle", "").strip().upper() if name_config.get("middle") else None
            full_name = name_config.get("full_name", "").strip().upper()
            
            if not first or not last:
                logger.warning(f"Skipping incomplete name config: {name_config}")
                continue
            
            # Pattern 1: Full name with space (case-insensitive)
            # Matches: "JOHN DOE", "John Doe", "john doe"
            if full_name:
                full_pattern = r"(?i)\b" + self._escape_regex(full_name) + r"\b"
                patterns.append(
                    Pattern(
                        name=f"full_name_{first}_{last}",
                        regex=full_pattern,
                        score=0.95,  # High confidence for full name
                    )
                )
            
            # Pattern 2: Full name concatenated (no space)
            # Matches: "JOHNDOE", "JohnDoe"
            if full_name:
                full_no_space = full_name.replace(" ", "")
                full_no_space_pattern = r"(?i)\b" + self._escape_regex(full_no_space) + r"\b"
                patterns.append(
                    Pattern(
                        name=f"full_name_concatenated_{first}_{last}",
                        regex=full_no_space_pattern,
                        score=0.95,
                    )
                )
            
            # Pattern 3: First + Last together (with space, case-insensitive)
            # Matches: "JOHN DOE", "John Doe"
            first_last_pattern = (
                r"(?i)\b" + self._escape_regex(first) + r"\s+" + self._escape_regex(last) + r"\b"
            )
            patterns.append(
                Pattern(
                    name=f"first_last_{first}_{last}",
                    regex=first_last_pattern,
                    score=0.90,  # High confidence for first+last together
                )
            )
            
            # Pattern 4: First + Last concatenated
            # Matches: "JOHNDOE"
            first_last_concatenated = first + last
            first_last_concatenated_pattern = r"(?i)\b" + self._escape_regex(first_last_concatenated) + r"\b"
            patterns.append(
                Pattern(
                    name=f"first_last_concatenated_{first}_{last}",
                    regex=first_last_concatenated_pattern,
                    score=0.90,
                )
            )
            
            # Pattern 5: First name only (increased threshold to reduce false positives)
            # Matches: "JOHN", "John"
            first_pattern = r"(?i)\b" + self._escape_regex(first) + r"\b"
            patterns.append(
                Pattern(
                    name=f"first_name_{first}",
                    regex=first_pattern,
                    score=0.80,  # Increased from 0.60 to reduce false positives
                )
            )
            
            # Pattern 6: Last name only (increased threshold to reduce false positives)
            # Matches: "DOE", "Doe"
            last_pattern = r"(?i)\b" + self._escape_regex(last) + r"\b"
            patterns.append(
                Pattern(
                    name=f"last_name_{last}",
                    regex=last_pattern,
                    score=0.80,  # Increased from 0.60 to reduce false positives
                )
            )
            
            # Pattern 7: First + Middle + Last (if middle exists)
            if middle:
                first_middle_last_pattern = (
                    r"(?i)\b" + self._escape_regex(first) + r"\s+" 
                    + self._escape_regex(middle) + r"\s+" 
                    + self._escape_regex(last) + r"\b"
                )
                patterns.append(
                    Pattern(
                        name=f"first_middle_last_{first}_{middle}_{last}",
                        regex=first_middle_last_pattern,
                        score=0.95,
                    )
                )
            
            # Pattern 8: Reversed concatenated full name
            # Matches: "EODNHOJ" (reversed "JOHNDOE")
            first_last_concatenated = first + last
            reversed_concatenated = first_last_concatenated[::-1]
            reversed_pattern = r"(?i)\b" + self._escape_regex(reversed_concatenated) + r"\b"
            patterns.append(
                Pattern(
                    name=f"reversed_concatenated_{first}_{last}",
                    regex=reversed_pattern,
                    score=0.90,  # High confidence for reversed concatenated name
                )
            )
            
            # Pattern 9: Reversed full name with spaces (if full_name exists)
            # Matches: "EOD NHOJ" (reversed "JOHN DOE")
            if full_name:
                reversed_full = full_name[::-1]  # Reverse character by character
                reversed_full_pattern = r"(?i)\b" + self._escape_regex(reversed_full) + r"\b"
                patterns.append(
                    Pattern(
                        name=f"reversed_full_name_{first}_{last}",
                        regex=reversed_full_pattern,
                        score=0.90,
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
        """Validate that the matched text is actually a name.
        
        This helps reduce false positives by checking if the match
        corresponds to a known name part.
        
        Args:
            pattern_text: The matched text
            
        Returns:
            True if valid name match, False otherwise
        """
        text_upper = pattern_text.strip().upper()
        
        # Check against all name parts
        for name_config in self.name_parts:
            first = name_config.get("first", "").strip().upper()
            last = name_config.get("last", "").strip().upper()
            middle = name_config.get("middle", "").strip().upper() if name_config.get("middle") else None
            full_name = name_config.get("full_name", "").strip().upper()
            
            # Check exact matches
            if text_upper == first or text_upper == last:
                return True
            
            # Check full name variations
            if full_name:
                if text_upper == full_name or text_upper == full_name.replace(" ", ""):
                    return True
            
            # Check first + last combination
            if text_upper == f"{first} {last}" or text_upper == f"{first}{last}":
                return True
            
            # Check first + middle + last
            if middle:
                if text_upper == f"{first} {middle} {last}" or text_upper == f"{first}{middle}{last}":
                    return True
            
            # Check reversed variations
            first_last_concatenated = first + last
            reversed_concatenated = first_last_concatenated[::-1]
            if text_upper == reversed_concatenated:
                return True
            
            if full_name:
                reversed_full = full_name[::-1]
                if text_upper == reversed_full:
                    return True
        
        return None  # Let Presidio decide based on pattern score

