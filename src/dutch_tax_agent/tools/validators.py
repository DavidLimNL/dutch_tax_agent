"""Data validation tools for ensuring type safety and data quality."""

import logging
from typing import Any

from dutch_tax_agent.schemas.tax_entities import Box1Income, Box3Asset

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
            value: Value to validate
            field_name: Name of field (for error messages)
            allow_negative: Whether negative values are allowed
            
        Returns:
            Validated float value
            
        Raises:
            ValidationError: If validation fails
        """
        try:
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

            return Box1Income(
                source_doc_id=source_doc_id,
                source_filename=source_filename,
                source_page=data.get("source_page"),
                income_type=data.get("income_type", "salary"),
                gross_amount_eur=gross_amount,
                tax_withheld_eur=tax_withheld,
                period_start=data["period_start"],
                period_end=data["period_end"],
                original_amount=data.get("original_amount"),
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
    def validate_box3_asset(data: dict, source_doc_id: str, source_filename: str) -> Box3Asset:
        """Validate and construct a Box3Asset object.
        
        Args:
            data: Dictionary of extracted data
            source_doc_id: Document ID for audit trail
            source_filename: Filename for audit trail
            
        Returns:
            Validated Box3Asset object
            
        Raises:
            ValidationError: If validation fails
        """
        try:
            # Validate required fields
            value_eur = DataValidator.validate_amount(
                data.get("value_eur_jan1", 0),
                "value_eur_jan1",
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

            return Box3Asset(
                source_doc_id=source_doc_id,
                source_filename=source_filename,
                source_page=data.get("source_page"),
                asset_type=data.get("asset_type", "savings"),
                value_eur_jan1=value_eur,
                realized_gains_eur=realized_gains,
                realized_losses_eur=realized_losses,
                original_value=data.get("original_value"),
                original_currency=data.get("original_currency", "EUR"),
                conversion_rate=data.get("conversion_rate"),
                reference_date=data["reference_date"],
                description=data.get("description"),
                extraction_confidence=DataValidator.validate_confidence(
                    data.get("extraction_confidence", 1.0)
                ),
                original_text_snippet=data.get("original_text_snippet"),
            )

        except KeyError as e:
            raise ValidationError(f"Missing required field: {e}") from e
        except Exception as e:
            raise ValidationError(f"Failed to validate Box3Asset: {e}") from e


