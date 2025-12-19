"""Unit tests for BSN recognizer with 11-proef validation."""

import pytest

from dutch_tax_agent.ingestion.recognizers import BsnRecognizer


def test_bsn_recognizer_valid():
    """Test BSN recognizer with valid BSNs."""
    recognizer = BsnRecognizer()

    # Valid BSN: 111222333 (passes 11-proef)
    # Checksum: 9*1 + 8*1 + 7*1 + 6*2 + 5*2 + 4*2 + 3*3 + 2*3 + (-1)*3 = 77 (divisible by 11)
    test_text = "BSN: 111222333"

    results = recognizer.analyze(test_text, ["NL_BSN"])

    assert len(results) > 0
    assert results[0].entity_type == "NL_BSN"
    assert results[0].score >= 0.9


def test_bsn_recognizer_invalid():
    """Test BSN recognizer with invalid BSN (fails 11-proef)."""
    recognizer = BsnRecognizer()

    # Invalid BSN: 123456789 (fails 11-proef)
    test_text = "BSN: 123456789"

    results = recognizer.analyze(test_text, ["NL_BSN"])

    # Should not recognize invalid BSN
    assert len(results) == 0


def test_bsn_recognizer_with_formatting():
    """Test BSN recognizer with formatted BSN."""
    recognizer = BsnRecognizer()

    # Valid BSN with spaces
    test_text = "Sofinummer: 111 22 2333"

    results = recognizer.analyze(test_text, ["NL_BSN"])

    assert len(results) > 0


def test_bsn_validation_algorithm():
    """Test 11-proef validation algorithm directly."""
    recognizer = BsnRecognizer()

    # Known valid BSN
    assert recognizer.validate_result("111222333") is True

    # Known invalid BSN
    assert recognizer.validate_result("123456789") is False

    # Invalid format
    assert recognizer.validate_result("12345678") is False
    assert recognizer.validate_result("1234567890") is False


