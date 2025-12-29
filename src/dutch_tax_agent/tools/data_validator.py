"""Data validation tools for ensuring type safety and data quality."""

import logging
from typing import Any

from dutch_tax_agent.schemas.tax_entities import Box1Income, Box3Asset
from dutch_tax_agent.tools.currency import parse_currency_string

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Raised when validation fails."""

    pass


class DataValidator:
    """Validates extracted data for type safety and business rules."""

    @staticmethod
    def validate_amount(
        value: Any, field_name: str, allow_negative: bool = False
    ) -> float:
        """Validate that a value is a valid numeric amount.
        
        Args:
            value: Value to validate (can be number or string with currency symbols)
            field_name: Name of field (for error messages)
            allow_negative: Whether negative values are allowed
            
        Returns:
            Validated float value
            
        Raises:
            ValidationError: If validation fails
        """
        try:
            # If it's a string, try to parse it as a currency string first
            if isinstance(value, str):
                amount = parse_currency_string(value)
            else:
                amount = float(value)
        except (TypeError, ValueError) as e:
            raise ValidationError(
                f"Invalid amount for {field_name}: '{value}' is not a number"
            ) from e

        if not allow_negative and amount < 0:
            raise ValidationError(
                f"Invalid amount for {field_name}: {amount} is negative"
            )

        return amount

    @staticmethod
    def validate_currency_code(code: Any) -> str:
        """Validate currency code format.
        
        Args:
            code: Currency code to validate
            
        Returns:
            Validated uppercase currency code
            
        Raises:
            ValidationError: If code is invalid
        """
        if not isinstance(code, str):
            raise ValidationError(f"Currency code must be a string, got {type(code)}")

        code_upper = code.upper()

        if len(code_upper) != 3:
            raise ValidationError(
                f"Currency code must be 3 characters, got '{code_upper}'"
            )

        if not code_upper.isalpha():
            raise ValidationError(
                f"Currency code must contain only letters, got '{code_upper}'"
            )

        return code_upper

    @staticmethod
    def validate_confidence(confidence: Any) -> float:
        """Validate confidence score is between 0 and 1.
        
        Args:
            confidence: Confidence value to validate
            
        Returns:
            Validated confidence score
            
        Raises:
            ValidationError: If confidence is invalid
        """
        try:
            conf = float(confidence)
        except (TypeError, ValueError) as e:
            raise ValidationError(
                f"Confidence must be a number, got '{confidence}'"
            ) from e

        if not 0.0 <= conf <= 1.0:
            raise ValidationError(
                f"Confidence must be between 0 and 1, got {conf}"
            )

        return conf

    @staticmethod
    def validate_box1_income(data: dict, source_doc_id: str, source_filename: str) -> Box1Income:
        """Validate and construct a Box1Income object.
        
        Args:
            data: Dictionary of extracted data
            source_doc_id: Document ID for audit trail
            source_filename: Filename for audit trail
            
        Returns:
            Validated Box1Income object
            
        Raises:
            ValidationError: If validation fails
        """
        try:
            # Validate required fields
            gross_amount = DataValidator.validate_amount(
                data.get("gross_amount_eur", 0),
                "gross_amount_eur",
            )

            # Optional fields with defaults
            tax_withheld = DataValidator.validate_amount(
                data.get("tax_withheld_eur", 0),
                "tax_withheld_eur",
            )
            
            # Parse original_amount if present (may come as string from LLM)
            original_amount = None
            if "original_amount" in data and data["original_amount"] is not None:
                original_amount = DataValidator.validate_amount(
                    data["original_amount"],
                    "original_amount",
                    allow_negative=True,  # Allow negative for refunds/adjustments
                )

            return Box1Income(
                source_doc_id=source_doc_id,
                source_filename=source_filename,
                source_page=data.get("source_page"),
                income_type=data.get("income_type", "salary"),
                gross_amount_eur=gross_amount,
                tax_withheld_eur=tax_withheld,
                period_start=data["period_start"],
                period_end=data["period_end"],
                original_amount=original_amount,
                original_currency=data.get("original_currency", "EUR"),
                extraction_confidence=DataValidator.validate_confidence(
                    data.get("extraction_confidence", 1.0)
                ),
                original_text_snippet=data.get("original_text_snippet"),
            )

        except KeyError as e:
            raise ValidationError(f"Missing required field: {e}") from e
        except Exception as e:
            raise ValidationError(f"Failed to validate Box1Income: {e}") from e

    @staticmethod
    def validate_box3_asset(
        data: dict, 
        source_doc_id: str, 
        source_filename: str,
        tax_year: int = 2024
    ) -> Box3Asset:
        """Validate and construct a Box3Asset object.
        
        Args:
            data: Dictionary of extracted data
            source_doc_id: Document ID for audit trail
            source_filename: Filename for audit trail
            tax_year: Tax year for reference date defaults
            
        Returns:
            Validated Box3Asset object
            
        Raises:
            ValidationError: If validation fails
        """
        try:
            # Check if this is a liability (mortgage or debt) - these can have negative values
            asset_type = data.get("asset_type", "other")
            is_liability = asset_type in ["mortgage", "debt"]
            
            # Validate Jan 1 value (can be None if document only has Dec 31)
            value_eur_jan1 = None
            if data.get("value_eur_jan1") is not None:
                value_eur_jan1 = DataValidator.validate_amount(
                    data["value_eur_jan1"],
                    "value_eur_jan1",
                    allow_negative=is_liability,
                )
            
            # Validate Dec 31 value (can be None if document only has Jan 1)
            value_eur_dec31 = None
            if data.get("value_eur_dec31") is not None:
                value_eur_dec31 = DataValidator.validate_amount(
                    data["value_eur_dec31"],
                    "value_eur_dec31",
                    allow_negative=is_liability,
                )
            
            # At least one value must be present
            if value_eur_jan1 is None and value_eur_dec31 is None:
                raise ValidationError(
                    "Box3Asset must have at least one of value_eur_jan1 or value_eur_dec31"
                )

            # Optional gain/loss fields
            realized_gains = None
            if "realized_gains_eur" in data and data["realized_gains_eur"] is not None:
                realized_gains = DataValidator.validate_amount(
                    data["realized_gains_eur"],
                    "realized_gains_eur",
                    allow_negative=True,
                )

            realized_losses = None
            if "realized_losses_eur" in data and data["realized_losses_eur"] is not None:
                realized_losses = DataValidator.validate_amount(
                    data["realized_losses_eur"],
                    "realized_losses_eur",
                    allow_negative=True,
                )
            
            # Parse original_value if present (may come as string from LLM)
            original_value = None
            if "original_value" in data and data["original_value"] is not None:
                original_value = DataValidator.validate_amount(
                    data["original_value"],
                    "original_value",
                    allow_negative=True,  # Allow negative for losses
                )
            
            # Handle reference_date - default to Jan 1 of tax year if not provided
            reference_date = data.get("reference_date")
            if reference_date is None:
                from datetime import date
                reference_date = date(tax_year, 1, 1)
            elif isinstance(reference_date, str):
                from datetime import datetime
                reference_date = datetime.fromisoformat(reference_date).date()

            # Calculate Actual Return: (End Value - Start Value) - (Deposits - Withdrawals)
            deposits = data.get("deposits_eur")
            withdrawals = data.get("withdrawals_eur")
            actual_return = None
            if value_eur_dec31 is not None:
                jan1_val = value_eur_jan1 or 0.0
                deposits_val = deposits or 0.0
                withdrawals_val = withdrawals or 0.0
                actual_return = (value_eur_dec31 - jan1_val) - (deposits_val - withdrawals_val)
            
            return Box3Asset(
                source_doc_id=source_doc_id,
                source_filename=source_filename,
                source_page=data.get("source_page"),
                asset_type=data.get("asset_type", "savings"),
                value_eur_jan1=value_eur_jan1 or 0.0,  # Box3Asset requires non-null, use 0.0 if None
                value_eur_dec31=value_eur_dec31,
                deposits_eur=deposits,
                withdrawals_eur=withdrawals,
                actual_return_eur=actual_return,
                realized_gains_eur=realized_gains,
                realized_losses_eur=realized_losses,
                original_value=original_value,
                original_currency=data.get("original_currency", "EUR"),
                conversion_rate=data.get("conversion_rate"),
                reference_date=reference_date,
                description=data.get("description"),
                account_number=data.get("account_number"),
                extraction_confidence=DataValidator.validate_confidence(
                    data.get("extraction_confidence", 1.0)
                ),
                original_text_snippet=data.get("original_text_snippet"),
            )

        except KeyError as e:
            raise ValidationError(f"Missing required field: {e}") from e
        except Exception as e:
            raise ValidationError(f"Failed to validate Box3Asset: {e}") from e

