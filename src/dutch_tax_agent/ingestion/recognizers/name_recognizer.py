"""Custom Presidio recognizer for personal names from configuration file.

Handles variations including:
- Full name (with/without spaces, concatenated)
- First + Last name combinations
- Individual name parts (first, last, middle)
- All combinations of middle names (if middle is an array)
- Reversed/inverted names (e.g., "JOHNDOE" -> "EODNHOJ")
- Case-insensitive matching
"""

import itertools
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

    def _normalize_middle(self, middle) -> Optional[list[str]]:
        """Normalize middle name(s) to a list of strings.
        
        Handles backward compatibility:
        - If middle is a string, split by spaces and return as list
        - If middle is a list, return as-is (normalized to uppercase)
        - If middle is None/null, return None
        
        Args:
            middle: Middle name(s) as string, list, or None
            
        Returns:
            List of middle name strings (uppercase) or None
        """
        if middle is None:
            return None
        
        if isinstance(middle, str):
            # Backward compatibility: split string by spaces
            parts = [part.strip().upper() for part in middle.split() if part.strip()]
            return parts if parts else None
        
        if isinstance(middle, list):
            # Normalize list to uppercase strings
            parts = [str(part).strip().upper() for part in middle if part and str(part).strip()]
            return parts if parts else None
        
        return None

    def _get_middle_combinations(self, middle_list: list[str]) -> list[str]:
        """Generate all combinations of middle names.
        
        For ["NAME1", "NAME2"], returns:
        - "NAME1 NAME2" (all)
        - "NAME1" (first only)
        - "NAME2" (second only)
        
        Args:
            middle_list: List of middle name strings
            
        Returns:
            List of all possible middle name combinations as strings
        """
        if not middle_list:
            return []
        
        combinations = []
        # Generate all non-empty subsets (combinations of length 1 to len(middle_list))
        for r in range(1, len(middle_list) + 1):
            for combo in itertools.combinations(middle_list, r):
                # Join with space to create the middle name string
                combinations.append(" ".join(combo))
        
        return combinations

    def _build_patterns(self, name_configs: list[dict]) -> list[Pattern]:
        """Build regex patterns for all name variations.
        
        Args:
            name_configs: List of name dicts with keys: first, last, middle, full_name
            - middle can be a string (backward compatible) or array of strings
            
        Returns:
            List of Pattern objects for name matching
        """
        patterns = []
        
        for name_config in name_configs:
            first = name_config.get("first", "").strip().upper()
            last = name_config.get("last", "").strip().upper()
            middle_raw = name_config.get("middle")
            middle_list = self._normalize_middle(middle_raw)
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
            
            # Pattern 7: First + Middle + Last (all combinations if middle exists)
            if middle_list:
                # Generate patterns for all combinations of middle names
                middle_combinations = self._get_middle_combinations(middle_list)
                for middle_combo in middle_combinations:
                    # Pattern 7a: First + Middle + Last (with spaces)
                    first_middle_last_pattern = (
                        r"(?i)\b" + self._escape_regex(first) + r"\s+" 
                        + self._escape_regex(middle_combo) + r"\s+" 
                        + self._escape_regex(last) + r"\b"
                    )
                    patterns.append(
                        Pattern(
                            name=f"first_middle_last_{first}_{middle_combo.replace(' ', '_')}_{last}",
                            regex=first_middle_last_pattern,
                            score=0.95,
                        )
                    )
                    
                    # Pattern 7b: First + Middle + Last (concatenated)
                    first_middle_last_concatenated = first + middle_combo.replace(" ", "") + last
                    first_middle_last_concatenated_pattern = (
                        r"(?i)\b" + self._escape_regex(first_middle_last_concatenated) + r"\b"
                    )
                    patterns.append(
                        Pattern(
                            name=f"first_middle_last_concatenated_{first}_{middle_combo.replace(' ', '_')}_{last}",
                            regex=first_middle_last_concatenated_pattern,
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
            middle_raw = name_config.get("middle")
            middle_list = self._normalize_middle(middle_raw)
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
            
            # Check first + middle + last (all combinations)
            if middle_list:
                middle_combinations = self._get_middle_combinations(middle_list)
                for middle_combo in middle_combinations:
                    if text_upper == f"{first} {middle_combo} {last}" or text_upper == f"{first}{middle_combo.replace(' ', '')}{last}":
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

